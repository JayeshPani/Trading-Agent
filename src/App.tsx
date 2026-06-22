import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { DEFAULT_SETTINGS, EMPTY_DASHBOARD } from "./defaults";
import {
  clearAuthToken,
  loadPreferences,
  saveAuthToken,
  saveBackendUrl,
  saveDraftSettings,
  saveLastTab
} from "./storage";
import type {
  AuditEvent,
  AgentDecision,
  AgentDecisionResponse,
  AgentStatus,
  AppTab,
  AutomationEvent,
  AutomationStatus,
  BacktestRun,
  ChampionRollout,
  ChampionState,
  ConnectionState,
  DailyReport,
  DailyImprovementReview,
  DashboardResponse,
  Explanation,
  ImprovementRun,
  ImprovementLesson,
  ImprovementStatus,
  LiveAutopilotStatus,
  LiveOrder,
  LiveReadiness,
  OpenTrade,
  PaperValidationStatus,
  SafetyStatus,
  ScannerResult,
  SetupStatus,
  StrategyEligibility,
  StrategyTemplate,
  StrategyVersion,
  TradeHistoryItem,
  TradingSettings
} from "./types";
import { normalizeSettings, normalizeSymbol, validateSettings } from "./validation";

function App() {
  const [backendUrl, setBackendUrl] = useState("");
  const [savedBackendUrl, setSavedBackendUrl] = useState("");
  const [authToken, setAuthToken] = useState<string | undefined>(undefined);
  const [connectionState, setConnectionState] = useState<ConnectionState>("checking");
  const [activeTab, setActiveTab] = useState<AppTab>("dashboard");
  const [settings, setSettings] = useState<TradingSettings>(DEFAULT_SETTINGS);
  const [dashboard, setDashboard] = useState<DashboardResponse>(EMPTY_DASHBOARD);
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null);
  const [openTrades, setOpenTrades] = useState<OpenTrade[]>([]);
  const [tradeHistory, setTradeHistory] = useState<TradeHistoryItem[]>([]);
  const [latestExplanation, setLatestExplanation] = useState<Explanation | null>(null);
  const [scannerResult, setScannerResult] = useState<ScannerResult | null>(null);
  const [strategies, setStrategies] = useState<StrategyTemplate[]>([]);
  const [dailyReport, setDailyReport] = useState<DailyReport | null>(null);
  const [backtests, setBacktests] = useState<BacktestRun[]>([]);
  const [strategyEligibility, setStrategyEligibility] = useState<StrategyEligibility | null>(null);
  const [liveOrders, setLiveOrders] = useState<LiveOrder[]>([]);
  const [liveAutopilotStatus, setLiveAutopilotStatus] = useState<LiveAutopilotStatus | null>(null);
  const [liveReadiness, setLiveReadiness] = useState<LiveReadiness | null>(null);
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null);
  const [agentDecisions, setAgentDecisions] = useState<AgentDecision[]>([]);
  const [automationStatus, setAutomationStatus] = useState<AutomationStatus | null>(null);
  const [automationEvents, setAutomationEvents] = useState<AutomationEvent[]>([]);
  const [paperValidation, setPaperValidation] = useState<PaperValidationStatus | null>(null);
  const [improvementRuns, setImprovementRuns] = useState<ImprovementRun[]>([]);
  const [improvementStatus, setImprovementStatus] = useState<ImprovementStatus | null>(null);
  const [improvementReviews, setImprovementReviews] = useState<DailyImprovementReview[]>([]);
  const [improvementLessons, setImprovementLessons] = useState<ImprovementLesson[]>([]);
  const [championRollout, setChampionRollout] = useState<ChampionRollout | null>(null);
  const [strategyVersions, setStrategyVersions] = useState<StrategyVersion[]>([]);
  const [championState, setChampionState] = useState<ChampionState | null>(null);
  const [safetyStatus, setSafetyStatus] = useState<SafetyStatus | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [symbolInput, setSymbolInput] = useState("");
  const [accountUsername, setAccountUsername] = useState("");
  const [accountPassword, setAccountPassword] = useState("");
  const [breezeAppKey, setBreezeAppKey] = useState("");
  const [breezeSecretKey, setBreezeSecretKey] = useState("");
  const [sessionKey, setSessionKey] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isCommandRunning, setIsCommandRunning] = useState(false);
  const [isSetupSubmitting, setIsSetupSubmitting] = useState(false);
  const [settingsDirty, setSettingsDirty] = useState(false);

  const validationErrors = useMemo(() => validateSettings(settings), [settings]);
  const canStartAutopilot =
    connectionState === "online" && validationErrors.length === 0 && setupStatus?.setupComplete === true;
  const sessionState = setupStatus?.sessionStatus ?? dashboard.sessionStatus;

  const loadDashboard = useCallback(
    async (url = savedBackendUrl, token = authToken) => {
      if (!url) {
        return;
      }

      const setupResult = await api.getSetupStatus(url, token);
      if (setupResult.error || !setupResult.data) {
        setConnectionState("offline");
        setApiError(setupResult.error);
        return;
      }

      const status = setupResult.data;
      setSetupStatus(status);
      setConnectionState("online");
      setApiError(null);

      if (!status.setupComplete) {
        setDashboard((current) => ({
          ...current,
          sessionStatus: status.sessionStatus
        }));
        return;
      }

      const result = await api.getDashboard(url, token);
      if (result.error || !result.data) {
        setConnectionState("offline");
        setApiError(result.error);
        return;
      }

      setDashboard(result.data);
      setOpenTrades(result.data.openTrades ?? []);
      setLatestExplanation(result.data.latestExplanation);
      setConnectionState("online");
      setApiError(null);
    },
    [authToken, savedBackendUrl]
  );

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      const preferences = await loadPreferences();
      if (cancelled) {
        return;
      }

      setBackendUrl(preferences.backendUrl);
      setSavedBackendUrl(preferences.backendUrl);
      setAuthToken(preferences.authToken);
      setActiveTab(preferences.lastTab);
      setSettings(normalizeSettings(preferences.draftSettings ?? DEFAULT_SETTINGS));
    }

    boot();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!savedBackendUrl) {
      return;
    }

    void loadDashboard(savedBackendUrl);
    const timer = window.setInterval(() => {
      void loadDashboard(savedBackendUrl);
    }, 5000);

    return () => window.clearInterval(timer);
  }, [loadDashboard, savedBackendUrl, authToken]);

  useEffect(() => {
    if (!savedBackendUrl || connectionState !== "online") {
      return;
    }
    if (setupStatus?.accountExists && !setupStatus.loggedIn) {
      return;
    }

    async function loadSecondaryData() {
      const [
        settingsResult,
        openResult,
        historyResult,
        explanationResult,
        scannerResult,
        strategiesResult,
        reportResult,
        backtestsResult,
        liveOrdersResult,
        liveStatusResult,
        liveReadinessResult,
        agentStatusResult,
        agentDecisionsResult,
        automationStatusResult,
        automationEventsResult,
        paperValidationResult,
        improvementResult,
        improvementStatusResult,
        improvementReviewsResult,
        improvementLessonsResult,
        versionsResult,
        championResult,
        championRolloutResult,
        safetyResult,
        auditResult
      ] = await Promise.all([
        api.getSettings(savedBackendUrl, authToken),
        api.getOpenTrades(savedBackendUrl, authToken),
        api.getTradeHistory(savedBackendUrl, authToken),
        api.getLatestExplanation(savedBackendUrl, authToken),
        api.getScannerLatest(savedBackendUrl, authToken),
        api.getStrategies(savedBackendUrl, authToken),
        api.getDailyReport(savedBackendUrl, authToken),
        api.getBacktests(savedBackendUrl, authToken),
        api.getLiveOrders(savedBackendUrl, authToken),
        api.getLiveAutopilotStatus(savedBackendUrl, authToken),
        api.getLiveReadiness(savedBackendUrl, authToken),
        api.getAgentStatus(savedBackendUrl, authToken),
        api.getAgentDecisions(savedBackendUrl, authToken),
        api.getAutomationStatus(savedBackendUrl, authToken),
        api.getAutomationEvents(savedBackendUrl, authToken),
        api.getPaperValidation(savedBackendUrl, authToken),
        api.getImprovementRuns(savedBackendUrl, authToken),
        api.getImprovementStatus(savedBackendUrl, authToken),
        api.getImprovementReviews(savedBackendUrl, authToken),
        api.getImprovementLessons(savedBackendUrl, authToken),
        api.getStrategyVersions(savedBackendUrl, authToken),
        api.getChampion(savedBackendUrl, authToken),
        api.getChampionRollout(savedBackendUrl, authToken),
        api.getSafetyStatus(savedBackendUrl, authToken),
        api.getAudit(savedBackendUrl, authToken)
      ]);

      if (settingsResult.data && !settingsDirty) {
        setSettings(normalizeSettings(settingsResult.data));
      }
      if (openResult.data) {
        setOpenTrades(openResult.data);
      }
      if (historyResult.data) {
        setTradeHistory(historyResult.data);
      }
      if (explanationResult.data) {
        setLatestExplanation(explanationResult.data);
      }
      if (scannerResult.data) {
        setScannerResult(scannerResult.data);
      }
      if (strategiesResult.data) {
        setStrategies(strategiesResult.data);
      }
      if (reportResult.data) {
        setDailyReport(reportResult.data);
      }
      if (backtestsResult.data) {
        setBacktests(backtestsResult.data);
        const latestStrategy = backtestsResult.data[0]?.strategy ?? "VWAP pullback";
        const eligibility = await api.getStrategyEligibility(savedBackendUrl, latestStrategy, authToken);
        if (eligibility.data) {
          setStrategyEligibility(eligibility.data);
        }
      }
      if (liveOrdersResult.data) {
        setLiveOrders(liveOrdersResult.data);
      }
      if (liveStatusResult.data) {
        setLiveAutopilotStatus(liveStatusResult.data);
      }
      if (liveReadinessResult.data) {
        setLiveReadiness(liveReadinessResult.data);
      }
      if (agentStatusResult.data) {
        setAgentStatus(agentStatusResult.data);
      }
      if (agentDecisionsResult.data) {
        setAgentDecisions(agentDecisionsResult.data);
      }
      if (automationStatusResult.data) {
        setAutomationStatus(automationStatusResult.data);
      }
      if (automationEventsResult.data) {
        setAutomationEvents(automationEventsResult.data);
      }
      if (paperValidationResult.data) {
        setPaperValidation(paperValidationResult.data);
      }
      if (improvementResult.data) {
        setImprovementRuns(improvementResult.data);
      }
      if (improvementStatusResult.data) {
        setImprovementStatus(improvementStatusResult.data);
      }
      if (improvementReviewsResult.data) {
        setImprovementReviews(improvementReviewsResult.data);
      }
      if (improvementLessonsResult.data) {
        setImprovementLessons(improvementLessonsResult.data);
      }
      if (versionsResult.data) {
        setStrategyVersions(versionsResult.data);
      }
      if (championResult.data) {
        setChampionState(championResult.data);
      }
      if (championRolloutResult.data) {
        setChampionRollout(championRolloutResult.data);
      }
      if (safetyResult.data) {
        setSafetyStatus(safetyResult.data);
      }
      if (auditResult.data) {
        setAuditEvents(auditResult.data);
      }
    }

    void loadSecondaryData();
  }, [authToken, connectionState, savedBackendUrl, setupStatus, settingsDirty]);

  function updateSettings(patch: Partial<TradingSettings>) {
    setSettingsDirty(true);
    setSettings((current) => {
      const next = normalizeSettings({ ...current, ...patch });
      void saveDraftSettings(next);
      return next;
    });
  }

  async function handleBackendUrlSave() {
    const nextUrl = backendUrl.trim().replace(/\/+$/, "");
    if (!nextUrl) {
      setApiError("Backend URL is required.");
      return;
    }

    await saveBackendUrl(nextUrl);
    setSavedBackendUrl(nextUrl);
    setNotice("Backend URL saved.");
    setConnectionState("checking");
    await loadDashboard(nextUrl);
  }

  async function handleTabChange(tab: AppTab) {
    setActiveTab(tab);
    await saveLastTab(tab);
  }

  async function handleSaveSettings() {
    const normalized = normalizeSettings(settings);
    const errors = validateSettings(normalized);
    if (errors.length > 0) {
      setApiError(errors[0]);
      return;
    }

    setIsSaving(true);
    setApiError(null);
    const result = await api.saveSettings(savedBackendUrl, normalized, authToken);
    setIsSaving(false);

    if (result.error) {
      setApiError(result.error);
      return;
    }

    setSettings(result.data ? normalizeSettings(result.data) : normalized);
    setSettingsDirty(false);
    await saveDraftSettings(result.data ? normalizeSettings(result.data) : normalized);
    setNotice("Settings saved.");
    await loadDashboard(savedBackendUrl);
  }

  async function handleAutopilotToggle() {
    if (dashboard.autopilotEnabled) {
      await runCommand("Autopilot stopped.", () => api.stopAutopilot(savedBackendUrl, authToken));
      return;
    }

    if (!canStartAutopilot) {
      setApiError(validationErrors[0] ?? "Complete setup before starting autopilot.");
      return;
    }

    await runCommand("Autopilot started.", () => api.startAutopilot(savedBackendUrl, authToken));
  }

  async function handleEmergencyExit() {
    const confirmed = window.confirm(
      "Send emergency exit to the BreezePilot backend? This will stop autopilot and trigger backend safety rules."
    );
    if (!confirmed) {
      return;
    }

    await runCommand("Emergency exit sent.", () => api.emergencyExit(savedBackendUrl, authToken));
  }

  async function handleRunScanner() {
    setIsCommandRunning(true);
    setApiError(null);
    const result = await api.runScanner(savedBackendUrl, authToken);
    setIsCommandRunning(false);

    if (result.error || !result.data) {
      setApiError(result.error);
      return;
    }

    setScannerResult(result.data);
    setNotice("Scanner completed.");
  }

  async function handleRunPaperOnce() {
    await runCommand("Paper run completed.", () => api.runPaperOnce(savedBackendUrl, authToken));
  }

  async function handleMonitorPaper() {
    setIsCommandRunning(true);
    setApiError(null);
    const result = await api.monitorPaper(savedBackendUrl, authToken);
    setIsCommandRunning(false);

    if (result.error || !result.data) {
      setApiError(result.error);
      return;
    }

    setOpenTrades(result.data);
    setNotice("Paper trades monitored.");
    await loadDashboard(savedBackendUrl);
  }

  async function handlePaperExit(tradeId: string) {
    await runCommand("Paper trade exited.", () => api.paperExit(savedBackendUrl, tradeId, authToken));
  }

  async function handleRunBacktest(strategyName?: string) {
    const strategy = strategyName ?? strategies[0]?.name ?? "VWAP pullback";
    const stockCode = defaultStockCode(settings);
    setIsCommandRunning(true);
    setApiError(null);
    const result = await api.runBacktest(savedBackendUrl, { strategy, stockCode }, authToken);
    setIsCommandRunning(false);

    if (result.error || !result.data) {
      setApiError(result.error);
      return;
    }

    setBacktests((current) => [result.data as BacktestRun, ...current.filter((run) => run.id !== result.data?.id)]);
    const eligibility = await api.getStrategyEligibility(savedBackendUrl, strategy, authToken);
    if (eligibility.data) {
      setStrategyEligibility(eligibility.data);
    }
    setNotice(result.data.passed ? "Backtest passed gates." : "Backtest completed with failed gates.");
  }

  async function handlePrepareLiveOrder() {
    setIsCommandRunning(true);
    setApiError(null);
    const result = await api.prepareLiveOrder(
      savedBackendUrl,
      {
        stockCode: defaultStockCode(settings),
        strategy: strategies[0]?.name ?? "VWAP pullback",
        side: "BUY"
      },
      authToken
    );
    setIsCommandRunning(false);

    if (result.error || !result.data) {
      setApiError(result.error);
      return;
    }

    setLiveOrders((current) => [result.data as LiveOrder, ...current.filter((order) => order.id !== result.data?.id)]);
    setNotice("Live order prepared for manual confirmation.");
  }

  async function handleLiveOrderAction(
    orderId: string,
    action: "confirm" | "cancel" | "square-off" | "refresh"
  ) {
    const labels = {
      confirm: "Confirm this live order and send it to Breeze?",
      cancel: "Cancel this live order?",
      "square-off": "Send limit square-off for this live order?",
      refresh: "Refresh this order status from Breeze?"
    };
    if (!window.confirm(labels[action])) {
      return;
    }

    setIsCommandRunning(true);
    setApiError(null);
    const result =
      action === "confirm"
        ? await api.confirmLiveOrder(savedBackendUrl, orderId, authToken)
        : action === "cancel"
          ? await api.cancelLiveOrder(savedBackendUrl, orderId, authToken)
          : action === "refresh"
            ? await api.refreshLiveOrder(savedBackendUrl, orderId, authToken)
            : await api.squareOffLiveOrder(savedBackendUrl, orderId, authToken);
    setIsCommandRunning(false);

    if (result.error || !result.data) {
      setApiError(result.error);
      return;
    }

    setLiveOrders((current) =>
      current.map((order) => (order.id === orderId ? (result.data as LiveOrder) : order))
    );
    setNotice(`Live order ${action} completed.`);
  }

  async function handleLiveAutopilot(start: boolean) {
    await runCommand(start ? "Live autopilot started." : "Live autopilot stopped.", async () => {
      const result = start
        ? await api.startLiveAutopilot(savedBackendUrl, authToken)
        : await api.stopLiveAutopilot(savedBackendUrl, authToken);
      if (result.data) {
        setLiveAutopilotStatus(result.data);
      }
      return result;
    });
  }

  async function handleAgentAction(action: "analyze" | "paper" | "live" | "monitor") {
    setIsCommandRunning(true);
    setApiError(null);
    const result =
      action === "analyze"
        ? await api.agentAnalyze(savedBackendUrl, authToken)
        : action === "paper"
          ? await api.agentPaperCycle(savedBackendUrl, authToken)
          : action === "live"
            ? await api.agentLiveProposal(savedBackendUrl, authToken)
            : await api.agentMonitor(savedBackendUrl, authToken);
    setIsCommandRunning(false);

    if (result.error || !result.data) {
      setApiError(result.error);
      return;
    }

    setAgentDecisions((current) => [
      (result.data as AgentDecisionResponse).decision,
      ...current.filter((decision) => decision.id !== result.data?.decision.id)
    ]);
    if (result.data.liveOrder) {
      setLiveOrders((current) => [
        result.data!.liveOrder as LiveOrder,
        ...current.filter((order) => order.id !== result.data?.liveOrder?.id)
      ]);
    }
    setLatestExplanation(result.data.explanation);
    setNotice(`Hermes decision: ${result.data.decision.action}.`);
    await loadDashboard(savedBackendUrl);
  }

  async function handleAutomationAction(action: "start" | "stop" | "run-once") {
    if (action === "start") {
      await runCommand("Automation started.", () => api.startAutomation(savedBackendUrl, authToken));
    } else if (action === "stop") {
      await runCommand("Automation stopped.", () => api.stopAutomation(savedBackendUrl, authToken));
    } else {
      await runCommand(
        "Automation cycle completed.",
        () => api.runAutomationOnce(savedBackendUrl, authToken),
        (data) => {
          if (data?.summary) {
            setNotice(data.summary);
          }
        }
      );
    }
    const [statusResult, eventsResult, validationResult] = await Promise.all([
      api.getAutomationStatus(savedBackendUrl, authToken),
      api.getAutomationEvents(savedBackendUrl, authToken),
      api.getPaperValidation(savedBackendUrl, authToken)
    ]);
    if (statusResult.data) {
      setAutomationStatus(statusResult.data);
    }
    if (eventsResult.data) {
      setAutomationEvents(eventsResult.data);
    }
    if (validationResult.data) {
      setPaperValidation(validationResult.data);
    }
  }

  async function handleRunImprovement() {
    setIsCommandRunning(true);
    setApiError(null);
    const result = await api.runImprovement(savedBackendUrl, authToken);
    setIsCommandRunning(false);

    if (result.error || !result.data) {
      setApiError(result.error);
      return;
    }

    setImprovementRuns((current) => [result.data as ImprovementRun, ...current]);
    const [
      versionsResult,
      championResult,
      statusResult,
      reviewsResult,
      lessonsResult,
      rolloutResult
    ] = await Promise.all([
      api.getStrategyVersions(savedBackendUrl, authToken),
      api.getChampion(savedBackendUrl, authToken),
      api.getImprovementStatus(savedBackendUrl, authToken),
      api.getImprovementReviews(savedBackendUrl, authToken),
      api.getImprovementLessons(savedBackendUrl, authToken),
      api.getChampionRollout(savedBackendUrl, authToken)
    ]);
    if (versionsResult.data) {
      setStrategyVersions(versionsResult.data);
    }
    if (championResult.data) {
      setChampionState(championResult.data);
    }
    if (statusResult.data) {
      setImprovementStatus(statusResult.data);
    }
    if (reviewsResult.data) {
      setImprovementReviews(reviewsResult.data);
    }
    if (lessonsResult.data) {
      setImprovementLessons(lessonsResult.data);
    }
    if (rolloutResult.data) {
      setChampionRollout(rolloutResult.data);
    }
    setNotice(result.data.reason);
  }

  async function handlePromoteChallenger(versionId: string) {
    if (!window.confirm("Promote this challenger to champion?")) {
      return;
    }
    await runCommand("Challenger promoted.", async () => {
      const result = await api.promoteChallenger(savedBackendUrl, versionId, authToken);
      const championResult = await api.getChampion(savedBackendUrl, authToken);
      if (championResult.data) {
        setChampionState(championResult.data);
      }
      return result;
    });
  }

  async function handleRollbackChampion() {
    if (!window.confirm("Rollback to the previous champion?")) {
      return;
    }
    await runCommand("Champion rolled back.", async () => {
      const result = await api.rollbackChampion(savedBackendUrl, authToken);
      const championResult = await api.getChampion(savedBackendUrl, authToken);
      if (championResult.data) {
        setChampionState(championResult.data);
      }
      return result;
    });
  }

  async function handleKillSwitch() {
    if (!window.confirm("Activate the backend kill switch? This blocks live trading.")) {
      return;
    }
    await runCommand("Kill switch activated.", async () => {
      const result = await api.activateKillSwitch(savedBackendUrl, authToken);
      if (result.data) {
        setSafetyStatus(result.data);
      }
      return result;
    });
  }

  async function handleSendDailyReport() {
    await runCommand("Daily report generated.", () => api.sendDailyReport(savedBackendUrl, authToken));
    const auditResult = await api.getAudit(savedBackendUrl, authToken);
    if (auditResult.data) {
      setAuditEvents(auditResult.data);
    }
  }

  async function handleAccountSubmit(kind: "register" | "login") {
    const username = accountUsername.trim();
    if (!username || accountPassword.length < 8) {
      setApiError("Username is required and password must be at least 8 characters.");
      return;
    }

    setIsSetupSubmitting(true);
    setApiError(null);
    const result =
      kind === "register"
        ? await api.register(savedBackendUrl, username, accountPassword)
        : await api.login(savedBackendUrl, username, accountPassword);
    setIsSetupSubmitting(false);

    if (result.error || !result.data) {
      setApiError(result.error);
      return;
    }

    setAuthToken(result.data.token);
    await saveAuthToken(result.data.token);
    setAccountPassword("");
    setNotice(kind === "register" ? "Local account created." : "Logged in.");
    await loadDashboard(savedBackendUrl, result.data.token);
  }

  async function handleLogout() {
    await api.logout(savedBackendUrl, authToken);
    setAuthToken(undefined);
    await clearAuthToken();
    setSetupStatus((current) => (current ? { ...current, loggedIn: false, setupComplete: false, nextStep: "login" } : current));
    setNotice("Logged out.");
  }

  async function handleSaveCredentials() {
    if (!breezeAppKey.trim() || !breezeSecretKey.trim()) {
      setApiError("Breeze AppKey and Secret Key are required.");
      return;
    }

    setIsSetupSubmitting(true);
    setApiError(null);
    const result = await api.saveBreezeCredentials(
      savedBackendUrl,
      { appKey: breezeAppKey, secretKey: breezeSecretKey },
      authToken
    );
    setIsSetupSubmitting(false);

    if (result.error) {
      setApiError(result.error);
      return;
    }

    setBreezeAppKey("");
    setBreezeSecretKey("");
    setNotice("Breeze credentials saved on backend.");
    await loadDashboard(savedBackendUrl);
  }

  async function handleSubmitSession() {
    if (!sessionKey.trim()) {
      setApiError("Daily Breeze session key is required.");
      return;
    }

    setIsSetupSubmitting(true);
    setApiError(null);
    const result = await api.submitSession(savedBackendUrl, sessionKey.trim(), authToken);
    setIsSetupSubmitting(false);

    if (result.error) {
      setApiError(result.error);
      return;
    }

    setSessionKey("");
    setNotice("Daily Breeze session is active.");
    await loadDashboard(savedBackendUrl);
  }

  async function runCommand<T>(
    message: string,
    command: () => Promise<{ error: string | null; data?: T | null }>,
    onSuccess?: (data: T | null | undefined) => void
  ) {
    setIsCommandRunning(true);
    setApiError(null);
    let result: { error: string | null; data?: T | null };
    try {
      result = await command();
    } catch {
      setApiError("Command failed unexpectedly. Check backend status and try again.");
      return;
    } finally {
      setIsCommandRunning(false);
    }

    if (result.error) {
      setApiError(result.error);
      return;
    }

    if (onSuccess) {
      onSuccess(result.data);
    } else {
      setNotice(message);
    }
    await loadDashboard(savedBackendUrl);
  }

  function addSymbol() {
    const symbol = normalizeSymbol(symbolInput);
    if (!symbol) {
      return;
    }

    updateSettings({
      stockPreset: "CUSTOM",
      allowedStocks: Array.from(new Set([...settings.allowedStocks, symbol]))
    });
    setSymbolInput("");
  }

  function removeSymbol(symbol: string) {
    updateSettings({
      allowedStocks: settings.allowedStocks.filter((item) => item !== symbol)
    });
  }

  return (
    <main className="app-shell">
      <header className="top-bar">
        <div>
          <p className="eyebrow">ICICI Direct control panel</p>
          <h1>BreezePilot</h1>
        </div>
        <StatusPill state={connectionState} session={sessionState} />
      </header>

      <section className="backend-row" aria-label="Backend connection settings">
        <label htmlFor="backendUrl">Backend API</label>
        <input
          id="backendUrl"
          value={backendUrl}
          onChange={(event) => setBackendUrl(event.target.value)}
          placeholder="http://127.0.0.1:8000"
        />
        <button type="button" className="secondary-button" onClick={handleBackendUrlSave}>
          Save
        </button>
      </section>

      {sessionState !== "active" && (
        <div className="warning-banner">
          ICICI Breeze session is {sessionState}. Generate the daily session before live
          trading.
        </div>
      )}

      {(notice || apiError) && (
        <div className={apiError ? "message error" : "message success"}>{apiError ?? notice}</div>
      )}

      <section className="control-strip" aria-label="Main trading controls">
        <div>
          <span className="label">Autopilot</span>
          <strong>{dashboard.autopilotEnabled ? "ON" : "OFF"}</strong>
        </div>
        <button
          type="button"
          className={dashboard.autopilotEnabled ? "secondary-button" : "primary-button"}
          onClick={handleAutopilotToggle}
          disabled={isCommandRunning || (!dashboard.autopilotEnabled && !canStartAutopilot)}
        >
          {dashboard.autopilotEnabled ? "Turn Off" : "Turn On"}
        </button>
        <button
          type="button"
          className="danger-button"
          onClick={handleEmergencyExit}
          disabled={
            isCommandRunning ||
            !savedBackendUrl ||
            (setupStatus?.accountExists === true && setupStatus.loggedIn === false)
          }
        >
          Emergency Exit
        </button>
      </section>

      {connectionState !== "online" || setupStatus?.setupComplete !== true ? (
        <SetupWizard
          connectionState={connectionState}
          setupStatus={setupStatus}
          username={accountUsername}
          password={accountPassword}
          breezeAppKey={breezeAppKey}
          breezeSecretKey={breezeSecretKey}
          sessionKey={sessionKey}
          settings={settings}
          validationErrors={validationErrors}
          isSaving={isSaving}
          isSubmitting={isSetupSubmitting}
          symbolInput={symbolInput}
          setUsername={setAccountUsername}
          setPassword={setAccountPassword}
          setBreezeAppKey={setBreezeAppKey}
          setBreezeSecretKey={setBreezeSecretKey}
          setSessionKey={setSessionKey}
          setSymbolInput={setSymbolInput}
          updateSettings={updateSettings}
          saveSettings={() => void handleSaveSettings()}
          addSymbol={addSymbol}
          removeSymbol={removeSymbol}
          saveBackendUrl={() => void handleBackendUrlSave()}
          submitAccount={(kind) => void handleAccountSubmit(kind)}
          saveCredentials={() => void handleSaveCredentials()}
          submitSession={() => void handleSubmitSession()}
          logout={() => void handleLogout()}
          startAutopilot={() => void handleAutopilotToggle()}
          canStartAutopilot={canStartAutopilot}
        />
      ) : (
        <>
          <nav className="tabs" aria-label="BreezePilot sections">
            <TabButton active={activeTab === "dashboard"} onClick={() => void handleTabChange("dashboard")}>
              Dashboard
            </TabButton>
            <TabButton active={activeTab === "agent"} onClick={() => void handleTabChange("agent")}>
              Agent
            </TabButton>
            <TabButton active={activeTab === "scanner"} onClick={() => void handleTabChange("scanner")}>
              Scanner
            </TabButton>
            <TabButton active={activeTab === "backtests"} onClick={() => void handleTabChange("backtests")}>
              Backtests
            </TabButton>
            <TabButton active={activeTab === "live"} onClick={() => void handleTabChange("live")}>
              Live
            </TabButton>
            <TabButton active={activeTab === "lab"} onClick={() => void handleTabChange("lab")}>
              Strategy Lab
            </TabButton>
            <TabButton active={activeTab === "safety"} onClick={() => void handleTabChange("safety")}>
              Safety
            </TabButton>
            <TabButton active={activeTab === "trades"} onClick={() => void handleTabChange("trades")}>
              Trades
            </TabButton>
            <TabButton
              active={activeTab === "explanation"}
              onClick={() => void handleTabChange("explanation")}
            >
              Explanation
            </TabButton>
          </nav>

          {activeTab === "dashboard" && (
            <DashboardTab
              dashboard={dashboard}
              settings={settings}
              validationErrors={validationErrors}
              isSaving={isSaving}
              symbolInput={symbolInput}
              setSymbolInput={setSymbolInput}
              updateSettings={updateSettings}
              saveSettings={() => void handleSaveSettings()}
              addSymbol={addSymbol}
              removeSymbol={removeSymbol}
            />
          )}

          {activeTab === "agent" && (
            <AgentTab
              agentStatus={agentStatus}
              agentDecisions={agentDecisions}
              automationStatus={automationStatus}
              automationEvents={automationEvents}
              paperValidation={paperValidation}
              isCommandRunning={isCommandRunning}
              analyze={() => void handleAgentAction("analyze")}
              paperCycle={() => void handleAgentAction("paper")}
              liveProposal={() => void handleAgentAction("live")}
              monitor={() => void handleAgentAction("monitor")}
              automationAction={(action) => void handleAutomationAction(action)}
            />
          )}

          {activeTab === "scanner" && (
            <ScannerTab
              scannerResult={scannerResult}
              strategies={strategies}
              dailyReport={dailyReport}
              isCommandRunning={isCommandRunning}
              runScanner={() => void handleRunScanner()}
              runPaperOnce={() => void handleRunPaperOnce()}
              monitorPaper={() => void handleMonitorPaper()}
            />
          )}

          {activeTab === "backtests" && (
            <BacktestsTab
              backtests={backtests}
              strategies={strategies}
              eligibility={strategyEligibility}
              isCommandRunning={isCommandRunning}
              runBacktest={(strategy) => void handleRunBacktest(strategy)}
            />
          )}

          {activeTab === "live" && (
            <LiveOrdersTab
              liveOrders={liveOrders}
              liveAutopilotStatus={liveAutopilotStatus}
              liveReadiness={liveReadiness}
              isCommandRunning={isCommandRunning}
              prepareLiveOrder={() => void handlePrepareLiveOrder()}
              confirmOrder={(orderId) => void handleLiveOrderAction(orderId, "confirm")}
              cancelOrder={(orderId) => void handleLiveOrderAction(orderId, "cancel")}
              refreshOrder={(orderId) => void handleLiveOrderAction(orderId, "refresh")}
              squareOffOrder={(orderId) => void handleLiveOrderAction(orderId, "square-off")}
              startLiveAutopilot={() => void handleLiveAutopilot(true)}
              stopLiveAutopilot={() => void handleLiveAutopilot(false)}
            />
          )}

          {activeTab === "lab" && (
            <StrategyLabTab
              improvementRuns={improvementRuns}
              improvementStatus={improvementStatus}
              improvementReviews={improvementReviews}
              improvementLessons={improvementLessons}
              strategyVersions={strategyVersions}
              championState={championState}
              championRollout={championRollout}
              isCommandRunning={isCommandRunning}
              runImprovement={() => void handleRunImprovement()}
              promoteChallenger={(versionId) => void handlePromoteChallenger(versionId)}
              rollbackChampion={() => void handleRollbackChampion()}
            />
          )}

          {activeTab === "safety" && (
            <SafetyTab
              safetyStatus={safetyStatus}
              automationStatus={automationStatus}
              paperValidation={paperValidation}
              automationEvents={automationEvents}
              auditEvents={auditEvents}
              isCommandRunning={isCommandRunning}
              activateKillSwitch={() => void handleKillSwitch()}
              sendDailyReport={() => void handleSendDailyReport()}
            />
          )}

          {activeTab === "trades" && (
            <TradesTab
              openTrades={openTrades}
              tradeHistory={tradeHistory}
              exitPaperTrade={(tradeId) => void handlePaperExit(tradeId)}
            />
          )}

          {activeTab === "explanation" && (
            <ExplanationTab explanation={latestExplanation ?? dashboard.latestExplanation} />
          )}
        </>
      )}
    </main>
  );
}

