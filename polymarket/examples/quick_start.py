"""
Quick Start Example for Polymarket Copy Trading System

This example demonstrates how to:
1. Connect to Polymarket API
2. Track top traders
3. Set up copy trading
"""

import asyncio
from loguru import logger

# Add parent directory to path
import sys
sys.path.insert(0, '..')

from config import get_settings
from api_client import PolymarketAPIClient
from trader_tracker import TraderTracker, TradeSignal
from copy_strategy import CopyTradingStrategy
from trade_executor import DryRunExecutor


async def main():
    """Quick start demonstration"""
    
    print("=" * 60)
    print("Polymarket Copy Trading System - Quick Start")
    print("=" * 60)
    
    # 1. Initialize API client and fetch markets
    print("\n[1] Connecting to Polymarket API...")
    api = PolymarketAPIClient()
    
    markets = await api.get_markets(limit=5)
    print(f"    Found {len(markets)} active markets:")
    for m in markets:
        yes_price = m.outcome_prices[0] if m.outcome_prices else 0
        print(f"    - {m.question[:50]}... (YES: {yes_price:.1%})")
    
    # 2. Initialize tracker
    print("\n[2] Initializing trader tracker...")
    tracker = TraderTracker()
    await tracker.initialize()
    
    # 3. Add a sample trader to track (replace with real address)
    sample_trader = "0x0000000000000000000000000000000000000001"  # Example
    print(f"\n[3] Adding sample trader: {sample_trader[:10]}...")
    
    # Note: In real usage, add actual trader addresses
    # await tracker.add_trader(sample_trader, alias="Sample Trader")
    
    # 4. Initialize strategy
    print("\n[4] Initializing copy trading strategy...")
    strategy = CopyTradingStrategy()
    await strategy.initialize()
    
    # 5. Initialize executor (dry run mode)
    print("\n[5] Initializing trade executor (DRY RUN mode)...")
    executor = DryRunExecutor()
    await executor.initialize()
    
    # 6. Simulate a trade signal
    print("\n[6] Simulating trade signal...")
    
    if markets:
        sample_market = markets[0]
        sample_signal = TradeSignal(
            trader_address=sample_trader,
            market_id=sample_market.id,
            market_slug=sample_market.slug,
            token_id=sample_market.tokens[0]["token_id"] if sample_market.tokens else "",
            direction=TradeDirection.BUY,
            price=sample_market.outcome_prices[0] if sample_market.outcome_prices else 0.5,
            size=100.0,
            amount_usd=50.0,
            transaction_hash="0x" + "a" * 64,
            timestamp=datetime.utcnow(),
            confidence=0.7
        )
        
        print(f"    Signal: BUY {sample_signal.size} shares @ ${sample_signal.price:.4f}")
        
        # Evaluate with strategy
        decision = await strategy.evaluate_signal(sample_signal)
        print(f"    Decision: {decision.action.value}")
        print(f"    Copy Size: {decision.copy_size:.2f}")
        print(f"    Copy Amount: ${decision.copy_amount:.2f}")
        
        # Execute (simulated)
        if decision.action.value != "SKIP":
            result = await executor.execute_decision(decision)
            print(f"    Execution: {'SUCCESS' if result.success else 'FAILED'}")
            if result.success:
                print(f"    Executed Price: ${result.executed_price:.4f}")
    
    # Cleanup
    await api.close()
    await executor.close()
    
    print("\n" + "=" * 60)
    print("Quick start complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Configure .env with your wallet credentials")
    print("2. Add real trader addresses to track")
    print("3. Run: python main.py run --dry-run")


# Need to import these for the simulation
from trader_tracker import TradeSignal
from models import TradeDirection
from datetime import datetime


if __name__ == "__main__":
    asyncio.run(main())
