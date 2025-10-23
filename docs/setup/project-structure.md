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
│   ├── csv/
│   │   └── order_log.csv
│   ├── data/
│   │   ├── 2m/ 
│   │   │   ├── 2025-10-22/ # Named whatever today's date is.
│   │   │   │   ├── part-20251022_133001.290000-c24f98a7.parquet
│   │   │   │   ├── # Alot of other individual candled-files
│   │   │   │   └── part-20251022_182800.654000-824267af.parquet
│   │   │   ├── 2025-10-21.parquet
│   │   │   └── # Others Daily files...
│   │   ├── 5m/
│   │   │   ├── 2025-10-22/
│   │   │   │   ├── part-20251022_133001.290000-fbe82934.parquet
│   │   │   │   ├── # samething here
│   │   │   │   └── part-20251022_182500.343000-6ef44dd7.parquet
│   │   │   ├── 2025-10-21.parquet
│   │   │   └── # Others Daily files...
│   │   └── 15m/
│   │       ├── 2025-10-22/
│   │       │   ├── part-20251022_133001.290000-8147ad38.parquet
│   │       │   ├── # samething here
│   │       │   └── part-20251022_181501.045000-cb117cc9.parquet
│   │       ├── 2025-10-21.parquet 
│   │       └── # Others Daily files... Alot more than the others.
│   ├── emas/
│   │   ├── 2M.json
│   │   ├── 5M.json
│   │   ├── 15M.json
│   │   └── ema_state.json
│   ├── flags/
│   │   ├── 2M.json
│   │   ├── 5M.json
│   │   └── 15M.json
│   ├── images/
│   │   ├── SPY_2M_chart.png
│   │   ├── SPY_5M_chart.png
│   │   ├── SPY_15M_chart.png
│   │   └── SPY_15M-zone_chart.png
│   ├── markers/
│   │   ├── 2M.json
│   │   ├── 5M.json
│   │   └── 15M.json
│   └── objects/...
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
