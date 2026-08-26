"""Job/agent COST + effort telemetry — persisted per run so the panel can show spend by
period, model, and harness (product-grade cost dashboard).

One record per AGENT INVOCATION (planner / executor / repair / recovery / review / diagnose /
chat) tagged with its dimensions, plus one JOB-summary record. Sinks are pluggable behind one
Protocol — Null (local/off) and DynamoDB (the deployed store) now; the same Protocol admits
another backend later without touching callers (mirrors observability.events).

Schema (DynamoDB, single table `openfactory-job-metrics`, PAY_PER_REQUEST):
  pk = project                         (partition)
  sk = "<iso-ts>#<ticket>#<role>"      (time-sortable within a project)
  kind ∈ {"agent_run", "job"}          + the dimension attributes below
A scan + in-process aggregation powers the dashboard (low volume: dozens of jobs/day)."""

from __future__ import annotations

import logging
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

log = logging.getLogger("openfactory.metrics")

#: `agent_loop` = one row of the open-loop ledger (ADR-0021): something an agent did that expects
#: something back, and later the row that closes it by observation.
#: `techlead_watch` = what one round of the tech-lead's rounds already reported, so the next one
#: does not repeat it (observed in the client channel: the same park announced twice in 40 min).
#: `agent_run` = one invocation · `job` = a ticket's outcome · `product_sweep` = what the product
#: role saw the last time it looked at the board (its memory between passes). A closed set on
#: purpose: the dashboard selects by it, so a typo must fail here rather than write a row nothing
#: ever reads — which is exactly what an unlisted kind did, silently, until a sweep repeated its
#: introduction because it could not remember having arrived.
MetricKind = Literal["agent_run", "job", "product_sweep", "techlead_watch", "agent_loop",
                     "message", "channel_message"]


class MetricRecord(BaseModel):
    """One telemetry row. An `agent_run` carries the dimensions of a single agent invocation
    (the cost driver); a `job` summarizes the whole ticket attempt (final state + wall-clock).
    Every field is optional beyond the keys so a partial record never blocks the write."""

    project: str
    ticket: str
    ts: str  # ISO-8601 UTC — the sort key's time component
    kind: MetricKind = "agent_run"
    # dimensions (agent_run)
    role: str = ""            # planner | executor | repair | recovery | review | diagnose | chat
    model: str = ""           # opus | sonnet | haiku | …  (the tier the invocation used)
    harness: str = ""         # the adapter identity, e.g. "claude_code"
    cost_usd: float | None = None
    num_turns: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    # job-summary fields (kind="job")
    state: str = ""           # merged | on_hold | needs_refinement | …
    title: str = ""           # the ticket title, so the dashboard table reads on its own
    wall_s: float | None = None      # workflow start→close
    total_cost_usd: float | None = None
    pr_url: str = ""
    # Which A/B arm the ticket ran in: "off" | "injected" | "unavailable" (ADR-0017). This is the
    # dimension the Knowledge Layer's gate is measured on — without it the dashboard cannot tell
    # the arms apart and the experiment is unmeasurable. "" for pre-instrumentation rows.
    knowledge: str = ""
    #: Unix epoch SECONDS after which DynamoDB deletes this row (ADR-0024: client conversation is
    #: retained, not kept forever). Set ONLY on `kind="message"` — an operational-memory row that
    #: carried this would make the tech-lead forget what it learned. Rows without it never expire,
    #: which is why enabling TTL on this shared table is safe.
    expires_at: int | None = None
    extra: dict = Field(default_factory=dict)

    def dynamo_key(self) -> dict:
        """The item's keys, plus the index key the agents' memory is read by.

        `kind_ts` backs the `by_kind` GSI (ADR-0021). Without it, "what am I still waiting on?"
        can only be answered by scanning the whole table — every project, every agent run, every
        job, since the beginning — on the one read path all of the agents' memory depends on."""
        return {
            "pk": self.project,
            "sk": f"{self.ts}#{self.ticket}#{self.role or self.kind}",
            "kind_ts": f"{self.kind}#{self.ts}#{self.ticket}",
        }


