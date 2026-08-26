"""PollWorkflow — the autonomous trigger (A1): the board IS the interface.

A Temporal Schedule fires this every few minutes. It scans each enabled project's
board TODO column and starts a JobWorkflow per new ticket — so creating a GitHub
issue is ALL a human does; everything else happens on its own. Running it as a
scheduled WORKFLOW (not a cron script) keeps the trigger itself durable and visible:
every tick, scan, and start is in Temporal's history — a failing poller can never
fail silently (the schedule UI shows it red).

Create/refresh the schedule once:  python -m openfactory.runtime.temporal.schedule
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from openfactory.runtime.temporal.activities import (
        announce_rate_pause,
        available_slots,
        scan_projects,
        scan_todo,
        start_jobs,
        tracker_budgets,
    )
    from openfactory.runtime.temporal.io import (
        PollInput,
        RatePauseInput,
        ScanInput,
        StartJobsInput,
    )

_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5))

#: THE HISTORY'S NAMES, NOT THE PLATFORM'S. A tick that was in flight when the worker was
#: replaced replays its history against this code, and its first command scheduled an activity
#: of THIS type — one vendor's budget, read before the project scan, judged against THIS number
#: (`_RATE_FLOOR`, then a literal here). A replay must schedule the same type and decide the
#: same way or the tick dies non-deterministic (TMPRL1100). Nothing on this code path imports
#: the vendor: the type is a string the engine compares, and the number is the one the recorded
#: decision was made by. Both are reached by `_pre_seam_tick` only, behind `patched()`.
_PRE_SEAM_BUDGET_ACTIVITY = "github_budget"
_PRE_SEAM_FLOOR = 200


@workflow.defn
class PollWorkflow:
    @workflow.run
    async def run(self, inp: PollInput) -> dict:
        # THE GATE (workflow-changes-need-patched). The per-vendor read changed the tick's first
        # command — `scan_projects` now precedes the budget read, and the budget activity has a
        # new type — so a tick started on the previous worker and replayed here would diverge
        # at command one. `patched()` answers False for exactly such a history (no marker was
        # recorded when it ran) and True for every tick started on this code, so the old
        # sequence below is what an old history sees and nothing else ever runs it. Once no
        # pre-seam tick can exist (a tick lives seconds; one deploy later) this becomes
        # `workflow.deprecate_patch("tracker-budgets")` and `_pre_seam_tick` goes.
        if workflow.patched("tracker-budgets"):
            projects, skipped = await self._tick_around_each_vendors_budget()
        else:
            projects, skipped = await self._pre_seam_tick()
        if skipped is not None:
            return skipped
        # Floor-aware pickup: start at most `slots` (= free floor) NEW tickets this tick, so a
        # batch dropped in TO-DO is picked up one at a time in order — not all launched at once
        # (the v1 floor is a single agent token). slots == 0 → a job is in flight, wait a tick.
        slots = await workflow.execute_activity(
            available_slots,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=_RETRY,
        )
        started: dict[str, list[str]] = {}
        for p in projects:
            if slots <= 0:
                break  # floor full — leave the rest in TO-DO for a later tick
            issues = await workflow.execute_activity(
                scan_todo,
                ScanInput(**p),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=_RETRY,
            )
            if not issues:
                continue
            take = issues[:slots]  # only as many as the floor can take, in board order
            started[p["project"]] = await workflow.execute_activity(
                start_jobs,
                StartJobsInput(project=p["project"], issues=take, sandbox=inp.sandbox),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=_RETRY,  # idempotent: AlreadyStarted is a skip
            )
            slots -= len(take)
        return started

    async def _tick_around_each_vendors_budget(self) -> tuple[list[dict], dict | None]:
        """`(projects to scan, skip result or None)` — the live arm.

        PROTECT EACH VENDOR'S QUOTA, AND ONLY THAT VENDOR'S PROJECTS. This read used to be one
        vendor by name, no project in scope, and a threshold written here (`_RATE_FLOOR = 200`)
        beside a second copy in the doctor. Now each tracker answers through the port, with its
        OWN floor on the value, and a spent quota on one vendor parks the projects on that
        vendor while the others are still scanned: a mixed deployment no longer parks its Jira
        board on GitHub's hourly limit. Fail OPEN — a budget that could not be read (`unread`)
        or a vendor that reports none (`not_reported`) must never freeze the poller."""
        projects = await workflow.execute_activity(
            scan_projects,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=_RETRY,
        )
        rows = await workflow.execute_activity(
            tracker_budgets,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=_RETRY,
        )
        paused: set[str] = set()
        for row in rows or []:
            if row.get("state") != "low":
                continue
            names = [str(n) for n in (row.get("projects") or [])]
            paused.update(names)
            reset_in = max(0, int(row.get("reset_epoch") or 0) - workflow.now().timestamp())
            workflow.logger.warning(
                "pickups paused for %s — %s %s budget low (%s left, resets in ~%dm)",
                ", ".join(names) or "every project", row.get("vendor") or row.get("kind"),
                row.get("resource"), row.get("remaining"), reset_in // 60)
            # AND IT SAYS SO WHERE SOMEBODY IS. The factory stops taking cards for up to an
            # hour, deliberately — and this said it to a workflow log nobody reads. The operator
            # met the wall from the other side, on a command that failed, and asked the question
            # that names the defect (2026-08-14): *"what limit? I never got any warning."* A
            # wait is a QUESTION, never a state (ADR-0038 D2), and a self-imposed one is still
            # a wait. Best-effort and outside the tick's critical path: a channel that is down
            # must not also stop the poll from ending cleanly.
            await workflow.execute_activity(
                announce_rate_pause,
                RatePauseInput(resource=str(row.get("resource") or "API"),
                               remaining=int(row.get("remaining") or 0),
                               reset_epoch=int(row.get("reset_epoch") or 0),
                               vendor=str(row.get("vendor") or row.get("kind") or ""),
                               kind=str(row.get("kind") or ""),
                               projects=names),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=_RETRY,
            )
        projects = [p for p in projects if str(p.get("project")) not in paused]
        if paused and not projects:
            return [], {"skipped": "budget_low",
                        "budget": [r for r in rows if r.get("state") == "low"]}
        return projects, None

    async def _pre_seam_tick(self) -> tuple[list[dict], dict | None]:
        """The sequence a history written BEFORE `tracker-budgets` carries — replayed, never run.

        One budget read, of the one vendor, by the activity type the history scheduled
        (`_PRE_SEAM_BUDGET_ACTIVITY`) and ahead of the project scan; a number under
        `_PRE_SEAM_FLOOR` announced the pause and skipped the whole tick. Every command here
        already sits in the history being replayed, so the engine answers each from the record
        and no activity of that type needs a worker — unless the tick was cut mid-activity, in
        which case that one tick fails and the schedule's next fires fresh on the live arm."""
        budget = await workflow.execute_activity(
            _PRE_SEAM_BUDGET_ACTIVITY,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=_RETRY,
        )
        if budget and budget.get("remaining", _PRE_SEAM_FLOOR) < _PRE_SEAM_FLOOR:
            reset_in = max(0, budget.get("reset", 0) - workflow.now().timestamp())
            workflow.logger.warning(
                "poll skipped — %s budget low (%s left, resets in ~%dm)",
                budget.get("resource"), budget.get("remaining"), reset_in // 60)
            await workflow.execute_activity(
                announce_rate_pause,
                RatePauseInput(resource=str(budget.get("resource") or "API"),
                               remaining=int(budget.get("remaining") or 0),
                               reset_epoch=int(budget.get("reset") or 0)),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=_RETRY,
            )
            return [], {"skipped": "github_rate_low", "budget": budget}
        projects = await workflow.execute_activity(
            scan_projects,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=_RETRY,
        )
        return projects, None