interface StatusPillProps {
  state: ConnectionState;
  session: string;
}

function StatusPill({ state, session }: StatusPillProps) {
  return (
    <div className="status-group" aria-label="Connection and session status">
      <span className={`status-pill ${state}`}>{state}</span>
      <span className={`status-pill session-${session}`}>session {session}</span>
    </div>
  );
}

interface TabButtonProps {
  active: boolean;
  children: string;
  onClick: () => void;
}

function TabButton({ active, children, onClick }: TabButtonProps) {
  return (
    <button type="button" className={active ? "tab active" : "tab"} onClick={onClick}>
      {children}
    </button>
  );
}

interface SetupWizardProps {
  connectionState: ConnectionState;
  setupStatus: SetupStatus | null;
  username: string;
  password: string;
  breezeAppKey: string;
  breezeSecretKey: string;
  sessionKey: string;
  settings: TradingSettings;
  validationErrors: string[];
  isSaving: boolean;
  isSubmitting: boolean;
  symbolInput: string;
  setUsername: (value: string) => void;
  setPassword: (value: string) => void;
  setBreezeAppKey: (value: string) => void;
  setBreezeSecretKey: (value: string) => void;
  setSessionKey: (value: string) => void;
  setSymbolInput: (value: string) => void;
  updateSettings: (patch: Partial<TradingSettings>) => void;
  saveSettings: () => void;
  addSymbol: () => void;
  removeSymbol: (symbol: string) => void;
  saveBackendUrl: () => void;
  submitAccount: (kind: "register" | "login") => void;
  saveCredentials: () => void;
  submitSession: () => void;
  logout: () => void;
  startAutopilot: () => void;
  canStartAutopilot: boolean;
}

