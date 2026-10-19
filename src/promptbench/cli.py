"""`promptbench` console script (SPEC §10). Exit codes: 0 pass, 1 regression, 2 config, 3 infra."""

from __future__ import annotations

import functools
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, TypeVar

import typer
from rich.console import Console
from rich.table import Table

from promptbench.config import Config, load_config
from promptbench.errors import ConfigError, InfraError, PromptBenchError
from promptbench.evaluators import EvalContext
from promptbench.gitinfo import git_branch, git_sha

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Regression-test prompts and LLM outputs.")
baseline_app = typer.Typer(no_args_is_help=True, help="Inspect and update committed baselines.")
app.add_typer(baseline_app, name="baseline")

err = Console(stderr=True)
F = TypeVar("F", bound=Callable[..., Any])

RootOpt = Annotated[Path, typer.Option("--root", help="Project root containing promptbench.toml.")]
SuiteOpt = Annotated[list[str] | None, typer.Option("--suite", "-s", help="Suite name (repeatable).")]
PROTECTED_BRANCHES = {"main", "master"}


def guarded(fn: F) -> F:
    """Map PromptBenchError to its exit code instead of a traceback."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except PromptBenchError as e:
            err.print(f"[bold red]error:[/] {e}")
            raise typer.Exit(e.exit_code) from e

    return wrapper  # type: ignore[return-value]


def _context(root: Path) -> tuple[Config, EvalContext]:
    config = load_config(root)
    return config, EvalContext(config=config)


@app.command()
@guarded
def validate(root: RootOpt = Path("."), suite: SuiteOpt = None) -> None:
    """Check golden sets, evaluator options, rubrics, targets and config. Offline and free."""
    from promptbench.pipeline import validate as run_validate

    config, ctx = _context(root)
    plans = run_validate(config, ctx, suite)
    for plan in plans:
        skipped = len(plan.suite.cases) - len(plan.cases)
        err.print(f"[green]ok[/] {plan.suite.suite}: {len(plan.cases)} cases ({skipped} skipped)")


@app.command()
@guarded
def run(
    root: RootOpt = Path("."),
    suite: SuiteOpt = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t", help="Only cases with this tag.")] = None,
    no_tracking: Annotated[bool, typer.Option("--no-tracking", help="Do not record to LangSmith.")] = False,
    report_md: Annotated[Path | None, typer.Option("--report-md", help="Write Markdown report.")] = None,
    junit: Annotated[Path | None, typer.Option("--junit", help="Write JUnit XML.")] = None,
    json_out: Annotated[Path | None, typer.Option("--json", help="Write full JSON results.")] = None,
    update_baseline: Annotated[
        bool, typer.Option("--update-baseline", help="Write new baselines from this run.")
    ] = False,
    i_know: Annotated[
        bool, typer.Option("--i-know-what-im-doing", help="Allow --update-baseline off main/master.")
    ] = False,
) -> None:
    """Run suites, record them, and gate against baselines."""
    from promptbench import pipeline
    from promptbench.reporting import print_report, render_markdown, write_json, write_junit
    from promptbench.scoring import build_baseline, write_baseline
    from promptbench.tracking import make_tracker

    config, ctx = _context(root)
    if update_baseline:
        if tag:
            raise ConfigError("--update-baseline cannot be combined with --tag (it would baseline a subset)")
        branch = git_branch(config.root)
        if branch not in PROTECTED_BRANCHES and not i_know:
            raise ConfigError(
                f"--update-baseline on branch {branch!r} requires --i-know-what-im-doing "
                "(baselines are normally updated on main via the baseline-update workflow)"
            )
    tracker, warnings = make_tracker(config, disabled=no_tracking)
    outcome = pipeline.run(config, ctx, names=suite, tags=tag, tracker=tracker)
    outcome.warnings[:0] = warnings

    print_report(outcome, err)
    markdown = render_markdown(outcome)
    if report_md:
        report_md.write_text(markdown, encoding="utf-8")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as f:
            f.write(markdown)
    if junit:
        write_junit(outcome, junit)
    if json_out:
        write_json(outcome, json_out)

    if update_baseline:
        if outcome.verdict.infra_error:
            raise InfraError("not updating baselines: this run had an infrastructure failure")
        for result in outcome.results:
            path = write_baseline(config.baselines_path, build_baseline(result, git_sha(config.root)))
            err.print(f"[green]wrote[/] {path}")
        raise typer.Exit(0)
    raise typer.Exit(outcome.verdict.exit_code)


@baseline_app.command("update")
@guarded
def baseline_update(
    root: RootOpt = Path("."),
    suite: SuiteOpt = None,
    from_results: Annotated[
        Path | None, typer.Option("--from-results", help="Results file from `promptbench run --json`.")
    ] = None,
    from_experiment: Annotated[
        str | None, typer.Option("--from-experiment", help="Build the baseline from a LangSmith experiment.")
    ] = None,
) -> None:
    """Accept a new quality level. Requires a human decision — see the update-baseline skill."""
    from promptbench.reporting import baselines_from_results
    from promptbench.scoring import write_baseline

    config = load_config(root)
    if (from_results is None) == (from_experiment is None):
        raise ConfigError("pass exactly one of --from-results or --from-experiment")
    if from_results is not None:
        baselines = baselines_from_results(from_results, suite)
    else:
        if not suite or len(suite) != 1:
            raise ConfigError("--from-experiment needs exactly one --suite")
        baselines = [_baseline_from_experiment(config, suite[0], from_experiment or "")]
    for b in baselines:
        path = write_baseline(config.baselines_path, b)
        metrics = ", ".join(f"{k}={m.mean:.3f}" for k, m in b.metrics.items())
        err.print(f"[green]wrote[/] {path}  ({metrics})")


def _baseline_from_experiment(config: Config, suite: str, experiment: str) -> Any:
    from datetime import UTC, datetime

    from promptbench.scoring import Baseline
    from promptbench.scoring.baseline import BaselineMetric
    from promptbench.tracking.langsmith import fetch_experiment_scores

    client = _langsmith_client()
    cases = fetch_experiment_scores(client, experiment)
    if not cases:
        raise ConfigError(f"no scored runs found in experiment {experiment!r}")
    keys = sorted({k for vals in cases.values() for k in vals})
    metrics = {}
    for k in keys:
        values = [v[k] for v in cases.values() if k in v]
        metrics[k] = BaselineMetric(mean=round(sum(values) / len(values), 6), n=len(values))
    judge_model = None
    try:
        project = client.read_project(project_name=experiment)
        judge_model = ((project.extra or {}).get("metadata") or {}).get("judge_model")
    except Exception:
        pass
    return Baseline(
        suite=suite,
        created_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        git_sha=git_sha(config.root),
        langsmith_experiment=experiment,
        judge_model=judge_model,
        metrics=metrics,
        cases={cid: dict(sorted(v.items())) for cid, v in sorted(cases.items())},
    )


@baseline_app.command("show")
@guarded
def baseline_show(root: RootOpt = Path("."), suite: SuiteOpt = None) -> None:
    """Print committed baseline metrics."""
    from promptbench.scoring import load_baseline

    config = load_config(root)
    names = suite or sorted(p.stem for p in config.baselines_path.glob("*.json"))
    if not names:
        err.print(f"no baselines in {config.baselines_path}")
        return
    out = Console()
    for name in names:
        b = load_baseline(config.baselines_path, name)
        if b is None:
            raise ConfigError(f"no baseline for suite {name!r}")
        table = Table(
            title=f"{name}  ({b.created_at}, judge {b.judge_model or '—'}, sha {(b.git_sha or '—')[:12]})"
        )
        table.add_column("metric")
        table.add_column("mean", justify="right")
        table.add_column("n", justify="right")
        for key, m in b.metrics.items():
            table.add_row(key, f"{m.mean:.3f}", str(m.n))
        out.print(table)


@app.command()
@guarded
def compare(experiment_a: str, experiment_b: str, limit: int = 30) -> None:
    """Per-case score deltas between two LangSmith experiments (B minus A)."""
    from promptbench.tracking.langsmith import fetch_experiment_scores

    client = _langsmith_client()
    a, b = fetch_experiment_scores(client, experiment_a), fetch_experiment_scores(client, experiment_b)
    rows = [
        (cid, key, a[cid][key], b[cid][key])
        for cid in sorted(a.keys() & b.keys())
        for key in sorted(a[cid].keys() & b[cid].keys())
    ]
    rows.sort(key=lambda r: r[3] - r[2])
    table = Table(title=f"{experiment_a} → {experiment_b}")
    for col in ("case", "metric", "A", "B", "Δ"):
        table.add_column(col, justify="right" if col in {"A", "B", "Δ"} else "left")
    for cid, key, va, vb in rows[:limit]:
        style = "red" if vb < va else ("green" if vb > va else "")
        table.add_row(
            cid, key, f"{va:.3f}", f"{vb:.3f}", f"[{style}]{vb - va:+.3f}[/]" if style else "+0.000"
        )
    Console().print(table)
    only_a, only_b = sorted(a.keys() - b.keys()), sorted(b.keys() - a.keys())
    if only_a or only_b:
        err.print(f"only in A: {only_a or 'none'} · only in B: {only_b or 'none'}")


def _langsmith_client() -> Any:
    if not os.environ.get("LANGSMITH_API_KEY"):
        raise InfraError("LANGSMITH_API_KEY is not set")
    from langsmith import Client

    return Client()


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
