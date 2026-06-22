# BreezePilot Backend

Part 2 adds the FastAPI backend control center for the Chrome extension.
Part 3 adds the typed ICICI Breeze REST bridge for cash-equity broker access.
Part 4 adds local setup, single-user auth, encrypted Breeze credentials, and target percentage settings.
Parts 5-9 add quote-driven paper trading, scanner, fixed strategies, stronger risk checks, and richer XAI.
Phases 10-15 add backtesting gates, manual-confirm live orders, autonomous-live eligibility locks, challenger strategy records, champion promotion, audit trails, safety status, and static-IP VPS notes.

## What It Does

- Stores trading settings in SQLite
- Tracks autopilot state, daily session state, emergency lock, trades, risk events, and explanations
- Exposes the REST API already used by the extension
- Creates one local BreezePilot account and requires bearer auth after the account exists
- Stores Breeze AppKey and Secret Key encrypted with a generated Fernet key under `backend/data`
- Can still read Breeze `APP_KEY` and `SECRET_KEY` from environment variables for local development
- Keeps paper mode as the default
- Keeps live mode gated behind credentials, daily session, and static-IP readiness
- Normalizes Breeze quote, candle, portfolio, order, trade, and square-off responses
- Runs scanner-selected paper trades using Breeze quote/history data without real order placement
- Runs historical backtests from Breeze cash-equity candles and stores pass/fail metrics
- Prepares live limit orders only after setup, session, static IP, backtest, and stock-universe gates pass
- Requires manual confirmation before any Breeze live order placement
- Tracks strategy versions, improvement runs, champion/challenger state, and rollback
- Exposes health, safety, audit, kill-switch, and daily-report handoff endpoints
- Runs an optional in-process automation runner for paper cycles, paper validation, live exits, and gated live entries

It does not add LangGraph, Docker, Redis, Celery, WebSockets, or Breeze streaming yet.
Live trading and scheduled automation remain disabled by default and must pass all gates before any live order can be confirmed or placed automatically.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set values in `.env` only when needed. Do not commit `.env`.

## Run

```bash
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

The extension default backend URL is `http://127.0.0.1:8000`.

## Local Setup API

The extension setup wizard uses these endpoints:

```http
GET /api/setup/status
POST /api/account/register
POST /api/account/login
POST /api/account/logout
PUT /api/credentials/breeze
GET /api/credentials/status
DELETE /api/credentials/breeze
```

Credential responses return only status booleans. They never return the stored AppKey or Secret Key.

## Daily Session

ICICI Breeze session key generation remains a manual daily step. Submit the generated session key to:

```http
POST /api/session
Content-Type: application/json

{"sessionKey": "daily-session-key"}
```

The API response never includes the raw session key or Breeze session token.

## Broker Inspection Endpoints

These endpoints are backend-only operational helpers. They require a valid daily Breeze session except for status.

```http
GET /api/broker/status
GET /api/broker/quote/HDFCBANK
GET /api/broker/history/HDFCBANK?interval=day
GET /api/broker/portfolio
GET /api/broker/orders
GET /api/broker/trades
```

Responses are normalized BreezePilot objects, not raw Breeze payloads. They never include the Breeze app key, secret key, raw session key, or session token.

## Paper Trading And Scanner Endpoints

```http
POST /api/scanner/run
GET /api/scanner/latest
GET /api/strategies
POST /api/paper/run-once
POST /api/paper/monitor
POST /api/trades/{trade_id}/paper-exit
GET /api/reports/daily
```

Paper trading uses live quote/history data for simulated entries and exits. It must not call Breeze live order placement.

## Backtesting, Live Orders, And Strategy Lab

```http
POST /api/backtests/run
GET /api/backtests
GET /api/backtests/{run_id}
GET /api/strategies/{strategy}/eligibility
POST /api/live/orders/prepare
POST /api/live/orders/{order_id}/confirm
POST /api/live/orders/{order_id}/cancel
POST /api/live/orders/{order_id}/refresh
GET /api/live/orders
POST /api/live/orders/{order_id}/square-off
POST /api/live/autopilot/start
POST /api/live/autopilot/stop
GET /api/live/autopilot/status
GET /api/live/readiness
POST /api/improvement/run-after-market
GET /api/improvement/runs
GET /api/improvement/status
GET /api/improvement/reviews
GET /api/improvement/lessons
GET /api/strategy-versions
GET /api/strategy-versions/{version_id}
GET /api/strategy-versions/{version_id}/validation
GET /api/champion
GET /api/champion/rollout
GET /api/challengers
POST /api/challengers/{version_id}/promote
POST /api/champion/rollback
```

