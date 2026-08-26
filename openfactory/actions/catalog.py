"""The actions themselves — one row each, one implementation each (C-23).

READ `openfactory/actions/__init__.py` FIRST; it says why this exists and what it deliberately is
not.

**Why the list is longer than the card's.** #51 named eight: resume, skip, approve_prod, promote,
enable, scan, ask, diagnose. Two more are here because they already exist in production and
leaving them out would defeat the whole point — `ack` (Slack only, closes a review finding's open
loop) and `start` (the panel's two launch routes). An action that stays outside the layer is an
action that drifts, and the ones that had already drifted are precisely these.

**Why the messages are in English.** The tech-lead's Slack channel speaks pt-BR today and these
sentences will read colder there. That is the accepted trade: this platform's rule for the two
surfaces is that the *client's* channel owes a voice and the *operator's* owes an answer — terse
and technical is allowed there, silence never is. Writing every sentence twice, or building an i18n
layer, would be the voice work the rule says to cut. A front end that wants warmth decorates; it
must not have to translate to be correct.

**Why every implementation is async and lazy-imports its dependencies.** Async so the three
transports have one calling convention (`await` in the panel, `asyncio.run` in Slack's threads and
the CLI). Lazy because half of these reach `temporalio`, which the panel is explicitly built to
serve without — the import graph is a feature here, not an accident.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Mapping
from pathlib import Path

from openfactory import namespace
from openfactory.actions.base import (
    CONFLICT,
    DENIED,
    FAILED,
    INVALID,
    NOT_FOUND,
    PRODUCT,
    UNAVAILABLE,
    ActionSpec,
    Actor,
    Outcome,
    done,
    refused,
)

log = logging.getLogger("openfactory.actions")


# ── shared plumbing ─────────────────────────────────────────────────────────────────────────────

def _project(name: str):
    """`(project, None)` or `(None, Outcome)` — resolving a project name in ONE place.

    The three front ends had three answers to an unknown project: the panel's `ProjectRegistry.get`
    raised a `KeyError` that FastAPI turned into a 404 with no body worth reading, Slack never
    looked it up at all (it holds a project object from its own registry walk), and the CLI printed
    a traceback. Naming the registered projects in the refusal is what makes this actionable — the
    single most common cause is a typo, and the second is a worker running with a registry that was
    baked without the project (see the `deploy/registry.yaml` memory)."""
    from openfactory.registry import ProjectRegistry

    registry = ProjectRegistry()
    try:
        return registry.get(name), None
    except KeyError:
        known = ", ".join(p.name for p in registry.list()) or "none"
        return None, refused(
            NOT_FOUND,
            f"there is no project called {name!r} on this deployment — it knows: {known}.",
        )


async def _connected():
    """`(client, None)` or `(None, Outcome)` — the durable engine, or a sentence about its absence.

    UNAVAILABLE RATHER THAN FAILED, because the two send an operator to different places: the
    engine being down is somebody else's outage and the action can simply be repeated, while a
    failure means the action was attempted and something about *this* request is wrong. Both front
    ends already made this distinction by hand (the panel's 503, Slack's "não consegui"), which is
    two hand-written copies of one rule."""
    from openfactory.runtime.temporal import view as tv
    from openfactory.util.causes import first_message

    try:
        return await tv.connect(), None
    except Exception as exc:  # noqa: BLE001 — unreachable engine is a state, not a crash
        return None, refused(
            UNAVAILABLE,
            f"the durable engine is not answering ({first_message(exc, limit=140)}) — nothing was "
            f"sent, so this is safe to repeat once it is back.",
        )


def _looks_missing(exc: BaseException) -> bool:
    """Whether an engine error means 'no such workflow' rather than 'something went wrong'.

    Matched on text because the Temporal SDK raises a generic `RPCError` for both and the status
    enum is not part of its public surface at this version. Deliberately narrow: a false positive
    here would tell an operator their ticket does not exist when the real cause was transient, and
    they would go looking at the board instead of at the engine."""
    from openfactory.util.causes import first_message

    blob = f"{type(exc).__name__} {first_message(exc)}".lower()
    return "not found" in blob or "notfound" in blob


# ── resume / skip — a parked job's two ways forward ──────────────────────────────────────────────

async def _signal_parked(*, project: str, issue: str, by: Actor, action: str,
                         choice: str = "") -> Outcome:
    """The body both `resume` and `skip` are. One function because they differ in exactly one
    string, and the previous arrangement — two front ends each branching on that string — is how
    `choice` came to exist on one side only.

    THE PARKED CHECK IS NOT DEFENSIVE. `tv.act_job` queries `awaiting_action` before signalling, so
    a signal is never delivered to a running or finished job. Without it a stray `skip` on a job
    that had already moved on would be accepted, do nothing, and be reported as done — the platform
    telling somebody it acted when it did not, which is worse than refusing."""
    from openfactory.runtime.temporal import view as tv
    from openfactory.util.causes import first_message

    found, bad = _project(project)
    if bad:
        return bad
    client, bad = await _connected()
    if bad:
        return bad
    try:
        await tv.act_job(client, found.name, issue, action=action, choice=choice)
    except RuntimeError as exc:  # the engine answered: this job is not parked
        return refused(
            CONFLICT,
            f"#{issue} is not parked waiting for anybody — there is nothing to {action}. "
            f"({first_message(exc, limit=120)})",
        )
    except ValueError as exc:  # act_job's own guardrail: only resume/skip may be signalled
        return refused(FAILED, first_message(exc))
    except Exception as exc:  # noqa: BLE001
        if _looks_missing(exc):
            return refused(
                NOT_FOUND,
                f"no job has ever run for #{issue} on {found.name} — check the ticket reference, "
                f"or start it first.",
            )
        raise
    picked = f" with option {choice!r}" if choice else ""
    return done(
        f"#{issue}: {action} sent{picked} — {by} asked, and the job is picking it up now.",
        project=found.name, issue=issue, action=action, choice=choice or None,
    )


async def _resume(*, project: str, issue: str, by: Actor, choice: str = "") -> Outcome:
    return await _signal_parked(project=project, issue=issue, by=by, action="resume", choice=choice)


async def _skip(*, project: str, issue: str, by: Actor) -> Outcome:
    return await _signal_parked(project=project, issue=issue, by=by, action="skip")


# ── ack — a person has this one ─────────────────────────────────────────────────────────────────

async def _ack(*, project: str, issue: str, by: Actor) -> Outcome:
    """Close a review finding's open loop (ADR-0021). Touches no job.

    IT EXISTS BECAUSE THE ALTERNATIVE WAS A LIST THAT ONLY GROWS. A finding flagged on an already
    merged ticket has nothing the factory could ever OBSERVE to close it — no reply to read, no
    state change to watch — so without a person saying "I have this" it sits open for ever, and a
    list that only grows is a list everybody learns to ignore.

    MOVED HERE FROM `runtime/slack/bot.py::_ack_finding`, which is where it had been living: a
    capability that changes the deployment's memory ledger, reachable only by typing a verb into
    one vendor's chat product. The panel — the surface that actually *shows* the open loops — had
    no way to close one."""
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import FINDING, close_by_observation, waiting

    found, bad = _project(project)
    if bad:
        return bad

    ledger = loop_store.read(found.name)
    mine = [x for x in waiting(ledger, kind=FINDING) if x.subject == str(issue)]
    if not mine:
        return refused(
            CONFLICT,
            f"there is nothing open about #{issue} on {found.name} — nothing to acknowledge.",
        )
    # The observed key is built FROM the loops found, because `close_by_observation` matches on
    # (kind, subject, about) and FINDING loops carry the decision in `about`. A hand-built key
    # without it closes nothing while the reply still claims success — which is what the first
    # version of this did.
    closed = close_by_observation(
        ledger, {(x.kind, x.subject, x.about): "acknowledged" for x in mine})
    if not closed:
        # A concurrent pass beat us to it, or nothing matched. Success may not be claimed for a
        # write that lands no rows: the loop would stay open behind a checkmark, which is the
        # precise failure this whole mechanism exists to prevent.
        return refused(
            FAILED,
            f"could not close the open finding on #{issue} just now — it is still on the list, "
            f"which is the safe side of this error. Try again.",
        )
    loop_store.write(found.name, closed)
    what = (mine[0].context or {}).get("detail", "")
    return done(
        f"#{issue} noted as handled by {by} — it will stop being raised."
        + (f" It was about: {what[:200]}" if what else ""),
        project=found.name, issue=issue, closed=len(mine), about=what[:200],
    )


# ── scan — pick up TO-DO right now, instead of waiting for the poller's tick ────────────────────

async def _scan(*, project: str, by: Actor) -> Outcome:
    """Scan this project's board TO-DO column right now — the 'don't wait for the 3-min tick'
    button. Starts a job per TO-DO card the floor has room for (skipping any already running) and
    reports what happened. The engine still runs one job at a time; extra cards queue.

    MOVED FROM `api/app.py::scan_now`. Three defects live in the ordering below, which is why it
    is not simplified on the move:

    - the board is built from the PROJECT OBJECT, never the path string — passing the string once
      made the button die silently, always reporting "Nothing in TO-DO", right after this same
      function had already validated that the board exists;
    - the floor count is GLOBAL — every running JobWorkflow, not just this project's — so a manual
      scan honours the same one-at-a-time floor as the poller;
    - an `AlreadyStarted` skip still counts against the floor: treating it as free and falling
      through to the next ticket would let a double-click or a scan racing the 3-minute tick
      overrun it (F1).

    ONE NORMALISATION ON THE MOVE: a `resolve_box_image` refusal used to return 200 with the
    refusal folded into `message` — the one branch of this endpoint that did not raise. Every
    other box.image refusal in this codebase (`temporal_start`, `cli.poll`) is a 400. There was no
    test pinning the 200, so this now reports it the same way everyone else does — `INVALID`,
    mapped to 400 by the panel."""
    import asyncio

    from openfactory.adapters.board import build_board
    from openfactory.credentials import deployment_tracker_token, tracker_token_for
    from openfactory.factory import resolve_box_image
    from openfactory.runtime.temporal import TASK_QUEUE, max_concurrent_jobs
    from openfactory.runtime.temporal.io import JobParams, default_sandbox

    proj, bad = _project(project)
    if bad:
        return bad

    # THE FACTORY DECIDES WHETHER THERE IS A BOARD, not a pair of GitHub-shaped option names. The
    # `board_owner`/`board_number` gate that stood here refused every Jira project — and now every
    # Azure one — with "has no board configured" while `build_board` built one without complaint.
    # Both put the column ON the work item, so neither has coordinates to give. See cli.py's
    # `pickup` for the same fix; the two sites had grown the same wrong question independently.
    # THE TRACKER AXIS ASKS ITS OWN. This resolved `… or _bot_token_provider()()` — the GitHub
    # App minter in bare-call shape, invisible to the ratchet that matches the `or` shape — so a
    # Jira project with no `JIRA_API_TOKEN` got a board whose tracker held a `ghs_…` token, and
    # Jira answers a foreign token with an EMPTY search, not a 401 (measured 2026-08-24).
    tok = tracker_token_for(proj) or deployment_tracker_token(proj)
    board = build_board(proj, token=tok)
    if board is None:
        return refused(INVALID, f"{proj.name} has no board configured — nothing to scan.")
    todo = ([] if board is None
            else await asyncio.to_thread(lambda: [str(n) for n in board.items_in_status("TO-DO")]))

    client, bad = await _connected()
    if bad:
        return bad
    from openfactory.runtime.temporal import view as tv

    # The floor is a single agent token (v1) — count ALL running JobWorkflows, not just this
    # project's, so a manual scan honours the same one-at-a-time floor as the poller.
    running_all, running = 0, []
    async for wf in client.list_workflows(
            'WorkflowType="JobWorkflow" AND ExecutionStatus="Running"'):
        running_all += 1
        p, iss = tv.parse_job_id(wf.id)
        if p == proj.name:
            running.append(iss)
    slots = max(0, max_concurrent_jobs() - running_all)

    if not todo:
        msg = "Nothing in TO-DO to run."
        if running:
            msg += f" (#{running[0]} is already running.)"
        return done(msg, started=[], skipped=[], todo=[], running=running)
    if slots <= 0:
        return done(
            f"Floor busy ({running_all} in flight) — TO-DO will be picked up one at a time as "
            f"each finishes.",
            started=[], skipped=todo, todo=todo, running=running,
        )

    # Resolved ONCE, against the sandbox JobParams will ACTUALLY use — the same default_factory
    # the model would apply — because resolving against nothing would skip the refusal and hand a
    # declaring project an image its box cannot honour, silently. Passing it explicitly also stops
    # the two from ever drifting apart.
    scan_sandbox = default_sandbox()
    try:
        scan_image = resolve_box_image(proj, sandbox=scan_sandbox)
    except ValueError as exc:
        return refused(INVALID, str(exc), started=[], skipped=todo, todo=todo, running=running)

    # Start only as many as the floor can take (in board order); the rest wait in TO-DO. `claimed`
    # counts BOTH fresh starts AND AlreadyStarted skips against the floor.
    started, skipped = [], []
    claimed = 0
    for issue in todo:
        if claimed >= slots:
            skipped.append(issue)  # deferred — floor full, a later scan/tick picks it up
            continue
        try:
            await client.start_workflow(
                "JobWorkflow",
                JobParams(project=proj.name, issue=issue, sandbox=scan_sandbox, image=scan_image),
                id=f"openfactory-{proj.name}-{issue}", task_queue=TASK_QUEUE,
            )
            started.append(issue)
            claimed += 1
        except Exception as exc:
            if "AlreadyStarted" in type(exc).__name__:
                skipped.append(issue)
                claimed += 1  # this ticket already holds a slot — don't hand it to another
            else:
                raise
    if started:
        msg = f"Started {len(started)} job(s): " + ", ".join("#" + s for s in started)
        if skipped:
            msg += f" — {len(skipped)} left in TO-DO (one at a time)."
    else:
        msg = "All TO-DO items are already running."
    return done(msg, started=started, skipped=skipped, todo=todo, running=running)


# ── start — one job for one ticket ──────────────────────────────────────────────────────────────

async def _start(*, project: str, issue: str, by: Actor, sandbox: str = "",
                 promote: bool = False, durable: bool = False) -> Outcome:
    """Start one job for one ticket. `durable` picks the ENGINE, not just a flag:

        durable=False (default)   `trigger_job` — a detached subprocess (`openfactory run …`), the
                                   worktree/local execution path
        durable=True               `temporal_start` — a durable Temporal workflow, which only
                                   the cloud worker runs and which therefore only accepts
                                   `sandbox="fargate"`

    MOVED FROM `api/app.py::trigger_job` AND `::temporal_start` — TWO routes because they were
    two different launch mechanisms wearing the same `NewJob` body, not because they differ in
    what a human is asking for: "run this ticket." One action, one parameter picking the engine,
    is what stops a third mechanism from needing a third route.

    A GAP CARRIED OVER, NOT INTRODUCED: `promote` only ever reached the workflow on the durable
    path (`JobParams.promote` → `JobWorkflow` auto-releasing after landing). The local/subprocess
    path (`build_runner(...).run(...)`) has no equivalent hook — `openfactory run` does not even
    have a
    `--promote` flag — so `promote=True` with `durable=False` is accepted and silently has no
    effect, exactly as `trigger_job` always did. Fixing that means designing what "auto-promote"
    means for the synchronous CLI runner, which is new functionality, not a move; it is a genuine
    pre-existing gap and is named here so it is not lost in the drift moving this action was meant
    to end."""
    from openfactory.factory import resolve_box_image
    from openfactory.runtime.temporal.io import default_sandbox

    found, bad = _project(project)
    if bad:
        return bad

    # UNSET MEANS THE DEPLOYMENT'S BOX. It defaulted to `"worktree"` — the box that isolates the
    # code state and nothing else — so every caller that did not name one got the weakest box on
    # the list, while `OPENFACTORY_SANDBOX` sat in the compose file being read by the durable path
    # alone.
    sandbox = (sandbox or "").strip().lower() or default_sandbox()

    if durable:
        return await _start_durable(found, issue, by=by, sandbox=sandbox, promote=promote)

    # The local path never validated `box.image` before this — a project that declared one for a
    # sandbox that cannot honour it failed silently, inside the detached subprocess, minutes
    # later, in a log file nobody was watching yet. `resolve_box_image` is cheap (no network, no
    # ports touched) and every other launch path already pays for it up front (`cli.poll`,
    # `temporal_start`, `scan`); this is the one that had been exempted by omission, not by
    # design.
    try:
        resolve_box_image(found, sandbox=sandbox)
    except ValueError as exc:
        return refused(INVALID, str(exc))

    import subprocess
    import sys

    from openfactory.paths import project_log_dir

    log_dir = project_log_dir(found)
    log_dir.mkdir(parents=True, exist_ok=True)
    out = (log_dir / f"{issue}-run.log").open("w")
    subprocess.Popen(  # noqa: S603 — fixed argv, no shell, every element is ours or validated
        [sys.executable, "-m", "openfactory.cli", "run", found.name, issue, "--sandbox", sandbox],
        stdout=out, stderr=out,
    )
    return done(f"#{issue}: started ({sandbox}) — {by} asked. Follow it at {log_dir}.",
                project=found.name, issue=issue, sandbox=sandbox, durable=False)


async def _start_durable(found, issue: str, *, by: Actor, sandbox: str, promote: bool) -> Outcome:
    from openfactory.adapters.sandbox.registry import box_traits
    from openfactory.factory import resolve_box_image
    from openfactory.runtime.temporal.io import JobParams

    # A DURABLE JOB RUNS ON THE WORKER, so its box must bound more than the code state — the
    # agent's arbitrary code would otherwise execute in the worker's own filesystem, beside the
    # scheduler that launched it, with the worker's credentials.
    #
    # IT USED TO SAY `!= "fargate"`, on the reasoning *"the cloud worker has no other execution
    # path"* — true of the deployment it was written on, false of the one this product SHIPS. On
    # a compose install the durable engine is Temporal OSS and the box is `container`, so the whole
    # durable path (the human merge gate, park/resume, every deadline) could not be started at all.
    # Measured by trying it, not by reading it.
    try:
        traits = box_traits(sandbox)
    except ValueError as exc:
        return refused(INVALID, str(exc))     # the box registry names what it does know
    if not traits.isolates_resources:
        return refused(
            INVALID,
            f"a durable job cannot run in the {sandbox!r} box: it isolates the code state and "
            f"nothing else — no CPU, memory, network or secret boundary — and a durable job runs "
            f"an agent on the worker itself. Use a box that bounds the work.")
    client, bad = await _connected()
    if bad:
        return bad
    from openfactory.runtime.temporal import view as tv

    try:
        params = JobParams(project=found.name, issue=issue, sandbox=sandbox, promote=promote,
                           image=resolve_box_image(found, sandbox=sandbox))
    except ValueError as exc:
        return refused(INVALID, str(exc))
    try:
        wf_id = await tv.start_job(client, params)
    except Exception as exc:
        if "AlreadyStarted" in type(exc).__name__:
            return refused(CONFLICT, f"a job for #{issue} is already running.")
        raise
    return done(f"#{issue}: durable job started ({wf_id}) — {by} asked.",
                project=found.name, issue=issue, sandbox=sandbox, durable=True,
                workflow_id=wf_id)


# ── enable — is this project picked up at all ───────────────────────────────────────────────────

async def _enable(*, project: str, by: Actor, enabled: bool = True) -> Outcome:
    """Turn pickup on or off for one project. The panel had this; Slack did not, which #51 names
    as a live defect — an operator watching a runaway board in a channel had to go find the panel
    to stop it.

    NOT A PAUSE OF THE POLLER. `enabled` is per project; the poller's schedule is deployment-wide.
    Said explicitly because they look interchangeable from a channel and are not: disabling every
    project still leaves auto-split refilling TO-DO, and only pausing the schedule holds the queue
    (`emptying-todo-does-not-hold-the-queue`)."""
    from openfactory.registry import ProjectRegistry

    found, bad = _project(project)
    if bad:
        return bad
    ProjectRegistry().set_enabled(found.name, bool(enabled))
    state = "enabled" if enabled else "disabled"
    tail = ("new tickets in TO-DO will be picked up." if enabled
            else "nothing new will be picked up; jobs already running are unaffected.")
    return done(f"{found.name} is {state} — {tail} ({by})",
                project=found.name, enabled=bool(enabled))


# ── prod release — shared plumbing for approve_prod and promote ────────────────────────────────
#
# `_forge_and_manifest` and `_env_prod_approvers` MOVED HERE FROM `api/app.py`, where
# `promote_info` (the read-only dialog-prefetch route, `GET /api/promote/{project}/{issue}`) still
# imports them from this module. That import points the way you would expect FROM a front end —
# `promote_info` is not becoming an action (it does nothing, it only fetches what a form needs to
# populate itself with), but the two things it reads from are genuine capability logic with no
# transport in them, and duplicating them back into app.py would be exactly the drift this whole
# card exists to end, one function sooner.

def _forge_and_manifest(project_name: str):
    """`(project, manifest, forge)` — or `KeyError` (unknown project) / `FileNotFoundError` (a
    deployed panel's placeholder `repo_path`, no checkout on disk). BOTH ARE RAISED, NOT RETURNED
    AS AN OUTCOME, unlike everything else in this module: `promote_info` (still a plain app.py
    route, not an action) is one of its two callers and needs a real exception to catch. `_promote`
    is the other, and does not catch either — they reach `perform`'s catch-all instead, which is a
    strict improvement over what used to happen there (a bare, unhandled 500)."""
    from openfactory.adapters.forge.registry import build_forge
    from openfactory.credentials import deployment_forge_token, forge_token_for
    from openfactory.loader import load_manifest
    from openfactory.registry import ProjectRegistry

    p = ProjectRegistry().get(project_name)
    manifest = load_manifest(p)
    # THE FORGE AXIS ASKS ITS OWN CREDENTIAL. `github_app.token_from_env()` stood here — one
    # vendor's mint handed to `build_forge` for ANY forge kind, and it OVERRODE a project's own
    # `forge.options.token_env` because an explicit `token=` wins over what a row resolves for
    # itself. Measured 2026-08-24: a GitHub project naming its own PAT was built with the
    # deployment's, and a third-party forge add-on was handed a `ghp_…` it never asked for.
    forge = build_forge(p, token=forge_token_for(p) or deployment_forge_token(p))
    return p, manifest, forge


def _env_prod_approvers() -> list[str]:
    """OPENFACTORY_PROD_APPROVERS (comma-separated) — the deployed panel's allowlist, where no
    repo/manifest exists on disk."""
    import os

    raw = os.environ.get("OPENFACTORY_PROD_APPROVERS", "")
    return [a.strip() for a in raw.split(",") if a.strip()]


def _prod_allowlist(project) -> list[str]:
    """Who may approve a production release for THIS project, from the first source that answers:
    the deployment-wide env allowlist, else the project's own manifest, else — on a deployed panel
    whose registry `repo_path` is a placeholder with no checkout — the password store's own
    logins. ONE injected secret (OPENFACTORY_APPROVERS) then arms the whole gate."""
    allowed = _env_prod_approvers()
    if allowed:
        return allowed
    try:
        _, manifest, _ = _forge_and_manifest(project.name)
        return manifest.prod_approvers
    except FileNotFoundError:
        from openfactory.approvals import list_approvers

        log.warning(
            "OPENFACTORY_PROD_ALLOWLIST_FROM_STORE: no OPENFACTORY_PROD_APPROVERS and no manifest "
            "on disk "
            "for %r — allowing the password store's logins", project.name,
        )
        return list_approvers()


def _approval_denied() -> Outcome:
    """An empty password store is a deployment config error no password can cure. It must be a
    loud UNAVAILABLE for the operator, never a DENIED that reads as a typo — a structurally dead
    approve button parks a release forever, and the two look identical from a rejected click."""
    from openfactory.approvals import list_approvers

    if not list_approvers():
        log.error(
            "OPENFACTORY_APPROVER_STORE_MISSING: prod approval refused — this runtime has no "
            "approver "
            "password store. Inject the OPENFACTORY_APPROVERS secret (JSON login->hash, SSM "
            "SecureString: `openfactory approver add <login>` then put "
            "~/.openfactory/approvers.json "
            "in the parameter) or run `openfactory approver add` where the panel runs."
        )
        return refused(
            UNAVAILABLE, "approval store not configured on this deployment — no password can "
                        "work until the OPENFACTORY_APPROVERS secret is provisioned (tell the "
                        "operator)")
    return refused(DENIED, "not an authorized approver / bad password")


# ── approve_prod — answer the durable release gate ──────────────────────────────────────────────

async def _approve_prod(*, project: str, issue: str, version: str, approver: str, password: str,
                        by: Actor, comment: str = "") -> Outcome:
    """Deliver an authenticated human decision on a job's production-release gate, as a durable
    signal to the parked workflow (D-12) — the human-in-the-loop path of the runtime.

    MOVED FROM `api/app.py::temporal_approve`. Distinct from `promote`: this SIGNALS a workflow
    that is already parked waiting for the answer; `promote` RUNS the release itself, synchronously,
    outside Temporal entirely. Two mechanisms because the durable path exists specifically for the
    cloud worker, which has no synchronous request to answer from — the signal is how the answer
    reaches a workflow that may have been waiting for hours."""
    from openfactory.util.causes import first_message

    found, bad = _project(project)
    if bad:
        return bad
    from openfactory.approvals import verify_approver

    if not verify_approver(approver, password, _prod_allowlist(found)):
        return _approval_denied()
    client, bad = await _connected()
    if bad:
        return bad
    from openfactory.runtime.temporal import view as tv

    try:
        await tv.approve_job(client, found.name, issue, version=version, approver=approver,
                             comment=comment)
    except RuntimeError as exc:  # not parked at the approval gate
        return refused(CONFLICT, first_message(exc))
    return done(f"#{issue}: production release ({version}) approved by {approver}.",
                project=found.name, issue=issue, version=version, approver=approver, signaled=True)


# ── promote — run the release in this process ───────────────────────────────────────────────────

async def _promote(*, project: str, issue: str, version: str, approver: str, password: str,
                   by: Actor, comment: str = "") -> Outcome:
    """Authenticated human action to release to prod (ADR-0001 D-12), run synchronously in this
    process rather than signalled to a durable workflow — the local/dev path, where there is no
    parked Temporal job waiting for the answer because the ticket was never durable to begin with.

    MOVED FROM `api/app.py::promote_prod` verbatim, including what it does NOT do: no
    `FileNotFoundError` guard around `_forge_and_manifest`, unlike `approve_prod`'s allowlist
    lookup. A deployed panel's placeholder checkout has no manifest to release FROM either, so
    there is nothing this path could do about it — it now surfaces as a FAILED outcome carrying
    the real message (`perform`'s catch-all), where it used to be a bare 500."""
    from openfactory.adapters.environment.registry import build_observer
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.approvals import verify_approver
    from openfactory.observability.registry import journal_for
    from openfactory.orchestrator.promotion import PromotionRunner
    from openfactory.paths import events_file

    p, manifest, forge = _forge_and_manifest(project)
    if not verify_approver(approver, password, manifest.prod_approvers):
        return _approval_denied()
    # EACH AXIS ASKS ITS OWN (#162). `token_from_env()` was `OPENFACTORY_BOT_TOKEN`, else a minted
    # GitHub App installation token — one vendor's credential, handed to a tracker and to an
    # observer on a path that names no vendor. It also OVERRODE a project's own PAT, because an
    # explicit `token=` wins over everything the registry rows resolve for themselves. The
    # observer watches the FORGE's CI, so it takes the forge axis's credential.
    from openfactory.credentials import (
        deployment_forge_token,
        deployment_tracker_token,
        forge_token_for,
        tracker_token_for,
    )

    tracker_tok = tracker_token_for(p) or deployment_tracker_token(p)
    runner = PromotionRunner(
        tracker=build_tracker(p, token=tracker_tok), forge=forge,
        observer=build_observer(p, token=forge_token_for(p) or deployment_forge_token(p)),
        manifest=manifest,
        events=journal_for(events_file(p, issue)),
        language=str(getattr(p, "language", "") or ""),  # #160: the release speaks the project's
    )
    result = runner.release_prod(f"#{issue.lstrip('#')}", version=version, approver=approver,
                                 comment=comment)
    return done(f"#{issue}: {result.note or result.state.value}",
                project=p.name, issue=issue, state=result.state.value, note=result.note)


# ── merge / adjust / discard — the human-gated PR becomes a question (#68, C-32) ────────────────
#
# THE GATE COULD NOT BE ANSWERED AT ALL before these. With `merge_policy: human` the workflow
# stays alive inside its merge watch for up to fourteen days, but `_paused` is never set — so
# `awaiting_action` is None, `act_job` refuses before signalling, and resume/skip both come back
# CONFLICT. The human path cannot self-heal either: the one branch that merges a clean PR is
# gated on `auto_merge`, which is False precisely when a human is the gate. A green, reviewed,
# human-gated PR had exactly two exits — somebody clicking merge on github.com, or fourteen days
# elapsing. That is the "In review nobody is asked" the card is named for.
#
# ONE SEAM, THREE ROWS. All three go through `view.answer_merge_gate`, which queries the gate
# before signalling so a stale answer is refused rather than swallowed.

#: How long an `adjust` instruction may be. It is free text typed into a panel that lands in an
#: agent's context at the same trust level as the ticket body, and verbatim in an audit line.
_ADJUST_MAX_CHARS = 2000


async def _answer_gate(*, project: str, issue: str, by: Actor, answer: str,
                       instruction: str = "") -> tuple[dict | None, Outcome | None]:
    """`(merge-wait dict, None)` or `(None, refusal)` — the part all three rows share."""
    from openfactory.runtime.temporal import view as tv
    from openfactory.util.causes import first_message

    found, bad = _project(project)
    if bad:
        return None, bad
    client, bad = await _connected()
    if bad:
        return None, bad
    try:
        gate = await tv.answer_merge_gate(client, found.name, issue, answer=answer,
                                          instruction=instruction, by=str(by))
    except tv.GateDeaf as exc:
        # The OPPOSITE of the case below: the job IS waiting on a merge, and its run can never
        # consume an answer (pre-patch replay). Folding this into 'not waiting on a merge' told
        # the operator the PR may have merged when the truth is the gate is deaf.
        return None, refused(CONFLICT, f"#{issue} is waiting on a merge it cannot hear: {exc}")
    except RuntimeError as exc:  # the engine answered: this job is not at the merge gate
        return None, refused(
            CONFLICT,
            f"#{issue} is not waiting on a merge — it may have merged already, been closed, or "
            f"never opened a PR. ({first_message(exc, limit=120)})")
    except Exception as exc:  # noqa: BLE001
        if _looks_missing(exc):
            return None, refused(
                NOT_FOUND, f"no job has ever run for #{issue} on {found.name}.")
        raise
    return gate, None


async def _merge(*, project: str, issue: str, by: Actor, comment: str = "") -> Outcome:
    """Land the PR a human-gated job is waiting on.

    TAKES NO `pr` PARAMETER, deliberately. The PR comes from the engine's own gate payload, so
    holding the panel token cannot be turned into merging an arbitrary PR in the repository.

    SAYS ASKED, NEVER MERGED. The forge can still refuse — branch protection this App cannot
    satisfy — and it reports that by returning False rather than raising, so the only honest
    thing this can claim is that the factory is now landing it. The workflow parks with the
    reason if the forge says no."""
    gate, bad = await _answer_gate(project=project, issue=issue, by=by, answer="merge")
    if bad:
        return bad
    return done(
        f"#{issue}: merging the PR now — {by} approved it. The card moves to Merged when the "
        f"forge confirms; if branch protection refuses, the job parks and says so.",
        project=project, issue=issue, answer="merge", pr_url=(gate or {}).get("pr_url"),
        by=str(by), comment=comment[:280])


async def _adjust(*, project: str, issue: str, instruction: str, by: Actor) -> Outcome:
    """Send the PR back for ONE repair pass against a human's own words — same branch, same PR.

    FREE TEXT, which is the product owner's decision and the reason this is a signal parameter
    rather than a `DecisionRequest` option key: a key is matched against a fixed list at both
    consumption sites and anything unmatched is silently dropped, so free text would arrive and
    then vanish.

    THE WHITESPACE CHECK IS NOT REDUNDANT. `perform` refuses a missing or empty required
    parameter, but its test is `in (None, "")` — so `"   "` passes it and would reach an agent as
    an instruction to do nothing in particular, at full price."""
    text = (instruction or "").strip()
    if not text:
        return refused(
            INVALID,
            "say what needs changing — 'adjust' is your own words, e.g. 'the button should be on "
            "the right' or 'this needs a test for the empty case'.")
    if len(text) > _ADJUST_MAX_CHARS:
        return refused(
            INVALID,
            f"that is {len(text)} characters and the limit is {_ADJUST_MAX_CHARS} — it becomes "
            f"an agent's instruction, so it has to stay a request rather than a document.")
    gate, bad = await _answer_gate(project=project, issue=issue, by=by, answer="adjust",
                                  instruction=text)
    if bad:
        return bad
    # THE SIZE, IN THE SENTENCE (#150). This confirmation is the only thing that stands between a
    # human's words and an agent spending a full pass on them, and it echoed a 120-character
    # PREFIX — which is indistinguishable from a whole short instruction. On the pilot a pasted
    # paragraph reached this function as its last twenty-six characters, was confirmed as a
    # success, and cost a pass. No surface can detect that; every surface can print the number,
    # and a person who typed a paragraph knows at a glance that 26 is wrong.
    return done(
        f"#{issue}: sent back for one pass — {by} asked for ({len(text)} characters): "
        f"{text[:120]}{'…' if len(text) > 120 else ''}. It pushes to the same PR and the gate "
        f"re-opens when the pass is done.",
        project=project, issue=issue, answer="adjust", pr_url=(gate or {}).get("pr_url"),
        by=str(by), instruction=text[:280], length=len(text))


async def _review(*, project: str, issue: str, by: Actor) -> Outcome:
    """Ask the independent reviewer to read the open pull request again, as it stands (#181).

    THE ANSWER TO A REJECTION THAT WAS ANSWERED. `adjust` sends the work back against a person's
    own words; until this verb existed there was no way to ask whether the change did what it was
    made for, so the operator either merged on their own reading of the diff — the work an
    independent review exists to remove — or merged against a verdict about code that was gone.

    IT WRITES NOTHING, and that is the sentence that distinguishes it from its two neighbours:
    the branch, the commits and the pull request are exactly as they were. What it changes is the
    verdict on the card, which it REPLACES rather than adds to.

    AND IT COSTS. A review is a model pass, so this says the price out loud instead of reading as
    a refresh button."""
    gate, bad = await _answer_gate(project=project, issue=issue, by=by, answer="review")
    if bad:
        return bad
    return done(
        f"#{issue}: reading the pull request again for {by} — it changes no code, and the verdict "
        f"on the card is replaced by what this pass finds. The gate re-opens when it is done.",
        project=project, issue=issue, answer="review", pr_url=(gate or {}).get("pr_url"),
        by=str(by))


async def _discard(*, project: str, issue: str, by: Actor, reason: str = "") -> Outcome:
    """Close the PR without merging and free the floor.

    NOTHING IS DELETED — `gh pr close` leaves the branch and its commits, so this is reversible
    and needs no password gate. The message says so, because the word promises more destruction
    than the operation performs."""
    gate, bad = await _answer_gate(project=project, issue=issue, by=by, answer="discard")
    if bad:
        return bad
    return done(
        f"#{issue}: PR closed without merging by {by} — the floor is free. The branch and its "
        f"commits are untouched, so the work can be picked up again.",
        project=project, issue=issue, answer="discard", pr_url=(gate or {}).get("pr_url"),
        by=str(by), reason=reason[:280], freed=True)


# ── stop — end a job that is going nowhere, without opening the engine ──────────────────────────

async def _stop(*, project: str, issue: str, by: Actor, reason: str = "") -> Outcome:
    """End a RUNNING job that nothing else can reach, and settle its ticket (#127).

    THE GAP THIS CLOSES. A wedged job — a workflow-task failure loop — holds the single-slot floor
    for ever, and until now no row in this catalogue could end one. `resume` and `skip` answer a
    PARK, and the engine refuses them with CONFLICT for a job that is not parked; the merge-gate
    verbs answer a GATE. So the tech-lead's own rounds ended up saying, honestly, *"the exit is in
    the engine: open Temporal and terminate"* — a true sentence, and a raw-engine operation being
    asked of an operator on the one surface this product promises they will never need.

    IT REFUSES A JOB THAT IS MERELY WAITING, and that refusal is the whole safety of the row.
    A park has `resume`/`skip`; a merge gate has `merge`/`adjust`/`discard`; a production gate has
    an authenticated approval. Terminating any of those would destroy a job a person was about to
    advance, and would do it under a verb that sounds like tidying up. Every one of them is named
    in the refusal, with the verb that fits, so the answer teaches the right gesture rather than
    just withholding the wrong one.

    IT IS NOT REVERSIBLE AND SAYS SO. `discard` can afford a softer sentence because `gh pr close`
    leaves the branch; a terminated workflow does not resume — the ticket goes back to the board
    and a fresh job starts from the beginning, losing whatever the run had in flight. Admin-gated
    for that reason.

    THE TICKET IS SETTLED, NOT LEFT. A workflow terminated with nobody told is the wedged job's
    own failure mode repeated by hand: the floor frees, and the card sits wherever it was, with no
    record of who ended it or why.
    """
    from openfactory.runtime.temporal import view as tv
    from openfactory.util.causes import first_message

    found, bad = _project(project)
    if bad:
        return bad
    client, unreachable = await _connected()
    if unreachable:
        return unreachable

    handle = client.get_workflow_handle(tv.job_id(found.name, issue))
    try:
        described = await handle.describe()
    except Exception as exc:  # noqa: BLE001 — a job nobody can find is not a job to terminate
        return refused(
            NOT_FOUND,
            f"there is no job for {found.name}#{issue} in the engine "
            f"({first_message(exc, limit=120)}) — nothing was stopped.")
    if str(tv.status_label(described.status)) != "running":
        return refused(
            CONFLICT,
            f"#{issue} is not running ({tv.status_label(described.status)}) — there is nothing to "
            f"stop, and the floor is not being held by it.")

    # WAITING IS NOT WEDGED. Asked of the workflow itself, through the same queries every other
    # surface uses, so a gate added later is refused here without this function being edited.
    waiting = await _what_it_is_waiting_on(handle)
    if waiting:
        what, how = waiting
        return refused(
            CONFLICT,
            f"#{issue} is not stuck — it is waiting on {what}, which is the platform working. "
            f"Answer it with `{how}` instead. Stopping a job somebody is about to advance loses "
            f"the run, and `stop` is for a job nothing else can reach.")

    why = str(reason or "").strip()[:280]
    try:
        await handle.terminate(reason=f"stopped by {by}" + (f": {why}" if why else ""))
    except Exception as exc:  # noqa: BLE001 — the engine refused; nothing changed
        log.exception("could not stop %s#%s", found.name, issue)
        return refused(
            FAILED,
            f"could not stop #{issue}: {first_message(exc, limit=160)} — nothing was changed, and "
            f"the floor is still held.")

    settled = await _settle_after_stop(found.name, issue, by=by, why=why)
    return done(
        f"#{issue}: stopped by {by} — the floor is free. This does not resume: the ticket goes "
        f"back to the board and a fresh job starts from the beginning, so whatever that run had "
        f"in flight is gone." + ("" if settled else " The ticket itself could not be updated — "
                                 "move it by hand and say why."),
        project=found.name, issue=issue, by=str(by), reason=why, freed=True, settled=settled)


#: What a job may be waiting for, and HOW A PERSON ANSWERS IT — in words they can act on.
#:
#: NOT THE GATE'S OWN LABEL. The first version returned `tv.HUMAN_GATES`' values, so the refusal
#: for a job at the production gate told the reader to "answer it with `prod_approval`" — a label
#: this codebase uses internally and no surface parses. Teaching a verb nothing accepts is the
#: defect the merge gate paid for (#68), reproduced inside the refusal that exists to prevent a
#: worse mistake. The keys are still checked against `HUMAN_GATES` below, so a gate added later
#: is refused rather than terminated; it simply gets its own name until somebody writes its
#: sentence.
_HOW_TO_ANSWER = {
    "awaiting_action": ("a person's decision", "resume` or `skip"),
    "awaiting_merge": ("a person's merge", "merge`, `adjust` or `discard"),
    "awaiting_approval": ("a production approval",
                          "the Approve button on the panel — it needs a version and the "
                          "approver's password, which is why it is not a chat verb"),
}


async def _what_it_is_waiting_on(handle) -> tuple[str, str] | None:
    """`(what it waits for, how a person answers it)` — or None when nothing is waiting.

    THE GATES COME FROM THE SHARED TABLE, so one added to the workflow later is refused by `stop`
    without this function being touched — it just describes itself by its query name until
    somebody gives it a sentence. The park query is asked first and separately: it is the one that
    answers with a payload rather than a flag, and it is the commonest of the three."""
    from openfactory.runtime.temporal import view as tv

    for query in ("awaiting_action", *tv.HUMAN_GATES):
        try:
            answered = await handle.query(query)
        except Exception as exc:  # noqa: BLE001 — a job that cannot answer is not a job at a gate
            log.info("stop: %s did not answer %s (%s)", handle.id, query, str(exc)[:120])
            continue
        if answered:
            return _HOW_TO_ANSWER.get(query, (f"whatever `{query}` reports", "the panel"))
    return None


async def _settle_after_stop(project: str, issue: str, *, by: Actor, why: str) -> bool:
    """Put the ticket back where a person will find it, with one comment saying who and why.

    BEST-EFFORT AND REPORTED. The workflow is already terminated — refusing to say so because the
    tracker blinked would leave the operator believing nothing happened, which is worse than a
    card in the wrong column."""
    import asyncio

    from openfactory.contracts import JobState
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal.activities import _tracker_for

    said = f"Stopped by {by}." + (f" Reason: {why}" if why else "") + (
        " The job was terminated in the engine; nothing was merged and no branch was deleted. "
        "This ticket is back on the board and can be picked up again.")
    try:
        tracker = _tracker_for(ProjectRegistry().get(project))
        await asyncio.to_thread(lambda: tracker.set_state(issue, JobState.SKIPPED, reason=said))
        await asyncio.to_thread(lambda: tracker.comment(issue, said))
    except Exception as exc:  # noqa: BLE001 — the stop stands; only the telling failed
        log.error("OPENFACTORY_STOP_NOT_RECORDED project=%s issue=%s (%s) — the job was stopped "
                  "and the ticket does not say so", project, issue, str(exc)[:160])
        return False
    return True


# ── ask — the tech-lead answers a question, from any front end ──────────────────────────────────

async def _ask(*, project: str, question: str, by: Actor) -> Outcome:
    """The tech-lead's read-only answer about a project (C-24 made this movable).

    IT WAS REACHABLE FROM ONE VENDOR'S CHAT PRODUCT AND NOWHERE ELSE. The capability now lives in
    `techlead/conversation.py`; this row is what lets the panel and `openfactory act ask` reach the
    same tech-lead the channel reaches, rather than each front end growing its own.

    NOT ADMIN-GATED, deliberately: this reads and answers, it does not act. The `suggestion` it may
    carry is a PROPOSAL — approving it means calling `resume` or `skip`, which are gated.

    RUN OFF THE EVENT LOOP. `conversation.answer` clones a repository, shells out to `gh` and runs
    an agent process, and it calls `asyncio.run` internally to read Temporal — which RAISES if
    there is already a running loop on this thread. Every caller of this layer is async, so the
    whole call goes to a worker thread; blocking the loop would also stall every other action the
    panel is serving.
    """
    found, bad = _project(project)
    if bad:
        return bad
    text = str(question or "").strip()
    if not text:
        return refused(INVALID, "a question with no words in it has no answer — say what to ask.")

    # THE THREAD IS WRITTEN DOWN, BOTH HALVES (#123). Everything the factory says already lands in
    # the panel's message store; what a PERSON said lived in a browser tab, so a refresh lost the
    # question, the answer and any staged suggestion — and the two halves rendered as two blocks,
    # which is why a narration could appear above a question asked before it. One feed, one clock.
    #
    # Best-effort and BEFORE the work: a store that will not write must cost the thread its record,
    # never the operator their answer.
    _remember(found.name, text, by=by)

    # AN INSTRUCTION IS NOT A QUESTION (#120). This row is deliberately not admin-gated because it
    # reads and answers — so it does not act here either: `_floor_say_as_an_intent` routes through
    # `perform`, which applies the same scope and admin check the panel's button goes through, to
    # the same actor. A credential that cannot press Merge cannot type its way past it.
    #
    # Anything that is not an unambiguous instruction — a question, a sentence about merging
    # rather than an order to merge, an ambiguous floor with two jobs waiting — falls through to
    # the tech-lead below and is answered in prose, which is what this row was always for.
    # A PLAIN "YES" ANSWERS THE QUESTION THE PLATFORM ITSELF ASKED (#156), and it is checked FIRST
    # because it is the least ambiguous thing in this function: the tech-lead put a button on the
    # screen, and the person is looking at it. It only fires when something is actually staged —
    # `run_staged` says which of superseded/answered/expired when it is not, so a yes arriving a
    # minute late is told what happened instead of quietly becoming a new question.
    from openfactory.actions.floor_intents import is_affirmation

    if is_affirmation(text):
        from openfactory.memory import messages as channel

        try:
            live = channel.staged(found.name)
        except Exception as exc:  # noqa: BLE001 — an unreadable store must not eat the question
            log.warning("could not check whether %s has a staged suggestion (%s) — the message "
                        "goes to the tech-lead as a question", found.name, str(exc)[:160])
            live = None
        if live is not None:
            accepted = await run_staged(project=found.name, by=by)
            _remember(found.name, accepted.message, factory=True)
            return accepted

    routed = await _floor_say_as_an_intent(text, project=found.name, by=by)
    if routed is not None:
        # A ROUTED INSTRUCTION IS PART OF THE CONVERSATION TOO. It never reaches the worker, so
        # nothing else would ever write it down — and "I told it to merge and it said X" is
        # precisely the turn somebody will want to find again.
        _remember(found.name, routed.message, factory=True)
        return routed

    # DISPATCHED TO THE WORKER, never executed here. This used to call
    # `conversation.answer` in whichever process served the request — and the panel's
    # process holds no harness credential (deliberately; it is the outward-facing
    # surface), so the tech-lead's "answer" there was the CLI's own "Not logged in ·
    # Please run /login", returned with a straight face. The agent runs where agents
    # run and authenticate: the worker, as a workflow, so the question also survives
    # the asker and shows up costed in the engine like every other invocation.
    client, bad = await _connected()
    if bad:
        return bad
    # WHAT THIS ASKER MAY ACTUALLY BE OFFERED, decided HERE and carried as data (#121). The
    # tech-lead runs on the worker, where the actor does not travel and must not be reinvented —
    # authority resolved down there would be authority granted down there. So the two checks
    # `perform` applies are applied here, to the actor that came through the door, and the answer
    # travels as a list of row names. A credential that cannot press Merge is never told to ask
    # for it, and its "ok" would be refused by `perform` anyway if it were.
    from openfactory import actions as _actions
    from openfactory.runtime.temporal import TASK_QUEUE
    from openfactory.runtime.temporal.io import AskInput

    try:
        raw = await client.execute_workflow(
            "AskWorkflow", AskInput(project=found.name, question=text,
                                    can=list(_actions.proposable(by)),
                                    thread=_thread_so_far(found.name, without=text)),
            # A FRESH ID PER QUESTION (#167). This was `abs(hash(text)) % 10**8`, which reads as
            # idempotency and is neither: Python's `hash` is salted per PROCESS, so the same
            # question asked twice in one panel deduplicates against itself — the second asker
            # silently receives the first one's answer — while the same question after a restart
            # does not. A question is not idempotent spend (`maximum_attempts=1` says so one file
            # over); two people asking the same thing deserve two answers.
            id=f"openfactory-ask-{found.name}-{uuid.uuid4().hex[:12]}",
            task_queue=TASK_QUEUE,
        )
    except Exception:  # noqa: BLE001 — an answer path must degrade, never raise
        log.exception("the tech-lead could not answer a question about %s", found.name)
        return refused(FAILED, "I could not work that out just now.")

    answer_text = str((raw or {}).get("text") or "")
    suggestion = [s for s in (raw or {}).get("suggestion") or [] if s]
    if not answer_text:
        return refused(FAILED, "the tech-lead produced no answer — check the worker's logs.")
    _remember(found.name, answer_text, factory=True,
              suggestion=(str(suggestion[0]), str(suggestion[1])) if len(suggestion) >= 2
              else None,
              # THE INSTRUCTION RIDES WITH THE PROPOSAL (#170), or `adjust` stages a button that
              # `perform` refuses for a missing required parameter — an approval that does nothing.
              params={"instruction": str(suggestion[2])} if len(suggestion) >= 3 and suggestion[2]
              else None)
    return done(answer_text,
                suggestion=suggestion or None,
                # WHAT IT COST, on the Outcome the asker already reads (#167). Every other agent
                # pass in this platform is priced; the one a person talks to was not.
                spend=(raw or {}).get("spend") or None,
                asked_by=by.id)


#: How much of the thread rides along. A budget in CHARACTERS rather than turns, because a turn
#: can be one word or a diagnosis — and token-efficiency is a promise, not a preference. Roughly
#: six ordinary exchanges; `transcript.recent` is newest-biased inside it.
_THREAD_BUDGET = 2400


def _thread_so_far(project: str, *, without: str = "") -> str:
    """The prior turns of this project's tech-lead conversation, rendered for the prompt (#168).

    NEVER RAISES AND NEVER BLOCKS AN ANSWER. A thread that cannot be read is a poorer answer, not a
    missing one — the same posture `_remember` takes one function down, for the same reason.

    `without` drops the turn just recorded: the question is already in the prompt as the question,
    and reading it back as history invites the model to answer it twice.
    """
    from openfactory.memory import transcript

    try:
        turns = [t for t in transcript.of_messages(project, budget=_THREAD_BUDGET)
                 if not (without and t.text == without)]
        return transcript.render(turns, agent_name="tech-lead")
    except Exception as exc:  # noqa: BLE001 — a thread we cannot read must not cost the answer
        log.warning("could not read the tech-lead thread for %s (%s) — answering without it",
                    project, str(exc)[:160])
        return ""


def _remember(project: str, text: str, *, by: Actor | None = None, factory: bool = False,
              suggestion: tuple[str, str] | None = None,
              params: dict[str, str] | None = None) -> None:
    """Write one turn of the tech-lead thread into the panel's own message store (#123).

    THE SAME STORE EVERYTHING ELSE THE FACTORY SAYS ALREADY USES — no new database, no new
    retention to forget, nothing to provision, and the free deployment keeps its promise that
    nothing is lost without a cloud. It is also what makes the thread ORDERED: both halves now
    carry a timestamp from one clock, where before the browser held one half with no clock at all
    and drew it after everything the server knew.

    AND THE STAGED SUGGESTION TRAVELS WITH IT. That was the expensive half of the refresh: the
    tech-lead ends an answer proposing one concrete action, the panel renders it as a button, and
    the operator approves by pressing it. Held only in the tab, a refresh at that moment discarded
    a decision the platform had just asked a human to make — a wait ending in nothing, which is the
    one shape this platform is not allowed to have. The proposal now rides on the row as a token
    and a payload, so the button is rebuilt from the store on any screen (`messages.staged`).

    NEVER RAISES AND NEVER BLOCKS AN ANSWER. Losing the record of a question is a bad day; refusing
    to answer it because the record failed is a worse one."""
    import json

    from openfactory.memory import messages

    try:
        if not factory:
            messages.told(project, text, by=str(by or ""), channel=project)
            return
        token = payload = ""
        if suggestion:
            token = messages.suggestion_token(suggestion[0], suggestion[1])
            payload = json.dumps({"suggestion": list(suggestion[:2]),
                                  "params": dict(params or {})})
        messages.say(project, text, channel=project, token=token, payload=payload)
    except Exception as exc:  # noqa: BLE001 — the conversation matters more than its transcript
        log.warning("could not record a tech-lead turn for %s (%s) — the answer still went out",
                    project, str(exc)[:160])


# ── running what the tech-lead proposed — ONE implementation, two doors (#156) ───────────────────

async def run_staged(*, project: str, by: Actor, token: str = "") -> Outcome:
    """Perform the action the tech-lead staged, and retire the button — whoever accepted it.

    THE DEFECT THAT MADE THIS A FUNCTION. The tech-lead ended an answer proposing `merge #101`; the
    operator typed *"pode seguir"*; nothing happened. The proposal could only be accepted by
    PRESSING it — so on the one screen where the platform itself asks a yes/no question, an answer
    in words did not count. That is this repository's own rule inverted: a wait is a QUESTION, and
    "a human who has decided in words has decided" is the sentence `floor_intents` exists for.

    A SECOND COPY OF THIS SEQUENCE WOULD HAVE BEEN THE REAL MISTAKE. `perform` → `answer` → `say`
    is three steps and every one of them matters: the first applies the scope and admin check to
    the credential that ACCEPTED (not the one that composed), the second retires the button on
    every screen, and the third puts the outcome in the thread. Written twice, the two doors drift
    — which is the defect class this file already paid for on the product gate (#105).

    `token` is the button's rule and the words path leaves it empty: pressing names WHICH proposal,
    so a click on a stale page is refused rather than applied to the replacement; typing "yes"
    means the one that is live, whatever it is, because that is what the person is looking at.
    """
    from openfactory import actions
    from openfactory.memory import messages as channel
    from openfactory.observability.query import StoreUnreadable

    try:
        found = channel.staged(project)
    except StoreUnreadable as exc:
        # NEVER "the tech-lead is not proposing that". An outage that renders as a refusal blames
        # a person for a decision nobody made — the rule `_readable_store` states for the routes.
        log.error("the message store would not answer while checking %s's proposal: %s",
                  project, exc)
        return refused(UNAVAILABLE,
                       "could not check what the tech-lead is proposing — the message store did "
                       "not answer. Nothing was lost and nothing was done; try again.")
    if found is None or (token and found[0].token != token):
        return refused(CONFLICT,
                       "that is not what the tech-lead is proposing now — reload the "
                       "conversation. Nothing was done.")
    message, why = found
    if why:
        return refused(CONFLICT, {
            "answered": "somebody already ran that one — nothing was done again.",
            "expired": "that suggestion is too old to press; ask the tech-lead again so it can "
                       "look at the floor as it is now.",
        }.get(why, f"that suggestion is no longer open ({why})."))
    proposal = channel.read_suggestion(message)
    if proposal is None:  # pragma: no cover — `staged` only returns rows that decode
        return refused(CONFLICT, "that suggestion cannot be read any more")

    # `**params` IS THE POINT OF THE THIRD SLOT (#170). A staged `adjust` without its instruction
    # is `perform` refusing a required parameter — an approval that does nothing, which is the one
    # failure shape a button must never have. `perform` type-checks whatever arrives, both
    # directions, so this widens what can be PROPOSED and not what can be performed.
    action, ref, params = proposal
    outcome = await actions.perform(action, by=by, project=project, issue=ref, **params)
    # THE DECISION IS RECORDED WHATEVER THE OUTCOME — it retires the button either way. A refusal
    # is an answer, and a proposal somebody has pressed and been refused must not sit there
    # inviting the same click. What went wrong travels in the thread beside it.
    channel.answer(project, token=message.token, answer="approve", by=str(by.id or by.display))
    channel.say(project, outcome.message, channel=project)
    return Outcome(ok=outcome.ok, message=outcome.message, code=outcome.code,
                   data={**dict(outcome.data), "token": message.token,
                         "action": action, "issue": ref, "params": params})


# ── diagnose — why is it parked, and what would move it ─────────────────────────────────────────

async def _diagnose(*, project: str, issue: str, by: Actor) -> Outcome:
    """The tech-lead's analysis of a parked job, produced on demand.

    THE GAP THIS CLOSES. Diagnosing lived inside `activities._do_diagnose`, reachable only from the
    impediment path a workflow takes on its way to parking — so the tech-lead could explain a
    failure the moment it happened and never again. A human looking at a job that parked yesterday
    had nowhere to ask, and that is precisely the layer humans were staffing by hand.

    IT PUBLISHES NOTHING. The impediment path posts a ticket comment and a channel notice because
    nobody is watching a job that just parked; an operator asking this IS watching, and a duplicate
    comment per question is how a ticket becomes unreadable.

    REFUSED WHEN THE JOB IS NOT PARKED, rather than answered anyway. Diagnosing a running job costs
    an agent pass and a repository clone to explain a problem that does not exist yet.

    RUN OFF THE EVENT LOOP: this clones a repository, shells out to `gh` and runs an agent process.
    """
    import asyncio

    from openfactory.contracts import handoff_to_plain
    from openfactory.runtime.temporal import view as tv

    # ALIASED. Unaliased, this line SHADOWS the module-level `from openfactory import namespace`,
    # and the call below then reads identically whether the shadow is there or not — one of the two
    # spellings raises `TypeError`. `_waiting_on_a_human` is where that cost a merge.
    from openfactory.runtime.temporal.connection import namespace as temporal_namespace
    from openfactory.techlead import diagnosis

    found, bad = _project(project)
    if bad:
        return bad
    client, bad = await _connected()
    if bad:
        return bad

    ref = str(issue).lstrip("#")
    job = next((j for j in await tv.list_jobs(client, temporal_namespace())
                if j.get("project") == found.name and str(j.get("issue")) == ref), None)
    if job is None:
        return refused(NOT_FOUND, f"no job for #{ref} on {found.name} — nothing to diagnose.")
    act = job.get("action") or {}
    if not (job.get("attention") or act.get("note") or act.get("decision")):
        return refused(
            CONFLICT,
            f"#{ref} is not waiting on anybody — it is {job.get('state') or 'running'}. "
            f"A diagnosis costs an agent pass and a checkout; ask when it parks.")

    ho = await asyncio.to_thread(diagnosis.diagnose, found, issue=ref,
                                 state=str(job.get("state") or ""),
                                 note=str(act.get("note") or ""))
    if ho is None:
        return refused(
            FAILED,
            f"the tech-lead could not produce a readable diagnosis of #{ref}. The raw note still "
            f"stands: {str(act.get('note') or '')[:200]}")
    return done(handoff_to_plain(ho), issue=ref, headline=ho.headline, asked_by=by.id)


# ── env — the onboarding round: PROPOSE, then verify, and write only on consent ─────────────────
#
# WHY THESE ROWS EXIST, in one sentence: everything this platform had before them VERIFIES what a
# client already declared. `doctor` grades the machine, `conformance` grades the manifest, `box
# prove` grades the box — three graders and nothing that PROPOSES. On a fifteen-year-old codebase
# the hard part is not verifying the test command; it is finding it among four candidates, three of
# which only work on one developer's laptop. There is an agent that can read a repository sitting
# right there, and until now nothing pointed it at this question.
#
# WHY THEY ARE ROWS AND NOT JUST TYPER CODE (ADR-0039, ADR-0038). The panel is the reference
# surface. A `openfactory env` that existed only as CLI code would be the next capability reachable
# from
# exactly one place — the defect class this repository has shipped some twenty times — and the one
# place would be a laptop, which is the machine that cannot answer the question. The CLI below is a
# mapping onto these three rows and holds no logic of its own.
#
# WHAT THEY MAY NOT DO, and it is physical rather than a promise: nothing here touches the tracker,
# the board, a branch or a pull request; `env_read` and `env_check` write not one byte anywhere;
# and `env_apply` writes exactly one file, in the client's own checkout, only when a human passed
# `yes`, and never over an existing file without `force`. A client whose hand-tuned
# `.openfactory/project.yaml` is destroyed by a helpful tool is a client who never runs that tool
# again.

#: What this platform is allowed to say about a value it proposes, strongest first. Same shape, and
#: the same reading, as `product/brownfield.py`'s evidence tiers: an unrecognised confidence
#: degrades DOWNWARD to `unknown`, never upward, because a mislabelled reading that claimed
#: `observed` would borrow provenance it does not have.
OBSERVED, INFERRED, UNKNOWN = "observed", "inferred", "unknown"
_CONFIDENCE = (OBSERVED, INFERRED, UNKNOWN)

#: A value a human typed in the room. Not a confidence the inference can produce — it is what
#: `env_apply --set` records, and it outranks everything above because a person said it out loud.
ANSWERED = "answered"


def _measured_on(by: Actor) -> str:
    """`worker` · `panel` · `local` — WHERE this answer was measured. Never omitted, never guessed.

    A finding with no provenance is a finding about the wrong machine, and that is how a client
    gets blamed for a Docker daemon that was fine: `doctor` runs `shutil.which` and `docker info`
    on whatever laptop typed the command and then reports the verdict in the vocabulary of the
    factory. Every row below carries this so a reader can tell the two apart.

    Only `worker` is DETECTED, and it is detected from something this process actually did rather
    than from an environment variable somebody has to remember to set: which registry file it read.
    `/var/lib/openfactory/registry.yaml` is the deployment's own mounted registry
    (`LIVE_REGISTRY_PATH`),
    so a process reading that file is running inside the deployment. The transport answers the
    other two, because the panel knows it is the panel and a shell knows it is a shell."""
    from openfactory.registry import LIVE_REGISTRY_PATH, ProjectRegistry

    if (by.via or "").strip().lower() == "panel":
        return "panel"
    if ProjectRegistry().path == LIVE_REGISTRY_PATH:
        return "worker"
    return "local"


def _jsonable(value: object) -> object:
    """A value any transport can carry — the panel serialises to JSON and the CLI prints.

    The fallback is `str()` rather than a drop, because a value this function cannot classify is
    still a value somebody proposed, and silently omitting it would take a field out of the report
    that the inference had actually found."""
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(v) for v in value]
    return str(value)


def _declares(value: object) -> bool:
    """Would writing this value into a manifest DECLARE anything? `None` and the empties do not.

    THIS IS THE `None` / `[]` RULE ARRIVING AT THE FILE, and it took a measurement to see. The two
    are different ANSWERS — `[]` is *we read the source and it installs nothing*, which is a real
    reading with evidence behind it — but they are the same DECLARATION, which is none: every
    manifest field this pass proposes already defaults to the empty container (`setup: []`,
    `components: {}`, `validate: {}`), so a line carrying one changes no behaviour at all.

    What it does change is the only signal anybody has that a human ever filled the file in.
    `Manifest.declared_keys()` reports `model_fields_set`, and `doctor._manifest` reads exactly
    that to tell "declares nothing — this project has no gates and a run with no gates reports
    green having proven nothing" (`ok=False`) from "declares N of 31 settings" (`ok=True`).
    Measured before this guard existed, on a one-stack repository with no readable CI:
    `env apply --yes` wrote a manifest whose entire content was `components: {}`, exited 0, and
    `doctor` then reported it `ok` as *"declares 2 of 31 settings"* — a file with no gates in it,
    graded healthy, produced by us. The refusal that exists two branches below ("an empty manifest
    LOADS, declares nothing, and is then reported as healthy, which is worse than no file at all")
    never fired, because an empty container had been counted as a field.

    The reading is NOT lost: the row stays in the report, in the YAML header, and in `skipped`
    with its citation. Only the no-op line in the document goes. This is also what
    `onboarding/infer.to_manifest_dict` already does for both fields — the sibling that writes the
    same document by another route — so the two agree rather than differing by an accident.

    A HUMAN'S OWN ANSWER IS EXEMPT (see the caller). This judges what the PLATFORM proposed; a
    person who typed `--set setup=` said something, and overruling the person in the room is not
    this function's business.
    """
    if value is None:
        return False
    if isinstance(value, str | Mapping | list | tuple | set | frozenset):
        return bool(value)  # 0 and False are values somebody set; "" and [] and {} are not
    return True


def _entry_point(thing: object, *names: str) -> tuple[object | None, str]:
    """`(callable, "")` or `(None, what-it-does-export)` — how this layer asks another module.

    THREE SHAPES, AND THE THIRD IS NOT HYPOTHETICAL. `openfactory/onboarding/__init__.py` re-exports
    its
    own `infer` FUNCTION, which shadows the `infer` SUBMODULE on the package — so
    `from openfactory.onboarding import infer` hands back a function and `infer.propose` is an
    `AttributeError`, measured. That is the same defect class as `getattr(bundle, "modules")` on a
    field actually called `module_map`: it does not crash where you can see it, it crashes inside
    a `try` and comes back as a sentence about the client's repository.

    So the entry point is RESOLVED and a failure to resolve it NAMES what the module does export,
    rather than sending the one person who does not yet know this system to read a two-thousand
    line module hunting for a function name."""
    import types

    for name in names:
        found = getattr(thing, name, None)
        if callable(found):
            return found, ""
    if callable(thing) and not isinstance(thing, types.ModuleType):
        return thing, ""
    exports = ", ".join(n for n in dir(thing) if not n.startswith("_"))
    return None, exports or "nothing public"


def _cite(entry: object, get) -> str:
    """Where a proposed value came from, as one string a human can go and open.

    TWO SPELLINGS, both first-class. A plain `source` string is what the contract named; a list of
    evidence objects with `path`/`line` is what the module that landed produces, and reading only
    the first would have printed `(no source recorded)` under EVERY field of a proposal that cited
    every one of them — a confident, wrong, and very calm report."""
    direct = str(get("source", "") or "")
    if direct:
        return direct
    raw = get("evidence", None)
    if raw is None:
        return ""
    items = raw if isinstance(raw, list | tuple) else [raw]
    out = []
    for item in items[:3]:  # three citations is already more than anybody reads aloud
        if isinstance(item, str):
            out.append(item)
            continue
        locator = getattr(item, "locator", None)
        if isinstance(locator, str) and locator:
            out.append(locator)
            continue
        pick = item.get if isinstance(item, Mapping) else (lambda k, _i=item: getattr(_i, k, None))
        path, line = pick("path"), pick("line")
        if path:
            out.append(f"{path}:{line}" if line else str(path))
    return ", ".join(out)


def _row(name: str, entry: object) -> dict | None:
    """One proposed field as a plain dict, or `None` when `entry` is not a proposed field at all.

    A `confidence` is what makes an entry a proposal: without one there is no claim about how sure
    the platform is, and printing the value anyway would give a guess the same weight as a
    measurement in the one report a client's developers read out loud."""
    get = entry.get if isinstance(entry, Mapping) else (lambda k, d=None: getattr(entry, k, d))
    raw = get("confidence", None)
    if raw is None:
        return None
    confidence = str(raw).strip().lower()
    if confidence not in _CONFIDENCE:
        confidence = UNKNOWN
    # THE RUNNERS-UP ARE CARRIED, not dropped. On a legacy repository there are four candidate test
    # commands and the interesting output is the list, not the winner: the developer in the room
    # recognises theirs faster from a list of four than from one confident wrong line.
    others = []
    for alt in (get("candidates", None) or [])[1:4]:
        pick = (alt.get if isinstance(alt, Mapping)
                else (lambda k, d=None, _a=alt: getattr(_a, k, d)))
        others.append({"value": _jsonable(pick("value", None)),
                       "source": _cite(alt, pick), "why": str(pick("why", "") or "")})
    return {
        "name": name,
        "value": _jsonable(get("value", None)),
        "source": _cite(entry, get),
        "confidence": confidence,
        "note": str(get("note", "") or ""),
        "candidates": others,
    }


#: What a proposal may also carry ABOUT ITSELF — coverage, and the questions it refuses to guess.
#: Read tolerantly and never required: a proposal without them is a smaller answer, not a broken
#: one. Every entry here exists because its ABSENCE would read as good news — "no unreadable
#: directories" and "nobody looked" are the same silence.
_PROPOSAL_EXTRAS = ("cannot_express", "questions", "ci_files_read", "ci_files_seen",
                    "not_attempted", "unreadable_dirs", "files_walked", "truncated")


def _extras(proposal: object) -> dict:
    out: dict[str, object] = {}
    for name in _PROPOSAL_EXTRAS:
        value = getattr(proposal, name, None)
        if value is None and isinstance(proposal, Mapping):
            value = proposal.get(name)
        if value not in (None, [], ""):
            out[name] = _jsonable(value)
    return out


def _proposed_rows(proposal: object) -> tuple[list[dict] | None, int]:
    """`(rows, unreadable)` — the proposal flattened, or `(None, n)` when it could not be READ.

    **`None` and `[]` are different answers and this is where the difference is most expensive.**
    `[]` means the inference ran and proposed nothing, which is an honest thing to say about an
    empty repository. `None` means `openfactory.onboarding.infer` returned a shape this transport
    does not
    understand — and rendering that as an empty proposal would put a confident blank report in
    front of a client's developers, which is the failure-looks-like-an-answer defect with an
    audience. The caller refuses on `None`; it prints on `[]`.

    `unreadable` counts entries that were present and not field-shaped. They are skipped rather
    than fatal — a proposal object carrying its own metadata (`repo`, `commit`) alongside the
    fields is a reasonable shape — but the count is returned so the report can SAY it skipped
    something instead of quietly narrowing what the client is shown.
    """
    if proposal is None:
        return None, 0
    raw: object = proposal
    for attr in ("fields", "proposed", "proposal"):
        if hasattr(raw, attr):
            raw = getattr(raw, attr)
            break
    else:
        dump = getattr(raw, "model_dump", None)  # a pydantic proposal, flattened by its own rules
        if callable(dump):
            raw = dump()

    if isinstance(raw, Mapping):
        entries: list[tuple[str, object]] = [(str(k), v) for k, v in raw.items()]
    elif isinstance(raw, list | tuple):
        entries = [(str(_field_name(e) or f"field[{i}]"), e) for i, e in enumerate(raw)]
    else:
        return None, 0

    rows, unreadable = [], 0
    for name, entry in entries:
        one = _row(name, entry)
        if one is None:
            unreadable += 1
        else:
            rows.append(one)
    if not rows and unreadable:
        # Every entry was unreadable: this is the "shape I do not understand" case, not an empty
        # repository. Reporting it as an empty proposal is the exact lie this returns None to stop.
        return None, unreadable
    return rows, unreadable


def _field_name(entry: object) -> str:
    get = entry.get if isinstance(entry, Mapping) else (lambda k, d=None: getattr(entry, k, d))
    return str(get("name", "") or get("field", "") or "")


def repo_for(target: str) -> tuple[object | None, Path | None, Outcome | None]:
    """`(project|None, checkout, None)` or `(None, None, refusal)` for a `<path|project>` handle.

    THE INTERPRETATION IS RETURNED, NOT ASSUMED. A bare word is looked up in the registry first and
    only then treated as a directory, and the caller prints which reading won — because "I read the
    wrong repository" is a mistake that produces a plausible report, and a plausible wrong report
    read aloud to a client's developers is worse than an error.

    Every refusal here is a DISTINCT sentence, which is the whole lesson of `doctor.py`: a project
    registered with a clone URL, a project whose `repo_path` points at a directory that does not
    exist (`docs/ONBOARDING.md`'s `/work/myapp # placeholder`, which today raises a
    `FileNotFoundError` at the client and reads as their fault) and a plain typo are three causes
    that used to arrive as one traceback.

    PUBLIC BECAUSE THE CLI SHARES IT. `openfactory env context --ask` runs the harness on the
    shell's own
    machine — the panel process has no checkout and no sandbox — so it needs the resolved path
    before it can call anything, and a second copy of this resolution in `cli.py` would mean the
    same handle could read one repository through the panel and another through the terminal."""
    from openfactory.registry import ProjectRegistry

    handle = (target or "").strip()
    if not handle:
        return None, None, refused(INVALID, "say which repository — a path, or a project name.")

    registry = ProjectRegistry()
    looks_like_path = handle.startswith(("/", ".", "~")) or "/" in handle or "\\" in handle
    if not looks_like_path:
        try:
            project = registry.get(handle)
        except KeyError:
            project = None
        if project is not None:
            raw = str(project.repo_path)
            if "://" in raw or raw.startswith("git@"):
                return None, None, refused(
                    INVALID,
                    f"{handle} is registered as a clone URL ({raw}), not a checkout on disk. "
                    f"`env read` reads a repository that is already here — clone it and pass the "
                    f"path, e.g. `openfactory env read ./{handle}`.")
            checkout = Path(raw).expanduser()
            if not checkout.is_dir():
                return None, None, refused(
                    NOT_FOUND,
                    f"{handle} is registered with repo_path {raw!r} and there is no directory "
                    f"there. Fix the registry entry (`openfactory project add …`) or pass a "
                    f"path directly — nothing was read.")
            return project, checkout, None

    checkout = Path(handle).expanduser()
    if not checkout.is_dir():
        known = ", ".join(p.name for p in registry.list()) or "none"
        return None, None, refused(
            NOT_FOUND,
            f"{handle!r} is neither a directory on this machine nor a project this deployment "
            f"knows (it knows: {known}) — nothing was read.")
    return None, checkout.resolve(), None


# ── the product role, on every transport ────────────────────────────────────────────────────────
#
# ADR-0038 says the panel is the reference surface and a channel is a transport; ADR-0040 records
# the product owner settling where the product role belongs: *"the product role is available ON THE
# PLATFORM, not in Slack"*. Both were TRUE AS DECISIONS AND FALSE AS CODE. Measured when #98 was
# opened:
#
#     openfactory/runtime/slack/product_channel.py     2,165 lines, 54 functions
#     openfactory/actions/catalog.py, product rows     0
#     openfactory/api/app.py, product routes           0
#
# So on a deployment without Slack the role swept and reconciled on a schedule and NOBODY COULD
# TALK TO IT: no way to propose a requirement, accept it, drop it or ask it anything.
#
# THE LOGIC WAS NEVER THE PROBLEM, which is why these rows are thin. `openfactory/product/module.py`
# already holds every verb — `draft`, `propose`, `accept`, `drop`, `file_issues` — with its own
# authorization, its own refusals and its own voice. The 2,165 lines in the Slack package are
# THREADS, MENTIONS AND MESSAGE FORMATTING wrapped around them. What was missing was a second
# transport, and ADR-0039 says exactly what that costs: one action, one implementation, N
# transports.


def _product_module(name: str, *, by: Actor | None = None):
    """`(module, project, None)` or `(None, None, refusal)`.

    The refusals are distinct on purpose. "No such project" and "this project has no product role"
    send different people to fix different things, and a single False would start a support
    conversation instead of ending one."""
    project, bad = _project(name)
    if bad:
        return None, None, bad
    cfg = getattr(project, "product", None)
    if cfg is None or not getattr(cfg, "enabled", True):
        return None, None, refused(
            INVALID,
            f"{name} has no product role enabled — there is nothing here to talk to. It is turned "
            f"on in the project's registry entry (`product:`), together with the documentation "
            f"repository it reasons over.")
    try:
        from openfactory.product.module import ProductModule
    except ImportError as exc:
        from openfactory.util.causes import first_message

        return None, None, refused(
            UNAVAILABLE,
            f"this deployment has no product module ({first_message(exc, limit=120)}).")
    # `via` IS THE TRUTH ABOUT WHERE THIS CAME FROM, and it is passed rather than defaulted
    # because the default is `"slack"`: a panel or CLI write recorded as a Slack one is a lie in
    # the only record that says who authorised a change to a client's requirements.
    return ProductModule(project, via=getattr(by, "via", "") or "api"), project, None


def _write_outcome(result, *, did: str, **data) -> Outcome:
    """One `WriteResult` rendered as an Outcome, keeping ITS sentence rather than inventing one.

    `product/voice.py` exists because these sentences are read by a client who was never meant to
    edit a configuration file. A transport that replaced them with "operation failed" would throw
    away the one thing this module spent a thousand lines getting right."""
    ok = bool(getattr(result, "ok", False))
    detail = str(getattr(result, "detail", "") or "")
    url = str(getattr(result, "url", "") or "")
    ref = str(getattr(result, "ref", "") or "")
    payload = dict(data, url=url, ref=ref, detail=detail,
                   number=int(getattr(result, "number", 0) or 0),
                   merged=bool(getattr(result, "merged", False)),
                   existed=bool(getattr(result, "existed", False)))
    if not ok:
        return refused(FAILED, detail or f"could not {did}, and the module said nothing about why "
                                         f"— which is itself a defect worth reporting.", **payload)
    # THE CLIENT READS `detail`; THE REF AND THE URL ARE FOR AN OPERATOR. `detail` is the sentence
    # `product/voice.py` composed for somebody who was never meant to open a pull request — and it
    # was arriving prefixed with a branch slug and a forge URL: "accepted requirement 12 —
    # req/0012-fechamento-mensal (https://github.com/acme/…/pull/57). Pronto, escrevi…". Both
    # already travel in `payload`, which is what a surface with an operator for a reader renders.
    # The `did` line survives only when the module said nothing, because a silent success still
    # has to say something happened.
    return done(detail or f"{did}{f' — {ref}' if ref else ''}", **payload)


async def _product_status(*, project: str, by: Actor) -> Outcome:
    """Whether the product role can see its corpus at all, and where that was measured.

    THE FIRST THING TO ASK ON A NEW DEPLOYMENT, and the one whose failure is silent everywhere
    else: the documentation repository is private, so a missing credential makes every other verb
    below answer "I can't see the requirements" while every test passes."""
    import asyncio

    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    health = await asyncio.to_thread(module.status_line)
    available = await asyncio.to_thread(lambda: module.available)
    ctx = await asyncio.to_thread(module.context)

    from openfactory.product.voice import corpus_state
    # THE DIAGNOSIS IS THE TEAM'S, THE SENTENCE IS THE CLIENT'S — and until now this row handed
    # `status_line` straight to whoever asked. Seen on the PO's own page, in both themes: "could
    # not read `.openfactory/product.yaml` in acme/dsk-context: could not check out acme/dsk-context
    # (branch 'main')" — a repository slug, a file path and a branch name, in front of a business
    # analyst who can act on none of them and now believes the product is broken.
    # `voice.unavailable` already existed for exactly this, and it says the true thing: the role
    # cannot see the requirements, so its answers would be guesses, and the team has been told.
    # The diagnosis still travels, under `detail`, for a surface whose reader is an operator.
    # BOTH BRANCHES, AND THE FIRST FIX ONLY DID ONE. `health()` is an operator's line in both
    # states, not just when it fails: the healthy one reads "product module ready on
    # acme/dsk-context — 12 requirements … 2 warnings" and carries `ProductLink.warnings`, which
    # are English sentences about `.openfactory/project.yaml`. Hiding the diagnosis only on the
    # failing path left the slug in front of the client on every working day and made the guard
    # pass — its fake answered `available=False`, so the arm that ships was never exercised.
    corpus = getattr(ctx, "corpus", None)
    requirements = list(getattr(corpus, "requirements", None) or ())
    promises = list(getattr(corpus, "promises", lambda: ())() or ()) if corpus is not None else []
    if not available:
        log.warning("[%s] the product corpus is unreadable: %s", proj.name, str(health)[:400])
    return done(corpus_state(available=bool(available), requirements=len(requirements),
                             promises=len(promises), language=getattr(proj, "language", None)),
                project=proj.name, available=bool(available),
                requirements=len(requirements), accepted=len(promises),
                # THE OPERATOR'S LINE IS NOT LOST — it travels for a surface whose reader has a
                # checkout, and a client-safe sentence that discarded the diagnosis would trade
                # one bad outcome for nobody able to fix the thing.
                detail=str(health or ""), measured_on=_measured_on(by))


async def _product_requirements(*, project: str, by: Actor) -> Outcome:
    """The corpus itself — every requirement, its number, title and status.

    THE READ THE WRITES ALREADY ASSUMED. `product_accept` and `product_drop` take a NUMBER, and
    until this row existed nothing on any transport could tell you what the numbers were: the
    Slack channel knew, because it had posted them into a thread somebody could scroll back
    through. On a surface without that history the only honest instruction was "type a number you
    got from somewhere else", which is how a client accepts the wrong requirement.

    `status` IS CARRIED VERBATIM, not reduced to a boolean. `proposed`, `accepted` and `observed`
    are three different things — the third is a reading of the code that nobody has confirmed
    (ADR-0019) — and a surface that showed two states would invite exactly the confirmation the
    `observed` status exists to withhold.

    READ-ONLY, so `needs_admin` is False: seeing what a client's product promises is not authority
    to change it, and a business analyst who cannot list them cannot use the writes either.
    """
    import asyncio

    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    ctx = await asyncio.to_thread(module.context)
    if not ctx.available:
        return refused(UNAVAILABLE, ctx.reason or "the product corpus could not be read.",
                       project=proj.name)
    corpus = ctx.corpus
    rows = [{"number": r.number, "title": r.title, "status": r.status, "slug": r.slug,
             "asked_by": r.asked_by, "date": r.date, "path": r.path,
             "has_decisions": bool(r.has_decisions), "affects": list(r.affects or ())}
            for r in sorted(corpus.requirements, key=lambda r: r.number)]
    return done(corpus.summary(), project=proj.name, requirements=rows,
                accepted=len(corpus.promises()), observed=len(corpus.observed()),
                # THE CORPUS'S OWN COMPLAINTS travel with it. A requirement that contradicts
                # another is a thing the person reading this list is the one who can settle.
                findings=[{"level": f.level, "message": f.message, "path": getattr(f, "path", "")}
                          for f in corpus.findings],
                measured_on=_measured_on(by))


async def _product_pending(*, project: str, by: Actor) -> Outcome:
    """What the product role has STAGED and is waiting on a person for.

    THE ONE THING NOTHING COULD ASK. `messages.pending` is reached from exactly one place —
    `/api/inbox`, a route — so the panel could show a waiting proposal and no other surface could
    even discover one existed. A client on the CLI had a proposal staged in their name, addressed
    to them, with no way to find it: the silent wait this platform exists to make impossible,
    inside the machinery built to prevent it.

    IT READS THE DURABLE STORE, NOT `_PENDING`. The in-process dict belongs to whichever worker
    staged the proposal; a panel or a CLI asking it would answer "nothing waiting" with perfect
    confidence about the wrong process's memory. `remember()` mirrors every proposal into the
    store precisely so the answer survives the process that produced it.

    THE FILTER IS STRUCTURAL, and it has to be, because this is a scoped credential reading a
    shared store. `messages.pending` returns every unanswered question the factory asked — the
    tech-lead's impediments included — and a product credential must not see the floor's. The
    discriminator is NOT the `key|fingerprint` token shape: that is a convention any caller of
    `ask_to_confirm` could match by accident, and building an authorization boundary on a string
    convention is how one becomes a leak. A staged proposal carries a FROZEN PAYLOAD, and `_thaw`
    VALIDATES it against the entry models rather than pattern-matching — anything that does not
    thaw into a proposal is, by construction, not one."""
    import asyncio

    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    del module  # the corpus is not read here — what is staged is waiting, not written

    from openfactory.memory import messages
    from openfactory.product.staging import _thaw

    try:
        waiting = await asyncio.to_thread(messages.pending, proj.name)
    except Exception:  # noqa: BLE001 — an unreadable store is an answer, not a crash
        log.exception("could not read what is staged for %s", proj.name)
        return refused(FAILED, "I could not read what is waiting just now.", project=proj.name)

    rows = []
    for q in waiting:
        entry = _thaw(getattr(q, "payload", "") or "")
        if entry is None:
            continue
        rows.append({
            "token": q.token, "text": q.text, "since": q.ts,
            # WHAT is waiting, not just that something is. "a drop" and "a decision" send the
            # reader to different judgements, and a list that says neither makes them open each.
            "kind": str(entry.get("kind") or "proposal"),
            "number": entry.get("number"),
            "approve": q.approve, "reject": q.reject,
            "thread": q.token.partition("|")[0],
        })

    # THE CLIENT'S LANGUAGE, AND NO INTERNAL SLUGS. This answered "2 proposal(s) waiting on a
    # person (accept, draft)" — English, in a thread whose every other line is the product's
    # Portuguese voice, listing routing keys nobody outside this codebase has a meaning for. The
    # kinds still travel in `pending` for a surface that wants to group by them.
    from openfactory.product.voice import waiting_on_you

    return done(waiting_on_you(count=len(rows), language=getattr(proj, "language", None)),
                project=proj.name, pending=rows, count=len(rows),
                measured_on=_measured_on(by))


#: How a staged proposal may be answered, and the third thing is never accepted. Named here rather
#: than compared inline so the refusal can list them: a transport sending `"sim"` or `"true"` is
#: telling us it does not know the vocabulary, and "that is not an answer" with the two words in it
#: ends the support conversation instead of starting one.
_ANSWERS = ("approve", "reject")


async def _product_answer(*, project: str, token: str, answer: str, by: Actor,
                          yes: object = False) -> Outcome:
    """Answer a proposal the product role STAGED — the pair of `product_pending`.

    `product_pending` lists what is waiting and hands back a token per row; this is what a person
    does about it. Until now the only ways to answer were a Slack button, a typed "sim" in the
    product channel, or the panel's own answer route — so a client who found a proposal from the
    CLI, staged in their name and addressed to them, had no way to say yes to it. A list you can
    read and cannot act on is the silent wait wearing a nicer shape.

    IT RUNS ON THE WORKER, AND THAT IS NOT A COPY OF THE CHEAP SIBLING'S SHAPE. Seven of the nine
    kinds are pure writes, but `accept` chains into the breakdown (an agent pass per unit of work)
    and `align` ends in `_role().ask_json` — and WHICH KIND A TOKEN NAMES CANNOT BE KNOWN before
    the entry is read, which only the compare-and-swap that performs it may do. So the process is
    chosen by the worst case: answering in-process would run an agent on somebody's laptop, or in
    the panel's container, which carries the harness binary and no credential for it.

    THE CONSENT IS ASKED FOR EVEN THOUGH THE ANSWER IS THE CONSENT, and the reason is that the
    answer is not always yes-shaped to the caller. A transport spells this `answer=approve`; the
    thing on the other side of it is a requirement entering a client's corpus, a card leaving
    their board or money being spent. Every other row that writes says so out loud, and one that
    quietly did not would be the exception a script reaches for.

    AUTHORISATION IS NOT RE-IMPLEMENTED HERE. `answer_staged` gates it — an approval needs
    `may_act`, a rejection allows the requester too — and names the outcome, which is what makes
    the refusal a code instead of a sentence somebody compares.
    """
    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    del module  # the act runs on the worker; this resolved the project and the product role

    # CONSENT BEFORE THE PAYLOAD, like `product_propose` two rows down. The order is not cosmetic:
    # it is what makes "refused for the wrong reason" impossible to mistake for the consent gate
    # working — a caller sending a malformed answer with no `yes` hears about the `yes`, which is
    # the thing standing between them and a write in a client's repository.
    if not _said_yes(yes):
        return refused(
            INVALID,
            f"nothing was answered: this performs what was staged — which can be a requirement "
            f"entering {proj.name}'s corpus, a card leaving their board, or work being queued. "
            f"Send `yes` to confirm. Read it first with `product_pending`.", project=proj.name)
    tok = (token or "").strip()
    if not tok:
        return refused(
            INVALID,
            "which proposal — the `token` is missing. `product_pending` lists what is waiting and "
            "carries one per row.", project=proj.name)
    said = (answer or "").strip().lower()
    if said not in _ANSWERS:
        return refused(
            INVALID,
            f"a staged proposal is answered with {' or '.join(_ANSWERS)}, not {answer!r} — a "
            f"question with two buttons cannot be answered with a third thing. Nothing was "
            f"recorded.", project=proj.name)

    client, bad_engine = await _connected()
    if bad_engine:
        return bad_engine
    from openfactory.runtime.temporal import TASK_QUEUE
    from openfactory.runtime.temporal.io import ProductAnswerInput

    try:
        raw = await client.execute_workflow(
            "ProductAnswerWorkflow",
            ProductAnswerInput(project=proj.name, token=tok, approved=(said == "approve"),
                               actor=by.id, via=getattr(by, "via", "") or ""),
            # KEYED BY THE TOKEN, which already carries the conversation AND the fingerprint of
            # exactly what was staged. Two people answering the same proposal collide on purpose —
            # the second gets the first one's result rather than performing it twice — while a
            # replacement, having a different fingerprint, is a different workflow.
            id=f"openfactory-product-answer-{proj.name}-{_workflow_safe(tok)}",
            task_queue=TASK_QUEUE)
    except Exception as exc:  # noqa: BLE001 — a write path must report, never raise
        # THE EXCEPTION DOES NOT GO IN THE SENTENCE: a Temporal timeout rendered to a client is
        # the same leak a repo slug would be.
        log.exception("the staged proposal could not be answered for %s (%s)", proj.name, exc)
        return refused(FAILED, "I could not answer that just now, and nothing was performed.",
                       project=proj.name)

    raw = raw or {}
    from openfactory.product.voice import strip_markup

    outcome = str(raw.get("outcome") or "")
    # STRIPPED, LIKE EVERY OTHER PRODUCT ROW. These sentences are written for a chat client and
    # carry `**bold**`; `Outcome.message` forbids markup, and the panel renders it as asterisks.
    text = strip_markup(str(raw.get("message") or ""))
    if outcome == "unauthorized":
        return refused(DENIED, text, project=proj.name)
    if outcome in ("gone", "replaced", "expired"):
        # CONFLICT, NOT FAILED. Nothing is wrong with the request: the proposal was answered
        # already, or replaced by a newer one, or aged out. The caller re-reads `product_pending`.
        return refused(CONFLICT, text, project=proj.name)
    if not outcome:
        return refused(FAILED, "I could not tell what happened to that proposal, so treat it as "
                               "unanswered and look again.", project=proj.name)
    return done(text, project=proj.name, token=tok, answer=said, outcome=outcome)


def _workflow_safe(token: str) -> str:
    """A workflow id fragment from a proposal token. `key|fingerprint` carries a Slack channel id
    and a hex digest, but the key is caller-supplied — so anything outside the safe set becomes
    `-` rather than travelling into an id, and the length is capped."""
    return re.sub(r"[^A-Za-z0-9_.-]", "-", token)[:120]


async def _product_triage(*, project: str, by: Actor) -> Outcome:
    """Read the board and report what is wrong with it. Writes NOTHING.

    ONE OF NINE INTENTS THAT ALREADY HAD A ROW, AND ONE OF FOUR THAT DID NOT. `_run_intent`'s
    dispatch predates the action layer, so "faz a triagem do board" reached `module.triage_board`
    through the Slack handler and through nothing else — the same client asking on the panel got
    conversation. This is the row that closes it, and it is a READ: ADR-0019's first-pass rule
    holds, because on request or on a schedule this role has the least context exactly when it is
    asked to look at everything at once.

    THE PROSE IS `voice.triage_report`, NOT A SECOND COPY. The channel composes the same sentence
    from the same function; a row that wrote its own would drift from it by the second release,
    and the client would learn that the answer depends on where they asked."""
    import asyncio

    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    report, error = await asyncio.to_thread(module.triage_board)
    if report is None:
        # THE DIAGNOSIS IS OPERATOR PROSE — English, with a repo slug in it. The log keeps it
        # whole; the caller hears that the problem is ours, which is the channel's own rule.
        log.warning("[%s] triage could not read the board: %s", proj.name, str(error)[:400])
        return refused(UNAVAILABLE, "I could not read the board just now.", project=proj.name)

    from openfactory.product.voice import strip_markup, triage_report

    cfg = getattr(proj, "product", None)
    # PLAIN, BECAUSE `Outcome.message` SAYS SO. `triage_report` writes for a person reading a chat
    # client, where `**7**` is the difference between a report and a wall of numbers — and this
    # layer forbids markup in as many words, because a message pre-decorated for Slack renders as
    # literal asterisks in the panel. One prose, two renderings; the row strips at the boundary
    # that states the rule.
    text = strip_markup(triage_report(report, language=getattr(proj, "language", None),
                                      agent_name=getattr(cfg, "agent_name", "") or ""))
    observations = list(getattr(report, "observations", None) or ())
    return done(text, project=proj.name, findings=len(observations),
                observations=[{"kind": str(getattr(o, "kind", "") or ""),
                               "ref": str(getattr(o, "ref", "") or ""),
                               "detail": str(getattr(o, "detail", "") or "")}
                              for o in observations],
                measured_on=_measured_on(by))


async def _product_baseline(*, project: str, by: Actor, yes: object = False) -> Outcome:
    """The brownfield first pass: the whole codebase read and written up as OBSERVATIONS.

    ADR-0019's shape — what the code DOES is observed, never agreed, until a person confirms it.
    It opens a pull request on the client's documentation repo and stops there.

    THIS ROW IS THE GATE, and that is not a style choice. `ProductModule.baseline` is on the
    module's own documented list of four verbs that write WITHOUT checking `may_act`, whose header
    says "THE YES IS ONE LAYER UP" — the channel was that layer and this row is the other one.
    `needs_admin` alone would not do: the panel hands `admin=True` to everybody who got through
    the door, so without the re-check any panel token opens a pull request on a client's
    documentation with nobody on `product.admins` involved. It is the `product_release` shape, for
    the same reason.

    AND IT WAITS, RATHER THAN ANNOUNCING. The channel's version runs off-thread and posts the
    result when it lands — correct there, where blocking a Socket Mode handler takes the channel
    down for everyone, and it already carries a named failure for when the announcement never
    arrives (`OPENFACTORY_PRODUCT_BASELINE_UNANNOUNCED`: the work happened, the pull request may
    exist,
    and nobody was told). A row has no such constraint and no such channel: the caller waits, like
    `product_ask`, and the answer is the return value. Nothing to deliver is nothing to lose.

    IDEMPOTENT WHERE IT COUNTS. `propose_baseline` asks the forge whether the branch already
    carries an open proposal and reports `existed` instead of writing a second one — which is what
    makes the workflow's bounded retry safe."""
    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    del module  # the pass runs on the worker; this resolved the project and the product role

    if not _said_yes(yes):
        return refused(
            INVALID,
            f"this reads {proj.name}'s whole codebase through an agent and opens a pull request on "
            f"its documentation repository — it spends real money and writes. Send `yes` to "
            f"confirm.", project=proj.name)

    import asyncio

    from openfactory.product.module import may_act, unauthorized_message

    via = getattr(by, "via", "") or "api"
    if not await asyncio.to_thread(lambda: may_act(proj, by.id, via=via)):
        return refused(DENIED, unauthorized_message(proj), project=proj.name)

    client, bad_engine = await _connected()
    if bad_engine:
        return bad_engine
    from openfactory.runtime.temporal import TASK_QUEUE
    from openfactory.runtime.temporal.io import ProductBaselineInput

    try:
        raw = await client.execute_workflow(
            "ProductBaselineWorkflow",
            ProductBaselineInput(project=proj.name, actor=by.id, via=via),
            id=f"openfactory-product-baseline-{proj.name}", task_queue=TASK_QUEUE)
    except Exception as exc:  # noqa: BLE001 — a write path must report, never raise
        log.exception("the baseline pass could not run for %s (%s)", proj.name, exc)
        return refused(FAILED, "I could not run the first pass just now.", project=proj.name)

    raw = raw or {}
    from openfactory.product.voice import strip_markup

    # THE SENTENCE COMES FROM THE WORKER, NOT FROM `_write_outcome`. `voice.baseline_done` runs the
    # failure detail through `client_safe_detail` and deliberately drops the pull request URL; the
    # generic helper interpolates both, which is the difference between a client-safe line and a
    # stack trace with a link in it.
    text = strip_markup(str(raw.get("text") or ""))
    if not raw.get("ok"):
        return refused(FAILED, text or "the first pass did not finish.", project=proj.name)
    return done(text, project=proj.name, existed=bool(raw.get("existed")),
                url=str(raw.get("url") or ""), ref=str(raw.get("ref") or ""),
                measured_on=_measured_on(by))


async def _product_needs_action(*, project: str, by: Actor, limit: object = 10) -> Outcome:
    """What is parked and WHOSE problem it is — the real classification, not a proxy.

    It reads the diagnosis the tech-lead already left on each ticket and decides whether the
    REQUIREMENT is what is wrong or somebody else's work is. Two agents conversing with no human
    in the loop is where two mistakes compound with nobody owning the result, so this reads and
    reports and touches nothing: `review_needs_action` hardcodes `may_act=False` at both return
    sites, and every decision it produces is an observation.

    IT DISPATCHES TO THE WORKER, AND `product_triage` NEXT DOOR DOES NOT — the two look like the
    same kind of read and are not. `triage_board` is a board read plus deterministic
    classification and costs nothing; this composes a git worktree of both repositories and then
    spends ONE MODEL CALL PER PARKED TICKET. Answering it in-process would run an agent inside
    the panel container, which carries the harness binary and neither its token nor the docker
    socket — a failure that passes every test here and appears only in production.

    NOT ADMIN-GATED, like `product_queue`: looking is not acting. What bounds it is `limit`, which
    is a BUDGET rather than a page size — it is what stands between a board with three hundred
    parked tickets and three hundred model calls."""
    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    del module  # the pass runs on the worker; this resolved the project and the product role
    try:
        want = max(1, min(50, int(str(limit).strip() or 10)))
    except ValueError:
        return refused(INVALID, f"{limit!r} is not a number of parked tickets to look at.")

    client, bad_engine = await _connected()
    if bad_engine:
        return bad_engine
    from openfactory.runtime.temporal import TASK_QUEUE
    from openfactory.runtime.temporal.io import ProductNeedsActionInput

    try:
        raw = await client.execute_workflow(
            "ProductNeedsActionWorkflow",
            ProductNeedsActionInput(project=proj.name, limit=want,
                                    via=getattr(by, "via", "") or ""),
            id=f"openfactory-product-needs-action-{proj.name}-{want}", task_queue=TASK_QUEUE)
    except Exception as exc:  # noqa: BLE001 — a reading path must degrade, never raise
        # THE EXCEPTION DOES NOT GO IN THE SENTENCE. `log.exception` above keeps it whole, and a
        # Temporal timeout or a connection error rendered to a client is the same defect this
        # session already closed one row over — the class does not care that the text came from
        # an engine rather than from a repo slug.
        log.exception("the product role could not review what is parked for %s (%s)",
                      proj.name, exc)
        return refused(FAILED, "I could not work that out just now.", project=proj.name)

    raw = raw or {}
    if not raw.get("ok"):
        # the operator's diagnosis stayed on the worker, in the log — this says whose fault it is
        return refused(UNAVAILABLE, "I could not look at what is parked just now.",
                       project=proj.name)

    from openfactory.product.voice import strip_markup

    return done(strip_markup(str(raw.get("text") or "")), project=proj.name,
                mine=raw.get("mine", 0), theirs=raw.get("theirs", 0),
                decisions=list(raw.get("decisions") or ()),
                measured_on=_measured_on(by))


async def _product_announce(*, project: str, by: Actor) -> Outcome:
    """The role arrives and says where things stand — the sentence a channel gets on joining.

    READ-ONLY and cheap, which is why it is worth having: it is the shortest proof a deployment
    can run that the product role is configured, sees its corpus and can speak the client's
    language, without spending an agent pass to find out."""
    import asyncio

    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    from openfactory.product.voice import strip_markup

    # `announcement()` writes `*O que eu faria primeiro:*` — emphasis for someone reading a chat
    # client, and literal asterisks in the panel. Same boundary as `product_triage`.
    text = await asyncio.to_thread(module.introduce)
    return done(strip_markup(str(text or "")), project=proj.name, measured_on=_measured_on(by))


async def _product_ask(*, project: str, question: str, by: Actor) -> Outcome:
    """Ask the product role something. READ-ONLY — it drafts, and writes nothing.

    THE DRAFT COMES BACK IN THE DATA, and that is what makes `product_propose` honest on a
    stateless transport. `ProductModule.propose` takes the answer `draft` produced rather than
    re-deriving one, *"so what a human saw in the conversation is exactly what gets committed"* —
    a second draft from the same words is a different text, and committing it would break that
    promise in the one place nobody would look.

    Anyone may ask. The gate is on RECORDING, not on thinking about it — the module's own rule.

    DISPATCHED TO THE WORKER, never executed here — the same route `ask` takes, for the same
    reason, found the same way one capability later. This row used to draft in whichever process
    served the request, behind `_harness_missing`: a check that the harness BINARY was on this
    process's PATH. Measured in the running panel container rather than trusted: it is, because
    the panel is built from `docker/worker.Dockerfile` and that ends in `npm install -g
    @anthropic-ai/claude-code`. So the guard passed on exactly the process it was written to stop,
    and what the panel actually lacks — `CLAUDE_CODE_OAUTH_TOKEN`, and the docker socket the box
    needs — was never being measured. The agent runs where agents authenticate; that makes the
    failure impossible rather than detected.
    """
    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    asked = (question or "").strip()
    if not asked:
        return refused(INVALID, "say something to the product role — an empty question drafts "
                                "nothing and spends a pass finding that out.")

    # THE SAME ROUTING `product_say` DOES, ON THE DOOR THAT IS ACTUALLY OPEN. Wiring it only into
    # `product_say` closed nothing: that row is called by no panel button, no CLI verb and no
    # channel — measured, not assumed — so "faz a triagem do board" typed into the client's ONE
    # free-text box still spent a drafting pass on a question about the board and answered with
    # prose. The gap this was meant to close was reopened by the fix, in the shape this codebase
    # has shipped twenty-one times: built, tested, reached by nothing.
    #
    # IT COMES BEFORE THE ENGINE ON PURPOSE — a recognised sentence must not cost a model pass to
    # find out it was a command.
    routed = await _say_as_an_intent(asked, project=proj.name, by=by)
    if routed is not None:
        return routed

    client, bad_engine = await _connected()
    if bad_engine:
        return bad_engine
    from openfactory.product.role import ProductAnswer
    from openfactory.runtime.temporal import TASK_QUEUE
    from openfactory.runtime.temporal.io import ProductAskInput

    try:
        raw = await client.execute_workflow(
            "ProductAskWorkflow",
            ProductAskInput(project=proj.name, question=asked, asked_by=by.id),
            id=f"openfactory-product-ask-{proj.name}-{abs(hash(asked)) % 10**8}",
            task_queue=TASK_QUEUE,
        )
    except Exception:  # noqa: BLE001 — an answer path must degrade, never raise
        log.exception("the product role could not draft for %s", proj.name)
        return refused(FAILED, "I could not work that out just now.")

    raw = raw or {}
    if not raw.get("ok"):
        return refused(FAILED, str(raw.get("error") or
                                   "the product role could not be read at all."),
                       project=proj.name)
    # REBUILT FROM THE WIRE, so every field below is the one the role produced rather than a
    # re-derivation: `product_propose` commits exactly this object and refuses to draft again.
    answer = ProductAnswer.model_validate(raw.get("answer") or {})
    draft = getattr(answer, "draft", None)
    return done(
        str(getattr(answer, "text", "") or ""),
        project=proj.name, measured_on=_measured_on(by),
        is_request=bool(getattr(answer, "is_request", False)),
        is_defect=bool(getattr(answer, "is_defect", False)),
        gesture=str(getattr(answer, "gesture", "") or ""),
        decisions=list(getattr(answer, "decisions", ()) or []),
        # THE WHOLE ANSWER, SERIALISED, so `product_propose` can commit exactly this text.
        answer=answer.model_dump(mode="json"),
        proposes_a_requirement=draft is not None,
    )


#: A sentence the client typed → the row that answers it. READ-ONLY ROWS ONLY, and the omissions
#: are the design rather than an unfinished table.
#:
#: `_run_intent` in the Slack package dispatches fourteen of these, and NINE already had a row when
#: this was written — it predates the action layer, so moving it into the core would have installed
#: a second dispatcher beside the catalogue and duplicated nine rows. ADR-0039's shape is one
#: action, one implementation, N transports: the transport recognises the sentence, the catalogue
#: performs it, and the day `_run_intent` goes it will be a deletion rather than a move.
#:
#: WHY NO WRITE INTENTS. `close`, `drop`, `decision`, `fact`, `defect`, `refine`, `align` and
#: `accept` all take consent, and consent needs a SECOND turn — the role says what it understood,
#: the person says "sim", and something must remember the proposal in between. That is the staging
#: machinery, whose executor lives in `product.channel.handle`. Routing a write here without
#: it would either act with no confirmation, or refuse and lose the proposal on the next message.
#: `baseline` is left out for the same reason and not because it is unreachable — it has a row and
#: a CLI verb; what it does not have is a way to hear "sim".
#:
#: `queue` IS LEFT OUT BECAUSE ITS ROW HAS NO SENTENCE. `product_queue` answers "queue proposed
#: for <project>." and puts the actual proposal in `data` — fine for a surface that renders a
#: table, useless as a reply to somebody who typed "o que fazemos agora?" in Portuguese and would
#: read six English words after a pass that spent money. Routing to it would have been worse than
#: not routing: the client pays for an answer and is shown a receipt. It goes back in when the row
#: composes a sentence.
#:
#: THIS IS WHERE THE PANEL'S TURN SPLITS READ FROM WRITE, and the split is deliberate (2026-08-25).
#: The chat handler's `_run_intent` dispatches fourteen typed intents; the four here are the
#: READ-ONLY ones. The other ten — fact, accept, drop, decision, close, align, refine, breakdown,
#: baseline, queue — STAGE a proposal for a yes to perform, and they stay off the panel's path
#: this wave: a "quebra o requisito 7" typed in the product box would act under the panel actor's
#: `may_act`, which is a product decision (two core dispatchers, ten beside four) and not a port.
#: Until it is taken, the panel writes through its rows (`product_propose`, `product_accept`, …)
#: and a message that names a write falls to conversation, where it is read and not performed.
#: `test_nothing_stages_a_proposal_under_the_panel_s_key_yet` measures the consequence.
_SAY_INTENTS: dict[str, str] = {
    "triage": "product_triage",
    "needs_action": "product_needs_action",
    "announce": "product_announce",
    "status": "product_status",
}


async def _waiting_on_a_human(project: str) -> list[dict] | None:
    """The project's jobs parked at the merge gate — `[{issue, pr_url}]` — or None for "I could
    not look".

    THE SAME `action.kind` THE PANEL'S MERGE BUTTON READS, imported from the module that produces
    it, so a sentence and a button can never disagree about which job is waiting.

    THREE ANSWERS, NOT TWO, AND THE PILOT PAID FOR THE MISSING ONE (2026-08-16). `[]` and "the read
    failed" used to be the same value, and this function then failed for a reason of its own: it
    called `namespace()`, which at module scope is `openfactory.namespace` — a MODULE. Every call
    raised `TypeError`, the blanket `except` below turned it into "nothing is waiting", and the
    operator's *"pode fazer o merge"* was handed to the tech-lead, which answered — correctly, for
    a floor it was told was empty — that there was nothing for it to merge. A live pull request was
    sitting at the gate the whole time, on screen, one button away.

    So `None` is now its own answer and the caller must say it out loud. An unreadable floor is a
    thing that happened; it is not a floor with nothing on it.
    """
    from openfactory.runtime.temporal import view as tv

    # ALIASED, NOT SHADOWED. `from …connection import namespace` would also work here — it is what
    # `_diagnose` did — but only by re-binding a module-level name inside one function, which is
    # exactly the arrangement that produced the defect above: the call reads as correct in both
    # functions and is correct in only one of them.
    from openfactory.runtime.temporal.connection import namespace as temporal_namespace

    try:
        client, bad = await _connected()
        if bad:
            return None  # the engine is unreachable — say so; do not report an empty floor
        return [{"issue": str(j.get("issue") or ""),
                 "pr_url": ((j.get("action") or {}).get("pr_url") or "")}
                for j in await tv.list_jobs(client, temporal_namespace())
                if j.get("project") == project
                and (j.get("action") or {}).get("kind") == tv.MERGE_WAIT
                and j.get("issue")]
    except Exception:  # noqa: BLE001 — an unreadable floor is not a ticket number
        # EXCEPTION, AND AT WARNING. The previous line logged at INFO, which neither the panel nor
        # the worker prints, and without a traceback — so a `TypeError` in this function's own body
        # was invisible on both surfaces while the feature it gates did nothing at all.
        log.exception("could not read which jobs await a human on %s", project)
        return None


async def _floor_say_as_an_intent(said: str, *, project: str, by: Actor) -> Outcome | None:
    """The floor row a typed sentence asks for, performed — or None (#120).

    THE SIBLING OF `_say_as_an_intent`, and here for the reason that one exists: the pilot typed
    *"pode fazer o merge"* to the tech-lead with the Merge button on screen, and was told merge is
    "ação de humano, fora do que eu executo". `merge_policy: human` makes the DECISION a human's;
    the EXECUTION is this catalogue's, and the button posts to the very row below. A human who has
    decided in words has decided.

    THROUGH `perform`, NEVER BY CALLING THE ROW — the scope and the admin check are applied to the
    SAME actor that came through the door, so a product-scoped credential that cannot press the
    button cannot type its way past it either. That is also why this lives here rather than on the
    worker: `AskInput` carries a bare project and a string, and a gate built down there would be
    inventing authority rather than checking it.

    WHICH JOB, ASKED RATHER THAN ASSUMED. One waiting → that one. None → hand the sentence to the
    tech-lead, who can say why nothing is waiting. More than one → say so and list them, because
    merging the wrong pull request is not a mistake a rephrase can undo."""
    from openfactory.actions.floor_intents import FLOOR_ROWS, match_floor_intent

    matched = match_floor_intent(said)
    if not matched:
        return None
    intent, captures = matched
    # A JOB THAT IS NOT AT A GATE IS NOT IN THE MERGE-WAIT LIST (#127). `stop` exists precisely for
    # the job no gate can reach, so resolving it through "what is waiting on a human" would refuse
    # every sentence it was written for. Its matcher REQUIRES a ref for the same reason the row is
    # admin-gated — terminating is not undoable — so there is nothing here to disambiguate.
    # `resume` AND `skip` JOIN IT (#159): the tech-lead's own diagnosis ends with "Reply
    # `resume #NN`", and the panel chat — the reference surface — executed neither. A message
    # dictating a command no matcher accepts is the defect with a number (#68/#120), and this
    # time the platform was dictating it to itself.
    if intent in ("stop", "resume", "skip"):
        ref = str(captures.get("ref") or "").lstrip("#")
        if not ref:  # pragma: no cover — the patterns cannot match without one
            return None
        from openfactory import actions

        outcome = await actions.perform(FLOOR_ROWS[intent], by=by, project=project, issue=ref)
        return Outcome(ok=outcome.ok, message=outcome.message, code=outcome.code,
                       data={**dict(outcome.data), "read_as": intent,
                             "performed": FLOOR_ROWS[intent], "issue": ref})
    row = FLOOR_ROWS.get(intent)
    if row is None:  # pragma: no cover — the table and the matcher are one file apart
        return None

    waiting = await _waiting_on_a_human(project)
    if waiting is None:
        # THE INSTRUCTION IS NOT SWALLOWED. Falling through here hands a decided human an answer
        # about what the tech-lead does and does not do, which reads as a refusal of the request
        # rather than as what it is: we could not see the floor. The button is still there and
        # still works, so the honest sentence names it.
        return refused(
            UNAVAILABLE,
            f"I read that as `{intent}`, but I could not read the floor just now — so I will not "
            f"guess at which job you meant. Try again in a moment, or use the {intent.title()} "
            f"button on the panel, which acts on the same job.")
    if not waiting:
        return None  # nothing to act on; the tech-lead answers, and can explain why

    # THE REF THE SENTENCE NAMES IS BINDING (sweep, 2026-08-16). It used to be dropped on the
    # floor, which cost all three ways at once: "merge #90" merged whatever happened to be
    # waiting; and with two PRs at the gate, the refusal below dictated the reply `merge #87` —
    # whose ref the matcher then threw away, re-entering this same refusal for ever. Acting on a
    # different job than the one named is worse than refusing.
    wanted = str(captures.get("ref") or "").lstrip("#").lower()
    if wanted:
        hit = next((w for w in waiting
                    if str(w["issue"]).lstrip("#").lower() == wanted), None)
        if hit is None:
            listed = ", ".join(f"#{w['issue']}" for w in waiting[:6])
            return refused(
                NOT_FOUND,
                f"#{captures['ref']} is not waiting on you — waiting: {listed}. I will not "
                f"{intent} a different job than the one you named.")
        issue = hit["issue"]
    elif len(waiting) > 1:
        listed = ", ".join(f"#{w['issue']}" for w in waiting[:6])
        return refused(
            INVALID,
            f"{len(waiting)} jobs are waiting on you ({listed}) — say which one, e.g. "
            f"\"{intent} #{waiting[0]['issue']}\". Merging the wrong pull request is not "
            "something a rephrase undoes.")
    else:
        issue = waiting[0]["issue"]
    log.info("FLOOR_SAY_AS_INTENT project=%s intent=%s row=%s issue=%s by=%s",
             project, intent, row, issue, by)
    from openfactory import actions

    extra = {"instruction": captures["instruction"]} if intent == "adjust" else {}
    outcome = await actions.perform(row, by=by, project=project, issue=issue, **extra)
    # THE ROUTE TRAVELS WITH THE ANSWER, exactly as the product side does: a surface can then say
    # "I read that as a merge" instead of leaving somebody wondering why a question about the
    # board produced a merged pull request.
    return Outcome(ok=outcome.ok, message=outcome.message, code=outcome.code,
                   data={**dict(outcome.data), "read_as": intent, "performed": row,
                         "issue": issue})


async def _say_as_an_intent(said: str, *, project: str, by: Actor) -> Outcome | None:
    """The row a typed sentence asks for, performed — or None, and None is the common answer.

    THROUGH `perform`, NEVER BY CALLING THE ROW. It is what applies the scope and the admin check,
    in that order, using the SAME actor that came through the door — so a sentence can never reach
    something its author's credential could not. Hand-rolling the dispatch would be a second
    authorization surface, and the worker cannot help: `ProductSayInput` carries a bare `asked_by`
    string with no scopes and no admin flag, so a gate built down there would be inventing
    authority rather than checking it.

    THE FALLBACK IS CONVERSATION, and it must be. A recognised intent that cannot be carried out
    has to hand the message back rather than swallow it — the rule `_run_intent` states for itself,
    for the same reason: the client asked a person a question, and a shrug from a matcher is worse
    than an answer that turns out to be about something else."""
    try:
        from openfactory.product.intents import match_intent
    except ImportError:  # pragma: no cover — the matcher is core; its absence is not a crash
        return None

    matched = match_intent(said)
    if not matched:
        return None
    row = _SAY_INTENTS.get(matched[0])
    if row is None:
        return None
    log.info("SAY_AS_INTENT project=%s intent=%s row=%s by=%s", project, matched[0], row, by)
    from openfactory import actions

    outcome = await actions.perform(row, by=by, project=project)
    # THE ROUTE TRAVELS WITH THE ANSWER so a surface can say "I read that as a triage" rather than
    # leaving the person wondering why they got a board report to a sentence about the board.
    return Outcome(ok=outcome.ok, message=outcome.message, code=outcome.code,
                   data={**dict(outcome.data), "read_as": matched[0], "performed": row})


async def _product_say(*, project: str, message: str, by: Actor, thread: str = "") -> Outcome:
    """A turn of CONVERSATION with the product role — it remembers, and it writes nothing.

    NOT `product_ask`, AND THE DIFFERENCE IS WHY THIS EXISTS. `ask` drafts: it reads a message as
    a request and returns a requirement to sign off. This is the other half — the reply that
    carries the thread, so "e o segundo?" means something and a correction lands on what was said
    before. Until now that half existed only inside the Slack package, so on any other surface
    every message was turn one.

    IT IS READ-ONLY, so it is not admin-gated — the module's own rule, the same one `product_ask`
    follows: the gate is on RECORDING, not on thinking about it. What it may do as a side effect
    is open a tracked loop when the role asks a human for something, and that is the opposite of
    a write nobody consented to: it is the platform refusing to let a request scroll away.
    """
    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    said = (message or "").strip()
    if not said:
        return refused(INVALID, "say something to the product role — an empty message spends a "
                                "pass finding that out.")

    routed = await _say_as_an_intent(said, project=proj.name, by=by)
    if routed is not None:
        return routed

    client, bad_engine = await _connected()
    if bad_engine:
        return bad_engine
    from openfactory.product.role import ProductAnswer
    from openfactory.runtime.temporal import TASK_QUEUE
    from openfactory.runtime.temporal.io import ProductSayInput

    try:
        raw = await client.execute_workflow(
            "ProductSayWorkflow",
            ProductSayInput(project=proj.name, message=said,
                            thread=(thread or "").strip(), asked_by=by.id,
                            via=getattr(by, "via", "") or ""),
            id=f"openfactory-product-say-{proj.name}-{abs(hash(said)) % 10**8}",
            task_queue=TASK_QUEUE)
    except Exception:  # noqa: BLE001 — a reply path must degrade, never raise
        log.exception("the product role could not answer for %s", proj.name)
        return refused(FAILED, "I could not work that out just now.")

    raw = raw or {}
    if not raw.get("ok"):
        return refused(FAILED, str(raw.get("error") or
                                   "the product role could not be read at all."),
                       project=proj.name)
    answer = ProductAnswer.model_validate(raw.get("answer") or {})
    return done(str(getattr(answer, "text", "") or ""),
                project=proj.name, measured_on=_measured_on(by),
                is_request=bool(getattr(answer, "is_request", False)),
                is_defect=bool(getattr(answer, "is_defect", False)),
                gesture=str(getattr(answer, "gesture", "") or ""),
                decisions=list(getattr(answer, "decisions", ()) or []),
                answer=answer.model_dump(mode="json"),
                proposes_a_requirement=getattr(answer, "draft", None) is not None)


async def _product_propose(*, project: str, by: Actor, answer: object = None,
                           question: str = "", yes: object = False) -> Outcome:
    """Record a drafted requirement as a pull request — the sign-off surface.

    `answer` is what `product_ask` returned, handed straight back. Without it this REFUSES rather
    than re-drafting: `propose` promises that what a human read is what gets committed, and a
    transport that re-derived the text would break that promise silently, in the one artefact the
    client is being asked to sign off.

    MERGING IS NOT ACCEPTING (ADR-0032). This lands the requirement as `proposed`; `product_accept`
    is what turns it into a promise the factory argues from."""
    import asyncio

    from openfactory.product.role import ProductAnswer

    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    if not _said_yes(yes):
        return refused(
            INVALID,
            "nothing was written: proposing a requirement opens a pull request in the client's "
            "documentation repository, so it needs `yes`. Read the draft first — that is what it "
            "is for.")
    if answer is None:
        return refused(
            INVALID,
            "nothing was written: hand back the `answer` that `product_ask` returned. Re-drafting "
            "from the same words produces a DIFFERENT text, and committing that would mean the "
            "requirement signed off is not the one anybody read." + (
                f" (Ask first: product_ask project={project} question={question!r}.)"
                if question else ""))
    try:
        parsed = ProductAnswer.model_validate(answer)
    except Exception as exc:  # noqa: BLE001 — any transport may send any shape
        from openfactory.util.causes import first_message

        return refused(
            INVALID,
            f"nothing was written: `answer` is not something `product_ask` produced "
            f"({first_message(exc, limit=160)}).")

    if parsed.draft is None:
        # EVERY FIELD OF `ProductAnswer` HAS A DEFAULT, so pydantic accepts `{"nope": 1}` and hands
        # back a well-formed answer carrying nothing. Measured: it validated, reached `propose`,
        # and came back in the client's voice — *"não consegui transformar isso num texto de
        # requisito que se sustentasse"* — which blames the model for what is a malformed payload
        # from the transport. Same shape as every other confusion in this file: a failure of ours
        # wearing a claim about somebody else.
        return refused(
            INVALID,
            "nothing was written: that answer carries no requirement draft. `product_ask` only "
            "drafts one when it reads the message as a REQUEST rather than a question — its "
            "`proposes_a_requirement` says which happened. Ask for the thing you want built.")

    result = await asyncio.to_thread(
        lambda: module.propose(parsed, actor=by.id, asked_by=by.id))
    return _write_outcome(result, did="proposed the requirement", project=proj.name)


async def _product_accept(*, project: str, number: str, by: Actor,
                          yes: object = False) -> Outcome:
    """Turn a written requirement into a PROMISE the factory defends (ADR-0032).

    The single most consequential act on this surface: after it, the factory ARGUES FROM this
    statement. Gated by an authorised person and one confirmation, exactly as the channel is.

    AND THEN THE CARDS, which is the third of the card's own acceptance test — *"propose a
    requirement, accept it and see the card born on the board"* — and was reachable only through
    Slack. `ProductModule.accept` writes the agreement and stops; the accept→`break_down` chain
    lived in `runtime/slack/product_channel.py` and nowhere else, so on a Slack-less deployment a
    client could agree to something and no work would ever appear.
    """
    import asyncio

    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    num, bad_num = _requirement_number(number)
    if bad_num:
        return bad_num
    if not _said_yes(yes):
        return refused(
            INVALID,
            f"nothing was accepted: after this the factory argues FROM requirement {num}, and "
            f"refuses work that contradicts it. That needs `yes`.")
    result = await asyncio.to_thread(lambda: module.accept(num, actor=by.id))
    accepted = _write_outcome(result, did=f"accepted requirement {num}", project=proj.name)
    if not accepted.ok:
        return accepted
    return await _with_the_work_filed(accepted, project=proj.name, number=num, by=by)


async def _with_the_work_filed(accepted: Outcome, *, project: str, number: int,
                               by: Actor) -> Outcome:
    """The acceptance, plus whatever the automatic breakdown produced.

    THE BREAKDOWN MUST NEVER BE ABLE TO COST THE AGREEMENT — the channel's rule, kept verbatim
    because it is right. The promise is already written and pushed when this runs, so every way
    this can go wrong still ends with the client told plainly that the requirement is agreed.
    That is why the whole thing sits under a catch-all, and why the failure sentence says WHAT
    STILL HOLDS before it says what did not happen: the other order reads as "your acceptance
    failed", about the one thing that certainly did not.

    TWO SHAPES, AND THEY ARE DIFFERENT NEWS. Work filed → say what was filed. Nothing filed → say
    so, say the agreement stands anyway, and offer the retry. Silence would leave a client
    believing cards exist that do not.
    """
    from openfactory.runtime.temporal import TASK_QUEUE
    from openfactory.runtime.temporal.io import ProductBreakdownInput

    filed: list[dict] = []
    try:
        client, bad = await _connected()
        if bad:
            raise RuntimeError(bad.message)
        filed = await client.execute_workflow(
            "ProductBreakdownWorkflow",
            ProductBreakdownInput(project=project, number=number, actor=by.id),
            id=f"openfactory-product-breakdown-{project}-{number}",
            task_queue=TASK_QUEUE,
        ) or []
    except Exception:  # noqa: BLE001 — the promise is written; this is a courtesy on top of it
        # ERROR, UNDER ITS OWN CODE. This catch-all is wide enough to swallow a refactor: rename
        # the workflow and every acceptance would go on answering politely that it filed nothing,
        # for ever, while the client assumes the platform is merely busy. A guard pins the
        # dispatch so a drift fails a build; this line is what makes the runtime version findable
        # in one grep instead of inferred.
        log.exception("OPENFACTORY_PRODUCT_AUTOBREAK_FAILED project=%s req=%s — the acceptance "
                      "stands "
                      "and no work was filed", project, number)

    # MERGED, NOT SPLATTED ALONGSIDE. `_write_outcome` already puts `project` and `number` in the
    # acceptance's data, so passing them again as keywords is a TypeError on the first SUCCESSFUL
    # acceptance — the one path a refusal test never reaches. Caught by running it.
    data = {**accepted.data, "project": project, "number": number, "filed": filed}
    made = [r for r in filed if r.get("ok")]
    if made:
        refs = ", ".join(r.get("ref") or r.get("url") or "?" for r in made)
        return done(f"{accepted.message} Work filed: {refs}. Starting any of it is still a "
                    f"person's decision.", **data)
    detail = next((r.get("detail") for r in filed if not r.get("ok") and r.get("detail")), "")
    return done(f"{accepted.message} I could not turn it into units of work "
                f"{f'({detail}) ' if detail else ''}— the agreement is recorded either way, and "
                f"asking me to break it down will try again.", **data)


async def _product_drop(*, project: str, number: str, by: Actor, reason: str = "",
                        yes: object = False) -> Outcome:
    """Drop a proposed requirement, with the reason recorded beside it."""
    import asyncio

    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    num, bad_num = _requirement_number(number)
    if bad_num:
        return bad_num
    if not _said_yes(yes):
        return refused(INVALID, f"nothing was dropped: requirement {num} stays as it is without "
                                f"`yes`.")
    result = await asyncio.to_thread(
        lambda: module.drop(num, actor=by.id, reason=(reason or "").strip()))
    return _write_outcome(result, did=f"dropped requirement {num}", project=proj.name)


async def _product_release(*, project: str, issue: str, by: Actor,
                           yes: object = False) -> Outcome:
    """The client's approval putting a delivery in front of their own users.

    THE HIGHEST-CONSEQUENCE THING THAT ONLY SLACK COULD DO. `_maybe_release` in the product channel
    was the single path to `product.release.release`, so on a deployment without Slack a client
    could not release production at all — measured, not assumed: the release module has no other
    caller in the tree.

    TWO OF THE CHANNEL'S THREE RULES ARE KEPT HERE, and the third belongs to the transport:

    1. AUTHORISATION IS RE-CHECKED, and it must be. `release()` says of itself *"the caller has
       ALREADY authorised the person… this is the pen, not the judgement"*, and unlike every other
       product row this one does NOT go through `ProductModule` — so nothing else would ask.
       `may_act` is the deployment's declared product allowlist, which is a different and stronger
       trust than `Actor.admin`: the operator who may skip a job and the client who may put
       software in front of users are not the same person, and never were.
    2. THE ACT IS OBSERVED BEFORE IT IS CLAIMED. `release()` re-asks the engine whether the job is
       still parked and returns the honest sentence when it is not; that sentence is carried
       through unchanged. A client told "it is going out" over a signal that reached nothing is
       the worst outcome available on this path.
    3. Ambiguity — *"which of the two deliveries did you test?"* — is NOT here on purpose. It is a
       question about reading a message, and this row is handed an issue by name. The channel is
       what turns "funcionou" into an issue, and what refuses to guess when two are waiting.

    `yes` because a release is the one act on this surface whose blast radius is the client's own
    users.
    """
    import asyncio

    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    ref = str(issue or "").strip().lstrip("#")
    if not ref:
        return refused(INVALID, "say which delivery to release — releasing 'the last one' is a "
                                "guess about which software the client's users get.")
    if not _said_yes(yes):
        return refused(
            INVALID,
            f"nothing was released: this puts #{ref} in front of the client's users, with your "
            f"name on it as the approval. That needs `yes`.")

    from openfactory.product.module import may_act, unauthorized_message

    via = getattr(by, "via", "") or "api"
    if not await asyncio.to_thread(lambda: may_act(proj, by.id, via=via)):
        return refused(DENIED, unauthorized_message(proj))

    from openfactory.product.release import release

    ok, why = await asyncio.to_thread(
        lambda: release(proj, ref, approver=by.id,
                        comment=f"approved by {by} on the product surface"))
    if not ok:
        # THE MODULE'S OWN SENTENCE, not a status phrase. It is written for a client and it is the
        # only thing that knows whether the window closed or somebody else already released it.
        return refused(CONFLICT, why or f"#{ref} could not be released, and nothing said why.",
                       project=proj.name, issue=ref)
    return done(f"#{ref} is going to production now, approved by {by}. Who released it and when "
                f"is on the record.", project=proj.name, issue=ref, approver=by.id)


async def _product_queue(*, project: str, by: Actor, limit: object = 5) -> Outcome:
    """What should start next, in order — and why each one, and why not the others.

    TWO ANSWERS, KEPT APART, because they are different kinds of claim. The readiness is
    arithmetic over the client's board and is true whatever the model said; the ordering is the
    judgement. Collapsing them would lose the answer this role most needs to be able to give —
    *"nothing is ready; these eleven need acceptance criteria first"* — and replace it with a
    confident list it invented.

    WRITES NOTHING, so it is not admin-gated: proposing is thinking, and `product_promote` below
    is where the money is spent."""
    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    try:
        want = max(1, min(50, int(str(limit).strip() or 5)))
    except ValueError:
        return refused(INVALID, f"{limit!r} is not a number of tickets to propose.")

    client, bad_engine = await _connected()
    if bad_engine:
        return bad_engine
    from openfactory.runtime.temporal import TASK_QUEUE
    from openfactory.runtime.temporal.io import ProductQueueInput

    try:
        raw = await client.execute_workflow(
            "ProductQueueWorkflow", ProductQueueInput(project=proj.name, limit=want),
            id=f"openfactory-product-queue-{proj.name}-{want}", task_queue=TASK_QUEUE)
    except Exception:  # noqa: BLE001 — a proposal path must degrade, never raise
        log.exception("the product role could not propose a queue for %s", proj.name)
        return refused(FAILED, "I could not work that out just now.")

    raw = raw or {}
    if raw.get("error"):
        return refused(FAILED, str(raw["error"]), project=proj.name)
    return done(f"queue proposed for {proj.name}.", project=proj.name,
                readiness=raw.get("readiness"), proposal=raw.get("proposal"),
                measured_on=_measured_on(by))


async def _product_promote(*, project: str, numbers: object, by: Actor,
                           yes: object = False) -> Outcome:
    """Move approved tickets into the queue — the ONE act here that spends money.

    THE SPEND GATE, AND UNTIL NOW IT HAD EXACTLY ONE DOOR. `ProductModule.promote` was reachable
    only by saying yes in the product channel, so a deployment without Slack could proposeated
    work and never start any of it — and, read the other way, the decision that costs a client
    money had no record outside one chat product.

    ORDER IS PRESERVED, and that is not cosmetic: the poller pulls in board order, so an approved
    sequence that arrives shuffled is not the sequence anybody approved.

    `may_act` is NOT re-checked here — `promote` asks it itself, and asking twice would mean two
    places to keep the answer right."""
    import asyncio

    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    wanted = [str(n).strip().lstrip("#") for n in
              (numbers if isinstance(numbers, (list, tuple)) else str(numbers or "").split(","))]
    wanted = [n for n in wanted if n]
    if not wanted:
        return refused(INVALID, "say which tickets to start — an empty list starts nothing and "
                                "spends a call finding that out.")
    if not _said_yes(yes):
        return refused(
            INVALID,
            f"nothing was started: this puts {len(wanted)} ticket(s) into the queue and the "
            f"factory begins spending on them. That needs `yes`.")

    results = await asyncio.to_thread(lambda: module.promote(wanted, actor=by.id))
    results = list(results or [])
    started = [r for r in results if getattr(r, "ok", False)]
    if not started:
        detail = next((str(getattr(r, "detail", "") or "") for r in results
                       if getattr(r, "detail", "")), "")
        return refused(FAILED, detail or "nothing could be moved into the queue, and the module "
                                         "said nothing about why.", project=proj.name)
    refs = ", ".join(str(getattr(r, "ref", "") or "?") for r in started)
    # THE PARTIAL CASE IS SAID, never rounded up to success: the client is spending on what did
    # start, and needs to know what did not.
    missed = [r for r in results if not getattr(r, "ok", False)]
    tail = (f" {len(missed)} did not move: "
            + "; ".join(str(getattr(r, "detail", "") or "?") for r in missed)) if missed else ""
    return done(f"started {len(started)} of {len(results)}: {refs}.{tail}",
                project=proj.name, started=[str(getattr(r, "ref", "")) for r in started],
                failed=[str(getattr(r, "detail", "")) for r in missed])


# ── the six write verbs that had no row (#105) ──────────────────────────────────────────────────
#
# Each was a branch of `product_channel._handle` and existed nowhere else, so a deployment without
# Slack could not close a card, align one to its requirement, refine one, record a decision taken
# after acceptance, write down something the client said, or file a broken promise as work.
#
# NONE OF THEM RE-CHECKS `may_act`. Unlike `product_release` — which reaches `product.release`
# directly and is therefore the only place the question would otherwise go unasked — every verb
# below is a `ProductModule` method that asks for itself. Asking twice would mean two places to
# keep the answer right, which is how they drift.

async def _product_close_card(*, project: str, number: str, by: Actor, in_favour_of: str = "",
                              reason: str = "", yes: object = False) -> Outcome:
    """Close one card, naming the one that stays — the hand behind a decision already taken."""
    import asyncio

    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    ref = str(number or "").strip().lstrip("#")
    if not ref:
        return refused(INVALID, "say which card to close.")
    if not _said_yes(yes):
        return refused(INVALID, f"nothing was closed: #{ref} stays as it is without `yes`.")
    result = await asyncio.to_thread(
        lambda: module.close_card(ref, actor=by.id,
                                  in_favour_of=(in_favour_of or "").strip() or None,
                                  reason=(reason or "").strip()))
    return _write_outcome(result, did=f"closed #{ref}", project=proj.name)


async def _product_record_decision(*, project: str, number: str, decision: str, by: Actor,
                                   yes: object = False) -> Outcome:
    """Write a decision taken AFTER the acceptance into the requirement's own register.

    THE PROVENANCE IS THE TRANSPORT'S, not invented here. `where` records the room the decision
    was taken in, and a row that hardcoded one would attribute every decision to the same place
    however it arrived."""
    import asyncio

    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    num, bad_num = _requirement_number(number)
    if bad_num:
        return bad_num
    said = (decision or "").strip()
    if not said:
        return refused(INVALID, "a decision with no words in it records nothing — say what was "
                                "decided.")
    if not _said_yes(yes):
        return refused(INVALID, f"nothing was recorded on requirement {num} without `yes`.")
    where = f"{by} ({getattr(by, 'via', '') or 'api'})"
    result = await asyncio.to_thread(
        lambda: module.record_decision(num, decision=said, actor=by.id, where=where))
    return _write_outcome(result, did=f"recorded a decision on requirement {num}",
                          project=proj.name)


async def _product_note_fact(*, project: str, term: str, body: str, by: Actor,
                             yes: object = False) -> Outcome:
    """Write down one thing somebody said about the business — as `aprendido`, attributed.

    IT REFUSES TO OVERWRITE, and that refusal is the module's: a term that already exists is
    answered with what is written, because two versions of the same fact is worse than either."""
    import asyncio

    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    handle, said = (term or "").strip(), (body or "").strip()
    if not handle or not said:
        return refused(INVALID, "a fact needs both the term it is filed under and what is true "
                                "about it.")
    if not _said_yes(yes):
        return refused(INVALID, f"nothing was written about {handle!r} without `yes`.")
    where = f"{by} ({getattr(by, 'via', '') or 'api'})"
    result = await asyncio.to_thread(
        lambda: module.note_fact(term=handle, body=said, said_by=by.id, where=where))
    return _write_outcome(result, did=f"noted {handle!r}", project=proj.name)


async def _product_file_defect(*, project: str, restated: str, by: Actor, violates: str = "",
                               severity: str = "", yes: object = False) -> Outcome:
    """Register a broken promise as work — classified, citing the requirement it violates.

    `violates` IS OPTIONAL AND MEANINGFUL WHEN ABSENT: a defect nobody can tie to a written
    promise is still a defect, and refusing to file it would make the corpus the price of
    reporting one."""
    import asyncio

    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    said = (restated or "").strip()
    if not said:
        return refused(INVALID, "say what is broken — an empty defect files nothing.")
    against: int | None = None
    if str(violates or "").strip():
        against, bad_num = _requirement_number(violates)
        if bad_num:
            return bad_num
    if not _said_yes(yes):
        return refused(INVALID, "nothing was filed: this puts a card on the client's board and "
                                "needs `yes`.")
    result = await asyncio.to_thread(
        lambda: module.file_defect(restated=said, reported_by=by.id, violates=against,
                                   severity=(severity or "").strip()))
    return _write_outcome(result, did="filed the defect", project=proj.name)


async def _product_card(verb: str, *, project: str, number: str, by: Actor,
                        requirement: int = 0, yes: object = False) -> Outcome:
    """`refine` or `align` one card — dispatched to the worker, because both run an agent pass.

    ONE HELPER FOR TWO ROWS: they differ only in the verb and in whether a requirement travels,
    and two copies of this dispatch would be two places for the timeout and the refusal to drift.
    """
    module, proj, bad = _product_module(project, by=by)
    if bad:
        return bad
    ref = str(number or "").strip().lstrip("#")
    if not ref:
        return refused(INVALID, "say which card.")
    if not _said_yes(yes):
        return refused(INVALID, f"nothing was written: rewriting #{ref} needs `yes`.")

    client, bad_engine = await _connected()
    if bad_engine:
        return bad_engine
    from openfactory.runtime.temporal import TASK_QUEUE
    from openfactory.runtime.temporal.io import ProductCardInput

    try:
        raw = await client.execute_workflow(
            "ProductCardWorkflow",
            ProductCardInput(project=proj.name, number=ref, verb=verb,
                             requirement=requirement, actor=by.id),
            id=f"openfactory-product-card-{verb}-{proj.name}-{ref}", task_queue=TASK_QUEUE)
    except Exception as exc:  # noqa: BLE001 — a write path must degrade, never raise
        log.exception("the product role could not %s #%s on %s (%s)", verb, ref, proj.name, exc)
        return refused(FAILED, f"I could not rewrite #{ref} just now.", project=proj.name)

    # The activity returns the `WriteResult`'s fields as data (it crossed a Temporal boundary);
    # `_write_outcome` reads them off an object, so it is handed one. Missing keys fall through to
    # its own defaults, which is why this is a namespace rather than a re-validated model.
    from types import SimpleNamespace

    return _write_outcome(SimpleNamespace(**(raw or {})), did=f"{verb}d #{ref}",
                          project=proj.name)


async def _product_refine_card(*, project: str, number: str, by: Actor,
                               yes: object = False) -> Outcome:
    """Give a backlog ticket something testable to be judged against.

    The most common reason a job parks is a ticket nobody can evaluate. The module REFUSES one
    that already says when it would be done, and that refusal arrives here as `existed`."""
    return await _product_card("refine", project=project, number=number, by=by, yes=yes)


async def _product_align_card(*, project: str, number: str, requirement: str, by: Actor,
                              yes: object = False) -> Outcome:
    """Make a card execute the requirement it should — the citation AND what it must satisfy."""
    num, bad_num = _requirement_number(requirement)
    if bad_num:
        return bad_num
    return await _product_card("align", project=project, number=number, by=by,
                               requirement=num, yes=yes)


def _requirement_number(raw: str) -> tuple[int, Outcome | None]:
    """`REQ-0007`, `#7`, `7` → 7. A refusal names what it got, because the alternative is acting on
    a number nobody meant."""
    text = str(raw or "").strip().lstrip("#").upper().removeprefix("REQ-")
    if not text.isdigit():
        return 0, refused(INVALID, f"{raw!r} is not a requirement number — say `7`, `#7` or "
                                   f"`REQ-0007`.")
    return int(text), None



async def _env_context(*, target: str, by: Actor, ask: object = False,
                       write: str = "", yes: object = False) -> Outcome:
    """Survey a repository and PROPOSE the context an agent will read from then on.

    THE OTHER HALF OF `env_read`, AND THE BIGGER ONE. `env_read` proposes how to BUILD the project;
    this proposes what the project IS — what it does, its vocabulary, its entry points, its
    invariants, and the questions only a developer can answer. On a legacy codebase that is the
    real work: the manifest is four fields, and the context is why anybody can write a requirement
    that means something in this domain.

    TWO MODES, AND THE FREE ONE IS THE DEFAULT.

    Without `ask`, this is DETERMINISTIC and costs nothing: the modules, the entry points, the
    domain words taken from file names and public symbols, and — the measurement that matters on a
    legacy repository — how many modules describe themselves by their own folder name, which is the
    deterministic reader working correctly and producing nothing.

    With `ask`, ONE read-only agent pass adds the semantic layer. `openfactory/knowledge` says of
    itself
    "never an LLM, never invented", and that is correct for an artefact regenerated at every merge.
    It is not this artefact: an agent proposing "this system does X, its entities are Y" is not
    hallucinating when a developer corrects it in the room. What makes it safe is not the promise —
    it is that every citation is checked against the filesystem before its sentence is allowed to
    exist, and a claim whose citation does not resolve is DEMOTED into a question carrying the
    sentence and the bad citation together.

    THE PASS IS REFUSED WHERE IT CANNOT RUN, AND THAT IS MEASURED RATHER THAN ASSUMED. The harness
    binary is looked for on this process's PATH: the panel serves HTTP from an image that has no
    coding agent in it (ADR-0038 — the worker runs agents), and letting the pass start there would
    hang a request for the harness timeout and then report a model failure, which is a claim about
    the model and not about us. `which` answers that in microseconds, on whichever machine is
    actually asking.

    `write` NEEDS `yes`, and never overwrites. These are documents about somebody else's codebase.
    """
    import asyncio

    from openfactory.util.causes import first_message

    where = _measured_on(by)
    project, checkout, bad = repo_for(target)
    if bad:
        return bad
    if checkout is None:  # unreachable by construction; a silent None here would print nothing
        return refused(FAILED, f"could not resolve {target!r} to a repository.")

    try:
        from openfactory.onboarding import context as ctx
    except ImportError as exc:
        return refused(
            UNAVAILABLE,
            f"this deployment has no context module ({first_message(exc, limit=120)}) — "
            f"`openfactory.onboarding.context` is what surveys a repository and proposes its "
            f"documentation. Nothing was read.")

    wants_ask = _said_yes(ask)
    ask_fn = None
    if wants_ask:
        # BUILT BEFORE THE WALK, so a harness nobody can run fails in front of a client with the
        # sentence that names the configuration, rather than after a survey of their monolith.
        try:
            ask_fn = _semantic_pass(project, checkout, ctx)
        except (TypeError, ValueError) as exc:
            return refused(INVALID, str(exc))
        except FileNotFoundError as exc:
            return refused(UNAVAILABLE, str(exc))

    try:
        survey = await asyncio.to_thread(ctx.survey, str(checkout))
    except Exception as exc:  # noqa: BLE001 — a client's repository may be anything at all
        log.exception("env_context failed surveying %s", checkout)
        return refused(
            FAILED,
            f"could not survey {checkout} ({first_message(exc, limit=200)}) — nothing was written "
            f"and nothing is proposed. This is the platform's fault, not the repository's.")

    try:
        proposal = await asyncio.to_thread(
            lambda: ctx.propose_context(survey, ask=ask_fn, docs_root=write or None))
        report = ctx.render_context_report(proposal)
    except Exception as exc:  # noqa: BLE001
        log.exception("env_context failed proposing for %s", checkout)
        return refused(
            FAILED,
            f"surveyed {checkout} and could not shape the proposal "
            f"({first_message(exc, limit=200)}). Nothing was written.")

    modules = len(getattr(survey, "modules", ()) or ())
    questions = len(getattr(proposal, "questions", ()) or ())
    common = dict(project=(project.name if project is not None else None), target=str(checkout),
                  measured_on=where, semantic=bool(getattr(proposal, "semantic", False)),
                  asked=int(getattr(proposal, "asked", 0) or 0), report=report,
                  questions=list(getattr(proposal, "questions", ()) or []),
                  documents=[d.path for d in (getattr(proposal, "documents", ()) or [])])

    # A FAILED AGENT PASS IS A REFUSAL, NOT A THINNER REPORT. `propose_context` returns the
    # deterministic documents either way — correctly, they were never the model's — but an outcome
    # that came back `ok` with the semantic half missing would read as "your code says nothing",
    # which is a claim about the client while the truth is a claim about us. The report travels
    # with the refusal, so nothing measured is lost.
    if not getattr(proposal, "ok", True):
        return refused(FAILED, str(getattr(proposal, "refusal", "") or
                                   "the agent pass did not land"), **common)

    if not write:
        return done(
            f"surveyed {checkout} — {modules} modules, {questions} questions only your developers "
            f"can answer. Nothing was written.", **common)

    if not _said_yes(yes):
        return refused(
            INVALID,
            f"nothing was written: writing into {write} needs `yes` (`--yes`). These are documents "
            f"about somebody else's codebase, and putting them in their repository is a decision "
            f"said out loud, not a side effect of producing them.", **common)

    outcome = await asyncio.to_thread(
        lambda: ctx.write_documents(proposal, write, consent=True))
    if outcome.refusal:
        return refused(INVALID, outcome.refusal, **common)
    common.update(wrote=list(outcome.wrote), skipped=list(outcome.skipped),
                  failed=list(outcome.failed), docs_root=write)
    if outcome.failed:
        return refused(
            FAILED,
            f"{len(outcome.wrote)} document(s) written and {len(outcome.failed)} that could not "
            f"be: {'; '.join(outcome.failed)}", **common)
    return done(
        f"{len(outcome.wrote)} document(s) written into {write}"
        + (f", {len(outcome.skipped)} left untouched because a file was already there"
           if outcome.skipped else "")
        + f" — {questions} questions only your developers can answer.", **common)


def _semantic_pass(project, checkout: Path, ctx):
    """The read-only agent primitive `propose_context` takes, bound to THIS deployment's harness.

    Raises rather than returning None on every failure, because each one is a different sentence a
    human acts on: no harness configured, a harness that cannot judge, or a harness that is not
    installed on the machine being asked."""
    import shutil

    from openfactory.adapters.agent import build_asker
    from openfactory.adapters.agent.registry import harness_binary, harness_kind
    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.adapters.sandbox.registry import judging_worktree

    kind = harness_kind(project, "techlead")
    binary = harness_binary(kind)
    if shutil.which(binary) is None:
        # WHAT THIS MEASURES, AND WHAT IT DOES NOT. A product row used to make the same check to
        # keep agent work off the panel, and that use was DELETED because it does not do it:
        # measured inside the running panel container, `claude` is at `/usr/local/bin/claude`,
        # because `docker-compose.yml` builds the panel from `docker/worker.Dockerfile` and that
        # ends in `npm install -g @anthropic-ai/claude-code`. The binary is present on the process
        # this was meant to stop; what is absent there is `CLAUDE_CODE_OAUTH_TOKEN` and the docker
        # socket. `product_ask` now dispatches to the worker (#98) so the question cannot arise.
        #
        # IT IS STILL RIGHT HERE, for the narrower thing it actually says: `env context --ask` is a
        # CLI verb aimed at a laptop, and on a laptop with no harness installed this is exactly
        # true and the remedy below is exactly the one that helps. It is a RAISE rather than a
        # shared refusal because it carries a second sentence the product rows do not — the
        # deterministic survey is a complete answer on its own, and "run it again without `ask`"
        # beats sending somebody to another machine for something they can have here, for free.
        raise FileNotFoundError(
            f"the semantic pass needs the {kind} harness and {binary!r} is not on this process's "
            f"PATH. The panel serves the surface and the worker runs agents (ADR-0038), so run "
            f"`openfactory env context <target> --ask` where the harness is installed. The "
            f"deterministic survey needs none of this and costs nothing — run it again "
            f"without `ask`.")
    return ctx.agent_ask(
        build_asker(project),
        sandbox=judging_worktree(project, root=checkout),
        workspace=Workspace(path=str(checkout), branch="main", base_branch="main"))


async def _env_read(*, target: str, by: Actor) -> Outcome:
    """Read a repository and PROPOSE what its `.openfactory/project.yaml` should say. Writes
    nothing.

    THE ONLY VERB IN THIS PLATFORM THAT PROPOSES. Every field comes back with the value, the place
    in the repository it was read from, and how sure the platform is — and the `unknown` ones are
    the point, not the leftovers: they are the questions a developer answers out loud while the
    report is on the screen. A tool that emitted `setup: []` instead of "nothing in this repository
    says how to install dependencies" would produce a manifest that loads, declares nothing, and is
    reported healthy by `doctor` — which is this file's most expensive defect class, at the exact
    moment a client is deciding whether to buy.

    PURE, AND SAFE ANYWHERE. It clones nothing, runs nothing from the repository, and spends no
    tokens of its own — so unlike `env_check` it is honest on a laptop, and it says so."""
    import asyncio

    from openfactory.util.causes import first_message

    where = _measured_on(by)
    project, checkout, bad = repo_for(target)
    if bad:
        return bad
    if checkout is None:  # unreachable by construction; a silent None here would print nothing
        return refused(FAILED, f"could not resolve {target!r} to a repository.")

    manifest_path = getattr(project, "manifest_path", None) or namespace.MANIFEST
    try:
        # THE ONE READER DECIDES WHETHER THIS REPOSITORY HAS A MANIFEST. `exists()` on the current
        # name alone read a repository still on the directory's retired name as "nothing declared"
        # and proposed it a manifest that, once applied, shadowed the one the client already obeyed
        # — while the loader, the doctor and onboarding refused the same repository by name
        # (review, 2026-08-25). The proposal is a proposal for a second manifest; the rename comes
        # first, and the sentence says so.
        destination = namespace.resolve(
            checkout, manifest_path, project=getattr(project, "name", "") or checkout.name)
    except namespace.RetiredNamespace as exc:
        return refused(
            CONFLICT, str(exc),
            verb="read", measured_on=where, wrote=None,
            project=getattr(project, "name", None), repo=str(checkout),
            read_as=("project" if project is not None else "path"))

    try:
        from openfactory.onboarding import infer
    except ImportError as exc:
        return refused(
            UNAVAILABLE,
            f"this deployment has no inference module ({first_message(exc, limit=120)}) — "
            f"`openfactory.onboarding.infer` is what reads a repository and proposes a manifest, "
            f"and "
            f"without it there is nothing to propose. Nothing was read.")

    entry, exports = _entry_point(infer, "propose", "infer")
    if entry is None:
        return refused(
            UNAVAILABLE,
            f"`openfactory.onboarding.infer` exports neither `propose(repo)` nor `infer(repo)` — "
            f"this "
            f"transport does not know how to ask it. It exports: {exports}")
    try:
        proposal = await asyncio.to_thread(entry, str(checkout))
    except Exception as exc:  # noqa: BLE001 — a client's repository may be anything at all
        log.exception("env_read failed on %s", checkout)
        return refused(
            FAILED,
            f"could not read {checkout} ({first_message(exc, limit=200)}) — nothing was written, "
            f"and nothing is proposed. This is the platform's fault, not the repository's; the "
            f"answer is still `openfactory env interview`-shaped: ask the developers.")

    rows, unreadable = _proposed_rows(proposal)
    if rows is None:
        # THE PROPOSAL EXISTS AND THIS TRANSPORT CANNOT READ IT. Refusing beats rendering an empty
        # report: an empty report says "your repository told me nothing", which is a claim about
        # the client, while the truth is a claim about us.
        return refused(
            FAILED,
            f"the inference produced a result this transport cannot read "
            f"({type(proposal).__name__}, {unreadable} entr{'y' if unreadable == 1 else 'ies'} "
            f"with no `confidence`). A field must carry value, source and confidence. Nothing is "
            f"proposed, deliberately — a blank report would read as 'your repository says "
            f"nothing'.")

    counts = {tier: sum(1 for r in rows if r["confidence"] == tier) for tier in _CONFIDENCE}
    message = (
        f"{len(rows)} field(s) proposed for {checkout.name}: {counts[OBSERVED]} observed, "
        f"{counts[INFERRED]} inferred, {counts[UNKNOWN]} only your developers can answer. "
        f"Nothing was written."
        if rows else
        f"read {checkout} and could propose nothing about it — that is an answer, not an error: "
        f"no build file, no CI file and no default branch were found. The whole manifest is a "
        f"question for your developers.")
    return done(
        message,
        verb="read", measured_on=where, wrote=None,
        project=getattr(project, "name", None), repo=str(checkout),
        read_as=("project" if project is not None else "path"),
        fields=rows, counts=counts, unreadable=unreadable,
        destination=str(destination), destination_exists=destination.exists(),
        uncited=[r["name"] for r in rows if r["confidence"] != UNKNOWN and not r["source"]],
        **_extras(proposal),
    )


#: Verdict words this transport recognises as "pickup is not blocked". NARROW ON PURPOSE: anything
#: unrecognised is reported as NOT ready, because the expensive direction of this mistake is the
#: confident false green — the card that opened this work measured `env check` printing READY over
#: a project whose box had never been proven, and called trading three honest disagreements for one
#: confident wrong answer worse than the state it replaced.
_READY_WORDS = frozenset({"READY", "PRONTO", "OK"})
#: …and the ones that mean "something is deliberately holding pickup", which is not the same as an
#: unfinished setup and sends a reader somewhere else entirely.
_HELD_WORDS = frozenset({"HELD", "SEGURADO", "BLOCKED", "BLOQUEADO"})


def _verdict(raw: str) -> tuple[str, bool, bool]:
    """`(word, ready, understood)` for whatever the readiness module returned.

    UNDERSTOOD IS A SEPARATE ANSWER from ready. A verdict this transport cannot classify must not
    be rendered as either colour: it is reported as not-ready AND as not-understood, so the reader
    goes and looks at the readiness module instead of at their own repository."""
    word = (str(raw or "").strip().split() or [""])[0].strip(":.,").upper()
    if word in _READY_WORDS:
        return word, True, True
    if word in _HELD_WORDS or word:
        return word, False, word in _HELD_WORDS or word.startswith(("NOT", "FALTA", "MISSING"))
    return "", False, False


async def _env_check(*, project: str, by: Actor) -> Outcome:
    """ONE verdict on whether this project can actually be picked up — with its provenance.

    THE PROBLEM IT REPLACES, measured live in the card that opened it: `doctor`, `conformance` and
    `box status` were asked about the same project in the same minute and gave four answers in four
    scopes, none of which knew about the others. This is the composition, and the composition is
    only worth anything if it says WHERE it measured — which is why every finding carries
    `measured_on` and why the message leads with it when the answer came from a laptop.

    `ok` IS ABOUT THE PLATFORM, NOT ABOUT THE ANSWER (see `actions/__init__.py`): checking a
    project and finding it not ready is a successful check. `data["ready"]` is the answer, and the
    CLI's exit code maps from it — never from `ok`."""
    import asyncio

    from openfactory.util.causes import first_message

    where = _measured_on(by)
    found, bad = _project(project)
    if bad:
        return bad

    try:
        from openfactory.onboarding import readiness
    except ImportError as exc:
        return refused(
            UNAVAILABLE,
            f"this deployment has no readiness module ({first_message(exc, limit=120)}) — "
            f"`openfactory.onboarding.readiness` is the one place that composes doctor, "
            f"conformance, "
            f"the "
            f"floor and the box gate into a single verdict. Until it lands, `openfactory doctor "
            f"{found.name}` and `openfactory box status {found.name}` are the honest partial "
            f"answers.")

    entry, exports = _entry_point(readiness, "check", "readiness_for")
    if entry is None:
        return refused(
            UNAVAILABLE,
            f"`openfactory.onboarding.readiness` exports neither `check(project)` nor "
            f"`readiness_for(project)` — this transport does not know how to ask it. It exports: "
            f"{exports}")
    try:
        result = await asyncio.to_thread(entry, found)
    except Exception as exc:  # noqa: BLE001 — a probe that raises must not read as "ready"
        log.exception("env_check failed for %s", found.name)
        return refused(
            FAILED,
            f"could not work out whether {found.name} is ready ({first_message(exc, limit=200)}) "
            f"— treat this as NOT ready: a check that crashed has proven nothing.")

    # TWO SHAPES, BOTH ACCEPTED. The card specified `(findings, verdict)`; the module that landed
    # returns a `Report` whose `verdict` is a property computed from its own findings — which is
    # the stronger design (a stored verdict can drift from its evidence) and the reason this reads
    # it rather than insisting on the tuple. Neither is guessed at: a shape that is neither is
    # refused below, in a sentence, instead of being unpacked into something plausible.
    if isinstance(result, tuple | list) and len(result) == 2:
        raw_findings, verdict_text = result
        holds = []
    elif hasattr(result, "findings") and hasattr(result, "verdict"):
        raw_findings = result.findings
        verdict_text = result.verdict
        holds = [str(h) for h in (getattr(result, "holds", None) or [])]
    else:
        return refused(
            FAILED,
            f"the readiness check returned {type(result).__name__}, which is neither "
            f"(findings, verdict) nor a report carrying both — this transport cannot tell ready "
            f"from not ready, so it says neither.")

    rows = []
    for f in raw_findings or []:
        get = f.get if isinstance(f, Mapping) else (lambda k, d=None, _f=f: getattr(_f, k, d))
        rows.append({
            "check": str(get("check", "") or "?"),
            "ok": bool(get("ok", False)),
            "message": str(get("message", "") or ""),
            "remedy": str(get("remedy", "") or ""),
            # DEFAULTS TO TRUE so a findings source that has no such concept is not silently
            # reported as having asked nothing. `False` is the third marker: not a pass and not a
            # failure, but "no answer exists on this machine" — and it must never be rendered as a
            # shade of ok.
            "answered": bool(get("answered", True)),
            # "" MEANS THE FINDING DID NOT SAY, and the renderer prints that as `?` rather than
            # inheriting the run's own provenance. Borrowing it would let a finding measured on a
            # laptop be presented as measured in the factory, which is the one substitution this
            # whole field exists to prevent.
            "measured_on": str(get("measured_on", "") or ""),
        })
    word, ready_word, understood = _verdict(verdict_text)
    failing = [r for r in rows if not r["ok"] and r["answered"]]
    unattributed = [r["check"] for r in rows if not r["measured_on"]]
    unanswered = [r["check"] for r in rows if not r["answered"]]
    # BOTH HAVE TO AGREE, AND SO DOES `holds`. A verdict of READY over a failing finding, or over a
    # live hold, is a contradiction — and the safe reading of a contradiction is the pessimistic
    # one. Nobody was ever harmed by being told to look again; the card that opened this work was
    # opened because the opposite mistake printed READY over a box that had never been proven.
    ready = bool(ready_word and understood and not failing and not holds)

    if not understood:
        message = (f"{found.name}: the readiness module answered {str(verdict_text)!r}, which this "
                   f"transport does not recognise — reporting NOT ready, because an unrecognised "
                   f"verdict must never read as a green one.")
    elif ready:
        message = (f"{found.name} is READY — {len(rows) - len(unanswered)} check(s) pass, measured "
                   f"on {where}. A card in the pickup column starts on its own.")
    elif holds:
        message = (f"{found.name} is HELD — {holds[0]} (measured on {where}). Nothing is picked "
                   f"up while that is true, whatever else is also unmet.")
    else:
        message = (f"{found.name} is NOT ready — {len(failing)} of "
                   f"{len(rows) - len(unanswered)} answered check(s) failing (measured on "
                   f"{where}).")
    if unanswered:
        # A GREEN REPORT THAT ASKED NOTHING IS NOT A GREEN REPORT. Counted in the sentence, never
        # counted in the verdict.
        message += (f" {len(unanswered)} check(s) could not be answered here and are counted "
                    f"neither way: {', '.join(unanswered)}.")
    if where != "worker":
        # THE FIRST THING A READER MUST KNOW. This is the correction the design attacked itself
        # over: a verdict about a laptop, delivered with the authority of a verdict about the
        # factory, is the same disease with a better interface.
        message += (f" Measured on {where}: this is the machine you typed on, not the one that "
                    f"runs your tickets — a docker, a PATH or a credential can differ there.")
    return done(
        message,
        verb="check", measured_on=where, wrote=None, project=found.name,
        ready=ready, verdict=str(verdict_text or ""), verdict_word=word,
        verdict_understood=understood, findings=rows, holds=holds,
        failing=[r["check"] for r in failing], unattributed=unattributed,
        unanswered=unanswered,
    )


#: How a caller SPELLS the two things this verb takes, so a refusal names the option the reader
#: actually has. The action layer speaks no transport — this is the same lesson `_parse_params`'
#: `flag` argument already encodes, keyed off `Actor.via`, which is the only thing here that
#: knows which door the request came through.
#:
#: WHY IT MATTERED: the refusal below taught `accept=[…]` and `answers={'validate.test': '…'}` —
#: PYTHON API syntax — to somebody who had just typed `openfactory env apply`. A remedy in a
#: language the reader is not writing is the `conformance` mistake this file names twice already.
#: Each entry: (accept in general, answer in general, accept THIS field, answer THIS field).
_SPELLING = {
    "cli": ("`--accept <field>` (or `--accept all`)", "`--set <field>=<value>`",
            "`--accept {name}`", "`--set {name}=…`"),
    "panel": ("`accept: [\"<field>\"]` (or `[\"all\"]`)", "`answers: {\"<field>\": \"<value>\"}`",
              "`accept: [\"{name}\"]`", "`answers: {{\"{name}\": \"…\"}}`"),
}
_SPELLING_DEFAULT = ("`accept=[…]`, or `accept=['all']`", "`answers={'validate.test': '…'}`",
                     "`accept=['{name}']`", "`answers={{'{name}': '…'}}`")


def _how_to_say_it(by: Actor) -> tuple[str, str]:
    """`(how to accept, how to answer)` in the vocabulary of whoever is reading."""
    return _SPELLING.get(str(getattr(by, "via", "") or "").lower(), _SPELLING_DEFAULT)[:2]


def _how_to_say_this_field(by: Actor, name: str, *, answer: bool) -> str:
    """The same, for ONE named field — what a schema error prints beside the thing it is missing.

    THIS ONE WAS HARDCODED TO THE CLI (`--set`, `--accept`), which is the same defect as the
    generic message being hardcoded to the Python API, pointing the other way: a panel reader was
    handed command-line flags for a surface with no command line."""
    entry = _SPELLING.get(str(getattr(by, "via", "") or "").lower(), _SPELLING_DEFAULT)
    return entry[3 if answer else 2].format(name=name)


def _wants_a_list(dotted: str) -> bool:
    """Does the manifest field this dotted name starts at hold a LIST?

    ASKED OF THE SCHEMA, never guessed. `setup` is `list[str]`, so `--set setup="uv sync"` handed
    a bare string to a field that cannot take one — and the CLI's own printed remedy for a missing
    `setup` is exactly `--set setup=<the answer>`. The platform documented a command that could
    only ever end in a validation error (pre-pilot review, 2026-08-09).
    """
    from typing import get_origin

    from openfactory.contracts.manifest import Manifest

    head = str(dotted or "").split(".")[0].split("[")[0]
    aliases = {(f.alias or n): n for n, f in Manifest.model_fields.items()}
    field = Manifest.model_fields.get(aliases.get(head, head))
    if field is None:
        return False
    # `get_origin`, not string-comparing type reprs — the process audit (2026-08-17) flagged the
    # first cut's two overlapping repr checks as the fragile spelling of exactly this question.
    return get_origin(field.annotation) is list or field.annotation is list


def _as_the_schema_wants(dotted: str, value: object) -> object:
    """A person's answer in the shape the field can hold.

    ONE SCALAR BECOMES ONE ELEMENT, and `&&` splits — because that is how a human writes two
    commands on one line and it is the shape the CLI's own `--set` can carry. Anything already a
    list, and any field that does not want one, passes through untouched: this widens what a
    person can type, never what the schema accepts.

    AN EMPTY ANSWER IS NOT WIDENED, and that is the interesting case. `--set setup=` is somebody
    saying "nothing", and the first cut of this turned it into `[""]` — a list the schema accepts,
    written to their repository as an install step that runs the empty string. The rule this
    action is built around is that a person's answer is never silently discarded AND never
    silently improved: an empty one goes to `Manifest` as it is, is refused in a sentence naming
    the field, and nothing is written. Corrected by the schema, which is the only thing here
    entitled to correct it."""
    if not isinstance(value, str) or not _wants_a_list(dotted):
        return value
    parts = [p.strip() for p in value.split("&&") if p.strip()]
    return parts or value


def _steps(dotted: str) -> tuple[list[str | int], str]:
    """`base_branch` → `['base_branch']`; `validate.test` → `['validate','test']`;
    `setup[1]` → `['setup', 1]`. Or `([], why)`.

    Those three shapes are how a human points at a manifest field out loud, which is why the
    proposal names fields that way and why this exists. A name this cannot parse REFUSES rather
    than inventing a key: `Manifest` is `extra="forbid"`, so a mangled key produces a file the
    platform's own loader rejects — at the client, who then reads it as their own mistake."""
    import re

    segment = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)((?:\[\d+\])*)$")
    steps: list[str | int] = []
    for part in str(dotted).split("."):
        match = segment.match(part)
        if not match:
            return [], f"{dotted!r} is not a field name this can place (at {part!r})"
        steps.append(match.group(1))
        steps.extend(int(i) for i in re.findall(r"\[(\d+)\]", match.group(2)))
    return steps, ""


