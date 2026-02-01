"""
Polymarket Copy Trading System - Main Entry Point

Usage:
    python main.py run          # Start the copy trading bot
    python main.py add-trader   # Add a trader to track
    python main.py list         # List tracked traders
    python main.py status       # Show system status
    python main.py demo         # Run demo mode
"""

import asyncio
import sys
from datetime import datetime
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.layout import Layout
from loguru import logger

from config import get_settings
from models import init_db, TrackedTrader
from api_client import PolymarketAPIClient
from trader_tracker import TraderTracker, TradeSignal, analyze_trader
from copy_strategy import CopyTradingStrategy, SignalDecision
from trade_executor import TradeExecutor, DryRunExecutor

# Configure logging
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    level="INFO"
)

console = Console()
settings = get_settings()


class CopyTradingBot:
    """
    Main copy trading bot that orchestrates all components
    """
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.tracker = TraderTracker()
        self.strategy = CopyTradingStrategy()
        self.executor = DryRunExecutor() if dry_run else TradeExecutor()
        self._running = False
    
    async def initialize(self):
        """Initialize all components"""
        console.print("[bold blue]Initializing Copy Trading Bot...[/bold blue]")
        
        await self.tracker.initialize()
        await self.strategy.initialize()
        await self.executor.initialize()
        
        # Connect components
        self.tracker.add_signal_callback(self._on_trade_signal)
        self.strategy.add_execute_callback(self._on_execute_decision)
        
        console.print("[bold green]✓ Initialization complete[/bold green]")
    
    async def _on_trade_signal(self, signal: TradeSignal):
        """Callback when a trade signal is detected"""
        logger.info(f"Trade signal received from {signal.trader_address[:10]}...")
        await self.strategy.process_signal(signal)
    
    async def _on_execute_decision(self, decision: SignalDecision):
        """Callback when strategy decides to execute"""
        result = await self.executor.execute_decision(decision)
        
        if result.success:
            console.print(
                f"[green]✓ Trade executed:[/green] "
                f"{decision.original_signal.direction.value} "
                f"{result.executed_size:.4f} @ ${result.executed_price:.4f}"
            )
        else:
            console.print(
                f"[red]✗ Trade failed:[/red] {result.error_message}"
            )
    
    async def run(self):
        """Start the bot"""
        await self.initialize()
        
        self._running = True
        mode = "DRY RUN" if self.dry_run else "LIVE"
        
        console.print(Panel(
            f"[bold]Copy Trading Bot Started[/bold]\n"
            f"Mode: [yellow]{mode}[/yellow]\n"
            f"Tracking: {len(self.tracker.get_tracked_traders())} traders\n"
            f"Press Ctrl+C to stop",
            title="Status"
        ))
        
        try:
            await self.tracker.start_monitoring(use_onchain=False)
        except KeyboardInterrupt:
            console.print("\n[yellow]Shutting down...[/yellow]")
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the bot"""
        self._running = False
        await self.tracker.stop_monitoring()
        await self.executor.close()
        console.print("[green]Bot stopped successfully[/green]")


# CLI Commands
@click.group()
def cli():
    """Polymarket Copy Trading System"""
    pass


@cli.command()
@click.option('--dry-run', is_flag=True, help='Run in simulation mode')
def run(dry_run: bool):
    """Start the copy trading bot"""
    bot = CopyTradingBot(dry_run=dry_run)
    asyncio.run(bot.run())


@cli.command()
@click.argument('address')
@click.option('--alias', '-a', help='Alias for the trader')
@click.option('--ratio', '-r', type=float, help='Copy ratio for this trader')
def add_trader(address: str, alias: Optional[str], ratio: Optional[float]):
    """Add a trader to track"""
    async def _add():
        tracker = TraderTracker()
        await tracker.initialize()
        
        # Analyze trader first
        console.print(f"[blue]Analyzing trader {address[:10]}...[/blue]")
        profile = await analyze_trader(address)
        
        # Display profile
        table = Table(title="Trader Analysis")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Address", address)
        table.add_row("Total Trades", str(profile.total_trades))
        table.add_row("Win Rate", f"{profile.win_rate:.1%}")
        table.add_row("Total Volume", f"${profile.total_volume:,.2f}")
        table.add_row("Active Positions", str(profile.active_positions))
        
        console.print(table)
        
        # Add trader
        success = await tracker.add_trader(address, alias, ratio)
        
        if success:
            console.print(f"[green]✓ Trader added successfully[/green]")
        else:
            console.print(f"[red]✗ Failed to add trader[/red]")
    
    asyncio.run(_add())


@cli.command()
@click.argument('address')
def remove_trader(address: str):
    """Remove a trader from tracking"""
    async def _remove():
        tracker = TraderTracker()
        await tracker.initialize()
        
        success = await tracker.remove_trader(address)
        
        if success:
            console.print(f"[green]✓ Trader removed[/green]")
        else:
            console.print(f"[red]✗ Trader not found[/red]")
    
    asyncio.run(_remove())


@cli.command('list')
def list_traders():
    """List all tracked traders"""
    async def _list():
        tracker = TraderTracker()
        await tracker.initialize()
        
        traders = tracker.get_tracked_traders()
        
        if not traders:
            console.print("[yellow]No traders being tracked[/yellow]")
            return
        
        table = Table(title="Tracked Traders")
        table.add_column("Address", style="cyan")
        table.add_column("Trades", justify="right")
        table.add_column("Win Rate", justify="right")
        table.add_column("PnL", justify="right")
        table.add_column("Status", justify="center")
        
        for t in traders:
            status = "[green]Active[/green]" if t.is_active else "[red]Inactive[/red]"
            pnl_color = "green" if t.total_pnl >= 0 else "red"
            
            table.add_row(
                f"{t.address[:10]}...{t.address[-6:]}",
                str(t.total_trades),
                f"{t.win_rate:.1%}",
                f"[{pnl_color}]${t.total_pnl:,.2f}[/{pnl_color}]",
                status
            )
        
        console.print(table)
    
    asyncio.run(_list())


@cli.command()
def status():
    """Show system status"""
    async def _status():
        strategy = CopyTradingStrategy()
        await strategy.initialize()
        
        summary = await strategy.get_portfolio_summary()
        metrics = summary["metrics"]
        positions = summary["positions"]
        
        # Metrics panel
        metrics_text = (
            f"Total Exposure: ${metrics['total_exposure']:,.2f}\n"
            f"Position Count: {metrics['position_count']}\n"
            f"Daily Trades: {metrics['daily_trades']}\n"
            f"Daily Volume: ${metrics['daily_volume']:,.2f}\n"
            f"Daily PnL: ${metrics['daily_pnl']:,.2f}"
        )
        console.print(Panel(metrics_text, title="Portfolio Metrics"))
        
        # Positions table
        if positions:
            table = Table(title="Current Positions")
            table.add_column("Market")
            table.add_column("Size", justify="right")
            table.add_column("Avg Price", justify="right")
            table.add_column("PnL", justify="right")
            
            for pos in positions:
                pnl = pos.get("unrealized_pnl", 0) or 0
                pnl_color = "green" if pnl >= 0 else "red"
                
                table.add_row(
                    pos.get("market", "")[:30],
                    f"{pos.get('size', 0):.2f}",
                    f"${pos.get('avg_price', 0):.4f}",
                    f"[{pnl_color}]${pnl:,.2f}[/{pnl_color}]"
                )
            
            console.print(table)
        else:
            console.print("[yellow]No open positions[/yellow]")
    
    asyncio.run(_status())


@cli.command()
@click.option('--market', '-m', help='Market ID or slug to search')
def markets(market: Optional[str]):
    """Browse or search markets"""
    async def _markets():
        api = PolymarketAPIClient()
        
        if market:
            results = await api.search_markets(market)
        else:
            results = await api.get_markets(limit=20)
        
        await api.close()
        
        if not results:
            console.print("[yellow]No markets found[/yellow]")
            return
        
        table = Table(title="Polymarket Markets")
        table.add_column("Question", max_width=50)
        table.add_column("Volume", justify="right")
        table.add_column("Liquidity", justify="right")
        table.add_column("Yes Price", justify="right")
        
        for m in results:
            yes_price = m.outcome_prices[0] if m.outcome_prices else 0
            
            table.add_row(
                m.question[:50],
                f"${m.volume:,.0f}",
                f"${m.liquidity:,.0f}",
                f"{yes_price:.1%}"
            )
        
        console.print(table)
    
    asyncio.run(_markets())


@cli.command()
def demo():
    """Run a demo showing system capabilities"""
    async def _demo():
        console.print(Panel(
            "[bold]Polymarket Copy Trading Demo[/bold]\n\n"
            "This demo shows the system's capabilities without making real trades.",
            title="Demo Mode"
        ))
        
        # Initialize components
        console.print("\n[blue]1. Initializing components...[/blue]")
        api = PolymarketAPIClient()
        
        # Fetch markets
        console.print("\n[blue]2. Fetching active markets...[/blue]")
        markets = []
        try:
            markets = await api.get_markets(limit=5)
            
            table = Table(title="Sample Markets")
            table.add_column("Market")
            table.add_column("Yes Price")
            table.add_column("Volume")
            
            for m in markets:
                yes_price = m.outcome_prices[0] if m.outcome_prices else 0
                table.add_row(
                    m.question[:40] + "...",
                    f"{yes_price:.1%}",
                    f"${m.volume:,.0f}"
                )
            
            console.print(table)
        except Exception as e:
            console.print(f"[yellow]Could not fetch markets (network issue): {e}[/yellow]")
            console.print("[yellow]Using simulated data for demo...[/yellow]")
        
        # Show sample signal
        console.print("\n[blue]3. Simulating trade signal...[/blue]")
        
        if markets:
            sample_market = markets[0]
            market_question = sample_market.question[:50]
            market_price = sample_market.outcome_prices[0] if sample_market.outcome_prices else 0.5
        else:
            market_question = "Will BTC reach $100k by end of 2026?"
            market_price = 0.65
        
        console.print(Panel(
            f"[bold]Sample Signal Detected[/bold]\n\n"
            f"Trader: 0x1234...5678\n"
            f"Market: {market_question}...\n"
            f"Action: BUY YES\n"
            f"Price: {market_price:.1%}\n"
            f"Size: 100 shares\n"
            f"Confidence: 75%",
            title="Trade Signal"
        ))
        
        # Show decision
        console.print("\n[blue]4. Strategy decision...[/blue]")
        console.print(Panel(
            f"[bold green]Decision: COPY[/bold green]\n\n"
            f"Copy Size: 10 shares (10% ratio)\n"
            f"Copy Amount: ${market_price * 10:.2f}\n"
            f"Risk Check: ✓ Within limits\n"
            f"Slippage Check: ✓ Acceptable",
            title="Strategy Decision"
        ))
        
        # Show simulated execution
        console.print("\n[blue]5. Simulated execution...[/blue]")
        import random
        slippage = random.uniform(-0.01, 0.02)
        exec_price = market_price * (1 + slippage)
        console.print(Panel(
            f"[bold green]Execution: SUCCESS[/bold green]\n\n"
            f"Intended Price: ${market_price:.4f}\n"
            f"Executed Price: ${exec_price:.4f}\n"
            f"Slippage: {slippage:.2%}\n"
            f"Order ID: SIM-123456789",
            title="Execution Result"
        ))
        
        try:
            await api.close()
        except:
            pass
        
        console.print("\n[green]Demo complete![/green]")
        console.print(
            "\nTo start real copy trading:\n"
            "1. Copy .env.example to .env and configure\n"
            "2. Add traders to track with: [cyan]python main.py add-trader <address>[/cyan]\n"
            "3. Start the bot with: [cyan]python main.py run --dry-run[/cyan] (simulation)\n"
            "4. Or: [cyan]python main.py run[/cyan] (live trading)"
        )
    
    asyncio.run(_demo())


@cli.command()
@click.argument('address')
def analyze(address: str):
    """Analyze a trader's performance"""
    async def _analyze():
        console.print(f"[blue]Analyzing trader {address}...[/blue]")
        
        profile = await analyze_trader(address)
        
        table = Table(title=f"Trader Analysis: {address[:10]}...{address[-6:]}")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Total Trades", str(profile.total_trades))
        table.add_row("Winning Trades", str(profile.winning_trades))
        table.add_row("Win Rate", f"{profile.win_rate:.1%}")
        table.add_row("Total Volume", f"${profile.total_volume:,.2f}")
        table.add_row("Total PnL", f"${profile.total_pnl:,.2f}")
        table.add_row("Active Positions", str(profile.active_positions))
        table.add_row("Last Trade", str(profile.last_trade_time or "N/A"))
        table.add_row("Is Profitable", "Yes" if profile.is_profitable else "No")
        table.add_row("Is Active", "Yes" if profile.is_active else "No")
        
        console.print(table)
        
        if profile.specialties:
            console.print(f"\n[cyan]Specialties:[/cyan] {', '.join(profile.specialties)}")
    
    asyncio.run(_analyze())


