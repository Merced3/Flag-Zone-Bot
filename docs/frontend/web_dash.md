# Web Dashboard Overview (`web_dash/`)

The `web_dash/` folder contains the code for StratForge’s **web dashboard** – a live charting UI built with Plotly Dash (a web framework for Python) and a FastAPI WebSocket backend. This dashboard allows you to visualize live candlestick charts and strategy data (like zones/levels) in real-time, separate from the core trading logic. It’s designed so that the backend trading engine and the frontend dashboard are decoupled (communicating via a WebSocket), following a separation-of-concerns approach described in the architecture docs.

At a high level, the web dashboard works as follows: the Dash app (frontend) displays charts (candlestick plots and zone/level annotations), and a FastAPI service in `ws_server.py` (backend) pushes update notifications to the Dash app via WebSockets. When a new candle closes, the backend triggers an update, the Dash UI refreshes the charts, and you see the latest data without needing to manually reload. The chart data itself comes from the StratForge storage system (the same candles and objects data used by strategies). Below we explain each file and component in the `web_dash/` module, and then outline the step-by-step flow of how they work together for real-time updates.

## Dash Application (`dash_app.py`)

This file is the entry point for the Dash web application. It creates the Dash app instance and defines the layout of the dashboard UI – essentially, what charts and components appear on the webpage. In `dash_app.py`, a Dash app is initialized (with any necessary configuration, e.g. specifying the `assets/` folder for static files) and a layout is set up using Dash HTML and Core Components. The layout typically includes:

* One or more graph components or image placeholders to display the live **candlestick charts** (for the configured timeframes like 2M, 5M, 15M).
* Another graph or image for the **zones chart** (the 15-minute “historical” chart with zones/levels overlaid).
* Possibly some basic controls or headings (depending on how interactive the dashboard is – for a beginner-level dashboard, there might simply be static images or auto-updating graphs, rather than complex user input controls).

The `dash_app.py` essentially **declares the UI**. For example, it might create a Dash `dcc.Graph` for each chart or use `html.Img` components to show chart images. If using images, the images would be those generated and stored in `storage/images/` (e.g. `SPY_2M_chart.png`, `SPY_15M-zone_chart.png`, etc.). If using interactive graphs, the layout links them to callbacks for updating. In either case, `dash_app.py` itself does not contain the chart-drawing logic – it only lays out the dashboard structure. It likely imports the `chart_updater` module (described next) to ensure the update mechanism is initialized, and then runs the Dash server. To launch the web dashboard, you run this file (or run the Dash app through `main.py` as configured), and it will start a local web server hosting the dashboard UI.

## Chart Updater (`chart_updater.py`)

The `chart_updater.py` module is responsible for **listening for update signals and refreshing the charts**. It acts as a bridge between the WebSocket messages (from the backend) and the chart generation functions. When a WebSocket message indicates that new data is available for a chart, `chart_updater.py` triggers the regeneration of that chart’s figure (and possibly the saving of a new image) so that the Dash frontend can update.

In practice, this module likely establishes a WebSocket client connection to the FastAPI server (to the `/ws/chart-updates` endpoint) and runs an event loop waiting for messages. For example, when it receives a message like `"chart:2M"` (indicating a 2-minute candle just closed and the 2M chart should update), the chart_updater will call the appropriate chart-drawing function from the `charts/` subfolder (e.g. a function to update the live 2M chart). The chart updater then produces a new chart – for instance, generating a Plotly figure for the 2-minute timeframe – and saves the updated chart output. Depending on the implementation, it might update a global Dash state or simply update the image file on disk.

* If the dashboard uses static images in the UI, the `chart_updater.py` would overwrite the old PNG file (e.g. `SPY_2M_chart.png`) with a new one whenever an update comes. The frontend can then display the new image (sometimes this is done by appending a timestamp or cache-busting query string to the image URL so the browser fetches the new image).
* If the dashboard uses interactive graph components, `chart_updater.py` might instead update a shared data store or use Dash callbacks to push the new figure to the client.

Under the hood, this module uses Python’s **WebSocket client** capabilities (for example via `websockets` or similar library) to subscribe to updates. It essentially runs in the background of the Dash app process. When an update message arrives, it loads the latest candle data (from the logs or Parquet files) and calls the chart functions. The candle data for each timeframe is continuously logged to files (e.g. `logs/SPY_2M.log` for 2-minute candles, etc.), which are used by the charting functions. In summary, `chart_updater.py` **waits for a “chart update” signal and then regenerates the chart data and visuals** so that the frontend can reflect the latest state.

