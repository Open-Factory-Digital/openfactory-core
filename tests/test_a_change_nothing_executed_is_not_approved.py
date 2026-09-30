"""A change whose acceptance criteria nothing executed is not announced as approved (#447).

MEASURED ON A LIVE PULL REQUEST. The review of a CSS fix wrote that the only evidence for every
criterion was a Playwright spec "never actually executed by any CI/validate gate … only code-level
reasoning does", decided `approved_with_findings`, and the requester was told "the automatic review
approved it". The toolbar was still cut off. The stance is now computed from what a gate executed
— the precedent is ADR-0054's card verdict — and never read from the reviewer's decision word.
"""
from __future__ import annotations

import pytest

from openfactory.contracts import (
    AcceptanceCheck,
    JobState,
    Manifest,
    ReviewResult,
    RunResult,
    ValidationResult,
)
from openfactory.review import verdict as V
from openfactory.review.evidence import cited, settle


def _gate(name: str, *, passed: bool = True, unrunnable: str = "") -> ValidationResult:
    return ValidationResult(name=name, command="true", passed=passed,
                            exit_code=0 if passed else 1, unrunnable=unrunnable)


def _review(*checks: AcceptanceCheck, decision: str = "approved_with_findings",
            score: int = 82) -> ReviewResult:
    return ReviewResult(decision=decision, score=score, acceptance=list(checks),
                        summary="the css chain is right by reading it")


def _check(status: str = "passed", evidence: str | None = None, **kw) -> AcceptanceCheck:
    return AcceptanceCheck(criterion="the toolbar is fully visible", status=status,
                           evidence=evidence, **kw)


# ── 1. the platform decides what executed, not the reviewer ─────────────────────────────────────

@pytest.mark.parametrize("evidence,gates,expected", [
    ("gate:frontend_test — HomePage.test.tsx asserts it", [_gate("frontend_test")],
     "frontend_test"),
    ("gate: `frontend_test` — it ran", [_gate("frontend_test")], "frontend_test"),
    ("gate:frontend_e2e — the spec covers it", [_gate("frontend_test")], None),   # never ran
    ("gate:frontend_test — it covers it", [_gate("frontend_test", passed=False)], None),
    ("gate:test — covers it", [_gate("test", passed=False, unrunnable="no interpreter")], None),
    ("the test gate covers it", [_gate("test")], None),       # a mention is not a citation
    ("frontend/e2e/home.spec.ts covers every criterion", [_gate("frontend_test")], None),
    (None, [_gate("test")], None),
])
def test_a_criterion_is_executed_only_by_a_cited_gate_that_ran_and_passed(evidence, gates,
                                                                          expected):
    got = settle(_review(_check(evidence=evidence)), gates)
    assert got.evidence_checked is True
    assert got.acceptance[0].executed_by == expected


def test_a_reviewer_that_writes_executed_by_itself_gains_nothing():
    claimed = _check(evidence="read the diff", executed_by="test")
    assert settle(_review(claimed), [_gate("test")]).acceptance[0].executed_by is None


def test_the_rule_the_reviewer_is_given_is_the_rule_the_code_applies():
    """One rule, not two: the example citation in the prompt parses as a citation, and both
    reviewers carry the rule and the field it asks for."""
    from openfactory.adapters.reviewer import claude_code, harness
    from openfactory.adapters.reviewer.base import EVIDENCE_RULE, ReviewInput
    from openfactory.contracts import Ticket

    assert cited(EVIDENCE_RULE)[:1] == ["test"], "the prompt's example is not a citation"
    ri = ReviewInput(ticket=Ticket(id="#1", title="t", objective="o", repo="o/r"), diff="+x",
                     validations=[_gate("test")])
    for prompt, schema in ((harness.build_review_prompt(ri), harness._SCHEMA),
                           (claude_code.ClaudeCodeReviewer()._prompt(ri), claude_code._SCHEMA)):
        assert EVIDENCE_RULE in prompt
        assert '"would_verify"' in schema and '"would_verify"' in prompt


# ── 2. the stance is computed ────────────────────────────────────────────────────────────────────

def _verdict(review: ReviewResult) -> dict:
    return review.model_dump()


def test_the_case_measured_live_is_not_verified_whatever_the_decision_says():
    review = settle(_review(_check("unknown", "frontend/e2e/home.spec.ts — not run by any gate",
                                   would_verify="npm run test:e2e — frontend/e2e/home.spec.ts"),
                            _check("passed", "the grid chain, read")),
                    [_gate("frontend_test"), _gate("frontend_build")])
    head = V.headline(_verdict(review))
    assert head["stance"] == V.NOT_VERIFIED and head["word"] == "Review could not verify it"
    assert "2 of 2 acceptance criteria were checked only by reading the code" in head["clause"]
    assert head["points"][0].startswith("wire `npm run test:e2e"), head["points"]
    assert V.not_verified(_verdict(review))


