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

RETENTION. These are real client conversations. Rows are partitioned by the PRODUCT, which is our
client boundary, so a deletion request is a bounded query rather than a hunt. Nothing here is
written outside that partition.

ONE MEMORY PER PRODUCT, NOT PER REGISTRY PROJECT (ADR-0051 D2, #266 slice 3). The partition was
the registry project until 2026-09-24, so two registry projects pointing at one context repository
— a product built from two repositories — had two memories of one conversation, and a person who
talked to the role from both pages was remembered by halves. Rows are now written under the
product's key (`product/key.py`), and each carries that key in its own `extra` as well: the mark is
what tells a row this code wrote from a row the registry-project partition held before, whatever
the partition's name, so a registry project an operator happened to name like a product key can
never leak its rows into that product's memory.

NO HISTORY IS LOST TO THE MOVE, AND NOTHING IS COPIED. The rows written before it stay where they
are, under each registry project's name, and every read of a product reads them through — the
product's own rows (marked) and each member registry project's old ones (unmarked), merged by
time. Nothing is migrated: a copy would be a second set of a client's words that retention and a
deletion both have to find. The read-through retires itself: `RETENTION_DAYS` after the move no
unmarked row is left to read, and reading the members' partitions can go.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
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


#: The key in a row's `extra` that marks it as written under a PRODUCT's partition, naming which.
PRODUCT_MARK = "product"

#: The key in a row's `extra` that marks it as NOT ADDRESSED TO THE ROLE (#266 slice 6, ADR-0051
#: D14): said in a group, to somebody else. Written only as `False`, so every row written before it
#: — and every row addressed to the role — reads as addressed.
ADDRESSED_MARK = "addressed"


@dataclass(frozen=True)
class Turn:
    """One thing somebody said. `role` is "person" or "agent" — not a Slack concept, because the
    prompt needs to know who is who and a user id does not say that.

    `id` is the message's own id and `in_reply_to` the one it answers (#266 slice 4, ADR-0051 D1,
    D13): a person's turn answers whatever they were replying to, and the role's turn answers the
    person's message — so in a room where several people write at once, a reply names the message
    it answers after it is recorded, not only on its way out. Empty for a turn recorded without
    one (the proactive posts, the rows written before).

    `addressed` is False for a line said in a group to somebody else, kept but never a turn
    (#266 slice 6, ADR-0051 D14) — it is read only by a caller that asks for it (`recent`)."""

    role: str
    text: str
    ts: str = ""
    actor: str = ""
    id: str = ""
    in_reply_to: str = ""
    addressed: bool = True


@dataclass(frozen=True)
class Partition:
    """Where one product's conversations are kept, and where its older rows still are.

    `key` is the partition every row is written under — the product's key, or, for a caller that
    names a partition outright (a test, an operator's tool), that name. `members` are the registry
    projects of the product: their own partitions held its rows before the move, and are read
    through and never written. `marked` says whether rows under `key` carry the product mark: a
    product's do, a partition named outright holds rows exactly as the old code wrote them.
    `shadowed` names the partitions somebody ELSE also writes under — a registry project outside
    the product NAMED like its key, or another product KEYED like one of its members' names. Reads
    are safe from it by the mark; a deletion by partition is not, and `forget` refuses it."""

    key: str
    members: tuple[str, ...] = field(default=())
    marked: bool = False
    shadowed: tuple[str, ...] = ()


def _key_of(project) -> str:
    """`product_key`, and a product of one for a stand-in without the registry's shape — as a
    project with no `product:` section is (`product_key`'s own rule)."""
    from openfactory.product.key import product_key

    try:
        return product_key(project)
    except AttributeError:
        return f"project:{getattr(project, 'name', '') or ''}"


def partition(project, *, registry=None) -> Partition:
    """The partition of the product `project` belongs to — its key, and every registry project of
    the same product whose old partition is read through.

    THE MEMBERS ARE READ FROM THE REGISTRY, because a project does not know its siblings: two
    registry projects are one product when they point at one context repository, and only the list
    of every project says which others do. A registry that cannot be read costs the siblings and
    never the project's own history — it is always a member of its own product."""
    name = str(getattr(project, "name", "") or "")
    key = _key_of(project)
    everyone: list = []
    try:
        if registry is None:
            from openfactory.registry import ProjectRegistry

            registry = ProjectRegistry()
        everyone = list(registry.list())
    except Exception as exc:  # noqa: BLE001 — the siblings are a read, the project's own is not
        log.warning("[%s] could not read the registry for the product's other projects (%s)",
                    name, exc)
    listed = [(str(getattr(p, "name", "") or ""), _key_of(p)) for p in everyone]
    members = [name] if name else []
    members += [n for n, k in listed if k == key and n and n not in members]
    shadowed = sorted({n for n, _k in listed if n == key and n not in members}
                      | {k for _n, k in listed if k != key and k in members})
    return Partition(key=key, members=tuple(members), marked=True, shadowed=tuple(shadowed))


def _where(project, *, members: bool = True) -> Partition:
    """What a caller handed: a `Partition` as it is, a string as a partition named outright, and a
    registry project as its product's partition — with its members read from the registry only
    when they are needed, which a write never does: a row is written under the product's key
    alone."""
    if isinstance(project, Partition):
        return project
    if isinstance(project, str):
        return Partition(key=project)
    if not members:
        return Partition(key=_key_of(project), marked=True)
    return partition(project)


def record(project, *, thread: str, role: str, text: str, actor: str = "",
           channel: str = "", message_id: str = "", in_reply_to: str = "",
           addressed: bool = True) -> str:
    """Append one turn; returns the `ts` it was written under, or "" when nothing was.

    `message_id` is the id of the message this turn is, `in_reply_to` the id of the one it answers
    (#266 slice 4) — kept on the row, so the record says which reply answers which message.

    `addressed=False` is a line said in a group to somebody else (#266 slice 6, ADR-0051 D14):
    kept like every other, marked (`ADDRESSED_MARK`), and left out of every read that builds a
    prompt.

    `project` is the registry project the turn was said on — recorded under its PRODUCT's
    partition, with the mark (see the module's docstring) — or a partition named outright.

    Best-effort and loud on failure, like every other write to this table: a transcript that
    quietly stops recording is indistinguishable from a quiet channel. The returned `ts` is what
    lets a handler that records the incoming message ON ARRIVAL exclude that same turn from the
    history it renders one moment later — without it, the current message shows up twice in the
    prompt (once as history, once as the question)."""
    text = (text or "").strip()
    if not text or not thread:
        return ""
    where = _where(project, members=False)
    try:
        from openfactory.observability.metrics import MetricRecord
        from openfactory.observability.registry import deployment_metrics_sink

        now = datetime.now(UTC)
        ts = now.isoformat()
        extra = {"text": text[:8000], "actor": actor, "channel": channel}
        if message_id:
            extra["id"] = str(message_id)
        if in_reply_to:
            extra["in_reply_to"] = str(in_reply_to)
        if not addressed:
            extra[ADDRESSED_MARK] = False
        if where.marked:
            extra[PRODUCT_MARK] = where.key
        deployment_metrics_sink().record(MetricRecord(
            project=where.key,
            ticket=thread,
            ts=ts,
            kind=TRANSCRIPT_KIND,
            role=role,
            expires_at=int((now + timedelta(days=RETENTION_DAYS)).timestamp()),
            extra=extra,
        ))
        return ts
    except Exception as exc:  # noqa: BLE001 — never fail a reply because the log did
        log.warning("[%s] could not record a turn of thread %s (%s)", where.key, thread, exc)
        return ""


def rows(project, *, limit: int = SCAN_ROWS) -> tuple[list[dict], bool]:
    """Every transcript row of a product, oldest first — its own and those its members' old
    partitions still hold — and whether any partition's window came back full.

    RAISES what the store raises; the readers below decide what an unreadable store costs them.
    ONE RULE FOR EVERY PARTITION READ: a row marked with THIS product's key is its own, wherever it
    sits; a row nobody marked is the product's only when it sits under one of its members' names,
    which is where the old code wrote it. A name that happens to equal a product key therefore
    cannot mix two clients' words in either direction (see the module's docstring). A partition
    named outright is read as it was always read — every row under it."""
    from openfactory.observability.query import records_of_kind

    where = _where(project)
    if not where.marked:
        got = records_of_kind(where.key, TRANSCRIPT_KIND, limit=limit)
        return list(got), len(got) >= limit
    merged: list[dict] = []
    full = False
    for name in dict.fromkeys((where.key, *where.members)):
        got = records_of_kind(name, TRANSCRIPT_KIND, limit=limit)
        full = full or len(got) >= limit
        for row in got:
            mark = (row.get("extra") or {}).get(PRODUCT_MARK)
            if mark == where.key or (not mark and name in where.members):
                merged.append(row)
    merged.sort(key=lambda r: str(r.get("ts", "")))
    return merged, full


def _addressed(row: dict) -> bool:
    """Whether a row was addressed to the role — every row but one marked otherwise."""
    return (row.get("extra") or {}).get(ADDRESSED_MARK) is not False


def recent(project, *, thread: str, channel: str = "",
           budget: int = DEFAULT_BUDGET, overheard: bool = False) -> list[Turn]:
    """The prior turns of one conversation, oldest first, newest-biased within `budget` characters.

    A conversation is the THREAD plus, when `channel` is given, the room's own rolling exchange
    (bare messages and the agent's proactive posts are keyed by the room — which is the chat
    add-on's to say, since #266 slice 6). The union is what makes a reply inside a fresh thread
    able to see the question the agent asked at room level a minute earlier: without it, her own
    question is the one turn she cannot remember.

    WHAT A GROUP SAID TO SOMEBODY ELSE IS LEFT OUT BY DEFAULT (#266 slice 6, ADR-0051 D14,
    decision 3): it is kept, and never added to a turn's prompt — and this is the read a prompt is
    built from, so the safe answer is the one a caller gets without asking. `overheard=True` is
    for a caller that SHOWS the conversation to the people in it (the panel's room, the thread
    row), who saw every line of it anyway.

    `project` is the registry project the conversation is held on, and what is read is its
    PRODUCT's memory — the rows of every registry project of that product, old and new; or a
    partition named outright.

    Returns `[]` both when the conversation is new and when the store cannot be read — the two are
    indistinguishable to the caller ON PURPOSE, because the reply must go out either way. They are
    NOT indistinguishable in the log, which is where the difference is recoverable.
    """
    if not thread and not channel:
        return []
    try:
        found, _full = rows(project, limit=SCAN_ROWS)
    except Exception as exc:  # noqa: BLE001
        log.warning("[%s] could not read the transcript of %s (%s)",
                    getattr(project, "name", project), thread, exc)
        return []

    keys = {k for k in (thread, channel) if k}
    mine = sorted((r for r in found if str(r.get("ticket", "")) in keys
                   and (overheard or _addressed(r))),
                  key=lambda r: str(r.get("ts", "")))
    return _newest_within(
        [Turn(role=str(r.get("role", "")) or "person",
              text=str((r.get("extra") or {}).get("text", "")).strip(),
              ts=str(r.get("ts", "")), actor=str((r.get("extra") or {}).get("actor", "")),
              id=str((r.get("extra") or {}).get("id", "") or ""),
              in_reply_to=str((r.get("extra") or {}).get("in_reply_to", "") or ""),
              addressed=_addressed(r))
         for r in mine],
        budget)


def took_part(project, *, conversation: str) -> bool:
    """Whether the role has SPOKEN in this conversation, as the product's memory holds it — the
    door's evidence, for a reply that nothing else made addressed to the role, that the role takes
    part in the conversation it replies in (#266 slice 6, ADR-0051 D14).

    A memory that cannot be read answers False, and says so in the log: the reply is then kept
    rather than turned, which costs the person a mention and never puts a stranger's words in a
    prompt."""
    if not conversation:
        return False
    try:
        found, _full = rows(project, limit=SCAN_ROWS)
    except Exception as exc:  # noqa: BLE001 — the door must answer; the reply is only kept
        log.warning("[%s] could not read whether the role spoke in %s (%s) — a reply there "
                    "without a mention is kept, not turned", getattr(project, "name", project),
                    conversation, exc)
        return False
    return any(str(r.get("ticket", "")) == conversation and str(r.get("role", "")) == "agent"
               for r in found)


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


def forget(project, *, table_name: str | None = None, region: str | None = None) -> int:
    """Delete every recorded turn of a PRODUCT: its own partition, and every member's old one.

    THE DELETION FOLLOWS THE KEY (ADR-0051 *Consequences*). Once memory is the product's, a
    request to forget one registry project's conversations is a request about the product's —
    every registry project of it shares them — and the rows written before the move are still
    under each member's name. A deletion that left those would report as done a request whose data
    is still there, so it deletes them too, one partition at a time through `forget_project`, and
    the count is the sum. The CLI names the members BEFORE it asks (`partition().members`).

    REFUSED, NOTHING DELETED, when somebody else writes under one of those partitions
    (`Partition.shadowed`): a deletion by partition cannot tell their rows from these, and a
    deletion request must never take another client's words with it."""
    where = _where(project)
    if where.shadowed:
        raise ValueError(
            f"cannot forget {where.key!r} by partition: {', '.join(where.shadowed)} "
            f"{'is' if len(where.shadowed) == 1 else 'are'} also written under by another "
            f"project or product, and a deletion here would take their conversations too. "
            f"Rename the registry project that collides, then ask again — nothing was deleted.")
    gone = 0
    for name in dict.fromkeys((where.key, *where.members)):
        gone += forget_project(name, table_name=table_name, region=region)
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
    from openfactory.observability.registry import deployment_metrics_sink

    return deployment_metrics_sink()


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
