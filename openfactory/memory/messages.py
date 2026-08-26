"""What the factory said, and what it is waiting to hear back — for a deployment with no chat app.

WHY THIS EXISTS (C-25). Every message this platform produces went to one provider. A deployment
that does not buy Slack did not get a quieter factory, it got a SILENT one: the scheduled rounds,
the tech-lead's notices and the product role's questions were all written, all delivered to
`ChannelAdapter.say`, and there was exactly one adapter behind it. "Never a silent wait" was false
for anyone without a Slack workspace.

SAME SINK AS EVERYTHING ELSE, deliberately. A message store with its own infrastructure is another
thing to deploy, secure and forget to provision — and the failure mode of forgetting is a factory
that silently stops talking, which is precisely what this closes.

APPEND-ONLY, LIKE THE LEDGER. Answering a question writes a NEW row; `pending` folds them on read.
Nothing here updates anything, so the record of what was asked survives the answer — "who approved
that, and what were they shown" is a question with an answer here, which is the same property the
loop ledger is built on.
"""

from __future__ import annotations

import itertools
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime

log = logging.getLogger("openfactory.memory")

#: The telemetry `kind` these rows carry. Listed in `MetricKind` — an unlisted kind is written and
#: never read, which already cost the product sweep its memory once.
MESSAGE_KIND = "channel_message"

#: How many rows to consider. A panel showing the last few hundred messages is a panel somebody can
#: scroll; older than that belongs to the metrics view, not to an operator's inbox.
READ_LAST = 500

#: One number per write, process-wide, so two rows minted in the same microsecond can never
#: share a storage key (see `write`).
_SEQ = itertools.count()

#: What a row is. `say` is one-way; `ask` waits for somebody; `answer` closes an `ask`; `told` is
#: a person speaking to the factory of their own accord.
SAID = "said"
ASKED = "asked"
ANSWERED = "answered"
#: A PERSON'S OWN WORDS, unprompted — the half of the conversation that was never written down.
#:
#: The panel's tech-lead thread lived in a JavaScript array, so the operator's questions and the
#: tech-lead's answers existed only in the tab that produced them: a refresh lost the thread, a
#: second screen never had it, and a staged suggestion the platform had just asked somebody to
#: approve vanished with it (pilot, 2026-08-16 — *"ao dar F5 este diálogo some"*). Worse, the two
#: halves rendered in two blocks — everything the store knew, then everything the tab knew — so a
#: narration that arrived AFTER a typed question was drawn above it.
#:
#: `told` closes both: one append-only feed, one clock, and the same retention as everything else
#: the factory has said. It is NOT `answered`, which closes a specific `ask` by token; this is
#: somebody starting a conversation.
TOLD = "told"

#: Every kind a row may carry. The reader gates on this set, so a kind added above and left out
#: here would be written and never read back — which is exactly what `TOLD` did for the hour
#: between adding it and writing the guard.
KINDS = frozenset({SAID, ASKED, ANSWERED, TOLD})


@dataclass(frozen=True)
class Message:
    """One thing the factory said, or asked, or was told."""

    kind: str
    text: str
    ts: str
    #: Which conversation this belongs to. Free-form: a Slack channel id, a project name, "".
    channel: str = ""
    #: Identifies WHAT is being confirmed, and comes back with the answer, so the reader's click can
    #: be matched to the thing they were shown rather than to whatever is staged now.
    token: str = ""
    #: For `asked`: the two things a person may say. For `answered`: which one they said.
    approve: str = ""
    reject: str = ""
    answer: str = ""
    #: Who answered. "" for anything the factory said on its own.
    by: str = ""
    #: An opaque payload the ASKER wants back when the question resolves (C-33): the staged
    #: product proposal travels here, frozen, so the process that answers — the panel, a
    #: different service — can reconstruct exactly what was staged. The store never reads it.
    payload: str = ""


@dataclass
class Pending:
    """A question nobody has answered yet, with what the reader must be shown."""

    token: str
    text: str
    ts: str
    channel: str = ""
    approve: str = "Approve"
    reject: str = "Reject"
    payload: str = ""


def _row(message: Message) -> dict:
    """A message as the flat string map telemetry stores. Everything is a string so the row
    survives a schema change without a migration."""
    return {
        "msg_kind": message.kind,
        "text": message.text,
        "channel": message.channel,
        "token": message.token,
        "approve": message.approve,
        "reject": message.reject,
        "answer": message.answer,
        "by": message.by,
        "said_ts": message.ts,
        "payload": message.payload,
    }


