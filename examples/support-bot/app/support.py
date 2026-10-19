"""A stand-in for an LLM-backed support bot, deterministic so the example runs offline.

Set SUPPORT_BOT_VARIANT=degraded to simulate a worse prompt and watch the gate fail.
"""

from __future__ import annotations

import os

FAQ: dict[tuple[str, ...], str] = {
    ("refund", "how long"): "You can request a refund within 30 days of purchase from your account page.",
    ("refund", "receipt"): "Yes. You don't need a receipt; use the order number shown on your account page.",
    ("cancel", "subscription"): "You can cancel your subscription any time under Settings → Billing. "
    "You keep access until the end of the current billing period.",
    (
        "change",
        "email",
    ): "Go to Settings → Profile, edit your email address, and confirm the link we send you.",
    ("password",): "Use 'Forgot password' on the sign-in page; the reset link is valid for 1 hour.",
    ("invoice",): "Invoices are under Settings → Billing → Invoices and can be downloaded as PDF.",
    (
        "shipping",
        "international",
    ): "Yes, we ship to 40 countries. International delivery takes 7–14 business days.",
}

FALLBACK = "I'm not sure about that. Please contact support@example.com and a human will help."

DEGRADED = "Thanks for reaching out! Please check our help centre for details."


def answer_question(question: str) -> str:
    if os.environ.get("SUPPORT_BOT_VARIANT") == "degraded":
        return DEGRADED
    q = question.casefold()
    best, best_hits = FALLBACK, 0
    for keywords, answer in FAQ.items():
        hits = sum(k in q for k in keywords)
        if hits == len(keywords) and hits > best_hits:
            best, best_hits = answer, hits
    return best
