"""The product chat on the panel's socket: one reader per open conversation, and every frame to
whoever may read it (#266 slice 5, ADR-0051 D13 and D15).

WHAT IT REPLACES. The product page was a form that polled: a message went to `product_say`, which
held the request open while the door polled the conversation for the answer (`door.converse`),
the page then re-read the thread every five seconds for five minutes in case the answer came later,
and the room was re-read every thirty seconds in case somebody else had spoken. Three clocks, one
set per tab, for a conversation that already knew the moment anything happened in it.

HOW IT WORKS NOW. A page opens `/api/product/stream` and subscribes to one conversation — the
project's room, or its person's own. A message it sends goes through the door and returns at once
(`product_say` with `wait=false`). What the conversation hears and publishes is read HERE, once per
open conversation however many tabs show it, from the conversation's own workflow
(`ConversationWorkflow.watch`: every entry numbered, read after a cursor) — the one way out of
ADR-0051 D13 — and handed to each subscriber this module lets read it. On (re)subscribing a page
is handed the conversation's recent turns from the transcript, which is the record; a socket that
dropped reconnects and catches up the same way.

NOT AN EVENT BUS, for the reason `api/app.py::_Broadcast` gives: the producer is the worker, in
another process, and what the two share is the durable engine. So this reads the engine on a
short clock while a conversation is open, and nothing reads it for a conversation nobody shows —
where the page used to read the store on a long clock whether anybody was writing or not.

THE FILTER IS THE ROUTING (`may_receive`). Every frame is offered to every subscriber of this
process and each one is ASKED: a private conversation's frames reach only the person whose key it
is — not because a subscription happened to be made right, but by a check made on every frame —
and a room's reach the people who may read the product area. What a subscriber is told about the
queue is its own place in it and never anybody else's name (ADR-0051 D5).

WHAT DOES NOT STREAM, SAID PLAINLY. The role's answer arrives WHOLE, the moment the conversation
publishes it: no harness in the core hands a product turn's text over as it is written. The
product role's `ask` returns a finished run; the stream a harness narrates is whole assistant
messages around tool calls, not the answer's tokens; and the answer is post-processed before
anybody may see it — markers stripped, a request turned into a staged draft, a claimed write
flagged. The presence this module publishes (`thinking`, then `answering` as the reply goes out)
is what the page shows in the meantime — and, since #395, WHAT the role is doing while it thinks
(`stage`: "lendo o quadro", "revisando o cartão (1/2)"), one line the page replaces in place.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import weakref
from dataclasses import dataclass, field

log = logging.getLogger("openfactory.api.product_chat")

#: How often an open conversation is read while something is happening in it (a message waiting,
#: a turn running), while nothing is, and after the engine did not answer.
BUSY_TICK = 0.4
IDLE_TICK = 1.5
AWAY_TICK = 5.0

#: How many frames wait for one socket. A socket that falls this far behind is told to catch up
#: from the transcript (`resync`) rather than handed a conversation with a hole in it.
QUEUE = 128

#: For how long after a page was handed the recent turns a live frame saying the same words is
#: the same turn — recorded in the transcript just before the page read it, and published just
#: after. DUPLICATES RATHER THAN GAPS: the history is read after the subscription is live, so a turn
#: is in the history, in a live frame, or in both, and never in neither.
ECHO_SECONDS = 10.0
#: How many of the last turns of that history such a frame is compared with.
ECHO_TURNS = 6

#: The presence a page shows — ADR-0051 D15's words, and `offline` for an engine that did not
#: answer, which is not a role with nothing to do.
IDLE, THINKING, ANSWERING, OFFLINE = "idle", "thinking", "answering", "offline"

#: A subscriber nobody has told yet what waits for it — distinct from None, which is "nothing".
_UNTOLD = object()


def staged_for(project, conversation: str, person: str) -> dict | None:
    """What waits for `person`'s answer in `conversation` — `{token, approve, reject}` or None —
    AS THE STORE SAYS IT (#443, `staging.waiting_in`).

    THE PAGE REPLACES ITS OWN WITH THIS, never keeps a token this did not name. It kept the token
    of the last reply that carried buttons until somebody clicked one, so a proposal answered any
    other way — a typed "sim", a click in another tab, an expiry — left its buttons on the page,
    and a history read after a restart drew them alone, under no question."""
    from openfactory.product.staging import waiting_in

    return waiting_in(project, conversation, person)


@dataclass(eq=False)
class Subscriber:
    """One socket, subscribed to one conversation.

    `person` is the actor's id — whose place in the queue this subscriber is told, and whose own
    messages are `mine`. `own` is the actor's private key (`person:`/`visitor:`, or "" for a
    caller the panel could not key); `may_read_room` whether the actor may read the product area.
    `generation` changes when the socket subscribes again, so a frame queued for the conversation
    it left is not delivered into the one it joined. `held` gathers what arrives while the
    subscriber's history is being read, so the history is always the first thing it is handed."""

    person: str
    own: str
    product: str
    project: str
    conversation: str
    may_read_room: bool
    frames: asyncio.Queue
    generation: int = 0
    held: list | None = field(default_factory=list)
    echoes: list[tuple[str, str]] = field(default_factory=list)
    echo_until: float = 0.0
    presence: dict | None = None
    #: The proposal this subscriber was last told is waiting (`staged_for`), so a `staged` frame
    #: is said when it changes and never on every read. `_UNTOLD` until its history is read.
    staged: object = field(default_factory=lambda: _UNTOLD)


