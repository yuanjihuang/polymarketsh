"""
Polymarket API Python Client
用于与 Polymarket 预测市场 API 交互的 Python 程序
"""

import requests
import json
from typing import List, Dict, Optional
from datetime import datetime


class PolymarketAPI:
    """Polymarket API 客户端"""
    
    def __init__(self):
        self.base_url = "https://gamma-api.polymarket.com"
        self.clob_url = "https://clob.polymarket.com"
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        })
    
    def get_markets(self, limit: int = 20, offset: int = 0, active: bool = True) -> List[Dict]:
        """
        获取市场列表
        
        Args:
            limit: 返回的市场数量
            offset: 偏移量
            active: 是否只返回活跃市场
            
        Returns:
            市场列表
        """
        try:
            params = {
                'limit': limit,
                'offset': offset
            }
            if active:
                params['active'] = 'true'
            
            response = self.session.get(f"{self.base_url}/markets", params=params)
            response.raise_for_status()
            markets = response.json()
            
            # 格式化市场数据
            formatted_markets = []
            for market in markets:
                formatted_markets.append(self._format_market(market))
            
            return formatted_markets
        
        except requests.exceptions.RequestException as e:
            print(f"获取市场列表失败: {e}")
            return []
    
    def get_market_by_id(self, condition_id: str) -> Optional[Dict]:
        """
        根据 ID 获取单个市场详情
        
        Args:
            condition_id: 市场条件 ID
            
        Returns:
            市场详情字典
        """
        try:
            response = self.session.get(f"{self.base_url}/markets/{condition_id}")
            response.raise_for_status()
            market = response.json()
            return self._format_market(market)
        
        except requests.exceptions.RequestException as e:
            print(f"获取市场详情失败: {e}")
            return None
    
    def search_markets(self, query: str, limit: int = 10) -> List[Dict]:
        """
        搜索市场
        
        Args:
            query: 搜索关键词
            limit: 返回结果数量
            
        Returns:
            匹配的市场列表
        """
        try:
            markets = self.get_markets(limit=100)
            # 简单的关键词匹配
            results = [
                market for market in markets 
                if query.lower() in market['question'].lower()
            ]
            return results[:limit]
        
        except Exception as e:
            print(f"搜索市场失败: {e}")
            return []
    
    def get_market_orderbook(self, token_id: str) -> Optional[Dict]:
        """
        获取市场订单簿
        
        Args:
            token_id: 代币 ID
            
        Returns:
            订单簿数据
        """
        try:
            response = self.session.get(f"{self.clob_url}/book", params={'token_id': token_id})
            response.raise_for_status()
            return response.json()
        
        except requests.exceptions.RequestException as e:
            print(f"获取订单簿失败: {e}")
            return None
    
    def get_market_trades(self, condition_id: str, limit: int = 50) -> List[Dict]:
        """
        获取市场交易历史
        
        Args:
            condition_id: 市场条件 ID
            limit: 返回的交易数量
            
        Returns:
            交易历史列表
        """
        try:
            params = {
                'market': condition_id,
                'limit': limit
            }
            response = self.session.get(f"{self.clob_url}/trades", params=params)
            response.raise_for_status()
            return response.json()
        
        except requests.exceptions.RequestException as e:
            print(f"获取交易历史失败: {e}")
            return []
    
    def _format_market(self, market: Dict) -> Dict:
        """
        格式化市场数据
        
        Args:
            market: 原始市场数据
            
        Returns:
            格式化后的市场数据
        """
        return {
            'id': market.get('condition_id') or market.get('id'),
            'question': market.get('question', ''),
            'description': market.get('description', ''),
            'outcomes': market.get('outcomes', []),
            'outcome_prices': market.get('outcome_prices', []),
            'yes_price': float(market.get('outcome_prices', [0.5, 0.5])[0]),
            'no_price': float(market.get('outcome_prices', [0.5, 0.5])[1]),
            'volume': float(market.get('volume', 0)),
            'liquidity': float(market.get('liquidity', 0)),
            'active': market.get('active', True),
            'closed': market.get('closed', False),
            'end_date': market.get('end_date_iso'),
            'category': market.get('category', ''),
            'market_slug': market.get('market_slug', ''),
            'tokens': market.get('tokens', [])
        }
    
    def print_market_summary(self, market: Dict):
        """打印市场摘要"""
        print("\n" + "="*80)
        print(f"问题: {market['question']}")
        print("="*80)
        if market['description']:
            print(f"描述: {market['description']}")
        print(f"\n当前概率:")
        print(f"  是: {market['yes_price']*100:.1f}%")
        print(f"  否: {market['no_price']*100:.1f}%")
        print(f"\n交易量: ${market['volume']:,.2f}")
        print(f"流动性: ${market['liquidity']:,.2f}")
        print(f"状态: {'已结束' if market['closed'] else '进行中' if market['active'] else '未激活'}")
        if market['end_date']:
            print(f"结束时间: {market['end_date']}")
        if market['category']:
            print(f"类别: {market['category']}")
        print("="*80 + "\n")


def main():
    """主函数 - 演示 API 使用"""
    print("🎯 Polymarket API Python 客户端\n")
    
    # 创建 API 客户端
    api = PolymarketAPI()
    
    # 1. 获取热门市场
    print("📊 获取前 5 个热门市场...\n")
    markets = api.get_markets(limit=5)
    
    if markets:
        print(f"成功获取 {len(markets)} 个市场:\n")
        for i, market in enumerate(markets, 1):
            print(f"{i}. {market['question']}")
            print(f"   是: {market['yes_price']*100:.1f}% | 否: {market['no_price']*100:.1f}%")
            print(f"   交易量: ${market['volume']:,.0f}\n")
    else:
        print("未能获取市场数据")
        return
    
    # 2. 查看第一个市场的详细信息
    if markets:
        first_market = markets[0]
        print("\n" + "🔍 查看第一个市场的详细信息:")
        api.print_market_summary(first_market)
        
        # 获取该市场的详细信息
        market_id = first_market['id']
        detailed_market = api.get_market_by_id(market_id)
        if detailed_market:
            print("✅ 成功获取详细市场数据")
    
    # 3. 搜索特定主题的市场
    print("\n🔎 搜索关键词 'bitcoin' 或 'BTC' 相关的市场...\n")
    search_results = api.search_markets('bitcoin', limit=3)
    
    if search_results:
        print(f"找到 {len(search_results)} 个相关市场:\n")
        for i, market in enumerate(search_results, 1):
            print(f"{i}. {market['question']}")
            print(f"   是: {market['yes_price']*100:.1f}% | 否: {market['no_price']*100:.1f}%\n")
    else:
        print("未找到相关市场\n")
    
    # 4. 获取交易历史（如果有市场 ID）
    if markets and markets[0]['id']:
        print(f"\n📈 获取市场交易历史...\n")
        trades = api.get_market_trades(markets[0]['id'], limit=5)
        if trades:
            print(f"最近 {len(trades)} 笔交易:")
            for trade in trades[:5]:
                print(f"  - {trade}")
        else:
            print("暂无交易历史数据")
    
    print("\n✅ API 调用演示完成!")


if __name__ == "__main__":
    main()