def _message(extra: dict) -> Message | None:
    """One stored row back into a message, or None if it is not one. Never raises: a malformed row
    must cost that row, not the whole history."""
    try:
        kind = str(extra.get("msg_kind") or "")
        # EVERY KIND THIS MODULE CAN WRITE, derived from the module's own vocabulary rather than
        # re-listed here. `TOLD` was added and this literal was not, so a person's own turns were
        # written to the store and silently dropped on the way back out — written, tested, read by
        # nothing, which is this codebase's most expensive recurring shape. Caught by the guard for
        # the feature, not by review.
        if kind not in KINDS:
            return None
        return Message(
            kind=kind,
            text=str(extra.get("text") or ""),
            ts=str(extra.get("said_ts") or ""),
            channel=str(extra.get("channel") or ""),
            token=str(extra.get("token") or ""),
            approve=str(extra.get("approve") or ""),
            reject=str(extra.get("reject") or ""),
            answer=str(extra.get("answer") or ""),
            by=str(extra.get("by") or ""),
            payload=str(extra.get("payload") or ""),
        )
    except Exception as exc:  # noqa: BLE001 — one bad row must not cost the history
        log.warning("skipping an unreadable message row (%s)", exc)
        return None


def read(project: str, *, scan=None) -> list[Message]:
    """Every message row for a project, oldest first.

    RAISES `StoreUnreadable` when the store will not answer (#126). This function used to catch it
    and return `[]`, with a comment saying exactly why that was wrong — *"a panel with no messages
    and a panel that cannot read them look identical to an operator"* — and the guard was DEAD CODE
    anyway, because `query.records_of_kind` and `sqlite_metrics._query` had both already swallowed
    to `[]` one and two layers below. Nothing could ever reach the `except`.

    What that cost was both halves of every human gate at once: the pending questions vanished from
    the operator's inbox, and a click on one that was still there came back "already answered". The
    panel now answers 503 and says which — see `api/app.py`.

    A MALFORMED ROW STILL COSTS ONLY ITSELF. `_message` returns None for one it cannot parse and
    the thread survives; that is a different failure from the store being unreachable, and the two
    keep their different answers."""
    if scan is None:
        from openfactory.observability.query import records_of_kind

        rows = records_of_kind(project, MESSAGE_KIND, limit=READ_LAST)
    else:  # tests hand in their own rows
        rows = [r for r in scan()
                if r.get("kind") == MESSAGE_KIND
                and str(r.get("pk") or r.get("project") or "") == project]
        rows.sort(key=lambda r: str(r.get("ts") or ""))
        rows = rows[-READ_LAST:]
    out = [_message(r.get("extra") or {}) for r in rows]
    return [m for m in out if m is not None]


def write(project: str, messages: list[Message], *, sink=None, now: str | None = None) -> int:
    """Append rows. Returns how many landed.

    Never raises: a factory that cannot record what it said must still say it. But a failure is
    logged at error, because the symptom of a silent one is a panel that looks like a quiet
    factory."""
    if not messages:
        return 0
    try:
        from openfactory.observability.metrics import MetricRecord

        if sink is None:
            from openfactory.runtime.temporal.activities import _metrics_sink

            sink = _metrics_sink()
        stamp = now or datetime.now(UTC).isoformat()
        written = 0
        for message in messages:
            # COUNTED ONLY WHEN THE SINK SAYS SO (sweep B4, 2026-08-16). This loop incremented
            # unconditionally, so with the sink swallowing its own failures the function promised
            # "returns how many landed" and counted attempts: one hundred writes, ninety-nine
            # rows, one hundred successes reported to callers that gate the operator's own
            # conversation on the answer.
            landed = sink.record(MetricRecord(
                project=project,
                # The sequence disambiguates rows written in the same microsecond — it was the
                # batch INDEX, which restarts at 0 per call, so two single-message writes in one
                # microsecond minted the same key and `INSERT OR REPLACE` quietly kept one. The
                # counter is process-wide and the pid separates the panel's writes from the
                # worker's on the shared store.
                ticket=f"{message.token or '_msg_'}.{os.getpid()}.{next(_SEQ)}",
                ts=stamp,
                kind=MESSAGE_KIND,
                role=message.by or "_factory_",
                extra=_row(message),
            ))
            written += 1 if landed else 0
        return written
    except Exception as exc:  # noqa: BLE001
        log.error("COULD NOT RECORD %d message(s) for %s (%s) — they were produced and nobody "
                  "will see them", len(messages), project, exc)
        return 0


