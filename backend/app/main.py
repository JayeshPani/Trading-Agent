from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.middleware.cors import CORSMiddleware

from .agent import AgentService
from .automation import AutomationRunner
from .advanced import AdvancedTradingService
from .auth import AuthService
from .breeze import BreezeClient
from .config import AppConfig, load_config
from .credentials import CredentialService
from .improvement import SelfImprovementService
from .rate_limit import RateLimiter
from .risk import RiskEngine
from .schemas import (
    AccountRequest,
    AgentDecision,
    AgentDecisionResponse,
    AgentStatus,
    AuditEvent,
    AutomationEvent,
    AutomationRun,
    AutomationStatus,
    AutopilotResponse,
    BacktestRequest,
    BacktestRun,
    BrokerCandle,
    BreezeCredentialsRequest,
    BrokerOrder,
    BrokerPortfolio,
    BrokerQuote,
    BrokerStatus,
    BrokerTrade,
    AuthResponse,
    ChampionState,
    CredentialsStatus,
    DashboardResponse,
    DailyReport,
    EmergencyExitResponse,
    Explanation,
    HealthResponse,
    ImprovementRun,
    ImprovementLesson,
    ImprovementStatus,
    DailyImprovementReview,
    LiveAutopilotStatus,
    LiveOrder,
    LiveOrderPrepareRequest,
    LiveReadiness,
    LogoutResponse,
    OpenTrade,
    PaperValidationStatus,
    PaperExitResponse,
    ReportSendResponse,
    SafetyStatus,
    SessionRequest,
    SessionResponse,
    ScannerResult,
    SetupStatus,
    StrategyEligibility,
    StrategyValidation,
    StrategyTemplate,
    StrategyVersion,
    TradeHistoryItem,
    TradingSettings,
    ChampionRollout,
)
from .store import SQLiteStore
from .trading import TradingService


