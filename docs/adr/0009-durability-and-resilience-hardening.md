# ADR 0009 — Durability & resilience hardening (post-audit)

- **Status:** **Accepted; shipped** (commit `efa93e4`) and **live-validated** (4-ticket run on a
  production client: 2 clean merges, 1 CI-repair, 1 e2e — all passed; the new `check_pr_status`
  activity ran in production).
- **Date:** 2026-07-17
- **Relates to:** ADR-0004 (CI-aware repair), ADR-0005 (deploy-watch), ADR-0007 (floor frees at
  merge), ADR-0008 (on-demand e2e), ADR-0001 [D-12/D-16]. Operational fallout (the deploy that
  destroyed the panel) is in `docs/runbook.md`.

## Context

Before running real tickets at volume, we ran a **deliberate adversarial audit** — five
independent passes (security, state-machine, concurrency, resilience, runaway/cost) — and
verified every serious finding directly in the source. The theme: the happy path was solid, but
several failures only bite **in production, over time** — a PR that sits for days, a human who
closes instead of merges, a GitHub blip during a long durable wait, a second CI-repair attempt,
a typo in a manifest. These are exactly the "surprises" a serial, single-floor autonomous system
cannot afford, because one stuck workflow freezes the whole queue.

This ADR records the decisions taken. Each fix shipped with a test; the set was proven live.

## Decisions

### 1. A closed-unmerged PR frees the floor immediately (finishes ADR-0007)

ADR-0007 said the workflow waits "until it merges **or is closed**" — the *closed* half was
never built. `_ci_merge_loop`/`_wait_for_merge` only checked `mergedAt`, so a human who **closes
a PR without merging** left the workflow polling until `merge_deadline_days` (14d) — freezing the
single-slot floor for two weeks on a PR that will never land.

**Decision:** read the PR **lifecycle state** (`merged` | `closed` | `open`) in one activity
(`check_pr_status`, forge `pr_status`). A `closed` PR → `ON_HOLD` **at once** ("closed without
merging — needs a human"). Applies to both the CI-watch loop and the promotion wait.

### 2. Adaptive merge-watch poll backoff — NOT `continue_as_new`

At the 2-minute poll, a human-gated PR that sits for days accrues ~11.6k Temporal **history
events/day** (activity + timer triplets). Temporal's hard ceiling is ~51.2k events; the server
**terminates** the workflow around day ~4-5 — with no `ON_HOLD`, no notification, no cleanup —
long before the 14-day deadline it promises.

**Decision:** widen the poll after the PR has been open a while — `_CI_POLL` (2 min) for the
first `_CI_FAST_WINDOW` (1 h, to keep auto-merge + CI-repair prompt), then `_CI_SLOW_POLL`
(15 min). 14 days then ≈ 23k events, comfortably under the ceiling.

**Rejected: `continue_as_new`.** The textbook fix for history growth is unsafe *here*:
`continue_as_new` restarts `run(params)` from the top, which would re-run `_stamp_title` and
**re-invoke the agent** (`run_job` is one coarse, single-attempt activity — re-running it costs
money and duplicates PRs/comments). The workflow is not structured to carry "PR already open,
just resume the merge watch" across a restart. Backoff achieves the durability goal without that
risk. (If we later split `run_job` into finer idempotent activities, `continue_as_new` becomes
viable — revisit then.)

### 3. Degrade a transient GitHub failure, never crash the durable wait

`check_ci_status` already degrades to `"unknown"` on a read failure, but the merge check was
unwrapped: a ~15-second GitHub outage during a days-long watch exhausted the retry budget → the
activity failed → the workflow FAILED, losing a durable wait whose PR was fine.

**Decision:** wrap the status poll and **degrade to `"open"`** (keep waiting) on any exception —
the same "react/degrade, don't crash" posture as the CI read. A brief outage is a no-op.

### 4. CI-repair idempotency is scoped **per attempt**

The Fargate launcher's idempotency key is `job_tag + SDLC_RUN_ID` (the workflow run id — constant
for the whole run). That makes activity **retries** converge, but it cannot tell a retry from a
**legitimate second `repair_ci` invocation** within the same run: attempt 2 finds attempt 1's
STOPPED task (ECS retains it ~1h ≫ the 2-min poll), same key, a reconcilable `pr_open` result →
**returns the stale result without launching anything**. The budgeted cap of 2 repair attempts
was silently **1**.

**Decision:** fold the attempt number into the idempotency scope — `repair_ci` stamps
`SDLC_RUN_ID = f"{workflow_run_id}-r{attempt}"`. Retries of one attempt still converge; a new
attempt reads as a distinct run and launches fresh.

### 5. A CI-repair that PAUSES resumes durably — never ends silently

If the agent hit a usage limit **during** a CI-repair, `_ci_merge_loop` returned the `PAUSED`
result as terminal — the workflow completed `PAUSED`, and **nothing resumes it** (the durable
resume loop only wrapped the initial `run_job`).

