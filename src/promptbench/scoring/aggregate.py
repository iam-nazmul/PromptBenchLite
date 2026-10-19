from __future__ import annotations

from dataclasses import dataclass

from promptbench.scoring.results import SuiteResult


@dataclass(frozen=True)
class MetricSummary:
    key: str
    mean: float | None
    n: int
    errored: int
    pass_rate: float | None


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize(result: SuiteResult) -> dict[str, MetricSummary]:
    """Per-key mean over non-errored scores of non-skipped cases (SPEC §8.1)."""
    summaries: dict[str, MetricSummary] = {}
    for key in result.keys:
        scores = [s for c in result.cases if (s := c.score(key)) is not None]
        ok = [s for s in scores if not s.errored]
        judged = [s.passed for s in ok if s.passed is not None]
        summaries[key] = MetricSummary(
            key=key,
            mean=mean([s.value for s in ok]),
            n=len(ok),
            errored=len(scores) - len(ok),
            pass_rate=(sum(judged) / len(judged)) if judged else None,
        )
    return summaries
