from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count

from app.hermes.client import HermesSuggestion


@dataclass
class SuggestionManager:
    _suggestions: dict[int, HermesSuggestion] = field(default_factory=dict)
    _ids: count = field(default_factory=lambda: count(1))

    def add_many(self, suggestions: list[HermesSuggestion]) -> list[tuple[int, HermesSuggestion]]:
        stored = []
        for suggestion in suggestions:
            suggestion_id = next(self._ids)
            self._suggestions[suggestion_id] = suggestion
            stored.append((suggestion_id, suggestion))
        return stored

    def list(self) -> list[tuple[int, HermesSuggestion]]:
        return list(self._suggestions.items())

    def approve(self, suggestion_id: int) -> HermesSuggestion:
        suggestion = self._get(suggestion_id)
        updated = HermesSuggestion(
            suggestion.suggestion_type,
            suggestion.title,
            suggestion.explanation,
            suggestion.proposed_change,
            "approved",
        )
        self._suggestions[suggestion_id] = updated
        return updated

    def reject(self, suggestion_id: int) -> HermesSuggestion:
        suggestion = self._get(suggestion_id)
        updated = HermesSuggestion(
            suggestion.suggestion_type,
            suggestion.title,
            suggestion.explanation,
            suggestion.proposed_change,
            "rejected",
        )
        self._suggestions[suggestion_id] = updated
        return updated

    def _get(self, suggestion_id: int) -> HermesSuggestion:
        try:
            return self._suggestions[suggestion_id]
        except KeyError as exc:
            raise KeyError(f"unknown suggestion id {suggestion_id}") from exc
