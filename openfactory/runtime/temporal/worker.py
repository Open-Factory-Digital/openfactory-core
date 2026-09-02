"""The Temporal worker — hosts the workflow + activities and executes them.

Run it where the credentials live (the bot key, the Claude token): the worker
mints tokens and drives sandboxes. In dev it connects to a local dev-server
(free, no account); on deploy the SAME code points at Temporal Cloud + Fargate —
only the connection target changes (address/namespace/TLS via env).

    python -m openfactory.runtime.temporal.worker            # → localhost:7233, ns 'default'
    TEMPORAL_ADDRESS=... TEMPORAL_NAMESPACE=... python -m openfactory.runtime.temporal.worker
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from temporalio.worker import Worker

from openfactory.runtime.temporal import TASK_QUEUE
from openfactory.runtime.temporal.activities import (
    adjust_pr,
    announce_rate_pause,
    available_slots,
    check_ci_status,
    check_deploy_status,
    check_pr_merged,
    check_pr_status,
    close_pr,
    coordinator_advise,
    diagnose_impediment,
    fetch_ticket_title,
    force_merge_pr,
    mark_needs_action,
    merge_pr_now,
    notify_coordinator,
    notify_coordinator_say,
    notify_deploy,
    open_review_loop,
    pr_mergeable_state,
    preflight_check,
    product_role_answer,
    product_role_ask,
    product_role_baseline,
    product_role_break_down,
    product_role_card,
    product_role_needs_action,
    product_role_queue,
    product_role_say,
    product_sweep,
    promote_staging,
    record_job_metrics,
    record_outcome,
    refresh_knowledge,
    release_prod,
    repair_ci,
    review_pr,
    run_job,
    scan_projects,
    scan_todo,
    settle_ticket,
    split_ticket,
    start_jobs,
    stop_job,
    techlead_ask,
    techlead_watch,
    tracker_budgets,
    update_pr_branch,
)
from openfactory.runtime.temporal.connection import address, connect, namespace
from openfactory.runtime.temporal.poller import PollWorkflow
from openfactory.runtime.temporal.workflow import (
    AskWorkflow,
    CoordinatorWorkflow,
    DeployWatchWorkflow,
    JobWorkflow,
    KnowledgeRefreshWorkflow,
    ProductAnswerWorkflow,
    ProductAskWorkflow,
    ProductBaselineWorkflow,
    ProductBreakdownWorkflow,
    ProductCardWorkflow,
    ProductNeedsActionWorkflow,
    ProductQueueWorkflow,
    ProductSayWorkflow,
    ProductSweepWorkflow,
    TechLeadWatchWorkflow,
)

log = logging.getLogger("openfactory.worker")

#: What this half of the deployment calls itself when it announces its build (#135). The panel reads
#: it back off the shared state volume and says so when the two halves disagree.
WORKER_ROLE = "worker"

# EVERY activity the workflows can call must be in this list, or the worker raises
# NotFoundError at run time (a new activity that's imported but never registered is invisible
# until it's invoked in prod — how the poller's budget read slipped through once). The worker
# registration guard holds it: the workflows' referenced activities must all be here.
WORKER_ACTIVITIES = [
    run_job, stop_job, check_pr_merged, check_pr_status, check_ci_status,
    repair_ci, check_deploy_status, notify_deploy, fetch_ticket_title,
    promote_staging, release_prod, scan_projects, scan_todo, start_jobs,
    available_slots, preflight_check, split_ticket, tracker_budgets,
    # the poller's own pause, said out loud — an activity the workflow calls on a
    # tick nobody is watching, which is exactly the shape that must be registered
    announce_rate_pause,
    pr_mergeable_state, update_pr_branch, force_merge_pr,
    # #68 — the three answers to a human-gated merge. REGISTERED, not just defined:
    # an activity the worker does not know about fails at the moment a human finally
    # answers the gate, hours later, with an unknown-activity-type error.
    # …and #181's fourth: re-review. Same rule — a person presses it hours later, and an
    # unregistered activity fails at exactly that moment.
    merge_pr_now, close_pr, adjust_pr, review_pr,
    coordinator_advise, notify_coordinator, notify_coordinator_say,
    mark_needs_action, settle_ticket, record_outcome, diagnose_impediment, record_job_metrics,
    refresh_knowledge, product_sweep, techlead_watch, open_review_loop,
    # the tech-lead's chat runs WHERE AGENTS AUTHENTICATE — the panel dispatches here
    techlead_ask,
    # …and so does the product role's drafting, for the same reason and by the same route (#98).
    product_role_ask,
    # …and the breakdown that turns an accepted requirement into cards (#98).
    product_role_break_down,
    product_role_queue,
    product_role_card,
    product_role_baseline,
    product_role_needs_action,
    product_role_say,
    # …and answering a staged proposal, because a yes on an `accept` chains into the breakdown and
    # a yes on an `align` ends in a model call — which kind a token names is only knowable after
    # the entry is read, so the whole act runs where agents authenticate (#105).
    product_role_answer,
]


#: The longest a first sentence may be and still be preferred to the fixed slice. A "sentence"
#: this long is not one — it is a paragraph that happens to contain `". "` — and printing it
#: whole is the unbounded log line this helper exists to prevent.
_SENTENCE_CAP = 1000


def _readable(exc: BaseException, cap: int = 200) -> str:
    """The reason, bounded — WHICHEVER FORM SAYS MORE, never cut in half.

    A FIXED SLICE DISCARDED THE REMEDY. The platform's own refusals are written for a person:
    the first clause names what was refused and everything after it says what to do about it, so
    `str(exc)[:200]` kept the complaint and dropped the fix — measured the day the channel
    refusal grew a remedy longer than the cut (2026-08-26), which is the only reason anybody
    looked.

    AND THEN KEEPING THE SENTENCE COST MORE THAN THE SLICE EVER DID. Preferring the first
    sentence unconditionally is the same defect facing the other way: a vendor SDK raises
    `Request failed. status=503 body={…}` — 392 characters whose first sentence is fourteen —
    and the diagnostic became the word "failed", with the status code and the body gone. That is
    strictly less than the slice this helper replaced, in the one place an operator reads it.

    So the two forms COMPETE and the longer wins: a refusal whose remedy runs past the cut keeps
    its whole sentence; a dump whose first sentence says nothing keeps `cap` characters of the
    part that does. Bounded either way — never past `_SENTENCE_CAP + 1`."""
    reason = str(exc)
    if len(reason) <= cap:
        return reason
    truncated = reason[:cap]
    first, dot, _rest = reason.partition(". ")
    sentence = f"{first}." if dot and len(first) <= _SENTENCE_CAP else ""
    return sentence if len(sentence) > len(truncated) else truncated


def start_channel_listeners(projects) -> list:
    """One channel adapter per DISTINCT kind the registry's projects speak through, each with its
    listeners started; the adapters are returned so the caller can HOLD them.

    WHY THE REGISTRY AND NOT ONE DEPLOYMENT-WIDE ANSWER. This used to be `build_channel()` with
    no project, which `channel_kind` resolves to the panel for any deployment — so the Slack
    Socket Mode listeners (chat replies, approve/reject clicks) were reached by nothing from the
    day the default flipped to the panel (2026-08-06) until 2026-08-26, while the worker image
    still installed the Slack extra "for the embedded tech-lead chat". A deployment-wide variable
    would have been the same defect one step later: nobody sets it, it resolves to the panel, and
    every existing Slack deployment (which declares only per-project coordinates) stays mute with
    nothing reporting the absence. The projects are the source of truth for which kinds exist —
    one Slack project and one add-on project is two adapters, and that is not a single value.

    ONE ADAPTER PER KIND, not per project: Slack's `start_listeners` already iterates the registry
    itself and opens one socket per project, so a second call per project would double every
    listener. An add-on whose listeners are per project does the same inside its own adapter.

    NO PROJECTS → THE PANEL, which is the surface that always exists: `build_channel()` with
    nothing in hand. A kind the registry refuses, or an adapter whose listeners fail to start, is
    LOGGED BY NAME and skipped — the durable worker serves jobs regardless, and the absence of a
    listener has a sentence in the log rather than a silence in a chat."""
    from openfactory.adapters.channel import build_channel, channel_kind

    kinds: list[str] = []
    by_kind: dict[str, object] = {}
    for project in projects:
        kind = channel_kind(project)
        if kind not in by_kind:
            by_kind[kind] = project
            kinds.append(kind)
    if not kinds:
        kinds, by_kind = ["panel"], {"panel": None}

    held: list = []
    for kind in kinds:
        try:
            adapter = build_channel(by_kind[kind])
            adapter.start_listeners()
        except Exception as exc:  # noqa: BLE001 — one channel's failure is a line, not a dead worker
            log.error("the %r channel's listeners did not start (%s) — the worker is up and will "
                      "run jobs, but nothing is listening on that channel", kind, _readable(exc))
            continue
        log.info("channel %r listening", kind)
        held.append(adapter)
    return held


async def main() -> None:
    load_dotenv()  # bot credentials + Claude token for the activities
    # Secrets Manager delivers the bot App key as CONTENT; light forge reads on the
    # worker (check_pr_merged, the board poll) need it as a file for token minting.
    from openfactory.runtime.boxed_job import materialize_app_key

    materialize_app_key(
        dict(os.environ), dest_dir=Path(tempfile.mkdtemp(prefix="openfactory-worker-"))
    )
    # C-12: the registry the worker DRIVES is writable and outlives the image; the image only
    # carries a seed. Copy it in on first boot, and never over projects that are already there —
    # otherwise every deploy silently reverts whatever was registered at runtime.
    from openfactory.registry import seed_registry

    seed_registry()
    # ADR-0037 D2: the harness toolbox, copied out of the image into the volume the BOXES mount.
    # Same shape as the registry seed above and for the same reason — the image carries it, the
    # volume outlives the image — and idempotent, so a restart is not an 800 MB re-copy.
    #
    # Never fatal. A worker built without the toolbox stage must still start; the absence shows up
    # as a named finding in `openfactory box prove`, not as a process that refuses to boot and says
    # nothing about why.
    from openfactory.runtime.toolbox import populate as populate_toolbox

    try:
        populate_toolbox()
    except Exception as exc:  # noqa: BLE001 — a broken toolbox is a diagnosis, not a dead worker
        log.warning("could not populate the harness toolbox (%s) — boxes will have none, and "
                    "`openfactory box prove` will say so", str(exc)[:200])
    # ADR-0015 v2: embed the tech-lead's chat listeners in the worker process (it's already
    # long-lived + has the registry, the App key, and the Claude token). Best-effort — a channel
    # hiccup never touches the durable worker. The ADAPTERS are what is held: each owns the
    # connections it opened, so keeping them alive keeps those alive.
    from openfactory.registry import ProjectRegistry

    try:
        projects = ProjectRegistry().list()
    except Exception as exc:  # noqa: BLE001 — a malformed registry must not be a mute worker
        log.error("could not read the project registry to start the channel listeners (%s) — "
                  "only the panel will listen until it is fixed", str(exc)[:200])
        projects = []
    _channels = start_channel_listeners(projects)  # noqa: F841 — held: they own the listeners
    client = await connect()  # dev-server or Temporal Cloud, per env

    # Reconcile the schedules a deploy is responsible for (poller, tech-lead rounds, product
    # sweeps). Idempotent by construction. Best-effort so a Temporal hiccup never stops the worker
    # from serving jobs — but NEVER silent: a factory whose tech-lead does no rounds looks exactly
    # like a factory with nothing to report, and that is the whole failure #478 was made of.
    # SAY WHICH BUILD THIS IS, where the panel can read it (#135). Both containers mount the same
    # state volume and each could only ever print its OWN stamp — so a stack rebuilt by halves
    # looked entirely healthy: the pilot rebuilt his worker, pressed F5, and read a page served by
    # an image twenty-eight hours older, reporting the older world, with nothing on screen able to
    # say so.
    from openfactory import namespace as _ns

    log.info("this worker runs build %s", _ns.announce_build(WORKER_ROLE) or "(not a built image)")

    from openfactory.runtime.temporal.schedule import ensure_all

    try:
        for line in await ensure_all():
            log.info("schedule %s", line)
    except Exception as exc:  # noqa: BLE001 — serving jobs matters more than reconciling schedules
        log.error(
            "COULD NOT RECONCILE SCHEDULES (%s) — the worker is up and will run jobs, but the "
            "tech-lead rounds and the product sweep may not be scheduled at all. Nothing will "
            "report their absence; check the Temporal UI.", exc)

    # (A second, watch-only reconcile stood here. `ensure_all` above already calls
    # `ensure_techlead_watch`, and has since f1d9fb2 — the duplicate was added on a mistaken
    # reading that nothing called it, and reconciled half of what the line above reconciles.)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[JobWorkflow, PollWorkflow, DeployWatchWorkflow, CoordinatorWorkflow,
                   ProductSweepWorkflow, TechLeadWatchWorkflow, AskWorkflow,
                   ProductAskWorkflow, ProductBreakdownWorkflow,
                   ProductQueueWorkflow, ProductCardWorkflow,
                   ProductSayWorkflow, ProductNeedsActionWorkflow,
                   ProductBaselineWorkflow, ProductAnswerWorkflow,
                   KnowledgeRefreshWorkflow],
        activities=WORKER_ACTIVITIES,
        # Audit fix (2026-07-23): =1 serialized EVERY activity behind the hours-long run_job —
        # proven in prod: #424's deploy-watch check queued 49 MINUTES (schedule-to-start) behind
        # #425's run_job, so its Slack "deploy success" arrived ~43 min late; polls and narration
        # starved the same way. The original worry (single Claude token → serialize) is already
        # enforced where it matters: the FLOOR is single (max_concurrent_jobs), so heavy agent
        # activities barely overlap by construction. 8 lets the read-only checks (check_*,
        # notify_*, scan_*) interleave with a running job — the panel and Slack stay real-time.
        max_concurrent_activities=8,
    )
    print(f"openfactory worker up · {address()} · ns={namespace()} · queue={TASK_QUEUE}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
