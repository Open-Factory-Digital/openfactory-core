"""A typed `Case` per conversation (#33, hole 7): the intake as state, not as a re-reading.

The staged proposal is one slot per conversation with a two-hour expiry, and it holds a DRAFT
awaiting a yes — nothing before it. "What did you expect? Which screen? Can you reproduce it?"
over four turns had no typed state: the model re-derived the intake from the transcript every
turn, and in a busy room a second proposal displaced the first in silence. The `Case` is that
state — collecting → proposed → confirmed → filed, or dropped — opened by one person in one
conversation, carrying what they said, what the role asked back, the kind the role read, the
draft once staged and the result once written. The role gets it beside the conversation; the
staging moves it from inside (`remember`, `consume`, `forget`) and the executor files it
(`confirm`), so no branch that stages has to remember to call it.
"""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import openfactory.product.channel as pc
from openfactory import actions
from openfactory.actions import catalog
from openfactory.actions.base import PRODUCT, Actor
from openfactory.product import case
from openfactory.product.case import (
    COLLECTING,
    CONFIRMED,
    DROPPED,
    FILED,
    PROPOSED,
    block_for,
    current,
    note_turn,
    open_cases,
)
from openfactory.product.role import ProductRole
from openfactory.product.staging import consume, forget, pending_for, remember
from tests.test_confirmation_by_click import ADMIN, KEY, _project

ROOT = Path(__file__).resolve().parents[1]
P = SimpleNamespace(name="acme")
NOW = time.time()


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    pc._PENDING.clear()
    case._reset_for_tests()
    # no disk unless a test asks for it — a SimpleNamespace project has no home
    yield
    pc._PENDING.clear()
    case._reset_for_tests()


def _answer(text="Qual tela?", **over):
    base = dict(ok=True, text=text, is_defect=False, is_ticket=False, is_reorder=False,
                is_request=False, gesture="", decisions=[])
    base.update(over)
    return SimpleNamespace(**base)


# ── the state, turn by turn ─────────────────────────────────────────────────────────────────────

def test_the_first_turn_opens_a_case_and_the_next_ones_join_it():
    first = note_turn(P, "acme", "ana", "o relatório quebra", _answer("Qual tela?"), now=NOW)
    assert first.state == COLLECTING and first.facts == ["o relatório quebra"]
    assert first.asked == ["Qual tela?"] and first.kind == ""
    second = note_turn(P, "acme", "ana", "a de fechamento", _answer("Consegue reproduzir?"),
                       now=NOW + 60)
    assert second.id == first.id
    assert second.facts == ["o relatório quebra", "a de fechamento"]
    assert second.asked == ["Qual tela?", "Consegue reproduzir?"]
    assert current(P, "acme", "ana", now=NOW + 100).id == first.id


def test_the_kind_the_role_read_is_kept_and_a_statement_asks_nothing():
    got = note_turn(P, "acme", "ana", "o total sai errado", _answer("Vou registrar como problema.",
                                                                   is_defect=True), now=NOW)
    assert got.kind == "defect" and got.asked == []


def test_another_person_in_the_same_room_has_their_own_case():
    a = note_turn(P, "acme", "ana", "quero X", _answer(), now=NOW)
    b = note_turn(P, "acme", "bruno", "quero Y", _answer(), now=NOW + 1)
    assert a.id != b.id and current(P, "acme", "ana", now=NOW + 2).id == a.id
    assert [c.opened_by for c in open_cases(P, "acme", now=NOW + 2)] == ["bruno", "ana"]


def test_an_intake_a_day_old_is_not_this_one():
    old = note_turn(P, "acme", "ana", "ontem", _answer(), now=NOW - 10)
    later = note_turn(P, "acme", "ana", "hoje", _answer(), now=NOW + case.CASE_TTL_SECONDS + 5)
    assert later.id != old.id and later.facts == ["hoje"]
    assert current(P, "acme", "ana", now=NOW + case.CASE_TTL_SECONDS + 6).id == later.id


def test_the_block_reads_back_what_was_said_and_asked_and_is_empty_for_a_first_turn():
    assert block_for(P, "acme", "ana") == ""
    note_turn(P, "acme", "ana", "o relatório quebra", _answer("Qual tela?"), now=NOW)
    block = block_for(P, "acme", "ana", now=NOW + 1)
    assert block.startswith("## This intake so far")
    assert "- o relatório quebra" in block and "what you asked back:\n- Qual tela?" in block


