# Project Structure (reference)

```bash
Flag-Zone-Bot/
├── .github/
│   └── workflows/
│       └── python-ci.yml
├── docs/
│   ├── adr/
│   │   ├── 0001-separate-frontend-from-backend.md
│   │   └── 0002-parquet-append-and-duckdb-reads.md
│   ├── api/
│   │   └── storage-viewport.md
│   ├── architecture/
│   │   └── overview.md
│   ├── configuration/
│   │   └── ticker-and-timeframes.md
│   ├── data/
│   │   ├── candles_schema.md
│   │   ├── objects_schema.md
│   │   └── storage-system.md
│   ├── frontend/
│   │   └── web_dash.md
│   ├── overview/
│   │   └── stratforge.md
│   ├── runbooks/
│   │   ├── end-of-day-compaction.md
│   │   └── rebuild-ema-state.md
│   ├── setup/
│   │   └── project-structure.md
│   ├── strategies/
│   │   └── README.md
│   ├── testing/
│   │   └── storage_tests.md
│   ├── roadmap.md
│   ├── release-notes.md
│   └── TOC.md
├── storage/
│   ├── data/2m|5m|15m/...parquet
│   ├── objects/...
│   └── images/...
├── web_dash/
│   ├── __init__.py
│   ├── dash_app.py
│   ├── chart_updater.py
│   ├── ws_server.py
│   ├── about_this_dash_folder.txt
│   ├── charts/
│   │   ├── live_chart.py
│   │   └── zones_chart.py
│   └── assets/
├── .gitignore
├── buy_option.py
├── config.json
├── cred.py
├── data_acquisition.py
├── economic_calender_scraper.py
├── error_handler.py
├── main.py
├── objects.py
├── order_handler.py
├── paths.py
├── print_discord_messages.py
├── README.md
├── requirements.txt
├── rule_manager.py
├── sentiment_engine.py
├── shared_state.py
└── submit_order.py
```
