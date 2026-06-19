# One-Shot Build Prompt: BreezePilot

You are a senior full-stack engineer, quantitative trading systems engineer, security engineer, and product designer. Build the complete project described below as a production-minded, safety-first MVP. Work autonomously, make conservative engineering decisions, and do not ask follow-up questions unless an external credential or account action makes progress impossible.

Do not create a marketing website. Build the actual working Chrome extension, backend, database, trading workflow, safety gates, tests, and deployment documentation.

## 1. Product

Project name: **BreezePilot**

BreezePilot is a near-zero-human-involvement, explainable AI stock-trading agent for ICICI Direct. It trades only NSE equity stocks through the official ICICI Direct Breeze API.

The user provides:

- Budget
- Stop-loss percentage
- Target percentage
- Maximum daily loss
- Maximum trades per day
- Intraday or delivery mode
- NIFTY 50 or a custom allowed-stock list
- Autopilot state

The system then:

1. Connects to the user’s daily Breeze session.
2. Scans the allowed equity universe.
3. Calculates market and technical features.
4. Selects and ranks suitable trade candidates.
5. Uses an AI decision layer to propose an action.
6. Sends every proposal through deterministic risk checks.
7. Simulates the trade in paper mode or prepares a limit order in live mode.
8. Monitors open positions.
9. Exits according to stop-loss, target, safety, and market-close rules.
10. Explains every selection, rejection, entry, hold, stop adjustment, and exit.
11. Produces daily reports and audit records.
12. Tests improved strategy versions offline using a champion-versus-challenger workflow.

Never promise profitability. This is a risk-controlled trading automation and research system, not a guaranteed-return product.

## 2. Non-Negotiable Scope And Safety Rules

- Version 1 supports only NSE cash-equity stocks.
- Do not support options, futures, IPOs, mutual funds, crypto, commodities, BSE, or MCX.
- The Chrome extension is only a dashboard and command interface. It must never scrape ICICI Direct or click buttons on its website.
- The extension must never store the Breeze AppKey, secret key, raw daily session key, broker session token, ICICI password, or AI-provider API key.
- Broker credentials and AI-provider credentials belong only on the backend.
- The user must manually generate and submit the Breeze session key each trading day. Do not attempt to bypass or automate this broker requirement.
- Orders must originate from the backend server whose static public IP is registered with ICICI Direct.
- Use limit or permitted stop-loss orders only. Never place market orders.
- Respect current official Breeze limits and requirements. At the time of this specification, the official documentation states 100 API calls per minute, 5,000 calls per day, a combined maximum of 10 order actions per second, static-IP order routing, and no market orders. Verify these values against current official ICICI Direct documentation during implementation and make them configurable safety limits.
- AI must never directly call live broker order placement.
- The mandatory execution path is:

  `market data -> scanner -> AI proposal -> deterministic risk engine -> execution service -> broker adapter -> audit log`

- The deterministic risk engine always has final authority and can reject any AI proposal.
- Paper trading is the default.
- Live trading is disabled by default.
- Automatic live entries are the final capability enabled, only after all validation gates pass.
- Emergency exit and kill-switch controls must remain available regardless of Autopilot state.
- Do not weaken, bypass, fake, or seed validation gates to make the system appear ready.

Official references:

- Breeze API: https://api.icicidirect.com/breezeapi/documents/index.html
- Manual daily session requirement: https://www.icicidirect.com/faqs/fno/is-there-any-way-to-automate-session-key-generation

## 3. Keep The Architecture Practical

Build a single-user system. Do not add multi-tenancy, Kubernetes, Redis, Celery, Kafka, microservices, GraphQL, or unnecessary infrastructure.

Use:

- Chrome Manifest V3
- React
- TypeScript
- Vite
- Python 3.11+
- FastAPI
- Pydantic
- SQLite for the MVP
- Fernet encryption for credentials stored by the backend
- A provider-neutral HTTP client for ICICI Breeze
- A provider-neutral structured-output AI adapter, initially supporting Kimi through an OpenAI-compatible API
- Pytest for backend tests
- TypeScript build checks for the extension
- GCP VPS with a static public IP for production
- systemd for the backend process
- Nginx and HTTPS for production access

