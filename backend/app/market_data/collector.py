from __future__ import annotations

from dataclasses import dataclass

from app.broker.base import BrokerAdapter, Quote


@dataclass(slots=True)
class MarketDataCollector:
    broker: BrokerAdapter

    async def quote(self, symbol: str) -> Quote:
        return await self.broker.get_quote(symbol)
