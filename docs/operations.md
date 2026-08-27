# Operations — how a job actually runs

This is the practical companion to `docs/adr/0001` (the *why*). It documents the
*how*: what runs where, which credentials live where, what the dependencies are, and
how to onboard and run a project. Keep it current — this is the map when something
breaks.

## What runs where (and why it matters)

The single most important operational fact: **the untrusted-code environment (the
sandbox) holds only the agent's model token. Everything that can touch the board,
the remote, or a merge runs on the host, with host credentials.**

| Component | Runs on | Credentials it uses |
|---|---|---|
| Orchestrator (`JobRunner`) | host | — (coordinates) |
| Tracker (`gh issue view/edit/comment`) | host | `gh` auth (board token) |
| Forge PR (`gh pr create`) | host | `gh` auth (forge token) |
| Branch push (`git push`) | host | host git creds (SSH key / gh helper) |
| Sandbox (worktree/container) | host daemon | — |
| **Agent (the executor role, on whichever harness serves it)** | **inside the sandbox** | **the harness credential only** |
| Validation commands | inside the sandbox | — (test config / stubs) |

Why: the agent runs arbitrary code autonomously. If the board/forge/merge token
were reachable from there, a bad run could move production. So those stay on the
host; only the harness's own credential is injected into the sandbox, and only for the job's
lifetime. This is the ADR floor made real, not a prompt.

**The role is the axis; a vendor's binary is not.** Which harness runs the executor is a registry
entry (`openfactory/adapters/agent/registry.py` → `HARNESSES`), and which variable carries its
credential is that harness's business — `box.env` names what the box may receive. This page names
roles for that reason; where it shows a concrete variable, that is one deployment's answer and not
the platform's.

## The run flow (one ticket)

Maps 1:1 to the `JobState` machine. `openfactory run <project> <issue>` drives:

1. **get_ticket** — host: `gh issue view` → parsed into a `Ticket`.
2. **SPEC_VALIDATION** — host, deterministic: acceptance criteria present? no
   scope contradiction? Fail → `gh` labels the issue `openfactory:needs_refinement` + a
   comment with the reason, and the job stops.
3. **PREPARING** — the sandbox is created: an ephemeral clone/worktree on a fresh
   `openfactory/<issue>` branch off the manifest's `base_branch`.
4. **IMPLEMENTING** — the **executor** role runs *inside* the sandbox, on whichever harness
   this project declares, and edits code.
5. commit — the orchestrator commits the agent's work on the branch.
6. **VALIDATING** — the platform (not the agent) runs the manifest's validation
   commands in the sandbox and reads exit codes. Touched components come from the
   real diff.
6b. **REPAIRING** (bounded) — if validation fails, the agent gets up to
   `repair_max_attempts` fix passes (each: repair → commit → re-validate). Only if it
   still fails does the job fail.
7. **REVIEWING** (optional) — the **reviewer** role, read-only, gets only
   spec+diff+validations → a structured verdict.
8. **push + PR_OPEN** — host pushes the branch and opens the PR (`gh pr create`);
   the PR body carries the validations, the review, touched components, and cost.
   The issue is labelled `openfactory:pr_open`.

Beyond the PR (D-12 — **built**): merge→staging, tag→prod, observe, notify. It is
`openfactory/orchestrator/promotion.py` → `PromotionRunner`, built by `openfactory/factory.py`
and driven post-merge: `promote()` walks every pre-production stage the manifest declares, in
order, observing each; then it **stops** and parks at `AWAITING_PROD_APPROVAL`, because
production is a person's gesture whatever the client calls it. `release_prod()` tags, observes,
and on a red production rolls back. A project that declares no environments finishes at the merge
and is told so, rather than parking on a gate nobody can open.

## Visibility & no silent hangs

The headless agent is **not** a black box, and stalls fail loudly:

- **Transcript.** The agent runs with `--output-format stream-json --verbose`; every
  action (edit, command) is a JSON event. The full stream is captured and, when a
  `log_dir` is set, written per job to `<repo>/../.openfactory-logs/<project>/<issue>-execute.jsonl`
  (and `-repair.jsonl`). That file is the record of exactly what the agent did.
- **`--max-turns`** caps the agent loop — it cannot run forever.
- **Timeout.** Every `sandbox.run` has a timeout; a hang is killed and surfaces as a
  failed job, never a silent stall.
- **Explicit permissions.** `--permission-mode acceptEdits` + `--allowedTools`:
  anything outside the grant is denied, not left waiting on an approval nobody will
  give.

### The job journal (structured, queryable)

