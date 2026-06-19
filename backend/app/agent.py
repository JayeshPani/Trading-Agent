from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from .advanced import AdvancedTradingService
from .breeze import BreezeClient
from .config import AppConfig
from .risk import ProposedTrade, RiskEngine, RiskResult
from .scanner import APPROVED_STRATEGIES, MarketScanner
from .schemas import (
    AgentDecision,
    AgentDecisionDraft,
    AgentDecisionResponse,
    AgentStatus,
    Explanation,
    LiveOrderPrepareRequest,
    ScannerCandidate,
    normalize_symbol,
)
from .store import SQLiteStore
from .time_utils import (
    IST,
    build_intraday_market_clock,
    is_intraday_entry_cutoff_time,
    now_utc,
    utc_iso,
)


APPROVED_STRATEGY_NAMES = {strategy.name for strategy in APPROVED_STRATEGIES}
MAX_SCANNER_PRICE_DEVIATION = 0.005
HERMES_INTRADAY_SYSTEM_PROMPT = (
    "You are BreezePilot Hermes, a balanced and risk-aware decision agent for same-day "
    "NSE cash-equity intraday trading. Return exactly one JSON object and no other text. "
    "Allowed actions are SKIP, PROPOSE_ENTRY, PROPOSE_EXIT, and HOLD. Do not emit "
    "TIGHTEN_STOP because stop modification is not implemented. All approved strategies "
    "are long-only: every PROPOSE_ENTRY must use side BUY. Never propose a short entry. "
    "For an entry, copy the exact stock and exact assigned strategy from one current "
    "scanner.shortlist candidate. Never use a rejected candidate, an already-open stock, "
    "or a stock absent from the shortlist. Use the candidate's current lastPrice as the "
    "entry reference and do not invent prices, indicators, news, fundamentals, strategies, "
    "assets, or order types. Evaluate the supplied RSI, EMA trend, VWAP relationship, "
    "volume spike, volatility, liquidity, support, and resistance evidence. Explain the "
    "strongest supporting evidence in reasons and material uncertainty in risks. Review "
    "open exposure, remaining capital, daily-loss capacity, and remaining trade slots. "
    "The budget is a maximum cap, not a target to deploy. Prefer risk-adjusted opportunity "
    "over trade frequency and choose SKIP when evidence is mixed, weak, stale, or when no "
    "clean approved setup exists. Scanner timestamps use UTC; use scanner.ageSeconds as the "
    "source of truth for freshness and never infer staleness from timezone differences. Never "
    "propose a new entry when marketClock.newEntriesAllowed "
    "is false or at/after 15:10 IST. All positions are intended to exit by 15:20 IST. "
    "For existing positions, use HOLD or PROPOSE_EXIT only. Confidence must be a decimal "
    "from 0.0 to 1.0, never a percentage. A PROPOSE_ENTRY must include stock, strategy, "
    "side, quantity, entryPrice, stopLoss, target, confidence, reasons, risks, and expiresAt. "
    "The reasons and risks fields must always be JSON arrays of short strings, including "
    "for SKIP and HOLD decisions; never return either field as a single string."
)


class HermesClientError(Exception):
    pass


@dataclass(frozen=True)
class HermesDecisionResult:
    draft: AgentDecisionDraft
    integrity_status: str
    integrity_message: str

    def __getattr__(self, name: str) -> Any:
        return getattr(self.draft, name)


