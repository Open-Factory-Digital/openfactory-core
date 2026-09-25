"""What a preview is OF: one card, or the requirement it executes (ADR-0050 D1).

A person asks to see a promise kept, and a requirement is usually kept by several cards — the
front end's and the back end's — each with its own pull request. Previewing each card alone would
show a screen without the service behind it, so a card that cites a requirement is previewed AS
the requirement: one key, one cookie, one compose project, every sibling's pull request in it.

THE CITATION IS READ WHERE IT MEANS SOMETHING, AND BY THE ONE READER THAT ALREADY EXISTS. A card
cites its requirement under `## Source` (`Executes **REQ-0012** in …`, written by
`product/authoring.py::issue_body`); a number in the objective is somebody explaining themselves.
`product/module.py::_cited_requirement` already reads exactly that section for the repair of
orphaned cards, and a second regex here would be a second definition of "this card executes
REQ-0012" the two would one day disagree on.
"""

from __future__ import annotations

from openfactory import preview
from openfactory.preview.plan import CardRef, Unit
from openfactory.product.module import _cited_requirement


def unit_of(project: str, card: CardRef, body: str) -> Unit | None:
    """The unit `card` is previewed as: the requirement its `## Source` cites, else the card
    itself. None when it is neither — a card whose reference holds no number gets no preview
    rather than a made-up address."""
    cited = _cited_requirement(body or "")
    if cited is not None:
        return Unit(project=project, kind="requirement", id=f"REQ-{cited:04d}", cards=(card,),
                    token=f"req{cited:04d}")
    number = preview.card_of(card.ref)
    if not number:
        return None
    return Unit(project=project, kind="card", id=card.ref, cards=(card,), token=number)
