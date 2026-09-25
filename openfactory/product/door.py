"""The ONE DOOR into the product role — `receive(Message)` (#266 slice 3, ADR-0051 D1).

THREE DOORS DRIFTED APART BECAUSE EACH WAS WRITTEN FOR ONE CALLER. The panel's box reached the role
through one row, the chat add-on through `channel.handle`, and the baseline's outcome through a bare
`say` from a thread — three ways in, each answering in the process that called it, and nothing
ordering two people who wrote at once. Every one of them comes through here now: the panel's row,
the CLI (which is the same row), the chat add-on's adapter, and every INTERNAL EVENT — the result
of an asynchronous task the role started, coming back to the conversation it was started from.

WHAT THE DOOR DOES, AND ALL IT DOES:

  - validates the message (a project with a product role, a conversation, words or an event's
    replies, sizes a workflow's history can carry);
  - resolves the registry project the speaker is on to its PRODUCT (`product/key.py`, D2) — past
    this line nothing keys a conversation by registry project;
  - enqueues the message on its conversation: a signal carrying the message's own id, to the
    conversation's long-lived workflow, started if it is not running (signal-with-start,
    `runtime/temporal/conversation.py`). The workflow deduplicates by that id;
  - returns an ACKNOWLEDGEMENT at once — within two seconds, whatever the role is doing — and
    never calls a model.

BUSY IS A PRESENCE, NEVER A REFUSAL (D5). The acknowledgement says where the message stands: a
receipt when the role is free to take it, "I have your message; you are next" when it is answering
somebody else in the conversation — WITHOUT THAT SOMEBODY'S NAME, in any language
(`voice.you_are_next` has no place a name could go), and nothing when the speaker's earlier message
is already waiting and this one joins it.

THE PANEL IS A CHAT (slice 5): its socket sends through `receive` and returns, and what the role
says comes back to the page as it is published — read ONCE per open conversation by the panel's
fan-out (`watch`, `api/product_chat.py`), never by the page asking again. A caller that wants the
answer in the same call — the CLI's row, the chat adapter — still waits for it: `converse` sends
through the door and then reads the conversation's outbox (`wait`) for the replies whose
`in_reply_to` is its own message — a bounded wait, because a turn is bounded and anything longer is
handed off and comes back later through this same door.

WHAT THE DOOR TRUSTS. A private conversation's key is its person's (`product/conversation.py`), and
the rows that call this resolve it for the caller before building the message (`catalog.
_conversation_key`) — the door is reached only through core code, never by a request that named a
conversation itself.

WHO THE MESSAGE IS FOR (#266 slice 6, ADR-0051 D14). The door hands the conversation what it can
know about that without the conversation: whether it is a DIRECT one with the role (a private key,
or a transport that said so), whether the transport detected the role MENTIONED, and — only for a
reply that neither made addressed, the one case that needs it — whether the product's memory holds
the role speaking in this conversation (`transcript.took_part`). The conversation decides
(`product/addressing.py`), and a message it keeps rather than turns is acknowledged as kept: said
to the room, not to the role.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import timedelta

from pydantic import BaseModel, ConfigDict

from openfactory.product.engine import Message, Reply

log = logging.getLogger("openfactory.product.door")

#: The conversation's workflow type, its signal and its query — named as strings, like every
#: other workflow the core starts, so this module imports no Temporal code until it is used.
WORKFLOW = "ConversationWorkflow"
SIGNAL = "admit"
QUERY = "where"
WATCH = "watch"

#: The transport an internal event says it came through: the role itself.
EVENT = "event"

#: THE NUMBERS ADR-0051 LEFT TO THIS SLICE, as documented defaults (`docs/configuration.md`).
#: "A few seconds" of debounce: long enough for a burst of two or three lines, short enough that a
#: single question does not feel ignored. About ninety seconds of turn (decision 4).
DEFAULT_DEBOUNCE_SECONDS = 3.0
DEFAULT_BOUND_SECONDS = 90.0
DEBOUNCE_ENV = "OPENFACTORY_PRODUCT_DEBOUNCE_SECONDS"
BOUND_ENV = "OPENFACTORY_PRODUCT_TURN_BOUND_SECONDS"

#: The longest message the door admits. A message is a signal, and a signal is history the engine
#: keeps; a pasted document belongs in a file the role reads, not in a workflow's history.
MAX_TEXT = 32_000
#: The longest id and conversation key admitted — ids and keys, never payloads.
MAX_ID = 128
MAX_CONVERSATION = 512
#: What an admitted page context carries (`product/page.py::admit`).
_CONTEXT_KEYS = frozenset({"page", "card"})

#: How long the door waits to hear where a message stands before it acknowledges anyway. Under
#: the two seconds D5 promises, with room for the signal before it.
_ASK_WITHIN = timedelta(seconds=1.2)
#: A waiter's pauses between reads of the outbox: brisk at first, then once a second.
_FIRST_PAUSE, _LONGEST_PAUSE = 0.2, 1.0
#: The longest any caller waits in one call — the ten minutes the panel's box already waited for
#: the per-message workflow this replaced.
_LONGEST_WAIT = 600.0

#: Where a message stands, as the conversation says it (`ConversationWorkflow.where`).
#: `overheard` is a message not addressed to the role (ADR-0051 D14): kept, and settled at once —
#: nothing will ever be said back to it.
QUEUED, RUNNING, ANSWERED, HANDED_OFF, OVERHEARD, UNKNOWN = (
    "queued", "running", "answered", "handed_off", "overheard", "unknown")
_SETTLED = (ANSWERED, HANDED_OFF, OVERHEARD)


@dataclass(frozen=True)
class Settings:
    """The door's two numbers: how long a conversation hears a speaker out before a turn, and how
    long a turn may hold its conversation before it is handed off."""

    debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS
    bound_seconds: float = DEFAULT_BOUND_SECONDS

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(debounce_seconds=_seconds(DEBOUNCE_ENV, DEFAULT_DEBOUNCE_SECONDS, zero=True),
                   bound_seconds=_seconds(BOUND_ENV, DEFAULT_BOUND_SECONDS, zero=False))

    def wait_for(self, ahead: int) -> float:
        """How long a caller waits for its answer: the turns in front of it and its own, each
        bounded, plus the longest the debounce may hold one — never more than ten minutes."""
        held = self.debounce_seconds * 4
        return min(_LONGEST_WAIT, self.bound_seconds * (1 + max(0, ahead)) + held + 15.0)


def _seconds(name: str, default: float, *, zero: bool) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = -1.0
    if value < 0 or (value == 0 and not zero):
        log.error("%s=%r is not a usable number of seconds — using the default, %s", name, raw,
                  default)
        return default
    return value


class Ack(BaseModel):
    """What the door answers, at once, for every message it is handed.

    `accepted` is False only for a message the door would not enqueue, and `reason` then says why
    in a sentence. `text` is the acknowledgement a transport may show — empty when there is nothing
    worth saying (a duplicate, a message joining one its speaker already has waiting, a read that
    is answered at once). `state` and `ahead` are where the message stands (see the constants
    above). `workflow_id` is the conversation's, for the waiter."""

    model_config = ConfigDict(frozen=True)

    accepted: bool
    id: str = ""
    product: str = ""
    conversation: str = ""
    workflow_id: str = ""
    state: str = UNKNOWN
    ahead: int = 0
    duplicate: bool = False
    text: str = ""
    reason: str = ""


