"""A project forgotten in one command — every layer the product role remembers (#453).

SEVEN LAYERS, AND ONE COMMAND COVERED ONE. `openfactory project forget-conversations` deleted the
transcript and what was derived from it; everything else the role remembers about a project lived
in other stores, each with its own API and none with a command. Measured on 2026-09-30: a
deployment's add-on grew a 120-line shell command to reach them all — a backup first, a refusal
while a model call ran, a restart at the end — which is the deployment doing what the core should
offer, and the next deployment writing it again. The layers are the core's; so is the command.

    layer            what it makes the role say           how it is forgotten here
    ───────────────  ───────────────────────────────────  ─────────────────────────────────────────
    conversations    "we discussed this yesterday"        `transcript.forget` (the product's, every
                                                          member's old rows with it), the index,
                                                          search record and recall indexes derived
                                                          from them, the files sent in them and
                                                          the names given to them
    engine           what was said, still in the run      the product's idle conversation runs and
                     that holds it                        the project's tech-lead run, closed, so
                                                          the engine's retention expires them
    loops            "I will tell you when it is fixed"   the store's `forget` of `agent_loop`
    records          old buttons, stale previews          the store's `forget` of `card_verdict`,
                                                          `preview`, `channel_message`,
                                                          `card_transition`
    intake           "I already noted this"               `case.forget_project`,
                                                          `events.forget_record`
    closed cards     "this was already reported as #N"    the row's own `remove_ticket`, each
    context          "requirement 66 covers this"         `authoring.forget_distillates`, only with
                                                          `--with-context`
    processes        anything from before, until restart  this process's copies; the others are
                                                          told by the stores they share, and to
                                                          restart

EACH THROUGH ITS OWN DOOR, NEVER AROUND IT. Every row above goes through the API its store already
deletes with — `ForgettingSink.forget`, which RAISES rather than answer 0 for a store that failed,
the tracker row's own removal, the case store's lock — so a layer this deployment cannot forget is
REFUSED BY NAME (a sink that does not delete, a hosted board with no removal of its own, a
partition another project also writes under), never reported as done.

NOTHING THAT IS NOT THE PROJECT'S. Every deletion is keyed by the project's own name or its
product's key, and by a closed list of kinds: the deployment's people (`person`, under a key of
the deployment's own), the cost rows, the rounds' marks and every other project's rows are not in
any list here. A test holds it with a second project's data, and the people, present.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("openfactory.product.forget")

CONVERSATIONS, ENGINE, LOOPS, RECORDS, INTAKE, CLOSED_CARDS, CONTEXT, PROCESSES = (
    "conversations", "engine", "loops", "records", "intake", "closed cards", "context",
    "processes")
#: Every layer, in the order it is forgotten — the conversations first, because a deletion request
#: is about them, and the runs that still hold them right after; the processes last, because what
#: they hold is told by the rest.
LAYERS = (CONVERSATIONS, ENGINE, LOOPS, RECORDS, INTAKE, CLOSED_CARDS, CONTEXT, PROCESSES)

#: The metrics-store kinds `records` forgets, each with what it is called when it is counted.
#: A CLOSED LIST, and the reason is the list of what is NOT in it: `person` (the deployment's
#: identity store), `agent_run` and `job` (what the work cost), `techlead_watch` and
#: `product_sweep` (what the rounds already reported — clearing them re-sends old notices).
RECORD_KINDS = {"card_verdict": "card verdicts", "preview": "preview records",
                "channel_message": "panel messages",
                # THE CARD'S DOOR KEEPS A RECORD OF EVERY TRANSITION (ADR-0055): who closed which
                # card and why. A forgotten project's cards are removed (`closed cards`), and the
                # record of their lives goes with them.
                "card_transition": "card transitions",
                # WHO SAID A CHANGE WAS RIGHT, AND ON WHICH HEAD (#448 slice 3, `accept.py`): a
                # person's name and the conversation they said it in, against a card of this
                # project. Its cards go, and so does what was said about them.
                "card_accepted": "acceptances",
                # WHO LET A CHANGE PREVIEW WITH ITS OWN SHAPE (#348, `preview/own.py`): a person's
                # name against a card of this project. It goes with the preview records it
                # belongs beside — kept, it would outlive the project it was given in.
                "preview_shape": "preview allowances"}

#: What is kept, said before anything is deleted.
KEPT = (
    "the project's registry entry, its box proof and its manifest",
    "the open cards, their numbers, and the code",
    "the requirements, decisions and facts in the context repository — the baseline's and the "
    "role's alike",
    "what the tech-lead's rounds and the product sweep already reported (clearing those re-sends "
    "old notices)",
    "what every agent run and job cost",
    "the deployment's people and their sessions, and every other project's rows",
    "the durable engine's history of each run this closes, until the engine's retention "
    "expires it — the run itself is closed, so that retention starts",
)

#: What a layer came to. `kept` is the operator's choice (a flag, or nothing there to forget);
#: `refused` is what this deployment cannot forget, by name; `failed` is a store that would not
#: answer; `restart` is a layer done here whose remainder lives in processes this one cannot reach.
FORGOTTEN, KEPT_BY_CHOICE, REFUSED, FAILED, RESTART = (
    "forgotten", "kept", "refused", "failed", "restart")
_MARK = {FORGOTTEN: "✓", KEPT_BY_CHOICE: "·", REFUSED: "✗", FAILED: "✗", RESTART: "!"}

#: Who a removal's audit line names, and why.
BY = "openfactory project forget"
REASON = "forgotten with the rest of what the product role remembers about the project"

#: What the worker and the panel still hold after this process dropped its own.
RESTART_SENTENCE = (
    "the worker and the panel still hold their own copies — staged proposals and held questions "
    "(for up to two hours), the intake cases they loaded, and on a hosted board its snapshot — "
    "until they restart: restart both (`docker compose restart worker panel`) before the next "
    "conversation. Until then the cases they hold cannot be written back: the case store carries "
    "when it was forgotten")


class Unforgettable(RuntimeError):
    """A layer this deployment cannot forget — its sentence names what and why."""


class CannotBackUp(RuntimeError):
    """The backup could not be taken; nothing was deleted."""


@dataclass
class Went:
    """What one layer came to: its state, what went (by name, with counts) and the sentence."""

    layer: str
    state: str
    counts: dict[str, int] = field(default_factory=dict)
    said: str = ""

    def line(self) -> str:
        counted = ", ".join(f"{n} {what}" for what, n in self.counts.items())
        body = "; ".join(part for part in (counted, self.said) if part)
        return f"{_MARK[self.state]} {self.layer}: {self.state}" + (f" — {body}" if body else "")


@dataclass(frozen=True)
class Target:
    """The project as every layer reads it: the registry project, its product's partition, and the
    registry projects of the same product (whose conversations are the same ones)."""

    project: object
    where: object
    members: tuple = ()

    @property
    def name(self) -> str:
        return str(getattr(self.project, "name", "") or "")

    @property
    def shared_with(self) -> list[str]:
        return [m for m in self.where.members if m != self.name]


def target(name: str, *, registry=None) -> Target:
    """The registered project `name`, with its product's partition and members. RAISES `KeyError`
    for a name this deployment does not drive."""
    from openfactory.memory import transcript
    from openfactory.registry import ProjectRegistry

    registry = registry or ProjectRegistry()
    project = registry.get(name)
    where = transcript.partition(project, registry=registry)
    members = []
    for member in where.members:
        try:
            members.append(registry.get(member))
        except KeyError:
            continue
    return Target(project=project, where=where, members=tuple(members))


# ── the store every metrics row is deleted through ───────────────────────────────────────────────

def _sink():
    """The deployment's metrics store, if it can delete — else `Unforgettable`, naming it."""
    from openfactory.observability.metrics import ForgettingSink
    from openfactory.observability.registry import deployment_metrics_sink

    sink = deployment_metrics_sink()
    if not isinstance(sink, ForgettingSink):
        raise Unforgettable(f"this deployment's metrics store ({type(sink).__name__}) does not "
                            f"implement deletion — its rows are still there")
    return sink


