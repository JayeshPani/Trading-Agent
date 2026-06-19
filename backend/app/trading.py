from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from fastapi import HTTPException

from .breeze import BreezeClient, BreezeClientError
from .config import AppConfig
from .rate_limit import RateLimitError
from .risk import ProposedTrade, RiskEngine, RiskResult
from .scanner import APPROVED_STRATEGIES, MarketScanner
from .schemas import (
    BrokerCandle,
    BrokerOrder,
    BrokerPortfolio,
    BrokerQuote,
    BrokerStatus,
    BrokerTrade,
    DashboardResponse,
    DailyReport,
    EmergencyExitResponse,
    Explanation,
    OpenTrade,
    PaperExitResponse,
    PnlSummary,
    ScannerCandidate,
    ScannerResult,
    StrategyTemplate,
    TradeHistoryItem,
    TradingSettings,
    is_equity_symbol,
    normalize_symbol,
)
from .state import RuntimeState
from .store import SQLiteStore
from .time_utils import current_trading_day, is_intraday_square_off_time, now_utc, utc_iso


class SignalService:
    def build_paper_signal(
        self, *, candidate: ScannerCandidate, settings: TradingSettings
    ) -> ProposedTrade:
        stock = normalize_symbol(candidate.stock_code)
        entry = candidate.last_price
        stop_loss = round(entry * (1 - settings.stop_loss_percent / 100), 2)
        target = round(entry * (1 + settings.target_percent / 100), 2)
        quantity = max(int(settings.budget // entry), 1)

        return ProposedTrade(
            stock=stock,
            side="BUY",
            quantity=quantity,
            entry_price=entry,
            stop_loss=stop_loss,
            target=target,
            order_type="LIMIT",
            asset_class="equity",
            strategy=candidate.strategy or "scanner-paper",
            strategy_version=candidate.strategy_version or "v1",
            confidence=min(max(candidate.score, 0), 95),
            liquidity=candidate.indicators.get("liquidity"),
            volatility=candidate.indicators.get("volatility"),
        )


@dataclass(frozen=True)
class BrokerMonitorFailure:
    stock: str
    message: str


@dataclass(frozen=True)
class PaperMonitorResult:
    open_trades: list[OpenTrade]
    attempted: int
    successful: int
    failures: list[BrokerMonitorFailure]

    @property
    def fully_successful(self) -> bool:
        return not self.failures

    @property
    def fully_failed(self) -> bool:
        return self.attempted > 0 and self.successful == 0


class TradingService:
    def __init__(
        self,
        *,
        config: AppConfig,
        store: SQLiteStore,
        risk_engine: RiskEngine,
        breeze_client: BreezeClient,
        signal_service: SignalService | None = None,
        scanner: MarketScanner | None = None,
        credentials_ready: Callable[[], bool] | None = None,
    ):
        self.config = config
        self.store = store
        self.risk_engine = risk_engine
        self.breeze_client = breeze_client
        self.signal_service = signal_service or SignalService()
        self.scanner = scanner or MarketScanner(breeze_client)
        self.credentials_ready = credentials_ready or (lambda: self.config.has_breeze_credentials)
        self.store.upsert_strategies(APPROVED_STRATEGIES)

    def dashboard(self) -> DashboardResponse:
        settings = self.store.get_settings()
        runtime = self.store.get_runtime()
        open_trades = self.store.list_open_trades()
        daily_loss = self.store.daily_loss_used()
        current_pnl = self.store.current_pnl()
        remaining_budget = max(settings.budget - self.store.open_capital_used(), 0)
        latest_explanation = self.store.latest_explanation()

        risk_status = "clear"
        risk_message = "Risk checks are available."
        if runtime.emergency_lock:
            risk_status = "locked"
            risk_message = "Emergency lock is active for the current trading day."
        elif self.config.is_live_mode and runtime.session_status != "active":
            risk_status = "warning"
            risk_message = "Live mode needs a valid daily Breeze session."
        elif daily_loss >= settings.daily_max_loss:
            risk_status = "locked"
            risk_message = "Daily max loss has been reached."

        return DashboardResponse(
            autopilotEnabled=runtime.autopilot_enabled,
            sessionStatus=runtime.session_status,
            pnl=PnlSummary(
                currentPnl=current_pnl,
                dailyLossUsed=daily_loss,
                remainingBudget=remaining_budget,
                openTradesCount=len(open_trades),
            ),
            openTrades=open_trades,
            latestExplanation=latest_explanation,
            riskStatus=risk_status,
            riskMessage=risk_message,
        )

    def save_settings(self, settings: TradingSettings) -> TradingSettings:
        self.store.save_settings(settings)
        return self.store.get_settings()

    def start_autopilot(self) -> bool:
        runtime = self.store.get_runtime()
        if runtime.emergency_lock:
            raise HTTPException(status_code=400, detail="Emergency lock is active.")
        if self.config.is_live_mode:
            self._assert_live_ready(runtime)

        runtime.autopilot_enabled = True
        runtime.trading_day = current_trading_day()
        self.store.save_runtime(runtime)

        if self.config.trading_mode == "paper" and not self.store.list_open_trades():
            self.run_once()

        return True

    def stop_autopilot(self) -> bool:
        runtime = self.store.get_runtime()
        runtime.autopilot_enabled = False
        self.store.save_runtime(runtime)
        return False

    def list_strategies(self) -> list[StrategyTemplate]:
        return self.store.list_strategies()

    def run_scanner(self, *, max_symbols: int | None = None) -> ScannerResult:
        result = self.scanner.scan(
            settings=self.store.get_settings(),
            runtime=self.store.get_runtime(),
            max_symbols=max_symbols,
        )
        self.store.save_scanner_result(result)
        return result

    def latest_scanner_result(self) -> ScannerResult:
        return self.store.latest_scanner_result()

    def run_paper_once(self) -> Explanation:
        if self.config.trading_mode != "paper":
            raise HTTPException(status_code=400, detail="Paper run is available only in paper mode.")
        self.run_once()
        explanation = self.store.latest_explanation()
        if explanation is None:
            raise HTTPException(status_code=500, detail="Paper run did not record an explanation.")
        return explanation

    def monitor_paper_trades(self) -> list[OpenTrade]:
        return self.monitor_paper_trades_with_status().open_trades

    def monitor_paper_trades_with_status(self) -> PaperMonitorResult:
        runtime = self.store.get_runtime()
        if runtime.session_status != "active" or not runtime.session_token:
            raise HTTPException(status_code=400, detail="A valid daily Breeze session is required.")

        settings = self.store.get_settings()
        intraday_cutoff = (
            self.config.enforce_market_hours
            and settings.mode == "intraday"
            and is_intraday_square_off_time()
        )
        trades = self.store.list_open_trades()
        successful = 0
        failures: list[BrokerMonitorFailure] = []
        for trade in trades:
            try:
                price = self._quote_price(runtime.session_token, trade.stock)
            except (BreezeClientError, RateLimitError) as exc:
                failures.append(
                    BrokerMonitorFailure(stock=trade.stock, message=str(exc))
                )
                continue
            successful += 1
            updated = self.store.update_open_trade_pnl(trade.id, price)
            if updated is None:
                continue
            if intraday_cutoff:
                self._close_paper_trade(
                    trade_id=updated.id,
                    exit_price=price,
                    status="exited",
                    exit_reason="Intraday square-off",
                )
            elif updated.side == "BUY" and price <= updated.stop_loss:
                self._close_paper_trade(
                    trade_id=updated.id,
                    exit_price=price,
                    status="stop_loss_hit",
                    exit_reason="Stop-loss hit",
                )
            elif updated.side == "BUY" and price >= updated.target:
                self._close_paper_trade(
                    trade_id=updated.id,
                    exit_price=price,
                    status="target_hit",
                    exit_reason="Target hit",
                )
            elif updated.side == "SELL" and price >= updated.stop_loss:
                self._close_paper_trade(
                    trade_id=updated.id,
                    exit_price=price,
                    status="stop_loss_hit",
                    exit_reason="Stop-loss hit",
                )
            elif updated.side == "SELL" and price <= updated.target:
                self._close_paper_trade(
                    trade_id=updated.id,
                    exit_price=price,
                    status="target_hit",
                    exit_reason="Target hit",
                )
        return PaperMonitorResult(
            open_trades=self.store.list_open_trades(),
            attempted=len(trades),
            successful=successful,
            failures=failures,
        )

    def paper_exit_trade(self, trade_id: str) -> PaperExitResponse:
        runtime = self.store.get_runtime()
        if runtime.session_status != "active" or not runtime.session_token:
            raise HTTPException(status_code=400, detail="A valid daily Breeze session is required.")
        trade = self.store.get_open_trade(trade_id)
        if trade is None:
            raise HTTPException(status_code=404, detail="Open trade was not found.")
        price = self._quote_price(runtime.session_token, trade.stock)
        history = self._close_paper_trade(
            trade_id=trade.id,
            exit_price=price,
            status="exited",
            exit_reason="Manual paper exit",
        )
        explanation = self.store.latest_explanation()
        if explanation is None:
            raise HTTPException(status_code=500, detail="Paper exit did not record an explanation.")
        return PaperExitResponse(trade=history, explanation=explanation)

    def monitor_live_exits(self) -> list[TradeHistoryItem]:
        runtime = self.store.get_runtime()
        if not self.config.is_live_mode:
            raise HTTPException(status_code=400, detail="Live exit monitoring requires live mode.")
        if runtime.session_status != "active" or not runtime.session_token:
            raise HTTPException(status_code=400, detail="A valid daily Breeze session is required.")

        closed: list[TradeHistoryItem] = []
        settings = self.store.get_settings()
        force_reason: str | None = None
        if runtime.emergency_lock:
            force_reason = "Emergency lock"
        elif self.store.daily_loss_used() >= settings.daily_max_loss:
            force_reason = "Daily max-loss lock"
        elif (
            self.config.enforce_market_hours
            and settings.mode == "intraday"
            and is_intraday_square_off_time()
        ):
            force_reason = "Intraday square-off"

        for trade in self.store.list_open_trades():
            price = self._quote_price(runtime.session_token, trade.stock)
            updated = self.store.update_open_trade_pnl(trade.id, price)
            if updated is None:
                continue
            exit_reason: str | None = force_reason
            status = "exited"
            if exit_reason is None:
                if updated.side == "BUY" and price <= updated.stop_loss:
                    exit_reason = "Stop-loss hit"
                    status = "stop_loss_hit"
                elif updated.side == "BUY" and price >= updated.target:
                    exit_reason = "Target hit"
                    status = "target_hit"
                elif updated.side == "SELL" and price >= updated.stop_loss:
                    exit_reason = "Stop-loss hit"
                    status = "stop_loss_hit"
                elif updated.side == "SELL" and price <= updated.target:
                    exit_reason = "Target hit"
                    status = "target_hit"
            if exit_reason is None:
                continue
            self._square_off_live_trade(runtime, updated, price)
            history = self.store.close_trade(
                trade_id=updated.id,
                exit_price=price,
                status=status,
                exit_reason=f"Auto live exit: {exit_reason}",
            )
            if history is not None:
                closed.append(history)
                self.store.insert_audit_event(
                    event_type="live.exit.auto",
                    message=f"Auto live exit sent for {history.stock}.",
                    details={"tradeId": history.id, "reason": exit_reason, "pnl": history.pnl},
                )
        return closed

    def daily_report(self) -> DailyReport:
        return self.store.build_daily_report()

    def emergency_exit(self) -> EmergencyExitResponse:
        runtime = self.store.get_runtime()
        runtime.autopilot_enabled = False
        runtime.emergency_lock = True
        self.store.save_runtime(runtime)

        if self.config.is_live_mode and self.store.list_open_trades():
            self._square_off_live_trades(runtime)

        closed = self.store.close_open_trades("Emergency exit")

        self.store.insert_explanation(
            Explanation(
                summary=f"Emergency exit activated. Closed {closed} open paper/live tracked trade(s).",
                positiveReasons=[],
                negativeReasons=["Emergency lock prevents new entries for the current trading day."],
                riskDecision="rejected",
                riskReason="Emergency lock is active.",
                exitReason="Emergency exit",
            )
        )
        return EmergencyExitResponse(locked=True)

    def broker_status(self) -> BrokerStatus:
        runtime = self.store.get_runtime()
        api_ok, api_reason = self.risk_engine.rate_limiter.can_call_api()
        order_ok, order_reason = self.risk_engine.rate_limiter.can_send_order_action()
        message = "Broker bridge is ready for paper-mode inspection."
        if self.config.is_live_mode and runtime.session_status != "active":
            message = "Live broker access needs a valid daily Breeze session."
        elif self.config.is_live_mode and not self.config.static_ip_ready:
            message = "Live broker order actions need the registered static IP."
        elif not api_ok:
            message = api_reason
        elif not order_ok:
            message = order_reason

        return BrokerStatus(
            credentialsConfigured=self.credentials_ready(),
            sessionStatus=runtime.session_status,
            tradingMode=self.config.trading_mode,
            staticIpReady=self.config.static_ip_ready,
            apiRateLimitAvailable=api_ok,
            orderRateLimitAvailable=order_ok,
            message=message,
        )

    def broker_quote(self, stock_code: str) -> BrokerQuote:
        stock = self._validate_broker_stock(stock_code)
        return self.breeze_client.get_quote(self._active_session_token(), stock)

    def broker_history(
        self,
        stock_code: str,
        *,
        from_date: str | None,
        to_date: str | None,
        interval: str,
    ) -> list[BrokerCandle]:
        stock = self._validate_broker_stock(stock_code)
        end = to_date or utc_iso()
        start = from_date or (now_utc() - timedelta(days=5)).isoformat()
        return self.breeze_client.get_historical_candles(
            self._active_session_token(),
            stock_code=stock,
            from_date=start,
            to_date=end,
            interval=interval,
        )

    def broker_portfolio(self) -> BrokerPortfolio:
        session_token = self._active_session_token()
        return BrokerPortfolio(
            funds=self.breeze_client.get_funds(session_token),
            holdings=self.breeze_client.get_holdings(session_token),
            positions=self.breeze_client.get_positions(session_token),
        )

    def broker_orders(self) -> list[BrokerOrder]:
        return self.breeze_client.get_order_list(self._active_session_token())

    def broker_trades(self) -> list[BrokerTrade]:
        return self.breeze_client.get_trade_list(self._active_session_token())

    def validate_session(self, session_key: str) -> RuntimeState:
        try:
            session = self.breeze_client.validate_session(session_key)
        except BreezeClientError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        runtime = self.store.get_runtime()
        runtime.session_status = "active"
        runtime.session_created_at = utc_iso()
        runtime.session_expires_at = session.expires_at
        runtime.session_token = session.session_token
        self.store.save_runtime(runtime)
        return runtime

    def run_once(self) -> RiskResult:
        settings = self.store.get_settings()
        runtime = self.store.get_runtime()
        scanner_result = self.run_scanner(max_symbols=self.config.scanner_max_symbols_per_cycle)
        candidate = self._select_scanner_candidate(scanner_result)
        if candidate is None:
            self.store.insert_explanation(self._no_candidate_explanation(scanner_result))
            return RiskResult(False, "No scanner candidate passed strategy and scanner checks.")

        proposed = self.signal_service.build_paper_signal(candidate=candidate, settings=settings)
        risk = self.risk_engine.review(
            settings=settings,
            runtime=runtime,
            trade=proposed,
            trades_today=self.store.count_trades_today(),
            daily_loss_used=self.store.daily_loss_used(),
            open_symbols={trade.stock for trade in self.store.list_open_trades()},
            open_capital_used=self.store.open_capital_used(),
            open_risk_used=self.store.open_risk_used(),
        )
        self.store.insert_risk_event(
            decision=risk.decision,
            reason=risk.reason,
            stock=proposed.stock,
            details={
                "strategy": proposed.strategy,
                "strategy_version": proposed.strategy_version,
                "mode": self.config.trading_mode,
            },
        )

        if not risk.approved:
            self.store.insert_explanation(self._risk_rejection_explanation(proposed, risk, scanner_result))
            return risk

        trade_id = self._execute(proposed, settings, runtime)
        self.store.insert_explanation(self._approval_explanation(trade_id, proposed, risk, scanner_result))
        return risk

    def _execute(
        self, proposed: ProposedTrade, settings: TradingSettings, runtime: RuntimeState
    ) -> str:
        if self.config.is_live_mode:
            if not runtime.session_token:
                raise HTTPException(status_code=400, detail="Missing active Breeze session token.")
            try:
                self.breeze_client.place_order(
                    runtime.session_token,
                    {
                        "stock_code": proposed.stock,
                        "exchange_code": "NSE",
                        "product_type": "cash",
                        "action": proposed.side.lower(),
                        "quantity": proposed.quantity,
                        "price": proposed.entry_price,
                        "order_type": "limit",
                        "validity": "day",
                    },
                )
            except BreezeClientError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        return self.store.insert_trade(
            stock=proposed.stock,
            side=proposed.side,
            quantity=proposed.quantity,
            entry_price=proposed.entry_price,
            stop_loss=proposed.stop_loss,
            target=proposed.target,
            mode=settings.mode,
            strategy=proposed.strategy,
            strategy_version=proposed.strategy_version,
            paper=not self.config.is_live_mode,
        )

    def _assert_live_ready(self, runtime: RuntimeState) -> None:
        if not self.credentials_ready():
            raise HTTPException(status_code=400, detail="Breeze credentials are required for live mode.")
        if runtime.session_status != "active":
            raise HTTPException(status_code=400, detail="A valid daily Breeze session is required.")
        if not self.config.static_ip_ready:
            raise HTTPException(status_code=400, detail="Registered static IP readiness is required.")

    def _active_session_token(self) -> str:
        runtime = self.store.get_runtime()
        if runtime.session_status != "active" or not runtime.session_token:
            raise HTTPException(status_code=400, detail="A valid daily Breeze session is required.")
        return runtime.session_token

    def _quote_price(self, session_token: str, stock: str) -> float:
        quote = self.breeze_client.get_quote(session_token, stock)
        price = getattr(quote, "last_price", None)
        if price is None and isinstance(quote, dict):
            price = quote.get("lastPrice") or quote.get("last_price")
        try:
            price_value = float(price)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Missing live quote for {stock}.")
        if price_value <= 0:
            raise HTTPException(status_code=400, detail=f"Invalid live quote for {stock}.")
        return price_value

    @staticmethod
    def _select_scanner_candidate(scanner_result: ScannerResult) -> ScannerCandidate | None:
        for candidate in scanner_result.shortlist:
            if not candidate.rejected and candidate.strategy:
                return candidate
        return None

    def _close_paper_trade(
        self,
        *,
        trade_id: str,
        exit_price: float,
        status: str,
        exit_reason: str,
    ) -> TradeHistoryItem:
        history = self.store.close_trade(
            trade_id=trade_id,
            exit_price=exit_price,
            status=status,
            exit_reason=exit_reason,
        )
        if history is None:
            raise HTTPException(status_code=404, detail="Open trade was not found.")
        self.store.insert_explanation(
            Explanation(
                tradeId=history.id,
                stock=history.stock,
                strategy=history.strategy,
                summary=f"Paper trade for {history.stock} closed: {exit_reason}.",
                positiveReasons=[f"Exit price was {exit_price:.2f}."],
                negativeReasons=[] if history.pnl >= 0 else ["Trade closed with a simulated loss."],
                riskDecision="approved",
                riskReason="Paper monitor applied configured exit rules.",
                exitReason=exit_reason,
            )
        )
        return history

    @staticmethod
    def _validate_broker_stock(stock_code: str) -> str:
        stock = normalize_symbol(stock_code)
        if not is_equity_symbol(stock):
            raise HTTPException(status_code=400, detail="Only cash-equity stock symbols are allowed.")
        return stock

    def _square_off_live_trades(self, runtime: RuntimeState) -> None:
        if not runtime.session_token:
            raise HTTPException(status_code=400, detail="Missing active Breeze session token.")

        try:
            for trade in self.store.list_open_trades():
                self._square_off_live_trade(runtime, trade, trade.entry_price)
        except (BreezeClientError, HTTPException) as exc:
            reason = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
            self.store.insert_explanation(
                Explanation(
                    summary="Emergency exit locked the system, but Breeze square-off failed.",
                    positiveReasons=["Autopilot was stopped and emergency lock was enabled."],
                    negativeReasons=[reason],
                    riskDecision="rejected",
                    riskReason=reason,
                    exitReason="Emergency exit square-off failed",
                )
            )
            raise HTTPException(status_code=400, detail=reason) from exc

    def _square_off_live_trade(
        self, runtime: RuntimeState, trade: OpenTrade, price: float
    ) -> None:
        if not runtime.session_token:
            raise HTTPException(status_code=400, detail="Missing active Breeze session token.")
        action = "sell" if trade.side == "BUY" else "buy"
        try:
            self.breeze_client.square_off(
                runtime.session_token,
                {
                    "stock_code": trade.stock,
                    "exchange_code": "NSE",
                    "product_type": "cash",
                    "quantity": trade.quantity,
                    "price": price,
                    "action": action,
                    "order_type": "limit",
                    "validity": "day",
                },
            )
        except BreezeClientError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @staticmethod
    def _approval_explanation(
        trade_id: str, proposed: ProposedTrade, risk: RiskResult, scanner_result: ScannerResult
    ) -> Explanation:
        rejected = [
            f"{candidate.stock_code}: {candidate.rejection_reason or 'lower score'}"
            for candidate in scanner_result.candidates
            if candidate.rejected or candidate.stock_code != proposed.stock
        ][:8]
        return Explanation(
            tradeId=trade_id,
            stock=proposed.stock,
            strategy=proposed.strategy,
            confidence=proposed.confidence,
            summary=f"Paper trade opened for {proposed.stock} after scanner, strategy, and risk approval.",
            positiveReasons=[
                "Stock is inside the allowed universe.",
                "Stop-loss is defined before entry.",
                "Budget and daily-loss checks passed.",
                f"Strategy selected: {proposed.strategy}.",
            ],
            negativeReasons=[],
            selectedCandidates=[proposed.stock],
            rejectedCandidates=rejected,
            riskDecision="approved",
            riskReason=risk.reason,
        )

    @staticmethod
    def _risk_rejection_explanation(
        proposed: ProposedTrade, risk: RiskResult, scanner_result: ScannerResult
    ) -> Explanation:
        return Explanation(
            stock=proposed.stock,
            strategy=proposed.strategy,
            confidence=proposed.confidence,
            summary=f"No trade opened for {proposed.stock}. Risk engine rejected the setup.",
            positiveReasons=[],
            negativeReasons=[risk.reason],
            selectedCandidates=[proposed.stock],
            rejectedCandidates=[
                f"{candidate.stock_code}: {candidate.rejection_reason or 'not selected'}"
                for candidate in scanner_result.candidates
                if candidate.stock_code != proposed.stock
            ][:8],
            riskDecision="rejected",
            riskReason=risk.reason,
        )

    @staticmethod
    def _no_candidate_explanation(scanner_result: ScannerResult) -> Explanation:
        rejected = [
            f"{candidate.stock_code}: {candidate.rejection_reason or 'not selected'}"
            for candidate in scanner_result.candidates
        ][:10]
        return Explanation(
            summary="No paper trade opened. Scanner did not find an approved candidate.",
            positiveReasons=[],
            negativeReasons=rejected or ["No scanner candidates were available."],
            selectedCandidates=[],
            rejectedCandidates=rejected,
            riskDecision="rejected",
            riskReason="No scanner candidate passed strategy and scanner checks.",
        )
