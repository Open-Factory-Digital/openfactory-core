"""The product conversation's CHAT ADAPTER: a chat surface's two callbacks, in front of the engine.

WHAT IS LEFT HERE, AND WHY IT IS SO LITTLE (#266 slice 2, ADR-0051 D12). This file held the whole
product conversation — 1,463 lines of settling, intents, gestures and staging — and its one caller
was the external Slack add-on, while the panel reached two reduced copies of it. The conversation
is `openfactory/product/engine.py` now, and every surface reaches that one. What stays here is the
shape a chat listener calls: `handle(project, text=…, user=…, conversation=…, people=…, via=…,
notify=…, confirm=…)`, turned into the engine's neutral `Message` on the way in and its `Reply`s
turned back into those two callbacks on the way out (`deliver`). No judgement lives here, and a
guard holds `handle` to that: it asks the add-on who its user is, hands the message to the door
and renders what comes back.

THROUGH THE ONE DOOR SINCE #266 SLICE 3 (ADR-0051 D1). `handle` no longer takes the turn in the
add-on's own process: the message goes through `product/door.py` onto its conversation's queue,
the turn runs on the worker, and the replies to this message come back here. The acknowledgement
reaches `notify` the moment the door has it.

ITS HISTORY IS WHY IT IS CORE. It lived in `runtime/slack/` from the day it was written until
2026-08-25, and the address was a false claim: the file has zero Slack imports and every one of its
dependencies is `openfactory.product.*` or `openfactory.memory.*`. What the address cost was
measured by deleting the Slack package on a tree that had it: 56 failed, 98 errors, 25 test modules
uncollectable — of which only five were about Slack. A channel (ADR-0038 D3) renders and parses; it
does not own the conversation.

NOTHING HERE PARSES A VENDOR'S EVENT ANY MORE (#266 slice 6, ADR-0051 D16). Two functions used to:
one read a chat event's thread timestamp to find its conversation, and one compared a channel id
with the product's configured one to decide whether a message was the product's at all. Both are
the add-on's now — which room is the product's, which conversation a message belongs to, whether
it names the role — and so is who its user is, answered through its own port
(`adapters/channel/base.py::PeopleOfAChannel`) and asked here, before anything is recorded, staged
or authorised. What an add-on hands `handle` is what the door's `Message` carries, in the core's
words: a person, a conversation key, a room, whether the role was mentioned or the conversation is
a direct one — and what counts as ADDRESSED TO THE ROLE is the core's to decide
(`product/addressing.py`, D14). The external chat add-on adapts to this outside the core
(`docs/writing-an-addon.md`, "A chat add-on and the product role").
"""

from __future__ import annotations

import logging

log = logging.getLogger("openfactory.product.channel")

# ── the CONFIRMATION EXECUTOR lives in `openfactory/product/confirm.py` (#105) ───────────────────
#
# The FUNCTIONS are bound here, unlike the mutable state below, and deliberately so: a test that
# monkeypatches `pc.answer_staged` is patching what `confirm_by_click` calls, which is the point.
# The typed yes reaches the executor through the ENGINE's own binding (`engine.confirm_staged`).
from openfactory.product.confirm import (  # noqa: E402,F401 — after the docstring; re-exported
    _is_requester,
    answer_staged,
    receipt,
)
from openfactory.product.confirm import confirm as confirm_staged  # noqa: E402,F401

# ── the staged proposal lives in `openfactory/product/staging.py` (#98 slice 3) ─────────────────
#
# RE-EXPORTED, NOT RE-IMPLEMENTED. `_PENDING` is bound BY IDENTITY here, never copied — but note
# that binding is NOT enough for a caller that REBINDS the name: eight test fixtures did exactly
# that (`monkeypatch.setattr(pc, "_PENDING", {})`) to isolate themselves, and after the move they
# must patch `openfactory.product.staging` instead, or they look like they isolate and do not.
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

#: THE MUTABLE STATE IS FORWARDED, NOT BOUND — and the difference is a defect the staging move
#: already produced once. `from … import _PENDING` copies the REFERENCE at import time, so the
#: moment anything rebinds the name on either side the two modules stop sharing: writes land in one
#: dict and reads come out of the other. Eight test fixtures rebind exactly this to isolate
#: themselves (`monkeypatch.setattr(staging, "_PENDING", {})`), so binding here would leave every
#: read on this module pointing at a dict nobody writes to — `KeyError` at best, and silently stale
#: at worst. PEP 562 module `__getattr__` resolves it on every access instead.
_FORWARDED = ("_PENDING", "_EXPIRED_TOMBSTONES")


