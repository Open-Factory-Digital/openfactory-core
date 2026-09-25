"""One semaphore per product on what becomes work, and the write sequence that keeps it short
(ADR-0051 D7–D9, #266 slice 3).

WHAT IT GUARDS. Every act that creates or changes the product's record — a requirement minted,
committed and pushed; a decision, a fact, an acceptance or an abandonment committed to the context
repository; a card filed from the conversation; a draft staged for its yes. Conversations run in
parallel and nothing orders them; what they turn into work passes here, one at a time per product.
Without it two proposals minted one number (the second push was refused and landed on a `req/N-…`
branch under the same N), two saves to the context repository collided and the second person was
told the save failed, and two conversations that both found nothing both wrote the same card.

KEYED BY THE PRODUCT, never by a registry project (`product/key.py`): numbers and decisions are
written in the context repository, and two registry projects of one context repository under two
locks would mint into one corpus twice.

CHECK AND WRITE ARE ONE STEP, WITHOUT A MODEL IN THE LOCK (D7, D8). The judgement "is this the same
as something that exists?" is a model call and happens BEFORE the lock, in the turn. What makes it
still true at the write is the product's WRITE SEQUENCE: every write and every staging bumps it,
and a turn notes the sequence before it searches. Inside the lock the sequence is compared:

    unchanged   nothing arrived since the check — mint, commit, push, bump
    moved       only what arrived after the noted sequence matters; of that, only what was SAVED
                can stop a write (D9). The same text — a deterministic check — stops it here. What
                is merely close is judged by the model AFTER the lock is released, and the turn
                comes back with the new sequence; a bounded number of rounds, and when they run
                out nothing is written unchecked — the person is told, and asks again.

WHY A FILE LOCK (`util/filelock.py`). The deployment's durable stores are the telemetry sink
(SQLite on one machine, DynamoDB on AWS), the registry file and the per-project JSON under the
journal root; the only Postgres in a deployment is Temporal's own database, which belongs to the
engine — its credentials, its schema, and none at all on Temporal Cloud. A lock taken there would
tie the product's record to the engine's storage. What every writer of a product DOES share is
the journal root (`paths.product_state_dir`): compose mounts it into the worker and the panel, and
the panel performs a confirmation in its own process. `flock` on a file there holds across the
worker's eight concurrent activities and across processes and containers on one host, and the
kernel releases it when a holder dies mid-write — so a dead holder leaves nothing to clear, and
its clone, pushed or not, is simply gone. Across HOSTS it holds nothing; a deployment of several
workers on several machines needs this seam moved to a store they all reach.

THE HOLD IS SECONDS: a file read, a comparison, and the write — most of it the push. It has a
timeout (`TIMEOUT_SECONDS`), and running out of it fails loudly: `Busy`, an ERROR line naming the
product, and a sentence the person reads (`voice.semaphore_busy`). A model call made while it is
held is refused outright (`held_here`, asked by `ProductRole._ask`): a turn that thinks inside the
lock holds every other write of the product for the length of a model call.

NOBODY IS NAMED, AND NOBODY CAN BE (D9). The write log keeps what was saved or staged — its kind,
its title, its number — and never a person: no requester field exists to leak. The conversation an
item came from is kept only as a digest, so it can be told apart from the asker's own and never
read back. What is found in another conversation is said by what it is — "this has just been asked
for; it is requirement 41", "someone asked for something close to this a few minutes ago".
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import threading
import time
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass

from openfactory.util.filelock import FileLock, Waited, replace_atomically

log = logging.getLogger("openfactory.product.semaphore")

#: How long a write waits for its turn before it is refused, out loud. A hold is a comparison and
#: a push; forty-five seconds is several of those queued, and still well inside a turn's bound.
TIMEOUT_SECONDS = 45.0
#: How long STAGING waits. A draft is nobody's yet and its confirmation re-checks everything, so a
#: staging that cannot have the lock in a moment stages anyway and only loses the anonymous notice.
STAGING_TIMEOUT_SECONDS = 5.0
#: The write log's own lock: held for a read and a replace of one small file, never for a push.
LOG_TIMEOUT_SECONDS = 10.0
#: How many times a write goes back to judge what arrived while it waited, before it gives up
#: rather than write unchecked. Each round is a model call at most, and only over saved items.
ROUNDS = 3
#: How long the log remembers an item. A staged draft is confirmable for two hours
#: (`staging.PROPOSAL_TTL_SECONDS`), so a confirmation needs what arrived during those two hours;
#: a day is that with room to spare, and `MAX_ITEMS` bounds a burst.
RETAIN_SECONDS = 24 * 60 * 60
MAX_ITEMS = 2000

STAGED = "staged"
SAVED = "saved"

#: The kinds a staged twin is looked for among: what becomes NEW work. An acceptance, a close or a
#: reorder acts on something that already exists, and two of them are not two requests.
NEW_WORK = frozenset({"draft", "requirement", "ticket", "defect", "fact"})

WORK_FILE = "work.json"


class Busy(RuntimeError):
    """The semaphore was not had within the timeout. `sentence` is what a person is told."""

    def __init__(self, key: str, waited: float, *, language: str | None = None) -> None:
        from openfactory.product.voice import semaphore_busy

        self.key = key
        self.waited = waited
        self.sentence = semaphore_busy(language=language)
        super().__init__(f"{self.sentence} (the product's semaphore was held by another write "
                         f"for the whole {waited:.1f}s this one waited)")


class ModelUnderSemaphore(RuntimeError):
    """A model was asked while this thread held a product's semaphore — refused (D8)."""


