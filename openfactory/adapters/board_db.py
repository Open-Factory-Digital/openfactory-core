"""`board.db` — the one file the local rows share (ADR-0049 D5).

THE SHAPE OF THIS MODULE IS `adapters/azure_devops.py`'s. That file is the client three rows on
three axes share so one vendor is spelled once; this is the same thing for a vendor that happens to
be the machine itself. The tracker row, the board row and — from slice 3 — the forge row all read
and write here, and none of them owns the file.

WHY SQLITE AND NOT THE REGISTRY'S DISCIPLINE. `ProjectRegistry` rewrites a YAML file under a flock
and swaps it in with `os.replace`, which is right for a document a person edits and wrong for this:
`os.replace` on a WAL database DETACHES the journal, so a reader mid-transaction is left holding a
file the writer has stopped extending. This is a database with three processes on it — the worker
polling, the panel serving and a CLI verb in a shell — so it uses a database's own answers: WAL, a
busy timeout, and `BEGIN IMMEDIATE` around anything that reads a value and writes it back.

WHY NOT THE METRICS SINK, which is also SQLite and also on the state volume: an event written there
without `expires_at` evicts the registered accounts (`identity/people.py`). A card is not an event
and must not age out of the board because a sweep decided it was old.

WHAT IS DELIBERATELY NOT HERE. No ORM, no migration framework and no schema version: every open
runs `CREATE TABLE IF NOT EXISTS`, which is idempotent, costs microseconds and makes a new table in
a later slice one more statement rather than a migration to write, test and run. The day a column
has to CHANGE rather than appear, that is a migration and it will need saying out loud.
"""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

#: Where the file is, when the deployment names it. Compose points the worker AND the panel at the
#: state volume they already share, exactly as it does for the registry; a host installation names
#: nothing and gets the operator's own directory.
PATH_ENV = "OPENFACTORY_BOARD_DB"

#: How long a writer waits for another process's lock before giving up. Five seconds is the
#: registry's own flock timeout, and the operations here are single-statement — a wait that long
#: means another process is wedged, not busy, and the caller should hear about it.
BUSY_TIMEOUT_MS = 5000

#: How long to keep asking for the WAL conversion, and why it needs asking at all — see `_to_wal`.
#: Forty tries of 10 ms is 0.4 s at the very worst, on the one open per process that can meet a
#: converting neighbour; every later open finds the file already in WAL and returns on the first.
_WAL_TRIES, _WAL_WAIT_S = 40, 0.01

_SCHEMA = (
    # A card. `ref` is an INTEGER per project because the number sequence is per project (D5);
    # the PORT's two spellings (`#N` and bare `N`) are a rendering question and are resolved by
    # `canonical_ref` at the row, never stored twice.
    """CREATE TABLE IF NOT EXISTS cards (
           project      TEXT NOT NULL,
           ref          INTEGER NOT NULL,
           title        TEXT NOT NULL DEFAULT '',
           body         TEXT NOT NULL DEFAULT '',
           state        TEXT NOT NULL DEFAULT 'open',
           closed_reason TEXT NOT NULL DEFAULT '',
           column_key   TEXT NOT NULL DEFAULT '',
           author       TEXT NOT NULL DEFAULT '',
           requester    TEXT NOT NULL DEFAULT '',
           created_at   TEXT NOT NULL,
           updated_at   TEXT NOT NULL,
           PRIMARY KEY (project, ref)
       )""",
    # Ordered by `seq` rather than by the timestamp: two comments written in the same second must
    # still come back oldest-first, and the ADR-0048 sweep reads the ORDER to decide whether an
    # answer is newer than the question it answers.
    """CREATE TABLE IF NOT EXISTS comments (
           project    TEXT NOT NULL,
           ref        INTEGER NOT NULL,
           seq        INTEGER NOT NULL,
           author     TEXT NOT NULL DEFAULT '',
           body       TEXT NOT NULL DEFAULT '',
           created_at TEXT NOT NULL,
           PRIMARY KEY (project, ref, seq)
       )""",
    """CREATE TABLE IF NOT EXISTS labels (
           project TEXT NOT NULL,
           ref     INTEGER NOT NULL,
           label   TEXT NOT NULL,
           PRIMARY KEY (project, ref, label)
       )""",
    # The board's own columns, in board order. A row per project, so two projects on one machine
    # may be renamed independently — which is what `columns:` in the registry already promises
    # every other board (C-14).
    """CREATE TABLE IF NOT EXISTS columns (
           project  TEXT NOT NULL,
           key      TEXT NOT NULL,
           name     TEXT NOT NULL,
           position INTEGER NOT NULL,
           PRIMARY KEY (project, key)
       )""",
    # Native parent→child linkage, the optional capability the splitter uses for idempotency.
    """CREATE TABLE IF NOT EXISTS links (
           project    TEXT NOT NULL,
           parent_ref INTEGER NOT NULL,
           child_ref  INTEGER NOT NULL,
           PRIMARY KEY (project, parent_ref, child_ref)
       )""",
)


def db_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Where `board.db` is — the registry's own resolution, for the same reasons.

    An explicit path is never second-guessed (`namespace.operator_path` states the rule); then the
    deployment's variable; then the operator's own directory beside `registry.yaml`, which is where
    a host installation's `project init`, `act`, `run`, `poll` and `serve` all look."""
    if explicit:
        return Path(explicit)
    if named := os.environ.get(PATH_ENV, "").strip():
        return Path(named)
    from openfactory import namespace

    return namespace.operator_path("board.db")