Backtest gate defaults:

- at least 100 backtest trades
- profit factor `>= 1.2`
- max drawdown `<= 10%`
- win rate `>= 45%`

Live autopilot also requires static-IP readiness, a valid daily session, saved credentials, an eligible strategy, and paper-validation gates. Manual-confirm live order flow is available before autonomous live trading.

## Local Live Intraday Checklist

The backend can place live Breeze orders only when all of these are true:

- `.env` has `TRADING_MODE=live`
- `.env` has `STATIC_IP_READY=true`
- the machine running the backend is the ICICI-registered static IP
- Breeze AppKey and Secret Key are saved in backend credentials
- today's manual Breeze session key has been submitted
- trading rules are valid and set to intraday
- the selected stock is in the configured universe
- the selected strategy has passed the backtest gate
- kill switch, emergency lock, and daily loss lock are clear

Check readiness from the extension Live tab or:

```http
GET /api/live/readiness
```

If manual live readiness is true, the safe order flow is:

1. `POST /api/live/orders/prepare`
2. Review the prepared limit order in the extension.
3. `POST /api/live/orders/{order_id}/confirm`
4. `POST /api/live/orders/{order_id}/refresh`
5. Use cancel or square-off only through the provided live order actions.

Self-improvement is after-market only. Reviews use stored paper-trading evidence,
feed bounded lessons into later Kimi decisions, and may create constrained JSON
challengers. Generated Python is never executed. Challengers must pass backtest and
isolated shadow-paper gates before promotion, then use staged 10/25/50/100 percent
capital rollout with automatic rollback checks. Profit is not guaranteed.

## Production Safety Endpoints

```http
GET /api/health
GET /api/audit
GET /api/safety/status
POST /api/safety/kill-switch
POST /api/reports/daily/send
```

## Automation Runner

Scheduled automation is off by default. Enable it only after Breeze session, Kimi, and risk settings are verified:

```env
AUTOMATION_ENABLED=true
AUTO_LIVE_EXITS_ENABLED=true
AUTO_LIVE_ENTRIES_ENABLED=false
```

Automation APIs:

```http
GET /api/automation/status
POST /api/automation/start
POST /api/automation/stop
POST /api/automation/run-once
GET /api/automation/events
GET /api/paper/validation
```

Paper automation monitors open trades, runs Hermes/Kimi paper cycles, and exits simulated trades when stop-loss/target rules trigger. Live exits can be enabled before live entries. Live entries require `AUTO_LIVE_ENTRIES_ENABLED=true`, live mode, static-IP readiness, active Breeze session, passing backtest, passing paper validation, live exits enabled, and clear safety locks.

See [deployment.md](deployment.md) for static-IP VPS setup, systemd, Nginx, HTTPS, backup/restore, and health-check notes.

## Safety Defaults

- `TRADING_MODE=paper` by default
- live mode requires `BREEZE_APP_KEY`, `BREEZE_SECRET_KEY`, active session, and `STATIC_IP_READY=true`
- autopilot start requires setup completion: local account, login, credentials, active session, valid rules, and no emergency lock
- only equity symbols are accepted
- only limit orders are allowed
- paper trades are rejected for duplicate open symbols, weak liquidity, high volatility, unsafe stop-loss distance, invalid target geometry, and daily trade/loss limits
- Breeze order actions are blocked unless `exchange_code=NSE` and `product_type=cash`
- emergency exit locks new entries for the current trading day
- live emergency exit sends Breeze square-off as a limit/stoploss cash-equity order, never a market order
- real order placement is manual-confirm only until autonomous-live gates pass
- live autopilot requires backtest, paper-validation, static-IP, max-loss, max-order, max-open-position, capital, session-expiry, and emergency-lock gates
- kill switch disables live autopilot and blocks new live entries
- audit events and API responses redact broker credentials and raw session values
