"""LangSmith tracking (SPEC §9). See .claude/references/langsmith.md.

PromptBench runs the target and evaluators itself, then *replays* the outputs and scores into a
LangSmith experiment, so the CLI and the pytest plugin share one code path and LangSmith is never
on the gate's critical path.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from promptbench.errors import InfraError
from promptbench.golden import Case, Suite
from promptbench.scoring.results import CaseResult, SuiteResult


def dataset_name(project: str, suite: str) -> str:
    return f"{project}.{suite}"


def _inputs_key(inputs: dict[str, Any]) -> str:
    return json.dumps(inputs, sort_keys=True, ensure_ascii=False)


def _example_payload(case: Case) -> dict[str, Any]:
    return {
        "inputs": case.inputs,
        "outputs": case.expected,
        "metadata": {"case_id": case.id, "tags": list(case.tags)},
    }


class LangSmithTracker:
    def __init__(
        self, client: Any, project: str, *, required: bool = False, max_concurrency: int = 4
    ) -> None:
        self.client = client
        self.project = project
        self.required = required
        self.max_concurrency = max_concurrency

    def record_suite(self, suite: Suite, result: SuiteResult, metadata: dict[str, Any]) -> list[str]:
        try:
            examples = self.sync_dataset(suite)
            self._evaluate(suite, result, examples, metadata)
        except Exception as e:
            msg = f"LangSmith tracking failed for suite {suite.suite!r}: {type(e).__name__}: {e}"
            if self.required:
                raise InfraError(msg) from e
            return [msg + " (results are still gated locally)"]
        return []

    def sync_dataset(self, suite: Suite) -> dict[str, Any]:
        """Upsert examples by case id; delete examples whose case is gone or skipped. Returns case_id → example."""
        name = dataset_name(self.project, suite.suite)
        if not self.client.has_dataset(dataset_name=name):
            self.client.create_dataset(dataset_name=name, description=suite.description or suite.suite)
        existing = {
            ex.metadata.get("case_id"): ex
            for ex in self.client.list_examples(dataset_name=name)
            if ex.metadata and ex.metadata.get("case_id")
        }
        wanted = {c.id: c for c in suite.cases if not c.skipped}

        new = [_example_payload(c) for cid, c in wanted.items() if cid not in existing]
        if new:
            self.client.create_examples(dataset_name=name, examples=new)
        changed = [
            {"id": existing[cid].id, **_example_payload(c)}
            for cid, c in wanted.items()
            if cid in existing and _differs(existing[cid], c)
        ]
        if changed:
            self.client.update_examples(dataset_name=name, updates=changed)
        stale = [ex.id for cid, ex in existing.items() if cid not in wanted]
        if stale:
            self.client.delete_examples(example_ids=stale)

        if new or changed or stale:
            existing = {
                ex.metadata.get("case_id"): ex
                for ex in self.client.list_examples(dataset_name=name)
                if ex.metadata and ex.metadata.get("case_id")
            }
        return {cid: ex for cid, ex in existing.items() if cid in wanted}

    def _evaluate(
        self, suite: Suite, result: SuiteResult, examples: dict[str, Any], metadata: dict[str, Any]
    ) -> None:
        by_case = {c.case_id: c for c in result.cases}
        outputs: dict[str, list[CaseResult]] = defaultdict(list)
        for c in result.cases:
            outputs[_inputs_key(c.inputs)].append(c)

        def replay_target(inputs: dict[str, Any]) -> dict[str, Any]:
            candidates = outputs.get(_inputs_key(inputs)) or []
            if not candidates:
                raise RuntimeError("no recorded output for these inputs")
            case = candidates[0]
            if case.output.errored:
                raise RuntimeError(case.output.error)
            return case.output.data

        def replay_scores(run: Any, example: Any) -> dict[str, Any]:
            case = by_case.get((example.metadata or {}).get("case_id", ""))
            if case is None:
                return {"results": []}
            results: list[dict[str, Any]] = [
                {"key": s.key, "score": s.value, "comment": s.comment} for s in case.scores if not s.errored
            ]
            errored = [s for s in case.scores if s.errored]
            if errored:
                results.append(
                    {
                        "key": "errored",
                        "score": len(errored),
                        "comment": "; ".join(f"{s.key}: {s.error}" for s in errored),
                    }
                )
            return {"results": results}

        data = [examples[c.case_id] for c in result.cases if c.case_id in examples]
        if not data:
            return
        experiment = self.client.evaluate(
            replay_target,
            data=data,
            evaluators=[replay_scores],
            experiment_prefix=suite.suite,
            metadata=metadata,
            max_concurrency=self.max_concurrency,
        )
        result.experiment = experiment.experiment_name
        result.experiment_url = getattr(experiment, "url", None)


def _differs(example: Any, case: Case) -> bool:
    payload = _example_payload(case)
    return bool(
        example.inputs != payload["inputs"]
        or (example.outputs or {}) != payload["outputs"]
        or (example.metadata or {}).get("tags") != payload["metadata"]["tags"]
    )


def fetch_experiment_scores(client: Any, experiment: str) -> dict[str, dict[str, float]]:
    """``{case_id: {key: score}}`` for a recorded experiment (used by `compare` and baseline import)."""
    runs = list(client.list_runs(project_name=experiment, is_root=True))
    run_to_example = {r.id: r.reference_example_id for r in runs if r.reference_example_id}
    if not run_to_example:
        return {}
    examples = client.list_examples(example_ids=list(set(run_to_example.values())))
    example_to_case = {ex.id: (ex.metadata or {}).get("case_id") for ex in examples}
    scores: dict[str, dict[str, float]] = defaultdict(dict)
    for fb in client.list_feedback(run_ids=list(run_to_example)):
        case_id = example_to_case.get(run_to_example.get(fb.run_id))
        if case_id and fb.score is not None and fb.key != "errored":
            scores[case_id][fb.key] = float(fb.score)
    return dict(scores)