def may_receive(sub: Subscriber, *, product: str, conversation: str) -> bool:
    """WHETHER ONE FRAME OF ONE CONVERSATION MAY REACH ONE SUBSCRIBER — asked for every frame.

    A frame reaches only a subscriber of THAT conversation of THAT product. A private one reaches
    only the person whose key it is: `own` is minted by the panel from who the credential names
    (`api/app.py::_conversation_of`), never taken from the page, so a subscription that somehow
    named another person's key would still be handed nothing of theirs. A room reaches whoever may
    read the product area — the rule every read of the room already has (`product_thread`)."""
    from openfactory.product.conversation import is_private, owner_of

    if sub.product != product or sub.conversation != conversation:
        return False
    if is_private(conversation):
        # ITS OWNER, whichever of their sessions it is (#335)
        return bool(sub.own) and owner_of(conversation) == sub.own
    return sub.may_read_room


def presence_for(raw: dict | None, person: str) -> dict:
    """The role's presence in a conversation, as ONE person may see it.

    `raw` is the conversation's own account (`ConversationWorkflow.watch`), which names whose
    messages wait; what comes out names nobody. `ahead` is how many turns come before this
    person's — 0 when none of theirs is waiting, or when theirs is next and nothing runs.

    `stage` IS WHAT THE ROLE IS DOING NOW (#395), in the person's words — "lendo o quadro" — and
    present only while it is thinking and has said one. The frame is deduplicated per subscriber
    (`_put`), so a page is handed each stage once and REPLACES the last with it: one status line,
    never a bubble per stage. A turn past its bound is still at work (`working`), so the role is
    still thinking — the silence #395 measured began exactly where this used to say idle."""
    if raw is None:
        return {"kind": "presence", "state": OFFLINE, "ahead": 0}
    waiting = [str(w) for w in (raw.get("waiting") or [])]
    running = bool(raw.get("running"))
    busy = (running or int(raw.get("fast") or 0) > 0 or bool(waiting)
            or int(raw.get("working") or 0) > 0)
    ahead = waiting.index(person) + (1 if running else 0) if person in waiting else 0
    stage = str(raw.get("stage") or "").strip() if busy else ""
    return {"kind": "presence", "state": THINKING if busy else IDLE, "ahead": ahead,
            **({"stage": stage} if stage else {})}


