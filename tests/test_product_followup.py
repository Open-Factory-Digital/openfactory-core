"""The product role following through (ADR-0021) — the half she did not have.

Her memory was good where it was designed to be: requirements and domain facts live in git,
versioned and attributed. What she had no record of was what she ASKED. A question put to a person
was fire-and-forget; if nobody answered it was gone, and the requirement it blocked waited for ever
with nobody aware.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from openfactory.memory.ledger import DELIVERY, QUESTION, open_loop
from openfactory.product.followup import (
    Question,
    answered,
    ask_text,
    chase_text,
    delivered,
    delivered_text,
    deliveries_to_open,
    questions_from,
    to_open,
)


def _obs(kind: str, ticket: int = 412):
    """A REAL triage Observation — not a lookalike. The first fixtures here were a dataclass with
    the field names followup.py had invented (`code`, `message`); fixture and code agreed with
    each other and both were wrong about triage, so the tests were green while the loop was inert.
    A fixture for another module's type must be that module's type."""
    from openfactory.product.triage import Observation

    return Observation(ticket=ticket, kind=kind,
                       detail="não diz o que acontece com um extrato já conciliado")


@dataclass
class _Ticket:
    number: int
    assignees: list[str] = field(default_factory=list)


# ── asking the right person ─────────────────────────────────────────────────────────────────────

def test_a_question_is_addressed_to_the_person_who_can_answer():
    """"Somebody should clarify #412" is a message everybody reads and nobody owns."""
    qs = questions_from([_obs("no-criteria")], [_Ticket(412, ["alice"])])
    assert len(qs) == 1 and qs[0].person == "alice"


def test_an_unowned_finding_is_still_asked_just_not_at_anybody():
    """An unowned problem is still a problem — it just cannot be anybody's to answer yet."""
    qs = questions_from([_obs("no-criteria")], [_Ticket(412)])
    assert len(qs) == 1 and qs[0].person == ""


def test_only_findings_a_PERSON_can_resolve_interrupt_somebody():
    """Everything triage notices is worth writing down; only some of it is worth interrupting
    somebody about. `closed-elsewhere` is real triage vocabulary — board hygiene the report
    already covers — so it must stay out of anybody's mentions."""
    assert questions_from([_obs("closed-elsewhere")], [_Ticket(412)]) == []


def test_she_never_asks_the_same_thing_twice():
    """Asking twice is indistinguishable, from the reader's side, from an agent not paying
    attention — and it is how a channel learns her messages are noise."""
    already = [open_loop(QUESTION, "412", owner="product", about="no-criteria", ts="T1")]
    assert to_open([Question(412, "no-criteria", "x")], already, ts="T2") == []


def test_a_DIFFERENT_question_about_the_same_ticket_is_still_asked():
    already = [open_loop(QUESTION, "412", owner="product", about="no-criteria", ts="T1")]
    out = to_open([Question(412, "stale", "parado há muito tempo")], already, ts="T2")
    assert len(out) == 1 and out[0].about == "stale"


# ── closing by observation ──────────────────────────────────────────────────────────────────────

def test_a_question_closes_when_the_THING_got_fixed_not_when_somebody_replied():
    """The design decision worth defending. Closing on a Slack reply needs conversation history, a
    token scope, and a rule for what counts as an answer — and answers the wrong question. A ticket
    that gained its criteria is resolved whether or not anybody typed back, and a polite reply that
    changed nothing is not an answer at all."""
    waiting = [open_loop(QUESTION, "412", owner="product", about="no-criteria", ts="T1")]
    assert answered(waiting, live_keys=set()) == {(QUESTION, "412", "no-criteria"): "resolved"}


def test_a_question_whose_problem_is_STILL_there_stays_open():
    waiting = [open_loop(QUESTION, "412", owner="product", about="no-criteria", ts="T1")]
    assert answered(waiting, live_keys={"412:no-criteria"}) == {}


# ── the sentence she could never say ────────────────────────────────────────────────────────────

