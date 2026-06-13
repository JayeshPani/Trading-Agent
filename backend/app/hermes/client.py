from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class HermesSuggestion:
    suggestion_type: str
    title: str
    explanation: str
    proposed_change: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"


class HermesClient:
    """Interface boundary for Hermes.

    Hermes receives logs and metrics, returns suggestions, and never receives broker
    credentials or an order-placement capability.
    """

    async def analyze(self, payload: dict[str, Any]) -> list[HermesSuggestion]:
        errors = [log for log in payload.get("logs", []) if log.get("level") in {"ERROR", "WARNING"}]
        suggestions: list[HermesSuggestion] = []
        if errors:
            suggestions.append(
                HermesSuggestion(
                    suggestion_type="operational_review",
                    title="Review failed or rejected events",
                    explanation="Inspect API errors, risk rejections, and missed exits before changing strategy logic.",
                    proposed_change={"task": "review_error_clusters", "count": len(errors)},
                )
            )
        suggestions.append(
            HermesSuggestion(
                suggestion_type="backtest_experiment",
                title="Compare active strategy against baseline",
                explanation="Run an offline backtest before promoting any strategy change.",
                proposed_change={"requires_backtest": True, "requires_paper_pass": True},
            )
        )
        return suggestions
