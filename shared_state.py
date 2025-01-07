# shared_state.py

import asyncio

# Global shared variables
latest_price = None  # To store the latest price
price_lock = asyncio.Lock()  # To ensure thread-safe access
