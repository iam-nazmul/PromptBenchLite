"""LLM-as-judge evaluator (SPEC §6.3). See .claude/references/anthropic-judge.md."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field

from promptbench.config import JudgeConfig
from promptbench.evaluators.base import EvalContext, Evaluator, EvaluatorConfigError, Score
from promptbench.evaluators.similarity import LexicalBackend
from promptbench.golden import Case
from promptbench.runner import Output

FALLBACK_BETA = "server-side-fallback-2026-07-01"

JUDGE_INSTRUCTIONS = """\
You are a strict, consistent evaluator for an automated regression test of an AI system.
You will receive the INPUTS sent to the system, a REFERENCE answer written by a human \
(one good answer, not the only acceptable one), optional CRITERIA specific to this case, \
and the ANSWER produced by the system.

Grade the ANSWER using only the rubric below. First write your reasoning, citing the specific \
parts of the ANSWER that determine the grade. Then give an integer score from 1 to 5 as defined \
by the rubric. Judge the ANSWER on its own merits; do not guess how other versions of the system scored.

<rubric>
{rubric}
</rubric>"""


class JudgeVerdict(BaseModel):
    reasoning: str = Field(description="Assessment against the rubric, written before the score.")
    score: int = Field(description="Integer from 1 (worst) to 5 (best) as defined by the rubric.")


@dataclass(frozen=True)
class JudgeRequest:
    rubric: str
    system: str
    user: str
    reference: str
    answer: str


@dataclass(frozen=True)
class Verdict:
    score: int
    reasoning: str
    served_model: str


class JudgeFailure(Exception):
    """The judge could not produce a verdict (refusal, truncation, API error)."""


class JudgeBackend(Protocol):
    model: str

    def judge(self, request: JudgeRequest) -> Verdict: ...


class AnthropicJudgeBackend:
    def __init__(self, client_factory: Callable[[], Any], config: JudgeConfig) -> None:
        self._client_factory = client_factory
        self._client: Any = None
        self._lock = threading.Lock()
        self.config = config
        self.model = config.model

    @property
    def client(self) -> Any:
        """Created on first use so `validate` never needs credentials."""
        with self._lock:
            if self._client is None:
                self._client = self._client_factory()
            return self._client

    def judge(self, request: JudgeRequest) -> Verdict:
        import anthropic

        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "output_config": {"effort": self.config.effort},
            "system": [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": request.user}],
            "output_format": JudgeVerdict,
        }
        try:
            if self.config.fallbacks:
                response = self.client.beta.messages.parse(
                    **kwargs, betas=[FALLBACK_BETA], fallbacks="default"
                )
            else:
                response = self.client.messages.parse(**kwargs)
        except anthropic.RateLimitError as e:
            raise JudgeFailure(f"rate limited after retries: {e}") from e
        except anthropic.APIStatusError as e:
            raise JudgeFailure(f"API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise JudgeFailure(f"connection error: {e}") from e

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise JudgeFailure(f"refusal: {category or 'unspecified'}")
        if response.stop_reason == "max_tokens":
            raise JudgeFailure(f"truncated at max_tokens={self.config.max_tokens}")
        parsed = response.parsed_output
        if parsed is None:
            raise JudgeFailure("no structured verdict in response")
        return Verdict(score=parsed.score, reasoning=parsed.reasoning, served_model=response.model)


class FakeJudgeBackend:
    """Deterministic stand-in for offline demos and tests: maps token overlap with the reference to 1-5."""

    model = "fake-judge"

    def judge(self, request: JudgeRequest) -> Verdict:
        overlap = LexicalBackend().similarity(request.answer, request.reference)
        score = 1 + round(overlap * 4)
        return Verdict(
            score=score, reasoning=f"token overlap with reference {overlap:.2f}", served_model=self.model
        )


def _default_client(cfg: JudgeConfig) -> Any:
    import anthropic

    return anthropic.Anthropic(max_retries=cfg.max_retries)


def judge_backend(ctx: EvalContext) -> JudgeBackend:
    cached = ctx.cache.get("judge_backend")
    if cached is not None:
        return cached
    cfg = ctx.config.judge
    backend: JudgeBackend
    if cfg.provider == "fake":
        backend = FakeJudgeBackend()
    else:
        factory = ctx.anthropic_client_factory or (lambda: _default_client(cfg))
        backend = AnthropicJudgeBackend(factory, cfg)
    ctx.cache["judge_backend"] = backend
    return backend


def render_user_message(case: Case, answer: str, reference: str) -> str:
    parts = [
        f"<inputs>\n{json.dumps(case.inputs, indent=2, ensure_ascii=False)}\n</inputs>",
        f"<reference>\n{reference}\n</reference>" if reference else "<reference>(none)</reference>",
    ]
    if case.criteria:
        parts.append(f"<criteria>\n{case.criteria}\n</criteria>")
    parts.append(f"<answer>\n{answer}\n</answer>")
    return "\n\n".join(parts)


class JudgeEvaluator(Evaluator):
    name = "judge"

    def __init__(
        self,
        *,
        rubric: str,
        rubric_text: str,
        backend: JudgeBackend,
        samples: int = 1,
        min_score: int | None = None,
        field: str = "answer",
    ) -> None:
        if min_score is not None and not 1 <= min_score <= 5:
            raise EvaluatorConfigError("judge: 'min_score' must be 1-5")
        if samples < 1:
            raise EvaluatorConfigError("judge: 'samples' must be >= 1")
        self.rubric = rubric
        self.system = JUDGE_INSTRUCTIONS.format(rubric=rubric_text.strip())
        self.backend = backend
        self.samples = samples
        self.min_score = min_score
        self.field = field

    @classmethod
    def from_config(cls, options: dict[str, Any], ctx: EvalContext) -> Evaluator:
        unknown = set(options) - {"rubric", "samples", "min_score", "field"}
        if unknown:
            raise EvaluatorConfigError(f"judge: unknown options {sorted(unknown)}")
        rubric = options.get("rubric")
        if not isinstance(rubric, str) or not rubric:
            raise EvaluatorConfigError("judge: 'rubric' is required (name of a file in rubrics_dir)")
        return cls(
            rubric=rubric,
            rubric_text=load_rubric(ctx, rubric),
            backend=judge_backend(ctx),
            samples=int(options.get("samples", ctx.config.judge.samples)),
            min_score=options.get("min_score"),
            field=options.get("field", "answer"),
        )

    @property
    def key(self) -> str:
        return f"judge.{self.rubric}"

    @property
    def keys(self) -> list[str]:
        return [self.key]

    def evaluate(self, case: Case, output: Output) -> list[Score]:
        answer = self.output_text(output)
        if answer is None:
            return [Score.errored_score(self.key, f"output has no field {self.field!r}")]
        reference = str(case.expected.get(self.field, ""))
        request = JudgeRequest(
            rubric=self.rubric,
            system=self.system,
            user=render_user_message(case, answer, reference),
            reference=reference,
            answer=answer,
        )
        verdicts: list[Verdict] = []
        failures: list[str] = []
        for _ in range(self.samples):
            try:
                verdict = self.backend.judge(request)
            except JudgeFailure as e:
                failures.append(str(e))
                continue
            if not 1 <= verdict.score <= 5:
                failures.append(f"score {verdict.score} outside 1-5")
                continue
            verdicts.append(verdict)

        meta: dict[str, Any] = {"judge_model": self.backend.model}
        if failures:
            meta["failures"] = failures
        if not verdicts:
            return [Score.errored_score(self.key, failures[0], **meta)]

        value = sum((v.score - 1) / 4 for v in verdicts) / len(verdicts)
        meta["served_model"] = verdicts[0].served_model
        meta["served_models"] = sorted({v.served_model for v in verdicts})
        meta["samples"] = [v.score for v in verdicts]
        passed = None if self.min_score is None else value >= (self.min_score - 1) / 4
        return [Score(self.key, value, passed=passed, comment=verdicts[0].reasoning, metadata=meta)]


def load_rubric(ctx: EvalContext, name: str) -> str:
    cache: dict[str, str] = ctx.cache.setdefault("rubrics", {})
    if name not in cache:
        path = ctx.config.rubrics_path / f"{name}.md"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            raise EvaluatorConfigError(f"judge: rubric {name!r} not found at {path}") from e
        if not text.strip():
            raise EvaluatorConfigError(f"judge: rubric {path} is empty")
        cache[name] = text
    return cache[name]