# ── the layers ───────────────────────────────────────────────────────────────────────────────────

def conversations(where, members=()) -> dict[str, int]:
    """THE CONVERSATIONS LAYER — `project forget` and `project forget-conversations` both delete
    through here, so the two can never come to forget different things.

    The rows of the product's partition and every member's old one (`transcript.forget`); and,
    for a product's partition, what was derived from them and what they carried: the index lines,
    the search record and every member's recall index (ADR-0053 D6), the files sent in them and
    the names people gave them — the four places `sessions.delete` already erases for ONE
    conversation (#335), for all of them. A partition named outright has no product of its own and
    nothing of that under one.

    RAISES `Unforgettable`, nothing deleted, for a partition somebody else also writes under and
    for a store that does not delete — `transcript.forget`'s two refusals, each in its own words.
    Anything else a store raises is raised as itself: a failure, never a refusal."""
    from openfactory.memory import transcript

    try:
        rows = transcript.forget(where)
    except (ValueError, NotImplementedError) as exc:
        raise Unforgettable(str(exc)) from exc
    counts = {"conversation rows": rows}
    if where.marked:
        from openfactory.product.attachments import forget_product
        from openfactory.product.index.retrieval import forget_conversations
        from openfactory.product.sessions import forget_names

        counts["index lines"] = forget_conversations(where.key, list(members))
        counts["files sent in them"] = forget_product(where.key)
        counts["people who named them"] = forget_names(where.key)
    return counts


