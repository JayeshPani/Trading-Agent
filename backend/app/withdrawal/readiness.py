from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True)
class WithdrawalStatus:
    withdrawable_balance: float | None
    settled: bool
    estimated_settlement_date: date | None
    message: str
    automation_enabled: bool = False


class WithdrawalReadiness:
    async def check(self, *, broker_withdrawable_balance: float | None, trade_date: date) -> WithdrawalStatus:
        if broker_withdrawable_balance is None:
            return WithdrawalStatus(
                withdrawable_balance=None,
                settled=False,
                estimated_settlement_date=trade_date + timedelta(days=1),
                message="Broker withdrawable balance is unavailable; verify manually in ICICI Direct.",
            )
        settled = broker_withdrawable_balance > 0
        return WithdrawalStatus(
            withdrawable_balance=broker_withdrawable_balance,
            settled=settled,
            estimated_settlement_date=None if settled else trade_date + timedelta(days=1),
            message="Funds appear withdrawable" if settled else "Funds are not withdrawable yet",
        )
