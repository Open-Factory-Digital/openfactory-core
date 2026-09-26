"""Project memory across stores — one read over everything anybody said (#33, hole 3).

MEMORY WAS PER CONVERSATION, NOT PER PROJECT. `transcript.recent` reads one thread (plus its
channel) out of the last few hundred rows; the tech-lead's own messages live in a second store
(`memory/messages.py`); nothing read across threads, nothing read across the two, and "knows
everything everyone said" was not a property either read could grow into by scanning harder.

ONE READ, TWO STORES, ONE INDEX. `refresh` pulls what is NEW from both stores since the last time
it looked — the transcript's rows (every thread, every person) and the channel messages (what the
factory told and was told) — into an inverted index persisted per project
(`paths.project_memory_dir`), and `recall` answers a question out of the index, ranked by how much
of the question a turn carries and how recent it is. The index is DERIVED: delete it and the next
refresh rebuilds it from the stores; it forgets what the stores forget (`RETENTION_DAYS`).

A PRIVATE CONVERSATION STAYS PRIVATE. #46 made the per-person key the one control over who reads
a conversation; a project-wide read that surfaced Ana's private turns to Bruno's question would
undo it from the other side. A hit from a private conversation (`product/conversation.is_private`)
is returned only to that conversation's own person; the room and the channel are everybody's.

WHAT A GROUP SAID TO SOMEBODY ELSE IS SEARCHABLE AND NEVER PROMPTED (#266 slice 6, ADR-0051 D14,
decision 3). A line not addressed to the role is indexed like every other — the explicit recall
finds it — and `recall` leaves it out unless the caller asks for it (`overheard=True`), because
the recall block a turn reads is built from `recall`, and the safe answer is the one a caller gets
without asking.
"""

from __future__ import annotations

import json
import logging
import math
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openfactory.memory import messages, transcript
from openfactory.product.conversation import is_private, owner_of

log = logging.getLogger("openfactory.memory.recall")

INDEX_FILE = "recall-index.json"
INDEX_VERSION = 1
RETENTION_DAYS = transcript.RETENTION_DAYS
#: rows asked of each store per refresh — the most recent; grows (×4, to the ceiling) while every
#: row that came back is newer than the index, because then rows may sit between
FETCH = 2000
FETCH_CEILING = 32000
DEFAULT_LIMIT = 8
#: How long a refresh waits for another one of the same index before answering from it as it
#: stands. A refresh is a store read and a file replace; ten seconds is several of them.
REFRESH_WAIT_SECONDS = 10.0
DEFAULT_BUDGET = 2400
CONVERSATION = "conversation"
CHANNEL = "channel"

_STOP = frozenset("""
a o e de da do das dos em no na nos nas um uma uns umas que por para com sem sobre como mais
menos muito ja nao sim ele ela eles elas isso isto aqui ali foi ser ter tem esta este essa esse
the and for with that this from into onto are was were has have had not but you your our its
about what when where which who how can could would should will just also then than there here
""".split())


@dataclass(frozen=True)
class Said:
    """One thing somebody said, wherever they said it."""

    id: str
    ts: str
    store: str     # CONVERSATION (the transcript) or CHANNEL (the factory's messages)
    where: str     # the conversation's key, or the channel
    role: str      # person | agent
    actor: str
    text: str
    #: False for a line said in a group to somebody else (ADR-0051 D14) — found by the explicit
    #: recall, never by a turn's. True for every row indexed before the mark existed.
    addressed: bool = True


@dataclass(frozen=True)
class Hit:
    said: Said
    score: float


def tokens(text: str) -> list[str]:
    """Words worth indexing: lower-cased, accents stripped (`ação` and `acao` are one word),
    three letters or more, no stopwords; numbers of two digits or more stay (a card number is
    the most useful token a turn carries)."""
    flat = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    out: list[str] = []
    for word in re.findall(r"[a-z0-9]+", flat.lower()):
        if word in _STOP:
            continue
        if len(word) >= 3 or (word.isdigit() and len(word) >= 2):
            out.append(word)
    return out


