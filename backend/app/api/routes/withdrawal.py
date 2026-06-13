from __future__ import annotations

from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends

from app.api.runtime import runtime
from app.core.security import require_dashboard_token
from app.withdrawal.checklist import manual_withdrawal_checklist
from app.withdrawal.readiness import WithdrawalReadiness

router = APIRouter(prefix="/api/withdrawal", tags=["withdrawal"], dependencies=[Depends(require_dashboard_token)])


@router.get("/status")
async def withdrawal_status() -> dict[str, object]:
    balance = await runtime.paper_broker.get_withdrawable_balance()
    status = await WithdrawalReadiness().check(broker_withdrawable_balance=balance, trade_date=date.today())
    return {"status": asdict(status)}


@router.get("/checklist")
async def checklist() -> dict[str, object]:
    return {"checklist": manual_withdrawal_checklist(), "automation_enabled": False}
