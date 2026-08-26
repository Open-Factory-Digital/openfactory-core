"""Reading telemetry by KIND instead of scanning everything (ADR-0021).

Every tech-lead round and every product sweep asks the same question — "what am I still waiting
on?" — and the only way to answer it was `scan_records()`: a full table scan across every project,
every agent run, every job, since the beginning, filtered in Python. That is fine at today's volume
and quietly worse every week, on the one read path all of the agents' memory depends on.

The table already had the keys for this; nothing was querying them. The `by_kind` index adds
`kind_ts`, so one partition read returns exactly the rows a caller asked for.

DEGRADES TO A SCAN, BUT NEVER SILENTLY. Before the index exists — a checkout ahead of its
deployment, a local dev box, the window between a code deploy and a terraform apply — the query
fails and this falls back to scanning, saying so. A memory that quietly got slow is a memory that
stays slow, because nothing ever reports it.
"""

from __future__ import annotations

import logging

log = logging.getLogger("openfactory.metrics.query")

INDEX = "by_kind"


class StoreUnreadable(RuntimeError):
    """The store could not be read. NOT "the store is empty" (#126).

    THE TWO USED TO BE ONE VALUE, and on the panel that cost both halves of every human gate at
    once. `messages.read` returned `[]` on failure — and its own guard was already dead code,
    because this module and `sqlite_metrics._query` had swallowed to `[]` a layer below. So an
    unreadable store rendered as:

      - a factory with nothing to say (the pending questions simply were not in the inbox);
      - and a click on a question that WAS there refused with 409 "answered already", which blames
        the person for a decision they never made.

    Both halves of a human gate, silently, from one exception nobody saw. It is the same family as
    `_waiting_on_a_human` (an empty floor that was actually a TypeError) and as the ticket and
    board reads in `techlead/conversation.py`, which pay for this lesson in prose: on any path that
    gates a human decision, "nothing" and "could not look" must never be the same value.

    READS ONLY. Writes keep the never-raise rule — a factory that cannot record what it said must
    still say it — and that asymmetry is deliberate: a lost write costs a row, while a read that
    lies costs a decision.
    """


def records_of_kind(project: str, kind: str, *, limit: int = 500,
                    table_name: str | None = None, region: str | None = None) -> list[dict]:
    """Rows of one kind for one project, oldest first.

    RAISES `StoreUnreadable` when the store would not answer (#126). It used to return `[]` and a
    log line, on the reasoning that "only the log tells them apart" — which is true and is exactly
    the problem: no caller reads a log, so every one of them treated an outage as an empty memory.
    A caller that genuinely wants to degrade now says so in one line and MEANS it.

    `[]` still means empty, and one case is not a failure at all: no readable store configured. A
    deployment that never provisioned telemetry has nothing to read rather than something it
    cannot — and `metrics_view._configured_sink` says out loud when the configured sink is one
    that records and cannot be read back.

    THE SINK THE REGISTRY BUILT IS THE ONLY DOOR. This reader used to fall through to
    `OPENFACTORY_METRICS_TABLE` whenever the registry's sink could not read — so with the table
    variable set and the sink saying `null`, `memory` or a third-party row, a memory read reached
    for one vendor's client (probes A/B/D, 2026-08-24). An explicit `table_name` is the operator's
    override and is registry-shaped too: the CONFIGURED sink's kind pointed at that table
    (`configured_metrics_sink`), refused by name where that kind's add-on is absent — never a
    vendor's kind spelled here."""
    if table_name:
        from openfactory.observability.registry import configured_metrics_sink

        sink = configured_metrics_sink(table=table_name, region=region)
    else:
        from openfactory.api.metrics_view import _configured_sink

        sink = _configured_sink()
    if sink is None:
        return []
    return sink.records_of_kind(project, kind, limit=limit)
