"""Load and validate promptbench.toml (or [tool.promptbench] in pyproject.toml)."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from promptbench.errors import ConfigError

CONFIG_FILE = "promptbench.toml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrackingConfig(_Strict):
    enabled: bool = True
    project: str = "promptbench"
    required: bool = False


class SimilarityConfig(_Strict):
    backend: Literal["sentence_transformers", "lexical"] = "sentence_transformers"
    model: str = "all-MiniLM-L6-v2"
    min: float = Field(default=0.75, ge=0.0, le=1.0)


class JudgeConfig(_Strict):
    provider: Literal["anthropic", "fake"] = "anthropic"
    model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    samples: int = Field(default=1, ge=1, le=10)
    max_retries: int = Field(default=3, ge=0)
    max_tokens: int = Field(default=4000, ge=256)
    fallbacks: bool = True


class MetricGate(_Strict):
    max_drop: float | None = Field(default=None, ge=0.0, le=1.0)
    floor: float | None = Field(default=None, ge=0.0, le=1.0)


class GateConfig(_Strict):
    mode: Literal["enforce", "warn"] = "enforce"
    default_max_drop: float = Field(default=0.05, ge=0.0, le=1.0)
    min_cases: int = Field(default=5, ge=0)
    max_error_rate: float = Field(default=0.10, ge=0.0, le=1.0)
    metrics: dict[str, MetricGate] = Field(default_factory=dict)

    def max_drop_for(self, key: str) -> float:
        override = self.metrics.get(key)
        if override is not None and override.max_drop is not None:
            return override.max_drop
        return self.default_max_drop

    def floor_for(self, key: str) -> float | None:
        override = self.metrics.get(key)
        return override.floor if override is not None else None


class Config(_Strict):
    root: Path = Field(default_factory=Path.cwd, exclude=True)
    goldens_dir: Path = Path("goldens")
    baselines_dir: Path = Path("baselines")
    rubrics_dir: Path = Path("rubrics")
    concurrency: int = Field(default=4, ge=1, le=64)
    target_timeout_s: float = Field(default=60.0, gt=0)
    tracking: TrackingConfig = Field(default_factory=TrackingConfig)
    similarity: SimilarityConfig = Field(default_factory=SimilarityConfig)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    gate: GateConfig = Field(default_factory=GateConfig)

    def path(self, p: Path) -> Path:
        return p if p.is_absolute() else self.root / p

    @property
    def goldens_path(self) -> Path:
        return self.path(self.goldens_dir)

    @property
    def baselines_path(self) -> Path:
        return self.path(self.baselines_dir)

    @property
    def rubrics_path(self) -> Path:
        return self.path(self.rubrics_dir)


def _read_raw(root: Path) -> dict[str, Any]:
    dedicated = root / CONFIG_FILE
    if dedicated.exists():
        data = _load_toml(dedicated)
        section = data.get("promptbench")
        if not isinstance(section, dict):
            raise ConfigError(f"{dedicated}: missing [promptbench] table")
        return section
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        section = _load_toml(pyproject).get("tool", {}).get("promptbench")
        if isinstance(section, dict):
            return section
    return {}


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: invalid TOML: {e}") from e


def _apply_env(raw: dict[str, Any], env: Mapping[str, str]) -> None:
    if env.get("PROMPTBENCH_TRACKING", "").lower() in {"off", "false", "0", "no"}:
        raw.setdefault("tracking", {})["enabled"] = False
    if project := env.get("LANGSMITH_PROJECT"):
        raw.setdefault("tracking", {})["project"] = project
    if samples := env.get("PROMPTBENCH_JUDGE_SAMPLES"):
        try:
            raw.setdefault("judge", {})["samples"] = int(samples)
        except ValueError as e:
            raise ConfigError(f"PROMPTBENCH_JUDGE_SAMPLES must be an integer, got {samples!r}") from e


def load_config(root: Path | None = None, env: Mapping[str, str] | None = None) -> Config:
    """Load config from ``root`` (default: cwd), then apply environment overrides (SPEC §7)."""
    root = (root or Path.cwd()).resolve()
    raw = _read_raw(root)
    _apply_env(raw, os.environ if env is None else env)
    try:
        return Config(root=root, **raw)
    except ValidationError as e:
        raise ConfigError(f"invalid PromptBench config in {root}:\n{e}") from e
