"""What was said — layer 0 and layer 1 of ADR-0024.

THE AGENT HAD NO WORKING MEMORY AT ALL. `product_channel` called `module.answer(text)` with one
argument, `ProductModule` was constructed fresh for every message, and `_PENDING` held a single
staged draft per thread. So every message was turn 1: the product role could not answer "e o
segundo?", did not know it had asked a question when the answer arrived, and could not take a
correction. That is not a degraded PO — it is a different thing wearing the name.

TWO LAYERS, ONE MODULE, AND THE DISTINCTION MATTERS:

  * `record()` writes the RAW LOG. Every message, verbatim, always, whether or not anything reads
    it. It is the substrate the other layers are derived from — change the summarisation strategy
    and you reprocess the log; keep only the distillate and the change is irreversible. It is also
    the only way to ever answer "why did she say that?".
  * `recent()` + `render()` build WORKING MEMORY for one thread: the last turns, verbatim, inside a
    token budget.

WHY THE THREAD AND NOT THE CHANNEL. Slack already draws the boundary a conversation has. A channel
is a room; a thread is an exchange. Keying on the room would mix two people's unrelated questions
into one history and make the agent answer the wrong one confidently.

WHY VERBATIM AND NOT SUMMARISED. The recent turns are exactly what the model needs word-for-word to
keep the thread of an argument. Summarising them is what makes an agent sound like a polite
amnesiac — it knows a conversation happened and cannot follow it.

WHY THIS TABLE. Same append-only telemetry table as everything else (ADR-0021's reasoning): a
transcript with its own infrastructure is a second thing to provision, secure and forget — and
forgetting looks exactly like an agent with nothing to remember.

RETENTION. These are real client conversations. Rows are partitioned by `project`, which is our
client boundary, so a deletion request is a bounded query rather than a hunt. Nothing here is
written outside that partition.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from openfactory.observability.metrics import ForgettingSink

log = logging.getLogger("openfactory.memory")

#: The telemetry `kind` these rows carry. Must be in `MetricKind` — an unlisted kind writes rows
#: that nothing queries, which already cost the product sweep its memory once.
TRANSCRIPT_KIND = "message"

#: How many characters of prior conversation to render. A budget in CHARACTERS, not messages,
#: because one message can be five characters or five thousand — counting messages budgets nothing.
#: ~6k chars ≈ 1.5k tokens: enough for a real exchange, small next to the repositories she reads.
DEFAULT_BUDGET = 6000

#: How many recent rows of this project to look through when rebuilding one thread. The GSI is
#: keyed by (project, kind#ts#…) so a thread's turns cannot be range-queried directly; they are
#: found by walking back through recent messages, which is cheap precisely because a live thread's
#: turns ARE recent. Revisit when one channel exceeds this in a day — see ADR-0024's threshold.
SCAN_ROWS = 300

#: How long a client's conversation is kept. Retention, not amnesia: long enough that the memory
#: is useful across months of a project, short enough to be a defensible answer to "how long do
#: you keep what I said?". Only these rows expire — the platform's operational memory carries no
#: TTL attribute at all and is never touched (see MetricRecord.expires_at).
RETENTION_DAYS = 180


@dataclass(frozen=True)
class Turn:
    """One thing somebody said. `role` is "person" or "agent" — not a Slack concept, because the
    prompt needs to know who is who and a user id does not say that."""

    role: str
    text: str
    ts: str = ""
    actor: str = ""


def record(project: str, *, thread: str, role: str, text: str, actor: str = "",
           channel: str = "") -> str:
    """Append one turn; returns the `ts` it was written under, or "" when nothing was.

    Best-effort and loud on failure, like every other write to this table: a transcript that
    quietly stops recording is indistinguishable from a quiet channel. The returned `ts` is what
    lets a handler that records the incoming message ON ARRIVAL exclude that same turn from the
    history it renders one moment later — without it, the current message shows up twice in the
    prompt (once as history, once as the question)."""
    text = (text or "").strip()
    if not text or not thread:
        return ""
    try:
        from openfactory.observability.metrics import MetricRecord
        from openfactory.runtime.temporal.activities import _metrics_sink

        now = datetime.now(UTC)
        ts = now.isoformat()
        _metrics_sink().record(MetricRecord(
            project=project,
            ticket=thread,
            ts=ts,
            kind=TRANSCRIPT_KIND,
            role=role,
            expires_at=int((now + timedelta(days=RETENTION_DAYS)).timestamp()),
            extra={"text": text[:8000], "actor": actor, "channel": channel},
        ))
        return ts
    except Exception as exc:  # noqa: BLE001 — never fail a reply because the log did
        log.warning("[%s] could not record a turn of thread %s (%s)", project, thread, exc)
        return ""


def recent(project: str, *, thread: str, channel: str = "",
           budget: int = DEFAULT_BUDGET) -> list[Turn]:
    """The prior turns of one conversation, oldest first, newest-biased within `budget` characters.

    A conversation is the THREAD plus, when `channel` is given, the channel's own rolling exchange
    (bare messages and the agent's proactive posts are keyed by the channel id — see
    `conversation_key`). The union is what makes a reply inside a fresh thread able to see the
    question the agent asked at channel level a minute earlier: without it, her own question is
    the one turn she cannot remember.

    Returns `[]` both when the conversation is new and when the store cannot be read — the two are
    indistinguishable to the caller ON PURPOSE, because the reply must go out either way. They are
    NOT indistinguishable in the log, which is where the difference is recoverable.
    """
    if not thread and not channel:
        return []
    try:
        from openfactory.observability.query import records_of_kind

        rows = records_of_kind(project, TRANSCRIPT_KIND, limit=SCAN_ROWS)
    except Exception as exc:  # noqa: BLE001
        log.warning("[%s] could not read the transcript of %s (%s)", project, thread, exc)
        return []

    keys = {k for k in (thread, channel) if k}
    mine = sorted((r for r in rows if str(r.get("ticket", "")) in keys),
                  key=lambda r: str(r.get("ts", "")))
    return _newest_within(
        [Turn(role=str(r.get("role", "")) or "person",
              text=str((r.get("extra") or {}).get("text", "")).strip(),
              ts=str(r.get("ts", "")), actor=str((r.get("extra") or {}).get("actor", "")))
         for r in mine],
        budget)


def _newest_within(turns: list[Turn], budget: int) -> list[Turn]:
    """The tail of a conversation that fits, oldest first.

    NEWEST FIRST WHILE TRIMMING: the opposite keeps the opening of a long conversation and drops
    what was just said, which is the half that carries the thread. Shared by both readers below,
    because two budget implementations is how one of them quietly stops bounding anything.
    """
    kept: list[Turn] = []
    spent = 0
    for turn in reversed(turns):
        if not turn.text:
            continue
        if spent + len(turn.text) > budget and kept:
            break
        spent += len(turn.text)
        kept.append(turn)
    return list(reversed(kept))


def of_messages(project: str, *, budget: int = DEFAULT_BUDGET, scan=None) -> list[Turn]:
    """The tech-lead's own thread, from the store the tech-lead actually writes to (#167).

    TWO STORES, AND THE FIRST WIRING READ THE WRONG ONE. `recent()` above reads the observability
    records the product channel writes; the tech-lead's turns go to `memory.messages` through
    `catalog._remember` — the same rows the panel paints. Reading the first for the second is why
    the live floor answered with an empty thread while sixty-four rows sat in the store, and no
    unit guard could see it: they stubbed the reader.

    `told` is a person, `said` is the factory. Anything else in that store — questions with
    tokens, recorded answers — is machinery, not conversation.
    """
    from openfactory.memory import messages

    # `scan` IS THE STORE'S OWN TEST SEAM, taken rather than invented: a reader with a private
    # way in is a reader whose guards can pass against a store nobody uses — which is exactly how
    # the first version of this shipped reading the wrong one.
    rows = [m for m in messages.read(project, scan=scan)
            if m.kind in (messages.TOLD, messages.SAID)]
    return _newest_within(
        [Turn(role="person" if m.kind == messages.TOLD else "agent",
              text=(m.text or "").strip(), ts=m.ts, actor="") for m in rows],
        budget)


def forget_project(project: str, *, table_name: str | None = None,
                   region: str | None = None) -> int:
    """Delete every recorded turn of one client. Returns how many rows went.

    THE RIGHT TO BE FORGOTTEN IS NOT A FEATURE, IT IS AN OBLIGATION, and it has to exist before
    the first client conversation rather than after the first request for one. The partition key
    IS the client (`pk=<project>`), which is what makes this a bounded delete rather than a hunt
    through a shared table.

    Only `kind="message"` rows go. The platform's operational memory for that project — what the
    tech-lead learned, what jobs ran — is a different thing from what a person said in a channel,
    and conflating them would either under-delete (a promise broken) or over-delete (an agent
    lobotomised by a privacy request).

    IT DELETES THROUGH THE SINK THAT RECORDED, and until recently it did not. Writing went through
    the configured sink; deleting reached for DynamoDB by hand — so a deployment running anything
    else (the OSS compose file says `OPENFACTORY_METRICS_SINK=sqlite` out loud) recorded a
    client's words
    and could not delete them. The obligation held on the vendor we happen to pay for, which is
    the core following our own deployment rather than the other way round.

    A SINK THAT CANNOT DELETE STILL RAISES, and must. Returning 0 for it would tell an operator
    answering a deletion request in good faith that it is done, about data that is still there.
    """
    sink = _sink_for(table_name=table_name, region=region)
    if not isinstance(sink, ForgettingSink):
        raise NotImplementedError(
            f"cannot forget {project!r}: this deployment's conversation store "
            f"({type(sink).__name__}) does not implement deletion. The turns WERE recorded "
            f"through the configured sink and are still there — nothing was deleted, and nothing "
            f"may be reported as deleted."
        )
    gone = sink.forget(project, kind=TRANSCRIPT_KIND)
    log.warning("FORGOT %s conversation rows for project %s (deletion request)", gone, project)
    return gone


def _sink_for(*, table_name: str | None = None, region: str | None = None):
    """The store this deployment records conversations in.

    `table_name`/`region` point the configured sink at a specific table — the two arguments this
    function has always taken, and how an operator aims the deletion. Without them the answer is
    whatever the deployment writes through, which is the whole point: the store that recorded is
    the store that must delete.
    """
    if table_name:
        # REGISTRY-SHAPED, like every other way of reaching a sink: the CONFIGURED kind, pointed
        # at the named table — the vendor's kind is not spelled here, and a deployment whose sink
        # cannot hold a table (or declares none) is refused by name rather than handed a class the
        # core no longer imports.
        from openfactory.observability.registry import configured_metrics_sink

        return configured_metrics_sink(table=table_name, region=region)
    from openfactory.runtime.temporal.activities import _metrics_sink

    return _metrics_sink()


def render(turns: list[Turn], *, agent_name: str = "", heading: str = "",
           you: str = "", somebody: str = "") -> str:
    """The prompt block, or "" when there is nothing to say.

    Deliberately plain text with no instructions in it: this is EVIDENCE of what was said, and a
    block that also tells the model what to do invites it to follow words a client typed. The
    surrounding prompt gives the orders; this gives the facts.

    THE LABELS ARE THE CALLER'S (#167). They were welded Portuguese, which is right for the
    product role talking to a pt-BR client and wrong for the tech-lead's prompt, whose whole
    surface is English by design. Defaults are English — the system's language — and the product
    channel passes its own.
    """
    if not turns:
        return ""
    me = agent_name or you or "you"
    other = somebody or "somebody"
    lines = [f"{me}: {t.text}" if t.role == "agent" else
             f"{t.actor or other}: {t.text}" for t in turns]
    return (heading or "## The conversation so far (oldest first)") + "\n" + "\n".join(lines)
