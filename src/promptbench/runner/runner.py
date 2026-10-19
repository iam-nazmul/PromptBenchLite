from __future__ import annotations

import asyncio
import importlib
import inspect
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from promptbench.errors import ConfigError
from promptbench.golden import Case

Target = Callable[..., Any]


@dataclass(frozen=True)
class Output:
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    latency_s: float = 0.0

    @property
    def errored(self) -> bool:
        return self.error is not None


def resolve_target(spec: str, root: Path | None = None) -> Target:
    """Import ``package.module:callable``; ``root`` is put on sys.path so project modules resolve."""
    module_name, _, attr_path = spec.partition(":")
    if root is not None and str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        obj: Any = importlib.import_module(module_name)
    except Exception as e:
        raise ConfigError(f"cannot import target module {module_name!r}: {e}") from e
    for attr in attr_path.split("."):
        try:
            obj = getattr(obj, attr)
        except AttributeError as e:
            raise ConfigError(f"target {spec!r}: {module_name} has no attribute {attr_path!r}") from e
    if not callable(obj):
        raise ConfigError(f"target {spec!r} is not callable")
    return obj


def _normalise(result: Any) -> dict[str, Any]:
    if isinstance(result, str):
        return {"answer": result}
    if isinstance(result, dict):
        return result
    raise TypeError(f"target must return str or dict, got {type(result).__name__}")


def _call(target: Target, inputs: dict[str, Any]) -> Any:
    if inspect.iscoroutinefunction(target):
        return asyncio.run(target(**inputs))
    return target(**inputs)


def run_target(target: Target, case: Case) -> Output:
    start = time.perf_counter()
    try:
        data = _normalise(_call(target, case.inputs))
    except Exception as e:
        return Output(error=f"{type(e).__name__}: {e}", latency_s=time.perf_counter() - start)
    return Output(data=data, latency_s=time.perf_counter() - start)


def run_targets(target: Target, cases: list[Case], *, concurrency: int, timeout_s: float) -> list[Output]:
    """Run ``target`` on every case; a timeout or exception yields an errored Output, never raises."""
    pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="promptbench-target")
    try:
        futures = [pool.submit(run_target, target, c) for c in cases]
        outputs = []
        for fut in futures:
            try:
                outputs.append(fut.result(timeout=timeout_s))
            except FutureTimeout:
                outputs.append(
                    Output(error=f"TimeoutError: target exceeded {timeout_s}s", latency_s=timeout_s)
                )
        return outputs
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
