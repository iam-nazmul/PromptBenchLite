from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from promptbench.evaluators.base import EvalContext, Evaluator, EvaluatorConfigError
from promptbench.evaluators.deterministic import (
    ContainsEvaluator,
    ExactEvaluator,
    JsonSchemaEvaluator,
    RegexEvaluator,
)
from promptbench.evaluators.judge import JudgeEvaluator
from promptbench.evaluators.similarity import SimilarityEvaluator

BUILTINS: dict[str, type[Evaluator]] = {
    cls.name: cls
    for cls in (
        ExactEvaluator,
        ContainsEvaluator,
        RegexEvaluator,
        JsonSchemaEvaluator,
        SimilarityEvaluator,
        JudgeEvaluator,
    )
}

ENTRY_POINT_GROUP = "promptbench.evaluators"


def available() -> dict[str, type[Evaluator]]:
    """Built-ins plus third-party evaluators from the ``promptbench.evaluators`` entry-point group."""
    found: dict[str, type[Evaluator]] = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        if ep.name not in BUILTINS:
            found[ep.name] = ep.load()
    return {**found, **BUILTINS}


def create(name: str, options: dict[str, Any], ctx: EvalContext) -> Evaluator:
    registry = ctx.cache.get("registry")
    if registry is None:
        registry = ctx.cache["registry"] = available()
    cls = registry.get(name)
    if cls is None:
        raise EvaluatorConfigError(f"unknown evaluator {name!r}; available: {sorted(registry)}")
    return cls.from_config(options, ctx)