Use simple REST polling every five seconds in the extension. Do not add WebSockets to the first version.

Use plain, explicit Python workflow services for the MVP. Keep boundaries clean enough that LangGraph can be introduced later if durable multi-agent workflow orchestration becomes necessary. Do not make LangGraph a blocker for a safe working system.

Optional advanced libraries such as VectorBT, Optuna, MLflow, Phoenix, and SHAP must be integrations, not hard runtime requirements for the core dashboard, paper trading, or live safety controls.

## 4. System Architecture

Build these layers:

### Chrome Extension

The extension is the remote control and monitoring interface.

Responsibilities:

- First-run setup
- Local BreezePilot account registration/login
- Backend URL configuration
- Safe settings editing
- Daily Breeze session submission
- Autopilot controls
- Paper automation controls
- Scanner results
- Backtest results
- Live-readiness display
- Manual-confirm live order workflow
- Strategy-lab controls
- Safety status
- Audit history
- Trade history
- XAI explanations
- Emergency exit

### FastAPI Backend

The backend is the control center.

Responsibilities:

- Authentication
- Encrypted credentials
- Trading settings
- Runtime state
- Daily session lifecycle
- Breeze request signing and normalization
- API rate limiting
- Market-hours enforcement
- Market scanner
- Strategy selection
- AI decisions
- Deterministic risk checks
- Paper execution
- Live order preparation and confirmation
- Open-position monitoring
- Automatic exits
- Reports
- Backtests
- Paper-validation gates
- Live-readiness gates
- Strategy versions
- Champion/challenger promotion
- Audit logs
- Automation runner

### ICICI Breeze Adapter

Provide a single typed adapter for:

- Customer/session authentication
- Quotes
- Historical candles
- Funds
- Demat holdings
- Portfolio holdings
- Portfolio positions
- Orders
- Trades
- Limit order placement
- Order refresh/status
- Order cancellation
- Limit/stop-loss square-off

Normalize broker responses before returning them to the application. Never leak raw secrets, request signatures, checksums, session keys, or broker session tokens.

### Database

Use SQLite with clear repository/store boundaries. Persist:

- Local account and password hash
- Auth tokens or sessions
- Encrypted Breeze credentials
- Trading settings
- Runtime and Autopilot state
- Daily Breeze session metadata, but never expose raw values
- Scanner runs and candidates
- Agent decisions
- Risk decisions
- Paper trades
- Live order records
- Explanations
- Backtest runs
- Paper-validation statistics
- Strategy versions
- Champion/challenger state
- Improvement runs
- Automation runs and events
- Audit events
- Daily reports

Make schema initialization and migrations safe and repeatable.

## 5. First-Run Setup Flow

The extension must guide the user through these steps:

1. **Backend**
   - Enter the backend URL.
   - Check `GET /api/health`.
   - Show online, offline, and stale states.

2. **Local account**
   - Register the single local BreezePilot account if one does not exist.
   - Otherwise log in.
   - Use bearer-token authentication after login.

3. **Breeze credentials**
   - Submit AppKey and Secret Key to the backend.
   - Encrypt them at rest using a backend-only Fernet key.
   - Return only boolean credential status.

4. **Daily session**
   - Let the user paste the manually generated Breeze daily session key.
   - Exchange it for the broker session token on the backend.
   - Show `active`, `missing`, `expired`, or `unknown`.
   - Never return the submitted key or broker token to the extension.

5. **Trading rules**
   - Budget
   - Stop-loss percentage
   - Target percentage
   - Daily maximum loss
   - Maximum trades per day
   - Intraday or delivery
   - NIFTY 50 or custom allowed stocks

6. **Readiness**
   - Account exists
   - User is logged in
   - Credentials saved
   - Daily session active
   - Settings valid
   - No emergency lock

Only after setup is complete may normal Autopilot be enabled.

