from __future__ import annotations

from dataclasses import dataclass

from app.broker.base import BrokerAdapter, PositionSnapshot


@dataclass(slots=True)
class PositionManager:
    broker: BrokerAdapter

    async def list_positions(self) -> list[PositionSnapshot]:
        return await self.broker.get_positions()

    async def open_positions(self) -> list[PositionSnapshot]:
        return [position for position in await self.list_positions() if position.status.value == "OPEN"]
