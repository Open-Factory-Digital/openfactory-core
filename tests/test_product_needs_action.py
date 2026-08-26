"""Needs Action — deciding whose problem a parked ticket is.

The expensive mistake here is not failing to act: it is acting on a technical impediment because it
was misread as a requirement defect, quietly, and leaving somebody to discover later that a parked
job was reinterpreted by an agent. So every rule below biases toward saying "not mine, and here is
why" rather than toward doing something.
"""

from __future__ import annotations

import pytest

from openfactory.product.needs_action import (
    ENVIRONMENT,
    REQUIREMENT,
    TECHNICAL,
    UNCLEAR,
    Verdict,
    classify_prompt,
    fix_comment,
    hand_back_comment,
    review,
)


def _v(cause=REQUIREMENT, confidence="high", **kw):
    kw.setdefault("ticket", 1)
    return Verdict(cause=cause, confidence=confidence, **kw)


# ── whose problem is it ─────────────────────────────────────────────────────────────────────────

def test_a_confident_requirement_defect_is_this_roles_to_fix():
    assert _v().mine is True


@pytest.mark.parametrize("cause", [TECHNICAL, ENVIRONMENT, UNCLEAR])
def test_anything_that_is_not_a_requirement_defect_is_not_touched(cause):
    assert _v(cause=cause).mine is False


def test_a_LOW_confidence_requirement_reading_does_not_act():
    """A low-confidence guess about whose problem this is has already told us it is unclear."""
    assert _v(confidence="low").mine is False


@pytest.mark.parametrize("junk", ["", "REQUIREMENT?", "produto", "requirment"])
def test_an_unrecognised_cause_degrades_to_unclear_never_to_requirement(junk):
    """Degrading toward the answer that ACTS would let a parsing accident rewrite somebody's
    ticket."""
    v = Verdict(ticket=1, cause=junk, confidence="high").normalised()
    assert v.cause == UNCLEAR and v.mine is False


# ── it always says what it concluded ────────────────────────────────────────────────────────────

def test_handing_something_back_is_WRITTEN_DOWN_not_silent():
    """A ticket the product role looked at and left must look like that, or the next person wastes
    the same five minutes reaching the same conclusion."""
    text = hand_back_comment(_v(cause=TECHNICAL, reason="a migração falha antes do código rodar"),
                             language="pt-BR")
    assert "não do requisito" in text
    assert "migração falha" in text


def test_an_unclear_verdict_admits_it_rather_than_picking_a_side():
    text = hand_back_comment(_v(cause=UNCLEAR, confidence="low", reason="o log não diz"),
                             language="pt-BR")
    assert "não consegui dizer" in text
    assert "uma pessoa decidir" in text


def test_a_hand_back_offers_no_technical_opinion():
    """An opinion somebody has to read and discard costs more than silence."""
    text = hand_back_comment(_v(cause=TECHNICAL, reason="o índice não existe"),
                             language="pt-BR")
    assert "não mexo nele" in text
    assert "sugiro" not in text.lower() and "recomendo" not in text.lower()


# ── acting ──────────────────────────────────────────────────────────────────────────────────────

def test_acting_names_what_changed_and_why():
    """A sign-off that cannot see what moved is a rubber stamp."""
    r = review([_v(reason="o critério não é avaliável", fix="reescrevi o critério 2")],
               may_act=True)
    d = r.decisions[0]
    assert d.acted is True
    assert "reescrevi o critério 2" in d.comment
    assert "critério não é avaliável" in d.comment


def test_acting_returns_it_to_BACKLOG_and_says_promotion_is_a_persons_call():
    r = review([_v(fix="x")], may_act=True, language="pt-BR")
    assert "Backlog" in r.decisions[0].comment
    assert "decisão de uma pessoa" in r.decisions[0].comment


def test_without_authority_it_still_says_what_it_WOULD_change():
    """"this is a requirement problem and here is what I would change" is useful even when nobody
    has authorised the role to change anything."""
    r = review([_v(fix="reescrever o critério 2")], may_act=False)
    d = r.decisions[0]
    assert d.acted is False
    assert "reescrever o critério 2" in d.comment
    assert "authorised" in d.detail   # internal, for the team — not the client-facing comment


