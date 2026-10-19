# Writing judge rubrics

Rubrics live in `rubrics/<name>.md` and are referenced from golden sets as `judge: {rubric: <name>}`. The rubric text goes into the cached system prompt (see `anthropic-judge.md`).

**Any edit to a rubric, even whitespace, changes the grader.** Scores before and after are not comparable, so a rubric change needs a baseline update (skill `update-baseline`) and a review by the `eval-reviewer` agent.

## Template

```markdown
# Correctness

## What you are judging
Whether the answer is factually correct and complete with respect to the reference answer
for the user's question. Ignore tone, length and formatting — other checks cover those.

## Inputs you will receive
- QUESTION: the user's input
- REFERENCE: a correct answer written by a human (one good answer, not the only one)
- ANSWER: the response to judge

## Scale
5 — All facts in REFERENCE that answer the question are present and correct. No incorrect claims.
4 — Correct and answers the question; omits a minor detail from REFERENCE.
3 — Mostly correct but omits an important detail, OR includes a minor incorrect claim.
2 — Contains an incorrect claim that would mislead the user, or misses the main point.
1 — Wrong, unrelated, or refuses without reason.

## Rules
- Judge only against REFERENCE and general knowledge needed to read it; do not reward extra facts you cannot verify.
- An answer that is correct but phrased differently from REFERENCE is not penalised.
- If ANSWER contradicts REFERENCE, REFERENCE wins.
- Write your reasoning first, citing the specific claims, then give the score.
```

## Principles

- **One dimension per rubric.** "Correct and polite and concise" produces scores nobody can act on. Make three rubrics, or move the mechanical parts (length, required phrases) to deterministic evaluators.
- **Anchor every level** with an observable description. Avoid "good", "adequate" or "poor" without saying what those mean.
- **Say what to ignore.** Unrelated qualities leak into scores unless they are excluded.
- **Reference is one good answer.** Tell the judge not to penalise valid alternatives, or similarity-style bias creeps in.
- **Reasoning before score.** The `JudgeVerdict` schema orders `reasoning` before `score`. Keep the instruction to match.
- **No case-specific content** in the rubric. Per-case details belong in the golden case (`expected`, or a per-case `criteria:` note rendered into the user message).
- **Don't mention the baseline, the prompt author or the PR.** The judge sees only the case.
- **Calibrate before merging.** Score 5–10 hand-picked outputs, including a known bad one and a known borderline one, and check the judge's scores match a human's within one point. Record that check in the PR description.

## Smells (flag these in review)

| Smell | Problem |
|---|---|
| Scale with no anchors | High variance, scores drift between runs |
| Scores cluster at 4–5 on every suite | Rubric too lenient, so the gate can't detect drops |
| Mentions specific products or answers | Overfits one suite and can't be reused |
| "Use your judgment" | Hands the definition of quality to the grader |
| Instructions that contradict the output schema (e.g., "reply with just a number") | Conflicts with structured output |
| Very long rubric (> ~1.5k words) | Cost, and the judge weights instructions inconsistently |
