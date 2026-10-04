"""A card's share of the product role's promises, when the card is gone and when it is back
(ADR-0055 D10).

THE CARD IS GONE (`closed` as not delivered, `withdrawn`, `removed`): its questions close as
`cancelled`, and so does every delivery that waited on it alone. A delivery that spans several
cards loses this one — recorded on the loop as cancelled — and keeps waiting on the rest; it closes
when what REMAINS is delivered (`followup.delivered`), or as `cancelled` when nothing remains.

THE CARD IS BACK (`reopened`): the delivery it was cancelled from waits on it again. A loop the
cancellation had closed is opened anew from its context — the ledger never revives a closed loop
(`ledger.fold`), so the promise starts again as a new one, and says so by its new opening time.

The work stopped but the card stays (`discarded`, `skipped`, `stopped`) touches nothing here: the
promise is still possible and stays open, and the card line says the card is in the backlog.
"""

from __future__ import annotations

from dataclasses import replace

#: How a cancellation that left a delivery waiting on other cards says so in the record — the
#: hourly sweep reads it to see whether what remains is delivered already (`executor.converge`).
STILL_WAITING = "still waiting on the rest"


def _issues(loop) -> set[str]:
    from openfactory.product.events import issues_of

    return issues_of(loop)


def _joined(cards: set[str]) -> str:
    return ",".join(sorted(cards))


def cancel(project, card: str) -> tuple[str, bool]:
    """Close what the product role promised about `card` alone, and take `card` out of what it
    shares. Returns what it did, as the record's outcome, and whether a delivery still waits on
    other cards — the one that may be due now (`Ports.loops`). Raises when the ledger cannot be
    written, so the sweep applies it again."""
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import (
        CANCELLED,
        CANCELLED_CARDS,
        CARD_QUESTION,
        CLOSED,
        DELIVERY,
        fold,
    )
    from openfactory.product.followup import cancelled_cards

    name = getattr(project, "name", "") or ""
    rows: list = []
    narrowed = closed = 0
    for loop in fold(loop_store.read(name)):
        if not loop.waiting:
            continue
        if loop.kind == CARD_QUESTION and _bare(loop.subject) == _bare(card):
            rows.append(replace(loop, state=CLOSED, outcome=CANCELLED))
            closed += 1
        elif loop.kind == DELIVERY and card in _issues(loop):
            gone = cancelled_cards(loop) | {card}
            ctx = {**(loop.context or {}), CANCELLED_CARDS: _joined(gone)}
            if _issues(loop) - gone:
                rows.append(replace(loop, context=ctx))
                narrowed += 1
            else:
                rows.append(replace(loop, context=ctx, state=CLOSED, outcome=CANCELLED))
                closed += 1
    if not rows:
        return "nothing was promised about it", False
    if loop_store.write(name, rows) < len(rows):
        raise RuntimeError("the ledger did not take every row")
    return f"{closed} closed as cancelled, {narrowed} {STILL_WAITING}", bool(narrowed)


def restore(project, card: str) -> str:
    """Put `card` back into the delivery it was cancelled from — the newest one per requirement."""
    from openfactory.adapters.board_db import now_iso
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import CANCELLED, CANCELLED_CARDS, DELIVERY, fold, open_loop
    from openfactory.product.followup import cancelled_cards

    name = getattr(project, "name", "") or ""
    newest: dict[tuple[str, str], object] = {}
    for loop in fold(loop_store.read(name)):
        if loop.kind != DELIVERY or card not in cancelled_cards(loop):
            continue
        if loop.waiting or loop.outcome == CANCELLED:
            key = (loop.subject, loop.about)
            if key not in newest or loop.ts > newest[key].ts:
                newest[key] = loop
    rows: list = []
    for loop in newest.values():
        gone = cancelled_cards(loop) - {card}
        ctx = {k: v for k, v in (loop.context or {}).items() if k != CANCELLED_CARDS}
        if gone:
            ctx[CANCELLED_CARDS] = _joined(gone)
        rows.append(replace(loop, context=ctx) if loop.waiting else
                    open_loop(DELIVERY, loop.subject, owner=loop.owner, about=loop.about,
                              ts=now_iso(), context=ctx))
    if not rows:
        return "nothing had been cancelled about it"
    if loop_store.write(name, rows) < len(rows):
        raise RuntimeError("the ledger did not take every row")
    return f"{len(rows)} waiting on it again"


def _bare(ref: str) -> str:
    from openfactory.contracts.refs import canonical_ref

    return canonical_ref(ref)
