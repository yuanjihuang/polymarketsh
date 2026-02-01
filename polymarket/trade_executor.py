"""
Trade Execution Module

Handles actual trade execution on Polymarket using py-clob-client
"""

import asyncio
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from enum import Enum

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY, SELL
    HAS_CLOB_CLIENT = True
except ImportError:
    HAS_CLOB_CLIENT = False
    logger.warning("py-clob-client not installed. Trading functionality will be limited.")

from config import get_settings, TradingConstants
from models import (
    CopiedTrade, Position, TradeDirection, TradeStatus,
    init_db, get_async_session
)
from copy_strategy import SignalDecision, SignalAction
from api_client import PolymarketAPIClient


class OrderResult(Enum):
    """Result of order execution"""
    SUCCESS = "SUCCESS"
    PARTIAL_FILL = "PARTIAL_FILL"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


@dataclass
class ExecutionResult:
    """Result of trade execution"""
    success: bool
    order_result: OrderResult
    order_id: Optional[str] = None
    transaction_hash: Optional[str] = None
    executed_price: Optional[float] = None
    executed_size: Optional[float] = None
    slippage: Optional[float] = None
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "result": self.order_result.value,
            "order_id": self.order_id,
            "tx_hash": self.transaction_hash,
            "price": self.executed_price,
            "size": self.executed_size,
            "slippage": self.slippage,
            "error": self.error_message
        }


