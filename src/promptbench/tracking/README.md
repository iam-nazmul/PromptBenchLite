# tracking

Records finished suites in LangSmith (SPEC §9). Never on the gate's critical path.

## Public API
- `Tracker` protocol: `record_suite(suite, result, metadata) -> list[str]` (warnings). Sets `result.experiment` / `experiment_url`.
- `NoopTracker`: tracking off.
- `make_tracker(config, disabled=False, env=None) -> (Tracker, warnings)`: returns a no-op tracker when tracking is disabled or `LANGSMITH_API_KEY` is missing. Raises `InfraError` if `tracking.required` and the key is missing.
- `langsmith.LangSmithTracker(client, project, required=False)`, `sync_dataset(suite)`, `fetch_experiment_scores(client, experiment)`, `dataset_name(project, suite)` → `"<project>.<suite>"`

## How it works
1. **Dataset sync.** One dataset per suite. Examples are upserted by `metadata.case_id`. Examples whose case was deleted or is now skipped are removed. The YAML is the source of truth.
2. **Replay.** `client.evaluate` runs a *replay* target that returns the outputs PromptBench already produced. A replay evaluator returns the already-computed scores as `{"results": [...]}`. Errored scores become one `errored` feedback entry (count + reasons), never a 0.

## Invariants
- A tracking failure is a warning unless `tracking.required = true`, in which case it's an `InfraError` (exit 3).
- `NoopTracker` imports nothing from `langsmith`.

## Tests
`uv run pytest tests/test_tracking.py` (in-memory fake client). Real round trip: `tests/live/` with `PROMPTBENCH_LIVE=1`.
