from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Action = Literal["BUY", "SELL"]
TradingMode = Literal["paper", "live"]


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3


@dataclass(slots=True)
class StrategySignal:
    symbol: str
    action: Action
    confidence: float
    entry_price: float
    stop_loss: float
    target: float
    invalidation_reason: str
    timeframe: str
    explanation: str
    strategy_name: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def risk_reward(self) -> float:
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.target - self.entry_price)
        if risk <= 0:
            return 0.0
        return round(reward / risk, 4)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "confidence": self.confidence,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "target": self.target,
            "risk_reward": self.risk_reward,
            "invalidation_reason": self.invalidation_reason,
            "timeframe": self.timeframe,
            "explanation": self.explanation,
            "strategy_name": self.strategy_name,
            "metadata": self.metadata,
        }


class StrategyPlugin(ABC):
    name: str
    version: str = "0.1.0"
    paper_only: bool = False

    @abstractmethod
    def generate_signals(
        self,
        symbol: str,
        candles: list[Candle],
        *,
        mode: TradingMode = "paper",
    ) -> list[StrategySignal]:
        """Generate zero or more strategy signals from validated market data."""
