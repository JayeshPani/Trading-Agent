from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.api.runtime import runtime
from app.core.security import require_dashboard_token

router = APIRouter(prefix="/api/positions", tags=["positions"], dependencies=[Depends(require_dashboard_token)])


@router.get("")
async def list_positions() -> dict[str, object]:
    positions = await runtime.paper_broker.get_positions()
    return {"positions": [asdict(position) for position in positions]}


@router.post("/square-off-all")
async def square_off_all() -> dict[str, object]:
    results = await runtime.paper_broker.square_off_all()
    runtime.log("manual square-off requested", metadata={"orders": len(results)})
    return {"results": [asdict(result) for result in results]}
