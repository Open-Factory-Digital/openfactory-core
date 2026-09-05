"""The product conversation: a client talking to their product, not an operator to a factory.

THIS IS THE PRODUCT ROLE'S CONVERSATION ENTRY, AND IT IS CORE. It lived in `runtime/slack/` from
the day it was written until 2026-08-25, and the address was a false claim: the file has zero Slack
imports and every one of its dependencies is `openfactory.product.*` or `openfactory.memory.*`. What
the address cost was measured by deleting the Slack package on a tree that had it: 56 failed, 98
errors, 25 test modules uncollectable — of which only five were about Slack; the other twenty were
the decision loop, the acceptance loop, confirmations, releases and memory recall, all of which had
been filed under a vendor. A channel (ADR-0038 D3) renders and parses; it does not own the
conversation. The Slack bot is one caller of `handle`; the panel's turn reaches `settle` — the
stage every surface shares — and nothing in here knows how either of them posts.

A project without a product channel never reaches any of this: the caller asks
`is_product_channel` first, so the tech-lead's path is untouched by construction.

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
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from openfactory.contracts.refs import canonical_ref

log = logging.getLogger("openfactory.product.channel")

# ── the CONFIRMATION EXECUTOR now lives in `openfactory/product/confirm.py` (#105)
# ───────────────────
#
# The ten branches that performed a confirmed write were the last thing keeping this file an
# implementation rather than a mapping. They were never Slack-specific: they read a staged entry,
# ask `may_act`, pop by compare-and-swap and call the product module. What made moving them worth
# doing is that the PANEL had to reach into this package to run one — the documented exception in
# `test_provider_seams`, now deleted.
#
# The FUNCTIONS are bound here, unlike the mutable state below, and deliberately so: a test that
# monkeypatches `pc.answer_staged` is patching what `confirm_by_click` calls, which is the point.
from openfactory.product.confirm import (  # noqa: E402 — after the docstring, like the staging import
    _breakdown_reply,
    _client_detail,
    _is_requester,
    _still_to_say,
    _unfinished,
    answer_staged,
    receipt,
)
from openfactory.product.confirm import confirm as confirm_staged  # noqa: E402

# ── the staged proposal now lives in `openfactory/product/staging.py` (#98 slice 3)
# ──────────────────
#
# It was never Slack-specific — its only dependencies are `openfactory.memory`,
# `openfactory.product.voice` and
# `openfactory.product.role`. It was written here first, which is exactly the coupling this card
# exists
# to undo, and it was already reached from a second surface before the move: `api/app.py` calls
# `answer_staged`, with the reach-into-Slack documented there as an explicit exception.
#
# RE-EXPORTED, NOT RE-IMPLEMENTED. `_PENDING` is bound BY IDENTITY here, never copied — but note
# that binding is NOT enough for a caller that REBINDS the name: eight test fixtures did exactly
# that (`monkeypatch.setattr(pc, "_PENDING", {})`) to isolate themselves, and after this move
# they must patch `openfactory.product.staging` instead, or they look like they isolate and do not.
from openfactory.product.staging import (  # noqa: F401,E402 — re-exported for callers and tests
    _ENTRY_MODELS,
    _MAX_PENDING,
    _NO,
    _PENDING_LOCK,
    PROPOSAL_TTL_SECONDS,
    _entry_models,
    _expired_recently,
    _freeze,
    _pending_from_store,
    _proposal_summary,
    _thaw,
    consume,
    find_waiting,
    forget,
    is_no,
    is_yes,
    pending_for,
    proposal_token,
    remember,
)

#: THE MUTABLE STATE IS FORWARDED, NOT BOUND — and the difference is a defect this move already
#: produced once. `from … import _PENDING` copies the REFERENCE at import time, so the moment
#: anything rebinds the name on either side the two modules stop sharing: writes land in one dict
#: and reads come out of the other. Eight test fixtures rebind exactly this to isolate themselves
#: (`monkeypatch.setattr(staging, "_PENDING", {})`), so binding here would leave every read on
#: this module pointing at a dict nobody writes to — `KeyError` at best, and silently stale at
#: worst. PEP 562 module `__getattr__` resolves it on every access instead.
_FORWARDED = ("_PENDING", "_EXPIRED_TOMBSTONES")


def __getattr__(name: str):
    if name in _FORWARDED:
        from openfactory.product import staging

        return getattr(staging, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")



class Posted(str):
    """Text that is ALREADY on the channel — post it again and the person sees it twice.

    IT IS THE TEXT, and it is TRUTHY EVEN WHEN EMPTY. Both matter, and both come from a bug this
    class exists to make impossible:

    `None` already means "this path could not answer — fall through to the conversational
    model", and the first interactive version returned `None` for "already posted". A queue
    proposal posted with buttons therefore read as an intent that had FAILED: the client got the
    buttons AND an unrelated conversational reply, and paid for a model call to produce it. Two
    different facts sharing one value — a class catalogued here four times, committed fresh.

    Being the text keeps the transcript honest: what she said is recorded from this value
    (ADR-0024), so a proposal posted interactively lands in her memory like any other turn
    instead of vanishing from it.
    """

    def __bool__(self) -> bool:
        return True


def offer_with_buttons(project, key: str, text: str, confirm) -> str | Posted:
    """Post `text` as an interactive confirmation when the provider can. Returns None when it did
    (already posted), or `text` for the caller to return as prose.

    ONE helper for all four staging sites, because four copies of "try buttons, else prose" is how
    three of them end up without the button and nobody notices — the shape of this repository's
    signature defect. `confirm` comes from the listener and is None everywhere else (an activity, a
    test, the panel), so those degrade to prose by construction rather than by remembering to.
    """
    entry = pending_for(key)
    if confirm is None or entry is None:
        return text
    from openfactory.product.voice import confirm_labels, or_just_reply

    lang = getattr(project, "language", None)
    approve, reject = confirm_labels(language=lang)
    # THE TYPED PATH IS ADVERTISED ALONGSIDE THE BUTTONS, and not as politeness. A click only
    # reaches the worker when the Slack app has Interactivity enabled — a setting this code cannot
    # check. With it off the button post still SUCCEEDS, so the prose fallback would not be sent and
    # the proposal would wait for a click that can never arrive. This line makes the confirmation
    # reachable either way, which beats a runbook step somebody has to remember.
    try:
        posted = confirm(f"{text}\n\n{or_just_reply(language=lang)}",
                         proposal_token(key, entry), approve, reject)
    except Exception:  # noqa: BLE001 — the affordance is optional; the proposal is not
        log.warning("could not offer an interactive confirmation", exc_info=True)
        return text
    return Posted(text) if posted else text




def confirm_by_click(project, *, token: str, approved: bool, user: str, module=None,
                     notify=None) -> str | None:
    """A person pressed Approve or Reject. Returns what to say, or None to stay quiet.

    THE POINT OF THE WHOLE BUTTON PATH: nothing here is interpreted. The click names the proposal,
    Slack names the clicker, and the only judgment left is authorisation — which is a lookup. The
    prose path (a word list, then a model reading the sentence) remains for people who type, and it
    is strictly the less certain of the two.

    `notify` is the same seam the typed path carries, and it is here because an approval is the
    slow path whichever way it arrives: without it a click could not even be acknowledged, so the
    one person who pressed the button got less than the one who typed "sim".
    """
    _code, sentence = answer_staged(project, token=token, approved=approved, user=user,
                                    module=module, notify=notify)
    return sentence


def conversation_key(event: dict, channel: str) -> str:
    """Which conversation a Slack event belongs to — the identity everything else keys on.

    THE 14TH INSTANCE OF THE SIGNATURE DEFECT LIVED IN THIS DECISION. The listener used
    `thread_ts or ts`: correct for replies inside a thread, but a bare channel message's fallback
    is ITS OWN ts — so every bare message became a brand-new conversation. All ten memory tests
    passed with a fixed thread id, and the real channel — where the product owner talks to Nina in
    bare messages, as the screenshots show — never produces one. Memory built, tested, reached by
    nothing. The same key also staged confirmations, so a bare "sim" could never find a proposal
    made two messages earlier.

    The fix: a bare message belongs to the CHANNEL's rolling conversation; only a message inside
    a real thread belongs to that thread. In a 1:1 client channel the room IS the exchange.
    """
    return event.get("thread_ts") or channel


def is_product_channel(project, channel: str) -> bool:
    cfg = getattr(project, "product", None)
    if cfg is None or not getattr(cfg, "enabled", True):
        return False
    return bool(channel) and channel == cfg.channel_id


def handle(project, *, text: str, user: str, thread: str, module=None,
           source: str = "", channel: str = "", notify=None, confirm=None,
           fingerprint: str = "") -> str | None:
    """One message in the product channel. Returns what to say, or None to stay quiet.

    `fingerprint` is what a CLICK already verified, carried down to the pop (`consume`). Empty for
    a typed message, which has verified nothing yet — this handler is where that happens.

    Never raises: a chat caller runs this inside its listener (Socket Mode, for one), where an
    exception takes the channel down for everyone until someone notices."""
    from openfactory.memory import transcript

    name = getattr(project, "name", "?")
    reply: str | None = None
    # ADR-0024 layer 0, the PERSON's turn: recorded on ARRIVAL, not after the reply. An answer here
    # can take minutes (a model call, a checkout), and a follow-up message that lands meanwhile
    # used to find no trace of this one — the handler answered the second message with amnesia
    # about the first. The GSI may or may not surface this row to a concurrent read; late is the
    # eventual-consistency cost either way, and absent-by-design was strictly worse.
    arrival_ts = ""
    try:
        arrival_ts = transcript.record(name, thread=thread, role="person", text=text, actor=user,
                                       channel=channel) or ""
    except Exception:  # noqa: BLE001 — the record must never cost the person their answer
        log.warning("[%s] could not record the incoming turn", name, exc_info=True)
    try:
        reply = _handle(project, text=text, user=user, thread=thread, module=module,
                        source=source, channel=channel, notify=notify, confirm=confirm,
                        arrival_ts=arrival_ts, fingerprint=fingerprint)
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
        # the AGENT's turn still lands after: what she said only exists once `_handle` returns
        if reply:
            # recorded from the value even when it was posted interactively — her memory must hold
            # the proposal she made, whichever way it reached the channel
            transcript.record(name, thread=thread, role="agent", text=str(reply), channel=channel)
    # `Posted` is on the channel already; returning it would show the person the same text twice
    return None if isinstance(reply, Posted) else reply


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
    loops that no client could ever close. The chat handler (`_handle`) and the worker's turn
    (`activities._product_conversation`) both call this now; each renders its own way, neither
    implements it.

    WHAT THE PANEL'S TURN ENTERS TODAY, STATED HONESTLY: the acceptance branch. The other two —
    a typed yes or no on a staged proposal, and the notice for one that expired — run on the
    panel's path and find nothing, because nothing STAGES a proposal under the panel's key: the
    producers (`offer_draft`, the typed intents) are chat-only, and the panel proposes through its
    own button (`product_propose`) and answers tokens through `product_answer`. They stay in the
    shared stage so the day a producer arrives on the panel, a yes typed there is performed by the
    executor the click uses rather than by a second copy of this; until then the gap is measured
    by `test_nothing_stages_a_proposal_under_the_panel_s_key_yet`, which goes red the day it
    closes and names the three places to update.

    `via` IS PROVENANCE, NOT PERMISSION — the transport this message arrived through, handed to
    every gate this stage reaches (`confirm`, the rejection, `_maybe_release`) so the record of who
    authorised a write says where they were speaking from. Defaulted like `may_act` is, so the
    chat handler keeps saying exactly what it said; the worker's turn passes what the panel sent.

    RENDERED SENTENCES, ON PURPOSE. Every branch answers in the client's voice (`product/voice`),
    which is core and takes the project's language; nothing here knows how a channel posts, and no
    `Posted` can come out of it — the interactive seam belongs to the caller.

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
    waiting_key, waiting = find_waiting(thread, channel, project=project)

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
        consume(waiting_key, waiting, fingerprint=fingerprint, project=project, by=user,
                approved=True)
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


def _handle(project, *, text: str, user: str, thread: str, module,
            source: str = "", channel: str = "", notify=None, confirm=None,
            arrival_ts: str = "", fingerprint: str = "") -> str | None:
    from openfactory.product.module import ProductModule, may_act
    from openfactory.product.voice import unavailable

    lang = getattr(project, "language", None)
    module = module or ProductModule(project)
    # ONE RECEIPT PER MESSAGE, and the factory is in the core so the click path gets the same one:
    # seeded by the message, so consecutive questions differ while the same message always produces
    # the same acknowledgement (deterministic tests, answerable support).
    _on_it = receipt(project, notify, seed=text)

    # ---- what she asked last is answered first --------------------------------------------------
    # A staged proposal, an open delivery, an expired proposal: `settle` is the stage this handler
    # shares with the worker's turn, so a chat surface and the panel give one answer to one message.
    # What is left below is what a CHAT surface does with a message that answered nothing — typed
    # intents, then the conversation with its staged drafts.
    settled = settle(project, text=text, user=user, thread=thread, module=module, channel=channel,
                     fingerprint=fingerprint, on_it=_on_it)
    if settled.reply is not None:
        return settled.reply
    waiting = settled.waiting

    # ---- a human spoke, so the decisions SHE asked for were answered ---------------------------
    # BEFORE anything else, and before her new reply can open fresh ones: this very message is the
    # person responding to what she asked last round. Closing after would either close the ones she
    # just opened, or leave last round's open for ever.
    # ONLY WHEN THE MESSAGE WILL ACTUALLY REACH HER. The first version closed every open decision on
    # ANY inbound message, resting on "a partial answer is safe because she re-asks what is still
    # undecided". That holds only if she READS the message — and the intent shortcuts below
    # (`status`, `triage`, a bare confirmation) answer from data already in hand and never reach the
    # model. So a bare "status" silently closed three chased decisions as `answered` and nothing
    # would ever ask again: precisely the silent loss the decision ledger exists to prevent.
    #
    # Deferred to the conversational path, which is the only one she reads. A message that only says
    # "status" leaves the decisions open — one more reminder, which is the cheap direction.
    _closed_decisions = False

    def _close_decisions_if_she_reads_this() -> None:
        nonlocal _closed_decisions
        if _closed_decisions:
            return
        _closed_decisions = True
        try:
            module.close_decisions_answered(channel=channel)
        except Exception:  # noqa: BLE001 — bookkeeping must never cost the reply
            log.warning("[%s] could not close answered decisions", getattr(project, "name", "?"),
                        exc_info=True)

    # ---- an explicit ASK for one of the things this role does on its own -----------------------
    # Matched before the corpus is consulted: "who are you" and "how are we doing" must answer even
    # when the requirements cannot be read, which is exactly when someone asks.
    from openfactory.product.intents import match_intent

    matched = match_intent(text)
    if matched:
        intent, captures = matched
        done = _run_intent(project, intent, captures, module=module, lang=lang, user=user,
                           on_it=_on_it, confirm=confirm,
                           thread=thread, channel=channel)
        if done:
            return done

    ctx = module.context()
    if not ctx.available:
        log.warning("[%s] product module unavailable: %s", project.name, ctx.reason)
        return unavailable(language=lang)

    # ---- everything else is a conversation ----------------------------------------------------
    # ADR-0024 layer 1. Without this every message was turn 1: no "e o segundo?", no correction,
    # no knowing she had asked something when the answer arrived.
    # THE RECEIPT GOES FIRST — before the transcript query, before the model. Everything below
    # this line is work the person is waiting through, and the whole point is that they should not
    # have to guess whether anything is happening.
    _on_it()

    from openfactory.memory import transcript

    # the CURRENT message is excluded by the ts it was recorded under: it is already the
    # "## Question" of this prompt, and history is strictly what came before it
    said = transcript.render(
        [t for t in transcript.recent(project.name, thread=thread, channel=channel)
         if not (arrival_ts and t.ts == arrival_ts)],
        agent_name=getattr(getattr(project, "product", None), "agent_name", ""),
        # THE CLIENT'S LANGUAGE, said here rather than welded into the renderer (#168). This block
        # is read by a model that is answering a pt-BR client; the tech-lead's identical block is
        # read by one whose whole surface is English.
        heading="## Conversa até aqui (mais antigo primeiro)", you="você", somebody="pessoa")
    _close_decisions_if_she_reads_this()

    # WHAT IS STILL WAITING — the fact whose absence let her announce five registered requirements
    # she had only proposed. `waiting` is the staged entry, read at the top of this handler.
    # THIS PERSON'S INTAKE IN THIS CONVERSATION, TYPED (#33 hole 7) — beside the transcript, so
    # the fourth turn of "which screen?" is a continuation and not a re-reading.
    from openfactory.product import case as _case
    intake = _case.block_for(project, thread, user)
    # PASSED ONLY WHEN THERE IS ONE, so a module double that predates the intake (every fake in the
    # suite, and any add-on's) keeps answering first turns exactly as before.
    answer = module.answer(text, conversation=said,
                           pending=_proposal_summary(waiting) if waiting else "",
                           **({"intake": intake} if intake else {}))
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
    if getattr(answer, "decisions", None):
        try:
            module.record_decisions(answer.decisions, channel=channel)
        except Exception:  # noqa: BLE001
            log.warning("[%s] could not record the decisions she asked for", project.name,
                        exc_info=True)

    # SHE CANNOT SEE WHETHER A WRITE HAPPENED, so a reply that says one did is a claim she has no
    # standing to make. This turn wrote nothing — the write paths are the staged-confirmation
    # branches above, which all return before reaching here. Detected rather than edited: a wrong
    # correction is worse than a flagged sentence, and what shipped was worse than both — a
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

    # A QUESTION ends here. A REQUEST becomes a draft, shown back for the one confirmation — this
    # is the only route from a conversation to something written down, and without it the whole
    # write path is unreachable from the channel: every message would get a polite answer and
    # nothing would ever be recorded.
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
                          # no severity: nobody judged one, and printing "média" as if somebody
                          # had is a fabricated classification the fix queue would sort by
                          "source": source or "", "channel": channel}, lang=lang, project=project)
        ask = defect_confirmation(violates=getattr(answer, "violates", None), language=lang)
        if not may_act(project, user):
            admins = _admin_mentions(project)
            if admins:
                ask += f"\n\n({admins}: o registro precisa da sua confirmação.)"
        # the defect proposal, offered with buttons when the provider has them. The agent's own
        # words stay in front of it: the person confirms a RESTATEMENT, so they must read it.
        body = replaced + ((answer.text + "\n\n") if answer.text else "") + ask
        return offer_with_buttons(project, thread, body, confirm)

    # A GESTURE THE MODEL RECOGNISED that the word list did not (role.QUEUE_MARKER). The pattern
    # in `product_intents` still runs first and still short-circuits — this is the escape for the
    # phrasings it does not carry, and it costs nothing extra because this call already happened.
    #
    # AFTER `is_defect` AND BEFORE `is_request`, and the order is load-bearing rather than
    # aesthetic: `remember` holds ONE staged entry per conversation (see its docstring), so two
    # branches staging in the same turn displace each other in silence. A broken promise outranks
    # a request to start — it is about work already owed — and asking to START the agreed work is
    # not asking for something NEW, so it must not fall through into a draft proposal.
    if getattr(answer, "is_ticket", False):
        # SHE decided the person asked for a card, as described — not a broken promise and not a
        # wish to be argued into a requirement. The person confirms the title; an admin's yes opens
        # it. The same gate as a defect, for the same reason: it puts a card on the client's board.
        from openfactory.product.voice import ticket_confirmation

        title = ((getattr(answer, "ticket_title", "") or "").strip() or text.strip())[:80]
        replaced = remember(thread, {"kind": "ticket", "title": title,
                                     "described": text.strip()[:1500],
                                     "reported_by": f"<@{user}>" if user else "",
                                     "source": source or "", "channel": channel},
                            lang=lang, project=project)
        ask = ticket_confirmation(title=title, language=lang)
        if not may_act(project, user):
            admins = _admin_mentions(project)
            if admins:
                ask += f"\n\n({admins}: abrir o cartão precisa da sua confirmação.)"
        body = replaced + ((answer.text + "\n\n") if answer.text else "") + ask
        return offer_with_buttons(project, thread, body, confirm)
    if getattr(answer, "gesture", "") == "queue":
        # HER ANSWER TRAVELS WITH IT. Both sibling branches carry `answer.text` in front of what
        # they stage — a person confirms a proposal, so they must read what she said about it —
        # and this one dropped it: she answered the question and the reply was replaced by a bare
        # queue. The gesture was recognised BY reading the message; throwing away the reading is
        # the one thing that makes the marker path worse than the pattern it exists to rescue.
        proposed = _run_intent(project, "queue",
                               {"preamble": f"{answer.text}\n\n" if answer.text else ""},
                               module=module, lang=lang, user=user,
                               on_it=_on_it, confirm=confirm, thread=thread, channel=channel)
        if proposed:
            # WHOLE AND UNTOUCHED, like `offered` below: `_queue_reply` can return a `Posted`, and
            # interpolating one into an f-string turns it into a plain `str` — the boundary then
            # cannot tell it was already posted and the proposal goes out twice.
            return proposed

    if answer.is_request:
        offered = offer_draft(project, request=text, user=user, thread=thread, module=module,
                              on_it=_on_it, confirm=confirm, channel=channel,
                              preamble=f"{answer.text}\n\n" if answer.text else "",
                              asked_by=f"<@{user}>" if user else "", source=source or "")
        if offered:
            # returned WHOLE and untouched, so `Posted` survives: interpolating it here is exactly
            # what posted the proposal twice
            return offered
    return answer.text


def offer_draft(project, *, request: str, user: str, thread: str, module,
                asked_by: str = "", date: str = "", source: str = "", on_it=None,
                confirm=None, preamble: str = "", channel: str = "") -> str | None:
    """Draft what was asked for and show it back for confirmation.

    Separate from `handle` because drafting is a deliberate step: it costs a model call and it is
    what puts a proposal in front of a person, so the caller decides when a message deserves one
    rather than every remark becoming a draft."""
    from openfactory.product.voice import confirmation_request

    lang = getattr(project, "language", None)
    if on_it:
        on_it()
    answer = module.draft(request, asked_by=asked_by or user)
    if not answer.ok or answer.draft is None:
        return None  # nothing to confirm; the conversation continues

    draft = answer.draft
    replaced = remember(thread, {"answer": answer, "asked_by": asked_by or user, "date": date,
                                 "source": source, "kind": "draft", "channel": channel,
                                 "number": _next_number(module)}, lang=lang, project=project)
    # THE REASONING GOES ABOVE THE BUTTONS, IN THE SAME MESSAGE. Returned separately it was posted
    # separately — and after the block it justifies, so the person read "confirm this?" before the
    # argument for it. Worse, concatenating a `Posted` into an f-string produced a plain `str`, the
    # boundary could no longer tell it had been posted, and the whole proposal went out TWICE.
    # A sentinel that survives only until somebody interpolates it is not a sentinel.
    return offer_with_buttons(project, thread, preamble + replaced + confirmation_request(
        title=draft.title, must_be_true=draft.must_be_true,
        conflicts=[_conflict_line(c) for c in draft.conflicts], language=lang), confirm)


def _conflict_line(conflict) -> str:
    ref = f"requisito {conflict.requirement}" if conflict.requirement else "algo já decidido"
    return f"{ref} — {conflict.explanation}"


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
    config — this is the one place a raw `<@id>` is correct, because the id IS the config."""
    cfg = getattr(project, "product", None)
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
                user: str = "", thread: str = "", on_it=None, confirm=None,
                channel: str = "") -> str | None:
    """Do the thing that was asked for. `None` falls back to conversation — a recognised intent
    that cannot be carried out must not swallow the message."""
    # IMPORTED ONCE, AT THE TOP — both of them, because a gate and its refusal are never used
    # apart. It used to be imported inside the `fact` branch, which makes it a function-local name
    # for the WHOLE function — so the next branch added above that line raised UnboundLocalError on
    # its authorisation check and the client got "algo quebrou do meu lado". A landmine that arms
    # itself for whoever writes the next intent is worth removing, not documenting.
    from openfactory.product.module import may_act, unauthorized_message
    from openfactory.product.voice import triage_report

    name = getattr(getattr(project, "product", None), "agent_name", "") or ""

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
                            lang=lang, project=project)
        ask = fact_confirmation(term=term, body=fact, language=lang)
        if not may_act(project, user):
            admins = _admin_mentions(project)
            if admins:
                ask += f"\n\n({admins}: a anotação precisa da sua confirmação.)"
        return offer_with_buttons(project, thread, replaced + ask, confirm)

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
        results = module.break_down(number, actor=user)
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
                        lang=lang, project=project)
        return offer_with_buttons(project, thread, body + accept_confirmation(
            number=number, title=req.title or req.slug, language=lang), confirm)

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
                        lang=lang, project=project)
        ask = drop_confirmation(number=number, title=req.title or req.slug,
                                was_a_promise=was_a_promise, language=lang)
        if not may_act(project, user):
            admins = _admin_mentions(project)
            if admins:
                ask += f"\n\n({admins}: a decisão precisa da sua confirmação.)"
        return offer_with_buttons(project, thread, body + ask, confirm)

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
                        lang=lang, project=project)
        # THE SENTENCE IS SHOWN BACK VERBATIM, and that is the point of staging this at all: the
        # whole value of the register is that somebody reads these exact words in three months, so
        # a paraphrase approved today is a paraphrase found then.
        ask = decision_confirmation(number=number, decision=decision, language=lang)
        if not may_act(project, user):
            admins = _admin_mentions(project)
            if admins:
                ask += f"\n\n({admins}: a decisão precisa da sua confirmação.)"
        return offer_with_buttons(project, thread, body + ask, confirm)

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
                        lang=lang, project=project)
        ask = close_confirmation(number=number, in_favour_of=in_favour_of, reason=reason,
                                 language=lang)
        if not may_act(project, user):
            admins = _admin_mentions(project)
            if admins:
                ask += f"\n\n({admins}: o encerramento precisa da sua confirmação.)"
        return offer_with_buttons(project, thread, body + ask, confirm)

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
                        lang=lang, project=project)
        ask = align_confirmation(number=number, requirement=requirement,
                                 title=req.title or req.slug, language=lang)
        if not may_act(project, user):
            admins = _admin_mentions(project)
            if admins:
                ask += f"\n\n({admins}: a mudança precisa da sua confirmação.)"
        return offer_with_buttons(project, thread, body + ask, confirm)

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
        return _baseline_reply(project, module, name, user, on_it)

    if intent == "queue":
        return _queue_reply(project, module, name, thread, confirm, channel=channel,
                            preamble=captures.get("preamble", ""))

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
    `_handle`'s `ctx.available` gate is reached only when the dispatcher falls through, while each
    of these three branches returns a sentence — so on a docs outage the product owner told an
    accounting client, flatly, that a requirement they had written themselves does not exist. It is
    the same state that once answered "how many requirements are there" with "zero".

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


