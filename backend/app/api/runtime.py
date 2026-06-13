from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import count
from typing import Any

from app.broker.paper_adapter import PaperBrokerAdapter
from app.hermes.suggestion_manager import SuggestionManager


@dataclass
class RuntimeState:
    settings: dict[str, Any] = field(
        default_factory=lambda: {
            "amount": 10_000.0,
            "risk_level": "conservative",
            "mode": "paper",
            "allowed_symbols": ["RELIANCE", "INFY", "TCS", "HDFCBANK", "ICICIBANK"],
            "max_daily_loss": 500.0,
            "max_loss_per_trade": 100.0,
            "strategy_selection": ["vwap_trend", "moving_average_crossover"],
            "auto_square_off_enabled": True,
            "emergency_stop_enabled": True,
        }
    )
    paper_broker: PaperBrokerAdapter = field(default_factory=lambda: PaperBrokerAdapter(starting_cash=10_000.0))
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    signals: dict[str, dict[str, Any]] = field(default_factory=dict)
    trade_logs: list[dict[str, Any]] = field(default_factory=list)
    reports: dict[str, dict[str, Any]] = field(default_factory=dict)
    emergency_stopped: bool = False
    latest_session_id: str | None = None
    suggestions: SuggestionManager = field(default_factory=SuggestionManager)
    _session_ids: count = field(default_factory=lambda: count(1))

    def next_session_id(self) -> str:
        return f"session-{next(self._session_ids):06d}"

    def log(self, message: str, level: str = "INFO", metadata: dict[str, Any] | None = None) -> None:
        self.trade_logs.append(
            {
                "created_at": datetime.now(UTC).isoformat(),
                "session_id": self.latest_session_id,
                "level": level,
                "message": message,
                "metadata": metadata or {},
            }
        )

    def reset_for_session(self) -> None:
        self.paper_broker = PaperBrokerAdapter(starting_cash=float(self.settings["amount"]))
        self.emergency_stopped = False


runtime = RuntimeState()
