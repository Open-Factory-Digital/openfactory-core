"""Closing a card and re-aiming one — the two everyday PO acts the channel had no words for.

THE EVIDENCE, both from 2026-07-31 and both on the same client's board.

Nina proposed closing `#511` as a duplicate of `#288`. The product owner confirmed. She answered
*"Registrado o pedido junto ao time"* — and nothing existed to record it: the sentence matched no
intent, fell
through to the conversation, and the client was invited to check a request that had never been
made. `#511` is still open; the next queue proposal put it first.

The same day, `refine` ran in production for the first time and refused correctly — *"o #516 já
dizia quando estaria pronto — não mexi"* — leaving the client holding a card whose criteria were
written from REQ-0004, a text that has since been replaced by REQ-0006. The refusal was right and
it went nowhere: there was no word for the act that fixes it.

So this file pins two gestures and one refusal, and the third is the one worth stating: **a refusal
must name what to say instead, and the sentence it names must be one this surface can actually
match.** That round trip is asserted here rather than left as prose, because a pointer to a gesture
nobody implemented is exactly the shape of what it is replacing.

WHAT IT DEFENDS ABOUT THE MATCHING ITSELF. Every gesture that names a number is matched ANYWHERE in
a message instead of at its start — a preamble had been killing intents ("Nina, boa observação e
vamos … Refina o #523 …" minted a spurious requirement). Widening is paid for by requiring the thing
to be NAMED and its number ATTACHED to the gesture, the imperative mood, and a clause that is not a
question; each of the three is asserted, because dropping any one of them turns an ordinary sentence
in an accounting firm's channel into a staged write against their board.

AND IT DEFENDS THE FAMILY, NOT A MEMBER OF IT. The rule was first written for `close` and `align`
and listed beside them by hand, so the intent the regression had actually happened to went on being
anchored — one fixed, five left behind, inside the fix. Which intents scan is now read off the
patterns, and the assertion that the two agree is here.
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

import pytest

import openfactory.product.channel as pc
from openfactory.product.corpus import _KNOWN_STATUS
from openfactory.product.intents import match_intent
from openfactory.product.voice import (
    align_confirmation,
    align_refused,
    align_to_dropped_replacement,
    align_to_unagreed,
    card_aligned,
    card_closed,
    claims_a_write,
    close_confirmation,
    criteria_written,
    drop_confirmation,
    jargon_in,
    refine_refused,
    survivor_unclear,
)

# ── 1. the gesture: closing a card, in the words a person uses ─────────────────────────────────

@pytest.mark.parametrize(("phrase", "number", "in_favour_of"), [
    ("fecha o #511 como duplicado do #288", "511", "288"),
    ("encerra o #511 em favor do #288", "511", "288"),
    ("o #511 é duplicado do #288", "511", "288"),
    ("Nina, fecha o #511 como duplicata do #288", "511", "288"),
    ("encerra o #511, está coberto pelo #288", "511", "288"),
    ("fecha o #511", "511", None),
    ("encerra o cartão 511", "511", None),
    ("feche o #511, não vamos fazer isso", "511", None),
])
def test_a_person_can_close_a_card_in_their_own_words(phrase, number, in_favour_of):
    matched = match_intent(phrase)

    assert matched, phrase
    assert matched[0] == "close", f"{phrase!r} matched {matched[0]!r}"
    assert matched[1]["number"] == number, matched
    assert matched[1].get("in_favour_of") == in_favour_of, matched


def test_a_PREAMBLE_no_longer_kills_the_gesture():
    """The regression that cost a spurious requirement: intents were anchored at the start, and
    people do not write that way. Widened only where the gesture names a card."""
    matched = match_intent("Nina, boa observação — e sim, fecha o #511 como duplicado do #288")

    assert matched and matched[0] == "close", matched
    assert matched[1]["number"] == "511" and matched[1]["in_favour_of"] == "288"


@pytest.mark.parametrize(("phrase", "intent", "number"), [
    ("Nina, boa observação — e sim, refina o #523", "refine", "523"),
    ("Nina, boa observação — e sim, aceita o requisito 1", "accept", "1"),
    ("então, cancela o requisito 2", "drop", "2"),
    ("Nina, boa observação — e sim, quebra o requisito 8 em tarefas", "breakdown", "8"),
    ("boa, e alinha o #288 ao requisito 6", "align", "288"),
    ("Nina, boa observação — e sim, fecha o #511", "close", "511"),
])
def test_the_preamble_rule_reaches_EVERY_gesture_that_names_a_number(phrase, intent, number):
    """The first row is the literal sentence quoted at the top of `product_intents`: it is the one
    the 2026-07-31 regression happened to, and it was the one still anchored at the start after the
    lesson was written down. The set of scanned intents was maintained by hand beside the patterns,
    so one intent was widened and five were left behind — this repository's signature defect,
    committed inside the fix for it.
    """
    matched = match_intent(phrase)

    assert matched and matched[0] == intent, f"{phrase!r} -> {matched}"
    assert matched[1]["number"] == number, matched


def test_no_gesture_can_be_scanned_without_saying_so():
    """The structural half: `_SCANNED` is derived from the patterns instead of listed next to them.
    A hand-kept list is what let the two facts sit four lines apart looking consistent."""
    from openfactory.product.intents import _INTENTS, _SCANNED

    for name, pattern in _INTENTS:
        anchored = pattern.pattern.startswith("^")
        assert anchored != (name in _SCANNED), (
            f"{name} is {'anchored' if anchored else 'scanned'} and the set disagrees")


@pytest.mark.parametrize(("plan", "order"), [
    ("amanhã a gente quebra o requisito 8 em tarefas", "quebra o requisito 8 em tarefas"),
    ("hoje a gente define os critérios do 288", "define os critérios do 288"),
    ("a gente fecha o #511 amanhã", "fecha o #511"),
    ("o time aceita o requisito 1 na quinta", "aceita o requisito 1"),
    ("amanhã a gente alinha o #288 ao requisito 6", "alinha o #288 ao requisito 6"),
    ("a gente cancela o requisito 2 se não der", "cancela o requisito 2"),
    # the same verb as a NOUN, which the mood guard cannot see either: "a quebra do requisito 8"
    ("a quebra do requisito 8 em tarefas foi ontem", "quebra o requisito 8 em tarefas"),
])
def test_a_PLAN_is_not_an_ORDER_even_when_they_are_spelled_the_same(plan, order):
    """The hole the widening opened, and the reason it is not closed with a list of pronouns.

    Portuguese spells the imperative and the third person singular identically, and "a gente +
    3rd person" is how this language says "we" — so "amanhã a gente quebra o requisito 8 em
    tarefas" reads as an order under every one of the other guards. It is a sentence about
    tomorrow, and it FILED WORK on the client's board today, with no confirmation in between.

    Every noun phrase in the language is a candidate subject, so a list of the ones to refuse has
    holes nobody can see and each hole is a write. What has no holes is the grammar: an imperative
    OPENS ITS CLAUSE. The pair is asserted together — the plan matching nothing proves nothing on
    its own, since a broken pattern would also match nothing.
    """
    assert match_intent(plan) is None, f"{plan!r} was read as an instruction"
    assert match_intent(order) is not None, f"the guard also killed the real order: {order!r}"


@pytest.mark.parametrize(("phrase", "intent"), [
    ("beleza, e fecha o #511", "close"),
    ("Nina, por favor encerra o #511", "close"),
    ("boa, e alinha o #288 ao requisito 6", "align"),
])
def test_a_CONNECTIVE_still_reaches_the_gestures_that_only_ask(phrase, intent):
    """People write "beleza, e fecha o #511", and each of these stages a proposal somebody has to
    confirm. Being wrong here costs a question, so the connective is affordable."""
    matched = match_intent(phrase)

    assert matched and matched[0] == intent, f"{phrase!r} -> {matched}"


@pytest.mark.parametrize("phrase", [
    "a gente vê isso, e quebra o requisito 8 em tarefas",
    "vou olhar, e refina o #412",
])
def test_the_SAME_CONNECTIVE_never_reaches_the_two_that_write_on_the_match_alone(phrase):
    """The other half of the same rule, and the whole reason the two groups differ. A connective is
    exactly what carries an elided subject into the next clause — "a gente vê isso e quebra o
    requisito 8" is one sentence about what we will do — and behind `breakdown` and `refine` there
    is nobody to ask: the match itself spends money and edits a client's ticket.

    So they are reached only where a clause actually begins. The cost is a rephrase; the cost of
    the other choice was eight tickets nobody released.
    """
    assert match_intent(phrase) is None, f"{phrase!r} filed work off a plan"


def test_the_gestures_matched_STRICTLY_are_the_ones_the_handler_leaves_ungated():
    """The two-tier rule is only sound while the tiers describe the handler, and a set maintained
    by hand beside the fact it describes is what this file already exists downstream of. So the
    membership is re-derived from `_run_intent` itself: an intent that stages a proposal calls
    `remember`, and one that does not reaches a client's board on the match alone."""
    from openfactory.product.intents import _SCANNED, _UNCONFIRMED

    ungated = {name for name, branch in _intent_branches().items()
               if name in _SCANNED and not any(
                   getattr(c.func, "id", "") == "remember"
                   for c in ast.walk(branch) if isinstance(c, ast.Call))}

    assert ungated == set(_UNCONFIRMED), (
        f"the handler writes without a confirmation for {ungated}, and the matcher believes "
        f"{set(_UNCONFIRMED)}")


def test_the_gestures_with_NO_confirmation_STILL_check_who_is_asking():
    """THE OTHER HALF OF THE DECLARED EXCEPTION, and the half that was missing. Running on the
    pattern alone is a decision this codebase can defend — filing spends nothing, and the way out
    of Backlog is separately staged and gated. Running on the pattern alone for ANYBODY is not.

    These two branches checked nothing and leaned on `file_issues`/`refine` to refuse one call
    deeper, so a non-approver bought a receipt and a round-trip before hearing no — and the day a
    second caller reaches those methods, the only gate is somewhere nobody writing a new branch is
    looking. Derived from the dispatcher rather than asserted about today's two, because the next
    gesture added to `_UNCONFIRMED` must inherit this rather than be remembered.
    """
    from openfactory.product.intents import _UNCONFIRMED

    branches = _intent_branches()
    unchecked = sorted(name for name in _UNCONFIRMED
                       if not any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "may_act"
                                  for c in ast.walk(branches[name])))

    assert not unchecked, (
        f"{unchecked} write on the match alone AND ask nobody whether the person may act — the "
        "exception covers the missing confirmation, never the missing gate")


