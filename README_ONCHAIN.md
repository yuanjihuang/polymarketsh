# 方案 A：基于链上数据的 Polymarket 跟单策略

## 📖 概述

这个方案通过直接监听 Polygon 区块链上的交易事件来实现跟单策略，**不依赖** Polymarket 官方 API 的用户数据接口。

### 核心优势

- ✅ **数据真实可靠** - 直接从区块链读取，无法造假
- ✅ **低延迟** - 实时监听新区块，快速响应
- ✅ **无需授权** - 区块链数据公开，不需要特殊权限
- ✅ **完全透明** - 所有交易都在链上可查

### 技术栈

- **Web3.py** - 与 Polygon 区块链交互
- **The Graph** - 索引和查询链上数据（可选）
- **Polygon RPC** - 区块链节点连接

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements_onchain.txt
```

### 2. 配置环境变量

```bash
# 复制配置文件模板
cp .env.example .env

# 编辑 .env 文件，填入你的配置
nano .env
```

关键配置：
- `POLYGON_RPC_URL` - Polygon RPC 节点地址
- `POLYMARKET_SUBGRAPH_URL` - The Graph subgraph 地址（可选）
- `PRIVATE_KEY` - 你的钱包私钥（仅用于执行交易）

### 3. 运行策略

```bash
# 运行基于 Web3 的链上监听
python onchain_copy_trading.py

# 或使用 The Graph（如果有 subgraph）
python thegraph_integration.py
```

## 📊 实现方案详解

### 方案 A-1：直接监听区块链

**原理**：实时监听 Polygon 区块链上的新区块，解析其中的交易。

```python
from web3 import Web3

# 连接到 Polygon
w3 = Web3(Web3.HTTPProvider('https://polygon-rpc.com'))

# 监听新区块
def watch_blocks():
    latest_block = w3.eth.block_number
    while True:
        current_block = w3.eth.block_number
        if current_block > latest_block:
            block = w3.eth.get_block(current_block, full_transactions=True)
            process_block(block)
            latest_block = current_block
        time.sleep(5)
```

**优点**：
- 实时性强，延迟低
- 不依赖第三方服务
- 数据完整

**缺点**：
- 需要自己解析交易数据
- 需要维护 RPC 连接
- 历史数据查询慢

### 方案 A-2：使用 The Graph

**原理**：The Graph 是一个区块链数据索引协议，提供 GraphQL API。

```python
# GraphQL 查询示例
query = """
{
  users(first: 20, orderBy: totalVolume, orderDirection: desc) {
    address
    totalVolume
    positions {
      market { question }
      outcome
      shares
    }
  }
}
"""
```

**优点**：
- 查询速度快
- 提供聚合数据
- 支持复杂查询
- 历史数据完整

**缺点**：
- 需要找到 Polymarket 的 subgraph
- 可能有轻微延迟（通常 < 1 分钟）
- 依赖第三方服务

## 🔍 关键技术点

### 1. 如何识别 Polymarket 交易？

```python
# Polymarket 使用 CTF Exchange 合约
EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

# 检查交易是否与 Polymarket 相关
if tx['to'] == EXCHANGE_ADDRESS:
    # 这是一笔 Polymarket 交易
    process_polymarket_tx(tx)
```

### 2. 如何解析交易内容？

```python
# 方法 1：通过 ABI 解析
contract = w3.eth.contract(address=EXCHANGE_ADDRESS, abi=EXCHANGE_ABI)
decoded = contract.decode_function_input(tx['input'])

# 方法 2：解析事件日志
receipt = w3.eth.get_transaction_receipt(tx_hash)
for log in receipt['logs']:
    if log['address'] == EXCHANGE_ADDRESS:
        decoded_log = decode_log(log)
```

### 3. 如何识别顶级交易者？

```python
# 统计最近 24 小时的交易
trader_stats = {}

for tx in recent_transactions:
    trader = tx['from']
    trader_stats[trader] = {
        'volume': trader_stats.get(trader, {}).get('volume', 0) + tx['value'],
        'count': trader_stats.get(trader, {}).get('count', 0) + 1
    }

# 按交易量排序
top_traders = sorted(trader_stats.items(), key=lambda x: x[1]['volume'], reverse=True)
```

### 4. 如何监听特定地址？

```python
# 方法 1：过滤区块中的交易
for tx in block['transactions']:
    if tx['from'] in tracked_addresses:
        handle_tracked_transaction(tx)

# 方法 2：使用事件过滤器（更高效）
event_filter = contract.events.OrderFilled.create_filter(
    fromBlock='latest',
    argument_filters={'maker': tracked_addresses}
)

for event in event_filter.get_all_entries():
    handle_event(event)
