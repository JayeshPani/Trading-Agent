export type TradingSettings = {
  amount: number;
  risk_level: "conservative" | "moderate" | "custom";
  mode: "paper" | "live";
  allowed_symbols: string[];
  max_daily_loss: number;
  max_loss_per_trade: number;
  strategy_selection: string[];
  auto_square_off_enabled: boolean;
  emergency_stop_enabled: boolean;
};

export type LiveStatus = {
  mode: "paper" | "live";
  session_id: string | null;
  emergency_stopped: boolean;
  paper_cash: number;
  open_positions: Array<{
    symbol: string;
    side: string;
    quantity: number;
    entry_price: number;
    last_price: number;
    pnl: number;
    status: string;
  }>;
  logs: Array<{ created_at: string; level: string; message: string; metadata: Record<string, unknown> }>;
};

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export function getApiBase(): string {
  return API_BASE;
}

async function request<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init.headers ?? {})
    }
  });
  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export const api = {
  getSettings: (token: string) => request<{ settings: TradingSettings }>("/api/settings", token),
  saveSettings: (token: string, settings: TradingSettings) =>
    request<{ settings: TradingSettings }>("/api/settings", token, {
      method: "POST",
      body: JSON.stringify(settings)
    }),
  startSession: (token: string) =>
    request<{ session: { id: string; status: string; starting_capital: number } }>("/api/sessions/start", token, {
      method: "POST"
    }),
  stopSession: (token: string, sessionId: string) =>
    request<{ session: { id: string; status: string } }>(`/api/sessions/${sessionId}/stop`, token, {
      method: "POST"
    }),
  emergencyStop: (token: string) =>
    request<{ emergency_stopped: boolean }>("/api/risk/emergency-stop", token, {
      method: "POST",
      body: JSON.stringify({ exit_positions: true })
    }),
  squareOffAll: (token: string) =>
    request<{ results: unknown[] }>("/api/positions/square-off-all", token, {
      method: "POST"
    }),
  analyzeHermes: (token: string, sessionId: string) =>
    request<{ suggestions: unknown[] }>(`/api/hermes/analyze-session/${sessionId}`, token, {
      method: "POST"
    }),
  getHermesSuggestions: (token: string) => request<{ suggestions: unknown[] }>("/api/hermes/suggestions", token)
};
