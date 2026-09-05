"""The product owner orders the backlog from chat (#33 slice 9 — the chat half of `reorder`).

#45 gave the module the verb (`ProductModule.reorder`, a `Rankable` capability on the three
boards) and a row behind `yes`; what was left was the sentence — "coloca nessa ordem: 7, 3, 9" —
which until now the role could only discuss. The marker `[[ORDEM: 7, 3, 9]]` is the model's
declaration that the person gave the backlog an order; the channel stages it like the queue, the
person reads the order back and confirms, an admin's yes writes it through the module.

ORDER IS THE WHOLE CONTENT, and every helper on the way is one that sorts: `ref_numbers` sorts and
deduplicates for a notification, which is right there and wrong here. The guards below pin that
nothing between the model and the board reorders the order.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import openfactory.product.channel as pc
from openfactory.product import confirm as confirm_module
from openfactory.product.role import _ORDER_RE, ORDER_MARKER, ProductAnswer
from openfactory.product.voice import reorder_confirmation, reordered
from tests.test_confirmation_by_click import ADMIN, KEY, _project

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean():
    pc._PENDING.clear()
    yield
    pc._PENDING.clear()


# ── the marker ──────────────────────────────────────────────────────────────────────────────────

def test_the_marker_carries_the_numbers_in_the_order_given():
    assert ORDER_MARKER == "[[ORDEM"
    assert _ORDER_RE.search("ok\n[[ORDEM: 7, 3, 9]]").group("numbers").strip() == "7, 3, 9"
    assert _ORDER_RE.search("[[ORDEM: #9,#3]]") is not None
    assert _ORDER_RE.search("[[ORDEM]]") is None, "an order with no numbers is not an order"


def test_the_answer_model_has_the_two_fields_and_they_default_off():
    answer = ProductAnswer(ok=True, text="x")
    assert answer.is_reorder is False and answer.order == []


def test_the_prompt_teaches_the_marker_between_the_card_and_the_queue():
    """Born in the prompt, like the other markers; placed between the card paragraph and the
    queue one, and it says the two things a person needs: top first as they said it, and nothing
    starts."""
    src = (ROOT / "openfactory" / "product" / "role.py").read_text(encoding="utf-8")
    ticket_at = src.index("A card is not a promise")
    order_at = src.index("[[ORDEM: 7, 3, 9]]", ticket_at)
    queue_at = src.index("IF THEY ASKED TO START THE WORK", order_at)
    assert 0 < order_at - ticket_at < 700 and 0 < queue_at - order_at < 800
    assert "spends nothing and starts nothing" in src


def test_the_marker_is_parsed_in_the_order_given_and_stripped_from_the_text(tmp_path):
    from tests.test_product_module import _module as _answering_module

    mod, _harness = _answering_module(
        tmp_path, answer="Fica assim então.\n[[ORDEM: 9, #3, 7, 3]]")
    answer = mod.answer("coloca nessa ordem: 9, 3, 7")
    assert answer.is_reorder and answer.order == ["9", "3", "7"], answer.order
    assert "[[ORDEM" not in answer.text and answer.text.strip() == "Fica assim então."


def test_no_marker_is_no_order(tmp_path):
    from tests.test_product_module import _module as _answering_module

    mod, _harness = _answering_module(tmp_path, answer="O #7 e o #3 estão no backlog.")
    answer = mod.answer("o que temos no backlog?")
    assert not answer.is_reorder and answer.order == []


# ── the channel: staged, asked, confirmed ───────────────────────────────────────────────────────

class _World:
    """The boundary fake `test_confirmation_by_click.py` uses, plus the verb under test — and
    `promote`, so a confirm that reached the wrong verb is seen rather than raised."""

    def __init__(self, *, order=("7", "3", "9"), says="Fica assim então.", fail=()):
        self.order, self.says, self.fail = list(order), says, set(fail)
        self.reordered: list[tuple[list[str], str]] = []
        self.promoted: list[list[str]] = []

    def settle_acceptance(self, text):
        return None

    def close_decisions_answered(self, *, channel=""):
        return 0

    def confirmed(self, reply, *, proposal):
        return "yes" if reply.strip().lower() in {"sim", "yes"} else "no"

    def context(self):
        return SimpleNamespace(available=True, reason="")

    def answer(self, question, *, context="", conversation="", **_):
        return SimpleNamespace(ok=True, is_reorder=True, order=list(self.order), is_ticket=False,
                               ticket_title="", is_defect=False, is_request=False, decisions=[],
                               gesture="", text=self.says, violates=None)

    def reorder(self, numbers, *, actor, board=None):
        self.reordered.append((list(numbers), actor))
        return [SimpleNamespace(ok=n not in self.fail, ref=f"#{n}" if n not in self.fail else "",
                                detail="" if n not in self.fail else "este quadro ainda não "
                                                                   "aceita reordenação por aqui")
                for n in numbers]

    def promote(self, numbers, *, actor, board=None):
        self.promoted.append(list(numbers))
        return []


def test_the_channel_stages_the_order_and_reads_it_back():
    world = _World()
    reply = pc.handle(_project(), text="coloca nessa ordem: 7, 3, 9", user=ADMIN, thread=KEY,
                      module=world)
    staged = pc.pending_for(KEY)
    assert staged and staged["kind"] == "reorder" and staged["numbers"] == ["7", "3", "9"]
    assert world.reordered == [] and world.promoted == [], "something moved before the yes"
    assert "#7, #3, #9" in str(reply) and "Confirma" in str(reply), reply
    assert "nada começa" in str(reply), "the ask does not say that nothing starts"


def test_a_yes_writes_the_order_through_the_module_in_sequence():
    world = _World()
    pc.handle(_project(), text="coloca nessa ordem: 7, 3, 9", user=ADMIN, thread=KEY,
              module=world)
    reply = pc.handle(_project(), text="sim", user=ADMIN, thread=KEY, module=world)
    assert world.reordered == [(["7", "3", "9"], ADMIN)], world.reordered
    assert world.promoted == [], "the yes started work instead of ordering it"
    assert "Ordem gravada" in str(reply) and "#7, #3, #9" in str(reply), reply
    assert pc.pending_for(KEY) is None, "the draft was consumed"


def test_the_reply_keeps_the_order_the_board_took_never_sorted():
    world = _World(order=("9", "3", "7"))
    pc.handle(_project(), text="primeiro o 9, depois o 3, depois o 7", user=ADMIN, thread=KEY,
              module=world)
    reply = pc.handle(_project(), text="sim", user=ADMIN, thread=KEY, module=world)
    assert "#9, #3, #7" in str(reply), reply


def test_a_card_the_board_refused_is_said_and_the_rest_stand():
    world = _World(fail={"3"})
    pc.handle(_project(), text="coloca nessa ordem: 7, 3, 9", user=ADMIN, thread=KEY,
              module=world)
    reply = str(pc.handle(_project(), text="sim", user=ADMIN, thread=KEY, module=world))
    assert "#7, #9" in reply and "1 não entraram na ordem" in reply, reply


def test_a_board_that_cannot_rank_answers_with_its_own_sentence():
    world = _World(fail={"7", "3", "9"})
    pc.handle(_project(), text="coloca nessa ordem: 7, 3, 9", user=ADMIN, thread=KEY,
              module=world)
    reply = str(pc.handle(_project(), text="sim", user=ADMIN, thread=KEY, module=world))
    assert "não aceita reordenação" in reply and "Ordem gravada" not in reply, reply


def test_the_reorder_kind_is_registered_beside_the_others():
    assert confirm_module._EXECUTORS["reorder"] is confirm_module._confirm_reorder
    assert confirm_module._EXECUTORS["queue"] is not confirm_module._confirm_reorder


# ── the voice ───────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("lang,starts", [("pt-BR", "nada começa"), ("en", "nothing starts")])
def test_the_confirmation_reads_the_order_and_says_nothing_starts(lang, starts):
    text = reorder_confirmation(numbers=["7", "3", "9"], language=lang)
    assert "#7, #3, #9" in text and starts in text


def test_the_recorded_sentence_carries_the_order_and_the_signature():
    assert reordered(["9", "3"], language="pt-BR", agent_name="Ana") == (
        "Ana: Ordem gravada no quadro: #9, #3. A próxima leva segue ela.")
    assert reordered(["9", "3"], language="en").startswith("Order recorded on the board: #9, #3")
