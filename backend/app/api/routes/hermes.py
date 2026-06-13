from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from app.api.runtime import runtime
from app.core.security import require_dashboard_token
from app.hermes.analyzer import HermesAnalyzer
from app.hermes.client import HermesClient

router = APIRouter(prefix="/api/hermes", tags=["hermes"], dependencies=[Depends(require_dashboard_token)])


@router.post("/analyze-session/{session_id}")
async def analyze_session(session_id: str) -> dict[str, object]:
    if session_id not in runtime.sessions:
        raise HTTPException(status_code=404, detail="session not found")
    analyzer = HermesAnalyzer(HermesClient())
    suggestions = await analyzer.analyze_session(
        session_id=session_id,
        report=runtime.reports.get(session_id, {}),
        trade_logs=[log for log in runtime.trade_logs if log.get("session_id") in {session_id, None}],
    )
    stored = runtime.suggestions.add_many(suggestions)
    return {
        "suggestions": [
            {"id": suggestion_id, **asdict(suggestion)}
            for suggestion_id, suggestion in stored
        ]
    }


@router.get("/suggestions")
async def list_suggestions() -> dict[str, object]:
    return {
        "suggestions": [
            {"id": suggestion_id, **asdict(suggestion)}
            for suggestion_id, suggestion in runtime.suggestions.list()
        ]
    }


@router.post("/suggestions/{suggestion_id}/approve")
async def approve_suggestion(suggestion_id: int) -> dict[str, object]:
    try:
        suggestion = runtime.suggestions.approve(suggestion_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"suggestion": {"id": suggestion_id, **asdict(suggestion)}}


@router.post("/suggestions/{suggestion_id}/reject")
async def reject_suggestion(suggestion_id: int) -> dict[str, object]:
    try:
        suggestion = runtime.suggestions.reject(suggestion_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"suggestion": {"id": suggestion_id, **asdict(suggestion)}}


@router.post("/suggestions/{suggestion_id}/test")
async def test_suggestion(suggestion_id: int) -> dict[str, object]:
    for stored_id, suggestion in runtime.suggestions.list():
        if stored_id == suggestion_id:
            return {
                "suggestion": {"id": suggestion_id, **asdict(suggestion)},
                "test": {"status": "queued", "live_changes": False},
            }
    raise HTTPException(status_code=404, detail="suggestion not found")
