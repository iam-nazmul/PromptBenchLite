"""Built-in deterministic evaluators (SPEC §6.1): exact, contains, regex, json_schema."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema

from promptbench.evaluators.base import EvalContext, Evaluator, EvaluatorConfigError, Score
from promptbench.golden import Case
from promptbench.runner import Output


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _missing(key: str, field: str) -> Score:
    return Score.errored_score(key, f"output has no field {field!r}")


class ExactEvaluator(Evaluator):
    name = "exact"

    def __init__(self, *, field: str = "answer", normalize: bool = True, value: str | None = None) -> None:
        self.field = field
        self.normalize = normalize
        self.value = value

    def required_expected_fields(self) -> list[str]:
        return [] if self.value is not None else [self.field]

    def evaluate(self, case: Case, output: Output) -> list[Score]:
        actual = self.output_text(output)
        if actual is None:
            return [_missing(self.name, self.field)]
        expected = self.value if self.value is not None else str(case.expected.get(self.field, ""))
        ok = _norm(actual) == _norm(expected) if self.normalize else actual == expected
        return [
            Score(self.name, 1.0 if ok else 0.0, passed=ok, comment=None if ok else f"expected {expected!r}")
        ]


class ContainsEvaluator(Evaluator):
    name = "contains"

    def __init__(
        self, *, values: list[str], all: bool = True, case_sensitive: bool = False, field: str = "answer"
    ) -> None:
        if not values or not all_str(values):
            raise EvaluatorConfigError("contains: 'values' must be a non-empty list of strings")
        self.values = values
        self.require_all = all
        self.case_sensitive = case_sensitive
        self.field = field

    def evaluate(self, case: Case, output: Output) -> list[Score]:
        text = self.output_text(output)
        if text is None:
            return [_missing(self.name, self.field)]
        hay = text if self.case_sensitive else text.casefold()
        found = [v for v in self.values if (v if self.case_sensitive else v.casefold()) in hay]
        missing = [v for v in self.values if v not in found]
        ok = not missing if self.require_all else bool(found)
        return [
            Score(
                self.name,
                len(found) / len(self.values),
                passed=ok,
                comment=f"missing: {missing}" if missing else None,
            )
        ]


def all_str(values: Any) -> bool:
    return isinstance(values, list) and all(isinstance(v, str) for v in values)


class RegexEvaluator(Evaluator):
    name = "regex"

    def __init__(self, *, pattern: str, must_match: bool = True, field: str = "answer") -> None:
        try:
            self.pattern = re.compile(pattern, re.MULTILINE)
        except re.error as e:
            raise EvaluatorConfigError(f"regex: invalid pattern {pattern!r}: {e}") from e
        self.must_match = must_match
        self.field = field

    def evaluate(self, case: Case, output: Output) -> list[Score]:
        text = self.output_text(output)
        if text is None:
            return [_missing(self.name, self.field)]
        ok = bool(self.pattern.search(text)) == self.must_match
        verb = "did not match" if self.must_match else "matched"
        return [
            Score(
                self.name,
                1.0 if ok else 0.0,
                passed=ok,
                comment=None if ok else f"{verb} {self.pattern.pattern!r}",
            )
        ]


class JsonSchemaEvaluator(Evaluator):
    name = "json_schema"

    def __init__(self, *, schema: dict[str, Any], field: str | None = None) -> None:
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError as e:
            raise EvaluatorConfigError(f"json_schema: invalid schema: {e.message}") from e
        self.validator = jsonschema.Draft202012Validator(schema)
        self.field = field or ""

    @classmethod
    def from_config(cls, options: dict[str, Any], ctx: EvalContext) -> Evaluator:
        schema = options.get("schema")
        if isinstance(schema, str):
            path = ctx.config.path(Path(schema))
            try:
                options = {**options, "schema": json.loads(path.read_text(encoding="utf-8"))}
            except (OSError, json.JSONDecodeError) as e:
                raise EvaluatorConfigError(f"json_schema: cannot load schema file {path}: {e}") from e
        return super().from_config(options, ctx)

    def evaluate(self, case: Case, output: Output) -> list[Score]:
        if not self.field:
            instance: Any = output.data
        else:
            if self.field not in output.data:
                return [_missing(self.name, self.field)]
            instance = output.data[self.field]
            if isinstance(instance, str):
                try:
                    instance = json.loads(instance)
                except json.JSONDecodeError as e:
                    return [Score(self.name, 0.0, passed=False, comment=f"not valid JSON: {e}")]
        errors = sorted(self.validator.iter_errors(instance), key=lambda e: list(e.path))
        if errors:
            return [Score(self.name, 0.0, passed=False, comment="; ".join(e.message for e in errors[:3]))]
        return [Score(self.name, 1.0, passed=True)]