## 6. Daily User Flow

### Before Market Open

The user:

1. Opens the extension.
2. Confirms the backend is online.
3. Generates the Breeze session key manually through ICICI Direct.
4. Submits it in BreezePilot.
5. Confirms rules and budget.
6. Enables normal Autopilot.
7. Starts the automation runner if it is not already scheduled.

Once enabled on the VPS, automation must continue even if the extension, Chrome, or the user’s laptop is closed. The local SSH tunnel is only needed to view or control the VPS backend, not for VPS automation itself.

### During Market Hours

The scheduler:

- Monitors paper positions approximately every 30 seconds.
- Runs a scanner/agent cycle approximately every five minutes.
- Limits each scanner cycle to a configurable subset, defaulting to 20 symbols, to protect the Breeze API quota.
- Rotates through the allowed universe over time rather than requesting all NIFTY 50 symbols every cycle.
- Runs only during configured NSE market hours when market-hours enforcement is active.
- Avoids repeated duplicate “market closed” events.

The scanner calculates or derives:

- Price movement
- OHLCV
- Volume and relative volume
- VWAP and distance from VWAP
- RSI
- Fast and slow EMA
- Trend strength
- Volatility
- Liquidity
- Spread when available
- Support distance
- Resistance distance
- Gap up/down
- Recent candle strength
- NIFTY or broad-market direction when available
- Sector strength when available

It ranks candidates, stores positive and negative reasons, and rejects candidates with explicit reasons.

### Trade Proposal

For the best shortlist, the agent may return only one of:

- `SKIP`
- `PROPOSE_ENTRY`
- `PROPOSE_EXIT`
- `TIGHTEN_STOP`
- `HOLD`

Use strict structured JSON validated by Pydantic. Reject malformed responses, unknown actions, unknown strategies, invalid symbols, missing required prices, or inconsistent geometry.

The agent response should include:

- Action
- Stock
- Strategy
- Confidence
- Proposed entry
- Stop-loss
- Target
- Reasoning summary
- Positive reasons
- Negative reasons
- Candidates selected
- Candidates rejected

If the AI provider is unavailable or returns invalid output, fail safely with a recorded technical error. Do not disguise provider failures as legitimate market `SKIP` decisions.

### Risk Review

The deterministic risk engine checks:

- Equity-only symbol validation
- NSE and cash product only
- Symbol is in the user’s allowed universe
- Market is open when required
- Daily session is active
- Static-IP readiness for live orders
- Budget is positive and sufficient
- Quantity is an integer and correctly sized
- Stop-loss is mandatory
- Target and stop geometry are valid
- Maximum possible loss is within the per-trade and daily limits
- Daily maximum loss has not been breached
- Maximum trades per day has not been reached
- Duplicate open positions are rejected
- Maximum open positions is respected
- Liquidity is acceptable
- Volatility is acceptable
- Spread is acceptable when available
- API quota and order-rate limits are safe
- Order type is permitted
- Kill switch is clear
- Emergency lock is clear
- Live mode and all live gates are satisfied

Every decision must be stored as approved or rejected with a human-readable reason.

### Execution

In paper mode:

- Simulate fills using current quote data.
- Store the same fields that a live trade would use.
- Never call live order placement.

In manual live mode:

- Prepare a live limit order record.
- Display the complete order for human review.
- Require a separate explicit confirmation request before calling Breeze.
- Support refresh, cancellation, and limit/stop-loss square-off.

In automatic live mode:

- Automatic exits must be enabled and proven before automatic entries.
- Automatic entries require every readiness gate to pass.
- Keep strict capital and order-count locks.

### Monitoring And Exit

Monitor each open trade and exit when:

- Stop-loss is reached
- Target is reached
- A valid trailing-stop rule is reached
- Daily loss lock is triggered
- Emergency exit is activated
- Kill switch is activated
- Session or market feed becomes unsafe
- An intraday position must be squared off before market close

Record the exit price, P&L, exit reason, explanation, and audit event.

### End Of Day

Generate a report containing:

