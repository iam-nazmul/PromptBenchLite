from typing import Any

import pytest

from promptbench.evaluators import EvalContext, EvaluatorConfigError, create
from promptbench.golden import Case
from promptbench.runner import Output

CASE = Case(id="c", inputs={"q": "x"}, expected={"answer": "Refunds within 30 days."})


def score(ctx: EvalContext, name: str, options: dict[str, Any], data: dict[str, Any], case: Case = CASE):
    (s,) = create(name, options, ctx).evaluate(case, Output(data=data))
    return s


@pytest.mark.parametrize(
    ("name", "options", "answer", "value", "passed"),
    [
        ("exact", {}, "refunds   within 30 DAYS.", 1.0, True),
        ("exact", {"normalize": False}, "refunds within 30 days.", 0.0, False),
        ("exact", {"value": "yes"}, "Yes", 1.0, True),
        ("contains", {"values": ["30 days", "refund"]}, "Refund in 30 DAYS", 1.0, True),
        ("contains", {"values": ["30 days", "receipt"]}, "Refund in 30 days", 0.5, False),
        ("contains", {"values": ["30 days", "receipt"], "all": False}, "Refund in 30 days", 0.5, True),
        ("contains", {"values": ["Days"], "case_sensitive": True}, "30 days", 0.0, False),
        ("regex", {"pattern": r"\d+ days"}, "within 30 days", 1.0, True),
        ("regex", {"pattern": r"(?i)sorry", "must_match": False}, "Sorry!", 0.0, False),
    ],
)
def test_text_evaluators(ctx, name, options, answer, value, passed) -> None:
    s = score(ctx, name, options, {"answer": answer})
    assert (s.value, s.passed, s.errored) == (value, passed, False)


@pytest.mark.parametrize("name", ["exact", "contains", "regex"])
def test_missing_output_field_is_errored(ctx, name) -> None:
    options = {"contains": {"values": ["x"]}, "regex": {"pattern": "x"}}.get(name, {})
    s = score(ctx, name, options, {"other": "x"})
    assert s.errored and "no field 'answer'" in (s.error or "")


SCHEMA = {"type": "object", "required": ["status"], "properties": {"status": {"enum": ["ok", "error"]}}}


@pytest.mark.parametrize(
    ("options", "data", "value"),
    [
        ({"schema": SCHEMA}, {"status": "ok"}, 1.0),
        ({"schema": SCHEMA}, {"status": "nope"}, 0.0),
        ({"schema": SCHEMA, "field": "answer"}, {"answer": '{"status": "error"}'}, 1.0),
        ({"schema": SCHEMA, "field": "answer"}, {"answer": "not json"}, 0.0),
    ],
)
def test_json_schema(ctx, options, data, value) -> None:
    assert score(ctx, "json_schema", options, data).value == value


def test_json_schema_from_file(ctx) -> None:
    path = ctx.config.root / "schema.json"
    path.write_text('{"type": "object", "required": ["a"]}')
    assert score(ctx, "json_schema", {"schema": "schema.json"}, {"a": 1}).value == 1.0


@pytest.mark.parametrize(
    ("name", "options"),
    [
        ("contains", {"values": []}),
        ("contains", {"values": "30 days"}),
        ("regex", {"pattern": "("}),
        ("json_schema", {"schema": {"type": "nonsense"}}),
        ("json_schema", {"schema": "missing.json"}),
        ("exact", {"unknown": 1}),
        ("nope", {}),
    ],
)
def test_bad_options_are_config_errors(ctx, name, options) -> None:
    with pytest.raises(EvaluatorConfigError):
        create(name, options, ctx)


def test_required_expected_fields(ctx) -> None:
    assert create("exact", {}, ctx).required_expected_fields() == ["answer"]
    assert create("exact", {"value": "x"}, ctx).required_expected_fields() == []
    assert create("contains", {"values": ["x"]}, ctx).required_expected_fields() == []