def product_of(project) -> str:
    """The product `project` belongs to (`product/key.py`). A stand-in with no `product` section
    at all is a product of one — what a registry project with no link is."""
    from openfactory.product.key import product_key

    try:
        return product_key(project)
    except AttributeError:
        return f"project:{getattr(project, 'name', '') or ''}"


def _dir(key: str):
    from openfactory.paths import product_state_dir

    return product_state_dir(key)


# ── the semaphore ────────────────────────────────────────────────────────────────────────────────

_mine = threading.local()


def _held_keys() -> list[str]:
    keys = getattr(_mine, "keys", None)
    if keys is None:
        keys = _mine.keys = []
    return keys


@contextlib.contextmanager
def held(project, *, timeout: float | None = None):
    """The product's semaphore, for the length of the block — or `Busy`, said out loud.

    Released on every way out of the block, an exception included. Re-entrant for the thread that
    holds it."""
    key = product_of(project)
    lock = FileLock(_dir(key) / "semaphore.lock")
    wait = TIMEOUT_SECONDS if timeout is None else timeout
    try:
        lock.acquire(timeout=wait)
    except Waited as exc:
        log.error("OPENFACTORY_PRODUCT_SEMAPHORE_TIMEOUT product=%s waited=%.1fs — another write "
                  "of this product held it the whole time; nothing was written, and the person "
                  "was told to ask again", key, exc.waited)
        raise Busy(key, exc.waited, language=getattr(project, "language", None)) from exc
    keys = _held_keys()
    keys.append(key)
    try:
        yield key
    finally:
        keys.remove(key)
        lock.release()


def held_here(project=None) -> bool:
    """Whether the CALLING thread holds a product's semaphore — this project's product, or any."""
    keys = _held_keys()
    return bool(keys) if project is None else product_of(project) in keys


def refuse_a_model_here(phase: str) -> None:
    """Raise when a model is about to be asked under a product's semaphore. The one guard every
    model call of the product role passes (`ProductRole._ask`)."""
    keys = _held_keys()
    if keys:
        log.error("OPENFACTORY_PRODUCT_MODEL_UNDER_SEMAPHORE phase=%s product=%s — a model was "
                  "asked while the semaphore on what becomes work was held; refused", phase,
                  keys[-1])
        raise ModelUnderSemaphore(
            f"the {phase} model call was asked while {keys[-1]}'s semaphore was held — the lock "
            f"is for a comparison and a write, never for a model (ADR-0051 D8)")


# ── the write log: the sequence, and what moved it ───────────────────────────────────────────────

@dataclass(frozen=True)
class Item:
    """One thing that moved the write sequence. No person in it, by construction."""

    seq: int
    state: str          # STAGED | SAVED
    kind: str           # requirement | ticket | defect | decision | fact | acceptance | draft…
    text: str           # what it is: a title, a term, a decision's sentence
    ref: str = ""       # how it is cited: REQ-0041, the card's ref
    url: str = ""       # where the card is, for a person to follow
    where: str = ""     # a DIGEST of the conversation it came from — compared, never read back
    token: str = ""     # a DIGEST of a staged proposal's token, so its answer closes it
    ts: float = 0.0