# ── the conversation's name ─────────────────────────────────────────────────────────────────────

def conversation_slug(conversation: str) -> str:
    """The conversation key in a spelling a workflow id can carry: its readable part, and a digest
    of the EXACT key — so two keys that read alike (`person:ana` and `person-ana`) are never one
    conversation. Deterministic, which Python's `hash` is not: the old ids ended in
    `hash(text)`, randomised per process, and no retry ever found its own workflow again."""
    readable = re.sub(r"[^a-z0-9]+", "-", conversation.lower()).strip("-")[:48].rstrip("-")
    digest = hashlib.sha256(conversation.encode("utf-8")).hexdigest()[:10]
    return f"{readable or 'conversation'}-{digest}"


def workflow_id(product: str, conversation: str) -> str:
    """`po-{product}-{conversation}` (ADR-0051 D3): one workflow per conversation of a PRODUCT, so
    the same conversation reached from two registry projects of one product is one queue. Nothing
    in it is a hash of what anybody said."""
    from openfactory.product.key import product_slug

    return f"po-{product_slug(product)}-{conversation_slug(conversation)}"


# ── the door ────────────────────────────────────────────────────────────────────────────────────

def _registered(name: str):
    from openfactory.registry import ProjectRegistry

    try:
        return ProjectRegistry().get(name)
    except KeyError:
        return None


