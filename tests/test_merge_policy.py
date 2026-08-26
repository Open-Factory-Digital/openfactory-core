"""Merge policy (ADR-0001 D-12): default human-on-PR; auto only when safe."""

from __future__ import annotations

from openfactory.contracts import Component, Manifest, ReviewResult, RunResult, ValidationResult
from openfactory.orchestrator.merge_policy import review_event, should_auto_merge

_PASS = [ValidationResult(name="test", command="t", exit_code=0, passed=True)]


def _result(**kw) -> RunResult:
    base = dict(ticket_id="#1", state="pr_open", validations=_PASS)
    base.update(kw)
    return RunResult(**base)


def test_review_event_maps_decision():
    assert review_event(ReviewResult(decision="approved", score=90)) == "approve"
    assert review_event(ReviewResult(decision="approved_with_findings", score=80)) == "comment"
    assert review_event(ReviewResult(decision="rejected", score=10)) == "request-changes"
    assert review_event(None) == "comment"


def test_default_policy_never_auto_merges():
    assert should_auto_merge(Manifest(), _result()) is False  # default merge_policy=human


def test_auto_merges_when_green_and_not_rejected():
    m = Manifest(merge_policy="auto")
    assert should_auto_merge(m, _result()) is True


def test_auto_blocked_by_failed_validation():
    m = Manifest(merge_policy="auto")
    failed = [ValidationResult(name="test", command="t", exit_code=1, passed=False)]
    assert should_auto_merge(m, _result(validations=failed)) is False


def test_auto_blocked_by_rejected_review():
    # A rejected review blocks the merge only under BLOCKING review (ADR-0014).
    m = Manifest(merge_policy="auto", review_mode="blocking")
    r = _result(review=ReviewResult(decision="rejected", score=10))
    assert should_auto_merge(m, r) is False


def test_advisory_rejected_review_does_not_block_merge():
    # ADR-0014: the default advisory review is informational — a rejection posts a PR comment
    # but the deterministic gates (all_passed) are the merge floor, so it still auto-merges.
    m = Manifest(merge_policy="auto")  # review_mode defaults to "advisory"
    r = _result(review=ReviewResult(decision="rejected", score=10))
    assert should_auto_merge(m, r) is True


def test_auto_blocked_by_high_risk_component():
    m = Manifest(
        merge_policy="auto",
        components={"infra": Component(path="terraform/", stack="terraform", risk="high")},
    )
    assert should_auto_merge(m, _result(touched_components=["infra"])) is False


def test_coverage_pragma_blocked_without_a_reviewer():
    # ADR-0011: a surviving coverage pragma needs an INDEPENDENT review to vet it; with no
    # reviewer there's nothing to trust it, so it still goes to a human.
    m = Manifest(merge_policy="auto")
    assert should_auto_merge(m, _result(added_suppressions=["pragma: no cover"])) is False


def test_coverage_pragma_auto_merges_when_review_approved():
    # ADR-0011: the suppression-repair loop kept a legit wiring pragma; the reviewer vetted it
    # (approved) — it may auto-merge (this is #69's case: no more merging pragmas by hand).
    m = Manifest(merge_policy="auto")
    r = _result(added_suppressions=["pragma: no cover"],
                review=ReviewResult(decision="approved_with_findings", score=90))
    assert should_auto_merge(m, r) is True


def test_hard_suppression_always_human_even_when_approved():
    # noqa / type: ignore / nosec silence a real error — they stay human-gated even with an
    # approving review (the coverage-pragma leniency does NOT extend to them).
    m = Manifest(merge_policy="auto")
    approved = ReviewResult(decision="approved", score=95)
    for kind in ("noqa", "type: ignore", "nosec"):
        r = _result(added_suppressions=[kind], review=approved)
        assert should_auto_merge(m, r) is False, kind
    # a coverage pragma mixed with a hard one → still blocked (the hard one dominates)
    r = _result(added_suppressions=["pragma: no cover", "nosec"], review=approved)
    assert should_auto_merge(m, r) is False


def test_coverage_pragma_blocked_when_review_rejected():
    m = Manifest(merge_policy="auto", review_mode="blocking")
    r = _result(added_suppressions=["pragma: no cover"],
                review=ReviewResult(decision="rejected", score=20))
    assert should_auto_merge(m, r) is False
