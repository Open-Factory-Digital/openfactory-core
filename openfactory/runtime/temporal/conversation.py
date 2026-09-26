"""One conversation with the product role: a long-lived workflow, one turn at a time (#266 slice 3).

ADR-0051 D3, D5 and D6, as the engine runs them. The door (`product/door.py`) sends every message
here as a signal, starting the workflow when it is not running — signal-with-start — and returns at
once. What the workflow owns is ORDER inside one conversation, and nothing across conversations:
each conversation — a private chat, a group room — is its own workflow,
`po-{product}-{conversation}`, so two conversations never wait on each other, and inside one the
role answers one turn at a time.

    admit (signal) ──► seen before? drop — the id is the key, never a hash of the words
                   ├─► something that happened (`kind=event`)? in line, like a message: published
                   │   when its turn comes, never inside another turn (#267 slice 3)
                   ├─► an internal event? publish its replies; no turn
                   ├─► not addressed to the role (D14)? kept — recorded, searchable — no turn
                   ├─► read-only (`engine.FAST`)? answered at once, beside any turn
                   └─► pending ──► heard out (debounce) ──► one speaker's messages, one turn
                                                              │
                              bounded (about 90 s) ◄──────────┤
                              past it: "I'll come back"       ▼
                              and the answer returns     publish(Reply) → the outbox a transport
                              through the door               reads: `where` for one message's
                                                             answer, `watch` for everything since
                                                             a transport's cursor (the panel's
                                                             socket, #266 slice 5)

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

IN A GROUP, ONLY WHAT IS ADDRESSED TO THE ROLE IS A TURN (#266 slice 6, ADR-0051 D14, decision
3). Every message is heard — the people in a room see each other — and each is read by the core's
one definition (`product/addressing.py`): a direct conversation, a mention, or a reply inside a
conversation the role takes part in. What is none of those is KEPT: recorded in the product's
memory, marked, by an activity that calls no model (`conversation_overheard`), so it can be found
by recall and is never put in a turn's prompt. It starts no turn, joins nobody's coalesced turn,
and holds nobody's place in the line. Whether the role takes part is this conversation's to know —
`joined`, set the moment it is addressed or speaks here, carried across continue-as-new.

WHAT HAPPENED WAITS ITS TURN (#267 slice 3). An event the role announces — a card delivered, a
check gone red — is an item of kind `event` (`io.EVENT_KIND`), put in the same line as the
messages: behind the turn in progress and behind whatever was sent before it. Its turn is the
publishing of what it says, already composed and recorded by its producer — no activity, no model,
no debounce — so it never lands between a person's message and the answer to it. It is nobody's
turn: it is never coalesced with a person's words, and never counted in anybody's place in the
line. A late answer is not one of these: it answers a message somebody is waiting on, and is
published the moment it arrives, as before.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from openfactory.product import addressing, voice
    from openfactory.runtime.temporal.activities import (
        conversation_fast,
        conversation_overheard,
        conversation_report,
        conversation_turn,
    )
    from openfactory.runtime.temporal.io import (
        EVENT_KIND,
        Arrival,
        ConversationInput,
        OverheardInput,
        ReportInput,
        TurnInput,
    )

#: How many message ids a conversation remembers for deduplication, across continue-as-new. A
#: transport retries within seconds; five hundred messages back is far past any retry.
SEEN = 512
#: How many published entries a conversation keeps for the transports that read them back.
OUTBOX = 64
#: How many of the messages it admitted a conversation keeps for the transports watching it — so a
#: room's members see what the others said as it is said (#266 slice 5). A DISPLAY COPY, cut at
#: `HEARD_CHARS`: the transcript is the record, and a transport that falls further behind than this
#: catches up from it.
HEARD = 32
HEARD_CHARS = 4000
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
#: Keeping a message not addressed to the role: one write to the product's memory, retried — a
#: second run of it records the line twice, which costs a duplicate row and never a prompt.
KEEP_CEILING = timedelta(minutes=2)
KEEP_RETRY = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=1))


def _speaker(arrival: Arrival) -> tuple[str, str]:
    """WHO a turn is for — the person, on the registry project they were on. One turn is one
    person's: coalescing gathers what ONE speaker said, never two people's words into one prompt."""
    return arrival.speaker, arrival.project


def _happened(arrival: Arrival) -> bool:
    """Whether this item in the line is something that happened, not somebody's message."""
    return arrival.kind == EVENT_KIND