def _place(doc: dict, dotted: str, value: object) -> str:
    """Put `value` at `dotted` inside `doc`; return `""`, or WHY it could not be placed.

    A GAP IN A LIST IS REFUSED, not padded. `setup[2]` proposed without `setup[0]` and `setup[1]`
    would have to be filled with something, and whatever that something is, it is a command that
    would run — in order, inside a client's box. There is no safe filler for that."""
    steps, problem = _steps(dotted)
    if problem:
        return problem
    node: object = doc
    for depth, step in enumerate(steps[:-1]):
        want: object = [] if isinstance(steps[depth + 1], int) else {}
        node, problem = _descend(node, step, want, dotted)
        if problem:
            return problem
    return _assign(node, steps[-1], value, dotted)


def _descend(node: object, step: str | int, want: object, dotted: str) -> tuple[object, str]:
    """One step down, creating the container the NEXT step needs. `(node, "")` or `(None, why)`."""
    if isinstance(step, int):
        if not isinstance(node, list):
            return None, f"{dotted!r}: [{step}] was proposed on something that is not a list"
        if step > len(node):
            return None, (f"{dotted!r}: index {step} was proposed but {len(node)} was not — a gap "
                          f"in a list would have to be filled with something nobody proposed")
        if step == len(node):
            node.append(want)
        return node[step], ""
    if not isinstance(node, dict):
        return None, f"{dotted!r}: {step!r} would have to live inside a mapping and does not"
    return node.setdefault(step, want), ""


