# Correctness

## What you are judging
Whether the ANSWER is factually correct and complete with respect to the REFERENCE for the
user's request in INPUTS. Ignore tone, length and formatting — other checks cover those.

## Inputs you will receive
- INPUTS: what the user sent to the support bot
- REFERENCE: a correct answer written by a human (one good answer, not the only one)
- CRITERIA (optional): extra requirements for this specific case
- ANSWER: the response to judge

## Scale
5 — Every fact in REFERENCE that answers the request is present and correct. No incorrect claims. Meets CRITERIA.
4 — Correct and answers the request; omits a minor detail from REFERENCE.
3 — Mostly correct but omits an important detail, OR includes a minor incorrect claim.
2 — Contains an incorrect claim that would mislead the user, misses the main point, or violates CRITERIA.
1 — Wrong, unrelated, or a non-answer.

## Rules
- Judge only against REFERENCE, CRITERIA and the general knowledge needed to read them; do not reward extra facts you cannot verify.
- An answer that is correct but phrased differently from REFERENCE is not penalised.
- If ANSWER contradicts REFERENCE, REFERENCE wins.
- For out-of-scope requests, a polite hand-off to a human is correct; an invented answer is a 1.
