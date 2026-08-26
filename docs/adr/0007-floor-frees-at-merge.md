# ADR 0007 — The floor frees at merge, not at agent-done (dependency safety)

- **Status:** **Accepted; shipped** (the human-review path now runs the durable wait-for-merge + CI-repair loop). Live-log streaming is still separate/pending. **Partly superseded by [ADR-0010](0010-single-line-strict-park-on-impediment.md):** the "floor holds until merge" decision stands, but the "`needs_refinement`/`on_hold` FREE the floor" part is replaced — those now PARK and hold the floor until the operator resumes/skips (strict single-line).
- **Date:** 2026-07-16
- **Relates to:** the floor-aware pickup (one-at-a-time), ADR-0003 (merge on the current base),
  ADR-0006 (review-repair loop — the mitigation), ADR-0001 [D-12].

## Context

The floor-aware pickup starts at most `max_concurrent_jobs` (default 1) **new** tickets per
tick, counting **RUNNING JobWorkflows**. But a JobWorkflow **completes** the moment it reaches
a terminal state — including `pr_open` on the human-review path (a rejected review, a high-risk
component, or `merge_policy: human`). So the floor frees while that ticket's PR is **still
open and unmerged**, and the next ticket starts off a `main` that does **not** contain it.

Observed live on a production client: #235 (Plan 95.5) was rejected by review → `pr_open`
(handed to human) → the floor freed → #238 (Plan 95.6) started immediately, branching off a
`main` without #235. For a series that builds on itself (the 95.x widget epic — all touching
the same widget area), this is the wrong default: **inter-ticket dependencies are very
common**, and building the next ticket on a base missing the previous one invites rework and
conflicts.

ADR-0003 (rebase onto the current base + re-validate at merge time) is a real safety net — it
prevents *silently* merging a stale/conflicting branch — but it reconciles **text**, not
**intent**: #238 was still planned and implemented against a `main` without #235.

## Decision

**The floor is held until the previous ticket's PR actually MERGES, not just until its agent
work is done.** A ticket that opened a PR keeps the floor occupied (so no new ticket starts)
until that PR merges or is closed. Concretely: the human-review path should **durably wait for
the merge** (like the auto-merge path's `_ci_merge_loop` / the promotion path's
`_wait_for_merge` already do) instead of completing at `pr_open` — so the RUNNING-workflow
count the pickup already uses naturally blocks the next ticket.

- **Applies to** tickets that reached a PR (`pr_open` / awaiting human merge). The workflow
  parks durably (no compute) until merge or the `merge_deadline_days` bound.
- **Does NOT apply to** `needs_refinement` / `on_hold` (no PR, returned to the owner for
  re-scoping) — those free the floor; blocking the whole queue on a ticket that isn't going to
  merge soon would be worse than the dependency risk.

### The stall, and its mitigation

The obvious cost: a ticket **stuck** waiting for a human (e.g. a rejected review) now **stalls
the queue** behind it. That is accepted **because** ADR-0006 (the bounded **review-repair
loop**, 1 attempt) mitigates the most common stall: a rejection with an actionable finding gets
one autonomous fix → re-review → merge → the queue flows again, no human needed. Floor-at-merge
and review-repair are designed together: the first makes the ordering safe for dependencies,
the second keeps it from stalling on the common case.

## Consequences

- **Dependency-safe by default** — the next ticket always builds on a `main` that includes the
  previous one. No planning/testing against a base that's about to change under it.
- **Serial on the *merge* chain**, not just agent execution — matches the intuition that a
  batch dropped in TO-DO is worked "one fully-done at a time, in order".
- **A stuck ticket blocks the queue** — mitigated by ADR-0006, and bounded by
  `merge_deadline_days`; a genuinely stuck PR still needs a human, as today. Operators can
  always re-order the board (move a blocker to Backlog) to unblock.
- **Throughput trade** — accepted: correctness-for-dependencies over max parallel-ish churn.
  The floor is one agent token anyway (v1), so the "lost" throughput is small.

## Implementation sketch (for when it's built)

- Machine/workflow: on the human-review path, instead of returning `pr_open` and completing,
  **park in a durable wait-for-merge** (reuse `_wait_for_merge`) → complete only when merged
  (→ `MERGED` + deploy-watch) or the deadline elapses (→ `on_hold`).
- `available_slots` needs no change if the workflow stays RUNNING until merge (the running
  count already gates pickup). Verify the deploy-watch child still spawns on the eventual merge.
- Pairs with ADR-0006 so a rejected review self-heals instead of parking for a human.