Beyond the raw transcript, every meaningful step is emitted as a structured
`JobEvent` (kind = state / agent_action / validation / review / pr / note / error)
to a pluggable sink. The CLI writes them to
`<repo>/../.openfactory-logs/<project>/<issue>-events.jsonl`. This is the backbone for
"ask the framework how development is going — including what the agent is doing":
the agent's tool uses (e.g. `Edit: app/health.py`, `Bash: pytest`) are journaled as
`agent_action` events, so a future conversational surface (and the evals layer) can
answer from structured data instead of scraping logs. Sinks are pluggable —
file/in-memory now, Postgres later — behind one `EventSink` Protocol.

Speed note: the first run is slow (cold caches — `pip install` / `npm ci` + the
full suite). A **persistent dependency cache** is available and off unless you ask for it: set
`box.cache_volume` in the project's registry entry and the container box mounts that Docker
volume at `/cache` (`openfactory/adapters/sandbox/container.py`), so it survives every job while
the code state stays ephemeral. It is unset by default because sharing one cache across projects
is a deployment's decision — a shared volume is a channel between two clients' builds.

**Mounting it is all the platform does.** Nothing here redirects a package manager into `/cache`:
that is the project's `setup:` commands and the variables its `box.env` names (a `PIP_CACHE_DIR`
or an `npm_config_cache` pointing at `/cache`). Declaring the volume and expecting the install to
get faster on its own buys an empty directory.

## Prerequisites

Host tools (the orchestrator shells out to these):

- **Python ≥ 3.12** (the platform itself; `pip install -e '.[dev]'`).
- **git** — worktrees, clones, push.
- **Docker** — only for `--sandbox container` (the production path).
- **`gh`** — the GitHub CLI, authenticated (`gh auth login` or `GH_TOKEN`). This is
  the board + forge credential. Least privilege for a real deployment: a bot
  account / GitHub App with issues:write, pull_requests:write, and push to feature
  branches — **not** merge on protected `main`.
- **a harness** — the CLI the roles run on, and which one is a registry entry
  (`harness:`, per project or per role). `openfactory/adapters/agent/registry.py` →
  `harness_binary` answers which executable a kind shells out to, and
  `openfactory doctor <project>` reports it missing by that name rather than by a fixed one.
  Its credential is its own: `box.env` names the variables the box may receive, so a deployment
  that authenticates through a gateway declares that instead. For the container path the
  variables are injected as env into the container; for the worktree path they must be in the
  host env.

## Board access, concretely

- **Read:** `gh issue view <n> --repo <owner/name> --json number,title,body`
- **Move:** the card's **Status column** is the movement. `set_state` asks the board first
  (`openfactory/adapters/tracker/github_project.py` maps every `JobState` to a column name), and
  only when there is no board, or the board refused the move, does it fall back to the
  `openfactory:<state>` label — `gh issue edit <n> --add-label openfactory:<state>` — and log
  `OPENFACTORY_BOARD_MOVE_FAILED`. The fallback exists because a card stuck in its old column
  while the platform records the transition as done is a silent forever-wait for whoever watches
  the board. Both live behind the one `TrackerAdapter.set_state` seam
  (`openfactory/adapters/tracker/github.py`), plus `gh issue comment` on refinement.
- **PR:** `gh pr create --repo <owner/name> --head openfactory/<n> --base <base> ...`

Provider axes are independent (`tracker` / `forge` / `ci`): GitHub fills all three
here, but a project may set e.g. Jira tracker + GitLab forge in its registry entry.

### The board columns (Status options) — names must match EXACTLY

The framework moves a card by matching `STATUS_MAP` to the board's Status **option
names, case-sensitively** (`openfactory/adapters/tracker/github_project.py`). A GitHub Projects
board driven by the framework needs these six single-select Status options:

| Column | What it means | Who acts |
|---|---|---|
| **Backlog** | Not started; not yet queued. | you (drag to TO-DO to run) |
| **TO-DO** | Queued — the poller picks these up (one at a time). | the framework |
| **In progress** | Running (or a rate-limit **pause**, which auto-resumes). | the framework |
| **In review** | PR open / merged / promoting — being overseen. | the framework |
| **Needs Action** | **Parked, waiting on YOUR decision** — the ticket comment says what. | **you** |
| **Done** | Completed. | — |

**`Needs Action` is required.** `openfactory project init` creates a NEW board with all six
options; on an **existing** board add it **by hand in the GitHub UI** — the API mutation that
edits a Status field (`updateProjectV2Field`) re-mints every option id and drops every card's
Status assignment, which is worse than the click it saves. Name it exactly `Needs Action` (a
red colour, placed after *In progress*, reads best). It's where `needs_refinement` / `on_hold` /
`failed` land, so a ticket that needs you never hides among the un-started Backlog items.
Until the column exists, those states **fall back to Backlog** (safe, old behaviour) — so a
missing column degrades, it never breaks; but you lose the at-a-glance "these need me".

