"""Serializable inputs for the Temporal workflow and its activities.

Everything crossing the workflow/activity boundary must be data (Temporal
persists it in history). These are plain Pydantic models; the worker uses
Temporal's Pydantic data converter, so they pass through directly.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from openfactory.adapters.sandbox.registry import DEFAULT_BOX_IMAGE, BoxTraits, box_traits

#: The box a deployment gets when it says nothing: the local container, the reference path.
DEFAULT_SANDBOX = "container"


#: Which box this DEPLOYMENT runs jobs in: `OPENFACTORY_SANDBOX`, else the local container.
#:
#: IT USED TO INFER A VENDOR'S BOX FROM A VENDOR'S VARIABLE — `fargate` whenever
#: `OPENFACTORY_FARGATE_CLUSTER` was set — on the reasoning that a knob nobody has to turn cannot be
#: wrong. The reasoning was fine and the knob was not: the core answering the name of a box it does
#: not implement, from a variable only that box's add-on reads, is the core knowing one connector
#: by heart. A deployment that runs its boxes remotely says so in the one variable every other
#: box already uses (`OPENFACTORY_SANDBOX=fargate`), and a deployment that says nothing gets the
#: box the open distribution ships (ADR-0040 D2). The same answer `api/app.py::_boxes_are_remote`
#: now reads off the box's TRAITS rather than off a cluster name.
#:
#: UNTIL C-13 NONE OF THIS WAS CONFIGURABLE AT ALL. The compose file set `OPENFACTORY_SANDBOX:
#: container` and nothing read it; the models split three ways — `JobParams` and `RunJobInput`
#: defaulted to `container`, `PollInput` and friends to `fargate`, and the cloud worked only
#: because `api/app.py` passed `sandbox="fargate"` by hand. A configuration that looks configured
#: and is ignored is this repository's signature defect.
def default_sandbox() -> str:
    import os

    explicit = (os.environ.get("OPENFACTORY_SANDBOX") or "").strip().lower()
    return explicit or DEFAULT_SANDBOX


class RatePauseInput(BaseModel):
    """Why the poller is standing still, said to a human.

    A SEPARATE INPUT rather than the budget dict: a workflow's activity arguments are part of
    its history, so a loose dict here would be replayed forever with whatever keys the probe
    happened to carry that day."""

    resource: str
    remaining: int
    reset_epoch: int
    #: WHOSE budget, as the adapter names itself (`"GitHub"`) — the announcement used to spell
    #: the vendor as a literal in the activity, which was right for exactly one tracker.
    vendor: str = ""
    #: The tracker KIND the budget belongs to (`github`, a stranger's `gitlab`) — the registry's
    #: key, distinct from the display name above. The once-per-window marker is keyed by it: two
    #: vendors exhausted in one reset window are two announcements, not one. Empty is the
    #: pre-per-vendor shape and keeps the marker name that shape had.
    kind: str = ""
    #: The projects on the exhausted vendor — the only ones the pause is ABOUT. Empty means every
    #: project (the shape before budgets were read per tracker), so an in-flight history replays
    #: with the meaning it had.
    projects: list[str] = Field(default_factory=list)


class JobParams(BaseModel):
    """The workflow input: one ticket, plus how to run it."""

    project: str
    issue: str
    sandbox: str = Field(default_factory=default_sandbox)
    image: str = Field(default_factory=lambda: DEFAULT_BOX_IMAGE)
    review: bool = True
    # Run the post-merge staging→prod path after the PR (only where a live
    # pipeline exists; a production client's prod is OFF in dev). Default: stop at the PR.
    promote: bool = False
    approval_deadline_days: int = 3
    merge_deadline_days: int = 14  # how long to durably wait for the PR merge (A2)
    # Single-line strict (ADR-0010): a job that hits an impediment PARKS holding the floor
    # until the operator resumes/skips. This bounds a forgotten block — after it, the floor
    # auto-frees (skip) so the queue can't be jammed forever by an unattended ticket.
    impediment_deadline_days: int = 3
    #: The language this project's UNPROMPTED messages are written in (#124).
    #:
    #: A FIELD, NOT A LOOKUP, and the distinction is a replay one. The park announcement is
    #: composed inside the workflow, which may not do IO — and fetching the language would be a
    #: NEW COMMAND in the sequence, so every job in flight would diverge (TMPRL1100). A field with
    #: a default deserialises fine on a history that predates it: an old job renders English,
    #: which is the same answer it would have given if nobody had configured anything.
    #:
    #: Filled by `start_jobs`, which is an activity and may read the registry.
    language: str = ""
    #: The box's TRAITS, stamped by the activity that starts the job — the same replay argument as
    #: `language`, one field up, applied to the box axis being open to add-ons. The workflow asks
    #: `remote` (must a stop be sent when the job ends abnormally?) and `idempotent` (may a failed
    #: attempt be retried?), and `box_traits` answers from the BUILT-IN table alone because it
    #: runs in the workflow body: an add-on's traits come from `importlib.metadata`, which is
    #: I/O, and from a package that may not be installed on the worker doing the replay. So the
    #: activity that starts the job looks the box up with the add-ons in view and writes the
    #: answer here, as data.
    #:
    #: `None` MEANS "NOT STAMPED" AND NOTHING ELSE: a history that predates this field, or a caller
    #: that built the params by hand. Then the built-in table answers, which for every box the
    #: platform ships is the same answer — and for an add-on's box it RAISES, naming the built-ins,
    #: rather than guessing whether a job it cannot see must be stopped.
    box: BoxTraits | None = None

    def traits(self) -> BoxTraits:
        """What the WORKFLOW may ask about this job's box, with no I/O: the stamped traits, else the
        built-in table. Read the field's comment for why the two are not the same lookup."""
        if self.box is not None:
            return self.box
        return box_traits(self.sandbox)