@pytest.mark.parametrize(("text", "wrote"), [
    ("quebra o requisito 7 em tarefas", "broke_down"),
    ("refina o #412", "refined"),
])
def test_a_gesture_that_writes_on_the_MATCH_ALONE_is_refused_to_a_non_approver(text, wrote):
    """Driven through `handle`, because the gate being present in the source is not the same fact
    as the write not happening. Both directions: refused to an outsider, and still working for the
    person whose yes would have unlocked it anyway."""
    project, module = _Project(admins=["UADM"]), _Module()

    reply = pc.handle(project, text=text, user="UOUTRO", thread="C1", channel="C1", module=module)

    assert getattr(module, wrote) is None, f"{text!r} wrote for somebody who may not approve"
    assert reply and "permissão" in reply, f"the refusal was swallowed or unreadable: {reply}"
    assert pc.pending_for("C1") is None, "a refused gesture left something staged"

    pc.handle(project, text=text, user="UADM", thread="C1", channel="C1", module=module)

    assert getattr(module, wrote) is not None, "the gate refused the approver too"


def test_no_scanned_gesture_can_be_matched_without_the_clause_anchor():
    """The structural half, like `_SCANNED` before it: the anchor is applied over the whole table
    in one place rather than written into eleven patterns by hand. Eleven copies is eleven chances
    to leave one out, which is the defect this file is downstream of, committed twice."""
    from openfactory.product.intents import (
        _BRIDGE,
        _CLAUSE_START,
        _INTENTS,
        _SCANNED,
        _UNCONFIRMED,
    )

    for name, pattern in _INTENTS:
        if name not in _SCANNED:
            continue
        expected = _CLAUSE_START + ("" if name in _UNCONFIRMED else _BRIDGE)
        assert pattern.pattern.startswith(expected), (
            f"{name} scans the whole message and does not require the gesture to open a clause")


@pytest.mark.parametrize("phrase", [
    "quando vamos aceitar o requisito 1?",
    "pode quebrar o requisito 8 em tarefas?",
    "cancela o requisito 2, isso ainda faz sentido?",
    "não vamos cancelar o requisito 2",
    "vamos quebrar o requisito 8 amanhã",
    "pode refinar o #412?",
])
def test_what_a_WIDENED_gesture_still_refuses(phrase):
    """Scanning is paid for by the three guards, and the family pays the same price the two that
    were widened first do. `refine` and `breakdown` write on the match alone — no confirmation
    stands between these sentences and a client's board — so the mood guard is load-bearing:
    "vamos quebrar" is a plan, and filing eight tickets off it spends money nobody released.

    The third row is why the question mark is read at the NUMBER and not at the end of the match:
    `drop` captures the rest of the message as a reason, so looking past it found no punctuation
    at all and an open question matched as an instruction.
    """
    assert match_intent(phrase) is None, f"{phrase!r} was read as an instruction"


@pytest.mark.parametrize("phrase", [
    "quando vamos fechar o #511?",
    "quando fecha o #511?",
    "podemos fechar o #511?",
    "vamos fechar o #511 depois",
    "não fecha o #511",
    "nao fecha o #511",
    "ainda não fecha o #511",
])
def test_what_must_NEVER_read_as_an_instruction_to_close(phrase):
    """Three separate guards, one per row of this table.

    The MOOD kills the modals: every one of them takes the infinitive in Portuguese, so refusing
    "fechar" refuses the whole class instead of a list somebody has to keep extending. The QUESTION
    MARK kills "quando fecha o #511?", whose verb really is the imperative form. The NEGATION kills
    the one shape whose meaning inverts while every other signal stays identical.
    """
    matched = match_intent(phrase)

    assert (matched or ("", {}))[0] != "close", f"{phrase!r} was read as an instruction to close"


@pytest.mark.parametrize("phrase", [
    "fecha o mês 10",
    "fecha o período 3 no sistema",
    "o fechamento do mês 2 travou",
])
def test_a_bare_number_is_not_a_card_in_an_accounting_firms_channel(phrase):
    """The reason the card reference is required and a number alone is not. "fecha o mês 10" is an
    ordinary sentence where this runs, and reading it as a card would stage a write on their
    board — with a confirmation button underneath it."""
    assert (match_intent(phrase) or ("", {}))[0] != "close", phrase


def test_the_surviving_card_is_read_off_a_CONNECTIVE_not_off_the_next_number():
    """Without the connective, the closing comment would name a card nobody mentioned — in writing,
    on the client's board, in their name."""
    _, captures = match_intent("fecha o #511, já falamos disso na semana 32")

    assert captures["number"] == "511"
    assert "in_favour_of" not in captures, captures


@pytest.mark.parametrize("phrase", [
    "fecha o #511, por favor, e depois o #288",
    "fecha o #511 por favor, olha o #288 também",
    "encerra o #511, por favor veja o #288",
    "fecha o #511 por favor e me avisa no #288",
    "fecha o #511. Por favor confira o #288 também",
    "fecha o #511, em lugar disso vamos ver o #288",
    # the same politeness with no comma to lean on — people type this way, and the connective is
    # then the only thing between an ordinary request and a duplicate relation on their board
    "fecha o #511 por favor o #288 também",
    "encerra o #511 por favor o #288",
])
def test_POLITENESS_never_names_a_surviving_card(phrase):
    """`favor` was a connective on its own, and "por favor" is the commonest politeness phrase in
    this language — so an ordinary sentence closed a card in favour of an unrelated one, and the
    closing comment said so in writing on the client's board.

    A connective is a PHRASE: "em favor de", "a favor de", "em lugar de". The noun alone means
    nothing, and neither does the clause that happens to follow it.
    """
    matched = match_intent(phrase)

    assert matched and matched[0] == "close", f"{phrase!r} -> {matched}"
    assert matched[1]["number"] == "511", matched
    assert "in_favour_of" not in matched[1], (
        f"{phrase!r} invented a duplicate relation nobody stated")


def test_the_number_a_gesture_NAMES_is_the_one_attached_to_it():
    """The other half of the same rule. A gap of "any twenty characters" is a whole clause, and a
    clause is where the next unrelated number lives."""
    assert match_intent("fecha isso, olha o #288") is None
    assert match_intent("refina isso pra mim até o dia 3") is None


# ── 2. the gesture: aligning a card to a requirement ───────────────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "alinha o #288 ao requisito 6",
    "Nina, realinha o #288 ao requisito 6",
    "escreve os critérios do #288 a partir do requisito 6",
    "reescreve os critérios do #523 com base no requisito 6",
    "atualiza os critérios do #516 para o requisito 6",
    "boa, e alinha o #288 ao requisito 6",
])
def test_a_person_can_ask_for_a_card_to_be_re_aimed(phrase):
    matched = match_intent(phrase)

    assert matched and matched[0] == "align", f"{phrase!r} -> {matched}"
    assert matched[1]["requirement"] == "6", matched


def test_naming_a_requirement_is_the_WHOLE_difference_from_refine():
    """One writes where nothing was written; the other replaces what somebody may already have
    worked from. The same sentence means both, and the requirement is what tells them apart."""
    assert match_intent("escreve os critérios do #288")[0] == "refine"
    assert match_intent("escreve os critérios do #288 a partir do requisito 6")[0] == "align"


@pytest.mark.parametrize("phrase", [
    "dá pra alinhar o #288 ao requisito 6?",
    "não alinha o #288 ao requisito 6",
    "alinha o #288 ao requisito 6?",
])
def test_a_question_or_a_refusal_never_re_aims_a_card(phrase):
    assert (match_intent(phrase) or ("", {}))[0] != "align", phrase


def test_the_NEGATION_guard_is_WHAT_REFUSES_a_negated_gesture():
    """One of the four guards this file advertises, and it used to decide nothing. Nothing could
    place "não " immediately before a verb — the clause anchor cannot span it and no bridge word
    carried it — so the lookbehind was never consulted and "não fecha o #511" was refused purely by
    where the clause begins.

    That matters on the day somebody widens the anchor, which this file has already done once: the
    guard would have looked present, and an instruction NOT to close would have become a staged
    close on a client's board with every test still green. So the negator is admitted as far as the
    verb and refused there, and this asserts the refusal comes from the guard by taking the guard
    out: with `_NOT_NEGATED` removed the sentence must match, or it is inert again.
    """
    from openfactory.product import intents

    close = next(p for name, p in intents._PATTERNS if name == "close")
    without_the_guard = close.pattern.replace(intents._NOT_NEGATED, "")
    assert without_the_guard != close.pattern, "the guard is no longer part of this pattern"
    disarmed = re.compile(intents._CLAUSE_START + intents._BRIDGE + without_the_guard, close.flags)

    assert disarmed.search("fecha o #511"), "the rebuilt pattern matches nothing at all"
    assert disarmed.search("não fecha o #511"), (
        "with the negation guard removed nothing changes — it decides nothing, and the clause "
        "anchor is the only thing refusing an instruction NOT to close a card")

    for negated in ("não fecha o #511", "nunca fecha o #511", "e não fecha o #511"):
        assert match_intent(negated) is None, negated


# ── the doubles ────────────────────────────────────────────────────────────────────────────────

class _Req:
    def __init__(self, number=6, status="accepted", superseded_by=None):
        self.number, self.status, self.superseded_by = number, status, superseded_by
        self.title, self.slug, self.path = "Aviso acionável", "aviso-acionavel", "0006-x.md"

    @property
    def is_live(self):
        return self.status not in ("superseded", "dropped")

    @property
    def is_promise(self):
        return self.status == "accepted"


class _Result:
    def __init__(self, ok=True, detail="", ref="", existed=False):
        self.ok, self.detail, self.ref, self.existed = ok, detail, ref, existed
        self.url, self.merged = "", True


