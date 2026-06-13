from __future__ import annotations

from app.strategies.base import Candle, StrategyPlugin, StrategySignal, TradingMode


class MovingAverageCrossoverStrategy(StrategyPlugin):
    name = "moving_average_crossover"
    version = "0.1.0"

    def __init__(self, short_window: int = 5, long_window: int = 20) -> None:
        if short_window >= long_window:
            raise ValueError("short_window must be smaller than long_window")
        self.short_window = short_window
        self.long_window = long_window

    def generate_signals(
        self,
        symbol: str,
        candles: list[Candle],
        *,
        mode: TradingMode = "paper",
    ) -> list[StrategySignal]:
        if len(candles) < self.long_window + 1:
            return []

        closes = [c.close for c in candles]
        prev_short = sum(closes[-self.short_window - 1 : -1]) / self.short_window
        prev_long = sum(closes[-self.long_window - 1 : -1]) / self.long_window
        curr_short = sum(closes[-self.short_window :]) / self.short_window
        curr_long = sum(closes[-self.long_window :]) / self.long_window

        if prev_short <= prev_long and curr_short > curr_long:
            entry = closes[-1]
            stop = min(c.low for c in candles[-self.short_window :])
            target = entry + (entry - stop) * 2
            if stop >= entry:
                return []
            return [
                StrategySignal(
                    symbol=symbol.upper(),
                    action="BUY",
                    confidence=0.62,
                    entry_price=entry,
                    stop_loss=stop,
                    target=target,
                    invalidation_reason="short moving average crosses back below long moving average",
                    timeframe="intraday",
                    explanation="Short moving average crossed above long moving average with recent price support.",
                    strategy_name=self.name,
                )
            ]
        return []
