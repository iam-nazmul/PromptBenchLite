# runner

Resolves and calls the prompt under test (the suite's `target`).

## Public API
- `resolve_target("pkg.module:callable", root)`: imports the target with `root` on `sys.path`. Raises `ConfigError`.
- `run_target(target, case) -> Output`: calls `target(**case.inputs)`. Async targets are run with `asyncio.run`.
- `run_targets(target, cases, concurrency=, timeout_s=) -> list[Output]`: runs them in a thread pool, keeping input order.
- `Output(data, error, latency_s)`. A `str` return becomes `{"answer": str}`. A `dict` is used as is.

## Invariants
- Never raises because the target failed. An exception, a wrong return type or a timeout becomes `Output(error=...)`.
- A timed-out call keeps running in its worker thread, because Python threads can't be killed. The result is discarded. A target that hangs forever can delay interpreter exit, so targets should set their own HTTP timeouts.

## Tests
`uv run pytest tests/test_pipeline.py -k "target"`
