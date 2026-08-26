# ADR 0001 — Foundational conceptual model of the platform

- **Status:** Accepted (conceptual model); scope and build sequencing are follow-ups.
- **Date:** 2026-07-12
- **Supersedes:** —
- **Note:** This ADR is deliberately broad. It freezes the *vocabulary and the
  load-bearing structural decisions* the platform is built on. Individual
  decisions marked **[D-n]** may each be elaborated (or revised) by a later,
  narrower ADR; this document is the shared foundation they all refer back to.

## Context

We already develop software with interactive coding agents (Claude Code, and
Aider under evaluation). In practice, when the specification is good, the
patterns already live in the repo, and the allowed commands are known, the human
intervention collapses to pressing "yes, yes, yes". That is not decision-making;
it is a manual authorization mechanism wrapped around a process that has become
predictable enough to automate.

The goal is **not** to build a new coding agent. Existing agents can already run
non-interactively and act as executors. The goal is to invert the control model:

```
Today:    human authorizes each action  →  agent works
Target:   policies authorize actions     →  human evaluates results
```

Crucially, this must be a **framework**, not a tool welded to one project. A
production client's repository is the first project it will drive, but nothing
project-specific may live in the framework. The design method is therefore:
**design against several imaginary projects at once (a Python backend, a Node
frontend, a Terraform infra), never against one.** Any decision that only makes
sense for that one client is in the wrong place.

## Glossary (the shared vocabulary)

- **The machine (framework).** Generic machinery: state machine, ephemeral
  environments, command execution, board integration, agent invocation, PR
  creation. It also carries the *generic* half of the agent's brain (base role
  prompts, stack presets, org defaults). It knows nothing about any specific
  project and never will.
- **Project knowledge.** Files that live *inside the project repo*, versioned with
  the code: the manifest, guidelines, ADRs, architecture docs. Content, not
  machinery. This layer is **not flat** — it is a cascade (see [D-2]).
- **The agent.** The worker that does the job (executor / reviewer). It is the
  bridge: it uses the machine and reads the project knowledge. The agent's
  *runtime* belongs to the framework; its *behavior* comes from the project.
- **The manifest** (`.sdlc/project.yaml`). The project's plug into the framework
  contract. The framework defines the shape of the plug (which slots exist, which
  are required); the project fills it in.
- **Component.** A stack-homogeneous area of a repo (e.g. `backend`, `frontend`,
  `infra`), each with its own stack, validation commands, guidelines, docs, and
  risk level. A single repo may hold several.
- **Board.** The external system of record for tickets (GitHub Issues/Projects,
  Jira, …). Tickets are born here, by humans. The framework consumes them; it does
  not invent them.

## Decisions

### [D-1] Framework ↔ project separation, via a declarative manifest

Nothing project-specific lives in the framework. The framework owns *mechanism*;
the project *declares* its specifics in `.sdlc/project.yaml`. The framework never
contains the string `pytest`; the project does (a Node project declares `vitest`).
The framework runs the validation commands the project **declared**, whatever they
are. The manifest is declarative by default; executable escape hatches (project
hooks) are allowed only as explicit, auditable exceptions, never as the norm.

### [D-2] Project knowledge is a cascade of authority; tighten, never loosen

Project knowledge is layered, from most-generic/most-authoritative to
most-specific:

| Layer | Owner | Example | May loosen upper layer? |
|---|---|---|---|
| 1. Framework floor | framework | "tests must pass; a security scan must run; no push to `main`" | ❌ never |
| 2. Stack preset | framework, keyed by language | "Python ⇒ ruff + bandit + mypy + pytest" | ⚠️ tighten only |
| 3. Org defaults | the organization | "every project in this organization uses TDD" | ⚠️ tighten only |
| 4. Project | the repo | "test command is `make test`; also run Playwright" | ✅ fills & tightens |

