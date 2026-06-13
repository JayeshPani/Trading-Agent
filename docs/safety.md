# Safety Rules

This project is designed for personal learning and paper trading first.

## Non-Negotiables

- No profit guarantees.
- No trade without deterministic risk checks.
- No trade without logs.
- No automatic live strategy changes.
- No Hermes direct trading.
- No DOM-click trading in ICICI Direct.
- No OTP automation.
- No broker password storage.
- No banking password storage.
- No hidden withdrawal automation.
- No F&O/options in version 1.
- No averaging down.
- No martingale.
- No penny stocks.
- No trade without stop-loss.
- No intraday position held overnight.

## Risk Engine

The risk engine is deterministic and hard-coded. Hermes suggestions and strategy plugins cannot override it.

Quantity is based on risk:

```text
quantity = floor(max_loss_per_trade / abs(entry_price - stop_loss))
```

Capital limits can reduce the quantity further. They cannot increase it above the risk-based quantity.

## Browser Extension

Allowed:

- Submit settings.
- Display status, P&L, positions, logs, and Hermes suggestions.
- Trigger backend emergency stop.

Not allowed:

- Store Breeze API keys.
- Click buy/sell buttons.
- Automate login or OTP.
- Scrape private banking data.
- Place trades directly.

## Broker Adapter

`PaperBrokerAdapter` is the default. `BreezeBrokerAdapter` is a safe placeholder and rejects live order attempts unless live controls are intentionally implemented later.
