from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from .breeze import BreezeClient, BreezeClientError
from .config import AppConfig
from .schemas import (
    BacktestMetrics,
    ChampionRollout,
    ConstrainedStrategyRule,
    DailyImprovementReview,
    ImprovementLesson,
    ImprovementReviewDraft,
    ImprovementRun,
    ImprovementStatus,
    ScannerResult,
    ScannerCandidate,
    StrategyValidation,
    StrategyVersion,
)
from .scanner import calculate_indicators
from .store import SQLiteStore
from .time_utils import (
    IST,
    current_trading_day,
    is_market_open,
    is_intraday_square_off_time,
    now_ist,
    now_utc,
    utc_iso,
)

BACKTEST_MIN_TRADES = 100
BACKTEST_MIN_PROFIT_FACTOR = 1.2
BACKTEST_MAX_DRAWDOWN = 10
BACKTEST_MIN_WIN_RATE = 45
SHADOW_MIN_DAYS = 5
SHADOW_MIN_TRADES = 10
SHADOW_MIN_PROFIT_FACTOR = 1.1
ROLLOUT_STAGES = (10, 25, 50, 100)
REVIEW_MIN_COMPLETED_TRADES = 3
ALLOWED_RANGES: dict[str, tuple[float, float]] = {
    "rsi": (0, 100),
    "priceToVwap": (-0.2, 0.2),
    "trend": (-0.2, 0.2),
    "volumeSpike": (0, 10),
    "volatility": (0, 0.5),
    "liquidity": (0, 1_000_000_000),
    "supportDistance": (-0.2, 1),
    "resistanceDistance": (-0.2, 1),
}

IMPROVEMENT_SYSTEM_PROMPT = (
    "You are the after-market research component of BreezePilot. Analyze only the supplied "
    "paper-trading evidence. Return exactly one JSON object with summary, successes, mistakes, "
    "lessons, entryTimingNotes, exitTimingNotes, and optional challenger. Never claim guaranteed "
    "profit. Every lesson must be supported by repeated or explicit evidence in the input. "
    "The challenger, when justified, must be a long-only NSE cash-equity intraday rule expressed "
    "only as JSON. It may use rsi, priceToVwap, trend, volumeSpike, volatility, liquidity, "
    "supportDistance, and resistanceDistance. Allowed operators are gt, gte, lt, lte, and between. "
    "Use 2 to 6 unique conditions. Do not output source code, formulas, news rules, asset classes, "
    "short selling, market orders, position sizing, or risk overrides. entryEndIst cannot exceed "
    "15:10. stopLossPercent must be positive and no larger than the configured stop loss. "
    "targetPercent must exceed stopLossPercent and cannot exceed the configured target. "
    "If evidence is insufficient for a challenger, return challenger as null."
)


class ImprovementProviderError(RuntimeError):
    pass


