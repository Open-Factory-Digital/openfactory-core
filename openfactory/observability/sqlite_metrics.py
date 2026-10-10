"""The same telemetry, on a machine with no AWS (C-11).

The cost dashboard is `architecture.md` §8's *"ruler we measure improvements with"*, and a
distribution that cannot render it is not a factory anybody can operate. DynamoDB is the deployed
store; this is the one that needs no service, no credentials and no network — which is what makes
`docker compose up` a real product rather than a demo.

WHY THIS IS NOT "WRITE ROWS TO A FILE". The Dynamo sink has four behaviours the dashboard and the
agents' memory depend on without ever saying so, and none of them is a property of SQLite:

    put_item OVERWRITES on the key      a retried activity must not double-count a job's cost
    TTL DELETES expired rows            ADR-0024 — client conversation is retained, not kept
    numbers survive the round trip      stored as strings there, parsed back by the reader
    a write failure never fails a job   telemetry is additive

The TTL one is the trap. Nothing raises and nothing logs if it is missed: the deployment simply
keeps client messages for ever while its own ADR says otherwise, and the first person to find out
is a client asking how long their data is held. So `expires_at` is honoured on every read AND
`purge_expired()` removes the bytes — filtering keeps the answer right, deleting keeps the promise.

SHAPE, NOT SCHEMA. Readers (`api/metrics_view.scan_records`, `observability/query.records_of_kind`)
consume `list[dict]` carrying DynamoDB's own keys. This store returns exactly that shape, so it is
a swap rather than a migration. The row is stored as JSON with the queried fields lifted into
columns; both are written from one `model_dump()` so they cannot drift.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from openfactory.observability.metrics import MetricRecord

log = logging.getLogger("openfactory.metrics")

#: Numbers the dashboard reads. DynamoDB stores them as strings and `scan_records` parses them
#: back; here JSON keeps them native, so this list exists to REJECT a string that sneaks in rather
#: than to convert one — a cost rendered as 0.00 is the failure this prevents.
_NUMERIC = ("cost_usd", "total_cost_usd", "wall_s", "num_turns", "input_tokens",
            "output_tokens", "tool_calls", "repeated_calls", "refused_calls",
            "turns_to_first_edit")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
    pk         TEXT    NOT NULL,          -- project
    sk         TEXT    NOT NULL,          -- <ts>#<ticket>#<role|kind>
    kind       TEXT    NOT NULL,
    ts         TEXT    NOT NULL,
    ticket     TEXT    NOT NULL,
    expires_at INTEGER,                   -- NULL = never expires
    data       TEXT    NOT NULL,          -- the whole record, as written
    PRIMARY KEY (pk, sk)                  -- == put_item: a retry replaces, never appends
);
CREATE INDEX IF NOT EXISTS metrics_by_kind ON metrics (pk, kind, ts);
CREATE INDEX IF NOT EXISTS metrics_by_ticket_key ON metrics (pk, kind, ticket, sk);
CREATE INDEX IF NOT EXISTS metrics_expiry  ON metrics (expires_at);
"""


#: The files whose schema this process has already made sure of, for READS (#137). A write applies
#: the schema every time, as it always has; a read applies it once per file per process, so the
#: panel — which reads on every request — pays for the `CREATE ... IF NOT EXISTS` once.
#:
#: WHAT BOUNDS IT: the path in `OPENFACTORY_METRICS_DB`, which a deployment declares and traffic
#: cannot change — one entry, in practice. It is declared in `tests/test_no_unbounded_growth.py`
#: like every other module-level cache; that guard could not see a set until #158's review, and
#: now can.
_SCHEMA_ENSURED: set[str] = set()


