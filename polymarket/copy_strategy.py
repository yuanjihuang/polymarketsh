"""
Copy Trading Strategy Engine

Implements intelligent copy trading logic with:
- Signal filtering
- Position sizing
- Risk management
- Execution timing
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings, TradingConstants
from models import (
    TrackedTrader, Position, CopiedTrade, TradeDirection, 
    TradeStatus, init_db, get_async_session
)
from trader_tracker import TradeSignal, TraderProfile
from api_client import PolymarketAPIClient


class SignalAction(Enum):
    """Action to take on a signal"""
    COPY = "COPY"
    SKIP = "SKIP"
    REDUCE = "REDUCE"  # Copy with reduced size


@dataclass
class SignalDecision:
    """Decision on whether to copy a trade signal"""
    action: SignalAction
    original_signal: TradeSignal
    copy_size: float = 0.0
    copy_amount: float = 0.0
    reason: str = ""
    confidence: float = 0.0


@dataclass
class RiskMetrics:
    """Current risk metrics for the portfolio"""
    total_exposure: float = 0.0
    position_count: int = 0
    daily_trades: int = 0
    daily_volume: float = 0.0
    daily_pnl: float = 0.0
    max_drawdown: float = 0.0
    
    def is_within_limits(self, settings) -> bool:
        """Check if current metrics are within risk limits"""
        return (
            self.total_exposure < settings.max_position_size and
            self.daily_trades < 50  # Daily trade limit
        )


class SignalFilter:
    """
    Filters trade signals based on various criteria
    """
    
    def __init__(self):
        self.settings = get_settings()
        self._recent_signals: Dict[str, List[TradeSignal]] = defaultdict(list)
    
    def is_duplicate(self, signal: TradeSignal) -> bool:
        """Check if this is a duplicate signal we've already seen"""
        market_signals = self._recent_signals[signal.market_id]
        
        for recent in market_signals:
            # Check for same trader, same direction within 5 minutes
            if (recent.trader_address == signal.trader_address and
                recent.direction == signal.direction and
                (signal.timestamp - recent.timestamp) < timedelta(minutes=5)):
                return True
        
        return False
    
    def meets_trader_criteria(self, signal: TradeSignal) -> bool:
        """Check if the trader meets our criteria"""
        profile = signal.trader_profile
        
        if not profile:
            return True  # No profile means we trust the trader
        
        # Check minimum trades
        if profile.total_trades < self.settings.min_trader_trades:
            return False
        
        # Check win rate
        if profile.win_rate < self.settings.min_trader_profit_rate:
            return False
        
        return True
    
    def meets_trade_criteria(self, signal: TradeSignal) -> bool:
        """Check if the trade itself meets our criteria"""
        # Minimum trade size
        if signal.amount_usd < self.settings.min_trade_amount:
            return False
        
        # Price sanity check
        if not (TradingConstants.MIN_PRICE <= signal.price <= TradingConstants.MAX_PRICE):
            return False
        
        return True
    
    def filter(self, signal: TradeSignal) -> tuple[bool, str]:
        """
        Filter a signal
        
        Returns:
            Tuple of (should_copy, reason)
        """
        # Check for duplicate
        if self.is_duplicate(signal):
            return False, "Duplicate signal"
        
        # Check trader criteria
        if not self.meets_trader_criteria(signal):
            return False, "Trader doesn't meet criteria"
        
        # Check trade criteria
        if not self.meets_trade_criteria(signal):
            return False, "Trade doesn't meet criteria"
        
        # Record this signal
        self._recent_signals[signal.market_id].append(signal)
        
        # Cleanup old signals
        self._cleanup_old_signals()
        
        return True, "Signal passed all filters"
    
    def _cleanup_old_signals(self):
        """Remove signals older than 1 hour"""
        cutoff = datetime.utcnow() - timedelta(hours=1)
        
        for market_id in list(self._recent_signals.keys()):
            self._recent_signals[market_id] = [
                s for s in self._recent_signals[market_id]
                if s.timestamp > cutoff
            ]


