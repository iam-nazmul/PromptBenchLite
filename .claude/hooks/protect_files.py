#!/usr/bin/env python3
"""PreToolUse hook: block hand edits to baselines and any access to .env files (except .env.example).

Exit 2 blocks the tool call; stderr is shown to Claude.
"""

import json
import re
import sys
from pathlib import PurePosixPath

BASELINE_MSG = (
    "Blocked: baselines/*.json is written only by `promptbench baseline update` "
    "after a human approves the quality change (see CLAUDE.md, skill update-baseline)."
)
ENV_MSG = "Blocked: .env files hold secrets. Use .env.example for the variable list."
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

ENV_IN_COMMAND = re.compile(r"(^|[\s/'\"=<>])\.env(\.(?!example\b)[\w.-]+)?(?=$|[\s'\";|&<>)])")
BASELINE_WRITE_IN_COMMAND = re.compile(
    r"(>|>>|\btee\b|\bsed\s+-i|\bmv\b|\bcp\b|\brm\b|\btruncate\b)[^|;&]*\bbaselines/[^\s'\"]*\.json"
)


def is_env_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return (name == ".env" or name.startswith(".env.")) and name != ".env.example"


def is_baseline(path: str) -> bool:
    return "baselines" in PurePosixPath(path).parts and path.endswith(".json")


def block(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return

    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}

    if tool == "Bash":
        command = tool_input.get("command", "")
        if ENV_IN_COMMAND.search(command):
            block(ENV_MSG)
        if "promptbench baseline update" not in command and BASELINE_WRITE_IN_COMMAND.search(command):
            block(BASELINE_MSG)
        return

    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if is_env_file(path):
        block(ENV_MSG)
    if tool in WRITE_TOOLS and is_baseline(path):
        block(BASELINE_MSG)


if __name__ == "__main__":
    main()
