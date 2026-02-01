# Polymarket API Python 客户端

这是一个用于与 Polymarket 预测市场 API 交互的 Python 程序。

## 功能特性

- ✅ 获取市场列表
- ✅ 搜索特定市场
- ✅ 获取市场详细信息
- ✅ 查询订单簿数据
- ✅ 获取交易历史
- ✅ 市场数据分析
- ✅ 导出数据到 JSON

## 安装依赖

```bash
pip install -r requirements.txt
```

或者直接安装：

```bash
pip install requests
```

## 快速开始

### 1. 基本使用

```python
from polymarket_api import PolymarketAPI

# 创建 API 客户端
api = PolymarketAPI()

# 获取市场列表
markets = api.get_markets(limit=10)

# 打印市场信息
for market in markets:
    print(f"问题: {market['question']}")
    print(f"是的概率: {market['yes_price']*100:.1f}%")
    print(f"交易量: ${market['volume']:,.0f}\n")
```

### 2. 运行主程序

```bash
python polymarket_api.py
```

这将执行演示程序，展示基本的 API 调用功能。

### 3. 运行示例程序

```bash
python example_usage.py
```

这将运行多个使用示例，包括：
- 获取市场列表
- 搜索市场
- 市场详细信息
- 概率分析
- 交易量分析
- 导出数据

## API 使用示例

### 获取市场列表

```python
api = PolymarketAPI()

# 获取前 20 个活跃市场
markets = api.get_markets(limit=20, active=True)

for market in markets:
    print(market['question'])
```

### 搜索市场

```python
# 搜索关键词 "Bitcoin"
results = api.search_markets("Bitcoin", limit=5)

for market in results:
    print(f"{market['question']}: {market['yes_price']*100:.1f}%")
```

### 获取市场详情

```python
# 根据市场 ID 获取详细信息
market_id = "0x1234..."
market = api.get_market_by_id(market_id)

if market:
    api.print_market_summary(market)
```

### 获取交易历史

```python
# 获取市场的交易历史
trades = api.get_market_trades(market_id, limit=50)

for trade in trades:
    print(trade)
```

### 市场数据分析

```python
markets = api.get_markets(limit=50)

# 筛选高概率市场
high_prob_markets = [m for m in markets if m['yes_price'] > 0.7]

# 按交易量排序
sorted_by_volume = sorted(markets, key=lambda x: x['volume'], reverse=True)

# 计算总交易量
total_volume = sum(m['volume'] for m in markets)
```

### 导出数据

```python
import json

markets = api.get_markets(limit=100)

# 导出到 JSON 文件
with open('markets.json', 'w', encoding='utf-8') as f:
    json.dump(markets, f, ensure_ascii=False, indent=2)
```

## API 方法说明

### PolymarketAPI 类

| 方法 | 描述 | 参数 | 返回值 |
|------|------|------|--------|
| `get_markets()` | 获取市场列表 | `limit`, `offset`, `active` | List[Dict] |
| `get_market_by_id()` | 获取单个市场详情 | `condition_id` | Dict |
| `search_markets()` | 搜索市场 | `query`, `limit` | List[Dict] |
| `get_market_orderbook()` | 获取订单簿 | `token_id` | Dict |
| `get_market_trades()` | 获取交易历史 | `condition_id`, `limit` | List[Dict] |
| `print_market_summary()` | 打印市场摘要 | `market` | None |

## 市场数据结构

每个市场对象包含以下字段：

```python
{
    'id': str,                    # 市场 ID
    'question': str,              # 市场问题
    'description': str,           # 市场描述
    'outcomes': List[str],        # 可能的结果
    'outcome_prices': List[float],# 结果价格
    'yes_price': float,           # "是"的概率 (0-1)
    'no_price': float,            # "否"的概率 (0-1)
    'volume': float,              # 交易量 (美元)
    'liquidity': float,           # 流动性 (美元)
    'active': bool,               # 是否活跃
    'closed': bool,               # 是否已关闭
    'end_date': str,              # 结束日期
    'category': str,              # 类别
    'market_slug': str,           # 市场 slug
    'tokens': List[Dict]          # 代币信息
}
```

## Polymarket API 端点

该程序使用以下 Polymarket API 端点：

- **Gamma API**: `https://gamma-api.polymarket.com`
  - `/markets` - 获取市场列表
  - `/markets/{id}` - 获取市场详情

- **CLOB API**: `https://clob.polymarket.com`
  - `/book` - 获取订单簿
  - `/trades` - 获取交易历史

## 注意事项

1. **API 限制**：Polymarket API 可能有速率限制，请合理使用
2. **数据实时性**：市场数据实时更新，价格和交易量会不断变化
3. **错误处理**：程序包含基本的错误处理，但建议在生产环境中增强
4. **认证**：当前程序使用公开 API，不需要认证。如需交易功能，需要添加钱包认证

## 高级用法

### 定时获取数据

```python
import time

api = PolymarketAPI()

while True:
    markets = api.get_markets(limit=10)
    # 处理市场数据
    for market in markets:
        print(f"{market['question']}: {market['yes_price']*100:.1f}%")
    
    # 每 60 秒更新一次
    time.sleep(60)
```

### 监控特定市场

```python
def monitor_market(market_id: str, interval: int = 30):
    """监控特定市场的价格变化"""
    api = PolymarketAPI()
    
    while True:
        market = api.get_market_by_id(market_id)
        if market:
            print(f"\n[{datetime.now()}] {market['question']}")
            print(f"是: {market['yes_price']*100:.1f}% | 否: {market['no_price']*100:.1f}%")
            print(f"交易量: ${market['volume']:,.0f}")
        
        time.sleep(interval)

# 使用示例
monitor_market("your_market_id_here", interval=60)
```

## 故障排除

### 常见问题

1. **无法获取数据**
   - 检查网络连接
   - 确认 API 端点是否可访问
   - 查看是否有速率限制

2. **数据格式错误**
   - Polymarket API 可能会更新数据格式
   - 查看官方文档获取最新信息

3. **依赖安装失败**
   - 确保使用 Python 3.7 或更高版本
   - 尝试升级 pip: `pip install --upgrade pip`

## 参考资源

- [Polymarket 官网](https://polymarket.com)
- [Polymarket API 文档](https://docs.polymarket.com)
- [Python Requests 文档](https://docs.python-requests.org)

## 许可证

本项目仅供学习和演示使用。

## 贡献

欢迎提交问题和改进建议！
