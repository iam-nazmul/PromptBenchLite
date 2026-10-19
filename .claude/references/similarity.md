# Semantic similarity with sentence-transformers

Source: sentence-transformers docs (github.com/huggingface/sentence-transformers), checked 2026-10-19 via Context7.

## Usage

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")   # lazy-load once per process

a = model.encode(outputs, normalize_embeddings=True)    # list[str] → np.ndarray
b = model.encode(expected, normalize_embeddings=True)
sims = model.similarity(a, b)                           # matrix; we need the diagonal
scores = [max(0.0, min(1.0, float(sims[i][i]))) for i in range(len(outputs))]
```

- `model.similarity` uses the model's `similarity_fn_name`. It is cosine for `all-MiniLM-L6-v2`, but other models can default to `dot`. Set `model.similarity_fn_name = "cosine"` explicitly, or use `sentence_transformers.util.cos_sim`, so a model swap can't silently change the metric.
- Cosine can be negative. Clip to [0, 1] (SPEC §6.2).
- Batch-encode all cases of a suite in one call rather than per case. It is much faster on CPU.

## Model cache and offline use

- Downloads go to the Hugging Face cache. `SENTENCE_TRANSFORMERS_HOME` (or the `cache_folder=` argument) overrides the location.
- If the model name is a local directory, the Hub is skipped entirely. `local_files_only=True` fails fast when the model isn't cached.
- CI: cache the model directory with `actions/cache` keyed on the model name (see `github-actions.md`). `all-MiniLM-L6-v2` is about 90 MB.

## Rules for PromptBench

- Loading the model is slow (seconds) and needs network on first use. Never load it at import time or in `__init__`. Load it on the first `evaluate`, behind a lock, because the runner calls evaluators concurrently.
- **Scores from different models are not comparable.** Changing `similarity.model` requires a baseline update. Record the model name in score metadata.
- Similarity rewards wording overlap with the reference. It is a drift signal, not a correctness check, and is no substitute for the judge or deterministic checks.
- Long texts get truncated to the model's max sequence length (256 word pieces for MiniLM). For long outputs, either pick a model with a longer window or document that only the start of the text is compared.

## Testing

- Unit tests use the `stub_similarity` backend, which is deterministic and needs no model download. Example: `1.0` if the strings are equal after normalising, `0.5` if they share any token, else `0.0`.
- One live test may load the real model to check the integration (marked `live`, because it downloads).
