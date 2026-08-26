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
_NUMERIC = ("cost_usd", "total_cost_usd", "wall_s", "num_turns", "input_tokens", "output_tokens")

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
CREATE INDEX IF NOT EXISTS metrics_expiry  ON metrics (expires_at);
"""


class SqliteMetricsSink:
    """A `MetricsSink` that also reads. Safe to construct anywhere: it touches no disk until used.

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
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=self.timeout)
        try:
            conn.execute("PRAGMA journal_mode=WAL")  # readers do not block the writer
            conn.execute("PRAGMA synchronous=NORMAL")  # telemetry does not deserve an fsync a row
            if write:
                conn.executescript(_SCHEMA)
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
            log.warning("metrics read failed on %s: %s", self.path, exc)
            raise StoreUnreadable(f"could not read the metrics store at {self.path}: {exc}") \
                from exc