- Trading day
- Total trades
- Wins
- Losses
- Net P&L
- Open positions
- Daily loss used
- Best-performing strategy
- Worst-performing strategy
- Rule violations
- Automation errors
- Important agent lessons

The report must distinguish a valid no-trade decision from a technical failure.

## 7. Approved Initial Strategies

Implement these fixed, explainable strategy templates:

- VWAP pullback
- EMA crossover
- Momentum breakout
- Opening range breakout
- Mean reversion

Each strategy must have:

- Name
- Version
- Description
- Deterministic eligibility conditions
- Required indicators
- Entry conditions
- Stop and target rules
- Rejection rules
- Backtest metrics

Begin live eligibility with **VWAP pullback** as the first gated strategy. New strategies cannot become live automatically.

## 8. Explainable AI

Every decision must be explainable without requiring the user to inspect logs.

For selections, entries, rejections, holds, and exits, show:

- Stock
- Strategy
- Strategy version
- Entry
- Stop-loss
- Target
- Quantity
- Confidence
- Positive reasons
- Negative reasons
- Selected candidates
- Rejected candidates
- Risk-engine decision
- Risk-engine reason
- Exit reason
- Post-trade lesson

Example:

`Bought HDFCBANK because price held above VWAP, relative volume was elevated, EMA trend was positive, and the planned loss was within the configured limit. Rejected RELIANCE because volatility and stop distance were too high.`

Use rule and feature-contribution explanations for the initial deterministic strategies. If a trained ML ranking model is added, use SHAP to calculate feature contribution. Do not pretend SHAP is being used when the decision came from deterministic rules or an LLM.

## 9. AI Provider

Create a provider-neutral AI adapter named around the concept of the Hermes agent. Initially support Kimi through an OpenAI-compatible endpoint.

Environment settings:

- `HERMES_ENABLED`
- `HERMES_PROVIDER`
- `HERMES_BASE_URL`
- `HERMES_MODEL`
- `HERMES_API_KEY`
- `HERMES_TIMEOUT_SECONDS`

Requirements:

- Store the API key only on the backend.
- Use provider-supported generation parameters.
- Validate structured output.
- Include useful provider error details in internal logs without leaking credentials.
- Apply timeouts.
- Fail closed.
- The AI advises; deterministic risk rules decide.

## 10. Extension Interface

Create a compact, professional operational dashboard. Avoid a marketing hero, decorative gradients, oversized headings, or excessive card nesting. Optimize for scanning and repeated use.

Provide these tabs:

### Dashboard

- Backend connection
- Session status
- Autopilot switch
- Emergency exit
- Current P&L
- Daily loss used
- Remaining budget
- Open-trade count
- Settings editor

### Agent

- AI provider status
- Analyze-only action
- Paper-cycle action
- Live-proposal action
- Monitor action
- Automation start, stop, and run-once
- Latest structured agent decision
- Recent automation events
- Paper-validation progress

### Scanner

- Run scanner
- Latest shortlist
- Scores
- Indicators
- Positive/negative reasons
- Rejected candidates and reasons
- Approved strategy templates
- Daily report

### Backtests

- Select strategy
- Select optional stock
- Run backtest
- Show trades, win rate, profit factor, maximum drawdown, average win/loss, and pass/fail reason
- Show strategy eligibility

### Live

- Live-readiness blockers and warnings
- Static-IP status
- Manual-live readiness
- Live-Autopilot readiness
- Capital lock
- Maximum orders per day
- Prepared orders
- Confirm, refresh, cancel, and square-off actions
- Start/stop live Autopilot

### Strategy Lab

- Current champion
- Challengers
- Improvement runs
- Tools available
- Strategy versions
- Metrics and risk notes
- Promote challenger
- Roll back champion

### Safety

- Kill switch
- Emergency lock
- Daily-loss lock
- Session status
- Static-IP status
- Trading mode
- Capital lock
- Order limit
- Paper gate
- Automation errors
- Audit events

### Trades

