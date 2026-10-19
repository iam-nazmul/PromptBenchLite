"""Semantic similarity evaluator (SPEC §6.2). See .claude/references/similarity.md."""

from __future__ import annotations

import re
import threading
from typing import Any, Protocol

from promptbench.evaluators.base import EvalContext, Evaluator, EvaluatorConfigError, Score
from promptbench.golden import Case
from promptbench.runner import Output


class SimilarityBackend(Protocol):
    model_name: str

    def similarity(self, a: str, b: str) -> float: ...


class SentenceTransformersBackend:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                except ImportError as e:
                    raise RuntimeError(
                        "similarity backend 'sentence_transformers' needs the extra: "
                        "uv add 'promptbench-lite[similarity]' (or set similarity.backend = 'lexical')"
                    ) from e
                model = SentenceTransformer(self.model_name)
                model.similarity_fn_name = "cosine"
                self._model = model
            return self._model

    def similarity(self, a: str, b: str) -> float:
        model = self._load()
        emb = model.encode([a, b], normalize_embeddings=True)
        return float(model.similarity(emb[0:1], emb[1:2])[0][0])


_TOKEN = re.compile(r"\w+")


class LexicalBackend:
    """Token-overlap (Jaccard) similarity. Offline and dependency-free; for demos and tests, not quality."""

    model_name = "lexical-jaccard"

    def similarity(self, a: str, b: str) -> float:
        ta, tb = set(_TOKEN.findall(a.casefold())), set(_TOKEN.findall(b.casefold()))
        if not ta and not tb:
            return 1.0
        return len(ta & tb) / len(ta | tb)


def default_backend(ctx: EvalContext) -> SimilarityBackend:
    cached = ctx.cache.get("similarity_backend")
    if cached is not None:
        return cached
    if ctx.similarity_backend_factory is not None:
        backend: SimilarityBackend = ctx.similarity_backend_factory()
    elif ctx.config.similarity.backend == "lexical":
        backend = LexicalBackend()
    else:
        backend = SentenceTransformersBackend(ctx.config.similarity.model)
    ctx.cache["similarity_backend"] = backend
    return backend


class SimilarityEvaluator(Evaluator):
    name = "similarity"

    def __init__(self, *, backend: SimilarityBackend, min: float, field: str = "answer") -> None:
        if not 0.0 <= min <= 1.0:
            raise EvaluatorConfigError("similarity: 'min' must be between 0 and 1")
        self.backend = backend
        self.min = min
        self.field = field

    @classmethod
    def from_config(cls, options: dict[str, Any], ctx: EvalContext) -> Evaluator:
        unknown = set(options) - {"min", "field"}
        if unknown:
            raise EvaluatorConfigError(f"similarity: unknown options {sorted(unknown)}")
        return cls(
            backend=default_backend(ctx),
            min=float(options.get("min", ctx.config.similarity.min)),
            field=options.get("field", "answer"),
        )

    def required_expected_fields(self) -> list[str]:
        return [self.field]

    def evaluate(self, case: Case, output: Output) -> list[Score]:
        text = self.output_text(output)
        if text is None:
            return [Score.errored_score(self.name, f"output has no field {self.field!r}")]
        expected = str(case.expected.get(self.field, ""))
        try:
            raw = self.backend.similarity(text, expected)
        except Exception as e:
            return [Score.errored_score(self.name, f"similarity backend failed: {e}")]
        value = max(0.0, min(1.0, raw))
        return [
            Score(
                self.name,
                value,
                passed=value >= self.min,
                comment=None if value >= self.min else f"similarity {value:.2f} < min {self.min:.2f}",
                metadata={"model": self.backend.model_name},
            )
        ]
