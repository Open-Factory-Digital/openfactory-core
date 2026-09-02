""""Already asked" is answered from the board, the corpus and the loops — not the transcript
(#33, slice 5).

The truth about what was asked lives in the board (a ticket somebody filed), the requirements
corpus (a promise, and who asked for it) and the open loops (a decision the role asked a person
for) — three places the role already reads. Built on the transcript it would recognise a repeat
only in the SAME conversation, which is precisely the case it must catch across people: Ana asks
on Monday, Bruno asks on Thursday from another browser, and the right answer to Bruno is "Ana
asked for this, it is #123, in To Do" — not a second draft of the same requirement.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory.memory.ledger import CLOSED, DECISION, Loop, open_loop
from openfactory.product import asked
from openfactory.product.role import ProductRole

ROOT = Path(__file__).resolve().parent.parent


class _Agent:
    name = "fake"


def _card(number, title, *, column="To Do", state="open", reason="", body="", assignees=()):
    return SimpleNamespace(number=number, title=title, column=column, state=state,
                           state_reason=reason, body=body, assignees=list(assignees))


def _req(number, title, slug, *, status="accepted", asked_by="", superseded_by=None):
    return SimpleNamespace(number=number, title=title, slug=slug, status=status,
                           asked_by=asked_by, path=f"requirements/{number:04d}-{slug}.md",
                           superseded_by=superseded_by)


CARDS = [_card(123, "Relatório mensal em PDF", assignees=["ana"]),
         _card(7, "Login com SSO", column="Done", state="closed", reason="completed"),
         _card(9, "Relatório de vendas por região", column="In Progress")]
CORPUS = SimpleNamespace(requirements=[
    _req(7, "Exportar CSV dos relatórios", "exportar-csv", asked_by="bia"),
    _req(3, "Login com SSO", "login-sso", status="delivered"),
])
LOOPS = [
    open_loop(DECISION, "relatorio-mensal-q4", owner="product", ts="2026-09-01T10:00:00",
              about="C0ABC", context={"asked": "o relatório mensal entra no Q4?"}),
]
_answered = open_loop(DECISION, "exportar-csv-depois", owner="product", ts="2026-08-01T10:00:00",
                      context={"asked": "exportar CSV fica para depois?"})
LOOPS.append(Loop(**{**_answered.__dict__, "state": CLOSED, "outcome": "answered"}))


# ── the read ────────────────────────────────────────────────────────────────────────────────────

def test_tokens_fold_accents_stopwords_and_the_verbs_of_wanting():
    assert asked.tokens("Quero que os relatórios mensais saiam em PDF") == \
        {"relatorios", "mensais", "saiam", "pdf"}
    assert asked.tokens("We would like to be able to export it") == {"export", "able"}
    assert "queremos" not in asked.tokens("queremos isso") and asked.tokens("é o de") == set()


def test_a_ticket_somebody_filed_is_found_under_another_inflection():
    """Ana filed «Relatório mensal em PDF»; Bruno asks for «relatórios mensais em pdf». The stem
    folds the plural, and the answer names the card, where it sits and who is on it."""
    found = asked.already_asked("queremos os relatórios mensais em pdf", cards=CARDS)

    assert [m.ref for m in found] == ["#123"], found
    match = found[0]
    assert match.kind == "ticket" and match.title == "Relatório mensal em PDF"
    assert match.where == "To Do, open" and match.who == "ana"


def test_a_requirement_is_found_with_who_asked_and_where_it_lives():
    found = asked.already_asked("dá para exportar csv?", corpus=CORPUS)

    assert [m.ref for m in found] == ["REQ-0007"]
    assert found[0].who == "bia" and "requirements/0007-exportar-csv.md" in found[0].where
    assert "(accepted)" in found[0].where


def test_an_open_decision_is_found_by_what_was_asked_and_a_closed_one_is_not():
    found = asked.already_asked("o relatório mensal fica para o Q4?", loops=LOOPS)

    assert [m.kind for m in found] == ["decision"]
    assert found[0].ref == "relatorio-mensal-q4" and "asked 2026-09-01 in C0ABC" in found[0].where

    assert asked.already_asked("exportar csv fica para depois?", loops=LOOPS) == [], \
        "an answered decision is not still asked"


def test_one_shared_word_is_a_coincidence_not_a_lead():
    assert asked.already_asked("relatório de custos", cards=[_card(1, "Relatório de vendas")]) == []
    assert asked.already_asked("quero uma coisa nova", cards=CARDS, corpus=CORPUS) == []
    assert asked.already_asked("", cards=CARDS) == []
    assert asked.render([]) == ""


def test_the_best_lead_comes_first_and_the_list_is_short():
    cards = [_card(3, "Relatório de vendas por região mensal"),     # 2 of 4 words: half
             _card(2, "Relatório mensal"),                            # whole title, 2 words
             _card(1, "Relatório mensal em PDF com logo"),            # whole title, 4 words
             _card(4, "Logo no relatório"),                           # whole title, 2 words
             _card(5, "Relatório mensal em PDF com logo e assinatura")]

    found = asked.already_asked("relatório mensal em pdf com logo", cards=cards)

    assert len(found) == asked.LIMIT
    assert [m.ref for m in found] == ["#1", "#5", "#2"], [(m.ref, m.score, m.shared) for m in found]
    assert found[0].shared == 4 and found[-1].shared == 2
    assert "#3" not in [m.ref for m in found], "half a title is the weakest lead, and the list is short"


def test_the_section_tells_the_role_to_point_and_not_to_draft_again():
    text = asked.render(asked.already_asked("relatórios mensais em pdf", cards=CARDS,
                                            corpus=CORPUS, loops=LOOPS))

    assert "checked for you" in text and "do not draft it again" in text
    assert "ticket #123 «Relatório mensal em PDF» — To Do, open, asked by ana" in text
    assert "decision relatorio-mensal-q4" in text


# ── the prompt and the module ──────────────────────────────────────────────────────────────────

class _Captured(Exception):
    pass


def test_the_role_puts_the_section_with_the_question_after_the_stable_half(monkeypatch):
    """Volatile, so it sits after everything the prompt cache can keep (ADR-0024 §2), and right
    before the question it is about."""
    seen: dict = {}

    def _ask(self, sandbox, workspace, prompt, phase):
        seen["prompt"] = prompt
        raise _Captured()

    monkeypatch.setattr(ProductRole, "_ask", _ask)
    role = ProductRole(_Agent())
    section = asked.render(asked.already_asked("relatórios mensais em pdf", cards=CARDS))

    with pytest.raises(_Captured):
        role.answer(sandbox=None, workspace=None, question="relatórios mensais em pdf?",
                    conversation="Ana: bom dia", asked=section)
    prompt = seen["prompt"]
    assert prompt.index("Ana: bom dia") < prompt.index("# Possibly already asked") \
        < prompt.index("## Question")

    with pytest.raises(_Captured):
        role.answer(sandbox=None, workspace=None, question="q")
    assert "Possibly already asked" not in seen["prompt"], "no section is drawn for nothing"


def _module(monkeypatch, *, loops=LOOPS, role=None):
    from openfactory.memory import store

    monkeypatch.setattr(store, "read", lambda project: list(loops))
    return SimpleNamespace(project=SimpleNamespace(name="acme"),
                           _board_cards=lambda: CARDS,
                           context=lambda: SimpleNamespace(available=True, corpus=CORPUS),
                           _workspace=lambda: (None, None),
                           _role=lambda pending="": role)


def test_the_module_reads_its_own_three_sources_and_hands_the_section_to_the_role(monkeypatch):
    from openfactory.product.module import ProductModule

    seen: dict = {}
    fake_role = SimpleNamespace(answer=lambda **kw: seen.update(kw) or "ok")
    fake = _module(monkeypatch, role=fake_role)
    fake.already_asked = lambda text: ProductModule.already_asked(fake, text)

    assert ProductModule.answer(fake, "queremos os relatórios mensais em pdf") == "ok"
    assert "#123" in seen["asked"] and "relatorio-mensal-q4" in seen["asked"]
    assert "REQ-0007" not in seen["asked"], "CSV was not asked; a lead is not a list of everything"


def test_an_unreadable_ledger_costs_the_decisions_half_and_nothing_else(monkeypatch, caplog):
    from openfactory.memory import store
    from openfactory.product.module import ProductModule

    fake = _module(monkeypatch)

    def unreadable(project):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(store, "read", unreadable)
    with caplog.at_level("WARNING", logger="openfactory.product"):
        text = ProductModule.already_asked(fake, "relatórios mensais em pdf")

    assert "#123" in text and "relatorio-mensal-q4" not in text
    assert "already asked" in caplog.text


def test_the_client_s_document_says_so():
    text = (ROOT / "docs/reference/product-role.md").read_text()
    assert "Was this asked before?" in text and "never from one" in text
