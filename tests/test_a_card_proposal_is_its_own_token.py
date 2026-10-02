"""#475 — a card proposal's confirmation button approves that card and no other.

THE DEFECT. `proposal_token` fingerprints `_proposal_summary(entry)`, which read the title, body and
criteria from `entry["answer"].draft`. The entries the engine stages for a card (the composed card,
the plain ticket, the defect) hold `title`, `card` and `described` at the top and have no `answer`,
so every card proposal in a conversation summarised to its kind alone, `tipo: ticket`, and shared
one token. A button posted for one card filed whichever card was staged when it was clicked, and
the confirmation judge was handed the kind with nothing to judge.

Found while building #452, where the shared token let a refused card through on a second worker.
"""

from __future__ import annotations

import pytest

import openfactory.product.channel as pc
from openfactory.product.staging import _proposal_summary, proposal_token
from tests.test_confirmation_by_click import ADMIN, KEY, _Module, _project
from tests.the_chat_turn import AS_NAMED, CHAT

CARD = ("## O que muda\nO carrinho mostra o total.\n\n## Critérios\n"
        + "".join(f"- critério {i} vale\n" for i in range(40)))


def _composed(title="Mostrar o total do carrinho", card=CARD, kind="ticket"):
    """What `engine` stages for a composed card or a defect: the title and the card on top."""
    return {"kind": kind, "title": title, "card": card, "described": "quero ver o total",
            "reported_by": ADMIN, "channel": KEY}


def _plain(title="Mostrar o total do carrinho", described="quero ver o total"):
    """What `engine` stages for a ticket filed without a composed card."""
    return {"kind": "ticket", "title": title, "described": described, "reported_by": ADMIN,
            "channel": KEY}


@pytest.fixture(autouse=True)
def _clean():
    pc._PENDING.clear()
    yield
    pc._PENDING.clear()


# ═══ the defect, end to end: a stale button does not file the card staged after it ═════════════

def test_a_button_for_one_card_does_not_file_the_card_staged_after_it():
    pc.forget(KEY)
    pc.remember(KEY, _composed("Mostrar o total do carrinho"))
    token = pc.proposal_token(KEY, pc.pending_for(KEY))
    pc.remember(KEY, _composed("Remover o rodapé", card="## O que muda\nSem rodapé.\n"))
    mod = _Module()

    reply = pc.confirm_by_click(_project(), people=AS_NAMED, via=CHAT, token=token,
                                approved=True, user=ADMIN, module=mod)

    assert reply and "diferente do que estava neste botão" in reply, reply
    assert pc.pending_for(KEY)["title"] == "Remover o rodapé", "the replacement was destroyed"


# ═══ every field the person was shown is in the fingerprint ═════════════════════════════════════

@pytest.mark.parametrize("one, other", [
    (_composed(title="Mostrar o total"), _composed(title="Remover o rodapé")),
    # a criterion near the end of a long card: past the 800 characters a draft's body is cut to
    (_composed(), _composed(card=CARD.replace("critério 39 vale", "critério 39 não vale"))),
    (_composed(kind="defect"), _composed(kind="defect", title="O total some no celular")),
    (_plain(title="Mostrar o total"), _plain(title="Remover o rodapé")),
    (_plain(described="na página inicial"), _plain(described="no checkout")),
], ids=["card title", "card criterion", "defect title", "ticket title", "ticket request"])
def test_two_proposals_that_differ_in_what_the_person_saw_never_share_a_token(one, other):
    assert proposal_token(KEY, one) != proposal_token(KEY, other)


def test_the_same_proposal_staged_twice_keeps_its_token():
    assert proposal_token(KEY, _composed()) == proposal_token(KEY, _composed())


def test_the_judge_is_handed_the_card_not_only_its_kind():
    said = _proposal_summary(_composed())
    assert "Mostrar o total do carrinho" in said and "critério 39 vale" in said
    assert said != "tipo: ticket"
