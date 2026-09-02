# OpenFactory — Architecture (the big picture)

A presentation-level walkthrough of the whole system. For depth, see [`adr/`](adr/) — 41
decision records, which are where the *why* actually lives. The durable engine realised on one
cloud is drawn in the runtime document that ships with the `openfactory-aws` add-on package,
outside this tree.

---

## 1. What it is, in one idea

An **autonomous software factory**. You drop a ticket on a board; it gets picked up,
implemented, validated, reviewed, merged, and deployed — with no human pressing "yes" at
each step. The control model is inverted:

```
   Interactive AI coding          OpenFactory
   ─────────────────────          ───────────
   human approves every action    policies approve actions
   agent does the work            agent does the work
   "yes… yes… yes…"               human judges the RESULT
```

It **orchestrates** existing coding agents (Claude Code by default, and the others §6 lists) — it is
not a new agent.
It is provider-neutral and multi-project by design.

---

## 2. The three layers (where we are, where we're going)

```
   ┌─────────────────────────────────────────────┐
   │  KNOWLEDGE LAYER      what EXISTS (reality)   │   ← roadmap
   │  a generated, source-linked map of the repo  │
   └─────────────────────────────────────────────┘
                        ▲ consumes
   ┌─────────────────────────────────────────────┐
   │  WORK DEFINITION     what we WANT (intent)    │   ← roadmap
   │  product / BA / architect agents · RFC→Task  │
   └─────────────────────────────────────────────┘
                        ▲ feeds
   ┌─────────────────────────────────────────────┐
   │  EXECUTION LAYER     build it (TODAY, v1.0)   │   ← shipped
   │  planner · executor · gates · merge · deploy │
   │  + the tech-lead                             │
   └─────────────────────────────────────────────┘
```

**Today we have the Execution Layer, proven.** The **Knowledge Layer's first two phases are
built** (`knowledge-layer.md`, ADR-0017) but deliberately dormant — every project has them off
until an A/B shows they lower cost/ticket. The Work layer is still roadmap. Each phase is gated
on measured value, not on being finished.

---

## 3. The execution flow (one ticket, end to end)

```
  board TO-DO
      │
      ▼
  ┌── PRE-FLIGHT ──┐   size the ticket. Too big? → auto-split into children.
  │   (INVEST)     │   Unclear? → ask a human. Fit? → go.
  └──────┬─────────┘
         ▼
     IMPLEMENT  ── a single agent, test-driven, in an isolated ephemeral box
         │
         ▼
     VALIDATE   ── the platform runs the project's OWN gates (test/lint/type/security…)
         │         red? → bounded auto-repair
         ▼
     REVIEW     ── an independent agent posts findings (advisory — doesn't block)
         │
         ▼
     PR → MERGE ── CI-aware: reacts to red CI, keeps the PR fresh, and self-heals a
         │          green-but-unmerged PR. The queue advances only on a clean merge.
         ▼
     DEPLOY     ── observe the project's own deploy, report the outcome
```

**If anything gets stuck** → it **parks** (never a silent hang) and the **tech-lead**
steps in (next section).

---

## 4. The tech-lead — the human interface

When a job hits an impediment, it doesn't just dump an error. A tech-lead agent:

```
   impediment
      │
      ▼
   clone the repo → read the failure + ticket + comments → VERIFY against real code
      │
      ▼
   post a human diagnosis  →  the ticket  +  the panel  (+ a chat channel, if one is connected)
      │
      ▼
   a human answers (resume / skip) — from the panel, or by typing in a connected channel
```

