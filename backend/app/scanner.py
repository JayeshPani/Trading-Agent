from __future__ import annotations

from datetime import timedelta
from statistics import mean
from typing import Any

from fastapi import HTTPException

from .breeze import BreezeClient, BreezeClientError
from .constants import NIFTY_50_SYMBOLS
from .rate_limit import RateLimitError
from .schemas import (
    ScannerCandidate,
    ScannerResult,
    StrategyTemplate,
    TradingSettings,
    normalize_symbol,
)
from .state import RuntimeState
from .time_utils import now_utc, utc_iso


APPROVED_STRATEGIES: list[StrategyTemplate] = [
    StrategyTemplate(
        name="VWAP pullback",
        version="v1",
        description="Long setup when price holds near or above VWAP with moderate RSI.",
    ),
    StrategyTemplate(
        name="EMA crossover",
        version="v1",
        description="Long setup when fast EMA is above slow EMA with positive trend.",
    ),
    StrategyTemplate(
        name="Momentum breakout",
        version="v1",
        description="Long setup when price is near resistance with elevated volume.",
    ),
    StrategyTemplate(
        name="Opening range breakout",
        version="v1",
        description="Long setup for early trend expansion with volume confirmation.",
    ),
    StrategyTemplate(
        name="Mean reversion",
        version="v1",
        description="Long setup when RSI is stretched low and price is near support.",
    ),
]


class StrategySelector:
    def __init__(self, strategies: list[StrategyTemplate] | None = None):
        self.strategies = strategies or APPROVED_STRATEGIES
        self._by_name = {strategy.name: strategy for strategy in self.strategies}

    def choose(self, indicators: dict[str, float]) -> StrategyTemplate | None:
        rsi = indicators["rsi"]
        trend = indicators["trend"]
        volume_spike = indicators["volumeSpike"]
        price_to_vwap = indicators["priceToVwap"]
        resistance_distance = indicators["resistanceDistance"]
        support_distance = indicators["supportDistance"]

        if volume_spike >= 1.5 and trend >= 0.01:
            return self._by_name["Opening range breakout"]
        if volume_spike >= 1.2 and resistance_distance <= 0.02 and trend > 0:
            return self._by_name["Momentum breakout"]
        if trend > 0.003:
            return self._by_name["EMA crossover"]
        if price_to_vwap >= -0.01 and 40 <= rsi <= 65:
            return self._by_name["VWAP pullback"]
        if rsi <= 35 and support_distance <= 0.03:
            return self._by_name["Mean reversion"]
        return None


