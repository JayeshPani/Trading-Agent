from __future__ import annotations

from datetime import datetime, time

from app.risk.engine import RiskEngine
from app.risk.rules import RiskState, TradingPlan
from app.strategies.base import StrategySignal


def buy_signal(**overrides: object) -> StrategySignal:
    data = {
        "symbol": "RELIANCE",
        "action": "BUY",
        "confidence": 0.7,
        "entry_price": 100.0,
        "stop_loss": 98.0,
        "target": 104.0,
        "invalidation_reason": "breakdown",
        "timeframe": "intraday",
        "explanation": "test",
        "strategy_name": "test_strategy",
    }
    data.update(overrides)
    return StrategySignal(**data)


def test_quantity_is_based_on_risk_not_buying_power() -> None:
    plan = TradingPlan(capital=10_000, max_loss_per_trade=100, max_capital_per_trade=10_000)
    decision = RiskEngine().evaluate(buy_signal(), plan, RiskState(), now=datetime(2026, 1, 1, 10, 0))
    assert decision.approved
    assert decision.calculated_quantity == 50
    assert decision.max_loss == 100


def test_rejects_symbol_outside_allowed_list() -> None:
    plan = TradingPlan(capital=10_000, allowed_symbols=("INFY",))
    decision = RiskEngine().evaluate(buy_signal(symbol="RELIANCE"), plan, RiskState(), now=datetime(2026, 1, 1, 10, 0))
    assert not decision.approved
    assert decision.rejection_reason == "symbol is outside the allowed list"


def test_daily_loss_limit_stops_trading() -> None:
    plan = TradingPlan(capital=10_000, max_daily_loss=500)
    state = RiskState(realized_pnl=-500)
    decision = RiskEngine().evaluate(buy_signal(), plan, state, now=datetime(2026, 1, 1, 10, 0))
    assert not decision.approved
    assert decision.rejection_reason == "daily loss limit reached"


def test_consecutive_losses_stop_trading() -> None:
    plan = TradingPlan(capital=10_000, max_consecutive_losses=2)
    state = RiskState(consecutive_losses=2)
    decision = RiskEngine().evaluate(buy_signal(), plan, state, now=datetime(2026, 1, 1, 10, 0))
    assert not decision.approved
    assert decision.rejection_reason == "maximum consecutive losses reached"


def test_emergency_stop_rejects_trade() -> None:
    decision = RiskEngine().evaluate(
        buy_signal(),
        TradingPlan(capital=10_000),
        RiskState(emergency_stopped=True),
        now=datetime(2026, 1, 1, 10, 0),
    )
    assert not decision.approved
    assert decision.rejection_reason == "emergency stop is active"


def test_hermes_cannot_override_risk_rules() -> None:
    signal = buy_signal(symbol="PENNY", metadata={"hermes_override": True})
    decision = RiskEngine().evaluate(signal, TradingPlan(capital=10_000), RiskState(), now=datetime(2026, 1, 1, 10, 0))
    assert not decision.approved
    assert decision.checks["hermes_override_ignored"] is True


def test_live_mode_blocked_without_flag() -> None:
    plan = TradingPlan(capital=10_000, mode="live", live_trading_enabled=False)
    decision = RiskEngine().evaluate(buy_signal(), plan, RiskState(), now=datetime(2026, 1, 1, 10, 0))
    assert not decision.approved
    assert decision.rejection_reason == "live trading is blocked by LIVE_TRADING_ENABLED=false"


def test_new_trades_blocked_after_cutoff() -> None:
    plan = TradingPlan(capital=10_000, stop_new_trades_after=time(14, 45))
    decision = RiskEngine().evaluate(buy_signal(), plan, RiskState(), now=datetime(2026, 1, 1, 14, 46))
    assert not decision.approved
    assert decision.rejection_reason == "new-trade cutoff time has passed"