def test_authority_does_not_extend_to_tickets_that_are_not_its_problem():
    r = review([_v(cause=TECHNICAL)], may_act=True)
    assert r.decisions[0].acted is False


def test_a_pass_reports_per_ticket_so_a_partial_result_is_legible():
    """"processed 12 items" tells a reader nothing about which ones moved."""
    r = review([_v(ticket=1), _v(ticket=2, cause=TECHNICAL), _v(ticket=3, confidence="low")],
               may_act=True)
    assert [d.verdict.ticket for d in r.mine()] == ["1"]
    assert [d.verdict.ticket for d in r.handed_back()] == ["2", "3"]
    assert all(d.comment for d in r.decisions)


def test_an_empty_column_is_not_an_error():
    assert review([], may_act=True).decisions == []


# ── the prompt ──────────────────────────────────────────────────────────────────────────────────

def test_the_diagnosis_is_given_as_TEXT_rather_than_asked_for():
    """It is already on the ticket. Two agents conversing with no human in the loop is where two
    mistakes compound with nobody owning the result."""
    prompt = classify_prompt(ticket_number=42, title="t", body="b",
                             diagnosis="the migration fails before the code runs")
    assert "migration fails" in prompt
    assert "#42" in prompt


def test_a_missing_diagnosis_is_stated_not_left_blank():
    prompt = classify_prompt(ticket_number=1, title="t", body="b", diagnosis="")
    assert "none was recorded" in prompt


def test_the_prompt_tells_it_to_stay_out_of_technical_judgement():
    prompt = classify_prompt(ticket_number=1, title="t", body="b", diagnosis="d")
    assert "Do not offer a technical opinion" in prompt
    assert "unclear" in prompt


def test_a_low_confidence_REQUIREMENT_reading_says_exactly_that():
    """It reached the hand-back with the right cause, so what stopped it was confidence. Saying so
    is the whole value of the message: a person now knows where to look, and knows the role
    declined to act rather than failed to notice. (This path used to raise.)"""
    text = hand_back_comment(_v(confidence="low", reason="o critério 2 é ambíguo",
                                fix="reescrever o critério 2"), language="pt-BR")
    assert "parece ser um problema do requisito" in text
    assert "não tenho certeza" in text
    assert "reescrever o critério 2" in text


@pytest.mark.parametrize("cause", [REQUIREMENT, TECHNICAL, ENVIRONMENT, UNCLEAR])
@pytest.mark.parametrize("confidence", ["high", "low"])
def test_every_verdict_produces_a_comment_and_never_raises(cause, confidence):
    """A pass over a column of parked tickets must not die on the one combination nobody tried."""
    r = review([_v(cause=cause, confidence=confidence)], may_act=True)
    assert r.decisions[0].comment


# ── provenance: the "diagnosis" may be anybody's last comment, and now it says so (#24 item 4) ──

def _tracker_with(comments):
    """A `TrackerAdapter` stand-in holding one ticket's history — or `None` for one that could not
    be read, which is the answer the port added and this reader now has to speak."""
    from openfactory.adapters.tracker.base import TicketComment

    class _Tracker:
        def comments(self, ref, *, limit=0):
            self.asked = {"ref": ref, "limit": limit}
            return (None if comments is None
                    else [TicketComment(**c) if isinstance(c, dict) else c for c in comments])

    return _Tracker()


def test_a_marked_diagnosis_is_returned_as_itself():
    from openfactory.product import board

    tracker = _tracker_with([{"body": "oi", "author": "alice"},
                             {"body": "🔧 Diagnóstico: falta o fixture", "author": "openfactory-bot"}])

    assert board._last_diagnosis(tracker, "412") == "🔧 Diagnóstico: falta o fixture"