- Open paper/live positions
- Completed trade history
- P&L
- Strategy
- Exit reason
- Manual paper-exit action where appropriate

### Explanation

- Latest complete explanation
- Positive and negative reasons
- Risk approval/rejection
- Exit reason

Required UX behavior:

- Clear loading, success, error, offline, stale, empty, disabled, warning, and locked states.
- Never display raw stack traces.
- Confirm emergency exit, kill switch, live confirmation, cancellation, square-off, promotion, and rollback actions.
- Disable unsafe actions and explain why.
- Save only backend URL, bearer token, last selected tab, and optional draft settings in Chrome storage.

## 11. Core API Contract

Implement and document these endpoints. Protect all operational endpoints with bearer auth except public health and the minimum setup endpoints needed before login.

### Setup And Authentication

- `GET /api/setup/status`
- `POST /api/account/register`
- `POST /api/account/login`
- `POST /api/account/logout`
- `PUT /api/credentials/breeze`
- `GET /api/credentials/status`
- `DELETE /api/credentials/breeze`
- `POST /api/session`

### Dashboard And Settings

- `GET /api/dashboard`
- `GET /api/settings`
- `PUT /api/settings`
- `POST /api/autopilot/start`
- `POST /api/autopilot/stop`
- `POST /api/emergency-exit`

### Broker Inspection

- `GET /api/broker/status`
- `GET /api/broker/quote/{stock_code}`
- `GET /api/broker/history/{stock_code}`
- `GET /api/broker/portfolio`
- `GET /api/broker/orders`
- `GET /api/broker/trades`

### Scanner, Paper Trading, And Reports

- `POST /api/scanner/run`
- `GET /api/scanner/latest`
- `GET /api/strategies`
- `POST /api/paper/run-once`
- `POST /api/paper/monitor`
- `POST /api/trades/{trade_id}/paper-exit`
- `GET /api/trades/open`
- `GET /api/trades/history`
- `GET /api/explanations/latest`
- `GET /api/reports/daily`
- `POST /api/reports/daily/send`

### Agent

- `GET /api/agent/status`
- `POST /api/agent/analyze`
- `POST /api/agent/paper-cycle`
- `POST /api/agent/live-proposal`
- `POST /api/agent/monitor`
- `GET /api/agent/decisions`

### Backtests

- `POST /api/backtests/run`
- `GET /api/backtests`
- `GET /api/backtests/{run_id}`
- `GET /api/strategies/{strategy}/eligibility`

### Live Orders

- `POST /api/live/orders/prepare`
- `POST /api/live/orders/{order_id}/confirm`
- `POST /api/live/orders/{order_id}/refresh`
- `POST /api/live/orders/{order_id}/cancel`
- `POST /api/live/orders/{order_id}/square-off`
- `GET /api/live/orders`
- `GET /api/live/readiness`
- `POST /api/live/autopilot/start`
- `POST /api/live/autopilot/stop`
- `GET /api/live/autopilot/status`

### Automation And Validation

- `GET /api/automation/status`
- `POST /api/automation/start`
- `POST /api/automation/stop`
- `POST /api/automation/run-once`
- `GET /api/automation/events`
- `GET /api/paper/validation`

### Strategy Improvement

- `POST /api/improvement/run-after-market`
- `GET /api/improvement/runs`
- `GET /api/strategy-versions`
- `GET /api/strategy-versions/{version_id}`
- `GET /api/champion`
- `GET /api/challengers`
- `POST /api/challengers/{version_id}/promote`
- `POST /api/champion/rollback`

### Operations And Safety

- `GET /api/health`
- `GET /api/safety/status`
- `POST /api/safety/kill-switch`
- `GET /api/audit`

Use camelCase JSON fields for the extension-facing API and clear Pydantic response models for every endpoint.

## 12. Validation-To-Live Progression

The system must enforce this exact progression:

### Phase 1: Paper Automation

Requirements:

- At least 5 real trading days
- At least 10 completed paper trades
- Profit factor at least 1.1
- No daily-loss breach
- No unresolved automation errors

