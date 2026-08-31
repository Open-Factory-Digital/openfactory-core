"""A review that could not be READ must not be presented as a judgement of the code.

The reviewer already draws this distinction internally — `adapters/reviewer/claude_code.py` returns
a different sentence for "the harness exited 127" than for "rc=0 and the output would not parse" —
and the DECISION deliberately stays `rejected`, because proceeding as if reviewed is the unsafe
default. That part is right and must not soften.

What was wrong is what a human sees. The PR body headed both cases `## Review — rejected (score 0)`
and put the explanation underneath, where a skim never reaches. Seen on the first real Azure DevOps
ticket (fx-ado PR #9, 2026-08-06): a diff that met all five acceptance criteria, headed "rejected".
Whoever opens that PR goes looking for what is wrong with the code. Nothing is; the reviewer is.

The same platform that refuses to let an unreadable board look like an empty queue cannot let an
unreadable review look like a bad diff.
"""

from __future__ import annotations

import pytest

from openfactory.contracts.review import ReviewResult


def _body(review: ReviewResult) -> str:
    """The PR body the state machine renders for a run carrying this review.

    Built the way `test_an_advisory_gate_reports_and_never_blocks` builds it — a SimpleNamespace
    standing in for the runner — so the two guards over this same renderer cannot drift into
    disagreeing about what it takes."""
    import types

    from openfactory.contracts import Manifest, RunResult, Ticket
    from openfactory.orchestrator.machine import JobRunner

    result = RunResult(ticket_id="12", state="pr_open", branch="sdlc/12", validations=[],
                       review=review)
    ticket = Ticket(id="12", title="t", objective="o", repo="factory/fx-ado")
    return JobRunner._pr_body(
        # A REAL MANIFEST, because `JobRunner.manifest` is never None: the constructor
        # takes one. The stub used to say None and `_pr_body` tolerated it only because
        # nothing there read a field of it — a shape production cannot produce, agreed
        # with by a test that built it.
        types.SimpleNamespace(manifest=Manifest()), ticket, result)


@pytest.mark.parametrize("summary", [
    "reviewer output could not be parsed (rc=0)",
    "the reviewer never ran: its harness exited 127 inside the box, so this diff has NOT been "
    "reviewed.",
])
def test_a_review_that_did_not_happen_is_not_headed_rejected(summary):
    body = _body(ReviewResult(decision="rejected", score=0, summary=summary))

    assert "DID NOT COMPLETE" in body
    assert "Review — rejected" not in body, (
        "the heading asserts a judgement of the code that nobody made — the reader goes looking "
        "for what is wrong with the diff instead of with the reviewer"
    )
    assert "(score 0)" not in body, "printing a score nobody gave is the same lie in smaller type"
    assert "not a judgement about the diff" in body


def test_a_REAL_rejection_still_says_so_loudly():
    """The positive twin. A guard that softened every rejection would be worse than the bug —
    a reviewer that genuinely refused a diff must not be reported as "did not complete"."""
    from openfactory.contracts.review import Finding

    body = _body(ReviewResult(
        decision="rejected", score=0,
        summary="the diff does not implement the third acceptance criterion",
        findings=[Finding(severity="high", description="no ValueError on a 4-tuple",
                                file="orders/pricing.py", line=20)],
    ))

    assert "Review — rejected (score 0)" in body
    assert "DID NOT COMPLETE" not in body
    assert "no ValueError on a 4-tuple" in body


def test_an_approval_is_untouched():
    body = _body(ReviewResult(decision="approved", score=92, summary="meets every criterion"))
    assert "Review — approved (score 92)" in body
    assert "DID NOT COMPLETE" not in body
