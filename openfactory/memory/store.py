"""Where the open loops live between rounds (ADR-0021 §3).

The same telemetry table everything else uses, because a loop ledger with its own infrastructure is
a second thing to deploy, secure and forget to provision — and the failure mode of forgetting is an
agent that silently stops remembering, which is precisely the defect this replaces.

APPEND-ONLY BY CONSTRUCTION. Nothing here updates a row: closing a loop writes a new one and `fold`
resolves them on read. That is not a limitation of the sink; it is the property that makes the
record trustworthy, so it is enforced here rather than left to callers.

BEST-EFFORT WRITES, LOUD FAILURES. A ledger write must never fail the work it describes — an agent
that cannot remember must still act. But it says so: a memory that quietly stops recording looks
exactly like an agent with nothing to remember, and that is the state this whole module exists to
make impossible.
"""

from __future__ import annotations

import logging

from openfactory.memory.ledger import Loop

log = logging.getLogger("openfactory.memory")

#: The telemetry `kind` these rows carry. Listed in `MetricKind`, because an unlisted kind is
#: written and never read — the dashboard selects by it, and a typo would produce a row nothing
#: queries. That exact bug already cost the product sweep its memory once.
LEDGER_KIND = "agent_loop"

#: How many rows to consider. Generous: the failures and questions worth learning from are the ones
#: that recur over weeks, and a window shorter than the problem is a memory that forgets on purpose.
READ_LAST = 500


def _row(loop: Loop) -> dict:
    """A loop as the flat string map telemetry stores. Everything is a string so the row survives a
    schema change without a migration — a ledger that needs one is a ledger that gets dropped."""
    out = {
        "loop_kind": loop.kind,
        "subject": loop.subject,
        "owner": loop.owner,
        "about": loop.about,
        "state": loop.state,
        "outcome": loop.outcome,
        "opened_ts": loop.ts,
        "chased_ts": loop.chased_ts,
    }
    for key, value in (loop.context or {}).items():
        out[f"ctx_{key}"] = str(value)
    return out


def _loop(extra: dict) -> Loop | None:
    """One stored row back into a loop, or None if it is not one. Never raises: a malformed row
    must cost that row, not the whole memory."""
    try:
        kind = str(extra.get("loop_kind") or "")
        if not kind:
            return None
        context = {k[4:]: str(v) for k, v in extra.items() if k.startswith("ctx_")}
        return Loop(
            kind=kind,
            subject=str(extra.get("subject") or ""),
            owner=str(extra.get("owner") or ""),
            about=str(extra.get("about") or ""),
            state=str(extra.get("state") or "open"),
            outcome=str(extra.get("outcome") or ""),
            ts=str(extra.get("opened_ts") or ""),
            chased_ts=str(extra.get("chased_ts") or ""),
            context=context,
        )
    except Exception as exc:  # noqa: BLE001 — one bad row must not cost the memory
        log.warning("skipping an unreadable ledger row (%s)", exc)
        return None


def read(project: str, *, scan=None) -> list[Loop]:
    """Every loop row for a project, oldest first — read by INDEX, not by scanning the table.

    An unreadable ledger returns nothing AND SAYS SO. Silence here would mean every remedy looks
    untried and every question unasked — the agents would carry on, correctly but with amnesia, and
    nothing would indicate why.

    THAT GUARD ONLY STARTED WORKING IN #126. `records_of_kind` and `sqlite_metrics._query` both
    swallowed to `[]` below this, so the `except` was unreachable and the log line it exists to
    emit had never been written. Degrading here is still the right call — an agent pass that stops
    because the memory is down is worse than one that proceeds without it — but it is now a choice
    this function makes rather than one made for it by a layer that told it nothing."""
    try:
        if scan is None:
            from openfactory.observability.query import records_of_kind

            rows = records_of_kind(project, LEDGER_KIND, limit=READ_LAST)
        else:  # tests hand in their own rows
            rows = [
                r for r in scan()
                if r.get("kind") == LEDGER_KIND
                and str(r.get("pk") or r.get("project") or "") == project
            ]
            rows.sort(key=lambda r: str(r.get("ts") or ""))
            rows = rows[-READ_LAST:]
        out = [_loop(r.get("extra") or {}) for r in rows]
        return [loop for loop in out if loop is not None]
    except Exception as exc:  # noqa: BLE001
        log.error(
            "COULD NOT READ THE LOOP LEDGER for %s (%s) — the agents will act correctly but with "
            "no memory: every remedy will look untried and every question unasked", project, exc)
        return []


def write(project: str, loops: list[Loop], *, sink=None, now: str | None = None) -> int:
    """Append rows. Returns how many landed.

    THE ROW'S `ts` IS WHEN IT WAS RECORDED, not when the loop opened. The loop's own opening time
    travels in `opened_ts` and is its identity; the row's timestamp is a fact about the row. An
    earlier version reused the loop's `ts` and appended the state to force uniqueness — which made
    a closing row sort BEFORE the opening it resolves, quietly inverting the ledger's chronology.

    Never raises: an agent that cannot remember must still be able to act. But a failure is logged
    at error, because the symptom of a silent one is an agent that has quietly become the thing it
    replaced."""
    if not loops:
        return 0
    try:
        from openfactory.observability.metrics import MetricRecord

        if sink is None:
            from openfactory.runtime.temporal.activities import _metrics_sink

            sink = _metrics_sink()
        if now is None:
            from datetime import UTC, datetime

            now = datetime.now(UTC).isoformat()
        written = 0
        for index, loop in enumerate(loops):
            sink.record(MetricRecord(
                project=project,
                # the index disambiguates rows written in the same microsecond — two loops closed
                # by one pass must not collapse into a single item
                ticket=f"{loop.subject or '_loop_'}.{index}",
                ts=now,
                kind=LEDGER_KIND,
                role=loop.owner or "_loop_",
                extra=_row(loop),
            ))
            written += 1
        return written
    except Exception as exc:  # noqa: BLE001
        log.error(
            "COULD NOT RECORD %d loop(s) for %s (%s) — those actions happened but nothing will "
            "follow them up: a remedy will look untried, a question will look unasked",
            len(loops), project, exc)
        return 0
