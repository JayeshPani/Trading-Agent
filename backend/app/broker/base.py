from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class BrokerMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class PositionStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass(slots=True)
class Quote:
    symbol: str
    last_price: float
    bid: float | None = None
    ask: float | None = None
    volume: int | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class HistoricalBar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(slots=True)
class OrderRequest:
    symbol: str
    side: OrderSide
    quantity: int
    order_type: OrderType = OrderType.LIMIT
    limit_price: float | None = None
    product_type: str = "cash"
    session_id: str | None = None
    signal_id: str | None = None
    manual_confirmation: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OrderResult:
    accepted: bool
    broker_order_id: str | None
    status: OrderStatus
    message: str
    filled_price: float | None = None
    filled_quantity: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PositionSnapshot:
    symbol: str
    side: OrderSide
    quantity: int
    entry_price: float
    last_price: float
    status: PositionStatus = PositionStatus.OPEN
    pnl: float = 0.0


class BrokerAdapter(ABC):
    mode: BrokerMode

    @abstractmethod
    async def get_quote(self, symbol: str) -> Quote:
        """Return the latest available quote for a symbol."""

    @abstractmethod
    async def get_history(self, symbol: str, interval: str, limit: int) -> list[HistoricalBar]:
        """Return recent historical bars."""

    @abstractmethod
    async def place_order(self, request: OrderRequest) -> OrderResult:
        """Place an order through the adapter implementation."""

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> OrderResult:
        """Cancel a pending order."""

    @abstractmethod
    async def get_orders(self) -> list[OrderResult]:
        """Return order state known by the adapter."""

    @abstractmethod
    async def get_positions(self) -> list[PositionSnapshot]:
        """Return open and closed positions known by the adapter."""

    @abstractmethod
    async def square_off_all(self) -> list[OrderResult]:
        """Close open intraday positions."""

    @abstractmethod
    async def get_withdrawable_balance(self) -> float | None:
        """Return withdrawable balance if the broker exposes it safely."""