class HermesClient:
    def __init__(self, config: AppConfig):
        self.config = config

    def decide(self, context: dict[str, Any]) -> HermesDecisionResult:
        if not self.config.hermes_enabled:
            raise HermesClientError("Hermes is disabled. Set HERMES_ENABLED=true to enable agent decisions.")

        content = self._request_content(
            [
                {"role": "system", "content": HERMES_INTRADAY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(context, separators=(",", ":")),
                },
            ]
        )
        try:
            return HermesDecisionResult(
                draft=parse_hermes_decision(content),
                integrity_status="genuine",
                integrity_message="Kimi returned a valid decision directly.",
            )
        except HermesClientError as exc:
            if not str(exc).startswith("Hermes returned invalid structured JSON."):
                raise

        repaired = self._request_content(
            [
                {
                    "role": "system",
                    "content": (
                        "Repair the supplied trading decision into exactly one valid JSON object. "
                        "Do not reconsider the market decision or add commentary. Required fields: "
                        "action, confidence, reasons, risks. reasons and risks must be JSON arrays "
                        "of strings. Allowed actions: SKIP, PROPOSE_ENTRY, PROPOSE_EXIT, HOLD. For "
                        "PROPOSE_ENTRY also preserve stock, strategy, side, quantity, entryPrice, "
                        "stopLoss, target, and expiresAt. Use null only for optional non-entry fields."
                    ),
                },
                {"role": "user", "content": content},
            ]
        )
        return HermesDecisionResult(
            draft=parse_hermes_decision(repaired),
            integrity_status="repaired",
            integrity_message="Kimi decision was normalized by one schema-repair request.",
        )

    def _request_content(self, messages: list[dict[str, str]]) -> str:
        body = json.dumps(
            {
                "model": self.config.hermes_model,
                "messages": messages,
                # This is a bounded classification task. Disabling Kimi's long
                # reasoning mode keeps scheduled decisions within the timeout.
                "thinking": {"type": "disabled"},
                "response_format": {"type": "json_object"},
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.config.hermes_api_key:
            headers["Authorization"] = f"Bearer {self.config.hermes_api_key}"
        request = urllib.request.Request(
            f"{self.config.hermes_base_url}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.hermes_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = _http_error_detail(exc)
            raise HermesClientError(
                f"Hermes request failed with HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise HermesClientError(f"Hermes request failed: {exc}") from exc

        return _extract_openai_content(payload)


def parse_hermes_decision(content: str) -> AgentDecisionDraft:
    try:
        raw = _decode_json_object(content)
        if isinstance(raw, dict):
            if isinstance(raw.get("decision"), dict):
                raw = raw["decision"]
            if isinstance(raw.get("action"), str):
                raw["action"] = raw["action"].strip().upper()
            for field in ("reasons", "risks"):
                value = raw.get(field)
                if value is None:
                    raw[field] = []
                elif isinstance(value, str):
                    raw[field] = [value]
                elif isinstance(value, list):
                    raw[field] = [
                        item if isinstance(item, str) else json.dumps(item, separators=(",", ":"))
                        for item in value
                    ]
            raw.setdefault("confidence", 0)
            confidence = raw.get("confidence")
            if (
                isinstance(confidence, (int, float))
                and not isinstance(confidence, bool)
                and 1 < confidence <= 100
            ):
                raw["confidence"] = confidence / 100
        draft = AgentDecisionDraft.model_validate(raw)
    except json.JSONDecodeError as exc:
        raise HermesClientError("Hermes returned invalid structured JSON.") from exc
    except ValidationError as exc:
        fields = sorted(
            {
                str(error["loc"][0])
                for error in exc.errors()
                if error.get("loc")
            }
        )
        detail = f" Invalid fields: {', '.join(fields)}." if fields else ""
        raise HermesClientError(f"Hermes returned invalid structured JSON.{detail}") from exc

    if draft.strategy and draft.strategy not in APPROVED_STRATEGY_NAMES:
        raise HermesClientError("Hermes selected an unsupported strategy.")
    if draft.stock:
        stock = normalize_symbol(draft.stock)
        if not stock:
            raise HermesClientError("Hermes selected an invalid stock symbol.")
        draft = draft.model_copy(update={"stock": stock})
    if draft.action == "PROPOSE_ENTRY":
        missing = [
            name
            for name, value in {
                "stock": draft.stock,
                "strategy": draft.strategy,
                "side": draft.side,
                "quantity": draft.quantity,
                "entryPrice": draft.entry_price,
                "stopLoss": draft.stop_loss,
                "target": draft.target,
            }.items()
            if value in {None, ""}
        ]
        if missing:
            raise HermesClientError(f"Hermes entry proposal is missing: {', '.join(missing)}.")
        if (draft.quantity or 0) <= 0:
            raise HermesClientError("Hermes entry quantity must be positive.")
    return draft


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "The provider rejected the request."
    finally:
        exc.close()

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"][:300]
        if isinstance(payload.get("message"), str):
            return payload["message"][:300]
    return "The provider rejected the request."


class AgentService:
    def __init__(
        self,
        *,
        config: AppConfig,
        store: SQLiteStore,
        risk_engine: RiskEngine,
        breeze_client: BreezeClient,
        advanced_service: AdvancedTradingService,
        hermes_client: HermesClient | None = None,
        scanner: MarketScanner | None = None,
    ):
        self.config = config
        self.store = store
        self.risk_engine = risk_engine
        self.breeze_client = breeze_client
        self.advanced_service = advanced_service
        self.hermes_client = hermes_client or HermesClient(config)
        self.scanner = scanner or MarketScanner(breeze_client)

    def status(self) -> AgentStatus:
        health = self.store.agent_health()
        message = "Hermes is configured for local agent decisions."
        if not self.config.hermes_enabled:
            message = "Hermes is disabled. Existing scanner/manual workflow remains available."
        elif not health["healthy"]:
            message = "Kimi has unresolved decision errors; failed entry cycles remain blocked."
        return AgentStatus(
            enabled=self.config.hermes_enabled,
            provider=self.config.hermes_provider,
            model=self.config.hermes_model,
            baseUrl=self.config.hermes_base_url,
            apiKeyConfigured=bool(self.config.hermes_api_key),
            tradingMode=self.config.trading_mode,
            healthy=bool(health["healthy"]),
            consecutiveSystemErrors=int(health["consecutive_system_errors"]),
            latestIntegrityStatus=health["latest_integrity_status"],
            lastValidDecisionAt=health["last_valid_decision_at"],
            message=message,
        )

    def analyze(self) -> AgentDecisionResponse:
        return self._decide_and_record(source="analyze", execute_paper=False, prepare_live=False)

    def paper_cycle(self) -> AgentDecisionResponse:
        if self.config.trading_mode != "paper":
            raise HTTPException(status_code=400, detail="Hermes paper cycle is available only in paper mode.")
        return self._decide_and_record(source="paper_cycle", execute_paper=True, prepare_live=False)

    def live_proposal(self) -> AgentDecisionResponse:
        return self._decide_and_record(source="live_proposal", execute_paper=False, prepare_live=True)

    def monitor(self) -> AgentDecisionResponse:
        return self._decide_and_record(source="monitor", execute_paper=False, prepare_live=False)

    def decisions(self) -> list[AgentDecision]:
        return self.store.list_agent_decisions()

    def _decide_and_record(
        self, *, source: str, execute_paper: bool, prepare_live: bool
    ) -> AgentDecisionResponse:
        settings = self.store.get_settings()
        runtime = self.store.get_runtime()
        scanner_result = self.scanner.scan(
            settings=settings,
            runtime=runtime,
            max_symbols=self.config.scanner_max_symbols_per_cycle,
        )
        self.store.save_scanner_result(scanner_result)
        if scanner_result.broker_status == "unavailable":
            raise HTTPException(
                status_code=503,
                detail=scanner_result.broker_error
                or "Breeze market data is temporarily unavailable.",
            )
        context = self._build_context(source, scanner_result)
        run_id = self.store.create_agent_run(source=source, mode=self.config.trading_mode, context=context)
        self.store.save_portfolio_snapshot(context["portfolio"])

        previous_health = self.store.agent_health()
        integrity_status = "genuine"
        integrity_message = "Kimi returned a valid decision directly."
        try:
            result = self.hermes_client.decide(context)
            if isinstance(result, HermesDecisionResult):
                draft = result.draft
                integrity_status = result.integrity_status
                integrity_message = result.integrity_message
            else:
                draft = result
        except HermesClientError as exc:
            draft = AgentDecisionDraft(
                action="SKIP",
                confidence=0,
                reasons=["No Kimi trading decision was accepted for this cycle."],
                risks=[_safe_agent_error(exc)],
            )
            integrity_status = "system_error"
            integrity_message = _safe_agent_error(exc)

        decision, risk, candidate = self._review_draft(
            run_id,
            source,
            draft,
            scanner_result,
            integrity_status=integrity_status,
            integrity_message=integrity_message,
        )
        explanation = self._explanation_for(decision)

        live_order = None
        if decision.action == "PROPOSE_ENTRY" and risk.approved:
            if execute_paper:
                trade_id = self.store.insert_trade(
                    stock=decision.stock or "",
                    side=decision.side or "BUY",
                    quantity=decision.quantity or 0,
                    entry_price=decision.entry_price or 0,
                    stop_loss=decision.stop_loss or 0,
                    target=decision.target or 0,
                    mode=settings.mode,
                    strategy=decision.strategy or "Hermes",
                    strategy_version=_candidate_strategy_version(candidate),
                    paper=True,
                )
                decision = decision.model_copy(update={"trade_id": trade_id})
                explanation = self._explanation_for(decision)
            elif prepare_live:
                live_order = self.advanced_service.prepare_live_order(
                    LiveOrderPrepareRequest(
                        stockCode=decision.stock,
                        strategy=decision.strategy,
                        quantity=decision.quantity,
                        price=decision.entry_price,
                        side=decision.side or "BUY",
                    )
                )
                decision = decision.model_copy(update={"order_id": live_order.id})
                explanation = self._explanation_for(decision)

        self.store.save_agent_decision(decision)
        self.store.insert_explanation(explanation)
        if decision.integrity_status == "system_error":
            self.store.insert_automation_event(
                event_type="agent.decision.error",
                severity="error",
                message=decision.integrity_message,
                details={"decisionId": decision.id, "source": source},
            )
        elif int(previous_health["consecutive_system_errors"]) > 0:
            self.store.insert_automation_event(
                event_type="agent.decision.recovered",
                severity="info",
                message="Kimi returned a usable decision after an earlier agent error.",
                details={
                    "decisionId": decision.id,
                    "integrityStatus": decision.integrity_status,
                    "source": source,
                },
            )
        self.store.insert_audit_event(
            event_type="agent.decision",
            message=f"Hermes decision: {decision.action}.",
            details={
                "decisionId": decision.id,
                "integrityStatus": decision.integrity_status,
                "integrityMessage": decision.integrity_message,
                "riskDecision": decision.risk_decision,
                "riskReason": decision.risk_reason,
                "source": source,
            },
        )
        return AgentDecisionResponse(decision=decision, explanation=explanation, liveOrder=live_order)

    def _review_draft(
        self,
        run_id: str,
        source: str,
        draft: AgentDecisionDraft,
        scanner_result,
        *,
        integrity_status: str,
        integrity_message: str,
    ) -> tuple[AgentDecision, RiskResult, ScannerCandidate | None]:
        risk = RiskResult(False, "Hermes did not propose an entry.")
        candidate = self._candidate_for(scanner_result.shortlist, draft.stock)
        if draft.action == "PROPOSE_ENTRY":
            validation_reason = self._validate_entry_draft(draft, candidate)
            if validation_reason:
                risk = RiskResult(False, validation_reason)
            else:
                proposed = self._proposed_trade_from_draft(draft, candidate)
                draft = draft.model_copy(update={"quantity": proposed.quantity})
                risk = self.risk_engine.review(
                    settings=self.store.get_settings(),
                    runtime=self.store.get_runtime(),
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
                stock=draft.stock,
                details={"source": "hermes", "strategy": draft.strategy},
            )

        decision = AgentDecision(
            id=str(uuid.uuid4()),
            runId=run_id,
            action=draft.action,
            stock=draft.stock,
            strategy=draft.strategy,
            side=draft.side,
            quantity=draft.quantity,
            entryPrice=draft.entry_price,
            stopLoss=draft.stop_loss,
            target=draft.target,
            confidence=draft.confidence,
            reasons=draft.reasons,
            risks=draft.risks,
            expiresAt=draft.expires_at,
            riskDecision=risk.decision if draft.action == "PROPOSE_ENTRY" else "none",
            riskReason=risk.reason if draft.action == "PROPOSE_ENTRY" else "No entry risk review required.",
            integrityStatus=integrity_status,
            integrityMessage=integrity_message,
            source=source,
            createdAt=utc_iso(),
        )
        return decision, risk, candidate

    def _validate_entry_draft(
        self, draft: AgentDecisionDraft, candidate: ScannerCandidate | None
    ) -> str | None:
        settings = self.store.get_settings()
        if settings.mode != "intraday":
            return "Hermes entries require intraday trading mode."
        if draft.side != "BUY":
            return "Hermes approved strategies allow long BUY entries only."
        if candidate is None:
            return "Hermes selected a stock that is absent from the current scanner shortlist."
        if draft.strategy != candidate.strategy:
            return "Hermes strategy does not match the scanner-assigned strategy."
        if self.config.enforce_market_hours and is_intraday_entry_cutoff_time():
            return "Intraday entry cutoff has passed."
        if candidate.last_price <= 0 or not self._price_is_aligned(
            draft.entry_price or 0, candidate.last_price
        ):
            return "Hermes entry price is not aligned with the current scanner quote."
        return None

    @staticmethod
    def _price_is_aligned(entry_price: float, scanner_price: float) -> bool:
        if entry_price <= 0 or scanner_price <= 0:
            return False
        return abs(entry_price - scanner_price) / scanner_price <= MAX_SCANNER_PRICE_DEVIATION

    def _proposed_trade_from_draft(
        self, draft: AgentDecisionDraft, candidate: ScannerCandidate | None
    ) -> ProposedTrade:
        settings = self.store.get_settings()
        entry_price = draft.entry_price or 0
        stop_loss = draft.stop_loss or 0
        risk_per_share = abs(entry_price - stop_loss)
        remaining_capital = max(settings.budget - self.store.open_capital_used(), 0)
        remaining_risk = max(
            settings.daily_max_loss
            - self.store.daily_loss_used()
            - self.store.open_risk_used(),
            0,
        )
        per_trade_risk = min(remaining_risk, settings.daily_max_loss / 3)
        max_by_capital = int(remaining_capital // entry_price) if entry_price > 0 else 0
        max_by_risk = int(per_trade_risk // risk_per_share) if risk_per_share > 0 else 0
        quantity = min(draft.quantity or 0, max_by_capital, max_by_risk)
        return ProposedTrade(
            stock=draft.stock or "",
            side=draft.side or "BUY",
            quantity=quantity,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=draft.target or 0,
            order_type="LIMIT",
            asset_class="equity",
            strategy=draft.strategy or "",
            strategy_version=_candidate_strategy_version(candidate),
            confidence=draft.confidence,
            liquidity=(candidate.indicators.get("liquidity") if candidate else None),
            volatility=(candidate.indicators.get("volatility") if candidate else None),
        )

    def _build_context(self, source: str, scanner_result) -> dict[str, Any]:
        settings = self.store.get_settings()
        report = self.store.build_daily_report()
        open_trades = [trade.model_dump(by_alias=True) for trade in self.store.list_open_trades()]
        history = [trade.model_dump(by_alias=True) for trade in self.store.list_trade_history(limit=10)]
        open_capital = self.store.open_capital_used()
        daily_loss = self.store.daily_loss_used()
        scanner_generated_at = datetime.fromisoformat(scanner_result.generated_at)
        scanner_age_seconds = max(
            int((now_utc() - scanner_generated_at).total_seconds()),
            0,
        )
        return {
            "source": source,
            "tradingMode": self.config.trading_mode,
            "marketClock": build_intraday_market_clock(),
            "rules": settings.model_dump(by_alias=True),
            "approvedStrategies": [strategy.model_dump(by_alias=True) for strategy in APPROVED_STRATEGIES],
            "scanner": {
                "generatedAt": scanner_result.generated_at,
                "generatedAtUtc": scanner_result.generated_at,
                "generatedAtIst": scanner_generated_at.astimezone(IST).isoformat(),
                "ageSeconds": scanner_age_seconds,
                "shortlist": [candidate.model_dump(by_alias=True) for candidate in scanner_result.shortlist[:8]],
                "rejected": [
                    candidate.model_dump(by_alias=True)
                    for candidate in scanner_result.candidates
                    if candidate.rejected
                ][:8],
            },
            "portfolio": {
                "currentPnl": self.store.current_pnl(),
                "dailyLossUsed": daily_loss,
                "openCapitalUsed": open_capital,
                "remainingCapital": max(settings.budget - open_capital, 0),
                "remainingDailyLoss": max(settings.daily_max_loss - daily_loss, 0),
                "remainingTradeSlots": max(
                    settings.max_trades_per_day - self.store.count_trades_today(), 0
                ),
                "dailyReport": report.model_dump(by_alias=True),
                "openTrades": open_trades,
                "recentHistory": history,
            },
            "requiredOutput": {
                "action": ["SKIP", "PROPOSE_ENTRY", "PROPOSE_EXIT", "HOLD"],
                "entryRules": (
                    "PROPOSE_ENTRY must use BUY and include a current shortlist stock, its exact "
                    "assigned strategy, quantity, entryPrice aligned with lastPrice, stopLoss, "
                    "target, confidence, reasons, risks, and expiresAt before 15:10 IST."
                ),
            },
        }

    @staticmethod
    def _candidate_for(candidates: list[ScannerCandidate], stock: str | None) -> ScannerCandidate | None:
        normalized = normalize_symbol(stock or "")
        for candidate in candidates:
            if candidate.stock_code == normalized:
                return candidate
        return None

    @staticmethod
    def _explanation_for(decision: AgentDecision) -> Explanation:
        if decision.action == "PROPOSE_ENTRY":
            summary = f"Hermes proposed {decision.side} {decision.stock} using {decision.strategy}."
        else:
            summary = f"Hermes decision: {decision.action}."
        if decision.trade_id:
            summary += " Paper trade opened after risk approval."
        if decision.order_id:
            summary += " Live order prepared for manual confirmation."
        return Explanation(
            tradeId=decision.trade_id,
            stock=decision.stock,
            strategy=decision.strategy,
            confidence=decision.confidence,
            summary=summary,
            positiveReasons=decision.reasons,
            negativeReasons=decision.risks,
            selectedCandidates=[decision.stock] if decision.stock else [],
            rejectedCandidates=[],
            riskDecision=decision.risk_decision,
            riskReason=decision.risk_reason,
            exitReason=None,
        )


def _candidate_strategy_version(candidate: ScannerCandidate | None) -> str:
    return candidate.strategy_version if candidate and candidate.strategy_version else "v1"


def _safe_agent_error(exc: Exception) -> str:
    message = str(exc)
    if message.startswith("Hermes returned invalid structured JSON."):
        return "Kimi response remained invalid after one schema-repair attempt."
    if message.startswith("Hermes selected"):
        return "Kimi response violated the approved trading-decision contract."
    return "Kimi request failed; no trading decision was accepted."


def _extract_openai_content(payload: dict[str, Any]) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HermesClientError("Hermes response did not match OpenAI-compatible chat format.") from exc
    if not isinstance(content, str):
        raise HermesClientError("Hermes response content was not text.")
    return content


def _strip_json_fence(content: str) -> str:
    stripped = content.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    return match.group(1).strip() if match else stripped


def _decode_json_object(content: str) -> Any:
    stripped = _strip_json_fence(content)
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        decoded = None

    if isinstance(decoded, str):
        try:
            decoded = json.loads(decoded)
        except json.JSONDecodeError:
            pass
    if isinstance(decoded, dict):
        return decoded

    decoder = json.JSONDecoder()
    for index, character in enumerate(stripped):
        if character != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate
    raise json.JSONDecodeError("No JSON object found", stripped, 0)
