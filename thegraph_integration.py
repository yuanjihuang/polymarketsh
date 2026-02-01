"""
使用 The Graph 查询 Polymarket 数据
The Graph 是一个去中心化的区块链数据索引协议
"""

import requests
import json
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PolymarketGraphClient:
    """
    Polymarket The Graph 客户端
    
    注意：需要找到 Polymarket 的官方 subgraph 地址
    可能的来源：
    1. Polymarket 官方文档
    2. The Graph Explorer
    3. Polymarket GitHub
    """
    
    def __init__(self, subgraph_url: Optional[str] = None):
        # Polymarket subgraph URL（需要确认）
        # 这是一个示例 URL，实际使用时需要替换为真实的 subgraph
        self.subgraph_url = subgraph_url or "https://api.thegraph.com/subgraphs/name/polymarket/..."
        
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json'
        })
    
    def query(self, query_string: str, variables: Optional[Dict] = None) -> Dict:
        """
        执行 GraphQL 查询
        
        Args:
            query_string: GraphQL 查询字符串
            variables: 查询变量
            
        Returns:
            查询结果
        """
        payload = {
            'query': query_string
        }
        
        if variables:
            payload['variables'] = variables
        
        try:
            response = self.session.post(self.subgraph_url, json=payload)
            response.raise_for_status()
            return response.json()
        
        except requests.exceptions.RequestException as e:
            logger.error(f"GraphQL 查询失败: {e}")
            return {}
    
    def get_top_traders(self, timeframe: int = 86400, limit: int = 20) -> List[Dict]:
        """
        获取顶级交易者
        
        Args:
            timeframe: 时间范围（秒）
            limit: 返回数量
            
        Returns:
            交易者列表
        """
        # 计算时间戳
        current_time = int(datetime.now().timestamp())
        start_time = current_time - timeframe
        
        query = """
        query GetTopTraders($startTime: Int!, $limit: Int!) {
          users(
            first: $limit
            orderBy: totalVolume
            orderDirection: desc
            where: {
              lastTradeTimestamp_gte: $startTime
            }
          ) {
            id
            address
            totalVolume
            totalTrades
            totalProfit
            winRate
            activePositions {
              id
              market {
                id
                question
              }
              outcome
              shares
              avgPrice
              currentValue
              unrealizedPnL
            }
          }
        }
        """
        
        variables = {
            'startTime': start_time,
            'limit': limit
        }
        
        result = self.query(query, variables)
        
        if 'data' in result and 'users' in result['data']:
            return result['data']['users']
        
        logger.warning("未能从 The Graph 获取数据")
        return []
    
    def get_user_positions(self, user_address: str) -> List[Dict]:
        """
        获取用户持仓
        
        Args:
            user_address: 用户地址
            
        Returns:
            持仓列表
        """
        query = """
        query GetUserPositions($userAddress: String!) {
          user(id: $userAddress) {
            id
            address
            positions(where: { shares_gt: 0 }) {
              id
              market {
                id
                question
                description
                outcomes
                volume
                liquidity
              }
              outcome
              shares
              avgPrice
              invested
              currentValue
              unrealizedPnL
              realizedPnL
              trades {
                id
                timestamp
                type
                outcome
                shares
                price
                value
              }
            }
          }
        }
        """
        
        variables = {
            'userAddress': user_address.lower()
        }
        
        result = self.query(query, variables)
        
        if 'data' in result and 'user' in result['data'] and result['data']['user']:
            return result['data']['user']['positions']
        
        return []
    
    def get_user_trades(self, user_address: str, limit: int = 100) -> List[Dict]:
        """
        获取用户交易历史
        
        Args:
            user_address: 用户地址
            limit: 返回数量
            
        Returns:
            交易列表
        """
        query = """
        query GetUserTrades($userAddress: String!, $limit: Int!) {
          trades(
            first: $limit
            orderBy: timestamp
            orderDirection: desc
            where: { user: $userAddress }
          ) {
            id
            timestamp
            user {
              address
            }
            market {
              id
              question
            }
            type
            outcome
            shares
            price
            value
            fee
            transactionHash
          }
        }
        """
        
        variables = {
            'userAddress': user_address.lower(),
            'limit': limit
        }
        
        result = self.query(query, variables)
        
        if 'data' in result and 'trades' in result['data']:
            return result['data']['trades']
        
        return []
    
    def monitor_new_trades(self, since_timestamp: int) -> List[Dict]:
        """
        监控新交易
        
        Args:
            since_timestamp: 起始时间戳
            
        Returns:
            新交易列表
        """
        query = """
        query GetNewTrades($sinceTimestamp: Int!) {
          trades(
            first: 1000
            orderBy: timestamp
            orderDirection: desc
            where: { timestamp_gte: $sinceTimestamp }
          ) {
            id
            timestamp
            user {
              id
              address
            }
            market {
              id
              question
            }
            type
            outcome
            shares
            price
            value
            transactionHash
          }
        }
        """
        
        variables = {
            'sinceTimestamp': since_timestamp
        }
        
        result = self.query(query, variables)
        
        if 'data' in result and 'trades' in result['data']:
            return result['data']['trades']
        
        return []
    
    def get_market_details(self, market_id: str) -> Optional[Dict]:
        """
        获取市场详情
        
        Args:
            market_id: 市场 ID
            
        Returns:
            市场详情
        """
        query = """
        query GetMarket($marketId: String!) {
          market(id: $marketId) {
            id
            question
            description
            outcomes
            outcomeTokens
            volume
            liquidity
            numTrades
            createdAtTimestamp
            endTimestamp
            resolvedAtTimestamp
            resolved
            winner
            currentPrices
            topTraders {
              user {
                address
              }
              volume
              profit
            }
          }
        }
        """
        
        variables = {
            'marketId': market_id
        }
        
        result = self.query(query, variables)
        
        if 'data' in result and 'market' in result['data']:
            return result['data']['market']
        
        return None


