"""
Trader Tracker Module

Monitors and tracks top traders on Polymarket through:
1. On-chain transaction monitoring
2. API-based trade detection
3. Third-party analytics data
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Set, Callable, Any
from dataclasses import dataclass, field
from collections import defaultdict
import json

from web3 import Web3, AsyncWeb3
try:
    from web3.middleware import geth_poa_middleware
    HAS_POA_MIDDLEWARE = True
except ImportError:
    # web3 v7+ uses different middleware system
    HAS_POA_MIDDLEWARE = False
from eth_account import Account
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings, ContractAddresses
from models import TrackedTrader, TraderTrade, TradeDirection, init_db, get_async_session
from api_client import PolymarketAPIClient, Trade


@dataclass
class TraderProfile:
    """Profile data for a tracked trader"""
    address: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_volume: float = 0.0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    avg_trade_size: float = 0.0
    active_positions: int = 0
    specialties: List[str] = field(default_factory=list)
    last_trade_time: Optional[datetime] = None
    
    @property
    def is_profitable(self) -> bool:
        return self.total_pnl > 0
    
    @property
    def is_active(self) -> bool:
        if not self.last_trade_time:
            return False
        return (datetime.utcnow() - self.last_trade_time) < timedelta(days=7)


@dataclass
class TradeSignal:
    """Signal generated when a tracked trader makes a trade"""
    trader_address: str
    market_id: str
    market_slug: str
    token_id: str
    direction: TradeDirection
    price: float
    size: float
    amount_usd: float
    transaction_hash: str
    timestamp: datetime
    trader_profile: Optional[TraderProfile] = None
    confidence: float = 0.5  # 0-1 based on trader's track record
    
    def to_dict(self) -> Dict:
        return {
            "trader": self.trader_address,
            "market_id": self.market_id,
            "market_slug": self.market_slug,
            "token_id": self.token_id,
            "direction": self.direction.value,
            "price": self.price,
            "size": self.size,
            "amount_usd": self.amount_usd,
            "tx_hash": self.transaction_hash,
            "timestamp": self.timestamp.isoformat(),
            "confidence": self.confidence
        }


class OnChainTracker:
    """
    Monitors on-chain transactions on Polygon for Polymarket trades
    """
    
    # Event signatures for Polymarket contracts
    # OrderFilled event
    ORDER_FILLED_TOPIC = Web3.keccak(
        text="OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)"
    ).hex()
    
    def __init__(self):
        self.settings = get_settings()
        self.w3: Optional[AsyncWeb3] = None
        self._running = False
        self._callbacks: List[Callable[[TradeSignal], Any]] = []
        
    async def connect(self):
        """Connect to Polygon RPC"""
        self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(self.settings.polygon_rpc_url))
        # Add PoA middleware for Polygon (web3 v6 and below)
        if HAS_POA_MIDDLEWARE:
            self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        
        if await self.w3.is_connected():
            logger.info(f"Connected to Polygon at {self.settings.polygon_rpc_url}")
        else:
            raise ConnectionError("Failed to connect to Polygon RPC")
    
    def add_callback(self, callback: Callable[[TradeSignal], Any]):
        """Register callback for trade signals"""
        self._callbacks.append(callback)
    
    async def _process_log(self, log: Dict, tracked_addresses: Set[str]) -> Optional[TradeSignal]:
        """Process a transaction log and extract trade signal if relevant"""
        # Check if this is from Polymarket contracts
        contract_address = log.get("address", "").lower()
        if contract_address not in [
            ContractAddresses.EXCHANGE.lower(),
            ContractAddresses.NEG_RISK_EXCHANGE.lower()
        ]:
            return None
        
        # Decode the log (simplified - actual implementation would need full ABI)
        # This is a placeholder for the actual event decoding
        topics = log.get("topics", [])
        if not topics:
            return None
        
        # Check if any tracked address is involved
        # In actual implementation, parse the maker/taker from the log data
        tx_hash = log.get("transactionHash", "").hex() if isinstance(
            log.get("transactionHash"), bytes
        ) else log.get("transactionHash", "")
        
        # Get full transaction for more details
        if self.w3:
            try:
                tx = await self.w3.eth.get_transaction(tx_hash)
                from_addr = tx.get("from", "").lower()
                
                if from_addr in tracked_addresses:
                    # Create signal (simplified)
                    return TradeSignal(
                        trader_address=from_addr,
                        market_id="",  # Would need to decode from log
                        market_slug="",
                        token_id="",
                        direction=TradeDirection.BUY,
                        price=0.0,
                        size=0.0,
                        amount_usd=0.0,
                        transaction_hash=tx_hash,
                        timestamp=datetime.utcnow()
                    )
            except Exception as e:
                logger.error(f"Error processing transaction {tx_hash}: {e}")
        
        return None
    
    async def monitor_blocks(self, tracked_addresses: Set[str]):
        """Monitor new blocks for trades from tracked addresses"""
        if not self.w3:
            await self.connect()
        
        self._running = True
        last_block = await self.w3.eth.block_number
        
        logger.info(f"Starting block monitoring from block {last_block}")
        
        while self._running:
            try:
                current_block = await self.w3.eth.block_number
                
                if current_block > last_block:
                    # Process new blocks
                    for block_num in range(last_block + 1, current_block + 1):
                        logs = await self.w3.eth.get_logs({
                            "fromBlock": block_num,
                            "toBlock": block_num,
                            "address": [
                                ContractAddresses.EXCHANGE,
                                ContractAddresses.NEG_RISK_EXCHANGE
                            ]
                        })
                        
                        for log in logs:
                            signal = await self._process_log(log, tracked_addresses)
                            if signal:
                                for callback in self._callbacks:
                                    await callback(signal)
                    
                    last_block = current_block
                
                await asyncio.sleep(2)  # Poll every 2 seconds
                
            except Exception as e:
                logger.error(f"Error in block monitoring: {e}")
                await asyncio.sleep(5)
    
    def stop(self):
        """Stop monitoring"""
        self._running = False


class APITracker:
    """
    Tracks trader activities via Polymarket API
    More reliable but with slight delay compared to on-chain tracking
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.api_client = PolymarketAPIClient()
        self._running = False
        self._callbacks: List[Callable[[TradeSignal], Any]] = []
        self._seen_trades: Set[str] = set()  # Track seen transaction hashes
        self._last_check: Dict[str, datetime] = {}
    
    def add_callback(self, callback: Callable[[TradeSignal], Any]):
        """Register callback for trade signals"""
        self._callbacks.append(callback)
    
    async def get_trader_recent_trades(
        self, 
        address: str,
        since: Optional[datetime] = None
    ) -> List[Trade]:
        """Get recent trades for a specific trader"""
        trades = await self.api_client.get_trades(maker=address, limit=50)
        
        if since:
            trades = [t for t in trades if t.timestamp > since]
        
        return trades
    
    async def _check_trader_trades(
        self, 
        address: str,
        profile: Optional[TraderProfile] = None
    ) -> List[TradeSignal]:
        """Check for new trades from a trader"""
        signals = []
        
        # Get last check time for this trader
        since = self._last_check.get(address, datetime.utcnow() - timedelta(minutes=5))
        
        trades = await self.get_trader_recent_trades(address, since)
        
        for trade in trades:
            # Skip if already seen
            if trade.transaction_hash in self._seen_trades:
                continue
            
            self._seen_trades.add(trade.transaction_hash)
            
            # Calculate confidence based on trader profile
            confidence = 0.5
            if profile:
                confidence = min(0.95, profile.win_rate * 1.2) if profile.win_rate > 0.5 else 0.3
            
            signal = TradeSignal(
                trader_address=address,
                market_id=trade.market_id,
                market_slug="",  # Would need market lookup
                token_id="",  # Would need additional API call
                direction=TradeDirection.BUY if trade.side == "BUY" else TradeDirection.SELL,
                price=trade.price,
                size=trade.size,
                amount_usd=trade.price * trade.size,
                transaction_hash=trade.transaction_hash,
                timestamp=trade.timestamp,
                trader_profile=profile,
                confidence=confidence
            )
            signals.append(signal)
        
        self._last_check[address] = datetime.utcnow()
        return signals
    
    async def monitor_traders(
        self, 
        traders: Dict[str, TraderProfile]
    ):
        """
        Monitor multiple traders for new trades
        
        Args:
            traders: Dict mapping address to TraderProfile
        """
        self._running = True
        
        logger.info(f"Starting API monitoring for {len(traders)} traders")
        
        while self._running:
            try:
                for address, profile in traders.items():
                    signals = await self._check_trader_trades(address, profile)
                    
                    for signal in signals:
                        logger.info(
                            f"New trade signal: {signal.trader_address[:10]}... "
                            f"{signal.direction.value} {signal.size}@{signal.price}"
                        )
                        
                        for callback in self._callbacks:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(signal)
                            else:
                                callback(signal)
                    
                    # Small delay between traders to avoid rate limiting
                    await asyncio.sleep(0.5)
                
                # Wait before next round
                await asyncio.sleep(self.settings.poll_interval)
                
            except Exception as e:
                logger.error(f"Error in API monitoring: {e}")
                await asyncio.sleep(10)
    
    def stop(self):
        """Stop monitoring"""
        self._running = False
    
    async def close(self):
        """Close API client"""
        await self.api_client.close()