def frames_of(entry: dict, sub: Subscriber) -> list[dict]:
    """The frames one numbered entry of the conversation becomes, for one subscriber."""
    seq = int(entry.get("seq") or 0)
    if entry.get("type") == "said":
        speaker = str(entry.get("speaker") or "")
        # `overheard`: said to the room, not to the role (ADR-0051 D14) — nobody waits for an
        # answer to it
        return [{"kind": "said", "seq": seq, "id": str(entry.get("id") or ""),
                 "text": str(entry.get("text") or ""), "speaker": speaker,
                 "mine": bool(speaker) and speaker == sub.person,
                 "overheard": bool(entry.get("overheard")),
                 **({"attachments": list(entry["attachments"])}
                    if entry.get("attachments") else {})}]
    out = []
    for n, reply in enumerate(entry.get("replies") or []):
        out.append({"kind": "reply", "seq": seq, "id": f"{seq}.{n}",
                    "text": str(reply.get("text") or ""),
                    "type": str(reply.get("kind") or "answer"),
                    "in_reply_to": str(reply.get("in_reply_to") or ""),
                    "options": reply.get("options") or None,
                    "final": bool(entry.get("final", True))})
    return out


class _Watch:
    """The one reader of one open conversation."""

    def __init__(self, hub: ProductChat, product: str, conversation: str) -> None:
        from openfactory.product import door

        self.hub, self.product, self.conversation = hub, product, conversation
        self.wid = door.workflow_id(product, conversation)
        self.cursor = 0
        self.raw: dict | None = {"running": False, "fast": 0, "waiting": []}
        self.primed = asyncio.Event()
        self.poke = asyncio.Event()
        self.task: asyncio.Task | None = None

    async def run(self) -> None:
        while True:
            try:
                tick = await self._once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — one bad read must not end the watch
                log.warning("the product chat could not read %s (%s)", self.wid, str(exc)[:200])
                tick = AWAY_TICK
            finally:
                self.primed.set()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.poke.wait(), timeout=tick)
            self.poke.clear()

    async def _once(self) -> float:
        from openfactory.product import door

        try:
            client = await self.hub.engine()
            got = await door.watch(client, self.wid, self.cursor)
        except door.NotStarted:
            self._present({"running": False, "fast": 0, "waiting": []})
            return IDLE_TICK
        except Exception as exc:  # noqa: BLE001 — an engine that did not answer is a presence
            log.info("the product chat could not reach %s (%s)", self.wid, str(exc)[:160])
            self._present(None)
            return AWAY_TICK
        seq = int(got.get("seq") or 0)
        entries = list(got.get("entries") or [])
        # THE FIRST READ ONLY SETS THE CURSOR: what came before it is history, and a subscriber is
        # handed history from the transcript. A conversation started again from nothing (its
        # count below the cursor) is read from its beginning.
        if self.primed.is_set() or seq < self.cursor:
            self._deliver(entries)
            if entries:
                # SOMETHING WAS SAID OR ANSWERED: what waits may have changed — a proposal staged,
                # or one answered by a typed yes the reply after it only thanks for (#443)
                await self.hub.restage(self.product, self.conversation)
        self.cursor = seq
        self._present(got.get("presence") or {})
        raw = self.raw or {}
        return BUSY_TICK if (raw.get("running") or raw.get("fast") or raw.get("waiting")
                             or raw.get("working")) else IDLE_TICK

    def _deliver(self, entries: list[dict]) -> None:
        if any(e.get("type") == "replies" and e.get("replies") for e in entries):
            # THE REPLY GOES OUT, said as a presence first — the one moment `answering` is true
            # while nothing streams; the presence read next says what the role does after it
            self.hub.offer(self.product, self.conversation,
                           lambda _sub: {"kind": "presence", "state": ANSWERING, "ahead": 0},
                           presence=True)
        for entry in entries:
            self.hub.offer(self.product, self.conversation,
                           lambda sub, entry=entry: frames_of(entry, sub))

    def _present(self, raw: dict | None) -> None:
        self.raw = raw
        self.hub.offer(self.product, self.conversation,
                       lambda sub: presence_for(raw, sub.person), presence=True)


