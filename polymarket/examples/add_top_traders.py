"""
Example: Adding Top Traders to Track

This script demonstrates how to:
1. Identify potential top traders
2. Analyze their performance
3. Add them to the tracking list

NOTE: You'll need to manually find trader addresses from:
- PolymarketAnalytics (https://polymarketanalytics.com)
- On-chain analysis
- Social media / forums
"""

import asyncio
import sys
sys.path.insert(0, '..')

from trader_tracker import TraderTracker, analyze_trader


# Example top trader addresses (REPLACE WITH REAL ADDRESSES)
# These are placeholder addresses for demonstration
EXAMPLE_TRADERS = [
    {
        "address": "0x0000000000000000000000000000000000000001",
        "alias": "Trader Alpha",
        "notes": "High win rate in political markets"
    },
    {
        "address": "0x0000000000000000000000000000000000000002", 
        "alias": "Trader Beta",
        "notes": "Specializes in crypto markets"
    },
    {
        "address": "0x0000000000000000000000000000000000000003",
        "alias": "Trader Gamma",
        "notes": "Large position sizes, consistent profits"
    },
]


async def analyze_and_add_traders():
    """Analyze potential traders and add promising ones"""
    
    print("=" * 60)
    print("Analyzing and Adding Top Traders")
    print("=" * 60)
    
    tracker = TraderTracker()
    await tracker.initialize()
    
    for trader_info in EXAMPLE_TRADERS:
        address = trader_info["address"]
        alias = trader_info["alias"]
        
        print(f"\n[Analyzing] {alias} ({address[:10]}...)")
        print(f"    Notes: {trader_info['notes']}")
        
        # Analyze trader
        try:
            profile = await analyze_trader(address)
            
            print(f"    Total Trades: {profile.total_trades}")
            print(f"    Win Rate: {profile.win_rate:.1%}")
            print(f"    Total Volume: ${profile.total_volume:,.2f}")
            print(f"    Is Active: {profile.is_active}")
            
            # Criteria for adding
            should_add = (
                profile.total_trades >= 10 and
                profile.win_rate >= 0.5 and
                profile.is_active
            )
            
            if should_add:
                success = await tracker.add_trader(address, alias=alias)
                if success:
                    print(f"    [✓] Added to tracking list")
                else:
                    print(f"    [!] Already being tracked")
            else:
                print(f"    [✗] Does not meet criteria")
                
        except Exception as e:
            print(f"    [ERROR] Could not analyze: {e}")
    
    # List all tracked traders
    print("\n" + "=" * 60)
    print("Currently Tracked Traders:")
    print("=" * 60)
    
    traders = tracker.get_tracked_traders()
    if traders:
        for t in traders:
            print(f"  - {t.address[:10]}... (Win Rate: {t.win_rate:.1%})")
    else:
        print("  No traders being tracked yet")
    
    print("\n[!] Remember to replace example addresses with real ones!")
    print("    Visit https://polymarketanalytics.com for top trader leaderboards")


if __name__ == "__main__":
    asyncio.run(analyze_and_add_traders())