class _Module:
    """The three calls this surface makes, and nothing else. Built to the contract rather than to
    the implementation, so it fails loudly if a signature moves."""

    def __init__(self, req=None, *, closes=None, aligns=None, refines=None, breaks=None,
                 corpus=(), available=True):
        # `corpus` holds the WHOLE chain when a test needs one: a supersession is a sequence, and a
        # double that can only answer for one requirement can only ever prove a single hop.
        self.reqs = list(corpus) or ([req] if req is not None else [])
        self.closed_with = self.aligned_with = None
        # the two that reach a client's board on the match alone, recorded so a sentence that must
        # never be an instruction can be asserted against the WRITE and not against the label
        self.broke_down = self.refined = None
        self._closes, self._aligns = closes or _Result(), aligns or _Result()
        self._refines = refines or _Result(detail="3 critérios")
        # one result per card, and each one is its own outcome: filed and placed, filed and NOT
        # placed, or found already there. The default is the happy one.
        self._breaks = list(breaks) if breaks is not None else [_Result(ok=True, ref="#901")]
        # AN UNREADABLE BASE STILL ANSWERS, AND ANSWERS EMPTY. `load_product_context` never raises:
        # it hands back a context whose corpus holds nothing, which is why "I could not read it"
        # and "there is no such requirement" were told apart by nothing.
        self._available = available

    def context(self):
        from types import SimpleNamespace

        # empty when unavailable, which is the whole point: the real loader answers this way too,
        # so "I could not read it" and "there is nothing there" look identical to `by_number`
        reqs = self.reqs if self._available else []

        class _Corpus:
            def by_number(self, n):
                return next((r for r in reqs if r.number == n), None)

        return SimpleNamespace(available=self._available, corpus=_Corpus(),
                               reason="" if self._available else "sem checkout")

    def close_card(self, number, *, actor, in_favour_of=None, reason=""):
        self.closed_with = (number, actor, in_favour_of, reason)
        return self._closes

    def align_card(self, number, *, requirement, actor):
        self.aligned_with = (number, requirement, actor)
        return self._aligns

    def break_down(self, number, *, actor):
        self.broke_down = (number, actor)
        return self._breaks

    def refine(self, number, *, actor=""):
        self.refined = (number, actor)
        return self._refines

    def settle_acceptance(self, text):
        return None

    # the conversational fall-through, so a message this surface REFUSES still gets an answer
    def answer(self, question, *, conversation="", pending="", **_):
        from types import SimpleNamespace

        return SimpleNamespace(ok=True, is_defect=False, is_request=False, decisions=[],
                               text="não sei dizer.", violates=None)

    def close_decisions_answered(self, *, channel=""):
        return None


class _Product:
    enabled, slack_channel, agent_name = True, "C1", "Nina"

    def __init__(self, admins):
        self.admins = admins


class _Project:
    name, language = "books", "pt-BR"

    def __init__(self, admins=("UADM",)):
        self.product = _Product(list(admins))


@pytest.fixture(autouse=True)
def _clean_stage(monkeypatch):
    # THE STATE LIVES IN `openfactory/product/staging.py` NOW (#98 slice 3), so isolation is
    # applied THERE. Rebinding the re-export on `product_channel` would leave the code
    # reading the original dict: the fixture would look like it isolates and would not,
    # which is how a staged proposal leaked into the next test when this move was first
    # attempted — with the symptom landing far from the cause.
    from openfactory.product import staging as _staging
    monkeypatch.setattr(_staging, "_PENDING", {})
    monkeypatch.setattr(_staging, "_EXPIRED_TOMBSTONES", {})
    from openfactory.memory import transcript

    monkeypatch.setattr(transcript, "record", lambda *a, **k: "")
    monkeypatch.setattr(transcript, "recent", lambda *a, **k: [])
    yield


# ── 3. closing: the whole gesture reaches the write, and not before ────────────────────────────

def test_the_whole_closing_gesture_reaches_the_write_through_the_channel():
    """The reachability assertion, not a unit one. The capability this replaces did not exist at
    all — the agent narrated an act nobody performed — so "the module has a method" proves nothing
    that matters here."""
    project, module = _Project(), _Module()

    ask = pc.handle(project, text="Nina, fecha o #511 como duplicado do #288",
                    user="UADM", thread="C1", channel="C1", module=module)

    assert "#511" in ask and "#288" in ask and "Confirma?" in ask, ask
    assert module.closed_with is None, "it wrote before anybody confirmed"

    done = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)

    assert module.closed_with == ("511", "UADM", "288", ""), module.closed_with
    assert "#511" in done and "#288" in done, done


def test_the_actor_reaching_the_module_is_the_RAW_slack_id():
    """`may_act` is re-checked one call deeper against the configured ids; a decorated `<@U…>`
    failed that lookup, so the gate that had just admitted the admin refused them. Decoration
    belongs only to what gets written."""
    project, module = _Project(), _Module()
    pc.handle(project, text="fecha o #511", user="UADM", thread="C1", channel="C1", module=module)

    pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)

    assert module.closed_with[1] == "UADM", module.closed_with


def test_an_unauthorised_yes_neither_closes_nor_consumes_the_proposal():
    project, module = _Project(admins=["UADM"]), _Module()
    pc.handle(project, text="fecha o #511 em favor do #288", user="UADM", thread="C1",
              channel="C1", module=module)

    refused = pc.handle(project, text="sim", user="USTRANGER", thread="C1", channel="C1",
                        module=module)

    assert module.closed_with is None, refused
    assert pc.pending_for("C1") is not None, "the real approver's yes would find nothing"


def test_the_person_who_asked_can_take_their_own_proposal_back():
    """Refusing is gated, but not by the approval rule: the requester correcting themselves and a
    third party destroying a draft an admin was about to approve are not the same act."""
    project, module = _Project(admins=["UADM"]), _Module()
    pc.handle(project, text="fecha o #511 como duplicado do #288", user="UCLIENT", thread="C1",
              channel="C1", module=module)

    pc.handle(project, text="não", user="UCLIENT", thread="C1", channel="C1", module=module)

    assert pc.pending_for("C1") is None, "the requester could not withdraw their own proposal"
    assert module.closed_with is None


def test_a_question_about_closing_stages_nothing_at_all():
    """Through the production handler, not through the matcher: the harm is not a wrong label, it
    is a confirmation button under a question — which also evicts whatever else was pending."""
    project, module = _Project(), _Module()

    pc.handle(project, text="quando vamos fechar o #511?", user="UADM", thread="C1",
              channel="C1", module=module)

    assert pc.pending_for("C1") is None, "a question armed the confirmation gate"


def test_a_machinery_failure_is_not_read_out_to_the_client():
    """Every `WriteResult.detail` a client reads passes the sanitiser. This branch is new, and the
    sibling that shipped raw stderr was new once too."""
    project = _Project()
    module = _Module(closes=_Result(ok=False, detail="fatal: could not read Username for github"))
    pc.handle(project, text="fecha o #511", user="UADM", thread="C1", channel="C1", module=module)

    said = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)

    assert "fatal" not in said and "github" not in said.lower(), said
    assert "do meu lado" in said, said


def test_a_business_refusal_IS_read_out_to_the_client():
    """The other half: "that card is already closed" is an explanation somebody can act on, and
    swapping it for "the problem is on my side" would be a lie."""
    project = _Project()
    module = _Module(closes=_Result(ok=False, detail="o #511 já estava encerrado"))
    pc.handle(project, text="fecha o #511", user="UADM", thread="C1", channel="C1", module=module)

    said = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)

    assert "já estava encerrado" in said, said


def test_a_HALF_DONE_close_is_not_announced_as_a_finished_one():
    """`close_card` closes the card and then writes the pointer on the survivor, and it reports the
    second half failing as a SUCCESS carrying a sentence for the client — the close happened and
    must not be re-offered. The reply composed its own headline and returned it, so that sentence
    was computed, logged for us, and never said: the client read "Escrevi nos dois" about a note
    that is not on the card the next person will pick up.
    """
    project = _Project()
    unlinked = _Result(ok=True, ref="#511",
                       detail="fechei o #511, mas não consegui deixar o registro disso no #288. "
                              "O time foi avisado.")
    module = _Module(closes=unlinked)
    pc.handle(project, text="fecha o #511 como duplicado do #288", user="UADM", thread="C1",
              channel="C1", module=module)

    said = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)

    assert "não consegui deixar o registro" in said, (
        f"the module wrote a sentence for the client and the channel dropped it: {said}")
    assert "nos dois" not in said, f"it claimed a link that does not exist: {said}"
    assert "#288" in said, said


def test_THE_SAME_RULE_holds_for_the_sibling_branch_that_writes_in_two_places():
    """One branch fixed and the next one left behind is what this repository keeps paying for.
    `file_defect` reports the identical shape — the problem was recorded and the board refused to
    place the card, so the card is invisible to the queue until a person moves it — and that
    sentence was dropped in exactly the same way."""
    project = _Project()

    class _Filing(_Module):
        def file_defect(self, **_):
            return _Result(ok=True, ref="#77",
                           detail="registrei o problema, mas ainda não consegui posicionar o "
                                  "cartão no quadro — o time foi avisado e posiciona.")

    module = _Filing()
    pc.remember("C1", {"kind": "defect", "restated": "o relatório sai com o mês errado",
                       "reported_by": "<@UADM>", "channel": "C1"})

    said = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)

    assert "não consegui posicionar" in said, (
        f"the module wrote a sentence for the client and the channel dropped it: {said}")


def test_a_WHOLE_close_still_reads_as_one():
    """The other side of the same branch: with nothing left to say, nothing extra is said."""
    project, module = _Project(), _Module()
    pc.handle(project, text="fecha o #511 como duplicado do #288", user="UADM", thread="C1",
              channel="C1", module=module)

    said = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)

    assert "Escrevi nos dois" in said, said


