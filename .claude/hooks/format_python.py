#!/usr/bin/env python3
"""PostToolUse hook: ruff-fix and ruff-format a Python file Claude just edited.

Never blocks: formatting problems are reported, not enforced.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path


def ruff_cmd() -> list[str] | None:
    if shutil.which("uv") and Path("pyproject.toml").exists():
        return ["uv", "run", "--quiet", "ruff"]
    if shutil.which("ruff"):
        return ["ruff"]
    return None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return

    path = (payload.get("tool_input") or {}).get("file_path", "")
    if not path.endswith((".py", ".pyi")) or not Path(path).exists():
        return

    ruff = ruff_cmd()
    if ruff is None:
        return

    for args in (["check", "--fix", "--quiet", path], ["format", "--quiet", path]):
        try:
            result = subprocess.run(ruff + args, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return
        if result.returncode != 0 and args[0] == "check" and result.stdout.strip():
            print(f"ruff found issues it could not fix in {path}:\n{result.stdout}", file=sys.stderr)


if __name__ == "__main__":
    main()
