import type {
  AuditEvent,
  AgentDecision,
  AgentDecisionResponse,
  AgentStatus,
  ApiResult,
  AuthResponse,
  AutomationEvent,
  AutomationRun,
  AutomationStatus,
  BacktestRun,
  ChampionState,
  CredentialsStatus,
  DailyReport,
  DashboardResponse,
  Explanation,
  ImprovementRun,
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

function normalizeBackendUrl(url: string): string {
  return url.trim().replace(/\/+$/, "");
}

async function request<T>(
  backendUrl: string,
  path: string,
  options: RequestInit = {},
  authToken?: string
): Promise<ApiResult<T>> {
  const url = `${normalizeBackendUrl(backendUrl)}${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined)
  };

  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }

  try {
    const response = await fetch(url, {
      ...options,
      headers
    });

    if (!response.ok) {
      const message = await readErrorMessage(response);
      return {
        data: null,
        error: message || `Request failed with status ${response.status}`
      };
    }

    if (response.status === 204) {
      return { data: null as T, error: null };
    }

    return { data: (await response.json()) as T, error: null };
  } catch {
    return {
      data: null,
      error: "Backend is unreachable. Check the API URL and server status."
    };
  }
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown; message?: unknown; error?: unknown };
    const rawMessage = body.detail ?? body.message ?? body.error;
    if (Array.isArray(rawMessage) && rawMessage.length > 0) {
      const first = rawMessage[0] as { msg?: unknown };
      return typeof first.msg === "string" ? first.msg : "";
    }
    return typeof rawMessage === "string" ? rawMessage : "";
  } catch {
    return "";
  }
}

export const api = {
  getSetupStatus: (backendUrl: string, authToken?: string) =>
    request<SetupStatus>(backendUrl, "/api/setup/status", {}, authToken),
  register: (backendUrl: string, username: string, password: string) =>
    request<AuthResponse>(backendUrl, "/api/account/register", {
      method: "POST",
      body: JSON.stringify({ username, password })
    }),
  login: (backendUrl: string, username: string, password: string) =>
    request<AuthResponse>(backendUrl, "/api/account/login", {
      method: "POST",
      body: JSON.stringify({ username, password })
    }),
  logout: (backendUrl: string, authToken?: string) =>
    request<{ ok: boolean }>(backendUrl, "/api/account/logout", { method: "POST" }, authToken),
  saveBreezeCredentials: (
    backendUrl: string,
    credentials: { appKey: string; secretKey: string },
    authToken?: string
  ) =>
    request<CredentialsStatus>(
      backendUrl,
      "/api/credentials/breeze",
      {
        method: "PUT",
        body: JSON.stringify(credentials)
      },
      authToken
    ),
  getCredentialsStatus: (backendUrl: string, authToken?: string) =>
    request<CredentialsStatus>(backendUrl, "/api/credentials/status", {}, authToken),
  submitSession: (backendUrl: string, sessionKey: string, authToken?: string) =>
    request<{ sessionStatus: string; expiresAt?: string | null }>(
      backendUrl,
      "/api/session",
      {
        method: "POST",
        body: JSON.stringify({ sessionKey })
      },
      authToken
    ),
  getDashboard: (backendUrl: string, authToken?: string) =>
    request<DashboardResponse>(backendUrl, "/api/dashboard", {}, authToken),
  getSettings: (backendUrl: string, authToken?: string) =>
    request<TradingSettings>(backendUrl, "/api/settings", {}, authToken),
  saveSettings: (backendUrl: string, settings: TradingSettings, authToken?: string) =>
    request<TradingSettings>(backendUrl, "/api/settings", {
      method: "PUT",
      body: JSON.stringify(settings)
    }, authToken),
  startAutopilot: (backendUrl: string, authToken?: string) =>
    request<{ autopilotEnabled: boolean }>(
      backendUrl,
      "/api/autopilot/start",
      { method: "POST" },
      authToken
    ),
  stopAutopilot: (backendUrl: string, authToken?: string) =>
    request<{ autopilotEnabled: boolean }>(
      backendUrl,
      "/api/autopilot/stop",
      { method: "POST" },
      authToken
    ),
  emergencyExit: (backendUrl: string, authToken?: string) =>
    request<{ locked: boolean }>(
      backendUrl,
      "/api/emergency-exit",
      { method: "POST" },
      authToken
    ),
  runPaperOnce: (backendUrl: string, authToken?: string) =>
    request<Explanation>(
      backendUrl,
      "/api/paper/run-once",
      { method: "POST" },
      authToken
    ),
  monitorPaper: (backendUrl: string, authToken?: string) =>
    request<OpenTrade[]>(
      backendUrl,
      "/api/paper/monitor",
      { method: "POST" },
      authToken
    ),
  paperExit: (backendUrl: string, tradeId: string, authToken?: string) =>
    request<{ trade: TradeHistoryItem; explanation: Explanation }>(
      backendUrl,
      `/api/trades/${encodeURIComponent(tradeId)}/paper-exit`,
      { method: "POST" },
      authToken
    ),
  getScannerLatest: (backendUrl: string, authToken?: string) =>
    request<ScannerResult>(backendUrl, "/api/scanner/latest", {}, authToken),
  runScanner: (backendUrl: string, authToken?: string) =>
    request<ScannerResult>(
      backendUrl,
      "/api/scanner/run",
      { method: "POST" },
      authToken
    ),
  getStrategies: (backendUrl: string, authToken?: string) =>
    request<StrategyTemplate[]>(backendUrl, "/api/strategies", {}, authToken),
  getDailyReport: (backendUrl: string, authToken?: string) =>
    request<DailyReport>(backendUrl, "/api/reports/daily", {}, authToken),
  runBacktest: (backendUrl: string, payload: { strategy: string; stockCode?: string }, authToken?: string) =>
    request<BacktestRun>(
      backendUrl,
      "/api/backtests/run",
      {
        method: "POST",
        body: JSON.stringify(payload)
      },
      authToken
    ),
  getBacktests: (backendUrl: string, authToken?: string) =>
    request<BacktestRun[]>(backendUrl, "/api/backtests", {}, authToken),
  getStrategyEligibility: (backendUrl: string, strategy: string, authToken?: string) =>
    request<StrategyEligibility>(
      backendUrl,
      `/api/strategies/${encodeURIComponent(strategy)}/eligibility`,
      {},
      authToken
    ),
  prepareLiveOrder: (
    backendUrl: string,
    payload: { stockCode?: string; strategy?: string; quantity?: number; price?: number; side?: "BUY" | "SELL" },
    authToken?: string
  ) =>
    request<LiveOrder>(
      backendUrl,
      "/api/live/orders/prepare",
      {
        method: "POST",
        body: JSON.stringify(payload)
      },
      authToken
    ),
  confirmLiveOrder: (backendUrl: string, orderId: string, authToken?: string) =>
    request<LiveOrder>(
      backendUrl,
      `/api/live/orders/${encodeURIComponent(orderId)}/confirm`,
      { method: "POST" },
      authToken
    ),
  cancelLiveOrder: (backendUrl: string, orderId: string, authToken?: string) =>
    request<LiveOrder>(
      backendUrl,
      `/api/live/orders/${encodeURIComponent(orderId)}/cancel`,
      { method: "POST" },
      authToken
    ),
  refreshLiveOrder: (backendUrl: string, orderId: string, authToken?: string) =>
    request<LiveOrder>(
      backendUrl,
      `/api/live/orders/${encodeURIComponent(orderId)}/refresh`,
      { method: "POST" },
      authToken
    ),
  squareOffLiveOrder: (backendUrl: string, orderId: string, authToken?: string) =>
    request<LiveOrder>(
      backendUrl,
      `/api/live/orders/${encodeURIComponent(orderId)}/square-off`,
      { method: "POST" },
      authToken
    ),
  getLiveOrders: (backendUrl: string, authToken?: string) =>
    request<LiveOrder[]>(backendUrl, "/api/live/orders", {}, authToken),
  getLiveAutopilotStatus: (backendUrl: string, authToken?: string) =>
    request<LiveAutopilotStatus>(backendUrl, "/api/live/autopilot/status", {}, authToken),
  getLiveReadiness: (backendUrl: string, authToken?: string) =>
    request<LiveReadiness>(backendUrl, "/api/live/readiness", {}, authToken),
  getAgentStatus: (backendUrl: string, authToken?: string) =>
    request<AgentStatus>(backendUrl, "/api/agent/status", {}, authToken),
  agentAnalyze: (backendUrl: string, authToken?: string) =>
    request<AgentDecisionResponse>(
      backendUrl,
      "/api/agent/analyze",
      { method: "POST" },
      authToken
    ),
  agentPaperCycle: (backendUrl: string, authToken?: string) =>
    request<AgentDecisionResponse>(
      backendUrl,
      "/api/agent/paper-cycle",
      { method: "POST" },
      authToken
    ),
  agentLiveProposal: (backendUrl: string, authToken?: string) =>
    request<AgentDecisionResponse>(
      backendUrl,
      "/api/agent/live-proposal",
      { method: "POST" },
      authToken
    ),
  agentMonitor: (backendUrl: string, authToken?: string) =>
    request<AgentDecisionResponse>(
      backendUrl,
      "/api/agent/monitor",
      { method: "POST" },
      authToken
    ),
  getAgentDecisions: (backendUrl: string, authToken?: string) =>
    request<AgentDecision[]>(backendUrl, "/api/agent/decisions", {}, authToken),
  startLiveAutopilot: (backendUrl: string, authToken?: string) =>
    request<LiveAutopilotStatus>(
      backendUrl,
      "/api/live/autopilot/start",
      { method: "POST" },
      authToken
    ),
  stopLiveAutopilot: (backendUrl: string, authToken?: string) =>
    request<LiveAutopilotStatus>(
      backendUrl,
      "/api/live/autopilot/stop",
      { method: "POST" },
      authToken
    ),
  runImprovement: (backendUrl: string, authToken?: string) =>
    request<ImprovementRun>(
      backendUrl,
      "/api/improvement/run-after-market",
      { method: "POST" },
      authToken
    ),
  getImprovementRuns: (backendUrl: string, authToken?: string) =>
    request<ImprovementRun[]>(backendUrl, "/api/improvement/runs", {}, authToken),
  getStrategyVersions: (backendUrl: string, authToken?: string) =>
    request<StrategyVersion[]>(backendUrl, "/api/strategy-versions", {}, authToken),
  getChampion: (backendUrl: string, authToken?: string) =>
    request<ChampionState>(backendUrl, "/api/champion", {}, authToken),
  getChallengers: (backendUrl: string, authToken?: string) =>
    request<StrategyVersion[]>(backendUrl, "/api/challengers", {}, authToken),
  promoteChallenger: (backendUrl: string, versionId: string, authToken?: string) =>
    request<StrategyVersion>(
      backendUrl,
      `/api/challengers/${encodeURIComponent(versionId)}/promote`,
      { method: "POST" },
      authToken
    ),
  rollbackChampion: (backendUrl: string, authToken?: string) =>
    request<StrategyVersion>(
      backendUrl,
      "/api/champion/rollback",
      { method: "POST" },
      authToken
    ),
  getSafetyStatus: (backendUrl: string, authToken?: string) =>
    request<SafetyStatus>(backendUrl, "/api/safety/status", {}, authToken),
  activateKillSwitch: (backendUrl: string, authToken?: string) =>
    request<SafetyStatus>(
      backendUrl,
      "/api/safety/kill-switch",
      { method: "POST" },
      authToken
    ),
  getAudit: (backendUrl: string, authToken?: string) =>
    request<AuditEvent[]>(backendUrl, "/api/audit", {}, authToken),
  sendDailyReport: (backendUrl: string, authToken?: string) =>
    request<{ ok: boolean; message: string }>(
      backendUrl,
      "/api/reports/daily/send",
      { method: "POST" },
      authToken
    ),
  getAutomationStatus: (backendUrl: string, authToken?: string) =>
    request<AutomationStatus>(backendUrl, "/api/automation/status", {}, authToken),
  startAutomation: (backendUrl: string, authToken?: string) =>
    request<AutomationStatus>(
      backendUrl,
      "/api/automation/start",
      { method: "POST" },
      authToken
    ),
  stopAutomation: (backendUrl: string, authToken?: string) =>
    request<AutomationStatus>(
      backendUrl,
      "/api/automation/stop",
      { method: "POST" },
      authToken
    ),
  runAutomationOnce: (backendUrl: string, authToken?: string) =>
    request<AutomationRun>(
      backendUrl,
      "/api/automation/run-once",
      { method: "POST" },
      authToken
    ),
  getAutomationEvents: (backendUrl: string, authToken?: string) =>
    request<AutomationEvent[]>(backendUrl, "/api/automation/events", {}, authToken),
  getPaperValidation: (backendUrl: string, authToken?: string) =>
    request<PaperValidationStatus>(backendUrl, "/api/paper/validation", {}, authToken),
  getOpenTrades: (backendUrl: string, authToken?: string) =>
    request<OpenTrade[]>(backendUrl, "/api/trades/open", {}, authToken),
  getTradeHistory: (backendUrl: string, authToken?: string) =>
    request<TradeHistoryItem[]>(backendUrl, "/api/trades/history", {}, authToken),
  getLatestExplanation: (backendUrl: string, authToken?: string) =>
    request<Explanation>(backendUrl, "/api/explanations/latest", {}, authToken)
};
