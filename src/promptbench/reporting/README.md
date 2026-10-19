# reporting

Turns a `RunOutcome` into human- and machine-readable output (SPEC §12).

## Public API
- `print_report(outcome, console=None)`: terminal tables (stderr by default).
- `render_markdown(outcome)`: starts with `MARKER` (`<!-- promptbench-report -->`), which the CI workflow uses to find and update its sticky PR comment.
- `render_junit(outcome)` / `write_junit(outcome, path)`: one testcase per golden case plus one per gated metric (`<suite>.gate`).
- `results_payload(outcome)` / `write_json(outcome, path)`: full results, `results_version = 1`.
- `baselines_from_results(path, suites=None)`: baseline candidates from a results file. Refuses suites whose status is `infra_error`.

## Invariants
- Each JSON suite entry carries `baseline_candidate`, built at run time. `baseline update --from-results` writes exactly that, so what was reviewed is what gets committed.
- Reporting never changes the verdict or the exit code.

## Tests
`uv run pytest tests/test_reporting.py`
