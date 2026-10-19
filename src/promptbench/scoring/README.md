# scoring

Aggregation, baseline files, and the regression gate (SPEC §8).

## Public API
- `CaseResult`, `SuiteResult` (`case_values()`, `error_counts()`, `keys`)
- `summarize(result) -> {key: MetricSummary(mean, n, errored, pass_rate)}`
- `Baseline`, `load_baseline(dir, suite)`, `build_baseline(result, git_sha)`, `write_baseline(dir, baseline)`
- `gate_suite(result, baseline, gate_config, judge_model) -> SuiteVerdict`, `RunVerdict(suites, mode).exit_code`
- `Status`: `pass | fail | warn | new`

## Gate rules
- Delta is computed on case ids present in **both** the baseline and the current run. The floor is checked on the full current mean.
- Fail if `baseline − current > max_drop` or `current < floor`.
- Downgraded to `warn` when fewer than `gate.min_cases` cases are comparable.
- Metric in the baseline but missing now (or all errored) → `fail`. Metric not in the baseline → `new`, not gated.
- No baseline for a suite → every metric is `new` and a warning is added.
- Judge model differs from the baseline's → warning.
- `errored / total > max_error_rate` → `infra_error`. Exit precedence is 3 > 1 > 0. `mode = "warn"` turns 1 into 0, but never 3.
- Comparisons use `EPS = 1e-6`, because baselines store 6 decimals.

## Invariants
- `gate.py` is pure: no I/O, no network. Same inputs → same verdict.
- Errored scores are excluded from every mean.
- Only `promptbench baseline update` (or `run --update-baseline`) writes baseline files. They are formatted deterministically (sorted, 2-space JSON, trailing newline) so diffs stay small.

## Tests
`uv run pytest tests/scoring` (table-driven, one case per rule)
