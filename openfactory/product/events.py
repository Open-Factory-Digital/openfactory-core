"""What happened, told to the conversation it concerns — the product role's events (#267 slice 3,
ADR-0052 "Events and the agenda").

THE ROLE HEARD OF A DELIVERY A WEEK LATE, AND SAID IT IN THE WRONG PLACE. The sentence the role is
named after — "what you asked for is ready" — came from `ProductSweepWorkflow`, every 168 hours,
posted to the project's one channel: a card delivered on Monday was announced when the sweep came
round, in a room the person who asked it may never read, and something asked in a private
conversation was answered in public. The role was pulled, not present.

NOW IT IS TOLD WHEN IT HAPPENS, BY WHAT MADE IT HAPPEN. Each kind has a producer in the factory,
which calls this module the moment it observes the thing; this module decides where it is said
and what is said, and hands it to the one door (`door.announce`), which records it and puts it in
line on that conversation — behind the turn in progress, never inside one.

    kind                producer on this branch
    ─────────────────   ──────────────────────────────────────────────────────────────────────
    delivered           `activities.record_outcome` — every job ends there; one that ended with
                        its card done asks whether that completed a delivery (`card_finished`)
                        — and the weekly sweep, which is now only the catch-all (`deliver`)
    ci_red              `activities.repair_ci` — the merge watch sends a pull request there
                        because a check that blocks it failed on the code, and the factory is
                        repairing it; said once per pull request, however many passes it takes
    pr_waiting          the tech-lead's hourly round (`activities.techlead_watch`) — a pull
                        request at the merge gate for 48 h (`pull_requests_at_the_gate`)
    preview_up          `activities.preview_up` — the preview's own step, the moment it is live
                        (`_the_preview_is_up`, #405); once per start
    ready_for_you       `activities.tell_the_requester` — the job's merge watch, the moment a
                        pull request a PERSON must decide enters it (#401); and the tech-lead's
                        round as the catch-all, which already lists every such gate
    document_ingested   `documents/ingest.py::announce` (#269) — a document read into the
                        product's memory, on the knowledge pipeline's tick or when somebody
                        brings it; an internal one is never said in a room (`_told_where`)
    card_moved          the card's door (`lifecycle/ports.py::tell`, ADR-0055) — a person
                        ended the work on a card (discarded, skipped, stopped: it is back in the
                        backlog), took it off the table (closed, withdrawn, removed: it will not
                        be built), or put it back (reopened); once per transition (#384, #412)
    merged              `activities.tell_the_requester_it_merged` — the job, the moment its pull
                        request merged, whoever merged it (#448 slice 3); not where the delivery
                        says it at that same moment
    staged              the tech-lead's hourly round (`activities._offer_the_release_to_the_client`)
                        — a job parked at the last gate before the product's users, ready for its
                        requester to try (#448 slice 4); once per card and run of its job, and
                        only after the room's own question landed

WHERE AN EVENT IS SAID (`conversation_for`). About a card: to the conversation its REQUESTER asked
in — recorded on the card's delivery loop when the work was filed, from what they had staged
(`module._open_delivery`, `confirm._whose`) — and to the product's room when nobody's is known
(`room_of`). A document: where it was brought, or the room. The sentence never names anybody
(`voice`), so the room hears "what was asked for in requirement 7 is ready" and not who asked it;
and nothing from one conversation is said in another — an event goes to exactly one.

WHAT IS SAID IS COMPOSED HERE, NEVER BY A MODEL. A delivery says what the sweep always said
(`followup.delivered_text` and the "did it work?" that opens the acceptance loop); the others have
their sentences in `voice`, in the client's words and the project's language. No model call is
spent on an event: its reaction is the sentence, the record it leaves in the conversation's memory
(so the next turn knows what it said), and the agenda it changes.

ONCE, AND NEVER TWICE. Every event has an id derived from WHAT happened, never a fresh one, so the
conversation drops a second telling of it (`ConversationWorkflow.admit`); and before telling, it is
checked against what was already said:

    a delivery      the ledger: an open delivery loop is announced, closed and followed by its
                    acceptance loop, under the product's lock, so the event and the catch-all
                    racing each other announce it once; a telling the door did not take leaves
                    it open for the next
    everything else this module's own record of what it told (`events.json` in the project's
                    memory directory, under its lock), written only after the door took it

ONLY THE FACTORY TELLS ONE. Nothing here is reachable from a transport: `receive` refuses an event
(`door.FORGED`), and the callers of this module and of `door.announce` are a closed list, held by a
guard (`tests/test_events_and_the_agenda.py`).
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime

log = logging.getLogger("openfactory.product.events")

#: The kinds of event (#267 slice 3; `ready_for_you` since #401; `card_moved` since #412, in place
#: of #384's `card_withdrawn`, which only the product role's own close could tell; `merged` since
#: #448; `staged` since #448 slice 4). A closed set: each has its sentence, its routing and its
#: record of having been said, and a kind nobody knows how to say is one nobody should tell.
DELIVERED, CI_RED, PR_WAITING, PREVIEW_UP, DOCUMENT_INGESTED, CARD_MOVED, READY_FOR_YOU = (
    "delivered", "ci_red", "pr_waiting", "preview_up", "document_ingested", "card_moved",
    "ready_for_you")
MERGED = "merged"
STAGED = "staged"
KINDS = (DELIVERED, CI_RED, PR_WAITING, PREVIEW_UP, DOCUMENT_INGESTED, CARD_MOVED,
         READY_FOR_YOU, MERGED, STAGED)

#: Which producer tells each kind on this branch — "" for a kind whose producer lives elsewhere.
#: The guard reads this, so a producer claimed here is a call that exists.
PRODUCERS = {
    DELIVERED: "openfactory/runtime/temporal/activities.py::record_outcome",
    CI_RED: "openfactory/runtime/temporal/activities.py::repair_ci",
    PR_WAITING: "openfactory/runtime/temporal/activities.py::techlead_watch",
    PREVIEW_UP: "openfactory/runtime/temporal/activities.py::preview_up",
    DOCUMENT_INGESTED: "openfactory/product/documents/ingest.py::announce",
    CARD_MOVED: "openfactory/lifecycle/ports.py::tell",
    READY_FOR_YOU: "openfactory/runtime/temporal/activities.py::tell_the_requester",
    MERGED: "openfactory/runtime/temporal/activities.py::tell_the_requester_it_merged",
    STAGED: "openfactory/runtime/temporal/activities.py::_offer_the_release_to_the_client",
}

#: Whose loops these are.
OWNER = "product"

#: How long a pull request waits on a person before the role says so (#267).
PR_WAIT_HOURS = 48.0

#: This module's record of what it told, beside the project's other memory.
_STORE = "events.json"
#: How many told ids, and how many sighted gates, the record keeps — far past any retry.
_KEEP = 512
#: How long a telling waits for another's to finish. A telling is a read, a signal and a write.
_WAIT_SECONDS = 30.0


# ── where ────────────────────────────────────────────────────────────────────────────────────────

def room_of(project) -> str:
    """The product's room: where its channel posts (`channel_destination`), the project's name on
    the panel. What an event about nobody's request is said to."""
    from openfactory.adapters.channel.registry import channel_destination

    return (channel_destination(project, product=True)
            or str(getattr(project, "name", "") or ""))


