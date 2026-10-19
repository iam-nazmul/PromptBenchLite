# PromptBench Lite

Catch prompt regressions before they merge.

PromptBench Lite runs a set of example inputs (a **golden set**) through your prompt on every pull request. It scores each answer three ways:

- **deterministic checks**, such as "must mention 30 days" or "must be valid JSON"
- **semantic similarity** to a reference answer
- an **LLM judge** (Claude) that grades against a written rubric

It compares the scores with the accepted **baseline** committed in your repo and fails the build when quality drops by more than the threshold you set. Every run can be recorded in **LangSmith**, so you can see exactly which answers got worse and why.

## Install

Requires Python 3.11+.

PromptBench Lite is not on PyPI yet. Install it from Git or from a local checkout:

```bash
# from Git
uv add --dev "promptbench-lite @ git+https://github.com/iam-nazmul/PromptBenchLite"
uv add --dev "promptbench-lite[similarity] @ git+https://github.com/iam-nazmul/PromptBenchLite"   # + sentence-transformers

# from a local checkout
uv add --dev --editable /path/to/PromptBenchLite

# with pip
pip install "promptbench-lite @ git+https://github.com/iam-nazmul/PromptBenchLite"
```

Once it is published to PyPI: `uv add --dev promptbench-lite`.

## Quick start

**1. Point PromptBench at your prompt.** Any function that takes the inputs as keyword arguments and returns a string (or a dict) works:

```python
# myapp/prompts.py
def answer_question(question: str) -> str:
    ...  # call your LLM with your prompt
```

**2. Write a golden set** in `goldens/support-bot.yaml`:

```yaml
suite: support-bot
target: myapp.prompts:answer_question
defaults:
  evaluators:
    similarity: {}
    judge: {rubric: correctness}
cases:
  - id: refund-window
    inputs: {question: "How long do I have to request a refund?"}
    expected: {answer: "You can request a refund within 30 days of purchase."}
    evaluators:
      contains: {values: ["30 days"]}
    tags: [billing]
```

**3. Write the rubric** the judge uses, in `rubrics/correctness.md`. Describe what each score from 1 to 5 means. A worked example is in [examples/support-bot/rubrics/correctness.md](examples/support-bot/rubrics/correctness.md).

**4. Configure** with `promptbench.toml` (every key is optional):

```toml
[promptbench.judge]
model = "claude-opus-5-5"

[promptbench.gate]
default_max_drop = 0.05      # fail if a metric's average drops by more than 0.05 (on a 0–1 scale)
```

**5. Run it:**

```bash
export ANTHROPIC_API_KEY=...            # judge
export LANGSMITH_API_KEY=...            # optional: tracking
promptbench validate                     # checks files; offline and free
promptbench run --json results.json      # first run: no baseline yet, nothing is gated
promptbench baseline update --from-results results.json
git add baselines/ && git commit -m "Add PromptBench baseline"
```

From now on, `promptbench run` exits with **1** if a gated metric drops beyond its threshold.

## Try it without API keys

The repo contains an offline example (fake judge, word-overlap similarity):

```bash
uv run promptbench run --root examples/support-bot --no-tracking
SUPPORT_BOT_VARIANT=degraded uv run promptbench run --root examples/support-bot --no-tracking   # fails
```

## Evaluators