def say(project: str, text: str, *, channel: str = "", token: str = "", payload: str = "",
        sink=None, now: str | None = None) -> bool:
    """Record something the factory said. Returns whether it landed.

    `token` and `payload` are for something the factory said that a person may ACT on — today, the
    tech-lead's staged suggestion (see `staged`). A plain narration carries neither."""
    return write(project, [Message(kind=SAID, text=text, ts=now or _stamp(), channel=channel,
                                   token=token, payload=payload)],
                 sink=sink, now=now) == 1


def told(project: str, text: str, *, by: str = "", channel: str = "", sink=None,
         now: str | None = None) -> bool:
    """Record what a PERSON said to the factory. Returns whether it landed.

    Best-effort at every call site: losing the record of a question is bad, and refusing to answer
    it because the record failed would be worse."""
    return write(project, [Message(kind=TOLD, text=text, ts=now or _stamp(), channel=channel,
                                   by=by)],
                 sink=sink, now=now) == 1


def ask(project: str, text: str, *, token: str, approve: str, reject: str, channel: str = "",
        payload: str = "", sink=None, now: str | None = None) -> bool:
    """Record a question waiting on a person. Returns whether it landed.

    A question that could not be recorded must be reported as NOT asked: the caller's fallback is
    to say it some other way, and a False here is the only thing that triggers it."""
    return write(project, [Message(kind=ASKED, text=text, ts=now or _stamp(), channel=channel,
                                   token=token, approve=approve, reject=reject,
                                   payload=payload)],
                 sink=sink, now=now) == 1


def answer(project: str, *, token: str, answer: str, by: str = "", sink=None,
           now: str | None = None) -> bool:
    """Record a person's reply to a question. Returns whether it landed.

    THE TOKEN IS THE SUBJECT. It identifies what the person was SHOWN, so an answer cannot be
    applied to whatever happens to be staged when it arrives — the difference between approving a
    proposal and approving its replacement."""
    return write(project, [Message(kind=ANSWERED, text="", ts=now or _stamp(), token=token,
                                   answer=answer, by=by)], sink=sink, now=now) == 1


def pending(project: str, *, scan=None) -> list[Pending]:
    """Questions nobody has answered yet, oldest first — folded from the append-only rows.

    ONE QUESTION PER CONVERSATION KEY. A staged product proposal's token is `key|fingerprint`
    (C-33), and restaging the SAME conversation mints a new fingerprint — the store being
    append-only, the superseded ask would otherwise sit pending for ever next to its
    replacement. The latest ask per key wins; answering a superseded token is refused
    downstream as "replaced", which is the truthful reading. Plain tokens have no `|`, so their
    key is the whole token and the rule collapses to "latest ask for a token wins" — harmless."""
    history = read(project, scan=scan)
    answered = {m.token for m in history if m.kind == ANSWERED and m.token}
    latest_per_key: dict[str, Message] = {}
    for m in history:
        if m.kind == ASKED and m.token:
            latest_per_key[m.token.partition("|")[0]] = m
    keep = {m.token for m in latest_per_key.values()}
    return [Pending(token=m.token, text=m.text, ts=m.ts, channel=m.channel,
                    approve=m.approve or "Approve", reject=m.reject or "Reject",
                    payload=m.payload)
            for m in history
            if m.kind == ASKED and m.token in keep and m.token not in answered]


#: How long the tech-lead's staged suggestion stays clickable. Long enough to survive a refresh, a
#: second screen and stepping away from the desk; short enough that nobody presses a button whose
#: reasoning was about a floor that has since moved on.
#:
#: THE SAME BOUND SLACK ALREADY HAD, and the reason it had one: `runtime/slack/bot.py::_PENDING`
#: expires on read because a suggestion is advice about a state, and state ages. The panel is the
#: reference surface (ADR-0038) and had no bound at all — its suggestion lived in a JavaScript
#: array, which is the one retention nobody has to think about because it dies with the tab.
SUGGESTION_TTL_HOURS = 12

#: Token prefix for a staged suggestion, so a fold can tell one from the product gate's tokens
#: without parsing either. `tl:<verb>:<ref>:<stamp>`.
SUGGESTION_TOKEN = "tl:"


