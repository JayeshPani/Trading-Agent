from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SENSITIVE_KEYS = {
    "api_key",
    "api_secret",
    "session_token",
    "password",
    "otp",
    "token",
    "secret",
    "bank_password",
}


def redact_for_dashboard(payload: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        normalized = key.lower()
        if normalized in SENSITIVE_KEYS or any(marker in normalized for marker in ("secret", "password", "otp")):
            redacted[key] = "[REDACTED]"
        elif isinstance(value, Mapping):
            redacted[key] = redact_for_dashboard(value)
        else:
            redacted[key] = value
    return redacted
