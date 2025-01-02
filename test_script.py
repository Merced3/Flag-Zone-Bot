import asyncio
import datetime
from data_acquisition import is_market_open, get_market_hours

async def test():
    if await is_market_open():
        print(f"Markets are open today.\n")
    else:
        print(f"Markets are closed today, waiting for tomorrow.\n")
    await asyncio.sleep(0.05)

    today_date = datetime.datetime.now().strftime('%Y-%m-%d')
    try:
        market_hours = await get_market_hours(today_date)
        if market_hours:
            print(f"Market opens at: {market_hours['open_time_et']} ET")
            print(f"Market closes at: {market_hours['close_time_et']} ET")
        else:
            print(f"Failed to fetch market hours.")
    except Exception as e:
        print(f"[ERROR] Failed to fetch market hours: {e}")
    await asyncio.sleep(0.05)

if __name__ == "__main__":
    asyncio.run(test())