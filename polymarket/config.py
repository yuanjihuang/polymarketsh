"""
Configuration module for Polymarket Copy Trading System
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
import os
from pathlib import Path


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Wallet Configuration
    private_key: str = Field(default="", description="Polygon wallet private key")
    wallet_address: str = Field(default="", description="Wallet address")
    
    # Polymarket API
    polymarket_host: str = Field(default="https://clob.polymarket.com")
    polymarket_gamma_host: str = Field(default="https://gamma-api.polymarket.com")
    chain_id: int = Field(default=137)
    
    # Polygon RPC
    polygon_rpc_url: str = Field(default="https://polygon-rpc.com")
    
    # Trading Limits
    max_trade_amount: float = Field(default=100.0, description="Max USDC per trade")
    min_trade_amount: float = Field(default=5.0, description="Min USDC per trade")
    max_position_size: float = Field(default=1000.0, description="Max total position")
    slippage_tolerance: float = Field(default=0.02, description="Slippage tolerance")
    
    # Copy Trading
    min_trader_profit_rate: float = Field(default=0.1, description="Min profit rate to follow")
    min_trader_trades: int = Field(default=10, description="Min trades for consideration")
    max_traders_to_follow: int = Field(default=10, description="Max traders to follow")
    copy_ratio: float = Field(default=0.1, description="Copy ratio of trade size")
    copy_delay_seconds: int = Field(default=5, description="Delay before copying")
    
    # Monitoring
    poll_interval: int = Field(default=30, description="Polling interval in seconds")
    
    # Database
    database_url: str = Field(default="sqlite+aiosqlite:///./copy_trading.db")
    
    # Logging
    log_level: str = Field(default="INFO")
    log_file: str = Field(default="logs/copy_trading.log")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


def get_settings() -> Settings:
    """Get application settings"""
    return Settings()


# Polymarket Contract Addresses (Polygon)
class ContractAddresses:
    """Polymarket smart contract addresses on Polygon"""
    
    # USDC on Polygon
    USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    
    # Polymarket Exchange Contract
    EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
    
    # Conditional Tokens Framework
    CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
    
    # Neg Risk Exchange (for certain markets)
    NEG_RISK_EXCHANGE = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
    
    # Neg Risk CTF Exchange
    NEG_RISK_CTF_EXCHANGE = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"


# API Endpoints
class APIEndpoints:
    """Polymarket API endpoints"""
    
    # CLOB API
    CLOB_HOST = "https://clob.polymarket.com"
    
    # Gamma API (Markets)
    GAMMA_HOST = "https://gamma-api.polymarket.com"
    
    # Endpoints
    MARKETS = "/markets"
    EVENTS = "/events"
    ORDER_BOOK = "/book"
    PRICE = "/price"
    MIDPOINT = "/midpoint"
    TRADES = "/trades"
    
    # Data API
    DATA_API = "https://data-api.polymarket.com"


# Trading Constants
class TradingConstants:
    """Trading-related constants"""
    
    # Order Types
    ORDER_TYPE_GTC = "GTC"  # Good Till Cancelled
    ORDER_TYPE_FOK = "FOK"  # Fill Or Kill
    ORDER_TYPE_GTD = "GTD"  # Good Till Date
    
    # Sides
    BUY = "BUY"
    SELL = "SELL"
    
    # Price bounds (prediction market probabilities)
    MIN_PRICE = 0.01
    MAX_PRICE = 0.99
    
    # Tick size
    TICK_SIZE = 0.01
