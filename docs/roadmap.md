# Roadmap

---

## Now

### NEW UI/UX

- **Goal**: Make the UI better than what we had previously
- **Status**: 🕒 Pending
- **Description**: Previously we had only 2 forms of vision; previous days 15 min chart (to get High and low zones/levels) and the live 2 min chart. What I have found is that more forms of vision can help find more signals in the noise of the market. Meaning more timeframes; more ways to see whats going on. This will help with our V4 of the this options trading bot.

---

## Next

### How To Look

- **Goal**: Let the bot see what the market is interacting with.
- **Status**: 🛠️ Not Started
- **Description**: Inorder to act you must see. With each new form of vision we need to log everything, what the candles are interacting with on each timeframe and make a consensus with as little or as much data as we have. This im still thinking about how im going to do my best to aviod over fitting plus a pluthora of other questions for a later date. Once the program logs what it sees, we can then decide how we can make the program make certian decisions.

---

## Later

### Multi-Buy-In

- **Goal**: Multi-Buy Into same order
- **Status**: 🛠️ Not Started
- **Description**: This is what i want to implement in the V4 update. Where if the program wants to, it can multi-buy into the same order. New order handling will be needed and will need to setup a sim for it (maybe a unit test of sorts) for rigorous testing.

---

### Adaptive Stop Loss

- **Goal**: Make a adaptive stoploss that uses all the emas, zones and levels.
- **Status**: 🛠️ Not Started
- **Description**: We need a stop loss that can determine what the best stoploss is, whether it be 13, 48 or 200 ema OR the zones or TPL_lines. This would be a great thing to expirement with.

---

### Candlestick Data Accuracy

- **Goal**: Generate OCHL candlestick data from a 2nd reliable real-time price stream via a sequential setup.
- **Status**: 🛑🕒 Blocked/Pending
- **Description**: Polygon’s data is unsuitable. We tried to setup a sequential websocket function where if one websocket fails (incase server side error or platform error, anything that can't be handled by us, provider issues) then we move onto the next. we have not found the next provider but will do.

---

### Refactor Discord Message IDs

- **Goal**: Store and access Discord Message IDs dynamically from a JSON file instead of global variables.
- **Status**: 🛠️ Not Started
- **Description**: Refactor all instances where Discord Message IDs are stored as global variables. Update the logic to dynamically retrieve these IDs from the existing JSON file when needed, reducing memory usage and improving modularity.

---

### Change End Of Day Calculaions

- **Goal**: Have it to where it calculates EVERYTHING based off the `message_ids.json`.
- **Status**: 🛠️ Not Started
- **Description**: instead of variables that store stort-term values we need everything based off of `message_ids.json` not only does it help with short-term testing but works with long term solutions as well. The end of day calculation will start at the `tll_trading_strategy.py` in the `todays_profit_loss` then you trace it back to the `get_profit_loss_orders_list()` function which returns this variable`todays_orders_profit_loss_list`, this is what is responsible for the end of day calculation. Figure out a work around or get rid of the variable entirely.

---

## Notes

- Tasks marked **🛑 Blocked** require external resolution (e.g., new provider, API access).
- Tasks are arranged by priority: Pending tasks are at the top, completed tasks are at the bottom.
- Update this file regularly as tasks progress or new ones are added.
