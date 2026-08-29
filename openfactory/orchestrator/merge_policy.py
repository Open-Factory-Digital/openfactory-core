"""PR merge policy (ADR-0001 D-12). Default is human-on-PR; `auto` merges only when
the review is not rejected, all validations pass, and nothing high-risk was touched.
Pure logic — the orchestrator applies the decision via the forge/tracker."""

from __future__ import annotations

from openfactory.adapters.forge.base import ReviewEvent
from openfactory.contracts import Manifest, ReviewResult, RunResult

_EVENT: dict[str, ReviewEvent] = {
    "approved": "approve",
    "approved_with_findings": "comment",
    "rejected": "request-changes",
}


def review_event(review: ReviewResult | None, mode: str = "blocking") -> ReviewEvent:
    # ADR-0014: an ADVISORY review is INFORMATIONAL — always a plain PR comment, never a
    # request-changes that would block the merge (or an approve that reads as a gate passing).
    if mode != "blocking":
        return "comment"
    return _EVENT.get(review.decision, "comment") if review else "comment"


# Coverage pragmas are the codebase's convention for genuinely-untestable wiring (a 100%-cov
# repo has hundreds of them). The others — noqa / type: ignore / nosec — SILENCE a real lint /
# type / security error and are rare + suspicious. So they are treated differently at merge (#12,
# ADR-0011): a surviving coverage pragma may auto-merge once an independent review vets it; a hard
# suppression always stays human-gated.
_COVERAGE_SUPPRESSIONS = {"pragma: no cover", "nocov"}


def _hard_suppressions(kinds: list[str]) -> list[str]:
    """The suppressions that silence a real error (lint/type/security) — never auto-mergeable."""
    return sorted({k for k in kinds if k not in _COVERAGE_SUPPRESSIONS})


def should_auto_merge(manifest: Manifest, result: RunResult) -> bool:
    if manifest.merge_policy != "auto":
        return False
    if not result.all_passed:
        return False
    # ADR-0014: only a BLOCKING review gates the merge. An advisory review informs a human via a
    # PR comment; the deterministic gates (validations, below) are the real merge floor.
    if (manifest.review_mode == "blocking"
            and result.review is not None and result.review.decision == "rejected"):
        return False
    # Suppressions that SURVIVED the suppression-repair loop (ADR-0011). A HARD suppression
    # (noqa / type: ignore / nosec) always goes to a human. A coverage pragma may auto-merge —
    # but ONLY when an INDEPENDENT review has vetted it (the reviewer caught #207 and passed
    # #69's legit wiring); with no reviewer, ANY surviving suppression stays human-gated (#12).
    if result.added_suppressions:
        if _hard_suppressions(result.added_suppressions):
            return False
        if result.review is None:
            return False
    # RISK IS ASKED IN ONE PLACE NOW, and that place answers a wider question than this loop did.
    # The loop walked the components the diff MATCHED and looked for `high` — so a change matching
    # NO component walked an empty list, found nothing, and merged. A path the manifest never
    # described is the one this platform knows least about; reading the gate as "no component, no
    # objection" inverts it. `needs_a_human` keeps `high` exactly as it was and adds that case. A
    # project that declares no components at all is untouched: it has not failed to declare
    # anything, and gating it would be the fix doing more damage than the defect (`risk.py`).
    from openfactory.orchestrator.risk import of_attempt

    return not of_attempt(manifest, result).needs_a_human


def format_review(review: ReviewResult) -> str:
    lines = [f"**{review.decision}** — score {review.score}", "", review.summary]
    for f in review.findings:
        loc = f" (`{f.file}:{f.line}`)" if f.file else ""
        lines.append(f"- **{f.severity}**{loc}: {f.description}")
    return "\n".join(lines)
