"""The index brought up to its sources — only what changed, one group at a time (#269 slice 2).

FOUR SOURCES, EACH READ WHERE IT ALREADY IS, NONE READ TWICE:

  - the DOCUMENTS as slice 1 recorded them (`product/documents/store.py`): the store's index says
    which version each path holds, and a group whose version — the record's digest, and whether a
    model's reading of it is still pending — has not moved is not touched. A path gone from the
    repository leaves the index. A requirement file is left to the corpus, which reads it with its
    status: indexed twice, a superseded requirement would come back once as a plain document;
  - the REQUIREMENTS as the corpus parsed them — the curated truth, with status and successor;
  - the CLOSED CARDS of the board the turn already read. A card this read does not include is
    kept: the board a turn reads is a window, and the index is what remembers past it; a card
    this read shows open again leaves;
  - the CONVERSATIONS as the product's recall index holds them (`memory/recall.py`), which the
    turn refreshed a moment before — the recall index of #33 joins the product's (ADR-0053 D5).
    A line older than the transcript's retention leaves the index as it leaves the store (D6).

EVERY SOURCE IS THE PRODUCT'S OWN. The documents come from the store keyed by the product, which
reads back only records of that product; the corpus and the board from the product's own checkout
and tracker; the conversations from the product's partition. And the index refuses an item of
another product whatever it is handed (`store.py`).

ONE SYNC AT A TIME PER PRODUCT, under the index's own lock — never the product's semaphore, which
is for what becomes work. A sync that cannot have it in a moment is skipped, and the search reads
the index as it stands: slightly behind is a better answer than a turn that waits.

THE VECTORS ARE MADE LAST, AND BOUNDED. A new item is searchable by its words at once and by its
meaning once it has a vector; a turn embeds at most `EMBED_PER_TURN` items, and the scheduled pass
after the documents' ingestion (`runtime/temporal/activities.py`) embeds the rest. Vectors made by
another model are forgotten and made again: a cosine across two models means nothing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath

from openfactory.product.index.items import (
    digest_of,
    from_card,
    from_record,
    from_requirement,
    from_turn,
)
from openfactory.product.index.store import Index

log = logging.getLogger("openfactory.product.index")

#: How long a sync waits for another one of the same product before it lets the search read the
#: index as it stands.
SYNC_WAIT_SECONDS = 3.0
#: How many items a turn's sync embeds; the scheduled pass is unbounded (None).
EMBED_PER_TURN = 2000
EMBED_BATCH = 128

_REQUIREMENT_FILE = re.compile(r"^\d{4}-[a-z0-9][a-z0-9-]*\.md$")


@dataclass
class Synced:
    """What one sync did — the log line's words."""

    changed: int = 0
    removed: int = 0
    forgotten: int = 0
    embedded: int = 0
    unembedded: int = 0
    busy: bool = False
    #: why the documents could not be read this time — the index keeps what it had
    documents_unread: str = ""
    #: why no vector was made — "" when an embedder was there and worked
    degraded: str = ""

    def sentence(self) -> str:
        if self.busy:
            return "another sync of this product was running — the index was read as it stood"
        said = [f"{self.changed} group(s) changed", f"{self.removed} removed"]
        if self.forgotten:
            said.append(f"{self.forgotten} line(s) past retention forgotten")
        said.append(f"{self.embedded} embedded, {self.unembedded} without a vector yet")
        if self.documents_unread:
            said.append(f"documents not read ({self.documents_unread})")
        if self.degraded:
            said.append(f"semantic stage off ({self.degraded})")
        return ", ".join(said)


def is_requirement_file(path: str, requirements_dir: str) -> bool:
    """Whether `path` is a requirement the corpus reads — `NNNN-slug.md` directly under the
    requirements folder, exactly the files `corpus.load_corpus` parses."""
    where = PurePosixPath(path)
    folder = PurePosixPath(requirements_dir or "requirements")
    return where.parent == folder and bool(_REQUIREMENT_FILE.match(where.name))


def sync(index: Index, *, records=None, corpus=None, requirements_dir: str = "requirements",
         cards=None, member: str = "", said=None, embedder=None, degraded: str = "",
         embed_limit: int | None = EMBED_PER_TURN, now: datetime | None = None,
         wait: float = SYNC_WAIT_SECONDS) -> Synced:
    """Bring `index` up to the sources handed in — a source left as None is not read this time.
    `records` is the product's document store, `corpus` its requirements, `cards` the board as a
    turn read it (None: not read), `said` the conversations' lines (`recall.Said`). Raises only
    what the index file itself raises; a source that cannot be read is said in the result."""
    from openfactory.util.filelock import Waited, lock_beside

    done = Synced(degraded=degraded)
    lock = lock_beside(index.path)
    index.path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock.acquire(timeout=wait)
    except Waited:
        done.busy = True
        log.info("[%s] %s", index.key, done.sentence())
        return done
    try:
        with index.open() as con:
            if records is not None:
                _documents(index, con, records, requirements_dir, done)
            if corpus is not None:
                _requirements(index, con, corpus, requirements_dir, done)
            if cards is not None:
                _cards(index, con, cards, member, done)
            if said is not None:
                _said(index, con, said, done)
            _forget(con, now or datetime.now(UTC), done)
            if embedder is not None:
                _embed(con, embedder, embed_limit, done)
            total, with_vector = Index.counts(con)
            done.unembedded = total - with_vector
    finally:
        lock.release()
    log.info("OPENFACTORY_PRODUCT_INDEX_SYNC product=%s %s", index.key, done.sentence())
    return done