def issues_of(loop) -> set[str]:
    """The cards a delivery loop waits on, as the provider wrote them (C-05)."""
    from openfactory.contracts.refs import canonical_ref

    return {canonical_ref(n) for n in str((loop.context or {}).get("issues") or "").split(",")
            if n.strip()}


def _deliveries_of(rows, card: str) -> list:
    from openfactory.contracts.refs import canonical_ref
    from openfactory.memory.ledger import DELIVERY, waiting

    card = canonical_ref(card)
    return [x for x in waiting(rows, owner=OWNER) if x.kind == DELIVERY and card in issues_of(x)]


def _the_request(rows, card: str):
    """The open delivery of `card` that recorded where its requester asked — the newest, when two
    requests share a card — or None. The ONE reading of it, for where they asked
    (`requester_conversation`) and for who asked there (`requester_of`, #448 slice 4)."""
    for loop in reversed(_deliveries_of(rows, card)):
        if str((loop.context or {}).get("conversation") or ""):
            return loop
    return None


def requester_conversation(project, card: str, *, rows=None) -> str:
    """The conversation `card`'s requester asked in, as the card's open delivery loop recorded it
    when the work was filed — the newest, when two requests share a card — or "" when nobody's
    is known: a card filed by hand, by the sweep, or before conversations were recorded."""
    if not str(card or "").strip():
        return ""
    if rows is None:
        from openfactory.memory import store as loop_store

        rows = loop_store.read(getattr(project, "name", "") or "")
    asked = _the_request(rows, card)
    return str(asked.context.get("conversation") or "") if asked is not None else ""


def conversation_for(project, card: str = "", *, rows=None) -> str:
    """WHERE AN EVENT ABOUT `card` IS SAID: the conversation its requester asked in
    (`requester_conversation`), else the product's room, where it is said to nobody by name."""
    return requester_conversation(project, card, rows=rows) or room_of(project)


def _speaks(project) -> bool:
    """Whether this project has a product role to say anything — an event about a project with
    none is nobody's to tell."""
    cfg = getattr(project, "product", None)
    return cfg is not None and bool(getattr(cfg, "enabled", True))


# ── the one way out ──────────────────────────────────────────────────────────────────────────────

