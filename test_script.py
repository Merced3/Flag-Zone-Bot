import asyncio
from data_acquisition import is_market_open

async def test():
    if await is_market_open():
        print(f"Markets are open today.\n")
    else:
        print(f"Markets are closed today, waiting for tomorrow.\n")
    await asyncio.sleep(0.05)

if __name__ == "__main__":
    asyncio.run(test())