from __future__ import annotations

from statistics import mean

from app.strategies.base import Candle, StrategyPlugin, StrategySignal, TradingMode


class VolumeBreakoutStrategy(StrategyPlugin):
    name = "breakout_with_volume"
    version = "0.1.0"

    def __init__(self, lookback: int = 15, volume_multiplier: float = 1.5) -> None:
        self.lookback = lookback
        self.volume_multiplier = volume_multiplier

    def generate_signals(
        self,
        symbol: str,
        candles: list[Candle],
        *,
        mode: TradingMode = "paper",
    ) -> list[StrategySignal]:
        if len(candles) < self.lookback + 1:
            return []
        prior = candles[-self.lookback - 1 : -1]
        last = candles[-1]
        breakout_level = max(c.high for c in prior)
        avg_volume = mean(c.volume for c in prior)
        if last.close > breakout_level and last.volume >= avg_volume * self.volume_multiplier:
            stop = min(c.low for c in candles[-5:])
            if stop >= last.close:
                return []
            target = last.close + (last.close - stop) * 2.2
            return [
                StrategySignal(
                    symbol=symbol.upper(),
                    action="BUY",
                    confidence=0.65,
                    entry_price=last.close,
                    stop_loss=stop,
                    target=target,
                    invalidation_reason="price falls back into the prior range",
                    timeframe="intraday",
                    explanation="Price broke the recent range on above-average volume.",
                    strategy_name=self.name,
                    metadata={"breakout_level": breakout_level, "avg_volume": avg_volume},
                )
            ]
        return []
