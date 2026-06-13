from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Literal

Mode = Literal["paper", "live"]


@dataclass(frozen=True, slots=True)
class TradingPlan:
    capital: float
    mode: Mode = "paper"
    allowed_symbols: tuple[str, ...] = ("RELIANCE", "INFY", "TCS", "HDFCBANK", "ICICIBANK")
    max_daily_loss: float = 500.0
    max_loss_per_trade: float = 100.0
    max_capital_per_trade: float = 2_500.0
    max_trades_per_day: int = 5
    max_open_positions: int = 2
    max_consecutive_losses: int = 2
    min_risk_reward: float = 1.5
    min_price: float = 50.0
    max_intraday_volatility_pct: float = 4.0
    stop_new_trades_after: time = time(14, 45)
    square_off_time: time = time(15, 10)
    live_trading_enabled: bool = False
    auto_square_off_enabled: bool = True
    emergency_stop_enabled: bool = True
    strategy_names: tuple[str, ...] = ("vwap_trend", "moving_average_crossover", "breakout_with_volume")

    def normalized_symbols(self) -> set[str]:
        return {symbol.upper() for symbol in self.allowed_symbols}


@dataclass(frozen=True, slots=True)
class RiskState:
    realized_pnl: float = 0.0
    trades_today: int = 0
    open_positions: int = 0
    consecutive_losses: int = 0
    emergency_stopped: bool = False
    current_volatility_pct: float = 0.0
    pending_order_actions_this_second: int = 0
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RiskDecision:
    approved: bool
    rejection_reason: str | None
    calculated_quantity: int
    max_loss: float
    checks: dict[str, bool | float | int | str]
