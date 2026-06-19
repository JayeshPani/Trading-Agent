from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class AppConfig:
    database_path: str
    encryption_key_path: str
    trading_mode: str
    breeze_app_key: str | None
    breeze_secret_key: str | None
    static_ip_ready: bool
    enforce_market_hours: bool
    breeze_base_url: str = "https://api.icicidirect.com/breezeapi/api/v1"
    hermes_enabled: bool = False
    hermes_base_url: str = "http://127.0.0.1:11434/v1"
    hermes_model: str = "hermes"
    hermes_api_key: str | None = None
    hermes_provider: str = "local"
    hermes_timeout_seconds: int = 20
    automation_enabled: bool = False
    auto_paper_scan_interval_seconds: int = 300
    auto_paper_monitor_interval_seconds: int = 30
    auto_live_exit_interval_seconds: int = 15
    auto_live_entry_interval_seconds: int = 300
    scanner_max_symbols_per_cycle: int = 20
    auto_live_entries_enabled: bool = False
    auto_live_exits_enabled: bool = False

    @property
    def is_live_mode(self) -> bool:
        return self.trading_mode == "live"

    @property
    def has_breeze_credentials(self) -> bool:
        return bool(self.breeze_app_key and self.breeze_secret_key)


def load_config() -> AppConfig:
    _load_dotenv()
    db_path = os.getenv("BREEZEPILOT_DB_PATH", "backend/data/breezepilot.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    key_path = os.getenv("BREEZEPILOT_ENCRYPTION_KEY_PATH", "backend/data/fernet.key")
    Path(key_path).parent.mkdir(parents=True, exist_ok=True)

    return AppConfig(
        database_path=db_path,
        encryption_key_path=key_path,
        trading_mode=os.getenv("TRADING_MODE", "paper").strip().lower(),
        breeze_app_key=os.getenv("BREEZE_APP_KEY") or None,
        breeze_secret_key=os.getenv("BREEZE_SECRET_KEY") or None,
        static_ip_ready=_env_bool("STATIC_IP_READY", False),
        enforce_market_hours=_env_bool("ENFORCE_MARKET_HOURS", True),
        breeze_base_url=os.getenv(
            "BREEZE_BASE_URL", "https://api.icicidirect.com/breezeapi/api/v1"
        ),
        hermes_enabled=_env_bool("HERMES_ENABLED", False),
        hermes_base_url=os.getenv("HERMES_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/"),
        hermes_model=os.getenv("HERMES_MODEL", "hermes"),
        hermes_api_key=os.getenv("HERMES_API_KEY") or None,
        hermes_provider=os.getenv("HERMES_PROVIDER", "local").strip().lower(),
        hermes_timeout_seconds=int(os.getenv("HERMES_TIMEOUT_SECONDS", "20")),
        automation_enabled=_env_bool("AUTOMATION_ENABLED", False),
        auto_paper_scan_interval_seconds=int(os.getenv("AUTO_PAPER_SCAN_INTERVAL_SECONDS", "300")),
        auto_paper_monitor_interval_seconds=int(os.getenv("AUTO_PAPER_MONITOR_INTERVAL_SECONDS", "30")),
        auto_live_exit_interval_seconds=int(os.getenv("AUTO_LIVE_EXIT_INTERVAL_SECONDS", "15")),
        auto_live_entry_interval_seconds=int(os.getenv("AUTO_LIVE_ENTRY_INTERVAL_SECONDS", "300")),
        scanner_max_symbols_per_cycle=int(os.getenv("SCANNER_MAX_SYMBOLS_PER_CYCLE", "20")),
        auto_live_entries_enabled=_env_bool("AUTO_LIVE_ENTRIES_ENABLED", False),
        auto_live_exits_enabled=_env_bool("AUTO_LIVE_EXITS_ENABLED", False),
    )
