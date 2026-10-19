# evaluators

Scores one case's output. Built-ins: `exact`, `contains`, `regex`, `json_schema`, `similarity`, `judge`.

## Public API
- `Score(key, value, passed=None, comment=None, metadata={}, error=None)`. Use `Score.errored_score(key, reason)` for failures.
- `Evaluator` (ABC): `name`, `evaluate(case, output) -> list[Score]`, `from_config(options, ctx)`, `keys`, `required_expected_fields()`
- `EvalContext(config, anthropic_client_factory=None, similarity_backend_factory=None)`: tests inject fakes here.
- `create(name, options, ctx)`, `available()`: the registry. Built-ins are in `registry.BUILTINS`, third-party evaluators come from the `promptbench.evaluators` entry-point group.

| Evaluator | Options | Score key | Cost |
|---|---|---|---|
| `exact` | `field`, `normalize=true`, `value` | `exact` | free |
| `contains` | `values`, `all=true`, `case_sensitive=false`, `field` | `contains` | free |
| `regex` | `pattern`, `must_match=true`, `field` | `regex` | free |
| `json_schema` | `schema` (inline or path), `field` (optional; JSON string parsed) | `json_schema` | free |
| `similarity` | `min` (default `similarity.min`), `field` | `similarity` | free (local model) |
| `judge` | `rubric` (required), `samples`, `min_score` (1–5), `field` | `judge.<rubric>` | `samples` API calls per case |

Backends: `similarity.backend = sentence_transformers | lexical`, `judge.provider = anthropic | fake`. `lexical` and `fake` are offline stand-ins for demos and tests. They don't measure quality.

## Invariants
- `value ∈ [0, 1]`, higher is better. `Score.__post_init__` enforces this.
- If an evaluator can't score, it returns an **errored** score, never `0.0`.
- Score keys are stable. They're LangSmith feedback keys and baseline metric names.
- No network or model loading in `__init__`/`from_config`. The Anthropic client and the embedding model are created on first `evaluate`, so `validate` works offline.
- `evaluate` must be thread-safe, because the pipeline calls it concurrently.
- The judge never sends `temperature`, `thinking` or forced `tool_choice` (rejected by current models). Its system prompt (instructions + rubric) is byte-stable and cached.

## Adding one
Follow the `add-evaluator` skill (`.claude/skills/add-evaluator/SKILL.md`).

## Tests
`uv run pytest tests/evaluators`