class SqliteMetricsSink:
    """A `MetricsSink` that also reads. Safe to construct anywhere: it touches no disk until used —
    and the first use, read or write, makes sure the table exists (#137).

    Two processes share the file — the worker writes while the panel reads — so every connection
    opens in WAL mode with a busy timeout. Without those, "database is locked" appears under
    concurrency, in production, and never in a single-process test.

    A connection is opened per operation rather than held. SQLite connections are not shareable
    across threads, and the panel serves requests on several; a cached connection would be a
    latent `ProgrammingError` that only appears once two requests overlap.
    """

    def __init__(self, path: str | Path, *, timeout: float = 5.0) -> None:
        self.path = Path(path)
        self.timeout = timeout

    # ── plumbing ────────────────────────────────────────────────────────────────────────────────

    @contextmanager
    def _connect(self, *, write: bool) -> Iterator[sqlite3.Connection]:
        """One connection for one operation — and, on a READ, the schema too, once (#137).

        A FRESH INSTALL WAS A PERMANENT ERROR STATE. The schema was applied only when writing, and
        nothing writes a metric until a job runs, so on a deployment that had run nothing yet every
        read failed with `no such table: metrics`: the panel logged it on essentially every request,
        and the people store — read on every request to decide whether the panel is open — said it
        was unreadable, so nobody registered by invitation could be identified. A store nobody has
        written to is EMPTY, not unreadable, and the table that says so costs one
        `CREATE ... IF NOT EXISTS`.

        A store that cannot take the schema — a read-only directory, a file that is not a database —
        is still read, and the read says what it finds: `StoreUnreadable`, never a silent `[]`."""
        key = str(self.path)
        ensure = write or key not in _SCHEMA_ENSURED
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        elif ensure:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:   # the connect below fails honestly and names the file
                log.info("metrics store %s: could not create its directory for a read — %s",
                         self.path, exc)
        conn = sqlite3.connect(self.path, timeout=self.timeout)
        try:
            conn.execute("PRAGMA journal_mode=WAL")  # readers do not block the writer
            conn.execute("PRAGMA synchronous=NORMAL")  # telemetry does not deserve an fsync a row
            if write:
                conn.executescript(_SCHEMA)
                _SCHEMA_ENSURED.add(key)
            elif ensure:
                try:
                    conn.executescript(_SCHEMA)
                    _SCHEMA_ENSURED.add(key)
                except sqlite3.Error as exc:   # the read below says what it finds
                    log.info("metrics store %s: could not apply its schema for a read — %s",
                             self.path, exc)
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _row(data: str) -> dict:
        rec = json.loads(data)
        for k in _NUMERIC:
            v = rec.get(k)
            if isinstance(v, str):  # a stringified number would render as zero and say nothing
                try:
                    rec[k] = float(v) if "." in v else int(v)
                except ValueError:
                    rec[k] = None
        return rec

    # ── write ───────────────────────────────────────────────────────────────────────────────────

    def record(self, rec: MetricRecord) -> bool:
        """Persist one record; True only when it landed. **Never raises** — telemetry is
        additive, and a job abandoned because a metrics write failed has confused what the
        platform is for with what it reports. The failure is logged AND returned, because the
        panel-chat path gates "your message was recorded" on this answer and counted attempts
        for as long as there was nothing to count (sweep B4, 2026-08-16)."""
        try:
            key = rec.dynamo_key()
            payload = {**rec.model_dump(), **key}
            with self._connect(write=True) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO metrics"
                    " (pk, sk, kind, ts, ticket, expires_at, data) VALUES (?,?,?,?,?,?,?)",
                    (key["pk"], key["sk"], rec.kind, rec.ts, rec.ticket, rec.expires_at,
                     json.dumps(payload, default=str)),
                )
            return True
        except Exception as exc:  # noqa: BLE001 — never fail the job for telemetry
            log.warning("metrics write failed for %s#%s: %s", rec.project, rec.ticket, exc)
            return False

    def record_if_absent(self, rec: MetricRecord, *, key: str) -> bool:
        """Write `rec` under `key` only if no row of its project holds that key (`KeyedSink`).

        A PLAIN `INSERT`, NOT `record`'s `INSERT OR REPLACE` — the primary key `(pk, sk)` is the
        condition, so the second of two writers racing for one key is refused by the database
        itself, inside one statement, and no read-then-write window exists to lose. The keys a
        caller chooses never begin with a digit (`lifecycle/record.py`), so they cannot meet a
        time-keyed row's `sk`.

        RAISES `StoreUnreadable` on anything but the collision, unlike `record`: this write is a
        person's decision being recorded, and "the store could not take it" must not read as
        "somebody else's decision came first"."""
        from openfactory.observability.query import StoreUnreadable

        payload = {**rec.model_dump(), "pk": rec.project, "sk": key}
        try:
            with self._connect(write=True) as conn:
                conn.execute(
                    "INSERT INTO metrics (pk, sk, kind, ts, ticket, expires_at, data)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (rec.project, key, rec.kind, rec.ts, rec.ticket, rec.expires_at,
                     json.dumps(payload, default=str)),
                )
            return True
        except sqlite3.IntegrityError:
            return False
        except Exception as exc:
            log.warning("keyed metrics write failed for %s %s: %s", rec.project, key, exc)
            raise StoreUnreadable(f"could not write to the metrics store at {self.path}: "
                                  f"{exc}") from exc

    def records_under(self, project: str, prefix: str) -> list[dict]:
        """Every row of `project` whose key starts with `prefix`, in key order (`KeyedSink`).

        A RANGE ON THE PRIMARY KEY, not `LIKE`: `prefix` is the caller's text (a card's ref can
        hold `%` or `_` on a hosted tracker), and `[prefix, prefix + U+FFFF)` is every key that
        starts with it, read from the index the table already has."""
        return self._query(
            "SELECT data FROM metrics WHERE pk = ? AND sk >= ? AND sk < ? ORDER BY sk",
            (project, prefix, prefix + "￿"))

    def forget(self, project: str, *, kind: str) -> int:
        """Delete every row of one kind for one client, and say how many went.

        NO `try` HERE, and it is the only method in this class without one — read `purge_expired`
        right below it for the contrast. Everything else in this file degrades to 0 or `[]`
        because telemetry must never fail the work it describes. A DELETION may not: "0 rows" from
        a store that threw looks exactly like a store that was already empty, and an operator
        answering a legal request would relay it as done. This is the same store the OSS
        distribution ships with (`OPENFACTORY_METRICS_SINK=sqlite` in the compose file), so until
        this
        existed a deployment off our own cloud could record a client's words and had no way to
        delete them.

        The index `metrics_by_kind (pk, kind, ts)` is what makes this a bounded delete rather than
        a table scan — the same shape the DynamoDB sink gets from its `by_kind` GSI.
        """
        with self._connect(write=True) as conn:
            cur = conn.execute("DELETE FROM metrics WHERE pk = ? AND kind = ?", (project, kind))
            return cur.rowcount or 0

    def backup(self, to: str | Path) -> Path:
        """A consistent copy of the whole store at `to`, taken through SQLite's own online backup
        — and RAISES, like `forget`, because it is the step a deletion stands on (#453).

        NOT A FILE COPY. The worker writes this file while the panel reads it, in WAL mode, so the
        rows of the last few seconds live in `-wal` beside it: a `shutil.copy` of the main file
        alone is a backup missing exactly what was written last, and a copy taken mid-checkpoint
        is a file that may not open. `Connection.backup` copies pages under SQLite's own locks and
        restarts when a writer changes one underneath it, so what lands is one moment of the
        store, whole."""
        target = Path(to)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._connect(write=False) as conn:
            copy = sqlite3.connect(target)
            try:
                conn.backup(copy)
            finally:
                copy.close()
        return target

    def purge_expired(self, *, now: int | None = None) -> int:
        """Delete rows past their TTL, returning how many went. Filtering on read keeps the answer
        correct; only this keeps the promise — "we delete it" has to mean the bytes are gone."""
        try:
            with self._connect(write=True) as conn:
                cur = conn.execute("DELETE FROM metrics WHERE expires_at IS NOT NULL"
                                   " AND expires_at <= ?", (now if now is not None else
                                                            int(time.time()),))
                return cur.rowcount or 0
        except Exception as exc:  # noqa: BLE001
            log.warning("metrics purge failed: %s", exc)
            return 0

    # ── read ────────────────────────────────────────────────────────────────────────────────────

    def scan(self) -> list[dict]:
        """Every live record, in the shape `api/metrics_view.scan_records` returns.

        RAISES `StoreUnreadable` when the file will not answer (#126). The caller that wants "no
        data yet" — the dashboard — catches it there, which is one line and is the difference
        between a surface CHOOSING to degrade and every surface degrading because it was never
        told anything went wrong."""
        return self._query(
            "SELECT data FROM metrics WHERE (expires_at IS NULL OR expires_at > ?)"
            " ORDER BY pk, sk", (int(time.time()),))

    def records_of_kind(self, project: str, kind: str, *, limit: int = 500) -> list[dict]:
        """Rows of one kind for one project, **oldest first**, keeping the most RECENT `limit`.

        The ordering is not cosmetic and `query.py` makes the same choice deliberately: a memory
        truncated to its oldest rows remembers the beginning of time and nothing about now."""
        rows = self._query(
            "SELECT data FROM metrics WHERE pk = ? AND kind = ?"
            " AND (expires_at IS NULL OR expires_at > ?)"
            " ORDER BY ts DESC, sk DESC LIMIT ?",
            (project, kind, int(time.time()), max(0, limit)))
        return list(reversed(rows))

    def records_of_ticket(self, project: str, kind: str, ticket: str, *, before: str = "",
                          limit: int = 50) -> list[dict]:
        """Rows of one kind under one ticket, **oldest first**, keeping the most RECENT `limit`
        whose key comes before `before` (`TicketReadingSink`, #566) — one conversation read by its
        key, a page at a time, through `metrics_by_ticket_key`. THE CURSOR IS THE ROW'S `sk`
        (`<ts>#<ticket>#<role>`), the primary key: unique, and ordered as the conversation was
        written, so a page boundary never skips nor repeats a row — a `ts` alone could tie."""
        # THE INDEX IS ON THE KEY (review of #581): one on `ts` was never consulted — the planner
        # took the primary key on `pk` alone and walked the project's whole partition, every kind,
        # for every page. On `(pk, kind, ticket, sk)` it seeks the conversation and reads it in key
        # order, so the LIMIT stops after one page. TWO STATEMENTS, because `(? = '' OR sk < ?)`
        # keeps SQLite from using `sk < ?` as a range: a page far back cost every newer row.
        live = " AND (expires_at IS NULL OR expires_at > ?)"
        if before:
            rows = self._query(
                "SELECT data FROM metrics WHERE pk = ? AND kind = ? AND ticket = ? AND sk < ?"
                + live + " ORDER BY sk DESC LIMIT ?",
                (project, kind, ticket, before, int(time.time()), max(0, limit)))
        else:
            rows = self._query(
                "SELECT data FROM metrics WHERE pk = ? AND kind = ? AND ticket = ?"
                + live + " ORDER BY sk DESC LIMIT ?",
                (project, kind, ticket, int(time.time()), max(0, limit)))
        return list(reversed(rows))

    def _query(self, sql: str, args: tuple) -> list[dict]:
        """RAISES `StoreUnreadable`. See `scan` — and note that this method is the LAYER the panel's
        human gates were blinded by: it returned `[]`, so `messages.read`'s own careful guard was
        dead code that could never fire, and an unreadable file reached the operator as a factory
        with nothing to say and a question that had "already been answered"."""
        from openfactory.observability.query import StoreUnreadable

        try:
            with self._connect(write=False) as conn:
                return [self._row(r[0]) for r in conn.execute(sql, args).fetchall()]
        except Exception as exc:
            # a file replaced or deleted while this process ran loses its table: make sure again
            # on the next read rather than failing on every one for the life of the process
            _SCHEMA_ENSURED.discard(str(self.path))
            log.warning("metrics read failed on %s: %s", self.path, exc)
            raise StoreUnreadable(f"could not read the metrics store at {self.path}: {exc}") \
                from exc
