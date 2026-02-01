"""
Polymarket Copy Trading System

A comprehensive system for tracking top traders and copying their trades
on the Polymarket prediction market platform.

Modules:
- config: Configuration management
- api_client: Polymarket API client
- models: Database models
- trader_tracker: Trader monitoring
- copy_strategy: Copy trading strategy engine
- trade_executor: Trade execution
- main: CLI entry point
"""

__version__ = "0.1.0"
__author__ = "Polymarket Copy Trading"

from .config import get_settings, Settings
from .api_client import PolymarketAPIClient, Market, Trade, OrderBook
from .models import TrackedTrader, TraderTrade, CopiedTrade, Position
from .trader_tracker import TraderTracker, TraderProfile, TradeSignal
from .copy_strategy import CopyTradingStrategy, SignalDecision
from .trade_executor import TradeExecutor, DryRunExecutor, ExecutionResult

__all__ = [
    # Config
    "get_settings",
    "Settings",
    # API
    "PolymarketAPIClient",
    "Market",
    "Trade",
    "OrderBook",
    # Models
    "TrackedTrader",
    "TraderTrade",
    "CopiedTrade",
    "Position",
    # Tracker
    "TraderTracker",
    "TraderProfile",
    "TradeSignal",
    # Strategy
    "CopyTradingStrategy",
    "SignalDecision",
    # Executor
    "TradeExecutor",
    "DryRunExecutor",
    "ExecutionResult",
]
