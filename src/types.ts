export type TradingMode = "intraday" | "delivery";
export type ConnectionState = "checking" | "online" | "offline";
export type SessionState = "active" | "missing" | "expired" | "unknown";
export type RiskStatus = "clear" | "warning" | "locked";
export type AgentAction = "SKIP" | "PROPOSE_ENTRY" | "PROPOSE_EXIT" | "TIGHTEN_STOP" | "HOLD";

export interface TradingSettings {
  budget: number;
  stopLossPercent: number;
  dailyMaxLoss: number;
  maxTradesPerDay: number;
  targetPercent: number;
  mode: TradingMode;
  stockPreset: "NIFTY 50" | "CUSTOM";
  allowedStocks: string[];
}

export interface PnlSummary {
  currentPnl: number;
  dailyLossUsed: number;
  remainingBudget: number;
  openTradesCount: number;
}

export interface OpenTrade {
  id: string;
  stock: string;
  side: "BUY" | "SELL";
  quantity: number;
  entryPrice: number;
  stopLoss: number;
  target: number;
  livePnl: number;
  status: string;
  strategy: string;
}

export interface TradeHistoryItem {
  id: string;
  stock: string;
  side: "BUY" | "SELL";
  quantity: number;
  entryPrice: number;
  exitPrice: number;
  pnl: number;
  strategy: string;
  status: string;
  exitReason: string;
  closedAt: string;
}

export interface Explanation {
  tradeId?: string;
  stock?: string;
  strategy?: string;
  confidence?: number;
  summary: string;
  positiveReasons: string[];
  negativeReasons: string[];
  selectedCandidates: string[];
  rejectedCandidates: string[];
  riskDecision: "approved" | "rejected" | "pending" | "none";
  riskReason: string;
  exitReason?: string;
}

export interface DashboardResponse {
  autopilotEnabled: boolean;
  sessionStatus: SessionState;
  pnl: PnlSummary;
  openTrades: OpenTrade[];
  latestExplanation: Explanation | null;
  riskStatus: RiskStatus;
  riskMessage: string;
}

export interface ExtensionPreferences {
  backendUrl: string;
  lastTab: AppTab;
  authToken?: string;
  draftSettings?: TradingSettings;
}

export type AppTab =
  | "dashboard"
  | "agent"
  | "scanner"
  | "backtests"
  | "live"
  | "lab"
  | "safety"
  | "trades"
  | "explanation";

export interface ApiResult<T> {
  data: T | null;
  error: string | null;
}

export interface AuthResponse {
  token: string;
  username: string;
}

export interface CredentialsStatus {
  breezeCredentialsSaved: boolean;
}

export interface SetupStatus {
  accountExists: boolean;
  loggedIn: boolean;
  breezeCredentialsSaved: boolean;
  sessionStatus: SessionState;
  settingsValid: boolean;
  emergencyLocked: boolean;
  setupComplete: boolean;
  nextStep: "account" | "login" | "credentials" | "session" | "rules" | "locked" | "ready" | string;
  tradingMode: string;
  staticIpReady: boolean;
}

export interface StrategyTemplate {
  name: string;
  version: string;
  description: string;
}

export interface ScannerCandidate {
  stockCode: string;
  score: number;
  strategy?: string | null;
  strategyVersion?: string | null;
  lastPrice: number;
  indicators: Record<string, number>;
  positiveReasons: string[];
  negativeReasons: string[];
  rejected: boolean;
  rejectionReason?: string | null;
}

export interface ScannerResult {
  generatedAt: string;
  candidates: ScannerCandidate[];
  shortlist: ScannerCandidate[];
  brokerStatus?: "healthy" | "degraded" | "unavailable";
  brokerErrorCount?: number;
  brokerError?: string | null;
}

export interface DailyReport {
  tradingDay: string;
  pnl: number;
  tradesCount: number;
  wins: number;
  losses: number;
  openTrades: number;
  dailyLossUsed: number;
  generatedAt: string;
}

export interface AutomationStatus {
  enabled: boolean;
  running: boolean;
  configEnabled: boolean;
  mode: string;
  autoLiveEntriesEnabled: boolean;
  autoLiveExitsEnabled: boolean;
  lastPaperScanAt?: string | null;
  lastPaperMonitorAt?: string | null;
  lastLiveExitAt?: string | null;
  lastLiveEntryAt?: string | null;
  latestError?: string | null;
  brokerHealth?: "healthy" | "degraded" | "unavailable";
  consecutiveBrokerFailures?: number;
  lastBrokerSuccessAt?: string | null;
  latestBrokerError?: string | null;
  message: string;
}

