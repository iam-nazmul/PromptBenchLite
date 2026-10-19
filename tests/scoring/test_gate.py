"""Table-driven tests for every gate rule in SPEC §8.3–8.5."""

from __future__ import annotations

import pytest

from promptbench.config import GateConfig, MetricGate
from promptbench.errors import EXIT_INFRA, EXIT_PASS, EXIT_REGRESSION
from promptbench.evaluators import Score
from promptbench.runner import Output
from promptbench.scoring import Baseline, CaseResult, RunVerdict, Status, SuiteResult, gate_suite
from promptbench.scoring.baseline import BaselineMetric

Values = dict[str, dict[str, float | None]]


def result(values: Values, skipped: list[str] | None = None, judge_model: str | None = None) -> SuiteResult:
    cases = [
        CaseResult(
            case_id=cid,
            inputs={},
            expected={},
            output=Output({"answer": "x"}),
            scores=[
                Score(k, v) if v is not None else Score.errored_score(k, "boom") for k, v in vals.items()
            ],
        )
        for cid, vals in values.items()
    ]
    return SuiteResult("s", cases, skipped=skipped or [], judge_model=judge_model)


def baseline(values: dict[str, dict[str, float]], judge_model: str | None = None) -> Baseline:
    keys = sorted({k for v in values.values() for k in v})
    metrics = {
        k: BaselineMetric(mean=sum(v[k] for v in values.values() if k in v) / len(values), n=len(values))
        for k in keys
    }
    return Baseline(suite="s", created_at="t", metrics=metrics, cases=values, judge_model=judge_model)


def uniform(n: int, **metrics: float | None) -> Values:
    return {f"c{i}": dict(metrics) for i in range(n)}


GATE = GateConfig(default_max_drop=0.05, min_cases=3, max_error_rate=0.1)


def status(v, key: str) -> Status:
    return next(m for m in v.metrics if m.key == key).status


@pytest.mark.parametrize(
    ("current", "base", "gate", "expected"),
    [
        pytest.param(uniform(5, m=0.80), uniform(5, m=0.80), GATE, Status.PASS, id="unchanged"),
        pytest.param(uniform(5, m=0.76), uniform(5, m=0.80), GATE, Status.PASS, id="drop-within-threshold"),
        pytest.param(uniform(5, m=0.75), uniform(5, m=0.80), GATE, Status.PASS, id="drop-exactly-threshold"),
        pytest.param(uniform(5, m=0.74), uniform(5, m=0.80), GATE, Status.FAIL, id="drop-beyond-threshold"),
        pytest.param(uniform(5, m=0.95), uniform(5, m=0.80), GATE, Status.PASS, id="improvement"),
        pytest.param(
            uniform(5, m=0.79),
            uniform(5, m=0.80),
            GateConfig(min_cases=3, metrics={"m": MetricGate(max_drop=0.0)}),
            Status.FAIL,
            id="per-metric-zero-tolerance",
        ),
        pytest.param(
            uniform(5, m=0.60),
            uniform(5, m=0.60),
            GateConfig(min_cases=3, metrics={"m": MetricGate(floor=0.7)}),
            Status.FAIL,
            id="below-floor-without-drop",
        ),
        pytest.param(uniform(2, m=0.10), uniform(2, m=0.90), GATE, Status.WARN, id="few-cases-warn-not-fail"),
    ],
)
def test_metric_rules(current: Values, base, gate: GateConfig, expected: Status) -> None:
    v = gate_suite(result(current), baseline(base), gate)
    assert status(v, "m") is expected
    assert v.failed is (expected is Status.FAIL)


def test_new_metric_is_reported_not_gated() -> None:
    v = gate_suite(result(uniform(5, m=0.8, new=0.1)), baseline(uniform(5, m=0.8)), GATE)
    assert status(v, "new") is Status.NEW and not v.failed


def test_missing_metric_fails() -> None:
    v = gate_suite(result(uniform(5, other=0.8)), baseline(uniform(5, m=0.8, other=0.8)), GATE)
    assert status(v, "m") is Status.FAIL and "missing" in v.metrics[0].reason


