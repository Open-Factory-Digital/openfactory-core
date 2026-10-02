"""Applies what the table says follows a transition, through the ports, and records each outcome
(ADR-0055 D3, D5) — and the sweep that converges what failed.

RECORDED FIRST, APPLIED AFTER. The door writes the transition before any effect runs, so a
person's decision is never lost because the tracker blinked; each effect's outcome is then written
under (transition, effect), and a half-applied transition is visible in the record, never silent.

CONVERGED AFTER, AND NEVER BACKWARDS. The hourly sweep (`converge`) applies again every effect
that failed or never ran — but only while its transition is still the card's latest. A late effect
of an older transition is marked `superseded` instead: applying it would move a card back to a
column a person has since moved it out of, the defect this record exists to end, produced by its
own repair.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from openfactory.lifecycle import record
from openfactory.lifecycle.table import (
    CardEvent,
    Close,
    Column,
    Comment,
    Effect,
    Forget,
    Loops,
    Preview,
    Remove,
    Reopen,
    Tell,
    consequences,
    name_of,
)

log = logging.getLogger("openfactory.lifecycle.executor")

FAILED = "failed"
SUPERSEDED = "superseded"

#: How long after a cancellation narrowed a delivery the sweep asks whether what remains of it is
#: delivered already — a day of hourly rounds, each a read of the board only while one is recent.
NARROWED_FOR = timedelta(hours=24)

#: How long an effect with no outcome yet belongs to the door that recorded it. The door applies
#: effects right after recording them, in seconds; past this the process that recorded it is
#: assumed gone, and the sweep applies what it left.
PENDING_GRACE = timedelta(minutes=10)


def _one(ports, row: record.Row, effect: Effect, *, carried: bool) -> str:
    facts = row.facts or {}
    note = str(facts.get("note") or "")
    if isinstance(effect, Column):
        return ports.column(row.card, effect.key)
    if isinstance(effect, Close):
        return ports.close(row.card, delivered=effect.delivered, note=note)
    if isinstance(effect, Remove):
        return ports.remove(row.card, note=note, by=row.by, why=row.why)
    if isinstance(effect, Reopen):
        return ports.reopen(row.card)
    if isinstance(effect, Comment):
        # EVERY ROW WRITES A CLOSE'S NOTE AS THE CARD'S COMMENT (the local board, GitHub, Azure
        # DevOps and Jira each do), so on a close or a removal the door's comment IS that note — a
        # second one here is the double comment D6 ends
        return "carried by the close" if carried else ports.comment(row.card, note)
    if isinstance(effect, Loops):
        return ports.loops(row.card, effect.action, about=str(facts.get("about") or ""))
    if isinstance(effect, Tell):
        return ports.tell(row.card, notice=effect.notice, event_id=row.event_id,
                          title=str(facts.get("title") or ""),
                          removed=row.event == CardEvent.REMOVED.value,
                          opened_by=str(facts.get("opened_by") or ""),
                          conversation=str(facts.get("conversation") or ""),
                          pass_number=int(facts.get("pass_number") or 0))
    if isinstance(effect, Preview):
        return ports.preview(row.card, action=effect.action, by=row.by)
    if isinstance(effect, Forget):
        return ports.forget()
    raise TypeError(f"no port applies {effect!r}")


def apply(ports, row: record.Row, effects: tuple[Effect, ...], *, sink=None,
          only: set[int] | None = None) -> list[tuple[str, str]]:
    """Apply `effects` (all of them, or the indexes in `only`) in order; record and return what
    each came to. Never raises: one effect failing does not stop the next — a comment the tracker
    refused is no reason not to tell the requester."""
    carried = any(isinstance(e, Close | Remove) for e in effects)
    out: list[tuple[str, str]] = []
    for index, effect in enumerate(effects):
        if only is not None and index not in only:
            continue
        try:
            outcome = str(_one(ports, row, effect, carried=carried) or "done")
        except Exception as exc:  # noqa: BLE001 — recorded, and the sweep applies it again
            from openfactory.util.causes import first_message

            outcome = f"{FAILED}: {first_message(exc, limit=200)}"
            log.warning("OPENFACTORY_CARD_EFFECT_FAILED project=%s card=%s event=%s effect=%s — %s",
                        ports.name, row.card, row.event, name_of(effect), outcome)
        if sink is not None:
            record.write_outcome(sink, ports.name, row, index, outcome)
        out.append((name_of(effect), outcome))
    return out


def _due(row: record.Row, *, now: datetime) -> set[int]:
    due: set[int] = set()
    try:
        recent = now - datetime.fromisoformat(row.ts) < PENDING_GRACE
    except (ValueError, TypeError):   # a time nobody can read is not recent
        recent = False
    for index in range(len(row.effects)):
        outcome = row.outcome(index)
        if outcome.startswith(FAILED) or (not outcome and not recent):
            due.add(index)
    return due


def converge(project, *, ports=None) -> list[str]:
    """Apply again what failed or never ran, on every card of `project` whose record has some —
    only for the card's latest transition; an older one's are superseded. Returns one line per
    effect it touched; never raises (the next sweep tries again)."""
    from openfactory.lifecycle.ports import Ports

    ports = ports or Ports(project)
    said: list[str] = []
    try:
        sink = ports.sink()
        histories = record.cards(sink, ports.name)
    except Exception as exc:  # noqa: BLE001 — a store that cannot answer converges nothing now
        log.info("[%s] the card record could not be read to converge it (%s)", ports.name, exc)
        return said
    now = datetime.now(UTC)
    for card, history in histories.items():
        latest = history.latest
        for row in history.rows:
            due = _due(row, now=now)
            if not due:
                continue
            try:
                effects = consequences(CardEvent(row.event), row.facts)
            except (KeyError, ValueError):
                effects = ()
            if row.seq != latest.seq or tuple(name_of(e) for e in effects) != row.effects:
                # NEVER BACKWARDS: a newer transition decided where the card is now — or the table
                # no longer says what this one recorded, and a guess would be worse than nothing
                for index in sorted(due):
                    record.write_outcome(sink, ports.name, row, index, SUPERSEDED)
                    said.append(f"#{card} {row.event} {row.effects[index]}: {SUPERSEDED}")
                continue
            for name, outcome in apply(ports, row, effects, sink=sink, only=due):
                said.append(f"#{card} {row.event} {name}: {outcome}")
    if any(_narrowed(row, now=now) for history in histories.values() for row in history.rows):
        # A DELIVERY SHARED BY SEVERAL CARDS lost one; if the rest were delivered before, it is due
        # now, and nothing else would announce it before the weekly catch-all (D10)
        ports.deliver_what_remains()
    return said


def _narrowed(row: record.Row, *, now: datetime) -> bool:
    from openfactory.lifecycle.loops import STILL_WAITING

    try:
        recent = now - datetime.fromisoformat(row.ts) < NARROWED_FOR
    except (ValueError, TypeError):
        return False
    return recent and any(STILL_WAITING in row.outcome(i) for i, name in enumerate(row.effects)
                          if name == "loops:cancel")
