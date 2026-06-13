# Live Trading Checklist

Do not enable live trading until every item is complete.

## Configuration

- `LIVE_TRADING_ENABLED=true` is deliberately set by the user.
- Breeze API key, secret, and session token are backend environment variables only.
- Registered static IP is configured and verified.
- Dashboard token is changed from the default.
- CORS is restricted to trusted extension/dashboard origins.
- Secrets are moved to a secrets manager before serious use.

## Compliance and Broker Rules

- Official Breeze docs are re-checked.
- Rate limits are enforced: 100 calls/minute and 5,000/day.
- Order-action limit is enforced: 10 combined actions/second.
- Market orders are rejected.
- Margin and Option Plus actions are rejected.
- Product type restrictions are enforced.
- Intraday square-off rules are configured.
- Algo/non-algo classification is reviewed.

## Risk Controls

- Max capital per day configured.
- Max capital per trade configured.
- Max loss per trade configured.
- Max daily loss configured.
- Max trades per day configured.
- Max open positions configured.
- Max consecutive losses configured.
- Minimum risk/reward configured.
- Stop-loss required before order.
- Target required before order.
- No averaging down.
- No martingale.
- No F&O/options in version 1.
- No penny stocks.
- No overnight intraday positions.

## Human Controls

- Manual confirmation is required for live orders.
- Emergency stop is tested.
- Square-off is tested.
- EOD report is reviewed.
- Hermes suggestions are reviewed manually.
- Backtest and paper-trade gates pass before strategy promotion.