function SetupWizard({
  connectionState,
  setupStatus,
  username,
  password,
  breezeAppKey,
  breezeSecretKey,
  sessionKey,
  settings,
  validationErrors,
  isSaving,
  isSubmitting,
  symbolInput,
  setUsername,
  setPassword,
  setBreezeAppKey,
  setBreezeSecretKey,
  setSessionKey,
  setSymbolInput,
  updateSettings,
  saveSettings,
  addSymbol,
  removeSymbol,
  saveBackendUrl,
  submitAccount,
  saveCredentials,
  submitSession,
  logout,
  startAutopilot,
  canStartAutopilot
}: SetupWizardProps) {
  const step = connectionState !== "online" ? "backend" : setupStatus?.nextStep ?? "backend";
  const accountMode: "register" | "login" = step === "login" ? "login" : "register";

  return (
    <section className="setup-shell" aria-label="BreezePilot setup">
      <div className="setup-steps">
        {["backend", "account", "credentials", "session", "rules", "ready"].map((item) => (
          <span key={item} className={item === step ? "current" : ""}>
            {item}
          </span>
        ))}
      </div>

      {step === "backend" && (
        <section className="panel setup-panel">
          <h2>Connect Backend</h2>
          <p className="muted">Backend is offline or not saved.</p>
          <button type="button" className="primary-button" onClick={saveBackendUrl}>
            Check Backend
          </button>
        </section>
      )}

      {(step === "account" || step === "login") && (
        <section className="panel setup-panel">
          <div className="panel-heading">
            <h2>{accountMode === "register" ? "Create Account" : "Login"}</h2>
            {setupStatus?.loggedIn && (
              <button type="button" className="secondary-button small" onClick={logout}>
                Logout
              </button>
            )}
          </div>
          <label className="text-field">
            <span>Username</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)} />
          </label>
          <label className="text-field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="primary-button"
            onClick={() => submitAccount(accountMode)}
            disabled={isSubmitting}
          >
            {accountMode === "register" ? "Create Account" : "Login"}
          </button>
        </section>
      )}

      {step === "credentials" && (
        <section className="panel setup-panel">
          <h2>Breeze Credentials</h2>
          <label className="text-field">
            <span>AppKey</span>
            <input value={breezeAppKey} onChange={(event) => setBreezeAppKey(event.target.value)} />
          </label>
          <label className="text-field">
            <span>Secret Key</span>
            <input
              type="password"
              value={breezeSecretKey}
              onChange={(event) => setBreezeSecretKey(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="primary-button"
            onClick={saveCredentials}
            disabled={isSubmitting}
          >
            Save Credentials
          </button>
        </section>
      )}

      {step === "session" && (
        <section className="panel setup-panel">
          <h2>Daily Session</h2>
          <p className="muted">Session status: {setupStatus?.sessionStatus ?? "unknown"}</p>
          <label className="text-field">
            <span>Session Key</span>
            <input
              type="password"
              value={sessionKey}
              onChange={(event) => setSessionKey(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="primary-button"
            onClick={submitSession}
            disabled={isSubmitting}
          >
            Submit Session
          </button>
        </section>
      )}

      {step === "rules" && (
        <SettingsPanel
          settings={settings}
          validationErrors={validationErrors}
          isSaving={isSaving}
          symbolInput={symbolInput}
          setSymbolInput={setSymbolInput}
          updateSettings={updateSettings}
          saveSettings={saveSettings}
          addSymbol={addSymbol}
          removeSymbol={removeSymbol}
        />
      )}

      {(step === "ready" || step === "locked") && (
        <section className="panel setup-panel">
          <h2>{step === "locked" ? "Emergency Locked" : "Ready"}</h2>
          <ul className="readiness-list">
            <li className={setupStatus?.accountExists ? "ok" : ""}>Account</li>
            <li className={setupStatus?.breezeCredentialsSaved ? "ok" : ""}>Breeze credentials</li>
            <li className={setupStatus?.sessionStatus === "active" ? "ok" : ""}>Daily session</li>
            <li className={setupStatus?.settingsValid ? "ok" : ""}>Trading rules</li>
          </ul>
          {step === "ready" && (
            <button
              type="button"
              className="primary-button"
              onClick={startAutopilot}
              disabled={!canStartAutopilot}
            >
              Turn On Autopilot
            </button>
          )}
        </section>
      )}
    </section>
  );
}

interface DashboardTabProps {
  dashboard: DashboardResponse;
  settings: TradingSettings;
  validationErrors: string[];
  isSaving: boolean;
  symbolInput: string;
  setSymbolInput: (value: string) => void;
  updateSettings: (patch: Partial<TradingSettings>) => void;
  saveSettings: () => void;
  addSymbol: () => void;
  removeSymbol: (symbol: string) => void;
}

function DashboardTab({
  dashboard,
  settings,
  validationErrors,
  isSaving,
  symbolInput,
  setSymbolInput,
  updateSettings,
  saveSettings,
  addSymbol,
  removeSymbol
}: DashboardTabProps) {
  return (
    <section className="tab-panel">
      <div className="metric-grid">
        <Metric label="Current P&L" value={formatMoney(dashboard.pnl.currentPnl)} tone={dashboard.pnl.currentPnl >= 0 ? "positive" : "negative"} />
        <Metric label="Open trades" value={String(dashboard.pnl.openTradesCount)} />
        <Metric label="Daily loss used" value={formatMoney(dashboard.pnl.dailyLossUsed)} tone="negative" />
        <Metric label="Remaining budget" value={formatMoney(dashboard.pnl.remainingBudget)} />
      </div>

      <SettingsPanel
        settings={settings}
        validationErrors={validationErrors}
        isSaving={isSaving}
        symbolInput={symbolInput}
        setSymbolInput={setSymbolInput}
        updateSettings={updateSettings}
        saveSettings={saveSettings}
        addSymbol={addSymbol}
        removeSymbol={removeSymbol}
      />

      <section className="panel">
        <h2>Risk Status</h2>
        <p className={`risk-line ${dashboard.riskStatus}`}>{dashboard.riskMessage}</p>
      </section>
    </section>
  );
}

interface SettingsPanelProps {
  settings: TradingSettings;
  validationErrors: string[];
  isSaving: boolean;
  symbolInput: string;
  setSymbolInput: (value: string) => void;
  updateSettings: (patch: Partial<TradingSettings>) => void;
  saveSettings: () => void;
  addSymbol: () => void;
  removeSymbol: (symbol: string) => void;
}

function SettingsPanel({
  settings,
  validationErrors,
  isSaving,
  symbolInput,
  setSymbolInput,
  updateSettings,
  saveSettings,
  addSymbol,
  removeSymbol
}: SettingsPanelProps) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>Risk Settings</h2>
        <button type="button" className="primary-button small" onClick={saveSettings} disabled={isSaving}>
          {isSaving ? "Saving" : "Save Settings"}
        </button>
      </div>

      {validationErrors.length > 0 && (
        <ul className="validation-list">
          {validationErrors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      )}

      <div className="form-grid">
        <NumberField
          label="Budget"
          value={settings.budget}
          onChange={(budget) => updateSettings({ budget })}
          prefix="₹"
        />
        <NumberField
          label="Stop-loss"
          value={settings.stopLossPercent}
          onChange={(stopLossPercent) => updateSettings({ stopLossPercent })}
          suffix="%"
        />
        <NumberField
          label="Target"
          value={settings.targetPercent}
          onChange={(targetPercent) => updateSettings({ targetPercent })}
          suffix="%"
        />
        <NumberField
          label="Daily max loss"
          value={settings.dailyMaxLoss}
          onChange={(dailyMaxLoss) => updateSettings({ dailyMaxLoss })}
          prefix="₹"
        />
        <NumberField
          label="Max trades"
          value={settings.maxTradesPerDay}
          onChange={(maxTradesPerDay) => updateSettings({ maxTradesPerDay })}
        />
      </div>

      <div className="segmented" aria-label="Trading mode">
        <button
          type="button"
          className={settings.mode === "intraday" ? "selected" : ""}
          onClick={() => updateSettings({ mode: "intraday" })}
        >
          Intraday
        </button>
        <button
          type="button"
          className={settings.mode === "delivery" ? "selected" : ""}
          onClick={() => updateSettings({ mode: "delivery" })}
        >
          Delivery
        </button>
      </div>

      <section className="stock-box" aria-label="Allowed stocks">
        <div className="panel-heading compact">
          <h3>Allowed Stocks</h3>
          <div className="segmented compact-control">
            <button
              type="button"
              className={settings.stockPreset === "NIFTY 50" ? "selected" : ""}
              onClick={() => updateSettings({ stockPreset: "NIFTY 50" })}
            >
              NIFTY 50
            </button>
            <button
              type="button"
              className={settings.stockPreset === "CUSTOM" ? "selected" : ""}
              onClick={() => updateSettings({ stockPreset: "CUSTOM" })}
            >
              Custom
            </button>
          </div>
        </div>

        <div className="symbol-row">
          <input
            value={symbolInput}
            onChange={(event) => setSymbolInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                addSymbol();
              }
            }}
            placeholder="Add symbol, e.g. HDFCBANK"
          />
          <button type="button" className="secondary-button" onClick={addSymbol}>
            Add
          </button>
        </div>

        <div className="chips" aria-label="Custom allowed stock list">
          {settings.allowedStocks.length === 0 ? (
            <span className="empty-text">No custom symbols added.</span>
          ) : (
            settings.allowedStocks.map((symbol) => (
              <button
                type="button"
                className="chip"
                key={symbol}
                onClick={() => removeSymbol(symbol)}
                title={`Remove ${symbol}`}
              >
                {symbol} ×
              </button>
            ))
          )}
        </div>
      </section>
    </section>
  );
}

