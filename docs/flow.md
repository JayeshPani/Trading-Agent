# System Flow

```mermaid
flowchart TD
  A["Enter capital, risk, symbols, mode, strategy"] --> B["Extension sends settings"]
  B --> C["Backend validates settings"]
  C --> D["Safety pre-check"]
  D --> E["Market data collector"]
  E --> F["Strategy engine"]
  F --> G["Signal generated"]
  G --> H["Risk engine"]
  H -->|Rejected| I["Log rejection and continue"]
  H -->|Approved| J["BrokerAdapter order"]
  J --> K["Paper fill or gated Breeze call"]
  K --> L["Order monitor"]
  L --> M["Position monitor"]
  M --> N{"Exit condition"}
  N -->|Target/stop/invalidation/risk/cutoff| O["Square off"]
  O --> P["EOD report"]
  P --> Q["Hermes review"]
  Q --> R["Suggestion"]
  R --> S["Backtest"]
  S --> T["Paper test"]
  T --> U["Human approval"]
```

## Phase Order

1. Scaffold backend, extension, schema, settings, health, WebSocket.
2. Paper trading with risk engine, strategies, logs, reports, emergency stop.
3. Backtesting and strategy comparison.
4. Breeze read-only and then live integration behind safety flags.
5. Hermes suggestions and offline testing workflow.
6. Live guardrails with tiny capital, manual confirmation, and monitoring.
7. Dashboard polish and operational guides.

The current scaffold implements the first two phases enough to develop and test locally, with placeholders for later phases.
