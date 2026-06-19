import { DEFAULT_PREFERENCES } from "./defaults";
import type { AppTab, ExtensionPreferences, TradingSettings } from "./types";

type StorageValue = string | number | boolean | object | undefined;

interface ChromeStorageArea {
  get(keys: string[] | string | Record<string, StorageValue>): Promise<Record<string, StorageValue>>;
  set(items: Record<string, StorageValue>): Promise<void>;
}

declare const chrome:
  | {
      storage?: {
        local?: ChromeStorageArea;
      };
    }
  | undefined;

const memoryStore: Record<string, StorageValue> = {};

function storageArea(): ChromeStorageArea | null {
  return typeof chrome !== "undefined" && chrome.storage?.local ? chrome.storage.local : null;
}

async function getValue<T>(key: string, fallback: T): Promise<T> {
  const area = storageArea();
  if (!area) {
    return (memoryStore[key] as T | undefined) ?? fallback;
  }

  const result = await area.get({ [key]: fallback as StorageValue });
  return (result[key] as T | undefined) ?? fallback;
}

async function setValue<T extends StorageValue>(key: string, value: T): Promise<void> {
  const area = storageArea();
  if (!area) {
    memoryStore[key] = value;
    return;
  }

  await area.set({ [key]: value });
}

export async function loadPreferences(): Promise<ExtensionPreferences> {
  const saved = await getValue<Partial<ExtensionPreferences>>("preferences", DEFAULT_PREFERENCES);
  return {
    ...DEFAULT_PREFERENCES,
    ...saved
  };
}

export async function saveBackendUrl(backendUrl: string): Promise<void> {
  const preferences = await loadPreferences();
  await setValue("preferences", { ...preferences, backendUrl });
}

export async function saveLastTab(lastTab: AppTab): Promise<void> {
  const preferences = await loadPreferences();
  await setValue("preferences", { ...preferences, lastTab });
}

export async function saveDraftSettings(draftSettings: TradingSettings): Promise<void> {
  const preferences = await loadPreferences();
  await setValue("preferences", { ...preferences, draftSettings });
}

export async function saveAuthToken(authToken: string): Promise<void> {
  const preferences = await loadPreferences();
  await setValue("preferences", { ...preferences, authToken });
}

export async function clearAuthToken(): Promise<void> {
  const preferences = await loadPreferences();
  const { authToken: _authToken, ...nextPreferences } = preferences;
  await setValue("preferences", nextPreferences);
}
