import type { DashboardResponse, ExtensionPreferences, TradingSettings } from "./types";

export const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";

export const DEFAULT_SETTINGS: TradingSettings = {
  budget: 10000,
  stopLossPercent: 1.5,
  dailyMaxLoss: 300,
  maxTradesPerDay: 3,
  targetPercent: 3,
  mode: "intraday",
  stockPreset: "NIFTY 50",
  allowedStocks: []
};

export const DEFAULT_PREFERENCES: ExtensionPreferences = {
  backendUrl: DEFAULT_BACKEND_URL,
  lastTab: "dashboard"
};

export const EMPTY_DASHBOARD: DashboardResponse = {
  autopilotEnabled: false,
  sessionStatus: "unknown",
  pnl: {
    currentPnl: 0,
    dailyLossUsed: 0,
    remainingBudget: 0,
    openTradesCount: 0
  },
  openTrades: [],
  latestExplanation: null,
  riskStatus: "warning",
  riskMessage: "Waiting for backend connection."
};
