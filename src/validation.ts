import type { TradingSettings } from "./types";

export function normalizeSymbol(symbol: string): string {
  return symbol.trim().toUpperCase().replace(/[^A-Z0-9&-]/g, "");
}

export function normalizeSettings(settings: TradingSettings): TradingSettings {
  const allowedStocks = Array.isArray(settings.allowedStocks) ? settings.allowedStocks : [];
  return {
    ...settings,
    targetPercent: Number.isFinite(settings.targetPercent) ? settings.targetPercent : 3,
    allowedStocks: Array.from(
      new Set(allowedStocks.map(normalizeSymbol).filter(Boolean))
    )
  };
}

export function validateSettings(settings: TradingSettings): string[] {
  const errors: string[] = [];

  if (!Number.isFinite(settings.budget) || settings.budget <= 0) {
    errors.push("Budget must be greater than 0.");
  }

  if (!Number.isFinite(settings.stopLossPercent) || settings.stopLossPercent <= 0) {
    errors.push("Stop-loss must be greater than 0.");
  }

  if (!Number.isFinite(settings.dailyMaxLoss) || settings.dailyMaxLoss <= 0) {
    errors.push("Daily max loss must be greater than 0.");
  }

  if (!Number.isFinite(settings.maxTradesPerDay) || settings.maxTradesPerDay <= 0) {
    errors.push("Max trades per day must be greater than 0.");
  }

  if (!Number.isFinite(settings.targetPercent) || settings.targetPercent <= 0) {
    errors.push("Target must be greater than 0.");
  }

  if (!settings.mode) {
    errors.push("Trading mode is required.");
  }

  if (settings.stockPreset === "CUSTOM" && settings.allowedStocks.length === 0) {
    errors.push("Add at least one allowed stock or choose the NIFTY 50 preset.");
  }

  return errors;
}