@dataclass
class MemoryIndex:
    """An inverted index over `Said` rows, persisted as one JSON file per project."""

    project: str
    version: int = INDEX_VERSION
    last_ts: dict[str, str] = field(default_factory=dict)   # per store
    rows: dict[str, dict] = field(default_factory=dict)      # id -> Said as dict
    postings: dict[str, list[str]] = field(default_factory=dict)  # token -> ids

    @classmethod
    def load(cls, path: Path, project: str) -> MemoryIndex:
        """The index on disk, or an empty one — for an absent file, an unreadable one, or one of
        another version: all three rebuild from the stores on the next refresh."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(project=project)
        if (not isinstance(data, dict) or data.get("version") != INDEX_VERSION
                or data.get("project") != project):
            return cls(project=project)
        try:
            return cls(project=project, last_ts=dict(data.get("last_ts") or {}),
                       rows=dict(data.get("rows") or {}),
                       postings={k: list(v) for k, v in (data.get("postings") or {}).items()})
        except (TypeError, ValueError):
            return cls(project=project)

    def save(self, path: Path) -> None:
        """Replaced whole, never truncated in place (#266 slice 3): a reader sees the index before
        this refresh or after it, and a kill between the two leaves the old one standing."""
        from openfactory.util.filelock import replace_atomically

        replace_atomically(Path(path), json.dumps({"version": self.version,
                                                   "project": self.project,
                                                   "last_ts": self.last_ts, "rows": self.rows,
                                                   "postings": self.postings},
                                                  ensure_ascii=False))

    def add(self, said: Said) -> bool:
        """Index one row; False when it was already there (the stores are read with overlap)."""
        if said.id in self.rows or not said.text.strip():
            return False
        self.rows[said.id] = asdict(said)
        for token in set(tokens(said.text)):
            self.postings.setdefault(token, []).append(said.id)
        if said.ts > self.last_ts.get(said.store, ""):
            self.last_ts[said.store] = said.ts
        return True

    def forget_before(self, cutoff_ts: str) -> int:
        """Drop what the stores have forgotten — the index must not remember longer than they do."""
        return self._drop([i for i, r in self.rows.items() if str(r.get("ts", "")) < cutoff_ts])

    def forget_where(self, where: str) -> int:
        """Drop every line said in conversation `where` — a person deleted it (#335)."""
        return self._drop([i for i, r in self.rows.items() if str(r.get("where", "")) == where])

    def _drop(self, gone: list[str]) -> int:
        for i in gone:
            del self.rows[i]
        if gone:
            dead = set(gone)
            for token in list(self.postings):
                kept = [i for i in self.postings[token] if i not in dead]
                if kept:
                    self.postings[token] = kept
                else:
                    del self.postings[token]
        return len(gone)

    def search(self, query: str, *, limit: int = DEFAULT_LIMIT) -> list[Hit]:
        """The rows carrying most of the question — rarer words weigh more, ties go to the
        newest."""
        asked = set(tokens(query))
        if not asked or not self.rows:
            return []
        total = len(self.rows)
        scores: dict[str, float] = {}
        for token in asked:
            ids = self.postings.get(token, ())
            if not ids:
                continue
            weight = 1.0 + math.log(total / len(ids))
            for i in ids:
                scores[i] = scores.get(i, 0.0) + weight
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], -_order(self.rows[kv[0]]["ts"])))
        return [Hit(Said(**self.rows[i]), score) for i, score in ranked[:limit]]


def _order(ts: str) -> float:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _from_transcript(rows: list[dict]) -> list[Said]:
    out: list[Said] = []
    for r in rows:
        extra = r.get("extra") or {}
        ts = str(r.get("ts", "") or "")
        where = str(r.get("ticket", "") or "")
        text = str(extra.get("text", "") or "").strip()
        if not ts or not text:
            continue
        out.append(Said(id=f"t:{where}:{ts}", ts=ts, store=CONVERSATION, where=where,
                        role=str(r.get("role", "") or "person"),
                        actor=str(extra.get("actor", "") or ""), text=text,
                        addressed=extra.get(transcript.ADDRESSED_MARK) is not False))
    return out