class ProductChat:
    """The fan-out of one event loop: its subscribers, and a reader per open conversation."""

    def __init__(self, engine=None) -> None:
        self._subs: set[Subscriber] = set()
        self._watches: dict[tuple[str, str], _Watch] = {}
        self._engine = engine

    async def engine(self):
        if self._engine is not None:
            return await self._engine()
        from openfactory.product import door

        return await door._engine()

    async def subscribe(self, sub: Subscriber) -> None:
        """Attach `sub`, starting its conversation's reader if nobody was reading it, and return
        once that reader has read the conversation once — so its live frames start after a cursor
        that was set before its history is read. What arrives meanwhile is HELD (`release`)."""
        self._subs.add(sub)
        key = (sub.product, sub.conversation)
        watch = self._watches.get(key)
        if watch is None or watch.task is None or watch.task.done():
            watch = _Watch(self, sub.product, sub.conversation)
            self._watches[key] = watch
            watch.task = asyncio.create_task(watch.run())
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(watch.primed.wait(), timeout=AWAY_TICK)
        self._put(sub, presence_for(watch.raw, sub.person), presence=True)

    def release(self, sub: Subscriber, first: dict) -> None:
        """Hand `sub` the frame that opens its subscription — its history — and then everything
        that was held while it was read, in the order it arrived."""
        held, sub.held = list(sub.held or []), None
        self._queue(sub, first)
        for frame in held:
            self._queue(sub, frame)

    def unsubscribe(self, sub: Subscriber) -> None:
        self._subs.discard(sub)
        key = (sub.product, sub.conversation)
        if any((s.product, s.conversation) == key for s in self._subs):
            return
        watch = self._watches.pop(key, None)
        if watch is not None and watch.task is not None:
            watch.task.cancel()

    async def restage(self, product: str, conversation: str) -> None:
        """Tell every subscriber of this conversation what waits for its answer now, when that is
        not what it was last told (#443). One store read per person, off the loop."""
        from openfactory.registry import ProjectRegistry

        subs = [s for s in list(self._subs)
                if may_receive(s, product=product, conversation=conversation)
                and s.staged is not _UNTOLD]
        said: dict[tuple[str, str], dict | None] = {}
        for sub in subs:
            who = (sub.project, sub.person)
            if who not in said:
                def _read(name=sub.project, person=sub.person):
                    try:
                        project = ProjectRegistry().get(name)
                    except KeyError:
                        return None
                    return staged_for(project, conversation, person)
                said[who] = await asyncio.to_thread(_read)
            now = said[who]
            if now != sub.staged:
                sub.staged = now
                self._put(sub, {"kind": "staged", "staged": now})

    def poke(self, product: str, conversation: str) -> None:
        """Something was just sent into this conversation: read it now, not at the next tick."""
        watch = self._watches.get((product, conversation))
        if watch is not None:
            watch.poke.set()

    def offer(self, product: str, conversation: str, frames, *, presence: bool = False) -> None:
        """Offer one conversation's frames to every subscriber, and hand them to whoever
        `may_receive` them. `frames` makes the frame (or the list of frames) for one subscriber."""
        for sub in list(self._subs):
            if not may_receive(sub, product=product, conversation=conversation):
                continue
            made = frames(sub)
            for frame in (made if isinstance(made, list) else [made]):
                self._put(sub, frame, presence=presence)

    def _put(self, sub: Subscriber, frame: dict, *, presence: bool = False) -> None:
        if presence:
            # A PRESENCE THAT DID NOT CHANGE IS NOT SAID AGAIN — the reader reads on a clock
            if frame == sub.presence:
                return
            sub.presence = frame
        if sub.held is not None:
            sub.held.append(frame)
            return
        self._queue(sub, frame)

    def _queue(self, sub: Subscriber, frame: dict) -> None:
        if self._an_echo(sub, frame):
            return
        try:
            sub.frames.put_nowait((sub.generation, frame))
        except asyncio.QueueFull:
            # A SOCKET THIS FAR BEHIND IS TOLD TO CATCH UP, never handed a conversation with a
            # hole in it: what it missed is in the transcript, which subscribing again reads
            while not sub.frames.empty():
                sub.frames.get_nowait()
            sub.frames.put_nowait((sub.generation, {"kind": "resync"}))

    @staticmethod
    def _an_echo(sub: Subscriber, frame: dict) -> bool:
        """Whether a live frame says what the history just handed to this subscriber already said
        (`ECHO_SECONDS`) — dropped once, the first time it is seen."""
        if not sub.echoes:
            return False
        if time.monotonic() > sub.echo_until:
            sub.echoes = []
            return False
        role = {"said": "person", "reply": "agent"}.get(frame.get("kind"))
        if not role:
            return False
        # BY IDENTITY FIRST (#402): a person's line is the same turn when it carries the same id,
        # an answer when it answers the same message. The words decide only for a history row
        # recorded with neither, so an answer that merely says what an earlier one said — the same
        # "Registrado." to a second proposal — is delivered, never taken for its echo.
        for said in (_echo_key(role, frame.get("id") if role == "person"
                               else frame.get("in_reply_to"), ""),
                     _echo_key(role, "", frame.get("text"))):
            if said[1] and said in sub.echoes:
                sub.echoes.remove(said)
                return True
        return False


