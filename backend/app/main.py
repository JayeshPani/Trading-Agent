from __future__ import annotations

import asyncio
from dataclasses import asdict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    health,
    hermes,
    market,
    orders,
    positions,
    reports,
    risk,
    sessions,
    settings,
    signals,
    strategies,
    withdrawal,
)
from app.api.runtime import runtime
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(title="ICICI Breeze Paper Trading Assistant", version="0.1.0")
settings_obj = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings_obj.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(health.router)
app.include_router(settings.router)
app.include_router(sessions.router)
app.include_router(market.router)
app.include_router(strategies.router)
app.include_router(signals.router)
app.include_router(orders.router)
app.include_router(positions.router)
app.include_router(risk.router)
app.include_router(reports.router)
app.include_router(hermes.router)
app.include_router(withdrawal.router)


@app.websocket("/ws/live-status")
async def live_status(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    if token != settings_obj.dashboard_api_token:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            positions = await runtime.paper_broker.get_positions()
            await websocket.send_json(
                {
                    "mode": runtime.settings["mode"],
                    "session_id": runtime.latest_session_id,
                    "emergency_stopped": runtime.emergency_stopped,
                    "paper_cash": runtime.paper_broker.cash,
                    "open_positions": [asdict(position) for position in positions],
                    "logs": runtime.trade_logs[-50:],
                }
            )
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return
