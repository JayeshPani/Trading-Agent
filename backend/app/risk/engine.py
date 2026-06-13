from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import floor

from app.risk.rules import RiskDecision, RiskState, TradingPlan
from app.strategies.base import StrategySignal


@dataclass(slots=True)
class RiskEngine:
    """Hard-coded risk engine.

    This module is intentionally deterministic and does not accept overrides from
    Hermes or strategy plugins. Any rejected signal must stay rejected.
    """

    def evaluate(
        self,
        signal: StrategySignal,
        plan: TradingPlan,
        state: RiskState,
        *,
        now: datetime | None = None,
    ) -> RiskDecision:
        now = now or datetime.now()
        checks: dict[str, bool | float | int | str] = {
            "mode": plan.mode,
            "hermes_override_ignored": bool(signal.metadata.get("hermes_override")),
        }

        rejection = self._first_rejection(signal, plan, state, now, checks)
        if rejection:
            return RiskDecision(False, rejection, 0, 0.0, checks)

        stop_distance = abs(signal.entry_price - signal.stop_loss)
        risk_quantity = floor(plan.max_loss_per_trade / stop_distance)
        capital_quantity = floor(min(plan.capital, plan.max_capital_per_trade) / signal.entry_price)
        quantity = min(risk_quantity, capital_quantity)
        checks["risk_quantity"] = risk_quantity
        checks["capital_quantity"] = capital_quantity
        checks["calculated_quantity"] = quantity

        if quantity <= 0:
            return RiskDecision(False, "calculated quantity is zero", 0, 0.0, checks)

        max_loss = round(quantity * stop_distance, 2)
        if max_loss > plan.max_loss_per_trade:
            return RiskDecision(False, "calculated loss exceeds per-trade risk", 0, max_loss, checks)

        return RiskDecision(True, None, quantity, max_loss, checks)

    def _first_rejection(
        self,
        signal: StrategySignal,
        plan: TradingPlan,
        state: RiskState,
        now: datetime,
        checks: dict[str, bool | float | int | str],
    ) -> str | None:
        if state.emergency_stopped:
            return "emergency stop is active"
        if plan.capital <= 0:
            return "capital must be positive"
        if plan.mode == "live" and not plan.live_trading_enabled:
            return "live trading is blocked by LIVE_TRADING_ENABLED=false"
        if signal.symbol.upper() not in plan.normalized_symbols():
            return "symbol is outside the allowed list"
        if signal.entry_price <= 0:
            return "entry price must be positive"
        if signal.entry_price < plan.min_price:
            return "stock price is below minimum allowed price"
        if signal.stop_loss <= 0:
            return "stop-loss must exist before trade"
        if signal.target <= 0:
            return "target must exist before trade"
        if signal.action == "BUY" and signal.stop_loss >= signal.entry_price:
            return "buy stop-loss must be below entry"
        if signal.action == "BUY" and signal.target <= signal.entry_price:
            return "buy target must be above entry"
        if signal.action == "SELL" and signal.stop_loss <= signal.entry_price:
            return "sell stop-loss must be above entry"
        if signal.action == "SELL" and signal.target >= signal.entry_price:
            return "sell target must be below entry"

        checks["risk_reward"] = signal.risk_reward
        if signal.risk_reward < plan.min_risk_reward:
            return "risk/reward is below configured minimum"

        daily_loss_used = abs(min(state.realized_pnl, 0.0))
        checks["daily_loss_used"] = daily_loss_used
        if daily_loss_used >= plan.max_daily_loss:
            return "daily loss limit reached"
        if state.trades_today >= plan.max_trades_per_day:
            return "maximum trades per day reached"
        if state.open_positions >= plan.max_open_positions:
            return "maximum open positions reached"
        if state.consecutive_losses >= plan.max_consecutive_losses:
            return "maximum consecutive losses reached"
        if state.current_volatility_pct > plan.max_intraday_volatility_pct:
            return "symbol volatility exceeds configured limit"
        if state.pending_order_actions_this_second >= 10:
            return "broker order-action rate limit would be exceeded"
        if now.time() >= plan.stop_new_trades_after:
            return "new-trade cutoff time has passed"
        if now.time() >= plan.square_off_time:
            return "square-off time has passed"
        return None