*(For a beginner: you can think of `chart_updater.py` as the part that says “hey, new data arrived – let’s redraw the chart!”. It keeps the Dash UI in sync with the backend data in real-time, without the page having to reload.)*

## WebSocket Server (`ws_server.py`)

The `ws_server.py` file implements the **FastAPI-based WebSocket server** that the dashboard uses for real-time updates. This is essentially the **backend service that broadcasts chart update notifications** to all connected dashboard clients. It serves two primary purposes:

1. **WebSocket Broadcast:** It defines a WebSocket endpoint (likely at a route such as `/ws/chart-updates`) that dashboard clients connect to. When clients (the Dash app’s updater module) are connected, the server can send messages to them over this WebSocket. The messages are simple signals, e.g. sending a message `"chart:5M"` to indicate the 5-minute chart should update. According to the internal API docs, the WebSocket sends messages in the format `chart:<TF>` (where `<TF>` might be “2M”, “5M”, “15M”, etc.).
2. **HTTP Trigger Endpoint:** It also provides a normal HTTP endpoint (for example, a POST route like `/trigger-chart-update`) that the **backend trading engine** can call to notify the WebSocket server that new data is available. When the trading logic finishes writing a candle (or a zone/level update) to the logs, it will make an HTTP POST request to this FastAPI service, including which timeframe needs updating (e.g. `{ "timeframe": "2M" }`). The `ws_server.py` will receive that HTTP request and then broadcast the corresponding WebSocket message (chart:2M in this example) out to all connected clients. The response might indicate the message was broadcast and how many clients received it.

In simpler terms, `ws_server.py` is a lightweight server that **relays update notifications**: the backend puts a message in, and all dashboards get that message through the WebSocket. FastAPI is used to handle both the HTTP route and the WebSocket route asynchronously. This design (an HTTP trigger + WebSocket broadcast) was chosen over simpler polling so that updates are pushed instantly and efficiently to the UI (as noted in the architecture decision record about WebSockets vs polling). You can find more details on these endpoints in the internal API documentation or the `docs/api/ws_server.md` file, but essentially:

* **POST** `/trigger-chart-update`: called by backend, causes a broadcast, returns a status (e.g. `"broadcasted"`).
* **WebSocket** /ws/chart-updates: used by frontend, sends out "chart:<timeframe>" messages on each update.

The FastAPI server runs independently of the Dash server. You might run `ws_server.py` (probably via Uvicorn) on a port (say 8000) and `dash_app.py` on a different port (say 8050). This separation allows the trading bot to run headless and only send update pings to the WebSocket service, while the Dash UI can be an optional component that users run to visualize the data. (If the dashboard is not running, the trading engine still functions - it just sends updates that no one receives, which is fine.)

## Chart Generation Modules (charts/ subfolder)

The `charts/` subdirectory contains modules that actually **generate the chart figures**. These are helper files used by `chart_updater.py` (or by other parts of the system) to create the visualizations. In StratForge’s web dashboard, there are two main chart types:

## `live_chart.py` – Live Candlestick Chart

The **live chart** module produces the intra-day candlestick charts for the active trading session. For example, it can generate the current 2-minute chart, 5-minute chart, and 15-minute chart of SPY (or whatever ticker is configured), including any real-time indicators or markers. This chart typically shows price candles up to the latest one that just closed, and may overlay strategy-specific annotations (for instance, flags or markers if any, though the primary overlays like zones are on the separate chart).

Key points about `live_chart.py`:

* It likely provides a function to **load recent candle data** for a given timeframe and create a Plotly figure from it. The data source would be the logs or Parquet files in `storage/data/` (which are constantly appended with new candle data). Indeed, the project logs every candle to files (see `logs/SPY_2M.log`, etc.) which are used not only by strategies but also by the frontend. The live chart code will read those entries to get the open, high, low, close (OHLC) and volume for each candle in the current day (or session) and then plot them.
* It sets up the **visual style** of the candlestick chart (using Plotly Graph Objects or Plotly Express). For example, drawing green/red candlestick bars, possibly adding moving averages or other overlays if needed, and setting axes labels, titles, etc.
* If needed, it might add annotations for strategy events (though a lot of those are zone/level related which are on the other chart). But something like buy/sell signals or flags could be marked here, if implemented.
* The output of this module’s function is typically saved as an image file in `storage/images/`. For instance, after generating the Plotly figure for the 2M chart, the code might save it as `SPY_2M_chart.png` (and similarly for 5M and 15M) in the images folder. These image files are what the Discord bot uses to post chart updates, and also what the Dash UI might directly display (the README confirms that the latest charts are written to `storage/images/` and served in the UI).

