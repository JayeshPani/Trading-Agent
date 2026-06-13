from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean, pstdev


@dataclass(frozen=True, slots=True)
class TradeResult:
    symbol: str
    pnl: float


def win_rate(trades: list[TradeResult]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for trade in trades if trade.pnl > 0)
    return round(wins / len(trades), 4)


def profit_factor(trades: list[TradeResult]) -> float:
    gross_profit = sum(trade.pnl for trade in trades if trade.pnl > 0)
    gross_loss = abs(sum(trade.pnl for trade in trades if trade.pnl < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return round(gross_profit / gross_loss, 4)


def max_drawdown(equity_curve: list[float]) -> float:
    peak = None
    worst = 0.0
    for value in equity_curve:
        peak = value if peak is None else max(peak, value)
        drawdown = value - peak
        worst = min(worst, drawdown)
    return round(abs(worst), 2)


def sharpe_ratio(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    deviation = pstdev(returns)
    if deviation == 0:
        return None
    return round((mean(returns) / deviation) * sqrt(252), 4)