def test_the_WHOLE_history_is_read_because_a_diagnosis_is_not_always_recent():
    """`limit=0` = every comment, and it is a decision rather than a default. The port truncates
    NEWEST-first for its other consumer ("has this been tried?"); this one is hunting a MARKED
    diagnosis, and a tech-lead's note followed by a long human argument is exactly what a window
    would hide — while the fallback below would then present a bystander's aside in its place."""
    from openfactory.product import board

    tracker = _tracker_with([{"body": "🔧 tech lead: o fixture não existe"},
                             *({"body": f"comentário {i}"} for i in range(30))])

    got = board._last_diagnosis(tracker, "412")

    assert tracker.asked == {"ref": "412", "limit": 0}
    assert got == "🔧 tech lead: o fixture não existe"


def test_the_NEWEST_marked_diagnosis_wins_because_the_port_hands_them_OLDEST_FIRST():
    """**THE ONE PROPERTY OF #97 THIS READER CONSUMES, AND IT WAS UNASSERTED.** `comments()`
    promises oldest-first on every vendor precisely so a reader can say "the last one"; this
    function spends that promise by scanning backwards, and nothing here noticed. Every existing
    test hands over a single marked comment, where forwards and backwards agree.

    A parked ticket with two tech-lead notes is not exotic — it is what a second diagnosis after a
    failed fix looks like, and it is the case where the two orders disagree completely: scanned
    forwards, the classifier is handed the hypothesis that was already tried and rejected, and
    `parked_with_diagnosis`'s own promise of "the LAST diagnosis left on it" is broken silently.

    It is also the only guard that would catch a provider regressing to newest-first. The adapters
    each assert their own order; nothing asserted that this reader DEPENDS on it."""
    from openfactory.product import board

    tracker = _tracker_with([
        {"body": "🔧 tech lead: suspeito do fixture", "author": "openfactory-bot"},
        {"body": "não era o fixture, já testei", "author": "alice"},
        {"body": "🔧 tech lead: é a migração, falha antes do código rodar", "author": "openfactory-bot"},
    ])

    assert board._last_diagnosis(tracker, "412") == (
        "🔧 tech lead: é a migração, falha antes do código rodar")


def test_the_FALLBACK_is_the_LAST_comment_because_that_is_what_it_CALLS_itself():
    """The unmarked fallback announces itself as *"o último comentário do ticket"*, and the sibling
    test below proves the qualifier and the author travel — over a thread of ONE comment, where the
    first and the last are the same object. So the sentence's central claim was never checked.

    This is the fallback that actually fires in production: measured live on a production client's
    Azure Boards project, work items 12, 13 and 14 — every parked card in `In review` came back
    through this arm. Handing
    over the OLDEST comment under a heading that says "último" is the same invented provenance the
    qualifier was written to stop, one step further in."""
    from openfactory.product import board

    got = board._last_diagnosis(_tracker_with([
        {"body": "abro isso amanhã de manhã", "author": "ana"},
        {"body": "já falei com o cliente, pode seguir sem essa parte", "author": "alice"},
    ]), "412")

    assert "pode seguir sem essa parte" in got
    assert "abro isso amanhã" not in got, "the OLDEST comment was presented as the last one"
    assert "de alice" in got and "de ana" not in got


def test_an_unmarked_last_comment_is_QUALIFIED_not_impersonated():
    """A human's passing "vou olhar isso amanhã" used to come back bare and be presented under
    the heading "the tech lead's diagnosis" — the platform publicly asserting a cause with
    invented provenance, contradicting the real tech-lead under his own title. The qualifier
    travels WITH the text because the two cross a model boundary together; a flag returned
    beside a string is a flag one caller forgets to read.

    AND IT NAMES THE AUTHOR NOW: `gh --json comments` was read for bodies alone, so "de autor não
    identificado" was literally true and is a worse sentence than the truth. `TicketComment.author`
    is each provider's most legible identity, which is exactly what a reader needs to tell a person
    from the platform."""
    from openfactory.product import board

    got = board._last_diagnosis(
        _tracker_with([{"body": "vou olhar isso amanhã", "author": "alice"}]), "412")

    assert got.startswith("(sem diagnóstico do tech-lead")
    assert "de alice" in got, "the author the port carries was thrown away"
    assert "vou olhar isso amanhã" in got

    anonymous = board._last_diagnosis(_tracker_with([{"body": "amanhã eu vejo"}]), "412")
    assert "de autor não identificado" in anonymous


