"""Which acceptance criteria something EXECUTED — decided by the platform, not the reviewer (#447).

MEASURED ON A LIVE PULL REQUEST. The review of a CSS fix wrote, in its own summary, that the only
evidence for every acceptance criterion was a Playwright spec "never actually executed by any
CI/validate gate, so the PASS results … don't include proof the fix works in a live browser — only
code-level reasoning does". It decided `approved_with_findings`, the platform said "Review approved
it", and the requester was told "the automatic review approved it". The requester resized the
window and the toolbar was still cut off.

The reviewer is asked to cite the gate that executed a criterion's evidence as `gate:<name>`. This
module checks that citation against the gates that actually ran on the attempt, and keeps the name
only when the gate ran and passed. Anything else — no citation, a gate that did not run, a gate
that failed, a gate that could not run — leaves `executed_by` empty, and the stance is computed
from that (`review/verdict.py::headline`), never from the reviewer's decision word.

PURE: a `ReviewResult` and the attempt's `ValidationResult`s in, a `ReviewResult` out.
"""

from __future__ import annotations

import re

from openfactory.contracts import ReviewResult, ValidationResult

#: How the reviewer cites a gate in `evidence`. A bare gate name is not a citation: gates are
#: called `test`, `lint`, `type`, and those words appear in every sentence about code.
CITATION = re.compile(r"\bgate:\s*`?([A-Za-z0-9_.\-]+)`?", re.IGNORECASE)


def cited(evidence: str | None) -> list[str]:
    """The gate names `evidence` cites, in order, lower-cased."""
    return [m.group(1).lower() for m in CITATION.finditer(evidence or "")]


def settle(review: ReviewResult, validations: list[ValidationResult]) -> ReviewResult:
    """`review` with each criterion's `executed_by` set from the gates that ran, and
    `evidence_checked` true. A criterion's own `executed_by` is never trusted: it is recomputed
    here, so a reviewer that writes the field itself gains nothing by it."""
    passed = {v.name.lower(): v.name for v in validations or []
              if v.passed and not v.unrunnable}
    checks = []
    for check in review.acceptance:
        name = next((passed[g] for g in cited(check.evidence) if g in passed), None)
        checks.append(check.model_copy(update={"executed_by": name}))
    return review.model_copy(update={"acceptance": checks, "evidence_checked": True})
