# promptbench (package root)

Top-level modules that are not packages of their own. Each package below has its own README.

| Module | Purpose |
|---|---|
| `config.py` | Load and validate `promptbench.toml` (or `[tool.promptbench]`), then apply env overrides. Public: `load_config(root, env)`, `Config` and sub-models. |
| `errors.py` | Exit-code contract: `ConfigError` → 2, `InfraError` → 3. Constants `EXIT_PASS/REGRESSION/CONFIG/INFRA`. |
| `pipeline.py` | The shared flow used by the CLI and the pytest plugin: `plan_suite` → `execute` → `evaluate_case` → tracker → `gate`. Public: `validate`, `run`, `RunOutcome`, `SuitePlan`. |
| `gitinfo.py` | Git/CI metadata (`git_sha`, `git_branch`, `run_metadata`). Prefers `GITHUB_*` env, falls back to `git`. |
| `cli.py` | `promptbench` console script (typer). Maps `PromptBenchError` to exit codes via `@guarded`. |
| `pytest_plugin.py` | pytest11 entry point. Inert unless `--promptbench`. Handles the `live` marker always. |

## Invariants
- `config.Config` forbids unknown keys, so a typo is a config error (exit 2), not silently ignored.
- `pipeline.run` never raises because a target or evaluator failed. Those become errored scores. It raises only `ConfigError` / `InfraError`.
- The gate (`scoring.gate`) is called with local data only. Tracking happens before it but can't change its inputs.

## Tests
`tests/test_config.py`, `tests/test_pipeline.py`, `tests/test_cli.py`, `tests/test_pytest_plugin.py`.