def _where(conversation: str) -> str:
    """The conversation, as something that can be compared and never read: a private key names
    its person (`person:<id>`), and this log is every registry project's of the product."""
    conversation = str(conversation or "")
    return hashlib.sha256(conversation.encode()).hexdigest()[:16] if conversation else ""


def _sealed(token: str) -> str:
    """A proposal token (`<conversation>|<fingerprint>`), digested for the reason `_where` is."""
    token = str(token or "")
    return hashlib.sha256(token.encode()).hexdigest()[:16] if token else ""


def _empty(key: str) -> dict:
    return {"version": 1, "product": key, "seq": 0, "floor": 0, "items": [], "closed": []}


def _load(key: str) -> dict:
    """The product's write log. Missing is a log nothing has moved yet; unreadable is said, and
    read as empty — `since` then treats every sequence noted against the lost one as incomplete."""
    path = _dir(key) / WORK_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty(key)
    except (OSError, ValueError) as exc:
        log.error("OPENFACTORY_PRODUCT_WORK_LOG_UNREADABLE product=%s (%s) — read as empty; a "
                  "write whose check predates this re-checks everything the log still holds",
                  key, exc)
        return _empty(key)
    if not isinstance(data, dict) or not isinstance(data.get("seq"), int):
        log.error("OPENFACTORY_PRODUCT_WORK_LOG_UNREADABLE product=%s — not a write log; read as "
                  "empty", key)
        return _empty(key)
    return data


def _items(data: dict) -> list[Item]:
    out: list[Item] = []
    for raw in data.get("items") or []:
        try:
            out.append(Item(**raw))
        except TypeError:
            log.warning("a write-log item of another shape was skipped: %r", raw)
    return out


def sequence(project) -> int:
    """The product's write sequence now. Read without a lock: the file is replaced whole."""
    return int(_load(product_of(project))["seq"])


def since(project, seen: int) -> tuple[list[Item], bool]:
    """What moved the sequence after `seen`, and whether that is ALL of it.

    Complete when `seen` lies inside what the log still holds. A sequence older than the log's
    floor (what retention dropped), or newer than the log itself (a log lost and started again),
    cannot be vouched for — every item still held comes back, so it is re-checked whole."""
    data = _load(product_of(project))
    items = _items(data)
    complete = int(data.get("floor", 0)) <= int(seen) <= int(data["seq"])
    return ([i for i in items if i.seq > int(seen)] if complete else items), complete


def note(project, *, state: str, kind: str, text: str, ref: str = "", url: str = "",
         conversation: str = "", token: str = "") -> int:
    """Append one item and bump the sequence. Returns the new sequence.

    Under the log's OWN lock and written by atomic replace: two appends never lose one another, and
    a reader never sees half a log. Called inside the semaphore by a write, and by staging."""
    key = product_of(project)
    with FileLock(_dir(key) / f"{WORK_FILE}.lock").held(timeout=LOG_TIMEOUT_SECONDS):
        data = _load(key)
        seq = int(data["seq"]) + 1
        item = Item(seq=seq, state=state, kind=kind, text=str(text or "")[:400], ref=str(ref or ""),
                    url=str(url or ""), where=_where(conversation), token=_sealed(token),
                    ts=time.time())
        items, floor = _pruned([*_items(data), item], floor=int(data.get("floor", 0)),
                               now=item.ts)
        data.update(seq=seq, floor=floor, items=[asdict(i) for i in items],
                    closed=list(data.get("closed") or [])[-MAX_ITEMS:])
        replace_atomically(_dir(key) / WORK_FILE, json.dumps(data, ensure_ascii=False))
    return seq


def close(project, token: str) -> None:
    """A staged proposal was answered — it is no longer a draft waiting in its conversation. No
    bump: an answer is neither a write nor a staging, and the write it leads to bumps on its own."""
    if not token:
        return
    key = product_of(project)
    with FileLock(_dir(key) / f"{WORK_FILE}.lock").held(timeout=LOG_TIMEOUT_SECONDS):
        data = _load(key)
        sealed = _sealed(token)
        closed = [t for t in (data.get("closed") or []) if t != sealed] + [sealed]
        data["closed"] = closed[-MAX_ITEMS:]
        replace_atomically(_dir(key) / WORK_FILE, json.dumps(data, ensure_ascii=False))