def test_a_failed_criterion_is_a_rejection_even_under_an_approval():
    review = settle(_review(_check("failed", "gate:test — it fails"), decision="approved"),
                    [_gate("test")])
    head = V.headline(_verdict(review))
    assert head["stance"] == V.REJECTED and "1 of 1 acceptance criteria are not met" in (
        head["clause"])


def test_every_criterion_executed_is_an_approval():
    review = settle(_review(_check("passed", "gate:test — test_toolbar_visible")),
                    [_gate("test")])
    head = V.headline(_verdict(review))
    assert head["stance"] in (V.APPROVED, V.FLAGGED) and not V.not_verified(_verdict(review))


def test_a_review_that_mapped_no_criterion_verified_nothing():
    head = V.headline(_verdict(settle(_review(), [_gate("test")])))
    assert head["stance"] == V.NOT_VERIFIED
    assert "mapped no acceptance criterion" in head["clause"]


def test_a_verdict_written_before_the_check_reads_as_it_always_did():
    old = {"decision": "approved_with_findings", "score": 82,
           "acceptance": [{"criterion": "c", "status": "passed"}]}
    assert V.headline(old)["stance"] == V.FLAGGED and not V.not_verified(old)


def test_stale_still_outranks_the_computed_stance():
    review = _verdict(settle(_review(), []))
    assert V.headline({**review, "stale": "a repair rewrote it"})["stance"] == V.UNREAD


def test_the_techlead_line_says_what_a_gate_executed():
    review = settle(_review(_check("passed", "gate:test — ok"), _check("passed", "read")),
                    [_gate("test")])
    assert "(1 of 2 executed by a gate)" in V.line(_verdict(review))


# ── 3. every surface says it ────────────────────────────────────────────────────────────────────

def test_the_pull_request_body_heads_with_not_verified_and_keeps_the_reviewers_word():
    from openfactory.orchestrator.machine import _REVIEW_HEADING, _review_lines

    review = settle(_review(_check("unknown", would_verify="npm run test:e2e")), [_gate("test")])
    body = "\n".join(_review_lines(review))
    assert body.startswith(f"{_REVIEW_HEADING}NOT VERIFIED (the reviewer said "
                           f"approved_with_findings, score 82)")
    assert "This is not an approval" in body and "wire `npm run test:e2e`" in body
    verified = settle(_review(_check("passed", "gate:test — ok")), [_gate("test")])
    assert _review_lines(verified)[0] == f"{_REVIEW_HEADING}approved_with_findings (score 82)"


@pytest.mark.parametrize("language,said", [
    ("en", "the automatic review could not verify it"),
    ("pt-BR", "a revisão automática não conseguiu verificar"),
])
def test_the_requester_is_never_told_it_was_approved(language, said):
    from openfactory.product import events, voice

    review = _verdict(settle(_review(_check("passed", "read")), [_gate("test")]))
    stance = events._stance(review)
    assert stance == V.NOT_VERIFIED
    text = voice.ready_for_you(ref="7", review=stance, language=language)
    assert said in text and "aprovou" not in text and "approved it" not in text


def test_the_verdict_query_carries_what_the_stance_is_computed_from():
    from openfactory.runtime.temporal.workflow import JobWorkflow

    wf = JobWorkflow.__new__(JobWorkflow)
    wf._verdict = None  # noqa: SLF001
    review = settle(_review(_check("passed", "gate:test — ok"),
                            _check("unknown", would_verify="npm run test:e2e")), [_gate("test")])
    wf._remember_verdict(RunResult(ticket_id="#1", state=JobState.PR_OPEN,  # noqa: SLF001
                                   review=review))
    got = wf._verdict  # noqa: SLF001
    assert got["evidence_checked"] is True
    assert [c["executed_by"] for c in got["acceptance"]] == ["test", ""]
    assert got["acceptance"][1]["would_verify"] == "npm run test:e2e"
    assert V.headline(got)["stance"] == V.NOT_VERIFIED


# ── 4. nothing unverified merges by itself ──────────────────────────────────────────────────────

@pytest.mark.parametrize("mode", ["blocking", "advisory"])
def test_a_change_nobody_verified_never_merges_by_itself(mode):
    from openfactory.orchestrator.merge_policy import should_auto_merge

    manifest = Manifest(merge_policy="auto", review_mode=mode, validate={"test": "true"})
    ran = [_gate("test")]

    def result(review):
        return RunResult(ticket_id="#1", state=JobState.PR_OPEN, validations=ran, review=review)

    assert not should_auto_merge(manifest, result(settle(_review(_check("passed", "read")), ran)))
    assert should_auto_merge(manifest, result(settle(_review(_check("passed", "gate:test — ok")),
                                                     ran)))


def test_every_review_the_machine_publishes_goes_through_the_evidence_check():
    import inspect

    from openfactory.orchestrator import machine

    src = inspect.getsource(machine)
    assert src.count("self.reviewer.review(") == 1, (
        "a review that bypasses `_review` publishes a stance nobody checked against the gates")
    assert "return settle(review, review_input.validations)" in src
    assert src.count("self._review(") >= 4