def now_iso() -> str:
    """`2026-09-09T12:34:56.789012+00:00` — the platform's timestamp, never SQLite's.

    NOT `CURRENT_TIMESTAMP`, and this is a correctness rule rather than a preference. SQLite writes
    `2026-09-09 12:34:56` — a SPACE, no offset — and the ADR-0048 sweep compares these as STRINGS
    (`knowledge/gather.py`) to decide whether a comment is newer than the question it answers.
    `'2026-09-09 12:35:00' <= '2026-09-09T12:30:00+00:00'` is true, because a space sorts below
    `T`, so an answer written five minutes AFTER the question would read as older than it and the
    person would be chased for an answer they had already given."""
    return datetime.now(UTC).isoformat()


@contextmanager
def connect(path: str | os.PathLike[str] | None = None,
            *, write: bool = False) -> Iterator[sqlite3.Connection]:
    """One connection, for one port call, with the discipline this file needs.

    ONE PER CALL rather than a pool or a module-level handle. A connection cached across calls is
    a connection held across a fork (the worker forks activities), across a request (the panel is
    async) and across a `docker compose exec` that has since exited — and SQLite's locking is
    per-connection, so a stale one is how the other two processes start seeing `database is
    locked` for a writer that went away.

    `write=True` opens the transaction with **BEGIN IMMEDIATE**, which is the whole reason this is
    a context manager. Two operations here READ A VALUE AND WRITE IT BACK — the next card number,
    and a column move that must not lose a concurrent one — and SQLite's default deferred
    transaction takes its write lock only at the first write, so two processes can both read `41`,
    both decide the next number is `42`, and the second one's INSERT fails or overwrites depending
    on the statement. `BEGIN IMMEDIATE` takes the lock at the top, so the second waits its
    `busy_timeout` and then reads `42`.

    The directory is created on demand: a host installation's `~/.openfactory/` exists because the
    registry made it, but a deployment that names `OPENFACTORY_BOARD_DB` somewhere else has no
    reason to have made it, and failing to open a database because its folder is missing is a
    remedy nobody can act on from the error sqlite3 gives."""
    target = Path(db_path(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        _to_wal(conn)
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys=ON")
        for statement in _SCHEMA:
            conn.execute(statement)
        if not write:
            yield conn
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
    finally:
        conn.close()


def _to_wal(conn: sqlite3.Connection) -> None:
    """Put the file in WAL, asking again while a neighbour is converting it.

    THE ONE STATEMENT THE BUSY HANDLER DOES NOT COVER. Every other lock here is waited out by
    `busy_timeout`; the WAL conversion needs a brief EXCLUSIVE lock and SQLite refuses that
    upgrade IMMEDIATELY rather than calling the handler. So two connections opening a brand-new
    file race for it, and the loser gets `database is locked` — from `connect`, before it has run
    anything.

    THIS IS A DEPLOYMENT'S FIRST MINUTE, NOT A TEST'S BAD LUCK. `board.db` does not exist yet on a
    fresh install, so the first concurrent opens ARE this race: the worker polling, the panel
    serving and a CLI verb in a shell, which is the arrangement this module's own docstring
    describes. Once the file is in WAL the pragma is a no-op and the race is gone, which is why it
    is rare and why it looked like a flaky test.

    MEASURED, INCLUDING THE FIX THAT DOES NOT WORK. Two threads opening a brand-new file, per
    variant:

        as it was, unconditional pragma              6 / 30 failed
        `busy_timeout` moved BEFORE the conversion   6 / 40 failed  (and 26/60 on the reviewer's
                                                                     machine — no better, likely
                                                                     worse)
        this: ask again while it is refused          0 / 60 failed

    Reordering is the obvious remedy and it is the wrong one: executing anything first takes a
    shared lock the conversion then has to break, and that upgrade is exactly what SQLite will not
    wait for. On an EXISTING file none of this arises — six processes writing 25 cards each
    produced 150 contiguous numbers, no duplicates, no failures.

    RAISES ON THE LAST TRY rather than degrading to a rollback journal: a file that is not in WAL
    would serialise the panel behind the worker, and the caller should hear that its database is
    genuinely wedged rather than silently getting the slower shape."""
    # THE EXHAUSTION RAISES WITHOUT CONSULTING THE BOUND, and a mutation is what taught the
    # difference. Written as `if attempt == _WAL_TRIES - 1: raise`, the loop's limit and its
    # give-up condition are two expressions that have to agree — cut the limit alone and the
    # function returns NORMALLY over a file it never converted, leaving the deployment in a
    # rollback journal with nobody told. Falling out of the loop cannot disagree with itself.
    last: sqlite3.OperationalError | None = None
    for _ in range(_WAL_TRIES):
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            last = exc
            time.sleep(_WAL_WAIT_S)
    raise last if last is not None else RuntimeError(
        "the journal mode was never set and nothing said why")


def next_ref(conn: sqlite3.Connection, project: str) -> int:
    """The next card number for this project — read and written inside the CALLER's transaction.

    `MAX(ref) + 1` rather than an autoincrement column, because the number is per PROJECT and one
    file holds several. It is safe only under `BEGIN IMMEDIATE`, which is why this takes an open
    connection instead of opening its own: a helper that opened its own would take the lock, drop
    it, and hand the caller a number another process could already have used."""
    row = conn.execute("SELECT MAX(ref) AS top FROM cards WHERE project = ?",
                       (project,)).fetchone()
    return int(row["top"] or 0) + 1