export interface AutomationEvent {
  id: string;
  eventType: string;
  severity: "info" | "warning" | "error";
  message: string;
  details: Record<string, unknown>;
  createdAt: string;
}

export interface AutomationRun {
  id: string;
  mode: string;
  status: string;
  startedAt: string;
  finishedAt?: string | null;
  summary: string;
}

export interface PaperValidationStatus {
  eligible: boolean;
  reason: string;
  days: number;
  completedTrades: number;
  profitFactor: number;
  dailyLossBreached: boolean;
  unresolvedAutomationErrors: number;
  unresolvedAgentErrors?: number;
  requiredDays: number;
  requiredTrades: number;
}

export interface BacktestMetrics {
  winRate: number;
  profitFactor: number;
  maxDrawdown: number;
  averageProfit: number;
  averageLoss: number;
  tradesCount: number;
  bestMarketCondition: string;
  worstMarketCondition: string;
}

export interface BacktestRun {
  id: string;
  strategy: string;
  strategyVersion: string;
  stockUniverse: string[];
  fromDate: string;
  toDate: string;
  metrics: BacktestMetrics;
  passed: boolean;
  reason: string;
  createdAt: string;
}

export interface StrategyEligibility {
  strategy: string;
  eligible: boolean;
  reason: string;
  latestBacktest?: BacktestRun | null;
}

export interface LiveOrder {
  id: string;
  stockCode: string;
  side: "BUY" | "SELL";
  quantity: number;
  price: number;
  orderType: string;
  status: string;
  strategy: string;
  brokerOrderId?: string | null;
  reason?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface LiveAutopilotStatus {
  enabled: boolean;
  eligible: boolean;
  reason: string;
  maxOrdersPerDay: number;
  maxOpenPositions: number;
  maxCapital: number;
}

export interface LiveReadiness {
  readyForManualLiveOrder: boolean;
  readyForLiveAutopilot: boolean;
  liveMode: boolean;
  credentialsReady: boolean;
  sessionActive: boolean;
  staticIpReady: boolean;
  strategyEligible: boolean;
  paperValidationReady: boolean;
  blockers: string[];
  warnings: string[];
  nextAction: string;
}

export interface ImprovementRun {
  id: string;
  status: string;
  toolsAvailable: Record<string, boolean>;
  createdVersionId?: string | null;
  reason: string;
  createdAt: string;
}

export interface StrategyVersion {
  id: string;
  strategy: string;
  version: string;
  parameters: Record<string, unknown>;
  backtestMetrics: Record<string, unknown>;
  paperMetrics: Record<string, unknown>;
  riskNotes: string[];
  promotionStatus: string;
  createdAt: string;
}

export interface ChampionState {
  champion?: StrategyVersion | null;
  challengers: StrategyVersion[];
}

export interface SafetyStatus {
  killSwitchActive: boolean;
  emergencyLocked: boolean;
  dailyLossLocked: boolean;
  sessionActive: boolean;
  staticIpReady: boolean;
  liveMode: boolean;
  capitalLock: number;
  maxOrderLimit: number;
  message: string;
}

export interface AuditEvent {
  id: string;
  eventType: string;
  message: string;
  details: Record<string, unknown>;
  createdAt: string;
}

export interface AgentStatus {
  enabled: boolean;
  provider: string;
  model: string;
  baseUrl: string;
  apiKeyConfigured: boolean;
  tradingMode: string;
  healthy?: boolean;
  consecutiveSystemErrors?: number;
  latestIntegrityStatus?: "genuine" | "repaired" | "system_error" | null;
  lastValidDecisionAt?: string | null;
  message: string;
}

export interface AgentDecision {
  id: string;
  runId: string;
  action: AgentAction;
  stock?: string | null;
  strategy?: string | null;
  side?: "BUY" | "SELL" | null;
  quantity?: number | null;
  entryPrice?: number | null;
  stopLoss?: number | null;
  target?: number | null;
  confidence: number;
  reasons: string[];
  risks: string[];
  expiresAt?: string | null;
  riskDecision: "approved" | "rejected" | "pending" | "none";
  riskReason: string;
  tradeId?: string | null;
  orderId?: string | null;
  integrityStatus?: "genuine" | "repaired" | "system_error";
  integrityMessage?: string;
  source: string;
  createdAt: string;
}

export interface AgentDecisionResponse {
  decision: AgentDecision;
  explanation: Explanation;
  liveOrder?: LiveOrder | null;
}
