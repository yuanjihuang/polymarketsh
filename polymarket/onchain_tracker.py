"""
On-Chain Trader Tracker

Tracks top traders purely through blockchain data,
without relying on Polymarket's API.

Data sources:
- Direct Polygon RPC queries
- Polygonscan API (for historical data)
- The Graph subgraphs (if available)
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Callable, Set
from dataclasses import dataclass, field
from collections import defaultdict

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from onchain_client import OnChainClient, OnChainTrade, TraderStats, PolygonscanClient
from models import TrackedTrader, TraderTrade, TradeDirection, init_db, get_async_session


@dataclass
class TradeSignal:
    """Represents a trade signal detected from on-chain activity"""
    trader_address: str
    trader_alias: Optional[str]
    token_id: str
    side: str  # BUY or SELL
    amount: float
    price: float
    tx_hash: str
    block_number: int
    timestamp: datetime
    confidence: float  # 0-1 based on trader stats
    market_id: Optional[str] = None
    market_question: Optional[str] = None


@dataclass
class SimulatedPosition:
    """A simulated position in the paper trading wallet"""
    token_id: str
    side: str  # The outcome we hold
    shares: float
    avg_price: float
    total_cost: float
    current_value: float = 0.0
    pnl: float = 0.0


class PaperTradingWallet:
    """
    Simulated wallet for dry-run copy trading
    
    Tracks:
    - Virtual USDC balance
    - Simulated positions
    - P&L calculation
    - Trade history
    """
    
    def __init__(self, initial_balance: float = 1000.0, copy_ratio: float = 0.1):
        self.initial_balance = initial_balance
        self.usdc_balance = initial_balance
        self.copy_ratio = copy_ratio  # Copy 10% of detected trade size
        self.positions: Dict[str, SimulatedPosition] = {}
        self.trade_history: List[Dict] = []
        self.total_trades = 0
        self.winning_trades = 0
        
    def execute_copy_trade(self, signal: 'TradeSignal') -> Dict:
        """
        Execute a simulated copy trade based on a signal
        
        Returns trade result dict
        """
        # Calculate copy size (ratio of detected trade)
        copy_amount = signal.amount * self.copy_ratio
        
        # Estimate price (use 0.5 if unknown, typical for binary markets)
        price = signal.price if signal.price > 0 else 0.50
        cost = copy_amount * price
        
        result = {
            "success": False,
            "signal": signal,
            "copy_amount": copy_amount,
            "price": price,
            "cost": cost,
            "reason": "",
        }
        
        if signal.side == "BUY":
            # Check if we have enough balance
            if cost > self.usdc_balance:
                # Reduce size to fit balance
                copy_amount = (self.usdc_balance * 0.95) / price  # Use 95% max
                cost = copy_amount * price
                
                if copy_amount < 1:
                    result["reason"] = f"Insufficient balance (${self.usdc_balance:.2f})"
                    return result
            
            # Execute buy
            self.usdc_balance -= cost
            
            # Update or create position
            if signal.token_id in self.positions:
                pos = self.positions[signal.token_id]
                new_shares = pos.shares + copy_amount
                pos.total_cost += cost
                pos.avg_price = pos.total_cost / new_shares
                pos.shares = new_shares
            else:
                self.positions[signal.token_id] = SimulatedPosition(
                    token_id=signal.token_id,
                    side="YES",  # Simplified
                    shares=copy_amount,
                    avg_price=price,
                    total_cost=cost,
                )
            
            result["success"] = True
            result["reason"] = "BUY executed"
            
        else:  # SELL
            if signal.token_id not in self.positions:
                result["reason"] = "No position to sell"
                return result
            
            pos = self.positions[signal.token_id]
            sell_shares = min(copy_amount, pos.shares)
            revenue = sell_shares * price
            
            # Calculate P&L for this trade
            cost_basis = sell_shares * pos.avg_price
            pnl = revenue - cost_basis
            
            self.usdc_balance += revenue
            pos.shares -= sell_shares
            pos.total_cost -= cost_basis
            
            if pos.shares <= 0:
                del self.positions[signal.token_id]
            
            result["success"] = True
            result["pnl"] = pnl
            result["reason"] = f"SELL executed, P&L: ${pnl:+.2f}"
            
            if pnl > 0:
                self.winning_trades += 1
        
        # Record trade
        self.total_trades += 1
        self.trade_history.append({
            "timestamp": signal.timestamp,
            "trader": signal.trader_alias or signal.trader_address[:10],
            "side": signal.side,
            "amount": copy_amount,
            "price": price,
            "cost": cost,
            "balance_after": self.usdc_balance,
            "tx_hash": signal.tx_hash,
        })
        
        return result
    
    def get_portfolio_value(self, default_price: float = 0.50) -> float:
        """Calculate total portfolio value"""
        positions_value = sum(
            p.shares * default_price for p in self.positions.values()
        )
        return self.usdc_balance + positions_value
    
    def get_total_pnl(self) -> float:
        """Calculate total P&L"""
        return self.get_portfolio_value() - self.initial_balance
    
    def get_summary(self) -> str:
        """Get portfolio summary string"""
        portfolio_value = self.get_portfolio_value()
        total_pnl = self.get_total_pnl()
        pnl_pct = (total_pnl / self.initial_balance) * 100 if self.initial_balance > 0 else 0
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        
        lines = [
            f"",
            f"╔══════════════════════════════════════════════════════════╗",
            f"║           📊 Paper Trading Portfolio Summary             ║",
            f"╠══════════════════════════════════════════════════════════╣",
            f"║  Initial Balance:    ${self.initial_balance:>10.2f}                  ║",
            f"║  Current USDC:       ${self.usdc_balance:>10.2f}                  ║",
            f"║  Positions Value:    ${portfolio_value - self.usdc_balance:>10.2f}                  ║",
            f"║  ────────────────────────────────────────────────────── ║",
            f"║  Portfolio Value:    ${portfolio_value:>10.2f}                  ║",
            f"║  Total P&L:          ${total_pnl:>+10.2f} ({pnl_pct:+.1f}%)            ║",
            f"║  ────────────────────────────────────────────────────── ║",
            f"║  Total Trades:       {self.total_trades:>10}                    ║",
            f"║  Win Rate:           {win_rate:>10.1f}%                   ║",
            f"╚══════════════════════════════════════════════════════════╝",
        ]
        
        if self.positions:
            lines.append(f"\n📈 Open Positions ({len(self.positions)}):")
            for token_id, pos in self.positions.items():
                lines.append(f"   • {pos.shares:.2f} shares @ ${pos.avg_price:.4f} (cost: ${pos.total_cost:.2f})")
        
        return "\n".join(lines)


class OnChainTraderTracker:
    """
    Tracks top traders using purely on-chain data
    
    Data sources:
    - Direct Polygon RPC queries
    - Polygonscan API
    - The Graph subgraphs (fallback)
    - No Polymarket API dependency!
    """
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        polygonscan_api_key: str = "",
        poll_interval: int = 15,
        min_trade_size: float = 50.0,
        dry_run: bool = False,
        paper_balance: float = 1000.0,
        copy_ratio: float = 0.1,
    ):
        self.client = OnChainClient(rpc_url=rpc_url)
        self.polygonscan = PolygonscanClient(api_key=polygonscan_api_key)
        self.poll_interval = poll_interval
        self.min_trade_size = min_trade_size
        
        # Paper trading mode
        self.dry_run = dry_run
        self.paper_wallet: Optional[PaperTradingWallet] = None
        if dry_run:
            self.paper_wallet = PaperTradingWallet(
                initial_balance=paper_balance,
                copy_ratio=copy_ratio
            )
        
        # Tracked traders
        self.tracked_traders: Dict[str, TraderStats] = {}
        self.trader_aliases: Dict[str, str] = {}
        
        # Signal callbacks
        self.signal_callbacks: List[Callable] = []
        
        # State tracking
        self.last_processed_block: int = 0
        self.running = False
        
        # Cache for recent trades to avoid duplicates
        self._seen_tx_hashes: Set[str] = set()
        self._max_seen_cache = 10000
    
    async def initialize(self):
        """Initialize the tracker"""
        logger.info("Initializing On-Chain Trader Tracker...")
        
        # Initialize database
        await init_db()
        
        # Connect to blockchain
        if not await self.client.connect():
            raise ConnectionError("Failed to connect to Polygon RPC")
        
        # Load tracked traders from database
        await self._load_tracked_traders()
        
        self.last_processed_block = await self.client.w3.eth.block_number
        logger.success("On-Chain Tracker initialized")
    
    async def _load_tracked_traders(self):
        """Load tracked traders from database"""
        async with get_async_session() as session:
            result = await session.execute(
                select(TrackedTrader).where(TrackedTrader.is_active == True)
            )
            traders = result.scalars().all()
            
            for t in traders:
                self.tracked_traders[t.address.lower()] = TraderStats(
                    address=t.address,
                    total_trades=t.total_trades,
                    profit_loss=t.total_pnl,
                )
                if t.alias:
                    self.trader_aliases[t.address.lower()] = t.alias
        
        logger.info(f"Loaded {len(self.tracked_traders)} tracked traders")
    
    def register_signal_callback(self, callback: Callable):
        """Register a callback for trade signals"""
        self.signal_callbacks.append(callback)
    
    async def _emit_signal(self, signal: TradeSignal):
        """Emit signal to all registered callbacks"""
        for callback in self.signal_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(signal)
                else:
                    callback(signal)
            except Exception as e:
                logger.error(f"Signal callback error: {e}")
    
    async def add_trader(
        self,
        address: str,
        alias: Optional[str] = None,
        fetch_stats: bool = True
    ) -> bool:
        """Add a trader to track"""
        address = address.lower()
        
        if address in self.tracked_traders:
            logger.warning(f"Trader {address} already being tracked")
            return False
        
        stats = TraderStats(address=address)
        
        # Try to fetch stats from multiple sources
        if fetch_stats:
            # First try Polygonscan (more reliable)
            try:
                trades = await self.polygonscan.get_polymarket_trades(address, limit=100)
                if trades:
                    stats.total_trades = len(trades)
                    logger.info(f"Found {len(trades)} trades for {address} via Polygonscan")
            except Exception as e:
                logger.warning(f"Polygonscan fetch failed: {e}")
            
            # Fallback to The Graph
            if stats.total_trades == 0:
                try:
                    fetched_stats = await self.client.get_trader_pnl(address)
                    if fetched_stats:
                        stats = fetched_stats
                        logger.info(f"Fetched stats from The Graph: {stats.total_trades} trades")
                except Exception as e:
                    logger.warning(f"Could not fetch stats from The Graph: {e}")
        
        # Save to database
        async with get_async_session() as session:
            trader = TrackedTrader(
                address=address,
                alias=alias,
                total_trades=stats.total_trades,
                total_pnl=stats.profit_loss,
                is_active=True,
            )
            session.add(trader)
            await session.commit()
        
        self.tracked_traders[address] = stats
        if alias:
            self.trader_aliases[address] = alias
        
        logger.success(f"Added trader: {alias or address}")
        return True
    
    async def remove_trader(self, address: str) -> bool:
        """Remove a trader from tracking"""
        address = address.lower()
        
        if address not in self.tracked_traders:
            return False
        
        async with get_async_session() as session:
            result = await session.execute(
                select(TrackedTrader).where(TrackedTrader.address == address)
            )
            trader = result.scalar_one_or_none()
            if trader:
                trader.is_active = False
                await session.commit()
        
        del self.tracked_traders[address]
        self.trader_aliases.pop(address, None)
        
        logger.info(f"Removed trader: {address}")
        return True
    
    async def discover_top_traders(self, limit: int = 20) -> List[TraderStats]:
        """Discover top traders from The Graph"""
        logger.info("Discovering top traders from on-chain data...")
        
        traders = await self.client.get_top_traders(limit=limit)
        
        if traders:
            logger.info(f"Found {len(traders)} top traders")
            for i, t in enumerate(traders[:5], 1):
                logger.info(f"  {i}. {t.address[:10]}... - P&L: ${t.profit_loss:,.2f}, Trades: {t.total_trades}")
        else:
            logger.warning("No traders found (The Graph may be unavailable)")
        
        return traders
    
    async def _process_new_blocks(self):
        """Process new blocks for tracked trader activity"""
        current_block = await self.client.w3.eth.block_number
        
        # On first run, start from current block (don't try to catch up)
        if self.last_processed_block == 0:
            self.last_processed_block = current_block - 2
            logger.info(f"Starting from block {self.last_processed_block}")
            return
        
        if current_block <= self.last_processed_block:
            return
        
        # If we're too far behind, skip to near current (avoid huge catch-up)
        if current_block - self.last_processed_block > 50:
            logger.warning(f"Too far behind ({current_block - self.last_processed_block} blocks), skipping to recent")
            self.last_processed_block = current_block - 5
            return
        
        # Process only 5 blocks at a time to avoid "Block range is too large" error
        start_block = self.last_processed_block + 1
        end_block = min(start_block + 4, current_block)  # Max 5 blocks
        
        logger.debug(f"Processing blocks {start_block} to {end_block}")
        
        # Query CTF TransferSingle events to find trader activity
        # This catches trades even when submitted by relayers
        ctf_address = self.client.contracts["CTF"]
        
        try:
            # Get TransferSingle events from CTF contract
            transfer_filter = {
                "fromBlock": start_block,
                "toBlock": end_block,
                "address": ctf_address,
                "topics": [
                    "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"  # TransferSingle
                ]
            }
            
            logs = await self.client.w3.eth.get_logs(transfer_filter)
            
            # Update processed block after successful query
            self.last_processed_block = end_block
            
            for log in logs:
                try:
                    # Decode TransferSingle: operator, from, to, id, value
                    if len(log.topics) >= 4:
                        from_addr = "0x" + log.topics[2].hex()[-40:].lower()
                        to_addr = "0x" + log.topics[3].hex()[-40:].lower()
                        
                        # Check if any tracked trader is involved (as sender or receiver)
                        trader_address = None
                        if from_addr in self.tracked_traders:
                            trader_address = from_addr
                        elif to_addr in self.tracked_traders:
                            trader_address = to_addr
                        
                        if trader_address:
                            tx_hash = log.transactionHash.hex()
                            
                            if tx_hash not in self._seen_tx_hashes:
                                self._seen_tx_hashes.add(tx_hash)
                                
                                # Maintain cache size
                                if len(self._seen_tx_hashes) > self._max_seen_cache:
                                    self._seen_tx_hashes = set(list(self._seen_tx_hashes)[-self._max_seen_cache//2:])
                                
                                # Get block info
                                block = await self.client.w3.eth.get_block(log.blockNumber)
                                
                                # Decode token_id and amount from data
                                if log.data and len(log.data) >= 64:
                                    from eth_abi import decode
                                    token_id, amount = decode(["uint256", "uint256"], log.data)
                                    
                                    # Determine buy or sell
                                    zero_addr = "0x" + "0" * 40
                                    if from_addr == zero_addr:
                                        side = "BUY"
                                    elif to_addr == zero_addr:
                                        side = "SELL"
                                    else:
                                        side = "BUY" if to_addr == trader_address else "SELL"
                                    
                                    await self._process_transfer_event(
                                        tx_hash, log, block, trader_address,
                                        token_id, amount, side, from_addr, to_addr
                                    )
                
                except Exception as e:
                    logger.warning(f"Error processing log: {e}")
        
        except Exception as e:
            logger.warning(f"Error getting logs: {e}")
            # Skip these blocks on error to avoid infinite retry loop
            self.last_processed_block = end_block
    
    async def _process_transfer_event(
        self, tx_hash: str, log, block, trader_address: str,
        token_id: int, amount: int, side: str, from_addr: str, to_addr: str
    ):
        """Process a CTF transfer event"""
        amount_decimal = amount / 1e6  # CTF tokens have 6 decimals
        
        if amount_decimal < self.min_trade_size:
            return
        
        token_id_str = str(token_id)
        
        # Ensure tx_hash has 0x prefix
        if not tx_hash.startswith("0x"):
            tx_hash = "0x" + tx_hash
        
        # Try to get market info and outcome
        outcome = "YES/NO"
        market_question = None
        
        try:
            market_info = await self.client.get_market_by_token_id(token_id_str)
            if market_info:
                outcome = market_info.get("outcome", "YES/NO")
                market_question = market_info.get("question")
        except Exception as e:
            logger.debug(f"Could not fetch market info: {e}")
        
        # Log with available details
        trader_alias = self.trader_aliases.get(trader_address, trader_address[:10] + "...")
        time_str = datetime.fromtimestamp(block.timestamp).strftime("%H:%M:%S")
        
        # Format action with outcome
        action_str = f"{side} {outcome}" if outcome and outcome != "YES/NO" else side
        
        logger.info(f"")
        logger.info(f"═══════════════════════════════════════════════════════════")
        logger.info(f"🔔 [{time_str}] Trade Detected")
        logger.info(f"   Trader: {trader_alias} ({trader_address})")
        logger.info(f"   Action: {action_str} | Amount: {amount_decimal:.2f} shares")
        if market_question:
            # Truncate long questions
            q = market_question[:60] + "..." if len(market_question) > 60 else market_question
            logger.info(f"   Market: {q}")
        logger.info(f"   Token ID: {token_id_str[:30]}...")
        logger.info(f"   ─────────────────────────────────────────────────────────")
        logger.info(f"   🔗 Verify TX: https://polygonscan.com/tx/{tx_hash}")
        logger.info(f"   🔗 Trader Profile: https://polymarket.com/profile/{trader_address}")
        logger.info(f"═══════════════════════════════════════════════════════════")
        
        # Calculate confidence based on trader stats
        stats = self.tracked_traders.get(trader_address)
        confidence = 0.5
        if stats and stats.profit_loss > 0:
            confidence = min(0.9, 0.5 + (stats.profit_loss / 10000) * 0.1)
        
        signal = TradeSignal(
            trader_address=trader_address,
            trader_alias=self.trader_aliases.get(trader_address),
            token_id=token_id_str,
            market_id=token_id_str[:20],
            side=side,
            amount=amount_decimal,
            price=0,  # Price requires additional decoding from exchange events
            tx_hash=tx_hash,
            block_number=block.number,
            timestamp=datetime.fromtimestamp(block.timestamp),
            confidence=confidence,
        )
        
        # Execute paper trade if in dry-run mode
        if self.dry_run and self.paper_wallet:
            result = self.paper_wallet.execute_copy_trade(signal)
            if result["success"]:
                logger.info(f"   💰 PAPER TRADE: {signal.side} {result['copy_amount']:.2f} @ ${result['price']:.4f}")
                logger.info(f"   💵 New Balance: ${self.paper_wallet.usdc_balance:.2f} | Total P&L: ${self.paper_wallet.get_total_pnl():+.2f}")
            else:
                logger.info(f"   ⚠️  PAPER TRADE SKIPPED: {result['reason']}")
        
        # Save to database
        await self._save_trade(signal)
        
        # Emit signal
        await self._emit_signal(signal)
    
    async def _save_trade(self, signal: TradeSignal):
        """Save trade to database"""
        async with get_async_session() as session:
            # Get trader ID from database
            from sqlalchemy import select
            result = await session.execute(
                select(TrackedTrader).where(
                    TrackedTrader.address == signal.trader_address.lower()
                )
            )
            trader = result.scalar_one_or_none()
            
            if not trader:
                logger.warning(f"Trader {signal.trader_address} not found in database")
                return
            
            trade = TraderTrade(
                trader_id=trader.id,
                token_id=signal.token_id,
                market_id=signal.market_id or signal.token_id[:20],
                direction=TradeDirection.BUY if signal.side == "BUY" else TradeDirection.SELL,
                size=signal.amount,
                amount_usd=signal.amount * signal.price if signal.price else signal.amount,
                price=signal.price or 0,
                transaction_hash=signal.tx_hash,
                block_number=signal.block_number,
                executed_at=signal.timestamp,
            )
            session.add(trade)
            await session.commit()
    
    async def run(self):
        """Start the tracker main loop"""
        self.running = True
        logger.info("Starting On-Chain Tracker...")
        
        while self.running:
            try:
                await self._process_new_blocks()
                await asyncio.sleep(self.poll_interval)
            except Exception as e:
                logger.error(f"Tracker error: {e}")
                await asyncio.sleep(self.poll_interval * 2)
    
    async def stop(self):
        """Stop the tracker"""
        self.running = False
        await self.client.close()
        logger.info("Tracker stopped")


async def demo():
    """Demo the on-chain tracker"""
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    
    console = Console()
    
    console.print(Panel(
        "[bold]On-Chain Polymarket Tracker Demo[/bold]\n\n"
        "This tracker works WITHOUT Polymarket API!\n"
        "Data sources:\n"
        "  • Polygon RPC (real-time monitoring)\n"
        "  • Polygonscan API (historical data)\n"
        "  • The Graph (if available)",
        title="Demo"
    ))
    
    tracker = OnChainTraderTracker()
    
    try:
        await tracker.initialize()
        
        # Test Polygonscan with a known trader
        console.print("\n[blue]1. Testing Polygonscan API...[/blue]")
        
        # Known active Polymarket trader (example)
        # You can replace this with any known trader address
        test_traders = [
            "0xBf5f611e7d25a7e4A73F28E89c4A2c13C5BeAC01",  # Example address
        ]
        
        for test_addr in test_traders:
            console.print(f"\n[cyan]Checking address: {test_addr[:10]}...[/cyan]")
            trades = await tracker.polygonscan.get_polymarket_trades(test_addr, limit=10)
            if trades:
                console.print(f"[green]✓ Found {len(trades)} recent trades[/green]")
                
                # Show sample trades
                table = Table(title=f"Recent Trades for {test_addr[:10]}...")
                table.add_column("TX Hash")
                table.add_column("Side")
                table.add_column("Token ID")
                table.add_column("Time")
                
                for t in trades[:5]:
                    tx_time = datetime.fromtimestamp(t["timestamp"]).strftime("%Y-%m-%d %H:%M")
                    table.add_row(
                        t["tx_hash"][:12] + "...",
                        t["side"],
                        str(t["token_id"])[:12] + "..." if t["token_id"] else "N/A",
                        tx_time
                    )
                console.print(table)
            else:
                console.print(f"[yellow]No trades found for this address[/yellow]")
        
        # Try to discover top traders via The Graph (may fail)
        console.print("\n[blue]2. Trying The Graph (may be unavailable)...[/blue]")
        top_traders = await tracker.discover_top_traders(limit=5)
        
        if top_traders:
            table = Table(title="Top Traders (The Graph)")
            table.add_column("Rank")
            table.add_column("Address")
            table.add_column("P&L")
            table.add_column("Trades")
            
            for i, t in enumerate(top_traders[:5], 1):
                table.add_row(
                    str(i),
                    f"{t.address[:8]}...{t.address[-4:]}",
                    f"${t.profit_loss:,.2f}",
                    str(t.total_trades),
                )
            console.print(table)
        else:
            console.print("[yellow]The Graph unavailable - using manual trader entry[/yellow]")
        
        # Show current state
        console.print(f"\n[blue]3. System Status[/blue]")
        console.print(f"   Current block: {tracker.last_processed_block}")
        console.print(f"   Tracked traders: {len(tracker.tracked_traders)}")
        
        console.print("\n[green]Demo complete![/green]")
        console.print(Panel(
            "To use this system:\n\n"
            "1. [cyan]Add a trader manually:[/cyan]\n"
            "   python main.py add-trader 0x... --alias 'My Trader'\n\n"
            "2. [cyan]Start on-chain monitoring:[/cyan]\n"
            "   python main.py onchain --dry-run\n\n"
            "3. [cyan]Test RPC connections:[/cyan]\n"
            "   python main.py test-rpc",
            title="Next Steps"
        ))
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()
    finally:
        await tracker.polygonscan.close()
        await tracker.stop()


if __name__ == "__main__":
    asyncio.run(demo())
