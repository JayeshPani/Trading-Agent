from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.api.runtime import runtime
from app.core.security import require_dashboard_token

router = APIRouter(prefix="/api/market", tags=["market"], dependencies=[Depends(require_dashboard_token)])


@router.get("/quote/{symbol}")
async def quote(symbol: str) -> dict[str, object]:
    q = await runtime.paper_broker.get_quote(symbol)
    return {"symbol": q.symbol, "last_price": q.last_price, "volume": q.volume, "timestamp": q.timestamp.isoformat()}


@router.get("/history/{symbol}")
async def history(symbol: str) -> dict[str, object]:
    bars = await runtime.paper_broker.get_history(symbol, interval="1minute", limit=200)
    return {"symbol": symbol.upper(), "bars": [asdict(bar) for bar in bars]}
