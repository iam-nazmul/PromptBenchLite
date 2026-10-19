import time

import pytest

from promptbench import pipeline
from promptbench.errors import EXIT_INFRA, EXIT_PASS, EXIT_REGRESSION, ConfigError
from promptbench.evaluators import EvalContext, Evaluator, Score
from promptbench.golden import Case
from promptbench.runner import Output, resolve_target, run_targets
from promptbench.scoring import build_baseline, write_baseline


def run(project, **kwargs):
    config = project.config()
    return config, pipeline.run(config, EvalContext(config=config), **kwargs)


def test_run_without_baseline_passes(make_project) -> None:
    _, outcome = run(make_project())
    (result,) = outcome.results
    assert [c.case_id for c in result.cases] == ["refund", "cancel", "password", "invoice", "email"]
    assert result.skipped == ["skipped-case"]
    assert result.judge_model == "fake-judge"
    assert outcome.verdict.exit_code == EXIT_PASS
    assert "git_sha" in outcome.metadata or "promptbench_version" in outcome.metadata


def test_regression_against_baseline(make_project) -> None:
    project = make_project()
    config, outcome = run(project)
    write_baseline(config.baselines_path, build_baseline(outcome.results[0]))
    project.set_answers(
        {k: "Please check the help centre." for k in ("refund", "cancel", "password", "invoice", "email")}
    )
    _, outcome = run(project)
    assert outcome.verdict.exit_code == EXIT_REGRESSION
    assert outcome.verdict.suites[0].regressions


def test_target_errors_make_errored_scores_and_infra_exit(make_project) -> None:
    project = make_project()
    project.set_answers({}, fail_on={"refund", "cancel"})
    _, outcome = run(project)
    case = outcome.results[0].cases[0]
    assert case.output.errored and all(s.errored for s in case.scores)
    assert {s.key for s in case.scores} == {"similarity", "judge.correctness", "contains"}
    assert outcome.verdict.exit_code == EXIT_INFRA


def test_tag_filter(make_project) -> None:
    _, outcome = run(make_project(), tags=["account"])
    assert [c.case_id for c in outcome.results[0].cases] == ["password", "email"]


def test_plan_collects_all_problems(make_project) -> None:
    cases = """\
cases:
  - id: a
    inputs: {question: refund}
    evaluators: {regex: {pattern: "("}}
  - id: b
    inputs: {question: refund}
    expected: {}
"""
    project = make_project(cases=cases, defaults="exact: {}")
    with pytest.raises(ConfigError) as e:
        pipeline.validate(project.config(), EvalContext(config=project.config()))
    msg = str(e.value)
    assert "demo/a: regex: invalid pattern" in msg
    assert "demo/b: evaluator 'exact' needs expected.answer" in msg


def test_validate_checks_target_import(make_project) -> None:
    project = make_project()
    project.golden_path().write_text(
        project.golden_path().read_text().replace(project.module, "no_such_module")
    )
    with pytest.raises(ConfigError, match="cannot import target module"):
        pipeline.validate(project.config(), EvalContext(config=project.config()))


def test_crashing_evaluator_is_errored() -> None:
    class Crash(Evaluator):
        name = "crash"

        def evaluate(self, case, output):
            raise ZeroDivisionError("oops")

    result = pipeline.evaluate_case(Case(id="a", inputs={}), Output({"answer": "x"}), [Crash()])
    (s,) = result.scores
    assert s.errored and "ZeroDivisionError" in (s.error or "")


def test_run_targets_timeout_and_shapes() -> None:
    def target(question: str):
        if question == "slow":
            time.sleep(1)
        if question == "dict":
            return {"answer": "d", "extra": 1}
        if question == "bad":
            return 42
        return question.upper()

    cases = [Case(id=i, inputs={"question": i}) for i in ("fast", "slow", "dict", "bad")]
    outs = run_targets(target, cases, concurrency=4, timeout_s=0.3)
    assert outs[0].data == {"answer": "FAST"}
    assert outs[1].errored and "TimeoutError" in (outs[1].error or "")
    assert outs[2].data == {"answer": "d", "extra": 1}
    assert outs[3].errored and "must return str or dict" in (outs[3].error or "")


def test_async_target() -> None:
    async def target(question: str) -> str:
        return question

    (out,) = run_targets(target, [Case(id="a", inputs={"question": "hi"})], concurrency=1, timeout_s=5)
    assert out.data == {"answer": "hi"}


@pytest.mark.parametrize("spec", ["json:nope", "json:dumps.nope", "no_such_mod:x", "json:__name__"])
def test_resolve_target_errors(spec) -> None:
    with pytest.raises(ConfigError):
        resolve_target(spec)


def test_scores_keep_evaluator_order(make_project) -> None:
    _, outcome = run(make_project())
    assert [s.key for s in outcome.results[0].cases[0].scores] == [
        "similarity",
        "judge.correctness",
        "contains",
    ]
    assert isinstance(outcome.results[0].cases[0].scores[0], Score)
