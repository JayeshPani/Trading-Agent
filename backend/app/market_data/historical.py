from __future__ import annotations

from dataclasses import dataclass

from app.broker.base import BrokerAdapter, HistoricalBar


@dataclass(slots=True)
class HistoricalDataLoader:
    broker: BrokerAdapter

    async def load(self, symbol: str, interval: str = "1minute", limit: int = 200) -> list[HistoricalBar]:
        return await self.broker.get_history(symbol, interval, limit)
