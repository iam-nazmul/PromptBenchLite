# RFC-0001: PromptBench Lite — regression gating for prompts in CI

| | |
|---|---|
| Status | Draft — open for review (reference implementation v0.1 in this repo) |
| Author | nazmul@glascutr.com |
| Created | 2026-10-19 |
| Reviewers | _TBD_ |
| Decision deadline | _TBD_ |
| Detailed spec | [SPEC.md](../SPEC.md) |

## 1. Summary

We propose a small Python toolkit, **PromptBench Lite**, that runs on every pull request that touches a prompt. It runs a reviewed set of example inputs (a *golden set*) through the changed prompt and scores the outputs three ways: deterministic checks, semantic similarity to a reference answer, and an LLM judge with a written rubric. It then compares the scores with a committed baseline and **fails the build when quality drops by more than a set threshold**. Every run is recorded in LangSmith so reviewers can see exactly which cases got worse and why.

This RFC asks reviewers to agree on the approach, the gating model, and the cost envelope. Field-level details (file formats, CLI flags, exit codes) are in [SPEC.md](../SPEC.md) and are not up for decision here unless they affect the questions in §10. A working reference implementation, including an offline example you can run in under a minute, is in this repository.

## 2. Motivation

Today a prompt change is reviewed like any other text diff. Reviewers read the wording and maybe try one or two inputs by hand. This has three problems:

1. **Regressions are invisible in the diff.** A one-line wording change can fix the case the author was looking at and break five others. Nobody sees those five until a user does.
2. **"Better" is not written down.** Without fixed examples and criteria, reviewers argue from intuition, and the same change can be approved or rejected depending on who reviews it.
3. **No history.** When quality slips gradually, we cannot say which change caused it, because past outputs were never recorded.

Unit tests catch broken code but not a worse answer. We need a check that treats **answer quality as a tested property** with a pass/fail outcome that CI can enforce.

## 3. Goals and non-goals

**Goals**
- A prompt change that lowers quality on the golden set fails CI, and the failure names the cases and the reasons.
- Golden sets, rubrics, and thresholds live in the repo and are reviewed like code.
- The pass/fail decision is reproducible from data in the repo plus the current run's scores. It does not depend on an external service being up.
- Running locally gives the same answer as CI.
- Contributors can run the unit test suite with no API keys.

**Non-goals**
- Not a hosted product or dashboard. LangSmith is the UI.
- Not automatic prompt optimisation.
- Not latency, throughput, or cost benchmarking. These are recorded but not gated in v1.
- Not a general eval framework. We support the three scoring methods above and a plug-in point, nothing more.

## 4. Proposal

### 4.1 How it works

```
PR changes a prompt
   │
   ▼
CI: promptbench validate ─► promptbench run
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
   deterministic checks   similarity          LLM judge (rubric)
          └────────────────────┼────────────────────┘
                               ▼
            suite averages ─► compare to baselines/<suite>.json
                               │
              ┌────────────────┴─────────────────┐
              ▼                                  ▼
      PR comment: per-metric deltas,      LangSmith experiment
      worst regressed cases + reasons     (full trace, per-case feedback)
              │
              ▼
      exit 0 pass · 1 regression · 2 config error · 3 infra error
```

### 4.2 Key components

| Component | What it does | Why this choice |
|---|---|---|
| **Golden sets** (`goldens/*.yaml`) | Named cases: inputs, a reference answer, which checks apply, tags. | YAML is readable in a PR diff. Stable case ids give per-case history. |
| **Deterministic checks** | `exact`, `contains`, `regex`, `json_schema`. | Cheap, exact, no noise. Use these wherever a hard requirement exists, such as "must mention 30 days". |
| **Semantic similarity** | Cosine similarity of local sentence-transformer embeddings (`all-MiniLM-L6-v2`). | Free, fast, deterministic, needs no API key. Catches outputs that drift away from the reference meaning. |
| **LLM judge** | Claude scores each output 1–5 against a rubric file and explains its score. The output is structured, so it is always parseable. | Catches quality that the other two cannot: correctness, tone, completeness. The written reasoning makes failures reviewable. |
| **Baselines** (`baselines/*.json`) | The accepted scores per suite and per case, committed to the repo. | Keeps the gate offline and reproducible. Changing the accepted quality level becomes a reviewed PR. |
| **LangSmith** | One experiment per suite per run, with git metadata and per-case feedback. Results are replayed into LangSmith after the run. | History, side-by-side comparison of runs, and a trace UI we don't have to build. Never on the gate's critical path. |
| **pytest plugin + CLI** | Same pipeline, two entry points. | pytest fits existing CI and IDE habits. The CLI suits scripts and the baseline workflow. |

