"""
Database Models for Polymarket Copy Trading System

Uses SQLAlchemy for ORM with async support
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, 
    ForeignKey, Text, Enum as SQLEnum, create_engine
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.ext.asyncio import async_sessionmaker
import enum

from config import get_settings

Base = declarative_base()


class TradeDirection(enum.Enum):
    """Trade direction enum"""
    BUY = "BUY"
    SELL = "SELL"


class TradeStatus(enum.Enum):
    """Trade execution status"""
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TrackedTrader(Base):
    """
    Tracked trader model - stores information about traders we're following
    """
    __tablename__ = "tracked_traders"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    address = Column(String(42), unique=True, nullable=False, index=True)
    alias = Column(String(100), nullable=True)
    
    # Performance metrics
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)
    
    # Tracking settings
    is_active = Column(Boolean, default=True)
    copy_ratio = Column(Float, default=0.1)  # Override global setting
    max_copy_amount = Column(Float, nullable=True)
    
    # Categories this trader specializes in
    specialties = Column(Text, nullable=True)  # JSON array
    
    # Timestamps
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_trade = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    trades = relationship("TraderTrade", back_populates="trader")
    copied_trades = relationship("CopiedTrade", back_populates="source_trader")
    
    def __repr__(self):
        return f"<TrackedTrader(address={self.address}, win_rate={self.win_rate:.2%})>"


class TraderTrade(Base):
    """
    Record of trades made by tracked traders
    """
    __tablename__ = "trader_trades"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    trader_id = Column(Integer, ForeignKey("tracked_traders.id"), nullable=False)
    
    # Trade details
    market_id = Column(String(100), nullable=False, index=True)
    market_slug = Column(String(255), nullable=True)
    token_id = Column(String(100), nullable=False)
    
    direction = Column(SQLEnum(TradeDirection), nullable=False)
    price = Column(Float, nullable=False)
    size = Column(Float, nullable=False)
    amount_usd = Column(Float, nullable=False)
    
    # On-chain data
    transaction_hash = Column(String(66), unique=True, nullable=False)
    block_number = Column(Integer, nullable=True)
    
    # Timestamps
    executed_at = Column(DateTime, nullable=False)
    detected_at = Column(DateTime, default=datetime.utcnow)
    
    # Was this trade copied?
    was_copied = Column(Boolean, default=False)
    
    # Relationships
    trader = relationship("TrackedTrader", back_populates="trades")
    copied_trade = relationship("CopiedTrade", back_populates="source_trade", uselist=False)
    
    def __repr__(self):
        return f"<TraderTrade(market={self.market_slug}, {self.direction.value} {self.size}@{self.price})>"


class CopiedTrade(Base):
    """
    Record of trades we executed by copying tracked traders
    """
    __tablename__ = "copied_trades"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    source_trade_id = Column(Integer, ForeignKey("trader_trades.id"), nullable=False)
    source_trader_id = Column(Integer, ForeignKey("tracked_traders.id"), nullable=False)
    
    # Our trade details
    market_id = Column(String(100), nullable=False)
    token_id = Column(String(100), nullable=False)
    
    direction = Column(SQLEnum(TradeDirection), nullable=False)
    intended_price = Column(Float, nullable=False)
    executed_price = Column(Float, nullable=True)
    intended_size = Column(Float, nullable=False)
    executed_size = Column(Float, nullable=True)
    amount_usd = Column(Float, nullable=True)
    
    # Execution details
    status = Column(SQLEnum(TradeStatus), default=TradeStatus.PENDING)
    transaction_hash = Column(String(66), nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Slippage tracking
    slippage = Column(Float, nullable=True)  # Actual - Intended price
    
    # PnL tracking
    entry_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    realized_pnl = Column(Float, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    executed_at = Column(DateTime, nullable=True)
    
    # Relationships
    source_trade = relationship("TraderTrade", back_populates="copied_trade")
    source_trader = relationship("TrackedTrader", back_populates="copied_trades")
    
    def __repr__(self):
        return f"<CopiedTrade(status={self.status.value}, {self.direction.value} {self.executed_size}@{self.executed_price})>"


class Position(Base):
    """
    Our current positions
    """
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    market_id = Column(String(100), nullable=False, index=True)
    market_slug = Column(String(255), nullable=True)
    token_id = Column(String(100), nullable=False, unique=True)
    outcome = Column(String(50), nullable=True)  # YES or NO
    
    # Position details
    size = Column(Float, default=0.0)
    average_price = Column(Float, default=0.0)
    total_cost = Column(Float, default=0.0)
    
    # Current value
    current_price = Column(Float, nullable=True)
    current_value = Column(Float, nullable=True)
    unrealized_pnl = Column(Float, nullable=True)
    
    # Timestamps
    opened_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Position(market={self.market_slug}, size={self.size}, pnl={self.unrealized_pnl})>"


class SystemStats(Base):
    """
    System-wide statistics and metrics
    """
    __tablename__ = "system_stats"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False, unique=True)
    
    # Trading stats
    total_trades = Column(Integer, default=0)
    successful_trades = Column(Integer, default=0)
    failed_trades = Column(Integer, default=0)
    
    # Financial stats
    total_volume = Column(Float, default=0.0)
    total_pnl = Column(Float, default=0.0)
    total_fees = Column(Float, default=0.0)
    
    # Performance
    win_rate = Column(Float, default=0.0)
    average_slippage = Column(Float, default=0.0)
    
    def __repr__(self):
        return f"<SystemStats(date={self.date}, pnl={self.total_pnl})>"


# Database initialization
async def init_db(database_url: Optional[str] = None):
    """Initialize database and create tables"""
    settings = get_settings()
    url = database_url or settings.database_url
    
    engine = create_async_engine(url, echo=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    return engine


def get_sync_engine(database_url: Optional[str] = None):
    """Get synchronous engine for simple operations"""
    settings = get_settings()
    url = database_url or settings.database_url
    
    # Convert async URL to sync
    sync_url = url.replace("+aiosqlite", "").replace("sqlite+aiosqlite", "sqlite")
    
    return create_engine(sync_url, echo=False)


# Global engine storage
_engine = None


async def get_engine():
    """Get or create async engine"""
    global _engine
    if _engine is None:
        _engine = await init_db()
    return _engine


from contextlib import asynccontextmanager

@asynccontextmanager
async def get_async_session():
    """Get async database session as context manager"""
    engine = await get_engine()
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = async_session()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
