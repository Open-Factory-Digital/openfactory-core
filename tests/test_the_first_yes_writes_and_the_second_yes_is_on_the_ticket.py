"""The first yes writes the requirement; the second yes is given on the ticket (ADR-0047).

THE PRODUCT OWNER'S DECISION, 2026-09-06: the draft of a requirement and the official ticket
written from it are two different things; the requester confirms both; and once confirmed, the
acceptance appears on the ticket, in the requester's name. What this file holds:

  1. the card opened from a `proposed` requirement says on its face whose acceptance it awaits;
     `open_cards_for` files it for a live requirement and refuses one that is off the table, while
     `break_down` keeps refusing a proposal (filing work from one commits nobody);
  2. the acceptance is stamped on the card: who, when, from where — and for whom, when the person
     who said yes is not the one who asked; an outsider is refused;
  3. the conversation: a yes on the draft writes the requirement, opens the card and STAGES the
     second yes under the same key; the second yes accepts, stamps the cards and does not break the
     requirement down again; an acceptance that reaches the executor with no cards (the panel's, an
     older requirement) still gets the breakdown, so no path is left with an agreement and no work;
  4. the write itself — direct to the base, the review request only when the base refuses — is
     pinned in `test_product_authoring.py`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from test_product_module import _TWO_ISSUES, ADMIN, OUTSIDER, _ctx, _Harness, _project

from openfactory.product import confirm as pc_confirm
from openfactory.product.authoring import WriteResult, issue_body
from openfactory.product.corpus import Corpus, Requirement
from openfactory.product.module import ProductModule, awaiting_of
from openfactory.product.role import IssueDraft
from openfactory.product.staging import pending_for, remember

# ── 1. the card before the promise ───────────────────────────────────────────────────────────


def _proposed(number: int = 4) -> Requirement:
    return Requirement(number=number, slug="x", path="requirements/0004-x.md",
                       title="Review queue", status="proposed", asked_by="<@U0PO>")


def test_a_card_opened_from_a_proposal_says_whose_acceptance_it_awaits():
    draft = IssueDraft(title="t", objective="o", acceptance_criteria=["c"], cites=4)
    body = issue_body(draft, requirement_path="requirements/0004-x.md", docs_repo="o/docs",
                      awaiting="<@U0PO>")
    assert "## Acceptance" in body and "Awaiting the acceptance of <@U0PO>" in body
    assert "not a promise" in body
    plain = issue_body(draft, requirement_path="p", docs_repo="o/docs")
    assert "Awaiting the acceptance" not in plain, "a promise's card awaits nobody"


def test_awaiting_is_the_requester_and_nobody_once_it_is_a_promise():
    assert awaiting_of(_proposed()) == "<@U0PO>"
    assert awaiting_of(Requirement(number=1, slug="x", path="p", status="accepted")) == ""
    assert awaiting_of(Requirement(number=1, slug="x", path="p", status="proposed")) == "the requester"


class _Tracker:
    def __init__(self, explode=False):
        self.created: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []
        self.explode = explode

    def find_ticket(self, *, title):
        return None

    def create_ticket(self, *, title, body):
        self.created.append((title, body))
        return f"#{500 + len(self.created)}"

    def comment(self, ref, body):
        if self.explode:
            raise RuntimeError("the tracker said no")
        self.comments.append((ref, body))


def _module_with(tmp_path, requirement: Requirement) -> ProductModule:
    corpus = Corpus(requirements=[requirement])
    return ProductModule(_project(), context=_ctx(tmp_path, corpus=corpus),
                         agent=_Harness(_TWO_ISSUES))


def test_open_cards_for_files_the_official_cards_of_a_proposal_saying_what_they_await(tmp_path):
    mod = _module_with(tmp_path, _proposed())
    tracker = _Tracker()

    results = mod.open_cards_for(4, actor=ADMIN, tracker=tracker, board=None)

    assert results and all(r.ok for r in results), results
    assert tracker.created, "no card was opened"
    for _title, body in tracker.created:
        assert "Awaiting the acceptance of <@U0PO>" in body, body
        assert "REQ-0004" in body


def test_break_down_still_refuses_a_proposal_and_open_cards_refuses_what_is_off_the_table(
        tmp_path):
    mod = _module_with(tmp_path, _proposed())
    (refused,) = mod.break_down(4, actor=ADMIN, board=None)
    assert refused.ok is False, "filing work from a proposal commits nobody — that stays refused"

    dropped = Requirement(number=5, slug="y", path="requirements/0005-y.md", status="dropped")
    (nothing,) = _module_with(tmp_path, dropped).open_cards_for(5, actor=ADMIN,
                                                                tracker=_Tracker(), board=None)
    assert nothing.ok is False and "não vale" in nothing.detail


# ── 2. the acceptance on the card ────────────────────────────────────────────────────────────


def test_the_acceptance_is_stamped_on_every_card_with_who_when_and_where(tmp_path):
    mod = _module_with(tmp_path, _proposed())
    tracker = _Tracker()

    results = mod.stamp_acceptance(4, ["#501", "#502"], actor=ADMIN, requester=ADMIN,
                                   where="conversa com o time de produto", tracker=tracker,
                                   today="2026-09-06")

    assert [r.ok for r in results] == [True, True]
    assert [ref for ref, _ in tracker.comments] == ["#501", "#502"]
    text = tracker.comments[0][1]
    assert f"<@{ADMIN}>" in text and "2026-09-06" in text and "conversa com o time" in text
    assert "em nome de" not in text, "the requester accepted for themselves"


def test_an_acceptance_by_somebody_else_says_on_whose_behalf(tmp_path):
    """Only where the deployment allows it (ADR-0047 §4, `product.accept_on_behalf`) — the
    default refuses, and `test_the_second_yes_is_the_requesters` pins that side."""
    corpus = Corpus(requirements=[_proposed()])
    mod = ProductModule(_project(product={"docs_repo": "acmecorp/acme-books-documentation",
                                          "slack_admins": [ADMIN], "accept_on_behalf": True}),
                        context=_ctx(tmp_path, corpus=corpus), agent=_Harness(_TWO_ISSUES))
    tracker = _Tracker()

    mod.stamp_acceptance(4, ["#501"], actor=ADMIN, requester="U0PO", where="", tracker=tracker,
                         today="2026-09-06")

    assert "em nome de <@U0PO>" in tracker.comments[0][1]


def test_an_outsider_cannot_stamp_and_a_refusing_tracker_is_said_per_card(tmp_path):
    mod = _module_with(tmp_path, _proposed())
    (refused,) = mod.stamp_acceptance(4, ["#501"], actor=OUTSIDER, tracker=_Tracker())
    assert refused.ok is False

    (failed,) = mod.stamp_acceptance(4, ["#501"], actor=ADMIN, tracker=_Tracker(explode=True))
    assert failed.ok is False and failed.ref == "#501"


# ── 3. the conversation: two yeses ───────────────────────────────────────────────────────────


class _Product:
    enabled = True
    slack_channel = "C1"
    agent_name = "Nina"
    channel_id = "C1"

    def __init__(self, admins):
        self.admins = admins


class _Project:
    name = "books"
    language = "pt-BR"

    def __init__(self, admins=("UADM",)):
        self.product = _Product(list(admins))


class _Module:
    """Records the acts; answers like the real module does."""

    def __init__(self, *, cards=("#41",)):
        self.cards = list(cards)
        self.stamped: list[tuple] = []
        self.broke_down: list[int] = []

    def propose(self, answer, *, actor, asked_by="", date="", source=""):
        return WriteResult(ok=True, merged=True, number=7, url="")

    def open_cards_for(self, number, *, actor):
        return [WriteResult(ok=True, ref=ref) for ref in self.cards]

    def accept(self, number, *, actor):
        return WriteResult(ok=True, ref="requirements/0007-x.md")

    def stamp_acceptance(self, number, cards, *, actor, requester="", where=""):
        self.stamped.append((number, list(cards), actor, requester, where))
        return [WriteResult(ok=True, ref=c) for c in cards]

    def break_down(self, number, *, actor):
        self.broke_down.append(number)
        return [WriteResult(ok=True, ref="#99")]


def _draft_entry() -> dict:
    answer = SimpleNamespace(ok=True, draft=SimpleNamespace(title="Fila de revisão"))
    return {"kind": "draft", "answer": answer, "asked_by": "<@UADM>", "channel": "C1",
            "number": 7}


@pytest.fixture(autouse=True)
def _quiet_records(monkeypatch):
    from openfactory.memory import messages

    monkeypatch.setattr(messages, "answer", lambda *a, **k: None)


def _yes(project, module, key="C1"):
    waiting = pending_for(key)      # the staged object itself: `consume` compares identity
    assert waiting is not None, "nothing is staged"
    return pc_confirm.confirm(project, key=key, entry=waiting, module=module, user="UADM",
                              lang="pt-BR")


def test_a_yes_on_the_draft_writes_opens_the_card_and_stages_the_second_yes():
    project, module = _Project(), _Module(cards=("#41",))
    remember("C1", _draft_entry())

    said = _yes(project, module)

    assert "escrevi" in said and "o cartão #41" in said and "sem aceite" in said, said
    staged = pending_for("C1")
    assert staged and staged["kind"] == "accept" and staged["number"] == 7
    assert staged["cards"] == ["#41"] and staged["asked_by"] == "<@UADM>"


def test_the_second_yes_accepts_and_stamps_the_cards_and_does_not_break_down_again():
    project, module = _Project(), _Module(cards=("#41", "#42"))
    remember("C1", _draft_entry())
    _yes(project, module)

    said = _yes(project, module)

    assert "Acordado" in said and "os cartões #41 e #42" in said, said
    assert module.stamped and module.stamped[0][1] == ["#41", "#42"]
    assert module.stamped[0][2] == "UADM" and module.stamped[0][3] == "UADM"
    assert module.broke_down == [], "the cards exist — breaking the requirement down again"
    assert pending_for("C1") is None, "the conversation is still waiting on something"


def test_an_acceptance_with_no_cards_still_breaks_the_requirement_down():
    """The panel's acceptance, or an older requirement's: no card was opened for it, so the
    agreement produces work the way ADR-0032 did — never an agreement and nothing."""
    project, module = _Project(), _Module()
    remember("C1", {"kind": "accept", "number": 7, "channel": "C1", "asked_by": "<@UADM>"})

    said = _yes(project, module)

    assert "Acordado" in said
    assert module.broke_down == [7] and module.stamped == []


def test_a_card_that_could_not_be_opened_costs_neither_the_write_nor_the_answer():
    class _NoCards(_Module):
        def open_cards_for(self, number, *, actor):
            raise RuntimeError("the tracker is down")

    project, module = _Project(), _NoCards()
    remember("C1", _draft_entry())

    said = _yes(project, module)

    assert "escrevi" in said and "cartão" not in said
    assert pending_for("C1") is None, "a second yes was staged for a card that does not exist"
