---
name: update-baseline
description: Accept a new quality level by regenerating baselines/*.json through the approved PromptBench flow. Use only when the user explicitly wants to accept new scores — after an intended trade-off, a rubric/judge/similarity-model change, or a new suite/metric. Never use it to make a failing PR pass without that decision.
---

# Update a baseline

Baselines are the accepted quality level. Changing them is a product decision, so a human must have made it. **Before doing anything, confirm with the user in plain words: which suites, and why the new level is acceptable.** If they cannot say why, stop and use `triage-regression` instead.

Hand edits to `baselines/*.json` are blocked by `.claude/hooks/protect_files.py`. Do not work around the hook.

## Valid reasons

- A deliberate trade-off reviewed in a merged PR (e.g., shorter answers, lower similarity accepted).
- Grader change: new `judge.model`, edited rubric, new `similarity.model`.
- New suite, or new metric/evaluator added to a suite (not gated until baselined).
- Cases added or removed and the user wants them in the gated set.

## Not valid

- "CI is red and we want to merge." That is a regression to triage, not a baseline update.
- An infra failure (exit 3) or a run with errored scores above the limit.

## Preferred: CI workflow (on `main`)

1. The change that caused the new level is merged to `main`.
2. Ask the user to confirm, then:
   ```bash
   gh workflow run baseline-update.yml --ref main -f suites="<suite1,suite2>" -f reason="<one line>"
   ```
3. The workflow waits for environment approval, re-runs the suites, and opens a PR containing only `baselines/*.json`.
4. Review that PR with the user: per-metric old → new, the cumulative change since the previous baseline, `judge_model`, and added/removed case ids.

## Local (only when the user asks, e.g. a new suite in a branch)

Costs money — ask first.

```bash
uv run promptbench run --suite <suite> --json results.json            # must exit 0 or 1, never 3
uv run promptbench baseline update --suite <suite> --from-results results.json
uv run promptbench baseline show --suite <suite>
```

Check before committing:
- `errored` counts are 0 or explainable.
- `judge_model` in the new file is the intended model.
- `git diff baselines/` shows only the intended suites.

Commit the baseline files in their **own commit**, with the reason in the message, so the change is easy to review and revert.
