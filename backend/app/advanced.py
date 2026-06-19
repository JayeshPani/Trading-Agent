from __future__ import annotations

import importlib.util
import uuid
from datetime import timedelta
from typing import Any

from fastapi import HTTPException

from .breeze import BreezeClient, BreezeClientError
from .config import AppConfig
from .schemas import (
    AuditEvent,
    BacktestMetrics,
    BacktestRequest,
    BacktestRun,
    ChampionState,
    HealthResponse,
    ImprovementRun,
    LiveAutopilotStatus,
    LiveOrder,
    LiveOrderPrepareRequest,
    LiveReadiness,
    ReportSendResponse,
    SafetyStatus,
    StrategyEligibility,
    StrategyVersion,
    normalize_symbol,
)
from .scanner import APPROVED_STRATEGIES, StrategySelector, calculate_indicators
from .state import RuntimeState
from .store import SQLiteStore
from .time_utils import current_trading_day, is_market_open, now_utc, utc_iso

BACKTEST_MIN_TRADES = 100
BACKTEST_MIN_PROFIT_FACTOR = 1.2
BACKTEST_MAX_DRAWDOWN = 10
BACKTEST_MIN_WIN_RATE = 45
PAPER_MIN_DAYS = 5
PAPER_MIN_PROFIT_FACTOR = 1.1