def refusal(message: Message, project) -> str:
    """Why the door will not enqueue this message, in a sentence — or "" when it will."""
    if project is None:
        return f"there is no project called {message.project!r} on this deployment."
    if getattr(project, "name", None) != message.project:
        return (f"a message for {message.project!r} was handed the project "
                f"{getattr(project, 'name', '?')!r}.")
    cfg = getattr(project, "product", None)
    if cfg is None or not getattr(cfg, "enabled", True):
        # ADR-0051 D1: a registry project with no active product link has no role to talk to
        return (f"{message.project} has no product role enabled — there is nothing here to talk "
                f"to.")
    if not (message.id or "").strip() or len(message.id) > MAX_ID:
        return "a message needs an id of its own, of at most 128 characters."
    if not (message.conversation or "").strip() or len(message.conversation) > MAX_CONVERSATION:
        return "a message needs the conversation it belongs to."
    context = message.context or {}
    if set(context) - _CONTEXT_KEYS or any(len(str(v)) > MAX_ID for v in context.values()):
        # the row ADMITS a context against the person who sent it (`product/page.py::admit`) and
        # hands on only the page and the card; anything else here came round that rule
        return "a message's page context is the page and the card, as its door admitted them."
    if message.replies:
        return ""
    said = (message.text or "").strip()
    if not said:
        return "say something to the product role — an empty message is not a turn."
    if len(said) > MAX_TEXT:
        return (f"that message is {len(said)} characters; the most one message may carry is "
                f"{MAX_TEXT}. Split it, or put the document where the role can read it.")
    return ""


async def _engine():
    """This process's client for the durable engine — the read side's pooled one.

    The import is caught HERE, where it is made (#178): on an install without the `runtime` extra
    the door answers why the engine cannot be reached, through each caller's own refusal, instead
    of ending in a raw `ModuleNotFoundError`."""
    try:
        from openfactory.runtime.temporal import view as tv
    except ImportError as exc:
        from openfactory.runtime.host import why_the_engine_cannot_be_read

        raise RuntimeError(why_the_engine_cannot_be_read(exc)) from exc
    return await tv.connect()


