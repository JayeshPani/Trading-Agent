from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.runtime import runtime
from app.core.security import require_dashboard_token

router = APIRouter(prefix="/api/reports", tags=["reports"], dependencies=[Depends(require_dashboard_token)])


@router.get("/daily")
async def daily_report() -> dict[str, object]:
    if not runtime.latest_session_id:
        return {"report": None}
    return {"report": runtime.reports.get(runtime.latest_session_id)}


@router.get("/{report_id}")
async def get_report(report_id: str) -> dict[str, object]:
    report = runtime.reports.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="report not found")
    return {"report": report}
