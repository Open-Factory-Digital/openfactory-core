"""What a finished job SPENT — written by whichever driver finished it.

ONE DEFINITION, TWO DRIVERS, and the second one had none. The durable path records a ticket's
spend from `record_job_metrics`, a Temporal activity: one `agent_run` row per pass, one `job` row
for the attempt. The ATTENDED path — `openfactory run` and `openfactory poll` — records nothing,
and `poll` is the only scheduler a one-machine deployment has. So on the door with no operations
team, the door whose whole promise is that a solo developer can see the factory work, a card ran
to Done and the cost dashboard, `metrics_view`, and every measurement built on those rows saw a
day with no jobs and no spend (measured end to end on 2026-09-11: a real card, a real merge, one
row in the metrics database and it was a channel message).

That is the same defect `deployment_metrics_sink` was written to end, one caller over — *"a
second spender could not build a second sink"* — and it is repeated here as its own sentence: a
second driver must not have a second answer to what a job cost. Both call this.

BEST-EFFORT, ALWAYS. Telemetry is additive: a sink that cannot be built or written must never
change what happened to the job. The sinks already swallow their write errors; this also shields
building one and serialising the rows.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

log = logging.getLogger("openfactory.metrics")


def record_one_pass(*, project: str, ticket: str, role: str, result: object) -> None:
    """One agent invocation made OUTSIDE a job, recorded the way a job's passes are.

    THE SAME DOOR, AND THE SAME ROW SHAPE. A ticket's passes are recorded by `record_job` above;
    the ones made outside a ticket — the backfill's semantic passes, the knowledge gate's
    authoring, and now the single question `box prove` asks the harness — are this. They differ in
    what the `role` and `ticket` say, never in where they go: `deployment_metrics_sink` exists so
    a second spender cannot keep its own books, and a spend nobody can see is the defect the first
    live onboarding shipped (six paid passes, a dashboard showing a day with no spend).

    NONE IS "NOT MEASURED", NEVER ZERO — a harness that reports no cost leaves the field empty,
    because a free-looking harness would silently win every comparison the dashboard makes.

    BEST-EFFORT, like every other write on this axis: telemetry must never change what happened
    to the work it measures."""
    from datetime import UTC, datetime

    from openfactory.observability.metrics import MetricRecord
    from openfactory.observability.registry import deployment_metrics_sink

    try:
        deployment_metrics_sink().record(MetricRecord(
            project=project, ticket=ticket, ts=datetime.now(UTC).isoformat(),
            kind="agent_run", role=role,
            model=getattr(result, "model", None) or "",
            harness=getattr(result, "harness", None) or "",
            cost_usd=getattr(result, "cost_usd", None),
            num_turns=getattr(result, "num_turns", None),
            input_tokens=getattr(result, "input_tokens", None),
            output_tokens=getattr(result, "output_tokens", None)))
    except Exception as exc:  # noqa: BLE001 — telemetry is additive; never fail the work
        log.info("the %s pass for %s was not recorded (%s)", role, project, str(exc)[:160])


def record_job(*, project: str, issue: str, ts: str, state: str = "", title: str = "",
               wall_s: float | None = None, total_cost_usd: float | None = None,
               pr_url: str = "", knowledge: str = "",
               agent_runs: Iterable[object] = ()) -> None:
    """Persist one attempt: a row per agent invocation, then the job summary.

    `agent_runs` takes either `AgentRunMetric`s (what a `RunResult` carries) or the dicts an
    activity boundary hands over — the durable path serialises them to cross it and the attended
    path never leaves the process, and neither should have to know what the other does."""
    from openfactory.observability.metrics import MetricRecord
    from openfactory.observability.registry import deployment_metrics_sink

    try:
        sink = deployment_metrics_sink()
        for entry in agent_runs:
            run = entry if isinstance(entry, dict) else entry.model_dump()
            sink.record(MetricRecord(
                project=project, ticket=issue, ts=ts, kind="agent_run",
                role=run.get("role", ""), model=run.get("model", ""),
                harness=run.get("harness", ""),
                cost_usd=run.get("cost_usd"), num_turns=run.get("num_turns"),
                input_tokens=run.get("input_tokens"), output_tokens=run.get("output_tokens"),
                # `.get` and not `.get(..., 0)`: an absent dimension stays absent all the way to
                # the row, because a pass nobody could read must not average as a pass that did
                # nothing.
                tool_calls=run.get("tool_calls"), repeated_calls=run.get("repeated_calls"),
                refused_calls=run.get("refused_calls"),
                turns_to_first_edit=run.get("turns_to_first_edit")))
        sink.record(MetricRecord(
            project=project, ticket=issue, ts=ts, kind="job", role="_job_",
            state=state, title=title, wall_s=wall_s, total_cost_usd=total_cost_usd,
            pr_url=pr_url, knowledge=knowledge))
    except Exception as exc:  # noqa: BLE001 — telemetry is additive; never fail the job
        log.info("job telemetry for %s#%s was not recorded (%s)", project, issue, str(exc)[:160])