class AdvancedTradingService:
    def __init__(
        self,
        *,
        config: AppConfig,
        store: SQLiteStore,
        breeze_client: BreezeClient,
        credentials_ready,
    ):
        self.config = config
        self.store = store
        self.breeze_client = breeze_client
        self.credentials_ready = credentials_ready

    def run_backtest(self, request: BacktestRequest) -> BacktestRun:
        self._assert_approved_strategy(request.strategy)
        runtime = self.store.get_runtime()
        if runtime.session_status != "active" or not runtime.session_token:
            raise HTTPException(status_code=400, detail="A valid daily Breeze session is required.")

        settings = self.store.get_settings()
        stock = normalize_symbol(request.stock_code or self._default_stock())
        from_date = request.from_date or (now_utc() - timedelta(days=365 * 5)).isoformat()
        to_date = request.to_date or now_utc().isoformat()

        try:
            candles = self.breeze_client.get_historical_candles(
                runtime.session_token,
                stock_code=stock,
                from_date=from_date,
                to_date=to_date,
                interval="day",
            )
        except BreezeClientError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        pnls = _strategy_backtest_pnls(
            candles,
            strategy=request.strategy,
            budget=settings.budget,
            stop_loss_percent=settings.stop_loss_percent,
            target_percent=settings.target_percent,
        )
        metrics = _build_backtest_metrics(pnls, starting_capital=settings.budget)
        passed, reason = _backtest_gate(metrics)
        run = BacktestRun(
            id=str(uuid.uuid4()),
            strategy=request.strategy,
            strategyVersion="v1",
            stockUniverse=[stock],
            fromDate=from_date,
            toDate=to_date,
            settingsSnapshot=settings.model_dump(by_alias=True),
            metrics=metrics,
            passed=passed,
            reason=reason,
            createdAt=utc_iso(),
        )
        self.store.save_backtest_run(run)
        self._upsert_strategy_version_from_backtest(run)
        return run

    def list_backtests(self) -> list[BacktestRun]:
        return self.store.list_backtests()

    def get_backtest(self, run_id: str) -> BacktestRun:
        run = self.store.get_backtest(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Backtest run was not found.")
        return run

    def strategy_eligibility(self, strategy: str) -> StrategyEligibility:
        latest = self.store.latest_passed_backtest(strategy)
        if latest is None:
            return StrategyEligibility(
                strategy=strategy,
                eligible=False,
                reason="No passing backtest is available.",
                latestBacktest=None,
            )
        return StrategyEligibility(
            strategy=strategy,
            eligible=True,
            reason="Latest backtest passed live eligibility gates.",
            latestBacktest=latest,
        )

    def prepare_live_order(self, request: LiveOrderPrepareRequest) -> LiveOrder:
        self._assert_live_order_ready()
        strategy = request.strategy or "VWAP pullback"
        self._assert_approved_strategy(strategy)
        eligibility = self.strategy_eligibility(strategy)
        if not eligibility.eligible:
            raise HTTPException(status_code=400, detail=eligibility.reason)

        state = self.store.get_safety_state()
        if self.store.count_live_orders_today() >= int(state["max_order_limit"]):
            raise HTTPException(status_code=400, detail="Max live order limit reached.")

        runtime = self.store.get_runtime()
        settings = self.store.get_settings()
        stock = normalize_symbol(request.stock_code or self._default_stock())
        if not settings.is_stock_allowed(stock):
            raise HTTPException(status_code=400, detail=f"{stock} is outside the configured stock universe.")
        price = request.price or self._quote_price(runtime, stock)
        quantity = request.quantity or max(int(float(state["capital_lock"]) // max(price, 1)), 1)
        if quantity <= 0 or price <= 0:
            raise HTTPException(status_code=400, detail="Live order quantity and price must be positive.")
        if quantity * price > float(state["capital_lock"]):
            raise HTTPException(status_code=400, detail="Live order exceeds capital lock.")

        now = utc_iso()
        order = LiveOrder(
            id=str(uuid.uuid4()),
            stockCode=stock,
            side=request.side,
            quantity=quantity,
            price=price,
            orderType="limit",
            status="prepared",
            strategy=strategy,
            reason="Prepared for manual confirmation.",
            createdAt=now,
            updatedAt=now,
        )
        self.store.save_live_order(order)
        self.store.insert_audit_event(
            event_type="live.order.prepare",
            message=f"Prepared live limit order for {stock}.",
            details={"orderId": order.id, "strategy": strategy},
        )
        return order

    def confirm_live_order(self, order_id: str) -> LiveOrder:
        self._assert_live_order_ready()
        runtime = self.store.get_runtime()
        order = self._get_live_order(order_id)
        if order.status != "prepared":
            raise HTTPException(status_code=400, detail="Only prepared orders can be confirmed.")
        try:
            broker_order = self.breeze_client.place_order(
                runtime.session_token or "",
                {
                    "stock_code": order.stock_code,
                    "exchange_code": "NSE",
                    "product_type": "cash",
                    "action": order.side.lower(),
                    "quantity": order.quantity,
                    "price": order.price,
                    "order_type": "limit",
                    "validity": "day",
                },
            )
        except BreezeClientError as exc:
            failed = order.model_copy(update={"status": "rejected", "reason": str(exc), "updated_at": utc_iso()})
            self.store.save_live_order(failed)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        broker_id = _broker_order_id(broker_order)
        confirmed = order.model_copy(
            update={
                "status": "submitted",
                "broker_order_id": broker_id,
                "reason": "Submitted to Breeze after manual confirmation.",
                "updated_at": utc_iso(),
            }
        )
        self.store.save_live_order(confirmed)
        self.store.insert_audit_event(
            event_type="live.order.confirm",
            message=f"Confirmed live order {order.id}.",
            details={"brokerOrderId": broker_id},
        )
        return confirmed

    def cancel_live_order(self, order_id: str) -> LiveOrder:
        order = self._get_live_order(order_id)
        if order.status == "prepared":
            cancelled = order.model_copy(update={"status": "cancelled", "reason": "Cancelled before broker submission.", "updated_at": utc_iso()})
            self.store.save_live_order(cancelled)
            return cancelled
        self._assert_live_order_ready(allow_exit=True)
        runtime = self.store.get_runtime()
        try:
            if hasattr(self.breeze_client, "cancel_order"):
                self.breeze_client.cancel_order(runtime.session_token or "", {"order_id": order.broker_order_id})
        except BreezeClientError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        cancelled = order.model_copy(update={"status": "cancelled", "reason": "Cancel sent to Breeze.", "updated_at": utc_iso()})
        self.store.save_live_order(cancelled)
        return cancelled

    def square_off_live_order(self, order_id: str) -> LiveOrder:
        self._assert_live_order_ready(allow_exit=True)
        runtime = self.store.get_runtime()
        order = self._get_live_order(order_id)
        action = "sell" if order.side == "BUY" else "buy"
        try:
            self.breeze_client.square_off(
                runtime.session_token or "",
                {
                    "stock_code": order.stock_code,
                    "exchange_code": "NSE",
                    "product_type": "cash",
                    "quantity": order.quantity,
                    "price": order.price,
                    "action": action,
                    "order_type": "limit",
                    "validity": "day",
                },
            )
        except BreezeClientError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        squared = order.model_copy(update={"status": "square_off_sent", "reason": "Limit square-off sent to Breeze.", "updated_at": utc_iso()})
        self.store.save_live_order(squared)
        return squared

    def list_live_orders(self) -> list[LiveOrder]:
        return self.store.list_live_orders()

    def live_readiness(self) -> LiveReadiness:
        runtime = self.store.get_runtime()
        state = self.store.get_safety_state()
        settings = self.store.get_settings()
        credentials_ready = self.credentials_ready()
        session_active = runtime.session_status == "active" and bool(runtime.session_token)
        daily_loss_locked = self.store.daily_loss_used() >= settings.daily_max_loss
        passed_strategy = self.store.latest_passed_backtest_any()
        paper_ready, paper_reason = _paper_validation_gate(self.store)
        blockers: list[str] = []
        warnings: list[str] = []

        if not self.config.is_live_mode:
            blockers.append("Set TRADING_MODE=live and restart the backend.")
        if not credentials_ready:
            blockers.append("Save Breeze AppKey and Secret Key on the backend.")
        if not session_active:
            blockers.append("Submit today's Breeze session key.")
        if not self.config.static_ip_ready:
            blockers.append("Run from the ICICI-registered static IP and set STATIC_IP_READY=true.")
        if state["kill_switch_active"]:
            blockers.append("Kill switch is active.")
        if runtime.emergency_lock:
            blockers.append("Emergency lock is active.")
        if daily_loss_locked:
            blockers.append("Daily max-loss lock is active.")
        if passed_strategy is None:
            blockers.append("Strategy is not live eligible: No passing backtest is available.")

        if not paper_ready:
            warnings.append(paper_reason)
        if settings.mode != "intraday":
            warnings.append("Trading rules are not set to intraday mode.")

        ready_for_manual = not blockers
        ready_for_autopilot = ready_for_manual and paper_ready
        next_action = "Manual live order flow is ready." if ready_for_manual else blockers[0]
        if ready_for_manual and not paper_ready:
            next_action = "Manual live order flow is ready; live autopilot still needs paper validation."

        return LiveReadiness(
            readyForManualLiveOrder=ready_for_manual,
            readyForLiveAutopilot=ready_for_autopilot,
            liveMode=self.config.is_live_mode,
            credentialsReady=credentials_ready,
            sessionActive=session_active,
            staticIpReady=self.config.static_ip_ready,
            strategyEligible=passed_strategy is not None,
            paperValidationReady=paper_ready,
            blockers=blockers,
            warnings=warnings,
            nextAction=next_action,
        )

    def refresh_live_order(self, order_id: str) -> LiveOrder:
        order = self._get_live_order(order_id)
        if order.status == "prepared":
            return order
        if not order.broker_order_id:
            raise HTTPException(status_code=400, detail="Live order does not have a broker order id.")
        self._assert_live_broker_read_ready()
        runtime = self.store.get_runtime()
        try:
            broker_order = self.breeze_client.get_order_status(
                runtime.session_token or "",
                {"order_id": order.broker_order_id},
            )
        except BreezeClientError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        broker_status = getattr(broker_order, "status", None)
        if broker_status is None and isinstance(broker_order, dict):
            broker_status = broker_order.get("status") or broker_order.get("orderStatus")
        refreshed = order.model_copy(
            update={
                "status": str(broker_status or order.status).lower(),
                "reason": "Broker order status refreshed from Breeze.",
                "updated_at": utc_iso(),
            }
        )
        self.store.save_live_order(refreshed)
        return refreshed

    def live_autopilot_status(self) -> LiveAutopilotStatus:
        state = self.store.get_safety_state()
        eligible, reason = self._live_autopilot_gate()
        return LiveAutopilotStatus(
            enabled=bool(state["live_autopilot_enabled"]),
            eligible=eligible,
            reason=reason,
            maxOrdersPerDay=int(state["max_order_limit"]),
            maxOpenPositions=int(state["max_open_positions"]),
            maxCapital=float(state["capital_lock"]),
        )

    def start_live_autopilot(self) -> LiveAutopilotStatus:
        eligible, reason = self._live_autopilot_gate()
        if not eligible:
            raise HTTPException(status_code=400, detail=reason)
        self.store.set_live_autopilot(True)
        return self.live_autopilot_status()

    def stop_live_autopilot(self) -> LiveAutopilotStatus:
        self.store.set_live_autopilot(False)
        return self.live_autopilot_status()

    def run_improvement(self) -> ImprovementRun:
        tools = _tool_availability()
        if is_market_open():
            run = ImprovementRun(
                id=str(uuid.uuid4()),
                status="blocked",
                toolsAvailable=tools,
                reason="Improvement jobs can run only after market hours.",
                createdAt=utc_iso(),
            )
            self.store.save_improvement_run(run)
            return run

        version = StrategyVersion(
            id=str(uuid.uuid4()),
            strategy="VWAP pullback",
            version=f"challenger-{current_trading_day()}",
            parameters={"targetPercent": 3, "stopLossPercent": 1.5},
            backtestMetrics={},
            paperMetrics={},
            riskNotes=["Generated as challenger only; champion is unchanged."],
            promotionStatus="generated",
            createdAt=utc_iso(),
        )
        self.store.save_strategy_version(version)
        run = ImprovementRun(
            id=str(uuid.uuid4()),
            status="created_challenger",
            toolsAvailable=tools,
            createdVersionId=version.id,
            reason="Created challenger strategy version.",
            createdAt=utc_iso(),
        )
        self.store.save_improvement_run(run)
        return run

    def list_improvement_runs(self) -> list[ImprovementRun]:
        return self.store.list_improvement_runs()

    def list_strategy_versions(self) -> list[StrategyVersion]:
        return self.store.list_strategy_versions()

    def get_strategy_version(self, version_id: str) -> StrategyVersion:
        version = self.store.get_strategy_version(version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="Strategy version was not found.")
        return version

    def champion_state(self) -> ChampionState:
        return ChampionState(champion=self.store.current_champion(), challengers=self.store.list_challengers())

    def promote_challenger(self, version_id: str) -> StrategyVersion:
        version = self.get_strategy_version(version_id)
        champion = self.store.current_champion()
        if not _version_can_promote(version, champion):
            raise HTTPException(status_code=400, detail="Challenger did not pass promotion gates.")
        promoted = self.store.promote_strategy_version(version_id)
        if promoted is None:
            raise HTTPException(status_code=404, detail="Strategy version was not found.")
        return promoted

    def rollback_champion(self) -> StrategyVersion:
        version = self.store.rollback_champion()
        if version is None:
            raise HTTPException(status_code=400, detail="No previous champion is available.")
        return version

    def health(self) -> HealthResponse:
        return HealthResponse(
            status="ok",
            database="ok",
            tradingMode=self.config.trading_mode,
            staticIpReady=self.config.static_ip_ready,
        )

    def safety_status(self) -> SafetyStatus:
        state = self.store.get_safety_state()
        runtime = self.store.get_runtime()
        settings = self.store.get_settings()
        daily_loss_locked = self.store.daily_loss_used() >= settings.daily_max_loss
        message = "Safety checks are clear."
        if state["kill_switch_active"]:
            message = "Kill switch is active."
        elif runtime.emergency_lock:
            message = "Emergency lock is active."
        elif daily_loss_locked:
            message = "Daily loss lock is active."
        elif self.config.is_live_mode and not self.config.static_ip_ready:
            message = "Static IP readiness is required for live trading."
        return SafetyStatus(
            killSwitchActive=bool(state["kill_switch_active"]),
            emergencyLocked=runtime.emergency_lock,
            dailyLossLocked=daily_loss_locked,
            sessionActive=runtime.session_status == "active",
            staticIpReady=self.config.static_ip_ready,
            liveMode=self.config.is_live_mode,
            capitalLock=float(state["capital_lock"]),
            maxOrderLimit=int(state["max_order_limit"]),
            message=message,
        )

    def activate_kill_switch(self) -> SafetyStatus:
        self.store.set_kill_switch(True)
        return self.safety_status()

    def audit_events(self) -> list[AuditEvent]:
        return self.store.list_audit_events()

    def send_daily_report(self) -> ReportSendResponse:
        report = self.store.build_daily_report()
        self.store.insert_audit_event(
            event_type="report.daily.send",
            message="Daily report generated for notifier handoff.",
            details={"tradingDay": report.trading_day, "pnl": report.pnl},
        )
        return ReportSendResponse(ok=True, message="Daily report generated. Notifier hook is not configured.")

    def _assert_live_order_ready(self, *, allow_exit: bool = False) -> None:
        runtime = self.store.get_runtime()
        state = self.store.get_safety_state()
        settings = self.store.get_settings()
        if not self.config.is_live_mode:
            raise HTTPException(status_code=400, detail="Set TRADING_MODE=live before live orders.")
        if state["kill_switch_active"] and not allow_exit:
            raise HTTPException(status_code=400, detail="Kill switch is active.")
        if runtime.emergency_lock and not allow_exit:
            raise HTTPException(status_code=400, detail="Emergency lock is active.")
        if self.store.daily_loss_used() >= settings.daily_max_loss and not allow_exit:
            raise HTTPException(status_code=400, detail="Daily max-loss lock is active.")
        if not self.credentials_ready():
            raise HTTPException(status_code=400, detail="Breeze credentials are required.")
        if runtime.session_status != "active" or not runtime.session_token:
            raise HTTPException(status_code=400, detail="A valid daily Breeze session is required.")
        if not self.config.static_ip_ready:
            raise HTTPException(status_code=400, detail="Registered static IP readiness is required.")

    def _assert_live_broker_read_ready(self) -> None:
        runtime = self.store.get_runtime()
        if not self.config.is_live_mode:
            raise HTTPException(status_code=400, detail="Set TRADING_MODE=live before live broker reads.")
        if not self.credentials_ready():
            raise HTTPException(status_code=400, detail="Breeze credentials are required.")
        if runtime.session_status != "active" or not runtime.session_token:
            raise HTTPException(status_code=400, detail="A valid daily Breeze session is required.")

    def _live_autopilot_gate(self) -> tuple[bool, str]:
        try:
            self._assert_live_order_ready()
        except HTTPException as exc:
            return False, str(exc.detail)
        if self.store.daily_loss_used() >= self.store.get_settings().daily_max_loss:
            return False, "Daily max-loss lock is active."
        if len(self.store.list_open_trades()) >= int(self.store.get_safety_state()["max_open_positions"]):
            return False, "Max open positions reached."
        if self.store.latest_passed_backtest_any() is None:
            return False, "No approved strategy has a passing backtest."
        paper_ok, paper_reason = _paper_validation_gate(self.store)
        if not paper_ok:
            return False, paper_reason
        return True, "Live autopilot gates passed."

    def _get_live_order(self, order_id: str) -> LiveOrder:
        order = self.store.get_live_order(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Live order was not found.")
        return order

    def _default_stock(self) -> str:
        settings = self.store.get_settings()
        if settings.stock_preset == "CUSTOM" and settings.allowed_stocks:
            return settings.allowed_stocks[0]
        return "HDFCBANK"

    def _assert_approved_strategy(self, strategy: str) -> None:
        approved = {template.name for template in APPROVED_STRATEGIES}
        if strategy not in approved:
            raise HTTPException(status_code=400, detail="Strategy must be one of the approved templates.")

    def _quote_price(self, runtime: RuntimeState, stock: str) -> float:
        quote = self.breeze_client.get_quote(runtime.session_token or "", stock)
        price = getattr(quote, "last_price", None)
        if price is None and isinstance(quote, dict):
            price = quote.get("lastPrice") or quote.get("last_price")
        try:
            value = float(price)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Missing live quote for {stock}.")
        if value <= 0:
            raise HTTPException(status_code=400, detail=f"Invalid live quote for {stock}.")
        return value

    def _upsert_strategy_version_from_backtest(self, run: BacktestRun) -> None:
        version = StrategyVersion(
            id=f"{run.strategy}:v1",
            strategy=run.strategy,
            version="v1",
            parameters={},
            backtestMetrics=run.metrics.model_dump(by_alias=True),
            paperMetrics={},
            riskNotes=[run.reason],
            promotionStatus="backtested" if run.passed else "rejected",
            createdAt=utc_iso(),
        )
        self.store.save_strategy_version(version)


def _build_backtest_metrics(pnls: list[float], *, starting_capital: float = 10000) -> BacktestMetrics:
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss else (gross_profit if gross_profit else 0)
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    max_drawdown_percent = (max_drawdown / max(starting_capital, 1)) * 100
    return BacktestMetrics(
        winRate=round((len(wins) / len(pnls) * 100) if pnls else 0, 2),
        profitFactor=round(profit_factor, 2),
        maxDrawdown=round(max_drawdown_percent, 2),
        averageProfit=round(sum(wins) / len(wins), 2) if wins else 0,
        averageLoss=round(sum(losses) / len(losses), 2) if losses else 0,
        tradesCount=len(pnls),
        bestMarketCondition="uptrend" if gross_profit >= gross_loss else "range",
        worstMarketCondition="drawdown" if losses else "none",
    )


def _backtest_gate(metrics: BacktestMetrics) -> tuple[bool, str]:
    failures: list[str] = []
    if metrics.trades_count < BACKTEST_MIN_TRADES:
        failures.append("Backtest needs at least 100 trades.")
    if metrics.profit_factor < BACKTEST_MIN_PROFIT_FACTOR:
        failures.append("Profit factor is below 1.2.")
    if metrics.max_drawdown > BACKTEST_MAX_DRAWDOWN:
        failures.append("Max drawdown is above 10%.")
    if metrics.win_rate < BACKTEST_MIN_WIN_RATE:
        failures.append("Win rate is below 45%.")
    if failures:
        return False, " ".join(failures)
    return True, "Backtest passed live eligibility gates."


def _strategy_backtest_pnls(
    candles: list[Any],
    *,
    strategy: str,
    budget: float,
    stop_loss_percent: float,
    target_percent: float,
) -> list[float]:
    selector = StrategySelector()
    pnls: list[float] = []
    for index in range(20, len(candles) - 1):
        current = candles[index]
        entry = _number(_field(current, "close"))
        volume = _number(_field(current, "volume"))
        if entry <= 0:
            continue
        quantity = int(budget // entry)
        if quantity <= 0:
            continue

        indicators = calculate_indicators(
            {"lastPrice": entry, "volume": volume},
            candles[max(0, index - 30) : index],
        )
        selected = selector.choose(indicators)
        if selected is None or selected.name != strategy:
            continue

        next_candle = candles[index + 1]
        next_low = _number(_field(next_candle, "low"))
        next_high = _number(_field(next_candle, "high"))
        next_close = _number(_field(next_candle, "close"))
        stop = entry * (1 - stop_loss_percent / 100)
        target = entry * (1 + target_percent / 100)

        # Daily candles cannot reveal whether target or stop was touched first.
        # Treat a same-candle collision as a stop for conservative eligibility.
        if next_low > 0 and next_low <= stop:
            exit_price = stop
        elif next_high >= target:
            exit_price = target
        elif next_close > 0:
            exit_price = next_close
        else:
            continue

        gross_pnl = (exit_price - entry) * quantity
        estimated_cost = entry * quantity * 0.001
        pnls.append(round(gross_pnl - estimated_cost, 2))
    return pnls


def _paper_validation_gate(store: SQLiteStore) -> tuple[bool, str]:
    validation = store.paper_validation_status(
        required_days=PAPER_MIN_DAYS,
        required_trades=10,
        min_profit_factor=PAPER_MIN_PROFIT_FACTOR,
    )
    return validation.eligible, validation.reason


def _tool_availability() -> dict[str, bool]:
    return {
        "vectorbt": importlib.util.find_spec("vectorbt") is not None,
        "optuna": importlib.util.find_spec("optuna") is not None,
        "mlflow": importlib.util.find_spec("mlflow") is not None,
        "phoenix": importlib.util.find_spec("phoenix") is not None,
    }


def _version_can_promote(version: StrategyVersion, champion: StrategyVersion | None) -> bool:
    metrics = version.backtest_metrics
    if not metrics:
        return champion is None and version.promotion_status in {"generated", "backtested", "candidate"}
    passed = (
        float(metrics.get("profitFactor", 0)) >= BACKTEST_MIN_PROFIT_FACTOR
        and float(metrics.get("maxDrawdown", 100)) <= BACKTEST_MAX_DRAWDOWN
        and float(metrics.get("winRate", 0)) >= BACKTEST_MIN_WIN_RATE
        and int(metrics.get("tradesCount", 0)) >= BACKTEST_MIN_TRADES
    )
    if not passed:
        return False
    if champion is None:
        return True
    champion_pf = float(champion.backtest_metrics.get("profitFactor", 0))
    champion_drawdown = float(champion.backtest_metrics.get("maxDrawdown", 100))
    challenger_pf = float(metrics.get("profitFactor", 0))
    challenger_drawdown = float(metrics.get("maxDrawdown", 100))
    return challenger_pf >= champion_pf + 0.1 or (
        challenger_pf >= champion_pf and challenger_drawdown < champion_drawdown
    )


def _broker_order_id(value: Any) -> str | None:
    if isinstance(value, dict):
        success = value.get("Success")
        if isinstance(success, dict):
            return str(success.get("order_id") or success.get("orderId") or "")
        return str(value.get("orderId") or value.get("order_id") or "") or None
    return getattr(value, "order_id", None)


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
