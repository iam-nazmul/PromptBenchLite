from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
TARGET = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$")

EvaluatorSpecs = dict[str, dict[str, Any] | None]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _json_safe(value: dict[str, Any], what: str) -> dict[str, Any]:
    try:
        json.dumps(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{what} must be JSON-serialisable: {e}") from e
    return value


class Case(_Strict):
    id: str
    inputs: dict[str, Any]
    expected: dict[str, Any] = Field(default_factory=dict)
    evaluators: EvaluatorSpecs = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    skip: str | None = None
    criteria: str | None = None

    @field_validator("id")
    @classmethod
    def _kebab_id(cls, v: str) -> str:
        if not KEBAB.match(v):
            raise ValueError(f"case id {v!r} must be kebab-case (a-z, 0-9, '-')")
        return v

    @field_validator("inputs")
    @classmethod
    def _inputs_json(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _json_safe(v, "inputs")

    @field_validator("expected")
    @classmethod
    def _expected_json(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _json_safe(v, "expected")

    @property
    def skipped(self) -> bool:
        return self.skip is not None


class Defaults(_Strict):
    evaluators: EvaluatorSpecs = Field(default_factory=dict)


class Suite(_Strict):
    suite: str
    target: str
    description: str = ""
    defaults: Defaults = Field(default_factory=Defaults)
    cases: list[Case]
    source: Path | None = Field(default=None, exclude=True)

    @field_validator("suite")
    @classmethod
    def _kebab_suite(cls, v: str) -> str:
        if not KEBAB.match(v):
            raise ValueError(f"suite name {v!r} must be kebab-case")
        return v

    @field_validator("target")
    @classmethod
    def _target_format(cls, v: str) -> str:
        if not TARGET.match(v):
            raise ValueError(f"target {v!r} must look like 'package.module:callable'")
        return v

    @model_validator(mode="after")
    def _unique_ids(self) -> Suite:
        if not self.cases:
            raise ValueError("a suite needs at least one case")
        ids = [c.id for c in self.cases]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate case ids: {dupes}")
        return self

    @property
    def name(self) -> str:
        return self.suite

    def evaluator_specs(self, case: Case) -> dict[str, dict[str, Any]]:
        """Suite defaults merged with the case's overrides; a ``null`` case override drops a default."""
        specs = {name: dict(opts or {}) for name, opts in self.defaults.evaluators.items()}
        for name, opts in case.evaluators.items():
            if opts is None:
                specs.pop(name, None)
            else:
                specs[name] = {**specs.get(name, {}), **opts}
        return specs

    def active_cases(self, tags: list[str] | None = None) -> list[Case]:
        cases = [c for c in self.cases if not c.skipped]
        if tags:
            cases = [c for c in cases if set(tags) & set(c.tags)]
        return cases