def _tell(project, *, id: str, conversation: str, text: str) -> bool:
    """THE ONE WAY A PROACTIVE MESSAGE LEAVES THE CORE (ADR-0051 D13): `door.announce` — recorded
    in the product's memory, then in line on its conversation. Returns whether the door took it;
    never raises. From synchronous code: every producer reaches it from a thread."""
    from openfactory.product import door

    try:
        return door.announce_now(project, id=id, conversation=conversation, text=text,
                                 room=conversation if conversation == room_of(project) else "")
    except Exception:  # noqa: BLE001 — the happening stands; only the telling failed
        log.exception("[%s] could not tell %s what happened",
                      getattr(project, "name", "?"), conversation)
        return False


def to_room(project, text: str) -> bool:
    """Something the role says to the product's room on its own — the sweep's report, a question
    about a card, a reminder: through the door like every proactive message, so it waits its turn
    in the room like one. Returns whether the door took it."""
    if not (text or "").strip():
        return False
    return _tell(project, id=f"room-{uuid.uuid4().hex}", conversation=room_of(project),
                 text=text)


def say_to(project, conversation: str, text: str) -> bool:
    """`to_room`, to the conversation a loop lives in — a reminder about something asked there."""
    if not (text or "").strip():
        return False
    return _tell(project, id=f"said-{uuid.uuid4().hex}", conversation=conversation or
                 room_of(project), text=text)


def _event_id(kind: str, project, *parts: str) -> str:
    """The id of a HAPPENING: the same thing told twice is one event (see the module)."""
    from openfactory.product.speaker import sealed

    name = getattr(project, "name", "") or ""
    return f"{kind}-{sealed('|'.join([name, *[str(p) for p in parts]]))}"


# ── the record of what was told ──────────────────────────────────────────────────────────────────

def _store_path(project):
    from openfactory.paths import project_memory_dir

    return project_memory_dir(project) / _STORE


@contextlib.contextmanager
def _held(project, *, required: bool):
    """This project's telling lock, held — `required=False` goes on without it when the memory
    directory cannot hold a lock at all (a delivery's own record, the ledger, still decides), and
    `required=True` does not (what is told once has no other record)."""
    from openfactory.util.filelock import lock_beside

    path = _store_path(project)
    lock = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = lock_beside(path)
        lock.acquire(timeout=_WAIT_SECONDS)
    except OSError as exc:
        if required:
            raise
        log.warning("[%s] could not take the telling lock (%s) — going on without it; the ledger "
                    "still says what was announced", getattr(project, "name", "?"), exc)
        lock = None
    try:
        yield path
    finally:
        if lock is not None:
            lock.release()


def _read(path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError) as exc:
        log.warning("could not read what was told from %s (%s)", path, exc)
        raw = {}
    return {"told": dict(raw.get("told") or {}), "seen": dict(raw.get("seen") or {})}


def _write(path, data: dict) -> None:
    from openfactory.util.filelock import replace_atomically

    for key in ("told", "seen"):
        kept = sorted(data[key].items(), key=lambda kv: kv[1])[-_KEEP:]
        data[key] = dict(kept)
    replace_atomically(path, json.dumps(data, sort_keys=True))


def forget_record(project) -> int:
    """This project's record of what was told, deleted — and how many entries it held (#453,
    `openfactory project forget`). Under the telling lock, so no telling lands in the middle;
    RAISES when the lock or the file will not be had, because a record that could not be deleted
    reported as an empty one is a role that goes on saying "I already noted this".

    Nothing in any process holds a copy: every telling reads the file afresh under the same lock
    (`_once`), so deleting it is the whole of forgetting it."""
    with _held(project, required=True) as path:
        if not path.is_file():
            return 0
        data = _read(path)
        path.unlink()
    held = len(data["told"]) + len(data["seen"])
    log.warning("OPENFACTORY_PRODUCT_EVENTS_FORGOTTEN project=%s entries=%d",
                getattr(project, "name", "?"), held)
    return held


def _once(project, event_id: str, compose) -> bool:
    """Tell what `compose()` says — `(conversation, text)` — unless `event_id` was told already.
    Composed only when it will be told, so a producer that fires on every round costs a read.
    Returns whether it was told now."""
    try:
        with _held(project, required=True) as path:
            data = _read(path)
            if event_id in data["told"]:
                return False
            conversation, text = compose()
            if not text or not _tell(project, id=event_id, conversation=conversation, text=text):
                return False
            data["told"][event_id] = time.time()
            _write(path, data)
            return True
    except (OSError, TimeoutError) as exc:
        # NOT TOLD RATHER THAN TOLD TWICE: with no record of what was said, every round of the
        # producer would say it again — the next round tries again once the record answers
        log.error("OPENFACTORY_PRODUCT_EVENT_UNRECORDED project=%s event=%s — what was told "
                  "cannot be recorded (%s), so it is not told", getattr(project, "name", "?"),
                  event_id, exc)
        return False