class MarketScanner:
    def __init__(self, breeze_client: BreezeClient, strategy_selector: StrategySelector | None = None):
        self.breeze_client = breeze_client
        self.strategy_selector = strategy_selector or StrategySelector()

    def scan(
        self,
        *,
        settings: TradingSettings,
        runtime: RuntimeState,
        max_symbols: int | None = None,
    ) -> ScannerResult:
        if runtime.session_status != "active" or not runtime.session_token:
            raise HTTPException(status_code=400, detail="A valid daily Breeze session is required.")

        candidates: list[ScannerCandidate] = []
        stock_universe = self._stock_universe(settings)
        if max_symbols is not None and max_symbols > 0:
            stock_universe = stock_universe[:max_symbols]

        consecutive_broker_failures = 0
        broker_error_count = 0
        latest_broker_error: str | None = None
        for stock in stock_universe:
            try:
                candidates.append(self._scan_stock(runtime.session_token, stock))
                consecutive_broker_failures = 0
            except BreezeClientError as exc:
                if not exc.retryable:
                    candidates.append(_rejected_candidate(stock, str(exc)))
                    consecutive_broker_failures = 0
                    continue
                broker_error_count += 1
                consecutive_broker_failures += 1
                latest_broker_error = str(exc)
                candidates.append(_rejected_candidate(stock, str(exc)))
                if consecutive_broker_failures >= 3:
                    break
            except RateLimitError as exc:
                candidates.append(_rejected_candidate(stock, str(exc)))
                break

        candidates.sort(key=lambda candidate: (-candidate.score, candidate.stock_code))
        broker_status = "healthy"
        if consecutive_broker_failures >= 3:
            broker_status = "unavailable"
        elif broker_error_count:
            broker_status = "degraded"
        return ScannerResult(
            generatedAt=utc_iso(),
            candidates=candidates,
            shortlist=[candidate for candidate in candidates if not candidate.rejected],
            brokerStatus=broker_status,
            brokerErrorCount=broker_error_count,
            brokerError=latest_broker_error,
        )

    def _scan_stock(self, session_token: str, stock: str) -> ScannerCandidate:
        try:
            quote = self.breeze_client.get_quote(session_token, stock)
            candles = self.breeze_client.get_historical_candles(
                session_token,
                stock_code=stock,
                from_date=(now_utc() - timedelta(days=30)).isoformat(),
                to_date=now_utc().isoformat(),
                interval="day",
            )
        except BreezeClientError as exc:
            if exc.retryable:
                raise
            return ScannerCandidate(
                stockCode=stock,
                score=0,
                lastPrice=0,
                indicators={},
                negativeReasons=[str(exc)],
                rejected=True,
                rejectionReason=str(exc),
            )

        indicators = calculate_indicators(quote, candles)
        strategy = self.strategy_selector.choose(indicators)
        positive, negative = build_reasons(indicators, strategy)
        rejection_reason = rejection_reason_for(indicators, strategy)
        return ScannerCandidate(
            stockCode=stock,
            score=score_indicators(indicators, strategy),
            strategy=strategy.name if strategy else None,
            strategyVersion=strategy.version if strategy else None,
            lastPrice=indicators["lastPrice"],
            indicators=indicators,
            positiveReasons=positive,
            negativeReasons=negative,
            rejected=rejection_reason is not None,
            rejectionReason=rejection_reason,
        )

    @staticmethod
    def _stock_universe(settings: TradingSettings) -> list[str]:
        if settings.stock_preset == "NIFTY 50":
            return sorted(NIFTY_50_SYMBOLS)
        return [normalize_symbol(stock) for stock in settings.allowed_stocks]


def _rejected_candidate(stock: str, reason: str) -> ScannerCandidate:
    return ScannerCandidate(
        stockCode=stock,
        score=0,
        lastPrice=0,
        indicators={},
        negativeReasons=[reason],
        rejected=True,
        rejectionReason=reason,
    )


def calculate_indicators(quote: Any, candles: list[Any]) -> dict[str, float]:
    rows = [_as_candle(candle) for candle in candles]
    quote_row = _as_quote(quote)
    closes = [row["close"] for row in rows if row["close"] > 0]
    highs = [row["high"] for row in rows if row["high"] > 0]
    lows = [row["low"] for row in rows if row["low"] > 0]
    volumes = [row["volume"] for row in rows if row["volume"] > 0]

    last_price = quote_row["lastPrice"] or (closes[-1] if closes else 0)
    avg_volume = mean(volumes[-10:]) if volumes else quote_row["volume"]
    volume = quote_row["volume"] or (volumes[-1] if volumes else avg_volume)
    vwap = calculate_vwap(rows) or last_price
    ema_fast = calculate_ema(closes, 5) or last_price
    ema_slow = calculate_ema(closes, 13) or last_price
    support = min(lows[-20:]) if lows else last_price
    resistance = max(highs[-20:]) if highs else last_price

    return {
        "lastPrice": round(last_price, 4),
        "rsi": round(calculate_rsi(closes), 4),
        "vwap": round(vwap, 4),
        "priceToVwap": round((last_price - vwap) / max(vwap, 1), 4),
        "emaFast": round(ema_fast, 4),
        "emaSlow": round(ema_slow, 4),
        "trend": round((ema_fast - ema_slow) / max(ema_slow, 1), 4),
        "volumeSpike": round(volume / max(avg_volume, 1), 4),
        "volatility": round((max(highs[-10:] or [last_price]) - min(lows[-10:] or [last_price])) / max(last_price, 1), 4),
        "liquidity": round(avg_volume, 4),
        "support": round(support, 4),
        "resistance": round(resistance, 4),
        "supportDistance": round((last_price - support) / max(last_price, 1), 4),
        "resistanceDistance": round((resistance - last_price) / max(last_price, 1), 4),
    }


