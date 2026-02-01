"""
Polymarket API Client Module

Provides unified access to Polymarket CLOB API and Gamma API
"""

import asyncio
import aiohttp
import httpx
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from datetime import datetime
from loguru import logger
from ratelimit import limits, sleep_and_retry

from config import get_settings, APIEndpoints


@dataclass
class Market:
    """Market data structure"""
    id: str
    question: str
    condition_id: str
    slug: str
    end_date: Optional[datetime]
    liquidity: float
    volume: float
    outcomes: List[str]
    outcome_prices: List[float]
    tokens: List[Dict[str, Any]]
    active: bool
    closed: bool
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Market":
        """Create Market from API response"""
        return cls(
            id=data.get("id", ""),
            question=data.get("question", ""),
            condition_id=data.get("condition_id", ""),
            slug=data.get("slug", ""),
            end_date=datetime.fromisoformat(data["end_date_iso"].replace("Z", "+00:00")) 
                if data.get("end_date_iso") else None,
            liquidity=float(data.get("liquidity", 0)),
            volume=float(data.get("volume", 0)),
            outcomes=data.get("outcomes", []),
            outcome_prices=[float(p) for p in data.get("outcomePrices", ["0", "0"])],
            tokens=data.get("tokens", []),
            active=data.get("active", False),
            closed=data.get("closed", False)
        )


@dataclass
class Trade:
    """Trade data structure"""
    id: str
    market_id: str
    maker: str
    taker: str
    side: str
    price: float
    size: float
    timestamp: datetime
    transaction_hash: str
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Trade":
        """Create Trade from API response"""
        return cls(
            id=data.get("id", ""),
            market_id=data.get("market", ""),
            maker=data.get("maker", ""),
            taker=data.get("taker", ""),
            side=data.get("side", ""),
            price=float(data.get("price", 0)),
            size=float(data.get("size", 0)),
            timestamp=datetime.fromtimestamp(int(data.get("timestamp", 0)) / 1000)
                if data.get("timestamp") else datetime.now(),
            transaction_hash=data.get("transactionHash", "")
        )


@dataclass
class OrderBook:
    """Order book data structure"""
    market_id: str
    token_id: str
    bids: List[Dict[str, float]]  # [{"price": 0.5, "size": 100}, ...]
    asks: List[Dict[str, float]]
    spread: float
    mid_price: float
    
    @classmethod
    def from_dict(cls, data: Dict, token_id: str) -> "OrderBook":
        """Create OrderBook from API response"""
        bids = [{"price": float(b["price"]), "size": float(b["size"])} 
                for b in data.get("bids", [])]
        asks = [{"price": float(a["price"]), "size": float(a["size"])} 
                for a in data.get("asks", [])]
        
        best_bid = bids[0]["price"] if bids else 0
        best_ask = asks[0]["price"] if asks else 1
        
        return cls(
            market_id=data.get("market", ""),
            token_id=token_id,
            bids=bids,
            asks=asks,
            spread=best_ask - best_bid,
            mid_price=(best_bid + best_ask) / 2 if bids and asks else 0
        )