interface NumberFieldProps {
  label: string;
  value: number;
  onChange: (value: number) => void;
  prefix?: string;
  suffix?: string;
}

function NumberField({ label, value, onChange, prefix, suffix }: NumberFieldProps) {
  return (
    <label className="number-field">
      <span>{label}</span>
      <div className="affixed-input">
        {prefix && <span>{prefix}</span>}
        <input
          type="number"
          min="0"
          value={Number.isFinite(value) ? value : ""}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        {suffix && <span>{suffix}</span>}
      </div>
    </label>
  );
}

interface MetricProps {
  label: string;
  value: string;
  tone?: "positive" | "negative";
}

function Metric({ label, value, tone }: MetricProps) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={tone ?? ""}>{value}</strong>
    </div>
  );
}

function AgentTab({
  agentStatus,
  agentDecisions,
  automationStatus,
  automationEvents,
  paperValidation,
  isCommandRunning,
  analyze,
  paperCycle,
  liveProposal,
  monitor,
  automationAction
}: {
  agentStatus: AgentStatus | null;
  agentDecisions: AgentDecision[];
  automationStatus: AutomationStatus | null;
  automationEvents: AutomationEvent[];
  paperValidation: PaperValidationStatus | null;
  isCommandRunning: boolean;
  analyze: () => void;
  paperCycle: () => void;
  liveProposal: () => void;
  monitor: () => void;
  automationAction: (action: "start" | "stop" | "run-once") => void;
}) {
  const latest = agentDecisions[0];
  const latestAutomationEvent = automationEvents[0];

  return (
    <section className="tab-panel">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Hermes Agent</h2>
            <p className="muted">{agentStatus?.message ?? "Agent status not loaded."}</p>
          </div>
          <div className="action-row">
            <button type="button" className="secondary-button small" onClick={monitor} disabled={isCommandRunning}>
              Monitor
            </button>
            <button type="button" className="secondary-button small" onClick={paperCycle} disabled={isCommandRunning}>
              Paper
            </button>
            <button type="button" className="secondary-button small" onClick={liveProposal} disabled={isCommandRunning}>
              Live Proposal
            </button>
            <button type="button" className="primary-button small" onClick={analyze} disabled={isCommandRunning}>
              Analyze
            </button>
          </div>
        </div>
        <div className="metric-grid">
          <Metric label="Enabled" value={agentStatus?.enabled ? "yes" : "no"} tone={agentStatus?.enabled ? "positive" : "negative"} />
          <Metric label="Provider" value={agentStatus?.provider ?? "-"} />
          <Metric label="Model" value={agentStatus?.model ?? "-"} />
          <Metric label="API key" value={agentStatus?.apiKeyConfigured ? "configured" : "missing"} tone={agentStatus?.apiKeyConfigured ? "positive" : "negative"} />
          <Metric label="Mode" value={agentStatus?.tradingMode ?? "-"} />
          <Metric
            label="Agent health"
            value={agentStatus?.healthy === undefined ? "unknown" : agentStatus.healthy ? "healthy" : "unhealthy"}
            tone={agentStatus?.healthy === undefined ? undefined : agentStatus.healthy ? "positive" : "negative"}
          />
          <Metric label="System errors" value={String(agentStatus?.consecutiveSystemErrors ?? 0)} tone={(agentStatus?.consecutiveSystemErrors ?? 0) > 0 ? "negative" : "positive"} />
          <Metric label="Last valid" value={agentStatus?.lastValidDecisionAt ? formatDate(agentStatus.lastValidDecisionAt) : "-"} />
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Automation</h2>
            <p className="muted">{automationStatus?.message ?? "Automation status not loaded."}</p>
          </div>
          <div className="action-row">
            <button type="button" className="secondary-button small" onClick={() => automationAction("run-once")} disabled={isCommandRunning}>
              Run Once
            </button>
            <button type="button" className="secondary-button small" onClick={() => automationAction("stop")} disabled={isCommandRunning || automationStatus?.enabled !== true}>
              Stop
            </button>
            <button type="button" className="primary-button small" onClick={() => automationAction("start")} disabled={isCommandRunning || automationStatus?.enabled === true}>
              Start
            </button>
          </div>
        </div>
        <div className="metric-grid">
          <Metric label="Scheduled" value={automationStatus?.enabled ? "ON" : "OFF"} tone={automationStatus?.enabled ? "positive" : "negative"} />
          <Metric label="Master switch" value={automationStatus?.configEnabled ? "enabled" : "disabled"} tone={automationStatus?.configEnabled ? "positive" : "negative"} />
          <Metric label="Live entries" value={automationStatus?.autoLiveEntriesEnabled ? "enabled" : "off"} tone={automationStatus?.autoLiveEntriesEnabled ? "positive" : "negative"} />
          <Metric label="Live exits" value={automationStatus?.autoLiveExitsEnabled ? "enabled" : "off"} tone={automationStatus?.autoLiveExitsEnabled ? "positive" : "negative"} />
          <Metric
            label="Broker health"
            value={automationStatus?.brokerHealth ?? "unknown"}
            tone={
              automationStatus?.brokerHealth === "healthy"
                ? "positive"
                : automationStatus?.brokerHealth === "unavailable"
                  ? "negative"
                  : undefined
            }
          />
          <Metric
            label="Broker failures"
            value={String(automationStatus?.consecutiveBrokerFailures ?? 0)}
            tone={(automationStatus?.consecutiveBrokerFailures ?? 0) >= 3 ? "negative" : undefined}
          />
          <Metric label="Paper gate" value={paperValidation?.eligible ? "passed" : "blocked"} tone={paperValidation?.eligible ? "positive" : "negative"} />
          <Metric label="Paper trades" value={paperValidation ? `${paperValidation.completedTrades}/${paperValidation.requiredTrades}` : "-"} />
        </div>
        {automationStatus?.brokerHealth === "degraded" && (
          <div className="risk-decision pending">
            <strong>Broker temporarily unavailable</strong>
            <span>{automationStatus.latestBrokerError ?? "Retrying on the normal schedule."}</span>
          </div>
        )}
        {automationStatus?.brokerHealth === "unavailable" && (
          <div className="risk-decision rejected">
            <strong>Broker unavailable</strong>
            <span>{automationStatus.latestBrokerError ?? "Breeze market data is currently unavailable."}</span>
          </div>
        )}
        {paperValidation && !paperValidation.eligible && (
          <div className="risk-decision rejected">
            <strong>Paper validation</strong>
            <span>{paperValidation.reason}</span>
          </div>
        )}
        {latestAutomationEvent && (
          <div
            className={`risk-decision ${
              latestAutomationEvent.severity === "info"
                ? "approved"
                : latestAutomationEvent.severity === "warning"
                  ? "pending"
                  : "rejected"
            }`}
          >
            <strong>{latestAutomationEvent.eventType}</strong>
            <span>{latestAutomationEvent.message}</span>
          </div>
        )}
      </section>

      {latest && (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Latest Decision</h2>
              <p className="muted">{formatDate(latest.createdAt)}</p>
            </div>
            <span className="confidence">{formatPercent(latest.confidence * 100)}</span>
          </div>
          <div className={`risk-decision ${latest.integrityStatus === "system_error" ? "rejected" : latest.riskDecision}`}>
            <strong>{decisionActionLabel(latest)}</strong>
            <span>{latest.integrityStatus === "system_error" ? latest.integrityMessage ?? "Kimi decision failed." : latest.riskReason}</span>
          </div>
          <div className="metric-grid">
            <Metric
              label="Integrity"
              value={integrityLabel(latest.integrityStatus)}
              tone={latest.integrityStatus === "system_error" ? "negative" : "positive"}
            />
            <Metric label="Stock" value={latest.stock ?? "-"} />
            <Metric label="Strategy" value={latest.strategy ?? "-"} />
            <Metric label="Side / Qty" value={latest.side ? `${latest.side} ${latest.quantity ?? "-"}` : "-"} />
            <Metric label="Entry" value={latest.entryPrice ? formatMoney(latest.entryPrice) : "-"} />
            <Metric label="Stop" value={latest.stopLoss ? formatMoney(latest.stopLoss) : "-"} />
            <Metric label="Target" value={latest.target ? formatMoney(latest.target) : "-"} />
          </div>
          <div className="reason-grid">
            <ReasonList title="Reasons" items={latest.reasons} tone="positive" />
            <ReasonList title="Risks" items={latest.risks} tone="negative" />
          </div>
        </section>
      )}

      <section className="panel">
        <h2>Decision History</h2>
        <TradeTable
          emptyText="No Hermes decisions yet."
          headers={["Time", "Action", "Integrity", "Stock", "Strategy", "Risk", "Source"]}
          rows={agentDecisions.map((decision) => [
            formatDate(decision.createdAt),
            decisionActionLabel(decision),
            integrityLabel(decision.integrityStatus),
            decision.stock ?? "-",
            decision.strategy ?? "-",
            decision.riskDecision,
            decision.source
          ])}
        />
      </section>
    </section>
  );
}

