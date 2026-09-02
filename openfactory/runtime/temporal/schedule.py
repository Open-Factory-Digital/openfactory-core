"""Create/refresh the poller Schedule — the heartbeat of full autonomy (A1).

    python -m openfactory.runtime.temporal.schedule [--every-minutes 3] [--sandbox fargate]

Idempotent: updates the schedule if it already exists. Overlap policy SKIP — a tick
that fires while the previous one still runs is dropped (the next one catches up),
so a slow scan can never pile up. Pause/resume any time in the Temporal UI.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import timedelta

from dotenv import load_dotenv
from temporalio.api.workflowservice.v1 import (
    DescribeNamespaceRequest,
    UpdateNamespaceRequest,
)
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleUpdate,
)

from openfactory.runtime.temporal import TASK_QUEUE
from openfactory.runtime.temporal.connection import connect
from openfactory.runtime.temporal.io import PollInput

log = logging.getLogger("openfactory.schedule")

SCHEDULE_ID = "openfactory-poller"

#: The product role's board sweep. Its own schedule, per project, because its cadence is a
#: judgement about people rather than about throughput: a poll every three minutes keeps the floor
#: busy, while a report every three minutes trains everyone to ignore it.
PRODUCT_SCHEDULE_PREFIX = "openfactory-product-sweep"

#: WEEKLY. Every finding this sweep reports is rot — a ticket nobody can finish because nobody wrote
#: what "done" means, a decision nobody made, work that ended and nobody closed. That decays over
#: weeks, not hours, so a daily pass would mostly be the same list again. It reports only what is
#: NEW and summarises the rest as counts, which makes even this cadence quiet most weeks.
PRODUCT_EVERY_HOURS = 24 * 7

#: The tech-lead's rounds. HOURLY, not weekly: a park holding the single-line floor costs capacity
#: every hour it sits — #478 cost eighteen — while a rotting backlog costs over weeks. Two watchers,
#: two cadences, because they watch things that decay at different speeds.
WATCH_SCHEDULE_PREFIX = "openfactory-techlead-watch"
WATCH_EVERY_HOURS = 1

#: The knowledge bundle, brought current against the base branch. SIX-HOURLY, and the number is
#: chosen by what it costs rather than by how fast a repository moves: a tick over a repository
#: nobody pushed to clones, walks, finds `derived_key` unchanged and publishes NOTHING
#: (`knowledge/bundle.py`), so the cost of being wrong about the cadence is a clone, not a commit.
#: The map only has to be current before the NEXT ticket reads it, and a ticket every six hours is
#: already a busy floor for a single-line deployment.
OKF_SCHEDULE_PREFIX = "openfactory-okf-refresh"
OKF_EVERY_HOURS = 6


def _schedule(every_minutes: int, sandbox: str | None) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            "PollWorkflow",
            # None → PollInput's own default_factory reads OPENFACTORY_SANDBOX, so a
            # deployment configures its box in ONE place instead of here as well.
            PollInput(**({"sandbox": sandbox} if sandbox else {})),
            id="openfactory-poll",
            task_queue=TASK_QUEUE,
            # A poll is a quick board scan (seconds). Cap the whole run below the tick
            # interval so a poll that HANGS (or repeatedly fails its workflow task —
            # e.g. an unregistered type after a bad deploy) times out and lets the next
            # tick run fresh, instead of a stuck run blocking every future poll under the
            # SKIP overlap policy. (engineering.md #8 — bound every wait.)
            execution_timeout=timedelta(minutes=2),
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=timedelta(minutes=every_minutes))]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


async def ensure_poller(*, every_minutes: int = 3, sandbox: str | None = None) -> str:
    """The poller schedule, CREATED IF MISSING and otherwise left exactly as it is.

    Deliberately not create-or-update like the other two. The poller's interval is a live
    operational dial somebody may have turned in the Temporal UI during an incident, and a worker
    boot silently resetting it to the source default is how a deploy undoes a decision nobody
    remembers making. A fresh deployment still self-provisions; a running one is not touched."""
    client = await connect()
    try:
        await client.create_schedule(SCHEDULE_ID, _schedule(every_minutes, sandbox))
        return f"created {SCHEDULE_ID}"
    except ScheduleAlreadyRunningError:
        return f"kept {SCHEDULE_ID}"


async def ensure_all() -> list[str]:
    """Every schedule this codebase expects to exist, reconciled at worker boot.

    THIS FUNCTION EXISTS BECAUSE OF A REAL DEFECT CLASS. `ensure_techlead_watch` and
    `ensure_product_sweeps` were written, tested, registered as workflows — and called by nothing,
    so the tech-lead's rounds and the product sweep would simply never have fired. A capability
    nobody can reach is indistinguishable from a capability that does not exist, and it is worse,
    because the tests are green. Reconciling at boot ties every schedule's existence to a deploy,
    which is the one event guaranteed to happen."""
    out: list[str] = []
    out.append(await ensure_retention())
    out.append(await ensure_poller())
    out += await ensure_techlead_watch()
    out += await ensure_product_sweeps()
    out += await ensure_okf_refresh()
    out += await retire_orphan_schedules()
    return out


#: How long the engine must remember a finished job, in days. A DEPLOYMENT DECLARES IT and this
#: module makes it true — the same shape every schedule here uses, and for the same reason: a
#: value that is only set at creation time is a value that is wrong on every deployment that
#: already exists.
RETENTION_DAYS = int(os.environ.get("OPENFACTORY_ENGINE_RETENTION_DAYS") or 30)


async def ensure_retention() -> str:
    """Raise the namespace's history retention to what this deployment declares. Never lowers it.

    THE DEFECT THIS CLOSES (pilot, 2026-08-17). `temporalio/auto-setup` creates the namespace with
    a **24-hour** retention. Two tickets ran on the 16th; the operator opened the panel ~26h later
    and the floor said *"nothing shipped yet"* — a claim, and a false one, about a factory that had
    shipped both. The engine had genuinely forgotten them; the journals on disk had not.

    RAISES, NEVER LOWERS. An operator who deliberately set a longer window on their own namespace
    (or a Temporal Cloud namespace governed by somebody's retention policy) must not have it cut
    by a platform default they never asked for — and a shorter number here would be this code
    deleting history, which is not a thing a boot-time reconciler should ever do.

    BEST-EFFORT AND SAID OUT LOUD. A namespace this credential may not administer — Temporal Cloud
    with a read-only role — is a legitimate deployment, not a failure; it returns the sentence and
    the worker starts. What it must never do is fail silently, because the symptom is a floor that
    quietly forgets a day later and reports the forgetting as "nothing shipped".
    """
    from temporalio.service import RPCError

    want = timedelta(days=max(1, RETENTION_DAYS))
    client = await connect()
    try:
        described = await client.service_client.workflow_service.describe_namespace(
            DescribeNamespaceRequest(namespace=client.namespace))
        current = described.config.workflow_execution_retention_ttl.ToTimedelta()
    except (RPCError, Exception) as exc:  # noqa: BLE001 — an unreadable namespace is not a crash
        log.warning("could not read %s's retention (%s) — leaving it alone", client.namespace, exc)
        return f"retention unread on {client.namespace}"
    if current >= want:
        return f"retention {current.days}d on {client.namespace} (>= the declared {want.days}d)"
    try:
        request = UpdateNamespaceRequest(namespace=client.namespace)
        request.config.workflow_execution_retention_ttl.FromTimedelta(want)
        await client.service_client.workflow_service.update_namespace(request)
    except Exception as exc:  # noqa: BLE001 — a namespace we may not administer is a real shape
        log.warning(
            "OPENFACTORY_RETENTION_NOT_RAISED %s keeps %sh of history and this deployment asked "
            "for %sd (%s) — finished jobs will vanish from the floor that soon; the Logs page "
            "reads the journals on disk and still has them",
            client.namespace, int(current.total_seconds() // 3600), want.days, str(exc)[:160])
        return f"retention {current.days}d on {client.namespace} — could NOT raise to {want.days}d"
    log.warning("raised %s's history retention from %sh to %sd", client.namespace,
                int(current.total_seconds() // 3600), want.days)
    return f"retention raised to {want.days}d on {client.namespace}"


async def retire_orphan_schedules() -> list[str]:
    """Delete our per-project schedules whose project is no longer registered.

    RECONCILE MEANS BOTH DIRECTIONS, and this half was missing: `ensure_*` creates and updates,
    and nothing ever removed. So a project renamed, removed, or moved to another deployment left
    its watch and its sweep running for ever — each firing on schedule, each failing with
    `KeyError: project not registered`, each a red line in the log that means nothing and is
    indistinguishable from one that does.

    Found live: a `openfactory-product-sweep-<project>` schedule for a client project that had been
    removed, firing hourly on a stack whose registry holds six fixture projects and not that one.

    NARROW ON PURPOSE. Only ids carrying our own per-project prefixes are ever considered, and
    only when the project behind the id is absent from the registry — a schedule this code did not
    create is not this code's to delete, and an unreadable registry deletes nothing rather than
    everything.
    """
    from openfactory.registry import ProjectRegistry

    try:
        known = {p.name for p in ProjectRegistry().list()}
    except Exception as exc:  # noqa: BLE001 — an unreadable registry must not look like "no
        log.warning("could not read the registry; retiring no schedule (%s)", exc)  # projects"
        return []
    if not known:
        return []  # the same reasoning: an empty answer is not evidence of absence

    client = await connect()
    retired: list[str] = []
    for prefix in (WATCH_SCHEDULE_PREFIX, PRODUCT_SCHEDULE_PREFIX, OKF_SCHEDULE_PREFIX):
        async for sched in await client.list_schedules():
            sid = str(getattr(sched, "id", ""))
            if not sid.startswith(f"{prefix}-"):
                continue
            owner = sid[len(prefix) + 1:]
            if owner in known:
                continue
            try:
                await client.get_schedule_handle(sid).delete()
                retired.append(f"retired {sid} (no project {owner!r})")
                log.warning("OPENFACTORY_ORPHAN_SCHEDULE %s fired for a project this deployment "
                            "does "
                            "not have — deleted", sid)
            except Exception as exc:  # noqa: BLE001 — a failed delete is a log line, not an outage
                log.warning("could not retire the orphan schedule %s (%s)", sid, exc)
    return retired


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--every-minutes", type=int, default=3)
    ap.add_argument("--sandbox", default=None,
                    help="box kind; defaults to $OPENFACTORY_SANDBOX, else container")
    args = ap.parse_args()

    load_dotenv()
    client = await connect()
    sched = _schedule(args.every_minutes, args.sandbox)
    try:
        await client.create_schedule(SCHEDULE_ID, sched)
        print(f"schedule {SCHEDULE_ID!r} created — every {args.every_minutes}min")
    except ScheduleAlreadyRunningError:
        handle = client.get_schedule_handle(SCHEDULE_ID)
        await handle.update(lambda _: ScheduleUpdate(schedule=sched))
        print(f"schedule {SCHEDULE_ID!r} updated — every {args.every_minutes}min")
    for line in (await ensure_techlead_watch() + await ensure_product_sweeps()
                 + await ensure_okf_refresh()):
        print(line)


if __name__ == "__main__":
    asyncio.run(main())


def _product_schedule(project_name: str, every_hours: int) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            "ProductSweepWorkflow",
            project_name,
            id=f"{PRODUCT_SCHEDULE_PREFIX}-{project_name}",
            task_queue=TASK_QUEUE,
            # Bounded for the same reason as the poller's (lines above): a run whose workflow
            # task cannot complete (unregistered type after a bad deploy, non-determinism) stays
            # open FOREVER by Temporal default, and under SKIP every later tick is dropped — the
            # whole proactive layer stops, silently, because a healthy sweep is also quiet. The
            # sweep is one activity, start_to_close 10m, no retry; 15m bounds the run with room
            # for scheduling latency while never letting it eat a second tick's slot.
            execution_timeout=timedelta(minutes=15),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=every_hours))]),
        # SKIP, like the poller: a sweep that fires while the previous one is still reading a large
        # board must be dropped rather than queued, or a slow read becomes a backlog of reports.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


async def ensure_product_sweeps(every_hours: int = PRODUCT_EVERY_HOURS) -> list[str]:
    """One schedule per project that has the product module, created or updated. Idempotent.

    Projects without the module get nothing — no schedule to notice, no schedule to pause.

    HAVING THE MODULE IS THE CONDITION; HAVING SLACK IS NOT. This also required `cfg.channel_id`,
    so a product module on a deployment that runs the panel alone got no sweep at all — the same
    ADR-0038 violation `ensure_techlead_watch` carried, in the function directly below it, found
    when the panel showed `watcher unknown: openfactory-product-sweep-fx-dsk` for a project whose
    product
    module is configured and whose Slack channel is not. Slack is a channel the voice travels on,
    never the reason the voice exists; the panel is the reference surface and needs no channel id.

    Fixing one and leaving its neighbour is how a defect class survives being found."""
    from openfactory.registry import ProjectRegistry

    client = await connect()
    made: list[str] = []
    for project in ProjectRegistry().list():
        cfg = getattr(project, "product", None)
        if cfg is None or not getattr(cfg, "enabled", True):
            continue
        sid = f"{PRODUCT_SCHEDULE_PREFIX}-{project.name}"
        schedule = _product_schedule(project.name, every_hours)
        try:
            await client.create_schedule(sid, schedule)
            made.append(f"created {sid}")
        except ScheduleAlreadyRunningError:
            handle = client.get_schedule_handle(sid)
            # bound as a default, not captured: the lambda outlives one iteration of the loop and
            # would otherwise update every project's schedule to whatever the last one was
            await handle.update(lambda _, sch=schedule: ScheduleUpdate(schedule=sch))
            made.append(f"updated {sid}")
    return made


def _okf_schedule(project_name: str, every_hours: int) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            "KnowledgeRefreshWorkflow",
            project_name,
            id=f"{OKF_SCHEDULE_PREFIX}-{project_name}",
            task_queue=TASK_QUEUE,
            # Same bound and the same reason as its two neighbours: one 10m activity, no retry,
            # so 15m caps the run with room for scheduling latency and never lets a stuck tick
            # eat the next one's slot under SKIP.
            execution_timeout=timedelta(minutes=15),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=every_hours))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


async def ensure_okf_refresh(every_hours: int = OKF_EVERY_HOURS) -> list[str]:
    """One knowledge-refresh schedule per project that asked for a map. Idempotent.

    WHY A SCHEDULE AND NOT A MERGE HOOK, which is what this codebase had. The published bundle
    describes the BASE BRANCH — `KnowledgeRefreshInput` says so itself — and the only thing that
    refreshed it was `JobWorkflow._refresh_knowledge`, called from `result.state ==
    JobState.MERGED` and nowhere else. On `merge_policy: human` (the default) a job ends at
    `PR_OPEN`, so the map went stale exactly on the deployments most likely to be new, and stayed
    stale until somebody merged something. Tying a description of `main` to one ticket's outcome
    was the defect; a schedule is what unties it.

    THE OPT-IN IS NOT CHECKED HERE, DELIBERATELY, and this is a layering decision rather than an
    omission. `knowledge_map` lives in the project's MANIFEST, in the client's repository, so
    reading it at boot would mean a forge round-trip per project inside a reconciler that must
    stay cheap and offline-safe — and a credential that happened to be expired at boot would then
    decide, silently, that a project gets no schedule at all. The activity already answers the
    question at the only place the manifest is legitimately in hand: `_do_refresh_knowledge`
    returns `"off"` when the project did not ask for a map and `"no-context"` when it has no
    context repository, both BEFORE it clones anything. So an unwanted tick costs a registry read
    and a word in the log, and the gate stays where the fact is.

    A DISABLED PROJECT GETS NONE, and that one IS decidable from the registry alone: its floor is
    deliberately off, the same reason the tech-lead's rounds skip it."""
    from openfactory.registry import ProjectRegistry

    client = await connect()
    made: list[str] = []
    for project in ProjectRegistry().list():
        if not project.enabled:
            continue
        sid = f"{OKF_SCHEDULE_PREFIX}-{project.name}"
        schedule = _okf_schedule(project.name, every_hours)
        try:
            await client.create_schedule(sid, schedule)
            made.append(f"created {sid}")
        except ScheduleAlreadyRunningError:
            handle = client.get_schedule_handle(sid)
            # bound as a default, never captured — the same loop-variable trap the sweep above
            # documents: the lambda outlives the iteration and would update every project's
            # schedule to the last one's.
            await handle.update(lambda _, sch=schedule: ScheduleUpdate(schedule=sch))
            made.append(f"updated {sid}")
    return made


def _watch_schedule(project_name: str, every_hours: int) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            "TechLeadWatchWorkflow",
            project_name,
            id=f"{WATCH_SCHEDULE_PREFIX}-{project_name}",
            task_queue=TASK_QUEUE,
            # Same bound, same reason as the product sweep's: one stuck run + SKIP would stop the
            # rounds permanently and indistinguishably from a quiet floor. One 10m activity, no
            # retry → 15m caps the run inside the hourly interval.
            execution_timeout=timedelta(minutes=15),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=every_hours))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


async def ensure_techlead_watch(every_hours: int = WATCH_EVERY_HOURS) -> list[str]:
    """One rounds schedule per ENABLED project. Idempotent.

    NO CHANNEL REQUIRED — that gate (`if not project.channel_id`) was Slack as a precondition
    for a capability, the exact shape ADR-0038 forbids: a deployment with no Slack had no
    on-call rounds at all, silently. The rounds speak through whatever notifier the project
    resolves — which, since the panel became the default voice, is never nothing.

    Disabled projects get none: their floor is deliberately off, and a watcher narrating a
    stopped floor every hour is noise wearing a safety vest."""
    from openfactory.registry import ProjectRegistry

    client = await connect()
    made: list[str] = []
    for project in ProjectRegistry().list():
        if not project.enabled:
            continue
        sid = f"{WATCH_SCHEDULE_PREFIX}-{project.name}"
        schedule = _watch_schedule(project.name, every_hours)
        try:
            await client.create_schedule(sid, schedule)
            made.append(f"created {sid}")
        except ScheduleAlreadyRunningError:
            handle = client.get_schedule_handle(sid)
            await handle.update(lambda _, sch=schedule: ScheduleUpdate(schedule=sch))
            made.append(f"updated {sid}")
    return made
