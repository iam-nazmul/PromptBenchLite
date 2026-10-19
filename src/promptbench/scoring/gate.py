"""The regression gate (SPEC §8.3–8.5). Pure functions: no I/O, no network."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from promptbench.config import GateConfig
from promptbench.errors import EXIT_INFRA, EXIT_PASS, EXIT_REGRESSION
from promptbench.scoring.aggregate import mean
from promptbench.scoring.baseline import Baseline
from promptbench.scoring.results import SuiteResult

EPS = 1e-6  # baselines store 6 decimals


class Status(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    NEW = "new"


@dataclass(frozen=True)
class MetricVerdict:
    key: str
    status: Status
    current_mean: float | None
    baseline_mean: float | None = None
    compared_current_mean: float | None = None
    delta: float | None = None
    max_drop: float | None = None
    floor: float | None = None
    n_compared: int = 0
    reason: str = ""


@dataclass(frozen=True)
class CaseRegression:
    case_id: str
    key: str
    before: float
    after: float

    @property
    def delta(self) -> float:
        return self.after - self.before


@dataclass
class SuiteVerdict:
    suite: str
    metrics: list[MetricVerdict]
    has_baseline: bool
    added_cases: list[str] = field(default_factory=list)
    removed_cases: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errored: int = 0
    total: int = 0
    infra_error: bool = False
    regressions: list[CaseRegression] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(m.status is Status.FAIL for m in self.metrics)

    @property
    def error_rate(self) -> float:
        return self.errored / self.total if self.total else 0.0


@dataclass
class RunVerdict:
    suites: list[SuiteVerdict]
    mode: str = "enforce"

    @property
    def infra_error(self) -> bool:
        return any(s.infra_error for s in self.suites)

    @property
    def regressed(self) -> bool:
        return any(s.failed for s in self.suites)

    @property
    def exit_code(self) -> int:
        if self.infra_error:
            return EXIT_INFRA
        if self.regressed and self.mode == "enforce":
            return EXIT_REGRESSION
        return EXIT_PASS


def gate_suite(
    result: SuiteResult, baseline: Baseline | None, gate: GateConfig, judge_model: str | None = None
) -> SuiteVerdict:
    current = result.case_values()
    errored, total = result.error_counts()
    verdict = SuiteVerdict(
        suite=result.suite, metrics=[], has_baseline=baseline is not None, errored=errored, total=total
    )
    if total and errored / total > gate.max_error_rate + EPS:
        verdict.infra_error = True
        verdict.warnings.append(
            f"{errored}/{total} evaluations errored ({errored / total:.0%}) > max_error_rate "
            f"{gate.max_error_rate:.0%}; results are not trustworthy"
        )

    if baseline is None:
        verdict.warnings.append("no baseline for this suite; metrics are reported, not gated")
        verdict.metrics = [
            MetricVerdict(key, Status.NEW, _full_mean(current, key), reason="no baseline")
            for key in result.keys
        ]
        return verdict

    verdict.added_cases = sorted(current.keys() - baseline.cases.keys())
    verdict.removed_cases = sorted(baseline.cases.keys() - current.keys() - set(result.skipped))
    if judge_model and baseline.judge_model and judge_model != baseline.judge_model:
        verdict.warnings.append(
            f"judge model {judge_model!r} differs from baseline's {baseline.judge_model!r}; "
            "scores from different graders are not directly comparable — re-baseline deliberately"
        )

    for key in sorted(set(result.keys) | baseline.metrics.keys()):
        verdict.metrics.append(_gate_metric(key, current, baseline, gate))
    verdict.regressions = _regressions(current, baseline)
    return verdict


def _full_mean(current: dict[str, dict[str, float | None]], key: str) -> float | None:
    return mean([v for vals in current.values() if (v := vals.get(key)) is not None])


def _gate_metric(
    key: str, current: dict[str, dict[str, float | None]], baseline: Baseline, gate: GateConfig
) -> MetricVerdict:
    full_mean = _full_mean(current, key)
    if key not in baseline.metrics:
        return MetricVerdict(key, Status.NEW, full_mean, reason="not in baseline; not gated")
    b_overall = baseline.metrics[key].mean
    max_drop, floor = gate.max_drop_for(key), gate.floor_for(key)
    if full_mean is None:
        return MetricVerdict(
            key,
            Status.FAIL,
            None,
            baseline_mean=b_overall,
            max_drop=max_drop,
            floor=floor,
            reason="metric missing from this run (evaluator removed, broken, or all scores errored)",
        )

    common = sorted(
        cid
        for cid, vals in current.items()
        if vals.get(key) is not None and key in baseline.cases.get(cid, {})
    )
    if not common:
        return MetricVerdict(
            key, Status.WARN, full_mean, baseline_mean=b_overall, max_drop=max_drop, floor=floor,
            reason="no case ids in common with the baseline",
        )  # fmt: skip

    b_mean = mean([baseline.cases[c][key] for c in common]) or 0.0
    c_mean = mean([v for c in common if (v := current[c][key]) is not None]) or 0.0
    delta = c_mean - b_mean
    problems = []
    if -delta > max_drop + EPS:
        problems.append(f"dropped {-delta:.3f} > max_drop {max_drop:.3f}")
    if floor is not None and full_mean < floor - EPS:
        problems.append(f"mean {full_mean:.3f} < floor {floor:.3f}")

    status, reason = Status.PASS, ""
    if problems:
        status, reason = Status.FAIL, "; ".join(problems)
        if len(common) < gate.min_cases:
            status = Status.WARN
            reason += f" (only {len(common)} comparable cases < min_cases {gate.min_cases}; not failing)"
    return MetricVerdict(
        key,
        status,
        full_mean,
        baseline_mean=b_mean,
        compared_current_mean=c_mean,
        delta=delta,
        max_drop=max_drop,
        floor=floor,
        n_compared=len(common),
        reason=reason,
    )


def _regressions(current: dict[str, dict[str, float | None]], baseline: Baseline) -> list[CaseRegression]:
    found = [
        CaseRegression(cid, key, before, after)
        for cid, vals in current.items()
        for key, after in vals.items()
        if after is not None
        and (before := baseline.cases.get(cid, {}).get(key)) is not None
        and after < before - EPS
    ]
    return sorted(found, key=lambda r: (r.delta, r.case_id, r.key))
