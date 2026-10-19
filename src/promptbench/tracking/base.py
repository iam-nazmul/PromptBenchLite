from __future__ import annotations

from typing import Any, Protocol

from promptbench.golden import Suite
from promptbench.scoring.results import SuiteResult


class Tracker(Protocol):
    def record_suite(self, suite: Suite, result: SuiteResult, metadata: dict[str, Any]) -> list[str]:
        """Record a finished suite; set ``result.experiment``/``experiment_url``. Returns warnings."""
        ...


class NoopTracker:
    """Tracking off: same code path, nothing leaves the machine."""

    def record_suite(self, suite: Suite, result: SuiteResult, metadata: dict[str, Any]) -> list[str]:
        return []