**Golden rule: each layer may *tighten* the layer above, never *loosen* it.** This
is what makes quality a guarantee rather than a matter of goodwill: the security
scan required by the floor cannot be switched off by a project manifest. Presets
are framework-owned but not project-specific — they are opinions about *generic
categories* (a language), which the framework is entitled to hold.

The org layer is **logical, not a separate repo.** For now it lives inside the
framework as default configuration. Physically there are two repos: framework and
project.

### [D-3] The framework owns the slots; conformance enforces them

The framework defines *which slots a project must provide* (validation command,
execution guidelines, acceptance-criteria format, …) and which are required vs.
optional. A conformance check verifies required slots are filled (directly, or by
a cascade default). A project that leaves a required slot empty with no default
does not run jobs. The *existence and obligation* of a slot is the framework's; the
*content* is the cascade's.

### [D-4] Ephemeral environment, persistent dependency cache

Each job runs in an ephemeral workspace (isolated branch, temporary credentials,
expiry, network policy). This buys reproducibility, parallel-safety, clean secrets
lifecycle, and a known initial state — and kills the "one fixed environment per AI
dev" idea. **Nuance:** the *code state* is ephemeral, but a *dependency cache*
(venv, `node_modules`, Docker layers, `~/.cache`) is persisted, so we do not pay a
full install per job. Ephemeral in the repo state; persistent in the dep cache.

**Decision (revised 2026-07-12): the real sandbox is a Docker container, not a git
worktree.** The isolation this ADR promises — bounded CPU/mem, network policy,
ephemeral secrets, restricted filesystem — is only *actually delivered* by a
container; a worktree isolates the code state and nothing else, which is
insufficient for autonomous execution of arbitrary code. Both live behind
`SandboxAdapter`, so this is an implementation choice, not a structural one:
`ContainerSandbox` is the production path; `WorktreeSandbox` is retained as a
lightweight local/test double (fast orchestrator tests and local debugging without
a Docker daemon), never for untrusted work. Container implications: a base image
per stack (toolchain + git + the `claude` CLI preinstalled), repo mounted (not
baked), dep cache as a mounted volume, and auth injected as env at run time.

### [D-5] One generic worker per ticket; executor and reviewer are separate contexts

A ticket is an **atomic unit of work = one PR.** One generic worker (the
executor) handles the whole ticket — whatever it touches. There is **no "backend
agent" and "frontend agent"**; there is one worker that wears the manuals of the
components the ticket touches (see [D-6]).

A **separate reviewer context** exists, whose value is *context independence*: it
receives only the specification, the diff, and the validation results — **never the
executor's conversation.** Its job is to find evidence that the solution is wrong
or incomplete (map acceptance criteria to evidence, hunt regressions, spot
unrequested scope, check architecture compliance), and to emit **structured
findings** — not to re-read the code and say "looks good". This lets the human
read a *report* instead of the raw diff, and dig into code only when the report
raises a flag. The reviewer **compresses the human's decision**; it does not
replace it.

Multi-agent decomposition (planner/architect/tester/security/… as separate
agents) is explicitly **not** adopted for v1: it multiplies cost, latency,
context loss, and debugging difficulty. Two independent contexts — executor and
reviewer — are the whole cast.

### [D-6] The label is a guess; the diff is the truth. Components resolve stacks.

A repo may be a polyglot monolith. The manifest declares **components**, each with
its own `stack`, `validate`, `guidelines`, `docs`, and `risk`. Front/back/devops
are **not different agents** — they are different manuals + permission sets + risk
levels that the same worker wears depending on what the ticket touches. IaC is
just a component with a `terraform` preset and `risk: high`.

We **do not** use front/back labels. Instead:

- **Before** execution, any label/area is at most a *hint* (for risk estimation
  and which manuals to pre-load).
- **After** execution, the **diff is the source of truth** for which components
  were touched. The framework runs the validation, applies the risk, and sets the
  human gate based on the *diff*, not the guess.

