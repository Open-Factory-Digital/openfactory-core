"""The open-loop ledger (ADR-0021) — what an agent did that expects something back.

THE PROBLEM THIS SOLVES, IN ONE LINE: both judging roles could act, and neither could follow
through. They emitted and forgot. A remedy was tried and nothing recorded whether it worked; a
question was asked and nothing noticed that nobody answered; work shipped carrying a critical
review finding and no person was ever told.

So the unit here is not an event, it is a LOOP: something is open until the world shows it closed.

    opened    an agent did something that expects a response
    chased    time passed, nothing came back, one reminder goes to a named person
    closed    observation says it resolved, and the outcome is recorded

PURE. Everything in this module is arithmetic over rows — no clock, no network, no store. The
activities supply "now" and the observed state; this decides what that means. That is what makes a
claim like "this has never worked" something a person can recount by hand rather than an impression
a model formed.

APPEND-ONLY. Closing a loop writes a second row rather than editing the first. History that can be
revised on a later pass is not history, it is an opinion with a timestamp — and the whole value of
this ledger is that an agent cannot quietly improve its own record.

AND NOTHING SELF-REPORTS SUCCESS. `close_by_observation` takes the world as another pass found it.
A remedy that grades its own homework is exactly what this ledger exists to stop believing.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

#: The states a loop can be in. `OPEN` is not "failing" and `CHASED` is not "escalated" — they are
#: both honest descriptions of "still waiting", which is the state most real work is in.
OPEN, CHASED, CLOSED = "open", "chased", "closed"

#: Loop kinds, one per gap the 2026-07-27 audit found. Kept as a closed set because every one of
#: them has a specific closing observation, and a kind nobody knows how to close is a row that stays
#: open for ever and slowly teaches everyone to ignore the list.
REMEDY, FINDING, QUESTION, DELIVERY = "remedy", "finding", "question", "delivery"

#: ACCEPTANCE is the loop that makes this a product role rather than a status reporter. `DELIVERY`
#: closes when the BOARD says the work is done — which is the factory agreeing with itself. It says
#: nothing about whether the person who asked got what they wanted, and a PO whose definition of
#: done is "the tickets are closed" is exactly the PO nobody wants. So the announcement OPENS this,
#: and only the client's own answer closes it: `worked` or `did-not-work`, straight from the person.
#: Unanswered it stays visibly open — never closed by time, because silence is not acceptance.
ACCEPTANCE = "acceptance"

#: A decision the agent asked a HUMAN for, in conversation. Deliberately NOT `QUESTION`, and the
#: reason is a trap that would have bitten silently: `followup.answered()` closes every open
#: QUESTION whose `subject:about` no longer appears among the board's live findings. A decision
#: asked in a chat has no board finding at all, so the very next sweep would have closed it as
#: "resolved" — the request would vanish from the ledger minutes after being made, and nobody
#: would ever be chased about it. Its own kind is what keeps it out of that rule.
DECISION = "decision"
KINDS = (REMEDY, FINDING, QUESTION, DELIVERY, ACCEPTANCE, DECISION)


@dataclass(frozen=True)
class Loop:
    """One thing an agent is waiting on.

    `subject` is what it is about in that kind's own terms — a ticket number for a remedy, a
    requirement number for a delivery, a thread id for a question. `about` narrows it further where
    one subject can have several open loops (a failure signature, a person's handle)."""

    kind: str
    subject: str
    #: who is waiting: "techlead" | "product"
    owner: str = ""
    about: str = ""
    state: str = OPEN
    #: how it ended, in that kind's own vocabulary. Empty while open — never a guess.
    outcome: str = ""
    #: when it was opened. Also its IDENTITY: two loops with the same (kind, subject, about, ts)
    #: are the same loop, which is how an append-only store tells a row from its own resolution.
    ts: str = ""
    #: when it was last chased, so a reminder happens once rather than every round
    chased_ts: str = ""
    #: anything the closing pass or the message needs, kept as plain strings so a row survives a
    #: schema change without a migration
    context: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.kind, self.subject, self.about, self.ts)

    @property
    def waiting(self) -> bool:
        return self.state in (OPEN, CHASED)