Paper `SKIP` decisions are allowed when no setup qualifies. Technical failures do not count as valid strategy decisions.

### Phase 2: Backtest Gate

For live-eligible strategy versions:

- At least 100 backtest trades
- Profit factor at least 1.2
- Maximum drawdown no more than 10%
- Win rate at least 45%

Store the full settings snapshot, universe, date range, metrics, pass/fail state, and reason.

### Phase 3: Manual-Confirm Live

Only after paper and backtest requirements pass:

- Switch to live mode deliberately.
- Keep scheduled live entries disabled.
- Keep automatic live exits disabled initially.
- Set first live capital cap to ₹1,000.
- Set maximum live orders per day to 1.
- Prepare exactly one limit order.
- Require human review and explicit confirmation.
- Verify order placement, refresh, cancel, and square-off.

### Phase 4: Automatic Live Exits

After manual live flow is proven:

- Enable the automation runner.
- Enable automatic live exits.
- Keep automatic live entries disabled.
- Verify stop, target, safety, and emergency exits.

### Phase 5: Automatic Live Entries

Enable last, only when:

- Live mode is explicit
- Static IP is registered and ready
- Credentials are saved
- Daily session is active
- Backtest gate passes
- Paper gate passes
- Automatic exits are enabled
- Kill switch is clear
- Emergency lock is clear
- Daily-loss lock is clear
- Capital lock is respected
- Maximum orders and open positions are respected
- Limit-order-only rule is enforced

## 13. Self-Improvement

The system may improve:

- Strategy parameters
- Ranking weights
- Entry filters
- Exit filters
- Trailing-stop rules
- Time-window filters
- Market-regime filters
- Prompt versions
- Feature weights

It must never modify:

- User budget
- Daily maximum loss
- Allowed asset class
- Stop-loss requirement
- Kill switch
- Emergency behavior
- Broker credentials
- API/regulatory limits
- Validation thresholds without an explicit code/config change

Every completed trade should retain:

- Stock
- Timestamps
- Strategy and version
- Entry and exit
- Stop and target
- Quantity
- P&L
- Market condition
- Indicators
- AI confidence
- Explanation
- Risk result
- Prompt version
- Model/provider version
- Exit reason

Use a champion/challenger model:

- The champion is the currently approved strategy version.
- New versions are challengers.
- A challenger must pass backtest, walk-forward evaluation, paper validation, deterministic risk review, and a small-capital test.
- Promotion must be explicit and audited.
- Rollback must be supported.
- A challenger must never silently replace the champion.

Integrate when available:

- VectorBT for fast strategy evaluation
- Optuna for bounded parameter optimization
- MLflow for experiment and version tracking
- Phoenix for LLM traces and evaluations
- SHAP for trained model explanations

The core application must still run safely if these optional packages are absent.

## 14. Security And Reliability

- Hash account passwords with a suitable password-hashing algorithm.
- Encrypt stored broker credentials.
- Keep encryption key, database, and `.env` outside public/static directories.
- Redact secrets from logs, errors, API responses, audit details, and tests.
- Do not log complete Breeze payload headers.
- Validate and normalize stock symbols.
- Reject derivative-like symbols.
- Use strict CORS appropriate for the extension and configured origins.
- Apply authentication consistently.
- Add request timeouts and bounded retries only where safe.
- Do not retry an order placement blindly.
- Make order confirmation idempotent.
- Use UTC internally and display IST to the user where appropriate.
- Keep NSE market-hours logic centralized and testable.
- Use transaction boundaries for state changes that must remain consistent.
- Maintain full audit records for safety-critical changes and order actions.
- Expose a simple health endpoint that checks the app and database without exposing secrets.

## 15. Deployment

Provide:

- `.env.example`
- Local development instructions
- Extension build and unpacked-install instructions
- Database and Fernet-key locations
- GCP VPS deployment script or documented commands
- systemd service file example
- Nginx HTTPS reverse-proxy example
- Backup and restore instructions for database, Fernet key, and `.env`
- Health-check commands
- Safe environment profiles:
  - Paper automation
  - Manual live
  - Live exits
  - Live entries