Consequently, **scope leak is normal, not a failure.** A "backend" ticket that
ends up touching the frontend is absorbed: the framework detects the touched
components from the diff, runs their validations, applies their risk, and flags it
in the PR. **Scope *explosion*** (touching many undeclared components, or a diff
past a configured threshold) is different: the executor stops and returns the
ticket to refinement ("scope exceeded"). This shares the repair-loop limits (max
attempts / runtime / cost).

For v1, a ticket touching several components is handled by **one executor wearing
the union of manuals**, not by several coordinated executors (that is a later
optimization).

### [D-7] Dependencies: declared is truth (deterministic); inferred is advisory

- **Declared** (`depends_on: #134` on the ticket): the orchestrator reads it and
  topologically orders work. Deterministic, no AI. For v1, **a dependent ticket
  only runs after its dependency is merged** — the only regime where "ephemeral +
  reproducible" stays true and no work is built on sand. Because v1 is
  single-process and deps run post-merge, **code conflicts do not exist** (there
  is always a linear base). Conflict is a problem parallelism *creates*; we do not
  create it early.
- **Inferred** (the orchestrator/AI suspects an undeclared dependency): **advisory
  only.** It raises a hand to the human ("this looks like it needs #134"); the
  human confirms, which turns it into a declared dependency. The human declares;
  AI at most suggests. AI is never the source of truth for dependencies.
- **Dependency discovered at runtime** (executor finds it needs an endpoint an
  unmerged ticket will build): treated as a *late-arriving dependency*. The
  executor stops and returns the ticket with the discovered `depends_on`; it does
  not fabricate the missing dependency. This is neither a gate failure nor scope
  explosion — it is new information about ordering.

### [D-8] Spec-quality gate: trust to start, verify to finish

Before spending resources, a `SPEC_VALIDATION` gate checks *deterministically
knowable* spec quality: acceptance criteria present and verifiable, clear
objective, referenced files/docs exist, declared dependencies exist, no
contradictions, an applicable validation command. Pass → the ticket becomes
`READY`. Fail → back to `NEEDS_REFINEMENT` **with the specific reason**, so the
human refines in minutes instead of guessing.

The gate **must not** reject a ticket for mis-predicting components (front vs.
back) — that is unknowable up front and is handled by the diff ([D-6]). The trust
model is: **trust enough to start (spec is executable), verify reality at the end
(the diff). Never blind trust.**

### [D-9] Docs: standard *roles*, not standard *locations*; ADRs are the constitution

The framework standardizes the **role** a doc plays, not *where* it lives. The
manifest maps role → path (a glob). `constraints` (ADRs), `architecture`,
`guidelines` are roles; each project points them wherever it keeps them. The
conformance check verifies the declared paths exist.

Doc *existence* varies per project and is handled by required/optional slots. The
**ticket-level spec is always required** (framework floor); **reference docs (ADR,
architecture) are optional per project.** Absence is graceful — but it has a
price: less declared knowledge → the executor flies blinder → **a stronger human
gate.** Documentation is therefore the **investment that buys autonomy**: every
ADR written is a bit of "yes, yes, yes" removed. The framework does not force docs;
it reflects the consequence in the gate.

Loading rule, by size/scope — **not** by front/back:

- **ADRs (`constraints`): always loaded, all of them.** They are the constitution:
  small, cross-cutting, hard constraints. We never rely on a ticket to link the
  right ADR — that is exactly how a decision gets violated by accident.
- **Component architecture (large): pulled on demand.** The executor receives a
  derived **index** (see [D-10]) and pulls the specific doc when it discovers which
  component it is in — the same discover-then-pull mechanism as [D-6].

A doc only prevents wrong code if it is **read at execution *and* checked at
review.** Read-only-by-executor = a suggestion; also-checked-by-reviewer = a
constraint. Every doc-consumption decision has both sides. Staleness is human
discipline; the framework can only verify a doc *exists* and, at most, *advise*
that an area's doc looks untouched.

### [D-10] Derive, do not maintain (the doc index, and beyond)