class PositionSizer:
    """
    Calculates appropriate position sizes for copy trades
    """
    
    def __init__(self):
        self.settings = get_settings()
    
    def calculate_size(
        self, 
        signal: TradeSignal,
        current_exposure: float,
        existing_position: Optional[float] = None
    ) -> tuple[float, float]:
        """
        Calculate the size to copy
        
        Args:
            signal: The trade signal
            current_exposure: Current total exposure
            existing_position: Existing position in this market
            
        Returns:
            Tuple of (size_to_copy, amount_usd)
        """
        # Base copy amount
        base_amount = signal.amount_usd * self.settings.copy_ratio
        
        # Apply confidence scaling
        confidence_multiplier = signal.confidence if signal.confidence > 0 else 0.5
        scaled_amount = base_amount * confidence_multiplier
        
        # Apply limits
        final_amount = min(
            scaled_amount,
            self.settings.max_trade_amount,
            self.settings.max_position_size - current_exposure
        )
        
        # Ensure minimum
        if final_amount < self.settings.min_trade_amount:
            return 0.0, 0.0
        
        # Calculate size based on price
        size = final_amount / signal.price if signal.price > 0 else 0
        
        return size, final_amount
    
    def should_scale_down(
        self, 
        current_exposure: float,
        pending_amount: float
    ) -> float:
        """
        Calculate scale-down factor if approaching limits
        
        Returns:
            Multiplier (0-1) to apply to position size
        """
        remaining_capacity = self.settings.max_position_size - current_exposure
        
        if remaining_capacity <= 0:
            return 0.0
        
        if remaining_capacity < pending_amount:
            return remaining_capacity / pending_amount
        
        return 1.0


class RiskManager:
    """
    Manages risk across the portfolio
    """
    
    def __init__(self):
        self.settings = get_settings()
        self._daily_stats: Dict[str, Any] = {
            "trades": 0,
            "volume": 0.0,
            "pnl": 0.0,
            "date": datetime.utcnow().date()
        }
    
    def _reset_if_new_day(self):
        """Reset daily stats if it's a new day"""
        today = datetime.utcnow().date()
        if self._daily_stats["date"] != today:
            self._daily_stats = {
                "trades": 0,
                "volume": 0.0,
                "pnl": 0.0,
                "date": today
            }
    
    async def get_current_metrics(self, db_engine) -> RiskMetrics:
        """Get current risk metrics"""
        self._reset_if_new_day()
        
        metrics = RiskMetrics(
            daily_trades=self._daily_stats["trades"],
            daily_volume=self._daily_stats["volume"],
            daily_pnl=self._daily_stats["pnl"]
        )
        
        # Get positions from database
        async with await get_async_session(db_engine) as session:
            result = await session.execute(select(Position))
            positions = result.scalars().all()
            
            metrics.position_count = len(positions)
            metrics.total_exposure = sum(p.total_cost for p in positions)
        
        return metrics
    
    def record_trade(self, amount: float, pnl: float = 0.0):
        """Record a trade for daily tracking"""
        self._reset_if_new_day()
        self._daily_stats["trades"] += 1
        self._daily_stats["volume"] += amount
        self._daily_stats["pnl"] += pnl
    
    def can_trade(self, metrics: RiskMetrics) -> tuple[bool, str]:
        """
        Check if we can make another trade
        
        Returns:
            Tuple of (can_trade, reason)
        """
        if metrics.total_exposure >= self.settings.max_position_size:
            return False, "Maximum position size reached"
        
        if metrics.daily_trades >= 50:
            return False, "Daily trade limit reached"
        
        # Additional checks could be added here
        # - Drawdown limits
        # - Consecutive loss limits
        # - Time-based restrictions
        
        return True, "OK"