In summary, `live_chart.py` knows *how to draw the current price chart*. It doesn’t run continuously on its own; instead, when `chart_updater.py` or some other trigger calls it (e.g. “update the 5M chart now”), it will fetch the latest data and return an updated chart. This separation means you could also run it independently (for example, to manually generate a chart image at end-of-day for review).

*(Beginner note: This module contains the Plotly chart code – if you want to adjust how the chart looks (colors, layout) or what data is shown, you’d do it in `live_chart.py`. It’s conceptually similar to writing a small script to plot a candlestick chart with Plotly.)*

## `zones_chart.py` – Zones/Levels Historical Chart

The **zones chart** module generates the *15-minute timeframe historical chart with zones and levels overlaid*. This chart is a bit different from the intraday live charts – it’s meant to show a broader view (typically multiple days or a large time window) with the **flag & zone detection** outputs drawn on top. In StratForge, “zones” and “levels” are important support/resistance areas computed by the strategy (often derived from patterns in the 15-minute candles). The `zones_chart.py` uses those to create a composite chart.

Key points about `zones_chart.py`:

* It reads **historical 15-minute candle data** (likely at least the recent few days or the current day plus previous day) to plot a candlestick baseline. The data might come from the Parquet files in `storage/data/15m/` or from a CSV backup (the project mentions a `SPY_15_minute_candles.csv` which contains previous day’s 15m candles). The code might combine current live data (from logs) with some stored historical data to have continuity.
* It loads the **zones and levels** from the `storage/objects/objects.json` file. This JSON is updated by the strategy logic (`objects.py`) whenever new zones or levels are identified. The chart code will parse this file to get all active zone price ranges and level lines. Then, on the Plotly chart, it will draw these as shaded regions or horizontal lines. For example, if a “demand zone” was identified between certain prices, the chart may highlight that area on the 15m candlestick plot. If a specific price level was marked as significant, it may draw a horizontal line across the chart.
* The chart provides a **historical context** – you can see how price interacted with these zones/levels over time. It’s considered “historical” because it’s not just the current session; it might span a couple of days of 15-minute bars with all the zones/levels that were computed. (However, note that extremely long history might not be shown by default – typically you’d show perhaps today + yesterday for context.)
* As with live charts, the zones chart is saved as an image (`SPY_15M-zone_chart.png` in `storage/images/`). The suffix “-zone” is used to distinguish it from the normal 15M live chart image. This image is displayed in the dashboard to give the trader a bigger-picture view of key levels.

The zones chart complements the live charts by highlighting strategic information. For instance, you might watch the 2M live chart for fine-grained price action, but glance at the 15M zones chart to see if price is near a major support zone identified earlier. The `zones_chart.py` code is what plots those zones on the candlestick graph. (Internally, it doesn’t use the `timeline.json` for historical zones; it only uses the current `objects.json` data for zones/levels, meaning it plots the latest known zones. Old zones from previous days might still appear if they persist into the current day’s `objects.json`.)

*(For a beginner: This module is mainly about adding colored regions or lines on a candlestick chart. If you open `objects.json` you’d see a list of zones with price ranges – the code reads those and then uses Plotly shapes or annotations to draw them behind the candles. It helps visualize where the algorithm sees important price “zones”.)*

## Assets Folder (`assets/`)

The `assets/` directory in a Dash app is a place to put static files like CSS, JavaScript, or images that the Dash app can serve directly. In this project, the `assets/` folder is optional and likely contains static resources for the dashboard. Common uses could be:

* A custom CSS file to tweak the styling of the dashboard (fonts, colors, sizing beyond the default Dash theme).
* A favicon or logo to display in the browser tab.
* Possibly a small JavaScript snippet if needed to handle things like forcing an image refresh (though often not needed, sometimes developers add a script to auto-reload images or handle a websocket on the client side).

If the folder is empty or minimal, it means the dashboard mostly uses Dash’s default styling. Since it’s included in the structure, you know you can drop static files here and Dash will automatically find them. (Dash automatically serves any files in `assets/` at the `/assets/*` URL path.) In summary, `assets/` is just for static front-end files – it doesn’t contain Python code, and the web dashboard will load anything placed here when it starts. It’s not crucial for functionality, but it’s available for enhancing the UI presentation.

*(For example, if you wanted to change the background color or hide the “Updating...” loading indicator, you could add a `assets/style.css` file. This project may already include some default styles there.)*

## Real-Time Chart Update Flow