def _language(project):
    return getattr(project, "language", None)


def _agent(project) -> str:
    return getattr(getattr(project, "product", None), "agent_name", "") or ""


def _title_of(project, card: str) -> str:
    """The card's title, from the board as last read — best-effort: a card named by its number
    alone is a vaguer sentence, never a lost one."""
    try:
        from openfactory.contracts.refs import canonical_ref
        from openfactory.product.board import read_board

        tickets, error = read_board(project)
        if error:
            return ""
        want = canonical_ref(card)
        hit = next((t for t in tickets if canonical_ref(t.number) == want), None)
        return str(getattr(hit, "title", "") or "")
    except Exception:  # noqa: BLE001 — a title is a courtesy
        log.info("could not read #%s's title for an event", card, exc_info=True)
        return ""


# ── delivered ────────────────────────────────────────────────────────────────────────────────────

def _delivered_now(project) -> set[str] | None:
    """The cards the board says were delivered, read FRESH — the job that just finished moved
    one — or None when it could not be read (the catch-all reads it next time)."""
    from openfactory.product.module import ProductModule
    from openfactory.product.triage import delivered_numbers

    tickets, error = ProductModule(project)._read_board(fresh=True)
    if error:
        log.info("[%s] the board could not be read to see what was delivered (%s)",
                 getattr(project, "name", "?"), error)
        return None
    return delivered_numbers(list(tickets or []))


def card_finished(project, *, card: str) -> list:
    """A JOB ENDED WITH ITS CARD DONE (`activities.record_outcome`): every delivery that completes
    is announced NOW, to its requester's conversation. Returns the ledger rows it wrote.

    Cheap when there is nothing to say: the ledger is read first, and the board only when an open
    delivery waits on this card. A card that is done is not always delivered — a split card is
    closed and ships nothing itself — so the board decides (`triage.delivered_numbers`), not the
    job's word. Never raises."""
    if not _speaks(project) or not str(card or "").strip():
        return []
    try:
        from openfactory.memory import store as loop_store

        if not _deliveries_of(loop_store.read(getattr(project, "name", "") or ""), card):
            return []
        delivered = _delivered_now(project)
        if delivered is None:
            return []
        return deliver(project, delivered=delivered)
    except Exception:  # noqa: BLE001 — the job ended; the announcement is the catch-all's then
        log.exception("[%s] could not see what #%s delivered — the sweep announces it",
                      getattr(project, "name", "?"), card)
        return []


def deliver(project, *, delivered: set[str]) -> list:
    """ANNOUNCE EVERY OPEN DELIVERY WHOSE WORK IS ALL DELIVERED — the event's work, and the sweep's
    as the catch-all for whatever an event missed. Returns the rows written: each delivery closed,
    and the acceptance loop its announcement opened.

    TO ITS REQUESTER'S CONVERSATION, the one recorded on the loop (`conversation`), else the room.
    The sentence is the one the sweep said — the requirement's or the fix's — with the "did it
    work?" whose answer closes the acceptance loop (ADR-0025).

    UNDER THE TELLING LOCK, RE-READ INSIDE IT: whoever comes second finds the loop closed and says
    nothing. The loop closes only once the door TOOK the announcement — one it did not take stays
    open for the next telling (ADR-0021: closed on observation, never on self-report)."""
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import DELIVERY, close_by_observation, waiting
    from openfactory.product import followup

    if not _speaks(project) or not delivered:
        return []
    name = getattr(project, "name", "") or ""
    written: list = []
    try:
        with _held(project, required=False):
            open_now = waiting(loop_store.read(name), owner=OWNER)
            # ALL OF ITS WORK, NEVER SOME — the one rule for it (`followup.delivered`)
            due = followup.delivered(open_now, delivered)
            for loop in [x for x in open_now if (x.kind, x.subject, x.about) in due]:
                where = str((loop.context or {}).get("conversation") or "") or room_of(project)
                text = (followup.delivered_text(loop, agent_name=_agent(project),
                                                language=_language(project))
                        + followup.acceptance_question(loop, agent_name=_agent(project),
                                                       language=_language(project)))
                if not _tell(project, id=_event_id(DELIVERED, project, *loop.key),
                             conversation=where, text=text):
                    continue
                rows = close_by_observation([loop], {(DELIVERY, loop.subject, loop.about):
                                                     "delivered"})
                asked = followup.acceptance_of(
                    replace(loop, context={**(loop.context or {}), "channel": where}),
                    ts=datetime.now(UTC).isoformat())
                # THE ACCEPTANCE LIVES WHERE IT WAS ASKED: its conversation, and whom it is for
                # as the delivery recorded them — a digest (`agenda.audience`)
                whom = str((loop.context or {}).get("requester") or "")
                rows.append(replace(asked, context={
                    **(asked.context or {}), "conversation": where,
                    **({"requester": whom} if whom else {})}))
                loop_store.write(name, rows)
                written += rows
    except TimeoutError as exc:
        log.warning("[%s] another telling held the lock past %ss (%s) — the deliveries it did not "
                    "announce stay open for the next", name, _WAIT_SECONDS, exc)
    return written


