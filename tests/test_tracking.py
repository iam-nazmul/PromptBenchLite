from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from promptbench import pipeline
from promptbench.config import Config, TrackingConfig
from promptbench.errors import InfraError
from promptbench.evaluators import EvalContext
from promptbench.golden import load_suite
from promptbench.tracking import NoopTracker, make_tracker
from promptbench.tracking.langsmith import LangSmithTracker, dataset_name, fetch_experiment_scores


@dataclass
class FakeLangSmith:
    """In-memory stand-in for the parts of ``langsmith.Client`` the tracker uses."""

    datasets: dict[str, dict[str, Any]] = field(default_factory=dict)
    evaluated: list[dict[str, Any]] = field(default_factory=list)
    fail_on_evaluate: bool = False

    def has_dataset(self, *, dataset_name: str) -> bool:
        return dataset_name in self.datasets

    def create_dataset(self, *, dataset_name: str, description: str) -> None:
        self.datasets[dataset_name] = {}

    def list_examples(self, *, dataset_name: str | None = None, example_ids: Any = None) -> list[Any]:
        if example_ids is not None:
            return [ex for ds in self.datasets.values() for ex in ds.values() if ex.id in set(example_ids)]
        return list(self.datasets[dataset_name].values())

    def create_examples(self, *, dataset_name: str, examples: list[dict[str, Any]]) -> None:
        for ex in examples:
            ex_id = uuid.uuid4().hex
            self.datasets[dataset_name][ex_id] = SimpleNamespace(id=ex_id, **ex)

    def update_examples(self, *, dataset_name: str, updates: list[dict[str, Any]]) -> None:
        for upd in updates:
            self.datasets[dataset_name][upd["id"]] = SimpleNamespace(**upd)

    def delete_examples(self, *, example_ids: list[str]) -> None:
        for ds in self.datasets.values():
            for ex_id in example_ids:
                ds.pop(ex_id, None)

    def evaluate(self, target: Any, *, data: list[Any], evaluators: list[Any], **kwargs: Any) -> Any:
        if self.fail_on_evaluate:
            raise ConnectionError("langsmith down")
        rows = []
        for ex in data:
            try:
                outputs, error = target(ex.inputs), None
            except RuntimeError as e:
                outputs, error = None, str(e)
            rows.append(
                {
                    "example": ex,
                    "outputs": outputs,
                    "error": error,
                    "feedback": evaluators[0](SimpleNamespace(outputs=outputs), ex),
                }
            )
        self.evaluated.append({"rows": rows, **kwargs})
        return SimpleNamespace(experiment_name=f"{kwargs['experiment_prefix']}-abc", url="https://smith/x")


@pytest.fixture
def tracked(make_project):
    project = make_project()
    project.set_answers(
        {"refund": "You can request a refund within 30 days of purchase."}, fail_on={"cancel"}
    )
    config = project.config()
    client = FakeLangSmith()
    tracker = LangSmithTracker(client, "pb")
    outcome = pipeline.run(config, EvalContext(config=config), tracker=tracker)
    return project, client, outcome


def test_dataset_synced_and_experiment_recorded(tracked) -> None:
    _, client, outcome = tracked
    ds = client.datasets[dataset_name("pb", "demo")]
    assert sorted(ex.metadata["case_id"] for ex in ds.values()) == [
        "cancel",
        "email",
        "invoice",
        "password",
        "refund",
    ]
    (run,) = client.evaluated
    assert run["experiment_prefix"] == "demo"
    assert run["metadata"]["suite"] == "demo" and run["metadata"]["judge_model"] == "fake-judge"
    assert outcome.results[0].experiment == "demo-abc"
    assert outcome.results[0].experiment_url == "https://smith/x"

    rows = {r["example"].metadata["case_id"]: r for r in run["rows"]}
    assert rows["refund"]["outputs"] == {"answer": "You can request a refund within 30 days of purchase."}
    keys = {f["key"] for f in rows["refund"]["feedback"]["results"]}
    assert keys == {"similarity", "judge.correctness", "contains"}
    assert rows["cancel"]["error"] == "RuntimeError: boom"
    errored = rows["cancel"]["feedback"]["results"]
    assert [f["key"] for f in errored] == ["errored"] and errored[0]["score"] == 2


def test_resync_updates_and_deletes(tracked) -> None:
    project, client, _ = tracked
    text = project.golden_path().read_text()
    text = text.replace("  - id: email\n", "  - id: email\n    skip: later\n").replace(
        "tags: [account]", "tags: [acct]", 1
    )
    project.golden_path().write_text(text)
    LangSmithTracker(client, "pb").sync_dataset(load_suite(project.golden_path()))
    ds = client.datasets[dataset_name("pb", "demo")]
    by_case = {ex.metadata["case_id"]: ex for ex in ds.values()}
    assert "email" not in by_case
    assert by_case["password"].metadata["tags"] == ["acct"]


def test_tracking_failure_warns_or_raises(make_project) -> None:
    project = make_project()
    config = project.config()
    client = FakeLangSmith(fail_on_evaluate=True)
    outcome = pipeline.run(config, EvalContext(config=config), tracker=LangSmithTracker(client, "pb"))
    assert any("tracking failed" in w for w in outcome.warnings)
    assert outcome.verdict.exit_code == 0
    with pytest.raises(InfraError):
        pipeline.run(
            config, EvalContext(config=config), tracker=LangSmithTracker(client, "pb", required=True)
        )


def test_make_tracker_choices() -> None:
    cfg = Config()
    assert isinstance(make_tracker(cfg, disabled=True, env={})[0], NoopTracker)
    tracker, warnings = make_tracker(cfg, env={})
    assert isinstance(tracker, NoopTracker) and "LANGSMITH_API_KEY" in warnings[0]
    with pytest.raises(InfraError):
        make_tracker(Config(tracking=TrackingConfig(required=True)), env={})
    off = Config(tracking=TrackingConfig(enabled=False))
    tracker, warnings = make_tracker(off, env={"LANGSMITH_API_KEY": "x"})
    assert isinstance(tracker, NoopTracker) and warnings == []


def test_fetch_experiment_scores() -> None:
    client = SimpleNamespace(
        list_runs=lambda **kw: [SimpleNamespace(id="r1", reference_example_id="e1")],
        list_examples=lambda **kw: [SimpleNamespace(id="e1", metadata={"case_id": "a"})],
        list_feedback=lambda **kw: [
            SimpleNamespace(run_id="r1", key="similarity", score=0.5),
            SimpleNamespace(run_id="r1", key="errored", score=1),
            SimpleNamespace(run_id="r1", key="judge.c", score=None),
        ],
    )
    assert fetch_experiment_scores(client, "exp") == {"a": {"similarity": 0.5}}
