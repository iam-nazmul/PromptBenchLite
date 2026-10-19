"""The pytest plugin, exercised through pytester in a temporary project."""

import pytest

from promptbench.scoring import load_baseline
from tests.conftest import DEFAULT_ANSWERS, DEFAULT_CONFIG


@pytest.fixture
def project(make_project, pytester, monkeypatch):
    p = make_project()
    monkeypatch.chdir(p.root)
    monkeypatch.syspath_prepend(str(p.root))
    return p


def test_one_item_per_case_and_skips(project, pytester) -> None:
    result = pytester.runpytest_inprocess("--promptbench", "--promptbench-no-tracking", "goldens", "-v")
    result.assert_outcomes(passed=5, skipped=1)
    result.stdout.fnmatch_lines(["*goldens/demo.yaml::refund PASSED*", "*promptbench gate*", "*PASS*"])
    assert result.ret == 0


def test_case_failure_and_gate_exit_code(project, pytester) -> None:
    pytester.runpytest_inprocess("--promptbench", "--promptbench-no-tracking", "goldens")
    from typer.testing import CliRunner

    from promptbench.cli import app

    CliRunner().invoke(
        app, ["run", "--root", str(project.root), "--update-baseline", "--i-know-what-im-doing"]
    )
    assert load_baseline(project.root / "baselines", "demo") is not None

    project.set_answers({**DEFAULT_ANSWERS, "refund": "nope", "cancel": "nope", "password": "nope"})
    result = pytester.runpytest_inprocess("--promptbench", "--promptbench-no-tracking", "goldens")
    result.assert_outcomes(passed=2, failed=3, skipped=1)
    result.stdout.fnmatch_lines(["*similarity:*", "*REGRESSION*"])
    assert result.ret == 1


def test_select_by_tag_keyword(project, pytester) -> None:
    result = pytester.runpytest_inprocess(
        "--promptbench", "--promptbench-no-tracking", "goldens", "-k", "account"
    )
    result.assert_outcomes(passed=2)


def test_ini_option_enables(project, pytester) -> None:
    (project.root / "pytest.ini").write_text("[pytest]\npromptbench = true\n")
    result = pytester.runpytest_inprocess("--promptbench-no-tracking", "goldens")
    result.assert_outcomes(passed=5, skipped=1)


def test_inert_without_flag(project, pytester) -> None:
    result = pytester.runpytest_inprocess("goldens")
    assert result.ret == pytest.ExitCode.NO_TESTS_COLLECTED


def test_bad_golden_is_collection_error(project, pytester) -> None:
    project.golden_path().write_text("suite: demo\ntarget: x:y\ncases:\n  - id: Bad\n    inputs: {}\n")
    result = pytester.runpytest_inprocess("--promptbench", "--promptbench-no-tracking", "goldens")
    assert result.ret == pytest.ExitCode.INTERRUPTED
    result.stdout.fnmatch_lines(["*kebab-case*"])


def test_bad_config_is_usage_error(project, pytester) -> None:
    (project.root / "promptbench.toml").write_text(DEFAULT_CONFIG + "\n[promptbench.judge]\nbogus = 1\n")
    result = pytester.runpytest_inprocess("--promptbench", "goldens")
    assert result.ret == pytest.ExitCode.USAGE_ERROR


def test_live_marker_skipped_without_env(pytester, monkeypatch) -> None:
    monkeypatch.delenv("PROMPTBENCH_LIVE", raising=False)
    pytester.makepyfile("import pytest\n@pytest.mark.live\ndef test_x():\n    assert False\n")
    pytester.runpytest_inprocess().assert_outcomes(skipped=1)
