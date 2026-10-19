"""Shared offline fixtures. Nothing here touches the network."""

from __future__ import annotations

import textwrap
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from promptbench.config import Config, load_config
from promptbench.evaluators import EvalContext
from promptbench.tracking import NoopTracker

pytest_plugins = ["pytester"]

DEFAULT_ANSWERS = {
    "refund": "You can request a refund within 30 days of purchase.",
    "cancel": "Cancel any time under Settings, Billing.",
    "password": "Use Forgot password on the sign-in page.",
    "invoice": "Invoices are under Settings, Billing, Invoices.",
    "email": "Edit your email under Settings, Profile.",
}

DEFAULT_CASES = """\
cases:
  - id: refund
    inputs: {question: refund}
    expected: {answer: "You can request a refund within 30 days of purchase."}
    evaluators:
      contains: {values: ["30 days"]}
    tags: [billing]
  - id: cancel
    inputs: {question: cancel}
    expected: {answer: "Cancel any time under Settings, Billing."}
    tags: [billing]
  - id: password
    inputs: {question: password}
    expected: {answer: "Use Forgot password on the sign-in page."}
    tags: [account]
  - id: invoice
    inputs: {question: invoice}
    expected: {answer: "Invoices are under Settings, Billing, Invoices."}
    tags: [billing]
  - id: email
    inputs: {question: email}
    expected: {answer: "Edit your email under Settings, Profile."}
    tags: [account]
  - id: skipped-case
    inputs: {question: shipping}
    expected: {answer: "We ship worldwide."}
    skip: "policy under review"
"""

DEFAULT_CONFIG = """\
[promptbench]
concurrency = 2
target_timeout_s = 5

[promptbench.tracking]
enabled = false

[promptbench.similarity]
backend = "lexical"
min = 0.5

[promptbench.judge]
provider = "fake"

[promptbench.gate]
min_cases = 3
"""

RUBRIC = "# Correctness\n5 — fully correct. 1 — wrong.\n"


@dataclass
class Project:
    root: Path
    module: str
    suite: str = "demo"

    def set_answers(self, answers: dict[str, str], fail_on: set[str] | None = None) -> None:
        fail = sorted(fail_on or set())
        code = textwrap.dedent(
            f"""\
            ANSWERS = {answers!r}
            FAIL = {fail!r}

            def answer(question):
                if question in FAIL:
                    raise RuntimeError("boom")
                return ANSWERS.get(question, "I don't know.")
            """
        )
        (self.root / f"{self.module}.py").write_text(code)
        import importlib
        import sys

        if self.module in sys.modules:
            importlib.reload(sys.modules[self.module])

    def config(self, env: dict[str, str] | None = None) -> Config:
        return load_config(self.root, env=env or {})

    def golden_path(self) -> Path:
        return self.root / "goldens" / f"{self.suite}.yaml"


@pytest.fixture
def make_project(tmp_path: Path) -> Callable[..., Project]:
    def _make(
        cases: str = DEFAULT_CASES,
        config: str = DEFAULT_CONFIG,
        defaults: str = "similarity: {}\n    judge: {rubric: correctness}",
        answers: dict[str, str] | None = None,
        suite: str = "demo",
    ) -> Project:
        root = tmp_path / f"proj-{uuid.uuid4().hex[:6]}"
        (root / "goldens").mkdir(parents=True)
        (root / "rubrics").mkdir()
        (root / "rubrics" / "correctness.md").write_text(RUBRIC)
        (root / "promptbench.toml").write_text(config)
        module = f"pbtarget_{uuid.uuid4().hex[:8]}"
        project = Project(root=root, module=module, suite=suite)
        project.set_answers(answers if answers is not None else DEFAULT_ANSWERS)
        header = f"suite: {suite}\ntarget: {module}:answer\ndefaults:\n  evaluators:\n    {defaults}\n"
        project.golden_path().write_text(header + cases)
        return project

    return _make


@dataclass
class FakeAnthropic:
    """Stands in for ``anthropic.Anthropic``; ``respond`` decides each response."""

    respond: Callable[[dict[str, Any]], Any] = field(default=lambda kwargs: verdict_response(5))
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.messages = SimpleNamespace(parse=self._parse("messages.parse"))
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse("beta.messages.parse")))

    def _parse(self, endpoint: str) -> Callable[..., Any]:
        def parse(**kwargs: Any) -> Any:
            self.calls.append({"endpoint": endpoint, **kwargs})
            result = self.respond(kwargs)
            if isinstance(result, Exception):
                raise result
            return result

        return parse


def verdict_response(
    score: int | None, *, stop_reason: str = "end_turn", model: str = "claude-opus-5-5", reasoning: str = "ok"
) -> SimpleNamespace:
    from promptbench.evaluators.judge import JudgeVerdict

    parsed = None if score is None else JudgeVerdict(reasoning=reasoning, score=score)
    return SimpleNamespace(
        stop_reason=stop_reason,
        parsed_output=parsed,
        model=model,
        stop_details=SimpleNamespace(category="cyber") if stop_reason == "refusal" else None,
    )


@pytest.fixture
def fake_anthropic() -> FakeAnthropic:
    return FakeAnthropic()


class StubSimilarity:
    model_name = "stub"

    def __init__(self, value: float | None = None) -> None:
        self.value = value

    def similarity(self, a: str, b: str) -> float:
        if self.value is not None:
            return self.value
        if " ".join(a.split()).casefold() == " ".join(b.split()).casefold():
            return 1.0
        return 0.5 if set(a.casefold().split()) & set(b.casefold().split()) else 0.0


@pytest.fixture
def stub_similarity() -> StubSimilarity:
    return StubSimilarity()


@pytest.fixture
def noop_tracker() -> NoopTracker:
    return NoopTracker()


@pytest.fixture
def ctx(tmp_path: Path, stub_similarity: StubSimilarity, fake_anthropic: FakeAnthropic) -> EvalContext:
    (tmp_path / "rubrics").mkdir(exist_ok=True)
    (tmp_path / "rubrics" / "correctness.md").write_text(RUBRIC)
    config = load_config(tmp_path, env={})
    return EvalContext(
        config=config,
        anthropic_client_factory=lambda: fake_anthropic,
        similarity_backend_factory=lambda: stub_similarity,
    )
