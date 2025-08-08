# Architecture Notes – Core Separation Principle

## Concept

We separated **frontend logic** (Dash live charts, zones visualizations) from the **backend core** (data acquisition, strategy execution, order handling) so we can:

- Restart and debug frontend without interrupting market data collection.
- Test UI or visualization changes without risking data loss or missed trades.
- Let backend run 24/7 while experimenting with new visual elements.

## Why it Matters

- Data collection should never stop during market hours — stability of the main loop is priority #1.
- Strategies, UI, and analytics are secondary processes and can be hot-swapped.
- Future-proofing: as strategies evolve, the data pipeline remains untouched and always live.

## Benefits

- Reduced downtime when debugging.
- Modular code paths — easier to extend new features without side effects.
- Encourages a service-oriented architecture where each component has a clear responsibility.

## How to Apply Elsewhere

- **Strategies:** Run them as separate workers consuming from shared state / database, so you can swap or restart without halting data flow.
- **Order Execution:** Separate broker connection handler from signal generation — allows testing signal logic offline.
- **Alerts & Reports:** Treat as independent services that subscribe to event streams rather than living inside `main.py`.

---

### *Keep this principle in mind whenever adding new features: “Can I restart this module without touching the rest of the system?”*
