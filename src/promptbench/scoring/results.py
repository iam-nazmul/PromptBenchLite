from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from promptbench.evaluators.base import Score
from promptbench.runner import Output


@dataclass
class CaseResult:
    case_id: str
    inputs: dict[str, Any]
    expected: dict[str, Any]
    output: Output
    scores: list[Score]
    tags: list[str] = field(default_factory=list)

    def score(self, key: str) -> Score | None:
        return next((s for s in self.scores if s.key == key), None)


@dataclass
class SuiteResult:
    suite: str
    cases: list[CaseResult]
    skipped: list[str] = field(default_factory=list)
    judge_model: str | None = None
    experiment: str | None = None
    experiment_url: str | None = None

    @property
    def keys(self) -> list[str]:
        return sorted({s.key for c in self.cases for s in c.scores})

    def case_values(self) -> dict[str, dict[str, float | None]]:
        """``{case_id: {key: value}}`` with ``None`` for errored scores."""
        return {c.case_id: {s.key: None if s.errored else s.value for s in c.scores} for c in self.cases}

    def error_counts(self) -> tuple[int, int]:
        scores = [s for c in self.cases for s in c.scores]
        return sum(s.errored for s in scores), len(scores)