def test_all_errored_metric_counts_as_missing() -> None:
    v = gate_suite(result(uniform(5, m=None)), baseline(uniform(5, m=0.8)), GateConfig(max_error_rate=1.0))
    assert status(v, "m") is Status.FAIL


def test_no_baseline_reports_new_and_warns() -> None:
    v = gate_suite(result(uniform(5, m=0.1)), None, GATE)
    assert not v.has_baseline and not v.failed
    assert all(m.status is Status.NEW for m in v.metrics)
    assert "no baseline" in v.warnings[0]


def test_only_common_case_ids_are_compared() -> None:
    base = {"a": {"m": 1.0}, "b": {"m": 1.0}, "c": {"m": 1.0}, "gone": {"m": 0.0}}
    current: Values = {"a": {"m": 1.0}, "b": {"m": 1.0}, "c": {"m": 1.0}, "new": {"m": 0.0}}
    v = gate_suite(result(current), baseline(base), GATE)
    m = v.metrics[0]
    assert m.status is Status.PASS
    assert (m.baseline_mean, m.compared_current_mean, m.n_compared) == (1.0, 1.0, 3)
    assert m.current_mean == 0.75
    assert v.added_cases == ["new"] and v.removed_cases == ["gone"]


def test_skipped_cases_are_not_reported_as_removed() -> None:
    base = {f"c{i}": {"m": 1.0} for i in range(4)}
    current = {f"c{i}": {"m": 1.0} for i in range(3)}
    v = gate_suite(result(current, skipped=["c3"]), baseline(base), GATE)
    assert v.removed_cases == []


def test_no_overlap_warns() -> None:
    v = gate_suite(result({"x": {"m": 0.0}}), baseline({"y": {"m": 1.0}}), GATE)
    assert status(v, "m") is Status.WARN


def test_judge_model_mismatch_warns() -> None:
    v = gate_suite(
        result(uniform(5, m=0.8)), baseline(uniform(5, m=0.8), judge_model="a"), GATE, judge_model="b"
    )
    assert any("differs from baseline" in w for w in v.warnings) and not v.failed


@pytest.mark.parametrize(("errored", "infra"), [(0, False), (1, False), (2, True)])
def test_error_rate(errored: int, infra: bool) -> None:
    values: Values = {f"c{i}": {"m": None if i < errored else 0.8} for i in range(10)}
    v = gate_suite(result(values), baseline(uniform(10, m=0.8)), GATE)
    assert v.errored == errored and v.total == 10
    assert v.infra_error is infra


def test_regressions_sorted_worst_first() -> None:
    current: Values = {"a": {"m": 0.9}, "b": {"m": 0.2}, "c": {"m": 1.0}}
    base = {"a": {"m": 1.0}, "b": {"m": 1.0}, "c": {"m": 1.0}}
    v = gate_suite(result(current), baseline(base), GATE)
    assert [(r.case_id, round(r.delta, 2)) for r in v.regressions] == [("b", -0.8), ("a", -0.1)]


def test_rounding_noise_is_not_a_regression() -> None:
    v = gate_suite(result({"a": {"m": 0.7142857}}), baseline({"a": {"m": 0.714286}}), GATE)
    assert v.regressions == []


@pytest.mark.parametrize(
    ("failed", "infra", "mode", "code"),
    [
        (False, False, "enforce", EXIT_PASS),
        (True, False, "enforce", EXIT_REGRESSION),
        (True, False, "warn", EXIT_PASS),
        (False, True, "enforce", EXIT_INFRA),
        (True, True, "enforce", EXIT_INFRA),
        (True, True, "warn", EXIT_INFRA),
    ],
)
def test_exit_codes(failed: bool, infra: bool, mode: str, code: int) -> None:
    current = uniform(5, m=0.1 if failed else 0.8)
    if infra:
        current = {**current, **{f"e{i}": {"m": None} for i in range(5)}}
    v = gate_suite(result(current), baseline(uniform(5, m=0.8)), GATE)
    assert RunVerdict([v], mode=mode).exit_code == code
