from __future__ import annotations

from datetime import datetime, timedelta

from app.strategies.base import Candle
from app.strategies.breakout import VolumeBreakoutStrategy
from app.strategies.moving_average import MovingAverageCrossoverStrategy
from app.strategies.rsi import RSIMeanReversionStrategy


def candles(prices: list[float], volume: int = 1_000) -> list[Candle]:
    start = datetime(2026, 1, 1, 9, 15)
    return [
        Candle("RELIANCE", start + timedelta(minutes=i), price - 0.5, price + 0.5, price - 1, price, volume)
        for i, price in enumerate(prices)
    ]


def assert_complete_signal(signal: object) -> None:
    data = signal.as_dict()
    for key in (
        "symbol",
        "action",
        "confidence",
        "entry_price",
        "stop_loss",
        "target",
        "risk_reward",
        "invalidation_reason",
        "timeframe",
        "explanation",
    ):
        assert key in data


def test_moving_average_outputs_complete_signal() -> None:
    strategy = MovingAverageCrossoverStrategy(short_window=2, long_window=4)
    result = strategy.generate_signals("RELIANCE", candles([100, 100, 100, 100, 99, 105]))
    assert result
    assert_complete_signal(result[0])


def test_breakout_outputs_complete_signal() -> None:
    strategy = VolumeBreakoutStrategy(lookback=3, volume_multiplier=1.1)
    base = candles([100, 101, 102], volume=1_000)
    breakout = Candle("RELIANCE", datetime(2026, 1, 1, 9, 18), 102, 106, 101, 106, 2_000)
    result = strategy.generate_signals("RELIANCE", [*base, breakout])
    assert result
    assert_complete_signal(result[0])


def test_rsi_strategy_is_paper_only() -> None:
    strategy = RSIMeanReversionStrategy(period=3, oversold=40)
    market = candles([100, 99, 98, 97])
    assert strategy.generate_signals("RELIANCE", market, mode="live") == []
    assert strategy.generate_signals("RELIANCE", market, mode="paper")
