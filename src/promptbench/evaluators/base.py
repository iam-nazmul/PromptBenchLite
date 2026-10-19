from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from promptbench.config import Config
    from promptbench.golden import Case
    from promptbench.runner import Output


@dataclass(frozen=True)
class Score:
    key: str
    value: float
    passed: bool | None = None
    comment: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        if self.error is None and not (0.0 <= self.value <= 1.0 and math.isfinite(self.value)):
            raise ValueError(f"score {self.key!r} value {self.value} outside [0, 1]")

    @property
    def errored(self) -> bool:
        return self.error is not None

    @classmethod
    def errored_score(cls, key: str, reason: str, **metadata: Any) -> Score:
        return cls(key=key, value=0.0, passed=None, comment=reason, metadata=metadata, error=reason)


@dataclass
class EvalContext:
    """What evaluators may need besides their own options. Tests inject fakes here."""

    config: Config
    anthropic_client_factory: Callable[[], Any] | None = None
    similarity_backend_factory: Callable[[], Any] | None = None
    cache: dict[str, Any] = field(default_factory=dict)


class EvaluatorConfigError(ValueError):
    """Bad evaluator options in a golden set; surfaced by `promptbench validate`."""


class Evaluator(ABC):
    name: ClassVar[str]
    field: str = "answer"

    @classmethod
    def from_config(cls, options: dict[str, Any], ctx: EvalContext) -> Evaluator:
        try:
            return cls(**options)
        except TypeError as e:
            raise EvaluatorConfigError(f"{cls.name}: {e}") from e

    @property
    def keys(self) -> list[str]:
        """Score keys this evaluator produces; used to record errored scores when the target fails."""
        return [self.name]

    def required_expected_fields(self) -> list[str]:
        """Fields that must exist in a case's ``expected``; checked by `promptbench validate`."""
        return []

    @abstractmethod
    def evaluate(self, case: Case, output: Output) -> list[Score]: ...

    def output_text(self, output: Output) -> str | None:
        value = output.data.get(self.field)
        if value is None:
            return None
        return value if isinstance(value, str) else str(value)
