"""The shared pipeline behind the CLI and the pytest plugin: plan → run → evaluate → track → gate."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from promptbench.config import Config
from promptbench.errors import ConfigError
from promptbench.evaluators import EvalContext, Evaluator, EvaluatorConfigError, Score, create
from promptbench.gitinfo import run_metadata
from promptbench.golden import Case, Suite, load_suites
from promptbench.runner import Output, Target, resolve_target, run_targets
from promptbench.scoring import CaseResult, RunVerdict, SuiteResult, SuiteVerdict, gate_suite, load_baseline
from promptbench.tracking import NoopTracker, Tracker


@dataclass
class SuitePlan:
    suite: Suite
    cases: list[Case]
    evaluators: dict[str, list[Evaluator]]

    @property
    def judge_model(self) -> str | None:
        for evs in self.evaluators.values():
            for ev in evs:
                backend = getattr(ev, "backend", None)
                if ev.name == "judge" and backend is not None:
                    return str(backend.model)
        return None


@dataclass
class RunOutcome:
    results: list[SuiteResult]
    verdict: RunVerdict
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def plan_suite(suite: Suite, ctx: EvalContext, tags: list[str] | None = None) -> SuitePlan:
    """Build every case's evaluators; collects all config problems into one ConfigError."""
    problems: list[str] = []
    evaluators: dict[str, list[Evaluator]] = {}
    for case in suite.cases:
        built: list[Evaluator] = []
        specs = suite.evaluator_specs(case)
        if not specs and not case.skipped:
            problems.append(f"{suite.suite}/{case.id}: no evaluators configured")
        for name, options in specs.items():
            try:
                ev = create(name, options, ctx)
            except EvaluatorConfigError as e:
                problems.append(f"{suite.suite}/{case.id}: {e}")
                continue
            missing = [f for f in ev.required_expected_fields() if f not in case.expected]
            if missing:
                problems.append(f"{suite.suite}/{case.id}: evaluator {name!r} needs expected.{missing[0]}")
            built.append(ev)
        evaluators[case.id] = built
    if problems:
        raise ConfigError("invalid evaluator configuration:\n  " + "\n  ".join(problems))
    return SuitePlan(suite=suite, cases=suite.active_cases(tags), evaluators=evaluators)


def validate(config: Config, ctx: EvalContext, names: list[str] | None = None) -> list[SuitePlan]:
    """Offline checks for `promptbench validate`: golden schema, evaluator options, rubrics, target import."""
    plans = []
    problems = []
    for suite in load_suites(config.goldens_path, names):
        try:
            plans.append(plan_suite(suite, ctx))
            resolve_target(suite.target, config.root)
        except ConfigError as e:
            problems.append(str(e))
    if problems:
        raise ConfigError("\n".join(problems))
    return plans


def evaluate_case(case: Case, output: Output, evaluators: list[Evaluator]) -> CaseResult:
    scores: list[Score] = []
    for ev in evaluators:
        if output.errored:
            scores.extend(Score.errored_score(k, f"target failed: {output.error}") for k in ev.keys)
            continue
        try:
            scores.extend(ev.evaluate(case, output))
        except Exception as e:
            scores.extend(
                Score.errored_score(k, f"evaluator crashed: {type(e).__name__}: {e}") for k in ev.keys
            )
    return CaseResult(
        case_id=case.id,
        inputs=case.inputs,
        expected=case.expected,
        output=output,
        scores=scores,
        tags=list(case.tags),
    )


def execute(plan: SuitePlan, target: Target, config: Config) -> SuiteResult:
    outputs = run_targets(
        target, plan.cases, concurrency=config.concurrency, timeout_s=config.target_timeout_s
    )
    with ThreadPoolExecutor(max_workers=config.concurrency, thread_name_prefix="promptbench-eval") as pool:
        case_results = list(
            pool.map(
                lambda pair: evaluate_case(pair[0], pair[1], plan.evaluators[pair[0].id]),
                zip(plan.cases, outputs, strict=True),
            )
        )
    return SuiteResult(
        suite=plan.suite.suite,
        cases=case_results,
        skipped=[c.id for c in plan.suite.cases if c.skipped],
        judge_model=plan.judge_model,
    )


def gate(results: list[SuiteResult], config: Config) -> RunVerdict:
    verdicts: list[SuiteVerdict] = [
        gate_suite(r, load_baseline(config.baselines_path, r.suite), config.gate, r.judge_model)
        for r in results
    ]
    return RunVerdict(verdicts, mode=config.gate.mode)


def run(
    config: Config,
    ctx: EvalContext,
    *,
    names: list[str] | None = None,
    tags: list[str] | None = None,
    tracker: Tracker | None = None,
) -> RunOutcome:
    tracker = tracker or NoopTracker()
    metadata = run_metadata(config.root)
    warnings: list[str] = []
    results: list[SuiteResult] = []
    for suite in load_suites(config.goldens_path, names):
        plan = plan_suite(suite, ctx, tags)
        if not plan.cases:
            warnings.append(f"suite {suite.suite!r}: no cases selected")
            continue
        target = resolve_target(suite.target, config.root)
        result = execute(plan, target, config)
        suite_meta = {**metadata, "suite": suite.suite}
        if plan.judge_model:
            suite_meta["judge_model"] = plan.judge_model
        warnings.extend(tracker.record_suite(suite, result, suite_meta))
        results.append(result)
    return RunOutcome(results=results, verdict=gate(results, config), warnings=warnings, metadata=metadata)