Now that each part is defined, here’s how they **work together to update the charts in real time**. This sequence assumes you have the trading engine running (producing candle data) and the web dashboard running (Dash app + WS server). The flow from a new candle close to the chart updating is:

1. **Candle Closes – Backend Triggers Update**: When a new candle completes (for example, every 2 minutes for the 2M chart), the backend strategy/data acquisition code detects it. The new OHLC data is logged to storage (appended to the log file and Parquet) and any strategy computations (indicators, zones, etc.) are updated. At this moment, the backend knows the charts should refresh (since there’s new data to show). It therefore makes a call to the WebSocket server’s HTTP trigger. Typically, the code will send an HTTP POST request to the FastAPI service `ws_server.py` at the `/trigger-chart-update` endpoint, including which timeframe needs updating (e.g. `"2M"`). This step is the backend’s responsibility – effectively saying *“Attention dashboard: the 2M chart has new data!”*. (If multiple timeframes closed simultaneously, it might trigger each, or batch them.)

2. **HTTP Endpoint Receives – WS Message Broadcast**: The FastAPI server (`ws_server.py`), upon receiving the trigger request, constructs a message for the WebSocket clients. For example, if it got `{"timeframe": "2M"}`, it will prepare the string `"chart:2M"`. It then **broadcasts** this message to all connected WebSocket clients on the `/ws/chart-updates` channel. In practice, “all clients” could be just one (your single Dash app instance in your browser), or multiple if you had the dashboard open in multiple windows. The FastAPI server ensures everyone gets the same update notification. The HTTP response is sent back to the caller indicating success (for example, it might respond with a JSON like `{"status": "broadcasted", "timeframe": "2M", "clients": 1}` to say one client got the message). At this point, the backend’s job is done – it doesn’t directly touch the Dash app, it only notified the WebSocket server, which in turn notified the frontend.

3. **Dashboard Receives WebSocket Signal**: In the Dash application process, the `chart_updater.py` module is running and listening on the WebSocket connection. It **receives the `"chart:2M"` message** that was broadcast. The chart updater interprets this message and determines that the 2M chart needs to be refreshed. It then calls the appropriate chart generation function – likely a function in `live_chart.py` responsible for building the 2M candlestick chart figure (or image). This function will load the latest 2M candle data (which now includes the newly closed candle) from the `logs/storage` and create an updated Plotly figure. It may also save the updated chart to `storage/images/SPY_2M_chart.png` on disk (overwriting the old chart). Similarly, if the update was for “15M” and concerned zones, it would call `zones_chart.py` to update the zones chart (reading the updated `objects.json` if a new zone was added, for instance). The key is that the **dashboard’s backend logic regenerates the chart in memory** in response to the signal.

4. **Dash UI Updates the Chart Display**: The final step is making the new chart visible to the user. Depending on how the Dash layout is implemented, this could happen in a couple of ways:

    * **If using live Graph components**: The chart_updater might update a Dash `dcc.Graph` component’s figure property via a callback. For example, Dash might have a callback that is triggered by an intermediate state (perhaps the chart_updater sets a flag or uses a `dcc.Store`). Once the new figure is ready, the callback provides it to the Graph component, and Dash updates that graph in the browser. The user sees the candlestick chart update (new candle appears) almost immediately.

    * **If using images**: If the dashboard is simply showing an `html.Img` with the chart PNG, then the image on disk has been replaced in step 3. To get the browser to show the new image, the dashboard might do something like update the src of the image with a dummy query parameter (e.g. add `?v=<current_time>` to the URL) to bust the cache and force reload. This could be done via a small clientside script or by a Dash interval component that notices the update. In any case, the image source is refreshed, causing the new PNG to load in the browser. Thus, the chart visibly refreshes.

    In both scenarios, the update happens **automatically and in near real-time** after the candle closes – you don’t need to refresh the page. The combination of the WebSocket signal and Dash update logic ensures the chart on your screen is always current with the latest data. You’ll see the new candle bar appear a few moments after it closes, and any new zones/levels will show up on the zones chart likewise.

To summarize the workflow: **the backend sends a signal → the WebSocket server broadcasts it → the Dash app’s updater hears it and regenerates the chart → the Dash UI component updates to show the new chart**. This design avoids constant polling by the frontend and instead uses an efficient push mechanism (as described in the project’s architecture notes on real-time updates). For more information, you can refer to the Architecture Overview and the Storage System documentation, which describe how the frontend and backend are decoupled and how data (like candles and objects) is stored and accessed. The Storage System docs, for instance, explain the logging of candles to Parquet/CSV and how zones/levels are persisted – all of which underpins what the web dashboard displays.






