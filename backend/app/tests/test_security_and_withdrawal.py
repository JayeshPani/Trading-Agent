from __future__ import annotations

from datetime import date

import pytest

from app.broker.base import BrokerMode
from app.broker.breeze_adapter import BreezeAdapterConfig
from app.broker.factory import BrokerFactoryConfig, build_broker
from app.core.redaction import redact_for_dashboard
from app.withdrawal.checklist import manual_withdrawal_checklist
from app.withdrawal.readiness import WithdrawalReadiness


def test_api_keys_are_never_sent_to_browser_payloads() -> None:
    payload = {"api_key": "abc", "nested": {"api_secret": "def"}, "mode": "paper"}
    redacted = redact_for_dashboard(payload)
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["api_secret"] == "[REDACTED]"
    assert redacted["mode"] == "paper"


def test_live_broker_cannot_start_unless_flag_enabled() -> None:
    config = BrokerFactoryConfig(
        mode=BrokerMode.LIVE,
        breeze=BreezeAdapterConfig(api_key="key", api_secret="secret", session_token="token"),
    )
    with pytest.raises(RuntimeError, match="LIVE_TRADING_ENABLED"):
        build_broker(config)


@pytest.mark.asyncio
async def test_withdrawal_module_does_not_automate_otp_or_password() -> None:
    status = await WithdrawalReadiness().check(broker_withdrawable_balance=None, trade_date=date(2026, 1, 1))
    checklist = manual_withdrawal_checklist()
    assert status.automation_enabled is False
    assert any("Do not share or store OTPs" in item for item in checklist)
