from __future__ import annotations

from pydantic import BaseModel

from .schemas import SessionStatus


class RuntimeState(BaseModel):
    autopilot_enabled: bool = False
    emergency_lock: bool = False
    trading_day: str
    session_status: SessionStatus = "missing"
    session_created_at: str | None = None
    session_expires_at: str | None = None
    session_token: str | None = None