def _conversations(t: Target, **_flags) -> Went:
    return Went(CONVERSATIONS, FORGOTTEN, conversations(t.where, t.members))


# ── the runs that still hold what was said ──────────────────────────────────────────────────────

#: Why a run this closes was ended, as the engine records it.
CLOSED_BECAUSE = "forgotten: what was said in it was deleted, and its history expires with the " \
                 "engine's retention"


@dataclass(frozen=True)
class Closed:
    """What closing a product's runs came to: the runs closed, the ones left open because a turn
    was at work in them, the engine's retention as it said it — and `unread`, why it could not."""

    runs: tuple[str, ...] = ()
    at_work: tuple[str, ...] = ()
    retention: str = ""
    unread: str = ""
    engine: bool = True

    def sentence(self) -> str:
        """`their history expires with the engine's retention (30 days)`, and what was left open."""
        kept = (f"their history expires with the engine's retention ({self.retention})"
                if self.retention else "their history expires with the engine's retention")
        if self.at_work:
            kept += (f"; {len(self.at_work)} left open, a turn at work in "
                     f"{'it' if len(self.at_work) == 1 else 'them'} — run this again once it ends")
        return kept


def coordinator_id(project: str) -> str:
    """The project's always-alive tech-lead run — the id `activities` signals it by."""
    return f"openfactory-coordinator-{project}"


async def _engine_client():
    """`(client, unread, declared)` — the engine as `in_flight` reaches it, for whoever must ask."""
    from openfactory.listeners import ENGINE as DECLARED
    from openfactory.util.causes import first_message

    # asked of the declaration itself (`connection.address()` asks the same), before any import
    # that needs the engine's library: an install without it still answers "none declared"
    if not DECLARED.declared():
        return None, "", False
    try:
        from openfactory.runtime.temporal import view as tv
    except ImportError as exc:
        from openfactory.runtime.host import why_the_engine_cannot_be_read

        return None, why_the_engine_cannot_be_read(exc), True
    try:
        return await tv.connect(), "", True
    except Exception as exc:  # noqa: BLE001 — said by the caller
        return None, f"the durable engine did not answer ({first_message(exc)})", True