def _pruned(items: list[Item], *, floor: int, now: float) -> tuple[list[Item], int]:
    """What the log keeps: a day, at most `MAX_ITEMS` — and the floor, the highest sequence it
    dropped, so `since` knows what it can no longer vouch for."""
    kept = [i for i in items if now - i.ts <= RETAIN_SECONDS][-MAX_ITEMS:]
    held_on = {i.seq for i in kept}
    dropped = [i.seq for i in items if i.seq not in held_on]
    return kept, max([floor, *dropped])


# ── what counts as the same ──────────────────────────────────────────────────────────────────────

def normalised(text: str) -> str:
    """A text with case, accents and punctuation folded away — the deterministic "same"."""
    folded = unicodedata.normalize("NFKD", str(text or ""))
    plain = "".join(c for c in folded if not unicodedata.combining(c)).lower()
    return " ".join(re.split(r"[^a-z0-9]+", plain)).strip()


def exact(text: str, items: list[Item]) -> Item | None:
    """The item that says exactly this, once folded — the check allowed inside the lock."""
    want = normalised(text)
    if not want:
        return None
    return next((i for i in items if normalised(i.text) == want), None)


def closest(text: str, items: list[Item]) -> list[Item]:
    """The items that share enough words with `text` to be the same request, best first — the
    lexical lead `product/asked.py` already uses, so "close" means one thing on this surface."""
    from openfactory.product import asked

    query = asked.tokens(text)
    scored = []
    for item in items:
        shared, score = asked.overlap(query, asked.tokens(item.text))
        if shared >= asked.MIN_SHARED and score >= asked.MIN_SCORE:
            scored.append((score, shared, item))
    scored.sort(key=lambda row: (-row[0], -row[1], -row[2].seq))
    return [item for _, _, item in scored]


def staged_elsewhere(project, text: str, *, conversation: str) -> list[Item]:
    """Drafts staged in OTHER conversations, not yet answered and not expired, that are close to
    `text` — what the anonymous "someone asked for something close to this" is said about.

    One per conversation, the latest: staging holds one proposal per conversation, so an older
    draft of the same conversation was displaced and is nobody's any more."""
    from openfactory.product.staging import PROPOSAL_TTL_SECONDS

    data = _load(product_of(project))
    closed = set(data.get("closed") or [])
    mine, now = _where(conversation), time.time()
    latest: dict[str, Item] = {}
    for item in _items(data):
        if item.state == STAGED and item.where:
            latest[item.where] = item
    live = [i for w, i in latest.items()
            if w != mine and i.kind in NEW_WORK and i.token not in closed
            and now - i.ts <= PROPOSAL_TTL_SECONDS]
    exactly = exact(text, live)
    return [exactly] if exactly is not None else closest(text, live)


# ── check and write, as one step ─────────────────────────────────────────────────────────────────

@dataclass
class Checked:
    """What `check_and_write` did: wrote (`result`), found it already saved (`found`), or ran out
    of rounds with the sequence still moving (`crowded`) — and then wrote nothing."""

    result: object = None
    found: Item | None = None
    crowded: bool = False


