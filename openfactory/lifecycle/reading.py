"""The requester's reading of a card's life — seven steps, read from its record (ADR-0055 D12,
#448 slice 6).

THE RECORD SAYS WHAT HAPPENED; THE PERSON WHO ASKED FOLLOWS SEVEN STEPS OF IT. A card's record is
every transition in order (`record.History`): filed, queued, a pull request, a pass, a merge, a
stage, a delivery, and the moves of the operator's columns between them. The person who asked for
the card follows only what is theirs to know — the change is ready to try, it is being adjusted,
they accepted it, it went in, it is on a stage, it was released, it is delivered — and before this
each surface derived that from comments, columns and journal lines, which disagreed.

PURE, AS THE TABLES ARE: no clock, no store, no tracker. Handed a card's history, `step` answers
the step the card is at and the steps it walked, in order; nothing else decides which transition
is which step.

    preview ready   a pull request a person decides (`pr_opened` with `needs_person`), and every
                    pass a person asked for, ready to try again (`adjusted`)
    adjusting       a pass sent back (`resumed`), and a "not yet" at a stage whose words become
                    the next pass (`stage_rejected`)
    accepted        the requester's "that's it" (`accepted`)
    merged          the change went in (`merged`)
    in staging      on a stage, before it reaches everyone (`staged`)
    released        the yes that put it in front of everyone (`released`)
    delivered       the last declared stage reached (`delivered`, or a close as delivered)

A CARD WHOSE WORK ENDED ANY OTHER WAY IS AT NO STEP: sent back to the backlog, taken off the
table, reopened, refused, parked — the steps are the loop's, and that card left it. A transition
that moves nothing of the loop (a filing, a queueing, an edit, a promise, a question) leaves the
card at the step it was at.
"""

from __future__ import annotations

from dataclasses import dataclass

PREVIEW_READY = "preview ready"
ADJUSTING = "adjusting"
ACCEPTED = "accepted"
MERGED = "merged"
IN_STAGING = "in staging"
RELEASED = "released"
DELIVERED = "delivered"

#: The seven steps, in the order a card that goes the whole way walks them first.
STEPS: tuple[str, ...] = (PREVIEW_READY, ADJUSTING, ACCEPTED, MERGED, IN_STAGING, RELEASED,
                          DELIVERED)

#: The step each event of the loop is, where it is one regardless of its facts.
_BY_EVENT: dict[str, str] = {
    "adjusted": PREVIEW_READY,
    "resumed": ADJUSTING,
    "stage_rejected": ADJUSTING,
    "accepted": ACCEPTED,
    "merged": MERGED,
    "staged": IN_STAGING,
    "released": RELEASED,
    "delivered": DELIVERED,
}

#: The events that take a card out of the loop: its work ended, and no step is its.
_OUT_OF_THE_LOOP = frozenset({"discarded", "skipped", "stopped", "withdrawn", "removed",
                              "reopened", "refused", "parked"})


@dataclass(frozen=True)
class Reading:
    """Where the card is in its requester's loop (`now`, `""` at no step) and the steps it walked,
    each once where it was walked again straight after (`walked`)."""

    now: str = ""
    walked: tuple[str, ...] = ()


def step_of(event: str, facts: dict | None = None) -> str | None:
    """The step one transition is — `""` when it takes the card out of the loop, `None` when it
    leaves the card at the step it was at."""
    facts = facts or {}
    if event in _BY_EVENT:
        return _BY_EVENT[event]
    if event == "pr_opened":
        # A PERSON DECIDES IT: the change is theirs to try. An armed merge waits on a build
        return PREVIEW_READY if facts.get("needs_person") else None
    if event == "closed":
        return DELIVERED if facts.get("delivered") else ""
    if event in _OUT_OF_THE_LOOP:
        return ""
    return None


def step(history) -> Reading:
    """The step `history`'s card is at, and the steps it walked — read from its rows alone."""
    now = ""
    walked: list[str] = []
    for row in getattr(history, "rows", ()) or ():
        said = step_of(str(getattr(row, "event", "") or ""), dict(getattr(row, "facts", {}) or {}))
        if said is None:
            continue
        now = said
        if said and (not walked or walked[-1] != said):
            walked.append(said)
    return Reading(now=now, walked=tuple(walked))