def test_a_HALF_DONE_alignment_is_not_announced_as_a_finished_one():
    """THE BRANCH THAT WAS LEFT BEHIND, and the sentence it dropped is the worst of the three.
    `align_card` rewrites the card and then comments to say what happened to it; the comment
    failing is reported as a SUCCESS with a sentence for the client, because the criteria really
    were replaced and the rewrite must not be re-offered.

    This branch said none of it AND announced the note: the card's criteria changed underneath
    thirteen people, nothing on the card says so, and the one who authorised it was told the
    opposite — "escrevi nos dois", one branch over, in a different vocabulary.
    """
    project = _Project()
    unexplained = _Result(ok=True, ref="#288",
                          detail="alinhei o #288, mas não consegui deixar escrito nele que o "
                                 "texto anterior foi substituído. O time foi avisado.")
    module = _Module(_Req(6, "accepted"), aligns=unexplained)
    pc.handle(project, text="alinha o #288 ao requisito 6", user="UADM", thread="C1",
              channel="C1", module=module)

    said = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)

    assert "não consegui deixar escrito" in said, (
        f"the module wrote a sentence for the client and the channel dropped it: {said}")
    assert "Deixei registrado no item" not in said, (
        f"it announced a note that is not on the card: {said}")


def test_a_WHOLE_alignment_still_reads_as_one():
    """The other side, and the reason this branch cannot simply say everything: `align_card`
    reports its happy path in the same field, as a COUNT of what it wrote. Appending that would
    hang a fragment off a finished sentence, so a measure is not something still to say — while
    anything that is not one still reaches the person it was written for."""
    project = _Project()
    module = _Module(_Req(6, "accepted"),
                     aligns=_Result(ok=True, ref="#288", detail="3 critérios"))
    pc.handle(project, text="alinha o #288 ao requisito 6", user="UADM", thread="C1",
              channel="C1", module=module)

    said = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)

    assert "Deixei registrado no item" in said, said
    assert "3 critérios" not in said, f"a count was read out as a caveat: {said}"


def test_a_HALF_DONE_refinement_is_not_announced_as_a_finished_one():
    """THE FOURTH SIBLING, and the only one the `_still_to_say` pass did not reach. `refine` writes
    the criteria and then comments to say who wrote them; the comment failing comes back `ok` with
    the module's own sentence about it, because the criteria really are on the card.

    This line took that sentence, put it in the parenthesis where the COUNT goes, and then said "e
    deixei um comentário dizendo que fui eu" anyway — so the client read a denial and an assertion
    of the same note eight words apart, in one sentence. Driven through `handle` on the production
    gesture: the branch is reached by the match alone, with no confirmation in between.
    """
    project = _Project()
    unexplained = _Result(ok=True, ref="#412",
                          detail="escrevi os critérios no #412, mas não consegui deixar o "
                                 "comentário dizendo que fui eu — isso está escrito no próprio "
                                 "item. O time foi avisado.")
    module = _Module(refines=unexplained)

    said = pc.handle(project, text="refina o #412", user="UADM", thread="C1", channel="C1",
                     module=module)

    assert module.refined == ("412", "UADM"), "the gesture never reached the write"
    assert "não consegui deixar o comentário" in said, (
        f"the module wrote a sentence for the client and the channel dropped it: {said}")
    assert "e deixei um comentário" not in said, (
        f"it announced the comment that failed, in the same sentence that denies it: {said}")


def test_a_WHOLE_refinement_still_reads_as_one():
    """The other side: `refine`'s happy path reports a COUNT in the same field, and a count is not
    something still to say. It belongs in the parenthesis, and the note it wrote may be claimed."""
    project, module = _Project(), _Module()

    said = pc.handle(project, text="refina o #412", user="UADM", thread="C1", channel="C1",
                     module=module)

    assert "(3 critérios)" in said, said
    assert "e deixei um comentário" in said, said
    assert said.count("comentário") == 1, f"the note is claimed and caveated at once: {said}"


# ── 8b. the FAMILY, not the fourth member of it ────────────────────────────────────────────────
#
# Four branches report a module method that writes TWICE. Three learned the rule and one did not,
# which is this repository's signature failure and the reason these two lists exist: the next
# branch is classified deliberately or the test fails, rather than shipping as the fifth exception.

#: Module methods that leave TWO marks and report the second one failing as an `ok` result carrying
#: a sentence written for the client. Every one of them must reach `_still_to_say`.
_WRITES_TWICE = {
    "close_card": "closes the card, then points the surviving one at it",
    "align_card": "rewrites the criteria, then says on the card what happened to them",
    "file_defect": "files the problem, then places the card on the board",
    "file_ticket": "opens the card as described, then places it on the board",
    "refine": "writes the criteria, then comments to say who wrote them",
    # THE FIFTH, AND THE ONE THIS HAND-WRITTEN TABLE GOT WRONG. It sat in `_WRITES_ONCE` under "one
    # card per task, each carrying its own result" — true, and about the wrong thing: each RESULT
    # still carries two marks, because `_file_one` creates the issue and then places it. The
    # sentence answered "how many results?" while the column asks "how many writes per result?", so
    # the reply announced "estão no Backlog" over a card the board had refused. A list maintained
    # beside the fact it describes, exactly what this file already exists downstream of — hence the
    # derived cross-check below.
    "break_down": "files each card, then places it on the board",
}
#: Module methods that leave ONE mark, so an `ok` result has nothing left over to say.
_WRITES_ONCE = {
    "accept": "one commit in the base",
    "drop": "one commit in the base",
    "note_fact": "one commit in the base",
    "propose": "one proposal, whose landing is reported by `merged`",
    "promote": "one move per card, each carrying its own result",
    "baseline": "one pass, announced by itself",
    # One commit, like its two siblings above — clone, append the row, push. The `existed` case
    # (the same decision already recorded today) is a prior result, not a residue: nothing was left
    # undone, so there is nothing for `_still_to_say` to carry.
    "record_decision": "one commit in the base",
}
#: Everything else the channel asks the module: reads, judgements and bookkeeping. Listed so that a
#: WRITE added later cannot arrive unclassified — an unknown name is a failure, not a silence.
_ASKS_ONLY = frozenset({
    "answer", "confirmed", "context", "draft", "introduce", "propose_queue", "record_decisions",
    "review_needs_action", "settle_acceptance", "status_line", "triage_board",
    "close_decisions_answered",
})

#: The one path. `_still_to_say` is what reads `WriteResult.detail` on a success and says whatever
#: the module has left to say; a branch that composes its own headline and returns it is exactly
#: how three sentences were computed, logged for us, and never reached the person they were for.
_ONE_PATH = "_still_to_say"


#: WHERE A REPLY TO A MODULE WRITE CAN BE COMPOSED — both files, because the confirmation executor
#: moved to the core (#105) while the typed intents stayed on the channel. A guard that kept
#: scanning only `product_channel.py` would have gone silently blind the day the branches moved:
#: `_module_calls` would find nothing for `close_card`, and "the channel never calls it" reads as
#: an accusation when it is really the scanner looking at the wrong file.
_COMPOSING_FILES = ("openfactory/product/channel.py", "openfactory/product/confirm.py")


def _channel_tree() -> ast.Module:
    """Both files as one tree, so a branch is found wherever the reply is composed."""
    merged = ast.Module(body=[], type_ignores=[])
    for path in _COMPOSING_FILES:
        body = ast.parse(Path(path).read_text()).body
        assert any(isinstance(n, ast.FunctionDef) for n in body), (
            f"{path} contributed no functions to the scan — the file moved or was renamed, and "
            f"every guard reading this tree is now looking at half the code")
        merged.body.extend(body)
    return merged


def _module_calls(tree: ast.Module) -> dict[str, list[ast.Call]]:
    """Every `module.<method>(…)` the channel makes, by method."""
    found: dict[str, list[ast.Call]] = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and getattr(node.func.value, "id", "") == "module"):
            found.setdefault(node.func.attr, []).append(node)
    return found


def _plainly_called(node: ast.AST) -> set[str]:
    return {c.func.id for c in ast.walk(node)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}


def _reporting_block(tree: ast.Module, call: ast.Call) -> ast.AST:
    """The narrowest block that has to turn this write into the client's sentence — the branch, not
    the whole handler: `_handle` calls `_still_to_say` three times already, so asking only whether
    the FUNCTION mentions it is how a fourth branch inside it would pass."""
    holds = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.If)) and any(x is call for x in ast.walk(n))]
    return max(holds, key=lambda n: (n.lineno, n.col_offset))


def _residue_carriers() -> set[str]:
    """Module methods that can answer a SUCCESS with a sentence still to say — READ OFF `module.py`
    rather than remembered here.

    A residue is `WriteResult(ok=True, …, detail=…)` with no `existed=True`: the second write
    failed, the first stands, and the module wrote a sentence for the client about the difference.
    `existed` is excluded because it is the module saying "this was already there", which the
    replies LEAD with; `ok=bool(...)` is excluded because a computed flag is a failure branch, not
    a residue.

    Then propagated one method to the next through `self.<name>(…)`, because that hop is precisely
    where the fifth branch hid: `break_down` returns `file_issues`, which returns `_file_one`, and
    only the last of the three constructs the result. A classification that stops at the method the
    channel names cannot see the write it delegates.
    """
    tree = ast.parse(Path("openfactory/product/module.py").read_text())
    functions = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    carriers = set()
    for name, fn in functions.items():
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call) and getattr(call.func, "id", "") == "WriteResult"):
                continue
            kw = {k.arg: k.value for k in call.keywords}
            ok, existed = kw.get("ok"), kw.get("existed")
            if not (isinstance(ok, ast.Constant) and ok.value is True) or "detail" not in kw:
                continue
            if isinstance(existed, ast.Constant) and existed.value is True:
                continue
            carriers.add(name)
    for _ in range(len(functions)):        # a fixpoint; the call graph here is three deep at most
        for name, fn in functions.items():
            if name in carriers:
                continue
            if any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                   and getattr(c.func.value, "id", "") == "self" and c.func.attr in carriers
                   for c in ast.walk(fn)):
                carriers.add(name)
    return carriers


