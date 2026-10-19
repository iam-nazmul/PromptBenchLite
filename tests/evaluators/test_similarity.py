import pytest

from promptbench.evaluators import EvaluatorConfigError, create
from promptbench.evaluators.similarity import LexicalBackend, SimilarityEvaluator
from promptbench.golden import Case
from promptbench.runner import Output

CASE = Case(id="c", inputs={}, expected={"answer": "refund within 30 days"})


def test_uses_injected_backend_and_config_min(ctx) -> None:
    (s,) = create("similarity", {}, ctx).evaluate(CASE, Output({"answer": "refund within 30 days"}))
    assert s.value == 1.0 and s.passed is True
    assert s.metadata == {"model": "stub"}
    assert ctx.config.similarity.min == 0.75


def test_below_min_fails_with_comment(ctx) -> None:
    (s,) = create("similarity", {"min": 0.9}, ctx).evaluate(CASE, Output({"answer": "refund later"}))
    assert s.value == 0.5 and s.passed is False and "min 0.90" in (s.comment or "")


@pytest.mark.parametrize(("raw", "clipped"), [(-0.3, 0.0), (1.2, 1.0), (0.4, 0.4)])
def test_value_is_clipped(raw, clipped) -> None:
    class Fixed:
        model_name = "fixed"

        def similarity(self, a: str, b: str) -> float:
            return raw

    (s,) = SimilarityEvaluator(backend=Fixed(), min=0.5).evaluate(CASE, Output({"answer": "x"}))
    assert s.value == clipped


def test_backend_failure_is_errored() -> None:
    class Broken:
        model_name = "broken"

        def similarity(self, a: str, b: str) -> float:
            raise RuntimeError("model download failed")

    (s,) = SimilarityEvaluator(backend=Broken(), min=0.5).evaluate(CASE, Output({"answer": "x"}))
    assert s.errored and "model download failed" in (s.error or "")


def test_missing_field_is_errored(ctx) -> None:
    (s,) = create("similarity", {}, ctx).evaluate(CASE, Output({"text": "x"}))
    assert s.errored


@pytest.mark.parametrize("options", [{"min": 2}, {"model": "other"}])
def test_bad_options(ctx, options) -> None:
    with pytest.raises(EvaluatorConfigError):
        create("similarity", options, ctx)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("Refund in 30 days", "refund in 30 DAYS!", 1.0),
        ("a b", "c d", 0.0),
        ("", "", 1.0),
        ("a b", "a c", 1 / 3),
    ],
)
def test_lexical_backend(a, b, expected) -> None:
    assert LexicalBackend().similarity(a, b) == pytest.approx(expected)
