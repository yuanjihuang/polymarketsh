"""
Example: Manual Trading

This script demonstrates how to manually place trades
without the copy trading automation.

Useful for:
- Testing your setup
- Making discretionary trades
- Understanding the trading mechanics
"""

import asyncio
import sys
sys.path.insert(0, '..')

from api_client import PolymarketAPIClient
from trade_executor import TradeExecutor, DryRunExecutor
from config import get_settings


async def browse_markets():
    """Browse available markets and their prices"""
    print("\n=== Available Markets ===\n")
    
    api = PolymarketAPIClient()
    markets = await api.get_markets(limit=10, active=True)
    
    for i, market in enumerate(markets, 1):
        yes_price = market.outcome_prices[0] if market.outcome_prices else 0
        no_price = market.outcome_prices[1] if len(market.outcome_prices) > 1 else 1 - yes_price
        
        print(f"{i}. {market.question[:60]}")
        print(f"   YES: {yes_price:.1%}  |  NO: {no_price:.1%}")
        print(f"   Volume: ${market.volume:,.0f}  |  Liquidity: ${market.liquidity:,.0f}")
        print(f"   ID: {market.id}")
        if market.tokens:
            print(f"   YES Token: {market.tokens[0].get('token_id', 'N/A')[:20]}...")
        print()
    
    await api.close()
    return markets


async def get_order_book(token_id: str):
    """Get order book for a token"""
    print(f"\n=== Order Book for {token_id[:20]}... ===\n")
    
    api = PolymarketAPIClient()
    order_book = await api.get_order_book(token_id)
    
    if order_book:
        print("ASKS (Sell Orders):")
        for ask in order_book.asks[:5]:
            print(f"  {ask['price']:.4f} - {ask['size']:.2f} shares")
        
        print(f"\n  --- Spread: {order_book.spread:.4f} ---")
        print(f"  --- Mid Price: {order_book.mid_price:.4f} ---\n")
        
        print("BIDS (Buy Orders):")
        for bid in order_book.bids[:5]:
            print(f"  {bid['price']:.4f} - {bid['size']:.2f} shares")
    else:
        print("Could not fetch order book")
    
    await api.close()
    return order_book


async def place_test_order(token_id: str, side: str, price: float, size: float):
    """
    Place a test order (DRY RUN - no real execution)
    
    Args:
        token_id: Token to trade
        side: "BUY" or "SELL"
        price: Limit price (0-1)
        size: Number of shares
    """
    print(f"\n=== Placing Test Order ===")
    print(f"Token: {token_id[:20]}...")
    print(f"Side: {side}")
    print(f"Price: {price:.4f}")
    print(f"Size: {size:.2f}")
    print()
    
    # Use dry run executor
    executor = DryRunExecutor()
    await executor.initialize()
    
    result = await executor.create_limit_order(token_id, side, price, size)
    
    if result.success:
        print(f"[SUCCESS] Order would be placed")
        print(f"  Order ID: {result.order_id}")
    else:
        print(f"[FAILED] {result.error_message}")
    
    await executor.close()


async def interactive_demo():
    """Interactive trading demonstration"""
    print("=" * 60)
    print("Polymarket Manual Trading Demo")
    print("=" * 60)
    
    # Browse markets
    markets = await browse_markets()
    
    if not markets:
        print("No markets found")
        return
    
    # Get first market's order book
    first_market = markets[0]
    if first_market.tokens:
        yes_token = first_market.tokens[0].get("token_id")
        if yes_token:
            await get_order_book(yes_token)
            
            # Place test order
            await place_test_order(
                token_id=yes_token,
                side="BUY",
                price=0.50,
                size=10.0
            )
    
    print("\n" + "=" * 60)
    print("Demo complete!")
    print("=" * 60)
    print("\nTo place real orders:")
    print("1. Configure your .env with private key")
    print("2. Use TradeExecutor instead of DryRunExecutor")
    print("3. Ensure you have USDC in your Polygon wallet")


if __name__ == "__main__":
    asyncio.run(interactive_demo())
