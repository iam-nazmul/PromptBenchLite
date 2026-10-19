# PromptBench Lite — Specification

Status: Draft v0.1 · Last updated: 2026-10-19

## 1. Summary

PromptBench Lite is a Python toolkit for regression-testing prompts and LLM outputs in CI.
It runs a **golden set** of cases through the prompt under test, scores each output with
**deterministic checks**, **semantic similarity**, and **LLM-as-judge** rubrics, records the
run as a **LangSmith experiment**, and **fails the build** when any gated metric drops more
than a configured threshold below the committed baseline.

Stack: Python 3.11+, pytest, LangSmith, Anthropic SDK (judge), sentence-transformers
(similarity), GitHub Actions. Tooling: `uv`, `ruff`, `mypy`.

## 2. Goals and non-goals

### Goals
- G1. A prompt change that lowers quality fails CI with a report that names the cases that regressed.
- G2. Golden sets live in the repo as human-readable YAML that can be reviewed in a PR.
- G3. One command runs locally and in CI with identical semantics: `promptbench run`.
- G4. Works as a pytest plugin (one test item per golden case) and as a standalone CLI.
- G5. Every run is traceable in LangSmith: inputs, outputs, per-evaluator feedback, judge reasoning.
- G6. The gate decision is deterministic given the scores: baseline + thresholds → pass/fail. It does not depend on network state.
- G7. Unit tests run offline with no API keys.

### Non-goals
- Hosting a UI (LangSmith is the UI).
- Prompt optimisation or auto-tuning.
- Load, latency, or cost benchmarking (latency and token counts are recorded but not gated in v1).
- Supporting LLM providers other than Anthropic for the judge in v1. The judge sits behind an interface so another provider can be added later.
- Generating golden cases automatically from production traffic (a helper may come later).

## 3. Users and primary flows

| Actor | Flow |
|---|---|
| Prompt author | Edits a prompt → opens PR → CI runs `promptbench run` → sees a PR summary showing deltas vs baseline → fixes or justifies. |
| Maintainer | After an intended quality change is merged, runs `promptbench baseline update` on `main` (or approves the CI job that does) to accept the new scores. |
| Eval author | Adds golden cases, rubrics, or evaluators → `promptbench validate` → PR. |

## 4. Architecture

```
goldens/*.yaml ──► loader ──► Case[] ──► runner ──► target callable (prompt under test)
                                              │
                                              ▼
                                         Output[]
                                              │
                          ┌───────────────────┼────────────────────┐
                          ▼                   ▼                    ▼
                   deterministic        similarity             judge (Claude)
                   (exact/regex/       (embeddings,           (rubric → structured
                    contains/json)      cosine)                score + reasoning)
                          └───────────────────┼────────────────────┘
                                              ▼
                                     CaseResult[] ──► aggregate ──► SuiteScores
                                              │                          │
                                              ▼                          ▼
                                     tracking (LangSmith)     gate (vs baselines/*.json)
                                                                         │
                                                                         ▼
                                                    report (terminal, Markdown, JUnit) + exit code
```

### 4.1 Package layout

```
src/promptbench/
  config.py          # load + validate promptbench.toml → Config (pydantic)
  golden/            # YAML schema, loader, validation
  runner/            # resolve target callable, execute cases (concurrency, retries, timeouts)
  evaluators/        # Evaluator protocol, registry, built-ins: deterministic, similarity, judge
  scoring/           # aggregation, baseline I/O, gate decision
  tracking/          # LangSmith adapter (no-op adapter when tracking is off)
  reporting/         # terminal, Markdown (GitHub step summary), JUnit XML
  pytest_plugin.py   # entry point `promptbench` in pytest11
  cli.py             # `promptbench` console script (typer)
tests/               # unit tests (offline); tests/live/ for real-API tests
goldens/             # example golden sets
baselines/           # committed baseline scores per suite
rubrics/             # judge rubric markdown files
.github/workflows/promptbench.yml
```

Every package under `src/promptbench/` has its own `README.md` (purpose, public API, invariants, how to test).

## 5. Golden set format

One YAML file per suite in `goldens/`. Validated against a pydantic model; unknown keys are errors.

