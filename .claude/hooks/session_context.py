#!/usr/bin/env python3
"""SessionStart hook: print environment facts that change how Claude should work here.

Reports which credentials are present (never their values) and the tracking mode.
"""

import os
import shutil
import subprocess


def present(var: str) -> str:
    return "set" if os.environ.get(var) else "not set"


def git_branch() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return out.stdout.strip() if out.returncode == 0 else "not a git repo"


def main() -> None:
    tracking = os.environ.get("PROMPTBENCH_TRACKING", "on")
    lines = [
        "PromptBench Lite session context:",
        f"- git branch: {git_branch()}",
        f"- uv: {'available' if shutil.which('uv') else 'MISSING — install uv before running commands'}",
        f"- ANTHROPIC_API_KEY: {present('ANTHROPIC_API_KEY')} (judge calls / live tests)",
        f"- LANGSMITH_API_KEY: {present('LANGSMITH_API_KEY')}",
        f"- PROMPTBENCH_TRACKING: {tracking} (LangSmith writes are {'disabled' if tracking == 'off' else 'ENABLED'})",
        "- Live tests and `promptbench run` cost money: ask before running them.",
    ]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
