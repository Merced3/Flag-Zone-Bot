# 📝 Project Tasks

## 🚧 Pending Tasks

### Adaptive Stop Loss

- **Goal**: Make a adaptive stoploss that uses all the emas, zones and Tp_lines.
- **Status**: 🕒 Pending
- **Description**: We need a stop loss that can determine what the best stoploss is, whether it be 13, 48 or 200 ema OR the zones or TPL_lines. This would be a great thing to expirement with.

### IMPLEMENT Version 3 Flag System

- **Goal**: Implement new flag system.
- **Status**: 🕒 Pending
- **Description**: The code that you already have done in the simulator, but before you do it you need to finish the adaptive stoploss functionality.

### Candlestick Data Accuracy

- **Goal**: Generate OCHL candlestick data from a 2nd reliable real-time price stream via a sequential setup.
- **Status**: 🛑 Blocked 🕒 Pending
- **Description**: Polygon’s data is unsuitable. We tried to setup a sequential websocket function where if one websocket fails (incase server side error or platform error, anything that can't be handled by us, provider issues) then we move onto the next. we have not found the next provider but will do.

### Refactor Discord Message IDs

- **Goal**: Store and access Discord Message IDs dynamically from a JSON file instead of global variables.
- **Status**: 🛠️ Not Started
- **Description**: Refactor all instances where Discord Message IDs are stored as global variables. Update the logic to dynamically retrieve these IDs from the existing JSON file when needed, reducing memory usage and improving modularity.

### Change End Of Day Calculaions

- **Goal**: Have it to where it calculates EVERYTHING based off the `message_ids.json`.
- **Status**: 🛠️ Not Started
- **Description**: instead of variables that store stort-term values we need everything based off of `message_ids.json` not only does it help with short-term testing but works with long term solutions as well. The end of day calculation will start at the `tll_trading_strategy.py` in the `todays_profit_loss` then you trace it back to the `get_profit_loss_orders_list()` function which returns this variable`todays_orders_profit_loss_list`, this is what is responsible for the end of day calculation. Figure out a work around or get rid of the variable entirely.

---

## ✅ Completed Tasks

### Version 3 Flag System

- **Goal**: Make the flag system ONLY dependent on other candlestick OCHL.
- **Status**: ✅ Completed
- **Description**: It uses multiple state files and even has a setting to store the state's in memory (as dictionary) for faster processing speed's.

### Market Open/Close API Integration

- **Goal**: Improve logic for handling market holidays and irregular schedules dynamically.
- **Status**: ✅ Completed
- **Description**: We use a API that's part of our polygon subcription and we put the code into `data_aquisition.py` and the function is called `is_market_open()`.

### Shared State Integration

- **Goal**: Implement a shared state module (`shared_state.py`) for centralized global variable management.
- **Status**: ✅ Completed
- **Description**: Created a `shared_state.py` to store `latest_price` and `price_lock` globally. Might add more stuff to it later on.

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
