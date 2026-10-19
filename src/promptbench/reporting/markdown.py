"""Markdown report for PR comments and $GITHUB_STEP_SUMMARY (SPEC §12)."""

from __future__ import annotations

from promptbench.pipeline import RunOutcome
from promptbench.scoring import MetricVerdict, Status, SuiteResult, SuiteVerdict

MARKER = "<!-- promptbench-report -->"
TOP_REGRESSIONS = 10
ICON = {Status.PASS: "✅ pass", Status.FAIL: "❌ fail", Status.WARN: "⚠️ warn", Status.NEW: "🆕 new"}


def _f(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "—"
    return f"{x:+.3f}" if signed else f"{x:.3f}"


def _cell(text: str) -> str:
    return " ".join(text.replace("|", "\\|").split())


def headline(outcome: RunOutcome) -> str:
    v = outcome.verdict
    if v.infra_error:
        return "🛑 **Infrastructure error** — too many evaluations errored; results are not trustworthy (exit 3)."
    if v.regressed and v.mode == "warn":
        return "⚠️ **Quality regression detected** — gate is in warn-only mode, build not failed."
    if v.regressed:
        return "❌ **Quality regression** — at least one gated metric dropped beyond its threshold (exit 1)."
    return "✅ **No regression** — all gated metrics are within thresholds."


def _metric_row(m: MetricVerdict) -> str:
    base = m.baseline_mean if m.baseline_mean is not None else None
    current = m.compared_current_mean if m.compared_current_mean is not None else m.current_mean
    return (
        f"| `{m.key}` | {_f(base)} | {_f(current)} | {_f(m.delta, signed=True)} | "
        f"{_f(m.max_drop)} | {_f(m.floor)} | {ICON[m.status]} | {_cell(m.reason)} |"
    )


def _suite_section(result: SuiteResult, verdict: SuiteVerdict) -> list[str]:
    lines = [f"### `{result.suite}`", ""]
    if result.experiment_url:
        lines += [f"LangSmith experiment: [{result.experiment}]({result.experiment_url})", ""]
    lines += [
        f"{len(result.cases)} cases run, {len(result.skipped)} skipped, "
        f"{verdict.errored}/{verdict.total} evaluations errored"
        + (f", judge `{result.judge_model}`" if result.judge_model else ""),
        "",
        "| metric | baseline | current | Δ | max drop | floor | status | note |",
        "|---|---:|---:|---:|---:|---:|---|---|",
        *(_metric_row(m) for m in verdict.metrics),
        "",
    ]
    for w in verdict.warnings:
        lines.append(f"> ⚠️ {w}")
    if verdict.warnings:
        lines.append("")
    if verdict.added_cases or verdict.removed_cases:
        lines.append(
            f"Cases added: {', '.join(f'`{c}`' for c in verdict.added_cases) or 'none'} · "
            f"removed: {', '.join(f'`{c}`' for c in verdict.removed_cases) or 'none'}"
        )
        lines.append("")
    if verdict.regressions:
        by_case = {c.case_id: c for c in result.cases}
        lines += [
            f"<details><summary>Top {min(TOP_REGRESSIONS, len(verdict.regressions))} regressed cases</summary>",
            "",
            "| case | metric | before | after | Δ | reason |",
            "|---|---|---:|---:|---:|---|",
        ]
        for r in verdict.regressions[:TOP_REGRESSIONS]:
            score = by_case[r.case_id].score(r.key)
            reason = _cell((score.comment or "") if score else "")[:300]
            lines.append(
                f"| `{r.case_id}` | `{r.key}` | {_f(r.before)} | {_f(r.after)} | {_f(r.delta, True)} | {reason} |"
            )
        lines += ["", "</details>", ""]
    return lines


def render_markdown(outcome: RunOutcome) -> str:
    lines = [MARKER, "## PromptBench report", "", headline(outcome), ""]
    for w in outcome.warnings:
        lines.append(f"> ⚠️ {w}")
    if outcome.warnings:
        lines.append("")
    for result, verdict in zip(outcome.results, outcome.verdict.suites, strict=True):
        lines += _suite_section(result, verdict)
    sha = outcome.metadata.get("git_sha")
    if sha:
        lines.append(
            f"<sub>commit {sha[:12]} · promptbench {outcome.metadata.get('promptbench_version', '')}</sub>"
        )
    return "\n".join(lines) + "\n"
