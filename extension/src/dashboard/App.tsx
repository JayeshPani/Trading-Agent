import { Play, RefreshCcw, Square } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { api, LiveStatus, TradingSettings } from "../api/client";
import { EmergencyStopButton } from "../components/EmergencyStopButton";
import { HermesSuggestions } from "../components/HermesSuggestions";
import { LogsPanel } from "../components/LogsPanel";
import { MetricTile } from "../components/MetricTile";
import { ModeBadge } from "../components/ModeBadge";
import { PositionsTable } from "../components/PositionsTable";
import { TradingPlanForm } from "../components/TradingPlanForm";
import { connectLiveStatus } from "../websocket/liveStatus";

const defaultSettings: TradingSettings = {
  amount: 10000,
  risk_level: "conservative",
  mode: "paper",
  allowed_symbols: ["RELIANCE", "INFY", "TCS", "HDFCBANK", "ICICIBANK"],
  max_daily_loss: 500,
  max_loss_per_trade: 100,
  strategy_selection: ["vwap_trend", "moving_average_crossover"],
  auto_square_off_enabled: true,
  emergency_stop_enabled: true
};

export function App() {
  const [token, setToken] = useState(() => localStorage.getItem("dashboardToken") ?? "change-me-dev-token");
  const [settings, setSettings] = useState<TradingSettings>(defaultSettings);
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [suggestions, setSuggestions] = useState<unknown[]>([]);

  const sessionId = status?.session_id ?? null;
  const pnl = useMemo(() => {
    if (!status) return 0;
    return status.paper_cash - settings.amount;
  }, [settings.amount, status]);

  useEffect(() => {
    localStorage.setItem("dashboardToken", token);
  }, [token]);

  useEffect(() => {
    if (!token) return;
    api
      .getSettings(token)
      .then((result) => setSettings(result.settings))
      .catch((error) => setMessage(error.message));
  }, [token]);

  useEffect(() => {
    if (!token) return;
    const socket = connectLiveStatus(token, setStatus);
    socket.onerror = () => setMessage("WebSocket disconnected");
    return () => socket.close();
  }, [token]);

  const savePlan = async () => {
    setSaving(true);
    setMessage("");
    try {
      const result = await api.saveSettings(token, settings);
      setSettings(result.settings);
      setMessage("Plan saved");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const run = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setMessage("");
    try {
      await action();
      setMessage(done);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="min-h-screen bg-panel p-4 text-ink">
      <div className="mx-auto max-w-6xl space-y-4">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-300 pb-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold">Breeze Trading Assistant</h1>
              <ModeBadge mode={status?.mode ?? settings.mode} />
            </div>
            <div className="mt-1 text-sm text-stone-600">{sessionId ?? "No active session"}</div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => run(() => api.startSession(token), "Session started")}
              className="inline-flex h-10 items-center gap-2 rounded-md bg-accent px-3 text-sm font-semibold text-white disabled:opacity-50"
            >
              <Play size={17} aria-hidden="true" />
              Start
            </button>
            <button
              type="button"
              disabled={busy || !sessionId}
              onClick={() => sessionId && run(() => api.stopSession(token, sessionId), "Session stopped")}
              className="inline-flex h-10 items-center gap-2 rounded-md bg-stone-800 px-3 text-sm font-semibold text-white disabled:opacity-50"
            >
              <Square size={17} aria-hidden="true" />
              Stop
            </button>
            <EmergencyStopButton disabled={busy} onClick={() => run(() => api.emergencyStop(token), "Emergency stop sent")} />
          </div>
        </header>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <MetricTile label="Cash" value={`₹${(status?.paper_cash ?? settings.amount).toFixed(2)}`} />
          <MetricTile label="P&L" value={`₹${pnl.toFixed(2)}`} tone={pnl < 0 ? "danger" : "default"} />
          <MetricTile label="Daily Loss" value={`₹${settings.max_daily_loss.toFixed(2)}`} />
          <MetricTile label="Open Positions" value={`${status?.open_positions.length ?? 0}`} />
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[360px_1fr]">
          <div className="space-y-4">
            <section className="rounded-md border border-stone-200 bg-white p-4">
              <label className="block text-sm font-medium text-stone-700">
                Backend Token
                <input
                  className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2"
                  type="password"
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                />
              </label>
            </section>
            <TradingPlanForm settings={settings} onChange={setSettings} onSave={savePlan} saving={saving} />
          </div>

          <div className="space-y-4">
            {message ? <div className="rounded-md border border-stone-300 bg-white px-4 py-3 text-sm">{message}</div> : null}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => run(() => api.squareOffAll(token), "Square-off requested")}
                className="inline-flex h-10 items-center gap-2 rounded-md border border-stone-300 bg-white px-3 text-sm font-semibold disabled:opacity-50"
              >
                <Square size={17} aria-hidden="true" />
                Square Off
              </button>
              <button
                type="button"
                disabled={busy || !sessionId}
                onClick={() =>
                  sessionId &&
                  run(async () => {
                    const result = await api.analyzeHermes(token, sessionId);
                    setSuggestions(result.suggestions);
                  }, "Hermes analysis queued")
                }
                className="inline-flex h-10 items-center gap-2 rounded-md border border-stone-300 bg-white px-3 text-sm font-semibold disabled:opacity-50"
              >
                <RefreshCcw size={17} aria-hidden="true" />
                Hermes Review
              </button>
            </div>
            <PositionsTable positions={status?.open_positions ?? []} />
            <LogsPanel logs={status?.logs ?? []} />
            <HermesSuggestions suggestions={suggestions} />
          </div>
        </div>
      </div>
    </main>
  );
}
