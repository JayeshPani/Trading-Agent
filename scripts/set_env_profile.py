#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


PROFILES: dict[str, dict[str, str]] = {
    "paper-automation": {
        "TRADING_MODE": "paper",
        "STATIC_IP_READY": "false",
        "AUTOMATION_ENABLED": "true",
        "AUTO_LIVE_EXITS_ENABLED": "false",
        "AUTO_LIVE_ENTRIES_ENABLED": "false",
        "HERMES_ENABLED": "true",
        "HERMES_PROVIDER": "kimi",
        "HERMES_BASE_URL": "https://api.moonshot.ai/v1",
        "HERMES_MODEL": "kimi-k2.6",
        "HERMES_TIMEOUT_SECONDS": "60",
        "SCANNER_MAX_SYMBOLS_PER_CYCLE": "20",
    },
    "manual-live": {
        "TRADING_MODE": "live",
        "STATIC_IP_READY": "true",
        "AUTOMATION_ENABLED": "false",
        "AUTO_LIVE_EXITS_ENABLED": "false",
        "AUTO_LIVE_ENTRIES_ENABLED": "false",
        "HERMES_ENABLED": "true",
    },
    "live-exits": {
        "TRADING_MODE": "live",
        "STATIC_IP_READY": "true",
        "AUTOMATION_ENABLED": "true",
        "AUTO_LIVE_EXITS_ENABLED": "true",
        "AUTO_LIVE_ENTRIES_ENABLED": "false",
        "HERMES_ENABLED": "true",
    },
    "live-entries": {
        "TRADING_MODE": "live",
        "STATIC_IP_READY": "true",
        "AUTOMATION_ENABLED": "true",
        "AUTO_LIVE_EXITS_ENABLED": "true",
        "AUTO_LIVE_ENTRIES_ENABLED": "true",
        "HERMES_ENABLED": "true",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply a safe BreezePilot .env profile.")
    parser.add_argument("profile", choices=sorted(PROFILES))
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    env_path = Path(args.env_file)
    existing = _read_env(env_path)
    next_values = {**existing, **PROFILES[args.profile]}
    content = _render_env(next_values)

    if args.dry_run:
        print(_redact(content))
        return 0

    env_path.write_text(content, encoding="utf-8")
    print(f"Applied {args.profile} profile to {env_path}.")
    print("Restart the backend for changes to take effect.")
    return 0


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _render_env(values: dict[str, str]) -> str:
    preferred_order = [
        "BREEZEPILOT_DB_PATH",
        "BREEZEPILOT_ENCRYPTION_KEY_PATH",
        "TRADING_MODE",
        "BREEZE_APP_KEY",
        "BREEZE_SECRET_KEY",
        "STATIC_IP_READY",
        "ENFORCE_MARKET_HOURS",
        "BREEZE_BASE_URL",
        "HERMES_ENABLED",
        "HERMES_PROVIDER",
        "HERMES_BASE_URL",
        "HERMES_MODEL",
        "HERMES_API_KEY",
        "HERMES_TIMEOUT_SECONDS",
        "AUTOMATION_ENABLED",
        "AUTO_PAPER_SCAN_INTERVAL_SECONDS",
        "AUTO_PAPER_MONITOR_INTERVAL_SECONDS",
        "AUTO_LIVE_EXIT_INTERVAL_SECONDS",
        "AUTO_LIVE_ENTRY_INTERVAL_SECONDS",
        "SCANNER_MAX_SYMBOLS_PER_CYCLE",
        "AUTO_LIVE_EXITS_ENABLED",
        "AUTO_LIVE_ENTRIES_ENABLED",
    ]
    keys = [key for key in preferred_order if key in values]
    keys.extend(sorted(key for key in values if key not in set(keys)))
    return "".join(f"{key}={values[key]}\n" for key in keys)


def _redact(content: str) -> str:
    redacted: list[str] = []
    for line in content.splitlines():
        if line.startswith(("HERMES_API_KEY=", "BREEZE_APP_KEY=", "BREEZE_SECRET_KEY=")):
            key, value = line.split("=", 1)
            redacted.append(f"{key}=<configured>" if value else f"{key}=")
        else:
            redacted.append(line)
    return "\n".join(redacted)


if __name__ == "__main__":
    raise SystemExit(main())
