"""A rejected pull request was announced in the words of an approved one (#149).

    self._say_on_ticket(ticket.id, f"PR ready for review: {pr}")
    self._notify(f"{ticket.id} PR ready for review: {pr}", "info")

The gate item on the panel was taught to carry this platform's own verdict. The ANNOUNCEMENT was
not — so the ticket comment and every chat or Slack notification said exactly the same sentence
whether the reviewer had approved the change, rejected it, or never run at all.

That is the surface a client reads first, and on a deployment with no panel it is the only one.
"""

from __future__ import annotations

import types

import pytest

from openfactory.contracts.review import Finding, ReviewResult
from openfactory.orchestrator.machine import _review_sentence


def _result(review):
    return types.SimpleNamespace(review=review)


# ── 1. the three answers stay three answers ─────────────────────────────────────────────────────

def test_a_REJECTED_pull_request_says_so():
    said = _review_sentence(_result(ReviewResult(decision="rejected", score=30)))

    assert "rejected" in said.lower()


def test_an_APPROVED_one_says_that_instead():
    said = _review_sentence(_result(ReviewResult(decision="approved", score=95)))

    assert "approved" in said.lower() and "rejected" not in said.lower()


def test_and_NO_REVIEW_is_its_own_answer_rather_than_a_clean_one():
    """"Nothing reviewed this" and "the review approved it" are opposite facts. The module this
    renders through exists because they were once the same pixels."""
    said = _review_sentence(_result(None))

    assert "No review" in said
    assert "approved" not in said.lower()


def test_the_three_sentences_are_all_DIFFERENT():
    seen = {_review_sentence(_result(r)) for r in (
        None,
        ReviewResult(decision="approved", score=95),
        ReviewResult(decision="rejected", score=30))}

    assert len(seen) == 3, f"two of the three answers read the same: {seen}"


def test_a_finding_travels_with_it():
    said = _review_sentence(_result(ReviewResult(
        decision="rejected", score=20,
        findings=[Finding(severity="high", description="no rollback", file="db/x.sql")])))

    assert "no rollback" in said and "db/x.sql" in said


def test_but_not_MORE_than_three_of_them():
    """This rides on a notification somebody reads on a phone. The panel and the tech-lead have
    the dense form; a wall of findings in Slack is a message nobody finishes.

    THE VERDICT IS FED AS A DICT, because that is the only shape that reaches five points:
    `headline` already caps FINDINGS at three, and suppressions and failed gates are two more on
    top — fields a `ReviewResult` has no room for. A guard built from findings alone measures
    `headline`'s cap and not this one."""
    said = _review_sentence(_result({
        "decision": "rejected", "score": 10,
        "suppressions": ["# noqa: E501"],
        "findings": [{"severity": "high", "description": f"finding {n}"} for n in range(4)],
        "gates": [{"name": "tests", "passed": False}]}))

    assert said.count("\n· ") == 3, f"a phone notification got {said.count(chr(10) + '· ')} points"


# ── 2. one renderer, and it is reached ──────────────────────────────────────────────────────────

def test_the_sentence_comes_from_the_SHARED_renderer(monkeypatch):
    """The panel's gate item renders the same verdict. A second wording here is how two surfaces
    come to describe one fact differently — which is the defect one layer up from this one."""
    import openfactory.review.verdict as verdict

    monkeypatch.setattr(verdict, "headline",
                        lambda v, **k: {"level": "ok", "word": "SENTINEL", "clause": "c",
                                        "points": []})

    assert "SENTINEL" in _review_sentence(_result(ReviewResult(decision="approved", score=1)))


def test_the_announcement_is_composed_ONCE_with_the_verdict_in_it():
    """#160 moved the sentence into `techlead/voice.NARRATION`, so it is now built in one place
    and used twice. That is stronger than what this card asked for — the two surfaces cannot drift
    — but only if the ONE composition is the one carrying the verdict."""
    import ast
    import inspect

    from openfactory.orchestrator import machine
    from openfactory.techlead import voice

    assert "job.pr-ready" in voice.NARRATION
    for language in ("en", "pt-BR"):
        assert "{review}" in voice.NARRATION["job.pr-ready"][language], (
            f"the {language} announcement has nowhere to put the verdict")

    src = inspect.getsource(machine)
    composed = [n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Call)
                and '"job.pr-ready"' in (ast.get_source_segment(src, n) or "")]

    assert len(composed) == 1, f"the PR announcement is composed {len(composed)} times"
    assert "review=said" in (ast.get_source_segment(src, composed[0]) or ""), (
        "the pull request is announced without this platform's own verdict")


@pytest.mark.parametrize("where", ["_say_on_ticket", "_notify"])
def test_and_BOTH_announcements_use_that_composition(where):
    """Reachability, and the shape this card is about: the ticket comment and the notification are
    two calls, and teaching only one of them would leave a client reading the wrong half."""
    import ast
    import inspect

    from openfactory.orchestrator import machine

    src = inspect.getsource(machine)
    # The composition is bound to `ready` immediately above both calls; a surface announcing a PR
    # any other way is the drift this guard exists to catch.
    announcing = [n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == where
                  and "ready" in {getattr(a, "id", "") for a in ast.walk(n)}]

    assert announcing, f"no `{where}` announces a PR any more — this guard measures nothing"
