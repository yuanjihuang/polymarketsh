"""
On-Chain Data Client for Polymarket

This module provides access to Polymarket data purely through:
1. Polygon RPC nodes (direct blockchain queries)
2. The Graph subgraphs (GraphQL queries)
3. Dune Analytics API (optional, for historical data)

No Polymarket API required!
"""

import asyncio
import aiohttp
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger
from web3 import Web3, AsyncWeb3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_abi import decode
import json


# ============== Public RPC Endpoints ==============
# Multiple fallback RPC endpoints for Polygon
POLYGON_RPC_ENDPOINTS = [
    "https://polygon-rpc.com",
    "https://1rpc.io/matic",
    "https://polygon.drpc.org",
    "https://rpc-mainnet.matic.quiknode.pro",
    "https://polygon-bor-rpc.publicnode.com",
]

# The Graph endpoints - NOTE: Hosted service is deprecated
# For production, you should deploy your own subgraph or use decentralized network
GRAPH_ENDPOINTS = {
    # Try decentralized network endpoints
    "decentralized": "https://gateway.thegraph.com/api/[api-key]/subgraphs/id/",
    # Alternative: self-hosted or community subgraphs
    "goldsky_activity": "https://api.goldsky.com/api/public/project_cl6mb8i9v0003e8xgq0k6h8g7/subgraphs/polymarket-activity/prod/gn",
}

# Alternative data sources that don't require Polymarket API
ALTERNATIVE_DATA_SOURCES = {
    # Dune Analytics (requires API key for full access)
    "dune": "https://api.dune.com/api/v1",
    # Polygonscan API (for transaction data)
    "polygonscan": "https://api.polygonscan.com/api",
}


# ============== Contract ABIs (partial) ==============

# CTF Exchange event signatures
CTF_EXCHANGE_EVENTS = {
    "OrderFilled": "0x8d3e4e95b0d2d14d22a8a73d5ce93f0a8a4b8e3e7a1f4c6b9d2e5a8f0c3b6d9e",
    "OrdersMatched": Web3.keccak(text="OrdersMatched(bytes32,bytes32,address,address,uint256,uint256,uint256,uint256,uint256,uint256)").hex(),
    "TokensTraded": Web3.keccak(text="TokensTraded(address,uint256,uint256,uint8,uint256,uint256,address,uint256)").hex(),
}

# Minimal ABI for reading transfer events
ERC20_TRANSFER_EVENT = Web3.keccak(text="Transfer(address,address,uint256)").hex()
ERC1155_TRANSFER_SINGLE = Web3.keccak(text="TransferSingle(address,address,address,uint256,uint256)").hex()
ERC1155_TRANSFER_BATCH = Web3.keccak(text="TransferBatch(address,address,address,uint256[],uint256[])").hex()


@dataclass
class OnChainTrade:
    """Represents a trade detected from blockchain data"""
    tx_hash: str
    block_number: int
    timestamp: datetime
    trader: str
    token_id: str
    amount: float
    price: float
    side: str  # BUY or SELL
    market_id: Optional[str] = None
    raw_data: Dict = field(default_factory=dict)


@dataclass
class TraderStats:
    """Statistics for a tracked trader"""
    address: str
    total_trades: int = 0
    total_volume: float = 0.0
    profit_loss: float = 0.0
    win_rate: float = 0.0
    avg_trade_size: float = 0.0
    last_active: Optional[datetime] = None
    positions: Dict[str, float] = field(default_factory=dict)


