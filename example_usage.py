"""
Polymarket API 使用示例
展示各种 API 调用方式
"""

from polymarket_api import PolymarketAPI
import json


def example_1_get_markets():
    """示例 1: 获取市场列表"""
    print("\n" + "="*80)
    print("示例 1: 获取市场列表")
    print("="*80)
    
    api = PolymarketAPI()
    markets = api.get_markets(limit=10)
    
    print(f"\n获取到 {len(markets)} 个市场\n")
    for market in markets:
        print(f"• {market['question']}")
        print(f"  概率: 是 {market['yes_price']*100:.1f}% | 否 {market['no_price']*100:.1f}%")
        print(f"  交易量: ${market['volume']:,.0f}\n")


def example_2_search_markets():
    """示例 2: 搜索市场"""
    print("\n" + "="*80)
    print("示例 2: 搜索市场")
    print("="*80)
    
    api = PolymarketAPI()
    
    # 搜索不同主题
    keywords = ['Trump', 'Bitcoin', 'AI', 'Election']
    
    for keyword in keywords:
        results = api.search_markets(keyword, limit=3)
        if results:
            print(f"\n🔍 关键词 '{keyword}' 的搜索结果 ({len(results)} 个):")
            for market in results:
                print(f"  • {market['question'][:80]}...")
        else:
            print(f"\n🔍 关键词 '{keyword}': 未找到相关市场")


def example_3_market_details():
    """示例 3: 获取市场详细信息"""
    print("\n" + "="*80)
    print("示例 3: 获取市场详细信息")
    print("="*80)
    
    api = PolymarketAPI()
    markets = api.get_markets(limit=1)
    
    if markets:
        market = markets[0]
        print(f"\n获取市场详情: {market['id']}\n")
        api.print_market_summary(market)


def example_4_analyze_probabilities():
    """示例 4: 分析市场概率"""
    print("\n" + "="*80)
    print("示例 4: 分析市场概率")
    print("="*80)
    
    api = PolymarketAPI()
    markets = api.get_markets(limit=20)
    
    if not markets:
        print("未能获取市场数据")
        return
    
    # 分析概率分布
    highly_probable = [m for m in markets if m['yes_price'] > 0.7]
    balanced = [m for m in markets if 0.4 <= m['yes_price'] <= 0.6]
    unlikely = [m for m in markets if m['yes_price'] < 0.3]
    
    print(f"\n📊 市场概率分析 (共 {len(markets)} 个市场):\n")
    
    print(f"高概率市场 (>70%): {len(highly_probable)} 个")
    for market in highly_probable[:3]:
        print(f"  • {market['question'][:70]}... ({market['yes_price']*100:.1f}%)")
    
    print(f"\n平衡市场 (40-60%): {len(balanced)} 个")
    for market in balanced[:3]:
        print(f"  • {market['question'][:70]}... ({market['yes_price']*100:.1f}%)")
    
    print(f"\n低概率市场 (<30%): {len(unlikely)} 个")
    for market in unlikely[:3]:
        print(f"  • {market['question'][:70]}... ({market['yes_price']*100:.1f}%)")


def example_5_volume_analysis():
    """示例 5: 交易量分析"""
    print("\n" + "="*80)
    print("示例 5: 交易量分析")
    print("="*80)
    
    api = PolymarketAPI()
    markets = api.get_markets(limit=50)
    
    if not markets:
        print("未能获取市场数据")
        return
    
    # 按交易量排序
    sorted_markets = sorted(markets, key=lambda x: x['volume'], reverse=True)
    
    print(f"\n💰 交易量前 10 的市场:\n")
    for i, market in enumerate(sorted_markets[:10], 1):
        print(f"{i:2d}. {market['question'][:65]}...")
        print(f"    交易量: ${market['volume']:,.0f} | 流动性: ${market['liquidity']:,.0f}")
        print(f"    概率: {market['yes_price']*100:.1f}%\n")
    
    # 统计总交易量
    total_volume = sum(m['volume'] for m in markets)
    total_liquidity = sum(m['liquidity'] for m in markets)
    
    print(f"📈 总交易量: ${total_volume:,.0f}")
    print(f"💵 总流动性: ${total_liquidity:,.0f}")
    print(f"📊 平均交易量: ${total_volume/len(markets):,.0f}")


def example_6_export_to_json():
    """示例 6: 导出市场数据到 JSON"""
    print("\n" + "="*80)
    print("示例 6: 导出市场数据到 JSON")
    print("="*80)
    
    api = PolymarketAPI()
    markets = api.get_markets(limit=20)
    
    if markets:
        filename = 'polymarket_data.json'
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(markets, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ 成功导出 {len(markets)} 个市场数据到 {filename}")
        print(f"文件大小: {len(json.dumps(markets, ensure_ascii=False))} 字节")
    else:
        print("\n❌ 未能获取市场数据")


def main():
    """运行所有示例"""
    print("\n" + "🎯 Polymarket API 使用示例集合")
    print("=" * 80)
    
    examples = [
        ("获取市场列表", example_1_get_markets),
        ("搜索市场", example_2_search_markets),
        ("市场详细信息", example_3_market_details),
        ("概率分析", example_4_analyze_probabilities),
        ("交易量分析", example_5_volume_analysis),
        ("导出数据", example_6_export_to_json),
    ]
    
    print("\n可用示例:")
    for i, (name, _) in enumerate(examples, 1):
        print(f"  {i}. {name}")
    
    print("\n运行所有示例...")
    
    for name, func in examples:
        try:
            func()
        except Exception as e:
            print(f"\n❌ 示例 '{name}' 执行失败: {e}")
    
    print("\n" + "="*80)
    print("✅ 所有示例执行完成!")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