def create_app(
    *,
    config: AppConfig | None = None,
    store: SQLiteStore | None = None,
    breeze_client: BreezeClient | None = None,
) -> FastAPI:
    app_config = config or load_config()
    app_store = store or SQLiteStore(app_config.database_path)
    rate_limiter = RateLimiter()
    auth_service = AuthService(app_store)
    credential_service = CredentialService(app_config, app_store)
    app_breeze = breeze_client or BreezeClient(
        app_config,
        rate_limiter,
        credential_provider=credential_service.get_breeze_credentials,
    )
    risk_engine = RiskEngine(
        app_config,
        rate_limiter,
        credentials_ready=credential_service.breeze_credentials_saved,
    )
    service = TradingService(
        config=app_config,
        store=app_store,
        risk_engine=risk_engine,
        breeze_client=app_breeze,
        credentials_ready=credential_service.breeze_credentials_saved,
    )
    advanced_service = AdvancedTradingService(
        config=app_config,
        store=app_store,
        breeze_client=app_breeze,
        credentials_ready=credential_service.breeze_credentials_saved,
    )
    improvement_service = SelfImprovementService(
        config=app_config,
        store=app_store,
        breeze_client=app_breeze,
    )
    agent_service = AgentService(
        config=app_config,
        store=app_store,
        risk_engine=risk_engine,
        breeze_client=app_breeze,
        advanced_service=advanced_service,
        improvement_service=improvement_service,
    )
    automation_runner = AutomationRunner(
        config=app_config,
        store=app_store,
        trading_service=service,
        agent_service=agent_service,
        advanced_service=advanced_service,
        improvement_service=improvement_service,
        credentials_ready=credential_service.breeze_credentials_saved,
    )
    bearer = HTTPBearer(auto_error=False)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await automation_runner.start_background()
        try:
            yield
        finally:
            await automation_runner.stop_background()

    app = FastAPI(title="BreezePilot Backend", version="0.1.0", lifespan=lifespan)
    app.state.improvement_service = improvement_service
    app.state.automation_runner = automation_runner
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    def optional_token(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> str | None:
        return credentials.credentials if credentials else None

    def require_auth(token: str | None = Depends(optional_token)) -> str | None:
        if not app_store.account_exists():
            return token
        if not auth_service.authenticate_token(token):
            raise HTTPException(status_code=401, detail="Login required.")
        return token

    def build_setup_status(logged_in: bool) -> SetupStatus:
        account_exists = app_store.account_exists()
        credentials_saved = credential_service.breeze_credentials_saved()
        runtime = app_store.get_runtime()
        try:
            app_store.get_settings()
            settings_valid = True
        except Exception:
            settings_valid = False

        setup_complete = (
            account_exists
            and logged_in
            and credentials_saved
            and runtime.session_status == "active"
            and settings_valid
            and not runtime.emergency_lock
        )
        if not account_exists:
            next_step = "account"
        elif not logged_in:
            next_step = "login"
        elif not credentials_saved:
            next_step = "credentials"
        elif runtime.session_status != "active":
            next_step = "session"
        elif not settings_valid:
            next_step = "rules"
        elif runtime.emergency_lock:
            next_step = "locked"
        else:
            next_step = "ready"

        return SetupStatus(
            accountExists=account_exists,
            loggedIn=logged_in,
            breezeCredentialsSaved=credentials_saved,
            sessionStatus=runtime.session_status,
            settingsValid=settings_valid,
            emergencyLocked=runtime.emergency_lock,
            setupComplete=setup_complete,
            nextStep=next_step,
            tradingMode=app_config.trading_mode,
            staticIpReady=app_config.static_ip_ready,
        )

    def ensure_setup_complete() -> None:
        status = build_setup_status(logged_in=True)
        if not status.setup_complete:
            raise HTTPException(
                status_code=400,
                detail=f"Complete setup before starting autopilot. Next step: {status.next_step}.",
            )

    @app.get("/api/setup/status", response_model=SetupStatus)
    def setup_status(token: str | None = Depends(optional_token)) -> SetupStatus:
        logged_in = auth_service.authenticate_token(token) if app_store.account_exists() else False
        return build_setup_status(logged_in=logged_in)

    @app.post("/api/account/register", response_model=AuthResponse)
    def register(request: AccountRequest) -> AuthResponse:
        token = auth_service.register(request.username, request.password)
        return AuthResponse(token=token, username=request.username.strip())

    @app.post("/api/account/login", response_model=AuthResponse)
    def login(request: AccountRequest) -> AuthResponse:
        token = auth_service.login(request.username, request.password)
        return AuthResponse(token=token, username=request.username.strip())

    @app.post("/api/account/logout", response_model=LogoutResponse)
    def logout(token: str | None = Depends(require_auth)) -> LogoutResponse:
        auth_service.logout(token)
        return LogoutResponse(ok=True)

    @app.put("/api/credentials/breeze", response_model=CredentialsStatus)
    def save_breeze_credentials(
        request: BreezeCredentialsRequest,
        _token: str | None = Depends(require_auth),
    ) -> CredentialsStatus:
        credential_service.save_breeze_credentials(request.app_key, request.secret_key)
        return CredentialsStatus(breezeCredentialsSaved=True)

    @app.get("/api/credentials/status", response_model=CredentialsStatus)
    def credentials_status(_token: str | None = Depends(require_auth)) -> CredentialsStatus:
        return CredentialsStatus(
            breezeCredentialsSaved=credential_service.breeze_credentials_saved()
        )

    @app.delete("/api/credentials/breeze", response_model=CredentialsStatus)
    def delete_breeze_credentials(_token: str | None = Depends(require_auth)) -> CredentialsStatus:
        credential_service.delete_breeze_credentials()
        return CredentialsStatus(
            breezeCredentialsSaved=credential_service.breeze_credentials_saved()
        )

    @app.get("/api/dashboard", response_model=DashboardResponse)
    def dashboard(_token: str | None = Depends(require_auth)) -> DashboardResponse:
        return service.dashboard()

    @app.get("/api/settings", response_model=TradingSettings)
    def get_settings(_token: str | None = Depends(require_auth)) -> TradingSettings:
        return app_store.get_settings()

    @app.put("/api/settings", response_model=TradingSettings)
    def put_settings(
        settings: TradingSettings,
        _token: str | None = Depends(require_auth),
    ) -> TradingSettings:
        return service.save_settings(settings)

    @app.post("/api/autopilot/start", response_model=AutopilotResponse)
    def start_autopilot(_token: str | None = Depends(require_auth)) -> AutopilotResponse:
        ensure_setup_complete()
        return AutopilotResponse(autopilotEnabled=service.start_autopilot())

    @app.post("/api/autopilot/stop", response_model=AutopilotResponse)
    def stop_autopilot(_token: str | None = Depends(require_auth)) -> AutopilotResponse:
        return AutopilotResponse(autopilotEnabled=service.stop_autopilot())

    @app.post("/api/emergency-exit", response_model=EmergencyExitResponse)
    def emergency_exit(_token: str | None = Depends(require_auth)) -> EmergencyExitResponse:
        return service.emergency_exit()

    @app.post("/api/paper/run-once", response_model=Explanation)
    def paper_run_once(_token: str | None = Depends(require_auth)) -> Explanation:
        ensure_setup_complete()
        return service.run_paper_once()

    @app.post("/api/paper/monitor", response_model=list[OpenTrade])
    def paper_monitor(_token: str | None = Depends(require_auth)) -> list[OpenTrade]:
        ensure_setup_complete()
        return service.monitor_paper_trades()

    @app.post("/api/trades/{trade_id}/paper-exit", response_model=PaperExitResponse)
    def paper_exit(
        trade_id: str,
        _token: str | None = Depends(require_auth),
    ) -> PaperExitResponse:
        ensure_setup_complete()
        return service.paper_exit_trade(trade_id)

    @app.get("/api/scanner/latest", response_model=ScannerResult)
    def scanner_latest(_token: str | None = Depends(require_auth)) -> ScannerResult:
        return service.latest_scanner_result()

    @app.post("/api/scanner/run", response_model=ScannerResult)
    def scanner_run(_token: str | None = Depends(require_auth)) -> ScannerResult:
        ensure_setup_complete()
        return service.run_scanner()

    @app.get("/api/strategies", response_model=list[StrategyTemplate])
    def strategies(_token: str | None = Depends(require_auth)) -> list[StrategyTemplate]:
        return service.list_strategies()

    @app.get("/api/reports/daily", response_model=DailyReport)
    def daily_report(_token: str | None = Depends(require_auth)) -> DailyReport:
        return service.daily_report()

    @app.post("/api/backtests/run", response_model=BacktestRun)
    def backtest_run(
        request: BacktestRequest,
        _token: str | None = Depends(require_auth),
    ) -> BacktestRun:
        ensure_setup_complete()
        return advanced_service.run_backtest(request)

    @app.get("/api/backtests", response_model=list[BacktestRun])
    def backtests(_token: str | None = Depends(require_auth)) -> list[BacktestRun]:
        return advanced_service.list_backtests()

    @app.get("/api/backtests/{run_id}", response_model=BacktestRun)
    def backtest_detail(
        run_id: str,
        _token: str | None = Depends(require_auth),
    ) -> BacktestRun:
        return advanced_service.get_backtest(run_id)

    @app.get("/api/strategies/{strategy}/eligibility", response_model=StrategyEligibility)
    def strategy_eligibility(
        strategy: str,
        _token: str | None = Depends(require_auth),
    ) -> StrategyEligibility:
        return advanced_service.strategy_eligibility(strategy)

    @app.post("/api/live/orders/prepare", response_model=LiveOrder)
    def live_order_prepare(
        request: LiveOrderPrepareRequest,
        _token: str | None = Depends(require_auth),
    ) -> LiveOrder:
        ensure_setup_complete()
        return advanced_service.prepare_live_order(request)

    @app.post("/api/live/orders/{order_id}/confirm", response_model=LiveOrder)
    def live_order_confirm(
        order_id: str,
        _token: str | None = Depends(require_auth),
    ) -> LiveOrder:
        ensure_setup_complete()
        return advanced_service.confirm_live_order(order_id)

    @app.post("/api/live/orders/{order_id}/cancel", response_model=LiveOrder)
    def live_order_cancel(
        order_id: str,
        _token: str | None = Depends(require_auth),
    ) -> LiveOrder:
        ensure_setup_complete()
        return advanced_service.cancel_live_order(order_id)

    @app.post("/api/live/orders/{order_id}/refresh", response_model=LiveOrder)
    def live_order_refresh(
        order_id: str,
        _token: str | None = Depends(require_auth),
    ) -> LiveOrder:
        ensure_setup_complete()
        return advanced_service.refresh_live_order(order_id)

    @app.get("/api/live/orders", response_model=list[LiveOrder])
    def live_orders(_token: str | None = Depends(require_auth)) -> list[LiveOrder]:
        return advanced_service.list_live_orders()

    @app.post("/api/live/orders/{order_id}/square-off", response_model=LiveOrder)
    def live_order_square_off(
        order_id: str,
        _token: str | None = Depends(require_auth),
    ) -> LiveOrder:
        ensure_setup_complete()
        return advanced_service.square_off_live_order(order_id)

    @app.post("/api/live/autopilot/start", response_model=LiveAutopilotStatus)
    def live_autopilot_start(_token: str | None = Depends(require_auth)) -> LiveAutopilotStatus:
        ensure_setup_complete()
        return advanced_service.start_live_autopilot()

    @app.post("/api/live/autopilot/stop", response_model=LiveAutopilotStatus)
    def live_autopilot_stop(_token: str | None = Depends(require_auth)) -> LiveAutopilotStatus:
        return advanced_service.stop_live_autopilot()

    @app.get("/api/live/autopilot/status", response_model=LiveAutopilotStatus)
    def live_autopilot_status(_token: str | None = Depends(require_auth)) -> LiveAutopilotStatus:
        return advanced_service.live_autopilot_status()

    @app.get("/api/live/readiness", response_model=LiveReadiness)
    def live_readiness(_token: str | None = Depends(require_auth)) -> LiveReadiness:
        return advanced_service.live_readiness()

    @app.get("/api/agent/status", response_model=AgentStatus)
    def agent_status(_token: str | None = Depends(require_auth)) -> AgentStatus:
        return agent_service.status()

    @app.post("/api/agent/analyze", response_model=AgentDecisionResponse)
    def agent_analyze(_token: str | None = Depends(require_auth)) -> AgentDecisionResponse:
        ensure_setup_complete()
        return agent_service.analyze()

    @app.post("/api/agent/paper-cycle", response_model=AgentDecisionResponse)
    def agent_paper_cycle(_token: str | None = Depends(require_auth)) -> AgentDecisionResponse:
        ensure_setup_complete()
        return agent_service.paper_cycle()

    @app.post("/api/agent/live-proposal", response_model=AgentDecisionResponse)
    def agent_live_proposal(_token: str | None = Depends(require_auth)) -> AgentDecisionResponse:
        ensure_setup_complete()
        return agent_service.live_proposal()

    @app.post("/api/agent/monitor", response_model=AgentDecisionResponse)
    def agent_monitor(_token: str | None = Depends(require_auth)) -> AgentDecisionResponse:
        ensure_setup_complete()
        return agent_service.monitor()

    @app.get("/api/agent/decisions", response_model=list[AgentDecision])
    def agent_decisions(_token: str | None = Depends(require_auth)) -> list[AgentDecision]:
        return agent_service.decisions()

    @app.post("/api/improvement/run-after-market", response_model=ImprovementRun)
    def improvement_run(_token: str | None = Depends(require_auth)) -> ImprovementRun:
        return improvement_service.retry_failed_review()

    @app.get("/api/improvement/runs", response_model=list[ImprovementRun])
    def improvement_runs(_token: str | None = Depends(require_auth)) -> list[ImprovementRun]:
        return advanced_service.list_improvement_runs()

    @app.get("/api/improvement/status", response_model=ImprovementStatus)
    def improvement_status(_token: str | None = Depends(require_auth)) -> ImprovementStatus:
        return improvement_service.status()

    @app.get("/api/improvement/reviews", response_model=list[DailyImprovementReview])
    def improvement_reviews(
        _token: str | None = Depends(require_auth),
    ) -> list[DailyImprovementReview]:
        return improvement_service.reviews()

    @app.get("/api/improvement/lessons", response_model=list[ImprovementLesson])
    def improvement_lessons(
        _token: str | None = Depends(require_auth),
    ) -> list[ImprovementLesson]:
        return improvement_service.lessons()

    @app.get("/api/strategy-versions", response_model=list[StrategyVersion])
    def strategy_versions(_token: str | None = Depends(require_auth)) -> list[StrategyVersion]:
        return advanced_service.list_strategy_versions()

    @app.get("/api/strategy-versions/{version_id}", response_model=StrategyVersion)
    def strategy_version(
        version_id: str,
        _token: str | None = Depends(require_auth),
    ) -> StrategyVersion:
        return advanced_service.get_strategy_version(version_id)

    @app.get(
        "/api/strategy-versions/{version_id}/validation",
        response_model=StrategyValidation,
    )
    def strategy_version_validation(
        version_id: str,
        _token: str | None = Depends(require_auth),
    ) -> StrategyValidation:
        return improvement_service.validation(version_id)

    @app.get("/api/champion", response_model=ChampionState)
    def champion(_token: str | None = Depends(require_auth)) -> ChampionState:
        return advanced_service.champion_state()

    @app.get("/api/challengers", response_model=list[StrategyVersion])
    def challengers(_token: str | None = Depends(require_auth)) -> list[StrategyVersion]:
        return advanced_service.champion_state().challengers

    @app.post("/api/challengers/{version_id}/promote", response_model=StrategyVersion)
    def promote_challenger(
        version_id: str,
        _token: str | None = Depends(require_auth),
    ) -> StrategyVersion:
        return advanced_service.promote_challenger(version_id)

    @app.post("/api/champion/rollback", response_model=StrategyVersion)
    def rollback_champion(_token: str | None = Depends(require_auth)) -> StrategyVersion:
        return advanced_service.rollback_champion()

    @app.get("/api/champion/rollout", response_model=ChampionRollout)
    def champion_rollout(_token: str | None = Depends(require_auth)) -> ChampionRollout:
        return improvement_service.rollout()

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return advanced_service.health()

    @app.get("/api/audit", response_model=list[AuditEvent])
    def audit(_token: str | None = Depends(require_auth)) -> list[AuditEvent]:
        return advanced_service.audit_events()

    @app.get("/api/safety/status", response_model=SafetyStatus)
    def safety_status(_token: str | None = Depends(require_auth)) -> SafetyStatus:
        return advanced_service.safety_status()

    @app.post("/api/safety/kill-switch", response_model=SafetyStatus)
    def safety_kill_switch(_token: str | None = Depends(require_auth)) -> SafetyStatus:
        return advanced_service.activate_kill_switch()

    @app.post("/api/reports/daily/send", response_model=ReportSendResponse)
    def send_daily_report(_token: str | None = Depends(require_auth)) -> ReportSendResponse:
        return advanced_service.send_daily_report()

    @app.get("/api/automation/status", response_model=AutomationStatus)
    def automation_status(_token: str | None = Depends(require_auth)) -> AutomationStatus:
        return automation_runner.status()

    @app.post("/api/automation/start", response_model=AutomationStatus)
    def automation_start(_token: str | None = Depends(require_auth)) -> AutomationStatus:
        ensure_setup_complete()
        return automation_runner.start()

    @app.post("/api/automation/stop", response_model=AutomationStatus)
    def automation_stop(_token: str | None = Depends(require_auth)) -> AutomationStatus:
        return automation_runner.stop()

    @app.post("/api/automation/run-once", response_model=AutomationRun)
    async def automation_run_once(_token: str | None = Depends(require_auth)) -> AutomationRun:
        ensure_setup_complete()
        return await automation_runner.run_once(manual=True)

    @app.get("/api/automation/events", response_model=list[AutomationEvent])
    def automation_events(_token: str | None = Depends(require_auth)) -> list[AutomationEvent]:
        return automation_runner.events()

    @app.get("/api/paper/validation", response_model=PaperValidationStatus)
    def paper_validation(_token: str | None = Depends(require_auth)) -> PaperValidationStatus:
        return automation_runner.paper_validation()

    @app.get("/api/trades/open", response_model=list[OpenTrade])
    def open_trades(_token: str | None = Depends(require_auth)) -> list[OpenTrade]:
        return app_store.list_open_trades()

    @app.get("/api/trades/history", response_model=list[TradeHistoryItem])
    def trade_history(_token: str | None = Depends(require_auth)) -> list[TradeHistoryItem]:
        return app_store.list_trade_history()

    @app.get("/api/explanations/latest", response_model=Explanation)
    def latest_explanation(_token: str | None = Depends(require_auth)) -> Explanation:
        explanation = app_store.latest_explanation()
        if explanation is None:
            return Explanation(
                summary="No AI explanation yet.",
                positiveReasons=[],
                negativeReasons=[],
                riskDecision="none",
                riskReason="No decision has been recorded.",
            )
        return explanation

    @app.post("/api/session", response_model=SessionResponse)
    def session(
        request: SessionRequest,
        _token: str | None = Depends(require_auth),
    ) -> SessionResponse:
        runtime = service.validate_session(request.session_key)
        return SessionResponse(
            sessionStatus=runtime.session_status,
            expiresAt=runtime.session_expires_at,
            tradingMode=app_config.trading_mode,
            staticIpReady=app_config.static_ip_ready,
        )

    @app.get("/api/broker/status", response_model=BrokerStatus)
    def broker_status(_token: str | None = Depends(require_auth)) -> BrokerStatus:
        return service.broker_status()

    @app.get("/api/broker/quote/{stock_code}", response_model=BrokerQuote)
    def broker_quote(
        stock_code: str,
        _token: str | None = Depends(require_auth),
    ) -> BrokerQuote:
        return service.broker_quote(stock_code)

    @app.get("/api/broker/history/{stock_code}", response_model=list[BrokerCandle])
    def broker_history(
        stock_code: str,
        from_date: str | None = None,
        to_date: str | None = None,
        interval: str = "day",
        _token: str | None = Depends(require_auth),
    ) -> list[BrokerCandle]:
        return service.broker_history(
            stock_code,
            from_date=from_date,
            to_date=to_date,
            interval=interval,
        )

    @app.get("/api/broker/portfolio", response_model=BrokerPortfolio)
    def broker_portfolio(_token: str | None = Depends(require_auth)) -> BrokerPortfolio:
        return service.broker_portfolio()

    @app.get("/api/broker/orders", response_model=list[BrokerOrder])
    def broker_orders(_token: str | None = Depends(require_auth)) -> list[BrokerOrder]:
        return service.broker_orders()

    @app.get("/api/broker/trades", response_model=list[BrokerTrade])
    def broker_trades(_token: str | None = Depends(require_auth)) -> list[BrokerTrade]:
        return service.broker_trades()

    return app


app = create_app()