def _assign(node: object, step: str | int, value: object, dotted: str) -> str:
    if isinstance(step, int):
        if not isinstance(node, list):
            return f"{dotted!r}: [{step}] was proposed on something that is not a list"
        if step > len(node):
            return (f"{dotted!r}: index {step} was proposed but {len(node)} was not — a gap in a "
                    f"list would have to be filled with something nobody proposed")
        if step == len(node):
            node.append(value)
        else:
            node[step] = value
        return ""
    if not isinstance(node, dict):
        return f"{dotted!r}: {step!r} would have to live inside a mapping and does not"
    node[step] = value
    return ""


def _yaml_header(written: list[dict], skipped: list[dict], *, when: str, who: str) -> str:
    """The provenance block that goes at the top of the file this writes.

    THE COMMENTS ARE PART OF THE PRODUCT. This file is the thing a client's developer opens in six
    months to ask "who decided our test command is that?" — and the answer being in the file, next
    to the value, with the line of the CI file it was read from, is the difference between a
    configuration artefact and the beginning of the context this platform keeps promising to
    create. It also states what is DELIBERATELY ABSENT, so a reader never has to wonder whether a
    missing field was an omission or a decision."""
    width = max((len(w["name"]) for w in written), default=0)
    lines = [
        f"# Written by `openfactory env apply` on {when}, asked for by {who}.",
        "# Proposed by reading this repository; every value below was accepted by a human.",
        "#",
        "# field, how sure the platform was, and where it came from:",
    ]
    lines += [f"#   {w['name']:<{width}}  {w['confidence']:<8}  {w['source'] or '—'}"
              for w in written]
    if skipped:
        lines += [
            "#",
            "# NOT written, on purpose — nobody answered these, and an empty value would be a",
            "# declaration that this project has no such thing:",
        ]
        # THE TWO REASONS ARE DIFFERENT AND THE FILE SAYS WHICH. "nobody answered it" sends a
        # reader to their developers; "we read it and it is empty" sends them nowhere, because
        # there is nothing to do — and a reader who cannot tell them apart chases the second one.
        lines += [f"#   {s['name']}  ({s['confidence']}){'  ' + s['source'] if s['source'] else ''}"
                  + ("  — read, and empty: writing it would only repeat the default"
                     if s.get("empty") else "")
                  for s in skipped]
    return "\n".join(lines) + "\n"


