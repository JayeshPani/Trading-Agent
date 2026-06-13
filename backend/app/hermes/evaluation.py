from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromotionGate:
    backtest_passed: bool
    paper_trade_passed: bool
    human_approved: bool

    @property
    def can_promote(self) -> bool:
        return self.backtest_passed and self.paper_trade_passed and self.human_approved