#: One fan-out per event loop. A panel runs on one loop; a test client may run each socket on a
#: loop of its own, and a queue or a task must never be shared across two — each loop's fan-out
#: reads the engine for its own subscribers (the pool `runtime/temporal/view.connect` keys by
#: loop, for the same reason).
_hubs: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def hub() -> ProductChat:
    loop = asyncio.get_running_loop()
    found = _hubs.get(loop)
    if found is None:
        found = _hubs[loop] = ProductChat()
    return found


# ── the panel's own way of detecting a mention (#266 slice 6, ADR-0051 D14) ────────────────────

#: The handles the panel's room reads as naming the product role, besides the role's own name:
#: the word on the dock's button, and the role's function. Words nobody in a room says to a person.
HANDLES = ("po", "product")


def _flat(text: str) -> str:
    """Lower case, accents off — `@Nína` and `@nina` name the same role."""
    import unicodedata

    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore") \
        .decode().lower()


def mentions_the_role(text: str, project) -> bool:
    """WHETHER A MESSAGE IN THE PANEL'S ROOM NAMES THE PRODUCT ROLE — the panel's detection, the
    one part of D14 that is the transport's (`product/addressing.py` is the core's).

    `@` and the role's name (`product.agent_name`, whole or its first word) or one of `HANDLES`,
    as a whole word, anywhere in the message, ignoring case and accents: `@Nina, can you…`,
    `… right @po?`. Nothing else is a mention: a message that merely contains the name is people
    talking ABOUT the role, which is exactly what a room is for."""
    import re

    name = str(getattr(getattr(project, "product", None), "agent_name", "") or "").strip()
    names = {*HANDLES}
    if name:
        names |= {_flat(name), _flat(name.split()[0])}
    said = _flat(text)
    return any(re.search(rf"(?<![\w@])@{re.escape(n)}(?![\w])", said) for n in names if n)


# ── one socket ──────────────────────────────────────────────────────────────────────────────────