def test_a_delivery_closes_only_when_ALL_of_the_work_is_done():
    """Telling somebody their requirement is done while half of it is open is the fastest way to
    make every future "it's done" worthless."""
    waiting = [open_loop(DELIVERY, "7", owner="product", ts="T1",
                         context={"issues": "500,501"})]
    assert delivered(waiting, closed_issues={"500"}) == {}
    assert delivered(waiting, closed_issues={"500", "501"}) == {(DELIVERY, "7", ""): "delivered"}


def test_a_requirement_that_produced_no_work_opens_no_delivery_loop():
    """A loop nothing can ever close is a row that sits open for ever and teaches everyone to
    ignore the list."""
    assert deliveries_to_open({7: []}, [], ts="T1") == []


def test_a_delivery_is_not_opened_twice_for_one_requirement():
    already = [open_loop(DELIVERY, "7", owner="product", ts="T1")]
    assert deliveries_to_open({7: [500]}, already, ts="T2") == []


# ── how it reads ────────────────────────────────────────────────────────────────────────────────

def test_the_question_carries_the_mention_the_people_module_resolved():
    """A wrong mention is worse than none, so this takes whatever `people.py` decided — a real id
    when it identified somebody, a plain name when it could not."""
    loop = open_loop(QUESTION, "412", owner="product", ts="T1",
                     context={"asked": "e um extrato já conciliado?"})
    assert "<@U1>" in ask_text(loop, mention="<@U1>")
    assert "alice" in ask_text(loop, mention="alice")


def test_the_reminder_says_it_is_a_reminder():
    """Otherwise it reads as a new question the person missed, which is a small accusation."""
    loop = open_loop(QUESTION, "412", owner="product", ts="T1", context={"asked": "x"})
    text = chase_text(loop, language="pt-BR")
    assert "voltando" in text and "perguntei" in text


def test_the_reminder_offers_a_way_OUT_not_just_a_repeat():
    """A chase somebody cannot answer with "not now" is just pressure."""
    loop = open_loop(QUESTION, "412", owner="product", ts="T1", context={"asked": "x"})
    assert "paro de cobrar" in chase_text(loop, language="pt-BR")


def test_every_client_facing_sentence_avoids_delivery_jargon():
    from openfactory.product.voice import jargon_in

    loop = open_loop(QUESTION, "412", owner="product", ts="T1", context={"asked": "e o extrato?"})
    done = open_loop(DELIVERY, "7", owner="product", ts="T1")
    for text in (ask_text(loop), chase_text(loop), delivered_text(done)):
        assert not jargon_in(text), f"jargon leaked: {jargon_in(text)} in {text!r}"


# ── the boundary that shipped broken ────────────────────────────────────────────────────────────

