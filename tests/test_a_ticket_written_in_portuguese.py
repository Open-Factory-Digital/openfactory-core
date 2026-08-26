"""A ticket must be readable in the language its author writes in.

FOUND ON THE FIRST REAL TICKET of the first open-source deployment (2026-08-02). The product owner
wrote a perfectly ordinary ticket — objective, five acceptance criteria, all in Portuguese under
`## Critérios de aceite` — and the platform parked it saying **"ticket has no acceptance
criteria"**. It had five. `_split_sections` matched the literal lowercased English strings
`objective`, `context`, `acceptance criteria`, `in scope`, `out of scope`, so every section fell
on the floor: the objective silently defaulted to the title, and the criteria became `[]`.

WHY THIS IS WORSE THAN THE SIBLING DEFECT. C-14 (#46) says a client's board columns belong to the
client, and it is right. This is the same principle applied to the ticket BODY, and it fails more
quietly: a column with the wrong name is visible on a board somebody is looking at, whereas a
heading with the wrong name deletes the acceptance criteria and then reports their absence as the
client's mistake. The first thing the platform told its first open-source user was that their
ticket was incomplete — about a ticket that was not.

IT IS NOT ONLY A TRANSLATION PROBLEM, which is why the fix is not a second hard-coded language.
`## Acceptance Criteria` works only because the comparison lowercases; `## AC`, `## Definition of
Done`, `## Success criteria` and `## Acceptance criteria:` all fail exactly the same way, in
English, on a template a client already uses. So there are two guards here and they are different
in kind:

1. **the alias table** — what the platform recognises out of the box, in both languages, tolerant
   of case, accents, bold markers and trailing colons;
2. **the message** — whatever the table misses must SAY what it saw. A vocabulary mismatch that
   names the headings it found is a thirty-second fix by the client; one that says "no acceptance
   criteria" is an argument with the machine.

The second guard is the one that survives the next unrecognised heading, and there will be one.
"""

from __future__ import annotations

import pytest

from openfactory.adapters.tracker.parse import parse_ticket_body, section_names

PT = """\
Hoje `calc.money.split(total_cents, ways)` divide em partes iguais.

## O que quero
`calc.money.split_by(total_cents, weights)` que divide proporcionalmente.

## Critérios de aceite
- `sum(split_by(total, weights)) == total` sempre
- `split_by(100, [1, 3]) == [25, 75]`
- pesos vazios, soma zero, ou peso negativo → `ValueError`

## Fora do escopo
- mudar a assinatura de `split`
"""


def _parse(body: str):
    return parse_ticket_body(id="#1", title="um titulo", body=body, repo="o/app")


# ── the ticket that started it ──────────────────────────────────────────────────────────────────

def test_the_real_ticket_that_was_rejected():
    ticket = _parse(PT)

    assert len(ticket.acceptance_criteria) == 3
    assert ticket.acceptance_criteria[1].text == "`split_by(100, [1, 3]) == [25, 75]`"
    assert ticket.out_of_scope == ["mudar a assinatura de `split`"]
    assert "split_by" in ticket.objective  # NOT the title, which is what it fell back to


# ── the alias table ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("heading", [
    "Acceptance criteria",
    "Acceptance Criteria",
    "ACCEPTANCE CRITERIA",
    "Acceptance criteria:",
    "**Acceptance criteria**",
    "Critérios de aceite",
    "Criterios de aceite",          # written without the accent, as people do
    "CRITÉRIOS DE ACEITE",
    "Critério de aceite",           # singular
    "Critérios de aceitação",
    "Definition of done",
    "Done when",
])
def test_a_criteria_heading_is_recognised(heading):
    ticket = _parse(f"## {heading}\n- it works\n")
    assert [c.text for c in ticket.acceptance_criteria] == ["it works"], heading