async def _retention(client) -> str:
    """The namespace's retention, as a person reads it (`30 days`) — `""` where it cannot be read:
    the sentence then names the retention without its value rather than a guess at it."""
    try:
        from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest

        described = await client.workflow_service.describe_namespace(
            DescribeNamespaceRequest(namespace=client.namespace))
        seconds = int(described.config.workflow_execution_retention_ttl.seconds)
    except Exception as exc:  # noqa: BLE001 — the value is said when it can be, and only then
        log.info("could not read the engine's retention (%s) — the report names it without its "
                 "value", exc)
        return ""
    if not seconds:
        return ""
    if seconds % 86400 == 0:
        days = seconds // 86400
        return f"{days} day{'' if days == 1 else 's'}"
    return f"{seconds // 3600} hours"


async def close_runs(where, *, coordinator: str = "", client=None) -> Closed:
    """CLOSE THE RUNS THAT STILL HOLD WHAT WAS SAID (#533): the product's conversation runs that
    no turn is at work in, and — for `project forget` — the project's tech-lead run.

    WHY CLOSE, AND NOT CLEAR. A conversation's run ends only in `continue_as_new`, after
    `TURNS_PER_RUN` turns, and a forgotten conversation takes no more: the run holding its words —
    every message a signal in its event history, the display copies in `_heard`, the replies in
    `_outbox` — stayed open indefinitely, measured with 76 entries six days after a forget, and an
    open run's history is never reached by retention. Clearing its state by a signal would leave
    the signals that carried the words in that same open history. Terminated, the run is closed:
    the engine's retention then expires its history, and the next message starts a new run with
    nothing in it (`door.receive` starts on a signal).

    A RUN WITH A TURN AT WORK IS LEFT OPEN and said, never ended mid-turn: `in_flight` refuses
    `project forget` while one is, so here it is the race of a message that came in between.
    The tech-lead's run holds the project's parked decisions and its narration of the cards'
    moments, not a conversation; it is closed only when named, by `project forget`, which forgets
    those cards' records too. It restarts on the next decision, by the same signal-with-start."""
    from openfactory.product.key import product_slug
    from openfactory.util.causes import first_message

    if client is None:
        client, unread, declared = await _engine_client()
        if not declared:
            return Closed(engine=False)
        if client is None:
            return Closed(unread=unread)
    prefix = f"po-{product_slug(where.key)}-"
    closed: list[str] = []
    at_work: list[str] = []
    try:
        mine = [str(wf.id) async for wf in client.list_workflows(_CONVERSATIONS)
                if str(wf.id).startswith(prefix)]
        await close_idle(client, mine, closed=closed, at_work=at_work)
        if coordinator:
            async for wf in client.list_workflows(
                    f'WorkflowId = "{coordinator}" AND ExecutionStatus = "Running"'):
                await client.get_workflow_handle(str(wf.id)).terminate(reason=CLOSED_BECAUSE)
                closed.append(str(wf.id))
    except Exception as exc:  # noqa: BLE001 — said; what closed before stays closed
        return Closed(runs=tuple(closed), at_work=tuple(at_work),
                      unread=f"the engine could not close the runs ({first_message(exc)})")
    return Closed(runs=tuple(closed), at_work=tuple(at_work), retention=await _retention(client))


async def close_idle(client, wids, *, closed: list | None = None,
                     at_work: list | None = None) -> tuple[list[str], list[str]]:
    """Terminate each conversation run in `wids` that no turn is at work in — `(closed, at_work)`.
    Apart from `close_runs`'s listing, so the engine's own semantics — the run closed, the next
    message starting a new one — are proven against a real engine, whose test server lists
    nothing (`tests/test_a_forgotten_conversation_s_run_is_closed.py`)."""
    from openfactory.product import door

    closed = [] if closed is None else closed
    at_work = [] if at_work is None else at_work
    for wid in wids:
        try:
            seen = await door.watch(client, wid, 0)
        except door.NotStarted:
            continue
        presence = (seen or {}).get("presence") or {}
        if any(presence.get(k) for k in ("running", "working", "fast", "waiting")):
            at_work.append(wid)
            continue
        await client.get_workflow_handle(wid).terminate(reason=CLOSED_BECAUSE)
        closed.append(wid)
    return closed, at_work


