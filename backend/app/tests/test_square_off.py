from __future__ import annotations

from datetime import datetime

import pytest

from app.broker.base import OrderRequest, OrderSide, OrderType
from app.broker.paper_adapter import PaperBrokerAdapter
from app.execution.square_off import SquareOffService
from app.risk.rules import TradingPlan


@pytest.mark.asyncio
async def test_square_off_is_triggered_after_configured_time() -> None:
    broker = PaperBrokerAdapter(starting_cash=10_000)
    broker.set_quote("RELIANCE", 100)
    await broker.place_order(OrderRequest("RELIANCE", OrderSide.BUY, 5, OrderType.LIMIT, limit_price=100))
    service = SquareOffService(broker)

    assert await service.should_square_off(TradingPlan(capital=10_000), now=datetime(2026, 1, 1, 15, 11))
    results = await service.square_off_all()
    assert results
    assert all(result.accepted for result in results)
