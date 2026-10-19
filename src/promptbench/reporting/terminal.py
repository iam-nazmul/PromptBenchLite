from __future__ import annotations

from rich.console import Console
from rich.table import Table

from promptbench.pipeline import RunOutcome
from promptbench.scoring import Status

STYLE = {Status.PASS: "green", Status.FAIL: "bold red", Status.WARN: "yellow", Status.NEW: "cyan"}


def _f(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "—"
    return f"{x:+.3f}" if signed else f"{x:.3f}"


def print_report(outcome: RunOutcome, console: Console | None = None) -> None:
    console = console or Console(stderr=True)
    for w in outcome.warnings:
        console.print(f"[yellow]warning:[/] {w}")
    for result, verdict in zip(outcome.results, outcome.verdict.suites, strict=True):
        table = Table(
            title=f"{result.suite}  ({len(result.cases)} cases, {verdict.errored}/{verdict.total} errored)",
            title_justify="left",
        )
        table.add_column("metric", no_wrap=True)
        for col in ("baseline", "current", "Δ", "max drop", "floor"):
            table.add_column(col, justify="right", no_wrap=True)
        table.add_column("status", no_wrap=True)
        for m in verdict.metrics:
            current = m.compared_current_mean if m.compared_current_mean is not None else m.current_mean
            table.add_row(
                m.key,
                _f(m.baseline_mean),
                _f(current),
                _f(m.delta, signed=True),
                _f(m.max_drop),
                _f(m.floor),
                f"[{STYLE[m.status]}]{m.status.value}[/]",
            )
        console.print(table)
        for m in verdict.metrics:
            if m.reason and m.status in (Status.FAIL, Status.WARN):
                console.print(f"  [{STYLE[m.status]}]{m.key}[/]: {m.reason}")
        for w in verdict.warnings:
            console.print(f"  [yellow]⚠ {w}[/]")
        if result.experiment_url:
            console.print(f"  LangSmith: {result.experiment_url}")
        for r in verdict.regressions[:5]:
            console.print(f"  [red]↓[/] {r.case_id} {r.key}: {r.before:.3f} → {r.after:.3f}")

    v = outcome.verdict
    if v.infra_error:
        console.print("[bold red]INFRA ERROR[/] — too many evaluations errored (exit 3)")
    elif v.regressed and v.mode == "warn":
        console.print("[yellow]REGRESSION (warn-only mode)[/] — exit 0")
    elif v.regressed:
        console.print("[bold red]REGRESSION[/] — gate failed (exit 1)")
    else:
        console.print("[green]PASS[/] — no gated metric regressed")
