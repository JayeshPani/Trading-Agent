from __future__ import annotations

from dataclasses import dataclass

from app.broker.base import BrokerAdapter, BrokerMode
from app.broker.breeze_adapter import BreezeAdapterConfig, BreezeBrokerAdapter
from app.broker.paper_adapter import PaperBrokerAdapter


@dataclass(slots=True)
class BrokerFactoryConfig:
    mode: BrokerMode = BrokerMode.PAPER
    starting_cash: float = 100_000.0
    breeze: BreezeAdapterConfig | None = None


def build_broker(config: BrokerFactoryConfig) -> BrokerAdapter:
    if config.mode is BrokerMode.PAPER:
        return PaperBrokerAdapter(starting_cash=config.starting_cash)
    if not config.breeze:
        raise RuntimeError("Breeze configuration is required for live mode")
    if not config.breeze.live_trading_enabled:
        raise RuntimeError("live broker creation blocked because LIVE_TRADING_ENABLED is false")
    return BreezeBrokerAdapter(config.breeze)
