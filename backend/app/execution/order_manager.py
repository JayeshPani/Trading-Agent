from __future__ import annotations

from dataclasses import dataclass

from app.broker.base import BrokerAdapter, OrderRequest, OrderSide, OrderType
from app.risk.engine import RiskEngine
from app.risk.rules import RiskDecision, RiskState, TradingPlan
from app.strategies.base import StrategySignal


@dataclass(slots=True)
class OrderExecutionResult:
    risk_decision: RiskDecision
    broker_order_id: str | None
    status: str
    message: str


@dataclass(slots=True)
class OrderManager:
    broker: BrokerAdapter
    risk_engine: RiskEngine

    async def evaluate_and_place(
        self,
        signal: StrategySignal,
        plan: TradingPlan,
        state: RiskState,
        *,
        manual_confirmation: bool = False,
    ) -> OrderExecutionResult:
        decision = self.risk_engine.evaluate(signal, plan, state)
        if not decision.approved:
            return OrderExecutionResult(decision, None, "rejected", decision.rejection_reason or "risk rejection")

        result = await self.broker.place_order(
            OrderRequest(
                symbol=signal.symbol,
                side=OrderSide(signal.action),
                quantity=decision.calculated_quantity,
                order_type=OrderType.LIMIT,
                limit_price=signal.entry_price,
                manual_confirmation=manual_confirmation,
            )
        )
        return OrderExecutionResult(decision, result.broker_order_id, result.status.value, result.message)