class TraderTracker:
    """
    Main trader tracking system that combines multiple data sources
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.api_tracker = APITracker()
        self.onchain_tracker = OnChainTracker()
        self._db_engine = None
        
        # Tracked traders cache
        self._traders: Dict[str, TraderProfile] = {}
        self._callbacks: List[Callable[[TradeSignal], Any]] = []
    
    async def initialize(self):
        """Initialize database and load tracked traders"""
        self._db_engine = await init_db()
        await self._load_tracked_traders()
    
    async def _load_tracked_traders(self):
        """Load tracked traders from database"""
        async with get_async_session() as session:
            result = await session.execute(
                select(TrackedTrader).where(TrackedTrader.is_active == True)
            )
            traders = result.scalars().all()
            
            for trader in traders:
                self._traders[trader.address.lower()] = TraderProfile(
                    address=trader.address,
                    total_trades=trader.total_trades,
                    winning_trades=trader.winning_trades,
                    total_pnl=trader.total_pnl,
                    win_rate=trader.win_rate,
                    specialties=json.loads(trader.specialties) if trader.specialties else [],
                    last_trade_time=trader.last_trade
                )
        
        logger.info(f"Loaded {len(self._traders)} tracked traders")
    
    async def add_trader(
        self, 
        address: str,
        alias: Optional[str] = None,
        copy_ratio: Optional[float] = None
    ) -> bool:
        """
        Add a new trader to track
        
        Args:
            address: Wallet address
            alias: Optional human-readable name
            copy_ratio: Override copy ratio for this trader
            
        Returns:
            Success status
        """
        address = address.lower()
        
        if address in self._traders:
            logger.warning(f"Trader {address} is already being tracked")
            return False
        
        async with get_async_session() as session:
            trader = TrackedTrader(
                address=address,
                alias=alias,
                copy_ratio=copy_ratio or self.settings.copy_ratio
            )
            session.add(trader)
            await session.commit()
            
            self._traders[address] = TraderProfile(address=address)
        
        logger.info(f"Added trader {address} ({alias or 'unnamed'}) to tracking")
        return True
    
    async def remove_trader(self, address: str) -> bool:
        """Remove a trader from tracking"""
        address = address.lower()
        
        if address not in self._traders:
            return False
        
        async with get_async_session() as session:
            await session.execute(
                update(TrackedTrader)
                .where(TrackedTrader.address == address)
                .values(is_active=False)
            )
            await session.commit()
        
        del self._traders[address]
        logger.info(f"Removed trader {address} from tracking")
        return True
    
    async def update_trader_stats(self, address: str, profile: TraderProfile):
        """Update trader statistics in database"""
        async with get_async_session() as session:
            await session.execute(
                update(TrackedTrader)
                .where(TrackedTrader.address == address.lower())
                .values(
                    total_trades=profile.total_trades,
                    winning_trades=profile.winning_trades,
                    total_pnl=profile.total_pnl,
                    win_rate=profile.win_rate,
                    last_trade=profile.last_trade_time,
                    specialties=json.dumps(profile.specialties) if profile.specialties else None
                )
            )
            await session.commit()
    
    def add_signal_callback(self, callback: Callable[[TradeSignal], Any]):
        """Register callback for trade signals"""
        self._callbacks.append(callback)
        self.api_tracker.add_callback(callback)
        self.onchain_tracker.add_callback(callback)
    
    async def _record_trade(self, signal: TradeSignal):
        """Record a detected trade in the database"""
        async with get_async_session() as session:
            # Get trader ID
            result = await session.execute(
                select(TrackedTrader).where(
                    TrackedTrader.address == signal.trader_address.lower()
                )
            )
            trader = result.scalar_one_or_none()
            
            if not trader:
                return
            
            trade = TraderTrade(
                trader_id=trader.id,
                market_id=signal.market_id,
                market_slug=signal.market_slug,
                token_id=signal.token_id,
                direction=signal.direction,
                price=signal.price,
                size=signal.size,
                amount_usd=signal.amount_usd,
                transaction_hash=signal.transaction_hash,
                executed_at=signal.timestamp
            )
            session.add(trade)
            await session.commit()
    
    async def start_monitoring(self, use_onchain: bool = False):
        """
        Start monitoring traders
        
        Args:
            use_onchain: Whether to use on-chain monitoring (more real-time but complex)
        """
        # Add internal callback to record trades
        self.add_signal_callback(self._record_trade)
        
        if use_onchain:
            # Start both API and on-chain monitoring
            await asyncio.gather(
                self.api_tracker.monitor_traders(self._traders),
                self.onchain_tracker.monitor_blocks(set(self._traders.keys()))
            )
        else:
            # Use API-based monitoring only
            await self.api_tracker.monitor_traders(self._traders)
    
    async def stop_monitoring(self):
        """Stop all monitoring"""
        self.api_tracker.stop()
        self.onchain_tracker.stop()
        await self.api_tracker.close()
    
    def get_tracked_traders(self) -> List[TraderProfile]:
        """Get list of currently tracked traders"""
        return list(self._traders.values())
    
    async def discover_top_traders(
        self, 
        min_trades: int = 10,
        min_win_rate: float = 0.55,
        limit: int = 20
    ) -> List[TraderProfile]:
        """
        Discover potential top traders to follow
        
        This is a placeholder - actual implementation would require:
        1. Scraping PolymarketAnalytics
        2. Analyzing on-chain data
        3. Using third-party APIs
        
        Returns:
            List of discovered trader profiles
        """
        # Placeholder implementation
        logger.warning("discover_top_traders: Using placeholder implementation")
        logger.info(
            f"To discover top traders, consider:\n"
            f"1. Visit https://polymarketanalytics.com for leaderboards\n"
            f"2. Analyze on-chain data directly\n"
            f"3. Monitor large trades manually"
        )
        return []


# Utility functions
async def analyze_trader(address: str) -> TraderProfile:
    """
    Analyze a trader's performance history
    
    Args:
        address: Trader wallet address
        
    Returns:
        TraderProfile with computed metrics
    """
    api_client = PolymarketAPIClient()
    
    try:
        # Get trader's positions
        positions = await api_client.get_trader_positions(address)
        
        # Get trader's recent trades
        trades = await api_client.get_trades(maker=address, limit=200)
        
        # Compute metrics
        total_trades = len(trades)
        total_volume = sum(t.price * t.size for t in trades)
        
        # Create profile
        profile = TraderProfile(
            address=address,
            total_trades=total_trades,
            total_volume=total_volume,
            active_positions=len(positions),
            last_trade_time=trades[0].timestamp if trades else None
        )
        
        # Note: Win rate and PnL calculation would require historical price data
        # This is a simplified version
        
        return profile
        
    finally:
        await api_client.close()
