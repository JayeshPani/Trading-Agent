from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.runtime import runtime
from app.core.security import require_dashboard_token

router = APIRouter(prefix="/api/risk", tags=["risk"], dependencies=[Depends(require_dashboard_token)])


class EmergencyStopRequest(BaseModel):
    exit_positions: bool = True


@router.get("/status")
async def risk_status() -> dict[str, object]:
    return {
        "emergency_stopped": runtime.emergency_stopped,
        "daily_loss_usage": 0,
        "max_daily_loss": runtime.settings["max_daily_loss"],
        "max_loss_per_trade": runtime.settings["max_loss_per_trade"],
        "paper_cash": runtime.paper_broker.cash,
    }


@router.post("/emergency-stop")
async def emergency_stop(payload: EmergencyStopRequest) -> dict[str, object]:
    runtime.emergency_stopped = True
    results = []
    if payload.exit_positions:
        results = await runtime.paper_broker.square_off_all()
    runtime.log("emergency stop activated", level="WARNING", metadata={"exit_positions": payload.exit_positions})
    return {"emergency_stopped": True, "square_off_results": [asdict(result) for result in results]}
