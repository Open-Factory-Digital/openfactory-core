"""The product role's ONE turn engine: a message in, the replies it earns out (#266 slice 2).

THREE DOORS DRIFTED APART, AND THIS IS WHAT THEY BECAME (ADR-0051 D12). Until 2026-09-24 the
product conversation had four partial copies. `product/channel.py::handle` held the whole of it —
settle, fourteen typed intents, the intake, the gestures, the staged draft — and was called only
by the external Slack add-on. The panel reached `activities._product_draft` through `product_ask`,
which answered and drafted and never settled, so a typed "sim" there confirmed nothing.
`activities._product_conversation`, behind `product_say`, settled and answered and never drafted,
and nothing called it. And `catalog._say_as_an_intent` routed four read-only intents a third way.
Everything those held is here now, in one place, and every surface reaches it the same way:
through the one door (`product/door.py`, #266 slice 3) onto its conversation, whose turns the
worker takes one at a time (`runtime/temporal/conversation.py`) — the panel's row, the CLI and the
chat adapter that `channel.handle` still is alike.

A RELOCATION, NOT A REDESIGN (ADR-0038's word). The judgement is kept line for line, and every
incident comment travelled with the line it explains. `tests/test_the_conversation_is_pinned.py`
pinned it flow by flow against `channel.handle` before any of it moved, and drives THIS module now,
through the neutral `Message`. What changed is the structure the judgement runs in:

    settle  →  intents  →  converse (the answer)  →  gestures  →  staging

— five stages, each a function that takes the one message being answered (`Exchange`) and can be
called on its own. `turn` runs them in that order and nothing else.

ONE WAY OUT (ADR-0051 D13). The engine never calls a channel and takes no callbacks. A receipt —
"I am on it" — is a `Reply` of its own kind; a question with buttons is a `Reply` carrying a
`Confirmation`, which each transport renders its own way (ADR-0038 D2): buttons where it has them,
the sentence alone where it has not. What a person says is recorded in the transcript on arrival,
and what the role says is recorded before it is returned — a reply memory has, whatever becomes of
it on the way out (the lesson of ADR-0024's audit).

THE CONVERSATION HAS EXACTLY ONE CONFIRMATION, and where it sits is the design:

    someone describes a need    →  the role answers, and if it heard a REQUEST it drafts
    the draft is shown          →  in the client's words, with any conflict stated FIRST
    the person says yes         →  it is written up for the team

That single "yes" is the PROVENANCE — the record of who wanted this and when. It is asked for in
the conversation with the person who wanted it, rather than on an artefact they would never open.
Anything more is a form; anything less and a requirement enters the corpus that nobody agreed to.

READ IS OPEN, WRITE IS GATED (ADR-0016's model). Asking what the product already promises is not a
privileged operation. Recording a new promise is: only a listed approver's "yes" counts, and an
unauthorised one is answered rather than swallowed — a request that vanishes is indistinguishable
from a broken bot, so the person simply repeats it.

EVERY MESSAGE HAS A PERSON BEHIND IT, AND EACH PERSON THEIR OWN (#266 slice 4). The speaker is a
person of the product with a role in it — client, product admin or engineer (`product/speaker.py`)
— and the role's answer is told which. What a turn stages is staged for that person in that
conversation (`staging.key_for`), so a second person's request in a room no longer displaces the
first's draft; a yes confirms only the speaker's own proposal unless the product lets an admin
accept on the requester's behalf (`confirm.not_theirs`); and a decision the role asked of one
person is closed only by that person, where it was asked. `in_reply_to` is kept in the transcript:
the person's turn records what it replies to, and the role's turn the message it answers.

NOTHING OUTSIDE THIS MODULE CALLS `ProductModule.answer` OR `ProductRole.answer`, and
`tests/test_one_turn_engine.py` walks the package to say so: a second caller of the model's answer
is a second conversation starting over. The factory's own question about a card (`consult`) comes
through here too, for that reason.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from openfactory.contracts.refs import canonical_ref
from openfactory.product.confirm import (
    _breakdown_reply,
    _client_detail,
    _is_requester,
    _still_to_say,
    _unfinished,
    receipt,
)
from openfactory.product.confirm import confirm as confirm_staged
from openfactory.product.staging import (
    _expired_recently,
    _proposal_summary,
    consume,
    find_waiting,
    is_no,
    is_yes,
    key_for,
    pending_for,
    proposal_token,
    remember,
)

log = logging.getLogger("openfactory.product.engine")


# ── the contract: a message in, replies out ─────────────────────────────────────────────────────

class Confirmation(BaseModel):
    """The two answers a staged proposal can be given, as options a transport may render.

    `token` names what was SHOWN — the proposal's key and fingerprint (`staging.proposal_token`) —
    so a click answers that proposal and never its replacement. `typed` is the sentence that says
    a typed answer works too: a click only reaches the worker where the transport's buttons are
    wired, and a proposal that waits for a click that cannot arrive waits for ever
    (`channel.deliver` puts it beside the buttons)."""

    model_config = ConfigDict(frozen=True)

    token: str
    approve: str
    reject: str
    typed: str


class Reply(BaseModel):
    """One thing the role says back (ADR-0051 D13).

    `kind="receipt"` is the acknowledgement before the slow part — NOT recorded in the transcript
    (`confirm.receipt` says why) and carrying no information but that somebody is on it.
    `kind="handoff"` is the conversation's own word when a turn outlived its bound (ADR-0051 D6):
    presence, like a receipt and likewise unrecorded — the work goes on, and its answer comes back
    through the door when it is done (`product/door.py`). Every other reply is `answer`. `options`
    is present when the reply asks for a yes or a no on something staged; a transport without
    buttons shows `text`, which always asks in words."""

    model_config = ConfigDict(frozen=True)

    text: str
    kind: Literal["receipt", "answer", "handoff"] = "answer"
    options: Confirmation | None = None
    addressed_to: str = ""
    in_reply_to: str = ""
    conversation: str = ""


class Message(BaseModel):
    """One message to the product role, in no transport's shape (ADR-0051 D1).

    WHAT EVERY TRANSPORT HANDS OVER, and nothing a vendor decided. The fields are the ones the
    conversation already needed — `channel.handle` took all of them as loose keywords — named for
    what they are rather than for where the first transport kept them:

    - `conversation` is the key the conversation is remembered and staged under: a thread, a
      room, a person's private key (`product/conversation.py`). Which conversation a message
      belongs to is the TRANSPORT's to say (a chat thread, the panel's scope); the engine never
      parses an event to find out.
    - `room` is the conversation a thread lives inside, when it lives inside one: a bare "sim"
      typed there still finds a proposal staged in the thread, and the thread's history carries
      the room's rolling exchange. Empty where there is no such room (the panel).
    - `speaker` is who said it: a person, by the id the transport identified them with. Their
      ROLE in this product — client, product admin or engineer, client by default — is the
      registry's to say, never the message's: the engine resolves it (`product/speaker.py`,
      #266 slice 4) from the product's configuration. The chat adapter still hands the vendor's
      own id; mapping it to a person of the platform is slice 6's.
    - `source` is where the message can be found again (a permalink), carried onto what it stages.
    - `fingerprint` is what a CLICK already verified, carried to the compare-and-swap that
      performs the proposal: empty for a typed message, which has verified nothing yet.
    - `via` is the transport it came through — PROVENANCE for every gate and write record, never
      permission. `api` when a caller did not say, the core's own name for a caller of its
      interface; the chat adapter says its own.
    - `context` is what the speaker was looking at when they wrote (#266 slice 5): the panel's
      page and, on a card's page, the card — ADMITTED where the message came in
      (`product/page.py::admit`), never as the browser said it, and read into the role's current
      state by `converse`. Empty for a transport with no pages.

    `id` names this message, so a reply can say which one it answers (`Reply.in_reply_to`); the
    door deduplicates on it (`product/door.py`). `in_reply_to` is the message this one replies to,
    and both are kept in the transcript (#266 slice 4): the person's turn under its own id and what
    it replies to, the role's turn as the reply to this id. FROZEN: a message is what was said, and
    no stage may rewrite it — the verdict of the confirmation judge is carried beside the text,
    never written over it (see `settle`).

    `replies` is empty for everything a PERSON says. It is how an INTERNAL EVENT comes through the
    same door (ADR-0051 D1, D6): the outcome of an asynchronous task the role started — the first
    pass over a codebase, an answer that outlived its turn — carried as the replies to publish,
    already recorded by whoever produced them. An event starts no turn and reaches no stage."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    project: str
    conversation: str
    room: str = ""
    speaker: str = ""
    text: str
    in_reply_to: str = ""
    source: str = ""
    fingerprint: str = ""
    via: str = "api"
    replies: tuple[Reply, ...] = ()
    context: dict[str, str] = Field(default_factory=dict)


class Exchange:
    """ONE MESSAGE BEING ANSWERED — what every stage reads, and what the turn has said so far.

    Built fresh per message, like the module it holds: one conversation must not carry
    another's state. The stages take it rather than eleven loose keywords, which is what lets
    each of them be called on its own."""

    def __init__(self, project, message: Message, module=None) -> None:
        from openfactory.product.module import ProductModule

        #: THE PRODUCT'S WRITE SEQUENCE AS THIS TURN'S CHECK SAW IT (ADR-0051 D8), noted FIRST —
        #: before the module reads a corpus, a board or a ledger — so whatever the turn's search
        #: could not have seen arrived after it. What this turn stages carries it, and the
        #: confirmation re-checks only what came after. None when it could not be read: the
        #: staging then notes the sequence it finds, the confirmation's own check stands.
        self.seen = _sequence_now(project)
        self.project = project
        self.message = message
        self.text = message.text
        self.user = message.speaker
        self.thread = message.conversation
        self.channel = message.room
        self.source = message.source
        self.fingerprint = message.fingerprint
        self.via = message.via
        self.lang = getattr(project, "language", None)
        self._person = None
        #: WHERE WHAT THIS TURN STAGES WAITS: this person's own place in this conversation
        #: (`staging.key_for`), so their draft and another person's in the same room never
        #: displace one another
        self.key = key_for(message.conversation, message.speaker)
        self.module = module or ProductModule(project, via=message.via)
        #: the receipts said so far, in order; the answer is appended by `turn`
        self.replies: list[Reply] = []
        # ONE RECEIPT PER MESSAGE, and the factory is in the core so the click path gets the same
        # one: seeded by the message, so consecutive questions differ while the same message
        # always produces the same acknowledgement (deterministic tests, answerable support).
        # Said INTO THIS TURN'S REPLIES, never to a channel — the engine has none to call.
        self.on_it = receipt(project, self._receipt, seed=message.text)
        self._closed_decisions = False

    def _receipt(self, said: str) -> None:
        self.replies.append(Reply(text=said, kind="receipt"))

    @property
    def person(self):
        """WHO IS SPEAKING, as a person of this product with a role in it (#266 slice 4) — read
        from the registry, never from the message. Resolved when a stage first needs it: the
        answer does; a yes performed by `settle` asks the allowlist itself, at its own gate, and a
        turn that never reaches the answer never asks twice."""
        if self._person is None:
            from openfactory.product.speaker import person

            self._person = person(self.project, self.message.speaker, via=self.message.via)
        return self._person

    def close_decisions_if_she_reads_this(self) -> None:
        """A HUMAN SPOKE, SO THE DECISIONS SHE ASKED FOR WERE ANSWERED — once per message.

        BEFORE anything else she says, and before her new reply can open fresh ones: this very
        message is the person responding to what she asked last round. Closing after would either
        close the ones she just opened, or leave last round's open for ever.

        ONLY WHEN THE MESSAGE WILL ACTUALLY REACH HER. The first version closed every open
        decision on ANY inbound message, resting on "a partial answer is safe because she re-asks
        what is still undecided". That holds only if she READS the message — and the intent
        shortcuts (`status`, `triage`, a bare confirmation) answer from data already in hand and
        never reach the model. So a bare "status" silently closed three chased decisions as
        `answered` and nothing would ever ask again: precisely the silent loss the decision ledger
        exists to prevent.

        Deferred to the conversational stage, which is the only one she reads. A message that only
        says "status" leaves the decisions open — one more reminder, which is the cheap
        direction.

        ONLY THE ONES SHE ASKED OF THIS PERSON, HERE (#266 slice 4, ADR-0051 D11). This closed
        every open decision of the project, so one person's "bom dia" answered a decision asked of
        somebody else in another conversation, and nobody was ever chased about it again."""
        if self._closed_decisions:
            return
        self._closed_decisions = True
        try:
            self.module.close_decisions_answered(
                channel=self.channel,
                **_scoped(self.module.close_decisions_answered, self.thread, self.user))
        except Exception:  # noqa: BLE001 — bookkeeping must never cost the reply
            log.warning("[%s] could not close answered decisions",
                        getattr(self.project, "name", "?"), exc_info=True)


def turn(project, message: Message, *, module=None) -> list[Reply]:
    """One message to the product role. Returns every reply it earned, receipts first.

    `project` is the registry project the message is for, and `message.project` must name it: the
    door resolves one from the other (slice 3), and a mismatch here is a caller's bug, raised
    rather than answered in the wrong project's voice. `module` is the product module to answer
    with — built fresh for this message when none is handed in — and its per-turn view of the
    product is released when the turn ends, whoever built it.

    NEVER RAISES otherwise: a chat caller runs this inside its listener (Socket Mode, for one), and
    the worker inside an activity with one attempt, where an exception takes the answer down with
    it. An empty list means the role stays quiet."""
    from openfactory.memory import transcript

    name = getattr(project, "name", "?")
    if message.project != name:
        raise ValueError(f"a message for {message.project!r} was handed the project {name!r}")
    text, user, thread, channel = message.text, message.speaker, message.conversation, message.room
    reply: Reply | str | None = None
    ex: Exchange | None = None
    # ADR-0024 layer 0, the PERSON's turn: recorded on ARRIVAL, not after the reply. An answer here
    # can take minutes (a model call, a checkout), and a follow-up message that lands meanwhile
    # used to find no trace of this one — the handler answered the second message with amnesia
    # about the first. The GSI may or may not surface this row to a concurrent read; late is the
    # eventual-consistency cost either way, and absent-by-design was strictly worse.
    # Recorded in the PRODUCT's memory (ADR-0051 D2): handed the registry project, the transcript
    # keeps it under the product that project belongs to.
    # AND WHICH MESSAGE IT IS, AND WHAT IT REPLIES TO (#266 slice 4): the role's turn below is
    # recorded as the reply to this id, so the record says which answer answers which message.
    arrival_ts = ""
    try:
        arrival_ts = transcript.record(project, thread=thread, role="person", text=text,
                                       actor=user, channel=channel, message_id=message.id,
                                       in_reply_to=message.in_reply_to) or ""
    except Exception:  # noqa: BLE001 — the record must never cost the person their answer
        log.warning("[%s] could not record the incoming turn", name, exc_info=True)
    try:
        ex = Exchange(project, message, module)
        reply = _answer(ex, arrival_ts=arrival_ts)
    except Exception:  # noqa: BLE001 — a bad message must never kill the socket
        # SILENCE IS THE WORST ANSWER. Returning None here meant the person wrote to their PO and
        # got nothing — indistinguishable from being ignored, and invisible to us until they
        # complained. It also broke the platform's own standing invariant: every stall either
        # self-heals or asks a human; none of them is a quiet nothing.
        log.exception("[%s] product channel handler failed", name)
        # a distinct marker so ONE occurrence pages, rather than blending into the generic error
        # burst threshold — a client hearing nothing is not a transient
        log.error("OPENFACTORY_PRODUCT_MUTE project=%s thread=%s — the client got no "
                  "answer", name, thread)
        from openfactory.product.voice import broke

        reply = broke(language=getattr(project, "language", None))
    finally:
        # the AGENT's turn still lands after: what she said only exists once the stages return
        if reply:
            # recorded from the TEXT even when it carries options — her memory must hold the
            # proposal she made, whichever way it reaches the person
            transcript.record(project, thread=thread, role="agent", text=_text_of(reply),
                              channel=channel, in_reply_to=message.id)
        release(ex.module if ex is not None else module)
    said = list(ex.replies) if ex is not None else []
    if reply:
        said.append(reply if isinstance(reply, Reply) else Reply(text=str(reply)))
    return [r.model_copy(update={"addressed_to": user, "in_reply_to": message.id,
                                 "conversation": thread}) for r in said]


def _text_of(reply: Reply | str) -> str:
    return reply.text if isinstance(reply, Reply) else str(reply)


def _accepts(fn, name: str) -> bool:
    """Whether `fn` declares the keyword `name` — by name, or through `**kwargs`. Read from the
    signature, like `_accepts_intake` and for its reason: a double or an add-on's module written
    before the keyword existed is called exactly as before, and a `TypeError` raised INSIDE a real
    call is never mistaken for a missing keyword."""
    import inspect

    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return True
    return name in params or any(p.kind is inspect.Parameter.VAR_KEYWORD
                                 for p in params.values())


def _scoped(verb, conversation: str, person: str) -> dict:
    """The conversation and the person a decision verb is scoped to (#266 slice 4) — `{}` for a
    module whose verb predates the scope, which keeps the rule it always had."""
    return ({"conversation": conversation, "person": person}
            if _accepts(verb, "person") and _accepts(verb, "conversation") else {})


def _sequence_now(project) -> int | None:
    """The product's write sequence, or None when it could not be read — never a raise: a turn is
    never refused for its bookkeeping (`product/semaphore.py`)."""
    try:
        from openfactory.product import semaphore

        return semaphore.sequence(project)
    except Exception:  # noqa: BLE001 — the confirmation's own check still stands
        log.warning("[%s] could not read the product's write sequence",
                    getattr(project, "name", "?"), exc_info=True)
        return None


def release(module) -> None:
    """The module's per-turn view of the product, removed (ADR-0051 D11) — when it has one.

    A module a caller built without one, or a stand-in that knows nothing of views, is left as it
    is: the view is the module's own to remove, and only what it composed itself is ever
    deleted."""
    done = getattr(module, "release", None)
    if not callable(done):
        return
    try:
        done()
    except Exception:  # noqa: BLE001 — a view that could not be removed costs disk, never a reply
        log.warning("could not release the turn's view of the product", exc_info=True)


def _answer(ex: Exchange, *, arrival_ts: str = "") -> Reply | str | None:
    """The stages, in their order — and the order is the judgement."""
    # ---- what she asked last is answered first --------------------------------------------------
    # A staged proposal, an open delivery, an expired proposal. What is left below is what the
    # conversation does with a message that answered nothing — typed intents, then the
    # conversation with its staged drafts.
    settled = settle(ex.project, text=ex.text, user=ex.user, thread=ex.thread, module=ex.module,
                     channel=ex.channel, fingerprint=ex.fingerprint, on_it=ex.on_it, via=ex.via)
    if settled.reply is not None:
        return settled.reply
    waiting = settled.waiting

    # ---- an explicit ASK for one of the things this role does on its own -----------------------
    done = intents(ex)
    if done:
        return done

    # ---- everything else is a conversation ----------------------------------------------------
    answer = converse(ex, waiting, arrival_ts=arrival_ts)
    if isinstance(answer, str):
        return answer

    # A QUESTION ends here. A REQUEST becomes a draft, shown back for the one confirmation — this
    # is the only route from a conversation to something written down, and without it the whole
    # write path is unreachable from the conversation: every message would get a polite answer and
    # nothing would ever be recorded. A GESTURE the role read comes first, in its own order.
    offered = gestures(ex, answer) or staging(ex, answer)
    if offered:
        # returned WHOLE and untouched, so the confirmation it carries survives: interpolating a
        # proposal into a sentence here is exactly what once posted it twice
        return offered
    return answer.text


# ── stage 1: settle — the message read as an ANSWER to what the role asked last ─────────────────

@dataclass(frozen=True)
class Settled:
    """What one message settled BEFORE it is read as conversation.

    `reply` is the sentence to say when the message answered something the role had asked — a
    staged proposal (a yes, or a no), an open delivery ("did it work?"), or a proposal that
    expired while the person was away. `None` means the message settled nothing and the turn goes
    on to intents and conversation, carrying `waiting`: the proposal still staged, or None once a
    rejection destroyed it. ONE fact per value: `reply=None` never means "stay quiet" — a branch
    with nothing to say answers "" and the caller stays quiet on that, exactly as it always did.

    ONLY WHAT A CALLER READS. The key the proposal is staged under travelled here for one day and
    was read by nobody — every consume happens inside this stage — so it went; a field nothing
    reads is a promise the next reader keeps for it.
    """

    reply: str | None
    waiting: dict | None


def settle(project, *, text: str, user: str, thread: str, module, channel: str = "",
           fingerprint: str = "", on_it=None, via: str = "slack") -> Settled:
    """The message read as an ANSWER to what the role asked last — before it is read as anything.

    THE ONE STAGE EVERY SURFACE SHARES, and until 2026-08-25 it was reached from exactly one:
    these branches lived inside the Slack handler, so `ProductModule.settle_acceptance` — the
    client's "worked / did not work" that closes the acceptance loop (ADR-0025), with the client's
    release behind it — had ONE production caller, in `runtime/slack/`, while the panel's turn
    went straight to `module.answer`. On a deployment without Slack the sweep opened acceptance
    loops that no client could ever close. The turn engine is its one caller now, and every
    surface reaches it through the engine.

    THE GAP IT ONCE HAD ON THE PANEL IS CLOSED (#266 slice 2). For a year the typed yes and the
    expiry notice ran on the panel's path and found nothing, because nothing STAGED a proposal
    under the panel's key: the producers (`offer_draft`, the typed intents) lived in the chat
    handler alone, and the panel proposed through its own button. The panel's turn is this engine
    now, the producers with it, so a draft staged there is confirmed by a yes typed there — by the
    executor the click uses, not by a second copy of it.

    `via` IS PROVENANCE, NOT PERMISSION — the transport this message arrived through, handed to
    every gate this stage reaches (`confirm`, the rejection, `_maybe_release`) so the record of who
    authorised a write says where they were speaking from. Defaulted like `may_act` is; the
    engine hands down what the message says.

    RENDERED SENTENCES, ON PURPOSE. Every branch answers in the client's voice (`product/voice`),
    which is core and takes the project's language; nothing here knows how a transport shows a
    reply, and no confirmation options come out of it — offering one belongs to the stages after.

    The order is load-bearing and each line of it was paid for:
      the staged proposal first — a pending proposal is a question just asked, and it wins;
      the acceptance second — "sim, resolveu" would otherwise be swallowed by the conversational
      model: a polite reply, and a delivery still recorded as unconfirmed;
      the expiry last — with a delivery loop open, a bare "sim" answers "did it work?".
    """
    from openfactory.product.module import may_act, unauthorized_message

    lang = getattr(project, "language", None)
    # A person confirms wherever they happen to be typing: inside the thread Nina replied in, or
    # back at channel level. The proposal must be findable from both, and consumed from wherever
    # it was staged — an approval that misses the draft falls through to the conversational model,
    # which answers politely and writes NOTHING (the audit's worst simulated conversation).
    # THEIR OWN FIRST (#266 slice 4): in a room each person's proposal waits under a key of its
    # own, and somebody else's is found after it — to be refused out loud, or confirmed on the
    # requester's behalf where the product allows it (`confirm.not_theirs`).
    waiting_key, waiting = find_waiting(thread, channel, project=project, person=user)

    # A REPLY THE WORD LIST CANNOT READ IS NOT A "NO". `is_yes` is deliberately narrow (it accepts
    # "sim", "pode registrar", and nothing needing interpretation); everything else used to fall
    # straight through to conversation, so "Sim — registre." wrote nothing while the reply said it
    # had. When a proposal is pending and neither gate fires, a model reads the sentence — the only
    # thing that can tell an affirmation from a word that appears inside one (ADR-0028).
    # initialised BEFORE the gate: the branches below read them unconditionally, and they are only
    # assigned when the model is consulted at all
    judged_yes = judged_no = False
    if waiting and not is_yes(text) and not is_no(text):
        verdict = "neither"
        try:
            verdict = module.confirmed(text, proposal=_proposal_summary(waiting))
        except Exception:  # noqa: BLE001 — an unreadable judgment leaves the proposal pending
            log.warning("[%s] could not judge the confirmation", getattr(project, "name", "?"),
                        exc_info=True)
        # THE VERDICT IS CARRIED, NOT WRITTEN OVER THE MESSAGE. Replacing `text` with "sim"/"não"
        # was destructive in the reject direction: a rejection falls THROUGH to the conversation, so
        # she received the bare word "não" instead of what the person wrote. It happened on the
        # first real one — the product owner answered her open question, confirmed the #288 origin
        # and agreed which number is authoritative, all in one message; the judge correctly read it
        # as "revise before recording", and every word of it was then thrown away. She got "não"
        # with three things on the table and rightly refused to guess which one it meant.
        #
        # A conditional yes IS a rejection of what is staged — and it is also the most informative
        # message in the exchange. Both are true, and only one of them used to survive.
        judged_yes = verdict == "approve"
        judged_no = verdict == "reject"

    # THE CONFIRMATION IS ONE CALL NOW (#105). Ten branches lived here — eight typed kinds, a
    # generic yes on a draft, and the rejection below — and the eight opened with an IDENTICAL
    # preamble: `may_act`, then a compare-and-swap pop, then "somebody answered first". That
    # preamble and every body moved to `openfactory/product/confirm.py`, which the panel and the
    # `product_answer` row now call as well: one implementation, three transports (ADR-0039).
    #
    # The receipt goes with it. A confirmed write is always the slow path — every branch reaches a
    # checkout, the client's board or an agent — and `confirm` fires `on_it` before the
    # authorisation, so nobody approves something irreversible and then waits in silence.
    if waiting and (is_yes(text) or judged_yes):
        return Settled(confirm_staged(project, key=waiting_key, entry=waiting,
                                      fingerprint=fingerprint, module=module, user=user,
                                      lang=lang, on_it=on_it, via=via),
                       waiting)

    # THE REJECTION STAYS HERE, and it is not the executor's tenth branch. It performs nothing: it
    # destroys the proposal and FALLS THROUGH, so whatever the person wrote is answered as the
    # correction it usually is. `confirm` returns a sentence; this one has to keep going.
    if waiting and (is_no(text) or judged_no):
        # REFUSING IS AN ACT, so it is gated — but NOT by the approval rule, which would be wrong.
        # Two different people can say "não" here and they are not the same case: the person whose
        # request this is, saying "não, não é isso" to CORRECT their own wording, and a third party
        # who would simply be destroying a proposal an admin was about to approve. The first is the
        # point of the draft loop; the second is vandalism. So: an admin, or the requester.
        if not may_act(project, user, via=via) and not _is_requester(waiting, user):
            return Settled(unauthorized_message(project), waiting)
        # the same compare-and-swap the approvals use, and the return is deliberately unread: a
        # refusal that lost its race destroyed nothing, which is the outcome we wanted anyway. What
        # replaced it announced itself when it was staged (`remember` returns that notice).
        # A NO IS RECORDED AS A NO (#272). This passed `approved=True` — the approval's
        # compare-and-swap reused with the approval's flag — so the durable store said the person
        # who refused a draft had approved it, and their intake case sat in `confirmed` with
        # nothing ever filed: shown as in progress, and handed to the model as confirmed. The flag
        # is the record of who agreed to what; a refusal says `reject` and drops the case, which
        # is what the same "não" given by click always recorded (`confirm.answer_staged`).
        consume(waiting_key, waiting, fingerprint=fingerprint, project=project, by=user,
                approved=False)
        # the discarded proposal must not survive in this turn's PROMPT either: `waiting` fed the
        # "still pending" section of the conversation, so after a rejection she was told the thing
        # the person had just thrown away was still on the table — and said so
        waiting_key, waiting = None, None
        # fall through: whatever they said next is the correction, and it deserves an answer

    # ---- an answer to "did it work?" — the loop that makes this a product role ----------------
    # AFTER the staging block on purpose: a pending proposal is a question just asked, and it wins.
    # BEFORE intents and conversation, because "sim, resolveu" would otherwise be swallowed by the
    # conversational model — a polite reply, and a delivery still recorded as unconfirmed.
    if not waiting:
        answered = module.settle_acceptance(text)
        if answered:
            from openfactory.product.followup import accepted_text, rejected_text

            verdict, loop, ambiguous = answered
            cfg = getattr(project, "product", None)
            agent = getattr(cfg, "agent_name", "") or ""
            # THE ONE ANSWER THAT SPENDS SOMETHING (board #6). A release loop's "funcionou" does
            # not merely record an opinion: it puts software in front of the client's own users.
            # So it leaves this shared path immediately and is handled where its extra rules live.
            released = _maybe_release(project, module, loop, verdict, user, agent, lang,
                                      ambiguous=ambiguous, via=via)
            if released is not None:
                return Settled(released, waiting)
            say = accepted_text if verdict == "worked" else rejected_text
            # `ambiguous` NAMES what was settled when more than one delivery was waiting. The
            # comment here used to promise exactly that and the code never did it — a silent
            # choice quietly marked the wrong delivery accepted.
            return Settled(say(loop, agent_name=agent, ambiguous=ambiguous), waiting)

    # A LATE CONFIRMATION OF AN EXPIRED PROPOSAL HEARS SO. Without this, the "sim" of somebody who
    # stepped away past the TTL found nothing staged and fell through to the conversational model —
    # a polite answer to a confirmation of nothing, with the person left believing they confirmed.
    # After the acceptance check on purpose: with a delivery loop open, a bare "sim" answers "did
    # it work?", and the ledger read first.
    if not waiting and (is_yes(text) or is_no(text)) and _expired_recently(thread, channel):
        from openfactory.product.voice import proposal_expired

        return Settled(proposal_expired(language=lang), waiting)

    return Settled(None, waiting)


# ── stage 2: intents — an explicit ASK for one of the things this role does on its own ──────────

def intents(ex: Exchange) -> Reply | str | None:
    """The typed intent this message names, carried out — or None, and the turn goes on.

    Matched before the corpus is consulted: "who are you" and "how are we doing" must answer even
    when the requirements cannot be read, which is exactly when someone asks."""
    from openfactory.product.intents import match_intent

    matched = match_intent(ex.text)
    if not matched:
        return None
    intent, captures = matched
    return _run_intent(ex.project, intent, captures, module=ex.module, lang=ex.lang,
                       user=ex.user, on_it=ex.on_it, thread=ex.thread, channel=ex.channel,
                       asked=ex.message.id, key=ex.key)


# ── the read-only fast path — answered without a turn ───────────────────────────────────────────

#: THE INTENTS THAT ONLY SHOW SOMETHING, AND SPEND NO MODEL CALL TO DO IT (ADR-0051 D6, decision
#: 5). A conversation takes one turn at a time and nobody jumps its queue — except for these: a
#: person who asks where things stand while the role is busy answering someone else in the same
#: room is shown it at once, because the answer is a read of the corpus, the board and the ledger,
#: and holding it behind a model turn would buy nothing.
#:
#: `needs_action` IS NOT HERE, though it only reads: it spends one model call per parked card
#: (`ProductModule.review_needs_action`), which is a turn's cost and waits like one. Every other
#: intent writes or stages, and stages go through the turn so the conversation's one staged
#: proposal is never displaced from beside it.
FAST = frozenset({"announce", "status", "triage"})


def reads_only(text: str) -> bool:
    """Whether a message asks only for one of the `FAST` intents — decided by the word list, with
    no model, so the door can decide it (`product/door.py`)."""
    from openfactory.product.intents import match_intent

    matched = match_intent(text or "")
    return bool(matched) and matched[0] in FAST


def fast(project, message: Message, *, module=None) -> list[Reply]:
    """A message that only asks to be SHOWN something, answered without a turn (ADR-0051 D6).

    Only the intents stage runs: nothing is settled, nothing conversed, nothing staged — so no
    model is called and no proposal is touched, which is what lets this run beside a turn in the
    same conversation rather than behind it. The person's words and the answer are recorded in the
    product's memory like any turn's; the replies come back addressed like `turn`'s.

    Handed a message that is not read-only, it answers that something broke rather than taking a
    turn out of order: the door and the worker decide `reads_only` with the same word list, so the
    only way here is a door and a worker that disagree about it."""
    from openfactory.memory import transcript
    from openfactory.product.voice import broke

    name = getattr(project, "name", "?")
    if message.project != name:
        raise ValueError(f"a message for {message.project!r} was handed the project {name!r}")
    thread, channel = message.conversation, message.room
    reply: Reply | str | None = None
    ex: Exchange | None = None
    try:
        transcript.record(project, thread=thread, role="person", text=message.text,
                          actor=message.speaker, channel=channel, message_id=message.id,
                          in_reply_to=message.in_reply_to)
    except Exception:  # noqa: BLE001 — the record must never cost the person their answer
        log.warning("[%s] could not record the incoming turn", name, exc_info=True)
    try:
        if not reads_only(message.text):
            log.error("OPENFACTORY_PRODUCT_NOT_READ_ONLY project=%s thread=%s — a message the "
                      "fast path was handed asks for more than a read", name, thread)
            reply = broke(language=getattr(project, "language", None))
        else:
            ex = Exchange(project, message, module)
            reply = intents(ex)
    except Exception:  # noqa: BLE001 — a read that broke is said, never swallowed
        log.exception("[%s] the read-only answer failed", name)
        reply = broke(language=getattr(project, "language", None))
    finally:
        if reply:
            transcript.record(project, thread=thread, role="agent", text=_text_of(reply),
                              channel=channel, in_reply_to=message.id)
        release(ex.module if ex is not None else module)
    said = list(ex.replies) if ex is not None else []
    if reply:
        said.append(reply if isinstance(reply, Reply) else Reply(text=str(reply)))
    return [r.model_copy(update={"addressed_to": message.speaker, "in_reply_to": message.id,
                                 "conversation": thread}) for r in said]


# ── stage 3: converse — the answer ──────────────────────────────────────────────────────────────

def _accepts_intake(module) -> bool:
    """Whether this module's `answer` declares `intake` — by name, or through `**kwargs`. Read from
    the signature, not by trying and catching: a `TypeError` raised INSIDE a real `answer` would
    otherwise be mistaken for a module that does not take the keyword, and answered without it. A
    callable with no readable signature is treated as taking it, because the shipped module does."""
    import inspect

    try:
        params = inspect.signature(module.answer).parameters
    except (TypeError, ValueError):
        return True
    return "intake" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD
                                     for p in params.values())


def _looking_at(ex: Exchange, module) -> dict:
    """WHERE THE PERSON WROTE FROM, as the role's current state (#266 slice 5, ADR-0051 D1) — the
    keyword to hand `answer`, or none.

    "Why did this stop?" typed on card #42's page is a question about #42, and until the message
    carried its page the role was handed the words alone. The context was admitted where the
    message came in (`product/page.py::admit`); this reads it — the card through the project's
    own tracker — into the section of the prompt `answer` already has for it. Handed only when
    there is something to say and only to a module whose `answer` takes it, for the reason
    `_accepts_intake` gives: a double that predates the keyword must keep answering."""
    if not ex.message.context:
        return {}
    from openfactory.product.page import looking_at

    state = looking_at(ex.project, ex.message.context)
    if not state:
        return {}
    import inspect

    try:
        params = inspect.signature(module.answer).parameters
    except (TypeError, ValueError):
        return {"context": state}
    takes = "context" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD
                                       for p in params.values())
    return {"context": state} if takes else {}


def converse(ex: Exchange, waiting: dict | None, *, arrival_ts: str = ""):
    """The role's answer to the message — a `ProductAnswer`, or the sentence to say instead when
    the product cannot be read or the model could not answer.

    ADR-0024 layer 1. Without the conversation handed over, every message was turn 1: no "e o
    segundo?", no correction, no knowing she had asked something when the answer arrived."""
    from openfactory.product.voice import unavailable

    project, module, lang = ex.project, ex.module, ex.lang
    text, user, thread, channel = ex.text, ex.user, ex.thread, ex.channel
    ctx = module.context()
    if not ctx.available:
        log.warning("[%s] product module unavailable: %s", project.name, ctx.reason)
        return unavailable(language=lang)

    # THE RECEIPT GOES FIRST — before the transcript query, before the model. Everything below
    # this line is work the person is waiting through, and the whole point is that they should not
    # have to guess whether anything is happening.
    ex.on_it()

    from openfactory.memory import transcript

    agent_name = getattr(getattr(project, "product", None), "agent_name", "")
    # the CURRENT message is excluded by the ts it was recorded under: it is already the
    # "## Question" of this prompt, and history is strictly what came before it
    said = transcript.render(
        [t for t in transcript.recent(project, thread=thread, channel=channel)
         if not (arrival_ts and t.ts == arrival_ts)],
        agent_name=agent_name,
        # THE CLIENT'S LANGUAGE, said here rather than welded into the renderer (#168). This block
        # is read by a model that is answering a pt-BR client; the tech-lead's identical block is
        # read by one whose whole surface is English.
        heading="## Conversa até aqui (mais antigo primeiro)", you="você", somebody="pessoa")
    # AND WHAT WAS SAID ABOUT IT ELSEWHERE IN THE PROJECT (#33 hole 3) — the panel's turn carried
    # this block alone for a year; one engine carries it for every surface.
    said = _with_elsewhere(project, said, text, own=thread, agent_name=agent_name or "")
    ex.close_decisions_if_she_reads_this()

    # WHAT IS STILL WAITING — the fact whose absence let her announce five registered requirements
    # she had only proposed. `waiting` is the staged entry, read by the settling stage.
    # THIS PERSON'S INTAKE IN THIS CONVERSATION, TYPED (#33 hole 7) — beside the transcript, so
    # the fourth turn of "which screen?" is a continuation and not a re-reading.
    from openfactory.product import case as _case
    intake = _case.block_for(project, thread, user)
    # PASSED ONLY WHEN THERE IS ONE, AND ONLY TO A MODULE THAT TAKES IT. "Only when there is one"
    # alone deferred the break instead of preventing it: a module whose `answer` predates the
    # intake answered the FIRST turn, and on the second — `note_turn` having opened a case with
    # facts — received a keyword it did not declare, raised, and took the mute path, paging on
    # every turn for a day (review of #66, 2026-09-06). The shipped module declares it; a double
    # or an add-on that does not is answered as before, every turn.
    # WHO IS ASKING, AND IN WHICH ROLE (#266 slice 4), to a module that takes it — the shipped
    # one does; a double or an add-on written before it is answered as it always was
    answer = module.answer(text, conversation=said,
                           pending=_proposal_summary(waiting) if waiting else "",
                           **({"speaker": ex.person} if _accepts(module.answer, "speaker") else {}),
                           **_looking_at(ex, module),
                           **({"intake": intake} if intake and _accepts_intake(module) else {}))
    if not answer.ok:
        return unavailable(language=lang)
    try:
        _case.note_turn(project, thread, user, text, answer)
    except Exception:  # noqa: BLE001 — the case is bookkeeping; the reply is the act
        log.info("[%s] could not note the intake turn", project.name, exc_info=True)

    # WHAT SHE ASKED A HUMAN FOR BECOMES A TRACKED LOOP. The product owner's second real
    # conversation ended with three decisions requested and NOTHING recorded: loops were only ever
    # opened by the board sweep, so a request made in conversation lived in a chat message and died
    # when it scrolled away. Nobody would have been reminded, which is the silent-wait failure this
    # platform exists to make impossible.
    # ASKED OF THIS PERSON, IN THIS CONVERSATION (#266 slice 4): only they, there, close it
    if getattr(answer, "decisions", None):
        try:
            module.record_decisions(answer.decisions, channel=channel,
                                    **_scoped(module.record_decisions, thread, user))
        except Exception:  # noqa: BLE001
            log.warning("[%s] could not record the decisions she asked for — "
                        "OPENFACTORY_PRODUCT_DECISIONS_UNRECORDED: it asked a human for "
                        "something and nothing is tracking it", project.name, exc_info=True)

    # SHE CANNOT SEE WHETHER A WRITE HAPPENED, so a reply that says one did is a claim she has no
    # standing to make. This turn wrote nothing — the write paths are the staged-confirmation
    # branches of `settle`, which all return before reaching here. Detected rather than edited: a
    # wrong correction is worse than a flagged sentence, and what shipped was worse than both — a
    # confirmation went unrecognised, nothing was written, and the reply announced five registered
    # requirements to somebody who believed it.
    from openfactory.product.voice import claims_a_write

    # OBSERVED, NOT ACTED ON — and that is a retreat justified by evidence, not a shrug.
    #
    # The append shipped, and in production it fired TWICE, both times on sentences that were
    # correct. Once on a retraction ("eu disse 'Registrado o Requisito 1' … Não foi") and once on an
    # accurate history ("o texto foi gravado, o pedido de revisão não abriu"). Zero true positives
    # in the same window. A word list cannot tell "I recorded it just now" from "it was recorded
    # last time": that needs tense and temporal reference, which this is not able to read.
    #
    # And a WRONG correction is expensive in a way a missed one is not. It contradicts the agent in
    # front of the client, so the reader learns to distrust both voices — and it lands hardest on
    # exactly the honest, self-correcting messages the rule exists to produce.
    #
    # What actually removed the original harm was the prompt: she is now told, every turn, that this
    # reply writes nothing and what is still pending, and she says so herself unprompted. This stays
    # as an OBSERVATION so a real false claim is still visible to us — and if one appears in this
    # log without a matching write, the append comes back with a model reading the sentence rather
    # than a regex matching a word.
    claim = claims_a_write(getattr(answer, "text", "") or "")
    if claim:
        # WARNING, not ERROR — recalibrated on the record: four firings in production, four false
        # positives ("Anotado", "Anotei" — her acknowledging what she UNDERSTOOD, which no word
        # list can tell from a write claim), zero true ones. An ERROR that is always wrong teaches
        # whoever watches the log to ignore ERRORs, which is how the real one gets missed. The
        # marker stays greppable; if a true positive ever shows up here, the promised model-read
        # correction is what comes back — not the louder level.
        log.warning("OPENFACTORY_PRODUCT_FALSE_CLAIM project=%s claim=%r — the reply mentions a "
                    "completed "
                    "write and this turn wrote nothing (NOT corrected in the channel; see "
                    "ADR-0031)", project.name, claim)
    return answer


def _with_elsewhere(project, conversation: str, message: str, *, own: str,
                    agent_name: str = "") -> str:
    """The conversation in front of the role, plus what was said about the same thing ELSEWHERE in
    the project (#33 hole 3) — other conversations, other people, the channel — from the project's
    memory index. The current conversation is already there and is left out; a private
    conversation's turns reach only their own person (#46's key, kept). A memory that cannot be
    read costs the block and never the reply.

    MOVED FROM THE WORKER'S TWO TURNS (#266 slice 2), where it was the one piece of judgement the
    panel's paths had and the chat handler did not. One engine carries it for every surface.

    THE CONVERSATIONS ARE THE PRODUCT'S (ADR-0051 D2): what is read is every conversation of the
    product this project belongs to — its other registry projects' included — while the index
    itself, and the channel's messages it also reads, stay this registry project's."""
    try:
        from openfactory.memory import transcript
        from openfactory.memory.recall import recall, render_recall
        from openfactory.paths import project_memory_dir
        hits = recall(getattr(project, "name", "") or "", message,
                      index_dir=project_memory_dir(project), own=own, exclude_where=own,
                      partition=transcript.partition(project))
        # NOBODY IS NAMED ACROSS CONVERSATIONS (ADR-0051 D9): the block informs the answer, and the
        # model is never handed a name from another conversation that it could repeat here.
        elsewhere = render_recall(hits, agent_name=agent_name, name_people=False)
    except Exception:  # noqa: BLE001 — the project's memory is a bonus on top of the thread's
        log.warning("[%s] could not read the project memory", getattr(project, "name", "?"),
                    exc_info=True)
        return conversation
    if not elsewhere:
        return conversation
    return f"{conversation}\n\n{elsewhere}" if conversation else elsewhere


# ── stage 4: gestures — what the role read the message as asking FOR ────────────────────────────

def gestures(ex: Exchange, answer) -> Reply | str | None:
    """A gesture the role read in the message, staged for its one yes — or None.

    THE ORDER IS LOAD-BEARING rather than aesthetic: `remember` holds ONE staged entry per
    conversation (see its docstring), so two branches staging in the same turn displace each other
    in silence. A broken promise outranks a request to start — it is about work already owed — and
    asking to START the agreed work is not asking for something NEW, so it must not fall through
    into a draft proposal."""
    from openfactory.product.module import may_act

    project, module, lang = ex.project, ex.module, ex.lang
    # `thread` IS THE STAGING KEY in this stage (#266 slice 4): everything below stages for this
    # person in this conversation (`ex.key`), which is all this stage uses it for
    text, user, thread, channel, source = ex.text, ex.user, ex.key, ex.channel, ex.source
    if getattr(answer, "is_defect", False):
        # Who can actually unlock the pen. Asking the REPORTER to confirm and then refusing their
        # confirmation — with a refusal written for the requirement flow ("registrar como
        # requisito acordado") — was the single worst conversation the audit simulated: the person
        # confirms their own report and gets turned away in the wrong vocabulary, with no hint of
        # WHO to ask. The admins are known by id; name them.
        # SHE decided this breaks an existing promise (the corpus is hers to know); the person
        # confirms the restatement, an admin's yes files it. No requirement ceremony: the promise
        # already exists — what is being recorded is that reality disagrees with it.
        from openfactory.product.voice import defect_confirmation

        replaced = remember(thread, {"kind": "defect", "restated": text.strip()[:400],
                          "reported_by": f"<@{user}>" if user else "",
                          "violates": getattr(answer, "violates", None),
                          # the sequence this turn's check saw: the yes re-checks what came after
                          "seq": ex.seen,
                          # no severity: nobody judged one, and printing "média" as if somebody
                          # had is a fabricated classification the fix queue would sort by
                          "source": source or "", "channel": channel},
                            lang=lang, project=project, person=user)
        ask = defect_confirmation(violates=getattr(answer, "violates", None), language=lang)
        if not may_act(project, user):
            admins = _admin_mentions(project)
            if admins:
                ask += f"\n\n({admins}: o registro precisa da sua confirmação.)"
        # the defect proposal, offered with its options. The agent's own words stay in front of
        # it: the person confirms a RESTATEMENT, so they must read it.
        body = replaced + ((answer.text + "\n\n") if answer.text else "") + ask
        return offer(project, thread, body)

    # A GESTURE THE MODEL RECOGNISED that the word list did not (role.QUEUE_MARKER). The pattern
    # in `product_intents` still runs first and still short-circuits — this is the escape for the
    # phrasings it does not carry, and it costs nothing extra because this call already happened.
    #
    # AFTER `is_defect` AND BEFORE `is_request` — see this stage's docstring for why.
    if getattr(answer, "is_ticket", False):
        # SHE decided the person asked for a card, as described — not a broken promise and not a
        # wish to be argued into a requirement. The person confirms the title; an admin's yes opens
        # it. The same gate as a defect, for the same reason: it puts a card on the client's board.
        from openfactory.product.voice import ticket_confirmation

        title = ((getattr(answer, "ticket_title", "") or "").strip() or text.strip())[:80]
        replaced = remember(thread, {"kind": "ticket", "title": title,
                                     "described": text.strip()[:1500],
                                     "seq": ex.seen,
                                     "reported_by": f"<@{user}>" if user else "",
                                     "source": source or "", "channel": channel},
                            lang=lang, project=project, person=user)
        ask = ticket_confirmation(title=title, language=lang)
        if not may_act(project, user):
            admins = _admin_mentions(project)
            if admins:
                ask += f"\n\n({admins}: abrir o cartão precisa da sua confirmação.)"
        body = replaced + ((answer.text + "\n\n") if answer.text else "") + ask
        return offer(project, thread, body)
    if getattr(answer, "is_reorder", False) and getattr(answer, "order", None):
        # SHE READ AN ORDER FOR THE BACKLOG (#33 slice 9, the chat half of `reorder`). Staged like
        # the queue: the person reads the order back and confirms it, an admin's yes writes it.
        # Not the queue gesture — writing the order starts nothing — but it decides what the next
        # start spends on, so it waits for the same yes. THE ORDER TRAVELS UNTOUCHED: no sort, no
        # set, top first as they said it.
        from openfactory.product.voice import reorder_confirmation

        order = [str(n) for n in answer.order]
        replaced = remember(thread, {"kind": "reorder", "numbers": order, "channel": channel},
                            lang=lang, project=project, person=user)
        ask = reorder_confirmation(numbers=order, language=lang)
        if not may_act(project, user):
            admins = _admin_mentions(project)
            if admins:
                ask += f"\n\n({admins}: gravar a ordem precisa da sua confirmação.)"
        body = replaced + ((answer.text + "\n\n") if answer.text else "") + ask
        return offer(project, thread, body)
    if getattr(answer, "gesture", "") == "queue":
        # HER ANSWER TRAVELS WITH IT. Both sibling branches carry `answer.text` in front of what
        # they stage — a person confirms a proposal, so they must read what she said about it —
        # and this one dropped it: she answered the question and the reply was replaced by a bare
        # queue. The gesture was recognised BY reading the message; throwing away the reading is
        # the one thing that makes the marker path worse than the pattern it exists to rescue.
        proposed = _run_intent(project, "queue",
                               {"preamble": f"{answer.text}\n\n" if answer.text else ""},
                               module=module, lang=lang, user=user,
                               on_it=ex.on_it, thread=ex.thread, channel=channel, key=thread)
        if proposed:
            # WHOLE AND UNTOUCHED, like `offered` in the staging stage: `_queue_reply` can return a
            # proposal carrying its confirmation, and interpolating one into an f-string used to
            # turn it into a plain `str` — the boundary then could not tell it was already posted
            # and the proposal went out twice.
            return proposed
    return None


# ── stage 5: staging — a request becomes a draft, staged for one yes ────────────────────────────

def staging(ex: Exchange, answer) -> Reply | str | None:
    """The draft of what was asked for, staged and shown back — or None when the role heard no
    request, or heard one and could draft nothing testable (the conversation continues)."""
    if answer.is_request:
        user = ex.user
        offered = offer_draft(ex.project, request=ex.text, user=user, thread=ex.thread,
                              key=ex.key, module=ex.module, on_it=ex.on_it, channel=ex.channel,
                              seen=ex.seen,
                              preamble=f"{answer.text}\n\n" if answer.text else "",
                              asked_by=f"<@{user}>" if user else "", source=ex.source or "")
        if offered:
            # returned WHOLE and untouched, so the confirmation survives: interpolating it here is
            # exactly what posted the proposal twice
            return offered
    return None


def offer(project, key: str, text: str) -> Reply | str:
    """The proposal staged at `key`, offered as a question with options — or the text alone when
    nothing is staged there to be answered.

    ONE HELPER FOR EVERY STAGING SITE, because four copies of "try buttons, else prose" is how
    three of them end up without the button and nobody notices — the shape of this repository's
    signature defect. The engine never posts anything: it says what the options ARE, and each
    transport renders them its own way (ADR-0038 D2) — `channel.deliver` with buttons where the
    chat surface has them, the panel with its own, anything else as the sentence, which always
    asks in words."""
    entry = pending_for(key)
    if entry is None:
        return text
    from openfactory.product.voice import confirm_labels, or_just_reply

    lang = getattr(project, "language", None)
    approve, reject = confirm_labels(language=lang)
    return Reply(text=text, options=Confirmation(token=proposal_token(key, entry),
                                                 approve=approve, reject=reject,
                                                 typed=or_just_reply(language=lang)))


def offer_draft(project, *, request: str, user: str, thread: str, module,
                asked_by: str = "", date: str = "", source: str = "", on_it=None,
                preamble: str = "", channel: str = "",
                seen: int | None = None, key: str = "") -> Reply | str | None:
    """Draft what was asked for and show it back for confirmation.

    Separate from the conversation because drafting is a deliberate step: it costs a model call and
    it is what puts a proposal in front of a person, so the conversation decides when a message
    deserves one rather than every remark becoming a draft.

    `seen` is the product's write sequence as the turn's check saw it (ADR-0051 D8): the draft
    keeps it, so its confirmation re-checks only what was saved after the check it came from.

    `key` is where the draft is staged — the turn's `key_for(conversation, person)`, so it waits
    for `user` beside anybody else's in the same room (#266 slice 4). A caller that gives none
    stages under `thread` itself, the conversation alone, as every caller did before."""
    from openfactory.product.voice import confirmation_request

    thread = key or thread
    lang = getattr(project, "language", None)
    if on_it:
        on_it()
    answer = module.draft(request, asked_by=asked_by or user)
    if not answer.ok or answer.draft is None:
        return None  # nothing to confirm; the conversation continues

    draft = answer.draft
    replaced = remember(thread, {"answer": answer, "asked_by": asked_by or user, "date": date,
                                 "source": source, "kind": "draft", "channel": channel,
                                 "seq": seen,
                                 "number": _next_number(module)}, lang=lang, project=project,
                        person=user)
    # THE REASONING GOES ABOVE THE BUTTONS, IN THE SAME MESSAGE. Returned separately it was posted
    # separately — and after the block it justifies, so the person read "confirm this?" before the
    # argument for it. Worse, concatenating an already-posted proposal into an f-string produced a
    # plain `str`, the boundary could no longer tell it had been posted, and the whole proposal
    # went out TWICE. A sentinel that survives only until somebody interpolates it is not a
    # sentinel — which is why the preamble is an argument here and never glued on outside.
    return offer(project, thread, preamble + replaced + confirmation_request(
        title=draft.title, must_be_true=draft.must_be_true,
        conflicts=[_conflict_line(c) for c in draft.conflicts], language=lang))


def _conflict_line(conflict) -> str:
    ref = f"requisito {conflict.requirement}" if conflict.requirement else "algo já decidido"
    return f"{ref} — {conflict.explanation}"


# ── the factory's own question, which is not a turn ────────────────────────────────────────────

def consult(project, question: str, *, context: str = "", module=None):
    """A question the FACTORY puts to the role about a card — never a person's turn.

    The job's gather asks the role what an undescribed file does before work starts (ADR-0048).
    Nobody said it, so nothing is recorded in a conversation, nothing is settled and nothing is
    staged: this is the model's answer and only that. It lives here because `ProductModule.answer`
    has one caller — this module — and a guard holds it to that (ADR-0051 D12)."""
    from openfactory.product.module import ProductModule

    return (module or ProductModule(project, via="api")).answer(question, context=context)


# ── the typed intents, carried out ──────────────────────────────────────────────────────────────

def _waiting_line(project) -> str:
    """What she is still waiting on, appended to the status.

    A DELIVERY, NOT A CALCULATION (C-24). Opening the memory store, filtering loop kinds and
    writing the Portuguese used to happen right here — the product role's own logic inside one
    provider's adapter. It now lives in `product/followup.waiting_line`, where the panel and any
    other channel can ask the same question and get the same sentence."""
    from openfactory.product.followup import waiting_line

    line = waiting_line(getattr(project, "name", "") or "",
                        language=getattr(project, "language", None))
    return f"\n{line}" if line else ""


#: words that carry no identity — a term must not begin or end with one. Portuguese runs on
#: articles and prepositions, which is why "first six words" produced handles like "a firma usa
#: Primavera para a": truncated mid-article, unfindable in a glossary, and colliding with every
#: other sentence that starts the same way.
_STOPWORDS = frozenset(
    "a o as os um uma uns umas de do da dos das em no na nos nas para pra por com sem que e ou "
    "se ao aos à às é são foi ser estar tem têm há aí ai lá la isso isto aquilo the of in on at "
    "to for and or is are was be".split())


def _term_of(fact: str) -> str:
    """A findable handle for one fact: strip leading/trailing stopwords, keep up to five words.

    Deterministic on purpose (no model call for a dictation), and honest about its limits: the
    person is shown the term and can re-dictate. What it must never do is what "first six words"
    did — cut mid-article and index a glossary by sentence fragments."""
    words = fact.split()
    while words and words[0].lower().strip(",.;:") in _STOPWORDS:
        words.pop(0)
    picked = words[:5]
    while picked and picked[-1].lower().strip(",.;:") in _STOPWORDS:
        picked.pop()
    return " ".join(picked) if picked else " ".join(fact.split()[:4])


def _admin_mentions(project) -> str:
    """The people whose yes unlocks the pen, as real mentions. Known by id from the deployment
    config — this is the one place a raw `<@id>` is correct, because the id IS the config.

    ONLY WHERE THEIR YES CAN COUNT (#266 slice 4). The note these mentions go into sits under a
    proposal staged by somebody off the admin list, telling the admins it needs their
    confirmation. Since the first yes is bound to the requester, an admin's yes on it counts only
    when the product lets admins accept on the requester's behalf (`accept_on_behalf`); anywhere
    else the note would send them to a refusal, so there is nobody to name."""
    cfg = getattr(project, "product", None)
    if not getattr(cfg, "accept_on_behalf", False):
        return ""
    admins = list(cfg.admins or [])[:3]
    return " ".join(f"<@{a}>" for a in admins)


def _next_number(module) -> int:
    from openfactory.product.authoring import next_number

    try:
        return next_number(module.context().corpus)
    except Exception as exc:  # noqa: BLE001 — a number is cosmetic in a chat message
        log.info("could not work out the next requirement number (%s) — showing none", exc)
        return 0


def _run_intent(project, intent: str, captures: dict, *, module, lang: str | None,
                user: str = "", thread: str = "", on_it=None,
                channel: str = "", asked: str = "", key: str = "") -> Reply | str | None:
    """Do the thing that was asked for. `None` falls back to conversation — a recognised intent
    that cannot be carried out must not swallow the message.

    `key` is where what an intent stages waits — the turn's `key_for(conversation, person)`
    (#266 slice 4) — and `thread` the conversation it was asked in. A caller that gives no key
    stages under the conversation itself, as every caller did before."""
    # IMPORTED ONCE, AT THE TOP — both of them, because a gate and its refusal are never used
    # apart. It used to be imported inside the `fact` branch, which makes it a function-local name
    # for the WHOLE function — so the next branch added above that line raised UnboundLocalError on
    # its authorisation check and the client got "algo quebrou do meu lado". A landmine that arms
    # itself for whoever writes the next intent is worth removing, not documenting.
    from openfactory.product.module import may_act, unauthorized_message
    from openfactory.product.voice import triage_report

    name = getattr(getattr(project, "product", None), "agent_name", "") or ""
    # FROM HERE ON `thread` IS THE STAGING KEY — every proposal below is staged for this person in
    # this conversation — and `conversation` is where the message was said (the first pass reports
    # back to it)
    conversation, thread = thread, (key or thread)

    if intent == "announce":
        return module.introduce()

    if intent == "fact":
        fact = (captures.get("fact") or "").strip().rstrip(".")
        # "lembra que semana passada o sistema caiu?" is a rhetorical QUESTION, not a dictation —
        # staging it produced "Vou anotar assim — *semana passada o sistema caiu?*", which reads
        # as a bot that cannot tell being asked from being told. A question mark ends the intent.
        if not fact or fact.endswith("?"):
            return None
        term = _term_of(fact)
        from openfactory.product.voice import fact_confirmation

        replaced = remember(thread, {"kind": "fact", "term": term, "body": fact,
                                     "said_by": f"<@{user}>" if user else "", "source": "",
                                     "channel": channel},
                            lang=lang, project=project, person=user)
        ask = fact_confirmation(term=term, body=fact, language=lang)
        if not may_act(project, user):
            admins = _admin_mentions(project)
            if admins:
                ask += f"\n\n({admins}: a anotação precisa da sua confirmação.)"
        return offer(project, thread, replaced + ask)

    if intent == "status":
        # COMPOSED HERE, NEVER `status_line()`. That one is `ProductContext.health()` — an operator
        # line carrying the repository slug, English prose, a warning count and a manifest path,
        # and it was the answer this channel gave to "como estamos?", the most-asked question on
        # the surface, every day. The diagnostics still exist and still reach the panel and the log;
        # what changes is who they are written for (ADR-0026).
        from openfactory.product.voice import corpus_state

        ctx = module.context()
        corpus = getattr(ctx, "corpus", None)
        if not ctx.available:
            log.warning("[%s] status asked while the product base is unreadable: %s",
                        getattr(project, "name", "?"), str(getattr(ctx, "reason", ""))[:200])
        return corpus_state(
            available=bool(ctx.available),
            requirements=len(getattr(corpus, "requirements", []) or []) if corpus else 0,
            promises=len(corpus.promises()) if corpus else 0,
            language=lang) + _waiting_line(project)

    if intent == "triage":
        if on_it:
            on_it()
        report, error = module.triage_board()
        if report is None:
            # `error` is loader/board prose written for an operator — English, with the repo slug
            # in it. There is no client-readable version of it: the log keeps the diagnosis whole,
            # the channel hears that the problem is ours.
            log.warning("[%s] triage could not read the board: %s",
                        getattr(project, "name", "?"), str(error)[:400])
            return ("Não consegui ler o quadro de trabalho agora — o problema é do meu lado, e o "
                    "time já tem o detalhe. Tente de novo daqui a pouco.")
        return triage_report(report, language=lang, agent_name=name)

    if intent == "needs_action":
        # the REAL classification, not a proxy: it reads the diagnosis already on each ticket and
        # decides whose problem it is
        if on_it:
            on_it()
        review, error = module.review_needs_action()
        if review is None:
            log.warning("[%s] needs-action could not read the board: %s",
                        getattr(project, "name", "?"), str(error)[:400])
            return ("Não consegui olhar o que está parado agora — o problema é do meu lado, e o "
                    "time já tem o detalhe. Tente de novo daqui a pouco.")
        return _needs_action_reply(review, name, language=lang)

    if intent == "breakdown":
        number = int(captures.get("number") or 0)
        # ONE OF THE TWO GESTURES THAT WRITE ON THE MATCH ALONE — a declared exception, argued in
        # full at the top of product_intents.py: filing spends nothing, the way out of Backlog is
        # separately staged and gated, and the four pattern guards are what pays for the missing
        # confirmation. The gate is NOT part of the exception. Checked here rather than only in
        # `file_issues`: a non-approver was buying a receipt and a round-trip before hearing no,
        # and an authorisation that lives one layer down is one nobody writing the next branch sees.
        if not may_act(project, user):
            return unauthorized_message(project)
        if on_it:
            on_it()
        # `asked_for=True` — A PERSON TYPED THIS, which is the one thing that tells it apart from
        # an acceptance's automatic second act. It is what keeps the breakdown available for a
        # requirement that was read off the code and then edited into more than the code does:
        # the file cannot show that, and a person saying so can (#182).
        results = module.break_down(number, actor=user, asked_for=True)
        return _breakdown_reply(results, number, name, lang, project)

    if intent == "accept":
        number = int(captures.get("number") or 0)
        req, _corpus, instead = _named_requirement(project, module, number, name, lang)
        if instead:
            return instead
        if req.is_promise:
            return f"{name}: o requisito {number} já estava acordado." if name else \
                   f"o requisito {number} já estava acordado."
        if not req.is_live:
            # THE MODULE'S OWN QUESTION, ASKED HERE TOO — `drop` reads this same flag one branch
            # below. This one compared a raw status to "accepted", so a retired requirement bought
            # a confirmation from a person; and `module.accept` refuses only what is ALREADY
            # agreed, so that yes would have written a text the client had taken off the table
            # back into force as a promise the factory defends.
            retired = (f"o requisito {number} já não vale, então acordá-lo agora seria trazer de "
                       f"volta um texto que vocês já tinham tirado da mesa. Se isso voltou a fazer "
                       f"sentido, me digam e eu proponho de novo para vocês confirmarem.")
            return f"{name}: {retired}" if name else retired
        from openfactory.product.voice import accept_confirmation

        body = remember(thread, {"kind": "accept", "number": number, "channel": channel,
                                 "asked_by": f"<@{user}>" if user else ""},
                        lang=lang, project=project, person=user)
        return offer(project, thread, body + accept_confirmation(
            number=number, title=req.title or req.slug, language=lang))

    if intent == "drop":
        number = int(captures.get("number") or 0)
        req, _corpus, instead = _named_requirement(project, module, number, name, lang)
        if instead:
            return instead
        if not req.is_live:
            # already off the table — saying "confirm and I'll drop it" would stage a write that
            # changes nothing, and the person would believe they had decided something
            return (f"{name}: o requisito {number} já não estava valendo." if name
                    else f"o requisito {number} já não estava valendo.")
        from openfactory.product.voice import drop_confirmation

        was_a_promise = req.is_promise
        body = remember(thread, {"kind": "drop", "number": number, "channel": channel,
                                 "reason": (captures.get("reason") or "").strip()[:300],
                                 "was_a_promise": was_a_promise,
                                 "asked_by": f"<@{user}>" if user else ""},
                        lang=lang, project=project, person=user)
        ask = drop_confirmation(number=number, title=req.title or req.slug,
                                was_a_promise=was_a_promise, language=lang)
        if not may_act(project, user):
            admins = _admin_mentions(project)
            if admins:
                ask += f"\n\n({admins}: a decisão precisa da sua confirmação.)"
        return offer(project, thread, body + ask)

    if intent == "decision":
        number = int(captures.get("number") or 0)
        decision = (captures.get("decision") or "").strip().rstrip(".")[:400]
        req, _corpus, instead = _named_requirement(project, module, number, name, lang)
        if instead:
            return instead
        if not req.is_live:
            # writing into a document nobody is executing records the decision where nobody will
            # go looking for it — and the person would believe it had landed somewhere useful
            gone = (f"o requisito {number} já não vale, então uma decisão registrada nele ficaria "
                    f"guardada onde ninguém vai procurar. Em qual requisito isso deve entrar?")
            return f"{name}: {gone}" if name else gone
        from openfactory.product.voice import decision_confirmation

        body = remember(thread, {"kind": "decision", "number": number, "channel": channel,
                                 "decision": decision,
                                 "asked_by": f"<@{user}>" if user else ""},
                        lang=lang, project=project, person=user)
        # THE SENTENCE IS SHOWN BACK VERBATIM, and that is the point of staging this at all: the
        # whole value of the register is that somebody reads these exact words in three months, so
        # a paraphrase approved today is a paraphrase found then.
        ask = decision_confirmation(number=number, decision=decision, language=lang)
        if not may_act(project, user):
            admins = _admin_mentions(project)
            if admins:
                ask += f"\n\n({admins}: a decisão precisa da sua confirmação.)"
        return offer(project, thread, body + ask)

    if intent == "close":
        # A CARD, NOT A REQUIREMENT (C-05) — the tracker's own ref, whatever shape it takes.
        # `int(... or 0)` sat on both of these and would have raised on a Jira ref, inside the
        # chat handler, where the client sees "algo quebrou do meu lado".
        number = canonical_ref(captures.get("number"))
        in_favour_of = canonical_ref(captures.get("in_favour_of")) or None
        reason = (captures.get("reason") or "").strip()[:300]
        if not number:
            return None
        unclear = int(captures.get("in_favour_of_unclear") or 0) or None
        if unclear and not in_favour_of:
            # A SURVIVOR NAMED WITHOUT A `#` IS AMBIGUITY, AND AMBIGUITY COSTS A QUESTION. Closing
            # anyway would perform the other of the two acts these texts exist to keep apart: the
            # card would go with no pointer, under the wording for work being given up, in answer
            # to a sentence that said the work moved. Nothing is staged — a question that displaced
            # a pending proposal would be charging for the doubt twice.
            from openfactory.product.voice import survivor_unclear

            asked = survivor_unclear(number=number, other=unclear, language=lang)
            return f"{name}: {asked}" if name else asked
        # NOTHING IS READ FIRST, deliberately, and it is the one place this branch differs from
        # `drop`. `drop` can check the requirement in the corpus it already holds in memory; the
        # equivalent check here is a read of the client's board — seconds, over the network, on the
        # listener thread, before the person has even confirmed. The contract puts "already closed"
        # and "no such card" behind `close_card`, which reports both as a sentence a client can
        # read, so the cost is paid once and only when somebody actually decided.
        from openfactory.product.voice import close_confirmation

        body = remember(thread, {"kind": "close", "number": number,
                                 "in_favour_of": in_favour_of, "reason": reason,
                                 "channel": channel,
                                 "asked_by": f"<@{user}>" if user else ""},
                        lang=lang, project=project, person=user)
        ask = close_confirmation(number=number, in_favour_of=in_favour_of, reason=reason,
                                 language=lang)
        if not may_act(project, user):
            admins = _admin_mentions(project)
            if admins:
                ask += f"\n\n({admins}: o encerramento precisa da sua confirmação.)"
        return offer(project, thread, body + ask)

    if intent == "correct":
        # A CARD (C-05), and what it should say instead (#156). Nothing is read first, for the
        # reason `close` gives: the board read belongs behind the confirmation, and `correct_card`
        # answers "not mine", "already started" and "no such card" as sentences a client can read.
        number = canonical_ref(captures.get("number"))
        text = (captures.get("text") or "").strip()[:2000]
        new_title = (captures.get("title") or "").strip()[:200]
        if not number or not (text or new_title):
            return None
        from openfactory.product.voice import correct_confirmation

        body = remember(thread, {"kind": "correct", "number": number, "text": text,
                                 "new_title": new_title, "channel": channel,
                                 "asked_by": f"<@{user}>" if user else ""},
                        lang=lang, project=project, person=user)
        ask = correct_confirmation(number=number, text=text, title=new_title, language=lang)
        if not may_act(project, user):
            admins = _admin_mentions(project)
            if admins:
                ask += f"\n\n({admins}: a correção precisa da sua confirmação.)"
        return offer(project, thread, body + ask)

    if intent == "align":
        # THE TWO AXES IN ONE GESTURE, and the reason bare `number` is not a safe name to guard
        # on: `number` is the CARD (the tracker's ref, any shape) and `requirement` is a REQ
        # number this platform mints itself, which is genuinely an integer.
        number = canonical_ref(captures.get("number"))
        requirement = int(captures.get("requirement") or 0)
        if not number or not requirement:
            return None
        req, corpus, instead = _named_requirement(project, module, requirement, name, lang)
        if instead:
            return instead
        if not req.is_promise:
            refusal = _align_refusal(project, corpus, req, number=number,
                                     requirement=requirement, lang=lang)
            return f"{name}: {refusal}" if name else refusal
        from openfactory.product.voice import align_confirmation

        body = remember(thread, {"kind": "align", "number": number, "requirement": requirement,
                                 "channel": channel,
                                 "asked_by": f"<@{user}>" if user else ""},
                        lang=lang, project=project, person=user)
        ask = align_confirmation(number=number, requirement=requirement,
                                 title=req.title or req.slug, language=lang)
        if not may_act(project, user):
            admins = _admin_mentions(project)
            if admins:
                ask += f"\n\n({admins}: a mudança precisa da sua confirmação.)"
        return offer(project, thread, body + ask)

    if intent == "refine":
        # A CARD (C-05) — see `close` above.
        number = canonical_ref(captures.get("number"))
        if not number:
            return None
        # the sibling of `breakdown`, under the same declared exception and the same reasoning:
        # this writes criteria only where there are NONE — `align` is the act that replaces
        # criteria somebody may already be working from, and that one is staged.
        if not may_act(project, user):
            return unauthorized_message(project)
        if on_it:
            on_it()
        return _refine_reply(module.refine(number, actor=user), number, name, lang, project)

    if intent == "baseline":
        return _baseline_reply(project, module, name, user, on_it, conversation=conversation,
                               room=channel, asked=asked)

    if intent == "queue":
        return _queue_reply(project, module, name, thread, channel=channel,
                            preamble=captures.get("preamble", ""), user=user)

    return None


def _no_such_requirement(number: int, name: str, lang) -> str:
    """Three gestures name a requirement by number and all three can miss. One sentence, said the
    same way each time — the third hand-written copy is where the wording drifts."""
    from openfactory.product.voice import requirement_not_found

    missing = requirement_not_found(number=number, language=lang)
    return f"{name}: {missing}" if name else missing


def _named_requirement(project, module, number: int, name: str, lang):
    """What a gesture that names a requirement by number is really asking for:
    `(requirement, corpus, "")`, or `(None, None, what to say instead)`.

    "I COULD NOT READ THE BASE" IS NOT "THAT REQUIREMENT DOES NOT EXIST", and the second was said
    for the first. Loading never raises: an unavailable `ProductContext` carries an EMPTY corpus,
    so `by_number` answers None for every number while the documentation base is unreachable. And
    the conversation's `ctx.available` gate is reached only when the dispatcher falls through,
    while each of these three branches returns a sentence — so on a docs outage the product owner
    told an accounting client, flatly, that a requirement they had written themselves does not
    exist. It is the same state that once answered "how many requirements are there" with "zero".

    Read once for the three. `requirement_not_found` was written to stop the wording drifting
    between them, and unified the wrong sentence across all three instead.
    """
    ctx = module.context()
    if not ctx.available:
        log.warning("[%s] a requirement gesture arrived while the base could not be read: %s",
                    getattr(project, "name", "?"), ctx.reason)
        from openfactory.product.voice import unavailable

        return None, None, unavailable(language=lang)
    req = ctx.corpus.by_number(number) if number else None
    if req is None:
        return None, None, _no_such_requirement(number, name, lang)
    return req, ctx.corpus, ""


def _replacement(corpus, number: int):
    """The last requirement a supersession chain NAMES, whatever its status — None when it names
    nothing that can be read.

    NOT A SECOND ANSWER TO `_successor`'S QUESTION, A DIFFERENT ONE. `_successor` says which
    PROMISE took over, and it is the reading the repair path stands on; it answers None both when
    the chain dangles and when the text that took over is merely proposed. Those two are not the
    same fact and the person cannot act on them the same way: one is a text they can read and
    agree to, the other is an inconsistency of ours. Telling them apart is what this reads, and
    nothing else — where both answer they must agree, and a test holds them to it.
    """
    seen: set[int] = set()
    current = corpus.by_number(number)
    while current is not None and current.superseded_by is not None:
        if current.number in seen:
            return None
        seen.add(current.number)
        current = corpus.by_number(current.superseded_by)
    return current if current is not None and current.number != number else None


def _align_refusal(project, corpus, req, *, number: str, requirement: int, lang) -> str:
    """Why this card will not be written from this requirement — said HERE, before anybody is asked.

    THE PRE-CHECK IS THE MODULE'S OWN GATE. `align_card` writes only from a PROMISE; this branch
    admitted anything still `is_live`, so a proposed requirement bought a "this changes what gets
    built — Confirma?" from a person, displaced whatever else was awaiting confirmation in the
    thread, and was refused one call deeper by a gate that had never moved. Asking somebody to
    authorise an act that cannot happen spends the only thing this surface asks of a human.

    THE DAMAGE THIS ACT EXISTS TO UNDO, ARRIVING FROM THE OTHER DIRECTION. Writing a card's
    criteria out of a retired text is what left thirteen cards executing REQ-0004 under a rule
    telling whoever works them not to go beyond it. Refused, and the refusal names the sentence
    that would work — a dead end is how somebody stops asking.

    THE END OF THE CHAIN, NOT THE NEXT LINK, and "unagreed" is not "unreadable". `superseded_by`
    is a claim about one hop; a replacement written in the same commit that retires its
    predecessor is `proposed` for as long as nobody has said yes. Reading that as a broken chain
    told a client our base pointed at a text nobody could open — about a requirement that reads
    perfectly well — and raised an operator alarm with nothing behind it. What it needs is the
    fourth answer: the replacement exists, and confirming it is the step that unlocks this one.

    AND "UNAGREED" IS NOT "REFUSED". `_replacement` answers which requirement the chain NAMES,
    whatever became of it; what this has to know is whether the person can still say yes to it. A
    replacement the client themselves dropped is neither missing nor pending, and offered as
    pending it invited them to reinstate the text they had cancelled — which `accept` would have
    written back into force. The status is read here, once, rather than assumed by the sentence.
    """
    from openfactory.product.module import _not_a_promise, _successor
    from openfactory.product.voice import (
        align_refused,
        align_to_dropped_replacement,
        align_to_unagreed,
    )

    if req.superseded_by is not None:
        promise = _successor(corpus, requirement)
        if promise:
            return align_refused(number=number, requirement=requirement, successor=promise,
                                 language=lang)
        replacement = _replacement(corpus, requirement)
        if replacement is not None:
            if not replacement.is_live:
                return align_to_dropped_replacement(number=number, requirement=requirement,
                                                    successor=replacement.number, language=lang)
            return align_to_unagreed(number=number, requirement=requirement,
                                     successor=replacement.number, language=lang)
        log.warning("OPENFACTORY_PRODUCT_CHAIN_BROKEN project=%s requirement=%s superseded_by=%s — "
                    "a "
                    "retired requirement points at a text the corpus cannot read, so nothing can "
                    "be re-aimed at it", getattr(project, "name", "?"), requirement,
                    req.superseded_by)
        return align_refused(number=number, requirement=requirement, replaced=True, language=lang)
    if not req.is_live:
        return align_refused(number=number, requirement=requirement, language=lang)
    # Live, and still not something the factory may be aimed at. THE MODULE'S OWN SENTENCE, not a
    # second one written here: `_not_a_promise` is what `align_card` and `break_down` both answer
    # with, and it separates a proposal from a reading of the code — a person told two different
    # things about one rule learns the rule is arbitrary.
    return _not_a_promise(requirement, req)


def _queue_reply(project, module, name: str, thread: str, *,
                 channel: str = "", preamble: str = "", user: str = "") -> Reply | str | None:
    """Propose what to start next, and stage it for one yes.

    The proposal is the argument; the yes is the decision. Staged like a draft because it is the
    same kind of commitment: approving a specific ordered list, not a direction. Staged for `user`
    (#266 slice 4): the yes that spends money is the one who asked for the start's, like every
    other."""
    from openfactory.product.voice import queue_proposal

    lang = getattr(project, "language", None)
    state, proposal, error = module.propose_queue()
    if state is None:
        log.warning("[%s] queue proposal could not read the board: %s",
                    getattr(project, "name", "?"), str(error)[:400])
        return ("Não consegui olhar o quadro agora — o problema é do meu lado, e o time já tem o "
                "detalhe. Tente de novo daqui a pouco.")

    titles = {}
    try:
        titles = {t.number: t.title for t in module._board_tickets or []}
    except Exception as exc:  # noqa: BLE001 — titles are decoration, the numbers still go out
        log.info("could not read ticket titles (%s) — the message will carry numbers only", exc)
        titles = {}

    text = queue_proposal(state, proposal, titles=titles, language=lang, agent_name=name)
    if proposal and proposal.items:
        replaced = remember(thread, {"kind": "queue", "channel": channel,
                                     "numbers": [i.ticket for i in proposal.items]},
                            lang=lang, project=project, person=user)
        # THE PREAMBLE GOES INSIDE, never around the return: an offered proposal interpolated
        # into an f-string turned into a plain `str`, and it went out twice. Same reason
        # `offer_draft` takes its preamble as an argument.
        return offer(project, thread, preamble + replaced + text)
    return text


def _needs_action_reply(review, name: str, *, language=None) -> str:
    """The composer moved to `openfactory/product/voice.py` (#105); this is the engine's call
    into it.

    It was the only sentence in the product's VOICE that lived in the channel's package, and it was
    hardcoded pt-BR — so a client on another language read Portuguese and a deployment without
    Slack could not reach the words at all. `language` is threaded through rather than defaulted
    here, because defaulting in the transport is how the hardcoding happened the first time."""
    from openfactory.product.voice import needs_action_report

    return needs_action_report(review, language=language, agent_name=name)


def _waiting_release_refs(project) -> list[str]:
    """The refs of every release still waiting on the client's word, oldest first — or [].

    Best-effort: this feeds ONE parenthesis in a chat reply, and an unreadable ledger must cost
    the parenthesis, never the answer."""
    try:
        from openfactory.memory import store as loop_store
        from openfactory.memory.ledger import ACCEPTANCE, waiting
        from openfactory.product.followup import OWNER, is_release

        loops = [x for x in waiting(loop_store.read(project.name), owner=OWNER)
                 if x.kind == ACCEPTANCE and is_release(x)]
        return [is_release(x) for x in sorted(loops, key=lambda x: x.ts)]
    except Exception as exc:  # noqa: BLE001 — the parenthesis is decoration; the ask is not
        log.info("could not list the waiting releases for the ambiguity reply (%s)", exc)
        return []


def _close_release(project, loop, verdict: str) -> None:
    """The release loop closed with a verdict the gate has let count (#273). Never raises.

    `settle_acceptance` hands a release loop back OPEN: it reads what was said and cannot see who
    said it. `_maybe_release` can, and this is the close it makes once the verdict counts. The
    ledger is re-read rather than taken from the caller, because another turn may have closed the
    loop in between, and `close_by_observation` then appends nothing: a settled outcome is never
    rewritten. Best-effort and loud, like every ledger write (`memory/store.py`): the verdict was
    heard, and recording it must never cost the reply."""
    name = getattr(project, "name", "") or ""
    try:
        from openfactory.memory import store as loop_store
        from openfactory.memory.ledger import ACCEPTANCE, close_by_observation

        rows = close_by_observation(loop_store.read(name),
                                    {(ACCEPTANCE, loop.subject, loop.about): verdict})
        if rows:
            loop_store.write(name, rows)
    except Exception:  # noqa: BLE001 — the reply is already earned; the record is best-effort
        log.warning("[%s] the verdict %r on %s was heard and could not be recorded — the loop "
                    "stays open", name, verdict, getattr(loop, "subject", "?"), exc_info=True)


def _maybe_release(project, module, loop, verdict: str, user: str, agent: str, lang,
                   *, ambiguous: bool, via: str = "slack") -> str | None:
    """The client's answer to "is it ready to go live?" — or None when this was an ordinary one.

    None rather than a boolean, so the caller's normal path is untouched by a branch that does not
    apply: every other acceptance still reads exactly as it did.

    THREE THINGS MAKE THIS DIFFERENT FROM ITS SIBLINGS, and each is a rule the ordinary acceptance
    does not need:

    1. AMBIGUITY IS REFUSED, NOT NAMED. With two deliveries waiting, `settle_acceptance` settles
       the newest and the reply says which — a wrong guess costs one correction. Here a wrong guess
       PUTS THE WRONG SOFTWARE IN FRONT OF THE CLIENT'S USERS, so the guess is not offered: they
       are asked which one, and nothing is released.
    2. AUTHORISATION IS RE-CHECKED. Reading a message is not an act; releasing is. `may_act` is the
       deployment's own declared list, so who may do this is a registry line and never "whoever is
       in the room". ON EVERY SURFACE THAT REACHES THIS STAGE (2026-08-25): a "funcionou o #12"
       typed in the panel's product box reaches this same gate — by design, the panel is the
       reference surface (ADR-0038 D1) and the product box is not a second, softer approver — and
       `via` records which surface the approver was speaking from, never who may approve.
    3. THE ACT IS OBSERVED BEFORE IT IS CLAIMED. `release()` re-asks the workflow whether it is
       still parked, and returns the honest sentence when it is not. A client told "subiu" over a
       signal that reached nothing is the worst outcome available on this path.

    A "não funcionou" releases NOTHING and says so plainly, and closes the loop as
    `did-not-work`, which is the record that matters.

    THE LOOP IS CLOSED HERE, AND ONLY ONCE THE VERDICT COUNTS (#273). `settle_acceptance` used to
    close it as `worked` before this asked who was speaking, so a refused "funcionou" released
    nothing and still took the question away from the admin who could have answered it — and the
    ledger said the release was accepted. It hands a release loop back open now, and this is the
    one place that closes it: on a "não funcionou", and on a "funcionou" after `may_act` passes.
    """
    # IMPORTED AT THE TOP OF THIS FUNCTION, never inside the branch that uses them. `may_act` was
    # imported inside one branch of `_run_intent` earlier today; the client read "algo quebrou do
    # meu lado" for an UnboundLocalError. The gate is the last thing that may be reached by luck.
    from openfactory.product.followup import is_release
    from openfactory.product.module import may_act, unauthorized_message

    issue = is_release(loop)
    if not issue:
        return None                      # an ordinary delivery acceptance; the caller handles it

    head = f"{agent}: " if agent else ""
    if verdict != "worked":
        # A "NÃO FUNCIONOU" CLOSES THE LOOP from whoever says it, as it did when the module closed
        # it: it spends nothing, and a release that did not work is not waiting on anybody's yes.
        _close_release(project, loop, verdict)
        return (f"{head}entendi — **não subi nada**. Vou devolver isso ao time com o que você "
                f"disse, e volto quando estiver corrigido para você conferir de novo.")
    if ambiguous:
        # NOTHING was released AND nothing was closed (module.settle_acceptance hands every release
        # back open — #24 item 2, #273): the question below is still pending, so the reply that
        # names the ref settles the right loop and releases it. The instruction gives the exact
        # sentence the parser understands, because "me diga o número" alone used to instruct a
        # reply no code path could read — an unfollowable instruction from the platform's own
        # mouth.
        listed = _waiting_release_refs(project)
        which = f" ({', '.join(f'#{r}' for r in listed)})" if listed else ""
        return (f"{head}tem mais de uma coisa esperando a sua conferida{which}, então **não subi "
                f"nada** — prefiro não adivinhar qual delas você testou. Responda "
                f"«funcionou o #número» e eu coloco essa no ar.")
    if not may_act(project, user, via=via):
        # THE QUESTION STAYS OPEN FOR SOMEBODY WHO MAY ANSWER IT (#273). Nothing has closed the
        # loop before this line, so it is still waiting — still chased — and an admin's own
        # "funcionou" lands on it and releases.
        return unauthorized_message(project)
    # CLOSED NOW, by the verdict of somebody who may act (#273) — and before the release, not
    # after it: the loop records what they said, and `release()` says separately, and honestly,
    # whether the workflow was still there to take it.
    _close_release(project, loop, verdict)

    from openfactory.product.release import release

    ok, why = release(project, issue, approver=user,
                      comment="aprovado pelo cliente no canal de produto")
    if not ok:
        return f"{head}{why}"
    return (f"{head}perfeito — **estou subindo para produção agora**, com o seu \"funcionou\" "
            f"como aprovação. Fica registrado que foi você quem liberou e quando. Eu volto aqui "
            f"quando estiver no ar.")


# ── `_where_it_came_from`, `_also_broke_it_down` and `_breakdown_reply` moved with the executor ──
#
# They are the confirmation's own prose: the provenance cell of a decision row, the acceptance's
# automatic breakdown, and what the client reads afterwards. `_breakdown_reply` is imported back
# because `_run_intent` composes the same sentence for a typed "quebra o requisito 7" — one voice,
# whether the breakdown was asked for or followed an acceptance.


def _refine_reply(result, number: str, name: str, lang=None, project=None) -> str:
    """What the client reads after a ticket was given something testable to be judged against.

    Composed from the real `WriteResult`, like every other write reply — the agent never narrates
    this (ADR-0028). Three outcomes, three sentences: written, already had criteria, failed.

    THE REFUSAL POINTS SOMEWHERE. It is still a refusal — this act unblocks a card with nothing
    written, and amending criteria somebody may already be working from is a different risk that
    costs a model call and changes what gets built. But it now names that other act, because a
    refusal with no alternative reads as "this cannot be done", and the person who hit it in
    production was holding exactly the card the other act was built for.

    THE FOURTH TWO-WRITE BRANCH, and the one left out when `close`, `defect` and `align` learned
    the rule. `refine` writes the criteria and then comments to say who wrote them, and the comment
    failing comes back as a SUCCESS carrying the module's own sentence about it. This line
    announced the comment regardless AND put that sentence where the count goes, so the client read
    a denial and an assertion of the same note eight words apart.
    """
    head = f"{name}: " if name else ""
    if not result.ok:
        return f"{head}{_client_detail(result.detail, lang, project=project)}"
    if getattr(result, "existed", False):
        from openfactory.product.voice import refine_refused

        return head + refine_refused(number=number, language=lang)
    from openfactory.product.voice import criteria_written

    # the count is shown only when there is a count: the same field carries the residue instead
    # whenever the second write failed, and `_unfinished` is the one reading that tells them apart.
    # Through the sanitiser even on SUCCESS — every detail a client reads is sanitised, with no
    # exception anybody has to remember.
    residue = _unfinished(result)
    return _still_to_say(
        head + criteria_written(
            number=number, noted=not residue,
            measure="" if residue else _client_detail(result.detail, lang, project=project),
            language=lang),
        result, lang, project=project)


def _baseline_reply(project, module, name: str, user: str, on_it=None, *,
                    conversation: str = "", room: str = "", asked: str = "") -> str:
    """Somebody asked for the brownfield first pass — a read of the whole codebase written up as
    OBSERVATIONS for a person to confirm (`brownfield.py`, ADR-0019).

    ANNOUNCED, THEN RUN, OFF THE LISTENER THREAD. It reads an entire repository through an agent
    and comes back with a pull request: minutes, not seconds. Blocking here would time out the
    Socket Mode handler and take the channel down for everyone; saying nothing until it finishes
    is the "looks broken while working" failure this whole layer exists to remove.

    THE RECEIPT IS SAID BEFORE THE PASS STARTS, not inside it (#266 slice 2): a receipt is a reply
    of THIS turn, and one said from the thread after the turn returned would reach nobody.

    THE OUTCOME COMES BACK THROUGH THE DOOR (ADR-0051 D6, #266 slice 3). It is an asynchronous
    task the role started and reports back on, so its result is an INTERNAL EVENT on the
    conversation it was asked in (`door.tell`): recorded in the product's memory, then published
    to that conversation — never a bare `say` on a channel from this thread, which reached a room
    the asker may not have been in and left memory without the answer. `conversation` is where it
    was asked (the project's room when a caller did not say), `asked` the message the outcome
    answers.

    For a while this replied that the pass was not wired — an honest admission that was better
    than pretending, and worse than doing it."""
    from openfactory.product.module import may_act, unauthorized_message
    from openfactory.product.voice import baseline_done, baseline_started

    if not may_act(project, user):
        return unauthorized_message(project)

    lang = getattr(project, "language", None)
    where = conversation or getattr(project, "name", "") or ""
    if on_it:
        on_it()

    def _run() -> None:
        try:
            result = module.baseline()
            text = baseline_done(ok=result.ok, url=result.url, detail=result.detail,
                                 existed=result.existed, language=lang, agent_name=name)
        except Exception as exc:  # noqa: BLE001 — a thread dying silently is the worst outcome
            log.exception("the baseline pass crashed for %s", getattr(project, "name", "?"))
            text = baseline_done(ok=False, detail=str(exc)[:200], language=lang, agent_name=name)
        finally:
            # the pass may have composed a view of its own after the turn released its one
            release(module)
        try:
            from openfactory.product import door

            told = door.tell(project, conversation=where, text=text, room=room,
                             in_reply_to=asked, addressed_to=user)
        except Exception as exc:  # noqa: BLE001 — the work happened; only the telling failed
            told = False
            log.error("the baseline finished but could not be announced (%s) — the pull request "
                      "may exist and nobody was told", exc)
        if not told:
            # the door reports a refusal by returning False, not only by raising — an engine that
            # is down, a project that lost its product role — and the error above never fires
            # for it, which is precisely the silence this marker exists to name
            log.error("OPENFACTORY_PRODUCT_BASELINE_UNANNOUNCED project=%s — the baseline outcome "
                      "never "
                      "reached the conversation; the client is still waiting on a 'done' that "
                      "was computed and not delivered", getattr(project, "name", "?"))

    threading.Thread(target=_run, daemon=True, name="product-baseline").start()
    return baseline_started(language=lang, agent_name=name)