The doc index the executor browses is **derived, never hand-maintained** — a
hand-maintained index rots. Its structure comes from a deterministic glob of the
manifest's declared doc paths; each entry's one-line summary comes from the doc's
own frontmatter `summary:` (or its first heading). It is **regenerated fresh at job
start**, so it can never be stale. An AI-generated summary is a last-resort
fallback for a doc with no summary/heading — cached and flagged machine-generated.

**General principle:** whenever a thing can be *derived* from a source of truth,
derive it; do not maintain it in parallel. A derived artifact maintained by hand is
an artifact that rots.

### [D-11] Deterministic-first

Where a step can be deterministic, it is deterministic — do not spend AI (cost,
latency, non-determinism) on work a glob, a topo-sort, or an exit code can do.
Reserve AI for the steps that genuinely require judgment (implementing, deciding
which doc to pull, interpreting a failure). Much of the "deterministic validation
layer" is not something to build — it already exists as each project's declared
commands (for a production client: `make check`, `make test`) and CI workflows. The
platform *invokes* them and reads the exit code; it does not reimplement them, and
this is exactly what gives independent validation — the platform runs the tests, it
does not believe the agent that says it ran them.

### [D-12] The platform is a lifecycle operator, not a PR-opener — it orchestrates & observes, it does not wield

The platform's responsibility does **not** end at the PR. It carries a change
through the full lifecycle — idea → dev/staging → prod — because a tool that stops
at the PR is just a PR-opener; the product is autonomous delivery with observation
and reaction. This is made safe not by *stopping early* but by a clean split of
powers:

| Concern | Who | Holds prod secrets? |
|---|---|---|
| **Execute** the deploy | the project's existing pipeline (e.g. GitHub Actions) | yes — it already does |
| **Trigger** a transition (merge, tag) | the platform | **no** — it only pulls a trigger |
| **Observe** the outcome (CI, deploy status, health) | the platform | **no** — read-only |

When "the platform put it in prod", mechanically the *pipeline* did it, invoked by
an action policy authorized the platform to take. The floor ("no prod access, no
reading secrets") stands: the platform never *wields* a secret — it triggers, the
pipeline executes.

Three capabilities follow:

1. **Gated promotions.** Each environment transition is a risk-gated action (the
   D-6 risk engine). **Default posture: auto up to staging (low-risk + green CI →
   automatic merge/staging deploy); prod always waits for human approval.** Tunable
   per risk. The platform triggers merge/tag; the pipeline executes.
2. **Read-only observation.** CI status, deploy status, and health probes. This is
   what feeds status/notification channels (e.g. Telegram) — without it, the human
   never learns whether a change actually shipped.
3. **Defined reactions** (never free surgery on prod). **Default: code repairs,
   infra reports.** A deploy/health failure caused by *code* → the bounded repair
   loop (now listening to post-deploy signals) → a new PR. A failure caused by
   *infra* → diagnose and either propose a high-risk IaC PR or escalate to the
   human with logs — **never an automatic infra apply**. A red post-deploy health
   check → rollback (a pre-defined safe pipeline action: re-deploy the last-good
   tag) + report.

**Prod is a deliberate, authenticated human action.** There is no auto-to-prod. The
framework carries a change to staging, verifies it, and **stops** at
`AWAITING_PROD_APPROVAL`. Releasing to prod requires a human action in the panel:
an approver in the project's `prod_approvers` allowlist **identifies + enters a
password** (hashes in a gitignored store, managed by `sdlc approver add`), **picks
the version** (the panel shows the latest tag and suggests the next patch/minor/major
bump), and may add a comment. The approval is recorded on the ticket (who + version +
comment), then the bot tags → the prod pipeline deploys → the framework observes.

**The invariant that is never traded away:** however far it goes, the platform has
**no standing, unsupervised power to destroy production.** It triggers, the
pipeline executes, the human is the risk-graduated gate, and reactions come from a
defined safe set (code repair, propose PR, rollback, report) — never arbitrary prod
action.

New seams (behind interfaces, like everything): **EnvironmentObserver** (read-only:
CI/deploy/health) and **Notifier** (Telegram/Slack/email — status + escalation).

**Identity & credentials (refinement).** The agent acts as a **distinct actor**
(`BotIdentity`), not as a human: commits, PRs, comments, and reviews are attributed
to it. This is separated into two provider-agnostic pieces so nothing is
provider-locked:

- *The actor* — one logical identity (name/email), used as the git commit author.
- *The credentials* — **one per axis**, because the axes are independent. A
  Jira-tracker + GitLab-forge project needs a Jira API token *and* a GitLab access
  token; a single-vendor GitHub project reuses one. Each token is **opaque to the
  framework** — how it's obtained (a GitHub App installation token, a GitLab
  Project/Group Access Token, a Jira API token, a bot PAT) is a per-provider
  concern that never enters the core. Least privilege on these tokens is the
  executable control that makes "cannot merge protected main" true by construction.
  Tokens come from the environment, never the registry.

