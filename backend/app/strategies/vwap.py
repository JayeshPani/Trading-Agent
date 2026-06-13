from __future__ import annotations

from app.strategies.base import Candle, StrategyPlugin, StrategySignal, TradingMode


class VWAPTrendStrategy(StrategyPlugin):
    name = "vwap_trend"
    version = "0.1.0"

    def generate_signals(
        self,
        symbol: str,
        candles: list[Candle],
        *,
        mode: TradingMode = "paper",
    ) -> list[StrategySignal]:
        if len(candles) < 5:
            return []
        total_volume = sum(c.volume for c in candles)
        if total_volume <= 0:
            return []
        vwap = sum(c.typical_price * c.volume for c in candles) / total_volume
        last = candles[-1]
        prior = candles[-2]
        if last.close > vwap and prior.close <= vwap and last.volume > candles[-2].volume:
            stop = min(c.low for c in candles[-5:])
            if stop >= last.close:
                return []
            target = last.close + (last.close - stop) * 2
            return [
                StrategySignal(
                    symbol=symbol.upper(),
                    action="BUY",
                    confidence=0.6,
                    entry_price=last.close,
                    stop_loss=stop,
                    target=target,
                    invalidation_reason="price closes back below VWAP",
                    timeframe="intraday",
                    explanation="Price reclaimed VWAP with rising volume.",
                    strategy_name=self.name,
                    metadata={"vwap": round(vwap, 4)},
                )
            ]
        return []