### 4.3 The gating rule

For every gated metric in a suite, compare the current average with the baseline average, **over the case ids present in both runs**:

- Fail if `baseline − current > max_drop` (default 0.05 on a 0–1 scale; configurable per metric).
- Fail if `current < floor` (optional absolute minimum per metric).

There are three safety rails:
- Errored evaluations (an API failure or a judge refusal) are **excluded from averages and counted separately**. If more than 10% error, the run exits with an infrastructure error (code 3). It is never reported as a pass or a regression. An outage must not look like a quality change.
- A suite with fewer than `min_cases` comparable cases only warns. Small samples are too noisy to block on.
- If the judge model differs from the one that produced the baseline, the run warns loudly. Scores from different graders are not comparable.

### 4.4 Changing the baseline

Quality can legitimately go down, for example after a deliberate trade-off, a stricter rubric, or a new judge model. The flow:

1. The PR fails the gate. The author explains the drop in the PR description.
2. After review and merge, a maintainer triggers the `baseline-update` workflow on `main`. It requires approval through a GitHub environment.
3. The workflow reruns the suites, writes new `baselines/*.json`, and opens a PR containing only those files. That PR is reviewed like any other.

Nobody edits baseline files by hand. Tooling enforces this, and it is also how the Claude Code agent configuration in this repo is set up.

## 5. Alternatives considered

| Alternative | Why not (for v1) |
|---|---|
| **Use LangSmith's evaluation features alone, no custom gate** | LangSmith records and compares experiments well, but it does not decide pass/fail for our CI. Keeping the baseline only in LangSmith would make the gate depend on a network service and an access token, and would hide the "accepted quality" decision outside code review. We still use LangSmith for everything except the decision. |
| **An existing open-source eval framework** (promptfoo, DeepEval, OpenAI Evals, …) | Each covers most of the scoring but brings its own config language, runner, and opinions about baselines. What we need on top (committed baselines, error-aware gating, exit-code contract, LangSmith metadata) would be bolted on anyway. The core we would write ourselves is small (~2.7k lines of Python in the reference implementation, about 1.7k statements). Revisit if scope grows. |
| **Exact-match / snapshot tests only** | LLM outputs vary run to run, so snapshots fail constantly or get loosened until they catch nothing. Deterministic checks are kept, but only for hard requirements. |
| **Similarity only, no judge** | Cheap, but it rewards rephrasing the reference and cannot tell a confident wrong answer from a right one with similar wording. |
| **Judge only, no similarity** | Higher cost and higher variance. Similarity is a free second signal and an early warning when the judge is noisy. |
| **Statistical test (bootstrap CI) instead of fixed `max_drop`** | More principled, but harder to explain in a PR comment and needs data on judge variance we don't have yet. Planned for v1.1 (§10, Q1). |
| **Run on a nightly schedule instead of on PRs** | Finds regressions after they are merged and makes blame harder. Nightly is kept for live API tests of the tool itself. |

## 6. Cost and performance

LLM judge calls are the only meaningful cost. Prices below are first-party Anthropic API list prices as of October 2026. Token counts are **estimates to be replaced with measured numbers in M2**.

Assumptions per judge call: rubric and instructions ~1.5k tokens (cached after the first call), case content ~1k input tokens, ~1.5k output tokens including the model's internal reasoning.

| Judge model | ≈ cost per judge call | 100 cases × 1 sample | 100 cases × 3 samples |
|---|---|---|---|
| `claude-opus-5-5` (default) | ~$0.035 | ~$3.50 | ~$10.50 |
| `claude-sonnet-5-5` | ~$0.017 | ~$1.70 | ~$5.10 |

At an assumed 20 qualifying PR runs per working day with one 100-case suite, that is roughly $35–70/day on the default model before re-runs. Levers, in order: only trigger on relevant paths (already in the design), use prompt caching (already in the design), lower `judge.effort`, switch to Sonnet 5.5, and reserve `samples > 1` for suites where variance has been measured to matter.

Wall time: with concurrency 4, a 100-case suite should finish in a few minutes, dominated by target and judge latency. Similarity on CPU adds seconds. The embedding model (~90 MB) is cached between CI runs.

