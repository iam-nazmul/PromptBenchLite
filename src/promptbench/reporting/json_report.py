"""Machine-readable results (`--json`). `promptbench baseline update --from-results` reads this format."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from promptbench import __version__
from promptbench.errors import ConfigError
from promptbench.pipeline import RunOutcome
from promptbench.scoring import Baseline, SuiteResult, SuiteVerdict, build_baseline

RESULTS_VERSION = 1


def suite_status(verdict: SuiteVerdict) -> str:
    if verdict.infra_error:
        return "infra_error"
    if verdict.failed:
        return "fail"
    return "pass"


def _case(c: Any) -> dict[str, Any]:
    return {
        "id": c.case_id,
        "tags": c.tags,
        "inputs": c.inputs,
        "expected": c.expected,
        "output": c.output.data,
        "error": c.output.error,
        "latency_s": round(c.output.latency_s, 4),
        "scores": [
            {
                "key": s.key,
                "value": None if s.errored else s.value,
                "passed": s.passed,
                "comment": s.comment,
                "error": s.error,
                "metadata": s.metadata,
            }
            for s in c.scores
        ],
    }


def _suite(result: SuiteResult, verdict: SuiteVerdict, git_sha: str | None) -> dict[str, Any]:
    return {
        "suite": result.suite,
        "status": suite_status(verdict),
        "experiment": result.experiment,
        "experiment_url": result.experiment_url,
        "judge_model": result.judge_model,
        "skipped": result.skipped,
        "verdict": {
            "has_baseline": verdict.has_baseline,
            "errored": verdict.errored,
            "total": verdict.total,
            "error_rate": round(verdict.error_rate, 4),
            "warnings": verdict.warnings,
            "added_cases": verdict.added_cases,
            "removed_cases": verdict.removed_cases,
            "metrics": [{**asdict(m), "status": m.status.value} for m in verdict.metrics],
            "regressions": [{**asdict(r), "delta": r.delta} for r in verdict.regressions],
        },
        "cases": [_case(c) for c in result.cases],
        "baseline_candidate": build_baseline(result, git_sha).model_dump(),
    }


def results_payload(outcome: RunOutcome) -> dict[str, Any]:
    git_sha = outcome.metadata.get("git_sha")
    return {
        "results_version": RESULTS_VERSION,
        "promptbench_version": __version__,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "metadata": outcome.metadata,
        "mode": outcome.verdict.mode,
        "exit_code": outcome.verdict.exit_code,
        "warnings": outcome.warnings,
        "suites": [
            _suite(r, v, git_sha) for r, v in zip(outcome.results, outcome.verdict.suites, strict=True)
        ],
    }


def write_json(outcome: RunOutcome, path: Path) -> None:
    path.write_text(json.dumps(results_payload(outcome), indent=2, ensure_ascii=False, default=str) + "\n")


def baselines_from_results(path: Path, suites: list[str] | None = None) -> list[Baseline]:
    """Baseline candidates from a results file; refuses suites whose run was an infra failure."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(f"cannot read results file {path}: {e}") from e
    entries = {s["suite"]: s for s in payload.get("suites", [])}
    wanted = suites or sorted(entries)
    missing = sorted(set(wanted) - entries.keys())
    if missing:
        raise ConfigError(f"suite(s) {missing} not in {path}")
    baselines = []
    for name in wanted:
        entry = entries[name]
        if entry["status"] == "infra_error":
            raise ConfigError(
                f"suite {name!r} had an infrastructure failure "
                f"({entry['verdict']['errored']}/{entry['verdict']['total']} errored); refusing to baseline it"
            )
        baselines.append(Baseline.model_validate(entry["baseline_candidate"]))
    return baselines