def open_loop(kind: str, subject: str, *, owner: str, ts: str, about: str = "",
              context: dict[str, str] | None = None) -> Loop:
    """Record that something is now expected back. Always `OPEN` — an agent may never open a loop
    already claiming an outcome."""
    if kind not in KINDS:
        raise ValueError(f"unknown loop kind {kind!r}; add it to KINDS with a closing observation")
    return Loop(kind=kind, subject=subject, owner=owner, about=about, ts=ts,
                context=dict(context or {}))


def fold(rows: list[Loop]) -> list[Loop]:
    """One entry per loop, carrying its latest known state.

    Rows arrive from a scan in no guaranteed order, so this must be order-independent in the one way
    that matters: a stale `OPEN` can never un-close a loop. Everything else takes the last write,
    which is how a chase updates a row it does not resolve."""
    latest: dict[tuple, Loop] = {}
    order: list[tuple] = []
    for row in rows:
        key = row.key
        if key not in latest:
            order.append(key)
            latest[key] = row
            continue
        if latest[key].state == CLOSED and row.state != CLOSED:
            continue  # a late `open` must never resurrect a settled loop
        latest[key] = row
    return [latest[k] for k in order]


def waiting(rows: list[Loop], *, kind: str = "", owner: str = "") -> list[Loop]:
    """Everything still expecting something back, optionally narrowed."""
    return [
        loop for loop in fold(rows)
        if loop.waiting
        and (not kind or loop.kind == kind)
        and (not owner or loop.owner == owner)
    ]


def close_by_observation(rows: list[Loop],
                         observed: dict[tuple[str, str, str], str]) -> list[Loop]:
    """The rows to APPEND that close what the world has resolved.

    `observed` maps `(kind, subject, about) → outcome`, supplied by a pass that LOOKED. A loop
    with no entry is still waiting, which is the safe reading: an unobserved loop stays open and
    gets chased, whereas assuming it closed would silently drop the follow-through this ledger
    exists to provide.

    THE KEY CARRIES `about`, and the first version did not — two reviewers found the same hole
    independently. A ticket fifteen days in progress with no criteria holds TWO questions
    (`stalled` and `no-criteria`); keyed on `(kind, subject)` alone, resolving either one closed
    both, and the surviving problem was never chased again. Same shape on the tech-lead side: two
    remedy attempts with different failure signatures collapsed onto one key and both took the
    newer outcome.

    Returns only the new rows. An already-closed loop produces nothing rather than a correction —
    the store is append-only, and rewriting a settled outcome is the one thing it must not allow."""
    out: list[Loop] = []
    for loop in fold(rows):
        if not loop.waiting:
            continue
        outcome = observed.get((loop.kind, loop.subject, loop.about))
        if outcome is None:
            continue
        out.append(replace(loop, state=CLOSED, outcome=outcome))
    return out


def reassert_waiting(rows: list[Loop]) -> list[Loop]:
    """Every still-waiting loop, as rows to APPEND unchanged — a keep-alive.

    The store is read through a recent window (the newest N rows). A loop opened weeks ago that
    nobody has closed — a review finding awaiting its `ack` — would eventually be pushed out of
    that window by sheer churn of newer questions and remedies, and evaporate: no close, no log,
    just gone, which is precisely the "announced and then forgotten" failure this ledger exists to
    end. Re-asserting the waiting rows each round keeps every open obligation inside any recent
    window, at the cost of a handful of rows per round.

    Safe against races by fold's own guard: if a concurrent pass closed a loop between our read
    and this write, the re-asserted OPEN row cannot resurrect it."""
    return [loop for loop in fold(rows) if loop.waiting]


def chase_due(rows: list[Loop], *, hours_open: dict[tuple[str, str, str], float],
              after_hours: float, ts: str) -> list[Loop]:
    """The rows to APPEND for loops worth ONE reminder.

    Bounded on purpose, and the bound is the design rather than a tuning knob. Two failure modes sit
    either side of this function: a question that evaporates because nobody was reminded, and an
    agent that asks the same thing every hour until somebody mutes the channel. A loop is chased
    once; after that it is a visible open item, and the answer to continued silence is a person
    looking at the list, not a louder agent."""
    out: list[Loop] = []
    for loop in fold(rows):
        if loop.state != OPEN:
            continue  # CHASED already had its reminder; CLOSED needs nothing
        age = hours_open.get((loop.kind, loop.subject, loop.about))
        if age is None or age < after_hours:
            continue
        out.append(replace(loop, state=CHASED, chased_ts=ts))
    return out