**Decision:** the CI-repair loop resumes a `PAUSED` repair durably (sleep `_PAUSE_BACKOFF`, retry,
bounded by `_MAX_PAUSE_RESUMES`), mirroring `run_job`. A pause does **not** consume a repair
attempt.

### 6. The suppression guard also covers the CI-repair path

The gate-suppression guard (engineering.md #12: a diff that adds `# noqa` / `pragma: no cover` /
`type: ignore` / `nosec` must not auto-merge) ran only on the main `run()` path. But a **CI-repair
re-pushes to an already-armed `--auto` PR** — so an agent that made CI green the wrong way (by
silencing a gate) would ride onto `main` when CI next passed.

**Decision:** `repair_ci` recomputes `_added_suppressions` on the repaired diff; if a gate was
silenced it **disarms auto-merge** (`forge.disable_auto_merge`), requests reviewers, and holds for
a human. *(Validated live: the repair agent instead correctly **deleted** the injected failing
test, so the guard didn't need to fire — but it is now the backstop if an agent ever cheats.)*

### 7. Cleanup sweeps the `-ci-repair` task variant

`stop_tasks`' `VARIANTS` listed `("", "-staging", "-release")` but **not** `-ci-repair`. A
cancelled/failed workflow left an orphaned repair task running to its own timeout — and its final
act is `publish_branch`, i.e. it could **push commits to a PR after the job was abandoned**.
Triple-confirmed by three independent audit passes.

**Decision:** `VARIANTS = ("", "-ci-repair", "-staging", "-release")`.

### 8. The agent workload never sees the whole token pool

`_scrubbed_env` stripped ambient AWS + forge credentials but **not** `SDLC_AGENT_TOKENS` — the
entire Claude **failover pool** was inherited by the sandbox subprocess, so a compromised agent
(or the project's own app/tests booting in the sandbox) could exfiltrate **every** token at once.

**Decision:** strip `SDLC_AGENT_TOKENS` too. The framework reads the pool in its **own** process
and delivers only the single active token to the CLI via `CLAUDE_CODE_OAUTH_TOKEN`. The prod path
is the worktree sandbox, so this closes it in production.

### 9. A manifest typo fails loud, and unbounded fields are bounded

Pydantic defaulted to `extra="ignore"`, so a typo (`max_cost:` for `max_cost_usd:`) was silently
dropped and the default silently applied — a runaway/mis-scoped job waiting to happen.

**Decision:** `extra="forbid"` on the manifest models (a typo is a load error, in the Fargate task,
before any agent runs) + bounds on the fields that can themselves cause a history bomb or nonsense
(`PostMergeDeploy.timeout_minutes ∈ [1, 720]`, repair/review-repair attempt caps ∈ [0, 10]).

### 10. `scan_now` counts an already-running ticket against the floor

The manual "Scan TO-DO" endpoint's guard was check-then-act: on `AlreadyStarted` it fell through
to the **next** ticket, so a double-click (or a scan racing the poller tick) could start a second
job on a floor of one — the dedup meant to save the race instead *redirected* it.

**Decision:** count an `AlreadyStarted` skip against the slot budget (`claimed`) — an occupied slot
is occupied whoever filled it.

## Consequences

- **The queue can no longer be frozen** by a closed PR, a days-long wait, or a transient GitHub
  outage — the three ways one stuck workflow used to jam a serial floor.
- **CI-repair is honest**: two real attempts, resumes through a rate-limit, and cannot launder a
  silenced gate onto `main`.
- **Config is fail-loud**: a typo is caught at load, not discovered as a runaway weeks later.
- **The token pool is contained** to the framework process.
- **Cost of the backoff:** a red CI on a long-open PR is noticed within ~15 min (vs 2 min) after
  the first hour. Accepted — that window only applies to PRs already sitting for a human.

### Deferred (documented, not fixed — scale-only or cosmetic)

Recorded in the production audit that produced this ADR (Round 4). None is a surprise in production **today** with
`max_concurrent_jobs = 1`: head-of-line blocking at `max_concurrent_activities=1`; per-client SSE
Temporal-action burn; the local-dev `POST /api/jobs` unbounded launcher; per-activity token-provider
re-mint; caching a *transient* read failure as a terminal panel state; the promotion runner's
non-best-effort side channels. Revisit when the floor grows past one.

## Validation

Proven live on a production client (serial floor), 2026-07-17: #277/#278 clean autonomous merges;
**#279** a
deliberate failing test injected after the PR armed → CI red → `repair_ci` fired → the agent
**removed** the bogus test → re-push → green → merged (the bogus test is gone from `main`, the
endpoint landed); **#280** e2e-labelled → dispatched → watched → "🤖 e2e PASSED ✅". The Temporal
history for #279 shows `check_pr_status` and `repair_ci` executing in production. The runbook
records the *operational* lesson from the same day (the deploy that destroyed the panel, and the
permanent `deploy.sh` fix).
