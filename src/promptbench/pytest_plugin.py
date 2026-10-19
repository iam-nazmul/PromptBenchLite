"""pytest integration (SPEC §11): one test item per golden case, suite gate at session end.

Inert unless enabled with ``--promptbench`` or ``promptbench = true`` in the pytest ini options.
The ``live`` marker is handled always: such tests are skipped unless ``PROMPTBENCH_LIVE=1``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from promptbench.config import Config, load_config
from promptbench.errors import EXIT_CONFIG, PromptBenchError
from promptbench.evaluators import EvalContext
from promptbench.golden import Case, Suite, load_suite
from promptbench.pipeline import SuitePlan, evaluate_case, gate, plan_suite
from promptbench.runner import Target, resolve_target, run_target
from promptbench.scoring import CaseResult, SuiteResult

STATE_KEY = pytest.StashKey["PluginState"]()


@dataclass
class PluginState:
    config: Config
    ctx: EvalContext
    results: dict[str, list[CaseResult]] = field(default_factory=dict)
    plans: dict[str, SuitePlan] = field(default_factory=dict)
    suites: dict[str, Suite] = field(default_factory=dict)
    targets: dict[str, Target] = field(default_factory=dict)
    setup_error: str | None = None


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("promptbench")
    group.addoption(
        "--promptbench", action="store_true", default=False, help="Collect golden cases as tests."
    )
    group.addoption("--promptbench-root", default=None, help="Project root containing promptbench.toml.")
    group.addoption("--promptbench-suite", action="append", default=[], help="Only this suite (repeatable).")
    group.addoption(
        "--promptbench-no-tracking", action="store_true", default=False, help="Do not use LangSmith."
    )
    parser.addini("promptbench", type="bool", default=False, help="Enable the PromptBench plugin.")


def _enabled(config: pytest.Config) -> bool:
    return bool(config.getoption("--promptbench") or config.getini("promptbench"))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live: calls real external APIs; skipped unless PROMPTBENCH_LIVE=1")
    config.addinivalue_line("markers", "promptbench_suite(name): golden case from the named suite")
    if not _enabled(config):
        return
    root = Path(config.getoption("--promptbench-root") or config.rootpath)
    try:
        pb_config = load_config(root)
    except PromptBenchError as e:
        raise pytest.UsageError(f"promptbench: {e}") from e
    config.stash[STATE_KEY] = PluginState(config=pb_config, ctx=EvalContext(config=pb_config))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("PROMPTBENCH_LIVE") == "1":
        return
    skip_live = pytest.mark.skip(reason="live test: set PROMPTBENCH_LIVE=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


def pytest_collect_file(file_path: Path, parent: pytest.Collector) -> pytest.Collector | None:
    state = parent.config.stash.get(STATE_KEY, None)
    if state is None or file_path.suffix not in {".yaml", ".yml"}:
        return None
    if file_path.parent.resolve() != state.config.goldens_path.resolve():
        return None
    wanted = parent.config.getoption("--promptbench-suite")
    if wanted and file_path.stem not in wanted:
        return None
    return GoldenFile.from_parent(parent, path=file_path)


class GoldenFile(pytest.File):
    def collect(self) -> Iterator[pytest.Item]:
        state: PluginState = self.config.stash[STATE_KEY]
        try:
            suite = load_suite(self.path)
            plan = plan_suite(suite, state.ctx)
        except PromptBenchError as e:
            raise self.CollectError(str(e)) from e
        state.suites[suite.suite] = suite
        state.plans[suite.suite] = plan
        state.results.setdefault(suite.suite, [])
        for case in suite.cases:
            item = GoldenCase.from_parent(self, name=case.id, case=case, suite=suite)
            item.add_marker(pytest.mark.promptbench_suite(suite.suite))
            item.extra_keyword_matches.update(case.tags)  # `-k <tag>` selects by tag
            if case.skipped:
                item.add_marker(pytest.mark.skip(reason=case.skip or "skipped in golden set"))
            yield item


class GoldenCaseFailure(Exception):
    pass


class GoldenCase(pytest.Item):
    def __init__(self, *, case: Case, suite: Suite, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.case = case
        self.suite = suite

    def runtest(self) -> None:
        state: PluginState = self.config.stash[STATE_KEY]
        target = state.targets.get(self.suite.suite)
        if target is None:
            target = resolve_target(self.suite.target, state.config.root)
            state.targets[self.suite.suite] = target
        output = run_target(target, self.case)
        result = evaluate_case(self.case, output, state.plans[self.suite.suite].evaluators[self.case.id])
        state.results[self.suite.suite].append(result)

        problems = [f"{s.key}: errored — {s.error}" for s in result.scores if s.errored]
        problems += [
            f"{s.key}: {s.value:.3f} — {s.comment or 'failed'}" for s in result.scores if s.passed is False
        ]
        if problems:
            raise GoldenCaseFailure("\n".join(problems))

    def repr_failure(self, excinfo: pytest.ExceptionInfo[BaseException], style: Any = None) -> str:
        if isinstance(excinfo.value, GoldenCaseFailure | PromptBenchError):
            return f"{self.suite.suite}::{self.case.id}\n{excinfo.value}"
        return str(super().repr_failure(excinfo))

    def reportinfo(self) -> tuple[Path, int, str]:
        return self.path, 0, f"{self.suite.suite}::{self.case.id}"


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    state = session.config.stash.get(STATE_KEY, None)
    if state is None or not any(state.results.values()):
        return
    results = [
        SuiteResult(
            suite=name,
            cases=cases,
            skipped=[c.id for c in state.suites[name].cases if c.skipped],
            judge_model=state.plans[name].judge_model,
        )
        for name, cases in state.results.items()
        if cases
    ]
    if not session.config.getoption("--promptbench-no-tracking"):
        from promptbench.tracking import make_tracker

        try:
            tracker, warnings = make_tracker(state.config)
            from promptbench.gitinfo import run_metadata

            meta = run_metadata(state.config.root)
            for r in results:
                warnings += tracker.record_suite(state.suites[r.suite], r, {**meta, "suite": r.suite})
        except PromptBenchError as e:
            warnings = [str(e)]
            session.exitstatus = e.exit_code
        for w in warnings:
            session.config.get_terminal_writer().line(f"promptbench warning: {w}", yellow=True)

    try:
        verdict = gate(results, state.config)
    except PromptBenchError as e:
        session.config.get_terminal_writer().line(f"promptbench gate error: {e}", red=True)
        session.exitstatus = EXIT_CONFIG
        return
    state.ctx.cache["verdict"] = verdict
    state.ctx.cache["suite_results"] = results
    session.exitstatus = verdict.exit_code


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    state = config.stash.get(STATE_KEY, None)
    if state is None or "verdict" not in state.ctx.cache:
        return
    import io

    from rich.console import Console

    from promptbench.pipeline import RunOutcome
    from promptbench.reporting import print_report

    buffer = io.StringIO()
    outcome = RunOutcome(results=state.ctx.cache["suite_results"], verdict=state.ctx.cache["verdict"])
    print_report(outcome, Console(file=buffer, force_terminal=False, width=120))
    terminalreporter.section("promptbench gate")
    terminalreporter.write(buffer.getvalue())
