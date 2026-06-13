from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.runtime import runtime
from app.core.security import require_dashboard_token

router = APIRouter(prefix="/api/signals", tags=["signals"], dependencies=[Depends(require_dashboard_token)])


@router.get("")
async def list_signals() -> dict[str, object]:
    return {"signals": list(runtime.signals.values())}


@router.get("/{signal_id}")
async def get_signal(signal_id: str) -> dict[str, object]:
    signal = runtime.signals.get(signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="signal not found")
    return {"signal": signal}
