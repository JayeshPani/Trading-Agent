from __future__ import annotations

import json
import sqlite3
import threading
import uuid
import atexit
from datetime import datetime
from pathlib import Path
from typing import Any

from .schemas import (
    AgentDecision,
    AuditEvent,
    AutomationEvent,
    AutomationRun,
    AutomationStatus,
    BacktestMetrics,
    BacktestRun,
    DailyReport,
    Explanation,
    ImprovementRun,
    LiveOrder,
    OpenTrade,
    PaperValidationStatus,
    ScannerCandidate,
    ScannerResult,
    StrategyVersion,
    StrategyTemplate,
    TradeHistoryItem,
    TradingSettings,
)
from .state import RuntimeState
from .time_utils import current_trading_day, now_utc, utc_iso

DEFAULT_SETTINGS = TradingSettings(
    budget=10000,
    stopLossPercent=1.5,
    dailyMaxLoss=300,
    maxTradesPerDay=3,
    targetPercent=3,
    mode="intraday",
    stockPreset="NIFTY 50",
    allowedStocks=[],
)


class SQLiteStore:
    def __init__(self, database_path: str):
        self.database_path = database_path
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(database_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        atexit.register(self.close)
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    budget REAL NOT NULL,
                    stop_loss_percent REAL NOT NULL,
                    daily_max_loss REAL NOT NULL,
                    max_trades_per_day INTEGER NOT NULL,
                    target_percent REAL NOT NULL DEFAULT 3,
                    mode TEXT NOT NULL,
                    stock_preset TEXT NOT NULL,
                    allowed_stocks TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runtime_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    autopilot_enabled INTEGER NOT NULL,
                    emergency_lock INTEGER NOT NULL,
                    trading_day TEXT NOT NULL,
                    session_status TEXT NOT NULL,
                    session_created_at TEXT,
                    session_expires_at TEXT,
                    session_token TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    stock TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    target REAL NOT NULL,
                    live_pnl REAL NOT NULL,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    exit_price REAL,
                    pnl REAL,
                    exit_reason TEXT,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    paper INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS explanations (
                    id TEXT PRIMARY KEY,
                    trade_id TEXT,
                    stock TEXT,
                    strategy TEXT,
                    confidence REAL,
                    summary TEXT NOT NULL,
                    positive_reasons TEXT NOT NULL,
                    negative_reasons TEXT NOT NULL,
                    selected_candidates TEXT NOT NULL DEFAULT '[]',
                    rejected_candidates TEXT NOT NULL DEFAULT '[]',
                    risk_decision TEXT NOT NULL,
                    risk_reason TEXT NOT NULL,
                    exit_reason TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS risk_events (
                    id TEXT PRIMARY KEY,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    stock TEXT,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS breeze_credentials (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    app_key_encrypted TEXT NOT NULL,
                    secret_key_encrypted TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    trade_id TEXT,
                    stock TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price REAL NOT NULL,
                    order_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    paper INTEGER NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS strategies (
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (name, version)
                );

                CREATE TABLE IF NOT EXISTS scanner_results (
                    id TEXT PRIMARY KEY,
                    stock TEXT NOT NULL,
                    score REAL NOT NULL,
                    strategy TEXT,
                    strategy_version TEXT,
                    last_price REAL NOT NULL,
                    indicators TEXT NOT NULL,
                    positive_reasons TEXT NOT NULL,
                    negative_reasons TEXT NOT NULL,
                    rejected INTEGER NOT NULL,
                    rejection_reason TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scanner_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    generated_at TEXT NOT NULL,
                    broker_status TEXT NOT NULL,
                    broker_error_count INTEGER NOT NULL,
                    broker_error TEXT
                );

                CREATE TABLE IF NOT EXISTS daily_reports (
                    trading_day TEXT PRIMARY KEY,
                    pnl REAL NOT NULL,
                    trades_count INTEGER NOT NULL,
                    wins INTEGER NOT NULL,
                    losses INTEGER NOT NULL,
                    open_trades INTEGER NOT NULL,
                    daily_loss_used REAL NOT NULL,
                    generated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id TEXT PRIMARY KEY,
                    strategy TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    stock_universe TEXT NOT NULL,
                    from_date TEXT NOT NULL,
                    to_date TEXT NOT NULL,
                    settings_snapshot TEXT NOT NULL,
                    metrics TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS live_orders (
                    id TEXT PRIMARY KEY,
                    stock TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price REAL NOT NULL,
                    order_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    broker_order_id TEXT,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS improvement_runs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    tools_available TEXT NOT NULL,
                    created_version_id TEXT,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS strategy_versions (
                    id TEXT PRIMARY KEY,
                    strategy TEXT NOT NULL,
                    version TEXT NOT NULL,
                    source_version_id TEXT,
                    parameters TEXT NOT NULL,
                    backtest_metrics TEXT NOT NULL,
                    paper_metrics TEXT NOT NULL,
                    risk_notes TEXT NOT NULL,
                    promotion_status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS safety_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    kill_switch_active INTEGER NOT NULL,
                    live_autopilot_enabled INTEGER NOT NULL,
                    capital_lock REAL NOT NULL,
                    max_order_limit INTEGER NOT NULL,
                    max_open_positions INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    context TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_decisions (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    stock TEXT,
                    strategy TEXT,
                    side TEXT,
                    quantity INTEGER,
                    entry_price REAL,
                    stop_loss REAL,
                    target REAL,
                    confidence REAL NOT NULL,
                    reasons TEXT NOT NULL,
                    risks TEXT NOT NULL,
                    expires_at TEXT,
                    risk_decision TEXT NOT NULL,
                    risk_reason TEXT NOT NULL,
                    trade_id TEXT,
                    order_id TEXT,
                    integrity_status TEXT,
                    integrity_message TEXT,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id TEXT PRIMARY KEY,
                    trading_day TEXT NOT NULL,
                    snapshot TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS automation_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled INTEGER NOT NULL,
                    last_paper_scan_at TEXT,
                    last_paper_monitor_at TEXT,
                    last_live_exit_at TEXT,
                    last_live_entry_at TEXT,
                    latest_error TEXT,
                    broker_health TEXT NOT NULL DEFAULT 'healthy',
                    consecutive_broker_failures INTEGER NOT NULL DEFAULT 0,
                    last_broker_success_at TEXT,
                    latest_broker_error TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS automation_runs (
                    id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    summary TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS automation_events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column("settings", "target_percent", "REAL NOT NULL DEFAULT 3")
            self._ensure_column("explanations", "selected_candidates", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column("explanations", "rejected_candidates", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column("agent_decisions", "integrity_status", "TEXT")
            self._ensure_column("agent_decisions", "integrity_message", "TEXT")
            self._ensure_column(
                "automation_state",
                "broker_health",
                "TEXT NOT NULL DEFAULT 'healthy'",
            )
            self._ensure_column(
                "automation_state",
                "consecutive_broker_failures",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column("automation_state", "last_broker_success_at", "TEXT")
            self._ensure_column("automation_state", "latest_broker_error", "TEXT")
            self._backfill_agent_integrity()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _backfill_agent_integrity(self) -> None:
        self._conn.execute(
            """
            UPDATE agent_decisions
            SET integrity_status = 'system_error',
                integrity_message = 'Historical Kimi response could not be parsed.'
            WHERE integrity_status IS NULL
              AND (
                    reasons = '["Hermes did not produce a usable decision."]'
                    OR risks LIKE '%Hermes returned invalid structured JSON%'
                    OR risks LIKE '%Hermes request failed%'
                  )
            """
        )
        self._conn.execute(
            """
            UPDATE agent_decisions
            SET integrity_status = 'genuine',
                integrity_message = 'Historical decision was accepted as a direct Kimi response.'
            WHERE integrity_status IS NULL
            """
        )

    def get_settings(self) -> TradingSettings:
        with self._lock:
            row = self._conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
            if row is None:
                self.save_settings(DEFAULT_SETTINGS)
                return DEFAULT_SETTINGS
            return self._settings_from_row(row)

    def save_settings(self, settings: TradingSettings) -> None:
        payload = settings.model_dump(by_alias=False)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO settings (
                    id, budget, stop_loss_percent, daily_max_loss, max_trades_per_day,
                    target_percent, mode, stock_preset, allowed_stocks, updated_at
                )
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    budget = excluded.budget,
                    stop_loss_percent = excluded.stop_loss_percent,
                    daily_max_loss = excluded.daily_max_loss,
                    max_trades_per_day = excluded.max_trades_per_day,
                    target_percent = excluded.target_percent,
                    mode = excluded.mode,
                    stock_preset = excluded.stock_preset,
                    allowed_stocks = excluded.allowed_stocks,
                    updated_at = excluded.updated_at
                """,
                (
                    payload["budget"],
                    payload["stop_loss_percent"],
                    payload["daily_max_loss"],
                    payload["max_trades_per_day"],
                    payload["target_percent"],
                    payload["mode"],
                    payload["stock_preset"],
                    json.dumps(payload["allowed_stocks"]),
                    utc_iso(),
                ),
            )

    def account_exists(self) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM account WHERE id = 1").fetchone()
        return row is not None

    def create_account(self, username: str, password_hash: str, salt: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO account (id, username, password_hash, salt, created_at)
                VALUES (1, ?, ?, ?, ?)
                """,
                (username, password_hash, salt, utc_iso()),
            )

    def get_account(self) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT username, password_hash, salt FROM account WHERE id = 1"
            ).fetchone()

    def save_auth_token(self, token_hash: str, username: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO auth_tokens (token_hash, username, created_at)
                VALUES (?, ?, ?)
                """,
                (token_hash, username, utc_iso()),
            )

    def auth_token_exists(self, token_hash: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM auth_tokens WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        return row is not None

    def delete_auth_token(self, token_hash: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (token_hash,))

    def save_breeze_credentials(self, app_key_encrypted: str, secret_key_encrypted: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO breeze_credentials (id, app_key_encrypted, secret_key_encrypted, updated_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    app_key_encrypted = excluded.app_key_encrypted,
                    secret_key_encrypted = excluded.secret_key_encrypted,
                    updated_at = excluded.updated_at
                """,
                (app_key_encrypted, secret_key_encrypted, utc_iso()),
            )

    def get_breeze_credentials(self) -> tuple[str, str] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT app_key_encrypted, secret_key_encrypted
                FROM breeze_credentials
                WHERE id = 1
                """
            ).fetchone()
        if row is None:
            return None
        return row["app_key_encrypted"], row["secret_key_encrypted"]

    def delete_breeze_credentials(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM breeze_credentials WHERE id = 1")

    def breeze_credentials_saved(self) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM breeze_credentials WHERE id = 1"
            ).fetchone()
        return row is not None

    def get_runtime(self) -> RuntimeState:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runtime_state WHERE id = 1").fetchone()
            if row is None:
                state = RuntimeState(trading_day=current_trading_day())
                self.save_runtime(state)
                return state

            state = RuntimeState(
                autopilot_enabled=bool(row["autopilot_enabled"]),
                emergency_lock=bool(row["emergency_lock"]),
                trading_day=row["trading_day"],
                session_status=row["session_status"],
                session_created_at=row["session_created_at"],
                session_expires_at=row["session_expires_at"],
                session_token=row["session_token"],
            )
            return self._refresh_runtime_day_and_session(state)

    def save_runtime(self, state: RuntimeState) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO runtime_state (
                    id, autopilot_enabled, emergency_lock, trading_day, session_status,
                    session_created_at, session_expires_at, session_token, updated_at
                )
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    autopilot_enabled = excluded.autopilot_enabled,
                    emergency_lock = excluded.emergency_lock,
                    trading_day = excluded.trading_day,
                    session_status = excluded.session_status,
                    session_created_at = excluded.session_created_at,
                    session_expires_at = excluded.session_expires_at,
                    session_token = excluded.session_token,
                    updated_at = excluded.updated_at
                """,
                (
                    int(state.autopilot_enabled),
                    int(state.emergency_lock),
                    state.trading_day,
                    state.session_status,
                    state.session_created_at,
                    state.session_expires_at,
                    state.session_token,
                    utc_iso(),
                ),
            )

    def insert_trade(
        self,
        *,
        stock: str,
        side: str,
        quantity: int,
        entry_price: float,
        stop_loss: float,
        target: float,
        mode: str,
        strategy: str,
        strategy_version: str,
        paper: bool,
        status: str = "open",
    ) -> str:
        trade_id = str(uuid.uuid4())
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO trades (
                    id, stock, side, quantity, entry_price, stop_loss, target, live_pnl,
                    status, mode, strategy, strategy_version, opened_at, paper
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade_id,
                    stock,
                    side,
                    quantity,
                    entry_price,
                    stop_loss,
                    target,
                    status,
                    mode,
                    strategy,
                    strategy_version,
                    utc_iso(),
                    int(paper),
                ),
            )
            self._conn.execute(
                """
                INSERT INTO orders (
                    id, trade_id, stock, side, quantity, price, order_type, status,
                    paper, reason, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'limit', 'filled', ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    trade_id,
                    stock,
                    side,
                    quantity,
                    entry_price,
                    int(paper),
                    "Paper fill" if paper else "Live order submitted",
                    utc_iso(),
                    utc_iso(),
                ),
            )
        return trade_id

    def close_open_trades(self, exit_reason: str) -> int:
        open_trades = self.list_open_trades()
        with self._lock, self._conn:
            for trade in open_trades:
                exit_price = trade.entry_price + (trade.live_pnl / max(trade.quantity, 1))
                self._conn.execute(
                    """
                    UPDATE trades
                    SET status = 'exited', exit_price = ?, pnl = ?, exit_reason = ?, closed_at = ?
                    WHERE id = ?
                    """,
                    (exit_price, trade.live_pnl, exit_reason, utc_iso(), trade.id),
                )
        return len(open_trades)

    def get_open_trade(self, trade_id: str) -> OpenTrade | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, stock, side, quantity, entry_price, stop_loss, target,
                       live_pnl, status, strategy
                FROM trades
                WHERE id = ? AND status = 'open'
                """,
                (trade_id,),
            ).fetchone()
        return self._open_trade_from_row(row) if row else None

    def update_open_trade_pnl(self, trade_id: str, current_price: float) -> OpenTrade | None:
        with self._lock, self._conn:
            row = self._conn.execute(
                """
                SELECT id, stock, side, quantity, entry_price, stop_loss, target,
                       live_pnl, status, strategy
                FROM trades
                WHERE id = ? AND status = 'open'
                """,
                (trade_id,),
            ).fetchone()
            if row is None:
                return None
            pnl = self._calculate_pnl(row["side"], row["entry_price"], current_price, row["quantity"])
            self._conn.execute("UPDATE trades SET live_pnl = ? WHERE id = ?", (pnl, trade_id))
            refreshed = dict(row)
            refreshed["live_pnl"] = pnl
        return self._open_trade_from_mapping(refreshed)

    def close_trade(
        self,
        *,
        trade_id: str,
        exit_price: float,
        exit_reason: str,
        status: str,
    ) -> TradeHistoryItem | None:
        with self._lock, self._conn:
            row = self._conn.execute(
                """
                SELECT id, stock, side, quantity, entry_price, stop_loss, target,
                       live_pnl, status, strategy
                FROM trades
                WHERE id = ? AND status = 'open'
                """,
                (trade_id,),
            ).fetchone()
            if row is None:
                return None
            pnl = self._calculate_pnl(row["side"], row["entry_price"], exit_price, row["quantity"])
            closed_at = utc_iso()
            self._conn.execute(
                """
                UPDATE trades
                SET status = ?, live_pnl = ?, exit_price = ?, pnl = ?, exit_reason = ?, closed_at = ?
                WHERE id = ?
                """,
                (status, pnl, exit_price, pnl, exit_reason, closed_at, trade_id),
            )
            history_row = {
                "id": row["id"],
                "stock": row["stock"],
                "side": row["side"],
                "quantity": row["quantity"],
                "entry_price": row["entry_price"],
                "exit_price": exit_price,
                "pnl": pnl,
                "strategy": row["strategy"],
                "status": status,
                "exit_reason": exit_reason,
                "closed_at": closed_at,
            }
        return self._history_from_mapping(history_row)

    def list_open_trades(self) -> list[OpenTrade]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, stock, side, quantity, entry_price, stop_loss, target,
                       live_pnl, status, strategy
                FROM trades
                WHERE status = 'open'
                ORDER BY opened_at DESC
                """
            ).fetchall()
        return [self._open_trade_from_row(row) for row in rows]

    def list_trade_history(self, limit: int = 50) -> list[TradeHistoryItem]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, stock, side, quantity, entry_price, exit_price, pnl, strategy,
                       status, exit_reason, closed_at
                FROM trades
                WHERE status != 'open'
                ORDER BY closed_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._history_from_row(row) for row in rows]

    def count_trades_today(self) -> int:
        day = current_trading_day()
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS total FROM trades WHERE substr(opened_at, 1, 10) = ?",
                (day,),
            ).fetchone()
        return int(row["total"])

    def daily_loss_used(self) -> float:
        day = current_trading_day()
        with self._lock:
            closed = self._conn.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END), 0) AS loss
                FROM trades
                WHERE status != 'open' AND substr(closed_at, 1, 10) = ?
                """,
                (day,),
            ).fetchone()
            open_loss = self._conn.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN live_pnl < 0 THEN ABS(live_pnl) ELSE 0 END), 0) AS loss
                FROM trades
                WHERE status = 'open'
                """
            ).fetchone()
        return float(closed["loss"] + open_loss["loss"])

    def current_pnl(self) -> float:
        day = current_trading_day()
        with self._lock:
            closed = self._conn.execute(
                """
                SELECT COALESCE(SUM(pnl), 0) AS pnl
                FROM trades
                WHERE status != 'open' AND substr(closed_at, 1, 10) = ?
                """,
                (day,),
            ).fetchone()
            open_row = self._conn.execute(
                "SELECT COALESCE(SUM(live_pnl), 0) AS pnl FROM trades WHERE status = 'open'"
            ).fetchone()
        return float(closed["pnl"] + open_row["pnl"])

    def open_capital_used(self) -> float:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COALESCE(SUM(entry_price * quantity), 0) AS capital
                FROM trades
                WHERE status = 'open'
                """
            ).fetchone()
        return float(row["capital"])

    def open_risk_used(self) -> float:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COALESCE(SUM(ABS(entry_price - stop_loss) * quantity), 0) AS risk
                FROM trades
                WHERE status = 'open'
                """
            ).fetchone()
        return float(row["risk"])

    def insert_explanation(self, explanation: Explanation) -> str:
        explanation_id = str(uuid.uuid4())
        payload = explanation.model_dump(by_alias=False)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO explanations (
                    id, trade_id, stock, strategy, confidence, summary, positive_reasons,
                    negative_reasons, selected_candidates, rejected_candidates,
                    risk_decision, risk_reason, exit_reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    explanation_id,
                    payload["trade_id"],
                    payload["stock"],
                    payload["strategy"],
                    payload["confidence"],
                    payload["summary"],
                    json.dumps(payload["positive_reasons"]),
                    json.dumps(payload["negative_reasons"]),
                    json.dumps(payload["selected_candidates"]),
                    json.dumps(payload["rejected_candidates"]),
                    payload["risk_decision"],
                    payload["risk_reason"],
                    payload["exit_reason"],
                    utc_iso(),
                ),
            )
        return explanation_id

    def latest_explanation(self) -> Explanation | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT trade_id, stock, strategy, confidence, summary, positive_reasons,
                       negative_reasons, selected_candidates, rejected_candidates,
                       risk_decision, risk_reason, exit_reason
                FROM explanations
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return self._explanation_from_row(row)

    def insert_risk_event(
        self, *, decision: str, reason: str, stock: str | None, details: dict[str, Any]
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO risk_events (id, decision, reason, stock, details, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), decision, reason, stock, json.dumps(details), utc_iso()),
            )

    def upsert_strategies(self, strategies: list[StrategyTemplate]) -> None:
        with self._lock, self._conn:
            for strategy in strategies:
                payload = strategy.model_dump(by_alias=False)
                self._conn.execute(
                    """
                    INSERT INTO strategies (name, version, description, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(name, version) DO UPDATE SET
                        description = excluded.description
                    """,
                    (payload["name"], payload["version"], payload["description"], utc_iso()),
                )

    def list_strategies(self) -> list[StrategyTemplate]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT name, version, description
                FROM strategies
                ORDER BY name, version
                """
            ).fetchall()
        return [
            StrategyTemplate(name=row["name"], version=row["version"], description=row["description"])
            for row in rows
        ]

    def save_scanner_result(self, result: ScannerResult) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM scanner_results")
            self._conn.execute(
                """
                INSERT INTO scanner_state (
                    id, generated_at, broker_status, broker_error_count, broker_error
                )
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    generated_at = excluded.generated_at,
                    broker_status = excluded.broker_status,
                    broker_error_count = excluded.broker_error_count,
                    broker_error = excluded.broker_error
                """,
                (
                    result.generated_at,
                    result.broker_status,
                    result.broker_error_count,
                    result.broker_error,
                ),
            )
            for candidate in result.candidates:
                payload = candidate.model_dump(by_alias=False)
                self._conn.execute(
                    """
                    INSERT INTO scanner_results (
                        id, stock, score, strategy, strategy_version, last_price, indicators,
                        positive_reasons, negative_reasons, rejected, rejection_reason, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        payload["stock_code"],
                        payload["score"],
                        payload["strategy"],
                        payload["strategy_version"],
                        payload["last_price"],
                        json.dumps(payload["indicators"]),
                        json.dumps(payload["positive_reasons"]),
                        json.dumps(payload["negative_reasons"]),
                        int(payload["rejected"]),
                        payload["rejection_reason"],
                        result.generated_at,
                    ),
                )

    def latest_scanner_result(self) -> ScannerResult:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT stock, score, strategy, strategy_version, last_price, indicators,
                       positive_reasons, negative_reasons, rejected, rejection_reason, created_at
                FROM scanner_results
                ORDER BY score DESC, stock ASC
                """
            ).fetchall()
            state = self._conn.execute(
                "SELECT * FROM scanner_state WHERE id = 1"
            ).fetchone()
        candidates = [self._scanner_candidate_from_row(row) for row in rows]
        generated_at = (
            state["generated_at"]
            if state is not None
            else rows[0]["created_at"]
            if rows
            else utc_iso()
        )
        return ScannerResult(
            generatedAt=generated_at,
            candidates=candidates,
            shortlist=[candidate for candidate in candidates if not candidate.rejected],
            brokerStatus=state["broker_status"] if state is not None else "healthy",
            brokerErrorCount=state["broker_error_count"] if state is not None else 0,
            brokerError=state["broker_error"] if state is not None else None,
        )

    def save_daily_report(self, report: DailyReport) -> None:
        payload = report.model_dump(by_alias=False)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO daily_reports (
                    trading_day, pnl, trades_count, wins, losses, open_trades,
                    daily_loss_used, generated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trading_day) DO UPDATE SET
                    pnl = excluded.pnl,
                    trades_count = excluded.trades_count,
                    wins = excluded.wins,
                    losses = excluded.losses,
                    open_trades = excluded.open_trades,
                    daily_loss_used = excluded.daily_loss_used,
                    generated_at = excluded.generated_at
                """,
                (
                    payload["trading_day"],
                    payload["pnl"],
                    payload["trades_count"],
                    payload["wins"],
                    payload["losses"],
                    payload["open_trades"],
                    payload["daily_loss_used"],
                    payload["generated_at"],
                ),
            )

    def build_daily_report(self) -> DailyReport:
        day = current_trading_day()
        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    COUNT(*) AS trades_count,
                    COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
                    COALESCE(SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END), 0) AS losses
                FROM trades
                WHERE status != 'open' AND substr(closed_at, 1, 10) = ?
                """,
                (day,),
            ).fetchone()
        report = DailyReport(
            tradingDay=day,
            pnl=self.current_pnl(),
            tradesCount=int(row["trades_count"]),
            wins=int(row["wins"]),
            losses=int(row["losses"]),
            openTrades=len(self.list_open_trades()),
            dailyLossUsed=self.daily_loss_used(),
            generatedAt=utc_iso(),
        )
        self.save_daily_report(report)
        return report

    def save_backtest_run(self, run: BacktestRun) -> None:
        payload = run.model_dump(by_alias=False)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO backtest_runs (
                    id, strategy, strategy_version, stock_universe, from_date, to_date,
                    settings_snapshot, metrics, passed, reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["id"],
                    payload["strategy"],
                    payload["strategy_version"],
                    json.dumps(payload["stock_universe"]),
                    payload["from_date"],
                    payload["to_date"],
                    json.dumps(payload["settings_snapshot"]),
                    json.dumps(payload["metrics"]),
                    int(payload["passed"]),
                    payload["reason"],
                    payload["created_at"],
                ),
            )
        self.insert_audit_event(
            event_type="backtest.run",
            message=f"Backtest completed for {run.strategy}.",
            details={"passed": run.passed, "reason": run.reason},
        )

    def list_backtests(self) -> list[BacktestRun]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM backtest_runs ORDER BY created_at DESC"
            ).fetchall()
        return [self._backtest_from_row(row) for row in rows]

    def get_backtest(self, run_id: str) -> BacktestRun | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM backtest_runs WHERE id = ?", (run_id,)).fetchone()
        return self._backtest_from_row(row) if row else None

    def latest_passed_backtest(self, strategy: str) -> BacktestRun | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM backtest_runs
                WHERE strategy = ? AND passed = 1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (strategy,),
            ).fetchone()
        return self._backtest_from_row(row) if row else None

    def latest_passed_backtest_any(self) -> BacktestRun | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM backtest_runs
                WHERE passed = 1
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        return self._backtest_from_row(row) if row else None

    def save_live_order(self, order: LiveOrder) -> None:
        payload = order.model_dump(by_alias=False)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO live_orders (
                    id, stock, side, quantity, price, order_type, status, strategy,
                    broker_order_id, reason, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    broker_order_id = excluded.broker_order_id,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
                """,
                (
                    payload["id"],
                    payload["stock_code"],
                    payload["side"],
                    payload["quantity"],
                    payload["price"],
                    payload["order_type"],
                    payload["status"],
                    payload["strategy"],
                    payload["broker_order_id"],
                    payload["reason"],
                    payload["created_at"],
                    payload["updated_at"],
                ),
            )

    def get_live_order(self, order_id: str) -> LiveOrder | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM live_orders WHERE id = ?", (order_id,)).fetchone()
        return self._live_order_from_row(row) if row else None

    def list_live_orders(self) -> list[LiveOrder]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM live_orders ORDER BY created_at DESC").fetchall()
        return [self._live_order_from_row(row) for row in rows]

    def count_live_orders_today(self) -> int:
        day = current_trading_day()
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS total FROM live_orders WHERE substr(created_at, 1, 10) = ?",
                (day,),
            ).fetchone()
        return int(row["total"])

    def save_strategy_version(self, version: StrategyVersion) -> None:
        payload = version.model_dump(by_alias=False)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO strategy_versions (
                    id, strategy, version, source_version_id, parameters, backtest_metrics,
                    paper_metrics, risk_notes, promotion_status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    backtest_metrics = excluded.backtest_metrics,
                    paper_metrics = excluded.paper_metrics,
                    risk_notes = excluded.risk_notes,
                    promotion_status = excluded.promotion_status
                """,
                (
                    payload["id"],
                    payload["strategy"],
                    payload["version"],
                    payload["source_version_id"],
                    json.dumps(payload["parameters"]),
                    json.dumps(payload["backtest_metrics"]),
                    json.dumps(payload["paper_metrics"]),
                    json.dumps(payload["risk_notes"]),
                    payload["promotion_status"],
                    payload["created_at"],
                ),
            )

    def get_strategy_version(self, version_id: str) -> StrategyVersion | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM strategy_versions WHERE id = ?",
                (version_id,),
            ).fetchone()
        return self._strategy_version_from_row(row) if row else None

    def list_strategy_versions(self) -> list[StrategyVersion]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM strategy_versions ORDER BY created_at DESC"
            ).fetchall()
        return [self._strategy_version_from_row(row) for row in rows]

    def list_challengers(self) -> list[StrategyVersion]:
        return [
            version for version in self.list_strategy_versions()
            if version.promotion_status in {"generated", "backtested", "paper_validated", "candidate"}
        ]

    def current_champion(self) -> StrategyVersion | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM strategy_versions
                WHERE promotion_status = 'champion'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        return self._strategy_version_from_row(row) if row else None

    def promote_strategy_version(self, version_id: str) -> StrategyVersion | None:
        version = self.get_strategy_version(version_id)
        if version is None:
            return None
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE strategy_versions SET promotion_status = 'previous_champion' WHERE promotion_status = 'champion'"
            )
            self._conn.execute(
                "UPDATE strategy_versions SET promotion_status = 'champion' WHERE id = ?",
                (version_id,),
            )
        promoted = self.get_strategy_version(version_id)
        self.insert_audit_event(
            event_type="strategy.promote",
            message=f"Promoted {version.strategy} {version.version} to champion.",
            details={"versionId": version_id},
        )
        return promoted

    def rollback_champion(self) -> StrategyVersion | None:
        with self._lock, self._conn:
            previous = self._conn.execute(
                """
                SELECT * FROM strategy_versions
                WHERE promotion_status = 'previous_champion'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
            if previous is None:
                return None
            current_id = previous["id"]
            self._conn.execute(
                "UPDATE strategy_versions SET promotion_status = 'rejected' WHERE promotion_status = 'champion'"
            )
            self._conn.execute(
                "UPDATE strategy_versions SET promotion_status = 'champion' WHERE id = ?",
                (current_id,),
            )
        self.insert_audit_event(
            event_type="strategy.rollback",
            message="Rolled back to previous champion.",
            details={"versionId": current_id},
        )
        return self.get_strategy_version(current_id)

    def save_improvement_run(self, run: ImprovementRun) -> None:
        payload = run.model_dump(by_alias=False)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO improvement_runs (
                    id, status, tools_available, created_version_id, reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["id"],
                    payload["status"],
                    json.dumps(payload["tools_available"]),
                    payload["created_version_id"],
                    payload["reason"],
                    payload["created_at"],
                ),
            )

    def list_improvement_runs(self) -> list[ImprovementRun]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM improvement_runs ORDER BY created_at DESC"
            ).fetchall()
        return [self._improvement_from_row(row) for row in rows]

    def get_safety_state(self) -> dict[str, Any]:
        with self._lock, self._conn:
            row = self._conn.execute("SELECT * FROM safety_state WHERE id = 1").fetchone()
            if row is None:
                self._conn.execute(
                    """
                    INSERT INTO safety_state (
                        id, kill_switch_active, live_autopilot_enabled, capital_lock,
                        max_order_limit, max_open_positions, updated_at
                    )
                    VALUES (1, 0, 0, 10000, 3, 1, ?)
                    """,
                    (utc_iso(),),
                )
                row = self._conn.execute("SELECT * FROM safety_state WHERE id = 1").fetchone()
        return dict(row)

    def set_kill_switch(self, active: bool) -> None:
        state = self.get_safety_state()
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE safety_state
                SET kill_switch_active = ?, live_autopilot_enabled = 0, updated_at = ?
                WHERE id = 1
                """,
                (int(active), utc_iso()),
            )
        self.insert_audit_event(
            event_type="safety.kill_switch",
            message="Kill switch activated." if active else "Kill switch cleared.",
            details={"previous": bool(state["kill_switch_active"]), "active": active},
        )

    def set_live_autopilot(self, enabled: bool) -> None:
        self.get_safety_state()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE safety_state SET live_autopilot_enabled = ?, updated_at = ? WHERE id = 1",
                (int(enabled), utc_iso()),
            )

    def insert_audit_event(
        self, *, event_type: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO audit_events (id, event_type, message, details, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), event_type, message, json.dumps(details or {}), utc_iso()),
            )

    def list_audit_events(self, limit: int = 100) -> list[AuditEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._audit_from_row(row) for row in rows]

    def create_agent_run(self, *, source: str, mode: str, context: dict[str, Any]) -> str:
        run_id = str(uuid.uuid4())
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO agent_runs (id, source, mode, context, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, source, mode, json.dumps(context), utc_iso()),
            )
        return run_id

    def save_agent_decision(self, decision: AgentDecision) -> AgentDecision:
        payload = decision.model_dump(by_alias=False)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO agent_decisions (
                    id, run_id, action, stock, strategy, side, quantity, entry_price,
                    stop_loss, target, confidence, reasons, risks, expires_at,
                    risk_decision, risk_reason, trade_id, order_id, integrity_status,
                    integrity_message, source, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    risk_decision = excluded.risk_decision,
                    risk_reason = excluded.risk_reason,
                    trade_id = excluded.trade_id,
                    order_id = excluded.order_id,
                    integrity_status = excluded.integrity_status,
                    integrity_message = excluded.integrity_message
                """,
                (
                    payload["id"],
                    payload["run_id"],
                    payload["action"],
                    payload["stock"],
                    payload["strategy"],
                    payload["side"],
                    payload["quantity"],
                    payload["entry_price"],
                    payload["stop_loss"],
                    payload["target"],
                    payload["confidence"],
                    json.dumps(payload["reasons"]),
                    json.dumps(payload["risks"]),
                    payload["expires_at"],
                    payload["risk_decision"],
                    payload["risk_reason"],
                    payload["trade_id"],
                    payload["order_id"],
                    payload["integrity_status"],
                    payload["integrity_message"],
                    payload["source"],
                    payload["created_at"],
                ),
            )
        return decision

    def list_agent_decisions(self, limit: int = 50) -> list[AgentDecision]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agent_decisions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._agent_decision_from_row(row) for row in rows]

    def agent_health(self) -> dict[str, Any]:
        decisions = self.list_agent_decisions(limit=100)
        consecutive_errors = 0
        last_valid_at: str | None = None
        for decision in decisions:
            if decision.integrity_status == "system_error" and last_valid_at is None:
                consecutive_errors += 1
            elif decision.integrity_status != "system_error":
                if last_valid_at is None:
                    last_valid_at = decision.created_at
        latest = decisions[0] if decisions else None
        return {
            "healthy": consecutive_errors == 0,
            "consecutive_system_errors": consecutive_errors,
            "latest_integrity_status": latest.integrity_status if latest else None,
            "last_valid_decision_at": last_valid_at,
        }

    def save_portfolio_snapshot(self, snapshot: dict[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO portfolio_snapshots (id, trading_day, snapshot, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), current_trading_day(), json.dumps(snapshot), utc_iso()),
            )

    def get_automation_state(self) -> dict[str, Any]:
        with self._lock, self._conn:
            row = self._conn.execute("SELECT * FROM automation_state WHERE id = 1").fetchone()
            if row is None:
                self._conn.execute(
                    """
                    INSERT INTO automation_state (
                        id, enabled, last_paper_scan_at, last_paper_monitor_at,
                        last_live_exit_at, last_live_entry_at, latest_error,
                        broker_health, consecutive_broker_failures,
                        last_broker_success_at, latest_broker_error, updated_at
                    )
                    VALUES (1, 0, NULL, NULL, NULL, NULL, NULL,
                            'healthy', 0, NULL, NULL, ?)
                    """,
                    (utc_iso(),),
                )
                row = self._conn.execute("SELECT * FROM automation_state WHERE id = 1").fetchone()
        return dict(row)

    def set_automation_enabled(self, enabled: bool) -> None:
        self.get_automation_state()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE automation_state SET enabled = ?, updated_at = ? WHERE id = 1",
                (int(enabled), utc_iso()),
            )

    def update_automation_timestamp(self, field: str) -> None:
        allowed = {
            "last_paper_scan_at",
            "last_paper_monitor_at",
            "last_live_exit_at",
            "last_live_entry_at",
        }
        if field not in allowed:
            raise ValueError("Unsupported automation timestamp field.")
        self.get_automation_state()
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE automation_state SET {field} = ?, updated_at = ? WHERE id = 1",
                (utc_iso(), utc_iso()),
            )

    def set_automation_error(self, message: str | None) -> None:
        self.get_automation_state()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE automation_state SET latest_error = ?, updated_at = ? WHERE id = 1",
                (message, utc_iso()),
            )

    def record_broker_success(self) -> None:
        self.get_automation_state()
        timestamp = utc_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE automation_state
                SET broker_health = 'healthy',
                    consecutive_broker_failures = 0,
                    last_broker_success_at = ?,
                    latest_broker_error = NULL,
                    latest_error = CASE
                        WHEN latest_error = latest_broker_error THEN NULL
                        ELSE latest_error
                    END,
                    updated_at = ?
                WHERE id = 1
                """,
                (timestamp, timestamp),
            )

    def record_broker_degraded(self, message: str, *, had_success: bool) -> None:
        self.get_automation_state()
        timestamp = utc_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE automation_state
                SET broker_health = 'degraded',
                    consecutive_broker_failures = 0,
                    last_broker_success_at = CASE
                        WHEN ? THEN ?
                        ELSE last_broker_success_at
                    END,
                    latest_broker_error = ?,
                    updated_at = ?
                WHERE id = 1
                """,
                (int(had_success), timestamp, message, timestamp),
            )

    def record_broker_failure(self, message: str, *, threshold: int = 3) -> dict[str, Any]:
        state = self.get_automation_state()
        failures = int(state.get("consecutive_broker_failures") or 0) + 1
        health = "unavailable" if failures >= threshold else "degraded"
        persistent_error = message if health == "unavailable" else None
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE automation_state
                SET broker_health = ?,
                    consecutive_broker_failures = ?,
                    latest_broker_error = ?,
                    latest_error = CASE
                        WHEN ? IS NOT NULL THEN ?
                        ELSE latest_error
                    END,
                    updated_at = ?
                WHERE id = 1
                """,
                (
                    health,
                    failures,
                    message,
                    persistent_error,
                    persistent_error,
                    utc_iso(),
                ),
            )
        return self.get_automation_state()

    def create_automation_run(self, *, mode: str, status: str, summary: str) -> str:
        run_id = str(uuid.uuid4())
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO automation_runs (id, mode, status, started_at, summary)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, mode, status, utc_iso(), summary),
            )
        return run_id

    def finish_automation_run(self, run_id: str, *, status: str, summary: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE automation_runs
                SET status = ?, summary = ?, finished_at = ?
                WHERE id = ?
                """,
                (status, summary, utc_iso(), run_id),
            )

    def insert_automation_event(
        self,
        *,
        event_type: str,
        severity: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO automation_events (id, event_type, severity, message, details, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    event_type,
                    severity,
                    message,
                    json.dumps(details or {}),
                    utc_iso(),
                ),
            )
        if severity == "error":
            self.set_automation_error(message)

    def list_automation_events(self, limit: int = 100) -> list[AutomationEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM automation_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._automation_event_from_row(row) for row in rows]

    def list_automation_runs(self, limit: int = 50) -> list[AutomationRun]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM automation_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._automation_run_from_row(row) for row in rows]

    def automation_error_count(self) -> int:
        day = current_trading_day()
        broker_unavailable = self.get_automation_state().get("broker_health") == "unavailable"
        with self._lock:
            resolved_after = self._conn.execute(
                """
                SELECT MAX(created_at) AS resolved_at
                FROM automation_events
                WHERE severity != 'error'
                  AND event_type IN ('automation.completed', 'automation.config')
                  AND substr(created_at, 1, 10) = ?
                """,
                (day,),
            ).fetchone()["resolved_at"]
            params: tuple[Any, ...]
            resolved_filter = ""
            if resolved_after:
                resolved_filter = "AND created_at > ?"
                params = (day, resolved_after)
            else:
                params = (day,)
            row = self._conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM automation_events
                WHERE severity = 'error' AND substr(created_at, 1, 10) = ?
                  AND event_type != 'automation.broker_unavailable'
                {resolved_filter}
                """,
                params,
            ).fetchone()
        return int(row["total"]) + int(broker_unavailable)

    def paper_validation_status(
        self,
        *,
        required_days: int = 5,
        required_trades: int = 10,
        min_profit_factor: float = 1.1,
    ) -> PaperValidationStatus:
        settings = self.get_settings()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT substr(closed_at, 1, 10) AS trading_day,
                       COUNT(*) AS trades_count,
                       COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0) AS gains,
                       COALESCE(SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END), 0) AS losses
                FROM trades
                WHERE paper = 1 AND status != 'open' AND closed_at IS NOT NULL
                GROUP BY substr(closed_at, 1, 10)
                """
            ).fetchall()
        days = len(rows)
        completed_trades = sum(int(row["trades_count"]) for row in rows)
        gains = sum(float(row["gains"]) for row in rows)
        losses = sum(float(row["losses"]) for row in rows)
        profit_factor = gains / losses if losses else (gains if gains else 0.0)
        daily_loss_breached = any(float(row["losses"]) >= settings.daily_max_loss for row in rows)
        automation_errors = self.automation_error_count()
        agent_errors = int(self.agent_health()["consecutive_system_errors"])
        failures: list[str] = []
        if days < required_days:
            failures.append(f"Needs at least {required_days} paper-trading days.")
        if completed_trades < required_trades:
            failures.append(f"Needs at least {required_trades} completed paper trades.")
        if profit_factor < min_profit_factor:
            failures.append("Paper profit factor is below 1.1.")
        if daily_loss_breached:
            failures.append("A paper daily-loss lock was breached.")
        if automation_errors > 0:
            failures.append("Automation errors are present today.")
        if agent_errors > 0:
            failures.append("Unresolved agent decision errors are present.")
        return PaperValidationStatus(
            eligible=not failures,
            reason="Paper validation passed." if not failures else " ".join(failures),
            days=days,
            completedTrades=completed_trades,
            profitFactor=round(profit_factor, 2),
            dailyLossBreached=daily_loss_breached,
            unresolvedAutomationErrors=automation_errors,
            unresolvedAgentErrors=agent_errors,
            requiredDays=required_days,
            requiredTrades=required_trades,
        )

    def _refresh_runtime_day_and_session(self, state: RuntimeState) -> RuntimeState:
        changed = False
        today = current_trading_day()
        if state.trading_day != today:
            state = RuntimeState(trading_day=today)
            changed = True
        elif state.session_expires_at:
            try:
                expires = datetime.fromisoformat(state.session_expires_at)
            except ValueError:
                expires = None
            if expires is not None and expires <= now_utc():
                state.session_status = "expired"
                state.session_token = None
                changed = True
        if changed:
            self.save_runtime(state)
        return state

    @staticmethod
    def _settings_from_row(row: sqlite3.Row) -> TradingSettings:
        return TradingSettings(
            budget=row["budget"],
            stopLossPercent=row["stop_loss_percent"],
            dailyMaxLoss=row["daily_max_loss"],
            maxTradesPerDay=row["max_trades_per_day"],
            targetPercent=row["target_percent"],
            mode=row["mode"],
            stockPreset=row["stock_preset"],
            allowedStocks=json.loads(row["allowed_stocks"]),
        )

    @staticmethod
    def _open_trade_from_row(row: sqlite3.Row) -> OpenTrade:
        return OpenTrade(
            id=row["id"],
            stock=row["stock"],
            side=row["side"],
            quantity=row["quantity"],
            entryPrice=row["entry_price"],
            stopLoss=row["stop_loss"],
            target=row["target"],
            livePnl=row["live_pnl"],
            status=row["status"],
            strategy=row["strategy"],
        )

    @staticmethod
    def _open_trade_from_mapping(row: dict[str, Any]) -> OpenTrade:
        return OpenTrade(
            id=row["id"],
            stock=row["stock"],
            side=row["side"],
            quantity=row["quantity"],
            entryPrice=row["entry_price"],
            stopLoss=row["stop_loss"],
            target=row["target"],
            livePnl=row["live_pnl"],
            status=row["status"],
            strategy=row["strategy"],
        )

    @staticmethod
    def _history_from_row(row: sqlite3.Row) -> TradeHistoryItem:
        return TradeHistoryItem(
            id=row["id"],
            stock=row["stock"],
            side=row["side"],
            quantity=row["quantity"],
            entryPrice=row["entry_price"],
            exitPrice=row["exit_price"] or 0,
            pnl=row["pnl"] or 0,
            strategy=row["strategy"],
            status=row["status"],
            exitReason=row["exit_reason"] or "",
            closedAt=row["closed_at"] or "",
        )

    @staticmethod
    def _history_from_mapping(row: dict[str, Any]) -> TradeHistoryItem:
        return TradeHistoryItem(
            id=row["id"],
            stock=row["stock"],
            side=row["side"],
            quantity=row["quantity"],
            entryPrice=row["entry_price"],
            exitPrice=row["exit_price"] or 0,
            pnl=row["pnl"] or 0,
            strategy=row["strategy"],
            status=row["status"],
            exitReason=row["exit_reason"] or "",
            closedAt=row["closed_at"] or "",
        )

    @staticmethod
    def _explanation_from_row(row: sqlite3.Row) -> Explanation:
        return Explanation(
            tradeId=row["trade_id"],
            stock=row["stock"],
            strategy=row["strategy"],
            confidence=row["confidence"],
            summary=row["summary"],
            positiveReasons=json.loads(row["positive_reasons"]),
            negativeReasons=json.loads(row["negative_reasons"]),
            selectedCandidates=json.loads(row["selected_candidates"]),
            rejectedCandidates=json.loads(row["rejected_candidates"]),
            riskDecision=row["risk_decision"],
            riskReason=row["risk_reason"],
            exitReason=row["exit_reason"],
        )

    @staticmethod
    def _scanner_candidate_from_row(row: sqlite3.Row) -> ScannerCandidate:
        return ScannerCandidate(
            stockCode=row["stock"],
            score=row["score"],
            strategy=row["strategy"],
            strategyVersion=row["strategy_version"],
            lastPrice=row["last_price"],
            indicators=json.loads(row["indicators"]),
            positiveReasons=json.loads(row["positive_reasons"]),
            negativeReasons=json.loads(row["negative_reasons"]),
            rejected=bool(row["rejected"]),
            rejectionReason=row["rejection_reason"],
        )

    @staticmethod
    def _backtest_from_row(row: sqlite3.Row) -> BacktestRun:
        metrics = json.loads(row["metrics"])
        return BacktestRun(
            id=row["id"],
            strategy=row["strategy"],
            strategyVersion=row["strategy_version"],
            stockUniverse=json.loads(row["stock_universe"]),
            fromDate=row["from_date"],
            toDate=row["to_date"],
            settingsSnapshot=json.loads(row["settings_snapshot"]),
            metrics=BacktestMetrics(
                winRate=_metric(metrics, "win_rate", "winRate"),
                profitFactor=_metric(metrics, "profit_factor", "profitFactor"),
                maxDrawdown=_metric(metrics, "max_drawdown", "maxDrawdown"),
                averageProfit=_metric(metrics, "average_profit", "averageProfit"),
                averageLoss=_metric(metrics, "average_loss", "averageLoss"),
                tradesCount=_metric(metrics, "trades_count", "tradesCount"),
                bestMarketCondition=_metric(metrics, "best_market_condition", "bestMarketCondition"),
                worstMarketCondition=_metric(metrics, "worst_market_condition", "worstMarketCondition"),
            ),
            passed=bool(row["passed"]),
            reason=row["reason"],
            createdAt=row["created_at"],
        )

    @staticmethod
    def _live_order_from_row(row: sqlite3.Row) -> LiveOrder:
        return LiveOrder(
            id=row["id"],
            stockCode=row["stock"],
            side=row["side"],
            quantity=row["quantity"],
            price=row["price"],
            orderType=row["order_type"],
            status=row["status"],
            strategy=row["strategy"],
            brokerOrderId=row["broker_order_id"],
            reason=row["reason"],
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )

    @staticmethod
    def _strategy_version_from_row(row: sqlite3.Row) -> StrategyVersion:
        return StrategyVersion(
            id=row["id"],
            strategy=row["strategy"],
            version=row["version"],
            sourceVersionId=row["source_version_id"],
            parameters=json.loads(row["parameters"]),
            backtestMetrics=json.loads(row["backtest_metrics"]),
            paperMetrics=json.loads(row["paper_metrics"]),
            riskNotes=json.loads(row["risk_notes"]),
            promotionStatus=row["promotion_status"],
            createdAt=row["created_at"],
        )

    @staticmethod
    def _improvement_from_row(row: sqlite3.Row) -> ImprovementRun:
        return ImprovementRun(
            id=row["id"],
            status=row["status"],
            toolsAvailable=json.loads(row["tools_available"]),
            createdVersionId=row["created_version_id"],
            reason=row["reason"],
            createdAt=row["created_at"],
        )

    @staticmethod
    def _audit_from_row(row: sqlite3.Row) -> AuditEvent:
        return AuditEvent(
            id=row["id"],
            eventType=row["event_type"],
            message=row["message"],
            details=json.loads(row["details"]),
            createdAt=row["created_at"],
        )

    @staticmethod
    def _agent_decision_from_row(row: sqlite3.Row) -> AgentDecision:
        return AgentDecision(
            id=row["id"],
            runId=row["run_id"],
            action=row["action"],
            stock=row["stock"],
            strategy=row["strategy"],
            side=row["side"],
            quantity=row["quantity"],
            entryPrice=row["entry_price"],
            stopLoss=row["stop_loss"],
            target=row["target"],
            confidence=row["confidence"],
            reasons=json.loads(row["reasons"]),
            risks=json.loads(row["risks"]),
            expiresAt=row["expires_at"],
            riskDecision=row["risk_decision"],
            riskReason=row["risk_reason"],
            tradeId=row["trade_id"],
            orderId=row["order_id"],
            integrityStatus=row["integrity_status"] or "genuine",
            integrityMessage=row["integrity_message"] or "Decision integrity was not recorded.",
            source=row["source"],
            createdAt=row["created_at"],
        )

    @staticmethod
    def _automation_event_from_row(row: sqlite3.Row) -> AutomationEvent:
        return AutomationEvent(
            id=row["id"],
            eventType=row["event_type"],
            severity=row["severity"],
            message=row["message"],
            details=json.loads(row["details"]),
            createdAt=row["created_at"],
        )

    @staticmethod
    def _automation_run_from_row(row: sqlite3.Row) -> AutomationRun:
        return AutomationRun(
            id=row["id"],
            mode=row["mode"],
            status=row["status"],
            startedAt=row["started_at"],
            finishedAt=row["finished_at"],
            summary=row["summary"],
        )

    @staticmethod
    def _calculate_pnl(side: str, entry_price: float, current_price: float, quantity: int) -> float:
        if side == "SELL":
            return round((entry_price - current_price) * quantity, 2)
        return round((current_price - entry_price) * quantity, 2)


def _metric(metrics: dict[str, Any], snake_name: str, alias_name: str) -> Any:
    return metrics[snake_name] if snake_name in metrics else metrics[alias_name]
