from __future__ import annotations

from app.strategies.base import Candle, StrategyPlugin, StrategySignal, TradingMode


class OpeningRangeBreakoutStrategy(StrategyPlugin):
    name = "opening_range_breakout"
    version = "0.1.0"
    paper_only = True

    def __init__(self, opening_range_minutes: int = 15) -> None:
        self.opening_range_minutes = opening_range_minutes

    def generate_signals(
        self,
        symbol: str,
        candles: list[Candle],
        *,
        mode: TradingMode = "paper",
    ) -> list[StrategySignal]:
        if mode != "paper" or len(candles) <= self.opening_range_minutes:
            return []
        opening_range = candles[: self.opening_range_minutes]
        last = candles[-1]
        high = max(c.high for c in opening_range)
        low = min(c.low for c in opening_range)
        if last.close > high and last.volume > opening_range[-1].volume:
            stop = low
            if stop >= last.close:
                return []
            target = last.close + (last.close - stop) * 2
            return [
                StrategySignal(
                    symbol=symbol.upper(),
                    action="BUY",
                    confidence=0.55,
                    entry_price=last.close,
                    stop_loss=stop,
                    target=target,
                    invalidation_reason="price returns inside the opening range",
                    timeframe="intraday",
                    explanation="Paper-only opening range breakout candidate with volume expansion.",
                    strategy_name=self.name,
                    metadata={"opening_range_high": high, "opening_range_low": low, "paper_only": True},
                )
            ]
        return []
