---
name: add-evaluator
description: Implement a new PromptBench evaluator (a new scoring method or check) end to end — protocol, registration, config, tests, docs. Use when the user wants a new metric, check, scorer, or judge variant.
---

# Add an evaluator

First decide whether a new evaluator is needed at all:
- A new *criterion for the judge* → write a rubric in `rubrics/` instead (see `.claude/references/rubric-writing.md`).
- A new *hard requirement* → can `contains`, `regex` or `json_schema` express it? Use those.
- Only add code when the scoring *method* is new.

## 1. Implement

Create `src/promptbench/evaluators/<name>.py`:

```python
from promptbench.evaluators.base import Evaluator, Score
from promptbench.golden import Case
from promptbench.runner import Output


class LengthEvaluator(Evaluator):
    name = "length"

    def __init__(self, *, field: str = "answer", max_chars: int = 800) -> None:
        self.field = field
        self.max_chars = max_chars

    def evaluate(self, case: Case, output: Output) -> list[Score]:
        text = str(output.data.get(self.field, ""))
        ok = len(text) <= self.max_chars
        return [Score(key=self.name, value=1.0 if ok else 0.0, passed=ok,
                      comment=None if ok else f"{len(text)} chars > {self.max_chars}")]
```

Invariants (SPEC §6):
- `value` is in `[0, 1]`, higher is better. Normalise anything else.
- `key` is stable. It becomes the LangSmith feedback key and the baseline metric name; renaming it breaks gating history.
- An evaluator that **cannot** score (API error, refusal, missing field due to a target error) returns an *errored* score via `Score.errored_score(key, reason)`. Never return `0.0` for "couldn't evaluate".
- Constructor args are the YAML config keys; validate them in `__init__` so `promptbench validate` catches typos.
- No network in `__init__`. Lazy-load clients and models on first `evaluate`.
- Thread-safe: the runner calls `evaluate` concurrently.

## 2. Register

Add to `[project.entry-points."promptbench.evaluators"]` in `pyproject.toml`:

```toml
length = "promptbench.evaluators.length:LengthEvaluator"
```

## 3. Test (offline)

`tests/evaluators/test_<name>.py`:
- Table-driven cases for pass, fail, boundary, and missing-field.
- Errored path returns an errored score, not 0.
- Config validation rejects bad args.
- If it calls an API, use the existing fakes (`fake_anthropic`, `stub_similarity`) from `tests/conftest.py`; put any real-API test in `tests/live/` with `@pytest.mark.live`.

```bash
uv run pytest tests/evaluators -x
uv run ruff check --fix . && uv run ruff format . && uv run mypy src
```

## 4. Document

- Update `src/promptbench/evaluators/README.md`: name, config keys, score meaning, cost (free / API calls per case).
- Add the evaluator to the table in SPEC §6.
- If it should be gated with a non-default `max_drop`, add a commented example under `[promptbench.gate.metrics]` in `promptbench.toml`.

## 5. Tell the user

Adding the evaluator to an existing suite introduces a new metric that is **not gated** until the baseline is updated (SPEC §8.3). Say so, and point to the `update-baseline` skill.
