from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.hermes.client import HermesClient, HermesSuggestion


@dataclass(slots=True)
class HermesAnalyzer:
    client: HermesClient

    async def analyze_session(
        self,
        *,
        session_id: str,
        report: dict[str, Any],
        trade_logs: list[dict[str, Any]],
    ) -> list[HermesSuggestion]:
        payload = {
            "session_id": session_id,
            "report": report,
            "logs": trade_logs,
            "capabilities": {
                "can_place_trades": False,
                "can_override_risk": False,
                "can_modify_live_strategy": False,
            },
        }
        return await self.client.analyze(payload)