**PR posture (refinement).** The **default is human-on-PR**: the bot opens the PR,
posts the reviewer's verdict as a real PR review (approve / comment /
request-changes, mapped from the review decision), requests the configured human
reviewers, and comments the ticket — then stops. A project may opt into
`merge_policy: auto`, which merges only when the review is not rejected, all
validations pass, and no touched component is high-risk. Auto-merge to prod is never
the default.

### [D-13] Evaluation model: judges are structured calls on deterministic gates; agent behavior is measured, not assumed

Judgment appears in three places, and none of them requires a cognitive-orchestration
framework. **A judge is a single structured LLM call** (context → a validated
Pydantic model like `ReviewResult`), never a graph:

- **Spec-readiness (`SPEC_VALIDATION`)** — a deterministic filter first (acceptance
  criteria present? referenced docs/deps exist? no contradictions?), *then* an
  optional LLM judge scoring spec quality. `score ≥ 80` → proceed; below → back to
  `NEEDS_REFINEMENT` with reasons. The deterministic stage exists so we never spend
  an LLM call on an obviously broken spec.
- **Dependency inference** — declared `depends_on` is deterministic truth; an LLM
  may *infer* an undeclared dependency, but only as **advisory** (it suggests, a
  human confirms). AI is never the source of truth for dependencies.
- **Review** — the reviewer (D-5) emits structured findings + a score from an
  independent context.

**Agent behavior is evaluated, not assumed.** Per-job we already produce objective
signals (validation pass/fail, repair attempts, reviewer score, cost). Across jobs,
an **evaluation/telemetry layer** aggregates them. The **ground-truth signal is the
human's final decision vs. the reviewer's score**: sustained divergence means the
reviewer is miscalibrated. Tracking this is precisely how the platform *earns* a
lower human gate over time — the whole point of the project. This layer is
analytics (a metrics rollup), not an agent framework, and is deferred until there
is job volume to measure; building it earlier would be overengineering.

**Consequence for frameworks:** no cognitive-orchestration framework (e.g.
LangGraph) is adopted. Its two niches are already filled — operational
orchestration is deterministic Python (D-11), and the cognitive loop
(plan→implement→interpret→fix) is delegated to the coding agent (D-5), which owns
its own loop. LangGraph would earn a place only if we later build our own executor
(instead of orchestrating existing agents) or a stateful, resumable cognitive
planner — and then only as one component behind an interface, not the platform's
center.

### [D-15] Pickup, ownership, and impediment handling

- **Pickup by board state, gated by an on/off switch.** The framework picks up
  tickets in the board's **TODO column** (configurable `pickup_status`), independent
  of who is assigned. A per-project **on/off toggle** (in the panel) gates this, so
  dragging a card to TODO does not start work until the board has been prioritized
  and turned on. With no parallelism (v1), tickets are processed one at a time.
- **The assignee is the owner, not a lock.** On pickup the bot makes itself the sole
  assignee (remembering the previous owner). The framework works the owner's ticket
  for them.
