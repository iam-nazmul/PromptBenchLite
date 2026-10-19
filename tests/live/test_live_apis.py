"""Real Anthropic / LangSmith calls. Skipped unless PROMPTBENCH_LIVE=1; run nightly, not on PRs."""

import os

import pytest

from promptbench.config import JudgeConfig
from promptbench.evaluators.judge import (
    JUDGE_INSTRUCTIONS,
    AnthropicJudgeBackend,
    JudgeRequest,
    _default_client,
)

pytestmark = pytest.mark.live

RUBRIC = """# Correctness
5 — states the refund window of 30 days. 3 — mentions refunds but not the window. 1 — wrong or unrelated."""


@pytest.mark.parametrize(
    ("answer", "lo", "hi"), [("Refunds are accepted within 30 days.", 4, 5), ("Bananas.", 1, 2)]
)
def test_anthropic_judge_structure(answer: str, lo: int, hi: int) -> None:
    cfg = JudgeConfig(effort="low")
    backend = AnthropicJudgeBackend(lambda: _default_client(cfg), cfg)
    verdict = backend.judge(
        JudgeRequest(
            rubric="correctness",
            system=JUDGE_INSTRUCTIONS.format(rubric=RUBRIC),
            user=f'<inputs>{{"question": "refund window?"}}</inputs>\n<answer>\n{answer}\n</answer>',
            reference="You can get a refund within 30 days.",
            answer=answer,
        )
    )
    assert lo <= verdict.score <= hi
    assert verdict.reasoning and verdict.served_model


@pytest.mark.skipif(not os.environ.get("LANGSMITH_API_KEY"), reason="LANGSMITH_API_KEY not set")
def test_langsmith_round_trip(make_project) -> None:
    from langsmith import Client

    from promptbench import pipeline
    from promptbench.evaluators import EvalContext
    from promptbench.tracking.langsmith import LangSmithTracker, fetch_experiment_scores

    project = make_project()
    config = project.config()
    client = Client()
    outcome = pipeline.run(
        config, EvalContext(config=config), tracker=LangSmithTracker(client, "promptbench-live")
    )
    assert not outcome.warnings, outcome.warnings
    experiment = outcome.results[0].experiment
    assert experiment
    scores = fetch_experiment_scores(client, experiment)
    assert "refund" in scores and "judge.correctness" in scores["refund"]