def conversation_for(actor, project, asked: dict) -> tuple[str, str]:
    """`(key, "")` — the conversation a subscription is for — or `("", why)`.

    THE PAGE NEVER NAMES A PRIVATE CONVERSATION. It says `room` (the project's room) or not (its
    person's own), and may name a room thread; the key is resolved by the rule every product row
    uses (`product/conversation.py::key_for`) against the key the panel minted for this person —
    so a private key that is not the person's own is refused here, before anything is read.

    A SESSION IS NAMED BY ITS ID ALONE (#335): `session` beside `room: false` is one of the
    person's own conversations, built on the key the panel minted — the page still never spells
    a private key, and cannot name somebody else's session because it cannot name their key."""
    from openfactory.product.conversation import key_for, session_key

    room = str(getattr(project, "name", "") or "")
    named = str(asked.get("thread") or "").strip()
    if not named and asked.get("room", True):
        named = room
    session = str(asked.get("session") or "").strip()
    if not named and session:
        named = session_key(getattr(actor, "conversation", "") or "", session) or ""
        if not named:
            return "", "that is not a conversation of yours this page can open."
    key = key_for(named=named, own=getattr(actor, "conversation", "") or "")
    if key is None:
        return "", ("that conversation is one person's alone — name the project's room, or "
                    "nothing for your own.")
    return key or room, ""


def _echo_key(role: str, ident, text) -> tuple[str, str]:
    """What a turn of the history is recognised by when it comes back as a live frame (#402): the
    identity that names it — a person's line by its own id, an answer by the message it answers —
    and the words only when it was recorded with neither (a proactive post, a row written before
    #266 slice 4). Never both: a key made of the words is what matched two different answers that
    happened to say the same thing."""
    ident = str(ident or "").strip()
    return (f"{role}#", ident) if ident else (role, str(text or "").strip())


def _history(project, key: str, person: str, *, before: str = "") -> tuple[list[dict], str]:
    """One page of the conversation from the transcript, and the cursor of the page before it
    (`""` at its start) — the catch-up a page is handed on subscribing, and each earlier page it
    asks for: EVERY LINE, the ones the room said to each other included (ADR-0051 D14) — this shows
    the room to the people in it, and builds no prompt.

    PAGED, NEVER BUDGETED (#566). It read `transcript.recent`, the prompt's read: the newest turns
    within 6,000 characters, so a person who reopened their own conversation saw its end — the
    first four of fourteen turns, where the requirement was worked out, were unreachable."""
    from openfactory.memory import transcript

    agent = getattr(getattr(project, "product", None), "agent_name", "") or "product"
    turns, cursor = transcript.page(project, thread=key, before=before)
    held = _held(project, key) if any(t.attachments for t in turns) else set()
    # WITH WHICH MESSAGE EACH TURN IS, AND WHICH ONE IT ANSWERS (#402). The transcript has kept
    # both since #266 slice 4 and this read dropped them, so the page could reconcile what it
    # already showed with what the store repaints by nothing but the words: a clicked yes's answer
    # it had drawn itself came back beside the same row, and was shown twice.
    return [{"role": t.role, "actor": agent if t.role == "agent" else (t.actor or ""),
             "text": t.text, "ts": t.ts, "id": t.id, "in_reply_to": t.in_reply_to,
             "mine": t.role != "agent" and bool(t.actor) and t.actor == person,
             "overheard": not t.addressed,
             **({"attachments": [_marked(f, held) for f in t.attachments]}
                if t.attachments else {})}
            for t in turns], cursor


def _held(project, key: str) -> set[str]:
    """The ids of the files `key` still holds — a line names a file it carried, and one discarded
    since (#336) is shown as gone rather than as a link that fails."""
    from openfactory.product import attachments as files
    from openfactory.product.key import product_key

    return {f["id"] for f in files.listed_in(product_key(project), key)}


def _marked(file: dict, held: set[str]) -> dict:
    return {**file, "gone": True} if str(file.get("id") or "") not in held else dict(file)


