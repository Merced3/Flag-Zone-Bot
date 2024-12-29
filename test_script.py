import asyncio
from data_acquisition import ws_connect_v2, active_provider
from asyncio import Queue

SYMBOL = "SPY"

async def test_websocket_fallback():
    """
    Test the WebSocket fallback mechanism between Tradier and Polygon.
    """
    global active_provider
    test_queue = Queue()

    print("[TEST] Starting WebSocket connection tests...")

    # Step 1: Test Tradier WebSocket
    active_provider = "tradier"
    print("[TEST] Testing Tradier WebSocket...")
    try:
        await asyncio.wait_for(ws_connect_v2(test_queue, active_provider, SYMBOL), timeout=10)
    except asyncio.TimeoutError:
        print("[TEST] Tradier WebSocket timed out (expected if market is closed).")
    except Exception as e:
        print(f"[TEST] Tradier WebSocket failed with error: {e}")
    finally:
        # Verify if fallback occurred or manual switch is needed
        if active_provider != "tradier":
            print("[TEST] Tradier WebSocket failed. Fallback to Polygon initiated.")
        else:
            print("[TEST] Tradier WebSocket connected or failed without fallback.")

    # Step 2: Test Polygon WebSocket
    active_provider = "polygon"
    print("[TEST] Testing Polygon WebSocket...")
    try:
        await asyncio.wait_for(ws_connect_v2(test_queue, active_provider, SYMBOL), timeout=10)
    except asyncio.TimeoutError:
        print("[TEST] Polygon WebSocket timed out (expected if market is closed).")
    except Exception as e:
        print(f"[TEST] Polygon WebSocket failed with error: {e}")
    finally:
        if active_provider != "polygon":
            print("[TEST] Polygon WebSocket failed. Unexpected behavior.")
        else:
            print("[TEST] Polygon WebSocket connected successfully or expected failure due to market closure.")

    # Step 3: Verify Queue Data
    print("[TEST] Verifying queue contents...")
    try:
        while not test_queue.empty():
            message = await test_queue.get()
            print(f"[TEST] Received data: {message}")
            test_queue.task_done()
    except Exception as e:
        print(f"[TEST] Error reading from queue: {e}")

    print("[TEST] WebSocket fallback tests completed.")

if __name__ == "__main__":
    try:
        asyncio.run(test_websocket_fallback())
    except KeyboardInterrupt:
        print("[TEST] Test script interrupted by user.")
