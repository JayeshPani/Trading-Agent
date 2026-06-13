from __future__ import annotations

from datetime import date
from itertools import count
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import require_dashboard_token

router = APIRouter(prefix="/api/strategies", tags=["strategies"], dependencies=[Depends(require_dashboard_token)])
_ids = count(100)
_strategies: dict[int, dict[str, Any]] = {
    1: {"id": 1, "name": "vwap_trend", "version": "0.1.0", "status": "paper", "config_json": {}},
    2: {"id": 2, "name": "moving_average_crossover", "version": "0.1.0", "status": "paper", "config_json": {}},
    3: {"id": 3, "name": "breakout_with_volume", "version": "0.1.0", "status": "paper", "config_json": {}},
    4: {
        "id": 4,
        "name": "rsi_mean_reversion",
        "version": "0.1.0",
        "status": "paper",
        "config_json": {"paper_only": True},
    },
    5: {
        "id": 5,
        "name": "opening_range_breakout",
        "version": "0.1.0",
        "status": "draft",
        "config_json": {"paper_only": True},
    },
}


class StrategyCreate(BaseModel):
    name: str
    version: str = "0.1.0"
    config_json: dict[str, Any] = {}


class ApprovalRequest(BaseModel):
    human_approved: bool = False


@router.get("")
async def list_strategies() -> dict[str, object]:
    return {"strategies": list(_strategies.values())}


@router.post("")
async def create_strategy(payload: StrategyCreate) -> dict[str, object]:
    strategy_id = next(_ids)
    strategy = {
        "id": strategy_id,
        "name": payload.name,
        "version": payload.version,
        "status": "draft",
        "config_json": payload.config_json,
    }
    _strategies[strategy_id] = strategy
    return {"strategy": strategy}


@router.post("/{strategy_id}/backtest")
async def backtest(strategy_id: int) -> dict[str, object]:
    strategy = _get_strategy(strategy_id)
    return {
        "strategy": strategy,
        "backtest": {
            "start_date": date.today().isoformat(),
            "end_date": date.today().isoformat(),
            "metrics_json": {"total_trades": 0, "note": "placeholder backtest engine"},
            "passed": False,
        },
    }


@router.post("/{strategy_id}/paper-test")
async def paper_test(strategy_id: int) -> dict[str, object]:
    strategy = _get_strategy(strategy_id)
    return {"strategy": strategy, "paper_test": {"metrics_json": {"total_trades": 0}, "passed": False}}


@router.post("/{strategy_id}/approve")
async def approve_strategy(strategy_id: int, payload: ApprovalRequest) -> dict[str, object]:
    strategy = _get_strategy(strategy_id)
    if not payload.human_approved:
        raise HTTPException(status_code=400, detail="human_approved=true is required")
    strategy["status"] = "paper"
    return {"strategy": strategy}


def _get_strategy(strategy_id: int) -> dict[str, Any]:
    strategy = _strategies.get(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="strategy not found")
    return strategy