def test_a_history_that_could_NOT_be_read_says_so_and_never_reads_as_silence(caplog):
    """**THE `None` ARM, and on this path it is the whole point of the port's rule.**
    `classify_prompt` renders an empty diagnosis as "(none was recorded)" — a fact about the
    TICKET. A comment thread that failed to load is a fact about US, and the model cannot tell the
    two apart: it concludes nobody has looked at this and repeats an answer that has already
    failed, with the confidence of a clean read.

    `[]` is the positive twin and it must stay silent: a ticket nobody has commented on is a real
    state, and apologising about it would put a warning in front of every ordinary parked card."""
    import logging

    from openfactory.product import board

    with caplog.at_level(logging.WARNING, logger="openfactory.product"):
        unreadable = board._last_diagnosis(_tracker_with(None), "412")

    assert unreadable, "an unreadable history came back as silence"
    assert "NÃO quer dizer que ninguém comentou" in unreadable
    assert "could not be read" in caplog.text

    assert board._last_diagnosis(_tracker_with([]), "412") == "", (
        "a ticket nobody has commented on was reported as a failure")


def test_a_tracker_that_RAISES_is_still_an_unreadable_history(caplog):
    """The port says the read side degrades rather than raising. This is the belt for the day an
    implementation breaks that promise: the caller is a review pass over a whole column, and one
    ticket whose history is unavailable must not take the other nine with it."""
    import logging

    from openfactory.product import board

    class _Broken:
        def comments(self, ref, *, limit=0):
            raise RuntimeError("401 Unauthorized")

    with caplog.at_level(logging.WARNING, logger="openfactory.product"):
        got = board._last_diagnosis(_Broken(), "412")

    assert "NÃO quer dizer que ninguém comentou" in got
    assert "401" not in got, "the transport error reached a prompt"


def test_the_prompt_no_longer_asserts_the_provenance_it_cannot_check():
    prompt = classify_prompt(ticket_number="412", title="t", body="b", diagnosis="algum texto")

    assert "## The tech lead's diagnosis" not in prompt
    assert "when one was recorded" in prompt


# ── and the language is the PROJECT'S, not this file's (#160) ───────────────────────────────────

def test_the_same_verdict_is_written_in_the_projects_own_language():
    """These comments were welded Portuguese and land on the ticket — the one surface a project
    has whether or not it has a channel. Every guard above asks for the Portuguese now, on purpose;
    this is the twin that proves the other row is reachable and says the same thing."""
    v = _v(cause=TECHNICAL, reason="the migration fails before the code runs")

    pt = hand_back_comment(v, language="pt-BR")
    en = hand_back_comment(v, language="en")

    assert pt != en, "the two languages render identically — one of the rows is not reached"
    assert "não do requisito" in pt
    assert "not the requirement" in en
    # The agent's own words travel verbatim through both: they are already written in the
    # project's language by the time they arrive (`roles.py::language_directive`).
    assert "the migration fails before the code runs" in pt
    assert "the migration fails before the code runs" in en


def test_and_an_UNCONFIGURED_project_gets_understandable_English():
    """The default a deployment that never configured anything would want — and the failure mode
    that matters: never a KeyError inside a comment on a client's ticket."""
    text = hand_back_comment(_v(cause=UNCLEAR, confidence="low"), language=None)

    assert "could not tell" in text and "{" not in text


def test_every_cause_and_both_languages_render_without_a_placeholder_left_in():
    """`_pick` degrades to English for an unknown language; what it cannot do is fill a field the
    caller forgot. A stray `{fix}` on a client's ticket is the shape that failure takes."""
    for language in ("pt-BR", "en", "de"):
        for cause in (REQUIREMENT, TECHNICAL, ENVIRONMENT, UNCLEAR):
            for fix in ("", "rewrite criterion 2"):
                text = hand_back_comment(_v(cause=cause, fix=fix, confidence="low"),
                                         language=language)
                assert "{" not in text and "}" not in text, (language, cause, text)
                acted = fix_comment(_v(cause=cause, fix=fix), language=language)
                assert "{" not in acted and "}" not in acted, (language, cause, acted)
