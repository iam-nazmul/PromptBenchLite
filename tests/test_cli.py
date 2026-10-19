import json

import pytest
from typer.testing import CliRunner

from promptbench.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("GITHUB_STEP_SUMMARY", "LANGSMITH_API_KEY", "GITHUB_HEAD_REF", "GITHUB_REF_NAME"):
        monkeypatch.delenv(var, raising=False)


def cli(*args: str):
    return runner.invoke(app, list(args))


def test_validate_ok_and_error(make_project) -> None:
    project = make_project()
    res = cli("validate", "--root", str(project.root))
    assert res.exit_code == 0, res.output
    assert "demo: 5 cases (1 skipped)" in res.output
    project.golden_path().write_text("suite: demo\n")
    assert cli("validate", "--root", str(project.root)).exit_code == 2


def test_full_flow(make_project, tmp_path, monkeypatch) -> None:
    project = make_project()
    root = str(project.root)
    results = tmp_path / "results.json"
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    res = cli("run", "--root", root, "--json", str(results), "--junit", str(tmp_path / "j.xml"))
    assert res.exit_code == 0, res.output
    assert "no baseline" in res.output
    assert summary.read_text().startswith("<!-- promptbench-report -->")

    res = cli("baseline", "update", "--root", root, "--from-results", str(results))
    assert res.exit_code == 0, res.output
    assert (project.root / "baselines" / "demo.json").exists()
    assert "judge.correctness" in cli("baseline", "show", "--root", root).output

    report = tmp_path / "report.md"
    assert cli("run", "--root", root, "--report-md", str(report)).exit_code == 0

    project.set_answers({"refund": "nope", "cancel": "nope", "password": "nope"})
    res = cli("run", "--root", root, "--report-md", str(report))
    assert res.exit_code == 1, res.output
    assert "Quality regression" in report.read_text()


def test_infra_exit_code(make_project) -> None:
    project = make_project()
    project.set_answers({}, fail_on={"refund", "cancel", "password", "invoice", "email"})
    assert cli("run", "--root", str(project.root)).exit_code == 3


def test_warn_mode_exits_zero(make_project) -> None:
    from tests.conftest import DEFAULT_CONFIG

    project = make_project(config=DEFAULT_CONFIG.replace("min_cases = 3", 'min_cases = 3\nmode = "warn"'))
    root = str(project.root)
    assert cli("run", "--root", root, "--update-baseline", "--i-know-what-im-doing").exit_code == 0
    project.set_answers({"refund": "nope", "cancel": "nope", "password": "nope"})
    res = cli("run", "--root", root)
    assert res.exit_code == 0 and "warn-only" in res.output


@pytest.mark.parametrize(
    "args",
    [
        ("baseline", "update"),
        ("baseline", "update", "--from-results", "x.json", "--from-experiment", "e"),
        ("run", "--update-baseline", "--tag", "billing"),
        ("run", "--suite", "nope"),
        ("baseline", "show", "--suite", "nope"),
    ],
)
def test_usage_errors_exit_2(make_project, args) -> None:
    project = make_project()
    assert cli(*args, "--root", str(project.root)).exit_code == 2


def test_update_baseline_refused_off_main(make_project, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_HEAD_REF", "feature/x")
    project = make_project()
    res = cli("run", "--root", str(project.root), "--update-baseline")
    assert res.exit_code == 2 and "--i-know-what-im-doing" in res.output
    monkeypatch.setenv("GITHUB_HEAD_REF", "main")
    assert cli("run", "--root", str(project.root), "--update-baseline").exit_code == 0


def test_compare_needs_langsmith_key() -> None:
    assert cli("compare", "a", "b").exit_code == 3


def test_baseline_update_refuses_infra_results(make_project, tmp_path) -> None:
    project = make_project()
    project.set_answers({}, fail_on={"refund", "cancel", "password", "invoice", "email"})
    results = tmp_path / "r.json"
    cli("run", "--root", str(project.root), "--json", str(results))
    assert json.loads(results.read_text())["suites"][0]["status"] == "infra_error"
    res = cli("baseline", "update", "--root", str(project.root), "--from-results", str(results))
    assert res.exit_code == 2 and not (project.root / "baselines" / "demo.json").exists()


def _fake_langsmith(experiments: dict[str, dict[str, dict[str, float]]]):
    from types import SimpleNamespace

    runs = {
        exp: [SimpleNamespace(id=f"{exp}:{cid}", reference_example_id=cid) for cid in cases]
        for exp, cases in experiments.items()
    }
    return SimpleNamespace(
        list_runs=lambda project_name, is_root: runs[project_name],
        list_examples=lambda example_ids: [
            SimpleNamespace(id=e, metadata={"case_id": e}) for e in example_ids
        ],
        list_feedback=lambda run_ids: [
            SimpleNamespace(run_id=rid, key=k, score=v)
            for rid in run_ids
            for k, v in experiments[rid.split(":")[0]][rid.split(":")[1]].items()
        ],
        read_project=lambda project_name: SimpleNamespace(
            extra={"metadata": {"judge_model": "claude-opus-5-5"}}
        ),
    )


def test_compare_and_baseline_from_experiment(make_project, monkeypatch) -> None:
    import promptbench.cli as cli_mod

    fake = _fake_langsmith(
        {"exp-a": {"a": {"m": 1.0}, "b": {"m": 0.5}}, "exp-b": {"a": {"m": 0.25}, "c": {"m": 1.0}}}
    )
    monkeypatch.setattr(cli_mod, "_langsmith_client", lambda: fake)
    res = cli("compare", "exp-a", "exp-b")
    assert res.exit_code == 0, res.output
    assert "-0.750" in res.output and "only in A: ['b']" in res.output

    project = make_project()
    res = cli(
        "baseline", "update", "--root", str(project.root), "--suite", "demo", "--from-experiment", "exp-a"
    )
    assert res.exit_code == 0, res.output
    from promptbench.scoring import load_baseline

    b = load_baseline(project.root / "baselines", "demo")
    assert b is not None and b.metrics["m"].mean == 0.75 and b.judge_model == "claude-opus-5-5"
    assert cli("baseline", "update", "--root", str(project.root), "--from-experiment", "exp-a").exit_code == 2