def _documents(index: Index, con, records, requirements_dir: str, done: Synced) -> None:
    try:
        lines = records.index().get("paths") or {}
    except (OSError, ValueError) as exc:
        # the index keeps what it had: an unreadable store is not a repository with no documents
        done.documents_unread = str(exc)[:160]
        log.warning("[%s] the document records could not be read (%s) — the index keeps the "
                    "documents it had", index.key, exc)
        return
    wanted: dict[str, tuple[str, str, str]] = {}
    for path, line in lines.items():
        if is_requirement_file(path, requirements_dir):
            continue
        digest = str((line or {}).get("digest") or "")
        if digest:
            wanted[f"doc:{path}"] = (path, digest,
                                     f"{digest}:{(line or {}).get('reading') or ''}")
    known = Index.groups(con, "doc:")
    with con:
        gone = [grp for grp in known if grp not in wanted]
        Index.drop_groups(con, gone)
        done.removed += len(gone)
        for grp, (path, digest, version) in wanted.items():
            if known.get(grp) == version:
                continue
            record = records.get(path, digest)
            if record is None:
                continue  # the store's index outlived the record: the next ingestion reads it
            index.replace_group(con, grp, version, from_record(record))
            done.changed += 1


def _requirements(index: Index, con, corpus, requirements_dir: str, done: Synced) -> None:
    wanted = {}
    for requirement in corpus.requirements:
        grp = f"req:{int(requirement.number):04d}"
        wanted[grp] = (requirement, digest_of(requirement.body, requirement.status,
                                              requirement.superseded_by, requirement.date,
                                              requirement.path, requirements_dir))
    known = Index.groups(con, "req:")
    with con:
        gone = [grp for grp in known if grp not in wanted]
        Index.drop_groups(con, gone)
        done.removed += len(gone)
        for grp, (requirement, version) in wanted.items():
            if known.get(grp) == version:
                continue
            index.replace_group(con, grp, version,
                                from_requirement(requirement, product=index.key,
                                                 requirements_dir=requirements_dir))
            done.changed += 1


def _cards(index: Index, con, cards, member: str, done: Synced) -> None:
    known = Index.groups(con, f"card:{member}:")
    with con:
        for card in cards:
            made = from_card(card, product=index.key, member=member)
            grp = f"card:{member}:{getattr(card, 'number', '')}"
            if not made:
                if grp in known:  # reopened: no longer a closed card
                    Index.drop_groups(con, [grp])
                    done.removed += 1
                continue
            version = digest_of(made[0].text, made[0].origin, made[0].date)
            if known.get(made[0].grp) == version:
                continue
            index.replace_group(con, made[0].grp, version, made)
            done.changed += 1


def _said(index: Index, con, said, done: Synced) -> None:
    from openfactory.memory.recall import CONVERSATION

    known = Index.groups(con, "turn:")
    with con:
        for line in said:
            if getattr(line, "store", CONVERSATION) != CONVERSATION or not str(line.text).strip():
                continue
            item = from_turn(line, product=index.key)
            version = digest_of(item.text, item.addressed)
            if known.get(item.grp) == version:
                continue
            index.replace_group(con, item.grp, version, [item])
            done.changed += 1


def _forget(con, now: datetime, done: Synced) -> None:
    """The lines the transcript has forgotten, forgotten here too (ADR-0053 D6)."""
    from openfactory.memory.transcript import RETENTION_DAYS

    cutoff = (now - timedelta(days=RETENTION_DAYS)).isoformat()
    old = [str(r[0]) for r in con.execute(
        "SELECT grp FROM items WHERE kind = 'turn' AND json_extract(extra, '$.ts') < ?",
        (cutoff,))]
    if old:
        with con:
            Index.drop_groups(con, old)
        done.forgotten += len(old)


def _embed(con, embedder, limit: int | None, done: Synced) -> None:
    """The vectors the index is missing, `limit` at most — made by `embedder`, and the vectors of
    any other model forgotten first. A model that fails costs the vectors, never the sync."""
    from openfactory.product.semaphore import refuse_a_model_here

    refuse_a_model_here("product_index_embed")
    if Index.meta(con, "embedder") != embedder.id:
        with con:
            Index.forget_vectors(con)
            Index.set_meta(con, "embedder", embedder.id)
            Index.set_meta(con, "dims", str(embedder.dims))
    left = limit
    while left is None or left > 0:
        batch = Index.without_vectors(con, EMBED_BATCH if left is None else min(EMBED_BATCH,
                                                                                    left))
        if not batch:
            return
        try:
            vectors = embedder.embed([f"{row['title']}\n{row['text']}" for row in batch])
        except Exception:  # noqa: BLE001 — the words are still searchable
            done.degraded = f"the {embedder.id} row failed (the reason is in the platform's log)"
            log.warning("[embed] %s", done.degraded, exc_info=True)
            return
        if len(vectors) != len(batch) or any(len(v) != embedder.dims for v in vectors):
            done.degraded = (f"the {embedder.id} row answered {len(vectors)} vector(s) for "
                             f"{len(batch)} text(s), or of the wrong size — none were kept")
            log.warning("[embed] %s", done.degraded)
            return
        with con:
            Index.set_vectors(con, [(int(row["rowid"]), vector)
                                    for row, vector in zip(batch, vectors, strict=True)])
        done.embedded += len(batch)
        if left is not None:
            left -= len(batch)