@pytest.mark.parametrize("heading,expected", [
    ("Objective", "the goal"),
    ("Objetivo", "the goal"),
    ("O que quero", "the goal"),
    ("Goal", "the goal"),
])
def test_an_objective_heading_is_recognised(heading, expected):
    assert _parse(f"## {heading}\n{expected}\n").objective == expected


@pytest.mark.parametrize("heading", ["Out of scope", "Fora do escopo", "Nao escopo",
                                     "Não escopo"])
def test_an_out_of_scope_heading_is_recognised(heading):
    assert _parse(f"## {heading}\n- not this\n").out_of_scope == ["not this"]


@pytest.mark.parametrize("heading", ["In scope", "No escopo", "Escopo", "Scope"])
def test_an_in_scope_heading_is_recognised(heading):
    assert _parse(f"## {heading}\n- this\n").in_scope == ["this"]


@pytest.mark.parametrize("heading", ["Context", "Contexto", "Background"])
def test_a_context_heading_is_recognised(heading):
    assert _parse(f"## {heading}\nwhy\n").context == "why"


# ── the English convention must not regress ─────────────────────────────────────────────────────

def test_the_documented_english_convention_still_parses():
    """`parse.py`'s own docstring, and every existing ticket on the pilot's board."""
    ticket = _parse(
        "## Objective\nship it\n\n## Context\nbecause\n\n"
        "## Acceptance criteria\n- a\n- b\n\n## In scope\n- x\n\n## Out of scope\n- y\n"
    )
    assert ticket.objective == "ship it"
    assert ticket.context == "because"
    assert [c.text for c in ticket.acceptance_criteria] == ["a", "b"]
    assert ticket.in_scope == ["x"]
    assert ticket.out_of_scope == ["y"]


def test_front_matter_still_works():
    ticket = _parse("---\nbase_branch: dev\ndepends_on: ['#4']\n---\n## Objetivo\nfazer\n")
    assert ticket.base_branch == "dev"
    assert ticket.depends_on == ["#4"]
    assert ticket.objective == "fazer"


# ── whatever the table misses must SAY what it saw ──────────────────────────────────────────────

def test_section_names_reports_the_headings_as_written():
    """The input to the refusal message. Kept as WRITTEN, not normalised, because the client has
    to find these headings in their own ticket."""
    assert section_names(PT) == ["O que quero", "Critérios de aceite", "Fora do escopo"]


def test_an_unrecognised_heading_still_yields_no_criteria():
    """The gate must not be defanged. A ticket that genuinely has no criteria still parks."""
    assert _parse("## Requisitos do negócio\n- algo\n").acceptance_criteria == []


def test_the_refusal_names_the_headings_it_found():
    """THE guard that survives the next unrecognised heading — and there will be one. "No
    acceptance criteria" about a ticket full of them is an argument with the machine; the same
    refusal listing `Requisitos do negócio` is a thirty-second fix."""
    from openfactory.contracts import Ticket
    from openfactory.orchestrator.machine import SpecValidationError, _spec_refusal

    body = "## Requisitos do negócio\n- algo\n"
    ticket = Ticket(id="#1", title="t", objective="o", repo="o/app", raw=body)

    with pytest.raises(SpecValidationError) as err:
        _spec_refusal(ticket)

    message = str(err.value)
    assert "Requisitos do negócio" in message, message
    assert "acceptance criteria" in message.lower()


def test_a_ticket_with_no_headings_at_all_says_so_plainly():
    """Naming an empty list would read as a bug. The commonest real case — somebody typed a
    paragraph into the issue box — deserves its own sentence."""
    from openfactory.contracts import Ticket
    from openfactory.orchestrator.machine import SpecValidationError, _spec_refusal

    ticket = Ticket(id="#1", title="t", objective="o", repo="o/app",
                    raw="just a paragraph, no headings at all")

    with pytest.raises(SpecValidationError) as err:
        _spec_refusal(ticket)
    assert "no sections" in str(err.value).lower()