async def receive(message: Message, *, project=None, client=None,
                  settings: Settings | None = None) -> Ack:
    """THE ONE ENTRY POINT. Validate, enqueue on the conversation, acknowledge — at once.

    `project` is the registry project the message names, when the caller already holds it; the
    registry is asked otherwise. `client` is the engine's client the caller holds (an activity's
    own, a row's); this process's is used otherwise. NEVER calls a model, and never raises for a
    message it refuses or an engine it cannot reach: the `Ack` says so, and the caller says it to
    the person."""
    from openfactory.product.engine import reads_only
    from openfactory.product.key import product_key

    if project is None:
        project = _registered(message.project)
    why = refusal(message, project)
    if why:
        return Ack(accepted=False, id=message.id, conversation=message.conversation, reason=why)
    settings = settings or Settings.from_environment()
    key = product_key(project)
    wid = workflow_id(key, message.conversation)
    cfg = getattr(project, "product", None)
    event = bool(message.replies)
    took_part = False
    if not event and _asks_whether_the_role_took_part(message):
        from openfactory.memory import transcript

        took_part = await asyncio.to_thread(transcript.took_part, project,
                                            conversation=message.conversation)
    arrival = _arrival(message, project, fast=not event and reads_only(message.text),
                       agent_name=getattr(cfg, "agent_name", "") or "", took_part=took_part)
    try:
        from openfactory.runtime.temporal import TASK_QUEUE
        from openfactory.runtime.temporal.io import ConversationInput

        client = client or await _engine()
        await client.start_workflow(
            WORKFLOW,
            ConversationInput(product=key, conversation=message.conversation,
                              debounce_seconds=settings.debounce_seconds,
                              bound_seconds=settings.bound_seconds),
            id=wid, task_queue=TASK_QUEUE, start_signal=SIGNAL, start_signal_args=[arrival])
    except Exception as exc:  # noqa: BLE001 — an engine that cannot be reached is a sentence
        from openfactory.util.causes import first_message

        log.exception("the door could not enqueue a message on %s", wid)
        return Ack(accepted=False, id=message.id, product=key, conversation=message.conversation,
                   workflow_id=wid,
                   reason=f"the durable engine is not answering ({first_message(exc, limit=140)})"
                          f" — nothing was enqueued, so this is safe to repeat.")
    stands = None if event else await _where(client, wid, message.id)
    return Ack(accepted=True, id=message.id, product=key, conversation=message.conversation,
               workflow_id=wid,
               state=str((stands or {}).get("state") or UNKNOWN),
               ahead=int((stands or {}).get("ahead") or 0),
               duplicate=bool((stands or {}).get("duplicate")),
               text="" if event else _acknowledgement(project, arrival, stands))


def is_direct(message: Message) -> bool:
    """Whether the conversation is the role and one person alone (ADR-0051 D14): a key a surface
    minted for one person (`product/conversation.py`), or a transport that said so."""
    from openfactory.product.conversation import is_private

    return bool(message.direct) or is_private(message.conversation)


def _asks_whether_the_role_took_part(message: Message) -> bool:
    """Whether reading the product's memory could change what the conversation decides: only for
    a reply that is neither in a direct conversation nor a mention — every other message is
    decided without it, so the door reads nothing for them."""
    return bool((message.in_reply_to or "").strip()) and not message.mentions_role \
        and not is_direct(message)


def _arrival(message: Message, project, *, fast: bool, agent_name: str,
             took_part: bool = False):
    from openfactory.runtime.temporal.io import Arrival

    return Arrival(id=message.id, project=message.project, conversation=message.conversation,
                   room=message.room, speaker=message.speaker, text=message.text,
                   in_reply_to=message.in_reply_to, source=message.source,
                   fingerprint=message.fingerprint, via=message.via,
                   language=getattr(project, "language", "") or "", agent_name=agent_name,
                   fast=fast, replies=[r.model_dump(mode="json") for r in message.replies],
                   context=dict(message.context or {}), direct=is_direct(message),
                   mentions_role=bool(message.mentions_role), took_part=bool(took_part))


async def _where(client, wid: str, message_id: str) -> dict | None:
    """Where one message stands, as its conversation says — or None when it did not say in time."""
    try:
        return await client.get_workflow_handle(wid).query(QUERY, message_id,
                                                           rpc_timeout=_ASK_WITHIN)
    except Exception as exc:  # noqa: BLE001 — the message is enqueued; only the telling is late
        log.info("the conversation %s did not say where %s stands (%s)", wid, message_id,
                 str(exc)[:160])
        return None


def _acknowledgement(project, arrival, stands: dict | None) -> str:
    """The sentence the door answers with — never a name but the role's own.

    A duplicate says nothing (it was acknowledged the first time); a read that is answered at once
    says nothing (the answer is the acknowledgement); a message joining one its speaker already
    has waiting says nothing (that one was acknowledged). A message with turns in front of it is
    told so, and that it is kept — never whose turn it is waiting behind. Anything else gets the
    receipt, now, before any of the slow part; and when the conversation did not say in time
    where the message stands, the one thing certain: it is kept. A message the conversation KEPT
    rather than turned — said to the room, not to the role (ADR-0051 D14) — is told so, and how
    to ask the role: a transport shows it to its sender, never to the room."""
    from openfactory.product import voice

    lang = getattr(project, "language", None)
    agent = arrival.agent_name
    if stands is None:
        return voice.heard(language=lang, agent_name=agent)
    if stands.get("duplicate"):
        return ""
    if stands.get("state") == OVERHEARD:
        return voice.overheard(language=lang, agent_name=agent)
    if arrival.fast or stands.get("coalesced"):
        return ""
    if stands.get("state") in _SETTLED:
        return ""
    ahead = int(stands.get("ahead") or 0)
    if ahead >= 1:
        return voice.you_are_next(ahead=ahead, language=lang, agent_name=agent)
    return voice.on_it(language=lang, agent_name=agent, seed=arrival.text)


