---
name: add-golden-case
description: Add or edit golden cases in a PromptBench suite (goldens/*.yaml). Use when the user wants to add test cases, cover a new behaviour or bug, extend a golden set, or turn an example/trace into a regression case.
---

# Add a golden case

Golden sets are the contract a prompt is tested against. A bad case (vague expectation, unstable id, leaked secret) makes the gate noisy or meaningless, so follow these steps in order.

## 1. Find the suite

- List `goldens/*.yaml`. Each file's `suite:` maps to `baselines/<suite>.json`.
- Pick the suite whose `target:` is the prompt under test. If none fits, create a new file (see §5).

## 2. Write the case

```yaml
  - id: refund-no-receipt            # kebab-case, descriptive, unique in suite
    inputs:
      question: "Can I get a refund without a receipt?"
    expected:
      answer: "Yes — use the order number from your account page."
    evaluators:                      # only what differs from suite defaults
      contains: {values: ["order number"]}
    tags: [billing, refunds]
```

Rules:
- **`id` is permanent.** Never rename or reuse an existing id; history and baseline comparison key on it. To replace a case, add a new id and delete the old one.
- `inputs` keys must match the target callable's parameters exactly.
- `expected.answer` is a *good* answer, not the only answer. Similarity and the judge compare against it.
- Put hard requirements in deterministic evaluators (`contains`, `regex`, `json_schema`), not in the judge rubric. They are cheaper and have no noise.
- Use only synthetic or approved data. No real customer names, emails, IDs, or secrets: inputs are sent to Anthropic and LangSmith.
- Tag cases so `--tag` filtering and triage work (`safety`, `edge-case`, area names).
- Prefer cases that discriminate. A case every plausible prompt passes adds cost but no signal.

## 3. Validate (offline, free)

```bash
uv run promptbench validate --suite <suite>
```

Fix every error before going further. Exit code 2 means a schema or config problem.

## 4. Optionally score it (costs money — ask the user first)

```bash
uv run promptbench run --suite <suite> --tag <tag> --no-tracking
```

New case ids are not gated (they are not in the baseline), so the run shows the new case's scores without failing on them. Report those scores to the user. If the current prompt scores badly on the new case, that is a finding to surface, not something to fix by weakening `expected`.

## 5. New suite

1. Create `goldens/<suite>.yaml` with `suite`, `target`, `description`, `defaults`, `cases` (see SPEC §5).
2. Aim for at least `gate.min_cases` cases (default 5); below that the gate only warns.
3. There is no baseline yet; tell the user a maintainer must run the `update-baseline` skill flow after merge.

## Do not

- Edit `baselines/*.json` (blocked by a hook; see `update-baseline`).
- Change `expected` on an existing case to make a failing run pass. That is moving the goalposts — raise it with the user instead.
- Edit LangSmith dataset examples in the UI; the YAML is the source of truth.
