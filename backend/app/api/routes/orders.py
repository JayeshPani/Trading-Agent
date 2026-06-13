from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from app.api.runtime import runtime
from app.core.security import require_dashboard_token

router = APIRouter(prefix="/api/orders", tags=["orders"], dependencies=[Depends(require_dashboard_token)])


@router.get("")
async def list_orders() -> dict[str, object]:
    orders = await runtime.paper_broker.get_orders()
    return {"orders": [asdict(order) for order in orders]}


@router.get("/{order_id}")
async def get_order(order_id: str) -> dict[str, object]:
    orders = await runtime.paper_broker.get_orders()
    for order in orders:
        if order.broker_order_id == order_id:
            return {"order": asdict(order)}
    raise HTTPException(status_code=404, detail="order not found")


@router.post("/{order_id}/cancel")
async def cancel_order(order_id: str) -> dict[str, object]:
    result = await runtime.paper_broker.cancel_order(order_id)
    return {"order": asdict(result)}
