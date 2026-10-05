"""What may happen to a card, and what follows when it does — two pure tables (ADR-0055 D2, D3).

PURE, AS ADR-0033's KERNEL ASKS: no clock, no store, no tracker. The door (`card.py`) reads the
world, asks these, and applies what they answer; a reader asking "what happens when a card is
discarded?" reads one row here instead of four processes.

THE EVENT SET IS CLOSED AND WHOLE FROM THE FIRST SLICE. All of D1's events are named now, and an
event no slice has decided yet is REFUSED IN EVERY STATE and has no row of consequences: D2's
default is refusal, so an event becomes possible only when somebody writes where it may happen and
what follows it — in the same change, here. Slice 1 (#412) decides the endings a person causes:
`discarded`, `skipped`, `stopped`, `closed`, `withdrawn`, `removed`, `reopened`; slice 2 (#413)
the job's endings; slice 3 (#414) a card's filing, its moves between the operator's columns and
its edits — `filed`, `promoted`, `reordered`, `edited` — what follows a change somebody made in
the vendor's own interface (`OBSERVED`, D8), the job's tellings — the question before the plan
(`question_asked`), the card a split closes, the delivery a finished card completes — and the
outcomes the box hands back for the worker to apply (D7): `refused`, `pr_opened`, `merged`,
beside the `parked` and `delivered` of slice 2 — and `promised`, the one event ADR-0055 gained
after its slices were cut (amended 2026-10-04): a card joining a requirement's promise, which no
one card's filing can carry, and which moves nothing (`MOVES_NOTHING`). The ADR's slice 4, #448
slice 6 (amended 2026-10-05), decides the requester's loop past the pull request: `resumed`,
`accepted`, `staged`, `stage_rejected` and `released`, with `merged` telling its requester and
`delivered` allowed from a card the record holds merged or staged (`HELD`). Only `picked_up` is
still undecided.
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
    PROMISED = "promised"


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
#: after its merge, and `needs_action` a production gate like any park. The record says them, and
#: the door reads it for the events whose legality turns on them (`READ_FROM_THE_RECORD`).
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

#: A CARD THE FACTORY HOLDS, from its first progress mark to its delivery (#448 slice 6, ADR-0055
#: amended 2026-10-05): under a job, waiting on a person at a gate, merged, at a stage. Where the
#: requester's loop past the pull request may happen — the engine says which job waits on what,
#: and every caller asks its gate first; the table refuses what no gate could be asked about: a
#: card nobody started, or one done or gone.
HELD = frozenset({State.RUNNING, State.WAITING_ON_A_PERSON, State.MERGED, State.STAGED})

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
    # card in Needs Action is often one no job is on, and refusing it here would strand it there.
    # So is a card the record holds merged or at a stage (#448 slice 6, review of #524): a close
    # seen on the vendor's screen is judged against the record's latest move (D8), and refusing it
    # would leave its promise open for ever, refused again on every round
    CardEvent.CLOSED: frozenset({State.BACKLOG, State.TODO, State.RUNNING,
                                 State.WAITING_ON_A_PERSON, State.MERGED, State.STAGED,
                                 State.DELIVERED}),
    CardEvent.WITHDRAWN: frozenset({State.BACKLOG, State.TODO, State.RUNNING,
                                    State.WAITING_ON_A_PERSON}),
    # never once the factory finished it: what was done and said on it is history (#384). A card
    # merged or at a stage is not finished — its delivery is still to come — and, as for a close,
    # a deletion seen on the vendor's screen is judged on the record (review of #524)
    CardEvent.REMOVED: frozenset({State.BACKLOG, State.TODO, State.RUNNING,
                                  State.WAITING_ON_A_PERSON, State.MERGED, State.STAGED}),
    # a card closed as not delivered, or one closed as delivered — and only once it IS closed
    # (`ONLY_ON_A_CLOSED_CARD`): a finished card nobody closed is `delivered` too, and open
    CardEvent.REOPENED: frozenset({State.CLOSED, State.DELIVERED}),
    # AN ANSWER IS RECORDED WHEREVER THE CARD IS (#413). What follows depends on where that is —
    # back to the queue only from the park the question put it in; a card that is gone closes its
    # question as cancelled and is NEVER put back in the queue, the error the inventory found:
    # the sweep returned a closed card to TO-DO from the ledger alone (`consequences`)
    CardEvent.QUESTION_ANSWERED: frozenset(State),
    # THE JOB'S OWN ENDINGS (#413, part 2), applied by the worker from the activities that already
    # wrote them — `mark_needs_action` and `settle_ticket` — so no workflow history changes
    CardEvent.PARKED: frozenset({State.TODO, State.RUNNING, State.WAITING_ON_A_PERSON}),
    # AND FROM A CARD THE RECORD HOLDS MERGED OR AT A STAGE (#448 slice 6): its delivery is the
    # last declared stage's (#448 slice 5), the deploy watch's green or the production release
    CardEvent.DELIVERED: HELD,
    # A PASS A PERSON ASKED FOR, BACK AT THE MERGE GATE (#413 part 3, #448 slice 2)
    CardEvent.ADJUSTED: frozenset({State.RUNNING, State.WAITING_ON_A_PERSON}),
    # A CARD JUST WRITTEN, PUT IN THE COLUMN IT IS FILED IN (#414). Read the moment after it was
    # created: on no column yet (a hosted board holds an issue only once it is added), already in
    # the backlog (the local board files there), or in TO-DO where a row's first status is the
    # queue's — which is why filing moves it out: cards land in the backlog (ADR-0019 §5)
    CardEvent.FILED: frozenset({State.BACKLOG, State.TODO}),
    # A PERSON QUEUES IT — the one gesture that spends (ADR-0019 §5). From the backlog, from the
    # queue itself (a move to where it is changes nothing and refuses nothing), and from a park:
    # a card left in Needs Action with no job on it is put back in the queue by hand, and whether a
    # job still waits there is the engine's to answer (`catalog._card_move`), as for a close
    CardEvent.PROMOTED: frozenset({State.BACKLOG, State.TODO, State.WAITING_ON_A_PERSON}),
    # A PERSON RE-ARRANGES THE OPERATOR'S COLUMNS without spending: out of the queue, back to the
    # backlog. Never out of the factory's columns — a card a job holds is ended by `stop`, `skip`
    # or `discard`, which tell the job; a drag would leave it running with nothing telling it
    CardEvent.REORDERED: frozenset({State.BACKLOG, State.TODO}),
    # THE TEXT IS CORRECTED BEFORE THE FACTORY READS IT (#150): an agent works from the text it
    # read at pickup, so after it the card is the factory's and a correction is a comment. A card
    # corrected at the merge gate, judged again with its review marked out of date, is #448 slice 1
    CardEvent.EDITED: frozenset({State.BACKLOG, State.TODO}),
    # A QUESTION BEFORE THE PLAN (#414, ADR-0048 §5): the gather asks the requester what the
    # product's context does not say, and parks the card on it. ADR-0055 names the event and not
    # where it may happen, so this is the narrowest rule it allows: where a job holds the card
    # before its plan — picked from the queue (TO-DO, until the box's first mark), already marked,
    # or resumed from a park — and never on a card that is gone, where a question asks nobody
    CardEvent.QUESTION_ASKED: frozenset({State.TODO, State.RUNNING, State.WAITING_ON_A_PERSON}),
    # THE BOX'S OUTCOMES, HANDED BACK AND APPLIED BY THE WORKER (#414, D7) — where the box used to
    # write them unconditionally. A job holds the card from the queue onwards: a card in TO-DO is
    # one it was handed (a refusal or a pull request found already open happen before the first
    # progress mark), `running` is what its progress marks show, and a person's gate is where a
    # resumed job, a repair pass or a re-review starts from. Never a card that is gone: a job
    # whose card was closed under it does not move it back onto the board.
    CardEvent.REFUSED: frozenset({State.TODO, State.RUNNING, State.WAITING_ON_A_PERSON}),
    # A PULL REQUEST IS ONE EVENT, whoever hands it to the door: the box that opened it (or found
    # it already open), the merge watch and the hourly round that tell its requester (#401). One
    # rule for all three, the box's: TO-DO is right for it — a job re-picked from the queue finds
    # its pull request already open before its first progress mark — and it is no wider for the
    # watch and the round, which hand over only a gate the engine holds. Never the backlog,
    # where no job holds the card, and never a card that is gone, which is nobody's to try
    CardEvent.PR_OPENED: frozenset({State.TODO, State.RUNNING, State.WAITING_ON_A_PERSON}),
    CardEvent.MERGED: frozenset({State.RUNNING, State.WAITING_ON_A_PERSON}),
    # A CARD JOINS A REQUIREMENT'S PROMISE (#414, ADR-0055 amended 2026-10-04): the breakdown files
    # some cards and REUSES others — open cards the requirement verified on the board — so a card
    # joins wherever it is open, a job on it or not. Never a card that is done or gone: its work
    # is no longer to come, and a promise waiting on it waits for a transition it will not make
    CardEvent.PROMISED: frozenset({State.BACKLOG, State.TODO, State.RUNNING,
                                   State.WAITING_ON_A_PERSON, State.MERGED, State.STAGED}),
    # THE REQUESTER'S LOOP PAST THE PULL REQUEST (#448 slice 6, ADR-0055 amended 2026-10-05), on a
    # card the factory holds. A pass sent back from the merge gate or the last one; a yes recorded
    # against what was tried; the box at a production gate, and the round asking about it; a "not
    # yet" there; the yes that releases it
    CardEvent.RESUMED: HELD,
    CardEvent.ACCEPTED: HELD,
    CardEvent.STAGED: HELD,
    CardEvent.STAGE_REJECTED: HELD,
    CardEvent.RELEASED: HELD,
}

#: THE EVENTS WHOSE LEGALITY TURNS ON MERGED OR STAGED (#448 slice 6, ADR-0055 D2 amended
#: 2026-10-05), which no column holds: a merged card sits In review like one under review, and a
#: production gate in Needs Action like any park. For these the door refines a column that reads
#: `running` or `waiting_on_a_person` by the record's latest move when that move left the card
#: merged or staged (`card.transition`); every other event is judged as it always was.
READ_FROM_THE_RECORD: frozenset[CardEvent] = frozenset({
    CardEvent.RESUMED, CardEvent.ACCEPTED, CardEvent.STAGED, CardEvent.STAGE_REJECTED,
    CardEvent.RELEASED})

#: The events that need the card CLOSED on its tracker, whatever its state says. `delivered` is a
#: card the factory finished, closed or not yet: every row closes it in Done — the local board too
#: since #500, Jira by `statusCategory` — but a person can drag an open card there, and a hosted
#: close can be refused (`OPENFACTORY_DELIVERED_CARD_NOT_CLOSED`). Reopening an open card was the
#: defect — on the local board it threw a card in progress back into Backlog — so a reopen asks for
#: the closed card itself.
ONLY_ON_A_CLOSED_CARD: frozenset[CardEvent] = frozenset({CardEvent.REOPENED})

#: The events whose legality a board that places no card cannot settle, and which are therefore
#: allowed on an open card it does not place — a tracker with no board, or a card not on it. The
#: rows' own gates still ask the engine. `reopened` is not here: a closed card is known to be closed
#: without any board.
WHERE_NO_BOARD_PLACES_IT: frozenset[CardEvent] = frozenset({
    CardEvent.DISCARDED, CardEvent.SKIPPED, CardEvent.STOPPED, CardEvent.CLOSED,
    CardEvent.WITHDRAWN, CardEvent.REMOVED, CardEvent.QUESTION_ANSWERED, CardEvent.PARKED,
    CardEvent.DELIVERED, CardEvent.ADJUSTED, CardEvent.FILED, CardEvent.PROMOTED,
    CardEvent.REORDERED, CardEvent.EDITED, CardEvent.QUESTION_ASKED, CardEvent.REFUSED,
    CardEvent.PR_OPENED, CardEvent.MERGED, CardEvent.PROMISED, *READ_FROM_THE_RECORD})

#: THE EVENTS THAT MOVE NOTHING (#414): what they record is a fact about the card's promises, never
#: where the card is — no column, no write to the card, no snapshot to forget, and the state after
#: is the state before. So the record's word on where a card is is its LATEST MOVE
#: (`record.History.latest_move`), never one of these: the sweep supersedes an older transition's
#: late effect only by a newer move, and an observed change is judged against the last move. A
#: requirement's promise recorded on a card a moment after its filing must neither stand for where
#: the card is nor strand the filing's placement, which the sweep would otherwise repair.
MOVES_NOTHING: frozenset[CardEvent] = frozenset({CardEvent.PROMISED})

#: THE ROWS THAT STOP AT A FAILED WRITE TO THE CARD — the one exception to "one effect failing
#: does not stop the next" (`executor.apply`). A question waits only on a card that was parked for
#: it: when the comment or the park does not land, the gather goes on and the work proceeds
#: (ADR-0048 §5), so a loop opened beside the failed park would wait on a card nobody parked, and
#: the park applied by the sweep an hour later would stop a card its job is working on. So what
#: follows the failed write is not applied, and nothing of the row converges: its caller went on
#: without it.
STOPS_AT_A_FAILED_WRITE: frozenset[CardEvent] = frozenset({CardEvent.QUESTION_ASKED})

#: Who `by` is when nobody of ours made the change: the board sweep found it on the tracker, made
#: in the vendor's own interface, and the record did not hold it (D8). The door judges such an
#: event against what the platform last KNEW of the card — the tracker already shows the change —
#: and applies what follows MINUS THE WRITES TO THE TRACKER AND THE BOARD, which already happened.
OBSERVED = "observed"


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
    """The card moves to the column with this neutral key — or of this job state, through the
    tracker's one writer of it. `needs_person` is what a state cannot say on its own (#166): a
    pull request waiting on a person and one an armed merge is watching are both `pr_open`."""

    key: str
    needs_person: bool | None = None


@dataclass(frozen=True)
class Place:
    """The card is put on the board, in the column with this neutral key — the BOARD's own write,
    by the column's name, for a person's gesture that places a card rather than a job's state that
    moves it: filing, a promotion, a move between the operator's columns. `Column` is a job's state
    reflected through the tracker's one writer (`set_state`), whose map has no state for "written
    down, not started" (`github_project.set_column`). On a deployment with no board there is
    nowhere to place a card, and that is the outcome, not a failure."""

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
    back, so is its part of the delivery it was cancelled from. `answer`: the question the card
    waited on closes as answered; `moot`: it closes as cancelled — the card is gone (#413). `ask`:
    the question the factory just put to the requester opens, to be answered on the card;
    `deliver`: every delivery the card completes is announced to whoever asked for it, closed,
    and its "did it work?" opened; `open`: the promise the transition carries (`facts["owed"]`)
    opens — the delivery a reported defect, or a card somebody asked for in a conversation, is
    owed with its filing; a requirement's, over every card of its breakdown, with each card's
    `promised` — ONE per subject, so the first card to carry it opens it and every other finds it
    owed already (#414).

    AND THE RELEASE QUESTION, the "did it work?" asked of a change parked at its last gate (#448
    slice 6): `release:ask` opens the room's copy once the room was asked, `release:ask-theirs` the
    requester's once they were told (`RELEASE_ASKS`); `release:worked` and `release:did-not-work`
    close every open copy with the verdict that counted, `release:theirs-worked` only the
    requester's — their yes recorded, the room's left for whoever releases (`RELEASE_CLOSES`)."""

    action: str