class CopyTradingStrategy:
    """
    Main copy trading strategy engine
    
    Combines signal filtering, position sizing, and risk management
    to make intelligent copy trading decisions
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.signal_filter = SignalFilter()
        self.position_sizer = PositionSizer()
        self.risk_manager = RiskManager()
        self.api_client = PolymarketAPIClient()
        self._db_engine = None
        
        # Callbacks for trade execution
        self._execute_callbacks: List[Callable[[SignalDecision], Any]] = []
    
    async def initialize(self):
        """Initialize strategy components"""
        self._db_engine = await init_db()
        logger.info("Copy trading strategy initialized")
    
    def add_execute_callback(self, callback: Callable[[SignalDecision], Any]):
        """Register callback for trade execution"""
        self._execute_callbacks.append(callback)
    
    async def evaluate_signal(self, signal: TradeSignal) -> SignalDecision:
        """
        Evaluate a trade signal and decide whether to copy
        
        Args:
            signal: Trade signal from tracked trader
            
        Returns:
            SignalDecision with action to take
        """
        # Step 1: Filter the signal
        should_copy, filter_reason = self.signal_filter.filter(signal)
        
        if not should_copy:
            return SignalDecision(
                action=SignalAction.SKIP,
                original_signal=signal,
                reason=filter_reason
            )
        
        # Step 2: Check risk limits
        metrics = await self.risk_manager.get_current_metrics(self._db_engine)
        can_trade, risk_reason = self.risk_manager.can_trade(metrics)
        
        if not can_trade:
            return SignalDecision(
                action=SignalAction.SKIP,
                original_signal=signal,
                reason=risk_reason
            )
        
        # Step 3: Get existing position in this market
        existing_position = await self._get_existing_position(signal.token_id)
        
        # Step 4: Calculate position size
        size, amount = self.position_sizer.calculate_size(
            signal, 
            metrics.total_exposure,
            existing_position
        )
        
        if size <= 0:
            return SignalDecision(
                action=SignalAction.SKIP,
                original_signal=signal,
                reason="Calculated size too small"
            )
        
        # Step 5: Check for scale-down
        scale_factor = self.position_sizer.should_scale_down(
            metrics.total_exposure, amount
        )
        
        if scale_factor < 1.0:
            size *= scale_factor
            amount *= scale_factor
            
            if amount < self.settings.min_trade_amount:
                return SignalDecision(
                    action=SignalAction.SKIP,
                    original_signal=signal,
                    reason="Scaled size below minimum"
                )
            
            action = SignalAction.REDUCE
        else:
            action = SignalAction.COPY
        
        return SignalDecision(
            action=action,
            original_signal=signal,
            copy_size=size,
            copy_amount=amount,
            reason=f"Copy with {scale_factor:.0%} of intended size",
            confidence=signal.confidence
        )
    
    async def _get_existing_position(self, token_id: str) -> Optional[float]:
        """Get existing position size for a token"""
        async with get_async_session() as session:
            result = await session.execute(
                select(Position).where(Position.token_id == token_id)
            )
            position = result.scalar_one_or_none()
            
            return position.size if position else None
    
    async def process_signal(self, signal: TradeSignal):
        """
        Process a trade signal - evaluate and execute if appropriate
        
        This is the main entry point called by the trader tracker
        """
        logger.info(
            f"Processing signal: {signal.trader_address[:10]}... "
            f"{signal.direction.value} {signal.size:.2f}@{signal.price:.4f}"
        )
        
        # Evaluate the signal
        decision = await self.evaluate_signal(signal)
        
        if decision.action == SignalAction.SKIP:
            logger.info(f"Skipping signal: {decision.reason}")
            return
        
        logger.info(
            f"Decision: {decision.action.value} - "
            f"Size: {decision.copy_size:.2f}, Amount: ${decision.copy_amount:.2f}"
        )
        
        # Apply delay before copying
        if self.settings.copy_delay_seconds > 0:
            logger.info(f"Waiting {self.settings.copy_delay_seconds}s before copying...")
            await asyncio.sleep(self.settings.copy_delay_seconds)
        
        # Execute callbacks (actual trade execution)
        for callback in self._execute_callbacks:
            if asyncio.iscoroutinefunction(callback):
                await callback(decision)
            else:
                callback(decision)
    
    async def get_portfolio_summary(self) -> Dict:
        """Get current portfolio summary"""
        metrics = await self.risk_manager.get_current_metrics(self._db_engine)
        
        async with get_async_session() as session:
            # Get positions
            positions_result = await session.execute(select(Position))
            positions = positions_result.scalars().all()
            
            # Get recent copied trades
            trades_result = await session.execute(
                select(CopiedTrade)
                .where(CopiedTrade.status == TradeStatus.EXECUTED)
                .order_by(CopiedTrade.executed_at.desc())
                .limit(10)
            )
            recent_trades = trades_result.scalars().all()
        
        return {
            "metrics": {
                "total_exposure": metrics.total_exposure,
                "position_count": metrics.position_count,
                "daily_trades": metrics.daily_trades,
                "daily_volume": metrics.daily_volume,
                "daily_pnl": metrics.daily_pnl
            },
            "positions": [
                {
                    "market": p.market_slug,
                    "size": p.size,
                    "avg_price": p.average_price,
                    "unrealized_pnl": p.unrealized_pnl
                }
                for p in positions
            ],
            "recent_trades": [
                {
                    "market": t.market_id,
                    "direction": t.direction.value,
                    "size": t.executed_size,
                    "price": t.executed_price,
                    "status": t.status.value
                }
                for t in recent_trades
            ]
        }
    
    async def close(self):
        """Cleanup resources"""
        await self.api_client.close()


class ConservativeStrategy(CopyTradingStrategy):
    """
    Conservative copy trading strategy
    - Higher trader quality requirements
    - Smaller position sizes
    - More strict risk limits
    """
    
    def __init__(self):
        super().__init__()
        # Override settings for conservative approach
        self.settings.min_trader_profit_rate = 0.6  # 60% win rate required
        self.settings.min_trader_trades = 20  # More trades required
        self.settings.copy_ratio = 0.05  # Only copy 5% of trade size
        self.settings.max_trade_amount = 50  # Max $50 per trade


class AggressiveStrategy(CopyTradingStrategy):
    """
    Aggressive copy trading strategy
    - Lower trader quality requirements
    - Larger position sizes
    - Less strict risk limits
    """
    
    def __init__(self):
        super().__init__()
        # Override settings for aggressive approach
        self.settings.min_trader_profit_rate = 0.5  # 50% win rate
        self.settings.min_trader_trades = 5  # Fewer trades required
        self.settings.copy_ratio = 0.2  # Copy 20% of trade size
        self.settings.max_trade_amount = 200  # Max $200 per trade