class RunJobInput(BaseModel):
    project: str
    issue: str
    sandbox: str = Field(default_factory=default_sandbox)
    image: str = Field(default_factory=lambda: DEFAULT_BOX_IMAGE)
    review: bool = True
    # C2 (perfect resume): an OPAQUE token from a prior PAUSED attempt. When set, the run
    # RESUMES that attempt (restore the partial worktree from its pushed branch + hand the
    # handle to the agent so it continues its session) instead of starting fresh — so a
    # rate-limit pause doesn't replan/re-implement. The core never interprets it. None → fresh.
    resume_handle: str | None = None
    # Which lifecycle-loop iteration this is (0-based). Folded into the launcher's idempotency
    # scope so an operator "Resume" after an impediment launches a FRESH task instead of
    # reconciling the PREVIOUS iteration's stale (still-STOPPED, ≤1h in ECS) pr_open result —
    # same fix shape as CiRepairInput.attempt (audit MED).
    attempt: int = 0
    # Cumulative agent turns already spent on this ticket (prior attempts) — feeds the
    # ticket-wide effort budget (ADR-0013 D4).
    spent_turns: int = 0
    # A human's answer to a DecisionRequest this ticket parked on, already resolved to injectable
    # text ("DECISION A — Trust only configured proxies"). Carried into the box so the agent
    # proceeds with the chosen option instead of re-asking. Empty on a normal run.
    decision: str = ""


class PreflightInput(BaseModel):
    """The pre-Fargate sizing gate's input (ADR-0013 D2) — runs on the WORKER."""

    project: str
    issue: str


class PreflightVerdict(BaseModel):
    """The sizer's parsed verdict. Degrade-safe by construction: anything that goes wrong
    (cache, agent, parsing) yields verdict='fit' with `degraded` set — the job then runs
    exactly as it would have without preflight; the gate can only ever help, never block."""

    verdict: str = "fit"  # fit | split | unclear
    estimated_files: int | None = None
    reasons: str = ""
    children: list[dict] = []  # [{title, objective, criteria:[...]}] — only for split
    questions: list[str] = []  # only for unclear
    degraded: str | None = None  # why the gate fell back to fit (None = clean judgment)


class SplitInput(BaseModel):
    """Create the .a/.b children for an oversized parent (ADR-0013 D3)."""

    project: str
    issue: str
    children: list[dict]  # the sizer's proposed decomposition
    reasons: str = ""


class MergeCheckInput(BaseModel):
    project: str
    pr_url: str


class CiRepairInput(BaseModel):
    """One CI-repair pass on an open PR (ADR-0004): the durable loop calls it when CI is red."""

    project: str
    issue: str
    pr_url: str
    sandbox: str = Field(default_factory=default_sandbox)
    # Which repair attempt this is (0-based). Folded into the launcher's idempotency scope so
    # a SECOND attempt launches a fresh task instead of reconciling the FIRST attempt's stale
    # (still-STOPPED, ≤1h in ECS) result — otherwise the repair cap of 2 collapses to 1.
    attempt: int = 0