# ── the staging moves it ────────────────────────────────────────────────────────────────────────

def test_a_staged_draft_makes_the_case_proposed_with_it():
    note_turn(P, "acme", "ana", "abre um card", _answer("Abro.", is_ticket=True), now=NOW)
    remember("acme", {"kind": "ticket", "title": "Exportar CSV"}, project=P)
    got = current(P, "acme", "ana", now=NOW + 1)
    assert got.state == PROPOSED and got.kind == "ticket"
    assert got.draft == {"kind": "ticket", "title": "Exportar CSV"}


def test_a_yes_confirms_it_and_a_no_drops_it():
    note_turn(P, "acme", "ana", "abre um card", _answer(is_ticket=True), now=NOW)
    entry = {"kind": "ticket", "title": "X"}
    remember("acme", entry, project=P)
    staged = pending_for("acme")
    assert consume("acme", staged, project=P, by="ana", approved=True) is not None
    assert current(P, "acme", "ana", now=NOW + 1).state == CONFIRMED
    case._reset_for_tests()
    pc._PENDING.clear()
    note_turn(P, "acme", "ana", "abre um card", _answer(is_ticket=True), now=NOW)
    remember("acme", entry, project=P)
    consume("acme", pending_for("acme"), project=P, by="ana", approved=False)
    assert current(P, "acme", "ana", now=NOW + 1) is None
    (gone,) = [c for c in case._CASES["acme"].values()]
    assert gone.state == DROPPED and gone.note == "rejected"


def test_a_forgotten_draft_drops_the_case():
    note_turn(P, "acme", "ana", "abre um card", _answer(is_ticket=True), now=NOW)
    remember("acme", {"kind": "ticket", "title": "X"}, project=P)
    forget("acme")
    (gone,) = list(case._CASES["acme"].values())
    assert gone.state == DROPPED and gone.note == "forgotten"


def test_a_displaced_proposal_goes_back_to_collecting_with_its_facts_kept():
    """THE ROOM'S LOSS, CLOSED. Ana's ticket draft is displaced by Bruno's queue proposal; the
    staging admits it in a sentence, and until now everything Ana had said was gone with it."""
    note_turn(P, "acme", "ana", "abre um card para o CSV", _answer(is_ticket=True), now=NOW)
    remember("acme", {"kind": "ticket", "title": "Exportar CSV"}, project=P)
    note_turn(P, "acme", "bruno", "podemos avançar?", _answer(gesture="queue"), now=NOW + 1)
    replaced = remember("acme", {"kind": "queue", "numbers": ["7"]}, project=P)
    assert replaced, "the staging did not admit the displacement"
    ana = current(P, "acme", "ana", now=NOW + 2)
    assert ana.state == COLLECTING and ana.draft == {} and "displaced" in ana.note
    assert ana.facts == ["abre um card para o CSV"], "what she said was lost"
    bruno = current(P, "acme", "bruno", now=NOW + 2)
    assert bruno.state == PROPOSED and bruno.kind == "queue"


# ── the executor files it ───────────────────────────────────────────────────────────────────────

class _World:
    def __init__(self):
        self.filed: list[dict] = []
        self.intakes: list[str] = []

    def settle_acceptance(self, text):
        return None

    def close_decisions_answered(self, *, channel=""):
        return 0

    def confirmed(self, reply, *, proposal):
        return "yes" if reply.strip().lower() in {"sim", "yes"} else "no"

    def context(self):
        return SimpleNamespace(available=True, reason="")

    def answer(self, question, *, context="", conversation="", intake="", **_):
        self.intakes.append(intake)
        return SimpleNamespace(ok=True, is_ticket=True, ticket_title="Exportar CSV",
                               is_defect=False, is_request=False, is_reorder=False, order=[],
                               decisions=[], gesture="", text="Abro sim.", violates=None)

    def file_ticket(self, **kw):
        self.filed.append(kw)
        return SimpleNamespace(ok=True, ref="#77", url="https://forge/x/77", detail="",
                               existed=False)