# ── the others ───────────────────────────────────────────────────────────────────────────────────

def ci_went_red(project, *, card: str, pr_url: str = "") -> bool:
    """A CHECK THAT BLOCKS THE MERGE FAILED and the factory is repairing it (`repair_ci`) —
    said once per pull request to the card's requester, else the room. Not again on the next red
    of the same pull request: a repair that needs three passes is one thing that happened."""
    if not _speaks(project) or not str(card or "").strip():
        return False
    from openfactory.product import voice

    return _once(project, _event_id(CI_RED, project, card, pr_url), lambda: (
        conversation_for(project, card),
        voice.ci_went_red(ref=card, title=_title_of(project, card),
                          language=_language(project), agent_name=_agent(project))))


def pull_requests_at_the_gate(project, gates: list[tuple[str, str]], *,
                              now: float | None = None) -> list[str]:
    """THE TECH-LEAD'S ROUND SAW THESE (card, pull request) WAITING ON A PERSON at the merge gate.
    Returns the cards told, now, that theirs has waited `PR_WAIT_HOURS`.

    THE WAIT IS COUNTED FROM THE FIRST ROUND THAT SAW IT, recorded here: the gate carries no
    timestamp of its own, and the job's age counts the hours its agent worked as waiting. So the
    first telling is at most one round late, and never early. Told once per pull request."""
    if not _speaks(project) or not gates:
        return []
    now = time.time() if now is None else now
    waited: list[tuple[str, str, float]] = []
    try:
        with _held(project, required=True) as path:
            data = _read(path)
            for card, pr in gates:
                first = float(data["seen"].setdefault(f"{card}|{pr}", now))
                if now - first >= PR_WAIT_HOURS * 3600:
                    waited.append((card, pr, now - first))
            _write(path, data)
    except (OSError, TimeoutError) as exc:
        log.warning("[%s] could not record which pull requests wait on a person (%s)",
                    getattr(project, "name", "?"), exc)
        return []
    from openfactory.product import voice

    told = []
    for card, pr, seconds in waited:
        if _once(project, _event_id(PR_WAITING, project, card, pr), lambda c=card, s=seconds: (
                conversation_for(project, c),
                voice.pull_request_waiting(ref=c, title=_title_of(project, c),
                                           days=int(s // 86400), language=_language(project),
                                           agent_name=_agent(project)))):
            told.append(card)
    return told


def preview_up(project, *, card: str, url: str, key: str = "") -> bool:
    """A PREVIEW OF A CARD'S CHANGE CAME UP (ADR-0050): where to try it, to the card's requester,
    else the room — once per preview (`key`, the preview's own id; the address otherwise).

    Its producer is the preview's own `up` step (`activities._the_preview_is_up`, #405); `url` is
    the panel's route that opens it (`preview/live.py::route`), never the preview's keyed host."""
    if not _speaks(project) or not str(card or "").strip() or not str(url or "").strip():
        return False
    from openfactory.product import voice

    return _once(project, _event_id(PREVIEW_UP, project, card, key or url), lambda: (
        conversation_for(project, card),
        voice.preview_up(ref=card, title=_title_of(project, card), url=url,
                         language=_language(project), agent_name=_agent(project))))


def document_ingested(project, *, name: str, key: str = "", conversation: str = "") -> bool:
    """A NEW DOCUMENT WAS READ INTO THE PRODUCT'S MEMORY (#269): said to the conversation it was
    brought to — which its producer resolves for the person who brought it, as every row resolves
    a key (`catalog._conversation_key`) — else the room; once per document (`key`, its id).

    Its producer is `documents/ingest.py::announce`, which decides WHICH documents are told and
    never hands this an internal one for a room (#269)."""
    if not _speaks(project) or not str(name or "").strip():
        return False
    from openfactory.product import voice

    return _once(project, _event_id(DOCUMENT_INGESTED, project, key or name), lambda: (
        conversation or room_of(project),
        voice.document_ingested(name=name, language=_language(project),
                                agent_name=_agent(project))))


def card_moved(project, *, card: str, notice: str, event_id: str, title: str = "",
               removed: bool = False, conversation: str = "") -> str:
    """THE CARD'S DOOR MOVED IT (ADR-0055 D10) — said to the conversation its requester asked in,
    else the room, once per transition: `event_id` is the transition's own, so the door applying
    its effects again (a retry, the sweep) never says it twice.

    WHY THE CONVERSATION HEARS IT. The product role answers from what was said in it; a card that
    disappears from the board, or stops being worked on, with nothing said there is one the role
    goes on describing as coming (#384, #409). Its only producer is the door every person-made
    ending goes through — never a transport.

    `conversation` is where the requester asked, as the door read it BEFORE the transition's
    effects ran — a cancellation closes the delivery loop that records it.

    RETURNS THE DOOR'S OUTCOME, AND RAISES WHEN NOTHING WAS SAID: the card's record keeps what each
    effect came to, and a telling the conversation did not take is applied again by the sweep —
    which `_once` makes safe, and which "told already" ends."""
    if not _speaks(project) or not str(card or "").strip():
        return "nobody to tell"
    from openfactory.product import voice
    said = _event_id(CARD_MOVED, project, card, event_id)
    if _once(project, said, lambda: (conversation or conversation_for(project, card),
                                     voice.card_moved(notice, ref=card, title=title,
                                                      removed=removed,
                                                      language=_language(project),
                                                      agent_name=_agent(project)))):
        return "told"
    if said in _read(_store_path(project))["told"]:
        return "told already"
    raise RuntimeError("the conversation's door did not take it")


# ── ready for you ────────────────────────────────────────────────────────────────────────────────

def _card_url(project, card: str) -> str:
    """Where a person opens the card — ASKED of the tracker (`ticket_url`), never spelled here: on
    the local board it is the panel's card, where the preview and the approve/adjust buttons live.
    Best-effort: "" leaves the line out, and the sentence still names the card."""
    try:
        from openfactory.product.module import ProductModule

        return str(ProductModule(project)._tracker().ticket_url(str(card)) or "")
    except Exception:  # noqa: BLE001 — a link is a courtesy
        log.info("could not ask the tracker where #%s lives", card, exc_info=True)
        return ""


def _preview_starts_itself(project) -> bool:
    """Whether this deployment starts an offered preview on its own (#437) — the SAME two
    conditions `preview/live.py::should_start` refuses on first: the project's
    `preview.auto_start`, and a runtime named. Not the preview's record: at the moment this is
    said the start may or may not have written `starting` yet, and the sentence must not depend
    on which of the two got there first. False when unsure — "start it from the card" is then
    said, which the card can always honour."""
    try:
        from openfactory.contracts.project import PreviewPolicy
        from openfactory.runtime.temporal.io import default_preview_runtime

        policy = getattr(project, "preview", None) or PreviewPolicy()
        kind = default_preview_runtime()
        return bool(getattr(policy, "auto_start", True)) and bool(kind) and kind != "none"
    except Exception:  # noqa: BLE001 — the sentence falls back to "start it from the card"
        log.info("could not read whether previews start themselves here", exc_info=True)
        return False


def _preview_offered(project, card: str) -> bool:
    """Whether the card offers a preview a person can start — this deployment runs previews
    (`preview.domain()`) and the job wrote an offer for the card's unit that is not waiting on a
    shape to be declared. Best-effort, and False when unsure: "open the card and check the change"
    is always true, while "start the preview" on a card with no button is a broken promise."""
    try:
        from openfactory import preview

        if not preview.domain():
            return False
        name = getattr(project, "name", "") or ""
        # THE CARD AS THE PANEL ASKS FOR IT: its number, never a qualified `repo#N`
        found = preview.latest(name, preview.unit_of_card(name, str(card).rsplit("#", 1)[-1]))
        return found is not None and not found.shape
    except Exception:  # noqa: BLE001 — the sentence falls back to "check the change"
        log.info("could not read whether #%s offers a preview", card, exc_info=True)
        return False


def _stance(verdict) -> str:
    """What the automatic review said, as `verdict.headline`'s own word — "" when the verdict is
    not known here (None), which says nothing rather than "no review"."""
    if verdict is None:
        return ""
    from openfactory.review.verdict import headline

    return str(headline(verdict if isinstance(verdict, dict) else {}).get("stance") or "")


def ready_for_you(project, *, card: str, pr_url: str, verdict: dict | None = None,
                  preview_url: str = "") -> bool:
    """A CARD'S CHANGE WAITS ON A PERSON, AND THE PERSON WHO ASKED FOR IT HEARS IT (#401) — in the
    conversation they asked in, once per card and pull request. Returns whether it was told now.

    THE ROLE PROMISED "EU AVISO AQUI" AND SAID NOTHING WHILE THE CARD WAITED ON THAT PERSON. With a
    person deciding the merge, the requester's own look is the gate: the change is built, reviewed
    and one click from a preview. The card carried the factory's comment; the role, who had said
    it would tell them, was silent, and the person learned it was ready by opening the board. The
    two-day reminder (`pull_requests_at_the_gate`) is not this: it says the TEAM has not looked.

    ONLY WHERE SOMEBODY ASKED (`requester_conversation`): a card nobody asked for in a conversation
    is not the role's to announce, and the room already has the card's own comment — so nothing is
    said and nothing is recorded, and the ledger is the only read it costs.

    TWO PRODUCERS, ONE EVENT, like a delivery: the job's merge watch the moment it begins
    (`activities.tell_the_requester`, with the review's verdict), and the tech-lead's round, which
    sees every gate and not the verdict (`verdict=None`) — for a job whose history predates the
    watch's call, or one whose merge was handed to a person later. The id is the card and the
    pull request, so whichever comes second finds it told.

    `preview_url` IS THE SEAM FOR A PREVIEW THAT IS ALREADY UP: given one, the message carries the
    address instead of "start the preview from the card". A preview that comes up after this was
    said is `preview_up`'s to announce."""
    if not _speaks(project) or not str(card or "").strip() or not str(pr_url or "").strip():
        return False
    where = requester_conversation(project, card)
    if not where:
        return False
    from openfactory.product import voice

    return _once(project, _event_id(READY_FOR_YOU, project, card, pr_url), lambda: (
        where,
        voice.ready_for_you(ref=card, title=_title_of(project, card),
                            card_url=_card_url(project, card), review=_stance(verdict),
                            preview=not preview_url and _preview_offered(project, card),
                            preview_url=preview_url, language=_language(project),
                            agent_name=_agent(project),
                            preview_starts_itself=_preview_starts_itself(project))))


def ready_at_the_gate(project, gates: list[tuple[str, str]]) -> list[str]:
    """THE TECH-LEAD'S ROUND SAW THESE (card, pull request) WAITING ON A PERSON — the catch-all of
    `ready_for_you`: each is told on the first round that sees it, unless the watch already did.
    Returns the cards told now. Never raises."""
    told = []
    for card, pr in gates or []:
        try:
            from openfactory.preview.live import link_for

            if ready_for_you(project, card=card, pr_url=pr,
                             preview_url=link_for(project, card)):
                told.append(card)
        except Exception:  # noqa: BLE001 — one card's telling is not the round's price
            log.exception("[%s] could not tell #%s's requester it is ready for them",
                          getattr(project, "name", "?"), card)
    return told



# ── the change went in ───────────────────────────────────────────────────────────────────────────

def _accepted_where(project, card: str, pr_url: str) -> str:
    """The conversation the requester accepted this pull request in (`accept.standing`), or "" —
    the way to them when no delivery of the card names one: a card the role opened from a request
    opens no delivery loop. Best-effort: an unread store is a vaguer route, never a raise."""
    try:
        from openfactory.product.accept import standing

        acc = standing(getattr(project, "name", "") or "", card, pr_url)
        return acc.where if acc is not None else ""
    except Exception:  # noqa: BLE001 — the delivery's conversation is still asked first
        log.info("could not read #%s's acceptance to find its requester's conversation", card,
                 exc_info=True)
        return ""


def _the_delivery_says_it(project, card: str, rows) -> bool:
    """Whether a delivery of `card` completes with this merge, and so says "it is ready" at the
    job's end (`card_finished`, #267) — the requester then hears THAT, not a second message. The
    board as read now plus this card: the job has not moved it to Done yet, and an unreadable
    board counts this card alone, so a single-card delivery is never told twice."""
    from openfactory.contracts.refs import canonical_ref
    from openfactory.product import followup

    loops = _deliveries_of(rows, card)
    if not loops:
        return False
    return bool(followup.delivered(loops, (_delivered_now(project) or set())
                                   | {canonical_ref(card)}))


def merged_for_you(project, *, card: str, pr_url: str, stages_follow: bool = False) -> bool:
    """THE CHANGE A CARD'S REQUESTER ASKED FOR WENT IN, and they hear it (#448 slice 3) — in the
    conversation they asked in, once per card and pull request, WHOEVER MERGED IT: a person on the
    floor or the forge, the factory on its own, or the requester's acceptance when the look was all
    that held it. Returns whether it was told now. Never raises.

    MEASURED BEFORE IT WAS ADDED. With no stage declared, the job ends Done at the merge and
    `card_finished` announces every delivery that completes — "what you asked for is ready, did it
    work?" — to the same conversation, so this says nothing where that does (`_the_delivery_says_
    it`). Everywhere else the requester heard nothing at the merge: a project with stages announces
    its delivery only once the last one is through, a card of a requirement whose other cards are
    still open completes no delivery, and a card the role opened from a request opens none.

    ONLY WHERE SOMEBODY ASKED: the delivery's conversation, else the one the requester accepted it
    in. A card nobody asked for in a conversation is the room's card comment, as for
    `ready_for_you`."""
    if not _speaks(project) or not str(card or "").strip() or not str(pr_url or "").strip():
        return False
    try:
        from openfactory.memory import store as loop_store

        rows = loop_store.read(getattr(project, "name", "") or "")
        where = requester_conversation(project, card, rows=rows) or _accepted_where(
            project, card, pr_url)
        if not where:
            return False
        if not stages_follow and _the_delivery_says_it(project, card, rows):
            return False
    except Exception:  # noqa: BLE001 — the merge stands; only its telling is lost
        log.exception("[%s] could not tell #%s's requester it went in",
                      getattr(project, "name", "?"), card)
        return False
    from openfactory.product import voice

    return _once(project, _event_id(MERGED, project, card, pr_url), lambda: (
        where,
        voice.merged_for_you(ref=card, title=_title_of(project, card),
                             stages_follow=stages_follow, language=_language(project),
                             agent_name=_agent(project))))


# ── it is theirs to try before it reaches anyone ─────────────────────────────────────────────────

def requester_of(project, card: str, *, rows=None) -> tuple[str, str]:
    """`(conversation, person)` for `card`'s requester — where they asked, and a DIGEST of who
    (`speaker.sealed`) — or `("", "")` when nobody's conversation is known (#448 slice 4). Never
    raises.

    THE SAME TWO WAYS TO THEM AS `merged_for_you`, IN THE SAME ORDER: the newest delivery of the
    card that recorded a conversation (`requester_conversation`'s reading), with the person it
    sealed when the work was filed; else the conversation they accepted the change in
    (`accept.standing`, for any pull request of the card — at the last gate the change is merged,
    and which pull request carried it is not the question), whose person is sealed here. The
    person is only ever a digest: what reads it compares it (`agenda`), and nothing reads it back
    as a name."""
    try:
        if rows is None:
            from openfactory.memory import store as loop_store

            rows = loop_store.read(getattr(project, "name", "") or "")
        asked = _the_request(rows, card)
        if asked is not None:
            return (str(asked.context.get("conversation") or ""),
                    str(asked.context.get("requester") or ""))
        from openfactory.product.accept import standing
        from openfactory.product.speaker import sealed

        acc = standing(getattr(project, "name", "") or "", card)
        if acc is not None and acc.where:
            return acc.where, sealed(acc.by)
    except Exception:  # noqa: BLE001 — a vaguer route, never a raise: the room was asked anyway
        log.info("could not read who asked for #%s", card, exc_info=True)
    return "", ""


def staged_for_you(project, *, card: str, where: str = "", run: str = "") -> bool:
    """A CARD'S CHANGE IS READY FOR THE PERSON WHO ASKED FOR IT TO TRY, BEFORE IT REACHES ANYONE
    ELSE, and they hear it where they asked (#448 slice 4) — once per card and per run of its job.
    Returns whether it was told now. Never raises.

    THE ROOM WAS ASKED AND THE REQUESTER WAS NOT. A job parked at the last gate before the
    product's users (`release.parked_for_release`) was offered, hourly, to the product's ROOM and
    nowhere else (`followup.release_question`): the person whose request it was learned it was
    ready to try only if they happened to read the room, and their answer, given where they had
    asked, reached nothing. The room is still asked exactly as before; this is the requester's
    own telling, and the round opens a question of theirs beside the room's only when this says
    it was told (`activities._offer_the_release_to_the_client`).

    ONCE PER RUN, NOT ONCE PER CARD. `run` is the parked job's run: the round asks every hour,
    and the run is what keeps the second hour silent while a LATER run of the same card — the
    work done again, with something new to try — is told again. A job that could not say its
    run (`""`) is told once per card.

    ONLY WHERE SOMEBODY ASKED, AND NOT IN THE ROOM. A card nobody asked for in a conversation is
    the room's question alone; and a requester whose conversation IS the room already read the
    room's question there — the same news twice, in the same place, is noise."""
    if not _speaks(project) or not str(card or "").strip():
        return False
    to, _ = requester_of(project, card)
    if not to or to == room_of(project):
        return False
    from openfactory.product import voice

    return _once(project, _event_id(STAGED, project, card, run), lambda: (
        to,
        voice.staged_for_you(ref=card, title=_title_of(project, card), where=where,
                             language=_language(project), agent_name=_agent(project))))


__all__ = ["CARD_MOVED", "CI_RED", "DELIVERED", "DOCUMENT_INGESTED", "KINDS", "MERGED",
           "PREVIEW_UP", "PRODUCERS", "PR_WAITING", "PR_WAIT_HOURS", "READY_FOR_YOU", "STAGED",
           "card_finished", "card_moved", "ci_went_red", "conversation_for", "deliver",
           "document_ingested", "forget_record", "issues_of", "merged_for_you", "preview_up",
           "pull_requests_at_the_gate", "ready_at_the_gate", "ready_for_you",
           "requester_conversation", "requester_of", "room_of", "say_to", "staged_for_you",
           "to_room"]