class AdjustInput(BaseModel):
    """One repair pass on an open PR driven by a HUMAN's own words (#68, C-32).

    The same shape as `CiRepairInput` plus the instruction, and it reaches the same machinery —
    `machine.repair_ci` checks out the EXISTING branch, runs one agent pass, and pushes to the
    same PR. The only difference is what fills the prose slot: a CI log when the build is red, a
    person's sentence when they read the diff and want something changed. Keeping the branch and
    the PR means the review history and the ticket's thread stay in one place, which is what the
    card asks for.
    """

    project: str
    issue: str
    pr_url: str
    sandbox: str = Field(default_factory=default_sandbox)
    #: which adjust pass this is (1-based), folded into the launcher's idempotency scope for the
    #: same reason `CiRepairInput.attempt` is — otherwise a second pass reconciles the first's
    #: stale result and the cap of 2 collapses to 1.
    attempt: int = 1
    #: what the human asked for, verbatim and already bounded by the caller.
    instruction: str = ""


class ReviewPassInput(BaseModel):
    """One re-read of an open PR by the independent reviewer, asked for by a person (#181).

    NEITHER `CiRepairInput` NOR `AdjustInput`, and the difference is the point: this pass writes
    nothing. It checks the branch out, reads the diff and publishes a verdict — so it carries no
    prose slot, and the `attempt` below exists for the same idempotency reason theirs do rather
    than to bound a repair.
    """

    project: str
    issue: str
    pr_url: str
    sandbox: str = Field(default_factory=default_sandbox)
    #: which re-review this is (1-based), folded into the launcher's idempotency scope — without
    #: it a second ask would reconcile the first one's stale STOPPED task and return its verdict.
    attempt: int = 1


class PromoteInput(BaseModel):
    project: str
    issue: str
    #: WHICH BOX RUNS THE PROMOTION. Neither promotion input carried one, and the activity behind
    #: them launched a vendor's task unconditionally — so a deployment on any other box reached the
    #: promotion tail and died on that vendor's missing environment. A field with a default
    #: deserialises on the histories in flight.
    #:
    #: `""` AND NOT `default_factory=default_sandbox`, unlike its siblings above, because THESE TWO
    #: ARE CONSTRUCTED INSIDE THE WORKFLOW BODY, where a factory that reads the environment runs
    #: under replay — measured: the promotion tests hung at the first
    #: `execute_activity(promote_staging, …)` when the factory was tried. The workflow names the
    #: JOB'S box here (`JobWorkflow._promotion_box`, behind `patched("promotion-box-kind")`);
    #: `""` is what a history from before that marker sends, and means "the deployment's box",
    #: which the ACTIVITY resolves (`_run_promotion`) — where the worker's environment was being
    #: read implicitly all along.
    sandbox: str = ""


class ReleaseInput(BaseModel):
    project: str
    issue: str
    version: str
    approver: str
    comment: str = ""
    #: see `PromoteInput.sandbox`
    sandbox: str = ""


class TicketRef(BaseModel):
    """A project + issue reference — for cheap read-only lookups (e.g. the ticket title
    the workflow stamps into its memo so the panel can show it next to the number)."""

    project: str
    issue: str


class AskInput(BaseModel):
    """A human's free-text question for the tech-lead, dispatched to the WORKER.

    Exists because `ask` used to execute in whichever process served the request — and the
    panel's process has (correctly) no harness credential, so the tech-lead's "answer" was the
    CLI's own "Not logged in · Please run /login". The agent runs where agents run."""

    project: str
    question: str
    #: The catalogue rows the ASKER may perform, decided at the door by `actions.proposable(by)`
    #: and carried as data (#121). The worker has no actor and must not build one: a tech-lead that
    #: resolved authority for itself would be granting it.
    #:
    #: DEFAULTS TO EMPTY, which `conversation.answer` reads as resume/skip — the pair that was
    #: hardcoded before this field existed. An AskWorkflow already in flight therefore deserialises
    #: into exactly the behaviour it was started with.
    can: list[str] = []
    #: THE CONVERSATION SO FAR, rendered at the door (#168). Every question used to be turn one:
    #: `_remember` wrote both halves of the thread on every turn and nothing under `techlead/` ever
    #: read them, so the tech-lead could not know what it had said two hours earlier — which is
    #: half of #159 (it re-dictated a command it had already been told was unexecutable) and the
    #: reason it read as a stranger each time.
    #:
    #: RENDERED AT THE DOOR AND CARRIED AS DATA, exactly like `can` one field up: the store lives
    #: where the question arrived and the worker must not acquire a second way to reach it.
    #: BOUNDED at the door too — token-efficiency is one of the three promises, so this is a
    #: character budget, not a turn count.
    thread: str = ""


