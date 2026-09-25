"""One SQLite file per product: the items, their full-text index and their vectors (#269 slice 2,
ADR-0053 D5, D9).

ON THE CLIENT'S MACHINE (ADR-0040). SQLite is in the standard library, its full-text search (FTS5)
is compiled into every CPython build this platform supports, and a file needs no server — so the
index is a file under the product's state directory, `<product_state_dir>/index/memory.sqlite`,
beside the document records it is built from (`product/documents/store.py`). No cloud vector
database, and no process to run.

VECTORS ARE BLOBS SCORED IN PYTHON, NOT A NATIVE EXTENSION. Measured on 2026-09-24 on a laptop,
256-dimensional float32 vectors read from this table and scored per query: 100,000 items (67,000
left after the audience filter) take 61 ms with numpy — which the `embed` extra installs, as its
library needs it — and 246 ms in pure Python (`math.sumprod`). A turn waits seconds to minutes on
its model; a native vector extension would save tens of milliseconds, cost a compiled binary loaded
into the process (and `enable_load_extension`, which some builds of Python refuse), and do the same
brute-force scan anyway at this size. The measurement to revisit it: a product whose index is
queried in more than a few hundred milliseconds.

KEYED BY PRODUCT, AND IT SAYS WHOSE IT IS (ADR-0053 D5). The file's path is the product's
(`paths.product_state_dir`), and the file records the product it was built for: opened for another
product it raises `ForeignIndex` rather than answer, an item of another product is refused at the
write, and every read filters on the product as well (`search.py`). No product's row reaches
another product's search by any one of these failing alone.

DERIVED, SO NEVER MIGRATED. A file of another schema version is deleted and built again from the
sources; so is one that cannot be opened. The next sync fills it.

THE WORDS ARE FOLDED AND STEMMED: FTS5's `unicode61` tokenizer with accents removed (`ação` is
`acao`), under its `porter` stemmer — so "payments" finds "payment". Porter is English's; on
Portuguese it takes a plural's `s` and little else, which does no harm. An exact reference is one
token of letters and digits (`req41`, `card512`), which neither changes.

WAL, SO READS DO NOT WAIT. Conversations run side by side, and each turn searches; a writer — one
sync at a time, under a lock of its own (`sync.py`) — never blocks them.
"""

from __future__ import annotations

import array
import contextlib
import json
import logging
import sqlite3
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

from openfactory.product.index.items import Item

log = logging.getLogger("openfactory.product.index")

DIRNAME = "index"
FILENAME = "memory.sqlite"
#: The schema this code reads and writes. Another is rebuilt, never migrated: the index is derived.
#: 2 (#269 slice 3): a conversation's distillate is an item of its own kind, carrying whose
#: conversation it is — an index built before would hold one as a plain document, for everybody.
SCHEMA_VERSION = 2
#: How long a statement waits for a writer's lock before it fails — a sync commits in batches.
BUSY_SECONDS = 10.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS groups (grp TEXT PRIMARY KEY, digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items (
    rowid INTEGER PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    grp TEXT NOT NULL,
    product TEXT NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    locator TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    date TEXT NOT NULL DEFAULT '',
    date_from TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT '',
    audience TEXT NOT NULL,
    status TEXT NOT NULL,
    successor INTEGER,
    requirements TEXT NOT NULL DEFAULT '',
    cards TEXT NOT NULL DEFAULT '',
    conversation TEXT NOT NULL DEFAULT '',
    private INTEGER NOT NULL DEFAULT 0,
    addressed INTEGER NOT NULL DEFAULT 1,
    extra TEXT NOT NULL DEFAULT '{}',
    vector BLOB
);
CREATE INDEX IF NOT EXISTS items_grp ON items(grp);
CREATE INDEX IF NOT EXISTS items_kind ON items(kind);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
    title, text, terms, tokenize = 'porter unicode61 remove_diacritics 2'
);
"""


class ForeignIndex(RuntimeError):
    """The file at a product's index path was built for another product — it is not read."""


def index_path(key: str) -> Path:
    from openfactory.paths import product_state_dir

    return product_state_dir(key) / DIRNAME / FILENAME


def ref_token(prefix: str, ref: object) -> str:
    """An exact reference as ONE word the full-text index keeps whole: `req41`, `card512`,
    `cardcont412` — so "requirement 41", "REQ-0041" and "requisito 41" all find it, and nothing
    in the document's own words can be mistaken for it."""
    text = str(ref).lower().lstrip("#")
    if prefix == "req":
        text = str(int(text)) if text.isdigit() else text
    return prefix + "".join(c for c in text if c.isalnum())


def terms_of(item: Item) -> str:
    return " ".join([*(ref_token("req", n) for n in item.requirements),
                     *(ref_token("card", c) for c in item.cards)])


def pack(vector: list[float]) -> bytes:
    """A vector as little-endian float32 bytes — whatever machine wrote it."""
    out = array.array("f", vector)
    if sys.byteorder != "little":
        out.byteswap()
    return out.tobytes()


def unpack(blob: bytes) -> array.array:
    out = array.array("f")
    out.frombytes(blob)
    if sys.byteorder != "little":
        out.byteswap()
    return out