- **Impediment → hold → return to owner.** If the agent stops or a validation can't
  be repaired, the framework comments the reason, returns the ticket to the previous
  owner (or leaves it unassigned if there was none), sets `ON_HOLD`, and **stops** —
  with no parallelism it does not pick up another task. The comment and a **web
  alarm** remain until a human acts.

### [D-14] Tenancy: single-tenant, multi-project (with a seam for later)

The framework is **multi-project** by construction (the ProjectRegistry drives N
repos), but **single-tenant**: one instance managed by one team, one registry, one
bot, no login/RBAC. It is not multi-tenant — it does not serve multiple isolated
customers, which would require auth, per-tenant isolation of the registry / DB /
secrets, and RBAC. That is a much larger surface and is deferred.

The design keeps the seam: a future "tenant" is a layer *above* project (a tenant
owns a set of projects, credentials, and users), added additively without reworking
the project/adapter/journal model. Build multi-tenancy only if the platform is sold
as a product to external teams.

### [D-16] Runtime: serverless-native, with Temporal as the durable-execution engine

The platform runs **in the cloud** (never on a laptop). Robustness is the priority
over scale: the system must never *silently* stall — every job, within a bounded
time, either advances or moves to a visible failed/held/paused state with a reason,
and nothing is lost if a process dies.

The orchestration/supervision of a long, flaky, multi-step, **AI-and-human-in-the-loop**
workflow is a *durable execution* problem, and we do **not** hand-roll it (a custom
Postgres+watchdog reinvents exactly the silent-hang class). The runtime:

- **Temporal** (durable execution) is the orchestration engine. Our `JobRunner`
  becomes a Temporal **workflow** (the logic stays portable Python, minimal rewrite);
  each side-effecting step (tracker/forge/agent/sandbox/board call) becomes an
  **activity** with automatic retry + timeout + heartbeat; prod approval is a
  **signal**; the rate-limit resume and the approval wait are **timers** (a workflow
  can durably sleep for days holding no process). A crashed worker resumes exactly
  where it was; the Temporal Web UI shows every step/retry/failure — it cannot hang
  silently. **Temporal Cloud**, not self-hosted: babysitting a Temporal cluster to
  save the fee would contradict the robustness goal for a two-person team.
- **Fargate** runs the heavy sandbox step (a container task per job, sized per job,
  no 15-min Lambda ceiling, isolated). Behind the existing `SandboxAdapter`.
- A **projection store** (DynamoDB or Postgres) + the journal feed the web panel,
  which stays the team's daily interface; the Temporal UI is the deep-dive safety net.
- Short event-driven glue (webhooks, the poll tick) → Lambda/EventBridge; alarms →
  CloudWatch.

Considered and rejected: **hand-rolled supervisor** (worst for robustness); **pure
SQS-loop** (fine for single-step jobs, but strains on long pauses + human-in-the-loop);
**Step Functions** (managed, robust, all-AWS, but a worse fit for this workflow's
shape — human-in-loop via task tokens, ASL, history limits — and AWS-locked). Step
Functions remains the fallback if an all-AWS/no-third-party posture is later required.

**Design consequence — activity idempotency:** because activities auto-retry, every
side-effecting activity must be idempotent (or carry an idempotency key), so a retry
never opens two PRs, posts two comments, or cuts two tags.

Development runs against a local Temporal dev-server; only the deploy points at
Temporal Cloud + Fargate. The core (workflow logic, adapters, contracts, panel) is
portable; the AWS/Temporal bits are the runtime.

### [D-17] Fargate sandbox execution model: whole-job-in-task (v1), token-in-task

Concretizes how the `SandboxAdapter` promise (D-4) is delivered on Fargate (D-16).
The local `ContainerSandbox` model — a long-lived container the host `docker exec`s
into per command, with the code cloned on the host and the **push done from the host**
so the bot token never enters the untrusted environment — does **not** map to Fargate
(no host bind-mount, no `docker exec`; `RunTask` is fire-and-forget). So the model
**inverts**: the Fargate task **is** the isolation boundary, and the *whole* job runs
inside it.

