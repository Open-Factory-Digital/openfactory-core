"""JobWorkflow — the generic SDLC lifecycle as a durable Temporal workflow.

This is the SAME lifecycle the JobRunner has always expressed, now orchestrated
durably: implement→validate→review→PR, then (where a live pipeline exists) a
human-gated staging→prod promotion. The workflow body is deterministic — all
side effects go through activities — which is exactly what lets Temporal resume
it from the last completed step after a crash, and park it for days awaiting a
human's prod approval without polling or a lost job.

One workflow for every project; project-specific behavior comes from the config
the activities load (docs/architecture.md; the cloud realisation's runtime document ships
with the openfactory-aws add-on package).
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from openfactory.adapters.sandbox.timeouts import ACTIVITY_CEILING
    from openfactory.contracts import DecisionOption, DecisionRequest, JobState, RunResult
    from openfactory.runtime.temporal.activities import (
        adjust_pr,
        check_ci_status,
        check_deploy_status,
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
        settle_ticket,
        split_ticket,
        stop_job,
        techlead_ask,
        techlead_watch,
        update_pr_branch,
    )
    from openfactory.runtime.temporal.io import (
        AdjustInput,
        AskInput,
        CiRepairInput,
        CoordinatorInput,
        CoordinatorItem,
        CoordinatorSayInput,
        DeployNotifyInput,
        DeployStatusInput,
        DeployWatchInput,
        HoldSyncInput,
        JobMetricsInput,
        JobParams,
        KnowledgeRefreshInput,
        MergeCheckInput,
        PreflightInput,
        ProductAnswerInput,
        ProductAskInput,
        ProductBaselineInput,
        ProductBreakdownInput,
        ProductCardInput,
        ProductNeedsActionInput,
        ProductQueueInput,
        ProductSayInput,
        PromoteInput,
        ReleaseInput,
        ReviewLoopInput,
        ReviewPassInput,
        RunJobInput,
        SplitInput,
        TicketRef,
    )
    from openfactory.techlead import classify, remedy_for

    # THE LIFECYCLE'S OWN PHRASEBOOK (#160). Eleven sentences were welded into this file, half of
    # them Portuguese and half English, so one client heard "Dividi o #12" and another "staging did
    # not verify" — both unprompted, neither in the language the project declares. Imported HERE,
    # inside the sandbox pass-through, because rendering is a dict lookup plus `format`: pure, and
    # therefore replay-safe. The language is `params.language`, a field for exactly this reason.
    from openfactory.techlead import voice as tl_voice
    from openfactory.util.causes import describe

# run_job is one COARSE activity (the whole JobRunner): re-running it re-invokes
# the agent (cost) and duplicates tracker comments, so it stays single-attempt
# until the sandbox is externalized (Fargate) and the job is split into finer,
# individually-idempotent activities. Fail loud instead.
_ONCE = RetryPolicy(maximum_attempts=1)
# Promotion steps are read-mostly and their one write (create_tag) is idempotent
# (find-or-create), so transient GitHub/network failures during a release can be
# retried safely — exactly where resilience matters most.
_RETRY = RetryPolicy(maximum_attempts=4, initial_interval=timedelta(seconds=2))
# The Fargate job is idempotent by job tag (a retry re-attaches to the running task or
# reconciles a finished one), so it CAN retry — recovering from a dead/expired worker.
_RETRY_REATTACHING = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=10))
# A job that PAUSED (agent hit a rate-limit / usage cap) is resumed DURABLY by the
# workflow itself — it sleeps (parked, no compute) and re-runs. This is the only correct
# home for resume: an external scheduler might not be running (that was the silent-stall
# bug). Bounded so a permanently-limited account can't loop forever.
_PAUSE_BACKOFF = timedelta(minutes=30)
# The resume backoff GROWS while the whole pool stays rate-limited (30→60→90→120…), capped —
# so a pool-wide usage exhaustion doesn't re-launch the agent every 30 min and re-burn the very
# tokens it's waiting on (partner-reported). (A perfect fix is C2's cheap session-resume; this
# paces it meanwhile.)
_PAUSE_BACKOFF_MAX = timedelta(hours=2)
_MAX_PAUSE_RESUMES = 48  # bounded retrying before giving up to ON_HOLD
#: Past this, a park's timeout is not a deadline — it is the caller saying "hold until a human
#: answers" (a decision park passes ten years for exactly that reason). A surface given the raw
#: number would print a date in the next decade as though somebody had set it; given `None` it
#: says what is true, which is that nothing will move this on its own (#140).
_HELD_UNTIL_ANSWERED = timedelta(days=30)
# CI-aware auto-merge (ADR-0004): watch the open PR's CI; on red, repair (bounded, mirrors
# the gate-repair cap) instead of leaving --auto armed forever. Poll gently — CI is minutes.
_CI_POLL = timedelta(minutes=2)
_CI_REPAIR_MAX = 2
# How many times to auto-update a BEHIND PR before escalating. Other developers keep advancing
# main, so our single PR can fall behind repeatedly; we bring it up to date (self-heal) up to
# this many times, then hand it to a human — never a silent forever-wait (owner invariant).
_REBASE_MAX = 6
# After the PR has been open a while, WIDEN the merge-watch poll. A human-gated PR can sit for
# days; at the 2-min poll that is ~11.6k Temporal history events/day, crossing the server's
# hard ~51.2k-event ceiling around day ~4-5 — which TERMINATES the workflow before the 14-day
# merge deadline it promises (no ON_HOLD, no notify). The wider poll keeps 14 days well under
# the ceiling; the fast window preserves prompt auto-merge + CI-repair right after PR-open.
_CI_FAST_WINDOW = timedelta(hours=1)
_CI_SLOW_POLL = timedelta(minutes=15)
#: How much of a human's `adjust` instruction reaches the agent (#68). It is free text typed into
#: a panel, and it lands in an agent's context at the same trust level as the ticket body — so it
#: is bounded here, at the boundary, rather than trusted to be short.
_ADJUST_CHARS = 2000
# Post-merge deploy watch (ADR-0005): a project's own CI deploys on push to main; we observe
# that run on the merge commit and notify its outcome. Poll gently — a deploy is minutes.
_DEPLOY_POLL = timedelta(minutes=1)


def merge_wait_note(auto: bool) -> str:
    """What the standing PR wait is ON, in the engine's own words — ONE definition (#148).

    The merge loop is shared by both paths, and for a long time so was this sentence: a PR on the
    HUMAN path was told "waiting for CI / the merge" to a reader who *was* the wait. Naming the
    wrong blocker is worse than naming none — it sends somebody to wait out a build that already
    finished. Pure, so the guard can read it straight rather than driving the engine."""
    return "waiting for CI / the merge" if auto else "waiting for your review and merge"


@workflow.defn
class AskWorkflow:
    """One question for the tech-lead, answered ON THE WORKER (where agents authenticate).

    Exists because `ask` used to run in whichever process served the HTTP request. The panel's
    process holds no harness credential — deliberately; it is the outward-facing surface — so the
    tech-lead's "answer" there was the CLI's own "Not logged in · Please run /login", returned
    with a straight face. Found by the product owner asking why the tech-lead chat had never
    appeared.

    A WORKFLOW rather than a bare RPC so the answer survives the asker: the panel can time out,
    the browser can close, and the question still completes, costed and visible in the engine
    like every other agent invocation."""

    @workflow.run
    async def run(self, inp: AskInput) -> dict:
        return await workflow.execute_activity(
            techlead_ask, inp,
            # clone + read-only agent pass; generous, and far under the merge-watch scale
            start_to_close_timeout=timedelta(minutes=6),
            retry_policy=RetryPolicy(maximum_attempts=1),  # a question is not idempotent spend
        )


@workflow.defn
class ProductAskWorkflow:
    """One request for the product role to draft, answered ON THE WORKER.

    THE SIBLING OF `AskWorkflow`, and here for the same reason measured a second time: the row
    used to draft in whichever process served the request, behind a check that the harness binary
    was on that process's PATH. The panel is built from the worker's own Dockerfile and therefore
    HAS the binary — what it has not got is the credential — so the check passed on precisely the
    process it existed to stop. See `ProductAskInput`.

    LONGER THAN THE TECH-LEAD'S SIX MINUTES, because this reads more: `ProductModule.draft` builds
    a worktree of the documentation repository AND the product's code — the role's own prompt
    promises it opens the source rather than inferring from documents — before the pass begins.

    ONE ATTEMPT, like its sibling: a draft is spend, not an idempotent read, and a retry would
    produce a DIFFERENT text for the same words — which is the one thing `product_propose` exists
    to prevent."""

    @workflow.run
    async def run(self, inp: ProductAskInput) -> dict:
        return await workflow.execute_activity(
            product_role_ask, inp,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn
class ProductBreakdownWorkflow:
    """An accepted requirement becoming units of work on the board (#98).

    A SECOND ACT ON A FINISHED ONE, and the timeouts say so. The agreement is written and pushed
    before this starts, so nothing here can cost it — the caller reports the acceptance whatever
    comes back, and this failing means cards are missing, never that a promise was lost.

    ONE ATTEMPT. `file_issues` writes tickets to a client's board, and a retry that ran after a
    partial success would file the same work twice; `break_down`'s own results already distinguish
    a card it created from one that `existed`."""

    @workflow.run
    async def run(self, inp: ProductBreakdownInput) -> list[dict]:
        return await workflow.execute_activity(
            product_role_break_down, inp,
            start_to_close_timeout=timedelta(minutes=12),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn
class ProductAnswerWorkflow:
    """A staged proposal answered by token, ON THE WORKER (#105).

    ONE ATTEMPT, and this is the one place where that is not a cost decision. The act is a
    COMPARE-AND-SWAP pop: attempt 1 may perform the write and then die before reporting, and
    attempt 2 would find the proposal gone and answer "somebody already handled this" — which is
    the honest sentence for a race but a lie about a retry of our own. Worse, the two kinds that
    write to a client's board (`accept` chains into the breakdown, `align` rewrites criteria) are
    exactly the ones a second run would duplicate.

    TWELVE MINUTES, the breakdown's number, because that is the longest thing a yes can turn into:
    a confirmed acceptance files a card per unit of work through an agent pass."""

    @workflow.run
    async def run(self, inp: ProductAnswerInput) -> dict:
        return await workflow.execute_activity(
            product_role_answer, inp,
            start_to_close_timeout=timedelta(minutes=12),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn
class ProductBaselineWorkflow:
    """The brownfield first pass, ON THE WORKER (#105).

    ONE ATTEMPT, AND THE FIRST VERSION SAID TWO ON AN ARGUMENT THAT DOES NOT HOLD. It read: a
    blind retry is safe because `propose_baseline` asks the forge whether the branch already
    carries an open proposal and reports `existed`. An adversarial pass measured the window that
    argument skips — attempt 1 pushes `product/baseline` and then FAILS to open the pull request
    (a rate limit, an expired token, the worker dying in between). Attempt 2 asks the forge, finds
    no PR, and pushes again; both attempts also overlap if the first is merely slow rather than
    dead. "Idempotent" was true of the happy path and asserted of all of them.

    So it does not retry. A first pass that fails is a first pass somebody runs again, knowing
    they are doing it — which is the correct amount of ceremony for a verb that spends tens of
    minutes and writes into a client's repository.

    FORTY MINUTES. It reads an ENTIRE repository through an agent before it writes anything; the
    needs-action pass next door is bounded by a ticket count, and this one by the size of the
    client's codebase."""

    @workflow.run
    async def run(self, inp: ProductBaselineInput) -> dict:
        return await workflow.execute_activity(
            product_role_baseline, inp,
            start_to_close_timeout=timedelta(minutes=40),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn
class ProductNeedsActionWorkflow:
    """What is parked and whose problem it is, classified ON THE WORKER (#105).

    READ-ONLY, so a retry is safe in the way `ProductAskWorkflow`'s is not — `review_needs_action`
    hardcodes `may_act=False` and every decision it produces is an observation. Bounded at two
    attempts all the same: it spends one model call per parked ticket, and an unbounded retry
    against a board that keeps timing out is money with no answer at the end.

    TWENTY MINUTES, not ten. `limit` defaults to 10 tickets and each one is its own agent call on
    top of composing a worktree of two repositories; the queue proposal next door makes ONE pass
    over a board it has already read."""

    @workflow.run
    async def run(self, inp: ProductNeedsActionInput) -> dict:
        return await workflow.execute_activity(
            product_role_needs_action, inp,
            start_to_close_timeout=timedelta(minutes=20),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


@workflow.defn
class ProductQueueWorkflow:
    """The queue proposal, produced ON THE WORKER (#98 / #105).

    READ-ONLY, so unlike its two siblings a retry is safe: nothing is written, and a second
    attempt after a transport blip costs one pass rather than a duplicated act. Still bounded —
    it reads a board and runs an agent over it, and an unbounded retry against a board that keeps
    timing out is spend with no answer at the end."""

    @workflow.run
    async def run(self, inp: ProductQueueInput) -> dict:
        return await workflow.execute_activity(
            product_role_queue, inp,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


@workflow.defn
class ProductCardWorkflow:
    """One card rewritten by the product role, on the worker (#105).

    ONE ATTEMPT. Both verbs end in a tracker write over a client's ticket body, and a retry after
    a partial success rewrites text a person may already have read. The module's own
    `WriteResult` distinguishes a card it changed from one that already said enough."""

    @workflow.run
    async def run(self, inp: ProductCardInput) -> dict:
        return await workflow.execute_activity(
            product_role_card, inp,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn
class ProductSayWorkflow:
    """One conversational turn with the product role, on the worker (#105).

    ONE ATTEMPT. The turn is recorded in the transcript before the model is asked, so a retry
    would answer a conversation that already contains its own question twice — and a second reply
    to one message is worse than none."""

    @workflow.run
    async def run(self, inp: ProductSayInput) -> dict:
        return await workflow.execute_activity(
            product_role_say, inp,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn
class DeployWatchWorkflow:
    """Post-merge deploy WATCH (ADR-0005). Started as an ABANDONED child the instant a job
    merges, so the parent JobWorkflow completes and frees the floor for the next ticket
    immediately. This durably polls the project's OWN deploy (its `deploy` CI on the merge
    commit) and NOTIFIES the outcome — it can never gate a ticket or hold the floor. Worst
    case is a late or missed notification, never a stuck pipeline (the user's rule: watch +
    notify, don't block)."""

    @workflow.run
    async def run(self, inp: DeployWatchInput) -> str:
        deadline = workflow.now() + timedelta(minutes=inp.timeout_minutes)
        last_url: str | None = None
        while workflow.now() < deadline:
            probe = await workflow.execute_activity(
                check_deploy_status,
                DeployStatusInput(project=inp.project, pr_url=inp.pr_url, workflow=inp.workflow),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=_RETRY,  # read-only, safe to retry
            )
            status = probe.get("status")
            last_url = probe.get("run_url") or last_url
            if status in ("success", "failure"):
                await self._notify(inp, status, last_url)
                return status
            # "none" (run not dispatched yet) / "pending" (still deploying) → keep watching
            await workflow.sleep(_DEPLOY_POLL)
        await self._notify(inp, "timeout", last_url)  # a stuck deploy notifies, never hangs
        return "timeout"

    async def _notify(self, inp: DeployWatchInput, status: str, run_url: str | None) -> None:
        # Best-effort: the notification is the watch's ONLY output, but a broken channel
        # (Telegram down) must not fail the DeployWatch — a failed child reads as
        # "deploy_failed" on the panel even when the deploy itself SUCCEEDED. Swallow so the
        # watch reports its true status to Temporal and only the side-channel is lost (M3).
        try:
            await workflow.execute_activity(
                notify_deploy,
                DeployNotifyInput(
                    project=inp.project, issue=inp.issue,
                    status=status, env=inp.env, run_url=run_url, url=inp.url,
                ),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=_RETRY,
            )
        except Exception:
            workflow.logger.warning("deploy notify failed for %s#%s", inp.project, inp.issue)
        # the tech-lead narrates the deploy outcome too (panel toast / Slack later).
        # Same versioning guard: an in-flight DeployWatch replaying old history skips this.
        if not workflow.patched("coordinator-narration"):
            return
        icon = {"success": "✓", "failure": "✗"}.get(status, "·")
        try:
            await workflow.execute_activity(
                notify_coordinator_say,
                CoordinatorSayInput(project=inp.project,
                                    text=f"{icon} #{inp.issue} {inp.env} deploy {status}",
                                    kind="deploy"),
                start_to_close_timeout=timedelta(minutes=1), retry_policy=_ONCE)
        except Exception:  # noqa: BLE001 — narration is additive; never fail a deploy over it
            workflow.logger.warning("deploy narration failed for #%s (%s)", inp.issue, inp.env)


# How many decisions one CoordinatorWorkflow run processes before continue-as-new — keeps the
# always-alive workflow's history bounded (a long-lived signal loop would grow forever).
_COORDINATOR_BATCH = 400


@workflow.defn
class CoordinatorWorkflow:
    """The project's ALWAYS-ALIVE tech lead (v0). One per project
    (id openfactory-coordinator-<project>),
    started on first need via signal-with-start and kept running (continue-as-new to bound
    history). JobWorkflows signal it (`on_decision`) whenever they park on a decision; it reasons
    as a senior engineer (LLM, coordinator role, project-aware) and signals a HUMANIZED briefing +
    recommendation back to that job (advise_decision). v0 is ADVISORY — it never takes the action;
    a human still decides. v1 grows project-wide awareness + a safe, recorded action set."""

    def __init__(self) -> None:
        self._queue: list[CoordinatorItem] = []  # decisions awaiting a humanized briefing
        self._log: list[dict] = []  # recent narrated updates (the panel toasts these)
        self._seq = 0  # monotonic message id, carried across continue-as-new
        self._signals = 0  # total signals this run (bounds history → continue-as-new)

    @workflow.signal
    async def on_decision(self, item: CoordinatorItem) -> None:
        self._queue.append(item)
        self._signals += 1

    @workflow.signal
    async def say(self, text: str, kind: str = "") -> None:
        """The coordinator narrates a relevant lifecycle moment (pickup / merge / deploy). Kept
        in a small ring buffer the panel polls + toasts — and the SAME feed a Slack/PO bot reads
        later (API-first). Best-effort: purely additive, no side effects here."""
        self._seq += 1
        self._log.append({"id": self._seq, "text": text[:280], "kind": kind[:24]})
        self._log = self._log[-50:]
        self._signals += 1

    @workflow.query
    def recent(self) -> list[dict]:
        """The recent narrated updates (id-ordered) — the panel/bot fetch this and show what's
        new since the id they last saw."""
        return self._log

    @workflow.run
    async def run(self, inp: CoordinatorInput) -> None:
        self._seq = inp.seq0  # keep ids monotonic across continue-as-new
        self._log = list(inp.recent)
        while True:
            await workflow.wait_condition(
                lambda: bool(self._queue) or self._signals >= _COORDINATOR_BATCH)
            while self._queue:  # advise on every parked decision (LLM tech-lead)
                item = self._queue.pop(0)
                try:
                    advice = await workflow.execute_activity(
                        coordinator_advise, item,
                        start_to_close_timeout=timedelta(minutes=10),
                        heartbeat_timeout=timedelta(seconds=120), retry_policy=_ONCE,
                    )
                except Exception:  # noqa: BLE001 — a flaky briefing must not kill the coordinator
                    # The human gets the raw decision with no humanised take, which is the whole
                    # point of the coordinator having been asked.
                    workflow.logger.warning("coordinator briefing failed for %s", item.issue)
                    advice = {}
                if advice:  # relay the tech-lead's take to the parked job (best-effort)
                    try:
                        await workflow.get_external_workflow_handle(item.job_id).signal(
                            "advise_decision", advice)
                    except Exception:
                        workflow.logger.warning("advise relay failed for %s", item.job_id)
            if self._signals >= _COORDINATOR_BATCH:
                break  # bound history — a fresh run below, carrying the log + seq
        workflow.continue_as_new(
            CoordinatorInput(project=inp.project, seq0=self._seq, recent=self._log))


@workflow.defn
class TechLeadWatchWorkflow:
    """The tech-lead's rounds (ADR-0020 §3).

    Its own workflow, and hourly rather than weekly: a park holding the floor costs capacity every
    hour it sits, while a rotting backlog costs over weeks. The two watchers have different
    cadences because they watch things that decay at different speeds."""

    @workflow.run
    async def run(self, project_name: str) -> str:
        return await workflow.execute_activity(
            techlead_watch,
            project_name,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=_ONCE,
        )


@workflow.defn
class ProductSweepWorkflow:
    """The product role's scheduled look at the board (ADR-0019).

    A workflow of its own rather than a step inside the poller: the poller's job is to START WORK,
    and hanging a reporting pass off it would mean a slow board read delaying a ticket. They also
    fail differently — a sweep that cannot read the board should be quiet, while a poller that
    cannot read it must not silently stop picking things up.

    One activity, no retries beyond the default: a sweep is a courtesy, and a missed one costs a
    day of not being told something that will still be true tomorrow."""

    @workflow.run
    async def run(self, project_name: str) -> str:
        return await workflow.execute_activity(
            product_sweep,
            project_name,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=_ONCE,
        )


@workflow.defn
class JobWorkflow:
    def __init__(self) -> None:
        self._approval: dict | None = None
        self._awaiting_approval = False
        # Single-line strict (ADR-0010): when the floor is HELD on a non-progressing job — an
        # impediment (spec/cost/validation/review/e2e/merge/CI/auth/crash) or a rate-limit pause —
        # `_paused` carries the reason for the panel, and `_action` is the operator's decision.
        self._paused: dict | None = None
        self._action: str | None = None  # "resume" | "skip"
        self._choice: str | None = None  # the DecisionRequest option key the operator picked
        # Set when the operator SKIPS from a park inside the merge loop — the outer impediment
        # check must then complete directly instead of parking the same give-up a second time.
        self._skipped = False
        #: how many times this job has already been remedied for each cause (ADR-0020). Per JOB,
        #: because a budget that resets on every park is not a budget — it is a loop that pauses.
        self._remedied: dict[str, int] = {}
        # Set while the job is in the durable merge watch — the PR exists and the job is
        # waiting for it to land. The panel reads this so "waiting for YOUR merge" (human
        # path) is never invisible again (#69 sat 7.5h showing "starting…"). Display-only:
        # no signal acts on it, so adding it is replay-safe for in-flight workflows.
        self._merge_wait: dict | None = None
        # THE HUMAN'S ANSWER TO THE MERGE GATE (#68, C-32) — {answer, instruction, by}.
        #
        # Until this existed the gate could not be answered AT ALL. `_paused` is never set during
        # the merge watch, so `awaiting_action` returns None; `view.act_job` queries it before
        # signalling and refuses; the action layer maps that to CONFLICT. The panel, Slack and
        # `openfactory act` were all structurally unable to reach a human-gated PR — and the human
        # path
        # cannot self-heal out either, because the one branch that merges a clean PR is gated on
        # `result.auto_merge`, which is False exactly when a human is the gate. So a green,
        # reviewed, human-gated PR had precisely two exits: somebody clicking merge on github.com,
        # or fourteen days elapsing. That is the "In review nobody is asked" the card is named for.
        self._gate: dict | None = None
        # How many `adjust` passes this job has already spent. Per JOB, like `_remedied`: every
        # pass is a paid agent run holding the single-slot floor, so an uncapped adjust is a
        # human-driven infinite loop with the 14-day deadline as its only backstop.
        self._adjust_passes = 0
        # How many times a person has asked for the pull request to be READ again (#181). Bounded
        # for the same reason and not the same one: a re-review writes nothing, so it cannot loop
        # the work — but it is a paid model pass holding the single-slot floor, and a button that
        # can be pressed for ever is a bill with no ceiling.
        self._review_passes = 0
        # The job's params (project/issue), stored so _wait_operator can tell the project's
        # tech-lead coordinator which ticket parked on a decision.
        self._params: JobParams | None = None
        # WHAT THE FACTORY'S OWN REVIEW AND GATES CONCLUDED about the attempt in hand (#121).
        #
        # It lived only in the RunResult, which is readable exactly once the workflow has FINISHED
        # — and the moment somebody most needs it is the one state where it never has: parked at
        # the merge gate, pull request open, a person deciding whether to land it. Asked "pode
        # fazer o merge", the tech-lead answered that the PR was "esperando revisão humana" while
        # this platform's own reviewer had already read the whole diff and scored it.
        #
        # DISPLAY-ONLY AND REPLAY-SAFE, for the reason `_merge_wait` states one field up: no
        # signal acts on it and a query issues no command, so an in-flight job simply repopulates
        # it as the worker replays the code that fills it.
        self._verdict: dict | None = None
        # WHERE A PERSON IS SENT to confirm this change, once the promotion has read the client's
        # manifest in the box (#122). Display-only and replay-safe, like `_merge_wait`.
        self._look: dict | None = None

    @workflow.signal
    async def advise_decision(self, advice: dict) -> None:
        """The tech-lead coordinator's humanized take on the decision this job is parked on —
        attach it so every channel shows the senior engineer's briefing beside the raw options.
        Ignored if the job isn't currently parked on a decision (a stale/replayed signal)."""
        if self._paused and self._paused.get("decision"):
            self._paused["decision"]["advice"] = advice

    @workflow.signal
    async def act_on_impediment(self, action: str, choice: str = "") -> None:
        """The operator's (or a bot's — same API) action on a job the floor is holding: 'resume'
        (re-run the fixed ticket / retry now) or 'skip' (free the floor, leave it for the owner).
        `choice` is the DecisionRequest option key picked when the park carried options (a planner
        blocker etc.) — round-tripped into the resumed run so the agent proceeds with that choice
        instead of re-asking. Only honored while actually parked — a premature or replayed signal
        is dropped (M6), so it can never auto-fire the instant a park begins."""
        if self._paused is None:
            return
        if action in ("resume", "skip"):
            self._choice = choice or None
            self._action = action

    @workflow.signal
    async def human_merge_gate(self, answer: str, instruction: str = "", by: str = "") -> None:
        """The human's answer to a PR waiting on them (#68): 'merge' | 'adjust' | 'discard' |
        'review' (#181).

        `adjust` carries FREE TEXT — the product owner's decision. It is deliberately NOT a
        `DecisionRequest` option key: a key is matched against a fixed list at both consumption
        sites and anything unmatched is silently dropped, so free text would ARRIVE intact and
        then vanish. That is the answer-shape failure this codebase has a name for; a signal
        parameter can say what an option key cannot.

        DROPPED WHEN THERE IS NO GATE OPEN, exactly as `act_on_impediment` drops a premature or
        replayed signal — so a stale answer replayed from history can never fire the instant a
        gate opens, and an answer to a PR that already merged does nothing rather than something
        surprising."""
        if self._merge_wait is None:
            return
        if answer in ("merge", "adjust", "discard", "review"):
            self._gate = {"answer": answer, "instruction": instruction, "by": by}

    @workflow.query
    def awaiting_action(self) -> dict | None:
        """What the floor is currently held on — {kind: 'impediment'|'rate_limit', state, note}
        — or None if the job is progressing normally. The panel reads this to show the ⏸ reason
        and the Resume/Skip controls where the 'Scan TO-DO' button lives."""
        return self._paused

    @workflow.query
    def awaiting_merge(self) -> dict | None:
        """While the job is parked in the merge watch: {pr_url, auto}. auto=False means the
        merge is a HUMAN's call (review requested / suppression handed over) — the panel must
        show 'PR ready — waiting for YOUR merge' with the link, never a silent 'starting…'."""
        return self._merge_wait

    @workflow.query
    def where_to_look(self) -> dict | None:
        """The stage a person is asked to confirm and the address they open — or None (#122).

        `{"stage": "qa", "url": "https://qa.example.com"}`, with `url` EMPTY when the project
        declares a stage worth confirming and no address for it.

        WHY A QUERY, AND WHY THE WORKER CANNOT JUST LOOK IT UP: the address is declared in the
        client's `.openfactory/project.yaml`, which exists in the BOX that ran the promotion and
        nowhere near the worker. It travels back on the RunResult; this exposes it while the job
        is still parked at the production gate, which is exactly when somebody is being asked.

        Replay-safe for the reason `verdict` states one field down: a query issues no command."""
        return self._look

    @workflow.query
    def verdict(self) -> dict | None:
        """What THIS platform's own review and gates concluded about the attempt in hand — or
        None before there is an attempt to report on (#121).

        `{decision, score, summary, findings: [{severity, description, file}], gates: [{name,
        passed, advisory}], suppressions: [kinds]}`.

        WHY A QUERY AND NOT THE RESULT. The RunResult carries all of this and is readable only
        after the workflow closes. A job sitting at the merge gate has not closed — that is what
        the gate IS — so on the one screen where somebody is deciding whether to land a pull
        request, the factory's own reading of that pull request was structurally unavailable. The
        tech-lead then told the pilot it was "waiting for human review", which was a guess.

        ADDING THIS IS REPLAY-SAFE, and the distinction is worth stating because this file gets it
        wrong in the expensive direction elsewhere: a query handler issues no command, so it never
        enters history and cannot diverge one. `workflow.patched` guards a new COMMAND — an
        activity, a timer, a signal out — and three of them in this file carry that gate for good
        reason. A query is the other kind of change entirely.
        """
        return self._verdict

    def _reviewed_again(self, result: RunResult) -> bool:
        """A repair pass came back with its own reading of what it pushed — publish it (#155).

        THE STALE MARKER IS THE FALLBACK, NOT THE ANSWER. #153 taught the verdict to declare itself
        out of date, which stopped the platform asserting something it could not support and left
        the person at the merge gate with no reading at all — and no way to ask for one, since
        nothing re-runs the reviewer on demand. A pass that rewrites a reviewed diff now reviews
        what it wrote, because it has the checkout in hand and nobody else does.

        Returns whether a verdict was published, so the caller knows whether to mark the old one
        stale instead. A pass that could not review (`review_mode: off`, a deployment with no
        reviewer) falls back to the honest marker rather than to silence.
        """
        if getattr(result, "review", None) is None:
            return False
        self._remember_verdict(result)
        # THE GATES DID NOT COME WITH IT, AND SILENCE WOULD BE THE OLD MISTAKE. A repair pass runs
        # one agent and pushes; it does not re-run the sandbox gates, so the fresh verdict carries
        # `gates: []` — which renders as nothing, and "nothing" is how a reader concludes there
        # were none. The previous run's gates are not carried forward either: they judged the diff
        # this pass has just rewritten, which is the whole reason this method exists.
        if self._verdict is not None:
            self._verdict = {**self._verdict,
                             "gates_note": "the forge's own CI is the live check"}
        return True

    def _the_reviewed_code_is_gone(self, why: str) -> None:
        """The diff the reviewer read has been rewritten since (#153).

        MEASURED ON THE PILOT. The review rejected #101 at 16:45 for one high finding: the ticket's
        deliverable was not reachable from stored data. Two repair passes then rewrote the pull
        request — the second adding exactly the migration that finding asked for — and at 18:09 the
        tech-lead, asked whether to merge, quoted the 16:45 verdict back and recommended DISCARDING
        the work that had fixed it. Every word it said was in the store; none of it was still true.

        A verdict belongs to the code it read. This platform's rule everywhere else is that an
        answer it can no longer support becomes UNREAD rather than stays confident, and a review is
        not exempt: nothing here re-runs the reviewer, so the honest move is to stop asserting.

        A FIELD, not a command — replay-safe for the reason `verdict` states two methods up.
        """
        if self._verdict:
            self._verdict = {**self._verdict, "stale": why}

    def _the_reviewed_code_is_still_here(self, result: RunResult) -> None:
        """The pass ended and the pull request is byte-identical to the one the reviewer read
        (#179) — so the marker raised on the way in comes back down.

        MEASURED ON THE PILOT. An adjust pass on podbeam #107 came back having changed nothing
        (`compare` reported 0 files, behind by 0) and the gate answered `Review out of date`. The
        REJECTED verdict — whose one finding named the exact stale migration the person was
        standing there to decide about — was replaced by "the diff was rewritten after the
        reviewer read it", about a rewrite that rewrote nothing. `Review out of date` is the right
        answer to the diff moving under the reviewer; the test behind it asked whether a pass had
        RUN, which is a different question with the same shape.

        The marker still goes up BEFORE the pass and that stays deliberate (#155): a worker dying
        mid-pass must not leave a confident reading of code that may already be gone. This is the
        other half — the pass came back, and it can say what it did.

        ONLY A MEASURED `False` CLEARS IT. `None` is "git could not be asked", and an unknown
        keeps the marker, because the expensive direction is presenting a rejected verdict as
        current about code it never saw.

        A FIELD, not a command — replay-safe for the reason `verdict` states four methods up.
        """
        if self._verdict and result.code_changed is False:
            self._verdict = {k: v for k, v in self._verdict.items() if k != "stale"}

    def _remember_verdict(self, result: RunResult) -> None:
        """Keep the reviewer's reading and the gate results where a query can reach them.

        TRIMMED HERE, not by the reader. A query response crosses the wire on every panel refresh
        that asks for it, and a reviewer's `summary` plus a dozen findings is prose measured in
        kilobytes; the caller that wants all of it reads the closed job's result, which has always
        carried the whole thing."""
        review = getattr(result, "review", None)
        gates = [{"name": v.name, "passed": bool(v.passed), "advisory": bool(v.advisory)}
                 for v in (result.validations or [])]
        # SUPPRESSIONS TRAVEL AS THEIR KINDS. They are the single commonest reason a green PR is
        # handed to a person (`_why` says so in as many words), so a merge gate that did not
        # mention them would be answering the question with the one fact left out.
        kinds = sorted({str(k) for k in (result.added_suppressions or [])})
        if review is None and not gates and not kinds:
            return  # nothing was measured — say nothing rather than an empty verdict
        self._verdict = {
            "decision": getattr(review, "decision", "") or "",
            "score": getattr(review, "score", None),
            "summary": (getattr(review, "summary", "") or "")[:600],
            "findings": [{"severity": f.severity, "description": (f.description or "")[:300],
                          "file": f.file or ""}
                         for f in (getattr(review, "findings", None) or [])[:8]],
            "gates": gates,
            "suppressions": kinds,
            # WHAT THE REVIEWER SAID ABOUT EACH CRITERION (#184). This projection is hand-listed,
            # and the field was simply never added to it — so the map reached the tech-lead's
            # channel, which reads the whole `ReviewResult`, and died at the merge gate, which
            # reads this query. #184 taught the renderer to show it and the data never arrived:
            # the fix worked on one surface and was invisible on the one where somebody decides.
            #
            # TRIMMED LIKE ITS NEIGHBOURS, for the reason the docstring above gives — this crosses
            # the wire on every panel refresh. The criterion text is what identifies it to a
            # reader; the evidence is prose and belongs to the closed job's result.
            "acceptance": [{"criterion": (c.criterion or "")[:200], "status": c.status}
                           for c in (getattr(review, "acceptance", None) or [])[:12]],
        }

    async def _flag_review_findings(self, params: JobParams, result: RunResult) -> None:
        """Something just merged. If the independent review REJECTED it or raised anything
        critical, say so to a person — and open a loop so it is followed up (ADR-0021).

        THE CASE THIS EXISTS FOR. #478 merged on 2026-07-27 with a review that rejected it: score
        38, a critical finding stating the entire deliverable rested on a decision nobody had made.
        Advisory review is deliberate (ADR-0014) and merging anyway is the design. Telling NOBODY
        is not — that finding reached no channel, no comment and no person, and the only reason it
        was ever seen is that somebody happened to read a workflow result by hand.

        The merge is never blocked here. Review stays advisory; what changes is that its worst
        output stops evaporating."""
        # VERSIONING: a new command on a path in-flight jobs already replay (see the note in
        # _coord_say). Without the gate, a replaying workflow would emit a say/activity its history
        # does not contain and diverge — TMPRL1100, which this codebase has hit before.
        if not workflow.patched("flag-review-findings"):
            return
        review = getattr(result, "review", None)
        if review is None:
            return
        critical = [f for f in (review.findings or [])
                    if str(getattr(f, "severity", "")).lower() == "critical"]
        if review.decision != "rejected" and not critical:
            return

        detail = critical[0].description if critical else (review.summary or "")
        what = tl_voice.say(
            tl_voice.NARRATION,
            "review.rejected" if review.decision == "rejected" else "review.critical",
            params.language)
        await self._coord_say(
            tl_voice.say(tl_voice.NARRATION, "review.flag", params.language,
                         issue=params.issue, what=what, score=review.score,
                         detail=detail[:400]),
            "review_finding")
        try:
            await workflow.execute_activity(
                open_review_loop,
                ReviewLoopInput(project=params.project, issue=params.issue,
                                decision=review.decision, score=review.score,
                                detail=detail[:400], pr_url=result.pr_url or ""),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=_RETRY,
            )
        except Exception as exc:  # noqa: BLE001 — the person was already told; the loop is extra
            workflow.logger.warning(
                "#%s: could not record the review finding for follow-up (%s) — it was announced "
                "once and will not be chased", params.issue, exc)

    async def _coord_say(self, text: str, kind: str) -> None:
        """Have the project's coordinator NARRATE a relevant lifecycle moment (pickup / merge) —
        a panel toast now, a Slack/PO message later (same API). Best-effort, never blocks."""
        # VERSIONING: this narration was added while jobs were already in flight. An in-flight
        # workflow replaying its OLD history (no say command) must NOT emit one now, or it
        # diverges (nondeterminism). patched() returns False during that replay → skip; new
        # executions (and the live tail of an in-flight job, e.g. its own merge) get True → narrate.
        if not workflow.patched("coordinator-narration"):
            return
        if not self._params:
            return
        try:
            await workflow.execute_activity(
                notify_coordinator_say,
                CoordinatorSayInput(project=self._params.project, text=text, kind=kind),
                start_to_close_timeout=timedelta(minutes=1), retry_policy=_ONCE)
        except Exception:  # noqa: BLE001 — a job must not fail because a channel did
            # Logged rather than swallowed: this is how a park, a pickup or a merge goes unsaid,
            # and silence here is indistinguishable from nothing having happened.
            workflow.logger.warning("could not narrate %r for #%s", kind, self._params.issue)

    @workflow.signal
    async def approve_prod(self, version: str, approver: str, comment: str = "") -> None:
        """The panel's authenticated prod approval (D-12), delivered as a signal. Only
        honored while the workflow is actually parked at the approval gate — a premature
        or replayed signal is dropped, so it can never bypass the human-in-the-loop or
        auto-fire the instant the gate is reached (M6)."""
        if not self._awaiting_approval:
            return
        self._approval = {"version": version, "approver": approver, "comment": comment}

    @workflow.query
    def awaiting_approval(self) -> bool:
        """Whether the workflow is parked at the prod-approval gate — the panel checks
        this before sending an approval, so a signal is never silently dropped (M6)."""
        return self._awaiting_approval

    async def _cleanup(self, params: JobParams, *, shield: bool) -> None:
        """Best-effort: stop any lingering Fargate task when the job ends abnormally,
        so nothing is left orphaned. Shielded from cancellation when the workflow itself
        is being cancelled, so the stop still runs."""
        # Asks whether the box is REMOTE, not whether it is one particular provider. A local box
        # dies with the process that owns it; a remote one keeps costing money until told to stop.
        if not params.traits().remote:
            return
        call = workflow.execute_activity(
            stop_job,
            RunJobInput(project=params.project, issue=params.issue, sandbox=params.sandbox),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=_RETRY,
        )
        try:
            await (asyncio.shield(call) if shield else call)
        except Exception:  # noqa: BLE001 — never mask the original outcome
            # This one COSTS MONEY when it fails: a cleanup that did not run leaves a Fargate task
            # alive, billing, with nothing watching it. Best-effort is right; silent is not.
            workflow.logger.warning(
                "CLEANUP FAILED for #%s — a sandbox task may still be running and billing",
                params.issue)

    async def _run_job_once(
        self, params: JobParams, resume_handle: str | None = None, attempt: int = 0,
        spent_turns: int = 0, decision: str = "",
    ) -> RunResult:
        result = await workflow.execute_activity(
            run_job,
            RunJobInput(
                project=params.project,
                issue=params.issue,
                sandbox=params.sandbox,
                image=params.image,
                review=params.review,
                resume_handle=resume_handle,  # C2: set only on a resume after a rate-limit pause
                attempt=attempt,  # discriminates loop iterations for launcher idempotency
                spent_turns=spent_turns,  # the ticket-wide effort budget's running total (D4)
                decision=decision,  # a resolved human choice injected into the resumed agent
            ),
            # strictly MORE than the agent's own wall, so the wall fires first and the
            # stop arrives as a diagnosis rather than a silent cancel — see timeouts.py
            start_to_close_timeout=timedelta(seconds=ACTIVITY_CEILING),
            # the activity heartbeats every ~30s; if a worker dies mid-job, Temporal
            # reschedules after this window instead of waiting out the ceiling.
            heartbeat_timeout=timedelta(seconds=120),
            # Retry only a box that RE-ATTACHES to work already in flight. For one that does
            # not, a retry costs a second agent pass and duplicates every comment the first wrote —
            # which is a property of the box, not of one provider's name (C-10).
            retry_policy=_RETRY_REATTACHING if params.traits().idempotent else _ONCE,
        )
        # COST TELEMETRY (observability.metrics → the panel's cost dashboard): persist this
        # attempt's per-invocation spend (by model/harness/role) + a summary. Every run_job
        # attempt flows through here, so resumes/retries each record their real spend. New
        # command → patched() so an in-flight job replaying pre-fix history stays deterministic;
        # best-effort, never blocks the job (the activity also swallows its own write errors).
        if workflow.patched("record-job-metrics") and (
                result.agent_runs or result.total_cost_usd is not None):
            try:
                wall = (workflow.now() - workflow.info().start_time).total_seconds()
                await workflow.execute_activity(
                    record_job_metrics,
                    JobMetricsInput(
                        project=params.project, issue=params.issue,
                        ts=workflow.now().isoformat(),
                        state=getattr(result.state, "value", str(result.state)),
                        title=getattr(self, "_title", ""),
                        wall_s=round(wall, 1),
                        total_cost_usd=result.total_cost_usd,
                        pr_url=result.pr_url or "",
                        knowledge=result.knowledge,
                        agent_runs=[m.model_dump() for m in result.agent_runs],
                    ),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_ONCE,
                )
            except Exception:  # noqa: BLE001 — telemetry is additive; never fail the job
                workflow.logger.info("metrics record skipped for %s#%s",
                                     params.project, params.issue)
        return result

    async def _wait_operator(
        self, kind: str, result: RunResult, timeout: timedelta, default: str
    ) -> tuple[str, str | None]:
        """Park the job — hold the floor, burn no compute — exposing the reason (and, when the
        stage asked a question, its OPTIONS) to every channel via `awaiting_action`, and return
        (decision, choice). On timeout return `default`: a rate-limit pause's timeout is the
        backoff (default='resume', auto-retry once the limit clears); an impediment's is the
        deadline (default='skip', a forgotten block eventually frees the floor). A resume/skip
        signal wakes it immediately — the operator/bot can act without waiting out the timer.
        NOTE: a park carrying a DecisionRequest passes a very long timeout from the caller, so it
        HOLDS until answered (owner: decisions are always human, never a timeout-default)."""
        # WHEN IT ACTUALLY WAKES, from the timer that actually runs it (#140). Every reader was
        # left guessing from `retry_at` — a vendor string that `_pause_backoff` a few lines below
        # DELIBERATELY REFUSES to obey, because formats vary and clocks skew. So the panel could
        # say "paused" and never "until when", and no surface could tell a 30-minute backoff from
        # a job nobody will ever resume. Any screen promoting a park to "needs a human" off
        # `retry_at` would fire up to 100 minutes before this workflow intended to resume by
        # itself — the panel and the engine disagreeing about the same fact.
        #
        # `workflow.now()` is replay-deterministic and neither line issues a command, so an
        # in-flight job replays unchanged and this needs no `workflow.patched()`.
        parked_at = workflow.now()
        self._paused = {"kind": kind, "state": result.state.value, "note": result.note or "",
                        "retry_at": getattr(result, "retry_at", None),
                        "parked_at": parked_at.isoformat(),
                        # A DECISION PARK PASSES TEN YEARS (see the caller) because a decision is
                        # always human and must never time out. Rendering that as a date would be
                        # a screen inventing a deadline nobody set, so a horizon this far out is
                        # reported as no deadline at all and the reader says "until answered".
                        "wakes_at": ((parked_at + timeout).isoformat()
                                     if timeout <= _HELD_UNTIL_ANSWERED else None),
                        # Carried so the tech-lead's ROUNDS see the same number the workflow has:
                        # they read this payload and nothing else, so without it the count exists
                        # on one side of the query and only as prose on the other (#124).
                        "attempts_spent": int(getattr(result, "attempts_spent", 0) or 0),
                        # the options (if any) so panel/Slack/Telegram/curl can all present them
                        "decision": result.decision.model_dump() if result.decision else None}
        self._action = None
        self._choice = None
        # A real decision → hand it to the project's ALWAYS-ALIVE tech-lead coordinator for a
        # humanized take (v0: advisory; it signals its briefing back via advise_decision).
        if result.decision and self._params:
            try:
                await workflow.execute_activity(
                    notify_coordinator,
                    CoordinatorItem(
                        project=self._params.project, issue=self._params.issue,
                        job_id=workflow.info().workflow_id, kind=result.decision.stage,
                        question=result.decision.question, context=result.decision.context,
                        options=[o.model_dump() for o in result.decision.options],
                        note=result.note or ""),
                    start_to_close_timeout=timedelta(minutes=1), retry_policy=_ONCE)
            except Exception:  # noqa: BLE001 — advice is additive; never block the park
                workflow.logger.warning(
                    "coordinator advice failed for #%s — the park holds without it",
                    self._params.issue if self._params else "?")
        answered = False
        try:
            await workflow.wait_condition(lambda: self._action is not None, timeout=timeout)
            act = self._action or default
            answered = self._action is not None
        except TimeoutError:
            # Not a failure: the timeout IS the mechanism — a rate-limit backoff elapsing means
            # "resume", an impediment deadline elapsing means "skip".
            #
            # AND IT IS RETURNED, NOT ONLY LOGGED. This branch already claimed the distinction was
            # "recorded so a job that took a default can be told apart from one somebody
            # answered" — in a log line, while the RETURN VALUE said the identical thing either
            # way. So the first version of the skip record reported an elapsed deadline as a
            # person's decision, in a comment on the client's ticket, under a test of mine
            # asserting it did not (2026-08-16). Can the answer shape say it? It could not.
            workflow.logger.info("#%s took the default %r after waiting on %s",
                                 self._params.issue if self._params else "?", default, kind)
            act = default
        choice = self._choice
        self._paused = None
        return act, choice, answered

    @staticmethod
    def _pause_backoff(resumes: int, retry_at: str | None = None) -> timedelta:
        """How long to park before the NEXT resume of a rate-limited job. It GROWS with the
        number of consecutive auto-resumes (30→60→90→120…, capped at _PAUSE_BACKOFF_MAX) so a
        pool-wide usage exhaustion isn't hammered every 30 min — each blind resume re-launches
        the agent and re-burns the very tokens it's waiting on (partner-reported re-burn). We
        deliberately DON'T parse retry_at into a precise sleep: the string is adapter/vendor
        telemetry (formats vary, clocks skew) and over-trusting it risks resuming too early into
        a still-closed window. It's surfaced on the panel; the growing backoff paces the retry."""
        return min(_PAUSE_BACKOFF * (resumes + 1), _PAUSE_BACKOFF_MAX)

    @workflow.run
    async def run(self, params: JobParams) -> RunResult:
        # The cleanup compensation wraps the WHOLE lifecycle (job AND promotion tasks) —
        # a cancel during a staging/release Fargate task must stop that task too; a
        # cancelled release left running could tag prod uncontrolled (R1).
        try:
            result = await self._lifecycle(params)
        except asyncio.CancelledError:
            await self._cleanup(params, shield=True)  # workflow cancelled → stop tasks
            await self._journal_outcome(params, JobState.ON_HOLD.value,
                                        "the workflow was cancelled or terminated", shield=True)
            raise
        except Exception as exc:
            await self._cleanup(params, shield=False)  # failed after retries → stop tasks
            await self._journal_outcome(params, JobState.FAILED.value, describe(exc, limit=200))
            raise
        await self._journal_outcome(params, result.state.value, result.note or "")
        return result

    async def _journal_outcome(self, params: JobParams, state: str, note: str, *,
                               shield: bool = False) -> None:
        """Record how this job ENDED in the journal on disk — the record that outlives the engine.

        THE ONE EXIT, AND THAT IS THE WHOLE POINT (pilot, 2026-08-17). The journal is written by
        the in-box orchestrator; the terminal state is decided out here, after the box is gone. So
        `#89`'s durable record read … reviewing → `review: rejected` and then STOPPED: its
        `open_pr` had raised (a branch with zero commits, which GitHub refuses), this workflow
        caught it and parked the job, and the file that outlives Temporal's 24-hour retention
        never learned what became of it. A day later the panel called a parked job `reviewing` and
        told the operator *nothing shipped yet*.

        Writing it in each terminal branch instead would be the same rule spread over a dozen
        sites — a crash, the rate-limit ladder giving up, an operator's skip, an answered merge
        gate, a chain finishing at its last stage. This platform has shipped "one branch forgot"
        seventeen times; the fix is a seam.

        VERSIONED, because it is a new COMMAND on a path in-flight jobs already replay: without
        the gate every running workflow would emit an activity its history does not contain and
        diverge (TMPRL1100), which this codebase has hit before.

        SHIELDED ON CANCELLATION, like `_cleanup` above and for the same reason: a job an operator
        stopped is exactly the one whose record somebody will go looking for.

        BEST-EFFORT. The job has already ended and its outcome already reached the board and the
        engine; failing here must not change what happened, but it is logged rather than swallowed
        — a journal that quietly stops recording outcomes looks exactly like a quiet floor."""
        if not workflow.patched("journal-the-outcome"):
            return
        call = workflow.execute_activity(
            record_outcome,
            HoldSyncInput(project=params.project, issue=params.issue, state=state,
                          note=(note or "")[:400]),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=_RETRY,
        )
        try:
            await (asyncio.shield(call) if shield else call)
        except Exception:  # noqa: BLE001 — never mask the outcome this exists to record
            workflow.logger.warning(
                "#%s ended as %s and its journal does not say so — after the engine's retention "
                "window, nothing will", params.issue, state)

    async def _pr_status(self, params: JobParams, pr_url: str) -> str:
        """Poll the PR's lifecycle state ("merged" | "closed" | "open"), DEGRADING a
        transient GitHub failure to "open" (keep waiting) rather than crashing the durable
        wait. A brief GitHub outage during a days-long merge watch must never fail an
        otherwise-healthy job — mirror check_ci_status's degrade-don't-crash posture (H1)."""
        try:
            return await workflow.execute_activity(
                check_pr_status,
                MergeCheckInput(project=params.project, pr_url=pr_url),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=_RETRY,  # read-only, safe to retry
            )
        except Exception as exc:  # noqa: BLE001 — degrade, never crash an otherwise-healthy job
            # "open" keeps the job waiting, which is safe; but a PR that MERGED and cannot be read
            # waits until the timeout, so this must be visible rather than inferred from a slow job.
            workflow.logger.warning("#%s: PR status unreadable (%s) — assuming still open",
                                    params.issue, exc)
            return "open"

    async def _wait_for_merge(self, params: JobParams, pr_url: str) -> str:
        """Durably wait until the PR resolves — returns "merged", "closed" (a human closed it
        without merging), or "timeout" (merge_deadline_days elapsed). Auto-merge may be armed
        but pending CI; a human may merge days later. The poll widens after the first hour so a
        long wait stays under Temporal's history-event ceiling (C1)."""
        deadline = workflow.now() + timedelta(days=params.merge_deadline_days)
        start = workflow.now()
        while workflow.now() < deadline:
            status = await self._pr_status(params, pr_url)
            if status in ("merged", "closed"):
                return status
            elapsed = workflow.now() - start
            await workflow.sleep(_CI_POLL if elapsed < _CI_FAST_WINDOW else _CI_SLOW_POLL)
        return "timeout"

    async def _decide_merge(
        self, params: JobParams, result: RunResult, kind: str
    ) -> tuple[str, str | None, bool]:
        """Park a stuck merge on a DecisionRequest with EXECUTABLE options and return
        (act, choice, answered-by-a-person) — held until a human/bot answers (no silent
        forever-wait; the factory acts on the choice). kind='behind' (busy-main starvation →
        wait / merge-now / skip) or 'dirty' (conflict → resolve-then-recheck / skip)."""
        n = (result.pr_url or "").rstrip("/").rsplit("/", 1)[-1]
        if kind == "behind":
            dr = DecisionRequest(
                stage="merge",
                question=f"PR #{n} keeps falling behind a busy base — how should it land?",
                context="Other developers keep advancing the base, so auto-merge can't catch up.",
                options=[
                    DecisionOption(key="wait", label="Keep auto-updating & waiting",
                                   consequence="keep rebasing until it lands", recommended=True),
                    DecisionOption(key="merge", label="Merge it now",
                                   consequence="force the merge, bypassing the up-to-date gate"),
                    DecisionOption(key="skip", label="Skip this ticket",
                                   consequence="free the floor; leave the PR for a human")],
                default="wait")
            note = "PR can't auto-merge — it keeps falling behind a busy base"
        else:  # dirty
            dr = DecisionRequest(
                stage="merge",
                question=f"PR #{n} conflicts with the base — how should it proceed?",
                context="A textual merge conflict the machine can't safely auto-resolve.",
                options=[
                    DecisionOption(key="resume", label="I resolved it — re-check",
                                   consequence="re-check mergeability and continue",
                                   recommended=True),
                    DecisionOption(key="skip", label="Skip this ticket",
                                   consequence="free the floor; leave the PR for a human")],
                default="resume")
            note = "PR has a merge conflict with the base"
        parked = RunResult(ticket_id=result.ticket_id, state=JobState.BLOCKED,
                           pr_url=result.pr_url, decision=dr, note=note)
        self._merge_wait = None  # it's a DECISION now, not a passive wait
        # THE SECOND SILENT DECISION (#71, found by the C-34 research and confirmed against
        # ADR-0038's own gap list, which names the merge GATE but not this path). This park
        # bypasses the lifecycle's park block, so it got neither the board move nor the channel
        # alert: a decision visible only to whoever happened to open the inbox, held for up to
        # ten years. The board move and the alert are mirrored here — the diagnosis is NOT,
        # deliberately: this is a question about how a PR should land, and there is nothing for
        # a tech-lead to investigate. New commands → their own patch guard (TMPRL1100).
        if workflow.patched("merge-decision-announces"):
            try:
                await workflow.execute_activity(
                    mark_needs_action,
                    HoldSyncInput(project=params.project, issue=params.issue,
                                  state=parked.state.value, note=note),
                    start_to_close_timeout=timedelta(minutes=2), retry_policy=_ONCE)
            except Exception:  # noqa: BLE001 — the board move is additive; never block the park
                workflow.logger.warning(
                    "board not moved for the merge decision on #%s", params.issue)
            keys = " / ".join(f"*{o.key}*" for o in dr.options)
            await self._coord_say(
                tl_voice.say(tl_voice.NARRATION, "park.decision", params.language,
                             issue=params.issue, question=dr.question, note=note, keys=keys),
                "needs_action")
        return await self._wait_operator("impediment", parked, timedelta(days=3650), "skip")

    async def _ci_merge_loop(self, params: JobParams, result: RunResult) -> RunResult:
        """Watch an open PR until it merges, reacting to CI (ADR-0004) — for BOTH paths:
        - auto-merge: `--auto` (armed by the machine) merges once CI is green; we confirm it.
        - human-review: the merge is a human's call; we just wait for it — but keep the PR
          healthy by repairing a red CI meanwhile.
        Either way a red CI triggers a bounded repair (react, don't block). The workflow stays
        RUNNING until the merge, so the floor is held until the ticket actually lands (ADR-0007)
        — the next ticket builds on a base that includes this one. Only an unfixable CI (after
        the cap) or the merge deadline holds for a human. Durable: a minutes-to-days wait never
        burns a worker or gets lost on a restart."""
        deadline = workflow.now() + timedelta(days=params.merge_deadline_days)
        start = workflow.now()
        pr_url = result.pr_url or ""
        attempts = 0
        pause_resumes = 0
        rebases = 0  # times we've auto-updated a BEHIND PR (bounded by _REBASE_MAX)
        while workflow.now() < deadline:
            status = await self._pr_status(params, pr_url)
            if status == "merged":
                result.state = JobState.MERGED
                return result
            if status == "closed":
                # A human CLOSED the PR without merging (ADR-0007: "until it merges OR is
                # closed"). Stop watching NOW — polling to the merge deadline would freeze the
                # single-slot floor for up to 14 days on a PR that will never land.
                return RunResult(
                    ticket_id=result.ticket_id, state=JobState.ON_HOLD, pr_url=result.pr_url,
                    note="PR was closed without merging — needs a human",
                )
            try:
                ci = await workflow.execute_activity(
                    check_ci_status,
                    MergeCheckInput(project=params.project, pr_url=pr_url),
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=_RETRY,  # read-only
                )
            except Exception as exc:  # noqa: BLE001
                workflow.logger.warning(
                    "#%s: CI status unreadable (%s) — treating as pending. The red-CI REPAIR "
                    "trigger is dormant while this is true; if the App is missing Checks:read, a "
                    "failing build will never be repaired, it will just never be noticed.",
                    params.issue, exc)
                # Can't read CI status (e.g. the bot App lacks Checks:read) — DEGRADE, never
                # crash: treat as pending and lean on the merge check above. The happy path
                # (--auto merges on green → the status check catches it) still completes; only
                # the red-CI *repair* trigger is dormant until CI is readable. (ADR-0004:
                # react/degrade, don't crash — a failed status read must not fail the job.)
                ci = "unknown"
            if ci == "failure":
                if attempts >= _CI_REPAIR_MAX:
                    return RunResult(
                        ticket_id=result.ticket_id, state=JobState.ON_HOLD, pr_url=result.pr_url,
                        note=f"CI still failing after {attempts} repair attempt(s) — needs a human",
                    )
                attempts += 1
                # THE REVIEWER READ THE OLD DIFF (#153) — a repair pass rewrites the pull request,
                # so the verdict stops describing it the moment this activity pushes.
                self._the_reviewed_code_is_gone(
                    f"a CI-repair pass rewrote the pull request (attempt {attempts})")
                rep = await workflow.execute_activity(
                    repair_ci,
                    CiRepairInput(
                        project=params.project, issue=params.issue,
                        pr_url=pr_url, sandbox=params.sandbox, attempt=attempts,
                    ),
                    start_to_close_timeout=timedelta(seconds=ACTIVITY_CEILING),
                    heartbeat_timeout=timedelta(seconds=120),
                    retry_policy=(_RETRY_REATTACHING
                                  if params.traits().idempotent else _ONCE),
                )
                self._reviewed_again(rep)  # the pass's own reading of what it pushed (#155)
                self._the_reviewed_code_is_still_here(rep)  # …or nothing was pushed at all (#179)
                if rep.state == JobState.PAUSED:
                    # The agent hit a usage limit DURING the CI repair. SAME single-line
                    # semantics as the main path (ADR-0010): a VISIBLE park (awaiting_action)
                    # that auto-retries on the backoff, with the operator able to Retry-now or
                    # Skip — never a blind sleep the panel can't see or act on. A pause does
                    # NOT consume a repair attempt.
                    if pause_resumes >= _MAX_PAUSE_RESUMES:
                        return RunResult(
                            ticket_id=result.ticket_id, state=JobState.ON_HOLD,
                            pr_url=result.pr_url,
                            note=f"still rate-limited during CI repair "
                                 f"after {pause_resumes} resumes",
                        )
                    act, _, by_a_person = await self._wait_operator(
                        "rate_limit", rep,
                        self._pause_backoff(pause_resumes, rep.retry_at), "resume")
                    if act == "skip":
                        self._skipped = True  # completes directly — no second park outside
                        return await self._skip(
                            params, result,
                            "rate-limited during CI repair — skipped by operator",
                            by_a_person=by_a_person)
                    pause_resumes += 1
                    attempts -= 1
                    continue
                # the repair couldn't proceed (agent auth stopped / needs refinement) → hand back
                if rep.state in (JobState.ON_HOLD, JobState.NEEDS_REFINEMENT):
                    return rep
                await workflow.sleep(_CI_POLL)  # let the re-pushed CI start before re-checking
            else:  # CI isn't failing — but the PR may still be unable to MERGE; keep it FRESH
                mstate = await workflow.execute_activity(
                    pr_mergeable_state,
                    MergeCheckInput(project=params.project, pr_url=pr_url),
                    start_to_close_timeout=timedelta(minutes=2), retry_policy=_RETRY,
                )
                if mstate == "behind":
                    # Busy-main starvation: other developers advanced the base, so auto-merge
                    # stalls. Bring the PR up to date so it can land — SELF-HEAL, bounded. Past
                    # _REBASE_MAX we stop the silent loop and ASK a human with EXECUTABLE options
                    # (owner: no forever-wait; the factory acts on the choice), then keep going.
                    if rebases >= _REBASE_MAX:
                        act, choice, by_a_person = await self._decide_merge(
                            params, result, "behind")
                        if act == "skip" or choice == "skip":
                            return await self._skip(
                                params, result,
                                "PR kept falling behind — skipped by operator",
                                by_a_person=by_a_person)
                        if choice == "merge":  # human chose: force it in now
                            await workflow.execute_activity(
                                force_merge_pr,
                                MergeCheckInput(project=params.project, pr_url=pr_url),
                                start_to_close_timeout=timedelta(minutes=2), retry_policy=_RETRY)
                        rebases = 0  # 'wait' (or after a force-merge attempt) → reset + keep going
                        continue
                    rebases += 1
                    self._merge_wait = {"pr_url": pr_url, "auto": bool(result.auto_merge),
                                        "note": f"behind the base — updating branch ({rebases})"}
                    await workflow.execute_activity(
                        update_pr_branch,
                        MergeCheckInput(project=params.project, pr_url=pr_url),
                        start_to_close_timeout=timedelta(minutes=2), retry_policy=_RETRY,
                    )
                    await workflow.sleep(_CI_POLL)  # let the update re-trigger CI
                elif mstate == "dirty":
                    # A textual conflict with the base — the machine can't safely auto-resolve it,
                    # so ASK a human (resolve-then-recheck / skip) rather than silently hold.
                    act, choice, by_a_person = await self._decide_merge(
                        params, result, "dirty")
                    if act == "skip" or choice == "skip":
                        return await self._skip(
                            params, result,
                            "PR conflicts with the base — skipped by operator",
                            by_a_person=by_a_person)
                    continue  # 'resume' → re-check mergeability (human resolved the conflict)
                elif (mstate in ("clean", "unstable") and result.auto_merge
                      and workflow.patched("merge-self-heal-clean")):
                    # SELF-HEAL — never leave a green, mergeable PR blocked. The PR is mergeable
                    # NOW (every required check passed) and this job is on the machine-merge path,
                    # yet it hasn't landed: `--auto` was never armed or got cleared (e.g. a worker
                    # restart dropped the arming). A tech-lead merges it rather than waiting out the
                    # 14-day merge deadline. A direct admin merge == a plain merge on a clean PR —
                    # nothing to bypass (required checks/up-to-date/reviews are already satisfied,
                    # else the state would be `blocked`/`behind`/`dirty`, not clean/unstable). A
                    # refusal (a race that just merged it, or a rule we genuinely can't bypass)
                    # falls through to the next poll, which sees the merge or reacts to the new
                    # state — bounded either way, never a silent forever-wait.
                    self._merge_wait = {"pr_url": pr_url, "auto": True,
                                        "note": "mergeable but not landing — merging it now"}
                    merged_ok = await workflow.execute_activity(
                        force_merge_pr,
                        MergeCheckInput(project=params.project, pr_url=pr_url),
                        start_to_close_timeout=timedelta(minutes=2), retry_policy=_RETRY)
                    if merged_ok:
                        result.state = JobState.MERGED
                        return result
                    await workflow.sleep(_CI_POLL)  # merge refused → re-poll and react
                else:  # blocked (required check pending) / unknown → give CI + --auto time
                    # WHO IS HOLDING IT PICKS THE SENTENCE (#148) — `auto` is right here in the
                    # same dict, and the note now reads it instead of describing only the
                    # machine's path. The phrasing lives in `merge_wait_note` so the panel, the
                    # inbox card and the tech-lead cannot be given three versions of it.
                    self._merge_wait = {"pr_url": pr_url, "auto": bool(result.auto_merge),
                                        "note": merge_wait_note(bool(result.auto_merge))}
                    elapsed = workflow.now() - start
                    nap = _CI_POLL if elapsed < _CI_FAST_WINDOW else _CI_SLOW_POLL
                    # THE HUMAN CAN NOW ANSWER (#68), and this is the only place they can be
                    # heard — the gate lives inside this loop.
                    #
                    # PATCHED because it is a workflow-BODY change on a loop that has jobs
                    # sitting in it for up to fourteen days: `wait_condition` is a new command,
                    # and a job replaying its pre-fix history must not expect it (TMPRL1100).
                    # Local tests never catch this; the guard is the only thing that does.
                    #
                    # WAIT_CONDITION, NOT SLEEP: the human's answer must be acted on within
                    # seconds, and the poll widens to fifteen minutes after the first hour. A
                    # click followed by a quarter of an hour of "waiting for YOUR merge" reads as
                    # a broken button, which is the same product failure as a gate nobody can
                    # answer. The timeout keeps the CI poll exactly as it was when nobody speaks.
                    #
                    # THE CALL SITE MUST NOT MOVE: for jobs already in this loop, the patch
                    # marker's position in history is part of their replay, and evaluating it
                    # earlier (say, at loop entry) would emit the marker in a different workflow
                    # task than their history recorded (TMPRL1100). The RESULT, though, is state —
                    # published into `_merge_wait` so `answer_merge_gate` can refuse a doomed
                    # answer instead of delivering it. FOUND LIVE (fx-mono#1, 2026-08-04): a
                    # deploy replaced a gate-holding job; its successor replayed pre-patch
                    # history, `patched()` memoized False, and the panel kept offering a gate
                    # whose every answer was accepted, confirmed to the operator — "sent back
                    # for one pass" — and then read by no code, forever. A silent forever-wait
                    # wearing a working button.
                    gate_live = workflow.patched("human-merge-gate")
                    self._merge_wait["gate_live"] = gate_live
                    # AND WHETHER THE FOURTH ANSWER IS REAL (#181). No surface may offer a
                    # re-review where nothing can review — "never send somebody to ask for
                    # something this platform cannot do" is the platform's own rule about its
                    # tech-lead and it binds the buttons too. Only the workflow holds all three
                    # halves: this job ran with review on, a reviewer demonstrably spoke, and the
                    # cap is not spent.
                    self._merge_wait["can_review"] = bool(
                        gate_live and not self._re_review_refusal(params))
                    if gate_live:
                        with contextlib.suppress(TimeoutError):
                            await workflow.wait_condition(lambda: self._gate is not None,
                                                          timeout=nap)
                        answered = await self._answer_merge_gate(params, result, pr_url)
                        if answered is not None:
                            return answered
                        continue
                    await workflow.sleep(nap)
        return RunResult(
            ticket_id=result.ticket_id, state=JobState.ON_HOLD, pr_url=result.pr_url,
            note=f"PR not merged within {params.merge_deadline_days}d (CI watch)",
        )

    #: How many `adjust` passes one job may spend. Mirrors `_CI_REPAIR_MAX` and for the same
    #: reason: each pass is a paid agent run holding the single-slot floor, so an uncapped one is
    #: a human-driven infinite loop with only the 14-day deadline underneath it.
    _ADJUST_MAX = 2

    #: How many times one job may be READ again on demand (#181). Higher than `_ADJUST_MAX`
    #: because a re-review writes nothing and cannot loop the work — and bounded all the same,
    #: because it is a paid model pass and an unbounded button is a bill with no ceiling.
    _REVIEW_MAX = 3

    def _re_review_refusal(self, params: JobParams) -> str:
        """Why this pull request cannot be read again — and `""` when it can (#181).

        ONE DEFINITION, IN TWO REGISTERS. The gate publishes the answer as a flag, so no surface
        offers a button that would be refused; the handler says it in words when somebody asked
        anyway — through the API, from a page that was open while the cap ran out, or by typing
        the gesture into a channel. Two copies of this test is exactly how a surface and its
        engine come to disagree about one job.

        NEVER SEND SOMEBODY TO ASK FOR SOMETHING THIS PLATFORM CANNOT DO is the rule this serves,
        and it is the platform's own rule about its tech-lead. It binds the buttons too.
        """
        if not params.review:
            return "this job ran with review turned off — there is no reviewer to ask"
        if not (self._verdict or {}).get("decision"):
            return "nothing has reviewed this pull request yet, so there is nothing to re-read"
        if self._review_passes >= self._REVIEW_MAX:
            return f"{self._REVIEW_MAX} re-reviews already spent on this pull request"
        return ""

    async def _answer_merge_gate(self, params: JobParams, result: RunResult,
                                 pr_url: str) -> RunResult | None:
        """Act on the human's answer. `None` means carry on watching the PR (#68).

        THE ANSWER IS CONSUMED FIRST, whatever happens next. A gate left set would re-fire on the
        next iteration and merge twice, or spend a second adjust pass nobody asked for."""
        gate, self._gate = self._gate, None
        if not gate:
            return None
        answer, who = gate.get("answer"), gate.get("by") or "somebody"

        if answer == "merge":
            # `merge_pr`, NOT `force_merge_pr`. The self-heal branch above uses the admin override
            # deliberately — it fires only on a PR that is ALREADY clean, so there is nothing to
            # bypass. Here a human is answering a gate that may still be blocked, and
            # `--admin` would ride straight through the client's own branch protection: their
            # required reviews, their required checks. The platform must not be the way somebody
            # gets around rules their own organisation set.
            self._merge_wait = {"pr_url": pr_url, "auto": False,
                                "note": f"{who} approved the merge — landing it"}
            merged_ok = await workflow.execute_activity(
                merge_pr_now,
                MergeCheckInput(project=params.project, pr_url=pr_url),
                start_to_close_timeout=timedelta(minutes=2), retry_policy=_RETRY)
            if merged_ok:
                result.state = JobState.MERGED
                return result
            # REFUSED IS NOT SILENCE. `merge_pr` reports failure by returning False, so without
            # this the human clicks Merge, nothing lands, and the panel goes back to saying
            # "waiting for YOUR merge" — a button that does nothing quietly, which is the exact
            # failure this card exists to end. Park it as a question instead.
            return RunResult(
                ticket_id=result.ticket_id, state=JobState.ON_HOLD, pr_url=pr_url,
                note=(f"{who} approved the merge but the forge refused it — most likely branch "
                      f"protection this App cannot satisfy (a required review, a required check). "
                      f"Merge it on the forge, or fix the rule and answer again."),
            )

        if answer == "discard":
            self._merge_wait = None
            # `_skipped` is the existing field for "the operator gave up inside the merge loop",
            # so the outer impediment check completes directly instead of parking the same
            # give-up a second time.
            self._skipped = True
            await workflow.execute_activity(
                close_pr,
                MergeCheckInput(project=params.project, pr_url=pr_url),
                start_to_close_timeout=timedelta(minutes=2), retry_policy=_RETRY)
            return RunResult(
                ticket_id=result.ticket_id, state=JobState.ON_HOLD, pr_url=pr_url,
                note=f"PR closed without merging by {who} — the branch is untouched",
            )

        if answer == "review":
            # THE CLOSING HALF OF THE LOOP (#181). `review rejects → adjust fixes it → ??? →
            # merge`: until now the third step did not exist, so the operator could either merge
            # on their own reading of the diff — the work an independent review exists to remove —
            # or merge a change whose last recorded verdict rejected code that is gone.
            refusal = self._re_review_refusal(params)
            if refusal:
                # THE SAME TEST THE BUTTON WAS PUBLISHED FROM, said in words. A person can arrive
                # here without a button — the API, a sentence in a channel, a page that was open
                # while the cap ran out — and a refusal computed a second time is how a surface
                # and its engine come to disagree about one job (#164).
                self._merge_wait = {"pr_url": pr_url, "auto": False, "can_review": False,
                                    "note": refusal}
                return None
            self._review_passes += 1
            # THE MACHINE HOLDS IT WHILE IT READS (#151). Nothing is being rewritten, but the
            # answer the person is waiting for is not in yet, and a gate that still offers Merge
            # invites them to decide on the verdict they just asked to replace.
            self._merge_wait = {"pr_url": pr_url, "auto": False, "working": True,
                                "can_review": False,
                                "note": f"{who} asked for a fresh review of this pull request"}
            read = await workflow.execute_activity(
                review_pr,
                ReviewPassInput(project=params.project, issue=params.issue, pr_url=pr_url,
                                sandbox=params.sandbox, attempt=self._review_passes),
                start_to_close_timeout=timedelta(seconds=ACTIVITY_CEILING),
                heartbeat_timeout=timedelta(seconds=120),
                retry_policy=(_RETRY_REATTACHING
                              if params.traits().idempotent else _ONCE),
            )
            # IT REPLACES THE STALE VERDICT, it does not sit beside it: two verdicts about two
            # diffs on one screen is the ambiguity #149 was opened to kill. `_reviewed_again` is
            # the one place that swaps a verdict, so the swap cannot drift between the paths.
            if not self._reviewed_again(read):
                # A PRESSED BUTTON THAT CHANGED NOTHING MUST SAY SO. `can_review` is meant to keep
                # this unreachable; if a box answers without a verdict anyway, the person hears it
                # rather than watching the same stale reading come back wearing a fresh minute.
                self._merge_wait = {
                    "pr_url": pr_url, "auto": False, "can_review": False,
                    "note": (read.note or "the re-review came back without a verdict")[:200],
                }
            return None  # nothing was rewritten; the gate re-opens with the reading in hand

        # adjust
        if self._adjust_passes >= self._ADJUST_MAX:
            self._merge_wait = {"pr_url": pr_url, "auto": False,
                                "note": f"{self._ADJUST_MAX} adjust passes already spent"}
            return None
        self._adjust_passes += 1
        # THE MACHINE HOLDS IT NOW (#151). `_merge_wait` is what every surface reads to decide a
        # job is at a gate, and it stayed set through the whole repair pass — so for the two
        # minutes an agent was rewriting the PR, the floor said "Needs you", the inbox offered
        # Merge and Discard, and a click would have landed or closed a PR mid-rewrite. A wait
        # nobody is being asked about is not a question (ADR-0038 D2). `working` is a FIELD, not a
        # command, so an in-flight job replaying pre-fix history stays deterministic.
        self._merge_wait = {"pr_url": pr_url, "auto": False, "working": True,
                            "note": f"{who} asked for a change — one more pass on the same PR"}
        self._the_reviewed_code_is_gone(f"{who} asked for a change and a pass rewrote the pull "
                                        f"request")
        passed = await workflow.execute_activity(
            adjust_pr,
            AdjustInput(project=params.project, issue=params.issue, pr_url=pr_url,
                        sandbox=params.sandbox, attempt=self._adjust_passes,
                        instruction=str(gate.get("instruction") or "")[:_ADJUST_CHARS]),
            start_to_close_timeout=timedelta(seconds=ACTIVITY_CEILING),
            heartbeat_timeout=timedelta(seconds=120),
            retry_policy=(_RETRY_REATTACHING if params.traits().idempotent else _ONCE),
        )
        # AND THE VERDICT CATCHES UP WITH THE CODE (#155). The stale marker above went up before
        # the push, so a worker dying mid-pass leaves no confident reading; this replaces it with
        # the pass's own, when the pass had one to give.
        self._reviewed_again(passed)
        # …AND IF IT PUSHED NOTHING, THE MARKER COMES BACK DOWN (#179). An adjust that could not
        # act on the instruction (#178) is the commonest way to get here having changed nothing,
        # and it must not cost the person the verdict they came to the gate to read.
        self._the_reviewed_code_is_still_here(passed)
        return None  # the pass pushed to the same PR; keep watching, the gate re-opens

    async def _refresh_knowledge(self, params: JobParams) -> None:
        """Post-merge Knowledge Pipeline (§11): reality changed, so regenerate the project's
        module map and publish it (§22 D-1/D-2). Runs here — after the merge, at the very end of
        the job — because the map describes the base branch's NEW state, and because the next
        ticket is the one that benefits.

        Two guards make this safe on a hot floor. `patched()` keeps an in-flight job that is
        replaying pre-fix history deterministic (a new command mid-replay is TMPRL1100). And the
        activity is single-attempt + swallowed: the ticket has ALREADY merged, so nothing about
        refreshing a navigation aid may fail the job or hold the floor (ADR-0007). Worst case the
        map stays one merge behind and the next job runs without it — the fail-safe posture the
        whole layer is built on (§12)."""
        if not workflow.patched("knowledge-pipeline"):
            return
        try:
            outcome = await workflow.execute_activity(
                refresh_knowledge,
                KnowledgeRefreshInput(project=params.project, issue=params.issue),
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=_ONCE,
            )
            workflow.logger.info("knowledge refresh: %s", outcome)
        except Exception:
            workflow.logger.warning("knowledge refresh failed for %s#%s (map stays behind)",
                                    params.project, params.issue)

    async def _skip(self, params: JobParams, result: RunResult, why: str, *,
                    by_a_person: bool) -> RunResult:
        """A person told the factory to stop. ONE ending for all five places they can say it.

        THERE WERE FIVE, AND THE FIRST FIX CAUGHT ONE (pilot, 2026-08-16). An operator can skip at
        the impediment gate, at a rate-limit pause, during CI repair, on a PR that keeps falling
        behind, and on one that conflicts with its base — and every one of them returned
        `ON_HOLD`, the state the job carried BEFORE anybody decided. The panel went on saying
        `on_hold`, the card stayed in *Needs Action*, and no comment recorded that a human had
        acted: *"o status não on_hold e sim skipped, ou seja, o que realmente aconteceu."*

        Patched at the call site rather than here, so an in-flight job replaying pre-fix history
        skips the new command consistently wherever it happens to be parked (TMPRL1100).

        `why` is kept verbatim from each site: it is the only thing that says what the ticket was
        skipped FROM, and the comment is where that has to survive.

        AND `by_a_person` DECIDES WHETHER ANY OF THIS APPLIES. `_wait_operator` returns its
        DEFAULT when the window elapses, and at the impediment gate that default is `"skip"` — so
        the first version of this recorded an expired deadline as somebody's decision, on the
        client's ticket, under a test of mine asserting it did not. Nobody acted there: the job is
        `ON_HOLD` with the reason it was always going to have."""
        if not by_a_person or not workflow.patched("a-skip-is-recorded"):
            return RunResult(ticket_id=result.ticket_id, state=JobState.ON_HOLD,
                             pr_url=result.pr_url, note=why)
        await self._settle(
            params, JobState.SKIPPED,
            f"Skipped from the operator's surface — the factory has stopped working on this and "
            f"the queue is free. Nothing was delivered: the ticket stays open and goes back to "
            f"the backlog. What it was skipped from: {why[:400]}")
        return RunResult(ticket_id=result.ticket_id, state=JobState.SKIPPED,
                         pr_url=result.pr_url, note=why,
                         total_cost_usd=result.total_cost_usd)

    async def _settle(self, params: JobParams, state: JobState, note: str) -> None:
        """Record a job's terminal outcome on the tracker — the column and one comment.

        ONE HELPER, TWO ENDINGS. `_finish_at_the_merge` and the skip above both need exactly this,
        and both exist because the same defect was found twice in two days: a human acts, the floor
        moves, and the board goes on showing what was true before they did. Best-effort by
        construction — the decision has already been taken and nothing about recording it may
        undo it."""
        try:
            await workflow.execute_activity(
                settle_ticket,
                HoldSyncInput(project=params.project, issue=params.issue,
                              state=state.value, note=note),
                start_to_close_timeout=timedelta(minutes=2), retry_policy=_ONCE)
        except Exception:  # noqa: BLE001 — the outcome stands whatever the tracker says
            workflow.logger.warning("could not settle %s#%s as %s — the card may still show what "
                                    "was true before", params.project, params.issue, state.value)

    async def _finish_at_the_merge(self, params: JobParams, result: RunResult) -> None:
        """The merge is the end of the road for this project — say so, on the board and in words.

        THE CARD COULD NOT REACH DONE (pilot, 2026-08-16). `JobState.MERGED` maps to *In review*
        deliberately, because a merged change is still overseen while it deploys; the column past
        it is written by `PromotionRunner`, and the promotion tail runs only when the manifest
        declares `environments:`. A project without them — which is every project this platform's
        own onboarding creates — therefore merged, freed the floor, and left its card in *In
        review* for ever, with the last word on the ticket being "PR ready for review".

        AND SILENCE WAS THE OTHER HALF. The operator asked the right question before merging:
        *"when the merge is done a deploy to staging happens, and I have not seen anywhere that
        picks up the staging domain so somebody can be asked to validate it"*. He was right, and
        nothing said so. The post-merge half of this platform is real — a deploy watch, a
        promotion chain, a production gate, a client asked to try it — and all of it is switched
        on by manifest keys the onboarding never mentions. A factory that quietly does nothing
        looks exactly like a factory whose next step has not arrived yet.

        So the closing comment states what THIS project declared and what follows from it, and
        names the file where that is changed. It is derived from the manifest the run carried, not
        from a template: a project that DOES declare a watch is told what is being watched.

        PATCHED, BEST-EFFORT, AFTER THE MERGE. A job in flight when this shipped must replay
        deterministically (TMPRL1100), and nothing about recording an outcome may fail a ticket
        that has already landed.
        """
        if not workflow.patched("merge-is-the-end-when-nothing-follows"):
            return
        cfg = result.post_merge_deploy
        if cfg:
            note = (
                f"Merged — and this job is done. This project's own `{cfg.workflow}` deploys it; "
                f"the factory is watching that run for up to {cfg.timeout_minutes} minutes and "
                f"will report the {cfg.env} outcome here. Nothing is promoted past it: the "
                f"manifest declares no `environments:`, so there is no chain to walk and no "
                f"approval to ask for.")
        else:
            note = (
                "Merged — and this job is done. This project's manifest declares no "
                "`post_merge_deploy:` and no `environments:`, so nothing here watches a deploy "
                "and nobody will be asked to validate one: whatever your pipeline does after this "
                "merge, the factory is not looking. Declare either of them in "
                "`.openfactory/project.yaml` to change that — see ONBOARDING §13.")
        await self._settle(params, JobState.DONE, note)

    def _confirm_the_stage(self, params: JobParams, staging: RunResult) -> str:
        """What a project whose chain ENDS at its last stage is told (#122).

        It is an ASK, not a status line. There is no production gate behind this, so somebody
        confirming the change is right is the whole of what is left — and a message that merely
        reports "verified, nothing is waiting on an approval" is how the shops with the shortest
        pipelines ended up being the only ones never asked to look at anything.

        AN EMPTY ADDRESS NEVER IMPLIES ONE. Without a declared `url:` this says so and names the
        field, rather than sending a person to look somewhere nobody named."""
        stage = staging.look_stage
        if not stage:
            return tl_voice.say(tl_voice.NARRATION, "stage.no-environment", params.language,
                                issue=params.issue)
        if staging.look_at:
            return tl_voice.say(tl_voice.NARRATION, "stage.confirm-at", params.language,
                                issue=params.issue, stage=stage, where=staging.look_at)
        return tl_voice.say(tl_voice.NARRATION, "stage.confirm-no-url", params.language,
                            issue=params.issue, stage=stage)

    async def _spawn_deploy_watch(self, params: JobParams, result: RunResult) -> None:
        """On merge, kick off the abandoned deploy-watch child (ADR-0005) and return at once —
        the ticket is DONE at merge, so the floor frees immediately; the watch runs on its own.
        ParentClosePolicy.ABANDON lets it outlive this workflow's completion. Best-effort: a
        failure to start the watch must NEVER fail an already-merged job (worst case: no deploy
        notification), so we swallow errors and let the job complete."""
        cfg = result.post_merge_deploy
        if not (cfg and result.pr_url):
            return
        try:
            await workflow.start_child_workflow(
                DeployWatchWorkflow.run,
                DeployWatchInput(
                    project=params.project, issue=params.issue, pr_url=result.pr_url,
                    workflow=cfg.workflow, env=cfg.env, timeout_minutes=cfg.timeout_minutes,
                    url=getattr(cfg, "url", "") or "",
                ),
                id=f"openfactory-deploy-{params.project}-{params.issue}",
                # inherit the parent's task queue (openfactory-jobs in prod) so the same worker
                # fleet
                # runs the watch — no separate deployment, and tests run it on their own queue.
                parent_close_policy=ParentClosePolicy.ABANDON,
            )
        except Exception:
            # already-watching (a re-run) or a transient start error — the merge stands and
            # the floor must free regardless. Never let the watch's start block the job (A3).
            workflow.logger.warning("deploy-watch not started for %s#%s", params.project,
                                    params.issue)

    async def _stamp_title(self, params: JobParams) -> None:
        """Stamp the ticket's title into the workflow memo so the panel shows it beside the
        number ("#123 Add health check") for the WHOLE run — done up front, before the long
        run_job. Best-effort: a title is cosmetic, so a lookup failure is swallowed and the job
        proceeds titled only by its number."""
        try:
            title = await workflow.execute_activity(
                fetch_ticket_title,
                TicketRef(project=params.project, issue=params.issue),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            if title:
                workflow.upsert_memo({"title": title})
                self._title = title  # reused by the metrics record so the cost table reads
        except Exception:
            workflow.logger.info("no title stamped for %s#%s", params.project, params.issue)

    async def _preflight(self, params: JobParams) -> RunResult | None:
        """ADR-0013 D2/D3 — size the ticket on the worker BEFORE any Fargate. Returns:
        None → fit/degraded/error: run the job exactly as before;
        DONE  → the ticket was SPLIT (children created, parent closed): complete, free floor;
        NEEDS_REFINEMENT → unclear: a preformed result the caller parks (Resume re-runs after
        the human clarifies — preflight runs again then, judging the improved text)."""
        try:
            v = await workflow.execute_activity(
                preflight_check,
                PreflightInput(project=params.project, issue=params.issue),
                start_to_close_timeout=timedelta(minutes=20),
                heartbeat_timeout=timedelta(seconds=120),
                retry_policy=_ONCE,  # a flaky gate must not delay the job — degrade instead
            )
        except Exception as exc:  # noqa: BLE001 — gate trouble → run the job, never block on it
            workflow.logger.warning("#%s: the pre-flight gate did not run (%s) — the job proceeds "
                                    "ungated, so an oversized ticket will not be caught here",
                                    params.issue, exc)
            return None
        if v.verdict == "unclear":
            qs = "; ".join(v.questions)[:300] or v.reasons[:300]
            return RunResult(ticket_id=params.issue, state=JobState.NEEDS_REFINEMENT,
                             note=f"pre-flight: can't size this ticket — {qs}")
        if v.verdict == "split" and v.children:
            try:
                note = await workflow.execute_activity(
                    split_ticket,
                    SplitInput(project=params.project, issue=params.issue,
                               children=v.children, reasons=v.reasons),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=2),  # idempotent (search-first)
                )
                return RunResult(ticket_id=params.issue, state=JobState.DONE, note=note)
            except Exception as exc:  # noqa: BLE001
                workflow.logger.warning("#%s: the automatic split failed (%s) — parking with the "
                                        "proposal for a person to split by hand", params.issue, exc)
                # splitting failed → park with the proposal so a human can split by hand
                return RunResult(
                    ticket_id=params.issue, state=JobState.NEEDS_REFINEMENT,
                    note=f"pre-flight judged this too large ({v.reasons[:200]}) but the "
                         "auto-split failed — split it manually",
                )
        return None  # fit / degraded

    @staticmethod
    def _promotion_box(params: JobParams, *, live: bool) -> dict:
        """Which box the promotion inputs name: the JOB'S, `params.sandbox`.

        The two promotion inputs were built here without a box, so `run_job`, the review pass and
        the CI repair ran on the job's box while promotion ran on the WORKER'S `default_sandbox()`
        — two sources of truth for one job's box, and a job on a remote add-on box promoted on a
        worker whose default is `container` was refused non-retryably with nothing launched.

        `live` is `workflow.patched("promotion-box-kind")`. Naming the box changes an ACTIVITY
        INPUT on a path with jobs in flight; a history that predates the marker built these inputs
        with `""` and let the activity resolve the deployment's box (`_run_promotion`), and it
        keeps doing so — that fallback exists for exactly those histories, not for new ones.
        Pure: `params.sandbox` is data the workflow already holds, so nothing here reads the
        environment under replay."""
        return {"sandbox": params.sandbox} if live else {}

    async def _lifecycle(self, params: JobParams) -> RunResult:
        self._params = params  # so _wait_operator can reach the project's coordinator
        await self._coord_say(tl_voice.say(tl_voice.NARRATION, "pickup", params.language,
                                          issue=params.issue), "pickup")  # the tech-lead narrates
        await self._stamp_title(params)
        # SINGLE-LINE STRICT (ADR-0010): the job runs to a resolution, and the queue advances
        # ONLY on a clean merge. EVERY non-progressing outcome holds the floor here — a rate-limit
        # pause (auto-retries on a backoff, or the operator retries-now/skips), and any impediment
        # (spec, cost, validation, review, e2e, merge conflict, unfixable CI, closed PR, agent
        # auth/token, or a crash) PARKS for the operator to Resume (re-run the fixed ticket) or
        # Skip (free the floor). So a ticket that needs attention never lets the next one start —
        # dependency-safe by construction, without any `depends_on` bookkeeping.
        rate_resumes = 0
        attempt = 0  # loop iteration — scopes launcher idempotency so a Resume re-runs for real
        resume_handle: str | None = None  # C2: carries a paused attempt's opaque token into resume
        # ADR-0013 D2/D3: size the ticket on the WORKER before any Fargate spin-up. A `split`
        # completes below (children created, parent closed, floor freed deliberately); an
        # `unclear` becomes a preformed needs_refinement result that PARKS — and a Resume after
        # the human clarifies re-arms the gate to judge the improved ticket. Re-armed ONLY for
        # preflight's own parks: a mid-run resumable hold must never be re-gated (a late `split`
        # would orphan preserved partial work). fit/degraded/error → run exactly as before.
        pre_pending = True
        spent_turns = 0  # ticket-wide effort total, carried across every attempt (D4)
        decision = ""  # a resolved human choice to inject into the NEXT run (a resumed blocker)
        result: RunResult | None = None
        while True:
            try:
                if result is None and pre_pending:
                    pre_pending = False
                    result = await self._preflight(params)
                    if result is not None and result.state == JobState.DONE:
                        return result  # split completed — children exist, the parent is closed
                if result is None:
                    result = await self._run_job_once(params, resume_handle, attempt,
                                                      spent_turns, decision)
                    decision = ""  # consumed — a resumed choice applies to exactly one run
                    attempt += 1
                    spent_turns = max(spent_turns, result.spent_turns)
                    # HERE, AND NOT INSIDE THE MERGE WATCH. This is the one point every attempt
                    # passes through, so a job that parks, is resumed and reviewed again reports
                    # the LATEST reading rather than the first — and a job that never reaches a
                    # pull request still carries what its gates said.
                    self._remember_verdict(result)
                    # Hold the floor until the PR actually MERGES — auto-merge (ADR-0004) and
                    # the human-review path (ADR-0007) both wait here, repairing red CI.
                    if result.state == JobState.PR_OPEN and result.pr_url:
                        # surface the wait to the panel: auto=False → "waiting for YOUR merge"
                        #
                        # WITH A NOTE, like the three assignments inside `_ci_merge_loop`. This one
                        # was the only one without, and it is the FIRST — so between here and the
                        # loop's first iteration the panel had a wait with nothing saying what it
                        # was on. A brief window, and briefly showing a wait without its reason is
                        # still the one thing this platform promises not to do; a suite run caught
                        # it as an intermittent `assert "note" in mw`.
                        self._merge_wait = {"pr_url": result.pr_url,
                                            "auto": bool(result.auto_merge),
                                            "note": "PR open — checking CI"}
                        try:
                            result = await self._ci_merge_loop(params, result)
                        finally:
                            self._merge_wait = None
            except asyncio.CancelledError:
                raise  # operator cancelled the workflow → run()'s handler cleans up + frees floor
            except Exception as exc:
                # A crash after the activity's own retries must NOT silently free the floor
                # (single-line): stop any lingering task, then park as an impediment the operator
                # can Resume (retry) or Skip. A determinism/replay error is not caught here (it is
                # not an Exception at this scope) — only genuine job failures reach this.
                await self._cleanup(params, shield=False)
                # `str(exc)` is `describe`'s fallback, not its first move: an exception raised
                # inside an ACTIVITY arrives here as `ActivityError`, and `str(ActivityError)` is
                # the temporalio SDK's fixed placeholder string `"Activity task failed"` — never
                # the real cause, which sits one level down in `__cause__` as an `ApplicationError`
                # carrying the original type and text. `describe` walks the chain for the first
                # message that is not itself a placeholder (#66) — the same fix that upstream
                # diagnostics (`SetupFailed`'s command + output tail, and the box-image resolver's
                # own refusal — see activities.py's `_resolved_image`) were already doing the work
                # to deserve, and were losing the moment they crossed this exact boundary.
                result = RunResult(
                    ticket_id=params.issue, state=JobState.ON_HOLD,
                    note=f"job errored after retries: {describe(exc, limit=150)}",
                )

            if result.state == JobState.PAUSED:  # rate-limit / usage cap (token ran out)
                if rate_resumes >= _MAX_PAUSE_RESUMES:  # persistent → escalate to a human
                    result = RunResult(
                        ticket_id=result.ticket_id, state=JobState.ON_HOLD,
                        note=f"still rate-limited after {rate_resumes} auto-resumes",
                        # THE NUMBER, NOT ONLY THE SENTENCE (#124). `classify` used to recover
                        # this by matching the prose above; a card about translating that prose
                        # would have disarmed the escalation it feeds.
                        attempts_spent=rate_resumes,
                    )
                else:
                    act, _, by_a_person = await self._wait_operator(
                        "rate_limit", result,
                        self._pause_backoff(rate_resumes, result.retry_at), "resume")
                    if act == "skip":
                        # A completed-"paused" job would read as "will resume automatically"
                        # (the machine's own ticket comment) when it never will. It is a SKIP: a
                        # person decided, and the record says which person's decision it was.
                        return await self._skip(
                            params, result, "rate-limited — skipped by operator",
                            by_a_person=by_a_person)
                    rate_resumes += 1
                    resume_handle = result.resume_handle  # C2: resume the paused attempt, not fresh
                    result = None  # next iteration runs the job again
                    continue  # backoff elapsed (or operator forced retry) → re-run
            # FAILED included (audit HIGH): the Fargate box converts ANY in-task crash into a
            # returned FAILED result — letting it fall through to `break` would COMPLETE the
            # workflow and silently free the floor with the ticket abandoned, violating
            # single-line strict (ADR-0010: every non-progressing outcome parks).
            if result.state in (JobState.NEEDS_REFINEMENT, JobState.ON_HOLD, JobState.FAILED,
                                JobState.BLOCKED):
                if self._skipped:  # the operator already gave up inside the merge loop
                    return result
                parked = result

                # ---- ADR-0020: is this ours to fix? ------------------------------------------
                # Before troubling anybody, ask what would actually resolve this. Throttling, a
                # network blip, a pool that failed one pass — those are the factory's own, and
                # parking them is idleness with paperwork. #478 lost eighteen hours to exactly that.
                #
                # It reuses the mechanism the rate-limit pause has used for months: hold the floor,
                # burn no compute, wake on a timer with `resume` as the default. New command
                # sequence, so it is guarded — a job already parked on the old path must replay the
                # old path.
                if workflow.patched("techlead-self-heal"):
                    # `engine` FROM patched(), NOT the default (#159). classify is pure, but its
                    # verdict DRIVES commands — a job parked under the old classification replays
                    # this call, and a new verdict there is a new command sequence (TMPRL1100).
                    verdict = classify(parked.note or "", state=parked.state.value,
                                       engine=workflow.patched("classify-engine-interrupted"))
                    tried = self._remedied.get(verdict.cause, 0)
                    remedy = remedy_for(
                        verdict, already_tried=tried, language=params.language,
                        already_spent=int(getattr(parked, "attempts_spent", 0) or 0))
                    if remedy.action == "retry" and remedy.wait_seconds > 0:
                        self._remedied[verdict.cause] = tried + 1
                        # SAY IT WHILE DOING IT: a channel that goes quiet during an incident
                        # teaches people to go and check the panel instead.
                        await self._coord_say(
                            tl_voice.say(tl_voice.NARRATION, "self-heal", params.language,
                                         issue=params.issue, say=remedy.say), "self_heal")
                        act, _, by_a_person = await self._wait_operator(
                            "self_healing", parked,
                            timedelta(seconds=remedy.wait_seconds), "resume")
                        if act == "resume":
                            result = None
                            continue
                        if act == "skip":
                            # A person interrupted the self-heal wait. The sixth place they can
                            # say it, and the last one still returning the parked result.
                            return await self._skip(
                                params, parked,
                                parked.note or "skipped during the self-heal wait",
                                by_a_person=by_a_person)
                # RECONCILE THE BOARD (#394): the in-job orchestrator normally sets the tracker to
                # Needs Action as it parks — but a crash/timeout kills the job first, leaving the
                # ticket reading "In progress" while it's actually waiting for a human. Set it from
                # the workflow so the board tells the truth. Idempotent (a clean park already set
                # it). patched(): an in-flight job replaying its pre-fix history must skip this new
                # command to stay deterministic; new runs and their live tail set it.
                author = ""
                if workflow.patched("park-marks-needs-action"):
                    try:
                        author = await workflow.execute_activity(
                            mark_needs_action,
                            HoldSyncInput(project=params.project, issue=params.issue,
                                          state=parked.state.value, note=parked.note or ""),
                            start_to_close_timeout=timedelta(minutes=1), retry_policy=_ONCE)
                    except Exception:  # noqa: BLE001 — reconciliation must never block the park
                        # The board now LIES: the card still reads "In progress" while the ticket
                        # waits for a person. Worth knowing about; not worth blocking a park.
                        workflow.logger.warning(
                            "could not mark #%s as needing action — its card may still read "
                            "In progress", params.issue)
                # TECH-LEAD DIAGNOSIS (ADR-0015): investigate the impediment against the real repo +
                # ticket and post a humanized HandOff to the ticket AND Slack — so the human gets a
                # diagnosis, not a raw stderr. Best-effort, generous timeout (clone + a read-only
                # agent pass); it NEVER blocks the park. New command → its own patch guard so an
                # in-flight job replaying pre-fix history stays deterministic.
                if workflow.patched("park-techlead-diagnosis"):
                    try:
                        await workflow.execute_activity(
                            diagnose_impediment,
                            HoldSyncInput(project=params.project, issue=params.issue,
                                          state=parked.state.value, note=parked.note or ""),
                            start_to_close_timeout=timedelta(minutes=10), retry_policy=_ONCE)
                    except Exception:  # noqa: BLE001 — the diagnosis is additive; never block the park
                        # THE ONE THAT COST EIGHTEEN HOURS. When this failed it took the only Slack
                        # message with it and #478 sat unmentioned. The alert no longer rides on it,
                        # but a diagnosis that cannot run is itself a symptom — usually the agent or
                        # the forge being unreachable, which is worth seeing in the log.
                        workflow.logger.warning(
                            "tech-lead diagnosis failed for #%s — the park is still announced, but "
                            "nobody explained it", params.issue)
                # ROUTE THE ESCALATION (no assignee in a lights-out flow): the coordinator SPEAKS
                # the needs-action back to whoever CREATED the ticket — a panel toast now, a Slack
                # @mention later (same API). New command → its own patch guard.
                if workflow.patched("park-says-needs-action"):
                    who = f" @{author}" if author else ""
                    note = (parked.note or "needs your input")[:200]
                    # THE ALERT, and it no longer DEPENDS on the diagnosis above having worked.
                    # That diagnosis is best-effort and its failure is swallowed by design, so
                    # routing the only Slack message through it made a parked job silent whenever
                    # it could not run — which is exactly what happened to #478 for eighteen hours.
                    #
                    # It stays AFTER the diagnosis in the sequence rather than before: reordering
                    # these commands would diverge the replay of any job already parked on the old
                    # order. The delay is one activity timeout at worst; the silence was total.
                    #
                    # It carries what to DO, because a message saying only that something stopped
                    # leaves the reader to find the panel and work out their options — the same
                    # silence with extra steps. When the CLASS of failure has its own way out
                    # (C-27: a policy that held on purpose, the client's own config), the
                    # remedy's sentence replaces the generic one — same commands, richer string,
                    # replay-safe (activity inputs are recorded, not compared).
                    verdict_here = classify(parked.note or "", state=parked.state.value)
                    remedy_here = remedy_for(
                        verdict_here, language=params.language,
                        already_tried=self._remedied.get(verdict_here.cause, 0),
                        already_spent=int(getattr(parked, "attempts_spent", 0) or 0))
                    steer = remedy_here.say
                    # `resume` IS OFFERED ONLY WHERE IT COULD WORK (pilot, 2026-08-16). This line
                    # was unconditional, so a park whose cause is the TICKET — where a re-run
                    # re-parks on the same blocker at full price — was answered with "responda
                    # resume para tentar de novo" directly under a sentence explaining that the
                    # execution was never the problem. Two instructions, contradicting each other,
                    # in one message; the pilot's reply was "não entendi".
                    #
                    # The remedy already knows: `action == "retry"` is the platform's own test for
                    # "trying again could help", and it is what the self-heal gates on.
                    retryable = remedy_here.action == "retry" or not steer
                    commands = tl_voice.say(
                        tl_voice.NARRATION,
                        "park.both-verbs" if retryable else "park.skip-only",
                        params.language, issue=params.issue)
                    # ASKED, NOT MATCHED (#124). This tested `"resume" not in steer and "skip"
                    # not in steer` — a substring check against the very sentence a translation
                    # card was about to rewrite, so the first rendering in another language would
                    # have printed the verbs twice or dropped them, depending on the wording. The
                    # remedy's author knows what the remedy says; nobody downstream should infer it.
                    ways = (f"{steer}\n{commands}"
                            if steer and not remedy_here.teaches_the_verbs
                            else steer or commands)
                    await self._coord_say(
                        tl_voice.say(tl_voice.NARRATION, "park.needs-you", params.language,
                                     issue=params.issue, who=who, note=note, ways=ways),
                        "needs_action")
                # A park that carries a DecisionRequest HOLDS until answered (owner: decisions are
                # always human — no timeout-default); a plain impediment keeps the deadline+skip.
                deadline = timedelta(days=3650 if parked.decision else
                                     params.impediment_deadline_days)
                act, choice, by_a_person = await self._wait_operator(
                    "impediment", parked, deadline, "skip")
                if act == "resume":
                    rate_resumes = 0
                    # ADR-0013 D1: a hold that CARRIES a handle is resumable — the stop preserved
                    # partial work (turn cap / agent stop / cost ceiling), so Resume CONTINUES it.
                    # A hold without one (spec refinement etc.) restarts clean as before.
                    resume_handle = parked.resume_handle
                    # Resolve the picked option into text the resumed agent gets, so it proceeds
                    # with that choice instead of re-asking (durable, auditable — the decision was
                    # also recorded on the ticket when the human/bot answered).
                    if parked.decision and choice:
                        opt = parked.decision.option(choice)
                        if opt:
                            decision = f"DECISION {opt.key} — {opt.label}" + (
                                f" ({opt.consequence})" if opt.consequence else "")
                    if (parked.note or "").startswith("pre-flight:"):
                        pre_pending = True  # the gate itself parked → re-judge the fixed ticket
                    result = None  # next iteration runs the job again
                    continue
                # SKIPPING IS AN ACT, AND THE RECORD MUST SHOW IT (pilot, 2026-08-16). This
                # returned the PARKED result untouched: the floor freed, and the panel went on
                # showing `on_hold` — the state the job had BEFORE a person decided — with the
                # card still in *Needs Action* and nothing on the ticket saying anybody had
                # decided anything. *"o status não on_hold e sim skipped, ou seja, o que realmente
                # aconteceu."* The same shape as the merge that could not reach Done: a human acts
                # and the record does not move.
                #
                # The DEADLINE is deliberately not this: nobody acted there, and `on_hold` with a
                # note about an elapsed window is exactly what happened.
                # WHO IS NOT CLAIMED anywhere in `_skip`: `act_on_impediment` carries the
                # action and a decision key, never an actor. Naming a person the signal never
                # delivered would be the same lie this session spent the day removing.
                if act == "skip" and by_a_person:
                    return await self._skip(params, result,
                                            parked.note or "no reason recorded",
                                            by_a_person=True)
                # THE DEADLINE RETURNS THE PARK UNTOUCHED. Nobody acted, so the job keeps the
                # state it parked in — `needs_refinement` stays `needs_refinement` — and rebuilding
                # it as ON_HOLD here would relabel a gate failure as an impediment.
                return result
            break  # resolved (merged / pr_open) → deploy-watch + promotion below

        # Merged → observe the project's own dev deploy (ADR-0005). An ABANDONED child does the
        # watching; this returns immediately, so the merge frees the floor for the next ticket
        # right away and the deploy notification arrives async — watching never gates.
        if result.state == JobState.MERGED:
            await self._coord_say(tl_voice.say(tl_voice.NARRATION, "merged", params.language,
                                          issue=params.issue), "merge")  # the tech-lead
            await self._flag_review_findings(params, result)
            await self._spawn_deploy_watch(params, result)
            await self._refresh_knowledge(params)
        # Promote when requested OR when the project's manifest declares environments —
        # the CONFIG decides (three-layer model), not a start-time flag (A2/C3).
        should_promote = params.promote or bool(result.environments)
        if result.state not in (JobState.PR_OPEN, JobState.MERGED) or not should_promote:
            if result.state == JobState.MERGED:
                await self._finish_at_the_merge(params, result)
            return result
        if not result.pr_url:
            return result

        # Never promote an unmerged change: wait for the ACTUAL merge (A2). A closed-unmerged
        # PR or the deadline both skip promotion and hand back — never poll on forever.
        merge = await self._wait_for_merge(params, result.pr_url)
        if merge != "merged":
            reason = (
                "PR was closed without merging — promotion skipped" if merge == "closed"
                else f"PR not merged within {params.merge_deadline_days}d — promotion skipped"
            )
            return RunResult(
                ticket_id=result.ticket_id, state=JobState.ON_HOLD,
                note=reason, pr_url=result.pr_url,
            )

        staging = await workflow.execute_activity(
            promote_staging,
            PromoteInput(project=params.project, issue=params.issue,
                         **self._promotion_box(
                             params, live=workflow.patched("promotion-box-kind"))),
            start_to_close_timeout=timedelta(minutes=40),  # > the launcher's 30min (R2)
            heartbeat_timeout=timedelta(seconds=120),
            # single-attempt: it posts a non-idempotent "staging verified" comment, so a
            # retry would duplicate it. A transient failure fails visibly (L5).
            retry_policy=_ONCE,
        )
        # WHERE A PERSON LOOKS, carried back from the box that read the client's manifest (#122).
        # Set before every return below, so the query answers for a job parked at the gate AND for
        # one that finished at its last stage.
        if staging.look_stage:
            self._look = {"stage": staging.look_stage, "url": staging.look_at}
        if staging.state != JobState.AWAITING_PROD_APPROVAL:
            # ANNOUNCED LIKE EVERY OTHER STALL. This tail returned raw: staging could fail, the
            # approval window could elapse, the release could land, and not one message was sent.
            # It surfaced only if somebody opened the panel's inbox unprompted — a silent wait on
            # the one gate that puts software in front of the client's users.
            #
            # DONE IS NOT A FAILURE, and this branch called it one (#122). A project whose chain
            # ends at its last stage — no production declared, an ordinary and supported shape —
            # finishes here with `DONE`, and every one of them was announced as "staging did not
            # verify". The one flow this card exists to serve was being told its green deploy had
            # gone wrong.
            if workflow.patched("promotion-tail-speaks"):
                if staging.state == JobState.DONE:
                    await self._coord_say(self._confirm_the_stage(params, staging), "needs_action")
                else:
                    await self._coord_say(
                        tl_voice.say(tl_voice.NARRATION, "stage.unverified", params.language,
                                     issue=params.issue,
                                     why=staging.note or staging.state),
                        "needs_action")
            return staging

        # Durable human-in-the-loop: park here (days) until the panel signals an
        # approval. No compute burned, no polling, nothing lost if we crash. The gate
        # flag makes the signal only count while we're actually parked here (M6).
        self._awaiting_approval = True
        try:
            await workflow.wait_condition(
                lambda: self._approval is not None,
                timeout=timedelta(days=params.approval_deadline_days),
            )
        except TimeoutError:
            # The workflow used to COMPLETE here with the card still reading "In review" and
            # nothing said. A release nobody approved is not a release nobody wanted.
            if workflow.patched("promotion-tail-speaks"):
                await self._coord_say(
                    tl_voice.say(tl_voice.NARRATION, "prod.window-elapsed", params.language,
                                 issue=params.issue,
                                 days=params.approval_deadline_days),
                    "needs_action")
            return RunResult(
                ticket_id=params.issue,
                state=JobState.ON_HOLD,
                note="prod approval window elapsed",
            )
        finally:
            self._awaiting_approval = False  # gate is closed; further signals are ignored

        assert self._approval is not None
        released = await workflow.execute_activity(
            release_prod,
            ReleaseInput(project=params.project, issue=params.issue, **self._approval,
                         **self._promotion_box(
                             params, live=workflow.patched("promotion-box-kind"))),
            start_to_close_timeout=timedelta(minutes=40),  # > the launcher's 30min (R2)
            heartbeat_timeout=timedelta(seconds=120),
            # single-attempt: it posts a non-idempotent "prod release approved by @x"
            # comment before the idempotent tag, so a retry would duplicate it (M7).
            retry_policy=_ONCE,
        )
        # THE OUTCOME, EITHER WAY. A production release that succeeded and a production release
        # that failed were equally silent — and the second is the one somebody needs to hear.
        if workflow.patched("promotion-tail-speaks"):
            ok = released.state not in (JobState.ON_HOLD, JobState.FAILED)
            await self._coord_say(
                tl_voice.say(tl_voice.NARRATION,
                             "prod.released" if ok else "prod.failed", params.language,
                             issue=params.issue, why=released.note or released.state),
                "merge" if ok else "needs_action")
        return released
