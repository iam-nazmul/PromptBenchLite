from pathlib import Path

import pytest

from promptbench.errors import ConfigError
from promptbench.golden import Case, Suite, load_suite, load_suites

BASE = "suite: demo\ntarget: mod:fn\n"


def write(tmp_path: Path, body: str, name: str = "demo") -> Path:
    path = tmp_path / f"{name}.yaml"
    path.write_text(body)
    return path


def test_load_valid_suite(tmp_path: Path) -> None:
    suite = load_suite(write(tmp_path, BASE + "cases:\n  - id: a-1\n    inputs: {q: x}\n"))
    assert suite.suite == "demo"
    assert suite.cases[0].id == "a-1"
    assert suite.source == tmp_path / "demo.yaml"


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        (BASE + "cases:\n  - id: Bad_Id\n    inputs: {}\n", "kebab-case"),
        (BASE + "cases:\n  - id: a\n    inputs: {}\n  - id: a\n    inputs: {}\n", "duplicate case ids"),
        (BASE + "cases: []\n", "at least one case"),
        (BASE + "cases:\n  - id: a\n    inputs: {}\n    extra: 1\n", "extra"),
        (BASE + "cases:\n  - id: a\n    inputs: {when: 2026-01-01}\n", "JSON-serialisable"),
        ("suite: demo\ntarget: not a target\ncases:\n  - id: a\n    inputs: {}\n", "package.module:callable"),
        ("- just\n- a list\n", "mapping"),
        ("suite: [unclosed\n", "invalid YAML"),
    ],
)
def test_invalid_golden_sets(tmp_path: Path, body: str, fragment: str) -> None:
    with pytest.raises(ConfigError, match=fragment):
        load_suite(write(tmp_path, body))


def test_file_name_must_match_suite(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="file name"):
        load_suite(write(tmp_path, BASE + "cases:\n  - id: a\n    inputs: {}\n", name="other"))


def test_evaluator_specs_merge_and_drop() -> None:
    suite = Suite(
        suite="demo",
        target="m:f",
        defaults={
            "evaluators": {"similarity": {"min": 0.5}, "judge": {"rubric": "correctness"}, "exact": None}
        },
        cases=[
            Case(id="a", inputs={}, evaluators={"similarity": {"field": "text"}, "judge": None}),
        ],
    )
    specs = suite.evaluator_specs(suite.cases[0])
    assert specs == {"similarity": {"min": 0.5, "field": "text"}, "exact": {}}


def test_active_cases_filters_skips_and_tags() -> None:
    suite = Suite(
        suite="demo",
        target="m:f",
        cases=[
            Case(id="a", inputs={}, tags=["x"]),
            Case(id="b", inputs={}, tags=["y"]),
            Case(id="c", inputs={}, tags=["x"], skip="later"),
        ],
    )
    assert [c.id for c in suite.active_cases()] == ["a", "b"]
    assert [c.id for c in suite.active_cases(["x"])] == ["a"]


def test_load_suites_by_name(tmp_path: Path) -> None:
    write(tmp_path, BASE + "cases:\n  - id: a\n    inputs: {}\n")
    write(tmp_path, "suite: two\ntarget: m:f\ncases:\n  - id: a\n    inputs: {}\n", name="two")
    assert [s.suite for s in load_suites(tmp_path)] == ["demo", "two"]
    assert [s.suite for s in load_suites(tmp_path, ["two"])] == ["two"]
    with pytest.raises(ConfigError, match="unknown suite"):
        load_suites(tmp_path, ["nope"])


def test_load_suites_empty_or_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="no golden sets"):
        load_suites(tmp_path)
    with pytest.raises(ConfigError, match="not found"):
        load_suites(tmp_path / "missing")