def test_the_hand_CLASSIFICATION_agrees_with_the_MODULE_ITSELF():
    """WHY THE TABLE ABOVE DID NOT CATCH THE FIFTH BRANCH: it is a hand-written set, and a hand
    written set beside the fact it describes is the defect this whole file is downstream of.
    `break_down` was filed under "writes once" with a sentence that was true about something else,
    the family test then skipped it by construction, and the reply it never checked told a client
    that cards with no column were in Backlog.

    So the two lists are now answerable to the module. Anything the channel calls that can hand
    back a success carrying a residue must be in `_WRITES_TWICE` — whether or not anybody
    remembered to move it.
    """
    misfiled = sorted((_residue_carriers() & set(_module_calls(_channel_tree()))) - set(
        _WRITES_TWICE))

    assert not misfiled, (
        f"{misfiled} can return an `ok` WriteResult carrying a sentence for the client and this "
        f"file classifies them as writing once — so whatever they could not do is computed, "
        f"logged for us, and never said")


def test_every_module_write_the_channel_makes_is_classified():
    """DEFAULT DENY. A fifth two-write branch means a module method this file has never seen, and
    an unclassified one fails here rather than being reported by a headline somebody wrote fresh."""
    called = set(_module_calls(_channel_tree()))
    unclassified = called - set(_WRITES_TWICE) - set(_WRITES_ONCE) - _ASKS_ONLY

    assert not unclassified, (
        f"the channel calls {sorted(unclassified)} and this file does not say whether they write "
        f"twice — a write that reports a residue must go through {_ONE_PATH}")


@pytest.mark.parametrize("method", sorted(_WRITES_TWICE))
def test_every_two_write_result_is_reported_through_the_ONE_path(method):
    """`close`, `align` and `defect` were given `_still_to_say`; `refine` was not, and its branch
    then denied and claimed the same comment in one sentence. Read off the file so a branch added
    later cannot be the next one left behind."""
    tree = _channel_tree()
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    calls = _module_calls(tree).get(method) or []

    assert calls, f"{method} writes twice and the channel never calls it"
    for call in calls:
        reached = _plainly_called(_reporting_block(tree, call))
        # one hop, because the reply may be composed by a `_…_reply` helper the branch hands it to
        indirect = {f for f in reached if f in functions and _ONE_PATH in _plainly_called(
            functions[f])}
        assert _ONE_PATH in reached or indirect, (
            f"the branch at line {call.lineno} reports {method} ({_WRITES_TWICE[method]}) without "
            f"{_ONE_PATH}: whatever it could not do is computed, logged for us, and never said")


def test_a_card_THE_BOARD_REFUSED_is_not_announced_as_being_in_Backlog():
    """DOOR ONE of the fifth branch. `_file_one` creates the issue and then places it; the board
    can refuse (no Backlog column, no card for the issue, no Status field, a failed `item-edit`),
    and that comes back as `ok` carrying the module's own sentence for the client.

    Every `ok` went into `landed` and only the FAILED results were ever read for a detail, so the
    client was told "Estão no Backlog — começar a trabalhar nelas continua sendo decisão de uma
    pessoa" about a card with no column at all: invisible to `readiness` and `propose_queue`, which
    match the column exactly and have no else-branch, so the role can never surface that work
    again. The sentence written for exactly this was computed, logged for us, and never said.
    """
    project = _Project()
    refused = _Result(ok=True, ref="#101",
                      detail="criado, mas o quadro recusou a colocação — o cartão está sem coluna "
                             "e o time foi avisado.")
    module = _Module(breaks=[refused])

    said = pc.handle(project, text="quebra o requisito 7 em tarefas", user="UADM", thread="C1",
                     channel="C1", module=module)

    assert module.broke_down == (7, "UADM"), "the gesture never reached the write"
    assert "recusou a colocação" in said, (
        f"the module wrote a sentence for the client and the channel dropped it: {said}")
    assert "no Backlog" not in said, (
        f"a card the board refused to place was announced as being in Backlog: {said}")


def test_a_card_that_ALREADY_EXISTED_is_not_announced_as_being_in_Backlog():
    """DOOR TWO, and the reason routing this reply through `_still_to_say` does not close it on its
    own: `_unfinished` deliberately answers "" for `existed`, because the replies that carry it
    lead with the fact themselves. Here nothing led with anything.

    `_file_one` returns EARLY when the tracker already answers for that title — the idempotency
    path, a retried conversation or a card filed in an earlier round — so `add_item` and
    `set_column` are never called. #404's column is whatever it already was: Done, In progress, or
    none. It was still announced as being in Backlog, by a turn that neither filed it nor moved it.
    """
    project = _Project()
    module = _Module(breaks=[_Result(ok=True, ref="#404", existed=True,
                                     detail="an issue titled 'Gerar o pacote' already exists")])

    said = pc.handle(project, text="quebra o requisito 7 em tarefas", user="UADM", thread="C1",
                     channel="C1", module=module)

    assert "no Backlog" not in said, (
        f"a card this turn never filed and never placed was announced as being in Backlog: {said}")
    assert "#404" in said and "já estava" in said, said
    # and never the tracker's own English explanation, which is written for us
    assert "already exists" not in said, said


def test_the_cards_that_DID_land_are_still_claimed_as_such():
    """The other side of both doors. A guard that only proves the retreat is indistinguishable from
    a reply that stopped saying anything — the happy path must keep its sentence, and a mixed batch
    must tell the three outcomes apart instead of collapsing them into the safest one."""
    project = _Project()
    module = _Module(breaks=[
        _Result(ok=True, ref="#101"),
        _Result(ok=True, ref="#404", existed=True, detail="an issue already exists"),
        _Result(ok=True, ref="#102", detail="criado, mas o quadro recusou a colocação."),
    ])

    said = pc.handle(project, text="quebra o requisito 7 em tarefas", user="UADM", thread="C1",
                     channel="C1", module=module)

    assert "#101 está no Backlog" in said, f"the card that landed lost its sentence: {said}"
    assert "#404 já existia" in said, said
    assert "Sobre #102" in said and "recusou a colocação" in said, said
    backlog = next(line for line in said.splitlines() if "no Backlog" in line)
    assert "#102" not in backlog and "#404" not in backlog, backlog


def test_a_breakdown_that_produced_NOTHING_announces_no_cards():
    """`file_issues` returns one result per draft, so no drafts is an empty list with no failure in
    it — and the count then read as zero cards successfully filed into Backlog."""
    said = pc.handle(_Project(), text="quebra o requisito 7 em tarefas", user="UADM", thread="C1",
                     channel="C1", module=_Module(breaks=[]))

    assert "Backlog" not in said, f"it announced a column for cards that do not exist: {said}"
    assert "0" not in said, said


def test_a_write_that_found_the_THING_ALREADY_THERE_says_so_ONCE():
    """The third meaning `detail` carries on a success, and the one the fix for the first two
    walked into. `file_defect` uses it for "I already have this" — a fact `defect_filed` already
    LEADS with — so the reply stated it twice, the second time in the slot reserved for something
    that went wrong. `existed` is the module's own word for it, and it is read here."""
    project = _Project()

    class _Filing(_Module):
        def file_defect(self, **_):
            return _Result(ok=True, ref="#77", existed=True,
                           detail="já registrei esse problema antes")

    pc.remember("C1", {"kind": "defect", "restated": "o relatório sai com o mês errado",
                       "reported_by": "<@UADM>", "channel": "C1"})

    said = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=_Filing())

    assert "Eu já tinha registrado" in said, said
    assert "já registrei esse problema antes" not in said, (
        f"the same fact was said twice, the second time as a caveat: {said}")


# ── 3b. the reason: promised in writing, and now actually written ──────────────────────────────

def test_the_success_line_claims_a_REASON_only_when_one_was_given():
    """The closing note holds who asked, and the reason only when somebody gave one — so the
    sentence that promised "quem decidiu **e por quê**" over "fechado a pedido de <@U…>." told the
    client about a record that did not exist. Whoever opened the card in six months found half of
    what they had been told was there."""
    project, module = _Project(), _Module()
    pc.handle(project, text="fecha o #511", user="UADM", thread="C1", channel="C1", module=module)
    bare = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)

    assert "por quê" not in bare, f"it promised a reason nobody gave: {bare}"

    project2, module2 = _Project(), _Module()
    pc.handle(project2, text="fecha o #511 porque o cliente desistiu do módulo", user="UADM",
              thread="C2", channel="C2", module=module2)
    given = pc.handle(project2, text="sim", user="UADM", thread="C2", channel="C2", module=module2)

    assert module2.closed_with[3] == "o cliente desistiu do módulo", module2.closed_with
    assert "por quê" in given, given


def test_the_reason_is_read_off_a_CONNECTIVE_and_shown_before_it_is_written():
    """Same discipline as the surviving card, for the same reason: this gesture is matched anywhere
    in a message, so taking the tail would write the next unrelated clause onto a client's card as
    the reason somebody decided. And what goes onto the card in their name is shown to the person
    who confirms it — a proposal is only a proposal for what it shows."""
    project, module = _Project(), _Module()

    ask = pc.handle(project, text="fecha o #511. Depois vamos falar do orçamento", user="UADM",
                    thread="C1", channel="C1", module=module)

    assert "orçamento" not in ask, f"an unrelated clause became the reason: {ask}"

    pc.forget("C1")
    shown = pc.handle(project, text="fecha o #511 porque o cliente desistiu", user="UADM",
                      thread="C1", channel="C1", module=module)

    assert "o cliente desistiu" in shown, shown


def test_a_survivor_named_without_a_hash_costs_a_QUESTION_and_never_a_write():
    """The two acts these texts exist to keep apart, one keystroke away from each other. "como
    duplicado do 288" says the work MOVED; dropping the second number closed the card with no
    pointer, under the wording for work being GIVEN UP — the opposite fact, confirmed by somebody
    who had said the first one. Ambiguity costs a question, and the question names the sentence
    that works."""
    project, module = _Project(), _Module()

    asked = pc.handle(project, text="fecha o #511 como duplicado do 288", user="UADM",
                      thread="C1", channel="C1", module=module)

    assert pc.pending_for("C1") is None, "it staged the other act on a guess"
    assert "#288" in asked and "#511" in asked, asked
    assert "Confirma?" not in asked, "a doubt was offered as a decision"

    quoted = re.search(r"fecha o #\d+ como duplicado do #\d+", asked)
    assert quoted, f"the question names no sentence to say: {asked}"
    matched = match_intent(quoted.group(0))
    assert matched and matched[0] == "close", matched
    assert matched[1].get("in_favour_of") == "288", matched