def _from_messages(rows: list[messages.Message]) -> list[Said]:
    out: list[Said] = []
    for m in rows:
        if m.kind not in (messages.TOLD, messages.SAID, messages.ASKED):
            continue
        text = (m.text or "").strip()
        if not text or not m.ts:
            continue
        out.append(Said(id=f"c:{m.ts}:{m.kind}", ts=m.ts, store=CHANNEL,
                        where=m.channel or "channel",
                        role="person" if m.kind == messages.TOLD else "agent",
                        actor=m.by or "", text=text))
    return out


def gather(project: str, *, fetch: int = FETCH, transcript_rows=None, messages_scan=None,
           partition=None) -> tuple[list[Said], bool]:
    """What the two stores hold now, newest `fetch` of each — and whether the transcript window
    was full (so a larger one may hold more).

    `partition` is where the conversations are read from: the PRODUCT's memory (ADR-0051 D2,
    `transcript.partition`) when the caller hands it, every registry project of the product and
    their rows from before the move included; the partition named `project` when it does not. The
    channel's messages stay the registry project's — the factory's floor is its unit."""
    if transcript_rows is None:
        rows, full = transcript.rows(partition if partition is not None else project,
                                     limit=fetch)
    else:
        rows = list(transcript_rows(fetch))
        full = len(rows) >= fetch
    said = _from_transcript(rows) + _from_messages(messages.read(project, scan=messages_scan))
    return said, full


def refresh(project: str, index_dir: Path, *, transcript_rows=None, messages_scan=None,
            now: datetime | None = None, partition=None) -> MemoryIndex:
    """Bring the project's index up to the stores: read what is newer than the last refresh, add
    it, forget what retention forgot, save. A store that will not answer costs this refresh and
    never the caller — the index stands as it was.

    ONE REFRESH AT A TIME PER INDEX, UNDER A LOCK OF ITS OWN (#266 slice 3, ADR-0051 D11). Every
    turn of every conversation refreshes it, and conversations now run in parallel: two refreshes
    that both loaded the index and both saved it kept whichever finished last. The lock is the
    index's own — never the product's semaphore, which is for what becomes work — and a refresh
    that cannot have it in time answers from the index as it stands, which is what a refresh that
    cannot reach the stores already does."""
    from openfactory.util.filelock import Waited, lock_beside

    path = Path(index_dir) / INDEX_FILE
    lock = lock_beside(path)
    try:
        lock.acquire(timeout=REFRESH_WAIT_SECONDS)
    except Waited:
        log.warning("[%s] another refresh held the project memory index past %ss — answering "
                    "from it as it stands", project, REFRESH_WAIT_SECONDS)
        return MemoryIndex.load(path, project)
    except OSError as exc:
        # a directory nobody may write in was already a refresh that could not save; it stays
        # exactly that, rather than becoming a refresh that raises
        log.warning("[%s] could not lock the project memory index (%s) — refreshing without the "
                    "lock", project, exc)
        return _refreshed(project, path, transcript_rows=transcript_rows,
                          messages_scan=messages_scan, now=now, partition=partition)
    try:
        return _refreshed(project, path, transcript_rows=transcript_rows,
                          messages_scan=messages_scan, now=now, partition=partition)
    finally:
        lock.release()


def _refreshed(project: str, path: Path, *, transcript_rows, messages_scan,
               now: datetime | None, partition=None) -> MemoryIndex:
    """`refresh`'s work, with the index's lock held."""
    index = MemoryIndex.load(path, project)
    fetch = FETCH
    while True:
        try:
            said, full = gather(project, fetch=fetch, transcript_rows=transcript_rows,
                                messages_scan=messages_scan, partition=partition)
        except Exception as exc:  # noqa: BLE001 — a memory that cannot be refreshed is the old memory
            log.warning("[%s] could not refresh the project memory (%s)", project, str(exc)[:160])
            return index
        seen_transcript = [s for s in said if s.store == CONVERSATION]
        last = index.last_ts.get(CONVERSATION, "")
        # EVERY ROW NEWER THAN THE INDEX and the window full: rows may sit between — widen.
        if (last and full and seen_transcript and fetch < FETCH_CEILING
                and min(s.ts for s in seen_transcript) > last):
            fetch = min(fetch * 4, FETCH_CEILING)
            continue
        break
    added = sum(1 for s in said if index.add(s))
    cutoff = ((now or datetime.now(UTC)) - timedelta(days=RETENTION_DAYS)).isoformat()
    forgotten = index.forget_before(cutoff)
    if added or forgotten:
        try:
            index.save(path)
        except OSError as exc:
            log.warning("[%s] could not save the project memory index (%s)", project, exc)
    return index


