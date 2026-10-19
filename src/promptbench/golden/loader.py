from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from promptbench.errors import ConfigError
from promptbench.golden.models import Suite


def load_suite(path: Path) -> Suite:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: invalid YAML: {e}") from e
    except OSError as e:
        raise ConfigError(f"{path}: cannot read: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    try:
        suite = Suite.model_validate({**raw, "source": path})
    except ValidationError as e:
        raise ConfigError(f"{path}: invalid golden set:\n{e}") from e
    if path.stem != suite.suite:
        raise ConfigError(f"{path}: file name must match suite name {suite.suite!r}")
    return suite


def discover(goldens_dir: Path) -> list[Path]:
    if not goldens_dir.is_dir():
        raise ConfigError(f"goldens directory not found: {goldens_dir}")
    return sorted(p for p in goldens_dir.iterdir() if p.suffix in {".yaml", ".yml"} and p.is_file())


def load_suites(goldens_dir: Path, names: list[str] | None = None) -> list[Suite]:
    """Load every suite in ``goldens_dir`` (or only ``names``); errors name the offending file."""
    suites = [load_suite(p) for p in discover(goldens_dir)]
    if not suites:
        raise ConfigError(f"no golden sets (*.yaml) in {goldens_dir}")
    if names:
        by_name = {s.suite: s for s in suites}
        missing = sorted(set(names) - by_name.keys())
        if missing:
            raise ConfigError(f"unknown suite(s): {missing}; available: {sorted(by_name)}")
        suites = [by_name[n] for n in names]
    return suites
