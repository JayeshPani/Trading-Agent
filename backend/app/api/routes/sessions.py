from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.runtime import runtime
from app.core.config import get_settings
from app.core.security import require_dashboard_token
from app.reporting.eod_report import EODReportGenerator

router = APIRouter(prefix="/api/sessions", tags=["sessions"], dependencies=[Depends(require_dashboard_token)])


@router.post("/start")
async def start_session() -> dict[str, Any]:
    settings = runtime.settings
    if settings["mode"] == "live" and not get_settings().live_trading_enabled:
        raise HTTPException(status_code=400, detail="live mode is disabled")
    if settings["mode"] != "paper":
        raise HTTPException(status_code=400, detail="v1 scaffold supports paper sessions only")

    runtime.reset_for_session()
    session_id = runtime.next_session_id()
    session = {
        "id": session_id,
        "mode": settings["mode"],
        "date": date.today().isoformat(),
        "starting_capital": settings["amount"],
        "ending_capital": None,
        "max_daily_loss": settings["max_daily_loss"],
        "max_loss_per_trade": settings["max_loss_per_trade"],
        "status": "running",
        "created_at": datetime.now(UTC).isoformat(),
        "closed_at": None,
    }
    runtime.sessions[session_id] = session
    runtime.latest_session_id = session_id
    runtime.log("paper trading session started", metadata={"session_id": session_id})
    return {"session": session}


@router.post("/{session_id}/stop")
async def stop_session(session_id: str) -> dict[str, Any]:
    session = runtime.sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    await runtime.paper_broker.square_off_all()
    session["status"] = "closed"
    session["closed_at"] = datetime.now(UTC).isoformat()
    session["ending_capital"] = runtime.paper_broker.cash
    report = EODReportGenerator().generate(
        session_id=session_id,
        starting_capital=session["starting_capital"],
        ending_capital=session["ending_capital"],
        trades=[],
        risk_rejections=[],
        api_errors=[],
        open_positions=[],
        settlement_status={"message": "paper trading has no real settlement"},
        hermes_suggestions=[],
    )
    runtime.reports[session_id] = report
    runtime.log("session stopped and square-off attempted", metadata={"session_id": session_id})
    return {"session": session, "report": report}


@router.get("/latest")
async def latest_session() -> dict[str, Any]:
    if not runtime.latest_session_id:
        return {"session": None}
    return {"session": runtime.sessions[runtime.latest_session_id]}


@router.get("/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    session = runtime.sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session": session}
