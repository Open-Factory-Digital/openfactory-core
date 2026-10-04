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

THE CARD IS FILED, AND SOMEBODY IS OWED IT (`filed` carrying `owed`, #414): the delivery a reported
defect or a card asked for in a conversation is owed opens with the filing, through the card's
door — so it is recorded with the transition that made it, and a filing whose promise could not be
written is the hourly sweep's to open again. A requirement's delivery is not opened here: it
spans several cards, some the breakdown reused rather than filed, and no one card's filing is it.

THE FACTORY ASKS (`question_asked`, #414): the question it put to the requester on the card opens,
for the card-question sweep to close when the answer arrives (ADR-0048 §6).

THE CARD IS DELIVERED (`delivered`, or closed as finished work, #414): every delivery it completes
is announced to the conversation its requester asked in, closed, and its "did it work?" opened —
the one place a delivery is announced (`announce`), reached only through the door: a transition's
`Loops("deliver")` — the job's settle, the box's hand-back at its last stage, a person's close, a
close observed on the vendor's own screen — and the converge of a delivery a cancellation
narrowed (`Ports.deliver_what_remains`). The job's exit and the weekly sweep announced it beside
the door until #414; the sweep's second chance is the door's converge now.
"""

from __future__ import annotations

import logging
from dataclasses import replace

log = logging.getLogger("openfactory.lifecycle.loops")

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
        DELIVERY,
        close_by_observation,
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
            rows += close_by_observation([loop], {(loop.kind, loop.subject, loop.about):
                                                  CANCELLED})
            closed += 1
        elif loop.kind == DELIVERY and card in _issues(loop):
            gone = cancelled_cards(loop) | {card}
            ctx = {**(loop.context or {}), CANCELLED_CARDS: _joined(gone)}
            if _issues(loop) - gone:
                rows.append(replace(loop, context=ctx))      # still waiting, on the rest
                narrowed += 1
            else:
                # the ledger's own closer, over the loop as it now reads (which card went)
                rows += close_by_observation([replace(loop, context=ctx)], {
                    (loop.kind, loop.subject, loop.about): CANCELLED})
                closed += 1
    if not rows:
        return "nothing was promised about it", False
    if loop_store.write(name, rows) < len(rows):
        raise RuntimeError("the ledger did not take every row")
    return f"{closed} closed as cancelled, {narrowed} {STILL_WAITING}", bool(narrowed)


def owe(project, card: str, owed) -> str:
    """Open the delivery `card` is owed — `owed` is what its filing carried: the loop's subject
    and its context (who asked, and where, as `followup.delivered_to` keeps them). ONE LOOP PER
    SUBJECT, as it always was: a promise already waiting is not opened again, so a retried filing
    or the sweep applying it again opens nothing twice. Raises when the ledger cannot be written,
    so the sweep applies it again."""
    from openfactory.adapters.board_db import now_iso
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import DELIVERY, open_loop, waiting

    name = getattr(project, "name", "") or ""
    subject = str((owed or {}).get("subject") or "")
    if not subject:
        return "nothing owed: the filing named no promise"
    if subject in {x.subject for x in waiting(loop_store.read(name)) if x.kind == DELIVERY}:
        return f"{subject} was owed already"
    context = {"issues": card, **{str(k): str(v) for k, v in
                                  dict((owed or {}).get("context") or {}).items()}}
    if loop_store.write(name, [open_loop(DELIVERY, subject, owner="product", ts=now_iso(),
                                         context=context)]) < 1:
        raise RuntimeError("the ledger did not take the promise")
    return f"{subject} owed"


def question(project, card: str, *, about: str, answered: bool) -> str:
    """Close the question the factory asked on `card` (`about` names which, `""` every one): as
    answered, or as cancelled when the card is gone and nobody will ever pick it up (#413)."""
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import CANCELLED, CARD_QUESTION, close_by_observation, fold

    name = getattr(project, "name", "") or ""
    open_now = [loop for loop in fold(loop_store.read(name))
                if loop.waiting and loop.kind == CARD_QUESTION
                and _bare(loop.subject) == _bare(card) and (not about or loop.about == about)]
    # THE LEDGER'S OWN CLOSER, never a hand-built closed row: `close_by_observation` is the one
    # place a loop is closed, and what keeps a settled outcome from being written twice
    rows = close_by_observation(open_now, {
        (x.kind, x.subject, x.about): "answered" if answered else CANCELLED for x in open_now})
    if not rows:
        return "no question was open on it"
    if loop_store.write(name, rows) < len(rows):
        raise RuntimeError("the ledger did not take every row")
    return f"{len(rows)} closed as {'answered' if answered else CANCELLED}"


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


def ask(project, card: str, *, about: str, context: dict) -> str:
    """Open the question the factory just put to `card`'s requester (ADR-0048 §5): `about` is the
    question's hash, `context` what the sweep that reads the answer needs — who was asked, by
    whom, when, about which files. The same question already waiting is not opened twice, so the
    sweep applying this again opens nothing. Raises when the ledger cannot be written."""
    from openfactory.adapters.board_db import now_iso
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import CARD_QUESTION, open_loop, waiting

    name = getattr(project, "name", "") or ""
    subject = _bare(card)
    if any(x.subject == subject and x.about == about
           for x in waiting(loop_store.read(name), kind=CARD_QUESTION)):
        return "already waiting on an answer"
    # THE ASKER'S CLOCK, NOT THIS ONE: the sweep reads only what was said on the card after the
    # question was asked, and the loop's opening time is that moment
    ts = str(context.get("asked_at") or "") or now_iso()
    if loop_store.write(name, [open_loop(CARD_QUESTION, subject, owner="techlead", about=about,
                                         ts=ts, context=dict(context))]) < 1:
        raise RuntimeError("the ledger did not take the question")
    return "1 opened"


def announce_what_it_completes(project, card: str, *, title: str = "") -> str:
    """What `card`, now delivered, completes (#414): every open delivery that waits on this card, or
    on the card it was split from (a split card's delivery is its parent's,
    `triage.delivered_numbers`), and whose work is ALL delivered, is announced (`announce`). Cheap
    when there is nothing to say — the ledger is read first, and the board only when such a
    delivery is open.

    ONLY WHAT THIS CARD COMPLETES, recorded once per card: a delivery due on cards none of which is
    this one is not its transition's to say — a card closed beside the door is said when the door
    sees it (`observe`), and a delivery a cancellation narrowed is said by the door's converge
    (`Ports.deliver_what_remains`). Announcing them here would put another card's news on this
    card's record, and make every delivery the hidden catch-all the weekly sweep was.

    RAISES WHEN NOTHING COULD BE DECIDED OR SAID — the board could not be read, or the
    conversation did not take a due announcement — so the door's converge applies it again, on
    the hourly round and the weekly sweep, where a weekly catch-all beside the door used to be the
    only second chance."""
    from openfactory.contracts.refs import split_parent_of
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import DELIVERY, waiting
    from openfactory.product import events

    if not events._speaks(project):
        return "nobody to tell: the project has no product role"
    name = getattr(project, "name", "") or ""
    mine = {_bare(card), split_parent_of(title)} - {""}
    if not any(x.kind == DELIVERY and events.issues_of(x) & mine
               for x in waiting(loop_store.read(name), owner=events.OWNER)):
        return "nothing was promised about it"
    delivered = events._delivered_now(project)
    if delivered is None:
        raise RuntimeError("the board could not be read to see what it delivered")
    written, missed = announce(project, delivered=delivered, cards=mine)
    if missed:
        raise RuntimeError(f"{missed} announcement(s) the conversation did not take")
    closed = sum(1 for x in written if x.kind == DELIVERY)
    return f"{closed} announced" if closed else "nothing it completes is due yet"


def announce(project, *, delivered: set[str], cards: set[str] | None = None) -> tuple[list, int]:
    """ANNOUNCE EVERY OPEN DELIVERY WHOSE WORK IS ALL DELIVERED — of those that wait on `cards`,
    when a card's transition asks (`announce_what_it_completes`); of all of them, when nothing is
    left to ask (a delivery a cancellation narrowed, `Ports.deliver_what_remains`). Returns the
    rows written — each delivery closed, and the acceptance loop its announcement opened — and how
    many due ones were NOT announced (the conversation did not take one, or another telling held
    the lock).

    TO ITS REQUESTER'S CONVERSATION, the one recorded on the loop (`conversation`), else the room.
    The sentence is the one the sweep always said — the requirement's or the fix's — with the "did
    it work?" whose answer closes the acceptance loop (ADR-0025).

    UNDER THE TELLING LOCK, RE-READ INSIDE IT: whoever comes second finds the loop closed and says
    nothing. The loop closes only once the door TOOK the announcement — one it did not take stays
    open for the next telling (ADR-0021: closed on observation, never on self-report). Moved here
    from `events.deliver` (#414): the delivery's loop is the card's promise, and closes with it."""
    from datetime import UTC, datetime

    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import DELIVERY, close_by_observation, waiting
    from openfactory.product import events, followup

    if not events._speaks(project) or not delivered:
        return [], 0
    name = getattr(project, "name", "") or ""
    agent, language = events._agent(project), events._language(project)
    written: list = []
    missed = 0
    try:
        with events._held(project, required=False):
            open_now = waiting(loop_store.read(name), owner=events.OWNER)
            # ALL OF ITS WORK, NEVER SOME — the one rule for it (`followup.delivered`)
            due = followup.delivered(open_now, delivered)
            for loop in [x for x in open_now if (x.kind, x.subject, x.about) in due
                         and (cards is None or events.issues_of(x) & cards)]:
                where = (str((loop.context or {}).get("conversation") or "")
                         or events.room_of(project))
                text = (followup.delivered_text(loop, agent_name=agent, language=language)
                        + followup.acceptance_question(loop, agent_name=agent,
                                                       language=language))
                if not events._tell(project, id=events._event_id(events.DELIVERED, project,
                                                                  *loop.key),
                                    conversation=where, text=text):
                    missed += 1
                    continue
                rows = close_by_observation([loop], {(DELIVERY, loop.subject, loop.about):
                                                     "delivered"})
                asked = followup.acceptance_of(
                    replace(loop, context={**(loop.context or {}), "channel": where}),
                    ts=datetime.now(UTC).isoformat())
                # THE ACCEPTANCE LIVES WHERE IT WAS ASKED: its conversation, and whom it is for
                # as the delivery recorded them — a digest (`agenda.audience`)
                whom = str((loop.context or {}).get("requester") or "")
                rows.append(replace(asked, context={
                    **(asked.context or {}), "conversation": where,
                    **({"requester": whom} if whom else {})}))
                loop_store.write(name, rows)
                written += rows
    except TimeoutError as exc:
        log.warning("[%s] another telling held the lock past %ss (%s) — the deliveries it did not "
                    "announce stay open for the next", name, events._WAIT_SECONDS, exc)
        missed = max(missed, 1)
    return written, missed


def _bare(ref: str) -> str:
    from openfactory.contracts.refs import canonical_ref

    return canonical_ref(ref)