#: The release question's actions (`Loops`), opened by the round's asking (`staged`) and closed by
#: the verdicts that count (`accepted` at the last gate, `stage_rejected`, `released`).
RELEASE_ASK, RELEASE_ASK_THEIRS = "release:ask", "release:ask-theirs"
RELEASE_WORKED, RELEASE_THEIRS_WORKED = "release:worked", "release:theirs-worked"
RELEASE_DID_NOT_WORK = "release:did-not-work"
RELEASE_ASKS = frozenset({RELEASE_ASK, RELEASE_ASK_THEIRS})
RELEASE_CLOSES = frozenset({RELEASE_WORKED, RELEASE_THEIRS_WORKED, RELEASE_DID_NOT_WORK})


@dataclass(frozen=True)
class Tell:
    """The requester's conversation is told, once, what happened and where the card is — or, for
    `TRIED`, the product's room, which a product admin reads (#448 slice 4)."""

    notice: str


@dataclass(frozen=True)
class Preview:
    """The card's preview is taken down."""

    action: str


@dataclass(frozen=True)
class Forget:
    """What this process remembers of the board is dropped (#393)."""


Effect = Column | Place | Close | Remove | Reopen | Comment | Loops | Tell | Preview | Forget

#: The effects that write the card where the vendor keeps it — its tracker or its board. An
#: OBSERVED change already made them, in the vendor's own interface (D8); what follows it is the
#: rest: the promise, the conversation, the preview, the snapshot.
WRITES_THE_CARD = (Column, Place, Close, Remove, Reopen, Comment)