class ProductAskInput(BaseModel):
    """A human's request for the PRODUCT role to draft, dispatched to the WORKER.

    THE SAME DEFECT AS `AskInput` ONE CLASS UP, and it was already live here — the row shipped
    drafting in whichever process served the request, behind a check that the harness BINARY was
    on this process's PATH.

    THAT CHECK PASSES ON THE PANEL. Measured in the running container rather than read off the
    docstring: `docker-compose.yml` builds the panel from `docker/worker.Dockerfile`, which ends
    in `npm install -g @anthropic-ai/claude-code`, so `claude` is at `/usr/local/bin/claude` on
    exactly the process the guard was written to stop. What the panel has not got is the
    CREDENTIAL (`CLAUDE_CODE_OAUTH_TOKEN` is unset there, by design) and the docker socket —
    neither of which was being measured. So the guard would have waved the request through to an
    unauthenticated agent and returned its "Not logged in · Please run /login" as the product
    role's own answer, which is the LATEST-48 defect verbatim, in a new capability.

    Dispatching makes it impossible rather than detected: the agent runs where agents authenticate.

    `asked_by` TRAVELS because the role records who asked in the requirement it drafts, and an
    activity that inferred it from the worker's own identity would attribute every client's
    requirement to the bot."""

    project: str
    question: str
    asked_by: str = ""
    #: Which conversation this turn belongs to (#33) — `person:<id>` or `visitor:<cookie>` from
    #: the panel, a chat thread from a channel, "" for the project-wide one. The row's answer is
    #: recorded under it and its earlier turns are handed to the role, so the web's free-text box
    #: is a conversation and not a sequence of first questions.
    thread: str = ""


class ProductBreakdownInput(BaseModel):
    """One accepted requirement, to be turned into units of work ON THE WORKER.

    THE CARD'S OWN ACCEPTANCE TEST RAN THROUGH SLACK AND NOWHERE ELSE. #98 states it as *"a
    deployment without slack_sdk can propose a requirement, accept it and see the card born on the
    board"*, and the last third of that was unreachable: `ProductModule.accept` writes the
    agreement and stops, and the accept→`break_down` chain existed only in
    `runtime/slack/product_channel.py`. Measured: `break_down` and `file_issues` had no production
    caller anywhere else in the tree.

    ON THE WORKER because `file_issues` runs an agent — `_role().issues_for(sandbox=…)` — so this
    is the same constraint `product_ask` has, reached by the same route rather than a second one.
    """

    project: str
    number: int
    actor: str = ""


class ProductQueueInput(BaseModel):
    """What should start next, proposed ON THE WORKER.

    `propose_queue` reads the client's board and then runs an agent pass to ORDER it — the
    readiness is arithmetic and true whatever the model says, the ordering is the judgement — so
    it carries the same constraint `product_ask` and the breakdown do, and reaches the worker by
    the same route rather than a third one."""

    project: str
    limit: int = 5


class ProductCardInput(BaseModel):
    """One card rewritten by the product role, ON THE WORKER.

    ONE MODEL FOR TWO VERBS, and only because they are genuinely the same shape: `refine` and
    `align_card` both check `may_act`, read the board, run ONE agent pass over a single card and
    then write the ticket body. Same timeout, same reason not to retry — rewriting a client's
    ticket twice is not idempotent. A third verb that differed in any of those would get its own
    model rather than a wider `verb`, because the moment the field stops meaning "which of two
    identical things" it stops documenting anything.

    `requirement` is only read for `align`; `refine` ignores it. Kept explicit rather than
    optional-by-convention so a caller that forgot it is refused by name."""

    project: str
    number: str
    verb: str
    requirement: int = 0
    actor: str = ""


