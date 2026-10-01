"""What may happen to a card, and what follows when it does — two pure tables (ADR-0055 D2, D3).

PURE, AS ADR-0033's KERNEL ASKS: no clock, no store, no tracker. The door (`card.py`) reads the
world, asks these, and applies what they answer; a reader asking "what happens when a card is
discarded?" reads one row here instead of four processes.

THE EVENT SET IS CLOSED AND WHOLE FROM THE FIRST SLICE. All of D1's events are named now, and an
event no slice has decided yet is REFUSED IN EVERY STATE and has no row of consequences: D2's
default is refusal, so an event becomes possible only when somebody writes where it may happen and
what follows it — in the same change, here. Slice 1 (#412) decides the endings a person causes:
`discarded`, `skipped`, `stopped`, `closed`, `withdrawn`, `removed`, `reopened`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class CardEvent(StrEnum):
    """What happened to a card, named from what happened and not from the column it lands in."""

    FILED = "filed"
    PROMOTED = "promoted"
    REORDERED = "reordered"
    PICKED_UP = "picked_up"
    REFUSED = "refused"
    QUESTION_ASKED = "question_asked"
    QUESTION_ANSWERED = "question_answered"
    PR_OPENED = "pr_opened"
    PARKED = "parked"
    RESUMED = "resumed"
    ADJUSTED = "adjusted"
    ACCEPTED = "accepted"
    MERGED = "merged"
    STAGED = "staged"
    STAGE_REJECTED = "stage_rejected"
    RELEASED = "released"
    DELIVERED = "delivered"
    DISCARDED = "discarded"
    SKIPPED = "skipped"
    STOPPED = "stopped"
    CLOSED = "closed"
    WITHDRAWN = "withdrawn"
    REMOVED = "removed"
    REOPENED = "reopened"
    EDITED = "edited"


class State(StrEnum):
    """Where a card is in its life — the platform's word, not the column's name (D2)."""

    BACKLOG = "backlog"
    TODO = "todo"
    RUNNING = "running"
    WAITING_ON_A_PERSON = "waiting_on_a_person"
    MERGED = "merged"
    STAGED = "staged"
    DELIVERED = "delivered"
    CLOSED = "closed"
    REMOVED = "removed"


#: The state an OPEN card is in, by the neutral column key its board placed it under
#: (`adapters/board/columns.py`). `in_review` is the factory's — review, the checks, a merge it is
#: watching — so it reads as `running`; whether a job truly holds the card there is the engine's
#: answer, which the rows still ask in this slice (`catalog._withdraw_refusal`, `_stop`).
#:
#: `merged` and `staged` are not read from a column: `in_review` holds a card both before and
#: after its merge. They become readable when the job's endings write the record (slice 2), and no
#: event of this slice turns on them.
BY_COLUMN: dict[str, State] = {
    "backlog": State.BACKLOG,
    "todo": State.TODO,
    "in_progress": State.RUNNING,
    "in_review": State.RUNNING,
    "needs_action": State.WAITING_ON_A_PERSON,
    "done": State.DELIVERED,
}

#: The ending a person causes while the factory holds the card: the work stops, the card goes back
#: to the backlog, and nothing it promised is cancelled (D10).
_BACK_TO_THE_BACKLOG = (CardEvent.DISCARDED, CardEvent.SKIPPED, CardEvent.STOPPED)

#: Where each event may happen. EVERY EVENT HAS A ROW, and a pair a row does not name is refused:
#: an empty set is "refused everywhere, because no slice has decided it yet" — written, never
#: implied (D2).
#:
#: The rows mirror what the board's own gates answered before this table existed, so nothing a
#: person could do yesterday is refused today — with one exception, the defect the inventory found:
#: `reopened` was allowed on an OPEN card, and on the local board it threw a card in progress back
#: into Backlog. It is allowed on a closed card only.
ALLOWED: dict[CardEvent, frozenset[State]] = {
    **{event: frozenset() for event in CardEvent},
    # the engine says which job is waiting on what; the column says the factory holds the card
    CardEvent.DISCARDED: frozenset({State.RUNNING, State.WAITING_ON_A_PERSON}),
    CardEvent.SKIPPED: frozenset({State.RUNNING, State.WAITING_ON_A_PERSON}),
    # a stop RESCUES a wedged job, and only the engine knows one is running (`_stop` asks it): a
    # job wedged before it moved its card leaves the card in TO-DO, or where a person dragged it
    CardEvent.STOPPED: frozenset({State.BACKLOG, State.TODO, State.RUNNING,
                                  State.WAITING_ON_A_PERSON}),
    # a close of a card a job may hold is the engine's to refuse (`_withdraw_refusal`, #191): a
    # card in Needs Action is often one no job is on, and refusing it here would strand it there
    CardEvent.CLOSED: frozenset({State.BACKLOG, State.TODO, State.RUNNING,
                                 State.WAITING_ON_A_PERSON, State.DELIVERED}),
    CardEvent.WITHDRAWN: frozenset({State.BACKLOG, State.TODO, State.RUNNING,
                                    State.WAITING_ON_A_PERSON}),
    # never once the factory finished it: what was done and said on it is history (#384)
    CardEvent.REMOVED: frozenset({State.BACKLOG, State.TODO, State.RUNNING,
                                  State.WAITING_ON_A_PERSON}),
    # a card closed as not delivered, or one closed as delivered — and only once it IS closed
    # (`ONLY_ON_A_CLOSED_CARD`): a finished card nobody closed is `delivered` too, and open
    CardEvent.REOPENED: frozenset({State.CLOSED, State.DELIVERED}),
}

#: The events that need the card CLOSED on its tracker, whatever its state says. `delivered` is a
#: card the factory finished, closed or not yet: the local board leaves it open in Done, Jira closes
#: it there (`statusCategory` done). Reopening an open card was the defect — on the local board it
#: threw a card in progress back into Backlog — so a reopen asks for the closed card itself.
ONLY_ON_A_CLOSED_CARD: frozenset[CardEvent] = frozenset({CardEvent.REOPENED})

#: The events whose legality a board that places no card cannot settle, and which are therefore
#: allowed on an open card it does not place — a tracker with no board, or a card not on it. The
#: rows' own gates still ask the engine. `reopened` is not here: a closed card is known to be closed
#: without any board.
WHERE_NO_BOARD_PLACES_IT: frozenset[CardEvent] = frozenset({
    CardEvent.DISCARDED, CardEvent.SKIPPED, CardEvent.STOPPED, CardEvent.CLOSED,
    CardEvent.WITHDRAWN, CardEvent.REMOVED})


@dataclass(frozen=True)
class Refusal:
    """Why an event may not happen to a card now. The door says it in the person's language."""

    event: CardEvent
    state: State | None


