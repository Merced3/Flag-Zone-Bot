# ✅ Release Notes

---

## Version 3 Flag System

- **Goal**: Make the flag system ONLY dependent on other candlestick OCHL.
- **Status**: ✅ Completed
- **Description**: It uses multiple state files and even has a setting to store the state's in memory (as dictionary) for faster processing speed's.

---

## Market Open/Close API Integration

- **Goal**: Improve logic for handling market holidays and irregular schedules dynamically.
- **Status**: ✅ Completed
- **Description**: We use a API that's part of our polygon subcription and we put the code into `data_aquisition.py` and the function is called `is_market_open()`.

---

## Shared State Integration

- **Goal**: Implement a shared state module (`shared_state.py`) for centralized global variable management.
- **Status**: ✅ Completed
- **Description**: Created a `shared_state.py` to store `latest_price` and `price_lock` globally. Might add more stuff to it later on.

---

## Enhance Config Management

- **Goal**: Ensure dynamic retrieval of config values during runtime.
- **Status**: ✅ Completed
- **Description**: Implemented `read_config()` function. Replaced hardcoded calls with dynamic ones (e.g., `read_config("SYMBOL")`).

---

## WebSocket Error Handling & Switching

- **Goal**: Improve reliability and error handling in WebSocket connections.
- **Status**: ✅ Completed
- **Description**: Fixed `ws_connect_v2` for Tradier and Polygon, debugged switching logic. Identified and removed Polygon as a provider.

---

## Refactor `get_current_price()`

- **Goal**: Handle cases where price data is missing in WebSocket messages.
- **Status**: ✅ Completed
- **Description**: Added checks for missing fields and handled invalid messages gracefully. Improved logging for troubleshooting.

---

## Version Control Hygiene

- **Goal**: Exclude sensitive files and unnecessary directories (e.g., `venv`) from version control.
- **Status**: ✅ Completed
- **Description**: Removed `venv` from the repo and updated `.gitignore`. Reviewed for sensitive files.
