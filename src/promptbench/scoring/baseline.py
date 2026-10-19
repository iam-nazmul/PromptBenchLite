"""Baseline files: baselines/<suite>.json (SPEC §8.2). Written only by `promptbench baseline update`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from promptbench import __version__
from promptbench.errors import ConfigError
from promptbench.scoring.aggregate import summarize
from promptbench.scoring.results import SuiteResult


class BaselineMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mean: float
    n: int


class Baseline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suite: str
    created_at: str
    git_sha: str | None = None
    langsmith_experiment: str | None = None
    promptbench_version: str = __version__
    judge_model: str | None = None
    metrics: dict[str, BaselineMetric] = Field(default_factory=dict)
    cases: dict[str, dict[str, float]] = Field(default_factory=dict)


def baseline_path(baselines_dir: Path, suite: str) -> Path:
    return baselines_dir / f"{suite}.json"


def load_baseline(baselines_dir: Path, suite: str) -> Baseline | None:
    path = baseline_path(baselines_dir, suite)
    if not path.exists():
        return None
    try:
        return Baseline.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as e:
        raise ConfigError(f"{path}: invalid baseline file:\n{e}") from e


def build_baseline(result: SuiteResult, git_sha: str | None = None) -> Baseline:
    metrics = {
        key: BaselineMetric(mean=round(m.mean, 6), n=m.n)
        for key, m in summarize(result).items()
        if m.mean is not None
    }
    cases = {
        case_id: {k: round(v, 6) for k, v in sorted(values.items()) if v is not None}
        for case_id, values in sorted(result.case_values().items())
    }
    return Baseline(
        suite=result.suite,
        created_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        git_sha=git_sha,
        langsmith_experiment=result.experiment,
        judge_model=result.judge_model,
        metrics=dict(sorted(metrics.items())),
        cases={k: v for k, v in cases.items() if v},
    )


def write_baseline(baselines_dir: Path, baseline: Baseline) -> Path:
    baselines_dir.mkdir(parents=True, exist_ok=True)
    path = baseline_path(baselines_dir, baseline.suite)
    path.write_text(json.dumps(baseline.model_dump(), indent=2) + "\n", encoding="utf-8")
    return path