function ScannerTab({
  scannerResult,
  strategies,
  dailyReport,
  isCommandRunning,
  runScanner,
  runPaperOnce,
  monitorPaper
}: {
  scannerResult: ScannerResult | null;
  strategies: StrategyTemplate[];
  dailyReport: DailyReport | null;
  isCommandRunning: boolean;
  runScanner: () => void;
  runPaperOnce: () => void;
  monitorPaper: () => void;
}) {
  const shortlist = scannerResult?.shortlist ?? [];
  const rejected = scannerResult?.candidates.filter((candidate) => candidate.rejected) ?? [];

  return (
    <section className="tab-panel">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Market Scanner</h2>
            <p className="muted">
              {scannerResult ? `Updated ${formatDate(scannerResult.generatedAt)}` : "No scan yet."}
            </p>
          </div>
          <div className="action-row">
            <button type="button" className="secondary-button small" onClick={monitorPaper} disabled={isCommandRunning}>
              Monitor
            </button>
            <button type="button" className="secondary-button small" onClick={runPaperOnce} disabled={isCommandRunning}>
              Paper Run
            </button>
            <button type="button" className="primary-button small" onClick={runScanner} disabled={isCommandRunning}>
              Run Scan
            </button>
          </div>
        </div>

        <TradeTable
          emptyText="No shortlisted stocks."
          headers={["Stock", "Score", "Strategy", "Price", "RSI", "Vol Spike"]}
          rows={shortlist.map((candidate) => [
            candidate.stockCode,
            candidate.score.toFixed(1),
            candidate.strategy ?? "-",
            formatMoney(candidate.lastPrice),
            formatNumber(candidate.indicators.rsi),
            formatNumber(candidate.indicators.volumeSpike)
          ])}
        />
      </section>

      <section className="panel">
        <h2>Approved Strategies</h2>
        <TradeTable
          emptyText="No strategies loaded."
          headers={["Strategy", "Version", "Purpose"]}
          rows={strategies.map((strategy) => [strategy.name, strategy.version, strategy.description])}
        />
      </section>

      <section className="panel">
        <h2>Rejected Candidates</h2>
        <TradeTable
          emptyText="No rejected candidates from the latest scan."
          headers={["Stock", "Score", "Reason"]}
          rows={rejected.slice(0, 8).map((candidate) => [
            candidate.stockCode,
            candidate.score.toFixed(1),
            candidate.rejectionReason ?? candidate.negativeReasons[0] ?? "-"
          ])}
        />
      </section>

      {dailyReport && (
        <section className="panel">
          <h2>Daily Paper Report</h2>
          <div className="metric-grid">
            <Metric label="P&L" value={formatMoney(dailyReport.pnl)} tone={dailyReport.pnl >= 0 ? "positive" : "negative"} />
            <Metric label="Trades" value={String(dailyReport.tradesCount)} />
            <Metric label="Wins / Losses" value={`${dailyReport.wins} / ${dailyReport.losses}`} />
            <Metric label="Open" value={String(dailyReport.openTrades)} />
          </div>
        </section>
      )}
    </section>
  );
}

