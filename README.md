# BreezePilot

BreezePilot is being built in small parts. Part 1 is the Chrome extension dashboard. Part 2 is the FastAPI backend control center. Part 3 is the typed ICICI Breeze REST bridge. Part 4 adds the local first-run setup flow. Parts 5-9 add quote-driven paper trading, scanner, fixed strategies, stronger risk checks, and richer explanations. Phases 10-15 add gated backtesting, manual-confirm live order preparation, autonomous live-trading locks, challenger strategy records, champion promotion, audit logs, and static-IP VPS production notes.

## Part 1: Chrome Extension

- Autopilot ON/OFF control
- Guided setup wizard for backend, local account, Breeze credentials, daily session, trading rules, and readiness
- Budget, stop-loss, target, daily max loss, max trades, mode, and allowed stock settings
- Backend URL configuration
- P&L summary, open trades, trade history, and latest AI explanation views
- Scanner shortlist, approved strategy list, and daily paper report view
- Backtests, live orders, strategy lab, and safety/audit tabs
- Emergency exit command with confirmation
- Offline/stale backend handling
- Chrome local storage only for safe preferences: backend URL, last tab, app bearer token, and draft settings

The extension does not scrape ICICI Direct, click website buttons, place orders, or store broker credentials.

## Part 2: FastAPI Backend

- Stores settings, runtime state, trade logs, risk events, and explanations in SQLite
- Supports a local single-user account with bearer-token auth after registration
- Stores Breeze credentials encrypted in backend runtime data, with env credentials still supported for local development
- Accepts the daily manually generated Breeze session key through `POST /api/session`
- Defaults to paper mode
- Gates live mode behind credentials, active session, and static-IP readiness
- Enforces deterministic risk checks before any execution path
- Provides normalized Breeze broker inspection endpoints for quote, history, portfolio, orders, and trades
- Runs scanner and paper trades from live Breeze quote/history data without placing real orders
- Stores backtest runs and strategy eligibility gates before live trading
- Keeps real order placement behind manual confirmation and live-mode/static-IP gates
- Adds kill switch, audit trail, daily report handoff, health checks, and safety status endpoints

See [backend/README.md](backend/README.md) for backend setup and run commands, and [backend/deployment.md](backend/deployment.md) for static-IP VPS notes.

## Backend API Used By Extension

- `GET /api/setup/status`
- `POST /api/account/register`
- `POST /api/account/login`
- `POST /api/account/logout`
- `PUT /api/credentials/breeze`
- `GET /api/credentials/status`
- `GET /api/dashboard`
- `GET /api/settings`
- `PUT /api/settings`
- `POST /api/session`
- `POST /api/autopilot/start`
- `POST /api/autopilot/stop`
- `POST /api/emergency-exit`
- `POST /api/paper/run-once`
- `POST /api/paper/monitor`
- `POST /api/trades/{trade_id}/paper-exit`
- `GET /api/scanner/latest`
- `POST /api/scanner/run`
- `GET /api/strategies`
- `GET /api/reports/daily`
- `POST /api/backtests/run`
- `GET /api/backtests`
- `GET /api/backtests/{run_id}`
- `GET /api/strategies/{strategy}/eligibility`
- `POST /api/live/orders/prepare`
- `POST /api/live/orders/{order_id}/confirm`
- `POST /api/live/orders/{order_id}/cancel`
- `GET /api/live/orders`
- `POST /api/live/orders/{order_id}/square-off`
- `POST /api/live/autopilot/start`
- `POST /api/live/autopilot/stop`
- `GET /api/live/autopilot/status`
- `POST /api/improvement/run-after-market`
- `GET /api/improvement/runs`
- `GET /api/improvement/status`
- `GET /api/improvement/reviews`
- `GET /api/improvement/lessons`
- `GET /api/strategy-versions`
- `GET /api/strategy-versions/{version_id}`
- `GET /api/strategy-versions/{version_id}/validation`
- `GET /api/champion`
- `GET /api/champion/rollout`
- `GET /api/challengers`
- `POST /api/challengers/{version_id}/promote`
- `POST /api/champion/rollback`
- `GET /api/health`
- `GET /api/audit`
- `GET /api/safety/status`
- `POST /api/safety/kill-switch`
- `POST /api/reports/daily/send`
- `GET /api/trades/open`
- `GET /api/trades/history`
- `GET /api/explanations/latest`

Daily self-improvement uses stored paper-trading evidence to create bounded lessons and
constrained JSON challengers. Generated code is never executed. Challengers remain in
isolated shadow trading until backtest and paper gates pass, then use staged capital
rollout with rollback checks. This process cannot guarantee profit.

The popup polls `/api/dashboard` every 5 seconds. No WebSockets are used in Part 1.

## Extension Development

```bash
npm install
npm run dev
```

## Build For Chrome

```bash
npm run build
```

Then open Chrome Extensions, enable Developer Mode, and load the generated `dist` folder as an unpacked extension.

## Safety Boundary

The extension must never store ICICI passwords, Breeze secret keys, session tokens, or API credentials. Those belong only in the backend.