def _in_a_thread(coro):
    """Run `coro` to its end from synchronous code — in this thread when no loop runs here, else
    in a thread of its own, so a caller already inside a loop is not refused by `asyncio.run`."""
    import asyncio
    import concurrent.futures

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def engine_went(closed: Closed) -> Went:
    """What closing the runs came to, as the report's `engine` line."""
    if not closed.engine:
        return Went(ENGINE, KEPT_BY_CHOICE,
                    said="no durable engine is declared here, so no conversation runs in one")
    conversations = sum(1 for r in closed.runs if r.startswith("po-"))
    counts = {"conversation runs closed": conversations}
    if len(closed.runs) > conversations:
        counts["tech-lead runs closed"] = len(closed.runs) - conversations
    if closed.unread:
        return Went(ENGINE, FAILED, counts,
                    said=f"{closed.unread} — run this again once the engine answers")
    if closed.at_work:
        return Went(ENGINE, FAILED, counts, said=closed.sentence())
    return Went(ENGINE, FORGOTTEN, counts, said=closed.sentence())


def _engine(t: Target, **_flags) -> Went:
    return engine_went(_in_a_thread(close_runs(t.where, coordinator=coordinator_id(t.name))))


def _loops(t: Target, **_flags) -> Went:
    from openfactory.memory.store import LEDGER_KIND

    return Went(LOOPS, FORGOTTEN, {"ledger rows": _sink().forget(t.name, kind=LEDGER_KIND)})


def _records(t: Target, **_flags) -> Went:
    sink = _sink()
    return Went(RECORDS, FORGOTTEN, {label: sink.forget(t.name, kind=kind)
                                     for kind, label in RECORD_KINDS.items()})


def _intake(t: Target, **_flags) -> Went:
    from openfactory.product import case, events

    return Went(INTAKE, FORGOTTEN, {"intake cases": case.forget_project(t.project),
                                    "events told": events.forget_record(t.project)})


class _Partly(RuntimeError):
    """Some of a layer went before one item would not — said with how many, so a partial removal
    is never read as none or as all."""

    def __init__(self, done: int, of: int, exc: BaseException) -> None:
        from openfactory.util.causes import first_message

        super().__init__(f"{done} of {of} went before one would not: {first_message(exc)}")


def _closed_cards(t: Target, *, keep_closed_cards: bool = False, **_flags) -> Went:
    """Every closed card, removed the way THIS board removes one — or refused by name on a board
    with no removal of its own (`tracker/base.py::removes`, the row's declaration, never its kind).
    """
    if keep_closed_cards:
        return Went(CLOSED_CARDS, KEPT_BY_CHOICE, said="kept, as asked (--keep-closed-cards)")
    from openfactory.adapters.tracker.base import removes
    from openfactory.adapters.tracker.registry import build_tracker, tracker_kind

    tracker = build_tracker(t.project)
    if not removes(tracker):
        return Went(CLOSED_CARDS, REFUSED,
                    said=f"the {tracker_kind(t.project) or '?'} board has no removal of its own, "
                         f"so its closed cards stay in that tracker's history — forget them on "
                         f"the tracker itself")
    closed = tracker.list_tickets(state="closed")
    if closed is None:
        raise RuntimeError("the board could not be read, so no closed card was removed")
    for done, card in enumerate(closed):
        try:
            tracker.remove_ticket(f"#{card.ref}", REASON, by=BY)
        except Exception as exc:
            raise _Partly(done, len(closed), exc) from exc
    from openfactory.product.board import forget_board

    forget_board(t.name)
    return Went(CLOSED_CARDS, FORGOTTEN, {"closed cards": len(closed)},
                said="each removal keeps its audit line (who, when, why, the title), as every "
                     "removal on this board does, and no number is handed out again")