```

## 🛠️ 实际部署步骤

### 步骤 1：选择 RPC 节点

**免费选项**（适合测试）：
```
https://polygon-rpc.com
https://rpc-mainnet.matic.network
```

**付费选项**（推荐生产环境）：
- **Infura** - 稳定，有免费额度
- **Alchemy** - 功能丰富，开发体验好
- **QuickNode** - 高性能

### 步骤 2：获取 Polymarket Subgraph

1. 访问 [The Graph Explorer](https://thegraph.com/explorer)
2. 搜索 "Polymarket"
3. 找到官方或社区维护的 subgraph
4. 复制 Query URL

或者查阅 [Polymarket 文档](https://docs.polymarket.com)

### 步骤 3：分析历史数据

```bash
# 运行分析脚本，找出顶级交易者
python onchain_copy_trading.py
```

输出示例：
```
📊 顶级交易者前 10 名:
1. 0xabc... - 交易量: $125,000 - 胜率: 68%
2. 0xdef... - 交易量: $98,500 - 胜率: 72%
...
```

### 步骤 4：开始监听

```python
# 添加要跟踪的地址
strategy.tracked_addresses = {
    '0xabc...',
    '0xdef...',
    # ...
}

# 开始实时监听
strategy.watch_new_blocks()
```

### 步骤 5：模拟交易

先在模拟模式下运行，验证策略：
```python
strategy.run_strategy(duration_hours=24, dry_run=True)
```

### 步骤 6：小额实盘

确认策略可行后，使用小额资金测试：
```python
# 配置钱包
strategy.setup_wallet(private_key=YOUR_PRIVATE_KEY)

# 开始真实交易（小额）
strategy.run_strategy(dry_run=False, max_position_size=100)
```

## 📈 性能优化

### 1. 使用 WebSocket 代替轮询

```python
from web3.providers import WebsocketProvider

w3 = Web3(WebsocketProvider('wss://polygon-rpc.com'))

# 订阅新区块头
def handle_event(event):
    block = w3.eth.get_block(event['number'], full_transactions=True)
    process_block(block)

# 使用异步处理
w3.eth.subscribe('newBlockHeaders', handle_event)
```

### 2. 批量查询历史数据

```python
# 使用 batch requests
batch = w3.batch_requests()
for i in range(start_block, end_block):
    batch.add(w3.eth.get_block, i, True)

blocks = batch.execute()
```

### 3. 缓存数据

```python
import redis

# 缓存交易者统计
cache = redis.Redis(host='localhost', port=6379)
cache.setex(f'trader:{address}', 3600, json.dumps(stats))
```

## ⚠️ 风险提示

1. **Gas 费用**
   - Polygon 上 gas 费较低，但仍需考虑
   - 设置合理的 gas price 上限

2. **RPC 限制**
   - 免费 RPC 有速率限制
   - 建议使用付费服务或自建节点

3. **数据延迟**
   - 区块确认需要时间（~2秒）
   - 价格可能已经变化

4. **交易失败**
   - 可能因为 gas 不足
   - 可能因为流动性不足
   - 可能因为价格变化过大

5. **私钥安全**
   - 永远不要泄露私钥
   - 使用硬件钱包或 HSM
   - 只存储必要的资金

## 🔧 故障排除

### 问题 1：无法连接到 RPC

**解决方案**：
```python
# 尝试不同的 RPC 节点
rpc_urls = [
    'https://polygon-rpc.com',
    'https://rpc-mainnet.matic.network',
    'https://matic-mainnet.chainstacklabs.com'
]

for url in rpc_urls:
    try:
        w3 = Web3(Web3.HTTPProvider(url))
        if w3.is_connected():
            print(f"✅ 连接成功: {url}")
            break
    except:
        continue
```

### 问题 2：找不到 Polymarket subgraph

**解决方案**：
1. 访问 Polymarket 社区论坛
2. 查看 GitHub 仓库
3. 使用直接的链上查询（虽然慢一些）
4. 自己创建 subgraph

### 问题 3：交易失败

**解决方案**：
```python
# 添加重试逻辑
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def send_transaction(tx):
    return w3.eth.send_transaction(tx)
```

## 📚 相关资源

- [Web3.py 文档](https://web3py.readthedocs.io/)
- [The Graph 文档](https://thegraph.com/docs/)
- [Polygon 文档](https://docs.polygon.technology/)
- [Polymarket 文档](https://docs.polymarket.com/)
- [Etherscan Polygon](https://polygonscan.com/)

## 💡 下一步

1. **获取真实的 subgraph URL**
2. **测试不同的 RPC 节点，选择最快的**
3. **分析历史数据，验证顶级交易者的持续性**
4. **在测试网上验证策略**
5. **小额实盘测试**
6. **持续监控和优化**

## 📞 支持

如果遇到问题，可以：
1. 查看日志文件
2. 检查区块浏览器上的交易
3. 参考 Polymarket 社区讨论
4. 审查代码中的错误处理逻辑

---

**免责声明**：本软件仅供学习和研究使用。交易有风险，投资需谨慎。