- **In-task** (`sdlc.runtime.fargate.entrypoint`): clone → register the project
  ephemerally → run the existing `JobRunner` with a local (worktree) sandbox →
  implement → validate → commit → push → PR → review, emitting the `RunResult` as one
  contract line in the logs. Reuses the `JobRunner` wholesale (no core surgery).
- **Host** (`sdlc.runtime.fargate.launcher`, called by the `run_job` activity when
  `sandbox='fargate'`): one `RunTask` → wait → read the `RunResult` from CloudWatch.
  Fire-and-forget maps cleanly to one durable activity; a retry is a fresh task, and
  D-16 forge idempotency (find-or-create PR / tag) makes repeats safe.

**Security tradeoff (v1, owner-accepted):** because the task runs the whole job, the
**bot push/PR token lives in the task env**, alongside the agent's arbitrary code —
this **gives up** the local model's "push token never enters the sandbox" boundary.
Accepted while we run **our own** code (the first production project), with the blast
radius bounded: an ephemeral single-repo task and a short-lived (~1h) installation
token. **Hardening before untrusted/third-party (multi-tenant) code:** the task
produces a **git bundle** to S3 and the **host** does the push/PR with the bot token —
restoring the boundary. Tracked as the next security increment; not built now.

Development and unit tests exercise the entrypoint (clone→run against a local repo)
and the launcher (`RunTask`/logs against fake boto3 clients) with no AWS. The live
proof waits on pushing the base image to ECR and wiring Secrets Manager.

## The lifecycle state machine

```
  (board) TODO ─→ SPEC_VALIDATION ─fail→ NEEDS_REFINEMENT (with reason)
                        │ pass
                      READY → PREPARING → IMPLEMENTING → VALIDATING ⇄ REPAIRING(≤N)
                                                              │ pass
                                                           REVIEWING → PR_OPEN
                                                                          │
   ── build phase 1 ends here ──────────────────────────────────────────┤
                                                                          │
                              CI_WAITING → [gate: auto if low-risk+green] → MERGED
                                                              │
                                          STAGING_DEPLOYING → STAGING_VERIFYING
                                              red ⇄ REPAIRING(code) │ rollback+report(infra)
                                                              │ green
                                          [gate: human for prod] → PROD_RELEASING
                                                              │
                                          PROD_VERIFYING ─red→ ROLLING_BACK + notify
                                                              │ green
                                                            DONE
```

`TODO` is intent. Only after `SPEC_VALIDATION` does a ticket become `READY` and be
authorized to consume resources. The **build** is staged: phase 1 delivers idea →
PR (the walking skeleton); the promotion/observation/notification layers (D-12)
land after the spine is proven. The *model* is the full lifecycle; the *build* is
incremental.

## Non-goals for v1 (explicitly deferred behind interfaces)

Implemented later, behind `BoardAdapter` / `CodingAgentAdapter` / `SandboxAdapter`,
but **not built now:** parallelism (v1 is single-process, one ticket at a time),
automatic code-conflict resolution, branch stacking, multi-agent decomposition, a
heavyweight workflow engine, and — pending the board decision — a second board
integration.

## Consequences

- A new repo can be onboarded by a standard act: fill the manifest and pass the
  conformance check. The first production client is not "the project" — it is the
  first instance of conformance.
- Quality is enforced by the floor + presets, not by per-project goodwill.
- The human's remaining job is real decision-making: what to build, how to slice
  it into tickets, and whether a result is acceptable — not authorizing `pytest`.
- Documentation becomes a measurable lever: more/better docs → less human review.
- Open decisions still to be made (each gating some of the build): the v1 board of
  record (GitHub vs. Jira vs. both), the v1 executor engine (Claude Code headless
  vs. Aider vs. both behind the adapter), and the first build slice. These are
  intentionally left out of this ADR and will be decided before implementation.