# ── the way back, for a transport that shows the whole conversation (slice 5) ──────────────────

#: How long a transport waits to hear what changed before it asks again.
_WATCH_WITHIN = timedelta(seconds=2)


class NotStarted(Exception):
    """The conversation has no workflow yet: nobody has written in it since the engine began."""


async def watch(client, wid: str, cursor: int) -> dict:
    """What the conversation `wid` published and heard after `cursor`, and the role's presence in
    it now (`ConversationWorkflow.watch`) — for a transport that shows the whole conversation, the
    panel's socket (`api/product_chat.py`).

    RAISES `NotStarted` for a conversation nobody has written in yet, and what the engine raises
    for anything else: the caller tells "nothing here yet" from "the engine is not answering",
    because the page says the two differently."""
    try:
        return await client.get_workflow_handle(wid).query(WATCH, int(cursor),
                                                           rpc_timeout=_WATCH_WITHIN)
    except Exception as exc:  # noqa: BLE001 — sorted into the two answers the caller has
        from openfactory.util.causes import first_message

        said = f"{type(exc).__name__} {first_message(exc)}".lower()
        if "not found" in said or "notfound" in said:
            raise NotStarted(wid) from exc
        raise


# ── the way back, for a caller that waits in the same call ─────────────────────────────────────

async def wait(ack: Ack, *, client=None, bound: float | None = None) -> list[Reply] | None:
    """The replies published FOR THIS MESSAGE — once its turn has answered it or handed it off —
    or None when `bound` seconds passed first.

    READ FROM THE CONVERSATION'S OUTBOX, by the message's own id: a caller is handed what was said
    back to what it sent, and nothing else in the conversation. None is not a failure — the message
    is enqueued and its answer will be published; the caller says so and moves on."""
    if not ack.accepted:
        return None
    client = client or await _engine()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + (bound if bound is not None
                              else Settings.from_environment().wait_for(ack.ahead))
    pause = _FIRST_PAUSE
    while True:
        stands = await _where(client, ack.workflow_id, ack.id)
        if stands and stands.get("state") in _SETTLED:
            return [Reply.model_validate(r) for r in stands.get("replies") or []]
        left = deadline - loop.time()
        if left <= 0:
            return None
        await asyncio.sleep(min(pause, left))
        pause = min(pause * 1.5, _LONGEST_PAUSE)


async def converse(message: Message, *, project=None, client=None,
                   settings: Settings | None = None, acknowledged=None,
                   bound: float | None = None) -> tuple[Ack, list[Reply] | None]:
    """Through the door, then back: the acknowledgement, and the replies to this message.

    `acknowledged` is handed the `Ack` the moment the door has it — before the wait — which is how
    a chat transport says "on it" before the slow part and not beside the answer (#266 slice 2
    moved it there; this moves it back, for every transport at once)."""
    settings = settings or Settings.from_environment()
    try:
        client = client or await _engine()
    except Exception as exc:  # noqa: BLE001 — an unreachable engine is a sentence, not a crash
        from openfactory.util.causes import first_message

        return Ack(accepted=False, id=message.id, conversation=message.conversation,
                   reason=f"the durable engine is not answering "
                          f"({first_message(exc, limit=140)}) — nothing was sent, so this is "
                          f"safe to repeat."), None
    ack = await receive(message, project=project, client=client, settings=settings)
    if acknowledged is not None:
        try:
            acknowledged(ack)
        except Exception:  # noqa: BLE001 — an acknowledgement that failed must not cost the answer
            log.warning("could not hand on the acknowledgement", exc_info=True)
    if not ack.accepted:
        return ack, None
    return ack, await wait(ack, client=client,
                           bound=bound if bound is not None else settings.wait_for(ack.ahead))