It also **narrates** the factory (picked up #123, merged #124, split #125), and
**answers questions** ("what's the status of X?"). Asking is open to everyone; **acting is what
the asker's own credential allows** — the catalogue decides, per row, and the tech-lead is only
ever offered what that answer contains (`actions.proposable`). Today that is resume, skip, merge
and discard for an operator, and nothing at all for a product credential. A production release is
never among them: it takes an approver and a version, so no ticket-shaped proposal can address it.
**One brain, two triggers: proactive + conversational.**

What it can SEE is the same question one layer down, and it is the one the platform got wrong
longest: the tech-lead reasons from a snapshot of every live job, and a field that reaches that
snapshot must be either shown or explicitly dropped with a reason (`conversation._RENDERED` /
`_NOT_RENDERED`, with a guard over both). Each job carries what it is **waiting on** — by name,
with the pull request's address — what this platform's **own review and gates** concluded about
it, the deploy outcome, the real ticket state and the board column.

---

## 5. Where it runs

**The default is your own machines, and it needs no cloud account at all** (ADR-0040). `docker
compose up` gives you the whole shape below; a cloud is one way to run the same shape at a
different size, never a requirement.

```
     your board  ──trigger──►  ┌───────────────────────────┐
                               │  WORKER  (always-on, tiny) │  orchestrates; hosts the panel
     the panel ◄─────────────► │                            │  and any connected channel
                               └────────────┬──────────────┘
                                            │ launches per ticket
                                            ▼
                               ┌───────────────────────────┐
                               │  BOX  (ephemeral, heavy)   │  clone + build + full test
                               │  sized, then torn down     │  suite + the agent
                               └───────────────────────────┘

     durable engine  ── job state, so a crash resumes exactly where it stopped
     a journal       ── cost + event telemetry, on disk by default
```

**Why this shape:** the agent runs on its vendor's servers, not yours — so orchestration is tiny
and always-on, while the heavy build/test box is ephemeral (you never pay for idle).

**Where each piece can live**, and none of these is the core:

| piece | on your machines (default) | one cloud realisation |
|---|---|---|
| worker + panel | a container in `docker compose` | a small always-on task, plus a hosted web front |
| the box | a throwaway Docker container | an ephemeral cloud task, sized per ticket |
| durable state | the engine running beside the worker | the engine's hosted service |
| telemetry | the journal on disk | a managed table |
| secrets | one `chmod 600` file | a parameter store |

The `openfactory-aws` add-on package carries **one** worked example of that right-hand column, on
one cloud — its `infra/` directory and the documents written in that vendor's own names — because a
reference deployment somebody can read beats a paragraph claiming portability. It is an add-on, not
this tree ([`STATUS.md`](STATUS.md) lists what leaves with it), and reading it as the architecture
is the misreading this table exists to prevent.
**Temporal** makes every job durable: a crash resumes exactly where it stopped.

**What it reaches out to, which is the question a security review asks first.** "Runs on your own
machines" is true about infrastructure and false about the network: there is no account to open and
no managed service to stand up, and the factory still necessarily reaches three destinations.

| destination | why it is irreducible |
|---|---|
| the harness endpoint (`api.anthropic.com`, OpenAI, Moonshot — whichever `harness:` names) | the coding agent IS a remote paid service; this is the product, not a dependency |
| the forge and the tracker (GitHub, Azure DevOps, Jira, and whatever an add-on adds) | working on a remote repository is the definition of the job |
| whatever `setup:` installs (PyPI, npm, NuGet, or a private registry) | the box is ephemeral, so dependencies are fetched per job unless a cache volume is configured |

Three consequences follow, and they are better read here than discovered in production:

- **An air-gapped environment cannot run this.** Not "with difficulty" — the agent has nowhere to
  think.
- **An egress-restricted environment needs an allowlist, and the three rows above are it.** The box
  takes its network from `box.network` in the registry (ADR-0037 D1), so pointing it at a
  restricted network or a proxy is configuration rather than a code change — but the harness
  endpoint must be reachable through it, and a TLS-intercepting corporate CA has to be trusted by
  the client's own image, which is one more reason that image is theirs.
- **The box has full outbound internet by default** (`network: bridge`). `ContainerSandbox`'s
  docstring once claimed a deny-by-default policy it did not have; the true statement is in its
  place — anything the box's network can reach is reachable by code the agent wrote.

---

## 6. Provider-neutral by design (no lock-in)

Every external dependency is behind an **adapter**, and every adapter is chosen by a **registry**
from the project's configuration — `kind → builder`, unknown kind raises. No module outside a
provider's own package names a concrete class; an AST test enforces it (ADR-0022).

```
   axis        protocol              ships in the core                                          a third one
   ───────────────────────────────────────────────────────────────────────────────────────────────────────────
   harness     CodingAgentAdapter    claude_code · codex · kimi · opencode                      harness.<kind>
   tracker     TrackerAdapter        github · jira · azure_devops                               tracker.<kind>
   board       BoardAdapter          github · jira · azure_devops                               board.<kind>
   forge       ForgeAdapter          github · azure_devops                                      forge.<kind>
   CI/deploy   EnvironmentObserver   github_actions · azure_pipelines                           ci.<kind>
   channel     ChannelAdapter        panel · slack (an add-on package: openfactory-slack)       channel.<kind>
   notifier    Notifier              panel · slack · telegram (an add-on package: openfactory-slack)   notifier.<kind>
   sandbox     SandboxAdapter        container · worktree · a cloud box (an add-on package: openfactory-aws)   box.<kind>
```

**Adding a third is an entry point, not a pull request.** A package declares `<axis>.<kind>` —
the axis spelled as in the last column, the names `openfactory/plugins.py::AXES` publishes — in
the `openfactory.adapters` entry-point group; its rows join the registry's table at lookup time,
a built-in row wins a collision, and an unknown kind still refuses by name
([`core/07-extensibility.md`](core/07-extensibility.md) §2). The maintainers' own cloud box and
chat channel arrive exactly that way (`openfactory-aws`, `openfactory-slack`);
[`STATUS.md`](STATUS.md) lists which paths of this tree leave with them.

**The bar is "born with two", not "has an interface".** An axis with one implementation and a
Protocol is agnostic on paper and single-vendor in the composition root — which is exactly what an
audit on 2026-07-28 found: `GitHubIssuesTracker` constructed by name in twelve places, `GitHubForge`
in eleven, and the board not existing as a concept at all. Protocols are `@runtime_checkable` and
the tests use `isinstance`, because a protocol nobody checks is documentation.

**The STACK needs no adapter and never did.** The platform names no build command — no `mvn`,
`dotnet`, `composer`, `npm`. The client's manifest declares `validate:` and the framework runs what
it is given, so Java, PHP, C#, Python and serverless deployments work with nothing new. This is what
a solved axis looks like.

**GitLab is deferred by decision, and no stub adapter exists** — an empty module nothing exercises
is this repository's signature defect (see `engineering-lessons.md` §1). Today a `gitlab` kind fails
at startup naming what IS supported, which is more useful than authenticating against the wrong
host. **Telegram is not a channel kind at all**: it is a notifier row (`notifier.telegram`) the
`openfactory-slack` add-on package declares, reached only as the deployment-wide fallback — the row
`OPENFACTORY_NOTIFIER_FALLBACK=telegram` declares for a caller with no project of its own; the two
variables it reads switch nothing on by themselves — and its module leaves the public tree with the
chat connectors.

One workflow, many projects: a new project is **data, not code** (register it + a
`.openfactory/project.yaml` manifest). One deployment hosts N projects, each isolated — its own
repository, its own board, and its own channel where one is connected.

---

## 7. The invariants (what makes it trustworthy)

- **Never a silent hang.** Every stall either self-heals (bounded) or parks and asks a
  human with executable options. Silence is never "success".
- **Nothing lost.** Durable workflows + preserved partial work — a crash mid-job costs
  nothing and never duplicates (no double PRs/merges).
- **The floor frees at merge, not at agent-done** — the next ticket builds on a base that
  includes this one (dependency safety).
- **Quality is a floor, not goodwill** — a project cannot switch off the gates the
  framework requires.
- **The code is the source of truth** — agents verify against real files; the knowledge map
  accelerates finding code and never replaces reading it. A map that cannot be proven fresh
  against the agent's own checkout is not served at all.
- **Everything is attributed to the bot**, never a human. Least privilege throughout.

**What "asks a human" looks like from the outside.** These five are what a self-hosting operator
meets in the first week; each is the factory working, not the factory broken.

| what you see | what it means | what to do |
|---|---|---|
| a card in **Needs Action** | the ticket's latest **comment** says why — a refinement question, a spent effort budget, an authorization failure | act on the comment. From the panel: **Resume** (a resumable hold *continues* the preserved work) or **Skip** (free the floor). A refinement question is answered by editing the ticket and dragging it back to TO-DO |
| a **"pre-flight sizing did not run"** comment | the sizing gate DEGRADED: it could not judge (harness token missing on the worker, a clone or sizer error, a garbage verdict), so the ticket ran UNSIZED | the gate is broken, not the ticket. The worker's log carries `OPENFACTORY_PREFLIGHT: DEGRADED` and the cause — usually the worker's own harness token. The ticket still ran (degrade-safe); do not read its size as clean |
| a ticket **split into `Plan Na` / `Nb`**, parent closed | pre-flight judged it too large to be one INVEST ticket | nothing. The children are already in TO-DO and run in order. Reopen or merge back only if the split was wrong |
| **ON_HOLD, "effort budget exhausted"** | the ticket out-ran `effort_budget_turns` even after recovery (ADR-0013) | the partial work is on the branch and is resumable. **Decide:** split the remainder into a follow-up, or raise `effort_budget_turns` and Resume. Never "go read the code" |
| **`.okf/repos/<owner>--<name>/`** appears in the project's CONTEXT repository (never the driven repo itself) | the knowledge pipeline (ADR-0017) publishing the generated module map — `modules.yaml` + `manifest.yaml`, never product code, one commit per merge that changes sources | nothing. It requires `product.docs_repo` to be set (`openfactory onboard`); with none, the refresh is a no-op. To stop it, set `knowledge_map: false` in that project's `.openfactory/project.yaml`. It never touches the driven repo and never triggers its deploy |

---

## 8. You can see everything

- **Web panel** (live, SSE): the floor, each job's pipeline, what needs attention, one-click
  resume/skip, prod-approval.
- **Cost dashboard** (per project): spend by period / model / harness, and **time + cost of
  every task** — the ruler we measure improvements with.
- **A chat channel — an ADD-ON, never required** (ADR-0038): the same narration, diagnoses and
  Q&A the panel already carries, delivered where a team already talks. The chat connector is an
  add-on package (`openfactory-slack`), not part of the core; nothing in the platform depends on
  it, and no capability lives only there.
- **The durable engine's own UI** (internal): deep workflow debugging, for free.

---

## 9. Where it's going

The dashboard isn't just reporting — it's the **instrument** that gates the next tier. The
**Knowledge Layer** is built as far as a deterministic module map (Phase 1) regenerated on every
merge and persisted in the client repo (Phase 2a) — and it is **off everywhere** until it
**measurably lowers cost/ticket**. Building it was cheap; turning it on is the decision the
numbers make. Then APIs/schema/ADRs → business rules → the Work Definition Layer with product
agents. The cathedral gets built one proven stone at a time.

---

## 10. Status

**v1.0.0** — proven in production: hundreds of tickets shipped autonomously, multi-ticket
plans decomposed + built + merged + deployed, the tech-lead diagnosing live, real per-task cost
telemetry flowing. The Knowledge Layer's first two phases sit on
top of this base, opt-in and unproven — awaiting their A/B.