def _context(t: Target, *, with_context: bool = False, **_flags) -> Went:
    link = getattr(t.project, "product", None)
    docs = str(getattr(link, "docs_repo", "") or "")
    if not docs:
        return Went(CONTEXT, KEPT_BY_CHOICE, said="the project has no context repository")
    if not with_context:
        return Went(CONTEXT, KEPT_BY_CHOICE,
                    said=f"{docs} as it is — --with-context removes the conversations' "
                         f"distillates from it")
    from openfactory.adapters.forge.registry import clone_url_for
    from openfactory.credentials import deployment_forge_token, forge_token_for
    from openfactory.product.authoring import forget_distillates

    token = forge_token_for(t.project) or deployment_forge_token(t.project) or None
    got = forget_distillates(docs_repo=docs, clone_url=clone_url_for(t.project, docs, token=token),
                             base=str(getattr(link, "docs_branch", "") or "main"))
    left = ""
    if got.requirements:
        left = (f"kept, written by the role from conversations: {', '.join(got.requirements)} "
                f"— a requirement is retired with a yes, not deleted: `openfactory act "
                f"product_drop -p {t.name} -P number=N -P yes=true` for each")
    if not got.ok:
        return Went(CONTEXT, FAILED, said="; ".join(p for p in (got.detail, left) if p))
    return Went(CONTEXT, FORGOTTEN, {"distillates": len(got.distillates)}, said=left)


def _processes(t: Target, **_flags) -> Went:
    """This process's own copies, dropped; the rest, said. The intake layer already dropped this
    process's cases and stamped the store the others read (`case.forget_project`)."""
    from openfactory.product.board import forget_board

    forget_board(t.name)
    return Went(PROCESSES, RESTART, said=RESTART_SENTENCE)


_RUN = {CONVERSATIONS: _conversations, ENGINE: _engine, LOOPS: _loops, RECORDS: _records,
        INTAKE: _intake, CLOSED_CARDS: _closed_cards, CONTEXT: _context, PROCESSES: _processes}


def forget(t: Target, *, with_context: bool = False,
           keep_closed_cards: bool = False) -> list[Went]:
    """Every layer, in order — each one's outcome, whatever the others came to.

    A LAYER THAT FAILS DOES NOT STOP THE REST, and it is never reported as forgotten: the layers
    are independent stores, and an operator answering a deletion request needs to hear, per layer,
    what went and what did not — "the loops failed" must not cost the conversations, and must not
    be hidden under them."""
    from openfactory.util.causes import first_message

    out: list[Went] = []
    for layer in LAYERS:
        try:
            out.append(_RUN[layer](t, with_context=with_context,
                                   keep_closed_cards=keep_closed_cards))
        except Unforgettable as exc:
            out.append(Went(layer, REFUSED, said=str(exc)))
        except Exception as exc:  # noqa: BLE001 — said per layer; never reported as forgotten
            log.error("OPENFACTORY_FORGET_LAYER_FAILED project=%s layer=%s (%s)", t.name, layer,
                      exc, exc_info=True)
            # EVERY DELETION HERE IS IDEMPOTENT, so the remedy is the same command: what went
            # before the failure is gone, and a second run deletes the rest
            out.append(Went(layer, FAILED,
                            said=f"{first_message(exc)} — nothing of it is reported forgotten; "
                                 f"run this again once the store answers"))
    log.warning("OPENFACTORY_PROJECT_FORGOTTEN project=%s %s", t.name,
                " ".join(f"{w.layer.replace(' ', '_')}={w.state}" for w in out))
    return out


# ── before: what will go, what runs, and the backup ─────────────────────────────────────────────

