"""
Polymarket 跟单套利策略
策略：跟踪高收益用户的持仓变化并跟单

注意：这是概念验证代码，实际使用需要：
1. 验证 Polymarket API 是否支持用户数据查询
2. 实现钱包认证和交易功能
3. 充分的风险管理和资金管理
4. 合法合规的使用
"""

import requests
import time
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from collections import defaultdict
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PolymarketCopyTrading:
    """Polymarket 跟单交易策略"""
    
    def __init__(self, 
                 check_interval: int = 300,  # 检查间隔（秒）
                 top_traders_count: int = 20,  # 跟踪的顶级交易者数量
                 min_position_size: float = 100,  # 最小持仓金额（美元）
                 copy_percentage: float = 0.1):  # 跟单比例（10%）
        
        self.base_url = "https://gamma-api.polymarket.com"
        self.clob_url = "https://clob.polymarket.com"
        self.check_interval = check_interval
        self.top_traders_count = top_traders_count
        self.min_position_size = min_position_size
        self.copy_percentage = copy_percentage
        
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        })
        
        # 存储跟踪的交易者信息
        self.tracked_traders: Dict[str, Dict] = {}
        self.previous_positions: Dict[str, Set[str]] = defaultdict(set)
        self.trade_history: List[Dict] = []
        
    def get_top_profitable_traders(self, timeframe: str = '24h') -> List[Dict]:
        """
        获取最高收益的交易者
        
        注意：这个功能需要 Polymarket API 支持，可能需要：
        1. 专业版 API 访问权限
        2. 链上数据分析
        3. 第三方数据聚合服务
        
        Args:
            timeframe: 时间范围 ('24h', '7d', '30d')
            
        Returns:
            交易者列表，按收益排序
        """
        try:
            # 尝试从 API 获取（这个端点可能不存在，需要验证）
            response = self.session.get(
                f"{self.base_url}/leaderboard",
                params={'timeframe': timeframe, 'limit': self.top_traders_count}
            )
            
            if response.status_code == 200:
                traders = response.json()
                logger.info(f"成功获取 {len(traders)} 个顶级交易者")
                return traders
            else:
                logger.warning(f"API 返回状态码: {response.status_code}")
                # 使用模拟数据进行测试
                return self._get_mock_top_traders()
                
        except requests.exceptions.RequestException as e:
            logger.error(f"获取顶级交易者失败: {e}")
            # 返回模拟数据用于测试
            return self._get_mock_top_traders()
    
    def _get_mock_top_traders(self) -> List[Dict]:
        """生成模拟的顶级交易者数据（用于测试）"""
        import random
        
        mock_traders = []
        for i in range(self.top_traders_count):
            mock_traders.append({
                'user_id': f"0x{''.join(random.choices('0123456789abcdef', k=40))}",
                'username': f"Trader_{i+1}",
                'profit_24h': random.uniform(1000, 50000),
                'profit_percentage': random.uniform(5, 150),
                'total_volume': random.uniform(10000, 500000),
                'win_rate': random.uniform(0.55, 0.85),
                'active_positions': random.randint(3, 15)
            })
        
        # 按收益排序
        mock_traders.sort(key=lambda x: x['profit_24h'], reverse=True)
        return mock_traders
    
    def get_user_positions(self, user_id: str) -> List[Dict]:
        """
        获取用户的当前持仓
        
        注意：需要验证 API 是否支持查询其他用户的持仓
        可能的方案：
        1. 如果 API 不支持，可以通过区块链浏览器查询
        2. 使用 The Graph 等链上数据服务
        3. 监听链上事件
        
        Args:
            user_id: 用户地址或 ID
            
        Returns:
            用户持仓列表
        """
        try:
            # 尝试从 API 获取（这个端点可能需要认证或不存在）
            response = self.session.get(
                f"{self.base_url}/users/{user_id}/positions"
            )
            
            if response.status_code == 200:
                positions = response.json()
                logger.info(f"获取用户 {user_id[:10]}... 的 {len(positions)} 个持仓")
                return positions
            else:
                logger.debug(f"无法获取用户持仓，状态码: {response.status_code}")
                # 返回模拟数据
                return self._get_mock_positions(user_id)
                
        except requests.exceptions.RequestException as e:
            logger.error(f"获取用户持仓失败: {e}")
            return []
    
    def _get_mock_positions(self, user_id: str) -> List[Dict]:
        """生成模拟持仓数据（用于测试）"""
        import random
        
        # 获取一些真实市场
        markets_response = self.session.get(
            f"{self.base_url}/markets",
            params={'limit': 50, 'active': True}
        )
        
        if markets_response.status_code == 200:
            markets = markets_response.json()[:10]
        else:
            markets = []
        
        positions = []
        num_positions = random.randint(2, 8)
        
        for _ in range(num_positions):
            if markets:
                market = random.choice(markets)
                condition_id = market.get('condition_id') or market.get('id')
                question = market.get('question', 'Unknown Market')
            else:
                condition_id = f"mock_market_{random.randint(1, 100)}"
                question = f"Mock Market Question {random.randint(1, 100)}"
            
            positions.append({
                'market_id': condition_id,
                'question': question,
                'outcome': random.choice(['YES', 'NO']),
                'shares': random.uniform(100, 5000),
                'avg_price': random.uniform(0.3, 0.7),
                'current_price': random.uniform(0.3, 0.7),
                'unrealized_pnl': random.uniform(-500, 2000),
                'timestamp': datetime.now().isoformat()
            })
        
        return positions
    
    def detect_position_changes(self, user_id: str, 
                               current_positions: List[Dict]) -> List[Dict]:
        """
        检测持仓变化
        
        Args:
            user_id: 用户 ID
            current_positions: 当前持仓
            
        Returns:
            新开仓的持仓列表
        """
        current_market_ids = {pos['market_id'] for pos in current_positions}
        previous_market_ids = self.previous_positions.get(user_id, set())
        
        # 找出新增的持仓
        new_positions = current_market_ids - previous_market_ids
        
        # 更新记录
        self.previous_positions[user_id] = current_market_ids
        
        if new_positions:
            new_position_details = [
                pos for pos in current_positions 
                if pos['market_id'] in new_positions
            ]
            logger.info(f"用户 {user_id[:10]}... 新增 {len(new_positions)} 个持仓")
            return new_position_details
        
        return []
    
    def should_copy_trade(self, position: Dict, trader_info: Dict) -> bool:
        """
        判断是否应该跟单
        
        Args:
            position: 持仓信息
            trader_info: 交易者信息
            
        Returns:
            是否跟单
        """
        # 检查持仓大小
        position_value = position.get('shares', 0) * position.get('avg_price', 0)
        if position_value < self.min_position_size:
            logger.debug(f"持仓金额太小，跳过: ${position_value:.2f}")
            return False
        
        # 检查交易者胜率
        if trader_info.get('win_rate', 0) < 0.6:
            logger.debug(f"交易者胜率过低，跳过: {trader_info.get('win_rate', 0):.2%}")
            return False
        
        # 可以添加更多过滤条件：
        # - 市场流动性检查
        # - 价格合理性检查
        # - 风险敞口限制
        # - 市场类别偏好
        
        return True
    
    def execute_copy_trade(self, position: Dict, trader_info: Dict) -> bool:
        """
        执行跟单交易
        
        注意：这需要：
        1. 钱包认证
        2. USDC 余额
        3. 交易签名
        4. Gas 费用
        
        Args:
            position: 要复制的持仓
            trader_info: 交易者信息
            
        Returns:
            是否执行成功
        """
        try:
            # 计算跟单金额
            original_amount = position.get('shares', 0) * position.get('avg_price', 0)
            copy_amount = original_amount * self.copy_percentage
            
            trade_info = {
                'timestamp': datetime.now().isoformat(),
                'trader_id': trader_info['user_id'],
                'trader_username': trader_info.get('username', 'Unknown'),
                'market_id': position['market_id'],
                'question': position.get('question', 'Unknown'),
                'outcome': position['outcome'],
                'original_amount': original_amount,
                'copy_amount': copy_amount,
                'price': position.get('avg_price', 0),
                'status': 'pending'
            }
            
            logger.info(f"🎯 跟单信号:")
            logger.info(f"   交易者: {trade_info['trader_username']}")
            logger.info(f"   市场: {trade_info['question'][:60]}...")
            logger.info(f"   方向: {trade_info['outcome']}")
            logger.info(f"   金额: ${copy_amount:.2f} (原始: ${original_amount:.2f})")
            logger.info(f"   价格: {trade_info['price']:.4f}")
            
            # 实际交易逻辑（需要实现）
            # success = self._place_order(
            #     market_id=position['market_id'],
            #     outcome=position['outcome'],
            #     amount=copy_amount,
            #     price=position.get('current_price')
            # )
            
            # 模拟交易成功
            success = True
            trade_info['status'] = 'executed' if success else 'failed'
            
            # 记录交易历史
            self.trade_history.append(trade_info)
            
            # 保存到文件
            self._save_trade_history()
            
            return success
            
        except Exception as e:
            logger.error(f"执行跟单失败: {e}")
            return False
    
    def _save_trade_history(self):
        """保存交易历史到文件"""
        try:
            filename = f"copy_trade_history_{datetime.now().strftime('%Y%m%d')}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.trade_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存交易历史失败: {e}")
    
    def run_strategy(self, duration_hours: int = 24, dry_run: bool = True):
        """
        运行跟单策略
        
        Args:
            duration_hours: 运行时长（小时）
            dry_run: 是否为模拟运行（不执行实际交易）
        """
        logger.info("="*80)
        logger.info("🚀 启动 Polymarket 跟单策略")
        logger.info("="*80)
        logger.info(f"跟踪交易者数量: {self.top_traders_count}")
        logger.info(f"检查间隔: {self.check_interval} 秒")
        logger.info(f"跟单比例: {self.copy_percentage*100}%")
        logger.info(f"最小持仓: ${self.min_position_size}")
        logger.info(f"模拟运行: {'是' if dry_run else '否'}")
        logger.info(f"运行时长: {duration_hours} 小时")
        logger.info("="*80)
        
        if not dry_run:
            logger.warning("⚠️  警告：即将执行真实交易！")
            response = input("确认继续？(yes/no): ")
            if response.lower() != 'yes':
                logger.info("用户取消操作")
                return
        
        start_time = datetime.now()
        end_time = start_time + timedelta(hours=duration_hours)
        iteration = 0
        
        try:
            while datetime.now() < end_time:
                iteration += 1
                logger.info(f"\n{'='*80}")
                logger.info(f"第 {iteration} 轮检查 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"{'='*80}")
                
                # 1. 获取顶级交易者
                top_traders = self.get_top_profitable_traders()
                
                if not top_traders:
                    logger.warning("未能获取交易者数据，等待下一轮...")
                    time.sleep(self.check_interval)
                    continue
                
                # 2. 检查每个交易者的持仓
                for trader in top_traders[:5]:  # 只展示前5个
                    logger.info(f"\n📊 交易者: {trader.get('username', 'Unknown')}")
                    logger.info(f"   24h收益: ${trader.get('profit_24h', 0):,.2f}")
                    logger.info(f"   胜率: {trader.get('win_rate', 0):.2%}")
                
                # 3. 检测持仓变化并跟单
                copy_trade_count = 0
                
                for trader in top_traders:
                    user_id = trader['user_id']
                    
                    # 获取当前持仓
                    current_positions = self.get_user_positions(user_id)
                    
                    if not current_positions:
                        continue
                    
                    # 检测新持仓
                    new_positions = self.detect_position_changes(user_id, current_positions)
                    
                    # 对新持仓执行跟单
                    for position in new_positions:
                        if self.should_copy_trade(position, trader):
                            if not dry_run:
                                success = self.execute_copy_trade(position, trader)
                                if success:
                                    copy_trade_count += 1
                            else:
                                logger.info(f"[模拟] 跟单: {position.get('question', 'Unknown')[:50]}...")
                                copy_trade_count += 1
                
                # 4. 统计信息
                logger.info(f"\n📈 本轮统计:")
                logger.info(f"   跟单数量: {copy_trade_count}")
                logger.info(f"   总交易数: {len(self.trade_history)}")
                
                # 5. 等待下一轮
                remaining_time = (end_time - datetime.now()).total_seconds()
                if remaining_time > 0:
                    wait_time = min(self.check_interval, remaining_time)
                    logger.info(f"\n⏳ 等待 {wait_time:.0f} 秒后进行下一轮检查...")
                    time.sleep(wait_time)
        
        except KeyboardInterrupt:
            logger.info("\n\n⚠️  用户中断程序")
        
        finally:
            # 生成报告
            self.generate_report()
    
    def generate_report(self):
        """生成策略运行报告"""
        logger.info("\n" + "="*80)
        logger.info("📊 策略运行报告")
        logger.info("="*80)
        
        if not self.trade_history:
            logger.info("没有执行任何交易")
            return
        
        total_trades = len(self.trade_history)
        total_amount = sum(t['copy_amount'] for t in self.trade_history)
        
        # 按交易者统计
        trader_stats = defaultdict(lambda: {'count': 0, 'amount': 0})
        for trade in self.trade_history:
            trader_id = trade['trader_username']
            trader_stats[trader_id]['count'] += 1
            trader_stats[trader_id]['amount'] += trade['copy_amount']
        
        logger.info(f"\n总交易数: {total_trades}")
        logger.info(f"总投入金额: ${total_amount:,.2f}")
        logger.info(f"平均每笔金额: ${total_amount/total_trades:,.2f}" if total_trades > 0 else "")
        
        logger.info(f"\n跟单交易者分布:")
        for trader, stats in sorted(trader_stats.items(), 
                                    key=lambda x: x[1]['count'], 
                                    reverse=True)[:10]:
            logger.info(f"  {trader}: {stats['count']} 笔, ${stats['amount']:,.2f}")
        
        logger.info("\n" + "="*80)
        logger.info(f"详细历史已保存到: copy_trade_history_*.json")
        logger.info("="*80 + "\n")


def main():
    """主函数"""
    print("\n" + "🎯 Polymarket 跟单套利策略")
    print("="*80)
    
    # 创建策略实例
    strategy = PolymarketCopyTrading(
        check_interval=60,  # 每分钟检查一次（测试用）
        top_traders_count=20,
        min_position_size=100,
        copy_percentage=0.1
    )
    
    # 运行策略（模拟模式）
    strategy.run_strategy(
        duration_hours=1,  # 运行1小时（测试用）
        dry_run=True  # 模拟运行，不执行真实交易
    )


if __name__ == "__main__":
    main()
