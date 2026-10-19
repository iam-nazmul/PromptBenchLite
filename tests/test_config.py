from pathlib import Path

import pytest

from promptbench.config import load_config
from promptbench.errors import ConfigError


def test_defaults_without_any_file(tmp_path: Path) -> None:
    cfg = load_config(tmp_path, env={})
    assert cfg.judge.model == "claude-opus-5-5"
    assert cfg.judge.effort == "medium"
    assert cfg.gate.default_max_drop == 0.05
    assert cfg.goldens_path == tmp_path.resolve() / "goldens"


def test_dedicated_file_wins_over_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.promptbench]\nconcurrency = 9\n")
    assert load_config(tmp_path, env={}).concurrency == 9
    (tmp_path / "promptbench.toml").write_text("[promptbench]\nconcurrency = 3\n")
    assert load_config(tmp_path, env={}).concurrency == 3


def test_env_overrides(tmp_path: Path) -> None:
    env = {"PROMPTBENCH_TRACKING": "off", "LANGSMITH_PROJECT": "p2", "PROMPTBENCH_JUDGE_SAMPLES": "3"}
    cfg = load_config(tmp_path, env=env)
    assert cfg.tracking.enabled is False
    assert cfg.tracking.project == "p2"
    assert cfg.judge.samples == 3


@pytest.mark.parametrize(
    "toml",
    [
        "[promptbench]\nunknown_key = 1\n",
        "[promptbench.judge]\nsamples = 0\n",
        "[promptbench.gate]\ndefault_max_drop = 2\n",
        "[promptbench]\nconcurrency = \n",
        "[other]\nx = 1\n",
    ],
)
def test_invalid_config_is_config_error(tmp_path: Path, toml: str) -> None:
    (tmp_path / "promptbench.toml").write_text(toml)
    with pytest.raises(ConfigError):
        load_config(tmp_path, env={})


def test_bad_samples_env(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path, env={"PROMPTBENCH_JUDGE_SAMPLES": "many"})


def test_metric_overrides(tmp_path: Path) -> None:
    (tmp_path / "promptbench.toml").write_text(
        '[promptbench.gate]\ndefault_max_drop = 0.1\n[promptbench.gate.metrics]\n"x" = {floor = 0.5}\n'
        '"y" = {max_drop = 0.0}\n'
    )
    gate = load_config(tmp_path, env={}).gate
    assert gate.max_drop_for("x") == 0.1 and gate.floor_for("x") == 0.5
    assert gate.max_drop_for("y") == 0.0 and gate.floor_for("y") is None
    assert gate.max_drop_for("z") == 0.1
