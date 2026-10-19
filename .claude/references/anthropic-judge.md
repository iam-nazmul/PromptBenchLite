# LLM judge on the Anthropic API

Source: Anthropic `claude-api` skill reference (models table cached 2026-10-06) and the installed SDK (`anthropic` 1.15), checked 2026-10-19. For anything not shown here, check the Python SDK docs. Don't guess method names.

Implemented in `src/promptbench/evaluators/judge.py` (`AnthropicJudgeBackend`). Tests: `tests/evaluators/test_judge.py`. anthropic 1.x uses `httpx2`, so build fake exceptions with `httpx2.Request`.

## Model and parameters

| Setting | Value | Why |
|---|---|---|
| `model` | `claude-opus-5-5` (config `judge.model`) | Current default Opus. `claude-sonnet-5-5` is the cheaper option ($2/$10 vs $4/$20 per MTok). |
| `output_config.effort` | `medium` (config `judge.effort`) | Opus 5.5 defaults to `medium`. Set it explicitly anyway so the baseline records what was used. |
| `thinking` | omit | Opus 5.5 runs adaptive thinking. `{"type": "disabled"}` and `budget_tokens` return 400. |
| `temperature` / `top_p` / `top_k` | **never send** | Rejected with 400 on current models. Use `judge.samples` for variance instead. |
| `max_tokens` | ~4000 | Reasoning + score is short; thinking tokens also count. Raise if `stop_reason == "max_tokens"` shows up. |
| `tool_choice` `any`/`tool` | **never send** | 400 on Opus 5.5 / Sonnet 5.5. Use structured outputs. |
| Prefill (trailing assistant message) | **never** | 400 on current models. |

Use the exact model ID strings. Never append a date suffix.

## Structured verdict

```python
import anthropic
from pydantic import BaseModel, Field

class JudgeVerdict(BaseModel):
    reasoning: str = Field(description="Step-by-step assessment against the rubric, written before the score.")
    score: int = Field(ge=1, le=5)

client = anthropic.Anthropic(max_retries=config.judge.max_retries)

response = client.beta.messages.parse(
    model=config.judge.model,
    max_tokens=4000,
    betas=["server-side-fallback-2026-07-01"],
    fallbacks="default",
    output_config={"effort": config.judge.effort},
    system=[
        {"type": "text", "text": JUDGE_INSTRUCTIONS + "\n\n" + rubric_text,
         "cache_control": {"type": "ephemeral"}},
    ],
    messages=[{"role": "user", "content": render_case(case, output)}],
    output_format=JudgeVerdict,
)
```

- Non-fallback form: `client.messages.parse(..., output_format=JudgeVerdict)` with no `betas` or `fallbacks`. `response.parsed_output` is the validated model.
- **Check `response.stop_reason` before reading `parsed_output`:**
  - `"refusal"` → errored score (`reason="refusal: <stop_details.category>"`). Never score it 0.
  - `"max_tokens"` → errored score. Raise `max_tokens` if it recurs.
- Record `response.model` in `Score.metadata["served_model"]`. With fallbacks on, it can differ from `judge.model`. The `fallbacks` parameter and its beta header must be used together, and they are Claude API only (not Bedrock/Vertex/Foundry).
- If the installed SDK lacks `client.beta.messages.parse`, use `client.beta.messages.create(..., output_config={"effort": ..., "format": {"type": "json_schema", "schema": JudgeVerdict.model_json_schema()}})` and validate the text block with `JudgeVerdict.model_validate_json(...)`.

## Prompt caching

- The cache is a **byte-exact prefix**: `tools` → `system` → `messages`. Keep the instructions plus the rubric in `system` with `cache_control`. Put everything that changes per case in the user message.
- No timestamps, run ids, or case data in the system prompt. Load rubric files with a stable encoding and newline handling.
- The minimum cacheable prefix depends on the model (512–4096 tokens). A short rubric silently won't cache. That's fine, just don't expect savings.
- Verify with `response.usage.cache_read_input_tokens > 0` on the second and later calls. Log it in debug output.
- Caches are per-model. Fallback-served calls don't reuse the primary model's cache.

## Errors and retries

The SDK retries 408/409/429/5xx and connection errors (`max_retries`, default 2). Catch exceptions from most specific to least specific:

```python
try:
    ...
except anthropic.RateLimitError: ...        # retries exhausted → errored score
except anthropic.APIStatusError as e: ...   # 4xx: likely config bug → errored score, log status
except anthropic.APIConnectionError: ...    # network → errored score
```

All of these produce **errored** scores, which SPEC §8.4 counts toward `max_error_rate` (exit 3).

## Variance (`judge.samples > 1`)

Call N times with the identical request and take the mean of normalised scores. Store the per-sample scores in `Score.metadata["samples"]` so triage can see the spread. The cached prefix makes repeats cheap on input. Output tokens dominate the cost.

## Testing

- Unit tests: the `fake_anthropic` fixture returns canned `parsed_output` / `stop_reason` / `model` values. Cover refusal, max_tokens, served-model mismatch and samples > 1.
- Live tests (`tests/live/`, `@pytest.mark.live`): one tiny rubric and 2–3 cases. Assert structure, not exact scores.

## Credentials

The SDK resolves credentials in this order: `ANTHROPIC_API_KEY`, then `ANTHROPIC_AUTH_TOKEN`, then an `ant auth login` profile. In CI, use the `ANTHROPIC_API_KEY` secret. Never log the key or the full request headers.