@pytest.mark.parametrize("phrase", [
    "fecha o #511 (duplicado do #288)",
    "encerra o #511, o #288 já cobre isso",
    "fecha o #511 porque já está coberto pelo #288",
])
def test_a_SECOND_CARD_NAMED_is_never_dropped_in_silence(phrase):
    """THE GUARD WAS KEYED ON THE CONNECTIVE AND THE FACT IS THE SECOND CARD. A survivor was read
    only through a listed word close enough to the number, so a parenthesis, an unlisted verb and
    three words of distance each threw #288 away — and closing with no survivor is the OTHER act:
    #511 goes under the wording for work being given up, and nothing on #288 says it absorbed
    anything. Meanwhile the strictly weaker signal, a bare number after a recognised connective,
    correctly cost a question. The clearer sentence bought the worse outcome.

    Driven through the handler: what must not happen is a staged close that has forgotten #288.
    Either it reads the relation or it asks — never silence.
    """
    project, module = _Project(), _Module()

    said = pc.handle(project, text=phrase, user="UADM", thread="C1", channel="C1", module=module)

    staged = pc.pending_for("C1")
    if staged is None:
        assert "#288" in said and "#511" in said, f"#288 vanished from the question: {said}"
        assert "Confirma?" not in said, "a doubt was offered as a decision"
    else:
        assert staged.get("in_favour_of") == "288", (
            f"a close was staged with no survivor from a sentence that named one: {staged}")


def test_a_PARENTHESISED_duplicate_is_read_as_the_relation_it_states():
    """The stronger half of the rule above. A question is the safe answer to a doubt, and this is
    not one: the connective is there, the relation is stated, and only a bracket stood between them
    — so the clearest way a person can write it must not be the one that costs an extra round."""
    project, module = _Project(), _Module()

    pc.handle(project, text="fecha o #511 (duplicado do #288)", user="UADM", thread="C1",
              channel="C1", module=module)

    staged = pc.pending_for("C1")
    assert staged is not None and staged.get("in_favour_of") == "288", staged


def test_a_CARD_named_in_passing_still_reads_as_a_plain_closure():
    """The other side, and the reason this asks about a CARD rather than about a number: "fecha o
    #511, já falamos disso na semana 32" names no second card, so nothing is doubtful and the
    ordinary closure must not start costing a question."""
    project, module = _Project(), _Module()

    pc.handle(project, text="fecha o #511, já falamos disso na semana 32", user="UADM",
              thread="C1", channel="C1", module=module)

    staged = pc.pending_for("C1")
    assert staged is not None and staged.get("in_favour_of") is None, staged


def test_A_PLANNING_SENTENCE_REACHES_NO_WRITE_THROUGH_THE_HANDLER():
    """Through the production path, because the harm is not a wrong label: `breakdown` is one of
    the two gestures with nothing between the match and the act. The sentence is somebody saying
    what the team will do tomorrow, and it called `break_down` — a model pass and eight tickets on
    the client's board, spent by a message that asked for nothing.

    Both directions in one test: the plan writes nothing, and the order still does. A guard that
    only proves the first is indistinguishable from a pattern somebody broke.
    """
    project, module = _Project(), _Module()

    pc.handle(project, text="amanhã a gente quebra o requisito 8 em tarefas", user="UADM",
              thread="C1", channel="C1", module=module)

    assert module.broke_down is None, "a sentence about tomorrow filed work today"
    assert pc.pending_for("C1") is None

    pc.handle(project, text="quebra o requisito 8 em tarefas", user="UADM", thread="C1",
              channel="C1", module=module)

    assert module.broke_down == (8, "UADM"), "the real instruction stopped working"


def test_a_confirmed_write_says_something_BEFORE_the_slow_part():
    """A yes is always the slow path — a checkout, the client's board, an agent. `align` runs two
    checkouts and a model call before it returns, and the branch said nothing at all until it did:
    the person confirmed an irreversible change to what gets built and heard silence for minutes.
    Sent once, from the one place every confirmed write passes through, rather than by six branches
    each remembering to."""
    project, module = _Project(), _Module(_Req(6, "accepted"))
    said: list[str] = []
    pc.handle(project, text="alinha o #288 ao requisito 6", user="UADM", thread="C1",
              channel="C1", module=module, notify=said.append)
    said.clear()

    pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module,
              notify=said.append)

    assert said, "the person confirmed an irreversible act and heard nothing until it finished"


def test_a_confirmation_BY_CLICK_is_acknowledged_too():
    """The affordance we built for people who would rather not type gave them strictly less: the
    click path could not send a receipt at all."""
    project, module = _Project(), _Module(_Req(6, "accepted"))
    pc.handle(project, text="alinha o #288 ao requisito 6", user="UADM", thread="C1",
              channel="C1", module=module)
    token = pc.proposal_token("C1", pc.pending_for("C1"))
    said: list[str] = []

    pc.confirm_by_click(project, token=token, approved=True, user="UADM", module=module,
                        notify=said.append)

    assert module.aligned_with == ("288", 6, "UADM"), module.aligned_with
    assert said, "a click confirmed an irreversible act in silence"


# ── 4. the fingerprint: which staged act a button is allowed to perform ────────────────────────

def test_two_closures_of_one_card_in_favour_of_DIFFERENT_cards_never_share_a_button():
    """The card that survives is half the decision. Without it in the fingerprint, a button posted
    for "close #511 into #288" would perform "close #511 into #300" — and the closing comment
    would name #300 in the client's own words."""
    into_288 = pc.proposal_token("C1", {"kind": "close", "number": 511, "in_favour_of": 288})
    into_300 = pc.proposal_token("C1", {"kind": "close", "number": 511, "in_favour_of": 300})

    assert into_288 != into_300


def test_two_alignments_of_one_card_to_DIFFERENT_requirements_never_share_a_button():
    to_4 = pc.proposal_token("C1", {"kind": "align", "number": 288, "requirement": 4})
    to_6 = pc.proposal_token("C1", {"kind": "align", "number": 288, "requirement": 6})

    assert to_4 != to_6


def test_every_staged_act_on_the_same_number_is_a_different_button():
    """Closing a card, dropping a requirement and accepting one are unrelated acts that happen to
    share a number. A stale button for any of them must never perform another."""
    tokens = {pc.proposal_token("C1", {"kind": kind, "number": 288})
              for kind in ("close", "align", "drop", "accept", "fact")}

    assert len(tokens) == 5, tokens


# ── 5. aligning: the act that changes what gets BUILT ──────────────────────────────────────────

def test_the_whole_alignment_gesture_reaches_the_write_through_the_channel():
    project, module = _Project(), _Module(_Req(6, "accepted"))

    ask = pc.handle(project, text="alinha o #288 ao requisito 6", user="UADM", thread="C1",
                    channel="C1", module=module)

    assert "#288" in ask and "requisito 6" in ask and "Confirma?" in ask, ask
    assert module.aligned_with is None, "it rewrote the card before anybody confirmed"

    done = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)

    assert module.aligned_with == ("288", 6, "UADM"), module.aligned_with
    assert "#288" in done and "requisito 6" in done, done


def test_aligning_to_a_REPLACED_requirement_is_refused_and_points_at_the_successor():
    """This is the damage the act exists to undo, arriving from the other direction: thirteen open
    cards already execute REQ-0004 because it was replaced and nobody re-pointed them. Writing a
    fourteenth from the same retired text would be the platform committing the defect on purpose."""
    project = _Project()
    module = _Module(corpus=[_Req(4, "superseded", superseded_by=6), _Req(6, "accepted")])

    reply = pc.handle(project, text="alinha o #288 ao requisito 4", user="UADM", thread="C1",
                      channel="C1", module=module)

    assert "6" in reply and "substituído" in reply, reply
    assert pc.pending_for("C1") is None, "it staged a write against a retired text"


def test_the_refusal_names_the_END_of_the_chain_and_not_the_next_link():
    """0002 → 0004 → 0006, the shape the corpus really has. Naming 0004 hands the person an
    instruction that walks them into this very refusal one number along, pointing at another
    retired text — the platform performing, as advice, the defect this act exists to undo."""
    project = _Project()
    module = _Module(corpus=[_Req(2, "superseded", superseded_by=4),
                             _Req(4, "superseded", superseded_by=6),
                             _Req(6, "accepted")])

    reply = pc.handle(project, text="alinha o #288 ao requisito 2", user="UADM", thread="C1",
                      channel="C1", module=module)

    quoted = re.search(r"alinh[ae] o #\d+ ao requisito (\d+)", reply)
    assert quoted, reply
    assert quoted.group(1) == "6", f"the refusal points at a retired requirement: {reply}"

    followed = pc.handle(project, text=quoted.group(0), user="UADM", thread="C1", channel="C1",
                         module=module)
    assert "Confirma?" in followed, f"following the instruction hit another refusal: {followed}"


def test_a_supersession_that_leads_NOWHERE_is_said_plainly_rather_than_called_abandoned():
    """A retired requirement whose replacement is not in the base is our inconsistency. Both other
    answers are lies about it: one sends the person to a number nobody can open, the other tells
    them the work was abandoned when somebody decided the opposite."""
    project, module = _Project(), _Module(corpus=[_Req(4, "superseded", superseded_by=6)])

    reply = pc.handle(project, text="alinha o #288 ao requisito 4", user="UADM", thread="C1",
                      channel="C1", module=module)

    assert "substituído" in reply, reply
    assert "abandonado" not in reply, reply
    assert pc.pending_for("C1") is None


def test_a_requirement_nobody_wrote_is_said_plainly_rather_than_staged():
    project, module = _Project(), _Module(_Req(6))

    reply = pc.handle(project, text="alinha o #288 ao requisito 9", user="UADM", thread="C1",
                      channel="C1", module=module)

    assert "não encontrei o requisito 9" in reply, reply
    assert pc.pending_for("C1") is None


@pytest.mark.parametrize("gesture", ["alinha o #288 ao requisito 6", "aceita o requisito 6",
                                     "cancela o requisito 6"])