def test_through_the_channel_the_case_walks_to_filed_and_the_role_saw_the_intake():
    world = _World()
    pc.handle(_project(), text="abre um card para exportar CSV", user=ADMIN, thread=KEY,
              module=world)
    got = current(_project(), KEY, ADMIN)
    assert got.state == PROPOSED and got.kind == "ticket" and got.draft["title"] == "Exportar CSV"
    assert world.intakes == [""], "a first turn carried an intake"
    pc.handle(_project(), text="sim", user=ADMIN, thread=KEY, module=world)
    (done_case,) = [c for c in case._CASES[_project().name].values()]
    assert done_case.state == FILED
    assert done_case.result["url"] == "https://forge/x/77", done_case.result
    assert "Aberto" in done_case.result["said"] or "Opened" in done_case.result["said"]
    assert current(_project(), KEY, ADMIN) is None, "a filed case is not open"


def test_the_second_turn_hands_the_role_the_intake(monkeypatch):
    world = _World()

    def asks(question, *, context="", conversation="", intake="", **_):
        world.intakes.append(intake)
        return _answer("Qual tela?")

    monkeypatch.setattr(world, "answer", asks)
    pc.handle(_project(), text="o relatório quebra", user=ADMIN, thread=KEY, module=world)
    pc.handle(_project(), text="a de fechamento", user=ADMIN, thread=KEY, module=world)
    assert world.intakes[0] == ""
    assert "- o relatório quebra" in world.intakes[1] and "- Qual tela?" in world.intakes[1]


# ── the role's prompt ───────────────────────────────────────────────────────────────────────────

def test_the_prompt_carries_the_intake_and_tells_her_to_continue_it():
    prompt = ProductRole(None, intake="## This intake so far\nkind: defect · state: collecting\n"
                                      "what they said:\n- o relatório quebra")._prompt(
        "x", "y", audience="client")
    assert "- o relatório quebra" in prompt and "do not start over" in prompt
    assert "do not ask again what they already answered" in prompt
    assert "This intake so far" not in ProductRole(None)._prompt("x", "y", audience="client")


def test_the_module_hands_the_intake_through_the_one_seam():
    src = (ROOT / "openfactory/product/module.py").read_text(encoding="utf-8")
    assert 'self._role(pending=pending, **({"intake": intake} if intake else {}))' in src
    assert "intake=intake," in src


# ── persistence ─────────────────────────────────────────────────────────────────────────────────

def test_the_cases_survive_the_process_when_the_project_has_a_home(tmp_path, monkeypatch):
    monkeypatch.setattr("openfactory.paths.project_memory_dir", lambda p: tmp_path / "mem")
    note_turn(P, "acme", "ana", "o relatório quebra", _answer("Qual tela?"), now=NOW)
    assert (tmp_path / "mem" / case.CASES_FILE).is_file()
    case._reset_for_tests()
    back = current(P, "acme", "ana", now=NOW + 1)
    assert back is not None and back.facts == ["o relatório quebra"]


# ── the read row ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_product_cases_shows_a_conversations_open_intakes_and_keeps_a_private_one_private(
        monkeypatch):
    project = SimpleNamespace(name="acme", product=SimpleNamespace(agent_name="Ana PO"))
    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_k: (object(), project, None))
    note_turn(project, "acme", "ana", "quero o CSV", _answer("Qual formato?"), now=NOW)
    note_turn(project, "person:ana", "ana", "segredo", _answer(), now=NOW)
    bruno = Actor(id="bruno", via="panel", conversation="person:bruno")
    room = await actions.perform("product_cases", by=bruno, project="acme", thread="acme")
    assert room.ok and [c["opened_by"] for c in room.data["cases"]] == ["ana"]
    assert "- quero o CSV" in room.message and "Qual formato?" in room.message
    private = await actions.perform("product_cases", by=bruno, project="acme",
                                    thread="person:ana")
    assert not private.ok, "Ana's private intake reached Bruno"
    ana = Actor(id="ana", via="panel", conversation="person:ana")
    mine = await actions.perform("product_cases", by=ana, project="acme")
    assert mine.ok and [c["facts"] for c in mine.data["cases"]] == [["segredo"]]
    empty = await actions.perform("product_cases", by=bruno, project="acme")
    assert empty.ok and "nothing is in progress" in empty.message


def test_the_row_is_a_read():
    spec = actions.spec("product_cases")
    assert spec.scope == PRODUCT and spec.needs_admin is False
    assert tuple(spec.required) == ("project",) and tuple(spec.optional) == ("thread",)