#: What the requester is told, by which way the work ended — and, for a pass a person asked for,
#: that the pass is ready to try; for a pull request a person decides, that the change is theirs
#: to try (#401, `events.ready_to_try`).
STOPPED_WORK, WILL_NOT_BE_BUILT, BACK_ON_THE_BOARD = "stopped_work", "will_not_be_built", "back"
PASS_READY = "pass_ready"
READY_FOR_YOU = "ready_for_you"
#: The requester's loop past the pull request (#448 slice 6): the change went in (`merged`), it is
#: theirs to try at a stage (`staged`), and — to the ROOM — they tried it and say it is right
#: where their word does not release it (`accepted` at the last gate).
MERGED_FOR_YOU, STAGED_FOR_YOU, TRIED = "merged_for_you", "staged_for_you", "tried"

_GONE = (Comment(), Loops("cancel"), Tell(WILL_NOT_BE_BUILT), Preview("stop"), Forget())

#: Where a card is when an answer to its question arrives, read from the transition's facts.
_GONE_STATES = frozenset({State.CLOSED.value, State.REMOVED.value})
_STILL_PARKED = frozenset({State.WAITING_ON_A_PERSON.value, ""})


def consequences(event: CardEvent, facts: Mapping[str, object] | None = None) -> tuple[Effect, ...]:
    """What follows `event`, in the order it is applied. Exhaustive over the events a slice has
    decided; an undecided event has no row, because no state allows it (`ALLOWED`).

    `facts` carries what the event knows. One fact changes a row: whether a close is of finished
    work (`delivered`). A delivered close cancels nothing and tells nobody that something will not
    be built — the delivery is the delivery's to announce.

    AN OBSERVED CHANGE (`facts["observed"]`, D8) is followed exactly as the same change made
    through the platform, minus the writes to the card the vendor's interface already made — with
    one exception, THE BOARD FOLLOWING A CLOSE: a card closed while it sits in the pickup column is
    filed where its close puts it, which is what the stale-pickup healer did by hand (#413). Only
    from TO-DO: on a row whose column IS its status (Jira, Azure Boards) a closed card is never in
    it, and moving a closed card into a column there would reopen it."""
    facts = facts or {}
    row = _row(event, facts)
    if not facts.get("observed"):
        return row
    kept = tuple(e for e in row if not isinstance(e, WRITES_THE_CARD))
    if event is CardEvent.CLOSED and str(facts.get("column") or "") == "todo":
        return (Column("done" if facts.get("delivered") else "backlog"), *kept)
    return kept


