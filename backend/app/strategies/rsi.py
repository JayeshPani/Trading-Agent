from __future__ import annotations

from app.strategies.base import Candle, StrategyPlugin, StrategySignal, TradingMode


class RSIMeanReversionStrategy(StrategyPlugin):
    name = "rsi_mean_reversion"
    version = "0.1.0"
    paper_only = True

    def __init__(self, period: int = 14, oversold: float = 30.0) -> None:
        self.period = period
        self.oversold = oversold

    def generate_signals(
        self,
        symbol: str,
        candles: list[Candle],
        *,
        mode: TradingMode = "paper",
    ) -> list[StrategySignal]:
        if mode != "paper" or len(candles) < self.period + 1:
            return []
        rsi = self._rsi([c.close for c in candles[-self.period - 1 :]])
        last = candles[-1]
        if rsi < self.oversold:
            stop = last.close * 0.99
            target = last.close * 1.02
            return [
                StrategySignal(
                    symbol=symbol.upper(),
                    action="BUY",
                    confidence=0.52,
                    entry_price=last.close,
                    stop_loss=stop,
                    target=target,
                    invalidation_reason="RSI fails to recover or price breaks the defined stop",
                    timeframe="intraday",
                    explanation="Paper-only RSI mean reversion candidate after oversold reading.",
                    strategy_name=self.name,
                    metadata={"rsi": round(rsi, 2), "paper_only": True},
                )
            ]
        return []

    def _rsi(self, closes: list[float]) -> float:
        gains = []
        losses = []
        for prev, curr in zip(closes, closes[1:], strict=False):
            delta = curr - prev
            gains.append(max(delta, 0))
            losses.append(abs(min(delta, 0)))
        avg_gain = sum(gains) / self.period
        avg_loss = sum(losses) / self.period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
