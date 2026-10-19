# PromptBench Lite

Regression-testing toolkit for prompts and LLM outputs in CI. Spec: [SPEC.md](SPEC.md). Rationale: [docs/RFC.md](docs/RFC.md). Each package under `src/promptbench/` has a README with its API and invariants.

## Architecture

```
goldens/*.yaml ─► golden/ (load+validate) ─► pipeline.plan_suite ─► runner/ ─► target callable ─► Output
                                                                                      │
                     ┌────────────────────────────────────────────────────────────────┼───────────────────┐
                     ▼                                          ▼                                         ▼
       evaluators/deterministic                 evaluators/similarity                       evaluators/judge
       exact|contains|regex|json_schema         sentence_transformers | lexical            anthropic | fake + rubrics/*.md
                     └────────────────────────────────────────────────────────────────┼───────────────────┘
                                                                                      ▼
                                                    pipeline.evaluate_case ─► SuiteResult
                                                                  │                │
                                         tracking/ (LangSmith replay | no-op)      ▼
                                                                    scoring/gate vs baselines/*.json  (pure, offline)
                                                                                   │
                                                  reporting/ (terminal, markdown, junit, json) + exit 0/1/2/3
                                                                                   ▲
                                          cli.py ───────── same pipeline ───────── pytest_plugin.py
```

## Commands

```bash
uv sync                                       # install (dev group included)
uv run pytest                                 # unit tests — offline, no keys
uv run pytest tests/path.py::test_name -x     # single test
uv run coverage run -m pytest && uv run coverage report   # coverage (not --cov; see gotchas)
uv run ruff check --fix . && uv run ruff format .
uv run mypy
uv run promptbench validate --root examples/support-bot
uv run promptbench run --root examples/support-bot --no-tracking            # offline example, free
SUPPORT_BOT_VARIANT=degraded uv run promptbench run --root examples/support-bot --no-tracking   # expect exit 1
PROMPTBENCH_LIVE=1 uv run pytest -m live      # real Anthropic/LangSmith — costs money, ask first
```

## Rules

- **Never edit `baselines/*.json` by hand.** Only `promptbench baseline update` or `run --update-baseline` writes them, and only after a human approves the quality change. A hook blocks direct edits.
- **Golden case `id`s are immutable** once merged. Add a new case instead of renaming.
- **Unit tests stay offline.** Use `fake_anthropic`, `stub_similarity`, `noop_tracker` and `make_project` from `tests/conftest.py`, or `FakeLangSmith` in `tests/test_tracking.py`. Real-API tests go in `tests/live/` with `pytestmark = pytest.mark.live`.
- **The gate must not depend on the network.** `scoring/gate.py` stays pure.
- **Errors are not scores.** A failed or refused evaluation returns `Score.errored_score(...)`, never `0.0`.
- **Exit codes are a contract** (0 pass, 1 regression, 2 config, 3 infra). Raise `ConfigError` or `InfraError`, and let `cli.guarded` map them.
- **No network or model loading at construction time.** The Anthropic client and the embedding model are lazy, so `validate` works without keys.
- Judge requests never send `temperature`, `thinking`, forced `tool_choice` or a prefill. Current models reject all four. Reduce variance with `judge.samples`.
- Update a package's `README.md` when its public API or invariants change. Add a README for any new package. Keep SPEC.md in sync with behaviour.
- Comments only when the *why* is not obvious.
- Never read `.env`. Use `.env.example` for the variable list.
- Claude sessions run with `PROMPTBENCH_TRACKING=off` (set in `.claude/settings.json`), so agent runs don't write to LangSmith.

## Recipes

| Task | Use |
|---|---|
| Add golden cases | skill `add-golden-case` |
| Add an evaluator | skill `add-evaluator` |
| CI failed with exit 1 or 3 | skill `triage-regression` (or agent `regression-analyst`) |
| Accept a new quality level | skill `update-baseline` |
| Review eval/rubric/threshold changes | agent `eval-reviewer` |
| Draft cases from traces/logs | agent `golden-curator` |
| New CLI flag | add to `cli.py`, document in SPEC §10 and README, add a `tests/test_cli.py` case |
| New config key | add to the model in `config.py` (it forbids unknown keys), SPEC §7, README config reference |

Reference notes for external APIs are in `.claude/references/`: `langsmith.md`, `anthropic-judge.md`, `similarity.md`, `github-actions.md`, `rubric-writing.md`.

## Gotchas

- **Coverage:** the pytest11 entry point imports `promptbench` before pytest-cov starts, so `--cov` under-reports. Use `coverage run -m pytest`.
- **anthropic 1.x uses `httpx2`**, not `httpx`. Build fake errors with `httpx2.Request/Response`.
- **ruff formats Markdown code blocks** in this version. `*.md` is excluded in `pyproject.toml`. Keep it that way, or the docs get rewritten.
- Tests that create target modules must use unique module names (`make_project` does), because `sys.modules` caches imports across tests.
- Scores from different graders are not comparable. This applies to `judge.model`, `judge.provider`, any rubric edit (even whitespace, because it changes the cached prefix), `similarity.model` and `similarity.backend`. All of these need a baseline update.
- Server-side fallback can serve a verdict from a different model. Check `metadata.served_model` before blaming a prompt.
- Only case ids present in both the baseline and the current run are compared. A suite where most ids changed gates on few cases (`min_cases` downgrades failures to warnings).
- LangSmith datasets are named `<project>.<suite>`. YAML is the source of truth, so don't edit examples in the LangSmith UI.
- Fork PRs have no secrets. `promptbench.yml` runs `validate` only for real suites. The bundled example still runs, because it needs no keys.
- A timed-out target keeps running in its thread (threads can't be killed). Targets should set their own HTTP timeouts.
