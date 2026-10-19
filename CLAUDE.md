# PromptBench Lite

Regression-testing toolkit for prompts and LLM outputs in CI. Full spec: [SPEC.md](SPEC.md).

## Architecture

```
goldens/*.yaml ─► golden/ (load+validate) ─► runner/ ─► target callable ─► outputs
                                                                │
                        ┌───────────────────────────────────────┼─────────────────────┐
                        ▼                                       ▼                     ▼
          evaluators/deterministic             evaluators/similarity      evaluators/judge
          exact|contains|regex|json_schema     sentence-transformers      Claude + rubrics/*.md
                        └───────────────────────────────────────┼─────────────────────┘
                                                                ▼
                                              scoring/ aggregate ─► gate vs baselines/*.json
                                                   │                        │
                                                   ▼                        ▼
                                  tracking/ (LangSmith | no-op)    reporting/ (terminal, md, junit, json)
                                                                            │
                         cli.py  ◄──────── same pipeline ────────►  pytest_plugin.py
                                                                            │
                                                                     exit 0 / 1 / 2 / 3
```

## Commands

```bash
uv sync                                   # install (dev deps included)
uv run pytest                             # unit tests — offline, no keys needed
uv run pytest tests/path::test_name -x    # single test
uv run pytest -m live                     # real Anthropic + LangSmith calls — costs money, ask first
uv run ruff check --fix . && uv run ruff format .
uv run mypy src
uv run promptbench validate               # schema-check goldens/rubrics/config, no network
uv run promptbench run --no-tracking      # full run, judge calls cost money — ask first
```

## Rules

- **Never edit `baselines/*.json` by hand.** Only `promptbench baseline update` writes them, and only after a human approves the quality change. A hook blocks direct edits.
- **Golden case `id`s are immutable** once merged. Renaming an id loses history; add a new case instead.
- **Unit tests must stay offline.** Use the `fake_anthropic`, `stub_similarity` and `noop_tracker` fixtures in `tests/conftest.py`. Anything that hits a real API goes in `tests/live/` with `@pytest.mark.live`.
- **The gate must not depend on the network.** It reads committed baselines and current scores. Nothing else.
- **Errors are not scores.** A failed or refused judge call yields an errored `Score`, never `0.0`. See SPEC §8.4.
- **Exit codes are a contract** (0 pass, 1 regression, 2 config, 3 infra). Changing them is a breaking change.
- Judge default model is `claude-opus-5-5`; current models reject `temperature`, so reduce variance with `judge.samples`, not sampling params.
- Each module under `src/promptbench/` has a `README.md`. Update it when the module's public API or invariants change; add one for any new module.
- Keep comments minimal — only when the *why* is not obvious.
- Read `.env` never. Use `.env.example` for the variable list.
- Claude sessions run with `PROMPTBENCH_TRACKING=off` and `LANGSMITH_TEST_TRACKING=false` (set in `.claude/settings.json`) so agent runs don't pollute LangSmith history.

## Recipes

| Task | Use |
|---|---|
| Add golden cases | skill `add-golden-case` |
| Add an evaluator | skill `add-evaluator` |
| CI failed with exit 1 | skill `triage-regression` (or agent `regression-analyst`) |
| Accept a new quality level | skill `update-baseline` |
| Review eval/rubric changes | agent `eval-reviewer` |
| Draft cases from traces/logs | agent `golden-curator` |

Reference notes for external APIs live in `.claude/references/`: `langsmith.md`, `anthropic-judge.md`, `similarity.md`, `github-actions.md`, `rubric-writing.md`.

## Gotchas

- Similarity scores across embedding models are not comparable. Changing `similarity.model` requires a baseline update.
- Same for `judge.model`: the gate warns when the baseline's `judge_model` differs. Treat that as a reason to re-baseline, not as a regression.
- Server-side fallback can serve a judge verdict from a different model. Check `Score.metadata["served_model"]` before blaming a prompt.
- Judge rubric text is in the cached system prefix — any byte change (including whitespace) invalidates the cache and can shift scores. Rubric edits need a baseline update.
- Only case ids present in both baseline and current run are compared; a suite where most ids changed will gate on very few cases (`min_cases` warns).
- Fork PRs have no secrets; CI runs `validate` only there.
- LangSmith dataset sync upserts by case `id` in example metadata; YAML is the source of truth, never edit examples in the LangSmith UI.
