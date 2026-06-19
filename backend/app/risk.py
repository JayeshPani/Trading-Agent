from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .config import AppConfig
from .rate_limit import RateLimiter
from .schemas import TradingSettings, is_equity_symbol, normalize_symbol
from .state import RuntimeState
from .time_utils import is_intraday_entry_cutoff_time, is_market_open


@dataclass(frozen=True)
class ProposedTrade:
    stock: str
    side: str
    quantity: int
    entry_price: float
    stop_loss: float
    target: float
    order_type: str
    asset_class: str
    strategy: str
    strategy_version: str
    confidence: float
    liquidity: float | None = None
    volatility: float | None = None


@dataclass(frozen=True)
class RiskResult:
    approved: bool
    reason: str

    @property
    def decision(self) -> str:
        return "approved" if self.approved else "rejected"


class RiskEngine:
    def __init__(
        self,
        config: AppConfig,
        rate_limiter: RateLimiter,
        credentials_ready: Callable[[], bool] | None = None,
    ):
        self.config = config
        self.rate_limiter = rate_limiter
        self.credentials_ready = credentials_ready or (lambda: self.config.has_breeze_credentials)

    def review(
        self,
        *,
        settings: TradingSettings,
        runtime: RuntimeState,
        trade: ProposedTrade,
        trades_today: int,
        daily_loss_used: float,
        open_symbols: set[str] | None = None,
        open_capital_used: float = 0,
        open_risk_used: float = 0,
    ) -> RiskResult:
        checks: list[str] = []
        stock = normalize_symbol(trade.stock)
        open_symbols = open_symbols or set()

        if runtime.emergency_lock:
            checks.append("Emergency lock is active.")
        if stock in open_symbols:
            checks.append(f"{stock} already has an open trade.")
        if trade.asset_class.lower() != "equity" or not is_equity_symbol(stock):
            checks.append("Only equity stock symbols are allowed.")
        if not settings.is_stock_allowed(stock):
            checks.append(f"{stock} is not in the allowed stock universe.")
        if trade.order_type.upper() != "LIMIT":
            checks.append("Only limit orders are allowed.")
        if trade.quantity <= 0:
            checks.append("Quantity must be greater than 0.")
        if trade.entry_price <= 0 or trade.stop_loss <= 0 or trade.target <= 0:
            checks.append("Entry, stop-loss, and target must be positive.")
        if trade.side == "BUY" and trade.stop_loss >= trade.entry_price:
            checks.append("Buy trades require stop-loss below entry.")
        if trade.side == "SELL" and trade.stop_loss <= trade.entry_price:
            checks.append("Sell trades require stop-loss above entry.")
        if trade.side == "BUY" and trade.target <= trade.entry_price:
            checks.append("Buy trades require target above entry.")
        if trade.side == "SELL" and trade.target >= trade.entry_price:
            checks.append("Sell trades require target below entry.")

        capital_required = trade.entry_price * trade.quantity
        if capital_required > settings.budget:
            checks.append("Trade exceeds configured budget.")
        remaining_capital = max(settings.budget - open_capital_used, 0)
        if capital_required > remaining_capital:
            checks.append("Trade exceeds remaining available budget.")

        risk_per_share = abs(trade.entry_price - trade.stop_loss)
        reward_per_share = abs(trade.target - trade.entry_price)
        stop_distance_percent = (risk_per_share / max(trade.entry_price, 1)) * 100
        max_trade_loss = risk_per_share * trade.quantity
        remaining_daily_loss = settings.daily_max_loss - daily_loss_used - open_risk_used
        if max_trade_loss <= 0:
            checks.append("Stop-loss does not define a possible loss.")
        if stop_distance_percent < 0.1:
            checks.append("Stop-loss distance is too small.")
        if stop_distance_percent > 5:
            checks.append("Stop-loss distance is too large.")
        if reward_per_share <= 0 or reward_per_share < risk_per_share * 0.75:
            checks.append("Target does not provide enough reward for the stop-loss distance.")
        if max_trade_loss > remaining_daily_loss:
            checks.append("Trade exceeds remaining daily loss capacity after open-position risk.")

        if trades_today >= settings.max_trades_per_day:
            checks.append("Max trades per day has been reached.")

        if trade.liquidity is not None and trade.liquidity < 1000:
            checks.append("Liquidity is below the trading minimum.")
        if trade.volatility is not None and trade.volatility > 0.12:
            checks.append("Volatility is above the trading limit.")

        if self.config.enforce_market_hours:
            if not is_market_open():
                checks.append("Market is closed.")
            elif settings.mode == "intraday" and is_intraday_entry_cutoff_time():
                checks.append("Intraday entry cutoff has passed.")

        if self.config.is_live_mode:
            if runtime.session_status != "active":
                checks.append("A valid daily Breeze session is required for live trading.")
            if not self.credentials_ready():
                checks.append("Breeze app key and secret key are required for live trading.")
            if not self.config.static_ip_ready:
                checks.append("Live trading requires the registered static IP.")

            api_ok, api_reason = self.rate_limiter.can_call_api()
            order_ok, order_reason = self.rate_limiter.can_send_order_action()
            if not api_ok:
                checks.append(api_reason)
            if not order_ok:
                checks.append(order_reason)

        if checks:
            return RiskResult(False, " ".join(checks))
        return RiskResult(True, "Approved by deterministic risk checks.")