def allowed(state: State | None, event: CardEvent, *, open_card: bool = True) -> Refusal | None:
    """None when `event` may happen to a card in `state`, else why not. `state` is None for an
    open card no board places (`WHERE_NO_BOARD_PLACES_IT`); `open_card` is the tracker's own word
    on whether the card is open (`ONLY_ON_A_CLOSED_CARD`)."""
    if open_card and event in ONLY_ON_A_CLOSED_CARD:
        return Refusal(event, state)
    if state is None:
        return None if event in WHERE_NO_BOARD_PLACES_IT else Refusal(event, state)
    return None if state in ALLOWED[event] else Refusal(event, state)


# ── the effects ────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Column:
    """The card moves to the column with this neutral key."""

    key: str


@dataclass(frozen=True)
class Close:
    """The card is closed — as delivered, or as not delivered."""

    delivered: bool


@dataclass(frozen=True)
class Remove:
    """The card is removed: deleted where the tracker removes, closed as not delivered elsewhere."""


@dataclass(frozen=True)
class Reopen:
    """The card is open again."""


@dataclass(frozen=True)
class Comment:
    """One comment on the card saying who decided and why — the door's, the same on every row
    (D6). Its words are the door's to compose from the transition; on a close or a removal they
    travel as that write's note, which every row writes as the card's comment."""