def _said_yes(value: object) -> bool:
    """Consent, and ONLY consent. `True`, or a word a human recognises as yes; nothing else.

    NOT `bool(value)`, and this is the whole reason the helper exists. A transport that sends JSON
    can send the STRING `"false"`, which is truthy in Python — so `if not yes` would let a form
    field carrying the word "false" overwrite a client's manifest. Consent that can be given by
    accident is not consent, and this is the one parameter in this module where being wrong costs
    somebody their file."""
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1"}
    return value is True


async def _env_apply(*, project: str, by: Actor, yes: object = False, force: object = False,
                     accept: object = None, answers: object = None,
                     out: object = "", pr: object = False) -> Outcome:
    """Write the manifest — and, on the `pr` path, RELEASE the clone it wrote into.

    A thin wrapper for one reason: the pull-request path makes a temporary clone that must
    outlive the function that creates it (`propose_manifest.clone_for_proposal`) and be removed
    however this ends — including the half-dozen refusals between the clone and the push. A
    `finally` here is the one place that covers all of them, which is why the growth guard's
    `_RELEASED_BY_CALLER` names this function by name."""
    import shutil

    holder: dict[str, Path] = {}
    try:
        return await _env_apply_impl(
            project=project, by=by, yes=yes, force=force, accept=accept, answers=answers,
            out=out, pr=pr, _clone_holder=holder)
    finally:
        stale = holder.get("dir")
        if stale is not None:
            shutil.rmtree(stale, ignore_errors=True)