def _people_waiting(pending: list[Arrival]) -> list[tuple[str, str]]:
    """Whose turns wait, in the order they will be taken — people only. An event in the line is
    published the moment its turn comes and takes no time, so it is nobody's place in the queue:
    counting it would tell a person "two turns before yours" about one."""
    groups: list[tuple[str, str]] = []
    for a in pending:
        if not _happened(a) and _speaker(a) not in groups:
            groups.append(_speaker(a))
    return groups


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
        #: THE NUMBER EVERYTHING A TRANSPORT CAN WATCH IS GIVEN, in the order it happened: each
        #: message heard and each entry published. Carried across continue-as-new, so a cursor a
        #: transport holds is never overtaken by a count that started again.
        self._seq = max(0, int(inp.seq))
        self._heard: list[dict] = []
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
        #: WHETHER THE ROLE TAKES PART IN THIS CONVERSATION (ADR-0051 D14): addressed in it, or
        #: spoken in it — what makes a reply here a message to the role
        self._joined = bool(inp.joined)
        #: messages not addressed to the role, waiting to be kept; and the ids of those kept,
        #: so `where` can say so
        self._overheard: list[Arrival] = list(inp.overheard)
        self._kept: list[str] = []

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
        if _happened(arrival) and arrival.replies:
            # SOMETHING HAPPENED (#267 slice 3): in line like a message, published when its turn
            # comes — never between somebody's message and the answer being written to it
            self._pending.append(arrival)
            self._arrived += 1
            return
        if arrival.replies:
            # AN INTERNAL EVENT: the outcome of work the role started, already recorded by whoever
            # produced it. It is published, and starts no turn. What it answers is marked
            # answered — every message the handed-off turn covered, not only the last.
            answered = ((self._covers_of(arrival.in_reply_to) or [arrival.in_reply_to])
                        if arrival.in_reply_to else [])
            self._joined = True
            self._publish([*answered, arrival.id], list(arrival.replies), final=True)
            return
        # ADDRESSED TO THE ROLE, OR KEPT (ADR-0051 D14, decision 3) — the core's one definition,
        # read here because only this conversation knows whether the role takes part in it yet
        why = addressing.why_addressed(direct=arrival.direct, mentioned=arrival.mentions_role,
                                       in_reply_to=arrival.in_reply_to,
                                       takes_part=self._joined or arrival.took_part)
        self._hear(arrival, addressed=bool(why))
        if not why:
            # KEPT, NEVER TURNED: recorded and searchable, no turn, no place in the line, and
            # no prompt ever reads it
            self._kept = [*self._kept, arrival.id][-SEEN:]
            self._overheard.append(arrival)
            return
        self._joined = True
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
        passed the bound; the answer will follow), `answered`, `overheard` (not addressed to the
        role: kept, and never a turn — ADR-0051 D14), or `unknown` (never admitted here).
        `ahead` is how many turns come before its own; `coalesced` says it joins a turn its speaker
        already has waiting. `replies` are only ever the ones published FOR THIS MESSAGE: a reader
        is handed the answer to what it sent and to nothing else in the conversation."""
        duplicate = message_id in self._twice
        if message_id in self._kept:
            return self._stand("overheard", duplicate=duplicate)
        if any(a.id == message_id for a in self._running) or message_id in self._answering \
                or any(a.id == message_id for a in self._fast):
            return self._stand("running", duplicate=duplicate)
        waiting = [a for a in self._pending if a.id == message_id]
        if waiting and _happened(waiting[0]):
            return self._stand("queued", duplicate=duplicate)
        if waiting:
            mine = _speaker(waiting[0])
            groups = _people_waiting(self._pending)
            first = next(a for a in self._pending if not _happened(a) and _speaker(a) == mine)
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

    @workflow.query
    def watch(self, cursor: int) -> dict:
        """EVERYTHING A TRANSPORT SUBSCRIBED TO THIS CONVERSATION HAS NOT BEEN HANDED YET, and the
        role's presence in it now (#266 slice 5, ADR-0051 D13, D15).

        `where` answers one message's sender; this answers a transport that shows the whole
        conversation — the panel's socket, which reads it once per open conversation however many
        tabs are open (`api/product_chat.py`). `entries` are what was heard (`said`: a person's
        message, as admitted) and what was published (`replies`, with what they answer), each
        numbered, newer than `cursor`, oldest first; `seq` is the newest number, the cursor to
        come back with. A cursor from the future — a conversation that was started again from
        nothing — gets everything this run still holds, so the transport can tell.

        `presence` is raw and names speakers: whose messages wait, in the order their turns will
        be taken, whether a turn is running, how many read-only answers are in flight. It is for
        the transport to turn into what EACH person may see — their own place in the line, never
        anybody else's name (ADR-0051 D5)."""
        cursor = int(cursor or 0)
        if cursor > self._seq:
            cursor = 0
        fresh = [{"type": "replies", **e} for e in self._outbox if e.get("seq", 0) > cursor]
        fresh += [h for h in self._heard if h["seq"] > cursor]
        fresh.sort(key=lambda e: e["seq"])
        return {"seq": self._seq, "entries": fresh, "presence": self._presence()}

    def _presence(self) -> dict:
        groups = _people_waiting(self._pending)
        return {"running": bool(self._running), "fast": len(self._fast) + len(self._answering),
                "waiting": [speaker for speaker, _project in groups]}

    def _hear(self, arrival: Arrival, *, addressed: bool = True) -> None:
        """A person's message, numbered and kept for the transports watching the conversation —
        and whether it was for the role, so a transport does not wait for an answer to a message
        the people in the room said to each other."""
        self._seq += 1
        self._heard = [*self._heard, {"type": "said", "seq": self._seq, "id": arrival.id,
                                      "speaker": arrival.speaker,
                                      "text": arrival.text[:HEARD_CHARS],
                                      # the files it carried (#336), so the room sees them live
                                      "attachments": [dict(a) for a in
                                                      (arrival.attachments or [])][:20],
                                      "overheard": not addressed}][-HEARD:]

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
        self._seq += 1
        self._outbox = [*self._outbox, {"covers": list(dict.fromkeys(covers)), "replies": said,
                                        "final": final, "seq": self._seq}][-OUTBOX:]

    def _said(self, text: str, arrival: Arrival, *, kind: str = "answer") -> dict:
        """A sentence the conversation says in its own voice, shaped as the engine's `Reply`."""
        return {"text": text, "kind": kind, "options": None, "addressed_to": arrival.speaker,
                "in_reply_to": arrival.id, "conversation": self._conversation}

    # ── the loop ────────────────────────────────────────────────────────────────────────────────

    @workflow.run
    async def run(self, inp: ConversationInput) -> None:
        self._keep(asyncio.create_task(self._fast_lane()))
        self._keep(asyncio.create_task(self._keeping_lane()))
        while True:
            await workflow.wait_condition(lambda: bool(self._pending) or self._may_rest())
            if not self._pending:
                break
            await self._hear_out()
            turn = self._next_turn()
            if _happened(turn[0]):
                self._tell(turn[0])
                continue
            await self._take(turn)
            self._turns += 1
        workflow.continue_as_new(ConversationInput(
            product=self._product, conversation=self._conversation,
            debounce_seconds=self._debounce, bound_seconds=self._bound,
            seen=list(self._seen), outbox=list(self._outbox), pending=list(self._pending),
            seq=self._seq, joined=self._joined, overheard=list(self._overheard)))

    def _may_rest(self) -> bool:
        """Whether this run may hand over to a new one: enough turns taken, or the engine asking,
        and nothing of this run's still in flight — a detached turn's answer must come back to the
        run that is waiting for it."""
        due = self._turns >= TURNS_PER_RUN or workflow.info().is_continue_as_new_suggested()
        return (due and not self._pending and not self._running and not self._fast
                and not self._overheard and self._busy == 0)

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
            if _happened(self._pending[0]):
                return   # nobody is typing an event: it is said the moment its turn comes
            head = _speaker(self._pending[0])
            now = workflow.now()
            times = [self._at.get(a.id, now) for a in self._pending
                     if not _happened(a) and _speaker(a) == head]
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
        still answered next — one turn later, exactly as without the second message.

        AN EVENT AT THE HEAD IS ITS OWN ITEM, and an event further back is nobody's words: a
        person's coalesced turn never gathers one, and two events are never one."""
        if _happened(self._pending[0]):
            return [self._pending.pop(0)]
        head = _speaker(self._pending[0])
        turn = [a for a in self._pending if not _happened(a) and _speaker(a) == head]
        self._pending = [a for a in self._pending if _happened(a) or _speaker(a) != head]
        for a in turn:
            self._at.pop(a.id, None)
        return turn

    def _tell(self, arrival: Arrival) -> None:
        """AN EVENT'S TURN (#267 slice 3): what its producer composed and recorded, published now
        — after every turn before it has answered, so it never interleaves with one. The role
        speaks in this conversation by it, so a reply to it is a message to the role (D14)."""
        self._joined = True
        self._publish([arrival.id], list(arrival.replies), final=True)

    def _input(self, arrivals: list[Arrival]) -> TurnInput:
        last = arrivals[-1]
        return TurnInput(
            product=self._product, project=last.project, conversation=self._conversation,
            room=last.room, speaker=last.speaker,
            text="\n\n".join(a.text for a in arrivals if a.text.strip()),
            id=last.id, ids=[a.id for a in arrivals], in_reply_to=last.in_reply_to,
            source=last.source, fingerprint=last.fingerprint, via=last.via,
            language=last.language, context=dict(last.context),
            # EVERY FILE OF EVERY MESSAGE THE TURN ANSWERS (#336), once each, in order
            attachments=list({str(f.get("id", "")): dict(f) for a in arrivals
                              for f in (a.attachments or [])}.values()))

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

    # ── what is not addressed to the role: kept, never turned ───────────────────────────────────

    async def _keeping_lane(self) -> None:
        """RECORD WHAT WAS SAID IN THE ROOM TO SOMEBODY ELSE (ADR-0051 D14, decision 3) — one at a
        time, beside any turn, with no model and no ceiling slot: it is stored and searchable, and
        nothing here turns it into a turn. A write that could not be made even after its retries
        is a line in the log, and never a turn in its place."""
        while True:
            await workflow.wait_condition(lambda: bool(self._overheard))
            arrival = self._overheard[0]
            self._busy += 1
            try:
                await workflow.execute_activity(
                    conversation_overheard,
                    OverheardInput(project=arrival.project, conversation=self._conversation,
                                   room=arrival.room, speaker=arrival.speaker, text=arrival.text,
                                   id=arrival.id, in_reply_to=arrival.in_reply_to),
                    start_to_close_timeout=KEEP_CEILING, retry_policy=KEEP_RETRY)
            except ActivityError:
                workflow.logger.error("OPENFACTORY_PRODUCT_OVERHEARD_LOST conversation=%s — a "
                                      "message not addressed to the role could not be kept",
                                      self._conversation)
            finally:
                self._overheard = self._overheard[1:]
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
