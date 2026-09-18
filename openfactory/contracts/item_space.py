"""Whose numbers a card's reference is — asked of the rows and compared, never assumed (#167).

THE JOB WROTE THE TRACKER'S CARD ID INTO THINGS THE FORGE OWNS, AS IF THE FORGE OWNED IT. The
commit message and the pull request title were `f"{ticket.id}: {ticket.title}"` and the body said
`Closes {ticket.id}`. A forge reads that id in its OWN terms, and that is right for exactly one
pairing — a tracker and a forge that number the same items. The registry builds every other
pairing too (each axis is its own row, `factory.py`), and on those the forge reads somebody else's
item. Reproduced with a local board over a forge whose `#N` is an organisation-wide work item: ids
6, 7, 9, 10, 11, 12, 14, 15, 20, 50 and 100 all existed there, in other projects, so every early
card's pull request linked an unrelated item. The deployment that found it worked around it by
renumbering its board past the forge's highest id.

SO EACH ROW SAYS WHERE ITS NUMBERS LIVE, AND THE CORE ONLY COMPARES. `item_space` is an optional
method a tracker row answers for a card (`item_space(ticket)`) and a forge row answers for itself
(`item_space()`): a tuple of two non-empty strings, opaque here, or `None`. The forge owns the card
exactly when the two answers are EQUAL — no vendor name in this module or in the orchestrator, and
a vendor this core has never heard of pairs with its own forge by declaring the same tuple on both
rows.

WHY NOT A METHOD ON THE PORTS. `ForgeAdapter` is a `runtime_checkable` Protocol, and so is the
tracker's: a new method there makes every add-on and every test double claim an answer it may not
have (CONTRIBUTING, "widening a port"), and the honest answer for most rows — the local board, the
local forge, Jira, an add-on — is "I share numbers with nobody". An ABSENT declaration says exactly
that, which is why the question is asked with `getattr` and an absence is `None`, the way
`RepositoryCreatingForge` is asked and the credential row's optional fields are read.

`None` NEVER MATCHES, NOT EVEN `None`. Two rows that declare nothing have not declared that they
share anything; the local board over the local forge is the case that would otherwise read as
"owned" by accident.

A TEST DOUBLE IS NOT A DECLARATION. A `MagicMock` answers every attribute with another mock, and
the same mock handed to both axes compares equal to itself. Only a tuple of two non-empty strings
counts; anything else is `None`, which is the side of this question that cannot misname an item.

OWNING A CARD IS NOT PERMISSION TO CLOSE IT. A second, separate declaration: `closing_keyword`, an
optional string on the FORGE row, is the word that forge closes an item with at the merge. Only a
forge that declares one gets a closing line, and only on a card it owns. The two questions are
apart on purpose, because one forge's answers differ: Azure Repos owns an Azure Boards card in its
organisation and links `#1234` natively, but its row already refuses to be a second writer of the
card's state (`transitionWorkItems: False`), so it declares no keyword and the card is only named.
"""

from __future__ import annotations

import logging

log = logging.getLogger("openfactory.item_space")

#: `(the kind of numbering, the scope it is unique in)` — opaque to the core, compared whole.
ItemSpace = tuple[str, str]


def declared_space(row: object, *args: object) -> ItemSpace | None:
    """What `row` declares about where its item numbers live, or `None` when it declares nothing
    a comparison can use. Never raises: a declaration that fails is a row that did not declare, and
    the neutral side is the one that cannot write somebody else's item into a forge."""
    ask = getattr(row, "item_space", None)
    if not callable(ask):
        return None
    try:
        space = ask(*args)
    except Exception as exc:  # noqa: BLE001 — an unanswerable declaration is no declaration
        log.info("%s could not say where its item numbers live (%s) — treated as its own",
                 type(row).__name__, str(exc)[:120])
        return None
    if (isinstance(space, tuple) and len(space) == 2
            and all(isinstance(part, str) and part.strip() for part in space)):
        return space
    return None


def closing_keyword(forge: object) -> str:
    """The word `forge` closes one of its own items with at the merge (`Closes`), or "" when it
    declares none. A single word or nothing: a mock, a phrase or a non-string is no declaration, and
    "" is the side that cannot ask a forge to close something."""
    word = getattr(forge, "closing_keyword", "")
    if isinstance(word, str) and word.strip().isalpha():
        return word.strip()
    return ""


def forge_owns_the_card(tracker: object, forge: object, ticket: object) -> bool:
    """True when the forge numbers the card's items itself — so its own mention of the card (`#12`)
    names THIS card and not an item that happens to share the number."""
    theirs = declared_space(tracker, ticket)
    return theirs is not None and theirs == declared_space(forge)
