from __future__ import annotations


def manual_withdrawal_checklist() -> list[str]:
    return [
        "Confirm all intraday positions are closed.",
        "Confirm there are no pending orders.",
        "Check the broker-reported withdrawable balance.",
        "Confirm settlement status and estimated payout date.",
        "Use only the official ICICI Direct flow for any payout-related action.",
        "Do not share or store OTPs, broker passwords, or bank credentials.",
    ]
