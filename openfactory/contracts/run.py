"""Results of running the platform's own steps.

Key ADR-0001 principle (D-11): the *platform* runs the validation commands and
reads their exit codes. It does not believe the agent that claims it ran them.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from openfactory.contracts.decision import DecisionRequest
from openfactory.contracts.manifest import PostMergeDeploy
from openfactory.contracts.review import ReviewResult
from openfactory.contracts.state import JobState


class AgentRunResult(BaseModel):
    """What a CodingAgentAdapter reports back after an execution/repair pass."""

    ok: bool
    summary: str = ""
    cost_usd: float | None = None  # from `claude -p --output-format json`
    # Human-readable trace of what the agent did (e.g. "Edit app/health.py",
    # "Bash: pytest") — parsed from the stream so the orchestrator can journal it
    # without knowing which agent produced it.
    actions: list[str] = Field(default_factory=list)
    # an infra pause (not a code failure): the agent hit a usage limit or an auth
    # problem. reason ∈ {"rate_limit", "auth"}; retry_at set only for rate limits.
    pause_reason: str | None = None
    retry_at: str | None = None
    # How many agent turns this invocation consumed — the agnostic effort currency feeding the
    # ticket-wide budget (ADR-0013 D4). None when the adapter doesn't report turns.
    num_turns: int | None = None
    # Cost-telemetry dimensions (observability.metrics): which model tier + harness produced this
    # result, and the token usage. Agnostic strings/ints any adapter can fill; None when unknown.
    model: str | None = None          # opus | sonnet | haiku | …
    harness: str | None = None        # the adapter identity, e.g. "claude_code"
    input_tokens: int | None = None
    output_tokens: int | None = None
    # Which credential of the pool produced this result — AGNOSTIC telemetry any adapter with
    # a credential pool can fill ({index, total, id, rotated}). The core just surfaces it (panel
    # token visibility + proof that failover happens); it never reads the actual token. None for
    # a keyless/single adapter. (Claude fills it from its token pool — the detail stays there.)
    credential: dict | None = None
    # OPAQUE resume token an adapter emits on a resumable pause and consumes on resume (C2):
    # the core round-trips it without interpreting it, so a Claude session id or a Codex handle
    # both work. None → nothing to resume (fresh run). Adapter-private meaning; core-agnostic.
    resume_handle: str | None = None
    raw_output: str = ""


class AgentRunMetric(BaseModel):
    """The cost/effort of ONE agent invocation within a job — the per-model / per-harness detail
    the orchestrator collects so the telemetry sink can persist spend by dimension. Kept in the
    contract layer (no observability dependency) so machine.py can fill it as it runs each pass."""

    role: str  # planner | executor | repair | recovery | review | diagnose | chat
    model: str = ""
    harness: str = ""
    cost_usd: float | None = None
    num_turns: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    # -- what the pass DID, not only what it cost (observability.trajectory) ---------------------
    # Cost and turns say how much was spent; these say on what. They are the instruments for the
    # two questions an operator asks about a factory and that nothing here could answer — is it
    # fast, is it cheap — and their raw material was already being parsed on every pass and thrown
    # away.
    #
    # NONE IS "NOT MEASURED", NEVER "ZERO". A harness with no stream reader, and a pass whose
    # output was not captured, both leave these None — because a recorded 0 would say the agent
    # called no tools, which is a measurement nobody took and the exact failure the trajectory
    # module exists to avoid.
    tool_calls: int | None = None
    #: calls whose key had already been seen. NOT automatically waste — re-reading a file after
    #: editing it is correct — but a run whose repeats dominate its calls is one to look at.
    repeated_calls: int | None = None
    #: calls for a tool this invocation never granted; the CLI denied them, so they are pass spent
    #: asking for something that was never going to arrive
    refused_calls: int | None = None
    #: model steps before the first edit — the exploration tax. None also when the pass edited
    #: nothing, which is why it is never summed across passes: it is a per-pass shape.
    turns_to_first_edit: int | None = None


class ValidationResult(BaseModel):
    """One declared validation command, run by the platform (not the agent)."""

    name: str  # e.g. "test", "lint", "security"
    command: str
    exit_code: int
    passed: bool
    output_tail: str = ""  # last N lines, for the PR/report
    #: Reported, never blocking (C-37). The field is on the RESULT and not only on the manifest
    #: because everything downstream — the merge decision, the repair loop, the PR body, the panel
    #: — reads results, and a consumer that had to re-derive the policy from the manifest is a
    #: consumer that will forget one branch. Default False: a gate that quietly stopped blocking
    #: is the dangerous direction of this change.
    advisory: bool = False


class Suppression(BaseModel):
    """A gate-suppression the diff ADDED (pragma: no cover, noqa, type: ignore, nosec) —
    with where it lives, so the panel can show the human exactly what to review instead of a
    bare "forcing human review" (engineering #12). Populated for jobs run after this shipped."""

    kind: str  # normalized type, e.g. "pragma: no cover"
    file: str = ""  # path the '+' line landed in, from the diff's `+++ b/…` header
    snippet: str = ""  # the added line's text (trimmed), e.g. the function it exempts


class RunResult(BaseModel):
    """The full outcome of one job attempt, assembled by the orchestrator."""

    ticket_id: str
    state: JobState  # the terminal state this attempt reached
    branch: str = ""
    note: str | None = None  # e.g. the NEEDS_REFINEMENT reason
    #: How many automatic attempts were ALREADY spent before this park — 0 when none were.
    #:
    #: A NUMBER, BECAUSE IT WAS ONE (#124). The pause ladder knew `rate_resumes` exactly and threw
    #: it away into prose — `note="still rate-limited after 3 auto-resumes"` — which
    #: `techlead/classify.py` then recovered with a REGEX OVER OUR OWN SENTENCE. So the escalation
    #: that stops the platform proposing the very thing whose failure the note describes was
    #: wired to the wording, in two languages, one of which matched a sentence `remedy_for`
    #: itself emits. Translating either would have disarmed it silently, and #124 is a
    #: translation card.
    attempts_spent: int = 0
    # When state is PAUSED (rate-limited): the reset time the agent reported, if any — surfaced
    # on the panel ("resumes after …") and used to pace the resume. Often absent (a vague/absent
    # limit message) → the workflow falls back to a growing backoff. Agnostic string telemetry.
    retry_at: str | None = None
    # OPAQUE resume token carried from the agent through to the resumed run (C2) — the workflow
    # round-trips it without interpreting it (Claude session id / Codex handle both fit).
    resume_handle: str | None = None
    # Cumulative agent turns this ticket has consumed across ALL attempts (executor + repairs +
    # recoveries + resumes) — the workflow carries it into each resume so the effort budget
    # (ADR-0013 D4) governs the TICKET, not one invocation.
    spent_turns: int = 0
    # Source of truth for which components were touched is the DIFF, not any label
    # (ADR-0001 D-6). Resolved after execution by mapping the diff to component paths.
    touched_components: list[str] = Field(default_factory=list)
    # THE OTHER HALF OF THE SAME QUESTION, and the half nothing recorded. `touched_components` holds
    # the components the diff MATCHED; these are the diff paths that matched none of them. Without
    # them the merge gate loops over an empty list, finds no high-risk component and permits a
    # change to a part of the repository the manifest never described — "no concept, no objection",
    # inverted, in the gate that decides whether a person sees the merge at all. Capped for the
    # pull request body a human reads; `undeclared_count` carries the true number.
    undeclared_paths: list[str] = Field(default_factory=list)
    undeclared_count: int = 0
    # THE VERIFIER'S OWN INPUTS, if this change edited any (`policy/protected.py`). Resolved from
    # the same diff, at the same moment, for the same reason the field above exists: the gate holds
    # a RunResult and not a diff, so a question nobody recorded is a question the gate cannot ask.
    #
    # An attempt from before this field existed carries `[]`, which reads as "nothing protected was
    # touched" — and that IS what the platform used to believe. It is not silently upgraded to
    # "unknown": an old result cannot answer a question nobody asked it, and inventing a gate for
    # it would refuse merges on evidence that does not exist.
    protected_hits: list[str] = Field(default_factory=list)
    #: the TRUE number of them. `protected_hits` is truncated for a person reading a pull request
    #: body; this is not. Split for the same reason `undeclared_paths`/`undeclared_count` above is
    #: split, and learned the same way: a change touching forty protected files reported twelve
    #: and the real number was gone, because a count taken from a truncated list is not a count.
    protected_count: int = 0
    #: THIS DEPLOYMENT COULD NOT READ ITS OWN FLOOR — a different fact from a violation, and the
    #: gate reads both. Kept apart because the sentence a human is shown differs: a violation names
    #: the client's own change, and this names OUR install. The first revision answered an
    #: unreadable floor with an arbitrary sample of changed paths, which gated correctly and told
    #: the durable record a falsehood about which files were touched.
    #:
    #: An attempt from before this field existed carries `False`, which reads as "the floor was
    #: readable" — the same rule as the fields above: an old result cannot answer a question nobody
    #: asked it, and inventing a gate for it would refuse merges on evidence that does not exist.
    floor_unreadable: bool = False
    # THE TEST CENSUS (`policy/census.py`), taken on the clean workspace after `setup:` and again
    # after the agent's edits. `None` is NOT zero and the distinction is the whole gate: None means
    # no census was taken — the project declares no inventory command, or it could not be read —
    # and 0 means the command ran and collected nothing. Collapsing them would read a project with
    # no census as a project whose suite just emptied.
    test_census_before: int | None = None
    test_census_after: int | None = None
    #: identifiers present before and absent after — the reason, capped for a human to read
    test_census_gone: list[str] = Field(default_factory=list)
    #: how many there really were. The cap above is for a reader; this is the measurement, and it
    #: is NOT recoverable from the count drop — a rename is minus-one-plus-one by this design's own
    #: argument, so the two numbers answer different questions. Same split as `undeclared_count`.
    test_census_gone_count: int = 0
    validations: list[ValidationResult] = Field(default_factory=list)
    repair_attempts: int = 0
    total_cost_usd: float | None = None
    # per-invocation cost telemetry (observability.metrics): one entry per agent pass this attempt
    # ran, each tagged with model/harness/role/cost/turns/tokens. The workflow persists these on
    # completion so the cost dashboard can slice by model and harness. Empty for pre-telemetry jobs.
    agent_runs: list[AgentRunMetric] = Field(default_factory=list)
    # WHICH A/B ARM this attempt ran in (ADR-0017's gate). Deliberately records what the agent
    # actually SAW, not what was configured:
    #   ""            — pre-instrumentation run (unknown; excluded from the comparison)
    #   "off"         — the project has not opted in
    #   "injected"    — the module map was in the agent's context
    #   "unavailable" — opted in, but nothing was injected (no bundle, or it was stale/orphaned)
    # The third value is why this isn't a boolean: a flag-on job whose map was stale belongs in
    # the CONTROL arm, and a high "unavailable" rate means the pipeline isn't keeping up and the
    # experiment is measuring noise rather than the map.
    knowledge: str = ""
    review: ReviewResult | None = None  # independent reviewer's verdict (D-5)
    #: Did THIS PASS change the pull request? Measured, on the checkout the pass had in hand: the
    #: diff against the base before the agent ran, against the diff after it committed and pushed.
    #:
    #: THE VERDICT'S STALENESS IS A STATEMENT ABOUT CODE, so it has to be answered by code (#179).
    #: A repair pass that could not act, a formatter that reformatted nothing, an amend, a rebase
    #: that replays identically — each of those used to demote the platform's own review to "out of
    #: date, go read the diff yourself" and take the finding a person was standing there to read
    #: off the screen. What moved was a commit sha; what the reviewer read did not move at all.
    #:
    #: `None` IS THE CONSERVATIVE ANSWER, not a missing one: git could not be asked, so the marker
    #: stays up. The expensive direction is the other one — presenting a rejected review as current
    #: about code it never saw — which is why an unknown never clears it.
    #:
    #: SCOPE, SO THE FIELD IS NOT READ FOR MORE THAN IT MEASURES: this is about the pass, not about
    #: the world. Somebody else pushing to the branch between the review and this pass is not
    #: detected here — it never was anywhere, since only our own passes ever raised the marker.
    code_changed: bool | None = None
    pr_url: str | None = None
    # True when the PR was opened under merge_policy=auto and auto-merge was ARMED but the
    # PR is not yet merged (waiting on required CI). The durable workflow then owns the
    # CI-watch/repair/merge loop (ADR-0004): react to a red CI instead of leaving it armed
    # forever. False when the machine already merged (CI green / no required checks) or on
    # the human-review path.
    auto_merge: bool = False
    # the manifest's declared environments (e.g. ["staging","prod"]) — lets the workflow
    # decide POST-PR promotion from the project's CONFIG, not a start-time flag (A2)
    environments: list[str] = Field(default_factory=list)
    #: The stage a PERSON is asked to confirm, and the address they open to do it (#122). Filled
    #: by `PromotionRunner` — which runs in a box with the manifest checked out — so the answer
    #: travels back to the worker, which has no checkout and would otherwise have to guess.
    #:
    #: `look_stage` set with `look_at` EMPTY is a real and different state: the project declares a
    #: stage worth confirming and no address for it. The messages say exactly that rather than
    #: sending somebody to a place nobody named.
    look_stage: str = ""
    look_at: str = ""
    # the manifest's post-merge deploy-watch config (ADR-0005), carried so the durable
    # workflow can spawn an abandoned watcher AFTER merge without re-reading config. None
    # when the project doesn't opt in — then no watch is started.
    post_merge_deploy: PostMergeDeploy | None = None
    # gate-suppression comments the diff ADDED (pragma: no cover, noqa, type: ignore,
    # nosec). An agent must not pass a quality gate by silencing it; detected
    # deterministically from the diff and always forced to human review (never
    # auto-merged), independent of the LLM reviewer. (engineering.md #12)
    added_suppressions: list[str] = Field(default_factory=list)
    # the same suppressions WITH their location (file + line text) — for the panel's
    # "why is this waiting for me" briefing. added_suppressions stays the type-list the
    # merge guard keys off; this is the display detail. Empty for pre-existing jobs.
    suppression_details: list[Suppression] = Field(default_factory=list)
    # When a stage parks needing a HUMAN CHOICE (a planner blocker, an unclear ticket), the
    # question + concrete options travel here so the workflow can surface them (panel/API) and
    # inject the picked option back on resume. None on a normal outcome. "No park without
    # options" (owner) — a bare state is never enough. See openfactory/contracts/decision.py.
    decision: DecisionRequest | None = None

    @property
    def all_passed(self) -> bool:
        """Every BLOCKING gate passed, and there was at least one.

        TWO DEFECTS LIVED IN `all(v.passed for v in self.validations)`, and both were about
        claiming a green nobody earned.

        ADVISORY WAS COUNTED. `machine._all_passed` learned to exclude advisory gates (C-37) and
        this property — the one `merge_policy.should_auto_merge` actually reads — did not, so an
        advisory security scan reporting a finding blocked the merge and parked the job with
        "validations failed". That is the exact opposite of what advisory means, and it would have
        made the free security preset the first thing a client turned off.

        `all([])` IS TRUE. A project registered with an empty `validate:` block ran the agent,
        passed every gate vacuously, and was eligible for auto-merge — its entire quality floor
        being `all([]) == True`. The floor (`policy/floor.py`) names `test` and `security` as
        non-negotiable, and its only reader was a CLI command nothing in the job path calls.

        Requiring at least one blocking gate is the safety net, not the fix: a project with no
        gates is refused before pickup, where refusing costs nothing (`policy/conformance.py`).
        This is what stops a green being reported if that ever fails to hold.
        """
        blocking = [v for v in self.validations if not v.advisory]
        return bool(blocking) and all(v.passed for v in blocking)