def forget_conversation(project: str, where: str, *, index_dir: Path) -> int:
    """Drop conversation `where` from the project's memory index, under the refresh's own lock —
    how many lines went. RAISES `Waited` when a refresh holds it past the wait: a deletion that
    could not run must say so, never report as done (#335)."""
    from openfactory.util.filelock import lock_beside

    path = Path(index_dir) / INDEX_FILE
    if not where or not path.is_file():
        return 0
    lock = lock_beside(path)
    lock.acquire(timeout=REFRESH_WAIT_SECONDS)
    try:
        index = MemoryIndex.load(path, project)
        gone = index.forget_where(where)
        if gone:
            index.save(path)
        return gone
    finally:
        lock.release()


def recall(project: str, query: str, *, index_dir: Path, own: str = "",
           exclude_where: str = "", limit: int = DEFAULT_LIMIT, transcript_rows=None,
           messages_scan=None, now: datetime | None = None, partition=None,
           overheard: bool = False) -> list[Hit]:
    """What was said about `query` anywhere in this project — for the person in conversation
    `own`. A private conversation's turns come back only to its own person; the current
    conversation (`exclude_where`) is left out, because the caller already has it in front of
    the role.

    A line said in a group to somebody else comes back ONLY WHEN ASKED FOR (`overheard=True`,
    the explicit recall a person runs): the block a turn reads is built from this, and what was
    not addressed to the role never reaches a prompt (ADR-0051 D14)."""
    index = refresh(project, index_dir, transcript_rows=transcript_rows,
                    messages_scan=messages_scan, now=now, partition=partition)
    hits = index.search(query, limit=limit * 4)
    kept = [h for h in hits
            if h.said.where != exclude_where
            and (overheard or h.said.addressed)
            and (not is_private(h.said.where) or owner_of(h.said.where) == owner_of(own))]
    return kept[:limit]


def render_recall(hits: list[Hit], *, agent_name: str = "", budget: int = DEFAULT_BUDGET,
                  heading: str = "## Said elsewhere in this project (most relevant first)",
                  name_people: bool = False) -> str:
    """The prompt block — evidence of what was said, where and when; "" when there is none.

    Without names is how a CONVERSATION reads it (ADR-0051 D9): what was said in another
    conversation may inform the answer, but the role never names a person from outside the one it
    is in — so the model is not handed a name it could repeat. The role's own turns keep its name;
    a person becomes "someone", and a private conversation's key, which names its person, becomes
    "a private conversation". The explicit recall action, asked by an operator, opts into names.

    WITHOUT NAMES IS THE DEFAULT because this is a privacy rule: a new caller that forgets the
    argument is coy, never a surface that leaks names."""
    if not hits:
        return ""
    lines = [heading]
    spent = 0
    for hit in hits:
        s = hit.said
        if s.role == "agent":
            who = agent_name or "the product role"
        else:
            who = (s.actor or "somebody") if name_people else "someone"
        if s.store == CHANNEL and s.where in ("", "channel"):
            where = "the channel"
        elif not name_people and is_private(s.where):
            # the speaker withheld and the key that names them printed beside it said who anyway
            where = "a private conversation"
        else:
            where = f"`{s.where}`"
        line = f"- {s.ts[:10]} · {who}, in {where}: {s.text}"
        if spent + len(line) > budget and len(lines) > 1:
            break
        spent += len(line)
        lines.append(line)
    return "\n".join(lines)


__all__ = [
    "CHANNEL",
    "CONVERSATION",
    "INDEX_FILE",
    "RETENTION_DAYS",
    "Hit",
    "MemoryIndex",
    "Said",
    "recall",
    "refresh",
    "render_recall",
    "tokens",
]
