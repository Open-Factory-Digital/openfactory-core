"""One conversation with the product role: a long-lived workflow, one turn at a time (#266 slice 3).

ADR-0051 D3, D5 and D6, as the engine runs them. The door (`product/door.py`) sends every message
here as a signal, starting the workflow when it is not running — signal-with-start — and returns at
once. What the workflow owns is ORDER inside one conversation, and nothing across conversations:
each conversation — a private chat, a group room — is its own workflow,
`po-{product}-{conversation}`, so two conversations never wait on each other, and inside one the
role answers one turn at a time.

    admit (signal) ──► seen before? drop — the id is the key, never a hash of the words
                   ├─► an internal event? publish its replies; no turn
                   ├─► read-only (`engine.FAST`)? answered at once, beside any turn
                   └─► pending ──► heard out (debounce) ──► one speaker's messages, one turn
                                                              │
                              bounded (about 90 s) ◄──────────┤
                              past it: "I'll come back"       ▼
                              and the answer returns     publish(Reply) → the outbox a transport
                              through the door               reads (`where`), until slice 5's socket

DURABLE BY CONSTRUCTION. A message is a signal, so it is in the workflow's history the moment the
door returns; a worker that dies mid-turn leaves the message there, the turn is run again on the
worker that replaces it (`TURN_RETRY`), and nothing a person said is lost with the process.

HISTORY IS BOUNDED. After `TURNS_PER_RUN` turns, or when the engine suggests it, an idle
conversation continues as new, carrying the ids it has seen, what it published recently and — if a
message arrived in the same instant — what it has not turned yet (`ConversationInput`).

NO SENTENCE HERE IS THE ROLE'S JUDGEMENT. The three this workflow says in its own voice are
presence — the hand-off at the bound, the apology when a turn could not be run at all — composed by
`product/voice.py`, which is a pure function of the project's language: a replay composes the same
words it composed the first time.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from openfactory.product import voice
    from openfactory.runtime.temporal.activities import (
        conversation_fast,
        conversation_report,
        conversation_turn,
    )
    from openfactory.runtime.temporal.io import (
        Arrival,
        ConversationInput,
        ReportInput,
        TurnInput,
    )

#: How many message ids a conversation remembers for deduplication, across continue-as-new. A
#: transport retries within seconds; five hundred messages back is far past any retry.
SEEN = 512
#: How many published entries a conversation keeps for the transports that read them back.
OUTBOX = 64
#: How many turns one run takes before it continues as new, once it is idle.
TURNS_PER_RUN = 25
#: The debounce never holds a speaker's turn longer than this many debounces after their first
#: message: somebody who types without pausing is still answered.
BURST_CEILING = 4
#: The longest a turn may run on the worker, bound or no bound — the breakdown's twelve minutes
#: (`ProductBreakdownWorkflow`), which is the longest thing a typed message can start in a turn.
TURN_CEILING = timedelta(minutes=15)
#: How soon a worker that died mid-turn is noticed: the turn heartbeats every few seconds
#: (`activities._turning`), and this long without one hands it to another worker.
HEARTBEAT = timedelta(seconds=30)
#: A TURN WHOSE WORKER DIED IS RUN AGAIN, ONCE. The message is what must not be lost. The cost is
#: stated rather than hidden: a turn that died after recording the person's words records them a
#: second time, and a yes that died after its write finds the proposal gone and says so — the
#: staging compare-and-swap is what makes the second run harmless where it matters.
TURN_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=1))
#: The read-only answer's ceiling. No heartbeat: it reads, and a retry of a read is a read.
FAST_CEILING = timedelta(minutes=5)
FAST_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=1))
#: Sending a late answer back through the door: a signal, retried — the event's id makes a
#: repeated report one event.
REPORT_RETRY = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=1))


def _speaker(arrival: Arrival) -> tuple[str, str]:
    """WHO a turn is for — the person, on the registry project they were on. One turn is one
    person's: coalescing gathers what ONE speaker said, never two people's words into one prompt."""
    return arrival.speaker, arrival.project


@workflow.defn
class ConversationWorkflow:
    """One conversation's queue: one turn at a time inside it, and nothing ordered across them."""

    @workflow.init
    def __init__(self, inp: ConversationInput) -> None:
        self._product = inp.product
        self._conversation = inp.conversation
        self._debounce = max(0.0, float(inp.debounce_seconds))
        self._bound = max(0.001, float(inp.bound_seconds))
        self._seen: list[str] = list(inp.seen)[-SEEN:]
        self._known: set[str] = set(self._seen)
        #: ids that arrived again after they were admitted — so the door can say "duplicate"
        self._twice: list[str] = []
        self._outbox: list[dict] = list(inp.outbox)[-OUTBOX:]
        self._pending: list[Arrival] = list(inp.pending)
        self._fast: list[Arrival] = []
        #: the turn being answered now — one speaker's messages
        self._running: list[Arrival] = []
        #: read-only answers in flight, beside the turn
        self._answering: list[str] = []
        self._at: dict[str, datetime] = {}
        self._arrived = 0
        #: fast answers, turns past their bound and reports still in flight: a run that continued
        #: as new under them would drop their results
        self._busy = 0
        self._turns = 0
        self._tasks: set[asyncio.Task] = set()

    # ── the door's signal ───────────────────────────────────────────────────────────────────────

    @workflow.signal
    def admit(self, arrival: Arrival) -> None:
        """One message through the door. DEDUPLICATED BY ITS ID before anything else: a message
        sent twice is one turn, and a transport retrying a send reads the first one's answer."""
        if arrival.id in self._known:
            self._twice = [*self._twice, arrival.id][-SEEN:]
            return
        self._seen.append(arrival.id)
        self._known.add(arrival.id)
        if len(self._seen) > SEEN:
            for gone in self._seen[:-SEEN]:
                self._known.discard(gone)
            del self._seen[:-SEEN]
        if arrival.replies:
            # AN INTERNAL EVENT: the outcome of work the role started, already recorded by whoever
            # produced it. It is published, and starts no turn. What it answers is marked
            # answered — every message the handed-off turn covered, not only the last.
            answered = ((self._covers_of(arrival.in_reply_to) or [arrival.in_reply_to])
                        if arrival.in_reply_to else [])
            self._publish([*answered, arrival.id], list(arrival.replies), final=True)
            return
        if arrival.fast:
            self._fast.append(arrival)
            return
        self._at[arrival.id] = workflow.now()
        self._pending.append(arrival)
        self._arrived += 1

    # ── what the door and the transports read ───────────────────────────────────────────────────

    @workflow.query
    def where(self, message_id: str) -> dict:
        """Where one message stands, and — once it is answered — what was said back to it.

        `state` is `queued` (waiting its turn), `running` (being answered), `handed_off` (its turn
        passed the bound; the answer will follow), `answered`, or `unknown` (never admitted here).
        `ahead` is how many turns come before its own; `coalesced` says it joins a turn its speaker
        already has waiting. `replies` are only ever the ones published FOR THIS MESSAGE: a reader
        is handed the answer to what it sent and to nothing else in the conversation."""
        duplicate = message_id in self._twice
        if any(a.id == message_id for a in self._running) or message_id in self._answering \
                or any(a.id == message_id for a in self._fast):
            return self._stand("running", duplicate=duplicate)
        waiting = [a for a in self._pending if a.id == message_id]
        if waiting:
            mine = _speaker(waiting[0])
            groups: list[tuple[str, str]] = []
            for a in self._pending:
                if _speaker(a) not in groups:
                    groups.append(_speaker(a))
            first = next(a for a in self._pending if _speaker(a) == mine)
            return self._stand("queued", ahead=groups.index(mine) + (1 if self._running else 0),
                               coalesced=first.id != message_id, duplicate=duplicate)
        entry = self._entry_of(message_id)
        if entry is not None:
            return self._stand("answered" if entry["final"] else "handed_off",
                               replies=entry["replies"], duplicate=duplicate)
        if message_id in self._known:
            # answered so long ago that the outbox has let it go
            return self._stand("answered", duplicate=duplicate)
        return self._stand("unknown")

    @staticmethod
    def _stand(state: str, *, ahead: int = 0, coalesced: bool = False, duplicate: bool = False,
               replies: list | None = None) -> dict:
        return {"state": state, "ahead": ahead, "coalesced": coalesced, "duplicate": duplicate,
                "replies": list(replies or [])}

    def _entry_of(self, message_id: str) -> dict | None:
        return next((e for e in reversed(self._outbox) if message_id in e["covers"]), None)

    def _covers_of(self, message_id: str) -> list[str]:
        entry = self._entry_of(message_id)
        return list(entry["covers"]) if entry is not None else []

    # ── the one way out ─────────────────────────────────────────────────────────────────────────

    def _publish(self, covers: list[str], replies: list[dict], *, final: bool) -> None:
        """`publish(Reply)` (ADR-0051 D13): what the role said, put where the conversation's
        transports read it. Recording happened before — the engine records what it says, the
        producer of an event records it — so a reply published is a reply memory already has.

        RECEIPTS ARE NOT PUBLISHED: the door acknowledged every message the moment it arrived,
        and an acknowledgement arriving again beside the answer says nothing twice."""
        said = [r for r in replies if r.get("kind") != "receipt"]
        self._outbox = [*self._outbox, {"covers": list(dict.fromkeys(covers)), "replies": said,
                                        "final": final}][-OUTBOX:]

    def _said(self, text: str, arrival: Arrival, *, kind: str = "answer") -> dict:
        """A sentence the conversation says in its own voice, shaped as the engine's `Reply`."""
        return {"text": text, "kind": kind, "options": None, "addressed_to": arrival.speaker,
                "in_reply_to": arrival.id, "conversation": self._conversation}

    # ── the loop ────────────────────────────────────────────────────────────────────────────────

    @workflow.run
    async def run(self, inp: ConversationInput) -> None:
        self._keep(asyncio.create_task(self._fast_lane()))
        while True:
            await workflow.wait_condition(lambda: bool(self._pending) or self._may_rest())
            if not self._pending:
                break
            await self._hear_out()
            await self._take(self._next_turn())
            self._turns += 1
        workflow.continue_as_new(ConversationInput(
            product=self._product, conversation=self._conversation,
            debounce_seconds=self._debounce, bound_seconds=self._bound,
            seen=list(self._seen), outbox=list(self._outbox), pending=list(self._pending)))

    def _may_rest(self) -> bool:
        """Whether this run may hand over to a new one: enough turns taken, or the engine asking,
        and nothing of this run's still in flight — a detached turn's answer must come back to the
        run that is waiting for it."""
        due = self._turns >= TURNS_PER_RUN or workflow.info().is_continue_as_new_suggested()
        return (due and not self._pending and not self._running and not self._fast
                and self._busy == 0)

    def _keep(self, task: asyncio.Task) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _hear_out(self) -> None:
        """THE DEBOUNCE (ADR-0051 D5): people write in bursts, so the next turn waits until its
        speaker has been quiet for `debounce` seconds — never longer than `BURST_CEILING` of them
        after their first message. Only that speaker's messages move the wait: in a busy room,
        somebody else talking does not hold a person's answer back."""
        if self._debounce <= 0:
            return
        while self._pending:
            head = _speaker(self._pending[0])
            now = workflow.now()
            times = [self._at.get(a.id, now) for a in self._pending if _speaker(a) == head]
            quiet = (now - max(times)).total_seconds()
            held = (now - min(times)).total_seconds()
            left = min(self._debounce - quiet, self._debounce * BURST_CEILING - held)
            if left <= 0:
                return
            mark = self._arrived
            try:
                await workflow.wait_condition(lambda mark=mark: self._arrived != mark,
                                              timeout=timedelta(seconds=left))
            except TimeoutError:
                return

    def _next_turn(self) -> list[Arrival]:
        """THE COALESCING (ADR-0051 D5): everything the next speaker has waiting is one turn.

        The turn stands where that speaker's FIRST waiting message stood, so nobody jumps the
        queue (decision 5): a person who wrote twice while the role was busy is answered once, in
        the place their first message earned, and whoever wrote between their two messages is
        still answered next — one turn later, exactly as without the second message."""
        head = _speaker(self._pending[0])
        turn = [a for a in self._pending if _speaker(a) == head]
        self._pending = [a for a in self._pending if _speaker(a) != head]
        for a in turn:
            self._at.pop(a.id, None)
        return turn

    def _input(self, arrivals: list[Arrival]) -> TurnInput:
        last = arrivals[-1]
        return TurnInput(
            product=self._product, project=last.project, conversation=self._conversation,
            room=last.room, speaker=last.speaker,
            text="\n\n".join(a.text for a in arrivals if a.text.strip()),
            id=last.id, ids=[a.id for a in arrivals], in_reply_to=last.in_reply_to,
            source=last.source, fingerprint=last.fingerprint, via=last.via,
            language=last.language)

    async def _take(self, turn: list[Arrival]) -> None:
        """ONE TURN, BOUNDED (ADR-0051 D6). The turn runs on the worker; the conversation waits
        for it `bound` seconds and no longer. Past the bound the person hears that the work goes
        on and where the answer will come, the conversation moves on to the next turn, and the
        answer — when it comes — returns through the door as an internal event
        (`_report_later`). A turn that could not be run at all is answered with the apology,
        never with silence."""
        self._running = turn
        work = self._input(turn)
        ids = [a.id for a in turn]
        last = turn[-1]
        handle = workflow.start_activity(
            conversation_turn, work, start_to_close_timeout=TURN_CEILING,
            heartbeat_timeout=HEARTBEAT, retry_policy=TURN_RETRY)
        try:
            await workflow.wait_condition(handle.done, timeout=timedelta(seconds=self._bound))
        except TimeoutError:
            self._publish(ids, [self._said(voice.handed_off(language=last.language or None,
                                                            agent_name=last.agent_name),
                                           last, kind="handoff")], final=False)
            self._busy += 1
            self._keep(asyncio.create_task(self._report_later(handle, work, last)))
            self._running = []
            return
        self._running = []
        self._publish(ids, self._replies_of(handle, last), final=True)

    def _replies_of(self, handle, last: Arrival) -> list[dict]:
        try:
            return list((handle.result() or {}).get("replies") or [])
        except ActivityError:
            workflow.logger.error("OPENFACTORY_PRODUCT_MUTE conversation=%s — the turn could not "
                                  "be run on any worker", self._conversation)
            return [self._said(voice.broke(language=last.language or None), last)]

    async def _report_later(self, handle, work: TurnInput, last: Arrival) -> None:
        """The answer of a turn that outlived its bound, sent BACK THROUGH THE DOOR as an internal
        event on this conversation (ADR-0051 D6) — the one way every result reaches a
        conversation. Only when the door cannot be reached at all is it published here instead:
        an answer lost to a refused report is still an answer lost."""
        try:
            try:
                await handle
            except ActivityError:
                pass
            replies = self._replies_of(handle, last)
            if not replies:
                return
            try:
                await workflow.execute_activity(
                    conversation_report,
                    ReportInput(project=work.project, conversation=self._conversation,
                                room=work.room, id=f"{work.id}:late", in_reply_to=work.id,
                                replies=replies),
                    start_to_close_timeout=timedelta(minutes=2), retry_policy=REPORT_RETRY)
            except ActivityError:
                workflow.logger.error("the late answer to %s could not go back through the door "
                                      "— published here instead", work.id)
                self._publish([*work.ids, f"{work.id}:late"], replies, final=True)
        finally:
            self._busy -= 1

    # ── the read-only fast path ─────────────────────────────────────────────────────────────────

    async def _fast_lane(self) -> None:
        """What only asks to be SHOWN something is answered at once, beside any turn (ADR-0051
        D6, decision 5) — the one thing that does not wait its turn, because it spends no model
        call and changes nothing."""
        while True:
            await workflow.wait_condition(lambda: bool(self._fast))
            arrival = self._fast.pop(0)
            self._busy += 1
            self._answering.append(arrival.id)
            self._keep(asyncio.create_task(self._answer_fast(arrival)))

    async def _answer_fast(self, arrival: Arrival) -> None:
        try:
            try:
                out = await workflow.execute_activity(
                    conversation_fast, self._input([arrival]),
                    start_to_close_timeout=FAST_CEILING, retry_policy=FAST_RETRY)
                replies = list((out or {}).get("replies") or [])
            except ActivityError:
                replies = [self._said(voice.broke(language=arrival.language or None), arrival)]
            self._publish([arrival.id], replies, final=True)
        finally:
            self._answering = [i for i in self._answering if i != arrival.id]
            self._busy -= 1