- A readiness-check script that returns non-zero when live blockers remain and supports JSON output

Suggested environment variables:

- `BREEZEPILOT_DB_PATH`
- `BREEZEPILOT_ENCRYPTION_KEY_PATH`
- `TRADING_MODE=paper`
- `BREEZE_APP_KEY`
- `BREEZE_SECRET_KEY`
- `STATIC_IP_READY=false`
- `ENFORCE_MARKET_HOURS=true`
- `BREEZE_BASE_URL`
- `HERMES_ENABLED`
- `HERMES_PROVIDER`
- `HERMES_BASE_URL`
- `HERMES_MODEL`
- `HERMES_API_KEY`
- `HERMES_TIMEOUT_SECONDS`
- `AUTOMATION_ENABLED=false`
- `AUTO_PAPER_SCAN_INTERVAL_SECONDS=300`
- `AUTO_PAPER_MONITOR_INTERVAL_SECONDS=30`
- `AUTO_LIVE_EXIT_INTERVAL_SECONDS=15`
- `AUTO_LIVE_ENTRY_INTERVAL_SECONDS=300`
- `SCANNER_MAX_SYMBOLS_PER_CYCLE=20`
- `AUTO_LIVE_EXITS_ENABLED=false`
- `AUTO_LIVE_ENTRIES_ENABLED=false`

## 16. Tests

Write meaningful automated tests for:

- Registration, login, logout, and auth enforcement
- Credential encryption and response redaction
- Daily session status and expiry
- Settings validation
- Equity-only symbol validation
- NIFTY 50 and custom universes
- Breeze signing and normalized responses
- Historical interval/date formatting
- API quotas and safe errors
- Scanner ranking and rejection reasons
- Strategy selection
- Structured AI validation
- Provider failures being recorded as errors, not market skips
- Deterministic risk rejection paths
- Paper entry and exit
- Stop, target, daily loss, and market-close exits
- Backtest metrics and gates
- Paper-validation gates
- Manual live preparation and explicit confirmation
- Idempotent live confirmation
- Market-order rejection
- Static-IP and session gates
- Automatic exits before automatic entries
- Kill switch and emergency lock
- Champion promotion and rollback
- Secret redaction
- Automation scheduling and market-closed throttling

Run and pass:

- Backend test suite
- TypeScript checks
- Extension production build
- Dependency security audit

## 17. Definition Of Done

The project is complete only when:

- The extension can be built and loaded in Chrome.
- The setup wizard works from an empty database.
- Secrets remain backend-only and encrypted.
- The user can submit a daily Breeze session.
- Dashboard polling and offline behavior work.
- Scanner, approved strategies, AI proposals, risk decisions, and explanations work.
- Paper trades can open, monitor, and close without live broker placement.
- Daily reports and audit records are generated.
- Paper and backtest gates are visible and enforced.
- Live orders cannot be sent without live mode, static IP, active session, eligible strategy, valid rules, and explicit confirmation.
- Automatic live entries remain disabled until all gates pass.
- Emergency exit and kill switch are reliable.
- Strategy challengers cannot silently become champion.
- Tests and builds pass.
- Documentation explains local use, Chrome loading, VPS deployment, safety profiles, backup, and readiness checks.

## 18. Implementation Method

Build in safe vertical slices:

1. Project scaffold and extension shell
2. Backend, database, settings, and health
3. Single-user auth and encrypted credentials
4. Daily session and Breeze inspection adapter
5. Scanner and fixed strategies
6. Deterministic risk engine
7. Paper trading and monitoring
8. AI structured-decision adapter and explanations
9. Automation runner and paper validation
10. Backtests and eligibility
11. Manual-confirm live order path
12. Automatic live exits
13. Gated automatic live entries
14. Strategy lab and optional improvement integrations
15. VPS deployment, tests, security review, and documentation

After each slice, run the relevant tests and keep the application usable. Never enable real-money behavior merely to demonstrate that the UI works.
