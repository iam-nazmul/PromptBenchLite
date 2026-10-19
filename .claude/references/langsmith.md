# LangSmith — how PromptBench uses it

Sources: LangSmith docs (docs.langchain.com/langsmith) via Context7 and the installed SDK (`langsmith` 0.14), checked 2026-10-19. Re-check before relying on a signature not shown here.

Implemented in `src/promptbench/tracking/langsmith.py`. Tests: `tests/test_tracking.py` (in-memory `FakeLangSmith`) and `tests/live/` (real round trip).

PromptBench uses LangSmith for **history and inspection only**. The gate never reads LangSmith (SPEC §8, G6).

## Env

| Var | Effect |
|---|---|
| `LANGSMITH_API_KEY` | Auth. Missing → no-op tracker with a warning (or exit 3 if `tracking.required`). |
| `LANGSMITH_PROJECT` | Overrides `tracking.project` (dataset/experiment prefix). |
| `PROMPTBENCH_TRACKING=off` | PromptBench uses the no-op tracker. Set in `.claude/settings.json`. |

## Design: replay, don't re-run

PromptBench runs the target and the evaluators itself. Tracking happens afterwards:

1. **Dataset sync.** The dataset is named `<project>.<suite>`. Examples are keyed by `metadata.case_id`.
   ```python
   client.has_dataset(dataset_name=name) / client.create_dataset(dataset_name=name, description=...)
   client.list_examples(dataset_name=name)                         # -> examples with .id/.inputs/.outputs/.metadata
   client.create_examples(dataset_name=name, examples=[{"inputs", "outputs", "metadata"}, ...])
   client.update_examples(dataset_name=name, updates=[{"id", "inputs", "outputs", "metadata"}, ...])
   client.delete_examples(example_ids=[...])                       # cases removed or now skipped
   ```
2. **Experiment.** `client.evaluate` with a replay target and a replay evaluator:
   ```python
   results = client.evaluate(
       replay_target,                 # inputs -> recorded output dict; raises if the target errored
       data=[examples...],            # only the cases that ran
       evaluators=[replay_scores],    # (run, example) -> {"results": [{"key", "score", "comment"}, ...]}
       experiment_prefix=suite,
       metadata={...git/CI metadata, "suite", "judge_model"},
       max_concurrency=config.concurrency,
   )
   results.experiment_name, results.url
   ```
   Returning several metrics from one evaluator through `{"results": [...]}` is supported. `EvaluationResults` is a TypedDict in `langsmith.evaluation.evaluator`.
3. Errored scores are never uploaded as 0. They become one `errored` feedback entry (the count, with reasons in the comment).

## Reading experiments back (`compare`, `baseline update --from-experiment`)

```python
runs = client.list_runs(project_name=experiment, is_root=True)          # run.reference_example_id
examples = client.list_examples(example_ids=[...])                      # example.metadata["case_id"]
feedback = client.list_feedback(run_ids=[...])                          # fb.run_id, fb.key, fb.score
client.read_project(project_name=experiment).extra["metadata"]          # experiment metadata (judge_model)
```

## Other evaluate() options (not used)

- `num_repetitions=N` re-runs the target. PromptBench handles judge variance with `judge.samples` instead.
- `upload_results=False` runs without recording. The no-op tracker covers this case without importing langsmith.

## Gotchas

- Experiment names get a random suffix after `experiment_prefix`. Always read `results.experiment_name`.
- Dataset edits made in the LangSmith UI are overwritten on the next sync.
- Duplicate `inputs` across cases share the first recorded output in the replay target. Scores are still matched precisely through `example.metadata.case_id`.
- Inputs and outputs are uploaded. Golden sets must contain synthetic or approved data only.