def plan(t: Target, *, with_context: bool = False, keep_closed_cards: bool = False) -> list[str]:
    """One line per layer — what it will forget — said before anything is asked or deleted."""
    shared = (f", shared with {', '.join(t.shared_with)} — one memory, so theirs go too "
              f"(each one's own loops, records, intake and cards are its own: forget it by its "
              f"name)" if t.shared_with else "")
    docs = str(getattr(getattr(t.project, "product", None), "docs_repo", "") or "")
    return [
        f"{CONVERSATIONS}: every recorded turn of the product's conversations{shared}; the index "
        f"lines, search record and recall indexes derived from them; the files sent in them and "
        f"the names people gave them",
        f"{ENGINE}: the product's conversation runs in the durable engine and the project's "
        f"tech-lead run, closed, so the engine's retention expires what they held — a run with "
        f"a turn at work is left open and said",
        f"{LOOPS}: the project's loop ledger — the product role's promises and waits, and every "
        f"other loop the same ledger holds",
        f"{RECORDS}: the card verdicts, the preview records (a preview still up runs to its own "
        f"expiry) and the panel's messages — the staged proposals' mirror, the tech-lead's "
        f"thread and the factory's notices",
        f"{INTAKE}: the intake cases and the record of what the role told",
        f"{CLOSED_CARDS}: " + ("kept (--keep-closed-cards)" if keep_closed_cards else
                               "every closed card on the board, removed — refused by name where "
                               "the board has no removal of its own"),
        f"{CONTEXT}: " + (f"the conversations' distillates in {docs}" if with_context and docs
                          else "kept" + (" (--with-context removes the conversations' "
                                         "distillates)" if docs else "")),
        f"{PROCESSES}: this process's copies; the worker and the panel restart after",
    ]


@dataclass(frozen=True)
class Flight:
    """What runs on the project now: its jobs, the product's conversations with a turn at work or
    a message waiting — and `unread`, why that could not be said, which refuses like a job."""

    jobs: tuple[str, ...] = ()
    turns: tuple[str, ...] = ()
    unread: str = ""
    engine: bool = True

    def refusal(self) -> str:
        if self.unread:
            return (f"cannot tell whether a job or a turn runs on the project — {self.unread}. "
                    f"Nothing was deleted; bring the engine up so this can look, then ask again")
        running = [*(f"job {j}" for j in self.jobs), *(f"a turn in {c}" for c in self.turns)]
        if running:
            return (f"{', '.join(running)} — running now, and it writes to the layers this "
                    f"deletes as it moves. Nothing was deleted; ask again once nothing runs")
        return ""


#: The two workflow types that write what this forgets while they run.
_JOBS = 'WorkflowType = "JobWorkflow" AND ExecutionStatus = "Running"'
_CONVERSATIONS = 'WorkflowType = "ConversationWorkflow" AND ExecutionStatus = "Running"'


async def in_flight(t: Target, *, client=None) -> Flight:
    """What runs on the project, asked of the durable engine — REFUSED BY THE CALLER while anything
    does, and while the engine that would say cannot be read (an unread list is not a drained
    floor, `cli._poller_reading`'s rule). A deployment that declares no engine runs nothing in one,
    and says so (`engine=False`).

    A JOB ALIVE AT A GATE COUNTS: when it moves it writes loops, events and records — the layers
    this deletes — so a forgetting under it is undone by its next step. A conversation counts when
    a turn is at work in it or a message waits for one (`ConversationWorkflow.watch`'s presence)."""
    from openfactory.util.causes import first_message

    if client is None:
        # NOBODY DECLARED AN ENGINE, so nothing runs in one; DECLARED AND NOT ASKABLE FROM HERE
        # is not "nothing runs" — the worker may well have the library this install lacks
        # (`_engine_client`, which `close_runs` reaches the engine through too)
        client, unread, declared = await _engine_client()
        if not declared:
            return Flight(engine=False)
        if client is None:
            return Flight(unread=unread)
    from openfactory.product import door
    from openfactory.product.key import product_slug

    try:  # a client handed in still needs the engine's library to read its ids
        from openfactory.runtime.temporal.view import parse_job_id
    except ImportError as exc:
        from openfactory.runtime.host import why_the_engine_cannot_be_read

        return Flight(unread=why_the_engine_cannot_be_read(exc))
    names = {t.name, *(str(getattr(m, "name", "") or "") for m in t.members)}
    prefix = f"po-{product_slug(t.where.key)}-"
    jobs: list[str] = []
    turns: list[str] = []
    try:
        async for wf in client.list_workflows(_JOBS):
            project, issue = parse_job_id(wf.id)
            if project in names:
                jobs.append(f"{project} #{issue}")
        async for wf in client.list_workflows(_CONVERSATIONS):
            if not str(wf.id).startswith(prefix):
                continue
            try:
                seen = await door.watch(client, wf.id, 0)
            except door.NotStarted:
                continue
            presence = (seen or {}).get("presence") or {}
            if any(presence.get(k) for k in ("running", "working", "fast", "waiting")):
                turns.append(str(wf.id))
    except Exception as exc:  # noqa: BLE001 — refused by the caller, said
        return Flight(unread=f"the engine could not say what runs ({first_message(exc)})")
    return Flight(jobs=tuple(jobs), turns=tuple(turns))


