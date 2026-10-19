# Example: support-bot

A small, fully offline PromptBench project. The "bot" (`app/support.py`) is deterministic. The judge is the `fake` provider and similarity is `lexical`, so it needs no API keys.

```bash
# from the repository root
uv run promptbench validate --root examples/support-bot
uv run promptbench run --root examples/support-bot --no-tracking            # exit 0

SUPPORT_BOT_VARIANT=degraded \
  uv run promptbench run --root examples/support-bot --no-tracking          # exit 1: regression

uv run pytest --promptbench --promptbench-root examples/support-bot \
  --promptbench-no-tracking examples/support-bot/goldens
```

To try it with real graders, change `promptbench.toml` to `judge.provider = "anthropic"` and `similarity.backend = "sentence_transformers"`, set `ANTHROPIC_API_KEY`, and install the extra: `uv sync --extra similarity`. Then create a new baseline. Scores from different graders are not comparable.
