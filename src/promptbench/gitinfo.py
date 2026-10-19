"""Git/CI metadata attached to LangSmith experiments and baselines."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def git_sha(root: Path) -> str | None:
    return os.environ.get("GITHUB_SHA") or _git(root, "rev-parse", "HEAD")


def git_branch(root: Path) -> str | None:
    return (
        os.environ.get("GITHUB_HEAD_REF")
        or os.environ.get("GITHUB_REF_NAME")
        or _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    )


def run_metadata(root: Path) -> dict[str, Any]:
    from promptbench import __version__

    meta = {
        "git_sha": git_sha(root),
        "git_branch": git_branch(root),
        "pr_number": os.environ.get("PR_NUMBER"),
        "ci_run_url": os.environ.get("CI_RUN_URL"),
        "promptbench_version": __version__,
    }
    return {k: v for k, v in meta.items() if v is not None}