```yaml
suite: support-bot                    # unique, kebab-case; maps to baselines/support-bot.json
target: myapp.prompts:answer_question # "module:callable"; called as target(**inputs) -> str | dict
description: Customer support answers for billing questions.
defaults:
  evaluators:
    similarity: {}                    # uses config default model
    judge: {rubric: correctness}      # rubrics/correctness.md
cases:
  - id: refund-window                 # unique within suite, stable forever (used for diffing)
    inputs:
      question: "How long do I have to request a refund?"
    expected:
      answer: "You can request a refund within 30 days of purchase."
    evaluators:                       # merged over defaults; set a key to null to drop a default
      contains: {values: ["30 days"]}
    tags: [billing, refunds]
  - id: refund-no-receipt
    inputs: {question: "Can I get a refund without a receipt?"}
    expected: {answer: "Yes, with the order number from your account."}
    skip: "Policy under review — PB-42"   # optional; skipped cases are excluded from aggregates
```

Rules:
- `id` values are immutable once merged. Renaming an id is a delete + add and loses history.
- If the target returns a `str`, it is wrapped as `{"answer": <str>}`. Evaluators compare against the `expected` field of the same name. The default field is `answer` and can be changed per evaluator with `field:`.
- `inputs` and `expected` must be JSON-serialisable.

## 6. Evaluators

All evaluators implement:

```python
class Evaluator(Protocol):
    name: str                                  # registry key, also LangSmith feedback key prefix
    def evaluate(self, case: Case, output: Output) -> list[Score]: ...

@dataclass(frozen=True)
class Score:
    key: str          # e.g. "similarity", "judge.correctness", "contains"
    value: float      # normalised to [0, 1]
    passed: bool | None   # per-case pass/fail if the evaluator defines a threshold, else None
    comment: str | None   # reasoning / diff, shown in reports and LangSmith
    metadata: dict[str, Any] = field(default_factory=dict)  # e.g. served_model, samples, similarity model
    error: str | None = None  # set → errored score; excluded from means (§8.4)

    @property
    def errored(self) -> bool: return self.error is not None

    @classmethod
    def errored_score(cls, key: str, reason: str) -> "Score": ...
```

Evaluators are registered with an entry-point group `promptbench.evaluators`, so third-party packages can add their own.

### 6.1 Deterministic (built-in)
| Name | Config | Score |
|---|---|---|
| `exact` | `field`, `normalize: bool` | 1.0 if equal else 0.0 |
| `contains` | `values: [str]`, `all: bool = true`, `case_sensitive: false` | fraction of values found |
| `regex` | `pattern`, `must_match: true` | 1.0/0.0 |
| `json_schema` | `schema` (inline or path) | 1.0 if output validates |

### 6.2 Semantic similarity
- Default backend: `sentence-transformers` with model `all-MiniLM-L6-v2`. It runs on CPU and needs no API key. The model is cached in CI with `actions/cache`.
- Score = cosine similarity between the embeddings of output and expected, clipped to [0, 1].
- Per-case `min` (default from config) sets `passed`.
- The backend is pluggable through config (`similarity.backend`). Only `sentence_transformers` ships in v1.

### 6.3 LLM-as-judge
- Provider: Anthropic Messages API through the official `anthropic` SDK.
- Default model: `claude-opus-5-5` (config `judge.model`). Effort is set explicitly (`judge.effort`, default `medium`).
- The rubric is a markdown file in `rubrics/<name>.md`. It defines the criteria and a 1–5 scale with an anchor description for each level.
- The response is constrained to a pydantic model through structured output (`client.messages.parse(..., output_format=JudgeVerdict)`):
  ```python
  class JudgeVerdict(BaseModel):
      reasoning: str        # written before the score
      score: int            # 1..5
  ```
  Normalised value = `(score - 1) / 4`.
