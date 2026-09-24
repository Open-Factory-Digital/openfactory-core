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
    preview_up          NOT WIRED HERE — the entry point is `preview_up`; the preview itself
                        (ADR-0050) is built on #265's branch, whose producer calls it
    document_ingested   NOT WIRED HERE — the entry point is `document_ingested`; documents are
                        read into the product's memory on #269's branch, whose producer calls it

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

#: The five kinds of event (#267 slice 3). A closed set: each has its sentence, its routing and
#: its record of having been said, and a kind nobody knows how to say is one nobody should tell.
DELIVERED, CI_RED, PR_WAITING, PREVIEW_UP, DOCUMENT_INGESTED = (
    "delivered", "ci_red", "pr_waiting", "preview_up", "document_ingested")
KINDS = (DELIVERED, CI_RED, PR_WAITING, PREVIEW_UP, DOCUMENT_INGESTED)

#: Which producer tells each kind on this branch — "" for a kind whose producer lives elsewhere.
#: The guard reads this, so a producer claimed here is a call that exists.
PRODUCERS = {
    DELIVERED: "openfactory/runtime/temporal/activities.py::record_outcome",
    CI_RED: "openfactory/runtime/temporal/activities.py::repair_ci",
    PR_WAITING: "openfactory/runtime/temporal/activities.py::techlead_watch",
    PREVIEW_UP: "",
    DOCUMENT_INGESTED: "",
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


def conversation_for(project, card: str = "", *, rows=None) -> str:
    """WHERE AN EVENT ABOUT `card` IS SAID: the conversation its requester asked in, as the card's
    open delivery loop recorded it when the work was filed — the newest, when two requests share
    a card — else the product's room, where it is said to nobody by name."""
    if card:
        if rows is None:
            from openfactory.memory import store as loop_store

            rows = loop_store.read(getattr(project, "name", "") or "")
        for loop in reversed(_deliveries_of(rows, card)):
            where = str((loop.context or {}).get("conversation") or "")
            if where:
                return where
    return room_of(project)


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

    THE ENTRY POINT, NOT WIRED ON THIS BRANCH: the preview is built on #265's stack, and its
    producer calls this when the preview answers."""
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

    THE ENTRY POINT, NOT WIRED ON THIS BRANCH: documents are ingested on #269's."""
    if not _speaks(project) or not str(name or "").strip():
        return False
    from openfactory.product import voice

    return _once(project, _event_id(DOCUMENT_INGESTED, project, key or name), lambda: (
        conversation or room_of(project),
        voice.document_ingested(name=name, language=_language(project),
                                agent_name=_agent(project))))


__all__ = ["CI_RED", "DELIVERED", "DOCUMENT_INGESTED", "KINDS", "PREVIEW_UP", "PRODUCERS",
           "PR_WAITING", "PR_WAIT_HOURS", "card_finished", "ci_went_red", "conversation_for",
           "deliver", "document_ingested", "issues_of", "preview_up", "pull_requests_at_the_gate",
           "room_of", "say_to", "to_room"]
