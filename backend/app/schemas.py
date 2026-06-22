from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .constants import NIFTY_50_SYMBOLS

TradingMode = Literal["intraday", "delivery"]
SessionStatus = Literal["active", "missing", "expired", "unknown"]
RiskStatus = Literal["clear", "warning", "locked"]
RiskDecisionValue = Literal["approved", "rejected", "pending", "none"]
AgentIntegrityStatus = Literal["genuine", "repaired", "system_error"]
AgentAction = Literal["SKIP", "PROPOSE_ENTRY", "PROPOSE_EXIT", "TIGHTEN_STOP", "HOLD"]
ImprovementHealth = Literal["disabled", "idle", "running", "healthy", "failed"]
RuleOperator = Literal["gt", "gte", "lt", "lte", "between"]
StrategyRuleField = Literal[
    "rsi",
    "priceToVwap",
    "trend",
    "volumeSpike",
    "volatility",
    "liquidity",
    "supportDistance",
    "resistanceDistance",
]

SYMBOL_RE = re.compile(r"^[A-Z0-9&-]{1,20}$")
DERIVATIVE_MARKERS = ("FUT", "CE", "PE")


def normalize_symbol(symbol: str) -> str:
    return re.sub(r"[^A-Z0-9&-]", "", symbol.strip().upper())


def is_equity_symbol(symbol: str) -> bool:
    normalized = normalize_symbol(symbol)
    if not normalized or not SYMBOL_RE.fullmatch(normalized):
        return False
    if "FUT" in normalized:
        return False
    if len(normalized) > 6 and normalized[-2:] in {"CE", "PE"} and any(char.isdigit() for char in normalized):
        return False
    return True


class TradingSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    budget: float = Field(gt=0)
    stop_loss_percent: float = Field(alias="stopLossPercent", gt=0)
    daily_max_loss: float = Field(alias="dailyMaxLoss", gt=0)
    max_trades_per_day: int = Field(alias="maxTradesPerDay", gt=0)
    target_percent: float = Field(default=3, alias="targetPercent", gt=0)
    mode: TradingMode
    stock_preset: Literal["NIFTY 50", "CUSTOM"] = Field(alias="stockPreset")
    allowed_stocks: list[str] = Field(default_factory=list, alias="allowedStocks")

    @field_validator("allowed_stocks", mode="before")
    @classmethod
    def normalize_allowed_stocks(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("allowedStocks must be a list of stock symbols.")

        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("allowedStocks must contain only strings.")
            symbol = normalize_symbol(item)
            if symbol and symbol not in normalized:
                normalized.append(symbol)
        return normalized

    @model_validator(mode="after")
    def validate_stock_universe(self) -> "TradingSettings":
        if self.stock_preset == "CUSTOM" and not self.allowed_stocks:
            raise ValueError("Add at least one allowed stock or choose the NIFTY 50 preset.")

        for symbol in self.allowed_stocks:
            if not is_equity_symbol(symbol):
                raise ValueError(f"{symbol} is not accepted as an equity stock symbol.")
        return self

    def is_stock_allowed(self, symbol: str) -> bool:
        normalized = normalize_symbol(symbol)
        if self.stock_preset == "NIFTY 50":
            return normalized in NIFTY_50_SYMBOLS
        return normalized in self.allowed_stocks


class PnlSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    current_pnl: float = Field(alias="currentPnl")
    daily_loss_used: float = Field(alias="dailyLossUsed")
    remaining_budget: float = Field(alias="remainingBudget")
    open_trades_count: int = Field(alias="openTradesCount")


class OpenTrade(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    stock: str
    side: Literal["BUY", "SELL"]
    quantity: int
    entry_price: float = Field(alias="entryPrice")
    stop_loss: float = Field(alias="stopLoss")
    target: float
    live_pnl: float = Field(alias="livePnl")
    status: str
    strategy: str


class TradeHistoryItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    stock: str
    side: Literal["BUY", "SELL"]
    quantity: int
    entry_price: float = Field(alias="entryPrice")
    exit_price: float = Field(alias="exitPrice")
    pnl: float
    strategy: str
    status: str
    exit_reason: str = Field(alias="exitReason")
    closed_at: str = Field(alias="closedAt")


class Explanation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    trade_id: str | None = Field(default=None, alias="tradeId")
    stock: str | None = None
    strategy: str | None = None
    confidence: float | None = None
    summary: str
    positive_reasons: list[str] = Field(default_factory=list, alias="positiveReasons")
    negative_reasons: list[str] = Field(default_factory=list, alias="negativeReasons")
    selected_candidates: list[str] = Field(default_factory=list, alias="selectedCandidates")
    rejected_candidates: list[str] = Field(default_factory=list, alias="rejectedCandidates")
    risk_decision: RiskDecisionValue = Field(alias="riskDecision")
    risk_reason: str = Field(alias="riskReason")
    exit_reason: str | None = Field(default=None, alias="exitReason")


class StrategyTemplate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    version: str
    description: str


class ScannerCandidate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    stock_code: str = Field(alias="stockCode")
    score: float
    strategy: str | None = None
    strategy_version: str | None = Field(default=None, alias="strategyVersion")
    last_price: float = Field(alias="lastPrice")
    indicators: dict[str, float] = Field(default_factory=dict)
    positive_reasons: list[str] = Field(default_factory=list, alias="positiveReasons")
    negative_reasons: list[str] = Field(default_factory=list, alias="negativeReasons")
    rejected: bool = False
    rejection_reason: str | None = Field(default=None, alias="rejectionReason")


class ScannerResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    generated_at: str = Field(alias="generatedAt")
    candidates: list[ScannerCandidate] = Field(default_factory=list)
    shortlist: list[ScannerCandidate] = Field(default_factory=list)
    broker_status: Literal["healthy", "degraded", "unavailable"] = Field(
        default="healthy",
        alias="brokerStatus",
    )
    broker_error_count: int = Field(default=0, alias="brokerErrorCount")
    broker_error: str | None = Field(default=None, alias="brokerError")


class DailyReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    trading_day: str = Field(alias="tradingDay")
    pnl: float
    trades_count: int = Field(alias="tradesCount")
    wins: int
    losses: int
    open_trades: int = Field(alias="openTrades")
    daily_loss_used: float = Field(alias="dailyLossUsed")
    generated_at: str = Field(alias="generatedAt")


class PaperExitResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    trade: TradeHistoryItem
    explanation: Explanation


class BacktestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    strategy: str
    stock_code: str | None = Field(default=None, alias="stockCode")
    from_date: str | None = Field(default=None, alias="fromDate")
    to_date: str | None = Field(default=None, alias="toDate")


class BacktestMetrics(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    win_rate: float = Field(alias="winRate")
    profit_factor: float = Field(alias="profitFactor")
    max_drawdown: float = Field(alias="maxDrawdown")
    average_profit: float = Field(alias="averageProfit")
    average_loss: float = Field(alias="averageLoss")
    trades_count: int = Field(alias="tradesCount")
    best_market_condition: str = Field(alias="bestMarketCondition")
    worst_market_condition: str = Field(alias="worstMarketCondition")


class BacktestRun(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    strategy: str
    strategy_version: str = Field(alias="strategyVersion")
    stock_universe: list[str] = Field(alias="stockUniverse")
    from_date: str = Field(alias="fromDate")
    to_date: str = Field(alias="toDate")
    settings_snapshot: dict[str, object] = Field(alias="settingsSnapshot")
    metrics: BacktestMetrics
    passed: bool
    reason: str
    created_at: str = Field(alias="createdAt")


class StrategyEligibility(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    strategy: str
    eligible: bool
    reason: str
    latest_backtest: BacktestRun | None = Field(default=None, alias="latestBacktest")


class LiveOrderPrepareRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    stock_code: str | None = Field(default=None, alias="stockCode")
    strategy: str | None = None
    quantity: int | None = None
    price: float | None = None
    side: Literal["BUY", "SELL"] = "BUY"


class LiveOrder(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    stock_code: str = Field(alias="stockCode")
    side: Literal["BUY", "SELL"]
    quantity: int
    price: float
    order_type: str = Field(alias="orderType")
    status: str
    strategy: str
    broker_order_id: str | None = Field(default=None, alias="brokerOrderId")
    reason: str | None = None
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")


class LiveAutopilotStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    enabled: bool
    eligible: bool
    reason: str
    max_orders_per_day: int = Field(alias="maxOrdersPerDay")
    max_open_positions: int = Field(alias="maxOpenPositions")
    max_capital: float = Field(alias="maxCapital")


class LiveReadiness(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ready_for_manual_live_order: bool = Field(alias="readyForManualLiveOrder")
    ready_for_live_autopilot: bool = Field(alias="readyForLiveAutopilot")
    live_mode: bool = Field(alias="liveMode")
    credentials_ready: bool = Field(alias="credentialsReady")
    session_active: bool = Field(alias="sessionActive")
    static_ip_ready: bool = Field(alias="staticIpReady")
    strategy_eligible: bool = Field(alias="strategyEligible")
    paper_validation_ready: bool = Field(alias="paperValidationReady")
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_action: str = Field(alias="nextAction")


class ImprovementRun(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    status: str
    tools_available: dict[str, bool] = Field(alias="toolsAvailable")
    created_version_id: str | None = Field(default=None, alias="createdVersionId")
    reason: str
    created_at: str = Field(alias="createdAt")


class StrategyRuleCondition(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    field: StrategyRuleField
    operator: RuleOperator
    value: float | None = None
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def validate_operands(self) -> "StrategyRuleCondition":
        if self.operator == "between":
            if self.minimum is None or self.maximum is None or self.minimum >= self.maximum:
                raise ValueError("between conditions require minimum < maximum.")
        elif self.value is None:
            raise ValueError("comparison conditions require value.")
        return self


class ConstrainedStrategyRule(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str = Field(min_length=3, max_length=60)
    description: str = Field(min_length=5, max_length=240)
    conditions: list[StrategyRuleCondition] = Field(min_length=2, max_length=6)
    minimum_score: float = Field(default=60, alias="minimumScore", ge=0, le=100)
    stop_loss_percent: float = Field(alias="stopLossPercent", gt=0, le=5)
    target_percent: float = Field(alias="targetPercent", gt=0, le=10)
    entry_start_ist: str = Field(default="09:20", alias="entryStartIst")
    entry_end_ist: str = Field(default="15:10", alias="entryEndIst")

    @field_validator("entry_start_ist", "entry_end_ist")
    @classmethod
    def validate_clock(cls, value: str) -> str:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("time must use HH:MM.")
        return value

    @model_validator(mode="after")
    def validate_rule(self) -> "ConstrainedStrategyRule":
        if self.entry_start_ist >= self.entry_end_ist:
            raise ValueError("entryStartIst must be before entryEndIst.")
        if self.entry_end_ist > "15:10":
            raise ValueError("generated strategies cannot enter after 15:10 IST.")
        if self.target_percent <= self.stop_loss_percent:
            raise ValueError("targetPercent must be greater than stopLossPercent.")
        fields = [condition.field for condition in self.conditions]
        if len(fields) != len(set(fields)):
            raise ValueError("strategy conditions must use unique indicators.")
        return self


class ImprovementReviewDraft(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    summary: str = Field(min_length=5, max_length=500)
    successes: list[str] = Field(default_factory=list, max_length=8)
    mistakes: list[str] = Field(default_factory=list, max_length=8)
    lessons: list[str] = Field(min_length=1, max_length=8)
    entry_timing_notes: list[str] = Field(default_factory=list, alias="entryTimingNotes", max_length=6)
    exit_timing_notes: list[str] = Field(default_factory=list, alias="exitTimingNotes", max_length=6)
    challenger: ConstrainedStrategyRule | None = None


class DailyImprovementReview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    trading_day: str = Field(alias="tradingDay")
    status: Literal["completed", "failed", "insufficient_data"]
    summary: str
    successes: list[str] = Field(default_factory=list)
    mistakes: list[str] = Field(default_factory=list)
    entry_timing_notes: list[str] = Field(default_factory=list, alias="entryTimingNotes")
    exit_timing_notes: list[str] = Field(default_factory=list, alias="exitTimingNotes")
    evidence_counts: dict[str, int] = Field(default_factory=dict, alias="evidenceCounts")
    created_version_id: str | None = Field(default=None, alias="createdVersionId")
    error: str | None = None
    created_at: str = Field(alias="createdAt")


class ImprovementLesson(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    review_id: str = Field(alias="reviewId")
    text: str
    evidence_count: int = Field(alias="evidenceCount", ge=1)
    active: bool = True
    created_at: str = Field(alias="createdAt")


class StrategyValidation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version_id: str = Field(alias="versionId")
    backtest_passed: bool = Field(alias="backtestPassed")
    backtest_reason: str = Field(alias="backtestReason")
    shadow_days: int = Field(alias="shadowDays")
    shadow_trades: int = Field(alias="shadowTrades")
    shadow_profit_factor: float = Field(alias="shadowProfitFactor")
    shadow_daily_loss_breached: bool = Field(alias="shadowDailyLossBreached")
    errors_clear: bool = Field(alias="errorsClear")
    champion_comparison_passed: bool = Field(alias="championComparisonPassed")
    eligible_for_promotion: bool = Field(alias="eligibleForPromotion")
    reason: str


class ChampionRollout(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    champion_version_id: str | None = Field(default=None, alias="championVersionId")
    stage_percent: int = Field(default=0, alias="stagePercent")
    live_days: int = Field(default=0, alias="liveDays")
    live_trades: int = Field(default=0, alias="liveTrades")
    live_profit_factor: float = Field(default=0, alias="liveProfitFactor")
    rollback_reason: str | None = Field(default=None, alias="rollbackReason")
    updated_at: str = Field(alias="updatedAt")


class ImprovementStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    enabled: bool
    health: ImprovementHealth
    scheduled_time_ist: str = Field(alias="scheduledTimeIst")
    auto_promotion_enabled: bool = Field(alias="autoPromotionEnabled")
    last_review_day: str | None = Field(default=None, alias="lastReviewDay")
    last_run_at: str | None = Field(default=None, alias="lastRunAt")
    latest_error: str | None = Field(default=None, alias="latestError")
    active_lessons: int = Field(alias="activeLessons")
    challengers: int
    rollout: ChampionRollout
    message: str


class StrategyVersion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    strategy: str
    version: str
    source_version_id: str | None = Field(default=None, alias="sourceVersionId")
    parameters: dict[str, object] = Field(default_factory=dict)
    backtest_metrics: dict[str, object] = Field(default_factory=dict, alias="backtestMetrics")
    paper_metrics: dict[str, object] = Field(default_factory=dict, alias="paperMetrics")
    risk_notes: list[str] = Field(default_factory=list, alias="riskNotes")
    promotion_status: str = Field(alias="promotionStatus")
    created_at: str = Field(alias="createdAt")


class ChampionState(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    champion: StrategyVersion | None = None
    challengers: list[StrategyVersion] = Field(default_factory=list)


class SafetyStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kill_switch_active: bool = Field(alias="killSwitchActive")
    emergency_locked: bool = Field(alias="emergencyLocked")
    daily_loss_locked: bool = Field(alias="dailyLossLocked")
    session_active: bool = Field(alias="sessionActive")
    static_ip_ready: bool = Field(alias="staticIpReady")
    live_mode: bool = Field(alias="liveMode")
    capital_lock: float = Field(alias="capitalLock")
    max_order_limit: int = Field(alias="maxOrderLimit")
    message: str


class AuditEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    event_type: str = Field(alias="eventType")
    message: str
    details: dict[str, object] = Field(default_factory=dict)
    created_at: str = Field(alias="createdAt")


class HealthResponse(BaseModel):
    status: str
    database: str
    trading_mode: str = Field(alias="tradingMode")
    static_ip_ready: bool = Field(alias="staticIpReady")


class ReportSendResponse(BaseModel):
    ok: bool
    message: str


class AutomationStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    enabled: bool
    running: bool
    config_enabled: bool = Field(alias="configEnabled")
    mode: str
    auto_live_entries_enabled: bool = Field(alias="autoLiveEntriesEnabled")
    auto_live_exits_enabled: bool = Field(alias="autoLiveExitsEnabled")
    last_paper_scan_at: str | None = Field(default=None, alias="lastPaperScanAt")
    last_paper_monitor_at: str | None = Field(default=None, alias="lastPaperMonitorAt")
    last_live_exit_at: str | None = Field(default=None, alias="lastLiveExitAt")
    last_live_entry_at: str | None = Field(default=None, alias="lastLiveEntryAt")
    latest_error: str | None = Field(default=None, alias="latestError")
    broker_health: Literal["healthy", "degraded", "unavailable"] = Field(
        default="healthy",
        alias="brokerHealth",
    )
    consecutive_broker_failures: int = Field(
        default=0,
        alias="consecutiveBrokerFailures",
    )
    last_broker_success_at: str | None = Field(default=None, alias="lastBrokerSuccessAt")
    latest_broker_error: str | None = Field(default=None, alias="latestBrokerError")
    message: str


class AutomationEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    event_type: str = Field(alias="eventType")
    severity: Literal["info", "warning", "error"]
    message: str
    details: dict[str, object] = Field(default_factory=dict)
    created_at: str = Field(alias="createdAt")


class AutomationRun(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    mode: str
    status: str
    started_at: str = Field(alias="startedAt")
    finished_at: str | None = Field(default=None, alias="finishedAt")
    summary: str


class PaperValidationStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    eligible: bool
    reason: str
    days: int
    completed_trades: int = Field(alias="completedTrades")
    profit_factor: float = Field(alias="profitFactor")
    daily_loss_breached: bool = Field(alias="dailyLossBreached")
    unresolved_automation_errors: int = Field(alias="unresolvedAutomationErrors")
    unresolved_agent_errors: int = Field(alias="unresolvedAgentErrors")
    required_days: int = Field(alias="requiredDays")
    required_trades: int = Field(alias="requiredTrades")


class DashboardResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    autopilot_enabled: bool = Field(alias="autopilotEnabled")
    session_status: SessionStatus = Field(alias="sessionStatus")
    pnl: PnlSummary
    open_trades: list[OpenTrade] = Field(alias="openTrades")
    latest_explanation: Explanation | None = Field(alias="latestExplanation")
    risk_status: RiskStatus = Field(alias="riskStatus")
    risk_message: str = Field(alias="riskMessage")


class AutopilotResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    autopilot_enabled: bool = Field(alias="autopilotEnabled")


class EmergencyExitResponse(BaseModel):
    locked: bool


class SessionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_key: str = Field(alias="sessionKey", min_length=1)


class SessionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_status: SessionStatus = Field(alias="sessionStatus")
    expires_at: str | None = Field(default=None, alias="expiresAt")
    trading_mode: str = Field(alias="tradingMode")
    static_ip_ready: bool = Field(alias="staticIpReady")


class AccountRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=200)


class AuthResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    token: str
    username: str


class LogoutResponse(BaseModel):
    ok: bool


class BreezeCredentialsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    app_key: str = Field(alias="appKey", min_length=1)
    secret_key: str = Field(alias="secretKey", min_length=1)


class CredentialsStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    breeze_credentials_saved: bool = Field(alias="breezeCredentialsSaved")


class SetupStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account_exists: bool = Field(alias="accountExists")
    logged_in: bool = Field(alias="loggedIn")
    breeze_credentials_saved: bool = Field(alias="breezeCredentialsSaved")
    session_status: SessionStatus = Field(alias="sessionStatus")
    settings_valid: bool = Field(alias="settingsValid")
    emergency_locked: bool = Field(alias="emergencyLocked")
    setup_complete: bool = Field(alias="setupComplete")
    next_step: str = Field(alias="nextStep")
    trading_mode: str = Field(alias="tradingMode")
    static_ip_ready: bool = Field(alias="staticIpReady")


class BrokerStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    credentials_configured: bool = Field(alias="credentialsConfigured")
    session_status: SessionStatus = Field(alias="sessionStatus")
    trading_mode: str = Field(alias="tradingMode")
    static_ip_ready: bool = Field(alias="staticIpReady")
    api_rate_limit_available: bool = Field(alias="apiRateLimitAvailable")
    order_rate_limit_available: bool = Field(alias="orderRateLimitAvailable")
    message: str


class BrokerQuote(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    stock_code: str = Field(alias="stockCode")
    exchange_code: str = Field(alias="exchangeCode")
    last_price: float = Field(alias="lastPrice")
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    timestamp: str | None = None


class BrokerCandle(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    stock_code: str = Field(alias="stockCode")
    exchange_code: str = Field(alias="exchangeCode")
    interval: str
    datetime: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


class BrokerFunds(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_bank_balance: float | None = Field(default=None, alias="totalBankBalance")
    allocated_equity: float | None = Field(default=None, alias="allocatedEquity")
    block_by_trade_equity: float | None = Field(default=None, alias="blockByTradeEquity")
    unallocated_balance: float | None = Field(default=None, alias="unallocatedBalance")


class BrokerHolding(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    stock_code: str = Field(alias="stockCode")
    isin: str | None = None
    quantity: float
    available_quantity: float | None = Field(default=None, alias="availableQuantity")


class BrokerPosition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    stock_code: str = Field(alias="stockCode")
    exchange_code: str = Field(alias="exchangeCode")
    product_type: str = Field(alias="productType")
    quantity: float
    average_price: float | None = Field(default=None, alias="averagePrice")
    pnl: float | None = None
    action: str | None = None


class BrokerOrder(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    order_id: str = Field(alias="orderId")
    stock_code: str | None = Field(default=None, alias="stockCode")
    action: str | None = None
    quantity: float | None = None
    price: float | None = None
    status: str | None = None
    order_type: str | None = Field(default=None, alias="orderType")
    product_type: str | None = Field(default=None, alias="productType")
    exchange_code: str | None = Field(default=None, alias="exchangeCode")
    created_at: str | None = Field(default=None, alias="createdAt")
    message: str | None = None


class BrokerTrade(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    trade_id: str = Field(alias="tradeId")
    order_id: str | None = Field(default=None, alias="orderId")
    stock_code: str | None = Field(default=None, alias="stockCode")
    action: str | None = None
    quantity: float | None = None
    price: float | None = None
    trade_date: str | None = Field(default=None, alias="tradeDate")
    exchange_code: str | None = Field(default=None, alias="exchangeCode")
    product_type: str | None = Field(default=None, alias="productType")


class BrokerPortfolio(BaseModel):
    funds: BrokerFunds
    holdings: list[BrokerHolding]
    positions: list[BrokerPosition]


class AgentStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    enabled: bool
    provider: str
    model: str
    base_url: str = Field(alias="baseUrl")
    api_key_configured: bool = Field(alias="apiKeyConfigured")
    trading_mode: str = Field(alias="tradingMode")
    healthy: bool
    consecutive_system_errors: int = Field(alias="consecutiveSystemErrors")
    latest_integrity_status: AgentIntegrityStatus | None = Field(
        default=None, alias="latestIntegrityStatus"
    )
    last_valid_decision_at: str | None = Field(default=None, alias="lastValidDecisionAt")
    message: str


class AgentDecision(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    run_id: str = Field(alias="runId")
    action: AgentAction
    stock: str | None = None
    strategy: str | None = None
    side: Literal["BUY", "SELL"] | None = None
    quantity: int | None = None
    entry_price: float | None = Field(default=None, alias="entryPrice")
    stop_loss: float | None = Field(default=None, alias="stopLoss")
    target: float | None = None
    confidence: float
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    expires_at: str | None = Field(default=None, alias="expiresAt")
    risk_decision: RiskDecisionValue = Field(alias="riskDecision")
    risk_reason: str = Field(alias="riskReason")
    trade_id: str | None = Field(default=None, alias="tradeId")
    order_id: str | None = Field(default=None, alias="orderId")
    integrity_status: AgentIntegrityStatus = Field(alias="integrityStatus")
    integrity_message: str = Field(alias="integrityMessage")
    source: str
    created_at: str = Field(alias="createdAt")


class AgentDecisionDraft(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    action: AgentAction
    stock: str | None = None
    strategy: str | None = None
    side: Literal["BUY", "SELL"] | None = None
    quantity: int | None = None
    entry_price: float | None = Field(default=None, alias="entryPrice")
    stop_loss: float | None = Field(default=None, alias="stopLoss")
    target: float | None = None
    confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    expires_at: str | None = Field(default=None, alias="expiresAt")


class AgentDecisionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    decision: AgentDecision
    explanation: Explanation
    live_order: LiveOrder | None = Field(default=None, alias="liveOrder")