async def _env_apply_impl(*, project: str, by: Actor, yes: object = False,
                          force: object = False, accept: object = None, answers: object = None,
                          out: object = "", pr: object = False,
                          _clone_holder: dict | None = None) -> Outcome:
    """Write the proposed `.openfactory/project.yaml` — the ONLY verb here that writes, and it
    is fenced.

    THE FENCES, each paid for by a different incident:

    1. **`yes` is required.** Without it this returns the exact file it WOULD write and refuses,
       which is the same shape `product init` already uses ("shows before it writes"). It is the
       client's repository; the first thing this platform does to it should be reviewable.
    2. **An existing manifest is never overwritten without `force`,** and even then the previous
       file is copied to `<name>.bak` first and the path is reported. A client with a hand-tuned
       manifest losing it to a helpful tool is the last time that tool gets run.
    3. **Only fields a human accepted are written.** `observed` fields — the ones actually measured
       in the repository — are written by default; `inferred` ones need naming in `accept` (or
       `accept=["all"]`); `unknown` ones are never written at all unless `answers` supplies the
       value, because there is nothing to write and an empty value is a claim.
    4. **The result is validated against `Manifest` before it touches the disk.** `Manifest` is
       `extra="forbid"`, so a field name this transport misread would otherwise produce a file the
       platform's own loader rejects — the client following our instructions and being told they
       did it wrong, which is the loop this whole card exists to break.
    5. **The write is atomic** (temp file in the same directory, then `os.replace`), so an
       interrupted apply cannot leave a client with half a manifest.
    """
    import asyncio
    import os
    import shutil
    import tempfile
    from datetime import UTC, datetime

    import yaml
    from pydantic import ValidationError

    from openfactory.contracts.manifest import Manifest
    from openfactory.util.causes import first_message

    where = _measured_on(by)
    consented, replace = _said_yes(yes), _said_yes(force)
    found, bad = _project(project)
    if bad:
        # A PATH IS AS GOOD AN ANSWER AS A NAME, and `env read` has always accepted both. Only
        # `apply` demanded a registered name — so the onboarding path grew an extra
        # registration whose ONLY purpose was to let this verb resolve a directory it was
        # about to be handed anyway. The pilot asked why ("mas quero entender o porquê disso
        # se o código fica todo no docker", 2026-08-12) and the honest answer was "no reason".
        # The manifest still belongs in the client's checkout — that part is design, and the
        # refusal below still holds for a URL-registered project.
        # A PATH LOOKS LIKE A PATH. Accepting any bare word that happens to match a directory
        # in the process's working directory would let a typo'd project name write a manifest
        # into whatever the worker's cwd contains — and the worker's cwd is the platform's own
        # install. Only an explicit path (a separator, `~`, or absolute) is treated as one.
        raw_arg = str(project)
        looks_like_a_path = raw_arg.startswith(("/", ".", "~")) or "/" in raw_arg
        candidate = Path(raw_arg).expanduser()
        if not (looks_like_a_path and candidate.is_dir()):
            return bad
        from openfactory.contracts.project import Project as _Project

        found = _Project(name=candidate.name, repo_path=str(candidate))
    raw_path = str(found.repo_path)
    propose_as_pr = _said_yes(pr)
    clone_to_discard: Path | None = None
    if "://" in raw_path or raw_path.startswith("git@"):
        # THE SERVER-SIDE HALF (pilot, 2026-08-12). A URL-registered project has no checkout
        # here, and writing into the worker's cache clone would be worse than refusing: nobody
        # reviews that tree and the next fetch replaces it. With `pr`, the factory clones,
        # writes, and proposes the manifest as a PULL REQUEST — the same shape the product
        # module already uses for requirements, and the only shape that keeps the human review
        # the file exists for.
        if not propose_as_pr:
            return refused(
                INVALID,
                f"{found.name} is registered as a clone URL ({raw_path}) — there is no checkout "
                f"here to write into. Either run this where a checkout is (`openfactory env "
                f"apply <path-to-your-checkout> --yes`), or let the factory propose it as a "
                f"pull request on that repository: add `--pr`.")
        if out:
            return refused(
                INVALID,
                "`out` writes to a path on this machine and `pr` proposes a branch on the "
                "repository — pick one; nothing was written.")
        from openfactory.adapters.forge.registry import build_forge, clone_url_for, repo_of
        from openfactory.credentials import forge_token_for
        from openfactory.onboarding.propose_manifest import (
            clone_for_proposal,
            default_branch,
        )
        from openfactory.util.causes import first_message

        token = forge_token_for(found)
        forge = build_forge(found, token=token)
        try:
            # THROUGH THE WRAPPER, NEVER `forge.clone_url` DIRECTLY. `build_forge` REFUSES an
            # ambient token on the Azure row on purpose — every caller in this codebase hands
            # the forge axis a GitHub credential — and calling the adapter's method with that
            # same token walks straight around the refusal: a github.com secret embedded in a
            # dev.azure.com URL and presented to Microsoft as HTTP Basic. `clone_url_for` is
            # the one place that lets the ADAPTER's own credential win (its docstring records
            # this exact defect being reintroduced by a convenience wrapper). Found by the
            # pre-commit adversarial review, 2026-08-12, before it ever ran.
            url = clone_url_for(found, repo_of(found), token=token)
        except Exception as exc:  # noqa: BLE001 — the message IS the finding
            return refused(UNAVAILABLE,
                           f"could not compose a clone URL for {found.name}: "
                           f"{first_message(exc, limit=160)}")
        # NO `--branch`: the clone lands on the repository's OWN default, and that is what the
        # pull request is opened against. `load_manifest_base_branch` answers `main` unless the
        # registry says otherwise, which fails at the PR for every `master`/`develop` client —
        # one step AFTER the push.
        clone_to_discard, why = clone_for_proposal(clone_url=url)
        if _clone_holder is not None and clone_to_discard is not None:
            # the wrapper's `finally` removes it however this ends
            _clone_holder["dir"] = clone_to_discard
        if clone_to_discard is None:
            return refused(
                UNAVAILABLE,
                f"could not clone {found.name} to propose its manifest ({why}) — check the "
                f"forge credential this deployment holds and that the repository exists.")
        checkout = clone_to_discard
        base = default_branch(clone_to_discard)
    else:
        if propose_as_pr:
            # NEVER ACCEPTED AND IGNORED. `pr` only means something for a project with no
            # checkout here; on a local path the file is written directly, and reporting "wrote
            # …" to somebody who asked for a pull request is the silent-no-op class this
            # codebase treats as its own defect (pre-commit review, 2026-08-12).
            return refused(
                INVALID,
                f"{found.name} is registered as a local checkout ({raw_path}), so `pr` has "
                f"nothing to do: the manifest is written into that checkout for you to review "
                f"in your own diff and commit. Drop `--pr`, or register the project by clone "
                f"URL if you want the factory to open the pull request itself.")
        checkout = Path(raw_path).expanduser()
        if not checkout.is_dir():
            return refused(
                NOT_FOUND,
                f"{found.name} has repo_path {raw_path!r} and there is no directory there "
                f"(measured on {where}) — nothing was written.")

    try:
        # THE ONE READER DECIDES WHETHER THIS REPOSITORY HAS A MANIFEST — before anything is
        # inferred, and whether the file would land in the checkout, in a clone about to become a
        # pull request, or at `out`. The `destination.exists()` fence below sees only the current
        # name, so a repository still on the directory's retired name read as "nothing here" and
        # this verb wrote a second manifest beside the one it has; the loader then answered from
        # the new file and the client's own gates were gone (review, 2026-08-25 — measured with
        # this function on a checkout carrying only the retired file). The refusal is the
        # loader's own sentence: what to rename, and that nothing under the old name is read.
        namespace.resolve(checkout, str(found.manifest_path), project=found.name)
    except namespace.RetiredNamespace as exc:
        return refused(CONFLICT, str(exc), verb="apply", measured_on=where, wrote=None,
                       project=found.name)

    try:
        from openfactory.onboarding import infer
    except ImportError as exc:
        return refused(
            UNAVAILABLE,
            f"this deployment has no inference module ({first_message(exc, limit=120)}) — there "
            f"is nothing to apply. Nothing was written.")
    entry, exports = _entry_point(infer, "propose", "infer")
    if entry is None:
        return refused(
            UNAVAILABLE,
            f"`openfactory.onboarding.infer` exports neither `propose(repo)` nor `infer(repo)` — "
            f"nothing "
            f"was written. It exports: {exports}")
    try:
        # RE-READ RATHER THAN REMEMBER. There is no proposal cached between `read` and `apply`, on
        # purpose: a stored proposal would let a repository change underneath it and be written
        # from a world that no longer exists, and the object that caches a read then writes to the
        # same source is a defect this codebase has already paid for once.
        proposal = await asyncio.to_thread(entry, str(checkout))
    except Exception as exc:  # noqa: BLE001
        log.exception("env_apply could not re-read %s", checkout)
        return refused(FAILED, f"could not read {checkout} ({first_message(exc, limit=200)}) — "
                               f"nothing was written.")
    rows, unreadable = _proposed_rows(proposal)
    if rows is None:
        return refused(FAILED, f"the inference produced a result this transport cannot read "
                               f"({type(proposal).__name__}, {unreadable} unreadable) — nothing "
                               f"was written.")

    # THE PANEL SENDS JSON AND THE CLI SENDS PYTHON, and the difference is a live hazard rather
    # than a tidiness point. `accept` arriving as the STRING "validate.test" iterates by character,
    # so the accepted set becomes {'v','a','l',…} and every inferred field is silently dropped —
    # a refusal that looks exactly like the rule working. One string is one field name.
    raw_accept = [accept] if isinstance(accept, str) else list(accept or [])
    accepted = {str(a).strip() for a in raw_accept if str(a).strip()}
    accept_all = "all" in {a.lower() for a in accepted}
    if answers is not None and not isinstance(answers, Mapping):
        return refused(
            INVALID,
            f"`answers` has to be a mapping of field to value, not {type(answers).__name__} — "
            f"nothing was written.")
    said = {str(k): v for k, v in dict(answers or {}).items()}
    how_accept, how_answer = _how_to_say_it(by)

    # A NAME NOBODY PROPOSED IS REFUSED, NOT DROPPED (#110). `--accept validate.tests` matched no
    # row, accepted nothing, and the refusal two screens down then blamed the reader for not
    # having accepted anything — a typo answered with an accusation. This is the courtesy every
    # adapter registry in this codebase already gives an unknown kind: say what exists.
    #
    # `answers` is deliberately NOT checked here: writing a field the inference never proposed is
    # this verb's design (a person in the room outranks a reading), and a name the SCHEMA refuses
    # is caught by `_place`/`Manifest` below with the field named.
    known = {r["name"] for r in rows}
    stray = sorted(a for a in accepted if a.lower() != "all" and a not in known)
    if stray:
        return refused(
            INVALID,
            f"nothing was written: {', '.join(stray)} "
            f"{'is not a field' if len(stray) == 1 else 'are not fields'} this read proposed. "
            f"It proposed: {', '.join(sorted(known)) or 'nothing'}. "
            f"Accept one of those with {how_accept}, or answer a field outright with "
            f"{how_answer}.",
            verb="apply", measured_on=where, wrote=None, project=found.name,
            written=[], skipped=[], unknown=stray, proposed=sorted(known))

    written, skipped = [], []
    for row in rows:
        name = row["name"]
        if name in said:
            # A HUMAN'S ANSWER IS WRITTEN WHATEVER SHAPE IT HAS, including an empty one: they were
            # in the room and they said it out loud. `_declares` judges the platform's proposals,
            # never a person's answer. `_as_the_schema_wants` only widens what they may TYPE — a
            # scalar for a list field — never what the schema will accept (#110).
            written.append({**row, "value": _jsonable(_as_the_schema_wants(name, said[name])),
                            "confidence": ANSWERED, "source": f"{by} said so"})
            continue
        chosen = (row["confidence"] == OBSERVED
                  or (row["confidence"] == INFERRED and (accept_all or name in accepted)))
        if chosen and not _declares(row["value"]):
            # READ, AND NOTHING THERE — a real answer, and not a declaration. See `_declares`: the
            # value equals the schema's own default, so the line would change no behaviour and
            # would spend the one bit `declared_keys()` has for "somebody filled this in".
            skipped.append({**row, "empty": True})
        elif chosen:
            written.append(row if row["confidence"] == OBSERVED
                           else {**row, "source": row["source"] or "accepted by hand"})
        else:
            skipped.append(row)
    # A field a human answered that the inference never proposed is still the human's answer, and
    # dropping it silently would be the platform overruling the person in the room.
    written += [{"name": k, "value": _jsonable(_as_the_schema_wants(k, v)),
                 "confidence": ANSWERED, "source": f"{by} said so", "note": ""}
                for k, v in said.items() if k not in known]

    if not written:
        # THE EMPTY READINGS ARE NAMED, not folded into "none was observed". A reader who just saw
        # `components  observed  src/App.csproj` in the report and is then told nothing was
        # observed would go looking for a bug in the read. What happened is narrower and it is the
        # whole point: it WAS read, and what it read declares nothing.
        empty = [s["name"] for s in skipped if s.get("empty")]
        return refused(
            INVALID,
            f"nothing to write: of {len(rows)} proposed field(s), none carries a value that "
            f"declares anything."
            + (f" {', '.join(empty)} {'was' if len(empty) == 1 else 'were'} read and "
               f"{'is' if len(empty) == 1 else 'are'} empty — that is an answer, but writing it "
               f"would only repeat the schema's own default and would make the file look filled "
               f"in." if empty else "")
            + f" Accept an inferred field with {how_accept}, or answer one with {how_answer} — "
              f"an empty manifest LOADS, declares nothing, and is then reported as healthy, "
              f"which is worse than no file at all.",
            # THE REFUSAL CARRIES ITS EVIDENCE. Refusing without showing what WAS read would trade
            # the false green for a silence, which is the same bug facing the other way: the client
            # in the room has to see that their repository answered, and that the answer was empty.
            verb="apply", measured_on=where, wrote=None, project=found.name,
            written=[], skipped=skipped)

    document: dict = {"version": 1}
    # THE SCHEMA'S OWN ORDER, not the proposal's. Two reasons, and neither is taste: the file has
    # to be byte-identical between two runs over the same repository (a manifest that reshuffles
    # itself is a diff nobody can review), and a client comparing it to `docs/project.yaml.example`
    # should find the fields where that file puts them.
    order = list(Manifest.model_fields)
    aliases = {(f.alias or n): n for n, f in Manifest.model_fields.items()}
    for row in sorted(written, key=lambda r: (
            order.index(aliases.get(str(r["name"]).split(".")[0].split("[")[0], ""))
            if aliases.get(str(r["name"]).split(".")[0].split("[")[0]) in order else len(order),
            str(r["name"]))):
        problem = _place(document, row["name"], row["value"])
        if problem:
            return refused(
                FAILED,
                f"cannot write {row['name']!r}: {problem}. Nothing was written — a manifest with a "
                f"key the schema forbids is a file that fails at the client, not here.")
    try:
        Manifest.model_validate(document)
    except ValidationError as exc:
        # A SCHEMA ERROR TURNED INTO AN EXECUTABLE OPTION, which is the whole card in one branch.
        # The commonest way to get here is real and was measured on a client's own repository: a
        # `Component` requires BOTH `path` and `stack`, so accepting the observed path and leaving
        # the inferred stack behind produces a manifest the schema refuses. Handing the client a
        # pydantic traceback there is `conformance` recommending `stack: security-oss` all over
        # again — a remedy the schema itself will not accept. So the fields the error names are
        # cross-referenced against the ones this run LEFT OUT, and the flag that would include each
        # one is printed.
        wanted = {".".join(str(p) for p in (e.get("loc") or ())) for e in exc.errors()}
        blocked = [s for s in skipped if s["name"] in wanted]
        options = " ".join(
            _how_to_say_this_field(by, s["name"], answer=s["confidence"] == UNKNOWN)
            for s in blocked)
        return refused(
            FAILED,
            f"the fields that were accepted do not make a valid manifest, so nothing was written: "
            f"{first_message(exc, limit=300)}"
            + (f" — {options} would supply what the schema is missing." if options else ""),
            verb="apply", measured_on=where, wrote=None, project=found.name,
            written=written, skipped=skipped, blocked_by=[s["name"] for s in blocked])

    when = datetime.now(UTC).date().isoformat()
    body = _yaml_header(written, skipped, when=when, who=str(by)) + yaml.safe_dump(
        document, sort_keys=False, allow_unicode=True, default_flow_style=False)
    destination = (Path(str(out)).expanduser() if out else checkout / found.manifest_path)

    if not consented:
        return refused(
            INVALID,
            f"nothing was written — this is what it WOULD write to {destination}. "
            f"{len(written)} field(s) in, {len(skipped)} left out. Run it again with yes=True "
            f"(`--yes`) if that is right.",
            verb="apply", measured_on=where, wrote=None, confirm=True, project=found.name,
            destination=str(destination), destination_exists=destination.exists(),
            content=body, written=written, skipped=skipped)
    if destination.exists() and not replace:
        return refused(
            CONFLICT,
            f"{destination} already exists and this will not overwrite it. If that file is theirs, "
            f"it wins — read it first. To replace it anyway pass force=True (`--force`); the "
            f"current file is copied to {destination.name}.bak before anything is written.",
            verb="apply", measured_on=where, wrote=None, project=found.name,
            destination=str(destination), destination_exists=True,
            content=body, written=written, skipped=skipped)

    backup = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            backup = destination.with_suffix(destination.suffix + ".bak")
            shutil.copy2(destination, backup)
        # ATOMIC: a temp file in the SAME directory (so `os.replace` stays on one filesystem),
        # then one rename. An interrupted write must never leave a client with half a manifest —
        # `write_text` truncates first, which is the exact durability defect `registry.py` already
        # records having shipped once.
        handle, temp = tempfile.mkstemp(dir=str(destination.parent), prefix=".openfactory-apply-")
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(temp, destination)
    except OSError as exc:
        return refused(
            FAILED,
            f"could not write {destination} ({exc.strerror or exc}) — nothing changed"
            + (f", and the previous file is still at {backup}." if backup else "."),
            verb="apply", measured_on=where, wrote=None, project=found.name)

    kept = ", ".join(w["name"] for w in written[:6]) + ("…" if len(written) > 6 else "")
    if clone_to_discard is not None:
        # The file exists only in a temporary clone. Committing and proposing it is what makes
        # the write real; without this arm the whole PR path would be an elaborate no-op in a
        # directory nobody will ever look at.
        from openfactory.adapters.forge.registry import repo_of
        from openfactory.onboarding.propose_manifest import propose

        outcome = propose(
            checkout=clone_to_discard, manifest_path=str(found.manifest_path),
            repo=repo_of(found), clone_url=url, base=base, forge=forge,
            project_name=found.name,
            summary=f"{len(written)} field(s) proposed from the repository: {kept}")
        if not outcome.ok:
            return refused(FAILED, outcome.detail, verb="apply", measured_on=where, wrote=None,
                           project=found.name, ref=outcome.ref, content=body)
        return done(
            f"{outcome.detail}"
            + (f" — {outcome.url}" if outcome.url else "")
            + (f". {len(skipped)} field(s) were left out on purpose."
               if skipped else ". Nothing was left out.")
            + f" Merge it, then: `openfactory env check {found.name}`.",
            verb="apply", measured_on=where, wrote=str(found.manifest_path),
            project=found.name, pull_request=outcome.url, ref=outcome.ref,
            existed=outcome.existed, written=written, skipped=skipped, content=body)

    return done(
        f"wrote {destination} — {len(written)} field(s): {kept}. "
        + (f"The previous file is at {backup.name}. " if backup else "")
        + (f"{len(skipped)} field(s) were left out on purpose; `openfactory env read "
           f"{found.name}` lists them." if skipped else "Nothing was left out.")
        + f" Next: `openfactory env check {found.name}`.",
        verb="apply", measured_on=where, wrote=str(destination), project=found.name,
        destination=str(destination), backup=str(backup) if backup else None,
        written=written, skipped=skipped, content=body)


