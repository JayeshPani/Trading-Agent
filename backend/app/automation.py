from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import HTTPException

from .advanced import AdvancedTradingService
from .agent import AgentService
from .breeze import BreezeClientError
from .config import AppConfig
from .schemas import (
    AgentDecisionResponse,
    AutomationEvent,
    AutomationRun,
    AutomationStatus,
    PaperValidationStatus,
)
from .store import SQLiteStore
from .time_utils import is_intraday_square_off_time, is_market_open, now_utc
from .trading import TradingService


class AutomationRunner:
    def __init__(
        self,
        *,
        config: AppConfig,
        store: SQLiteStore,
        trading_service: TradingService,
        agent_service: AgentService,
        advanced_service: AdvancedTradingService,
        credentials_ready,
    ):
        self.config = config
        self.store = store
        self.trading_service = trading_service
        self.agent_service = agent_service
        self.advanced_service = advanced_service
        self.credentials_ready = credentials_ready
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    def status(self) -> AutomationStatus:
        state = self.store.get_automation_state()
        latest_events = self.store.list_automation_events(limit=1)
        enabled = bool(state["enabled"])
        message = "Automation is stopped."
        if not self.config.automation_enabled:
            message = "Set AUTOMATION_ENABLED=true and restart the backend to allow scheduled automation."
        elif enabled:
            message = "Automation runner is enabled."
        elif latest_events:
            message = latest_events[0].message
        if state["latest_error"]:
            message = f"Latest automation error: {state['latest_error']}"
        elif state.get("broker_health") == "degraded":
            message = "Broker temporarily unavailable, retrying on schedule."
        elif state.get("broker_health") == "unavailable":
            message = "Breeze market data is unavailable. Monitoring will keep retrying safely."
        return AutomationStatus(
            enabled=enabled,
            running=bool(self._task and not self._task.done()),
            configEnabled=self.config.automation_enabled,
            mode=self.config.trading_mode,
            autoLiveEntriesEnabled=self.config.auto_live_entries_enabled,
            autoLiveExitsEnabled=self.config.auto_live_exits_enabled,
            lastPaperScanAt=state["last_paper_scan_at"],
            lastPaperMonitorAt=state["last_paper_monitor_at"],
            lastLiveExitAt=state["last_live_exit_at"],
            lastLiveEntryAt=state["last_live_entry_at"],
            latestError=state["latest_error"],
            brokerHealth=state.get("broker_health") or "healthy",
            consecutiveBrokerFailures=int(state.get("consecutive_broker_failures") or 0),
            lastBrokerSuccessAt=state.get("last_broker_success_at"),
            latestBrokerError=state.get("latest_broker_error"),
            message=message,
        )

    def start(self) -> AutomationStatus:
        if not self.config.automation_enabled:
            raise HTTPException(
                status_code=400,
                detail="Set AUTOMATION_ENABLED=true and restart the backend before starting automation.",
            )
        self.store.set_automation_enabled(True)
        self.store.set_automation_error(None)
        self.store.insert_automation_event(
            event_type="automation.start",
            severity="info",
            message="Automation enabled.",
        )
        return self.status()

    def stop(self) -> AutomationStatus:
        self.store.set_automation_enabled(False)
        self.store.insert_automation_event(
            event_type="automation.stop",
            severity="info",
            message="Automation stopped.",
        )
        return self.status()

    def events(self) -> list[AutomationEvent]:
        return self.store.list_automation_events()

    def paper_validation(self) -> PaperValidationStatus:
        return self.store.paper_validation_status()

    async def start_background(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop_background(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def _loop(self) -> None:
        while True:
            try:
                state = self.store.get_automation_state()
                if self.config.automation_enabled and bool(state["enabled"]):
                    # Scheduled automation should remain idle outside market hours.
                    # Manual Run Once still records a clear "Market is closed" result.
                    if not self.config.enforce_market_hours or is_market_open():
                        await self.run_once(manual=False)
            except Exception as exc:  # pragma: no cover - defensive loop guard
                self.store.insert_automation_event(
                    event_type="automation.error",
                    severity="error",
                    message=str(exc),
                )
            await asyncio.sleep(5)

    async def run_once(self, *, manual: bool = True) -> AutomationRun:
        async with self._lock:
            return await asyncio.to_thread(self._run_once_sync, manual)

    def _run_once_sync(self, manual: bool) -> AutomationRun:
        run_id = self.store.create_automation_run(
            mode=self.config.trading_mode,
            status="running",
            summary="Automation cycle started.",
        )
        try:
            blocker = self._blocker(manual=manual)
            if blocker:
                self.store.insert_automation_event(
                    event_type="automation.blocked",
                    severity="warning",
                    message=blocker,
                    details={"mode": self.config.trading_mode},
                )
                self.store.finish_automation_run(run_id, status="blocked", summary=blocker)
                return self._latest_run(run_id)

            if self.config.trading_mode == "paper":
                summary = self._run_paper_cycle()
            elif self.config.is_live_mode:
                summary = self._run_live_cycle()
            else:
                summary = f"Unsupported trading mode: {self.config.trading_mode}."

            if self.store.get_automation_state().get("broker_health") != "unavailable":
                self.store.set_automation_error(None)
            self.store.finish_automation_run(run_id, status="completed", summary=summary)
            self.store.insert_automation_event(
                event_type="automation.completed",
                severity="info",
                message=summary,
                details={"mode": self.config.trading_mode},
            )
            return self._latest_run(run_id)
        except Exception as exc:
            self.store.insert_automation_event(
                event_type="automation.error",
                severity="error",
                message=str(exc),
                details={"mode": self.config.trading_mode},
            )
            self.store.finish_automation_run(run_id, status="failed", summary=str(exc))
            return self._latest_run(run_id)

    def _blocker(self, *, manual: bool) -> str | None:
        runtime = self.store.get_runtime()
        settings = self.store.get_settings()
        safety = self.store.get_safety_state()
        if not manual and not self.config.automation_enabled:
            return "Automation config is disabled."
        if self.config.enforce_market_hours and not is_market_open():
            return "Market is closed."
        if safety["kill_switch_active"]:
            return "Kill switch is active."
        if runtime.emergency_lock:
            return "Emergency lock is active."
        if runtime.session_status != "active" or not runtime.session_token:
            return "Daily Breeze session is not active."
        if self.store.daily_loss_used() >= settings.daily_max_loss:
            return "Daily max-loss lock is active."
        if self.config.is_live_mode:
            if not self.credentials_ready():
                return "Breeze credentials are required."
            if not self.config.static_ip_ready:
                return "Registered static IP readiness is required."
        return None

    def _run_paper_cycle(self) -> str:
        runtime = self.store.get_runtime()
        if not runtime.autopilot_enabled:
            return "Paper automation skipped because autopilot is OFF."

        actions: list[str] = []
        settings = self.store.get_settings()
        intraday_cutoff = (
            self.config.enforce_market_hours
            and settings.mode == "intraday"
            and is_intraday_square_off_time()
        )
        if intraday_cutoff:
            result = self._monitor_paper_trades()
            return (
                "intraday square-off processed; "
                f"{len(result.open_trades)} paper trade(s) remain open"
            )

        state = self.store.get_automation_state()
        monitor_had_failures = False
        if self._due(state["last_paper_monitor_at"], self.config.auto_paper_monitor_interval_seconds):
            result = self._monitor_paper_trades()
            monitor_had_failures = bool(result.failures)
            actions.append(f"monitored {len(result.open_trades)} open paper trade(s)")
            if result.failures:
                actions.append(f"{len(result.failures)} quote update(s) unavailable")
            if result.fully_failed:
                return "; ".join(actions)

        state = self.store.get_automation_state()
        if self._due(state["last_paper_scan_at"], self.config.auto_paper_scan_interval_seconds):
            try:
                response = self.agent_service.paper_cycle()
            except HTTPException as exc:
                if exc.status_code != 503:
                    raise
                message = str(exc.detail)
                self._record_broker_failure(message)
                actions.append("scanner paused because Breeze market data is unavailable")
                return "; ".join(actions)
            except BreezeClientError as exc:
                if not exc.retryable:
                    raise
                self._record_broker_failure(str(exc))
                actions.append("scanner paused because Breeze market data is unavailable")
                return "; ".join(actions)
            finally:
                self.store.update_automation_timestamp("last_paper_scan_at")
            actions.append(f"agent decision {response.decision.action}")
            self._apply_paper_agent_exit(response)
            scanner_result = self.store.latest_scanner_result()
            if scanner_result.broker_status == "degraded":
                self._record_broker_degraded(
                    scanner_result.broker_error
                    or "Some Breeze scanner requests were temporarily unavailable.",
                    had_success=(
                        len(scanner_result.candidates)
                        > scanner_result.broker_error_count
                    ),
                )
            elif not monitor_had_failures:
                self._record_broker_success()
            self._record_recovered_requests()

        return "; ".join(actions) if actions else "No paper automation action was due."

    def _monitor_paper_trades(self):
        try:
            result = self.trading_service.monitor_paper_trades_with_status()
        finally:
            # An attempted cycle must wait for the normal monitor interval even if
            # Breeze is unavailable, otherwise the 5-second scheduler creates a retry storm.
            self.store.update_automation_timestamp("last_paper_monitor_at")

        self._record_recovered_requests()
        if result.attempted == 0:
            return result
        if result.fully_successful:
            self._record_broker_success()
        elif result.fully_failed:
            message = result.failures[0].message
            self._record_broker_failure(message)
        else:
            message = result.failures[0].message
            self._record_broker_degraded(message, had_success=result.successful > 0)
        return result

    def _record_recovered_requests(self) -> None:
        consumer = getattr(
            self.trading_service.breeze_client,
            "consume_recovery_notices",
            None,
        )
        if not callable(consumer):
            return
        for notice in consumer():
            self.store.insert_automation_event(
                event_type="automation.broker_retry_recovered",
                severity="warning",
                message=notice.message,
                details={"endpoint": notice.endpoint},
            )

    def _record_broker_degraded(self, message: str, *, had_success: bool) -> None:
        self.store.record_broker_degraded(message, had_success=had_success)
        self.store.insert_automation_event(
            event_type="automation.broker_degraded",
            severity="warning",
            message="Broker temporarily unavailable for part of this cycle; retrying on schedule.",
            details={"brokerError": message},
        )

    def _record_broker_failure(self, message: str) -> None:
        previous = self.store.get_automation_state()
        state = self.store.record_broker_failure(message)
        failures = int(state.get("consecutive_broker_failures") or 0)
        unavailable = state.get("broker_health") == "unavailable"
        became_unavailable = unavailable and previous.get("broker_health") != "unavailable"
        self.store.insert_automation_event(
            event_type=(
                "automation.broker_unavailable"
                if became_unavailable
                else "automation.broker_degraded"
            ),
            severity="error" if became_unavailable else "warning",
            message=(
                "Breeze market data is unavailable after three consecutive cycles."
                if became_unavailable
                else "Broker temporarily unavailable; retrying on schedule."
            ),
            details={
                "brokerError": message,
                "consecutiveFailures": failures,
            },
        )

    def _record_broker_success(self) -> None:
        previous = self.store.get_automation_state()
        self.store.record_broker_success()
        if previous.get("broker_health") != "healthy":
            self.store.insert_automation_event(
                event_type="automation.broker_recovered",
                severity="info",
                message="Breeze market data recovered and monitoring is healthy.",
            )

    def _run_live_cycle(self) -> str:
        actions: list[str] = []
        settings = self.store.get_settings()
        intraday_cutoff = (
            self.config.enforce_market_hours
            and settings.mode == "intraday"
            and is_intraday_square_off_time()
        )
        state = self.store.get_automation_state()
        if (
            self.config.auto_live_exits_enabled
            and (
                intraday_cutoff
                or self._due(state["last_live_exit_at"], self.config.auto_live_exit_interval_seconds)
            )
        ):
            closed = self.trading_service.monitor_live_exits()
            self.store.update_automation_timestamp("last_live_exit_at")
            actions.append(f"processed {len(closed)} live exit(s)")

        state = self.store.get_automation_state()
        if (
            self.config.auto_live_entries_enabled
            and self.config.auto_live_exits_enabled
            and not intraday_cutoff
            and self._due(state["last_live_entry_at"], self.config.auto_live_entry_interval_seconds)
        ):
            status = self.advanced_service.live_autopilot_status()
            if not status.eligible or not status.enabled:
                actions.append(f"live entry skipped: {status.reason}")
            else:
                response = self.agent_service.live_proposal()
                if response.live_order is not None:
                    self.advanced_service.confirm_live_order(response.live_order.id)
                    actions.append(f"confirmed live order {response.live_order.id}")
                else:
                    actions.append(f"agent decision {response.decision.action}")
            self.store.update_automation_timestamp("last_live_entry_at")

        return "; ".join(actions) if actions else "No live automation action was due."

    def _apply_paper_agent_exit(self, response: AgentDecisionResponse) -> None:
        decision = response.decision
        if decision.action != "PROPOSE_EXIT" or not decision.stock:
            return
        trade = next(
            (open_trade for open_trade in self.store.list_open_trades() if open_trade.stock == decision.stock),
            None,
        )
        if trade is None:
            return
        self.trading_service.paper_exit_trade(trade.id)
        self.store.insert_automation_event(
            event_type="paper.exit.agent",
            severity="info",
            message=f"Paper trade exited after Hermes recommendation for {decision.stock}.",
            details={"tradeId": trade.id, "decisionId": decision.id},
        )

    def _latest_run(self, run_id: str) -> AutomationRun:
        for run in self.store.list_automation_runs():
            if run.id == run_id:
                return run
        raise HTTPException(status_code=500, detail="Automation run was not recorded.")

    @staticmethod
    def _due(value: str | None, interval_seconds: int) -> bool:
        if value is None:
            return True
        try:
            previous = datetime.fromisoformat(value)
        except ValueError:
            return True
        return (now_utc() - previous).total_seconds() >= interval_seconds
