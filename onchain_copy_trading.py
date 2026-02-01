"""
基于链上数据的 Polymarket 跟单策略
使用 Web3.py 监听 Polygon 区块链上的交易事件
"""

from web3 import Web3
from web3.middleware import geth_poa_middleware
import json
import time
import requests
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


class OnChainCopyTrading:
    """基于链上数据的跟单交易系统"""
    
    def __init__(self, 
                 rpc_url: str = "https://polygon-rpc.com",
                 check_interval: int = 5,  # 检查新区块的间隔（秒）
                 min_trade_value: float = 100):  # 最小跟单金额（USDC）
        
        # Web3 连接
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        
        if not self.w3.is_connected():
            logger.error("❌ 无法连接到 Polygon RPC")
            raise ConnectionError("Web3 connection failed")
        
        logger.info(f"✅ 已连接到 Polygon，当前区块: {self.w3.eth.block_number}")
        
        # Polymarket 合约地址（需要根据实际情况更新）
        # CTF Exchange 合约地址
        self.exchange_address = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
        
        # USDC 合约地址（Polygon）
        self.usdc_address = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
        
        # 跟踪的顶级交易者地址
        self.tracked_addresses: Set[str] = set()
        
        # 交易历史
        self.trade_history: List[Dict] = []
        self.user_trades: Dict[str, List[Dict]] = defaultdict(list)
        self.user_pnl: Dict[str, float] = defaultdict(float)
        
        # 配置参数
        self.check_interval = check_interval
        self.min_trade_value = min_trade_value
        
        # 最后处理的区块
        self.last_processed_block = self.w3.eth.block_number
        
        # 加载 ABI
        self.exchange_abi = self._load_exchange_abi()
        self.erc20_abi = self._load_erc20_abi()
        
        # 创建合约实例
        if self.exchange_abi:
            self.exchange_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(self.exchange_address),
                abi=self.exchange_abi
            )
        else:
            logger.warning("未加载交易所 ABI，将使用日志解析")
            self.exchange_contract = None
    
    def _load_exchange_abi(self) -> Optional[List]:
        """
        加载 Polymarket Exchange 合约 ABI
        可以从 Polygonscan 或 Polymarket 文档获取
        """
        # 简化的 ABI，包含主要事件
        # 实际使用时应该从 Etherscan/Polygonscan 获取完整 ABI
        abi = [
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "maker", "type": "address"},
                    {"indexed": True, "name": "taker", "type": "address"},
                    {"indexed": False, "name": "tokenId", "type": "uint256"},
                    {"indexed": False, "name": "makerAmount", "type": "uint256"},
                    {"indexed": False, "name": "takerAmount", "type": "uint256"}
                ],
                "name": "OrderFilled",
                "type": "event"
            },
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "from", "type": "address"},
                    {"indexed": True, "name": "to", "type": "address"},
                    {"indexed": True, "name": "tokenId", "type": "uint256"},
                    {"indexed": False, "name": "value", "type": "uint256"}
                ],
                "name": "TransferSingle",
                "type": "event"
            }
        ]
        return abi
    
    def _load_erc20_abi(self) -> List:
        """加载 ERC20 标准 ABI"""
        return [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            },
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "from", "type": "address"},
                    {"indexed": True, "name": "to", "type": "address"},
                    {"indexed": False, "name": "value", "type": "uint256"}
                ],
                "name": "Transfer",
                "type": "event"
            }
        ]
    
    def get_top_traders_from_chain(self, 
                                   lookback_blocks: int = 43200) -> List[Dict]:
        """
        从链上分析最近的顶级交易者
        
        Args:
            lookback_blocks: 回溯的区块数（43200 blocks ≈ 24小时）
            
        Returns:
            顶级交易者列表
        """
        logger.info(f"🔍 分析最近 {lookback_blocks} 个区块的交易数据...")
        
        current_block = self.w3.eth.block_number
        from_block = max(0, current_block - lookback_blocks)
        
        # 存储交易者统计
        trader_stats = defaultdict(lambda: {
            'total_volume': 0,
            'trade_count': 0,
            'tokens_traded': set(),
            'recent_trades': []
        })
        
        # 分批查询事件（避免超时）
        batch_size = 2000
        
        try:
            for start in range(from_block, current_block, batch_size):
                end = min(start + batch_size, current_block)
                
                logger.info(f"  处理区块 {start} 到 {end}...")
                
                # 查询 Transfer 事件（ERC1155 代币转移）
                filter_params = {
                    'fromBlock': start,
                    'toBlock': end,
                    'address': Web3.to_checksum_address(self.exchange_address)
                }
                
                logs = self.w3.eth.get_logs(filter_params)
                
                for log in logs:
                    try:
                        # 解析交易数据
                        tx_hash = log['transactionHash'].hex()
                        block_number = log['blockNumber']
                        
                        # 获取交易详情
                        tx = self.w3.eth.get_transaction(log['transactionHash'])
                        
                        if tx:
                            trader = tx['from']
                            value = tx.get('value', 0)
                            
                            # 更新统计
                            trader_stats[trader]['total_volume'] += value
                            trader_stats[trader]['trade_count'] += 1
                            trader_stats[trader]['recent_trades'].append({
                                'tx_hash': tx_hash,
                                'block': block_number,
                                'value': value,
                                'timestamp': self._get_block_timestamp(block_number)
                            })
                    
                    except Exception as e:
                        logger.debug(f"解析日志失败: {e}")
                        continue
                
                # 避免 RPC 速率限制
                time.sleep(0.1)
        
        except Exception as e:
            logger.error(f"查询链上数据失败: {e}")
            logger.info("使用模拟数据...")
            return self._get_mock_top_traders()
        
        # 转换为列表并排序
        top_traders = []
        for address, stats in trader_stats.items():
            if stats['trade_count'] >= 5:  # 至少5笔交易
                top_traders.append({
                    'address': address,
                    'total_volume': stats['total_volume'],
                    'trade_count': stats['trade_count'],
                    'avg_trade_size': stats['total_volume'] / stats['trade_count'],
                    'tokens_count': len(stats['tokens_traded']),
                    'recent_trades': stats['recent_trades'][-10:]
                })
        
        # 按交易量排序
        top_traders.sort(key=lambda x: x['total_volume'], reverse=True)
        
        logger.info(f"✅ 找到 {len(top_traders)} 个活跃交易者")
        
        return top_traders[:20]
    
    def _get_mock_top_traders(self) -> List[Dict]:
        """生成模拟的顶级交易者（用于测试）"""
        import random
        
        mock_traders = []
        for i in range(20):
            address = f"0x{''.join(random.choices('0123456789abcdef', k=40))}"
            mock_traders.append({
                'address': address,
                'total_volume': random.uniform(10000, 100000),
                'trade_count': random.randint(10, 100),
                'avg_trade_size': random.uniform(100, 5000),
                'tokens_count': random.randint(5, 20),
                'recent_trades': []
            })
        
        mock_traders.sort(key=lambda x: x['total_volume'], reverse=True)
        return mock_traders
    
    def _get_block_timestamp(self, block_number: int) -> str:
        """获取区块时间戳"""
        try:
            block = self.w3.eth.get_block(block_number)
            return datetime.fromtimestamp(block['timestamp']).isoformat()
        except:
            return datetime.now().isoformat()
    
    def monitor_address_transactions(self, 
                                    address: str, 
                                    from_block: int,
                                    to_block: int = None) -> List[Dict]:
        """
        监控特定地址的交易
        
        Args:
            address: 要监控的地址
            from_block: 起始区块
            to_block: 结束区块（None 表示最新）
            
        Returns:
            交易列表
        """
        if to_block is None:
            to_block = self.w3.eth.block_number
        
        address = Web3.to_checksum_address(address)
        transactions = []
        
        try:
            # 查询该地址相关的所有日志
            logs = self.w3.eth.get_logs({
                'fromBlock': from_block,
                'toBlock': to_block
            })
            
            for log in logs:
                tx = self.w3.eth.get_transaction(log['transactionHash'])
                
                if tx and (tx['from'] == address or tx['to'] == address):
                    transactions.append({
                        'hash': tx['hash'].hex(),
                        'from': tx['from'],
                        'to': tx['to'],
                        'value': tx['value'],
                        'block': tx['blockNumber'],
                        'timestamp': self._get_block_timestamp(tx['blockNumber'])
                    })
        
        except Exception as e:
            logger.error(f"监控地址交易失败: {e}")
        
        return transactions
    
    def watch_new_blocks(self, callback):
        """
        实时监听新区块
        
        Args:
            callback: 处理新区块的回调函数
        """
        logger.info("🔄 开始监听新区块...")
        
        while True:
            try:
                current_block = self.w3.eth.block_number
                
                if current_block > self.last_processed_block:
                    # 处理所有未处理的区块
                    for block_num in range(self.last_processed_block + 1, current_block + 1):
                        block = self.w3.eth.get_block(block_num, full_transactions=True)
                        callback(block)
                        self.last_processed_block = block_num
                
                time.sleep(self.check_interval)
            
            except KeyboardInterrupt:
                logger.info("\n⚠️  停止监听")
                break
            except Exception as e:
                logger.error(f"监听区块失败: {e}")
                time.sleep(self.check_interval)
    
    def process_block(self, block):
        """
        处理新区块，检测跟踪地址的交易
        
        Args:
            block: 区块数据
        """
        block_number = block['number']
        timestamp = datetime.fromtimestamp(block['timestamp'])
        
        logger.info(f"📦 处理区块 {block_number} (交易数: {len(block['transactions'])})")
        
        for tx in block['transactions']:
            try:
                # 检查是否是跟踪的地址
                if tx['from'] in self.tracked_addresses:
                    self._handle_tracked_transaction(tx, block_number, timestamp)
            
            except Exception as e:
                logger.debug(f"处理交易失败: {e}")
    
    def _handle_tracked_transaction(self, tx, block_number: int, timestamp: datetime):
        """
        处理跟踪地址的交易
        
        Args:
            tx: 交易数据
            block_number: 区块号
            timestamp: 时间戳
        """
        trader_address = tx['from']
        
        # 判断是否是 Polymarket 相关交易
        if tx['to'] and tx['to'].lower() == self.exchange_address.lower():
            trade_info = {
                'timestamp': timestamp.isoformat(),
                'block': block_number,
                'tx_hash': tx['hash'].hex(),
                'trader': trader_address,
                'value': self.w3.from_wei(tx['value'], 'ether'),
                'gas_price': tx['gasPrice']
            }
            
            logger.info(f"🎯 检测到跟踪地址的交易:")
            logger.info(f"   交易者: {trader_address[:10]}...")
            logger.info(f"   金额: {trade_info['value']} MATIC")
            logger.info(f"   区块: {block_number}")
            
            # 分析交易详情
            self._analyze_and_copy_trade(trade_info)
    
    def _analyze_and_copy_trade(self, trade_info: Dict):
        """
        分析交易并决定是否跟单
        
        Args:
            trade_info: 交易信息
        """
        # 获取交易收据以获取更多信息
        try:
            receipt = self.w3.eth.get_transaction_receipt(trade_info['tx_hash'])
            
            # 解析日志获取具体的交易细节
            for log in receipt['logs']:
                # 这里需要根据实际的事件 ABI 解析
                # 获取：买入/卖出、代币ID、数量等
                pass
            
            # 判断是否跟单
            if self._should_copy_trade(trade_info):
                logger.info(f"✅ 决定跟单此交易")
                self._execute_copy_trade(trade_info)
            else:
                logger.debug(f"⏭️  跳过此交易")
        
        except Exception as e:
            logger.error(f"分析交易失败: {e}")
    
    def _should_copy_trade(self, trade_info: Dict) -> bool:
        """判断是否应该跟单"""
        # 检查交易金额
        if trade_info['value'] < self.min_trade_value:
            return False
        
        # 可以添加更多过滤条件
        return True
    
    def _execute_copy_trade(self, trade_info: Dict):
        """
        执行跟单交易
        
        注意：实际实现需要：
        1. 私钥管理
        2. 交易签名
        3. Gas 估算
        4. 交易发送
        """
        logger.warning("⚠️  跟单功能需要实现钱包签名和交易发送")
        
        # 记录到历史
        self.trade_history.append({
            **trade_info,
            'copy_status': 'simulated',
            'copy_amount': trade_info['value'] * 0.1  # 10% 跟单
        })
    
    def run_strategy(self, duration_hours: int = 24):
        """
        运行链上跟单策略
        
        Args:
            duration_hours: 运行时长（小时）
        """
        logger.info("="*80)
        logger.info("🚀 启动链上跟单策略")
        logger.info("="*80)
        logger.info(f"RPC 节点: {self.w3.provider.endpoint_uri}")
        logger.info(f"当前区块: {self.w3.eth.block_number}")
        logger.info(f"监听间隔: {self.check_interval} 秒")
        logger.info("="*80)
        
        # 1. 分析并选择顶级交易者
        logger.info("\n步骤 1: 分析顶级交易者...")
        top_traders = self.get_top_traders_from_chain(lookback_blocks=10000)
        
        if top_traders:
            logger.info(f"\n📊 顶级交易者前 5 名:")
            for i, trader in enumerate(top_traders[:5], 1):
                logger.info(f"{i}. {trader['address']}")
                logger.info(f"   交易量: {trader['total_volume']:.2f}")
                logger.info(f"   交易次数: {trader['trade_count']}")
            
            # 选择要跟踪的地址
            self.tracked_addresses = {t['address'] for t in top_traders[:10]}
            logger.info(f"\n✅ 开始跟踪 {len(self.tracked_addresses)} 个地址")
        else:
            logger.warning("未找到交易者，使用演示模式")
        
        # 2. 开始监听新区块
        logger.info("\n步骤 2: 开始监听链上交易...")
        
        try:
            self.watch_new_blocks(self.process_block)
        except KeyboardInterrupt:
            logger.info("\n用户中断")
        finally:
            self._generate_report()
    
    def _generate_report(self):
        """生成报告"""
        logger.info("\n" + "="*80)
        logger.info("📊 策略运行报告")
        logger.info("="*80)
        logger.info(f"跟踪地址数: {len(self.tracked_addresses)}")
        logger.info(f"检测到的交易数: {len(self.trade_history)}")
        logger.info("="*80 + "\n")


def main():
    """主函数"""
    print("\n🔗 基于链上数据的 Polymarket 跟单策略")
    print("="*80)
    
    # RPC 节点选择
    rpc_options = {
        '1': 'https://polygon-rpc.com',
        '2': 'https://rpc-mainnet.matic.network',
        '3': 'https://rpc-mainnet.maticvigil.com',
        '4': 'https://matic-mainnet.chainstacklabs.com'
    }
    
    print("\n选择 RPC 节点:")
    for key, url in rpc_options.items():
        print(f"  {key}. {url}")
    
    choice = input("\n请选择 (1-4，默认 1): ").strip() or '1'
    rpc_url = rpc_options.get(choice, rpc_options['1'])
    
    print(f"\n使用 RPC: {rpc_url}")
    print("\n初始化中...")
    
    try:
        # 创建策略实例
        strategy = OnChainCopyTrading(
            rpc_url=rpc_url,
            check_interval=5,  # 5秒检查一次
            min_trade_value=100
        )
        
        # 运行策略
        strategy.run_strategy(duration_hours=1)
    
    except Exception as e:
        logger.error(f"❌ 策略运行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
