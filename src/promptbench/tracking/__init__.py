from __future__ import annotations

import os
from collections.abc import Mapping

from promptbench.config import Config
from promptbench.errors import InfraError
from promptbench.tracking.base import NoopTracker, Tracker


def make_tracker(
    config: Config, *, disabled: bool = False, env: Mapping[str, str] | None = None
) -> tuple[Tracker, list[str]]:
    """Pick the tracker for this run. Returns ``(tracker, warnings)``."""
    env = os.environ if env is None else env
    if disabled or not config.tracking.enabled:
        return NoopTracker(), []
    if not env.get("LANGSMITH_API_KEY"):
        if config.tracking.required:
            raise InfraError("tracking.required is true but LANGSMITH_API_KEY is not set")
        return NoopTracker(), ["LANGSMITH_API_KEY not set; LangSmith tracking disabled for this run"]
    from langsmith import Client

    from promptbench.tracking.langsmith import LangSmithTracker

    return (
        LangSmithTracker(
            Client(),
            config.tracking.project,
            required=config.tracking.required,
            max_concurrency=config.concurrency,
        ),
        [],
    )


__all__ = ["NoopTracker", "Tracker", "make_tracker"]