def _row(event: CardEvent, facts: Mapping[str, object]) -> tuple[Effect, ...]:
    """The row of `consequences` for a change made through the platform."""
    if event in _BACK_TO_THE_BACKLOG:
        # the promise stays open, and the requester is told the card is back in the backlog (D10)
        return (Column("backlog"), Comment(), Tell(STOPPED_WORK), Preview("stop"), Forget())
    if event is CardEvent.CLOSED:
        if facts.get("delivered"):
            # FINISHED WORK, closed — by its job, by a person, or on the vendor's own screen: the
            # deliveries it completes are announced now (#414), not at the weekly catch-all
            return (Close(delivered=True), Comment(), Loops("deliver"), Forget())
        if facts.get("split_into"):
            # A CARD SPLIT INTO OTHERS (#414): closed as not delivered, and NOT gone — its work
            # lives in the cards split from it, and its promise stands until they are delivered
            # (`triage.delivered_numbers`). Nothing is cancelled and nobody is told it will not be
            # built. ADR-0055 is silent on a split; D10's "the card is gone" is not what happened
            return (Close(delivered=False), Comment(), Forget())
        return (Close(delivered=False), *_GONE)
    if event is CardEvent.WITHDRAWN:
        return (Close(delivered=False), *_GONE)
    if event is CardEvent.REMOVED:
        return (Remove(), *_GONE)
    if event is CardEvent.REOPENED:
        return (Reopen(), Comment(), Loops("restore"), Tell(BACK_ON_THE_BOARD), Forget())
    if event is CardEvent.PARKED:
        # the park's own state (on hold, needs refinement…) is the column; the comment is the
        # caller's note when it has one — the box usually wrote its own as it parked
        said = (Comment(),) if facts.get("note") else ()
        return (Column(str(facts.get("job_state") or "on_hold")), *said, Forget())
    if event is CardEvent.ADJUSTED:
        # EVERY PASS ENDS THE WAY THE FIRST DID (#448): the preview shows the new head, and the
        # person who asked hears that this pass is theirs to try — keyed by the pass, so a second
        # pass is never folded into the first one's telling
        return (Comment(), Preview("rebuild"), Tell(PASS_READY), Forget())
    if event is CardEvent.DELIVERED:
        # the card closes as delivered (`Column("done")` is DONE, which every row now closes on),
        # and THEN the deliveries it completes are announced (#414) — after the close, because the
        # announcement reads the board fresh, and a card still open there delivered nothing. The
        # comment is the caller's note when it has one: a delivery the box handed back was said
        # on the card by the box as it reached it (#414), and an empty note is no comment
        return (Column("done"), *_said(facts), Loops("deliver"), Forget())
    if event is CardEvent.QUESTION_ASKED:
        # THE ORDER IS ADR-0048 §5's: the question on the card (the comment, marker first), the
        # park, and only then the loop the answer closes — and the row stops at a failed write
        # (`STOPS_AT_A_FAILED_WRITE`), so no question waits on a card that was not parked for it
        return (Comment(), Column("needs_refinement"), Loops("ask"), Forget())
    if event is CardEvent.REFUSED:
        # THE FACTORY WILL NOT BUILD THE CARD AS WRITTEN (#414) — its spec or its plan gate said
        # so, and the card goes back to a person to refine. The box said why on the card as it
        # refused it; what follows here is the column and the snapshot
        return (Column("needs_refinement"), *_said(facts), Forget())
    if event is CardEvent.PR_OPENED:
        # THE CHANGE IS IN A PULL REQUEST (#414): on the merge gate's column when a person is the
        # blocker, in review when the factory is the one watching it. And WHEN A PERSON DECIDES
        # IT, its requester hears it is theirs to try (#401) — keyed by the pull request, so the
        # box that opened it, the merge watch and the hourly round are one transition, and
        # whichever hands it to the door second is answered from the card's record
        # (`handed_back.gate_event`). The preview's start is the job's tail's (#405), not this
        # row's. The box said the pull request on the card, so its hand-back writes no comment
        tell = (Tell(READY_FOR_YOU),) if facts.get("needs_person") and facts.get("pr_url") else ()
        return (Column("pr_open", needs_person=facts.get("needs_person")), *_said(facts), *tell,
                Forget())
    if event is CardEvent.MERGED:
        if "stages_follow" in facts and facts.get("pr_url"):
            # ITS REQUESTER HEARS IT WENT IN (#448 slice 6), from the job's telling — the one hand
            # that knows whether stages follow, keyed by the pull request
            # (`handed_back.merged_event`). It writes no column: the box's hand-back, the settle
            # and the stages place the card, and a deploy watch may already have held it in Needs
            # Action by the time the job says it — a column here would move that card back
            return (Tell(MERGED_FOR_YOU), Forget())
        # MERGED, AND OVERSEEN WHILE IT DEPLOYS: `in_review` until the delivery — the promotion's
        # last stage, or the settle when nothing follows the merge (ADR-0049 slice 5). The box's
        # hand-back and the settle tell nobody
        return (Column("merged"), *_said(facts), Forget())
    if event is CardEvent.RESUMED:
        # A PERSON SENT IT BACK FOR ANOTHER PASS (#448 slice 6) — from the merge gate, on the same
        # pull request, or from the last gate, as a new change. The bar was corrected and the pass
        # sent by the transition's act; the pass's progress marks are its column, and `adjusted`
        # ends it, so nothing else is written here
        return (*_said(facts), Forget())
    if event is CardEvent.ACCEPTED:
        if facts.get("gate") == "last" and facts.get("unreleased"):
            # A YES THAT MAY RELEASE, AND THE JOB WAS NO LONGER THERE TO TAKE IT (#273): the verdict
            # still counts — every copy of the question closes as worked, and nobody is told the
            # room's news; the person heard why nothing went out
            return (Loops(RELEASE_WORKED), *_said(facts), Forget())
        if facts.get("gate") == "last":
            # THE REQUESTER TRIED IT AT THE LAST GATE AND SAYS IT IS RIGHT, AND THEIR WORD DOES
            # NOT RELEASE IT (#448 slice 4, `release_by_requester` off): their copy of the question
            # closes as worked, the room's stays for whoever releases, and the room hears it
            return (Loops(RELEASE_THEIRS_WORKED), Tell(TRIED), *_said(facts), Forget())
        # "THAT'S IT", RECORDED AGAINST THE HEAD THEY TRIED (#448 slice 3) by the transition's act;
        # the card says who, on which head, and whether it is going in
        return (*_said(facts), Forget())
    if event is CardEvent.STAGED:
        if facts.get("asked_at"):
            # THE ROUND ASKED THE ROOM, AND THE QUESTION LANDED (#448 slice 4): the room's copy
            # opens, the requester is told where they asked — once per run of the job — and their
            # own copy opens only when they were (`ports.loops`). The card does not move
            return (Loops(RELEASE_ASK), Tell(STAGED_FOR_YOU), Loops(RELEASE_ASK_THEIRS))
        # THE BOX REACHED A PRODUCTION GATE (#448 slice 6) — a park until now. It waits on a person
        # there; nobody is told yet: the requester hears it after the room's question landed
        return (Column("awaiting_prod_approval"), *_said(facts), Forget())
    if event is CardEvent.STAGE_REJECTED:
        # "NOT YET" AT THE LAST GATE, FROM SOMEBODY WHOSE VERDICT COUNTS (#448 slice 4): every copy
        # of the question closes as not worked; the words become the next pass (`resumed`)
        return (*_said(facts), Loops(RELEASE_DID_NOT_WORK), Forget())
    if event is CardEvent.RELEASED:
        # THE YES THAT PUTS IT IN FRONT OF EVERYONE, delivered to the parked job by the
        # transition's act (the sealed `approve_prod`): every copy of the question closes as
        # worked. The box says the approval on the card as it tags
        return (*_said(facts), Loops(RELEASE_WORKED), Forget())
    if event is CardEvent.QUESTION_ANSWERED:
        before = str(facts.get("before") or "")
        if before in _GONE_STATES:
            return (Loops("moot"),)
        if before in _STILL_PARKED:
            return (Column("todo"), Comment(), Loops("answer"), Forget())
        # somebody already moved it on — answered, and left where it is
        return (Comment(), Loops("answer"))
    if event is CardEvent.FILED:
        # PLACED WHERE IT IS FILED, and nothing said: the card's own body says who asked for it,
        # and the conversation that asked was answered there. `""` is a caller with no board — a
        # card is still filed on a tracker alone, and there is nowhere to place it.
        #
        # AND THE PROMISE THE FILING MAKES OPENS WITH IT (#414): a reported defect, or a card
        # somebody asked for in a conversation, is owed its delivery, and the events about the card
        # find their requester through it. A requirement's delivery spans several cards — some
        # the breakdown reused rather than filed — so no one card's filing carries it: every card
        # of the breakdown carries it as `promised`, below
        key = _filed_in(facts)
        owed = (Loops("open"),) if facts.get("owed") else ()
        return (*((Place(key),) if key else ()), *owed, Forget())
    if event is CardEvent.PROMOTED:
        # NO COMMENT AND NOBODY TOLD (#414): the vendor's own history records a move, and a queue
        # position is not a promise — what the requester hears next is the work's own news
        return (Place("todo"), Forget())
    if event is CardEvent.REORDERED:
        return (Place("backlog"), Forget())
    if event is CardEvent.EDITED:
        # the note says which parts moved (`card_edit_note`), on every row — the door's comment
        return (Comment(), Forget())
    if event is CardEvent.PROMISED:
        # THE CARD JOINS A REQUIREMENT'S PROMISE, AND THE PROMISE OPENS (#414, ADR-0055 amended
        # 2026-10-04). Every card of the breakdown, filed or reused, carries the WHOLE promise —
        # the requirement's subject and every card of it — and the ledger keeps one per subject
        # (`loops.owe`): the first card the door admits opens it, every other finds it owed
        # already, so neither one card's refusal nor a breakdown interrupted after its first card
        # leaves it unopened. Nothing is said and nothing is written to the card: the breakdown
        # answered its requester, and a reused card was told which requirement it now serves
        # (`module._reused_card`). It moves nothing (`MOVES_NOTHING`)
        return (Loops("open"),)
    raise KeyError(f"no slice has decided what follows {event.value!r} — it is refused in every "
                   f"state until one does (ADR-0055 D2)")