## 7. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **Judge noise causes flaky failures** | People learn to re-run until it passes, and the gate loses credibility. | `max_drop` above observed noise; `samples > 1` where needed; `min_cases`; measure run-to-run variance in M2 and tune defaults from data. |
| **Judge model changes underneath us** (new version, server-side fallback) | Scores shift with no prompt change. | Pin the model in config. Record the served model on every score. Warn on mismatch with the baseline. Re-baseline deliberately. |
| **Golden set goes stale or is too easy** | The gate passes while real users see problems. | Cases are code, owned by the prompt's owners. The `golden-curator` agent drafts new cases from real traces for human review. Periodic review is listed in the rollout plan. |
| **Baseline creep** (repeatedly accepting small drops) | Quality decays through approved PRs. | Optional absolute `floor` per metric. Baseline-update PRs show the cumulative delta from the previous baseline. |
| **Rubric overfitting** (prompt tuned to please the judge) | High scores, worse answers. | Mix in deterministic checks and similarity. Keep rubrics specific and anchored. Have humans spot-check a sample of judge reasoning when baselines change. |
| **Secrets in fork PRs** | Fork PRs cannot run the judge. | Fork PRs run `validate` only and the summary says so. Maintainers can re-run on a branch. |
| **Sensitive data in golden sets is sent to LangSmith and Anthropic** | Data-handling exposure. | Golden sets must contain synthetic or approved data only. The `eval-reviewer` agent flags personal data in review. Tracking can be turned off per run. |
| **Cost overrun** | Surprise bill. | Path-filtered triggers, caching, and spend checked monthly against §6. |

## 8. Rollout plan

| Phase | Scope | Exit criteria |
|---|---|---|
| **M1 — offline core** | Config, golden loader, `validate`, deterministic checks, aggregation, baselines, gate, CLI with tracking off. | Example suite gates correctly with no network. Exit codes behave as specified. ✅ in reference implementation |
| **M2 — scoring** | Similarity and judge evaluators, rubrics, retries, error accounting. Measure judge variance and real token costs. | Live tests pass. Variance report published. §6 updated with measured numbers. |
| **M3 — tracking** | LangSmith experiments, dataset sync, `compare`. | Experiments visible with git metadata and per-case feedback. |
| **M4 — CI** | pytest plugin, Markdown/JUnit reports, PR comment, `baseline-update` workflow. | First real repo running the gate with `gate.mode = "warn"` for 2 weeks. |
| **Enforce** | Switch the first repo to `gate.mode = "enforce"`. | Fewer than 1 flaky failure per 20 runs during warn-only. Owners agree. |

The code for M2–M4 exists and is covered by offline tests. What remains for those phases is the measurement work (variance, real costs) and the warn-only trial on a real repository.

Warn-only mode (the gate reports but exits 0; infrastructure errors still exit 3) lets us tune thresholds on real traffic before anyone is blocked.

## 9. Success metrics

- At least one real regression caught before merge in the first month of enforcement.
- Flaky-failure rate (a failure that passes on an unchanged re-run) below 5%.
- Median added CI time under 5 minutes per PR.
- Judge spend within the §6 envelope.
- Prompt authors report the PR comment is enough to act on without opening LangSmith in most cases (informal survey after one month).

## 10. Open questions for reviewers

1. **Gate statistics.** Is a fixed `max_drop` acceptable for v1, with a bootstrap confidence interval in v1.1? Or should v1 ship with the statistical test?
2. **Default judge model.** Should the default be `claude-opus-5-5` (higher quality, ~2× cost) or `claude-sonnet-5-5`? The proposal is Opus by default, with Sonnet as an opt-in per suite.
3. **Baseline storage.** Are committed JSON files the right home, or do reviewers prefer LangSmith-only baselines? This RFC argues for committed files (§5).
4. **Per-tag thresholds.** Should we support stricter gates for tagged cases (e.g., `safety`) in v1?
5. **Ownership.** Who owns each golden set and rubric? Proposal: the owners of the prompt, listed in `CODEOWNERS`.
6. **Data policy.** Is synthetic-or-approved-only data in golden sets sufficient, or do we need a redaction step before LangSmith upload?

## 11. References

- [SPEC.md](../SPEC.md) — full technical specification (formats, CLI, exit codes, config).
- [README.md](../README.md) — user guide; [examples/support-bot](../examples/support-bot) — offline example.
- LangSmith docs — evaluation (`Client.evaluate`) and datasets: https://docs.langchain.com/langsmith
- Anthropic docs — structured outputs, prompt caching, models and pricing: https://docs.claude.com
