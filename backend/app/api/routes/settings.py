from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.runtime import runtime
from app.core.config import get_settings
from app.core.redaction import redact_for_dashboard
from app.core.security import require_dashboard_token

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_dashboard_token)])


class TradingSettings(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    risk_level: Literal["conservative", "moderate", "custom"] = "conservative"
    mode: Literal["paper", "live"] = "paper"
    allowed_symbols: list[str] = Field(min_length=1, max_length=50)
    max_daily_loss: float = Field(gt=0)
    max_loss_per_trade: float = Field(gt=0)
    strategy_selection: list[str] = Field(min_length=1)
    auto_square_off_enabled: bool = True
    emergency_stop_enabled: bool = True


@router.post("")
async def update_settings(settings: TradingSettings) -> dict[str, object]:
    if settings.mode == "live" and not get_settings().live_trading_enabled:
        raise HTTPException(status_code=400, detail="live mode is disabled by LIVE_TRADING_ENABLED=false")
    if settings.max_loss_per_trade > settings.max_daily_loss:
        raise HTTPException(status_code=400, detail="max loss per trade cannot exceed max daily loss")
    runtime.settings = settings.model_dump()
    runtime.log("settings updated", metadata=redact_for_dashboard(runtime.settings))
    return {"settings": redact_for_dashboard(runtime.settings)}


@router.get("")
async def get_current_settings() -> dict[str, object]:
    return {"settings": redact_for_dashboard(runtime.settings)}