function BacktestsTab({
  backtests,
  strategies,
  eligibility,
  isCommandRunning,
  runBacktest
}: {
  backtests: BacktestRun[];
  strategies: StrategyTemplate[];
  eligibility: StrategyEligibility | null;
  isCommandRunning: boolean;
  runBacktest: (strategy: string) => void;
}) {
  const defaultStrategy = strategies[0]?.name ?? "VWAP pullback";

  return (
    <section className="tab-panel">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Backtest Gate</h2>
            <p className="muted">
              {eligibility
                ? `${eligibility.strategy}: ${eligibility.reason}`
                : "Run a backtest before live eligibility."}
            </p>
          </div>
          <button
            type="button"
            className="primary-button small"
            onClick={() => runBacktest(defaultStrategy)}
            disabled={isCommandRunning}
          >
            Run Backtest
          </button>
        </div>
        {eligibility && (
          <div className={`risk-decision ${eligibility.eligible ? "approved" : "rejected"}`}>
            <strong>{eligibility.eligible ? "Eligible" : "Not eligible"}</strong>
            <span>{eligibility.reason}</span>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Runs</h2>
        <TradeTable
          emptyText="No backtests yet."
          headers={["Strategy", "Trades", "Win", "PF", "Drawdown", "Gate", "Created"]}
          rows={backtests.map((run) => [
            run.strategy,
            String(run.metrics.tradesCount),
            formatPercent(run.metrics.winRate),
            run.metrics.profitFactor.toFixed(2),
            formatPercent(run.metrics.maxDrawdown),
            run.passed ? "passed" : run.reason,
            formatDate(run.createdAt)
          ])}
        />
      </section>
    </section>
  );
}

function LiveOrdersTab({
  liveOrders,
  liveAutopilotStatus,
  liveReadiness,
  isCommandRunning,
  prepareLiveOrder,
  confirmOrder,
  cancelOrder,
  refreshOrder,
  squareOffOrder,
  startLiveAutopilot,
  stopLiveAutopilot
}: {
  liveOrders: LiveOrder[];
  liveAutopilotStatus: LiveAutopilotStatus | null;
  liveReadiness: LiveReadiness | null;
  isCommandRunning: boolean;
  prepareLiveOrder: () => void;
  confirmOrder: (orderId: string) => void;
  cancelOrder: (orderId: string) => void;
  refreshOrder: (orderId: string) => void;
  squareOffOrder: (orderId: string) => void;
  startLiveAutopilot: () => void;
  stopLiveAutopilot: () => void;
}) {
  return (
    <section className="tab-panel">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Live Trading Gate</h2>
            <p className="muted">
              {liveReadiness?.nextAction ?? liveAutopilotStatus?.reason ?? "Live mode is disabled until safety gates pass."}
            </p>
          </div>
          <div className="action-row">
            <button
              type="button"
              className="secondary-button small"
              onClick={stopLiveAutopilot}
              disabled={isCommandRunning || liveAutopilotStatus?.enabled !== true}
            >
              Stop Live
            </button>
            <button
              type="button"
              className="primary-button small"
              onClick={startLiveAutopilot}
              disabled={isCommandRunning || liveAutopilotStatus?.eligible !== true}
            >
              Start Live
            </button>
          </div>
        </div>
        <div className="metric-grid">
          <Metric label="Live autopilot" value={liveAutopilotStatus?.enabled ? "ON" : "OFF"} />
          <Metric label="Manual order" value={liveReadiness?.readyForManualLiveOrder ? "ready" : "blocked"} tone={liveReadiness?.readyForManualLiveOrder ? "positive" : "negative"} />
          <Metric label="Max capital" value={formatMoney(liveAutopilotStatus?.maxCapital ?? 0)} />
          <Metric label="Max orders/day" value={String(liveAutopilotStatus?.maxOrdersPerDay ?? 0)} />
          <Metric label="Static IP" value={liveReadiness?.staticIpReady ? "ready" : "not ready"} tone={liveReadiness?.staticIpReady ? "positive" : "negative"} />
        </div>
        {liveReadiness && (liveReadiness.blockers.length > 0 || liveReadiness.warnings.length > 0) && (
          <div className="reason-grid">
            <ReasonList title="Live blockers" items={liveReadiness.blockers} tone="negative" />
            <ReasonList title="Warnings" items={liveReadiness.warnings} tone="negative" />
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>Manual Live Orders</h2>
          <button
            type="button"
            className="primary-button small"
            onClick={prepareLiveOrder}
            disabled={isCommandRunning}
          >
            Prepare
          </button>
        </div>
        {liveOrders.length === 0 ? (
          <p className="empty-text">No live orders prepared.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {["Stock", "Side", "Qty", "Price", "Strategy", "Status", ""].map((header) => (
                    <th key={header}>{header}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {liveOrders.map((order) => (
                  <tr key={order.id}>
                    <td>{order.stockCode}</td>
                    <td>{order.side}</td>
                    <td>{order.quantity}</td>
                    <td>{formatMoney(order.price)}</td>
                    <td>{order.strategy}</td>
                    <td>{order.status}</td>
                    <td>
                      <div className="action-row table-actions">
                        {order.status === "prepared" && (
                          <button
                            type="button"
                            className="primary-button tiny"
                            onClick={() => confirmOrder(order.id)}
                            disabled={isCommandRunning}
                          >
                            Confirm
                          </button>
                        )}
                        <button
                          type="button"
                          className="secondary-button tiny"
                          onClick={() => refreshOrder(order.id)}
                          disabled={isCommandRunning || order.status === "prepared"}
                        >
                          Refresh
                        </button>
                        <button
                          type="button"
                          className="secondary-button tiny"
                          onClick={() => cancelOrder(order.id)}
                          disabled={isCommandRunning || order.status === "cancelled"}
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          className="secondary-button tiny"
                          onClick={() => squareOffOrder(order.id)}
                          disabled={isCommandRunning || order.status === "prepared"}
                        >
                          Square
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}

function StrategyLabTab({
  improvementRuns,
  improvementStatus,
  improvementReviews,
  improvementLessons,
  strategyVersions,
  championState,
  championRollout,
  isCommandRunning,
  runImprovement,
  promoteChallenger,
  rollbackChampion
}: {
  improvementRuns: ImprovementRun[];
  improvementStatus: ImprovementStatus | null;
  improvementReviews: DailyImprovementReview[];
  improvementLessons: ImprovementLesson[];
  strategyVersions: StrategyVersion[];
  championState: ChampionState | null;
  championRollout: ChampionRollout | null;
  isCommandRunning: boolean;
  runImprovement: () => void;
  promoteChallenger: (versionId: string) => void;
  rollbackChampion: () => void;
}) {
  const champion = championState?.champion ?? null;
  const challengers = championState?.challengers ?? [];

  return (
    <section className="tab-panel">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Champion</h2>
            <p className="muted">{champion ? `${champion.strategy} ${champion.version}` : "No champion promoted yet."}</p>
          </div>
          <div className="action-row">
            <button
              type="button"
              className="secondary-button small"
              onClick={rollbackChampion}
              disabled={isCommandRunning || !champion}
            >
              Rollback
            </button>
            <button
              type="button"
              className="primary-button small"
              onClick={runImprovement}
              disabled={isCommandRunning}
            >
              Improve
            </button>
          </div>
        </div>
        <div className="metric-grid">
          <Metric label="Improvement" value={improvementStatus?.health ?? "unknown"} tone={improvementStatus?.health === "failed" ? "negative" : improvementStatus?.health === "healthy" ? "positive" : undefined} />
          <Metric label="Daily review" value={improvementStatus?.enabled ? improvementStatus.scheduledTimeIst : "off"} />
          <Metric label="Active lessons" value={String(improvementStatus?.activeLessons ?? 0)} />
          <Metric label="Auto promotion" value={improvementStatus?.autoPromotionEnabled ? "enabled" : "off"} tone={improvementStatus?.autoPromotionEnabled ? "positive" : undefined} />
          <Metric label="Capital stage" value={`${championRollout?.stagePercent ?? 0}%`} />
          <Metric label="Live evidence" value={`${championRollout?.liveDays ?? 0}d / ${championRollout?.liveTrades ?? 0}t`} />
        </div>
        {championRollout?.rollbackReason && (
          <div className="risk-decision rejected">
            <strong>Latest rollback</strong>
            <span>{championRollout.rollbackReason}</span>
          </div>
        )}
        <TradeTable
          emptyText="No challengers."
          headers={["Strategy", "Version", "Status", "PF", "Drawdown"]}
          rows={challengers.map((version) => [
            version.strategy,
            version.version,
            version.promotionStatus,
            metricText(version.backtestMetrics.profitFactor),
            metricText(version.backtestMetrics.maxDrawdown)
          ])}
        />
        {challengers.length > 0 && (
          <div className="action-row lab-actions">
            {challengers.slice(0, 3).map((version) => (
              <button
                type="button"
                className="secondary-button tiny"
                key={version.id}
                onClick={() => promoteChallenger(version.id)}
                disabled={isCommandRunning}
              >
                Promote {version.version}
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Daily Reviews</h2>
        <TradeTable
          emptyText="No daily improvement reviews yet."
          headers={["Day", "Status", "Summary", "Mistakes"]}
          rows={improvementReviews.map((review) => [
            review.tradingDay,
            review.status,
            review.summary,
            review.mistakes.join("; ") || "-"
          ])}
        />
      </section>

      <section className="panel">
        <h2>Learned Lessons</h2>
        <TradeTable
          emptyText="No evidence-backed lessons yet."
          headers={["State", "Evidence", "Lesson", "Created"]}
          rows={improvementLessons.map((lesson) => [
            lesson.active ? "active" : "archived",
            String(lesson.evidenceCount),
            lesson.text,
            formatDate(lesson.createdAt)
          ])}
        />
      </section>

      <section className="panel">
        <h2>Strategy Versions</h2>
        <TradeTable
          emptyText="No strategy versions recorded."
          headers={["Strategy", "Version", "Status", "Rule / Notes"]}
          rows={strategyVersions.map((version) => [
            version.strategy,
            version.version,
            version.promotionStatus,
            String(version.parameters.description ?? version.riskNotes[0] ?? "-")
          ])}
        />
      </section>

      <section className="panel">
        <h2>Improvement Runs</h2>
        <TradeTable
          emptyText="No improvement runs."
          headers={["Status", "Tools", "Reason", "Created"]}
          rows={improvementRuns.map((run) => [
            run.status,
            toolSummary(run.toolsAvailable),
            run.reason,
            formatDate(run.createdAt)
          ])}
        />
      </section>
    </section>
  );
}

function SafetyTab({
  safetyStatus,
  automationStatus,
  paperValidation,
  automationEvents,
  auditEvents,
  isCommandRunning,
  activateKillSwitch,
  sendDailyReport
}: {
  safetyStatus: SafetyStatus | null;
  automationStatus: AutomationStatus | null;
  paperValidation: PaperValidationStatus | null;
  automationEvents: AutomationEvent[];
  auditEvents: AuditEvent[];
  isCommandRunning: boolean;
  activateKillSwitch: () => void;
  sendDailyReport: () => void;
}) {
  return (
    <section className="tab-panel">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Safety Controls</h2>
            <p className="muted">{safetyStatus?.message ?? "Safety status unavailable."}</p>
          </div>
          <div className="action-row">
            <button
              type="button"
              className="secondary-button small"
              onClick={sendDailyReport}
              disabled={isCommandRunning}
            >
              Daily Report
            </button>
            <button
              type="button"
              className="danger-button small"
              onClick={activateKillSwitch}
              disabled={isCommandRunning || safetyStatus?.killSwitchActive === true}
            >
              Kill Switch
            </button>
          </div>
        </div>
        <div className="metric-grid">
          <Metric label="Kill switch" value={safetyStatus?.killSwitchActive ? "active" : "clear"} tone={safetyStatus?.killSwitchActive ? "negative" : "positive"} />
          <Metric label="Emergency" value={safetyStatus?.emergencyLocked ? "locked" : "clear"} tone={safetyStatus?.emergencyLocked ? "negative" : "positive"} />
          <Metric label="Daily loss" value={safetyStatus?.dailyLossLocked ? "locked" : "clear"} tone={safetyStatus?.dailyLossLocked ? "negative" : "positive"} />
          <Metric label="Static IP" value={safetyStatus?.staticIpReady ? "ready" : "not ready"} tone={safetyStatus?.staticIpReady ? "positive" : "negative"} />
        </div>
      </section>

      <section className="panel">
        <h2>Automation Gates</h2>
        <div className="metric-grid">
          <Metric label="Automation" value={automationStatus?.enabled ? "ON" : "OFF"} tone={automationStatus?.enabled ? "positive" : "negative"} />
          <Metric label="Config" value={automationStatus?.configEnabled ? "enabled" : "disabled"} tone={automationStatus?.configEnabled ? "positive" : "negative"} />
          <Metric label="Paper days" value={paperValidation ? `${paperValidation.days}/${paperValidation.requiredDays}` : "-"} />
          <Metric label="Profit factor" value={paperValidation ? String(paperValidation.profitFactor) : "-"} />
          <Metric label="Auto errors" value={paperValidation ? String(paperValidation.unresolvedAutomationErrors) : "-"} tone={paperValidation?.unresolvedAutomationErrors ? "negative" : "positive"} />
        </div>
        {automationStatus?.latestError && (
          <div className="risk-decision rejected">
            <strong>Latest error</strong>
            <span>{automationStatus.latestError}</span>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Automation Events</h2>
        <TradeTable
          emptyText="No automation events yet."
          headers={["Severity", "Event", "Message", "Created"]}
          rows={automationEvents.map((event) => [
            event.severity,
            event.eventType,
            event.message,
            formatDate(event.createdAt)
          ])}
        />
      </section>

      <section className="panel">
        <h2>Audit Trail</h2>
        <TradeTable
          emptyText="No audit events yet."
          headers={["Event", "Message", "Created"]}
          rows={auditEvents.map((event) => [
            event.eventType,
            event.message,
            formatDate(event.createdAt)
          ])}
        />
      </section>
    </section>
  );
}

function TradesTab({
  openTrades,
  tradeHistory,
  exitPaperTrade
}: {
  openTrades: OpenTrade[];
  tradeHistory: TradeHistoryItem[];
  exitPaperTrade: (tradeId: string) => void;
}) {
  return (
    <section className="tab-panel">
      <section className="panel">
        <h2>Open Trades</h2>
        {openTrades.length === 0 ? (
          <p className="empty-text">No open trades.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {["Stock", "Strategy", "Qty", "Entry", "SL", "Target", "P&L", "Status", ""].map((header) => (
                    <th key={header}>{header}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {openTrades.map((trade) => (
                  <tr key={trade.id}>
                    <td>{trade.stock}</td>
                    <td>{trade.strategy}</td>
                    <td>{trade.quantity}</td>
                    <td>{formatMoney(trade.entryPrice)}</td>
                    <td>{formatMoney(trade.stopLoss)}</td>
                    <td>{formatMoney(trade.target)}</td>
                    <td>{formatMoney(trade.livePnl)}</td>
                    <td>{trade.status}</td>
                    <td>
                      <button type="button" className="secondary-button tiny" onClick={() => exitPaperTrade(trade.id)}>
                        Exit
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Trade History</h2>
        <TradeTable
          emptyText="No completed trades."
          headers={["Stock", "P&L", "Strategy", "Status", "Exit", "Closed"]}
          rows={tradeHistory.map((trade) => [
            trade.stock,
            formatMoney(trade.pnl),
            trade.strategy,
            trade.status,
            trade.exitReason,
            formatDate(trade.closedAt)
          ])}
        />
      </section>
    </section>
  );
}

function TradeTable({
  headers,
  rows,
  emptyText
}: {
  headers: string[];
  rows: string[][];
  emptyText: string;
}) {
  if (rows.length === 0) {
    return <p className="empty-text">{emptyText}</p>;
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.join("-")}>
              {row.map((cell, index) => (
                <td key={`${cell}-${index}`}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ExplanationTab({ explanation }: { explanation: Explanation | null }) {
  if (!explanation) {
    return (
      <section className="tab-panel">
        <section className="panel">
          <h2>AI Explanation</h2>
          <p className="empty-text">No AI explanation yet.</p>
        </section>
      </section>
    );
  }

  return (
    <section className="tab-panel">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>{explanation.stock ?? "Latest Decision"}</h2>
            <p className="muted">{explanation.strategy ?? "Strategy pending"}</p>
          </div>
          {typeof explanation.confidence === "number" && (
            <span className="confidence">{explanation.confidence}/100</span>
          )}
        </div>
        <p className="explanation-summary">{explanation.summary}</p>

        <div className="reason-grid">
          <ReasonList title="Positive reasons" items={explanation.positiveReasons} tone="positive" />
          <ReasonList title="Negative reasons" items={explanation.negativeReasons} tone="negative" />
        </div>

        {(explanation.selectedCandidates.length > 0 || explanation.rejectedCandidates.length > 0) && (
          <div className="reason-grid">
            <ReasonList title="Selected candidates" items={explanation.selectedCandidates} tone="positive" />
            <ReasonList title="Rejected candidates" items={explanation.rejectedCandidates} tone="negative" />
          </div>
        )}

        <div className={`risk-decision ${explanation.riskDecision}`}>
          <strong>Risk engine: {explanation.riskDecision}</strong>
          <span>{explanation.riskReason}</span>
        </div>

        {explanation.exitReason && (
          <p className="muted">
            <strong>Exit reason:</strong> {explanation.exitReason}
          </p>
        )}
      </section>
    </section>
  );
}

function ReasonList({
  title,
  items,
  tone
}: {
  title: string;
  items: string[];
  tone: "positive" | "negative";
}) {
  return (
    <section className="reason-list">
      <h3>{title}</h3>
      {items.length === 0 ? (
        <p className="empty-text">None reported.</p>
      ) : (
        <ul>
          {items.map((item) => (
            <li className={tone} key={item}>
              {item}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function defaultStockCode(settings: TradingSettings): string {
  if (settings.stockPreset === "CUSTOM" && settings.allowedStocks.length > 0) {
    return settings.allowedStocks[0];
  }
  return "HDFCBANK";
}

function formatMoney(value: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0
  }).format(value || 0);
}

function formatPercent(value: number): string {
  if (!Number.isFinite(value)) {
    return "-";
  }
  return `${value.toFixed(1)}%`;
}

function metricText(value: unknown): string {
  if (typeof value === "number") {
    return value.toFixed(2);
  }
  if (typeof value === "string" && value) {
    return value;
  }
  return "-";
}

function toolSummary(tools: Record<string, boolean>): string {
  const enabled = Object.entries(tools)
    .filter(([, available]) => available)
    .map(([name]) => name);
  return enabled.length > 0 ? enabled.join(", ") : "optional tools missing";
}

function formatNumber(value: number | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(2);
}

function formatDate(value: string): string {
  if (!value) {
    return "-";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function integrityLabel(status: AgentDecision["integrityStatus"]): string {
  if (status === "system_error") {
    return "System Error";
  }
  if (status === "repaired") {
    return "Repaired";
  }
  return status === "genuine" ? "Genuine" : "Unknown";
}

function decisionActionLabel(decision: AgentDecision): string {
  return decision.integrityStatus === "system_error" ? "SYSTEM ERROR" : decision.action;
}

export default App;