@dataclass(frozen=True)
class Loops:
    """The card's share of the product role's promises (D10). `cancel`: the card is gone, so its
    questions and its part of a delivery close as `cancelled`. `restore`: a cancelled card is
    back, so is its part of the delivery it was cancelled from."""

    action: str


@dataclass(frozen=True)
class Tell:
    """The requester's conversation is told, once, what happened and where the card is."""

    notice: str


@dataclass(frozen=True)
class Preview:
    """The card's preview is taken down."""

    action: str


@dataclass(frozen=True)
class Forget:
    """What this process remembers of the board is dropped (#393)."""


Effect = Column | Close | Remove | Reopen | Comment | Loops | Tell | Preview | Forget

#: What the requester is told, by which way the work ended.
STOPPED_WORK, WILL_NOT_BE_BUILT, BACK_ON_THE_BOARD = "stopped_work", "will_not_be_built", "back"

_GONE = (Comment(), Loops("cancel"), Tell(WILL_NOT_BE_BUILT), Preview("stop"), Forget())


def consequences(event: CardEvent, facts: Mapping[str, object] | None = None) -> tuple[Effect, ...]:
    """What follows `event`, in the order it is applied. Exhaustive over the events a slice has
    decided; an undecided event has no row, because no state allows it (`ALLOWED`).

    `facts` carries what the event knows. One fact changes a row: whether a close is of finished
    work (`delivered`). A delivered close cancels nothing and tells nobody that something will not
    be built — the delivery is the delivery's to announce."""
    facts = facts or {}
    if event in _BACK_TO_THE_BACKLOG:
        # the promise stays open, and the requester is told the card is back in the backlog (D10)
        return (Column("backlog"), Comment(), Tell(STOPPED_WORK), Preview("stop"), Forget())
    if event is CardEvent.CLOSED:
        if facts.get("delivered"):
            return (Close(delivered=True), Comment(), Forget())
        return (Close(delivered=False), *_GONE)
    if event is CardEvent.WITHDRAWN:
        return (Close(delivered=False), *_GONE)
    if event is CardEvent.REMOVED:
        return (Remove(), *_GONE)
    if event is CardEvent.REOPENED:
        return (Reopen(), Comment(), Loops("restore"), Tell(BACK_ON_THE_BOARD), Forget())
    raise KeyError(f"no slice has decided what follows {event.value!r} — it is refused in every "
                   f"state until one does (ADR-0055 D2)")


def after(event: CardEvent, facts: Mapping[str, object] | None = None) -> State:
    """The state a decided event leaves the card in."""
    facts = facts or {}
    if event in _BACK_TO_THE_BACKLOG or event is CardEvent.REOPENED:
        return State.BACKLOG
    if event is CardEvent.CLOSED and facts.get("delivered"):
        return State.DELIVERED
    if event in (CardEvent.CLOSED, CardEvent.WITHDRAWN):
        return State.CLOSED
    if event is CardEvent.REMOVED:
        return State.REMOVED
    raise KeyError(f"no slice has decided where {event.value!r} leaves a card")


#: The events some slice has decided — those allowed somewhere. The derived test holds that every
#: one of them has a row in `consequences` and in `after`, and that no other event does.
DECIDED: frozenset[CardEvent] = frozenset(
    event for event, states in ALLOWED.items() if states or event in WHERE_NO_BOARD_PLACES_IT)


def name_of(effect: Effect) -> str:
    """An effect as the record writes it: its kind, and its argument where it has one."""
    kind = type(effect).__name__.lower()
    arg = next(iter(vars(effect).values()), None) if vars(effect) else None
    return f"{kind}:{str(arg).lower()}" if arg is not None else kind
