import anthropic
import httpx2 as httpx
import pytest

from promptbench.evaluators import EvaluatorConfigError, create
from promptbench.evaluators.judge import FALLBACK_BETA, FakeJudgeBackend, JudgeRequest
from promptbench.golden import Case
from promptbench.runner import Output
from tests.conftest import verdict_response

CASE = Case(
    id="c",
    inputs={"question": "refund?"},
    expected={"answer": "30 days"},
    criteria="Must mention the window.",
)
OUT = Output({"answer": "Within 30 days."})


def judge(ctx, **options):
    return create("judge", {"rubric": "correctness", **options}, ctx)


@pytest.mark.parametrize(("raw", "value"), [(1, 0.0), (3, 0.5), (5, 1.0)])
def test_score_is_normalised(ctx, fake_anthropic, raw, value) -> None:
    fake_anthropic.respond = lambda kw: verdict_response(raw, reasoning="because")
    (s,) = judge(ctx).evaluate(CASE, OUT)
    assert s.key == "judge.correctness"
    assert s.value == value and s.passed is None and s.comment == "because"
    assert s.metadata["served_model"] == "claude-opus-5-5"


def test_request_shape(ctx, fake_anthropic) -> None:
    judge(ctx).evaluate(CASE, OUT)
    (call,) = fake_anthropic.calls
    assert call["endpoint"] == "beta.messages.parse"
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"] == {"effort": "medium"}
    assert "temperature" not in call and "thinking" not in call and "tool_choice" not in call
    (system,) = call["system"]
    assert system["cache_control"] == {"type": "ephemeral"}
    assert "<rubric>" in system["text"] and "Correctness" in system["text"]
    user = call["messages"][0]["content"]
    for part in ("<inputs>", "refund?", "<reference>\n30 days", "<criteria>", "<answer>\nWithin 30 days."):
        assert part in user


def test_fallbacks_disabled_uses_plain_parse(ctx, fake_anthropic) -> None:
    ctx.config.judge.fallbacks = False
    judge(ctx).evaluate(CASE, OUT)
    assert fake_anthropic.calls[0]["endpoint"] == "messages.parse"
    assert "fallbacks" not in fake_anthropic.calls[0]


def test_system_prompt_is_identical_across_cases(ctx, fake_anthropic) -> None:
    ev = judge(ctx)
    ev.evaluate(CASE, OUT)
    ev.evaluate(Case(id="d", inputs={"question": "other"}), Output({"answer": "x"}))
    assert fake_anthropic.calls[0]["system"] == fake_anthropic.calls[1]["system"]


@pytest.mark.parametrize(
    ("response", "fragment"),
    [
        (verdict_response(None, stop_reason="refusal"), "refusal: cyber"),
        (verdict_response(None, stop_reason="max_tokens"), "max_tokens"),
        (verdict_response(None), "no structured verdict"),
        (verdict_response(7), "outside 1-5"),
        (anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")), "connection error"),
        (
            anthropic.BadRequestError(
                "bad", response=httpx.Response(400, request=httpx.Request("POST", "https://x")), body=None
            ),
            "API error 400",
        ),
    ],
)
def test_failures_are_errored_not_zero(ctx, fake_anthropic, response, fragment) -> None:
    fake_anthropic.respond = lambda kw: response
    (s,) = judge(ctx).evaluate(CASE, OUT)
    assert s.errored and fragment in (s.error or "")


def test_samples_mean_and_partial_failures(ctx, fake_anthropic) -> None:
    responses = iter(
        [verdict_response(5), verdict_response(None, stop_reason="refusal"), verdict_response(3)]
    )
    fake_anthropic.respond = lambda kw: next(responses)
    (s,) = judge(ctx, samples=3).evaluate(CASE, OUT)
    assert s.value == pytest.approx(0.75)
    assert s.metadata["samples"] == [5, 3]
    assert s.metadata["failures"] == ["refusal: cyber"]
    assert len(fake_anthropic.calls) == 3


def test_fallback_served_model_is_recorded(ctx, fake_anthropic) -> None:
    fake_anthropic.respond = lambda kw: verdict_response(4, model="claude-opus-4-8")
    (s,) = judge(ctx).evaluate(CASE, OUT)
    assert s.metadata["served_model"] == "claude-opus-4-8"
    assert s.metadata["judge_model"] == "claude-opus-5-5"


def test_min_score_sets_passed(ctx, fake_anthropic) -> None:
    fake_anthropic.respond = lambda kw: verdict_response(3)
    assert judge(ctx, min_score=4).evaluate(CASE, OUT)[0].passed is False
    assert judge(ctx, min_score=3).evaluate(CASE, OUT)[0].passed is True


def test_client_is_created_lazily(ctx) -> None:
    created = []
    ctx.anthropic_client_factory = lambda: created.append(1) or None
    judge(ctx)
    assert created == []


@pytest.mark.parametrize(
    "options", [{"rubric": "missing"}, {"rubric": ""}, {"rubric": "correctness", "min_score": 9}, {"x": 1}]
)
def test_bad_options(ctx, options) -> None:
    with pytest.raises(EvaluatorConfigError):
        create("judge", options, ctx)


def test_fake_backend_is_deterministic() -> None:
    req = JudgeRequest(
        rubric="r", system="s", user="u", reference="refund in 30 days", answer="refund in 30 days"
    )
    assert FakeJudgeBackend().judge(req).score == 5
    req = JudgeRequest(rubric="r", system="s", user="u", reference="refund in 30 days", answer="hello")
    assert FakeJudgeBackend().judge(req).score == 1