class ProductBaselineInput(BaseModel):
    """The brownfield first pass — the whole codebase read and written up, ON THE WORKER.

    IT WRITES. `ProductModule.baseline` runs one whole-repository agent survey and opens a pull
    request on the client's documentation repo (branch `product/baseline`). Idempotent by asking
    the forge first: a second run finds the open proposal and reports `existed`, which is what
    makes the bounded retry below safe.

    `actor` IS CARRIED BECAUSE THE MODULE CANNOT ASK. `baseline` is one of four verbs documented
    as writing without checking `may_act` — its gate is "one layer up" — so the row asks, and this
    field is what the row's answer travels on."""

    project: str
    actor: str = ""
    via: str = ""
    areas: list[str] | None = None


class ProductNeedsActionInput(BaseModel):
    """What is parked and WHOSE PROBLEM IT IS, classified on the worker.

    IT LOOKS LIKE A READ AND SPENDS LIKE A WRITE, which is the whole reason this input exists.
    `review_needs_action` composes a git worktree of both repositories and then runs ONE MODEL
    CALL PER PARKED TICKET (`product/module.py`) — up to `limit` of them. Its sibling
    `triage_board` spends nothing and is answered in-process, so copying that row's shape here
    would run an agent inside the panel container: a place that has the harness binary and
    neither its token nor the docker socket. That failure passes every test in this repository
    and appears only in production.

    `limit` IS THE BUDGET, not a page size. It is what stands between a board with three hundred
    parked tickets and three hundred model calls."""

    project: str
    limit: int = 10
    #: WHERE THE REQUEST CAME FROM, carried rather than defaulted. `ProductModule`'s default is
    #: `"slack"` and this activity's would be `"api"` — either one is a false statement the day the
    #: row is reached from the other surface, in the record that says who asked for a pass that
    #: spends money.
    via: str = ""


class ProductSayInput(BaseModel):
    """A turn of CONVERSATION with the product role, on the worker.

    NOT `product_ask`, AND THE DIFFERENCE IS THE POINT. `ask` drafts: it reads a message as a
    request and comes back with a requirement to sign off. This is the other half — the reply that
    remembers, so "e o segundo?" means something and a correction lands on what was said before.
    Without it every message on a Slack-less deployment was turn one, which is the state ADR-0024
    layer 1 exists to prevent.

    `thread` IS THE CONVERSATION'S IDENTITY, and it travels rather than being derived: the Slack
    package keys history by thread, the panel by project, and a row that invented one would split
    a single conversation across two memories or merge two clients into one."""

    project: str
    message: str
    thread: str = ""
    asked_by: str = ""
    #: the transport the message arrived through — provenance for every gate the turn reaches
    #: (`may_act`), so a "funcionou" typed in the panel is recorded as the panel's and not as the
    #: channel's. Empty means "the row did not say", and the worker reads that as `api`.
    via: str = ""


class ProductAnswerInput(BaseModel):
    """A staged proposal ANSWERED by token, resolved ON THE WORKER (#105).

    IT IS ON THE WORKER BECAUSE OF WHAT A YES CAN BE. Most confirmations are cheap — a fact, a
    decision, a drop — but two of the nine kinds spend an agent: `accept` chains into
    `break_down` (`file_issues` runs a pass) and `align` ends in `_role().ask_json`. Which one a
    token names is not knowable until the staged entry is read, and the entry may only be read
    once, by the compare-and-swap that performs it. So the process is chosen by the WORST case,
    not the common one — a CLI on somebody's laptop or the panel's container would otherwise run
    an agent with no credential for it, which passes every test here and breaks only in
    production.

    `via` TRAVELS because it is the provenance of a write in a client's documentation: an answer
    given on the panel recorded as a Slack one is a lie in the one record that says who
    authorised the change."""

    project: str
    token: str
    approved: bool
    actor: str = ""
    via: str = ""


class HoldSyncInput(BaseModel):
    """The WORKFLOW reconciling the board to a parked state. Normally the in-job orchestrator
    sets the tracker status, but a crashed/timed-out job dies before it can — leaving the ticket
    reading 'In progress' while it actually needs a human. The workflow calls this so the board
    tells the truth. `state` is a JobState value; every impediment state maps to Needs Action."""

    project: str
    issue: str
    state: str = "on_hold"
    note: str = ""


class DeployWatchInput(BaseModel):
    """The abandoned post-merge deploy-watch child workflow's input (ADR-0005). Carries the
    merged PR so the watcher resolves the merge commit SHA itself, plus the deploy workflow to
    observe and a label for the notification. Watching only NOTIFIES; it never gates."""

    project: str
    issue: str
    pr_url: str
    workflow: str  # the deploy workflow to observe (`gh run list --workflow`)
    env: str = "dev"
    timeout_minutes: int = 30
    #: Where a person looks once it is green (`post_merge_deploy.url`). Defaulted so an in-flight
    #: watch started before #122 keeps deserialising.
    url: str = ""


