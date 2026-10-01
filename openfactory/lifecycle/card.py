"""The card's one door: `transition` (ADR-0055 D1).

    transition(project, card, event, *, by, why, facts)  ->  Transition

THE ONLY WAY A CARD CHANGES STATE — for the events a slice has moved through it. In order:

  1. the card's record is read, and THE SAME EVENT ARRIVING AGAIN (a retried request, a double
     click) is answered from its own row: nothing is decided twice, and a retry is never refused
     for a transition that in fact succeeded (D5, the event id first);
  2. the card is read where it is (`Ports.seen`) and `allowed` is asked: a refused transition
     changes nothing and says why, in the project's language (D2);
  3. `act`, when the caller has one, runs — the engine's half of a person's decision (a signal to
     a parked job, a merge gate's answer, a terminate). Its refusal is the caller's to return, and
     nothing is recorded or applied;
  4. the transition is recorded at the card's next sequence number, ONLY IF NO OTHER TRANSITION
     TOOK IT; a writer that lost the race reads the card again and decides again, against what the
     winner made true (D5, the sequence number second);
  5. what the table says follows is applied through the ports, each outcome recorded, and what
     failed is the hourly sweep's to converge (`executor.converge`).

A STORE THAT CANNOT KEEP THE RECORD DOES NOT STOP A PERSON'S DECISION. The record is refused for
it by name (`record.keyed_sink`), and the transition is applied unrecorded and says so
(`Transition.recorded`). A deployment with no metrics store at all has no ledger and no record of
anything, and refusing every close there would be a worse failure than the record it cannot keep.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from openfactory.lifecycle import executor, record
from openfactory.lifecycle.table import (
    CardEvent,
    State,
    after,
    allowed,
    consequences,
    name_of,
)

log = logging.getLogger("openfactory.lifecycle.card")

#: How many times a writer that lost the race for a card's next number reads and decides again.
_RACES = 3


@dataclass(frozen=True)
class Transition:
    """What the door did with one event. `refused` is the sentence when nothing changed; `answer`
    is the caller's `act`'s own refusal, returned untouched when the engine said no."""

    card: str
    event: CardEvent
    event_id: str = ""
    seq: int = 0
    before: State | None = None
    after: State | None = None
    effects: tuple[tuple[str, str], ...] = ()
    refused: str = ""
    answer: object = None
    recorded: bool = False
    replayed: bool = False
    facts: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.refused and self.answer is None

    def outcome(self, kind: str) -> str:
        """The outcome of the first effect whose name starts with `kind` (`close`, `tell`, …)."""
        return next((o for n, o in self.effects if n.split(":")[0] == kind), "")

    @property
    def failed(self) -> list[str]:
        return [f"{n}: {o}" for n, o in self.effects if o.startswith(executor.FAILED)]


def _event_id(project_name: str, card: str, event: CardEvent, seq: int) -> str:
    """The id of a decision about `card` at its `seq`-th transition — two clicks on one button
    before either landed carry the same one, and are one transition."""
    digest = hashlib.sha256(f"{project_name}|{card}|{event.value}|{seq}".encode()).hexdigest()
    return f"{event.value}-{digest[:20]}"


_UNRECORDED_SAID: set[str] = set()


def _sink(ports):
    try:
        return ports.sink()
    except record.Unrecordable as exc:
        if ports.name not in _UNRECORDED_SAID:
            _UNRECORDED_SAID.add(ports.name)
            log.warning("OPENFACTORY_CARD_RECORD_REFUSED project=%s — %s; a card's transitions "
                        "are applied unrecorded here, and the sweep has nothing to converge",
                        ports.name, exc)
        return None


def transition(project, card: str, event: CardEvent, *, by: str, why: str = "",
               facts: Mapping[str, object] | None = None, event_id: str = "",
               act: Callable[[], object] | None = None, tracker=None, board=None,
               columns: dict[str, str] | None = None, ports=None) -> Transition:
    """Move `card` through `event`, decided by `by` because `why`. See the module for the order.
    Never raises: a refusal is a `Transition` with `refused`, and a port that failed is an outcome
    the sweep converges."""
    from openfactory.contracts.refs import canonical_ref
    from openfactory.lifecycle.ports import Ports
    from openfactory.product.voice import card_note, card_raced, card_refused

    card = canonical_ref(card)
    event = CardEvent(event)
    ports = ports or Ports(project, tracker=tracker, board=board, columns=columns)
    language = getattr(project, "language", None)
    sink = _sink(ports)
    first_id = event_id
    acted = False
    for _ in range(_RACES):
        history = record.History()
        if sink is not None:
            try:
                history = record.read(sink, ports.name, card)
            except Exception as exc:  # noqa: BLE001 — an unread history is not an empty one
                log.error("OPENFACTORY_CARD_RECORD_UNREAD project=%s card=%s — %s; this "
                          "transition is applied unrecorded", ports.name, card, exc)
                sink = None
        this_id = event_id or _event_id(ports.name, card, event, history.next_seq)
        first_id = first_id or this_id
        again = history.by_event_id(first_id)
        if again is not None:
            return Transition(card=card, event=event, event_id=again.event_id, seq=again.seq,
                              before=_state(again.before), after=_state(again.after),
                              effects=tuple((n, again.outcome(i))
                                            for i, n in enumerate(again.effects)),
                              recorded=True, replayed=True, facts=dict(again.facts))
        seen = ports.seen(card)
        if seen.cannot_tell:
            return Transition(card=card, event=event, refused=seen.cannot_tell)
        refusal = allowed(seen.state, event, open_card=seen.open)
        if refusal is not None and acted and seen.state is after(event, {**(facts or {}),
                                                                        "before": ""}):
            # THE ENGINE ACTED, AND THE JOB'S OWN ENDING GOT THERE FIRST: a person's skip signals
            # the job, whose settle can record before this row does (#413). The card is already
            # where this decision leaves it — the decision stands, and nothing is applied twice.
            return Transition(card=card, event=event, before=seen.state, after=seen.state)
        if refusal is not None:
            if acted:
                log.error("OPENFACTORY_CARD_ACTED_UNRECORDED project=%s card=%s event=%s — the "
                          "engine acted, and a transition recorded meanwhile makes this one "
                          "refused", ports.name, card, event.value)
            return Transition(card=card, event=event, before=seen.state, refused=card_refused(
                event.value, state=(seen.state.value if seen.state else ""), ref=card,
                language=language))
        if act is not None and not acted:
            answer = act()
            if answer is not None:
                return Transition(card=card, event=event, before=seen.state, answer=answer)
            acted = True
        known = dict(facts or {})
        # where the card was, for the rows whose consequences turn on it (`question_answered`)
        known["before"] = seen.state.value if seen.state else ""
        known.setdefault("title", seen.title)
        known.setdefault("opened_by", seen.opened_by)
        # WHERE THE REQUESTER ASKED, READ BEFORE ANYTHING IS APPLIED: the card's delivery loop
        # says it, and a cancellation closes that loop — so a telling applied after it, or by the
        # sweep an hour later, would find nobody's conversation and say it to the room
        known.setdefault("conversation", ports.asked_in(card))
        if "note" not in known:     # the caller's own words win, and only then is one composed
            known["note"] = card_note(event.value, who=by, why=why, language=language)
        effects = consequences(event, known)
        row = record.Row(card=card, seq=history.next_seq, event_id=this_id, event=event.value,
                         by=by, why=why, before=seen.state.value if seen.state else "",
                         after=after(event, known).value,
                         effects=tuple(name_of(e) for e in effects), facts=known)
        recorded = False
        if sink is not None:
            try:
                if not record.write(sink, ports.name, row):
                    continue          # another transition took this number: read, decide again
                recorded = True
            except Exception as exc:  # noqa: BLE001 — the decision stands; only its record failed
                log.error("OPENFACTORY_CARD_RECORD_UNWRITTEN project=%s card=%s event=%s — %s; "
                          "applied unrecorded", ports.name, card, event.value, exc)
                sink = None
        done = executor.apply(ports, row, effects, sink=sink if recorded else None)
        return Transition(card=card, event=event, event_id=this_id, seq=row.seq,
                          before=seen.state, after=after(event, known), effects=tuple(done),
                          recorded=recorded, facts=known)
    return Transition(card=card, event=event, refused=card_raced(ref=card, language=language))


def _state(value: str) -> State | None:
    try:
        return State(value) if value else None
    except ValueError:
        return None


#: The endings that leave a card in the backlog with its promise still open (D10).
_STOPPED_THERE = frozenset({CardEvent.DISCARDED.value, CardEvent.SKIPPED.value,
                            CardEvent.STOPPED.value})


def back_in_the_backlog(project, card: str) -> bool:
    """Whether `card` is in the backlog because a person ended the work on it — its record's latest
    transition is a discard, a skip or a stop — rather than because it was filed there and nobody
    has started it. False when the record cannot say: "the work stopped" is a claim, and a card
    nobody can account for is not said to have one."""
    from openfactory.contracts.refs import canonical_ref

    try:
        latest = record.read(record.keyed_sink(), getattr(project, "name", "") or "",
                             canonical_ref(card)).latest
    except Exception:  # noqa: BLE001 — see the docstring: unknown is not "stopped"
        log.info("could not read #%s's record to tell why it is in the backlog", card,
                 exc_info=True)
        return False
    return latest is not None and latest.event in _STOPPED_THERE