def __getattr__(name: str):
    if name in _FORWARDED:
        from openfactory.product import staging

        return getattr(staging, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def handle(project, *, text: str, user: str, conversation: str, people, via: str,
           room: str = "", in_reply_to: str = "", message_id: str = "", mentioned: bool = False,
           direct: bool = False, source: str = "", fingerprint: str = "", notify=None,
           confirm=None) -> str | None:
    """One message from a chat add-on to the product role. Returns what to say, or None.

    THE CHAT ADAPTER AND NOTHING ELSE. The add-on says, in the core's words, what its vendor's
    event was: the `conversation` the message belongs to and the `room` that conversation lives
    in (its keys, its choice), the message it is `in_reply_to`, whether the role was `mentioned`
    (detected its own way) and whether this is a `direct` conversation with the role. `user` is
    its own user, turned into a person of the platform HERE, through the add-on's port (`people`,
    a `PeopleOfAChannel`): a user it cannot name is a guest who may write nothing. `via` is the
    add-on's own name, the provenance every gate behind the message records. The message then goes
    through THE ONE DOOR (`product/door.py`) onto its conversation's queue, like every other
    transport's, and the core decides whether it is addressed to the role (ADR-0051 D14): what is
    not is kept and searchable, starts no turn and is never put in a prompt — and this returns
    None for it.

    THE ACKNOWLEDGEMENT REACHES `notify` THE MOMENT THE DOOR HAS IT — before the slow part, which
    is where a receipt belongs. When the role is answering somebody else in this conversation, it
    is "I have your message; you are next", naming nobody. The turn itself runs on the worker, one
    at a time per conversation, and this waits — bounded — for the replies to THIS message.

    `message_id` is the add-on's own id for the message, so a retry of it is one message; one is
    minted when it has none. `fingerprint` is what a CLICK already verified, carried down to the
    pop (`consume`). Empty for a typed message, which has verified nothing yet — the engine is
    where that happens.

    Never raises: a chat caller runs this inside its listener, where an exception takes the channel
    down for everyone until someone notices."""
    from openfactory.product.door import say
    from openfactory.product.engine import Message
    from openfactory.product.speaker import of_channel

    speaker = of_channel(people, user, project=project, via=via)
    replies = say(project, Message(**({"id": str(message_id)} if message_id else {}),
                                   project=getattr(project, "name", "?"),
                                   conversation=str(conversation or ""), room=str(room or ""),
                                   speaker=speaker, text=str(text or ""),
                                   in_reply_to=str(in_reply_to or ""), source=str(source or ""),
                                   fingerprint=str(fingerprint or ""), via=str(via or ""),
                                   mentions_role=bool(mentioned), direct=bool(direct)),
                  notify=notify)
    return deliver(replies, confirm=confirm)


def deliver(replies, *, notify=None, confirm=None) -> str | None:
    """The engine's replies, rendered the way a chat surface renders them — what to say, or None.

    A RECEIPT GOES TO `notify` and is never returned: it is "we are on it", not the answer, and a
    notify that fails must never cost the answer that follows it.

    A REPLY WITH OPTIONS IS OFFERED TO `confirm` — the text, the proposal's token and the two
    labels — when the surface has buttons. `confirm` is None everywhere else (an activity, a test,
    the panel), so those get the proposal as prose by construction rather than by remembering to.
    When the buttons were POSTED the text is already on the channel, and returning it would show
    the person the same proposal twice — so None comes back. `None` already means "stay quiet", and
    the first interactive version returned it for "already posted" too: a queue proposal posted with
    buttons read as an intent that had FAILED, and the person got the buttons AND an unrelated
    conversational reply. That is why the posted text is not handed back to the engine to decide
    about: the engine never posts, and the one place that knows it did is this one."""
    said: str | None = None
    for reply in replies:
        if reply.kind == "receipt":
            if notify is None:
                continue
            try:
                notify(reply.text)
            except Exception:  # noqa: BLE001 — a receipt must never cost us the real answer
                log.warning("could not send the acknowledgement", exc_info=True)
            continue
        said = _offered(reply, confirm)
    return said


def _offered(reply, confirm) -> str | None:
    """One reply, as prose or as buttons — None when the buttons were posted."""
    options = reply.options
    if confirm is None or options is None:
        return reply.text
    # THE TYPED PATH IS ADVERTISED ALONGSIDE THE BUTTONS, and not as politeness. A click only
    # reaches the worker when the Slack app has Interactivity enabled — a setting this code cannot
    # check. With it off the button post still SUCCEEDS, so the prose fallback would not be sent and
    # the proposal would wait for a click that can never arrive. This line makes the confirmation
    # reachable either way, which beats a runbook step somebody has to remember.
    try:
        posted = confirm(f"{reply.text}\n\n{options.typed}",
                         options.token, options.approve, options.reject)
    except Exception:  # noqa: BLE001 — the affordance is optional; the proposal is not
        log.warning("could not offer an interactive confirmation", exc_info=True)
        return reply.text
    return None if posted else reply.text


def confirm_by_click(project, *, token: str, approved: bool, user: str, people, via: str,
                     module=None, notify=None) -> str | None:
    """A person pressed Approve or Reject on a chat add-on. Returns what to say, or None.

    THE POINT OF THE WHOLE BUTTON PATH: nothing here is interpreted. The click names the proposal,
    the add-on names the clicker — its own user, turned into a person of the platform through its
    port (`people`), exactly as a typed message's is (`handle`) — and the only judgment left is
    authorisation, which is a lookup of that person. The prose path (a word list, then a model
    reading the sentence) remains for people who type, and it is strictly the less certain of the
    two.

    `notify` is the same seam the typed path carries, and it is here because an approval is the
    slow path whichever way it arrives: without it a click could not even be acknowledged, so the
    one person who pressed the button got less than the one who typed "sim".
    """
    from openfactory.product.speaker import of_channel

    person = of_channel(people, user, project=project, via=via)
    _code, sentence = answer_staged(project, token=token, approved=approved, user=person,
                                    module=module, notify=notify, via=via)
    return sentence