# ── for callers that are not async ──────────────────────────────────────────────────────────────

def _run(coroutine):
    """Run a coroutine to its end from synchronous code — on a thread of its own when this thread
    already runs an event loop, which cannot be blocked on a second one."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    out: dict = {}

    def _go() -> None:
        try:
            out["value"] = asyncio.run(coroutine)
        except BaseException as exc:  # noqa: BLE001 — carried to the caller's thread
            out["error"] = exc

    runner = threading.Thread(target=_go, name="product-door", daemon=True)
    runner.start()
    runner.join()
    if "error" in out:
        raise out["error"]
    return out.get("value")


def say(project, message: Message, *, notify=None) -> list[Reply]:
    """The chat adapter's way through the door (`channel.handle`), for a listener that is not
    async: the acknowledgement handed to `notify` the moment the door has it, then the replies to
    this message, without receipts — the acknowledgement was the receipt.

    NEVER RAISES, AND NEVER SILENCE: an engine that cannot be reached, or a door that refused, is
    answered with the sentence for something that broke on our side, and the log says which."""
    from openfactory.product.voice import broke

    lang = getattr(project, "language", None)

    def _heard(ack: Ack) -> None:
        # A MESSAGE THE ROOM KEPT IS ACKNOWLEDGED TO NOBODY ON A CHAT: `notify` posts into the
        # room, and a line under every message people say to each other is the noise D14 exists
        # to keep out of it
        if notify is not None and ack.text and ack.state != OVERHEARD:
            notify(ack.text)

    try:
        ack, replies = _run(converse(message, project=project, acknowledged=_heard))
    except Exception:  # noqa: BLE001 — a listener must never be taken down by the door
        log.exception("the chat adapter could not reach the door")
        return [Reply(text=broke(language=lang), in_reply_to=message.id,
                      conversation=message.conversation, addressed_to=message.speaker)]
    if not ack.accepted:
        log.error("OPENFACTORY_PRODUCT_DOOR_REFUSED project=%s — %s", message.project, ack.reason)
        return [Reply(text=broke(language=lang), in_reply_to=message.id,
                      conversation=message.conversation, addressed_to=message.speaker)]
    return [r for r in (replies or []) if r.kind != "receipt"]


def tell(project, *, conversation: str, text: str, room: str = "", in_reply_to: str = "",
         addressed_to: str = "") -> bool:
    """An INTERNAL EVENT through the door: something the role says outside a turn — the outcome
    of an asynchronous task it started (ADR-0051 D6) — recorded in the product's memory FIRST and
    then published to the conversation it belongs to. Returns whether the door took it.

    RECORDED BEFORE IT IS DELIVERED (D13): a proactive message sent by a bare `say` was the one
    turn ADR-0024's audit found memory without, so the person who answered it was answered by a
    role that did not know what it had asked."""
    from openfactory.memory import transcript

    name = getattr(project, "name", "") or ""
    said = (text or "").strip()
    if not said or not conversation:
        return False
    try:
        transcript.record(project, thread=conversation, role="agent", text=said, channel=room)
    except Exception:  # noqa: BLE001 — the record must never cost the telling
        log.warning("[%s] could not record what the role told %s", name, conversation,
                    exc_info=True)
    reply = Reply(text=said, in_reply_to=in_reply_to, conversation=conversation,
                  addressed_to=addressed_to)
    event = Message(id=uuid.uuid4().hex, project=name, conversation=conversation, room=room,
                    text=said, in_reply_to=in_reply_to, via=EVENT, replies=(reply,))
    try:
        ack = _run(receive(event, project=project))
    except Exception:  # noqa: BLE001 — the work happened; only the telling failed, and says so
        log.exception("[%s] the door could not take what the role told %s", name, conversation)
        return False
    if not ack.accepted:
        log.error("[%s] the door refused what the role told %s: %s", name, conversation,
                  ack.reason)
    return ack.accepted