# ── the table ───────────────────────────────────────────────────────────────────────────────────
#
# ORDER IS DELIBERATE and it is what `openfactory act --list` prints: the two everyday answers to
# a parked job first, then the things that change what the factory is doing, then the release
# gate, then the read-only questions. Alphabetical would put `ack` above `approve_prod` and bury
# `resume`.

CATALOG: dict[str, ActionSpec] = {
    spec.name: spec for spec in (
        ActionSpec(
            name="resume",
            summary="tell a parked job to carry on — optionally picking one of the options it "
                    "offered",
            run=_resume,
            required=("project", "issue"),
            optional=("choice",),
            choose_when="ONLY if a fresh run would make progress. If it would re-park on the "
                        "same blocker — no acceptance criteria, a throwaway ticket, a human-only "
                        "fix needed first — then resuming LOOPS and `skip` is the honest answer",
        ),
        ActionSpec(
            name="skip",
            summary="abandon a parked job and free the floor for the next ticket",
            run=_skip,
            required=("project", "issue"),
            choose_when="for a parked job a re-run cannot advance, and for an ORPHANED one "
                        "(ticket closed, workflow still holding the line). The ticket is left for "
                        "its owner rather than thrown away",
        ),
        ActionSpec(
            name="ack",
            summary="record that a person has taken a review finding, closing its open loop",
            run=_ack,
            required=("project", "issue"),
        ),
        ActionSpec(
            name="enable",
            summary="turn pickup on or off for a project",
            run=_enable,
            required=("project",),
            optional=("enabled",),
        ),
        ActionSpec(
            name="merge",
            summary="land the PR a human-gated job is waiting on",
            run=_merge,
            required=("project", "issue"),
            optional=("comment",),
            choose_when="when the gates passed and the review did not reject. The DECISION is "
                        "the human's and they have made it by asking; the execution is this "
                        "platform's, with its own credential — so say what you are relying on",
        ),
        ActionSpec(
            name="adjust",
            summary="send the PR back for one repair pass against your own words — same PR",
            run=_adjust,
            required=("project", "issue", "instruction"),
            choose_when="when the work is nearly right and you can NAME the change: a review "
                        "finding that still applies, a missed case, a wrong shape. Prefer this "
                        "over `discard` for anything salvageable — it keeps the same pull request "
                        "and spends one repair pass, where discarding throws the run away and the "
                        "ticket starts again from nothing",
        ),
        ActionSpec(
            name="review",
            summary="read the open PR again with the independent reviewer — same PR, no change "
                    "to the code, and the verdict on the card is replaced",
            run=_review,
            required=("project", "issue"),
            choose_when="when the reading you have is out of date or was answered — an `adjust` "
                        "fixed what the review rejected, or a pass rewrote the diff — and "
                        "somebody is about to decide on a verdict about code that is gone. It "
                        "spends a model pass and writes nothing, so prefer it over sending a "
                        "person to read the diff themselves, and never offer it as a formality "
                        "on a verdict that is already current",
        ),
        ActionSpec(
            name="discard",
            summary="close the PR without merging and free the floor — the branch is untouched",
            run=_discard,
            required=("project", "issue"),
            optional=("reason",),
            choose_when="for work that should not land: the review rejected it, or the change "
                        "is wrong at the root and no instruction would repair it. NEVER as a way "
                        "to clear a queue, and never when `adjust` would do",
        ),
        ActionSpec(
            name="stop",
            summary="end a running job nothing else can reach and free the floor — it cannot "
                    "resume; the ticket goes back to the board",
            run=_stop,
            required=("project", "issue"),
            optional=("reason",),
            choose_when="for a job nothing else can reach — wedged, holding the floor with no "
                        "gate and no park to answer. It does NOT resume: the ticket goes back to "
                        "the board and a fresh job starts from the beginning, losing whatever that "
                        "run had in flight. Never for a job that is WAITING on somebody; that is "
                        "the platform working and it has its own verb",
        ),
        ActionSpec(
            name="scan",
            summary="scan a project's TO-DO column now and start what the floor allows",
            run=_scan,
            required=("project",),
        ),
        ActionSpec(
            name="start",
            summary="start one job for one ticket",
            run=_start,
            required=("project", "issue"),
            optional=("sandbox", "promote", "durable"),
        ),
        ActionSpec(
            name="approve_prod",
            summary="answer a job's production-release gate — the parked workflow is waiting on it",
            run=_approve_prod,
            required=("project", "issue", "version", "approver", "password"),
            optional=("comment",),
        ),
        ActionSpec(
            name="promote",
            summary="run the staging→production promotion for a ticket in this process",
            run=_promote,
            required=("project", "issue", "version", "approver", "password"),
            optional=("comment",),
        ),
        ActionSpec(
            name="ask",
            summary="ask the tech-lead a question about a project and get its read-only answer",
            run=_ask,
            required=("project", "question"),
            needs_admin=False,
        ),
        ActionSpec(
            name="diagnose",
            summary="ask the tech-lead why a job is parked and what it would do about it",
            run=_diagnose,
            required=("project", "issue"),
            needs_admin=False,
        ),
        # ── the environment round. `read` before `check` before `apply`, which is the order they
        # are used in and the order they are safe in: the one that proposes, the one that grades,
        # and the one that writes. `needs_admin` splits on exactly that line — reading a repository
        # and asking whether a project is ready are questions, and a question is not authority.
        # ── the product role. ADR-0039's shape: these are the SAME calls the Slack package makes,
        # so a deployment with no Slack can propose a requirement, accept it and watch the cards
        # appear — which is the acceptance test #98 states for itself.
        ActionSpec(
            name="product_status",
            scope=PRODUCT,
            summary="whether the product role can see its corpus at all, and where measured",
            run=_product_status,
            required=("project",),
            needs_admin=False,
        ),
        ActionSpec(
            name="product_requirements",
            scope=PRODUCT,
            summary="every requirement in the corpus — number, title and status",
            run=_product_requirements,
            required=("project",),
            needs_admin=False,
        ),
        ActionSpec(
            name="product_triage",
            scope=PRODUCT,
            summary="read the board and report what is wrong with it — writes nothing",
            run=_product_triage,
            required=("project",),
            needs_admin=False,
        ),
        ActionSpec(
            name="product_baseline",
            scope=PRODUCT,
            summary="the brownfield first pass — reads the whole codebase and proposes what it "
                    "observed, as a pull request",
            run=_product_baseline,
            required=("project",),
            optional=("yes",),
            needs_admin=True,
        ),
        ActionSpec(
            name="product_needs_action",
            scope=PRODUCT,
            summary="what is parked and whose problem it is — reads, writes nothing, "
                    "and spends one model call per parked ticket",
            run=_product_needs_action,
            required=("project",),
            optional=("limit",),
            needs_admin=False,
        ),
        ActionSpec(
            name="product_announce",
            scope=PRODUCT,
            summary="the role arrives and says where things stand",
            run=_product_announce,
            required=("project",),
            needs_admin=False,
        ),
        ActionSpec(
            name="product_pending",
            scope=PRODUCT,
            summary="what the product role has staged and is waiting on a person for",
            run=_product_pending,
            required=("project",),
            needs_admin=False,
        ),
        ActionSpec(
            name="product_answer",
            scope=PRODUCT,
            summary="answer a proposal the product role staged — the pair of product_pending",
            run=_product_answer,
            required=("project", "token", "answer"),
            optional=("yes",),
        ),
        ActionSpec(
            name="product_ask",
            scope=PRODUCT,
            summary="ask the product role something — it drafts, and writes nothing",
            run=_product_ask,
            required=("project", "question"),
            needs_admin=False,
        ),
        ActionSpec(
            name="product_say",
            scope=PRODUCT,
            summary="a turn of conversation with the product role — it remembers, "
                    "and writes nothing",
            run=_product_say,
            required=("project", "message"),
            optional=("thread",),
            needs_admin=False,
        ),
        ActionSpec(
            name="product_propose",
            scope=PRODUCT,
            summary="record a drafted requirement as a pull request — the sign-off surface",
            run=_product_propose,
            required=("project",),
            optional=("answer", "question", "yes"),
        ),
        ActionSpec(
            name="product_accept",
            scope=PRODUCT,
            summary="turn a written requirement into a promise the factory defends (ADR-0032)",
            run=_product_accept,
            required=("project", "number"),
            optional=("yes",),
        ),
        ActionSpec(
            name="product_close_card",
            scope=PRODUCT,
            summary="close one card, naming the one that stays",
            run=_product_close_card,
            required=("project", "number"),
            optional=("in_favour_of", "reason", "yes"),
        ),
        ActionSpec(
            name="product_align_card",
            scope=PRODUCT,
            summary="make a card execute the requirement it should — citation and criteria",
            run=_product_align_card,
            required=("project", "number", "requirement"),
            optional=("yes",),
        ),
        ActionSpec(
            name="product_refine_card",
            scope=PRODUCT,
            summary="give a backlog ticket something testable to be judged against",
            run=_product_refine_card,
            required=("project", "number"),
            optional=("yes",),
        ),
        ActionSpec(
            name="product_record_decision",
            scope=PRODUCT,
            summary="write a decision taken after acceptance into the requirement's register",
            run=_product_record_decision,
            required=("project", "number", "decision"),
            optional=("yes",),
        ),
        ActionSpec(
            name="product_note_fact",
            scope=PRODUCT,
            summary="write down one thing somebody said about the business, attributed",
            run=_product_note_fact,
            required=("project", "term", "body"),
            optional=("yes",),
        ),
        ActionSpec(
            name="product_file_defect",
            scope=PRODUCT,
            summary="register a broken promise as work, citing the requirement it violates",
            run=_product_file_defect,
            required=("project", "restated"),
            optional=("violates", "severity", "yes"),
        ),
        ActionSpec(
            name="product_queue",
            scope=PRODUCT,
            summary="what should start next, in order — and why not the others",
            run=_product_queue,
            required=("project",),
            optional=("limit",),
            needs_admin=False,
        ),
        ActionSpec(
            name="product_promote",
            scope=PRODUCT,
            summary="move approved tickets into the queue — the one act here that spends money",
            run=_product_promote,
            required=("project", "numbers"),
            optional=("yes",),
        ),
        ActionSpec(
            name="product_release",
            scope=PRODUCT,
            summary="the client's approval putting a delivery in front of their own users",
            run=_product_release,
            required=("project", "issue"),
            optional=("yes",),
        ),
        ActionSpec(
            name="product_drop",
            scope=PRODUCT,
            summary="drop a proposed requirement, with the reason recorded beside it",
            run=_product_drop,
            required=("project", "number"),
            optional=("reason", "yes"),
        ),
        ActionSpec(
            name="env_read",
            summary=f"read a repository and propose what its {namespace.MANIFEST} should say — "
                    f"writes nothing",
            run=_env_read,
            required=("target",),
            needs_admin=False,
        ),
        ActionSpec(
            name="env_context",
            summary="survey a repository and propose the context an agent will read from then on "
                    "— writes nothing",
            run=_env_context,
            required=("target",),
            optional=("ask", "write", "yes"),
            needs_admin=False,
        ),
        ActionSpec(
            name="env_check",
            summary="one verdict on whether a project can be picked up, and where it was measured",
            run=_env_check,
            required=("project",),
            needs_admin=False,
        ),
        ActionSpec(
            name="env_apply",
            summary="write the proposed manifest — only the fields a human accepted, only with yes",
            run=_env_apply,
            required=("project",),
            optional=("yes", "force", "accept", "answers", "out", "pr"),
        ),
    )
}

#: The rows whose implementation has not moved yet, as a literal. A test asserts this equals what
#: the catalog actually reports, so the migration cannot quietly stall and cannot quietly finish:
#: moving one and forgetting this list fails the suite, which is the reminder to update the card.
#:
#: `ask` and `diagnose` are blocked on C-24 (#52) and #53 rather than on effort — their brains do
#: not exist as neutral code yet.
NOT_MOVED: tuple[str, ...] = ()
