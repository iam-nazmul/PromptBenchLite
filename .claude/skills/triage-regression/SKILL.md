---
name: triage-regression
description: Diagnose a failed PromptBench gate (exit code 1) or infra failure (exit 3) — decide whether it is a real quality regression, judge/grader noise, a config or baseline mismatch, or an infrastructure problem, and recommend the fix. Use when CI fails on promptbench, a PR comment shows red metrics, or the user asks why scores dropped.
---

# Triage a PromptBench failure

Goal: a short verdict with evidence — **real regression**, **noise**, **grader change**, **eval bug**, or **infra** — and the next action. Do not "fix" a failure by editing goldens, rubrics, thresholds or baselines unless the user agrees that is the correct call.

For a long investigation, hand off to the `regression-analyst` agent.

## 1. Get the report

- CI: `gh run list --workflow promptbench.yml` → `gh run view <id> --log-failed`, and the `report.md` / `results.json` artifacts (`gh run download <id>`).
- Local: `results.json` from `promptbench run --json results.json`.
- Note the **exit code**: 1 = gate failed, 2 = config/validation, 3 = infra.

## 2. Exit 3 or 2 — not a quality question

- **3**: look at the `errored` counts per evaluator. Common causes: missing/expired `ANTHROPIC_API_KEY` or `LANGSMITH_API_KEY`, rate limits (429), judge refusals (`stop_reason == "refusal"`), target timeouts. Fix the infra; re-run. Never re-baseline on an infra failure.
- **2**: run `uv run promptbench validate` and fix what it reports.

## 3. Exit 1 — check for grader or setup changes first

Run through these before blaming the prompt:

| Check | Where | If true |
|---|---|---|
| Judge model differs from baseline | report warning; `baseline.judge_model` vs config | Grader change — scores not comparable. Re-baseline deliberately. |
| Verdicts served by a fallback model | `Score.metadata.served_model` in `results.json` | Grader changed for some cases. Re-run; if it persists, raise with user. |
| Rubric file changed in this PR | `git diff main -- rubrics/` | Eval change, not prompt change. Needs re-baseline + review by `eval-reviewer`. |
| Similarity model changed | `promptbench.toml` diff | Same — re-baseline. |
| Few comparable cases | report: `n`, added/removed ids | Small-sample noise. |

## 4. Real regression or noise?

1. List the regressed cases sorted by delta (report's "top regressed" table, or `promptbench compare <baseline_experiment> <current_experiment>`).
2. For the top 3–5, read: input, expected, new output, judge reasoning.
3. Classify:
   - Outputs clearly worse and reasoning is specific → **real regression**. Identify which prompt change causes it (`git diff main -- <prompt files>`).
   - Outputs equivalent, scores moved by ≤ 1 judge point on scattered cases, no pattern → **noise**. Evidence: re-run the suite once (ask first — costs money). If it passes on an unchanged re-run, it is noise; recommend raising `judge.samples` or `max_drop` for that metric and record it.
   - Outputs correct but the case's `expected` or rubric is wrong → **eval bug**. Fix the case/rubric in a separate PR reviewed by `eval-reviewer`.
4. Check whether the drop is concentrated in one tag (`--tag`) — a pattern is strong evidence of a real regression.

## 5. Report back

```
Verdict: real regression | noise | grader change | eval bug | infra
Metric(s): judge.correctness 0.86 → 0.78 (max_drop 0.05)
Evidence: 6/40 cases dropped ≥ 2 points, all tagged `refunds`; outputs stopped mentioning the 30-day window after line 12 of prompts/support.md changed.
Next action: <concrete step>
```

If the user decides the drop is an accepted trade-off, point them to the `update-baseline` skill. Do not run it yourself.