def test_an_UNREADABLE_BASE_is_never_reported_as_a_requirement_that_does_not_exist(gesture):
    """A DEFINITIVE FALSE STATEMENT, and the honest one was computed six lines further down and
    never reached. Loading the documentation base never raises — it hands back a context that is
    `available=False` carrying an EMPTY corpus — so on an outage `by_number` answers None for every
    number, and all three gestures told the client the requirement is not written in their base.

    `_handle`'s `ctx.available` gate is only reached when the intent dispatcher returns nothing,
    and each of these returns a sentence. So the gate existed, one screen below, and none of the
    three could ever reach it. The three say the same thing, which is why one wrong sentence became
    three: they were unified before they were correct.
    """
    project, module = _Project(), _Module(_Req(6, "accepted"), available=False)

    reply = pc.handle(project, text=gesture, user="UADM", thread="C1", channel="C1", module=module)

    assert "não encontrei o requisito" not in reply, (
        f"an unreadable base was reported as a requirement that does not exist: {reply}")
    assert "não estou conseguindo enxergar" in reply.lower(), reply
    assert pc.pending_for("C1") is None, "it staged an act over a base it could not read"


@pytest.mark.parametrize("status", sorted(_KNOWN_STATUS))
def test_align_asks_for_a_confirmation_ONLY_where_the_module_would_write(status):
    """THE GATE THE CHANNEL CHECKS IS THE ONE THE MODULE ENFORCES. `align_card` writes only from a
    PROMISE; this branch admitted anything still live, so a proposed requirement bought a "this
    changes what gets built — Confirma?" from a person, displaced whatever else was awaiting
    confirmation in the thread, and was then refused one call deeper by a gate that had never
    moved. A confirmation asked for an act that cannot happen spends the only thing this surface
    ever asks of a human.

    Parametrised over every status the corpus knows, read from the corpus: a lifecycle state added
    later is covered on the day it is added rather than on the day somebody remembers this file.
    """
    project, module = _Project(), _Module(_Req(6, status))

    reply = pc.handle(project, text="alinha o #288 ao requisito 6", user="UADM", thread="C1",
                      channel="C1", module=module)

    staged = pc.pending_for("C1") is not None
    assert staged is _Req(6, status).is_promise, (
        f"a {status} requirement {'was staged' if staged else 'was refused'}: {reply}")


def test_the_refusal_for_an_UNAGREED_requirement_is_the_MODULE_S_OWN_SENTENCE():
    """`_not_a_promise` is what `align_card` and `break_down` both answer with, and it separates a
    proposal ("confirm it and I'll go") from a reading of the code ("this was never a promise").
    A second sentence written here would be a person told two different things about one rule,
    which teaches them the rule is arbitrary."""
    from openfactory.product.module import _not_a_promise

    project = _Project()
    req = _Req(7, "proposed")

    reply = pc.handle(project, text="alinha o #288 ao requisito 7", user="UADM", thread="C1",
                      channel="C1", module=_Module(req))

    assert _not_a_promise(7, req) in reply, reply


def test_a_replacement_NOBODY_HAS_AGREED_TO_YET_is_not_reported_as_a_BROKEN_BASE(caplog):
    """`propose_requirement` retires the predecessor in the SAME commit that writes the
    replacement as a proposal, so between that commit and somebody's yes every alignment onto the
    old number lands here — the commonest shape there is.

    Read as a broken chain it produced two harms at once: the client was told our base points at a
    text nobody can open, about a requirement that reads perfectly well, and an operator alarm
    fired with nothing behind it — a bug report somebody chases and finds nothing. The truth is
    that the alignment is one confirmation away, and the message says which one, in sentences this
    surface matches.
    """
    project = _Project()
    module = _Module(corpus=[_Req(4, "superseded", superseded_by=6), _Req(6, "proposed")])

    with caplog.at_level(logging.WARNING):
        reply = pc.handle(project, text="alinha o #288 ao requisito 4", user="UADM", thread="C1",
                          channel="C1", module=module)

    assert "OPENFACTORY_PRODUCT_CHAIN_BROKEN" not in caplog.text, "a readable corpus raised an alarm"
    assert "não consegui achar" not in reply, f"a readable text was called unreadable: {reply}"
    assert "requisito 6" in reply, reply
    assert pc.pending_for("C1") is None, "it staged a write the module would refuse"

    steps = re.findall(r"«([^»]+)»", reply)
    assert [match_intent(s) and match_intent(s)[0] for s in steps] == ["accept", "align"], steps


def test_a_replacement_THE_CLIENT_KILLED_is_never_offered_as_one_confirmation_away(caplog):
    """The other end of the same walk. `_replacement` answers which requirement the chain NAMES,
    whatever became of it, and the branch read that as "a text waiting for a yes" — so REQ-0004
    superseded by a REQ-0006 the client had DROPPED came back as "o 6 ainda não foi acordado …
    me diga «aceita o requisito 6»".

    That instruction is the harm, not the wording: `accept` refuses only what is already agreed, so
    the yes it invites would write a text the client decided against back into force as a promise
    the factory defends. Nothing here is one confirmation away, and the reply must not pretend it
    is — nor call a readable base broken, which is the other wrong answer one line down.
    """
    project = _Project()
    module = _Module(corpus=[_Req(4, "superseded", superseded_by=6), _Req(6, "dropped")])

    with caplog.at_level(logging.WARNING):
        reply = pc.handle(project, text="alinha o #288 ao requisito 4", user="UADM", thread="C1",
                          channel="C1", module=module)

    assert "ainda não foi acordado" not in reply, (
        f"a requirement the client cancelled is described as pending a yes: {reply}")
    assert re.findall(r"«([^»]+)»", reply) == [], (
        f"it tells the client to type something that would reinstate a dropped text: {reply}")
    assert "OPENFACTORY_PRODUCT_CHAIN_BROKEN" not in caplog.text, "a readable corpus raised an alarm"
    assert "requisito 6" in reply and "já não vale" in reply, reply
    assert pc.pending_for("C1") is None, "it staged a write the module would refuse"


def test_a_RETIRED_requirement_is_never_staged_for_acceptance():
    """Where that instruction used to lead. This branch compared a raw status to "accepted" while
    the module's own question is `is_promise`, and it never asked `is_live` at all — the flag
    `drop` reads one branch below. So a superseded or dropped requirement bought a confirmation
    from a person, and `module.accept` refuses only what is ALREADY agreed: the yes would have put
    a retired text back into force."""
    project = _Project()

    for status in ("superseded", "dropped"):
        module = _Module(_Req(6, status, superseded_by=8 if status == "superseded" else None))

        said = pc.handle(project, text="aceita o requisito 6", user="UADM", thread="C1",
                         channel="C1", module=module)

        assert pc.pending_for("C1") is None, f"a {status} requirement was staged for acceptance"
        assert "já não vale" in said, said
        assert "Confirma?" not in said, said


def test_the_two_readings_of_a_SUPERSESSION_CHAIN_agree():
    """Two walks of one chain is how the two come to disagree — the reason `_successor` was
    borrowed rather than re-implemented. `_replacement` answers a different question ("is there a
    text at all"), and where both answer they must give the same node."""
    from openfactory.product.module import _successor

    corpus = _Module(corpus=[_Req(2, "superseded", superseded_by=4),
                             _Req(4, "superseded", superseded_by=6),
                             _Req(6, "accepted")]).context().corpus

    for number in (2, 4):
        promise = _successor(corpus, number)
        replacement = pc._replacement(corpus, number)
        assert promise == replacement.number, (number, promise, replacement)


def test_an_unauthorised_yes_neither_aligns_nor_consumes_the_proposal():
    project, module = _Project(admins=["UADM"]), _Module(_Req(6))
    pc.handle(project, text="alinha o #288 ao requisito 6", user="UADM", thread="C1",
              channel="C1", module=module)

    pc.handle(project, text="sim", user="USTRANGER", thread="C1", channel="C1", module=module)

    assert module.aligned_with is None
    assert pc.pending_for("C1") is not None


# ── 6. a refusal that points somewhere, and the pointer is EXECUTABLE ──────────────────────────

def test_the_refine_refusal_names_the_other_act():
    """It stays a refusal — amending criteria somebody may already be working from is a different
    risk from writing where there was nothing. What changed is that it no longer ends nowhere."""
    from openfactory.product.authoring import WriteResult

    # the language is NAMED: this guard asserts the Portuguese refusal, and the platform's
    # default became English in 2026-08-14
    said = pc._refine_reply(WriteResult(ok=True, ref="#516", existed=True, detail="x"), 516,
                            "Nina", lang="pt-BR")

    assert "já dizia quando estaria pronto" in said, said
    assert "alinha" in said.lower(), "the refusal still leaves the person at a dead end"


#: The token `refine_refused` writes where the person has to supply a number. It cannot know which
#: requirement applies to the card, so its instruction is a SHAPE — and a shape has to be declared
#: as one, here, rather than patched away inside the assertion.
_PLACEHOLDER = "N"


@pytest.mark.parametrize(("text", "card", "placeholder"), [
    (refine_refused(number=516, language="pt-BR"), 516, _PLACEHOLDER),
    (align_refused(number=288, requirement=4, successor=6, language="pt-BR"), 288, ""),
])
def test_the_sentence_a_refusal_TELLS_YOU_TO_SAY_is_one_this_surface_matches(text, card,
                                                                            placeholder):
    """THE ASSERTION THIS FILE EXISTS FOR, generalised. A refusal that names an act nobody
    implemented is precisely what it is replacing: Nina told a client a request had been recorded
    by an operation that did not exist. So the instruction is lifted out of the message verbatim
    and run back through the matcher.

    VERBATIM IS THE WHOLE POINT, and it was not. The instruction used to be rewritten — "requisito
    N" swapped for "requisito 6" — before it was matched, so the one sentence this file exists to
    prove executable was the one asserted against a string the channel never emits. A refusal that
    names a shape must SAY it is a shape: the placeholder is declared per row, the substitution is
    the only edit allowed, and the row that carries a real number is matched untouched.

    QUOTATION IS PART OF THE SENTENCE, and stripping it is how this test used to pass over the
    defect it was written for. The message shows «alinha o #288 ao requisito 6»; the clause anchor
    rejected a leading «, so the client who copied what they were shown matched nothing — while
    this test lifted the instruction from the verb onward and removed the very characters they see.
    """
    quoted = re.search(r"«\s*alinh[ae] o #\d+ ao requisito [^»]+»", text, re.IGNORECASE)
    assert quoted, f"the refusal names no sentence to say: {text}"

    instruction = quoted.group(0)
    if placeholder:
        assert instruction.endswith(f"requisito {placeholder}»"), (
            f"the placeholder moved and the substitution below is now a rewrite: {instruction!r}")
        instruction = instruction.replace(f"requisito {placeholder}»", "requisito 6»")
    else:
        assert re.search(r"requisito \d+»$", instruction), (
            f"a refusal that knows the number must quote it: {instruction!r}")

    matched = match_intent(instruction)

    assert matched and matched[0] == "align", f"{instruction!r} -> {matched}"
    assert matched[1]["number"] == str(card), matched


