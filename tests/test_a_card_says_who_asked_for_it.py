"""A card says who asked for it — machine-readably, on every vendor.

THE PERSON THE PLAN CALLS IS THE CARD'S REQUESTER (issue #33, decision 2, 2026-09-06): "whether
the role wrote the ticket or somebody wrote it directly, it has to call the requester". Until now
the only person a job could name was `Ticket.author` — the CREATOR, which on a card the factory
opens is the platform's own App: a question routed there asks nobody. The factory's three body
builders wrote `**Pedido por:** <@U1>` / `**Reportado por:** <@U1>` as prose, and nothing in the
tree read it back.

What this file holds:
  1. every body the factory writes carries `requester:` as front matter, and `parse_ticket_body`
     reads it back into `Ticket.requester`;
  2. an older card, written before the key existed, is read from its prose labels — the three
     shapes, and ADR-0047's "Awaiting the acceptance of";
  3. `requester_of` is the requester when the card names one and the creator otherwise — a
     hand-written card's creator IS its requester; "não registrado" is nobody, not a person;
  4. a card born from a requirement is asked for by whoever asked for the requirement.
"""

from __future__ import annotations

from types import SimpleNamespace

from openfactory.adapters.tracker.parse import parse_ticket_body
from openfactory.contracts.ticket import Ticket, requester_of
from openfactory.product.authoring import defect_body, issue_body, ticket_body
from openfactory.product.role import IssueDraft


def _parsed(body: str, author: str | None = "openfactory-bot") -> Ticket:
    ticket = parse_ticket_body(id="#7", title="t", body=body, repo="o/r")
    return ticket.model_copy(update={"author": author})


# ── 1. written and read back ─────────────────────────────────────────────────────────────────


def test_the_card_a_person_asked_for_names_them_as_front_matter():
    body = ticket_body(described="um relatório mensal", reported_by="<@U0PO>", source="chat")

    assert body.startswith("---\nrequester:"), body[:60]
    assert "**Pedido por:** <@U0PO>" in body, "the prose line stays for the person reading"
    assert _parsed(body).requester == "<@U0PO>"


def test_the_defect_card_names_who_reported_it():
    body = defect_body(restated="o fecho não gera o pacote", reported_by="<@U0BA>",
                       severity="alta", source="chat", requirement=None,
                       requirement_path="requirements/0001-x.md", docs_repo="o/docs")

    assert _parsed(body).requester == "<@U0BA>"


def test_the_card_born_from_a_requirement_is_asked_for_by_who_asked_for_the_requirement():
    draft = IssueDraft(title="t", objective="o", acceptance_criteria=["c"], cites=4)
    body = issue_body(draft, requirement_path="requirements/0004-x.md", docs_repo="o/docs",
                      requester="<@U0PO>")

    assert body.startswith("---\nrequester:")
    assert _parsed(body).requester == "<@U0PO>"
    # the executor's sections are intact behind the front matter
    ticket = _parsed(body)
    assert ticket.objective == "o" and ticket.acceptance_criteria[0].text.endswith("c")


def test_a_card_with_nobody_recorded_carries_no_key():
    body = ticket_body(described="x", reported_by="", source="")

    assert not body.startswith("---"), "a key naming nobody would be read as somebody"
    assert "**Pedido por:** não registrado" in body
    assert _parsed(body).requester is None


# ── 2. older cards, from their prose ─────────────────────────────────────────────────────────


def test_an_older_card_is_read_from_its_prose_labels():
    assert _parsed("**Tipo:** tarefa\n**Pedido por:** <@U0PO>\n\n## O que foi pedido\n\nx\n"
                   ).requester == "<@U0PO>"
    assert _parsed("**Tipo:** defeito\n**Reportado por:** <@U0BA>\n").requester == "<@U0BA>"
    assert _parsed("## Acceptance\n\nAwaiting the acceptance of <@U0PO> (ADR-0047). Until then "
                   "this card is a proposal.\n").requester == "<@U0PO>"
    assert _parsed("Requested by: alice\n").requester == "alice"


def test_the_front_matter_wins_over_the_prose():
    body = "---\nrequester: alice\n---\n**Pedido por:** <@U0OLD>\n"
    assert _parsed(body).requester == "alice"


# ── 3. requester_of ──────────────────────────────────────────────────────────────────────────


def test_requester_of_is_the_requester_when_named_and_the_creator_otherwise():
    named = Ticket(id="#1", title="t", objective="o", repo="o/r", author="openfactory-bot",
                   requester="<@U0PO>")
    hand_written = Ticket(id="#2", title="t", objective="o", repo="o/r", author="alice")
    nobody = Ticket(id="#3", title="t", objective="o", repo="o/r", author=None)

    assert requester_of(named) == "<@U0PO>", "the bot created it; the person asked for it"
    assert requester_of(hand_written) == "alice", "a hand-written card's creator is its requester"
    assert requester_of(nobody) is None


def test_nobody_recorded_is_not_a_person():
    ticket = Ticket(id="#1", title="t", objective="o", repo="o/r", author="alice",
                    requester="não registrado")
    assert requester_of(ticket) == "alice"
    assert requester_of(SimpleNamespace(requester="", author="")) is None
