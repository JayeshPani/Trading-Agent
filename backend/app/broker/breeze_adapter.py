from __future__ import annotations

from dataclasses import dataclass

from app.broker.base import (
    BrokerAdapter,
    BrokerMode,
    HistoricalBar,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    Quote,
)


@dataclass(slots=True)
class BreezeAdapterConfig:
    api_key: str | None
    api_secret: str | None
    session_token: str | None
    live_trading_enabled: bool = False
    require_manual_confirmation: bool = True
    registered_static_ip: str | None = None


class BreezeBrokerAdapter(BrokerAdapter):
    """Safe placeholder for ICICI Direct Breeze integration.

    This class intentionally does not perform live order placement yet. Real calls must
    be added only after reviewing current Breeze docs, enabling LIVE_TRADING_ENABLED,
    confirming the registered static IP, and adding integration tests/mocks.
    """

    mode = BrokerMode.LIVE

    def __init__(self, config: BreezeAdapterConfig) -> None:
        self.config = config
        self._client = None

    async def get_quote(self, symbol: str) -> Quote:
        self._ensure_credentials_for_read()
        # TODO: Wire to breeze_connect.BreezeConnect.get_quotes using env-only credentials.
        raise NotImplementedError("Breeze quote retrieval is not implemented in the safe scaffold")

    async def get_history(self, symbol: str, interval: str, limit: int) -> list[HistoricalBar]:
        self._ensure_credentials_for_read()
        # TODO: Wire to Breeze historical chart APIs with rate-limit accounting.
        raise NotImplementedError("Breeze historical retrieval is not implemented in the safe scaffold")

    async def place_order(self, request: OrderRequest) -> OrderResult:
        if not self.config.live_trading_enabled:
            return OrderResult(
                accepted=False,
                broker_order_id=None,
                status=OrderStatus.REJECTED,
                message="LIVE_TRADING_ENABLED is false; live Breeze orders are blocked",
            )
        if self.config.require_manual_confirmation and not request.manual_confirmation:
            return OrderResult(
                accepted=False,
                broker_order_id=None,
                status=OrderStatus.REJECTED,
                message="manual confirmation is required for live orders",
            )
        if request.order_type is OrderType.MARKET:
            return OrderResult(
                accepted=False,
                broker_order_id=None,
                status=OrderStatus.REJECTED,
                message="market orders are not permitted for Breeze integration",
            )
        self._ensure_credentials_for_live()
        # TODO: Use Breeze order placement API here after final compliance review.
        return OrderResult(
            accepted=False,
            broker_order_id=None,
            status=OrderStatus.REJECTED,
            message="live Breeze order placement is intentionally not implemented in v1 scaffold",
        )

    async def cancel_order(self, broker_order_id: str) -> OrderResult:
        if not self.config.live_trading_enabled:
            return OrderResult(False, broker_order_id, OrderStatus.REJECTED, "live cancellation blocked by flag")
        # TODO: Implement Breeze cancellation with 10 order-action/sec guard.
        return OrderResult(False, broker_order_id, OrderStatus.REJECTED, "Breeze cancellation TODO")

    async def get_orders(self) -> list[OrderResult]:
        # TODO: Implement read-only Breeze order-book retrieval.
        return []

    async def get_positions(self) -> list[PositionSnapshot]:
        # TODO: Implement read-only Breeze positions retrieval.
        return []

    async def square_off_all(self) -> list[OrderResult]:
        if not self.config.live_trading_enabled:
            return [OrderResult(False, None, OrderStatus.REJECTED, "live square-off blocked by flag")]
        # TODO: Implement Breeze square-off with manual confirmation and action-rate guard.
        return [OrderResult(False, None, OrderStatus.REJECTED, "Breeze square-off TODO")]

    async def get_withdrawable_balance(self) -> float | None:
        # TODO: Implement read-only funds endpoint if Breeze exposes withdrawable balance.
        return None

    def _ensure_credentials_for_read(self) -> None:
        if not self.config.api_key or not self.config.api_secret or not self.config.session_token:
            raise RuntimeError("Breeze credentials are missing from backend environment")

    def _ensure_credentials_for_live(self) -> None:
        self._ensure_credentials_for_read()
        if not self.config.registered_static_ip:
            raise RuntimeError("registered static IP must be configured before live order actions")
