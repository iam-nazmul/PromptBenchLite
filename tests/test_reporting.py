import json
import xml.etree.ElementTree as ET

import pytest

from promptbench import pipeline
from promptbench.errors import ConfigError
from promptbench.evaluators import EvalContext
from promptbench.reporting import MARKER, baselines_from_results, render_junit, render_markdown, write_json
from promptbench.scoring import build_baseline, write_baseline


@pytest.fixture
def regressed(make_project):
    project = make_project()
    config = project.config()
    outcome = pipeline.run(config, EvalContext(config=config))
    write_baseline(config.baselines_path, build_baseline(outcome.results[0]))
    project.set_answers({"refund": "No idea.", "cancel": "Cancel any time under Settings, Billing."})
    return pipeline.run(config, EvalContext(config=config))


def test_markdown(regressed) -> None:
    md = render_markdown(regressed)
    assert md.startswith(MARKER)
    assert "❌ **Quality regression**" in md
    assert "| `judge.correctness` |" in md
    assert "Top" in md and "`refund`" in md
    assert "token overlap" in md


def test_junit(regressed) -> None:
    root = ET.fromstring(render_junit(regressed))
    (suite,) = root.findall("testsuite")
    assert suite.get("name") == "demo"
    assert int(suite.get("failures")) >= 1 and suite.get("skipped") == "1"
    names = {tc.get("name") for tc in suite.findall("testcase")}
    assert {"refund", "skipped-case", "judge.correctness"} <= names


def test_json_and_baseline_candidates(regressed, tmp_path) -> None:
    path = tmp_path / "results.json"
    write_json(regressed, path)
    payload = json.loads(path.read_text())
    (suite,) = payload["suites"]
    assert payload["exit_code"] == 1 and suite["status"] == "fail"
    assert suite["cases"][0]["scores"][0]["key"] == "similarity"
    (b,) = baselines_from_results(path)
    assert b.suite == "demo" and "judge.correctness" in b.metrics


def test_baselines_from_results_refuses_infra_failures(regressed, tmp_path) -> None:
    path = tmp_path / "results.json"
    write_json(regressed, path)
    payload = json.loads(path.read_text())
    payload["suites"][0]["status"] = "infra_error"
    path.write_text(json.dumps(payload))
    with pytest.raises(ConfigError, match="refusing to baseline"):
        baselines_from_results(path)
    with pytest.raises(ConfigError, match="not in"):
        baselines_from_results(path, ["other"])