| Name | What it checks | Options |
|---|---|---|
| `contains` | The answer contains given phrases | `values`, `all`, `case_sensitive` |
| `regex` | The answer matches (or doesn't match) a pattern | `pattern`, `must_match` |
| `exact` | The answer equals the reference | `normalize`, `value` |
| `json_schema` | The output is valid against a JSON schema | `schema` (inline or file path), `field` |
| `similarity` | Meaning is close to the reference answer | `min` |
| `judge` | Claude grades the answer 1–5 against your rubric | `rubric`, `samples`, `min_score` |

Every evaluator also accepts `field` (default `answer`) when your target returns a dict.

## How the gate decides

For each metric, PromptBench compares the average score on the cases that exist in both the baseline and the current run.

- **Fails** if the average dropped by more than `max_drop`, or if it's below an optional `floor`.
- **Warns but doesn't fail** if fewer than `min_cases` cases are comparable, if there's no baseline yet, or if the judge model changed since the baseline.
- New cases and new metrics are reported but not gated until the next baseline update.
- An API error or a refusal is **not** scored as 0. If more than `max_error_rate` of evaluations fail, the run exits with **3**, so an outage never looks like a regression or a pass.

Per-metric thresholds:

```toml
[promptbench.gate.metrics]
"judge.correctness" = { max_drop = 0.05, floor = 0.70 }
"contains"          = { max_drop = 0.0 }
```

Set `gate.mode = "warn"` to report regressions without failing the build. This is useful while you tune thresholds.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | No regression |
| 1 | Quality regression |
| 2 | Configuration or golden-set error |
| 3 | Infrastructure error (too many evaluations failed, or required tracking unavailable) |

## Updating the baseline

When a quality change is intended, for example a deliberate trade-off or a new rubric, accept it explicitly:

```bash
promptbench run --json results.json
promptbench baseline update --from-results results.json   # or --from-experiment <langsmith experiment>
```

Commit the changed `baselines/*.json` in its own pull request so reviewers can see what was accepted. The included `baseline-update` GitHub workflow does this on `main` after an approval.

## pytest

Run golden cases as pytest tests, one test per case:

```bash
pytest --promptbench goldens/
```

The suite-level gate runs at the end of the session and sets pytest's exit code. Use `-k <tag>` to select cases by tag. Enable it permanently with `promptbench = true` under `[tool.pytest.ini_options]`.

## GitHub Actions

Copy [.github/workflows/promptbench.yml](.github/workflows/promptbench.yml) into your repo and set `PB_ROOT: "."`. Add the `ANTHROPIC_API_KEY` secret, and optionally `LANGSMITH_API_KEY`. The workflow:

- runs the gate on pull requests that touch prompts or golden sets
- posts a single PR comment with the per-metric changes and the worst-regressed cases, and updates it on each run
- uploads Markdown, JUnit and JSON reports as artifacts

PRs from forks have no access to secrets, so they run `validate` only.

## Configuration reference

```toml
[promptbench]
goldens_dir = "goldens"
baselines_dir = "baselines"
rubrics_dir = "rubrics"
concurrency = 4
target_timeout_s = 60

[promptbench.tracking]
enabled = true            # also: PROMPTBENCH_TRACKING=off, --no-tracking
project = "promptbench"   # LangSmith dataset/experiment prefix (or LANGSMITH_PROJECT)
required = false          # true: tracking failures exit 3

[promptbench.similarity]
backend = "sentence_transformers"   # or "lexical" (offline, word overlap)
model = "all-MiniLM-L6-v2"
min = 0.75

[promptbench.judge]
provider = "anthropic"    # or "fake" (offline, for demos)
model = "claude-opus-5-5"
effort = "medium"         # low | medium | high | xhigh | max
samples = 1               # >1 averages several judge calls (or PROMPTBENCH_JUDGE_SAMPLES)
max_retries = 3
fallbacks = true          # server-side refusal fallbacks; the serving model is recorded

[promptbench.gate]
mode = "enforce"          # or "warn"
default_max_drop = 0.05
min_cases = 5
max_error_rate = 0.10
```

## Costs

The judge is the only part that calls a paid API: `samples` calls per case per run. The rubric is sent as a cached prompt prefix, so repeated calls mostly pay for the answer being judged plus the judge's reasoning. To spend less:

- use a lower `effort`
- use a cheaper judge model, such as `claude-sonnet-5-5`
- restrict the workflow to the paths that contain prompts

Similarity runs locally and is free.

## License

MIT