class DeployStatusInput(BaseModel):
    """One deploy-status probe: read the deploy workflow's run on a merge commit (ADR-0005)."""

    project: str
    pr_url: str
    workflow: str


class DeployNotifyInput(BaseModel):
    """Emit the deploy-watch's outcome via the project's notifier (ADR-0005)."""

    project: str
    issue: str
    status: str  # "success" | "failure" | "timeout"
    env: str = "dev"
    run_url: str | None = None
    #: Where a PERSON looks, from the manifest's `post_merge_deploy.url` (#122). Carried on the
    #: input rather than read inside the activity so the WORKFLOW's history records the address
    #: that was actually announced — a manifest edited mid-watch cannot rewrite what was said.
    url: str = ""


class PollInput(BaseModel):
    """One poller tick: which sandbox new jobs run on."""

    sandbox: str = Field(default_factory=default_sandbox)


class ScanInput(BaseModel):
    project: str
    board_owner: str
    board_number: str
    pickup_status: str = "TO-DO"


class StartJobsInput(BaseModel):
    project: str
    issues: list[str]
    sandbox: str = Field(default_factory=default_sandbox)


class CoordinatorItem(BaseModel):
    """A parked decision handed to the project's tech-lead coordinator for a humanized take.
    Carries the JobWorkflow id so the coordinator can signal its advice back to that job."""

    project: str
    issue: str
    job_id: str
    kind: str = ""  # plan | merge | impediment | rate_limit …
    question: str = ""
    context: str = ""
    options: list[dict] = []  # [{key,label,consequence,recommended}]
    note: str = ""


class CoordinatorSayInput(BaseModel):
    """A one-line update the coordinator narrates (a ticket picked up, a merge, a deploy). Shown
    as a panel toast now; the SAME data is what a Slack/PO bot will post later (API-first)."""

    project: str
    text: str
    kind: str = ""  # pickup | merge | deploy | ...


class CoordinatorInput(BaseModel):
    """The always-alive coordinator's input — one per project. `seq0`/`recent` carry the message
    log across continue-as-new so ids stay monotonic and the panel doesn't lose recent toasts."""

    project: str
    seq0: int = 0
    recent: list[dict] = []


class JobMetricsInput(BaseModel):
    """Cost/effort telemetry the workflow persists on completion (observability.metrics → the
    cost dashboard). Carries the per-invocation breakdown (agent_runs, from the RunResult) plus
    the job summary — final state, wall-clock seconds, total cost, PR. `ts` is the ISO completion
    time the workflow stamps (deterministic: workflow.now()), reused as each record's sort key."""

    project: str
    issue: str
    ts: str
    state: str = ""
    title: str = ""
    wall_s: float | None = None
    total_cost_usd: float | None = None
    pr_url: str = ""
    # which A/B arm the run was in (off | injected | unavailable) — ADR-0017's gate dimension
    knowledge: str = ""
    # each: {role, model, harness, cost_usd, num_turns, input_tokens, output_tokens}
    agent_runs: list[dict] = []


class KnowledgeRefreshInput(BaseModel):
    """The post-merge Knowledge Pipeline run for one project (§11 / §22). `issue` is carried for
    the log line only — the refresh is about the BASE BRANCH's new state, not about one ticket."""

    project: str
    issue: str = ""


class ReviewLoopInput(BaseModel):
    """A merged ticket whose independent review rejected it or raised something critical.

    Carried as its own input rather than the whole ReviewResult: the workflow already decided this
    is worth following up, and shipping the full review through an activity boundary would move a
    lot of text to re-derive a judgement that has been made."""

    project: str
    #: `str`, like every other `issue` in this file (#69). It was the ONE `int` among eighteen,
    #: and it is constructed from `JobParams.issue`, which is a `str` — so on a Jira/ADO
    #: deployment pydantic REFUSED to build this input, the workflow's `except Exception` around
    #: the call swallowed it, and the review finding was announced once and never chased. The
    #: whole open-loop mechanism (ADR-0021) could not start on those deployments, and the log line
    #: said only "could not record the review finding for follow-up".
    issue: str
    decision: str
    score: int = 0
    detail: str = ""
    pr_url: str = ""