class OnChainClient:
    """
    Pure on-chain data client for Polymarket
    
    Features:
    - Direct blockchain queries via Polygon RPC
    - GraphQL queries via The Graph
    - No dependency on Polymarket's official API
    """
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        graph_endpoint: Optional[str] = None,
    ):
        self.rpc_endpoints = [rpc_url] + POLYGON_RPC_ENDPOINTS if rpc_url else POLYGON_RPC_ENDPOINTS
        self.current_rpc_index = 0
        self.graph_endpoint = graph_endpoint or GRAPH_ENDPOINTS.get("goldsky")
        
        self.w3: Optional[AsyncWeb3] = None
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Polymarket contract addresses
        self.contracts = {
            "CTF_EXCHANGE": "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
            "NEG_RISK_CTF_EXCHANGE": "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",
            "CTF": "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045",
            "USDC": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
            "USDC_E": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",  # USDC.e (native)
        }
        
        self._block_cache: Dict[int, Dict] = {}
    
    async def connect(self) -> bool:
        """Connect to Polygon RPC with automatic fallback"""
        for i, rpc_url in enumerate(self.rpc_endpoints):
            try:
                logger.info(f"Trying RPC: {rpc_url}")
                self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
                # Add POA middleware for Polygon network
                self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
                
                if await self.w3.is_connected():
                    block = await self.w3.eth.block_number
                    logger.success(f"Connected to Polygon RPC: {rpc_url}, block: {block}")
                    self.current_rpc_index = i
                    return True
            except Exception as e:
                logger.warning(f"RPC {rpc_url} failed: {e}")
                continue
        
        logger.error("All RPC endpoints failed")
        return False
    
    async def _ensure_session(self):
        """Ensure aiohttp session is created"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"Content-Type": "application/json"}
            )
    
    async def close(self):
        """Close connections"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    # ============== The Graph Queries ==============
    
    async def graph_query(self, query: str, variables: Optional[Dict] = None) -> Dict:
        """Execute a GraphQL query against The Graph"""
        await self._ensure_session()
        
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        
        try:
            async with self.session.post(self.graph_endpoint, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "errors" in data:
                        logger.warning(f"GraphQL errors: {data['errors']}")
                    return data.get("data", {})
                else:
                    logger.error(f"GraphQL request failed: {resp.status}")
                    return {}
        except Exception as e:
            logger.error(f"GraphQL query error: {e}")
            return {}
    
    async def get_trader_pnl(self, trader_address: str) -> Optional[TraderStats]:
        """Get trader P&L data from The Graph"""
        query = """
        query GetTraderPnL($trader: String!) {
            userPnls(where: {user: $trader}, first: 100) {
                id
                user
                realizedPnl
                unrealizedPnl
                totalVolume
                numberOfTrades
            }
        }
        """
        
        data = await self.graph_query(query, {"trader": trader_address.lower()})
        
        if data and "userPnls" in data:
            pnls = data["userPnls"]
            if pnls:
                total_pnl = sum(float(p.get("realizedPnl", 0)) for p in pnls)
                total_volume = sum(float(p.get("totalVolume", 0)) for p in pnls)
                total_trades = sum(int(p.get("numberOfTrades", 0)) for p in pnls)
                
                return TraderStats(
                    address=trader_address,
                    total_trades=total_trades,
                    total_volume=total_volume,
                    profit_loss=total_pnl,
                    avg_trade_size=total_volume / total_trades if total_trades > 0 else 0,
                )
        
        return None
    
    async def get_top_traders(self, limit: int = 20) -> List[TraderStats]:
        """Get top traders by P&L from The Graph"""
        query = """
        query GetTopTraders($limit: Int!) {
            userPnls(
                first: $limit,
                orderBy: realizedPnl,
                orderDirection: desc,
                where: {numberOfTrades_gt: 10}
            ) {
                id
                user
                realizedPnl
                unrealizedPnl
                totalVolume
                numberOfTrades
            }
        }
        """
        
        data = await self.graph_query(query, {"limit": limit})
        
        traders = []
        if data and "userPnls" in data:
            for p in data["userPnls"]:
                traders.append(TraderStats(
                    address=p["user"],
                    total_trades=int(p.get("numberOfTrades", 0)),
                    total_volume=float(p.get("totalVolume", 0)),
                    profit_loss=float(p.get("realizedPnl", 0)),
                ))
        
        return traders
    
    async def get_recent_trades_by_trader(
        self, 
        trader_address: str, 
        limit: int = 50
    ) -> List[Dict]:
        """Get recent trades for a specific trader from The Graph"""
        query = """
        query GetTraderTrades($trader: String!, $limit: Int!) {
            fpmmTrades(
                first: $limit,
                orderBy: creationTimestamp,
                orderDirection: desc,
                where: {creator: $trader}
            ) {
                id
                creator
                outcomeTokenAmounts
                outcomeTokenNetCost
                transactionHash
                creationTimestamp
                fpmm {
                    id
                    title
                }
            }
        }
        """
        
        data = await self.graph_query(query, {
            "trader": trader_address.lower(),
            "limit": limit
        })
        
        return data.get("fpmmTrades", [])
    
    # ============== Direct Blockchain Queries ==============
    
    async def get_block_timestamp(self, block_number: int) -> datetime:
        """Get timestamp for a block number"""
        if block_number in self._block_cache:
            return self._block_cache[block_number]["timestamp"]
        
        block = await self.w3.eth.get_block(block_number)
        timestamp = datetime.fromtimestamp(block.timestamp)
        self._block_cache[block_number] = {"timestamp": timestamp}
        return timestamp
    
    async def get_recent_ctf_transfers(
        self,
        trader_address: Optional[str] = None,
        from_block: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get recent CTF (Conditional Token Framework) transfers
        These represent trades on Polymarket
        """
        if not self.w3:
            await self.connect()
        
        if from_block is None:
            current_block = await self.w3.eth.block_number
            from_block = current_block - 10000  # Last ~10k blocks (~4-6 hours)
        
        # Build filter for ERC1155 TransferSingle events on CTF contract
        topics = [ERC1155_TRANSFER_SINGLE]
        if trader_address:
            # Filter by recipient (to address is in topics[3])
            padded_address = "0x" + trader_address.lower().replace("0x", "").zfill(64)
            topics.append(None)  # operator (any)
            topics.append(None)  # from (any)
            topics.append(padded_address)  # to
        
        try:
            logs = await self.w3.eth.get_logs({
                "address": self.contracts["CTF"],
                "fromBlock": from_block,
                "toBlock": "latest",
                "topics": topics[:1] if len(topics) == 1 else topics,
            })
            
            transfers = []
            for log in logs[-limit:]:
                transfers.append({
                    "tx_hash": log.transactionHash.hex(),
                    "block_number": log.blockNumber,
                    "log_index": log.logIndex,
                    "address": log.address,
                    "topics": [t.hex() for t in log.topics],
                    "data": log.data.hex() if log.data else "",
                })
            
            return transfers
        except Exception as e:
            logger.error(f"Error fetching CTF transfers: {e}")
            return []
    
    async def monitor_trader_transactions(
        self,
        trader_address: str,
        callback,
        poll_interval: int = 15
    ):
        """
        Monitor a trader's transactions in real-time
        
        Args:
            trader_address: Wallet address to monitor
            callback: Async function to call when new transaction detected
            poll_interval: Seconds between polls
        """
        if not self.w3:
            await self.connect()
        
        last_block = await self.w3.eth.block_number
        trader_checksum = Web3.to_checksum_address(trader_address)
        
        logger.info(f"Starting to monitor trader: {trader_address}")
        
        while True:
            try:
                current_block = await self.w3.eth.block_number
                
                if current_block > last_block:
                    # Check for transactions in new blocks
                    for block_num in range(last_block + 1, current_block + 1):
                        try:
                            block = await self.w3.eth.get_block(block_num, full_transactions=True)
                            
                            for tx in block.transactions:
                                # Check if trader is involved
                                if tx.get("from") == trader_checksum or tx.get("to") == trader_checksum:
                                    # Check if it's a Polymarket contract interaction
                                    if tx.get("to") in [
                                        self.contracts["CTF_EXCHANGE"],
                                        self.contracts["NEG_RISK_CTF_EXCHANGE"],
                                        self.contracts["CTF"],
                                    ]:
                                        logger.info(f"Detected Polymarket tx from {trader_address}: {tx.hash.hex()}")
                                        await callback(tx, block_num)
                        except Exception as e:
                            logger.warning(f"Error processing block {block_num}: {e}")
                    
                    last_block = current_block
                
                await asyncio.sleep(poll_interval)
                
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(poll_interval * 2)
    
    async def decode_trade_from_tx(self, tx_hash: str) -> Optional[OnChainTrade]:
        """Decode trade details from a transaction hash"""
        if not self.w3:
            await self.connect()
        
        try:
            tx = await self.w3.eth.get_transaction(tx_hash)
            receipt = await self.w3.eth.get_transaction_receipt(tx_hash)
            
            # Parse logs to find trade details
            for log in receipt.logs:
                if log.address.lower() == self.contracts["CTF"].lower():
                    # ERC1155 TransferSingle
                    if len(log.topics) >= 4:
                        operator = "0x" + log.topics[1].hex()[-40:]
                        from_addr = "0x" + log.topics[2].hex()[-40:]
                        to_addr = "0x" + log.topics[3].hex()[-40:]
                        
                        # Decode data (token_id, amount)
                        if log.data and len(log.data) >= 64:
                            token_id, amount = decode(["uint256", "uint256"], log.data)
                            
                            # Determine if buy or sell
                            side = "BUY" if from_addr == "0x" + "0" * 40 else "SELL"
                            
                            block = await self.w3.eth.get_block(tx.blockNumber)
                            
                            return OnChainTrade(
                                tx_hash=tx_hash,
                                block_number=tx.blockNumber,
                                timestamp=datetime.fromtimestamp(block.timestamp),
                                trader=to_addr if side == "BUY" else from_addr,
                                token_id=str(token_id),
                                amount=amount / 1e6,  # Assuming 6 decimals
                                price=0,  # Price needs additional decoding
                                side=side,
                                raw_data={
                                    "operator": operator,
                                    "from": from_addr,
                                    "to": to_addr,
                                }
                            )
            
            return None
        except Exception as e:
            logger.error(f"Error decoding tx {tx_hash}: {e}")
            return None
    
    async def get_wallet_ctf_balances(self, wallet_address: str) -> Dict[str, float]:
        """Get all CTF token balances for a wallet (positions)"""
        # This requires knowing token IDs or querying transfer events
        # For simplicity, we'll use The Graph if available
        
        query = """
        query GetWalletPositions($wallet: String!) {
            userPositions(where: {user: $wallet}, first: 100) {
                id
                tokenId
                balance
                market {
                    id
                    title
                }
            }
        }
        """
        
        data = await self.graph_query(query, {"wallet": wallet_address.lower()})
        
        positions = {}
        if data and "userPositions" in data:
            for pos in data["userPositions"]:
                token_id = pos.get("tokenId", "unknown")
                balance = float(pos.get("balance", 0))
                positions[token_id] = balance
        
        return positions
    
    async def get_market_by_token_id(self, token_id: str) -> Optional[Dict]:
        """
        Get market information by token ID
        
        Tries multiple sources:
        1. Gamma API (most reliable for market info)
        2. Heuristic fallback
        
        Returns market title, question, and outcome details
        """
        # Ensure token_id is string
        token_id = str(token_id)
        
        # Try Gamma API first (most reliable)
        await self._ensure_session()
        
        try:
            url = f"https://gamma-api.polymarket.com/markets?clob_token_ids={token_id}"
            
            async with self.session.get(url, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and len(data) > 0:
                        market = data[0]
                        return {
                            "condition_id": market.get("condition_id", ""),
                            "question": market.get("question", "Unknown Market"),
                            "market_slug": market.get("market_slug", ""),
                            "outcome": market.get("outcome", ""),
                            "outcomes": market.get("outcomes", ""),
                            "description": market.get("description", "")[:200] if market.get("description") else "",
                            "image": market.get("image", ""),
                            "end_date": market.get("end_date_iso", ""),
                            "active": market.get("active", False),
                        }
        except Exception as e:
            logger.debug(f"Gamma API unavailable: {e}")
        
        # Fallback: Try The Graph (may not work for all markets)
        result = await self._get_market_from_graph(token_id)
        if result:
            return result
        
        return None
    
    async def _get_market_from_graph(self, token_id: str) -> Optional[Dict]:
        """
        Get market and outcome info from The Graph
        
        Note: The Graph endpoint may not have all market data
        """
        # Ensure string type
        token_id_str = str(token_id)
        
        # Try a simpler query that's more likely to work
        query = """
        query GetMarketInfo($tokenId: String!) {
            fixedProductMarketMakers(
                where: {id_contains: $tokenId}
                first: 1
            ) {
                id
                title
                outcomes
            }
        }
        """
        
        try:
            data = await self.graph_query(query, {"tokenId": token_id_str})
            
            if data and "fixedProductMarketMakers" in data and data["fixedProductMarketMakers"]:
                fpmm = data["fixedProductMarketMakers"][0]
                outcomes = fpmm.get("outcomes", ["YES", "NO"])
                
                return {
                    "condition_id": "",
                    "question": fpmm.get("title", "Unknown Market"),
                    "outcome": outcomes[0] if outcomes else "YES",
                    "outcomes": outcomes,
                }
        except Exception as e:
            logger.debug(f"Graph query failed: {e}")
        
        return None
    
    async def lookup_markets_batch(self, token_ids: List[str]) -> Dict[str, Dict]:
        """Batch lookup markets by token IDs"""
        results = {}
        
        # Query in batches of 10
        for i in range(0, len(token_ids), 10):
            batch = token_ids[i:i+10]
            ids_param = ",".join(batch)
            
            try:
                await self._ensure_session()
                url = f"https://gamma-api.polymarket.com/markets?clob_token_ids={ids_param}"
                
                async with self.session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        for market in data:
                            for token in market.get("tokens", []):
                                if token.get("token_id") in batch:
                                    results[token["token_id"]] = {
                                        "question": market.get("question", "Unknown"),
                                        "outcome": token.get("outcome", ""),
                                        "market_slug": market.get("market_slug", ""),
                                    }
            except Exception as e:
                logger.warning(f"Batch lookup error: {e}")
        
        return results


class DuneClient:
    """
    Optional Dune Analytics client for historical data
    
    Note: Requires Dune API key for full functionality
    Free tier has limited access
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.base_url = "https://api.dune.com/api/v1"
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Public Polymarket dashboards on Dune
        self.dashboards = {
            "polymarket_overview": "https://dune.com/rchen8/polymarket",
            "polymarket_trades": "https://dune.com/polymarket/polymarket",
        }
    
    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["X-Dune-API-Key"] = self.api_key
            self.session = aiohttp.ClientSession(headers=headers)
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def get_query_results(self, query_id: int) -> Dict:
        """Get results from a pre-existing Dune query"""
        if not self.api_key:
            logger.warning("Dune API key not set, limited functionality")
            return {}
        
        await self._ensure_session()
        
        try:
            url = f"{self.base_url}/query/{query_id}/results"
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logger.error(f"Dune API error: {resp.status}")
                    return {}
        except Exception as e:
            logger.error(f"Dune query error: {e}")
            return {}


class PolygonscanClient:
    """
    Polygonscan API client for transaction data
    
    Free tier: 5 calls/sec, 100,000 calls/day
    Get API key at: https://polygonscan.com/apis
    """
    
    def __init__(self, api_key: str = ""):
        self.api_key = api_key or "YourApiKeyToken"  # Free tier without key has limits
        self.base_url = "https://api.polygonscan.com/api"
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def _request(self, params: Dict) -> Dict:
        """Make API request"""
        await self._ensure_session()
        params["apikey"] = self.api_key
        
        try:
            async with self.session.get(self.base_url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "1":
                        return data.get("result", [])
                    else:
                        logger.warning(f"Polygonscan API: {data.get('message', 'error')}")
                        return []
        except Exception as e:
            logger.error(f"Polygonscan error: {e}")
        return []
    
    async def get_transactions(
        self, 
        address: str,
        start_block: int = 0,
        end_block: int = 99999999,
        page: int = 1,
        offset: int = 100
    ) -> List[Dict]:
        """Get transactions for an address"""
        params = {
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": start_block,
            "endblock": end_block,
            "page": page,
            "offset": offset,
            "sort": "desc"
        }
        return await self._request(params)
    
    async def get_internal_transactions(
        self,
        address: str,
        start_block: int = 0,
        end_block: int = 99999999
    ) -> List[Dict]:
        """Get internal transactions for an address"""
        params = {
            "module": "account",
            "action": "txlistinternal",
            "address": address,
            "startblock": start_block,
            "endblock": end_block,
            "sort": "desc"
        }
        return await self._request(params)
    
    async def get_erc20_transfers(
        self,
        address: str,
        contract_address: Optional[str] = None,
        page: int = 1,
        offset: int = 100
    ) -> List[Dict]:
        """Get ERC20 token transfers for an address"""
        params = {
            "module": "account",
            "action": "tokentx",
            "address": address,
            "page": page,
            "offset": offset,
            "sort": "desc"
        }
        if contract_address:
            params["contractaddress"] = contract_address
        return await self._request(params)
    
    async def get_erc1155_transfers(
        self,
        address: str,
        contract_address: Optional[str] = None,
        page: int = 1,
        offset: int = 100
    ) -> List[Dict]:
        """Get ERC1155 token transfers for an address (CTF tokens)"""
        params = {
            "module": "account",
            "action": "token1155tx",
            "address": address,
            "page": page,
            "offset": offset,
            "sort": "desc"
        }
        if contract_address:
            params["contractaddress"] = contract_address
        return await self._request(params)
    
    async def get_polymarket_trades(
        self,
        address: str,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get Polymarket trades for an address by looking at 
        CTF token (ERC1155) transfers
        """
        ctf_address = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
        transfers = await self.get_erc1155_transfers(
            address=address,
            contract_address=ctf_address,
            offset=limit
        )
        
        trades = []
        for tx in transfers:
            trades.append({
                "tx_hash": tx.get("hash"),
                "block_number": int(tx.get("blockNumber", 0)),
                "timestamp": int(tx.get("timeStamp", 0)),
                "from": tx.get("from"),
                "to": tx.get("to"),
                "token_id": tx.get("tokenID"),
                "token_value": tx.get("tokenValue"),
                "side": "BUY" if tx.get("to", "").lower() == address.lower() else "SELL"
            })
        
        return trades


# ============== Utility Functions ==============

async def find_working_rpc() -> Optional[str]:
    """Find a working Polygon RPC endpoint"""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
        for rpc in POLYGON_RPC_ENDPOINTS:
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "eth_blockNumber",
                    "params": [],
                    "id": 1
                }
                async with session.post(rpc, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "result" in data:
                            logger.info(f"Working RPC found: {rpc}")
                            return rpc
            except:
                continue
    return None


async def test_connection():
    """Test on-chain client connection"""
    client = OnChainClient()
    
    print("Testing Polygon RPC connection...")
    if await client.connect():
        print(f"✅ Connected to Polygon")
        
        # Test block query
        block = await client.w3.eth.block_number
        print(f"Current block: {block}")
        
        # Test Graph query
        print("\nTesting The Graph...")
        traders = await client.get_top_traders(limit=5)
        if traders:
            print(f"✅ Found {len(traders)} top traders")
            for t in traders[:3]:
                print(f"  - {t.address[:10]}... P&L: ${t.profit_loss:,.2f}")
        else:
            print("⚠️ The Graph query returned no results (may need different endpoint)")
    else:
        print("❌ Failed to connect to Polygon RPC")
    
    await client.close()


if __name__ == "__main__":
    asyncio.run(test_connection())