## Bot identity & credentials (provider-agnostic)

The agent acts as a **distinct bot identity**, not as you. Two separate pieces:

- **Actor** — `OPENFACTORY_BOT_NAME` / `OPENFACTORY_BOT_EMAIL` (the git commit author). Falls back
  to "OpenFactory Bot" / `openfactory-bot@localhost` (`credentials.bot_identity`).
- **Credentials — one per axis** (the axes are independent):
  `OPENFACTORY_BOT_TOKEN` is the default for all; `OPENFACTORY_TRACKER_TOKEN` / `OPENFACTORY_FORGE_TOKEN`
  override per axis when providers differ (e.g. Jira tracker + GitLab forge). Each
  token is opaque; how it's minted is per-provider (GitHub App installation token,
  GitLab access token, Jira API token, bot PAT). Tokens come from the env, never the
  registry. `None` → ambient CLI auth (dev only).

Least privilege on these tokens is the real control: a bot whose token cannot merge
protected `main` cannot merge it, regardless of what any prompt says.

The **coding-agent** credential pool (`OPENFACTORY_AGENT_TOKENS`) is separate from these bot
tokens, and its rotation / rate-limit-pause / resume behaviour has exact rules — see
[`rotation-and-retention.md`](rotation-and-retention.md) (which also documents the image
prune/retention rules). The core never reads an agent token; it only round-trips opaque
`credential` (panel visibility) and `resume_handle` (session continuation) values.

### Getting the token from a GitHub App

1. Create and install the App per **[docs/setup/github.md](setup/github.md)** — the
   permission table lives there and only there (this page used to carry a third, divergent
   copy; a guard test now forbids that).
2. Come back with the **App ID**, the **private key** (.pem) and the **Installation ID**.
3. App installation tokens are short-lived (~1h), so mint one on demand:

   ```bash
   export OPENFACTORY_GH_APP_ID=...            OPENFACTORY_GH_APP_KEY=~/openfactory-bot.pem
   export OPENFACTORY_GH_APP_INSTALLATION_ID=...
   export OPENFACTORY_BOT_TOKEN=$(openfactory bot-token)   # RS256-signs an App JWT, exchanges it
   export OPENFACTORY_BOT_NAME="OpenFactory Bot"  OPENFACTORY_BOT_EMAIL="openfactory-bot@yourco.com"
   ```

   (A bot PAT in `OPENFACTORY_BOT_TOKEN` works too, skipping the mint — simpler, less clean.)
   Token acquisition is GitHub-specific and lives in the GitHub adapter; the core only
   ever sees the opaque `OPENFACTORY_BOT_TOKEN`.

### PR posture (merge policy)

Default `merge_policy: human` — the bot opens the PR, posts the reviewer's verdict
as a real PR review, requests the manifest's `reviewers`, comments the ticket, and
stops (card → In review). `merge_policy: auto` merges only when the review is not
rejected, all validations pass, and no touched component is high-risk.

Under `auto`, the bot **merges on the current base** (ADR-0003): right before merging it
rebases the branch onto the latest base; if the base moved it re-runs every gate on the
rebased result and re-pushes, then merges. A textual conflict or a failed re-validation
holds for a human — it never crashes.

### Branches the platform creates in a driven repo

- `openfactory/<issue>` — one per ticket, squash-merged then deleted. Expected.
- `openfactory-knowledge` — **unless the project declares `knowledge_map: false`** (ADR-0017,
  default flipped to `true` by ADR-0035). Holds the
  generated module map (`knowledge/*.yaml`) and nothing else: no product code, never merged into
  `main`, one commit per merge that changes sources. It is deliberately NOT on `main` — a commit
  there would trigger the repo's own deploy and put every open PR behind. Safe to delete at any
  time; the next source-changing merge republishes it, and no job depends on it — since ADR-0023 a
  job derives its own map from its own checkout. Leave it OUT of branch protection.

### Branch-protection standard (driven repos)

Set this once on the default branch of every repo the platform drives — it enforces the
PR flow without blocking autonomy (ADR-0003):

