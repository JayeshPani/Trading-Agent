#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.advanced import AdvancedTradingService  # noqa: E402
from backend.app.breeze import BreezeClient  # noqa: E402
from backend.app.config import load_config  # noqa: E402
from backend.app.credentials import CredentialService  # noqa: E402
from backend.app.rate_limit import RateLimiter  # noqa: E402
from backend.app.store import SQLiteStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check BreezePilot real-trading readiness.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    config = load_config()
    store = SQLiteStore(config.database_path)
    credentials = CredentialService(config, store)
    rate_limiter = RateLimiter()
    breeze = BreezeClient(
        config,
        rate_limiter,
        credential_provider=credentials.get_breeze_credentials,
    )
    advanced = AdvancedTradingService(
        config=config,
        store=store,
        breeze_client=breeze,
        credentials_ready=credentials.breeze_credentials_saved,
    )

    runtime = store.get_runtime()
    safety = advanced.safety_status()
    live = advanced.live_readiness()
    paper = store.paper_validation_status()
    agent_ok = bool(config.hermes_enabled and config.hermes_api_key)
    readiness = {
        "environment": {
            "tradingMode": config.trading_mode,
            "staticIpReady": config.static_ip_ready,
            "automationEnabled": config.automation_enabled,
            "autoLiveExitsEnabled": config.auto_live_exits_enabled,
            "autoLiveEntriesEnabled": config.auto_live_entries_enabled,
            "kimiConfigured": agent_ok,
        },
        "setup": {
            "credentialsReady": credentials.breeze_credentials_saved(),
            "sessionStatus": runtime.session_status,
            "sessionActive": runtime.session_status == "active" and bool(runtime.session_token),
            "settingsMode": store.get_settings().mode,
        },
        "gates": {
            "manualLiveReady": live.ready_for_manual_live_order,
            "liveAutopilotReady": live.ready_for_live_autopilot,
            "paperValidationReady": paper.eligible,
            "paperValidationReason": paper.reason,
            "strategyEligible": live.strategy_eligible,
            "killSwitchActive": safety.kill_switch_active,
            "emergencyLocked": safety.emergency_locked,
            "dailyLossLocked": safety.daily_loss_locked,
        },
        "blockers": live.blockers,
        "warnings": live.warnings,
        "nextAction": live.next_action,
    }

    store.close()
    if args.json:
        print(json.dumps(readiness, indent=2))
    else:
        _print_human(readiness)
    return 0 if not readiness["blockers"] else 1


def _print_human(readiness: dict[str, object]) -> None:
    print("BreezePilot real-trading readiness")
    print("")
    for section in ("environment", "setup", "gates"):
        print(section.upper())
        values = readiness[section]
        assert isinstance(values, dict)
        for key, value in values.items():
            print(f"- {key}: {value}")
        print("")
    blockers = readiness["blockers"]
    warnings = readiness["warnings"]
    print("BLOCKERS")
    if blockers:
        for blocker in blockers:
            print(f"- {blocker}")
    else:
        print("- none")
    print("")
    print("WARNINGS")
    if warnings:
        for warning in warnings:
            print(f"- {warning}")
    else:
        print("- none")
    print("")
    print(f"NEXT ACTION: {readiness['nextAction']}")


if __name__ == "__main__":
    raise SystemExit(main())
