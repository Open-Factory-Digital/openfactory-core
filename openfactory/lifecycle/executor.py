"""Applies what the table says follows a transition, through the ports, and records each outcome
(ADR-0055 D3, D5) — and the sweep that converges what failed.

RECORDED FIRST, APPLIED AFTER. The door writes the transition before any effect runs, so a
person's decision is never lost because the tracker blinked; each effect's outcome is then written
under (transition, effect), and a half-applied transition is visible in the record, never silent.

CONVERGED AFTER, AND NEVER BACKWARDS. The hourly sweep (`converge`) applies again every effect
that failed or never ran — but only while no newer transition has MOVED the card. A late effect
of an older transition is marked `superseded` instead: applying it would move a card back to a
column a person has since moved it out of, the defect this record exists to end, produced by its
own repair. A promise moves nothing (`table.MOVES_NOTHING`, #414), so it supersedes nothing: a
filing whose placement failed is still placed when a requirement's promise was recorded after it.

ONE ROW STOPS AT A FAILED WRITE (`table.STOPS_AT_A_FAILED_WRITE`, #414): a question waits only on
a card that was parked for it. Its caller goes on without what failed, so what follows is not
applied and the sweep leaves the row alone.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from openfactory.lifecycle import record
from openfactory.lifecycle.table import (
    MERGED_FOR_YOU,
    RELEASE_ASKS,
    RELEASE_CLOSES,
    STAGED_FOR_YOU,
    STOPS_AT_A_FAILED_WRITE,
    TRIED,
    WRITES_THE_CARD,
    CardEvent,
    Close,
    Column,
    Comment,
    Effect,
    Forget,
    Loops,
    Place,
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
#: What an effect after a failed write comes to, on a row that stops there.
NOT_APPLIED = "not applied"

#: The record's names for the effects that write the card (`name_of`'s kind).
_WRITE_NAMES = frozenset(kind.__name__.lower() for kind in WRITES_THE_CARD)

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
        if effect.needs_person is None:
            return ports.column(row.card, effect.key)
        # who the blocker is, where only the caller knew it (#166): a pull request's gate
        return ports.column(row.card, effect.key, needs_person=effect.needs_person)
    if isinstance(effect, Place):
        # the board's own name for the column when the caller holds it (what the person named,
        # or the module's constant); else the port asks the platform's own name for the key
        return ports.place(row.card, effect.key, name=str(facts.get("column_name") or ""))
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
        if effect.action == "open":
            # THE PROMISE A FILING MAKES, as the filing carried it (#414)
            return ports.loops(row.card, effect.action, owed=dict(facts.get("owed") or {}))
        if effect.action in RELEASE_ASKS | RELEASE_CLOSES:
            # THE RELEASE QUESTION (#448 slice 6): asked as the round asked it — when, where to
            # look, which run — and closed for the card the transition is about
            return ports.loops(row.card, effect.action, release=_release_facts(facts))
        # `asked` is the loop a question opens, as its asker composed it (`_do_gather`); the
        # title is how a delivery finds the card a split card was split from
        # (`loops.announce_what_it_completes`)
        return ports.loops(row.card, effect.action, about=str(facts.get("about") or ""),
                           context=dict(facts.get("asked") or {}),
                           title=str(facts.get("title") or ""))
    if isinstance(effect, Tell):
        return ports.tell(row.card, notice=effect.notice, event_id=row.event_id,
                          title=str(facts.get("title") or ""),
                          removed=row.event == CardEvent.REMOVED.value,
                          opened_by=str(facts.get("opened_by") or ""),
                          conversation=str(facts.get("conversation") or ""),
                          pass_number=int(facts.get("pass_number") or 0),
                          pr_url=str(facts.get("pr_url") or ""),
                          review=str(facts.get("review") or ""),
                          preview_url=str(facts.get("preview_url") or ""),
                          **_loop_facts(effect.notice, facts))
    if isinstance(effect, Preview):
        return ports.preview(row.card, action=effect.action, by=row.by)
    if isinstance(effect, Forget):
        return ports.forget()
    raise TypeError(f"no port applies {effect!r}")


#: What the release question's port reads from a transition's facts (`ports.loops`).
_RELEASE_FACTS = ("asked_at", "run", "where", "requirement", "room")


def _release_facts(facts) -> dict[str, str]:
    return {key: str(facts.get(key) or "") for key in _RELEASE_FACTS}


def _loop_facts(notice: str, facts) -> dict[str, object]:
    """What a telling of the requester's loop past the pull request carries beyond the card's own
    (#448 slice 6) — handed only to those, so a port written before them is called as it was."""
    if notice == MERGED_FOR_YOU:
        return {"stages_follow": bool(facts.get("stages_follow"))}
    if notice in (STAGED_FOR_YOU, TRIED):
        return {"where": str(facts.get("where") or ""), "run": str(facts.get("run") or ""),
                "who": str(facts.get("who") or "")}
    return {}


def _stops(row: record.Row) -> bool:
    """Whether `row`'s event stops at a failed write to the card (`STOPS_AT_A_FAILED_WRITE`)."""
    try:
        return CardEvent(row.event) in STOPS_AT_A_FAILED_WRITE
    except ValueError:
        return False


def apply(ports, row: record.Row, effects: tuple[Effect, ...], *, sink=None,
          only: set[int] | None = None) -> list[tuple[str, str]]:
    """Apply `effects` (all of them, or the indexes in `only`) in order; record and return what
    each came to. Never raises: one effect failing does not stop the next — a comment the tracker
    refused is no reason not to tell the requester — EXCEPT on a row that stops at a failed write
    (`STOPS_AT_A_FAILED_WRITE`), where what follows the failed write is recorded `not applied`."""
    carried = any(isinstance(e, Close | Remove) for e in effects)
    stops, stopped_at = _stops(row), ""
    out: list[tuple[str, str]] = []
    for index, effect in enumerate(effects):
        if only is not None and index not in only:
            continue
        if stopped_at:
            outcome = f"{NOT_APPLIED}: {stopped_at} did not land"
        else:
            try:
                outcome = str(_one(ports, row, effect, carried=carried) or "done")
            except Exception as exc:  # noqa: BLE001 — recorded, and the sweep applies it again
                from openfactory.util.causes import first_message

                outcome = f"{FAILED}: {first_message(exc, limit=200)}"
                log.warning("OPENFACTORY_CARD_EFFECT_FAILED project=%s card=%s event=%s "
                            "effect=%s — %s", ports.name, row.card, row.event, name_of(effect),
                            outcome)
            if stops and outcome.startswith(FAILED) and isinstance(effect, WRITES_THE_CARD):
                stopped_at = name_of(effect)
        if sink is not None:
            record.write_outcome(sink, ports.name, row, index, outcome)
        out.append((name_of(effect), outcome))
    return out


def _due(row: record.Row, *, now: datetime) -> set[int]:
    due: set[int] = set()
    if _stops(row) and any(row.outcome(i).startswith(FAILED) for i, name in
                           enumerate(row.effects) if name.split(":")[0] in _WRITE_NAMES):
        # THE ROW STOPPED AT A FAILED WRITE, AND ITS CALLER WENT ON WITHOUT IT: the gather let the
        # work proceed when the park did not land, so a park applied now would stop a card its job
        # is working on (`STOPS_AT_A_FAILED_WRITE`)
        return due
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
    only for the card's latest move and the promises after it; an older one's are superseded.
    Returns one line per effect it touched; never raises (the next sweep tries again)."""
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
        # THE LATEST MOVE, NOT THE LATEST ROW (#414): a promise recorded after a filing moves
        # nothing, so it supersedes nothing — the filing's failed placement is still applied
        moved = history.latest_move
        for row in history.rows:
            due = _due(row, now=now)
            if not due:
                continue
            try:
                effects = consequences(CardEvent(row.event), row.facts)
            except (KeyError, ValueError):
                effects = ()
            if ((moved is not None and row.seq < moved.seq)
                    or tuple(name_of(e) for e in effects) != row.effects):
                # NEVER BACKWARDS: a newer move decided where the card is now — or the table
                # no longer says what this one recorded, and a guess would be worse than nothing
                for index in sorted(due):
                    record.write_outcome(sink, ports.name, row, index, SUPERSEDED)
                    said.append(f"#{card} {row.event} {row.effects[index]}: {SUPERSEDED}")
                continue
            for name, outcome in apply(ports, row, effects, sink=sink, only=due):
                said.append(f"#{card} {row.event} {name}: {outcome}")
    if any(_narrowed(row, now=now) for history in histories.values() for row in history.rows):
        # A DELIVERY SHARED BY SEVERAL CARDS lost one; if the rest were delivered before, it is due
        # now, and no card's transition is left to announce it (D10)
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
