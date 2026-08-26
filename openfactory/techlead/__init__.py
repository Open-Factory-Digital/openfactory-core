"""The tech-lead's own logic: what a failure IS, and what resolves it (ADR-0020).

Kept apart from `adapters/agent/techlead.py` — that is the role's *voice*, the prompts it speaks
through a harness. This is its *judgement*, and it is deliberately deterministic: whether GitHub
throttled us is a fact about a string, not an opinion worth a model call.
"""

from openfactory.techlead.classify import (
    CODE,
    CREDENTIAL,
    ENVIRONMENT,
    POLICY,
    PROJECT,
    REQUIREMENT,
    TRANSIENT,
    UNKNOWN,
    Remedy,
    Verdict,
    classify,
    remedy_for,
)
from openfactory.techlead.conversation import Answer

__all__ = [
    "CODE",
    "Answer",
    "CREDENTIAL",
    "ENVIRONMENT",
    "POLICY",
    "PROJECT",
    "REQUIREMENT",
    "TRANSIENT",
    "UNKNOWN",
    "Remedy",
    "Verdict",
    "classify",
    "remedy_for",
]
