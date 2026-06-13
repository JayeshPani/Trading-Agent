from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count

from app.broker.base import (
    BrokerAdapter,
    BrokerMode,
    HistoricalBar,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    PositionStatus,
    Quote,
)


@dataclass
class PaperBrokerAdapter(BrokerAdapter):
    starting_cash: float = 100_000.0
    quotes: dict[str, Quote] = field(default_factory=dict)
    mode: BrokerMode = BrokerMode.PAPER

    def __post_init__(self) -> None:
        self.cash = self.starting_cash
        self._orders: dict[str, OrderResult] = {}
        self._positions: dict[str, PositionSnapshot] = {}
        self._order_ids = count(1)

    def set_quote(self, symbol: str, price: float, volume: int | None = None) -> None:
        self.quotes[symbol.upper()] = Quote(symbol=symbol.upper(), last_price=price, volume=volume)

    async def get_quote(self, symbol: str) -> Quote:
        normalized = symbol.upper()
        return self.quotes.get(normalized, Quote(symbol=normalized, last_price=100.0))

    async def get_history(self, symbol: str, interval: str, limit: int) -> list[HistoricalBar]:
        return []

    async def place_order(self, request: OrderRequest) -> OrderResult:
        normalized = request.symbol.upper()
        broker_order_id = f"PAPER-{next(self._order_ids):06d}"

        rejection = self._validate_order(request)
        if rejection:
            result = OrderResult(
                accepted=False,
                broker_order_id=broker_order_id,
                status=OrderStatus.REJECTED,
                message=rejection,
            )
            self._orders[broker_order_id] = result
            return result

        quote = await self.get_quote(normalized)
        fill_price = request.limit_price or quote.last_price
        notional = fill_price * request.quantity

        if request.side is OrderSide.BUY:
            if notional > self.cash:
                result = OrderResult(
                    accepted=False,
                    broker_order_id=broker_order_id,
                    status=OrderStatus.REJECTED,
                    message="insufficient paper cash",
                )
                self._orders[broker_order_id] = result
                return result
            self.cash -= notional
            existing = self._positions.get(normalized)
            if existing and existing.status is PositionStatus.OPEN:
                total_qty = existing.quantity + request.quantity
                existing.entry_price = ((existing.entry_price * existing.quantity) + notional) / total_qty
                existing.quantity = total_qty
                existing.last_price = fill_price
            else:
                self._positions[normalized] = PositionSnapshot(
                    symbol=normalized,
                    side=OrderSide.BUY,
                    quantity=request.quantity,
                    entry_price=fill_price,
                    last_price=fill_price,
                )
        else:
            position = self._positions.get(normalized)
            if not position or position.status is PositionStatus.CLOSED or request.quantity > position.quantity:
                result = OrderResult(
                    accepted=False,
                    broker_order_id=broker_order_id,
                    status=OrderStatus.REJECTED,
                    message="paper adapter only allows SELL to close an existing long position",
                )
                self._orders[broker_order_id] = result
                return result

            self.cash += notional
            position.quantity -= request.quantity
            position.last_price = fill_price
            position.pnl += (fill_price - position.entry_price) * request.quantity
            if position.quantity == 0:
                position.status = PositionStatus.CLOSED

        result = OrderResult(
            accepted=True,
            broker_order_id=broker_order_id,
            status=OrderStatus.FILLED,
            message="paper order filled",
            filled_price=fill_price,
            filled_quantity=request.quantity,
            raw={"mode": self.mode.value, "cash": self.cash},
        )
        self._orders[broker_order_id] = result
        return result

    async def cancel_order(self, broker_order_id: str) -> OrderResult:
        order = self._orders.get(broker_order_id)
        if not order:
            return OrderResult(False, broker_order_id, OrderStatus.REJECTED, "unknown paper order")
        if order.status is OrderStatus.FILLED:
            return OrderResult(False, broker_order_id, OrderStatus.REJECTED, "filled paper orders cannot be cancelled")
        order.status = OrderStatus.CANCELLED
        return order

    async def get_orders(self) -> list[OrderResult]:
        return list(self._orders.values())

    async def get_positions(self) -> list[PositionSnapshot]:
        return list(self._positions.values())

    async def square_off_all(self) -> list[OrderResult]:
        results: list[OrderResult] = []
        for position in list(self._positions.values()):
            if position.status is PositionStatus.OPEN and position.quantity > 0:
                request = OrderRequest(
                    symbol=position.symbol,
                    side=OrderSide.SELL,
                    quantity=position.quantity,
                    order_type=OrderType.LIMIT,
                    limit_price=position.last_price,
                    metadata={"reason": "paper_square_off"},
                )
                results.append(await self.place_order(request))
        return results

    async def get_withdrawable_balance(self) -> float | None:
        return self.cash

    def _validate_order(self, request: OrderRequest) -> str | None:
        if request.quantity <= 0:
            return "quantity must be positive"
        if request.order_type is OrderType.MARKET:
            return "market orders are disabled; use limit orders"
        if request.limit_price is None or request.limit_price <= 0:
            return "limit_price is required for paper orders"
        if request.product_type.lower() not in {"cash", "intraday"}:
            return "paper adapter only supports cash/intraday equity orders"
        return None