def _said(facts: Mapping[str, object]) -> tuple[Effect, ...]:
    """The door's comment when the transition carries a note — none when the caller says the card
    was told already (`note=""`), so nothing is said twice (D6)."""
    return (Comment(),) if facts.get("note") else ()


def after(event: CardEvent, facts: Mapping[str, object] | None = None) -> State | None:
    """The state a decided event leaves the card in — `None` only for an event that moves nothing
    (`MOVES_NOTHING`) found on a card no board places: it leaves the card where it found it."""
    facts = facts or {}
    if event in MOVES_NOTHING:
        before = str(facts.get("before") or "")
        return State(before) if before else None
    if event in _BACK_TO_THE_BACKLOG or event is CardEvent.REOPENED:
        return State.BACKLOG
    if event is CardEvent.CLOSED and facts.get("delivered"):
        return State.DELIVERED
    if event in (CardEvent.CLOSED, CardEvent.WITHDRAWN):
        return State.CLOSED
    if event is CardEvent.REMOVED:
        return State.REMOVED
    if event is CardEvent.QUESTION_ANSWERED:
        before = str(facts.get("before") or "")
        return State.TODO if before in _STILL_PARKED else State(before)
    if event in (CardEvent.PARKED, CardEvent.ADJUSTED, CardEvent.QUESTION_ASKED,
                 CardEvent.REFUSED):
        return State.WAITING_ON_A_PERSON
    if event is CardEvent.PR_OPENED:
        return State.WAITING_ON_A_PERSON if facts.get("needs_person") else State.RUNNING
    if event is CardEvent.MERGED:
        return State.MERGED
    if event is CardEvent.DELIVERED:
        return State.DELIVERED
    if event in (CardEvent.RESUMED, CardEvent.RELEASED):
        # ADJUSTING IS NOT A STATE (D2): a card under a pass is running; so is one being released
        return State.RUNNING
    if event in (CardEvent.STAGED, CardEvent.STAGE_REJECTED):
        # a "not yet" leaves the job waiting at the stage it was said at
        return State.STAGED
    if event is CardEvent.ACCEPTED:
        # a yes moves no card: it is where it was — at the merge gate, or at a stage
        before = str(facts.get("before") or "")
        return State(before) if before else (State.STAGED if facts.get("gate") == "last"
                                             else State.WAITING_ON_A_PERSON)
    if event is CardEvent.FILED:
        return BY_COLUMN.get(_filed_in(facts) or "backlog", State.BACKLOG)
    if event is CardEvent.PROMOTED:
        return State.TODO
    if event is CardEvent.REORDERED:
        return State.BACKLOG
    if event is CardEvent.EDITED:
        # the text moved and the card did not; one no board places is, to its life, unstarted
        before = str(facts.get("before") or "")
        return State(before) if before else State.BACKLOG
    raise KeyError(f"no slice has decided where {event.value!r} leaves a card")


#: The columns a card may be FILED into: the backlog, or — a person's own choice on the board — the
#: queue. Never a column the factory writes: a card nobody started is not in progress.
FILING_COLUMNS = frozenset({"backlog", "todo"})


def _filed_in(facts: Mapping[str, object]) -> str:
    """The neutral key a filed card is placed in: the caller's `column`, `backlog` when it named
    none, and `""` when it said there is no board to place it on (`column=""`)."""
    key = facts.get("column", "backlog")
    return str(key) if key in FILING_COLUMNS else ""


#: The events some slice has decided — those allowed somewhere. The derived test holds that every
#: one of them has a row in `consequences` and in `after`, and that no other event does.
DECIDED: frozenset[CardEvent] = frozenset(
    event for event, states in ALLOWED.items() if states or event in WHERE_NO_BOARD_PLACES_IT)


def name_of(effect: Effect) -> str:
    """An effect as the record writes it: its kind, and its argument where it has one."""
    kind = type(effect).__name__.lower()
    arg = next(iter(vars(effect).values()), None) if vars(effect) else None
    return f"{kind}:{str(arg).lower()}" if arg is not None else kind