class Index:
    """One product's index file."""

    def __init__(self, key: str, *, path: Path | None = None) -> None:
        self.key = key
        self.path = Path(path) if path is not None else index_path(key)

    # ── opening ─────────────────────────────────────────────────────────────────────────────

    @contextlib.contextmanager
    def open(self) -> Iterator[sqlite3.Connection]:
        """A connection to the product's index, its schema ensured and its owner checked."""
        con = self._connect()
        try:
            yield con
        finally:
            con.close()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            con = self._opened()
        except sqlite3.DatabaseError as exc:
            log.warning("[%s] the index %s could not be opened (%s) — it is rebuilt from its "
                        "sources", self.key, self.path, exc)
            self.drop()
            con = self._opened()
        found = dict(con.execute("SELECT key, value FROM meta").fetchall())
        if found.get("product") not in (None, self.key):
            con.close()
            log.error("OPENFACTORY_INDEX_FOREIGN the index at %s was built for %r, not %r — it "
                      "is not read", self.path, found.get("product"), self.key)
            raise ForeignIndex(f"the index at {self.path} belongs to {found.get('product')!r}, "
                               f"not {self.key!r}")
        if found.get("schema") not in (None, str(SCHEMA_VERSION)):
            con.close()
            log.info("[%s] the index is of schema %s — rebuilt as %s", self.key,
                     found.get("schema"), SCHEMA_VERSION)
            self.drop()
            con = self._opened()
        if "product" not in found or found.get("schema") != str(SCHEMA_VERSION):
            with con:
                con.execute("INSERT OR REPLACE INTO meta VALUES ('product', ?)", (self.key,))
                con.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)",
                            (str(SCHEMA_VERSION),))
        return con

    def _opened(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path), timeout=BUSY_SECONDS)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(f"PRAGMA busy_timeout={int(BUSY_SECONDS * 1000)}")
        con.executescript(_SCHEMA)
        return con

    def drop(self) -> None:
        """The file removed — derived, so the next sync builds it again."""
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.path}{suffix}").unlink(missing_ok=True)

    # ── meta ────────────────────────────────────────────────────────────────────────────────

    @staticmethod
    def meta(con: sqlite3.Connection, key: str) -> str:
        row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row else ""

    @staticmethod
    def set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
        con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    # ── groups ──────────────────────────────────────────────────────────────────────────────

    @staticmethod
    def groups(con: sqlite3.Connection, prefix: str) -> dict[str, str]:
        """`grp → digest` for every group whose name starts with `prefix`."""
        rows = con.execute("SELECT grp, digest FROM groups WHERE substr(grp, 1, ?) = ?",
                           (len(prefix), prefix)).fetchall()
        return {str(r[0]): str(r[1]) for r in rows}

    def replace_group(self, con: sqlite3.Connection, grp: str, digest: str,
                      items: Iterable[Item]) -> int:
        """The group's items replaced by `items`, and its version recorded. Refuses an item of
        another product, or of another group."""
        made = list(items)
        for item in made:
            if item.product != self.key:
                raise ValueError(f"an item of {item.product!r} was handed the index of "
                                 f"{self.key!r}")
            if item.grp != grp:
                raise ValueError(f"the item {item.id!r} is of the group {item.grp!r}, not {grp!r}")
        self.drop_groups(con, [grp])
        for item in made:
            cur = con.execute(
                "INSERT INTO items (id, grp, product, kind, source, locator, title, text, date, "
                "date_from, origin, audience, status, successor, requirements, cards, "
                "conversation, private, addressed, extra) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (item.id, item.grp, item.product, item.kind, item.source, item.locator,
                 item.title, item.text, item.date, item.date_from, item.origin, item.audience,
                 item.status, item.successor, " ".join(str(n) for n in item.requirements),
                 " ".join(item.cards), item.conversation, int(item.private), int(item.addressed),
                 json.dumps(item.extra, ensure_ascii=False, sort_keys=True)))
            con.execute("INSERT INTO fts (rowid, title, text, terms) VALUES (?,?,?,?)",
                        (cur.lastrowid, item.title, item.text, terms_of(item)))
        con.execute("INSERT OR REPLACE INTO groups VALUES (?, ?)", (grp, digest))
        return len(made)

    @staticmethod
    def drop_groups(con: sqlite3.Connection, grps: Iterable[str]) -> None:
        for grp in grps:
            rowids = [r[0] for r in con.execute("SELECT rowid FROM items WHERE grp = ?", (grp,))]
            if rowids:
                marks = ",".join("?" * len(rowids))
                con.execute(f"DELETE FROM fts WHERE rowid IN ({marks})", rowids)  # nosec B608
                con.execute(f"DELETE FROM items WHERE rowid IN ({marks})", rowids)  # nosec B608
            con.execute("DELETE FROM groups WHERE grp = ?", (grp,))

    # ── vectors ─────────────────────────────────────────────────────────────────────────────

    @staticmethod
    def without_vectors(con: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
        return con.execute("SELECT rowid, title, text FROM items WHERE vector IS NULL "
                           "ORDER BY rowid LIMIT ?", (limit,)).fetchall()

    @staticmethod
    def set_vectors(con: sqlite3.Connection, made: list[tuple[int, list[float]]]) -> None:
        con.executemany("UPDATE items SET vector = ? WHERE rowid = ?",
                        [(pack(vector), rowid) for rowid, vector in made])

    @staticmethod
    def forget_vectors(con: sqlite3.Connection) -> None:
        con.execute("UPDATE items SET vector = NULL")

    @staticmethod
    def counts(con: sqlite3.Connection) -> tuple[int, int]:
        """`(items, items with a vector)`."""
        row = con.execute("SELECT count(*), count(vector) FROM items").fetchone()
        return int(row[0]), int(row[1])
