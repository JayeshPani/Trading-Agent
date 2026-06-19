#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import load_config  # noqa: E402
from backend.app.credentials import CredentialService  # noqa: E402
from backend.app.store import SQLiteStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Save Breeze credentials into encrypted storage.")
    parser.add_argument("--values-file", required=True)
    parser.add_argument("--delete-values-file", action="store_true")
    args = parser.parse_args()

    values_path = Path(args.values_file)
    values = json.loads(values_path.read_text(encoding="utf-8"))
    app_key = str(values.get("appKey", "")).strip()
    secret_key = str(values.get("secretKey", "")).strip()
    if not app_key or not secret_key:
        raise SystemExit("Both appKey and secretKey are required.")

    config = load_config()
    store = SQLiteStore(config.database_path)
    try:
        credentials = CredentialService(config, store)
        credentials.save_breeze_credentials(app_key, secret_key)
    finally:
        store.close()

    if args.delete_values_file:
        values_path.unlink(missing_ok=True)

    print("Breeze credentials saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
