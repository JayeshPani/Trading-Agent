# ICICI Breeze Trading Assistant

Paper-first, API-first scaffold for a personal intraday trading assistant. The browser extension is only a dashboard and control panel. Trading actions must be performed by the backend through broker adapters, and the default adapter is `PaperBrokerAdapter`.

This project is for learning and paper trading first. It does not guarantee profits, does not bypass broker controls, does not automate OTPs, does not store broker or bank passwords, and does not click ICICI Direct buy/sell buttons in the browser.

## Current Scope

- FastAPI backend with auth-token protected API routes.
- PostgreSQL SQLAlchemy models for sessions, signals, orders, positions, reports, Hermes suggestions, and tests.
- Paper broker simulation with limit-order-only behavior.
- Deterministic risk engine with quantity based on stop-loss risk.
- Strategy plugin interface plus VWAP, moving average, breakout, and paper-only RSI scaffolds.
- Emergency stop and square-off endpoints.
- EOD report generator.
- Hermes analysis boundary that can suggest and test changes but cannot trade or override risk.
- Withdrawal readiness and manual checklist module.
- React + TypeScript + Tailwind Chrome extension dashboard scaffold.
- Safe placeholder `BreezeBrokerAdapter` with live order calls intentionally blocked in v1.

## Setup

```bash
cd trading-agent
cp .env.example .env
```

Backend:

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

Infrastructure:

```bash
cd trading-agent
docker compose up postgres redis
```

Extension:

```bash
cd extension
npm install
npm run dev
```

For a packaged extension:

```bash
npm run build
```

Then load `extension/dist` as an unpacked extension in Chrome.

## API Defaults

- Dashboard token: `DASHBOARD_API_TOKEN` from `.env`.
- Default mode: paper.
- Live trading flag: `LIVE_TRADING_ENABLED=false`.
- Browser never receives Breeze credentials.

## Tests

```bash
cd trading-agent/backend
python3 -m pytest
```

The initial suite covers risk rejection, risk-based sizing, emergency stop, consecutive-loss stops, paper broker simulation, paper/live broker separation, square-off, redaction, and withdrawal non-automation.

## Breeze Notes

The scaffold documents the current Breeze constraints from official ICICI/Breeze docs: 100 API calls per minute, 5,000 per day, static IP requirement for order placement, 10 combined order actions per second, no market orders, and no Margin/Option Plus order placement/modification/cancellation through Breeze. Re-check official docs before enabling any live path.

## Live Trading Status

Live trading is not implemented as a default behavior. `BreezeBrokerAdapter.place_order()` returns a rejection until the live integration is deliberately implemented, tested, reviewed, and guarded by:

- `LIVE_TRADING_ENABLED=true`
- backend-only Breeze credentials
- registered static IP
- manual confirmation
- deterministic risk approval
- order-action rate limiting
- audit logging
- intraday square-off

Read [docs/live-trading-checklist.md](docs/live-trading-checklist.md) before adding live calls.