class SelfImprovementService:
    def __init__(
        self,
        *,
        config: AppConfig,
        store: SQLiteStore,
        breeze_client: BreezeClient,
    ):
        self.config = config
        self.store = store
        self.breeze_client = breeze_client
        self._reconcile_state_from_latest_review()

    def _reconcile_state_from_latest_review(self) -> None:
        reviews = self.store.list_improvement_reviews(limit=1)
        if not reviews:
            return
        latest = reviews[0]
        state = self.store.get_improvement_state()
        if state["last_review_day"] != latest.trading_day:
            return
        expected_health = "failed" if latest.status == "failed" else "healthy"
        expected_error = latest.error if latest.status == "failed" else None
        if (
            state["health"] == expected_health
            and state["latest_error"] == expected_error
        ):
            return
        self.store.update_improvement_state(
            health=expected_health,
            last_review_day=latest.trading_day,
            latest_error=expected_error,
        )

    def status(self) -> ImprovementStatus:
        state = self.store.get_improvement_state()
        health = state["health"] if self.config.self_improvement_enabled else "disabled"
        message = "Daily self-improvement is disabled."
        if self.config.self_improvement_enabled:
            message = "Daily after-market review is scheduled."
        if state["latest_error"]:
            message = f"Latest improvement error: {state['latest_error']}"
        return ImprovementStatus(
            enabled=self.config.self_improvement_enabled,
            health=health,
            scheduledTimeIst=self.config.self_improvement_time_ist,
            autoPromotionEnabled=self.config.auto_challenger_promotion,
            lastReviewDay=state["last_review_day"],
            lastRunAt=state["last_run_at"],
            latestError=state["latest_error"],
            activeLessons=len(self.store.list_improvement_lessons(active_only=True)),
            challengers=len(self.store.list_challengers()),
            rollout=self.store.get_champion_rollout(),
            message=message,
        )

    def reviews(self) -> list[DailyImprovementReview]:
        return self.store.list_improvement_reviews()

    def lessons(self) -> list[ImprovementLesson]:
        return self.store.list_improvement_lessons()

    def rollout(self) -> ChampionRollout:
        return self.store.get_champion_rollout()

    def run_daily_review(
        self,
        *,
        trading_day: str | None = None,
        force: bool = False,
    ) -> ImprovementRun:
        day = trading_day or current_trading_day()
        if is_market_open():
            return self._record_run(
                "blocked",
                None,
                "Improvement jobs can run only after market hours.",
            )
        existing = self.store.get_improvement_review(day)
        if existing and not force:
            return self._record_run(
                "already_completed",
                existing.created_version_id,
                f"Improvement review already exists for {day}.",
            )
        if not self.config.self_improvement_enabled and not force:
            return self._record_run("disabled", None, "Self-improvement is disabled.")
        if not self.config.hermes_enabled or not self.config.hermes_api_key:
            return self._failed_review(day, "Kimi is not configured for improvement reviews.")

        evidence = self.store.improvement_evidence(day)
        completed = [
            trade for trade in evidence["trades"]
            if trade.get("closed_at") and trade.get("pnl") is not None
        ]
        counts = {
            "completedTrades": len(completed),
            "decisions": len(evidence["decisions"]),
            "riskEvents": len(evidence["riskEvents"]),
            "automationErrors": sum(
                1 for event in evidence["automationEvents"] if event["severity"] == "error"
            ),
        }
        if len(completed) < REVIEW_MIN_COMPLETED_TRADES:
            review = DailyImprovementReview(
                id=str(uuid.uuid4()),
                tradingDay=day,
                status="insufficient_data",
                summary="Not enough completed paper trades for a reliable daily review.",
                evidenceCounts=counts,
                createdAt=utc_iso(),
            )
            self.store.save_improvement_review(review)
            self.store.update_improvement_state(
                health="healthy",
                last_review_day=day,
                latest_error=None,
            )
            return self._record_run(
                "insufficient_data",
                None,
                review.summary,
            )

        self.store.update_improvement_state(health="running", latest_error=None)
        try:
            draft = self._request_review(evidence)
            challenger = self._validate_challenger(draft.challenger)
            version = self._create_and_backtest_challenger(challenger, day) if challenger else None
            review = DailyImprovementReview(
                id=str(uuid.uuid4()),
                tradingDay=day,
                status="completed",
                summary=draft.summary,
                successes=draft.successes,
                mistakes=draft.mistakes,
                entryTimingNotes=draft.entry_timing_notes,
                exitTimingNotes=draft.exit_timing_notes,
                evidenceCounts=counts,
                createdVersionId=version.id if version else None,
                createdAt=utc_iso(),
            )
            self.store.save_improvement_review(review)
            self.store.replace_review_lessons(review.id, draft.lessons)
            self.store.update_improvement_state(
                health="healthy",
                last_review_day=day,
                latest_error=None,
            )
            self.store.insert_audit_event(
                event_type="improvement.review.completed",
                message=f"Completed daily improvement review for {day}.",
                details={
                    "reviewId": review.id,
                    "createdVersionId": review.created_version_id,
                    "evidenceCounts": counts,
                },
            )
            if version:
                self.evaluate_and_promote(version.id)
            return self._record_run(
                "created_challenger" if version else "review_completed",
                version.id if version else None,
                "Daily evidence review completed."
                + (" A constrained challenger was created." if version else ""),
            )
        except (ImprovementProviderError, ValidationError, ValueError, BreezeClientError) as exc:
            return self._failed_review(day, str(exc), counts)

    def run_scheduled_if_due(self) -> ImprovementRun | None:
        if not self.config.self_improvement_enabled:
            return None
        target_day = self._scheduled_target_day()
        existing = self.store.get_improvement_review(target_day) if target_day else None
        if target_day is None or existing:
            self.evaluate_rollout()
            return None
        return self.run_daily_review(trading_day=target_day)

    def retry_failed_review(self) -> ImprovementRun:
        day = current_trading_day()
        existing = self.store.get_improvement_review(day)
        if existing is None:
            return self.run_daily_review(trading_day=day)
        if existing.status != "failed":
            return self._record_run(
                "already_completed",
                existing.created_version_id,
                f"Improvement review already exists for {day}.",
            )
        return self.run_daily_review(trading_day=day, force=True)

    def process_shadow_cycle(self, scanner_result: ScannerResult) -> None:
        self.monitor_shadow_trades()
        settings = self.store.get_settings()
        for version in self.store.list_challengers():
            if version.promotion_status not in {"backtested", "paper_validated", "candidate"}:
                continue
            rule = self.store.get_strategy_rule(version.id)
            if rule is None or self.store.list_shadow_open_trades(version.id):
                continue
            candidate = next(
                (
                    item for item in scanner_result.candidates
                    if item.last_price > 0
                    and item.indicators
                    and _rule_matches(rule, item.indicators)
                ),
                None,
            )
            if candidate is None:
                continue
            quantity = max(int(settings.budget // candidate.last_price), 1)
            stop = candidate.last_price * (1 - rule.stop_loss_percent / 100)
            target = candidate.last_price * (1 + rule.target_percent / 100)
            self.store.insert_shadow_trade(
                version_id=version.id,
                stock=candidate.stock_code,
                entry_price=candidate.last_price,
                stop_loss=round(stop, 2),
                target=round(target, 2),
                quantity=quantity,
            )

    def apply_champion_rule(self, scanner_result: ScannerResult) -> ScannerResult:
        champion = self.store.current_champion()
        if champion is None:
            return scanner_result
        rule = self.store.get_strategy_rule(champion.id)
        if rule is None:
            return scanner_result
        matches: list[ScannerCandidate] = []
        match_by_stock: dict[str, ScannerCandidate] = {}
        for candidate in scanner_result.candidates:
            if candidate.last_price <= 0 or not candidate.indicators:
                continue
            if not _rule_matches(rule, candidate.indicators):
                continue
            matched = candidate.model_copy(
                    update={
                        "strategy": champion.strategy,
                        "strategy_version": champion.version,
                        "rejected": False,
                        "rejection_reason": None,
                        "positive_reasons": [
                            *candidate.positive_reasons,
                            f"Champion rule matched: {champion.strategy}.",
                        ],
                    }
                )
            matches.append(matched)
            match_by_stock[candidate.stock_code] = matched
        existing = {
            (candidate.stock_code, candidate.strategy)
            for candidate in scanner_result.shortlist
        }
        combined = list(scanner_result.shortlist)
        combined.extend(
            candidate
            for candidate in matches
            if (candidate.stock_code, candidate.strategy) not in existing
        )
        combined.sort(key=lambda candidate: (-candidate.score, candidate.stock_code))
        candidates = [
            match_by_stock.get(candidate.stock_code, candidate)
            for candidate in scanner_result.candidates
        ]
        return scanner_result.model_copy(
            update={"candidates": candidates, "shortlist": combined}
        )

    def monitor_shadow_trades(self) -> None:
        runtime = self.store.get_runtime()
        if runtime.session_status != "active" or not runtime.session_token:
            return
        for trade in self.store.list_shadow_open_trades():
            try:
                quote = self.breeze_client.get_quote(runtime.session_token, trade["stock"])
                price = float(
                    getattr(quote, "last_price", None)
                    or (quote.get("lastPrice") if isinstance(quote, dict) else 0)
                )
            except (BreezeClientError, TypeError, ValueError):
                continue
            if price <= 0:
                continue
            if is_intraday_square_off_time():
                self.store.close_shadow_trade(
                    trade["id"],
                    exit_price=price,
                    status="exited",
                    exit_reason="Intraday shadow square-off",
                )
            elif price <= float(trade["stop_loss"]):
                self.store.close_shadow_trade(
                    trade["id"],
                    exit_price=price,
                    status="stop_loss_hit",
                    exit_reason="Shadow stop-loss hit",
                )
            elif price >= float(trade["target"]):
                self.store.close_shadow_trade(
                    trade["id"],
                    exit_price=price,
                    status="target_hit",
                    exit_reason="Shadow target hit",
                )
        for version in self.store.list_challengers():
            self.evaluate_and_promote(version.id)

    def validation(self, version_id: str) -> StrategyValidation:
        version = self.store.get_strategy_version(version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="Strategy version was not found.")
        metrics = version.backtest_metrics
        backtest_passed = _metrics_pass(metrics)
        shadow = self.store.shadow_metrics(version_id)
        errors_clear = (
            self.store.automation_error_count() == 0
            and int(self.store.agent_health()["consecutive_system_errors"]) == 0
        )
        champion = self.store.current_champion()
        comparison = _beats_champion(version, champion)
        failures: list[str] = []
        if not backtest_passed:
            failures.append("Backtest gate has not passed.")
        if shadow["days"] < SHADOW_MIN_DAYS:
            failures.append("Needs at least 5 shadow paper days.")
        if shadow["trades"] < SHADOW_MIN_TRADES:
            failures.append("Needs at least 10 closed shadow trades.")
        if shadow["profitFactor"] < SHADOW_MIN_PROFIT_FACTOR:
            failures.append("Shadow profit factor is below 1.1.")
        if shadow["dailyLossBreached"]:
            failures.append("Shadow daily-loss breach detected.")
        if not errors_clear:
            failures.append("Unresolved automation or agent errors are present.")
        if not comparison:
            failures.append("Challenger does not outperform the champion.")
        return StrategyValidation(
            versionId=version_id,
            backtestPassed=backtest_passed,
            backtestReason=(
                "Backtest passed."
                if backtest_passed
                else "Backtest requires 100 trades, PF >= 1.2, drawdown <= 10%, and win rate >= 45%."
            ),
            shadowDays=shadow["days"],
            shadowTrades=shadow["trades"],
            shadowProfitFactor=shadow["profitFactor"],
            shadowDailyLossBreached=shadow["dailyLossBreached"],
            errorsClear=errors_clear,
            championComparisonPassed=comparison,
            eligibleForPromotion=not failures,
            reason="Promotion gates passed." if not failures else " ".join(failures),
        )

    def evaluate_and_promote(self, version_id: str) -> StrategyValidation:
        validation = self.validation(version_id)
        version = self.store.get_strategy_version(version_id)
        if version is None:
            return validation
        shadow = self.store.shadow_metrics(version_id)
        status = version.promotion_status
        if validation.backtest_passed and shadow["trades"] > 0:
            status = "paper_validated" if validation.eligible_for_promotion else "backtested"
        updated = version.model_copy(
            update={"paper_metrics": shadow, "promotion_status": status}
        )
        self.store.save_strategy_version(updated)
        if (
            validation.eligible_for_promotion
            and self.config.auto_challenger_promotion
            and version.promotion_status != "champion"
        ):
            promoted = self.store.promote_strategy_version(version_id)
            if promoted:
                self.store.set_champion_rollout(
                    champion_version_id=version_id,
                    stage_percent=self.config.challenger_canary_percent,
                )
        return validation

    def evaluate_rollout(self) -> ChampionRollout:
        rollout = self.store.get_champion_rollout()
        if not rollout.champion_version_id:
            return rollout
        version = self.store.get_strategy_version(rollout.champion_version_id)
        if version is None:
            return rollout
        metrics = self.store.live_strategy_metrics(version.id)
        validated_drawdown = float(version.backtest_metrics.get("maxDrawdown", 10))
        safety = self.store.get_safety_state()
        runtime = self.store.get_runtime()
        failure_reason: str | None = None
        if metrics["trades"] >= 10 and metrics["profitFactor"] < 0.9:
            failure_reason = "Rolling live profit factor fell below 0.9."
        elif metrics["maxDrawdown"] > validated_drawdown:
            failure_reason = "Live drawdown exceeded validated drawdown."
        elif safety["kill_switch_active"] or runtime.emergency_lock:
            failure_reason = "A live safety lock became active."
        elif self.store.automation_error_count() > 0:
            failure_reason = "Unresolved automation errors are present."
        elif int(self.store.agent_health()["consecutive_system_errors"]) > 0:
            failure_reason = "Unresolved agent-integrity errors are present."

        if failure_reason:
            previous = self.store.rollback_champion()
            if previous:
                self.store.set_champion_rollout(
                    champion_version_id=previous.id,
                    stage_percent=self.config.challenger_canary_percent,
                    rollback_reason=failure_reason,
                )
            else:
                self.store.set_live_autopilot(False)
                self.store.set_champion_rollout(
                    champion_version_id=version.id,
                    stage_percent=0,
                    rollback_reason=failure_reason,
                )
            return self.store.get_champion_rollout()

        if (
            rollout.live_days >= 5
            and rollout.live_trades >= 10
            and rollout.live_profit_factor >= 1.1
        ):
            current = rollout.stage_percent
            next_stage = next((stage for stage in ROLLOUT_STAGES if stage > current), current)
            if next_stage != current:
                self.store.set_champion_rollout(
                    champion_version_id=version.id,
                    stage_percent=next_stage,
                )
        return self.store.get_champion_rollout()

    def _request_review(self, evidence: dict[str, Any]) -> ImprovementReviewDraft:
        settings = self.store.get_settings()
        sanitized = {
            "evidence": evidence,
            "riskLimits": {
                "stopLossPercent": settings.stop_loss_percent,
                "targetPercent": settings.target_percent,
                "dailyMaxLoss": settings.daily_max_loss,
                "maxTradesPerDay": settings.max_trades_per_day,
            },
        }
        body = json.dumps(
            {
                "model": self.config.hermes_model,
                "messages": [
                    {"role": "system", "content": IMPROVEMENT_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(sanitized, separators=(",", ":"), default=str),
                    },
                ],
                "thinking": {"type": "disabled"},
                "response_format": {"type": "json_object"},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.hermes_base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.hermes_api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.config.hermes_timeout_seconds,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ImprovementProviderError(f"Kimi improvement request failed: {exc}") from exc
        try:
            content = payload["choices"][0]["message"]["content"]
            raw = _decode_review_content(content)
            return ImprovementReviewDraft.model_validate(raw)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise ImprovementProviderError("Kimi returned an invalid improvement review.") from exc

    def _validate_challenger(
        self,
        rule: ConstrainedStrategyRule | None,
    ) -> ConstrainedStrategyRule | None:
        if rule is None:
            return None
        settings = self.store.get_settings()
        if rule.stop_loss_percent > settings.stop_loss_percent:
            raise ValueError("Challenger attempted to loosen the configured stop-loss.")
        if rule.target_percent > settings.target_percent:
            raise ValueError("Challenger target exceeds the configured target.")
        for condition in rule.conditions:
            lower, upper = ALLOWED_RANGES[condition.field]
            values = (
                [condition.minimum, condition.maximum]
                if condition.operator == "between"
                else [condition.value]
            )
            if any(value is None or value < lower or value > upper for value in values):
                raise ValueError(f"Challenger condition for {condition.field} is outside bounds.")
        return rule

    def _create_and_backtest_challenger(
        self,
        rule: ConstrainedStrategyRule,
        day: str,
    ) -> StrategyVersion:
        runtime = self.store.get_runtime()
        if runtime.session_status != "active" or not runtime.session_token:
            raise ValueError("A valid Breeze session is required to backtest a challenger.")
        stock = "HDFCBANK"
        settings = self.store.get_settings()
        candles = self.breeze_client.get_historical_candles(
            runtime.session_token,
            stock_code=stock,
            from_date=(now_utc() - timedelta(days=365 * 5)).isoformat(),
            to_date=now_utc().isoformat(),
            interval="day",
        )
        pnls = _constrained_backtest_pnls(
            candles,
            rule=rule,
            budget=settings.budget,
        )
        metrics = _build_metrics(pnls, settings.budget)
        version_id = str(uuid.uuid4())
        version = StrategyVersion(
            id=version_id,
            strategy=f"Adaptive: {rule.name}",
            version=f"challenger-{day}-{version_id[:6]}",
            sourceVersionId=(
                self.store.current_champion().id
                if self.store.current_champion()
                else None
            ),
            parameters=rule.model_dump(by_alias=True),
            backtestMetrics=metrics.model_dump(by_alias=True),
            paperMetrics={},
            riskNotes=[
                "Generated from daily evidence as constrained JSON.",
                "Cannot bypass deterministic risk controls.",
            ],
            promotionStatus="backtested" if _metrics_pass(metrics.model_dump(by_alias=True)) else "rejected",
            createdAt=utc_iso(),
        )
        self.store.save_strategy_version(version)
        self.store.save_strategy_rule(version.id, rule)
        return version

    def _failed_review(
        self,
        day: str,
        error: str,
        counts: dict[str, int] | None = None,
    ) -> ImprovementRun:
        review = DailyImprovementReview(
            id=str(uuid.uuid4()),
            tradingDay=day,
            status="failed",
            summary="Daily improvement review failed without changing the active strategy.",
            evidenceCounts=counts or {},
            error=error[:500],
            createdAt=utc_iso(),
        )
        self.store.save_improvement_review(review)
        self.store.update_improvement_state(
            health="failed",
            last_review_day=day,
            latest_error=error[:500],
        )
        return self._record_run("failed", None, error[:500])

    def _record_run(
        self,
        status: str,
        version_id: str | None,
        reason: str,
    ) -> ImprovementRun:
        run = ImprovementRun(
            id=str(uuid.uuid4()),
            status=status,
            toolsAvailable={"lightweight": True, "kimi": self.config.hermes_enabled},
            createdVersionId=version_id,
            reason=reason,
            createdAt=utc_iso(),
        )
        self.store.save_improvement_run(run)
        return run

    def _scheduled_target_day(self) -> str | None:
        now = now_ist()
        if now.weekday() >= 5:
            return None
        hour, minute = (int(part) for part in self.config.self_improvement_time_ist.split(":", 1))
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now >= scheduled:
            return now.date().isoformat()
        if now.time() < datetime.strptime("09:15", "%H:%M").time():
            previous = now.date() - timedelta(days=1)
            while previous.weekday() >= 5:
                previous -= timedelta(days=1)
            return previous.isoformat()
        return None


def _rule_matches(rule: ConstrainedStrategyRule, indicators: dict[str, float]) -> bool:
    for condition in rule.conditions:
        value = indicators.get(condition.field)
        if value is None:
            return False
        if condition.operator == "gt" and not value > float(condition.value):
            return False
        if condition.operator == "gte" and not value >= float(condition.value):
            return False
        if condition.operator == "lt" and not value < float(condition.value):
            return False
        if condition.operator == "lte" and not value <= float(condition.value):
            return False
        if condition.operator == "between" and not (
            float(condition.minimum) <= value <= float(condition.maximum)
        ):
            return False
    return True


def _decode_review_content(content: Any) -> dict[str, Any]:
    if isinstance(content, list):
        content = "".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in content
        )
    if isinstance(content, dict):
        raw: Any = content
    elif isinstance(content, str):
        stripped = content.strip()
        fence = re.fullmatch(
            r"```(?:json)?\s*(.*?)\s*```",
            stripped,
            flags=re.DOTALL,
        )
        if fence:
            stripped = fence.group(1).strip()
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError:
            raw = None
            decoder = json.JSONDecoder()
            for index, character in enumerate(stripped):
                if character != "{":
                    continue
                try:
                    candidate, _ = decoder.raw_decode(stripped[index:])
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, dict):
                    raw = candidate
                    break
            if raw is None:
                raise
        if isinstance(raw, str):
            raw = json.loads(raw)
    else:
        raise TypeError("Improvement response content must be JSON text.")
    if not isinstance(raw, dict):
        raise TypeError("Improvement response must be a JSON object.")
    if isinstance(raw.get("review"), dict):
        raw = raw["review"]

    aliases = {
        "entry_timing_notes": "entryTimingNotes",
        "exit_timing_notes": "exitTimingNotes",
        "newStrategy": "challenger",
        "strategy": "challenger",
    }
    normalized = dict(raw)
    for source, target in aliases.items():
        if target not in normalized and source in normalized:
            normalized[target] = normalized.pop(source)
    for field in (
        "successes",
        "mistakes",
        "lessons",
        "entryTimingNotes",
        "exitTimingNotes",
    ):
        value = normalized.get(field)
        if value is None:
            normalized[field] = []
        elif isinstance(value, str):
            normalized[field] = [value]
    challenger = normalized.get("challenger")
    if isinstance(challenger, dict):
        challenger = dict(challenger)
        challenger_aliases = {
            "minimum_score": "minimumScore",
            "stop_loss_percent": "stopLossPercent",
            "target_percent": "targetPercent",
            "entry_start_ist": "entryStartIst",
            "entry_end_ist": "entryEndIst",
        }
        for source, target in challenger_aliases.items():
            if target not in challenger and source in challenger:
                challenger[target] = challenger.pop(source)
        conditions = challenger.get("conditions")
        if isinstance(conditions, list):
            normalized_conditions = []
            for condition in conditions:
                if not isinstance(condition, dict):
                    normalized_conditions.append(condition)
                    continue
                item = dict(condition)
                if "minimum" not in item and "min" in item:
                    item["minimum"] = item.pop("min")
                if "maximum" not in item and "max" in item:
                    item["maximum"] = item.pop("max")
                if isinstance(item.get("operator"), str):
                    item["operator"] = item["operator"].lower()
                normalized_conditions.append(item)
            challenger["conditions"] = normalized_conditions
        normalized["challenger"] = challenger
    return normalized


def _constrained_backtest_pnls(
    candles: list[Any],
    *,
    rule: ConstrainedStrategyRule,
    budget: float,
) -> list[float]:
    pnls: list[float] = []
    for index in range(30, len(candles) - 1):
        current = candles[index]
        entry = _number(_field(current, "close"))
        volume = _number(_field(current, "volume"))
        if entry <= 0:
            continue
        indicators = calculate_indicators(
            {"lastPrice": entry, "volume": volume},
            candles[index - 30 : index],
        )
        if not _rule_matches(rule, indicators):
            continue
        quantity = int(budget // entry)
        if quantity <= 0:
            continue
        stop = entry * (1 - rule.stop_loss_percent / 100)
        target = entry * (1 + rule.target_percent / 100)
        next_candle = candles[index + 1]
        low = _number(_field(next_candle, "low"))
        high = _number(_field(next_candle, "high"))
        close = _number(_field(next_candle, "close"))
        if low > 0 and low <= stop:
            exit_price = stop
        elif high >= target:
            exit_price = target
        elif close > 0:
            exit_price = close
        else:
            continue
        pnl = (exit_price - entry) * quantity - (entry * quantity * 0.001)
        pnls.append(round(pnl, 2))
    return pnls


def _build_metrics(pnls: list[float], starting_capital: float) -> BacktestMetrics:
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    equity = peak = max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return BacktestMetrics(
        winRate=round((len(wins) / len(pnls) * 100) if pnls else 0, 2),
        profitFactor=round(gross_profit / gross_loss, 2) if gross_loss else round(gross_profit, 2),
        maxDrawdown=round(max_drawdown / max(starting_capital, 1) * 100, 2),
        averageProfit=round(sum(wins) / len(wins), 2) if wins else 0,
        averageLoss=round(sum(losses) / len(losses), 2) if losses else 0,
        tradesCount=len(pnls),
        bestMarketCondition="uptrend" if gross_profit >= gross_loss else "range",
        worstMarketCondition="drawdown" if losses else "none",
    )


def _metrics_pass(metrics: dict[str, Any]) -> bool:
    return (
        int(metrics.get("tradesCount", 0)) >= BACKTEST_MIN_TRADES
        and float(metrics.get("profitFactor", 0)) >= BACKTEST_MIN_PROFIT_FACTOR
        and float(metrics.get("maxDrawdown", 100)) <= BACKTEST_MAX_DRAWDOWN
        and float(metrics.get("winRate", 0)) >= BACKTEST_MIN_WIN_RATE
    )


def _beats_champion(
    challenger: StrategyVersion,
    champion: StrategyVersion | None,
) -> bool:
    if champion is None:
        return True
    challenger_pf = float(challenger.backtest_metrics.get("profitFactor", 0))
    challenger_drawdown = float(challenger.backtest_metrics.get("maxDrawdown", 100))
    champion_pf = float(champion.backtest_metrics.get("profitFactor", 0))
    champion_drawdown = float(champion.backtest_metrics.get("maxDrawdown", 100))
    return challenger_pf >= champion_pf + 0.1 or (
        challenger_pf >= champion_pf and challenger_drawdown < champion_drawdown
    )


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
