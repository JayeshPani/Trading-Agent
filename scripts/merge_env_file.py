#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge KEY=VALUE lines into a .env file.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--values-file", required=True)
    parser.add_argument("--delete-values-file", action="store_true")
    args = parser.parse_args()

    env_path = Path(args.env_file)
    values_path = Path(args.values_file)
    existing = _read_env(env_path)
    updates = _read_env(values_path)
    if not updates:
        raise SystemExit(f"No KEY=VALUE lines found in {values_path}.")

    next_values = {**existing, **updates}
    env_path.write_text(_render_env(next_values), encoding="utf-8")

    if args.delete_values_file:
        values_path.unlink(missing_ok=True)

    print(f"Merged {len(updates)} value(s) into {env_path}.")
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
    ordered = [key for key in preferred_order if key in values]
    ordered.extend(sorted(key for key in values if key not in set(ordered)))
    return "".join(f"{key}={values[key]}\n" for key in ordered)


if __name__ == "__main__":
    raise SystemExit(main())