@runtime_checkable
class MetricsSink(Protocol):
    def record(self, rec: MetricRecord) -> bool:
        """Persist one record; True only when it LANDED.

        `-> bool`, NOT `-> None`, and the sweep priced the difference (2026-08-16): the sinks
        swallow their own failures by design — telemetry must never fail a job — so with no return
        value every caller that promised "returns whether it landed" was counting attempts. One
        hundred panel-chat writes, ninety-nine rows, one hundred Trues: `messages.write` gates the
        operator's own conversation on this bool, and it was vacuous. Can the answer shape say it?
        This one could not."""
        ...


@runtime_checkable
class ReadableSink(Protocol):
    """A sink that can be READ BACK — the contract the dashboard and every agent memory rely on.

    ON THE PORT, NOT DISCOVERED BY `hasattr`. The two readers used to decide by attribute shape:
    `hasattr(sink, "scan")` to read at all, and `isinstance(getattr(sink, "table_name"), str)` to
    mean "this is DynamoDB, go through boto3" — two facts in one attribute name. A third-party
    sink with an ordinary `table_name` attribute was silently starved to `[]` or misrouted to a
    vendor's client (probes C and D, 2026-08-24). A sink says it can read by implementing these
    two methods; a sink that does not is not read as empty — `metrics_view._configured_sink` says
    so out loud and answers None.

    BOTH RAISE `query.StoreUnreadable` WHEN THE STORE WILL NOT ANSWER (#126). "Nothing recorded" and
    "could not look" are opposite facts on every path that gates a human decision.
    """

    def scan(self) -> list[dict]:
        """Every record, in the shape `api/metrics_view.dashboard` consumes (numbers as numbers)."""
        ...

    def records_of_kind(self, project: str, kind: str, *, limit: int = 500) -> list[dict]:
        """Rows of one kind for one project, oldest first, keeping the most RECENT `limit`."""
        ...


@runtime_checkable
class ForgettingSink(Protocol):
    """A sink that can DELETE one client's rows of one kind, and say how many went.

    A SEPARATE PROTOCOL, like `ConfirmingChannel` beside `ChannelAdapter`, so a sink is never
    forced to claim a capability it cannot honestly perform — an isinstance check that lies is
    worse than one that says no.

    WHY THIS EXISTS AT ALL. Deleting a client's conversation was implemented against DynamoDB
    DIRECTLY, while writing it went through the configured sink — so the platform recorded what a
    person said on every deployment and could only delete it on ours. The right to be forgotten
    is an obligation, not a feature, and an obligation that only holds on the vendor we happen to
    pay for is the core following our deployment instead of the other way round.

    IT RAISES ON FAILURE, and that is the one place in this module where the house rule inverts.
    Everything else here is best-effort: a telemetry write must never fail a job, so it logs and
    swallows. A DELETION may not do that. "Deleted 0 rows" returned from a store that threw is
    indistinguishable from a store that was already empty, and somebody answering a legal request
    in good faith would relay it as done.
    """

    def forget(self, project: str, *, kind: str) -> int: ...


class NullMetricsSink:
    """Default: drops records (local dev / metrics off). Never raises."""

    def record(self, rec: MetricRecord) -> bool:
        # False, honestly: nothing landed anywhere. A caller that promises "returns whether it
        # landed" must not be made a liar by the sink that never stores.
        return False

    def forget(self, project: str, *, kind: str) -> int:
        """0, AND IT IS THE TRUE ANSWER rather than a shrug. This sink dropped every record it was
        ever given, so there is nothing of this client anywhere in it — which is exactly what an
        operator answering a deletion request needs to hear. The dangerous version of this method
        is one on a sink that DID store something and returns 0 anyway."""
        return 0


class InMemoryMetricsSink:
    """Test/aggregation sink — keeps records in a list."""

    def __init__(self) -> None:
        self.records: list[MetricRecord] = []

    def record(self, rec: MetricRecord) -> bool:
        self.records.append(rec)
        return True

    def forget(self, project: str, *, kind: str) -> int:
        before = len(self.records)
        self.records = [r for r in self.records
                        if not (r.project == project and r.kind == kind)]
        return before - len(self.records)