def demo_thegraph_usage():
    """演示 The Graph 使用"""
    print("\n" + "="*80)
    print("📊 The Graph Polymarket 数据查询演示")
    print("="*80)
    
    # 创建客户端
    client = PolymarketGraphClient()
    
    print("\n注意：此演示需要有效的 Polymarket subgraph URL")
    print("请查阅 Polymarket 官方文档获取 subgraph 地址\n")
    
    # 示例：获取顶级交易者
    print("1. 获取顶级交易者...")
    top_traders = client.get_top_traders(timeframe=86400, limit=10)
    
    if top_traders:
        print(f"\n找到 {len(top_traders)} 个顶级交易者:")
        for i, trader in enumerate(top_traders[:5], 1):
            print(f"\n{i}. 地址: {trader['address']}")
            print(f"   总交易量: ${trader['totalVolume']:,.2f}")
            print(f"   交易次数: {trader['totalTrades']}")
            print(f"   胜率: {trader['winRate']:.2%}")
    else:
        print("未能获取数据（可能需要配置正确的 subgraph URL）")
    
    # 示例：获取用户持仓
    print("\n2. 获取用户持仓...")
    example_address = "0x1234567890123456789012345678901234567890"
    positions = client.get_user_positions(example_address)
    
    if positions:
        print(f"\n找到 {len(positions)} 个持仓:")
        for pos in positions[:3]:
            print(f"\n  市场: {pos['market']['question']}")
            print(f"  方向: {pos['outcome']}")
            print(f"  份额: {pos['shares']}")
            print(f"  未实现盈亏: ${pos['unrealizedPnL']:,.2f}")
    
    # 示例：监控新交易
    print("\n3. 监控新交易...")
    since_timestamp = int((datetime.now() - timedelta(hours=1)).timestamp())
    new_trades = client.monitor_new_trades(since_timestamp)
    
    if new_trades:
        print(f"\n最近1小时的交易: {len(new_trades)} 笔")
        for trade in new_trades[:5]:
            print(f"\n  交易者: {trade['user']['address']}")
            print(f"  市场: {trade['market']['question'][:60]}...")
            print(f"  类型: {trade['type']}")
            print(f"  金额: ${trade['value']:,.2f}")
    
    print("\n" + "="*80)
    print("演示完成")
    print("="*80 + "\n")


if __name__ == "__main__":
    demo_thegraph_usage()
