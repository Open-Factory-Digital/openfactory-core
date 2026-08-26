# ADR 0010 — Single-line strict: the queue advances only on a clean merge (park on any impediment)

- **Status:** **Accepted; shipped.**
- **Date:** 2026-07-17
- **Supersedes** the part of [ADR-0007](0007-floor-frees-at-merge.md) that let `needs_refinement`
  / `on_hold` **free** the floor. Relates to ADR-0004 (CI-repair pause), ADR-0001 [D-12].

## Context

ADR-0007 made the floor hold until a PR **merges**, so the next ticket builds on a base that
includes the previous one. But it deliberately let the *impediment* outcomes —
`needs_refinement`, `on_hold`, `failed` — **complete and free the floor**, on the reasoning that
a ticket needing human re-scoping shouldn't freeze the whole queue.

That reasoning breaks the dependency guarantee. Observed live (2026-07-17): the operator dropped
a real backlog ticket (#69, "Plan 88.1") whose body had no `## Acceptance Criteria` → the spec
gate returned `needs_refinement` → the workflow completed → the floor freed → the poller would
have picked up the **next** TO-DO ticket. With a batch of dependent tickets in TO-DO, the next one
could start **without** the one before it. The operator had to move everything back to Backlog by
hand to stay safe. Their requirement: *"single line — if a ticket raised any requirement at all
it stays 'paused' waiting for an action, otherwise we overcomplicate this"* — and, on scope, *"you
have to think about EVERY pause scenario"* (the token running out being one).

A `depends_on` field exists on the ticket contract but is **not enforced** anywhere; pickup is
pure board order. Enforcing declared dependencies was the alternative — rejected as more moving
parts than the operator wants.

## Decision

**The queue advances ONLY on a clean merge. Every non-progressing outcome PARKS the job — holding
the floor — until the operator acts.** Because pickup counts RUNNING JobWorkflows, a parked
(still-RUNNING) workflow blocks the next ticket automatically. No `depends_on`: a ticket that
needs attention simply never lets the next one start, so ordering — and therefore dependencies —
is safe by construction.

A parked job exposes an `awaiting_action` query (`{kind, state, note}`); the operator resolves it
from the panel (where "Scan TO-DO" lives) with two actions delivered as a durable signal:

- **▶ Resume** — re-run the job **from the top** (it re-reads the now-fixed ticket). *Restart, not
  continue-from-where-it-stopped*: `run_job` is one coarse activity with no durable mid-point, and
  the impediment is usually fundamental (missing spec, red gate) — a fresh pass is the correct,
  robust behavior.
- **⏭ Skip** — complete the job, free the floor, leave the ticket for its owner (Backlog).

A forgotten block cannot jam the queue forever: after `impediment_deadline_days` (default 3) the
park auto-**skips**, freeing the floor.

### Every pause scenario is covered (the operator's ask)

The park is reached uniformly for **all** ways a job can stop making progress:

| Scenario | Reaches park as | Behavior |
|---|---|---|
| Spec gate (no objective / **no acceptance criteria** / scope overlap) | `needs_refinement` | park → Resume/Skip |
| Plan too big / SPLIT verdict | `needs_refinement` | park → Resume/Skip |
| Agent stopped, cost ceiling, validations red after repairs, review-repair broke a gate | `on_hold` | park → Resume/Skip |
| e2e couldn't dispatch / didn't finish / RED | `on_hold` | park → Resume/Skip |
| Merge conflict / unmergeable / **PR closed unmerged** / unfixable CI / merge deadline | `on_hold` | park → Resume/Skip |
| CI-repair agent stopped / added a gate suppression | `on_hold` | park → Resume/Skip |
| **Token ran out — auth failed / revoked / expired** | `on_hold` (never auto-retried) | park → Resume/Skip |
| **Token ran out — usage/rate limit (transient)** | `paused` | auto-retries on a 30-min backoff (holds the floor); operator can **Retry-now** or **Skip**; after 48 auto-resumes (~24 h) it escalates to `on_hold` (park) |
| **Job crashed** (activity failed after its retries) | caught → `on_hold` "job errored…" | stop any lingering task, then park → Resume/Skip |

A rate-limit thus self-heals without a click when the cap resets, but the operator is never *stuck*
waiting on it — the panel shows the reason and offers Retry-now / Skip. A genuine crash no longer
silently frees the floor; it stops its Fargate task and parks like any other impediment.

### What is NOT caught

Temporal replay/determinism errors are handled by the SDK at the task level (the task retries; the
workflow does not complete), so they are intentionally not swallowed by the crash-park. Operator
**cancellation** of the workflow still propagates (frees the floor by intent). The prod-approval
gate is unchanged (its own signal/query).

## Consequences

- **Dependency-safe by construction**, with zero dependency bookkeeping: drop a whole batch in
  TO-DO; it runs strictly one-fully-done-at-a-time, and any snag stops the line until you act.
- **The floor can be *held* by a parked job** — that is the point. `available_slots` needs no
  change (a parked workflow stays RUNNING and is counted). The bounded `impediment_deadline_days`
  keeps a forgotten block from jamming the queue forever.
- **Resume re-runs the agent** (cost) — accepted: the ticket was fixed, a fresh pass is correct.
- **Panel is the control surface**: the Resume/Skip controls sit where "Scan TO-DO" is; the button
  is hidden whenever the floor is occupied (running or parked). No card-dragging required.
- **Revises ADR-0007**: its floor-holds-until-merge stays; its impediment-frees-the-floor does not.

## Implementation

`JobWorkflow._lifecycle` runs the job in a loop: `_run_job_once` → on `PAUSED` a rate-limit park
(auto-resume on backoff, bounded), on `needs_refinement`/`on_hold` (or a caught crash) an
impediment park via `_wait_operator(kind, result, timeout, default)` — a `workflow.wait_condition`
on the `act_on_impediment` signal, `awaiting_action` exposing the reason. Resume → `continue`
(re-run); skip/deadline → complete. Panel: `POST /api/temporal/act/{project}/{issue}` `{action}`
→ `temporal_view.act_job`. `impediment_deadline_days` on `JobParams` (default 3). Tests cover
park→resume→merge, park→skip, deadline→auto-skip, and crash→stop-task→park.

### Consistency amendment (same day, pre-production audit)

Two divergences between this ADR's table and the code were found and closed:

1. **The CI-repair pause inside the merge watch was a blind `sleep`** — invisible to the panel
   (no `awaiting_action`) and not operator-actionable, while the table promises Retry-now/Skip
   for *every* rate-limit. It now parks via the same `_wait_operator`; a Skip there completes
   directly (`_skipped` flag) instead of re-parking outside.
2. **Skipping a rate-limited job completed with state `paused`** — misleading, since the ticket
   comment says "will resume automatically" and it never would. A rate-limit Skip now completes
   `on_hold` with note "rate-limited — skipped by operator".

Deliberate non-parks (NOT gaps): post-merge outcomes — a failed staging promotion or an elapsed
prod-approval window — complete without parking, because the dependency guarantee is already
satisfied at merge (the next ticket safely builds on a base containing this one). `PAUSED` has no
board column (the card stays "In progress" during a pause); the panel is the source of truth for
parked state.