def _real_triage_kinds() -> set[str]:
    """Every `kind="..."` triage.py actually emits — derived from its source, never hand-kept.
    A hand-kept copy of another module's vocabulary is the exact mistake this guards against."""
    import ast
    from pathlib import Path

    kinds = set()
    tree = ast.parse(Path("openfactory/product/triage.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "kind" \
                and isinstance(getattr(node.value, "value", None), str):
            kinds.add(node.value.value)
    return kinds


def test_ASKABLE_speaks_triages_actual_vocabulary():
    """The first ASKABLE was five plausible codes invented in followup.py; triage emits ONE of
    them. Every question silently failed the `code not in ASKABLE` check and the loop shipped
    fully inert — eleventh instance of built-tested-reached-by-nothing, in code written the same
    day as the guard for the tenth."""
    from openfactory.product.followup import ASKABLE

    real = _real_triage_kinds()
    assert real, "the scan found no kinds — triage.py changed shape and this guard went blind"
    ghosts = set(ASKABLE) - real
    assert not ghosts, (
        f"ASKABLE names kinds triage never emits: {sorted(ghosts)}. Real vocabulary: {sorted(real)}"
    )


def test_questions_actually_come_out_of_a_REAL_triage_report():
    """End to end through the genuine triage function — a fixture invented here could agree with
    followup.py about field names and both be wrong about triage."""
    from datetime import UTC, datetime, timedelta

    from openfactory.product.followup import questions_from
    from openfactory.product.triage import Ticket, triage

    old = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    tickets = [Ticket(number=412, title="Conciliação", state="open", column="Backlog",
                      body="sem critérios aqui", updated_at=old, assignees=["alice"])]
    report = triage(tickets)
    assert report.observations, "triage saw nothing wrong with a criteria-less stale ticket"

    questions = questions_from(report.observations, tickets)
    assert questions, (
        "a real triage finding produced no question — the loop is inert again; check the field "
        "names and ASKABLE against triage.py"
    )
    assert questions[0].person == "alice", "the assignee was not resolved as the person to ask"


def test_she_never_floods_the_channel_with_questions():
    """The first real sweep against a live 52-card backlog produced THIRTEEN questions in one
    burst. Nobody answers thirteen questions — they mute the channel, and the fourteenth, the one
    that mattered, goes unread."""
    from openfactory.product.followup import MAX_QUESTIONS_PER_PASS

    many = [Question(ticket=n, code="no-criteria", text=f"pergunta {n}") for n in range(400, 420)]
    assert len(to_open(many, [], ts="T1")) == MAX_QUESTIONS_PER_PASS


def test_the_cap_counts_questions_ALREADY_waiting():
    """Three new a week on top of ten unanswered is the same flood arriving slowly."""
    from openfactory.memory.ledger import QUESTION, open_loop
    from openfactory.product.followup import MAX_QUESTIONS_PER_PASS

    outstanding = [open_loop(QUESTION, str(n), owner="product", about="stalled", ts="T0")
                   for n in range(300, 300 + MAX_QUESTIONS_PER_PASS)]
    many = [Question(ticket=n, code="no-criteria", text="x") for n in range(400, 410)]
    assert to_open(many, outstanding, ts="T1") == [], "it asked more while N were unanswered"


def test_a_batch_of_questions_is_ONE_message_with_ONE_reason():
    """Observed in the client channel, 2026-07-28: three separate posts, each closing with the
    same "enquanto isso não estiver claro..." paragraph. Repeated, a justification stops being a
    reason and becomes wallpaper — and three posts in a row read as a machine emptying a queue
    rather than a colleague asking something."""
    from openfactory.memory.ledger import QUESTION, open_loop
    from openfactory.product.followup import _WHY_ASKING_T, _say, ask_batch

    loops = [(open_loop(QUESTION, str(n), owner="product", about="x", ts="T1",
                        context={"title": f"Card {n}", "asked": "o que falta?"}), "")
             for n in (280, 272, 141)]
    text = ask_batch(loops, agent_name="Nina", language="pt-BR")

    assert text.count(_say(_WHY_ASKING_T, "pt-BR")) == 1, "the reason is repeated per question again"
    for n in (280, 272, 141):
        assert f"#{n} (Card {n})" in text, f"#{n} lost its line or its title"
    assert text.count("Nina:") == 1, "the signature repeats"


def test_a_single_question_keeps_its_full_shape():
    """One question is a sentence, not a bulleted list of one."""
    from openfactory.memory.ledger import QUESTION, open_loop
    from openfactory.product.followup import _WHY_ASKING_T, _say, ask_batch

    loop = open_loop(QUESTION, "412", owner="product", about="x", ts="T1",
                     context={"title": "Conciliação", "asked": "o que falta?"})
    text = ask_batch([(loop, "<@U1>")], agent_name="Nina", language="pt-BR")
    assert "•" not in text and "<@U1>" in text and _say(_WHY_ASKING_T, "pt-BR") in text


def test_each_line_keeps_its_OWN_person():
    """A batch must not flatten who is being asked what — the whole point of naming somebody."""
    from openfactory.memory.ledger import QUESTION, open_loop
    from openfactory.product.followup import ask_batch

    a = open_loop(QUESTION, "1", owner="product", about="x", ts="T1", context={"asked": "q"})
    b = open_loop(QUESTION, "2", owner="product", about="x", ts="T1", context={"asked": "q"})
    text = ask_batch([(a, "<@U1>"), (b, "")], agent_name="", language="pt-BR")
    assert "<@U1> — sobre o #1" in text
    assert "sobre o #2" in text and text.count("<@U1>") == 1
