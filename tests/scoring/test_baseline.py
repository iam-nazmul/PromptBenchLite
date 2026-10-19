import json

import pytest

from promptbench.errors import ConfigError
from promptbench.evaluators import Score
from promptbench.runner import Output
from promptbench.scoring import (
    CaseResult,
    SuiteResult,
    build_baseline,
    load_baseline,
    summarize,
    write_baseline,
)


def suite_result() -> SuiteResult:
    def case(cid: str, scores: list[Score]) -> CaseResult:
        return CaseResult(cid, {}, {}, Output({"answer": "x"}), scores)

    return SuiteResult(
        "demo",
        [
            case("a", [Score("m", 1.0, passed=True), Score("j", 0.5)]),
            case("b", [Score("m", 0.0, passed=False), Score.errored_score("j", "refusal")]),
            case("c", [Score.errored_score("m", "x"), Score.errored_score("j", "x")]),
        ],
        judge_model="claude-opus-5-5",
        experiment="demo-123",
    )


def test_summarize_excludes_errored() -> None:
    s = summarize(suite_result())
    assert (s["m"].mean, s["m"].n, s["m"].errored, s["m"].pass_rate) == (0.5, 2, 1, 0.5)
    assert (s["j"].mean, s["j"].n, s["j"].errored, s["j"].pass_rate) == (0.5, 1, 2, None)


def test_build_write_load_roundtrip(tmp_path) -> None:
    b = build_baseline(suite_result(), git_sha="abc")
    assert b.metrics["m"].mean == 0.5 and b.metrics["j"].n == 1
    assert b.cases == {"a": {"j": 0.5, "m": 1.0}, "b": {"m": 0.0}}
    assert (b.judge_model, b.langsmith_experiment, b.git_sha) == ("claude-opus-5-5", "demo-123", "abc")
    path = write_baseline(tmp_path / "baselines", b)
    assert path.read_text().endswith("}\n")
    assert json.loads(path.read_text())["suite"] == "demo"
    assert load_baseline(tmp_path / "baselines", "demo") == b


def test_missing_baseline_is_none(tmp_path) -> None:
    assert load_baseline(tmp_path, "nope") is None


def test_invalid_baseline_is_config_error(tmp_path) -> None:
    (tmp_path / "demo.json").write_text('{"suite": "demo"}')
    with pytest.raises(ConfigError, match="invalid baseline"):
        load_baseline(tmp_path, "demo")


def test_score_value_must_be_in_range() -> None:
    with pytest.raises(ValueError):
        Score("k", 1.5)
    assert Score.errored_score("k", "why").errored