def calculate_rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < 2:
        return 50
    deltas = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    window = deltas[-period:]
    gains = [delta for delta in window if delta > 0]
    losses = [-delta for delta in window if delta < 0]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 70 if avg_gain > 0 else 50
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_ema(values: list[float], period: int) -> float | None:
    if not values:
        return None
    multiplier = 2 / (period + 1)
    ema = values[0]
    for value in values[1:]:
        ema = (value * multiplier) + (ema * (1 - multiplier))
    return ema


def calculate_vwap(rows: list[dict[str, float]]) -> float | None:
    total_volume = 0.0
    total_value = 0.0
    for row in rows[-20:]:
        volume = row["volume"]
        if volume <= 0:
            continue
        typical_price = (row["high"] + row["low"] + row["close"]) / 3
        total_value += typical_price * volume
        total_volume += volume
    if total_volume <= 0:
        return None
    return total_value / total_volume


def score_indicators(indicators: dict[str, float], strategy: StrategyTemplate | None) -> float:
    score = 0.0
    score += 18 if indicators["liquidity"] >= 1000 else max(indicators["liquidity"] / 1000 * 18, 0)
    score += min(indicators["volumeSpike"], 2.0) / 2.0 * 18
    score += 18 if indicators["trend"] > 0 else max(10 + indicators["trend"] * 100, 0)
    score += 14 if indicators["priceToVwap"] >= -0.01 else max(8 + indicators["priceToVwap"] * 100, 0)
    score += 12 if 35 <= indicators["rsi"] <= 70 else 4
    score += 10 if indicators["volatility"] <= 0.08 else max(10 - indicators["volatility"] * 100, 0)
    score += 10 if strategy else 0
    return round(min(max(score, 0), 100), 2)


def build_reasons(
    indicators: dict[str, float], strategy: StrategyTemplate | None
) -> tuple[list[str], list[str]]:
    positive: list[str] = []
    negative: list[str] = []
    if indicators["liquidity"] >= 1000:
        positive.append("Liquidity check passed.")
    else:
        negative.append("Liquidity is below the paper-trading minimum.")
    if indicators["volumeSpike"] >= 1.2:
        positive.append("Volume is above its recent average.")
    else:
        negative.append("Volume spike is weak.")
    if indicators["trend"] > 0:
        positive.append("EMA trend is positive.")
    else:
        negative.append("EMA trend is not positive.")
    if indicators["priceToVwap"] >= -0.01:
        positive.append("Price is holding near or above VWAP.")
    else:
        negative.append("Price is below VWAP.")
    if indicators["volatility"] <= 0.12:
        positive.append("Volatility is inside the scanner limit.")
    else:
        negative.append("Volatility is too high.")
    if strategy:
        positive.append(f"Strategy matched: {strategy.name}.")
    else:
        negative.append("No approved strategy template matched.")
    return positive, negative


def rejection_reason_for(indicators: dict[str, float], strategy: StrategyTemplate | None) -> str | None:
    if indicators["lastPrice"] <= 0:
        return "Missing valid market price."
    if indicators["liquidity"] < 1000:
        return "Liquidity is below the scanner minimum."
    if indicators["volatility"] > 0.12:
        return "Volatility is above the scanner limit."
    if strategy is None:
        return "No approved strategy template matched."
    return None


def _as_quote(quote: Any) -> dict[str, float]:
    return {
        "lastPrice": _number(_field(quote, "last_price", "lastPrice")),
        "volume": _number(_field(quote, "volume")),
    }


def _as_candle(candle: Any) -> dict[str, float]:
    return {
        "open": _number(_field(candle, "open")),
        "high": _number(_field(candle, "high")),
        "low": _number(_field(candle, "low")),
        "close": _number(_field(candle, "close")),
        "volume": _number(_field(candle, "volume")),
    }


def _field(value: Any, *names: str) -> Any:
    if isinstance(value, dict):
        for name in names:
            if name in value:
                return value[name]
        return None
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