# ── 7. what the client reads ───────────────────────────────────────────────────────────────────

#: The one piece of free text a CLIENT supplies to these messages. It comes back quoted in «…», the
#: same way an instruction is, and it is the only quoted span that is not something to type — so it
#: is written once here and read by both the sentence and the walk below, which cannot then drift.
_A_CLIENTS_OWN_WORDS = "o cliente desistiu"


def _every_new_sentence() -> list[str]:
    return [
        close_confirmation(number=511, language="pt-BR"),
        close_confirmation(number=511, in_favour_of=288, language="pt-BR"),
        close_confirmation(number=511, reason=_A_CLIENTS_OWN_WORDS, language="pt-BR"),
        card_closed(number=511, language="pt-BR", agent_name="Nina"),
        card_closed(number=511, reasoned=True, language="pt-BR", agent_name="Nina"),
        card_closed(number=511, in_favour_of=288, language="pt-BR", agent_name="Nina"),
        card_closed(number=511, in_favour_of=288, linked=False, language="pt-BR",
                    agent_name="Nina"),
        survivor_unclear(number=511, other=288, language="pt-BR"),
        align_confirmation(number=288, requirement=6, title="Aviso acionável", language="pt-BR"),
        card_aligned(number=288, requirement=6, language="pt-BR", agent_name="Nina"),
        card_aligned(number=288, requirement=6, noted=False, language="pt-BR", agent_name="Nina"),
        align_refused(number=288, requirement=4, successor=6, language="pt-BR"),
        align_refused(number=288, requirement=5, language="pt-BR"),
        align_refused(number=288, requirement=4, replaced=True, language="pt-BR"),
        align_to_unagreed(number=288, requirement=4, successor=6, language="pt-BR"),
        align_to_dropped_replacement(number=288, requirement=4, successor=6, language="pt-BR"),
        refine_refused(number=516, language="pt-BR"),
        criteria_written(number=412, measure="3 critérios", language="pt-BR"),
        criteria_written(number=412, noted=False, language="pt-BR"),
    ]


def test_every_sentence_a_message_TELLS_THE_CLIENT_TO_TYPE_is_matched_AS_SHOWN():
    """Every refusal that names the sentence that works quotes it in «…», and the clause anchor
    rejected a leading « — so a client who copied the instruction exactly as they had been shown it
    matched NOTHING and fell through to the conversational model, the path that has already minted
    a requirement nobody asked for. The one sentence this surface asks a person to type was the one
    it could not read.

    Derived from the messages themselves rather than from a list beside them, and lifted WITH the
    quotation: a sentence added to any of these texts is covered on the day it is written.
    """
    shown = [q for text in _every_new_sentence() for q in re.findall(r"«[^»]*»", text)
             if q.strip("«»") != _A_CLIENTS_OWN_WORDS]
    assert shown, "no message quotes a sentence to say — this test would prove nothing"

    for quoted in shown:
        # the ONE edit allowed, and it is declared: `refine_refused` cannot know which requirement
        # applies to the card, so its instruction is a shape
        typed = quoted.replace(f"requisito {_PLACEHOLDER}»", "requisito 6»")
        matched = match_intent(typed)

        assert matched, f"the client is told to type {quoted!r} and this surface matches nothing"
        assert matched[0] == match_intent(typed.strip("«»"))[0], (
            f"the quotation marks changed what {quoted!r} means")


def test_a_QUOTED_gesture_never_carries_its_QUOTATION_into_a_record():
    """The other half of admitting «…» where a clause begins. A capture is free text that travels
    onward: `drop`'s reason is written into the record in the client's name and read back to them,
    so a stray » must not end up as the grounds on which somebody decided to retire a promise."""
    assert match_intent("«cancela o requisito 2»") == ("drop", {"number": "2"})

    matched = match_intent("«cancela o requisito 2 porque mudou a lei»")

    assert matched[1]["reason"] == "porque mudou a lei", matched


@pytest.mark.parametrize("text", _every_new_sentence(), ids=range(len(_every_new_sentence())))
def test_no_machinery_reaches_the_client(text):
    assert jargon_in(text) == [], text
    for field in ("status", "superseded", "in_favour_of", "acceptance criteria"):
        assert field not in text.lower(), f"a field name reached the client: {text}"


def test_closing_a_DUPLICATE_never_reads_like_closing_something_abandoned():
    """One says the work moved, the other says it will not be done. Two facts, two sentences —
    the class this codebase has paid for four times."""
    alone = close_confirmation(number=511, language="pt-BR")
    duplicate = close_confirmation(number=511, in_favour_of=288, language="pt-BR")

    assert alone != duplicate
    assert "#288" in duplicate and "#288" not in alone
    assert "não está sendo cancelado" in duplicate, (
        "closing a duplicate reads as giving the work up")


def test_closing_a_CARD_never_reads_like_dropping_a_REQUIREMENT():
    """They are one sentence apart in a chat window and opposite in weight. A person who confirms
    the wrong one of these has not made a small mistake: dropping a requirement takes back what
    the factory defends."""
    card = close_confirmation(number=511, in_favour_of=288, language="pt-BR")
    promise = drop_confirmation(number=6, title="Aviso acionável", was_a_promise=True,
                                language="pt-BR")

    assert "defeito" not in card, "closing a card claims to change what the product promises"
    assert "promete" in card or "acordado" in card, (
        "closing a card does not say that the promises are untouched")
    assert "defende" in promise and "defende" not in card


def test_aligning_says_what_changes_and_that_nothing_starts_because_of_it():
    """The only act on this surface that changes WHAT GETS BUILT without spending anything yet.
    Both halves have to be said, or a person confirms either a formatting tidy-up or a build."""
    text = align_confirmation(number=288, requirement=6, title="Aviso acionável", language="pt-BR")

    assert "o que vai ser construído" in text, "it reads like a wording fix"
    assert "Nada começa" in text, "nobody is told that confirming this starts no work"
    assert "requisito 6" in text and "#288" in text


@pytest.mark.parametrize(("fn", "kw"), [
    (card_closed, {"number": 511}),
    (card_closed, {"number": 511, "reasoned": True}),
    (card_closed, {"number": 511, "in_favour_of": 288}),
    (card_closed, {"number": 511, "in_favour_of": 288, "linked": False}),
    (card_aligned, {"number": 288, "requirement": 6}),
    (card_aligned, {"number": 288, "requirement": 6, "noted": False}),
    (criteria_written, {"number": 412, "measure": "3 critérios"}),
    (criteria_written, {"number": 412, "noted": False}),
])
def test_every_new_success_sentence_is_visible_to_the_false_claim_detector(fn, kw):
    """Derived from the real phrases, like the sentences before them. The detector's worst blind
    spot has always been the platform's OWN confirmation vocabulary echoed back by the agent — the
    first version could not see "Anotado", the word `fact_noted` uses.

    THE WORD THE SENTENCE LEADS WITH, not "some claim somewhere in it". Both of these end with a
    second, older claim verb ("escrevi", "registrado"), so a detector blind to "encerrado" and
    "alinhado" would still fire and look covered — while the agent echoing only the headline
    ("Encerrado o #511") passed straight through it.
    """
    text = fn(language="pt-BR", **kw)
    leads_with = text.split()[0].strip(":.,*").lower()

    assert claims_a_write(text).lower() == leads_with, (
        f"{fn.__name__} announces a write with {leads_with!r} and the detector cannot see it")


# ── 8. the two landmines this surface has already paid for ─────────────────────────────────────

def _run_intent_body() -> ast.FunctionDef:
    tree = ast.parse(Path("openfactory/product/channel.py").read_text())
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_run_intent")


def _intent_branches() -> dict[str, ast.If]:
    """`intent name -> the branch that carries it out`, read off the dispatcher.

    What a gesture COSTS when it is matched wrongly is decided here, in the handler, and the
    matcher has to know it. Reading it rather than restating it is what keeps the two from drifting
    apart while both look right."""
    return {node.test.comparators[0].value: node
            for node in _run_intent_body().body
            if isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
            and getattr(node.test.left, "id", "") == "intent"
            and isinstance(node.test.comparators[0], ast.Constant)}


def test_may_act_is_imported_ONCE_at_the_top_of_the_intent_dispatcher():
    """Importing it inside a branch makes it a function-local name for the WHOLE function, so the
    next branch added above that line raises UnboundLocalError on its authorisation check — which
    the client reads as "algo quebrou do meu lado". Two branches were added above it here."""
    fn = _run_intent_body()
    imports = [n for n in ast.walk(fn)
               if isinstance(n, ast.ImportFrom) and any(a.name == "may_act" for a in n.names)]

    assert len(imports) == 1, f"may_act is imported {len(imports)} times inside _run_intent"
    assert imports[0] in fn.body, "may_act is imported inside a branch — a landmine for the next one"


@pytest.mark.parametrize("method", ["close_card", "align_card"])
def test_the_channel_actually_calls_the_module(method):
    """This repository's signature defect, fourteen times over: a capability that exists, passes
    its tests and is reached by nothing in production."""
    tree = _channel_tree()

    assert any(isinstance(n, ast.Call) and getattr(n.func, "attr", None) == method
               for n in ast.walk(tree)), f"{method} is written and reached by nothing"