def backups_root() -> Path:
    """Where a forgetting's backup goes: beside the registry — the state volume the registry, the
    metrics store and the board share on a deployment (`/var/lib/openfactory` in compose)."""
    from openfactory.registry import ProjectRegistry

    return ProjectRegistry().path.parent / "backups"


def backup(t: Target, *, root: Path | None = None, now: datetime | None = None) -> Path:
    """Everything the layers delete that nothing else can rebuild, copied first — the metrics
    store and the board through SQLite's own backup, the memory directories and the product's files
    and names as they are — into one folder, returned. RAISES `CannotBackUp`, and nothing has
    been deleted when it does.

    WHAT IS NOT COPIED, AND WHY: the index, the search record and the recall indexes are derived
    from the store copied here (ADR-0053 D6 — the next turn rebuilds them), and the context
    repository's history is its own backup."""
    from openfactory.adapters import board_db
    from openfactory.adapters.tracker.registry import tracker_kind
    from openfactory.observability.metrics import NullMetricsSink
    from openfactory.observability.registry import deployment_metrics_sink
    from openfactory.paths import product_state_dir, project_memory_dir

    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", t.name).strip("._") or "project"
    folder = (root or backups_root()) / f"forget-{safe}-{stamp}"
    try:
        sink = deployment_metrics_sink()
        take = getattr(sink, "backup", None)
        if callable(take):
            take(folder / "metrics.db")
        elif not isinstance(sink, NullMetricsSink):
            raise CannotBackUp(
                f"this deployment's metrics store ({type(sink).__name__}) offers no backup the "
                f"core can take — take the store's own (a point-in-time copy), then run this "
                f"again with --no-backup. Nothing was deleted")
        if tracker_kind(t.project) == "local":
            # the file THIS project's board is in — a project may name its own (`board_db`)
            options = getattr(getattr(t.project, "tracker", None), "options", None) or {}
            board_db.backup(folder / "board.db", options.get("board_db") or None)
        for member in t.members:
            memory = Path(project_memory_dir(member))
            if memory.is_dir():
                shutil.copytree(memory, folder / "memory" / str(member.name))
        if t.where.marked:
            state = product_state_dir(t.where.key)
            for part in ("attachments", "sessions"):
                if (state / part).is_dir():
                    shutil.copytree(state / part, folder / part)
    except CannotBackUp:
        raise
    except Exception as exc:
        from openfactory.util.causes import first_message

        raise CannotBackUp(f"the backup into {folder} failed ({first_message(exc)}) — nothing "
                           f"was deleted") from exc
    return folder


__all__ = ["BY", "CLOSED_CARDS", "CONTEXT", "CONVERSATIONS", "FAILED", "FORGOTTEN", "INTAKE",
           "KEPT", "KEPT_BY_CHOICE", "LAYERS", "LOOPS", "PROCESSES", "REASON", "RECORDS",
           "RECORD_KINDS", "REFUSED", "RESTART", "CannotBackUp", "Flight", "Target",
           "Unforgettable", "Went", "backup", "backups_root", "conversations", "forget",
           "in_flight", "plan", "target"]