@cli.command()
@click.option('--dry-run', is_flag=True, help='Run in simulation mode')
@click.option('--balance', default=1000.0, help='Initial paper trading balance (USD)')
@click.option('--copy-ratio', default=0.1, help='Copy ratio (0.1 = 10%% of detected trade size)')
def onchain(dry_run: bool, balance: float, copy_ratio: float):
    """
    Start copy trading using ONLY on-chain data.
    
    This mode does NOT require Polymarket API access.
    Data sources: Polygon RPC + The Graph
    """
    async def _onchain():
        from onchain_tracker import OnChainTraderTracker
        
        mode_info = f"Mode: [yellow]{'DRY RUN (Paper Trading)' if dry_run else 'LIVE'}[/yellow]"
        if dry_run:
            mode_info += f"\n  • Initial Balance: ${balance:.2f}"
            mode_info += f"\n  • Copy Ratio: {copy_ratio:.0%}"
        
        console.print(Panel(
            "[bold]On-Chain Copy Trading Mode[/bold]\n\n"
            "This mode works WITHOUT Polymarket API!\n"
            "Data sources:\n"
            "  • Polygon blockchain (direct RPC)\n"
            "  • The Graph subgraphs\n\n"
            f"{mode_info}",
            title="On-Chain Mode"
        ))
        
        tracker = OnChainTraderTracker(
            dry_run=dry_run,
            paper_balance=balance,
            copy_ratio=copy_ratio
        )
        
        try:
            await tracker.initialize()
            
            # Register signal handler
            async def on_signal(signal):
                pass  # Already logged in tracker
            
            tracker.register_signal_callback(on_signal)
            
            # Show status
            console.print(f"\n[blue]Tracking {len(tracker.tracked_traders)} traders[/blue]")
            if dry_run and tracker.paper_wallet:
                console.print(f"[blue]Paper Wallet Balance: ${tracker.paper_wallet.usdc_balance:.2f}[/blue]")
            console.print("[green]Press Ctrl+C to stop[/green]\n")
            
            await tracker.run()
            
        except KeyboardInterrupt:
            console.print("\n[yellow]Shutting down...[/yellow]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
        finally:
            # Show paper trading summary on exit
            if dry_run and tracker.paper_wallet:
                console.print(tracker.paper_wallet.get_summary())
            await tracker.stop()
    
    asyncio.run(_onchain())


@cli.command()
def onchain_demo():
    """
    Demo the on-chain tracker (no Polymarket API needed).
    
    Shows how to discover and track traders using
    purely blockchain data.
    """
    async def _demo():
        from onchain_tracker import demo
        await demo()
    
    asyncio.run(_demo())


@cli.command()
def discover():
    """
    Discover top traders from on-chain data.
    
    Uses The Graph to find profitable traders without
    needing Polymarket API access.
    """
    async def _discover():
        from onchain_tracker import OnChainTraderTracker
        
        console.print("[blue]Discovering top traders from on-chain data...[/blue]")
        
        tracker = OnChainTraderTracker()
        
        try:
            await tracker.initialize()
            
            traders = await tracker.discover_top_traders(limit=20)
            
            if traders:
                table = Table(title="Top Traders (On-Chain Data)")
                table.add_column("Rank", style="cyan")
                table.add_column("Address")
                table.add_column("P&L", justify="right")
                table.add_column("Trades", justify="right")
                table.add_column("Volume", justify="right")
                
                for i, t in enumerate(traders, 1):
                    pnl_color = "green" if t.profit_loss >= 0 else "red"
                    table.add_row(
                        str(i),
                        f"{t.address[:8]}...{t.address[-4:]}",
                        f"[{pnl_color}]${t.profit_loss:,.2f}[/{pnl_color}]",
                        str(t.total_trades),
                        f"${t.total_volume:,.0f}"
                    )
                
                console.print(table)
                
                console.print(
                    "\nTo track a trader:\n"
                    "[cyan]python main.py add-trader <ADDRESS>[/cyan]"
                )
            else:
                console.print("[yellow]Could not fetch traders (The Graph may be unavailable)[/yellow]")
                console.print("[yellow]You can still add traders manually if you know their addresses[/yellow]")
        
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
        finally:
            await tracker.stop()
    
    asyncio.run(_discover())


@cli.command()
def test_rpc():
    """Test connection to Polygon RPC nodes."""
    async def _test():
        from onchain_client import OnChainClient, POLYGON_RPC_ENDPOINTS
        
        console.print("[blue]Testing Polygon RPC connections...[/blue]\n")
        
        for rpc in POLYGON_RPC_ENDPOINTS:
            client = OnChainClient(rpc_url=rpc)
            try:
                if await client.connect():
                    block = await client.w3.eth.block_number
                    console.print(f"[green]✓[/green] {rpc} - Block: {block}")
                else:
                    console.print(f"[red]✗[/red] {rpc} - Connection failed")
            except Exception as e:
                console.print(f"[red]✗[/red] {rpc} - {str(e)[:50]}")
            finally:
                await client.close()
        
        console.print("\n[blue]Use a working RPC in your .env file:[/blue]")
        console.print("POLYGON_RPC_URL=<working_rpc_url>")
    
    asyncio.run(_test())


if __name__ == "__main__":
    cli()
