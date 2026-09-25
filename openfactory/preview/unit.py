"""What a preview is OF: one card, or the requirement it executes (ADR-0050 D1).

A person asks to see a promise kept, and a requirement is usually kept by several cards — the
front end's and the back end's — each with its own pull request. Previewing each card alone would
show a screen without the service behind it, so a card that cites a requirement is previewed AS
the requirement: one key, one cookie, one compose project, every sibling's pull request in it.

THE CITATION IS READ WHERE IT MEANS SOMETHING, AND BY THE ONE READER THAT ALREADY EXISTS. A card
cites its requirement under `## Source` (`Executes **REQ-0012** in …`, written by
`product/authoring.py::issue_body`), and a defect under the heading that names the promise it
breaks; a number in the objective is somebody explaining themselves. `product/module.py::
_cited_requirement` already reads exactly that for the repair of orphaned cards, and a second regex
here would be a second definition of "this card executes REQ-0012" the two would one day disagree
on.

A REQUIREMENT NEEDS THE PRODUCT TO BE ONE. Its siblings are found on the product's board and
bounded by the product's `sources:` (§6.2) — both of which only an active product module can
vouch for. When it is off, or unusable, the card is previewed ALONE and says why, rather than
standing for a whole requirement it can see one card of: a preview that looks like REQ-0012 and
holds a third of it answers a question nobody asked.
"""

from __future__ import annotations

from openfactory import preview
from openfactory.preview.plan import CardRef, Unit
from openfactory.product.module import _cited_requirement


def alone_because(ctx) -> str:
    """Why a card that cites a requirement is previewed as one card, or "" when it is not:
    the product context's own sentence, when the module is off or cannot be used."""
    if ctx is not None and getattr(ctx, "available", False):
        return ""
    reason = str(getattr(ctx, "reason", "") or "the product module could not be read")
    return f"previewed as one card: the product module is off — {reason}"


def unit_of(project: str, card: CardRef, body: str, *, ctx) -> Unit | None:
    """The unit `card` is previewed as: the requirement its `## Source` cites — when the product
    context `ctx` is available to find its siblings — else the card itself, with `alone` saying why
    when it cited one. None when it is neither — a card whose reference holds no number gets no
    preview rather than a made-up address.

    `ctx` is REQUIRED: every caller says what it knows of the product, so no caller can make a
    card a requirement's unit by forgetting to ask whether the requirement can be seen."""
    cited = _cited_requirement(body or "")
    alone = alone_because(ctx) if cited is not None else ""
    if cited is not None and not alone:
        return Unit(project=project, kind="requirement", id=f"REQ-{cited:04d}", cards=(card,),
                    token=f"req{cited:04d}")
    number = preview.card_of(card.ref)
    if not number:
        return None
    return Unit(project=project, kind="card", id=card.ref, cards=(card,), token=number,
                alone=alone)
