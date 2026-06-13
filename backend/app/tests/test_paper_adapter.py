from __future__ import annotations

import pytest

from app.broker.base import OrderRequest, OrderSide, OrderStatus, OrderType
from app.broker.paper_adapter import PaperBrokerAdapter


@pytest.mark.asyncio
async def test_paper_broker_simulates_limit_buy_and_sell() -> None:
    broker = PaperBrokerAdapter(starting_cash=10_000)
    broker.set_quote("RELIANCE", 100)
    buy = await broker.place_order(
        OrderRequest("RELIANCE", OrderSide.BUY, 10, OrderType.LIMIT, limit_price=100)
    )
    assert buy.accepted
    assert buy.status is OrderStatus.FILLED
    assert broker.cash == 9_000

    sell = await broker.place_order(
        OrderRequest("RELIANCE", OrderSide.SELL, 10, OrderType.LIMIT, limit_price=105)
    )
    assert sell.accepted
    assert broker.cash == 10_050


@pytest.mark.asyncio
async def test_paper_broker_rejects_market_orders() -> None:
    broker = PaperBrokerAdapter(starting_cash=10_000)
    result = await broker.place_order(OrderRequest("RELIANCE", OrderSide.BUY, 1, OrderType.MARKET))
    assert not result.accepted
    assert result.status is OrderStatus.REJECTED
    assert "market orders are disabled" in result.message


@pytest.mark.asyncio
async def test_breeze_adapter_is_not_called_in_paper_mode() -> None:
    from app.broker.base import BrokerMode
    from app.broker.factory import BrokerFactoryConfig, build_broker

    broker = build_broker(BrokerFactoryConfig(mode=BrokerMode.PAPER, starting_cash=5_000))
    assert isinstance(broker, PaperBrokerAdapter)
