import { Save, ShieldCheck } from "lucide-react";

import { TradingSettings } from "../api/client";

type TradingPlanFormProps = {
  settings: TradingSettings;
  onChange: (settings: TradingSettings) => void;
  onSave: () => void;
  saving: boolean;
};

const strategies = [
  "vwap_trend",
  "moving_average_crossover",
  "breakout_with_volume",
  "rsi_mean_reversion"
];

export function TradingPlanForm({ settings, onChange, onSave, saving }: TradingPlanFormProps) {
  const update = <K extends keyof TradingSettings>(key: K, value: TradingSettings[K]) => {
    onChange({ ...settings, [key]: value });
  };

  const toggleStrategy = (name: string) => {
    const selected = settings.strategy_selection.includes(name)
      ? settings.strategy_selection.filter((item) => item !== name)
      : [...settings.strategy_selection, name];
    update("strategy_selection", selected);
  };

  return (
    <section className="space-y-3 rounded-md border border-stone-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-ink">Trading Plan</h2>
        <ShieldCheck size={18} className="text-accent" aria-hidden="true" />
      </div>

      <label className="block text-sm font-medium text-stone-700">
        Capital Today
        <input
          className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2"
          type="number"
          min={1}
          value={settings.amount}
          onChange={(event) => update("amount", Number(event.target.value))}
        />
      </label>

      <div className="grid grid-cols-2 gap-3">
        <label className="block text-sm font-medium text-stone-700">
          Daily Loss
          <input
            className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2"
            type="number"
            min={1}
            value={settings.max_daily_loss}
            onChange={(event) => update("max_daily_loss", Number(event.target.value))}
          />
        </label>
        <label className="block text-sm font-medium text-stone-700">
          Trade Loss
          <input
            className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2"
            type="number"
            min={1}
            value={settings.max_loss_per_trade}
            onChange={(event) => update("max_loss_per_trade", Number(event.target.value))}
          />
        </label>
      </div>

      <label className="block text-sm font-medium text-stone-700">
        Allowed Symbols
        <input
          className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2"
          value={settings.allowed_symbols.join(", ")}
          onChange={(event) =>
            update(
              "allowed_symbols",
              event.target.value
                .split(",")
                .map((symbol) => symbol.trim().toUpperCase())
                .filter(Boolean)
            )
          }
        />
      </label>

      <div className="grid grid-cols-2 gap-3">
        <label className="block text-sm font-medium text-stone-700">
          Mode
          <select
            className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2"
            value={settings.mode}
            onChange={(event) => update("mode", event.target.value as TradingSettings["mode"])}
          >
            <option value="paper">Paper</option>
            <option value="live">Live</option>
          </select>
        </label>
        <label className="block text-sm font-medium text-stone-700">
          Risk
          <select
            className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2"
            value={settings.risk_level}
            onChange={(event) => update("risk_level", event.target.value as TradingSettings["risk_level"])}
          >
            <option value="conservative">Conservative</option>
            <option value="moderate">Moderate</option>
            <option value="custom">Custom</option>
          </select>
        </label>
      </div>

      <div className="space-y-2">
        <div className="text-sm font-medium text-stone-700">Strategies</div>
        <div className="grid grid-cols-2 gap-2">
          {strategies.map((strategy) => (
            <label key={strategy} className="flex items-center gap-2 rounded-md border border-stone-200 px-2 py-2 text-xs">
              <input
                type="checkbox"
                checked={settings.strategy_selection.includes(strategy)}
                onChange={() => toggleStrategy(strategy)}
              />
              <span>{strategy}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 text-sm">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={settings.auto_square_off_enabled}
            onChange={(event) => update("auto_square_off_enabled", event.target.checked)}
          />
          Auto square-off
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={settings.emergency_stop_enabled}
            onChange={(event) => update("emergency_stop_enabled", event.target.checked)}
          />
          Kill switch
        </label>
      </div>

      <button
        type="button"
        disabled={saving}
        onClick={onSave}
        className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-accent px-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Save size={17} aria-hidden="true" />
        Save Plan
      </button>
    </section>
  );
}