async def serve(ws, *, actor, watch, close_code) -> None:
    """One accepted socket, for as long as it lasts and its credential holds.

    `actor` is who the credential names, resolved by the panel the way every row's actor is;
    `watch` is the credential's watch (`api/app.py::_CredentialWatch`), asked again on its own
    clock — the socket ends, with a `bye`, when the answer is no. EVERY FRAME LEAVES THROUGH ONE
    QUEUE AND ONE LOOP, so what a page is told arrives in the order it happened: its subscription,
    its history, then the conversation live."""
    fan = hub()
    frames: asyncio.Queue = asyncio.Queue(maxsize=QUEUE)
    state: dict = {"sub": None, "generation": 0}

    async def _tell(frame: dict) -> None:
        # a frame for this socket whatever it is subscribed to: an ack, a refusal
        await frames.put((None, frame))

    async def _subscribe(asked: dict) -> None:
        from openfactory.actions.base import PRODUCT
        from openfactory.product.conversation import is_private
        from openfactory.product.key import product_key
        from openfactory.registry import ProjectRegistry

        name = str(asked.get("project") or "").strip()
        try:
            project = await asyncio.to_thread(ProjectRegistry().get, name)
        except KeyError:
            project = None
        cfg = getattr(project, "product", None)
        if project is None or cfg is None or not getattr(cfg, "enabled", True):
            await _tell({"kind": "refused", "why": f"there is no product role to talk to on "
                                                   f"{name!r}."})
            return
        if not actor.may_enter(PRODUCT):
            await _tell({"kind": "refused", "why": "this credential may not read the product "
                                                   "area."})
            return
        key, why = conversation_for(actor, project, asked)
        if why:
            log.warning("DENIED_CONVERSATION %s by %s", name, actor)
            await _tell({"kind": "refused", "why": why})
            return
        if state["sub"] is not None:
            fan.unsubscribe(state["sub"])
        state["generation"] += 1
        generation = state["generation"]
        sub = Subscriber(person=actor.id, own=getattr(actor, "conversation", "") or "",
                         product=product_key(project), project=project.name, conversation=key,
                         may_read_room=actor.may_enter(PRODUCT), frames=frames,
                         generation=generation)
        state["sub"] = sub
        state["project"] = project
        from openfactory.product.conversation import session_of

        await frames.put((generation, {"kind": "subscribed", "project": project.name,
                                       "private": is_private(key),
                                       "room": key == project.name,
                                       "session": session_of(key)}))
        await fan.subscribe(sub)
        # THE CATCH-UP IS THE TRANSCRIPT, read once the subscription is live
        turns, earlier = await asyncio.to_thread(_history, project, key, actor.id)
        sub.echoes = [_echo_key(t["role"], t["id"] if t["role"] != "agent" else t["in_reply_to"],
                                t["text"]) for t in turns[-ECHO_TURNS:]]
        sub.echo_until = time.monotonic() + ECHO_SECONDS
        # …AND WHAT WAITS FOR THEIR ANSWER, from the store — the page replaces its own with it
        sub.staged = await asyncio.to_thread(staged_for, project, key, actor.id)
        # `earlier`: the cursor of the page before this one, `""` when this is the whole of it
        fan.release(sub, {"kind": "history", "turns": turns, "staged": sub.staged,
                          "earlier": earlier})

    async def _earlier(asked: dict) -> None:
        """THE PAGE BEFORE THE ONE SHOWN (#566), of the conversation this socket is subscribed
        to — never one the frame names, so a page asks only for more of what it may already read.
        """
        sub, project = state["sub"], state.get("project")
        if sub is None or project is None:
            return
        turns, earlier = await asyncio.to_thread(_history, project, sub.conversation, actor.id,
                                                 before=str(asked.get("before") or "")[:256])
        # UNDER THE SUBSCRIPTION'S GENERATION, like the catch-up: a page that changed conversation
        # while this was read drops it, rather than drawing one conversation's turns on another
        await frames.put((sub.generation, {"kind": "earlier", "turns": turns,
                                           "earlier": earlier}))

    async def _say(asked: dict) -> None:
        from openfactory import actions

        sub = state["sub"]
        said_id = str(asked.get("id") or "")
        if sub is None:
            await _tell({"kind": "ack", "id": said_id, "ok": False,
                         "text": "open a conversation before writing in it."})
            return
        text = str(asked.get("text") or "")
        # THE PANEL DETECTS THE MENTION ITS OWN WAY, here, from the words — never from a flag the
        # page could set (ADR-0051 D14). In a person's own conversation every message is for the
        # role; the core reads that from the key, whatever this says.
        mentioned = mentions_the_role(text, state.get("project"))
        files = asked.get("attachments") or []
        outcome = await actions.perform(
            "product_say", by=actor, project=sub.project, message=text,
            thread=sub.conversation, context=asked.get("context") or None,
            message_id=said_id, wait="false", mentioned="true" if mentioned else "false",
            **({"attachments": [str(f) for f in files][:20]} if isinstance(files, list)
               and files else {}))
        data = dict(outcome.data or {})
        await _tell({"kind": "ack", "id": said_id, "ok": outcome.ok, "text": outcome.message,
                     "state": data.get("state", ""), "ahead": data.get("ahead", 0)})
        if outcome.ok:
            fan.poke(sub.product, sub.conversation)

    async def _read() -> None:
        while True:
            try:
                asked = await ws.receive_json()
            except ValueError:
                continue
            if not isinstance(asked, dict):
                continue
            try:
                if asked.get("kind") == "subscribe":
                    await _subscribe(asked)
                elif asked.get("kind") == "say":
                    await _say(asked)
                elif asked.get("kind") == "earlier":
                    await _earlier(asked)
            except Exception:  # noqa: BLE001 — one frame that broke must not end the socket mute
                log.exception("the product chat could not handle a %r frame",
                              str(asked.get("kind"))[:20])
                await _tell({"kind": "refused", "id": str(asked.get("id") or "")[:128],
                             "why": "something broke on our side — nothing was sent; try again "
                                    "in a moment."})

    async def _until_the_credential_ends() -> None:
        # THE SOCKET'S HANDSHAKE WAS ITS ONLY GATE until #208; this is the same re-check the floor's
        # socket makes, on the same watch, speaking through the same queue
        while True:
            await asyncio.sleep(watch.seconds_left())
            said = await watch.ended() if watch.due() else None
            if said is None:
                continue
            while frames.full():
                frames.get_nowait()
            frames.put_nowait((None, {"kind": "bye", "reason": said.get("detail", ""),
                                      "ended": said}))
            return

    reader = asyncio.create_task(_read())
    watcher = asyncio.create_task(_until_the_credential_ends())
    try:
        await ws.send_json({"kind": "hello"})
        while True:
            getting = asyncio.create_task(frames.get())
            done, _ = await asyncio.wait({getting, reader}, return_when=asyncio.FIRST_COMPLETED)
            if getting not in done:
                getting.cancel()
                reader.result()  # the page went away, or its reader broke: this socket ends
                return
            generation, frame = getting.result()
            if frame.get("kind") == "bye":
                await ws.send_json(frame)
                why = frame["ended"]["why"]
                await ws.close(code=close_code(why), reason=why)
                return
            if generation is None or generation == state["generation"]:
                await ws.send_json(frame)
    except Exception as exc:  # noqa: BLE001 — a page that left ends the loop; anything else is said
        if type(exc).__name__ != "WebSocketDisconnect":
            log.warning("the product chat socket ended (%s)", str(exc)[:200])
    finally:
        reader.cancel()
        watcher.cancel()
        if state["sub"] is not None:
            fan.unsubscribe(state["sub"])
