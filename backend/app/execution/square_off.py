from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.broker.base import BrokerAdapter, OrderResult
from app.risk.rules import TradingPlan


@dataclass(slots=True)
class SquareOffService:
    broker: BrokerAdapter

    async def should_square_off(self, plan: TradingPlan, *, now: datetime | None = None) -> bool:
        current = now or datetime.now()
        return plan.auto_square_off_enabled and current.time() >= plan.square_off_time

    async def square_off_all(self) -> list[OrderResult]:
        return await self.broker.square_off_all()