class PolymarketAPIClient:
    """
    Unified Polymarket API Client
    
    Handles both CLOB API and Gamma API for market data
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.clob_host = self.settings.polymarket_host
        self.gamma_host = self.settings.polymarket_gamma_host
        self._session: Optional[aiohttp.ClientSession] = None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Content-Type": "application/json"}
            )
        return self._session
    
    async def close(self):
        """Close the HTTP session"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    @sleep_and_retry
    @limits(calls=10, period=1)  # Rate limit: 10 calls per second
    async def _request(
        self, 
        method: str, 
        url: str, 
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None
    ) -> Dict:
        """Make HTTP request with rate limiting"""
        session = await self._get_session()
        
        try:
            async with session.request(
                method, url, params=params, json=json_data
            ) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as e:
            logger.error(f"API request failed: {e}")
            raise
    
    # ==================== Market Data APIs ====================
    
    async def get_markets(
        self, 
        limit: int = 100,
        offset: int = 0,
        active: bool = True,
        closed: bool = False
    ) -> List[Market]:
        """
        Get list of markets from Gamma API
        
        Args:
            limit: Number of markets to fetch
            offset: Pagination offset
            active: Filter active markets
            closed: Filter closed markets
            
        Returns:
            List of Market objects
        """
        url = f"{self.gamma_host}/markets"
        params = {
            "limit": limit,
            "offset": offset,
            "active": str(active).lower(),
            "closed": str(closed).lower()
        }
        
        data = await self._request("GET", url, params=params)
        return [Market.from_dict(m) for m in data]
    
    async def get_market(self, market_id: str) -> Optional[Market]:
        """Get single market by ID"""
        url = f"{self.gamma_host}/markets/{market_id}"
        
        try:
            data = await self._request("GET", url)
            return Market.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to get market {market_id}: {e}")
            return None
    
    async def search_markets(self, query: str, limit: int = 20) -> List[Market]:
        """Search markets by keyword"""
        url = f"{self.gamma_host}/markets"
        params = {"_q": query, "limit": limit}
        
        data = await self._request("GET", url, params=params)
        return [Market.from_dict(m) for m in data]
    
    # ==================== Order Book APIs ====================
    
    async def get_order_book(self, token_id: str) -> Optional[OrderBook]:
        """
        Get order book for a token
        
        Args:
            token_id: The token ID (YES or NO outcome token)
            
        Returns:
            OrderBook object
        """
        url = f"{self.clob_host}/book"
        params = {"token_id": token_id}
        
        try:
            data = await self._request("GET", url, params=params)
            return OrderBook.from_dict(data, token_id)
        except Exception as e:
            logger.error(f"Failed to get order book for {token_id}: {e}")
            return None
    
    async def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get midpoint price for a token"""
        url = f"{self.clob_host}/midpoint"
        params = {"token_id": token_id}
        
        try:
            data = await self._request("GET", url, params=params)
            return float(data.get("mid", 0))
        except Exception as e:
            logger.error(f"Failed to get midpoint for {token_id}: {e}")
            return None
    
    async def get_price(self, token_id: str, side: str = "BUY") -> Optional[float]:
        """Get best price for a token"""
        url = f"{self.clob_host}/price"
        params = {"token_id": token_id, "side": side}
        
        try:
            data = await self._request("GET", url, params=params)
            return float(data.get("price", 0))
        except Exception as e:
            logger.error(f"Failed to get price for {token_id}: {e}")
            return None
    
    # ==================== Trade History APIs ====================
    
    async def get_trades(
        self, 
        market_id: Optional[str] = None,
        maker: Optional[str] = None,
        limit: int = 100
    ) -> List[Trade]:
        """
        Get trade history
        
        Args:
            market_id: Filter by market
            maker: Filter by maker address
            limit: Number of trades to fetch
            
        Returns:
            List of Trade objects
        """
        url = f"{self.clob_host}/trades"
        params = {"limit": limit}
        
        if market_id:
            params["market"] = market_id
        if maker:
            params["maker"] = maker
        
        try:
            data = await self._request("GET", url, params=params)
            return [Trade.from_dict(t) for t in data]
        except Exception as e:
            logger.error(f"Failed to get trades: {e}")
            return []
    
    # ==================== Trader Data APIs ====================
    
    async def get_trader_positions(self, address: str) -> List[Dict]:
        """
        Get positions for a trader address
        
        Args:
            address: Wallet address
            
        Returns:
            List of position dictionaries
        """
        url = f"{self.clob_host}/positions"
        params = {"user": address}
        
        try:
            data = await self._request("GET", url, params=params)
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"Failed to get positions for {address}: {e}")
            return []
    
    async def get_trader_orders(
        self, 
        address: str,
        market_id: Optional[str] = None
    ) -> List[Dict]:
        """Get open orders for a trader"""
        url = f"{self.clob_host}/orders"
        params = {"maker": address}
        
        if market_id:
            params["market"] = market_id
        
        try:
            data = await self._request("GET", url, params=params)
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"Failed to get orders for {address}: {e}")
            return []


class PolymarketDataClient:
    """
    Client for fetching additional data from third-party sources
    (e.g., PolymarketAnalytics, on-chain data)
    """
    
    def __init__(self):
        self.analytics_base = "https://polymarketanalytics.com/api"
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def get_top_traders(
        self, 
        timeframe: str = "week",
        category: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get top traders (Note: This is a placeholder - actual implementation
        depends on available data sources)
        
        Args:
            timeframe: "day", "week", "month"
            category: "politics", "crypto", "sports", etc.
            limit: Number of traders to return
            
        Returns:
            List of trader data dictionaries
        """
        # This would need actual API endpoint or on-chain data scraping
        # Placeholder implementation
        logger.warning("get_top_traders: Using placeholder implementation")
        return []
    
    async def get_trader_stats(self, address: str) -> Optional[Dict]:
        """
        Get detailed statistics for a trader
        
        Args:
            address: Wallet address
            
        Returns:
            Trader statistics dictionary
        """
        # Placeholder implementation
        logger.warning("get_trader_stats: Using placeholder implementation")
        return None


# Synchronous wrapper for compatibility
class SyncPolymarketClient:
    """Synchronous wrapper for PolymarketAPIClient"""
    
    def __init__(self):
        self._async_client = PolymarketAPIClient()
    
    def _run(self, coro):
        """Run async coroutine synchronously"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    
    def get_markets(self, **kwargs) -> List[Market]:
        return self._run(self._async_client.get_markets(**kwargs))
    
    def get_market(self, market_id: str) -> Optional[Market]:
        return self._run(self._async_client.get_market(market_id))
    
    def get_order_book(self, token_id: str) -> Optional[OrderBook]:
        return self._run(self._async_client.get_order_book(token_id))
    
    def get_trades(self, **kwargs) -> List[Trade]:
        return self._run(self._async_client.get_trades(**kwargs))
    
    def close(self):
        self._run(self._async_client.close())
