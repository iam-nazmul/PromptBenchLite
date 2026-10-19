# LangSmith — how PromptBench uses it

Source: LangSmith docs (docs.langchain.com/langsmith), checked 2026-10-19 via Context7. Re-check before relying on a signature that is not shown here.

PromptBench uses LangSmith for **history and inspection only**. The gate never reads LangSmith (SPEC §8, G6).

## Install and env

```bash
uv add "langsmith[pytest]"     # pytest integration needs langsmith>=0.3.4
```

| Var | Effect |
|---|---|
| `LANGSMITH_API_KEY` | Auth. Missing → PromptBench disables tracking with a warning. |
| `LANGSMITH_PROJECT` | Default project for traces. |
| `LANGSMITH_TEST_SUITE` | Suite name that groups pytest-plugin runs. |
| `LANGSMITH_TEST_TRACKING=false` | pytest plugin runs tests normally, syncs nothing. Set in `.claude/settings.json`. |
| `PROMPTBENCH_TRACKING=off` | Our own switch: tracking adapter becomes the no-op adapter. |

## Datasets — sync from YAML

One dataset per suite, named `<tracking.project>/<suite>`. YAML is the source of truth. Upsert by case id stored in example metadata:

```python
from langsmith import Client

client = Client()
dataset = client.create_dataset(dataset_name=name, description=suite.description)

client.create_examples(
    dataset_id=dataset.id,
    examples=[
        {"inputs": c.inputs, "outputs": c.expected, "metadata": {"case_id": c.id, "tags": c.tags}}
        for c in new_cases
    ],
)

existing = {e.metadata["case_id"]: e for e in client.list_examples(dataset_name=name)}
client.update_examples(
    example_ids=[existing[c.id].id for c in changed],
    inputs=[c.inputs for c in changed],
    outputs=[c.expected for c in changed],
    metadata=[{"case_id": c.id, "tags": c.tags} for c in changed],
)
```

- `list_examples(dataset_name=..., metadata={...})` filters by metadata — use it to run a subset (`--tag`).
- Cases removed from YAML: delete (or archive) their examples so old ids don't linger in new experiments.
- Never write `skip:`ped cases as examples.

## Experiments — one per suite per run

```python
results = client.evaluate(
    target,                         # fn(inputs: dict) -> dict
    data=name,                      # or client.list_examples(...)
    evaluators=[...],               # see below
    experiment_prefix=suite.name,
    metadata={"git_sha": sha, "git_branch": branch, "pr_number": pr,
              "ci_run_url": url, "promptbench_version": v, "judge_model": model},
    max_concurrency=config.concurrency,
    upload_results=True,            # False = run locally, record nothing
)
results.experiment_name             # store in results.json / baseline file
results.to_pandas()                 # needs pandas
```

- `num_repetitions=N` runs each example N times. **We don't use it for judge variance** — `judge.samples` repeats only the judge, not the target. Keep the two separate.
- `upload_results=False` is an option for the no-op path, but the no-op adapter should not import or call LangSmith at all, so unit tests stay offline.

## Evaluator adapter

LangSmith evaluators take `(inputs, outputs, reference_outputs)` and return a bool, a number, or a dict `{"key": ..., "score": ..., "comment": ...}`. PromptBench evaluators return `list[Score]`, so wrap each one:

```python
def to_langsmith(evaluator):
    def _fn(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
        scores = evaluator.evaluate(Case.from_example(inputs, reference_outputs), Output(outputs))
        return {"results": [
            {"key": s.key, "score": s.value, "comment": s.comment}
            for s in scores if not s.errored
        ]}
    _fn.__name__ = evaluator.name
    return _fn
```

Errored scores are **not** sent as feedback with score 0; record them as a comment on the run (or a separate `errored` feedback key with no score) so LangSmith charts don't show fake drops.

> Returning multiple scores from one evaluator via `{"results": [...]}` — confirm against current docs when implementing; the single-score dict form is documented above.

## pytest plugin integration

```python
import pytest
from langsmith import testing as t

@pytest.mark.langsmith
def test_case(case):
    t.log_inputs(case.inputs)
    t.log_reference_outputs(case.expected)
    output = run_target(case)
    t.log_outputs(output.data)
    for s in score(case, output):
        t.log_feedback(key=s.key, score=s.value)
    assert all(s.passed is not False for s in scores)
```

Run with `pytest --langsmith-output` for the rich terminal view. Pass/fail is logged automatically under the `pass` feedback key.

## Comparing experiments (`promptbench compare`)

- `client.read_project(project_name=experiment_name, include_stats=True)` → aggregate feedback stats.
- Per-case: list runs for each experiment and join on `example.metadata["case_id"]`.

## Gotchas

- Experiment names get a random suffix after `experiment_prefix`; always read `results.experiment_name`, never construct it.
- Dataset edits in the LangSmith UI are overwritten on the next sync.
- Rate limits on large suites: keep `max_concurrency` aligned with `config.concurrency`.
- Inputs and outputs are uploaded. Golden sets must contain synthetic or approved data only.