def suggestion_token(verb: str, ref: str, *, now: str | None = None) -> str:
    """The identity of one staged suggestion — WHAT was proposed, about WHICH ticket, and WHEN.

    The stamp is in it deliberately: two proposals of the same action on the same ticket are two
    decisions, and an approval must attach to the one the person was actually shown. This is the
    same rule `answer`'s docstring states, made addressable."""
    return f"{SUGGESTION_TOKEN}{verb}:{ref}:{now or _stamp()}"


def read_suggestion(message: Message) -> tuple[str, str, dict[str, str]] | None:
    """`(action, ref, params)` a said row is proposing, or None. Never raises — a payload we cannot
    read is a message without a button, not a broken thread.

    THE THIRD SLOT IS WHAT MAKES `adjust` PROPOSABLE (#170): a repair pass carries an instruction,
    and a proposal one verb and one ticket wide had nowhere to put it. Old rows deserialise into an
    empty mapping, so a proposal staged before this shipped still presses exactly as it did.

    STRINGS ONLY, AND SHALLOW. Whatever comes back is spread into `perform(**params)`, which
    type-checks it — but a nested structure arriving from a store is a shape nobody wrote a reader
    for, and this is the one place it could enter.
    """
    if not message.token.startswith(SUGGESTION_TOKEN) or not message.payload:
        return None
    try:
        import json

        body = json.loads(message.payload)
        got = body.get("suggestion")
        if isinstance(got, list) and len(got) == 2 and all(isinstance(x, str) for x in got):
            raw = body.get("params")
            params = ({k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}
                      if isinstance(raw, dict) else {})
            return got[0], got[1], params
    except Exception as exc:  # noqa: BLE001 — one unreadable payload is not the whole history
        log.warning("could not read a staged suggestion for %s (%s)", message.token, exc)
    return None


def staged(project: str, *, scan=None, now: str | None = None) -> tuple[Message, str] | None:
    """The suggestion a person may still act on, and WHY any other is retired — or None (#123).

    `(message, "")` when it is live; `(message, reason)` when the newest one exists but must not be
    pressed. The reason is returned rather than swallowed because of what this card is about: a
    staged suggestion that simply VANISHES on a refresh is a wait ending in nothing, and so is one
    that silently stops working. A person who sees "this expired" knows to ask again; a person who
    sees an empty answer concludes the platform forgot.

    THREE WAYS IT RETIRES, and each is a fold over the append-only rows — the same shape `pending`
    uses, for the same reason: nothing here updates anything, so the record of what was proposed
    survives its own retirement.

      superseded  a newer suggestion exists. Only the latest can be live; two live buttons in one
                  thread is somebody choosing between two pieces of advice, one of which was
                  written before the other and is therefore about a floor that changed.
      answered    somebody already pressed it. `answer` writes the row; a second click on a stale
                  page must not read as a second decision, which is the rule the product gate's
                  own route states in as many words.
      expired     older than `SUGGESTION_TTL_HOURS`.
    """
    from datetime import timedelta

    history = read(project, scan=scan)
    proposals = [m for m in history if m.kind == SAID and read_suggestion(m) is not None]
    if not proposals:
        return None
    latest = proposals[-1]
    if any(m.kind == ANSWERED and m.token == latest.token for m in history):
        return latest, "answered"
    try:
        when = datetime.fromisoformat(latest.ts)
        stamp = datetime.fromisoformat(now) if now else datetime.now(UTC)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        if stamp - when > timedelta(hours=SUGGESTION_TTL_HOURS):
            return latest, "expired"
    except (TypeError, ValueError) as exc:
        # A row whose timestamp will not parse cannot be aged, and a suggestion that can never
        # expire is worse than one that expires early — so it is retired rather than trusted.
        log.warning("a staged suggestion for %s has an unreadable timestamp %r (%s) — retiring it",
                    project, latest.ts, exc)
        return latest, "expired"
    return latest, ""


def answer_of(project: str, token: str, *, scan=None) -> Message | None:
    """The reply to one question, or None while nobody has given one.

    THE ASKER'S SIDE OF THE ROUND TRIP. A channel that can only be written to is a notification
    system; the thing that makes this a CHANNEL is that the caller can find out what was said
    back."""
    for m in reversed(read(project, scan=scan)):
        if m.kind == ANSWERED and m.token == token:
            return m
    return None


def _stamp() -> str:
    return datetime.now(UTC).isoformat()

