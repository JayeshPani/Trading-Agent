from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Trading Agent"
    environment: str = "development"
    dashboard_api_token: str = Field(default="change-me-dev-token", repr=False)
    cors_origins: list[str] = ["http://localhost:5173", "chrome-extension://*"]
    database_url: str = "postgresql+psycopg://trading_agent:trading_agent@localhost:5432/trading_agent"
    redis_url: str = "redis://localhost:6379/0"
    default_mode: str = "paper"
    live_trading_enabled: bool = False
    require_manual_confirmation_live: bool = True
    breeze_api_key: str | None = Field(default=None, repr=False)
    breeze_api_secret: str | None = Field(default=None, repr=False)
    breeze_session_token: str | None = Field(default=None, repr=False)
    breeze_registered_static_ip: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