def check_and_write(project, *, seen: int | None, kind: str, text: str,
                    write: Callable[[], object],
                    saved: Callable[[object], tuple[str, str] | None] | None = None,
                    judge: Callable[[str, list[Item]], Item | None] | None = None,
                    against: tuple[str, ...] | None = None, rounds: int = ROUNDS,
                    timeout: float | None = None) -> Checked:
    """The write, if nothing SAVED since the turn's check is the same thing — as one step (D7).

    `seen` is the sequence the turn noted before its duplicate search; None is a caller that ran
    none, and its check is now. `write` runs INSIDE the semaphore and returns the act's result;
    `saved(result)` says what it saved — `(ref, url)` — or None when it saved nothing new, and a
    saved item bumps the sequence before the lock is let go. `judge` runs OUTSIDE it: a model
    call over the few items that arrived. `against` is which kinds can be the same as this one
    (default: this kind alone; empty: nothing is compared, the lock is for the write alone — an
    acceptance). Raises `Busy` when the semaphore was not had in time."""
    kinds = (kind,) if against is None else tuple(against)
    mark = sequence(project) if seen is None else int(seen)
    for _ in range(max(1, rounds)):
        pending: list[Item] = []
        with held(project, timeout=timeout):
            now = sequence(project)
            if now != mark:
                moved, complete = since(project, mark)
                # ONLY A SAVED RECORD STOPS A WRITE (D9): a staged draft has no number to link to,
                # and two people who each staged the same thing would otherwise hold each other off
                # until one draft expired
                arrived = [i for i in moved if i.state == SAVED and i.kind in kinds]
                if not complete:
                    log.warning("OPENFACTORY_PRODUCT_SEQUENCE_UNVOUCHED product=%s seen=%s — the "
                                "log no longer holds everything since this check; everything it "
                                "holds is re-checked", product_of(project), mark)
                same = exact(text, arrived)
                if same is not None:
                    return Checked(found=same)
                if arrived and judge is not None:
                    pending, mark = arrived, now
            if not pending:
                result = write()
                described = saved(result) if saved is not None else None
                if described:
                    _note_saved(project, kind=kind, text=text, ref=described[0], url=described[1])
                return Checked(result=result)
        # THE LOCK IS RELEASED HERE, and only here is anything judged: a model call under it would
        # hold every other write of the product for as long as the model takes (D8)
        same = judge(text, pending)
        if same is not None:
            return Checked(found=same)
    log.warning("OPENFACTORY_PRODUCT_SEQUENCE_KEPT_MOVING product=%s rounds=%d — nothing was "
                "written unchecked; the person was told to ask again", product_of(project), rounds)
    return Checked(crowded=True)


def _note_saved(project, *, kind: str, text: str, ref: str, url: str) -> None:
    """The saved item, bumped into the sequence while the semaphore is still held — so the next
    writer, whatever it checked, finds it among what arrived."""
    try:
        note(project, state=SAVED, kind=kind, text=text, ref=ref, url=url)
    except Exception:  # noqa: BLE001 — the write happened; only the sequence missed it
        log.error("OPENFACTORY_PRODUCT_SEQUENCE_NOT_BUMPED product=%s kind=%s ref=%s — written, "
                  "and a concurrent twin will be caught only by the exact checks of the record "
                  "itself", product_of(project), kind, ref, exc_info=True)


def stage(project, *, kind: str, text: str, conversation: str, token: str) -> list[Item]:
    """A draft staged: the twins it has in other conversations, then the sequence bumped — under
    the semaphore, so two drafts staged at one moment cannot both miss each other.

    Never raises: staging is not a write, and a lock that cannot be had costs the notice, never
    the draft — the sequence is still bumped, through the log's own lock."""
    try:
        with held(project, timeout=STAGING_TIMEOUT_SECONDS):
            twins = staged_elsewhere(project, text, conversation=conversation)
            note(project, state=STAGED, kind=kind, text=text, conversation=conversation,
                 token=token)
            return twins
    except Busy:
        log.warning("OPENFACTORY_PRODUCT_STAGED_WITHOUT_THE_SEMAPHORE product=%s — a write held it "
                    "past the staging's wait; the draft is staged and sequenced, and its twins in "
                    "other conversations were not looked for", product_of(project))
    except Exception:  # noqa: BLE001 — the draft is staged regardless; its confirmation re-checks
        log.warning("OPENFACTORY_PRODUCT_STAGED_UNSEQUENCED product=%s — the write log could not "
                    "take this staging; its twins were not looked for", product_of(project),
                    exc_info=True)
        return []
    try:
        note(project, state=STAGED, kind=kind, text=text, conversation=conversation, token=token)
    except Exception:  # noqa: BLE001 — the draft is staged regardless; its confirmation re-checks
        log.warning("OPENFACTORY_PRODUCT_STAGED_UNSEQUENCED product=%s — the write log could not "
                    "take this staging either", product_of(project), exc_info=True)
    return []


__all__ = [
    "MAX_ITEMS",
    "NEW_WORK",
    "ROUNDS",
    "SAVED",
    "STAGED",
    "TIMEOUT_SECONDS",
    "Busy",
    "Checked",
    "Item",
    "ModelUnderSemaphore",
    "check_and_write",
    "close",
    "closest",
    "exact",
    "held",
    "held_here",
    "normalised",
    "note",
    "product_of",
    "refuse_a_model_here",
    "sequence",
    "since",
    "stage",
    "staged_elsewhere",
]