class TradeExecutor:
    """
    Executes trades on Polymarket
    
    Uses py-clob-client for order placement and management
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.api_client = PolymarketAPIClient()
        self._clob_client: Optional[Any] = None
        self._db_engine = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize the executor with CLOB client"""
        if self._initialized:
            return
        
        self._db_engine = await init_db()
        
        if not HAS_CLOB_CLIENT:
            logger.error("py-clob-client is required for trading. Install with: pip install py-clob-client")
            return
        
        if not self.settings.private_key:
            logger.warning("No private key configured. Trading will be in simulation mode.")
            return
        
        try:
            self._clob_client = ClobClient(
                host=self.settings.polymarket_host,
                key=self.settings.private_key,
                chain_id=self.settings.chain_id,
                signature_type=0  # EOA wallet
            )
            
            # Set up API credentials
            creds = self._clob_client.create_or_derive_api_creds()
            self._clob_client.set_api_creds(creds)
            
            self._initialized = True
            logger.info("Trade executor initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize CLOB client: {e}")
    
    @property
    def is_ready(self) -> bool:
        """Check if executor is ready for trading"""
        return self._initialized and self._clob_client is not None
    
    async def execute_decision(self, decision: SignalDecision) -> ExecutionResult:
        """
        Execute a copy trading decision
        
        Args:
            decision: The signal decision to execute
            
        Returns:
            ExecutionResult with execution details
        """
        if decision.action == SignalAction.SKIP:
            return ExecutionResult(
                success=False,
                order_result=OrderResult.REJECTED,
                error_message=decision.reason
            )
        
        signal = decision.original_signal
        
        # Record the intended trade
        copied_trade = await self._create_copied_trade_record(decision)
        
        if not self.is_ready:
            # Simulation mode
            logger.warning("Executing in simulation mode (no CLOB client)")
            result = await self._simulate_execution(decision)
        else:
            # Real execution
            result = await self._execute_trade(decision)
        
        # Update the trade record
        await self._update_copied_trade_record(copied_trade, result)
        
        # Update position
        if result.success:
            await self._update_position(decision, result)
        
        return result
    
    async def _create_copied_trade_record(self, decision: SignalDecision) -> int:
        """Create a record for the copied trade"""
        signal = decision.original_signal
        
        async with get_async_session() as session:
            trade = CopiedTrade(
                source_trade_id=1,  # Would need actual source trade ID
                source_trader_id=1,  # Would need actual trader ID
                market_id=signal.market_id,
                token_id=signal.token_id,
                direction=signal.direction,
                intended_price=signal.price,
                intended_size=decision.copy_size,
                amount_usd=decision.copy_amount,
                status=TradeStatus.PENDING
            )
            session.add(trade)
            await session.commit()
            return trade.id
    
    async def _update_copied_trade_record(
        self, 
        trade_id: int, 
        result: ExecutionResult
    ):
        """Update the copied trade record with execution result"""
        async with get_async_session() as session:
            status = TradeStatus.EXECUTED if result.success else TradeStatus.FAILED
            
            await session.execute(
                update(CopiedTrade)
                .where(CopiedTrade.id == trade_id)
                .values(
                    status=status,
                    executed_price=result.executed_price,
                    executed_size=result.executed_size,
                    transaction_hash=result.transaction_hash,
                    slippage=result.slippage,
                    error_message=result.error_message,
                    executed_at=datetime.utcnow() if result.success else None
                )
            )
            await session.commit()
    
    async def _update_position(
        self, 
        decision: SignalDecision,
        result: ExecutionResult
    ):
        """Update position after successful trade"""
        signal = decision.original_signal
        
        async with get_async_session() as session:
            # Get existing position
            pos_result = await session.execute(
                select(Position).where(Position.token_id == signal.token_id)
            )
            position = pos_result.scalar_one_or_none()
            
            if position:
                # Update existing position
                if signal.direction == TradeDirection.BUY:
                    new_size = position.size + result.executed_size
                    new_cost = position.total_cost + (result.executed_price * result.executed_size)
                    new_avg_price = new_cost / new_size if new_size > 0 else 0
                else:
                    new_size = position.size - result.executed_size
                    new_cost = position.total_cost - (result.executed_price * result.executed_size)
                    new_avg_price = position.average_price  # Keep same avg for sells
                
                await session.execute(
                    update(Position)
                    .where(Position.id == position.id)
                    .values(
                        size=new_size,
                        total_cost=new_cost,
                        average_price=new_avg_price,
                        current_price=result.executed_price
                    )
                )
            else:
                # Create new position
                new_position = Position(
                    market_id=signal.market_id,
                    market_slug=signal.market_slug,
                    token_id=signal.token_id,
                    size=result.executed_size,
                    average_price=result.executed_price,
                    total_cost=result.executed_price * result.executed_size,
                    current_price=result.executed_price
                )
                session.add(new_position)
            
            await session.commit()
    
    async def _execute_trade(self, decision: SignalDecision) -> ExecutionResult:
        """Execute actual trade via CLOB client"""
        signal = decision.original_signal
        
        try:
            # Determine side
            side = BUY if signal.direction == TradeDirection.BUY else SELL
            
            # Get current market price for slippage calculation
            current_price = await self.api_client.get_price(
                signal.token_id,
                "BUY" if signal.direction == TradeDirection.BUY else "SELL"
            )
            
            # Check slippage
            if current_price:
                price_diff = abs(current_price - signal.price)
                slippage = price_diff / signal.price if signal.price > 0 else 0
                
                if slippage > self.settings.slippage_tolerance:
                    return ExecutionResult(
                        success=False,
                        order_result=OrderResult.REJECTED,
                        error_message=f"Slippage too high: {slippage:.2%}"
                    )
            
            # Create and submit order
            # Using market order for faster execution
            order_args = MarketOrderArgs(
                token_id=signal.token_id,
                amount=decision.copy_amount,
                side=side
            )
            
            signed_order = self._clob_client.create_market_order(order_args)
            response = self._clob_client.post_order(signed_order, OrderType.FOK)
            
            if response and response.get("success"):
                executed_price = float(response.get("avgPrice", signal.price))
                executed_size = float(response.get("filled", decision.copy_size))
                
                return ExecutionResult(
                    success=True,
                    order_result=OrderResult.SUCCESS,
                    order_id=response.get("orderID"),
                    transaction_hash=response.get("transactionHash"),
                    executed_price=executed_price,
                    executed_size=executed_size,
                    slippage=(executed_price - signal.price) / signal.price if signal.price > 0 else 0
                )
            else:
                return ExecutionResult(
                    success=False,
                    order_result=OrderResult.FAILED,
                    error_message=response.get("errorMsg", "Order submission failed")
                )
                
        except Exception as e:
            logger.error(f"Trade execution failed: {e}")
            return ExecutionResult(
                success=False,
                order_result=OrderResult.FAILED,
                error_message=str(e)
            )
    
    async def _simulate_execution(self, decision: SignalDecision) -> ExecutionResult:
        """Simulate trade execution for testing"""
        signal = decision.original_signal
        
        # Simulate some slippage
        import random
        slippage_pct = random.uniform(-0.01, 0.02)
        executed_price = signal.price * (1 + slippage_pct)
        
        logger.info(
            f"[SIMULATION] Executed {signal.direction.value} "
            f"{decision.copy_size:.4f} @ ${executed_price:.4f} "
            f"(slippage: {slippage_pct:.2%})"
        )
        
        return ExecutionResult(
            success=True,
            order_result=OrderResult.SUCCESS,
            order_id=f"SIM-{datetime.utcnow().timestamp()}",
            transaction_hash=None,
            executed_price=executed_price,
            executed_size=decision.copy_size,
            slippage=slippage_pct
        )
    
    async def create_limit_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float
    ) -> ExecutionResult:
        """
        Create a limit order
        
        Args:
            token_id: Token to trade
            side: "BUY" or "SELL"
            price: Limit price (0-1)
            size: Number of shares
            
        Returns:
            ExecutionResult
        """
        if not self.is_ready:
            return ExecutionResult(
                success=False,
                order_result=OrderResult.FAILED,
                error_message="Executor not initialized"
            )
        
        try:
            order_side = BUY if side.upper() == "BUY" else SELL
            
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=order_side
            )
            
            signed_order = self._clob_client.create_order(order_args)
            response = self._clob_client.post_order(signed_order, OrderType.GTC)
            
            if response and response.get("success"):
                return ExecutionResult(
                    success=True,
                    order_result=OrderResult.SUCCESS,
                    order_id=response.get("orderID")
                )
            else:
                return ExecutionResult(
                    success=False,
                    order_result=OrderResult.FAILED,
                    error_message=response.get("errorMsg", "Order failed")
                )
                
        except Exception as e:
            logger.error(f"Limit order failed: {e}")
            return ExecutionResult(
                success=False,
                order_result=OrderResult.FAILED,
                error_message=str(e)
            )
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order"""
        if not self.is_ready:
            return False
        
        try:
            self._clob_client.cancel(order_id)
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
    
    async def cancel_all_orders(self) -> bool:
        """Cancel all open orders"""
        if not self.is_ready:
            return False
        
        try:
            self._clob_client.cancel_all()
            return True
        except Exception as e:
            logger.error(f"Failed to cancel all orders: {e}")
            return False
    
    async def get_open_orders(self) -> List[Dict]:
        """Get all open orders"""
        if not self.is_ready:
            return []
        
        try:
            from py_clob_client.clob_types import OpenOrderParams
            orders = self._clob_client.get_orders(OpenOrderParams())
            return orders if orders else []
        except Exception as e:
            logger.error(f"Failed to get open orders: {e}")
            return []
    
    async def get_balances(self) -> Dict[str, float]:
        """Get account balances"""
        if not self.is_ready:
            return {}
        
        try:
            # This would need actual balance checking implementation
            # Placeholder for now
            return {"USDC": 0.0}
        except Exception as e:
            logger.error(f"Failed to get balances: {e}")
            return {}
    
    async def close(self):
        """Cleanup resources"""
        await self.api_client.close()


class DryRunExecutor(TradeExecutor):
    """
    Executor that only simulates trades without real execution
    Useful for testing and backtesting
    """
    
    def __init__(self):
        super().__init__()
        self._trade_history: List[Dict] = []
    
    async def initialize(self):
        """Initialize without CLOB client"""
        self._db_engine = await init_db()
        self._initialized = True
        logger.info("Dry run executor initialized (simulation mode)")
    
    @property
    def is_ready(self) -> bool:
        return self._initialized
    
    async def _execute_trade(self, decision: SignalDecision) -> ExecutionResult:
        """Always simulate in dry run mode"""
        result = await self._simulate_execution(decision)
        
        # Record for history
        self._trade_history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "market": decision.original_signal.market_id,
            "direction": decision.original_signal.direction.value,
            "size": decision.copy_size,
            "price": result.executed_price,
            "result": result.order_result.value
        })
        
        return result
    
    def get_trade_history(self) -> List[Dict]:
        """Get history of simulated trades"""
        return self._trade_history.copy()
    
    def get_simulated_pnl(self) -> float:
        """Calculate simulated PnL (placeholder)"""
        # Would need actual market outcome data
        return 0.0
