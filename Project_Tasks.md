# 📝 Project Tasks

## 🚧 Pending Tasks

### Version 3 Flag System

- **Goal**: Make the flag system ONLY dependent on other candlestick OCHL.
- **Status**: 🕒 Pending
- **Description**: Instead of it monitoring one state at a time and constantly resetting state when it crosses the 200ema. It needs to operate multiple flag types (bear and bull) at the same time completely indepented from the emas, emas no longer dictate what flag we look at, we look at all of them.

### Market Open/Close API Integration

- **Goal**: Improve logic for handling market holidays and irregular schedules dynamically.
- **Status**: 🕒 Pending
- **Description**: Research a free or low-cost API (e.g., EODHD) to retrieve detailed market hours. Update logic for half-days and holidays. Add tests for edge cases.

### Candlestick Data Accuracy

- **Goal**: Generate OCHL candlestick data from a reliable real-time price stream.
- **Status**: 🛑 Blocked
- **Description**: Polygon’s data is unsuitable. Explore providers offering real-time trade data for candlestick generation. Test Tradier’s data stream for this purpose.

### Documentation & Process Improvement

- **Goal**: Maintain clear, updated documentation for workflows, errors, and fixes.
- **Status**: 🕒 Pending
- **Description**: Write a troubleshooting guide for WebSocket issues. Add comments in code explaining complex functions like `ws_connect_v2`.

### Refactor Discord Message IDs

- **Goal**: Store and access Discord Message IDs dynamically from a JSON file instead of global variables.
- **Status**: 🛠️ Not Started
- **Description**: Refactor all instances where Discord Message IDs are stored as global variables. Update the logic to dynamically retrieve these IDs from the existing JSON file when needed, reducing memory usage and improving modularity.

### Change End Of Day Calculaions

- **Goal**: Have it to where it calculates EVERYTHING based off the `message_ids.json`.
- **Status**: 🛠️ Not Started
- **Description**: instead of variables that store stort-term values we need everything based off of `message_ids.json` not only does it help with short-term testing but works with long term solutions as well. The end of day calculation will start at the `tll_trading_strategy.py` in the `todays_profit_loss` then you trace it back to the `get_profit_loss_orders_list()` function which returns this variable`todays_orders_profit_loss_list`, this is what is responsible for the end of day calculation. Figure out a work around or get rid of the variable entirely.

### Shared State Integration

- **Goal**: Implement a shared state module (`shared_state.py`) for centralized global variable management.
- **Status**: 🕒 Pending
- **Description**: Create `shared_state.py` to store `latest_price` and `price_lock` globally. Refactor `data_acquisition.py` and `main.py` to use `shared_state.py` for accessing and updating the latest price. Ensure modularity and avoid circular imports. This need's to be tested throughly And look for other things that need to be inside of shared state.

---

## ✅ Completed Tasks

### Enhance Config Management

- **Goal**: Ensure dynamic retrieval of config values during runtime.
- **Status**: ✅ Completed
- **Description**: Implemented `read_config()` function. Replaced hardcoded calls with dynamic ones (e.g., `read_config("SYMBOL")`).

### WebSocket Error Handling & Switching

- **Goal**: Improve reliability and error handling in WebSocket connections.
- **Status**: ✅ Completed
- **Description**: Fixed `ws_connect_v2` for Tradier and Polygon, debugged switching logic. Identified and removed Polygon as a provider.

### Refactor `get_current_price()`

- **Goal**: Handle cases where price data is missing in WebSocket messages.
- **Status**: ✅ Completed
- **Description**: Added checks for missing fields and handled invalid messages gracefully. Improved logging for troubleshooting.

### Version Control Hygiene

- **Goal**: Exclude sensitive files and unnecessary directories (e.g., `venv`) from version control.
- **Status**: ✅ Completed
- **Description**: Removed `venv` from the repo and updated `.gitignore`. Reviewed for sensitive files.

---

## Notes

- Tasks marked **🛑 Blocked** require external resolution (e.g., new provider, API access).
- Tasks are arranged by priority: Pending tasks are at the top, completed tasks are at the bottom.
- Update this file regularly as tasks progress or new ones are added.