```bash
gh api -X PUT repos/<owner>/<repo>/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": null,
  "enforce_admins": false,
  "required_pull_request_reviews": { "required_approving_review_count": 0 },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

- **PR required, 0 approvals** — every change goes through a PR, but a required *human*
  review would break autonomy; the pipeline's automated review + gates are the quality bar.
- **Linear history** — squash/rebase merges only (the bot squash-merges).
- **Grant the bot GitHub App "Checks: Read"** — the CI-aware loop reads the PR's check
  states (`forge.pr_ci_status`); without this permission the App gets "Resource not
  accessible by integration" and the loop can't see a red CI (it degrades to the merge-only
  happy path, never crashing — but the *repair* trigger stays dormant). Set it in the App's
  settings → Repository permissions → **Checks: Read-only**, then accept the permission on
  the installation.
- **Enable repo "Allow auto-merge"** — `gh api -X PATCH repos/<owner>/<repo> -f
  allow_auto_merge=true`. Without it, `gh pr merge --auto` cannot arm and the merge fails
  ("base branch policy prohibits the merge") the moment required CI is still pending — the job
  holds instead of waiting. This bit us live (a production client had it off); it's part of the standard.
- **Require the CI status checks** (ADR-0004) — with the CI-aware repair loop in place, a red
  CI on the bot's PR is *reacted to* (repaired), not merged past. Set `required_status_checks`
  with `strict: true` and the check contexts. **This is per-project config, never baked into
  the framework** (the platform reads whatever checks exist via `pr_ci_status` — zero coupling
  to any project's check names). Two rules when choosing the contexts:
  - **Only checks that run on EVERY PR.** A path-filtered or otherwise conditional check
    (e.g. a `terraform` job gated on `paths:`) would sit `pending` forever on a PR that
    doesn't trigger it — a dead block. Exclude those.
  - **Prefer deterministic checks.** A flaky check (e.g. slow end-to-end) makes the CI-repair
    loop chase failures that aren't code bugs. Require the fast, reliable gates; leave flaky
    ones advisory.
- **Admins not enforced** — an operator can still intervene by hand.

Also enable **auto-delete of head branches on merge** (repo setting, not branch protection),
so merged `openfactory/<id>` branches don't accumulate — the remaining `openfactory/*` branches then always
equal the open PRs, which keeps "what's in flight" readable at a glance:

```bash
gh api -X PATCH repos/<owner>/<repo> -f delete_branch_on_merge=true
```

## Ticket format

Tickets are GitHub Issues. The body uses optional YAML front-matter + markdown
sections (the parser is `openfactory/adapters/tracker/parse.py`):

```markdown
---
depends_on: ["#134"]
base_branch: main
relevant_docs: ["docs/architecture/reconcile.md"]
---
## Objective
One clear sentence of what to build.

## Acceptance criteria
- a verifiable statement
- another one (ideally test-backed)

## Out of scope
- things the agent must not touch
```

No acceptance criteria → the SPEC_VALIDATION gate bounces it to refinement.

## Validation is whatever the manifest declares (no `make` assumption)

The framework never assumes `make`. It runs the strings in the manifest's
`validate:` block (and the stack preset's defaults). `myapp` happens to
declare `make test` etc. because it already has those targets; a project without
`make` declares `pytest` / `npm test` / `go test ./...`, or leans entirely on the
stack preset (a `stack: python` component gets `pytest`+`ruff`+`bandit` for free).

## Base images (container path)

One image per stack, project-agnostic, with the toolchain + git preinstalled (the repo is mounted
at run time, never baked). `docker/base-python.Dockerfile` also installs the `claude` CLI at a
pinned version, which is a convenience of the image the platform ships and not a requirement of
the platform: under ADR-0037 D2 the worker copies a **toolbox** out of its own image into a
volume and mounts it read-only into every box, so a harness that is not in the image still
resolves. A box with neither is a named finding from `openfactory box prove`, not a mystery.

```bash
docker build -f docker/base-python.Dockerfile -t openfactory-python .
```

`ContainerSandbox` overrides the image ENTRYPOINT to keep the container alive and
marks the mounted workspace as a git `safe.directory` (host-owned bind mount).

### On a network that re-signs HTTPS

If your organisation terminates outbound TLS (Zscaler, Netskope, a corporate proxy), the images
above will not build: the proxy presents a certificate signed by a root no public image ships,
and every `pip install` / `npm install` dies on `CERTIFICATE_VERIFY_FAILED`. **`apt` usually
survives** — Debian's mirrors are plain HTTP — so the failure lands on the second network
instruction and reads like a broken package rather than a broken trust store.

Put your root certificate in `docker/extra-ca/` and build normally:

```bash
cp /path/to/your-corporate-root.crt docker/extra-ca/
docker compose --env-file .env.compose up -d --build
```

Every image that fetches copies what it finds there into the system trust store and points `npm`
and `pip` at the result; the box also exports `NODE_EXTRA_CA_CERTS`, so the CLIENT's own
`npm ci` trusts it at run time and not only during the build. With no `.crt` there the block is a
no-op and the build is what it always was. `docker/extra-ca/README.md` has the rest, including
the two variables to add to `.env.compose` for the worker's own **runtime** calls — `httpx` and
`requests` read `certifi`'s bundle rather than the system store, so an image alone does not fix
them.

### …and one where port 80 does not finish

The same networks tend to inspect 443 and throttle 80, which is what Debian's mirrors use by
design. The shape of that failure is worth recognising, because it does not look like a network
problem: `apt-get update` succeeds, most of the archive streams, and the install then dies on

```
E: Failed to fetch http://deb.debian.org/…/npm_9.2.0~ds1-3_all.deb
   Unable to connect to deb.debian.org:http [IP: 146.75.90.132 80]
```

Point `apt` somewhere reachable — Debian over https, or your own mirror — with one row in
`.env.compose`:

```
DEBIAN_MIRROR=https://deb.debian.org
```

**Set the CA first.** An https mirror cannot be verified by an image that does not yet trust the
root your proxy presents, and that failure is the least informative one in this document: apt
returns no package lists at all and every install line then reports `E: Unable to locate package
git`, which reads like a broken mirror rather than a missing certificate.

## Web panel (observability + management)

```bash
openfactory serve            # http://127.0.0.1:8787
```

A self-contained page (no build step) served by FastAPI. It reads the registry
(projects) and the job journal (what each job is doing, live via SSE) and triggers
runs — it is a *view* over the journal, not a separate system. From the panel you
can: register a project, trigger a job, watch the live event feed of the agent's
actions, and jump to the PR. The API (`/api/projects`, `/api/jobs`,
`/api/jobs/{project}/{issue}/stream`) is the same data any richer UI would consume.

## Onboard and run

```bash
openfactory project add myapp ~/Projects/myapp --provider github --repo yourorg/myapp
openfactory project init myapp             # scaffold .openfactory/project.yaml (then edit it)
openfactory conformance myapp              # required slots filled? (floor: test + security)
openfactory run myapp 142 --sandbox container      # drive issue #142 end-to-end
```

**Board setup (one-time, per project's GitHub Projects board):** the Status field must have
the six options above — `openfactory project init` creates a new board with all of them; on an
existing board **add `Needs Action` by hand** (editing the Status field by API re-mints every
option id and wipes assignments; exact name, red, after *In progress*). Record the board in the
registry entry (`board_owner` + `board_number`). Without the column the framework still runs;
parked tickets just fall back to Backlog instead of `Needs Action`.

## What the framework decides before it runs a ticket (ADR-0013)

Dropping a ticket into TO-DO no longer goes straight to execution. On the **worker**, before
any sandbox is launched, a **pre-flight sizer** judges the ticket by **INVEST** — is it one
cohesive, independent, testable outcome? (File count is *not* a criterion.) Then:

- **fit** → runs normally (plan → code → validate → review → PR).
- **split** → the ticket is **decomposed autonomously** into `Plan Na` / `Plan Nb` children
  (full acceptance criteria, ordered), which go **straight to TO-DO in order**; the parent is
  closed. Single-line strict runs them one at a time, each on the prior child's merge — so a
  dependency between them is safe with no `depends_on`. (`split_to_todo: false` keeps children
  in Backlog for manual sequencing.)
- **unclear** → parks in **Needs Action** with questions; you clarify, then Resume.

If a well-sized ticket still stops mid-work (the agent gets stuck / hits the per-invocation
turn cap), it does **not** go to a human first: a bounded **recovery ladder** (continue the
same session, then a fresh recovery pass that may *simplify* scope) tries to finish it, all
within a **ticket-wide effort budget** (`effort_budget_turns`). Only when that's exhausted does
it park in **Needs Action** — with a *decision-shaped* message (split the remainder, or raise
the budget and Resume) — and the partial work is always **preserved** on the branch, never
discarded. See ADR-0013 and `docs/rotation-and-retention.md`.

## Where configuration lives

- **`~/.openfactory/registry.yaml`** — the project registry (host-global): name, repo path,
  provider axes. Managed by `openfactory project`.
- **`<repo>/.openfactory/project.yaml`** — the project manifest (versioned in the project
  repo): setup, validation commands, docs roles, components, risk. This is the
  project's plug into the contract.
- **Framework-owned:** `openfactory/presets/*.yaml` (stack defaults), `openfactory/org_defaults/`
  (org guidelines), `openfactory/policy/floor.py` (the non-negotiable floor).