def _queue_reply(project, module, name: str, thread: str, confirm=None, *,
                 channel: str = "", preamble: str = "") -> str | None:
    """Propose what to start next, and stage it for one yes.

    The proposal is the argument; the yes is the decision. Staged like a draft because it is the
    same kind of commitment: approving a specific ordered list, not a direction."""
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
                            lang=lang, project=project)
        # THE PREAMBLE GOES INSIDE, never around the return. `offer_with_buttons` can hand back a
        # `Posted`, and interpolating one into an f-string turns it into a plain `str` — the
        # boundary then cannot tell it was posted and the proposal goes out twice. Same reason
        # `offer_draft` takes its preamble as an argument.
        return offer_with_buttons(project, thread, preamble + replaced + text, confirm)
    return text


def _needs_action_reply(review, name: str, *, language=None) -> str:
    """The composer moved to `openfactory/product/voice.py` (#105); this is the channel's call
    into it.

    It was the only sentence in the product's VOICE that lived in this package, and it was
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

    A "não funcionou" releases NOTHING and says so plainly — the loop is already closed as
    rejected by the caller, which is the record that matters.
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
        return (f"{head}entendi — **não subi nada**. Vou devolver isso ao time com o que você "
                f"disse, e volto quando estiver corrigido para você conferir de novo.")
    if ambiguous:
        # NOTHING was released AND nothing was closed (module.settle_acceptance keeps an ambiguous
        # release open — #24 item 2): the question below is still pending, so the reply that names
        # the ref settles the right loop and releases it. The instruction gives the exact sentence
        # the parser understands, because "me diga o número" alone used to instruct a reply no code
        # path could read — an unfollowable instruction from the platform's own mouth.
        listed = _waiting_release_refs(project)
        which = f" ({', '.join(f'#{r}' for r in listed)})" if listed else ""
        return (f"{head}tem mais de uma coisa esperando a sua conferida{which}, então **não subi "
                f"nada** — prefiro não adivinhar qual delas você testou. Responda "
                f"«funcionou o #número» e eu coloco essa no ar.")
    if not may_act(project, user, via=via):
        return unauthorized_message(project)

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


def _baseline_reply(project, module, name: str, user: str, on_it=None) -> str:
    """Somebody asked for the brownfield first pass — a read of the whole codebase written up as
    OBSERVATIONS for a person to confirm (`brownfield.py`, ADR-0019).

    ANNOUNCED, THEN RUN, OFF THE LISTENER THREAD. It reads an entire repository through an agent
    and comes back with a pull request: minutes, not seconds. Blocking here would time out the
    Socket Mode handler and take the channel down for everyone; saying nothing until it finishes
    is the "looks broken while working" failure this whole layer exists to remove.

    For a while this replied that the pass was not wired — an honest admission that was better
    than pretending, and worse than doing it."""
    from openfactory.product.module import may_act, unauthorized_message
    from openfactory.product.voice import baseline_done, baseline_started

    if not may_act(project, user):
        return unauthorized_message(project)

    lang = getattr(project, "language", None)
    channel_id = getattr(getattr(project, "product", None), "channel_id", None)

    def _run() -> None:
        try:
            if on_it:
                on_it()
            result = module.baseline()
            text = baseline_done(ok=result.ok, url=result.url, detail=result.detail,
                                 existed=result.existed, language=lang, agent_name=name)
        except Exception as exc:  # noqa: BLE001 — a thread dying silently is the worst outcome
            log.exception("the baseline pass crashed for %s", getattr(project, "name", "?"))
            text = baseline_done(ok=False, detail=str(exc)[:200], language=lang, agent_name=name)
        try:
            from openfactory.adapters.channel import build_channel

            told = build_channel(project).say(project=project, channel=channel_id, text=text)
        except Exception as exc:  # noqa: BLE001 — the work happened; only the telling failed
            told = False
            log.error("the baseline finished but could not be announced (%s) — the pull request "
                      "may exist and nobody was told", exc)
        if not told:
            # `say` reports refusal by returning False, not only by raising — the common failure
            # (a channel the bot is not in, a rejected post) came back on this path and the error
            # above never fired, which is precisely the silence it exists to name
            log.error("OPENFACTORY_PRODUCT_BASELINE_UNANNOUNCED project=%s — the baseline outcome "
                      "never "
                      "reached the channel; the client is still waiting on a 'done' that was "
                      "computed and not delivered", getattr(project, "name", "?"))

    threading.Thread(target=_run, daemon=True, name="product-baseline").start()
    return baseline_started(language=lang, agent_name=name)
