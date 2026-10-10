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
            pr_url=pr_url, knowledge=knowledge, extra={"platform": platform_stamp()}))
    except Exception as exc:  # noqa: BLE001 — telemetry is additive; never fail the job
        log.info("job telemetry for %s#%s was not recorded (%s)", project, issue, str(exc)[:160])


def platform_stamp() -> dict[str, str]:
    """WHICH PLATFORM RAN THE ATTEMPT: the package's version and the image's build code (`""`
    outside a built image), on every `job` row (#356).

    NOTHING RECORDED IT. A deployment that stays current is one of the partner program's
    thresholds, and "which versions ran here over the last ninety days" was answerable only from
    the operator's memory: the build stamp lived in one file the image writes, read by whoever
    asked at that moment, and no row of what a job did said which code did it. The outcome
    aggregates read this back (`query.outcomes`); a row written before it carries none and is
    counted as UNSTAMPED, never as some version."""
    from openfactory import __version__, namespace

    code, _built = namespace.build_stamp()
    return {"version": __version__, "build": code}


#: Who signs a job's ending when the attended driver ran it — `openfactory run` or `openfactory
#: poll`, a one-machine deployment's scheduler (#551). The workflow signs `the workflow`.
BY_THE_ATTENDED_DRIVER = "the attended driver"


def record_ending(project, issue: str, state: str, *, by: str, note: str = "") -> str:
    """Append a job's ENDING to its card's journal — a `state` line that carries `by` — and return
    the state written. RAISES what the journal raises: each caller decides what a failure means.

    THE ONE WRITER OF THE LINE `query.outcomes` READS AS AN ENDING (#551), for the same reason
    `record_job` is one function: two drivers, and the second one had none. The workflow wrote it
    from `record_outcome` at the job's one exit; the attended driver — `openfactory run` and
    `openfactory poll`, the only scheduler a one-machine deployment has — wrote nothing. So there
    every job read as "without a recorded ending", `jobs` was 0, and an evidence pack's activity
    threshold failed however much work the deployment did. Both drivers write through here, so a
    second one cannot grow a second shape of the line.

    APPENDS, NEVER REWRITES: the box's own `state` lines say how far the job got, and carry a
    `reason`, never a `by` (`machine._set_state`); this adds what it became."""
    from openfactory.observability.events import JobEvent, now_iso
    from openfactory.observability.registry import journal_for
    from openfactory.paths import events_file

    journal_for(events_file(project, issue)).emit(JobEvent(
        ts=now_iso(), job_id=f"#{issue}", ticket_id=f"#{issue}", kind="state", message=state,
        data={"reason": (note or "").strip() or None, "by": by}))
    return state
