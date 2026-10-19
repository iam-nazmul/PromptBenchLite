# GitHub Actions for PromptBench

Sources: astral-sh/setup-uv README (via Context7) and GitHub Actions docs, checked 2026-10-19. The `setup-uv` pin was verified with `git ls-remote`: `bec219d24cd3e171d82865faccec33120bb574f4` = v10.1.0.

The workflows are the source of truth. Read them rather than copying snippets from here:

| Workflow | Trigger | What it does |
|---|---|---|
| `.github/workflows/ci.yml` | push to main, PRs | ruff, format check, mypy, `coverage run -m pytest` (≥90%) on Python 3.11 and 3.13. Then the example end to end: unchanged must exit 0, `SUPPORT_BOT_VARIANT=degraded` must exit 1. |
| `.github/workflows/promptbench.yml` | PRs touching prompts/goldens/rubrics/src/examples | `validate`, then `run` with Markdown/JUnit/JSON output, artifacts, and a sticky PR comment. `PB_ROOT` selects the project (`examples/support-bot` here, `.` in a user repo). |
| `.github/workflows/baseline-update.yml` | `workflow_dispatch` on main | Waits for `baseline-approval` environment approval, runs the suites, writes baselines `--from-results`, opens a PR with only baseline files. Exit 0/1 continue; 2/3 abort. |
| `.github/workflows/live.yml` | nightly cron, manual | `PROMPTBENCH_LIVE=1 pytest -m live` with real secrets. |

## Patterns used (and why)

- **Secrets in `if:`**: `secrets.*` can't be used directly in step `if:`, so a step writes `has_keys=${{ secrets.ANTHROPIC_API_KEY != '' }}` to `$GITHUB_OUTPUT`.
- **Fork PRs** get no secrets. They run `validate` only. Never switch to `pull_request_target` to work around this, because it runs untrusted PR code with secrets.
- **Sticky comment**: `report.md` starts with `<!-- promptbench-report -->`. The step finds a comment that starts with the marker and PATCHes it, otherwise it creates one. It is skipped for fork PRs, whose token can't comment.
- **Step summary**: `promptbench run` appends the Markdown report to `$GITHUB_STEP_SUMMARY` itself.
- **Exit code is the signal**: no `continue-on-error`. During rollout, use `gate.mode = "warn"` in config instead.
- **`uv sync --frozen`** fails on a stale `uv.lock`. That's intended.
- **Model cache**: `SENTENCE_TRANSFORMERS_HOME=.cache/st` with `actions/cache` keyed on the model name.
- **Inputs to shell**: workflow inputs go through `env:`, never interpolated straight into `run:`, which avoids script injection.

## Secrets

| Secret | Used by |
|---|---|
| `ANTHROPIC_API_KEY` | judge (`judge.provider = "anthropic"`) |
| `LANGSMITH_API_KEY` | tracking (optional) |

Never `echo` a secret or put one on a command line.