- The rubric and instructions go in a cached system prefix (`cache_control: {"type": "ephemeral"}`). Per-case content goes in the user message, after the cache breakpoint.
- `judge.samples` (default 1): when > 1, the judge is called N times and the mean is used. This reduces variance. Sampling parameters such as `temperature` are not accepted by current models, so repeated sampling is the only way to reduce variance.
- Refusals (`stop_reason == "refusal"`) and API errors after retries produce an **errored** score, not a 0 (see §8.4).
- Server-side refusal fallbacks are enabled (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`). The model that served each verdict is recorded in the score metadata, because a fallback changes the grader.
- The judge never sees the baseline score or previous outputs.

## 7. Configuration

`promptbench.toml` at the repo root (or `[tool.promptbench]` in `pyproject.toml`; the dedicated file wins).

```toml
[promptbench]
goldens_dir   = "goldens"
baselines_dir = "baselines"
rubrics_dir   = "rubrics"
concurrency   = 4
target_timeout_s = 60

[promptbench.tracking]
enabled = true                 # overridden by PROMPTBENCH_TRACKING=off
project = "promptbench"        # LangSmith dataset/experiment prefix

[promptbench.similarity]
backend = "sentence_transformers"
model   = "all-MiniLM-L6-v2"
min     = 0.75

[promptbench.judge]
model   = "claude-opus-5-5"
effort  = "medium"
samples = 1
max_retries = 3

[promptbench.gate]
default_max_drop = 0.05        # absolute drop in suite mean (0–1 scale) allowed per metric
min_cases        = 5           # suites with fewer scored cases warn instead of failing
max_error_rate   = 0.10        # fail (exit 3) if more than 10% of evaluations errored

[promptbench.gate.metrics]     # per-metric overrides; keys are Score.key
"judge.correctness" = { max_drop = 0.05, floor = 0.70 }
"similarity"        = { max_drop = 0.03 }
"contains"          = { max_drop = 0.0 }
```

Environment variables:
| Var | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Judge calls (or any credential the SDK resolves). |
| `LANGSMITH_API_KEY` | Tracking. If missing and tracking is enabled → warning, tracking disabled. |
| `LANGSMITH_PROJECT` | Optional override of `tracking.project`. |
| `PROMPTBENCH_TRACKING` | `off` disables LangSmith regardless of config. |
| `PROMPTBENCH_JUDGE_SAMPLES` | Override `judge.samples`. |

## 8. Scoring and gating

### 8.1 Aggregation
For each suite and each score key: `mean` over non-skipped, non-errored cases. Also recorded: `n`, `pass_rate` (where `passed` is defined), `errored`.

### 8.2 Baseline file
`baselines/<suite>.json`. Written only by `promptbench baseline update`. Never edit it by hand.

```json
{
  "suite": "support-bot",
  "created_at": "2026-10-19T12:00:00Z",
  "git_sha": "abc1234",
  "langsmith_experiment": "support-bot-3f9a2c",
  "promptbench_version": "0.1.0",
  "judge_model": "claude-opus-5-5",
  "metrics": {
    "judge.correctness": {"mean": 0.86, "n": 40},
    "similarity": {"mean": 0.81, "n": 40}
  },
  "cases": {
    "refund-window": {"judge.correctness": 1.0, "similarity": 0.93}
  }
}
```

### 8.3 Gate decision
A metric **fails** when either holds:
- `baseline.mean - current.mean > max_drop`
- `current.mean < floor` (if a floor is set)

A suite fails if any gated metric fails. The run fails if any suite fails.

Special cases:
- New metric (not in baseline): reported, not gated.
- Metric in baseline but missing now: fail (evaluator was removed or broken).
- New cases: included in the current mean. Removed cases: excluded from the baseline mean before comparing. Only the intersection of case ids is compared; the report lists added/removed ids.
- `judge_model` differs from the baseline's: warn loudly. Scores from different graders are not directly comparable.
- `n < min_cases`: warn, don't fail.

### 8.4 Errors
- Target raised or timed out → case errored for all evaluators.
- Evaluator errored (API failure after retries, refusal) → that score errored.
- Errored scores are excluded from means. If `errored / total > max_error_rate` → exit 3. Infra failure must never look like a pass or a regression.

### 8.5 Exit codes
| Code | Meaning |
|---|---|
| 0 | All suites pass the gate |
| 1 | Quality regression (gate failed) |
| 2 | Usage / config / golden-set validation error |
| 3 | Infrastructure error (error rate exceeded, LangSmith required but unreachable, etc.) |

## 9. LangSmith integration

- Each suite maps to a LangSmith dataset `<project>/<suite>`. It is synced from YAML on each run: examples are upserted by case `id` (stored in example metadata). The YAML is the source of truth, and examples deleted from YAML are archived.
- Each run creates one experiment per suite via `Client.evaluate(target, data=dataset, evaluators=[...], experiment_prefix=<suite>, metadata={...})`.
- Experiment metadata: `git_sha`, `git_branch`, `pr_number`, `ci_run_url`, `promptbench_version`, `judge_model`.
- Each `Score` becomes a feedback entry with `key=Score.key`, `score=value`, `comment=comment`.
- The pytest plugin uses `@pytest.mark.langsmith` / `langsmith.testing` (`log_inputs`, `log_outputs`, `log_reference_outputs`, `log_feedback`) so pytest runs appear as LangSmith test-suite experiments.
- When tracking is off, the no-op adapter keeps the same code path and writes results only to the local report. The gate behaves the same.

## 10. CLI

```
promptbench validate [--suite NAME]...         # schema-check goldens, rubrics, config; no network
promptbench run [--suite NAME]... [--tag T]... # run + gate
     [--no-tracking] [--report-md PATH] [--junit PATH] [--json PATH]
     [--update-baseline]                        # only allowed with --i-know-what-im-doing on non-main branches
promptbench baseline update [--suite NAME]... [--from-experiment NAME]
promptbench baseline show [--suite NAME]
promptbench compare EXPERIMENT_A EXPERIMENT_B  # per-case delta table from LangSmith
```

## 11. pytest plugin

- Enabled with `pytest --promptbench` (or `promptbench = true` in `[tool.pytest.ini_options]`).
- Collects one test item per golden case: `goldens/support-bot.yaml::refund-window`.
- A case item fails if any score with a defined `passed` is `False`. Per-case thresholds are separate from the regression gate.
- In `pytest_sessionfinish`, the suite-level gate runs and sets `session.exitstatus` to the exit codes in §8.5.
- Markers: `promptbench_suite(name)`, `live` (real API; skipped unless `PROMPTBENCH_LIVE=1`).

## 12. Reporting

- Terminal: table per suite — metric, baseline, current, delta, threshold, status.
- Markdown (`--report-md`, and `$GITHUB_STEP_SUMMARY` when set): the same table, the top 10 regressed cases by delta with judge reasoning, a link to the LangSmith experiment, and added/removed cases.
- JUnit XML for CI test UIs.
- JSON (`--json`) is the machine-readable full result. The `baseline update` command reads this format.

## 13. GitHub Actions

`.github/workflows/promptbench.yml`:
- Triggers: `pull_request` (paths: `prompts/**`, `goldens/**`, `rubrics/**`, `src/**`, `promptbench.toml`) and `workflow_dispatch`.
- Steps: checkout → `astral-sh/setup-uv` → cache HF model dir → `uv sync --frozen` → `uv run promptbench validate` → `uv run promptbench run --report-md report.md --junit junit.xml` → upload artifacts → post/update a single sticky PR comment with `report.md`.
- Secrets: `ANTHROPIC_API_KEY`, `LANGSMITH_API_KEY`. PRs from forks have no secrets: the job runs `validate` only and says so in the summary.
- `concurrency: promptbench-${{ github.ref }}` with `cancel-in-progress: true`.
- A separate `baseline-update` workflow (`workflow_dispatch`, `main` only, requires environment approval) runs `promptbench baseline update` and opens a PR with the new baseline files.

## 14. Testing strategy (for this repo)

- Unit tests (`tests/`): fully offline. The judge uses a fake `anthropic` client fixture, similarity uses a stub backend, and LangSmith uses the no-op adapter. Target coverage is at least 90% for `scoring/` and `golden/`.
- Gate logic gets table-driven tests covering every rule in §8.3, including the special cases.
- Live tests (`tests/live/`, marker `live`): one tiny suite against the real Anthropic and LangSmith APIs. They run nightly, not on PRs.
- An example project in `examples/support-bot/` is exercised end-to-end in CI with tracking off and a fake judge.

## 15. Milestones

| M | Scope | Done when |
|---|---|---|
| M1 | Config, golden loader, `validate`, deterministic evaluators, aggregation, baseline I/O, gate, terminal report, CLI `run` with tracking off | Example suite gates correctly offline; exit codes per §8.5 |
| M2 | Similarity evaluator, judge evaluator, rubrics, retries/error accounting | Live test passes; error-rate gate works |
| M3 | LangSmith tracking, dataset sync, `compare` | Experiments visible with metadata + feedback |
| M4 | pytest plugin, Markdown/JUnit reports, GitHub Actions workflows | PR comment shows deltas; baseline-update workflow opens a PR |

## 16. Open questions

1. Should the gate support a statistical test (e.g., bootstrap CI on the delta) in addition to fixed `max_drop`? Proposed for v1.1, once we have data on judge variance.
2. Store baselines in LangSmith only (tagged experiment) instead of committed JSON? Rejected for v1 because it gives up offline determinism (G6). Revisit later.
3. Per-tag gating (e.g., stricter thresholds for `safety` cases)?
