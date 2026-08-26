# ADR 0002 — Task sizing and the execution budget

- **Status:** Accepted
- **Date:** 2026-07-16
- **Relates to:** ADR-0001 [D-5] (generic worker), [D-6] (scope-explosion), [D-8]
  (spec-quality gate), [D-12] (bounded repair)

## Context

ADR-0001 [D-5] splits a job into a **planner** (read-only, investigates and drafts a
testable plan) and an **executor** (implements the plan with TDD). Each agent invocation
carries a **turn cap** (`--max-turns`) — a hard stop so a stuck agent cannot loop forever.

Once the two-stage split was actually enforced (the planner made genuinely read-only, so it
plans instead of implementing), a problem surfaced: the executor now does the **entire**
implementation. A real feature — a backend route + a widget helper + their TDD test runs —
exceeded the old cap of 60 turns and was **cut off mid-work**, landing the ticket
`ON_HOLD` with the change half-applied.

The deeper issue is not the number. It is that the turn cap is a constraint on the
**execution** side with **no counterpart on the intake side**. When one side has a budget
and the other has no size contract, the two are *decoupled*: either legitimate work gets
cut, or cost runs unbounded. And `turns` is the wrong unit to bound by — it is a mechanical
proxy with no relationship to the value or size of the ticket.

Two coherent ways to recouple them:

1. **Let execution run as long as needed**, guarded only by cost/time. Simpler, but removes
   the natural pressure toward small, reviewable changes and makes spend unpredictable.
2. **Constrain task size at intake** so that a ticket which is admitted fits the execution
   budget *by construction*. An oversized ticket fails fast and cheap, before the expensive
   executor runs.

We choose (2).

## Decision

### 1. The turn cap is a runaway disjuntor, not a task limit

`--max-turns` exists to stop loops (an agent repeating a failing action burns tokens, and on
a strong model that is real money). It is **not** the semantic limit on how large a task may
be. It is set generously (default **120**) and is tunable via `SDLC_MAX_TURNS` without a
rebuild. The read-only planner never approaches it.

### 2. The planner is the estimator

The planner already investigates the codebase read-only and drafts the change. It is
therefore the natural, cheap estimator. Its plan now ends with a machine-readable estimate:

```
## Estimate
- files: <n>
- steps: <n>
```

and, when the ticket cannot be delivered as one small, testable change, it returns a
**verdict** instead of a plan:

```
SPLIT NEEDED: <why this is too large for one ticket>
- <sub-ticket 1>
- <sub-ticket 2>
```

### 3. Task-sizing gate — intake couples to execution

After the plan is ready and **before** the executor runs, the orchestrator gates on the
planner's estimate against a per-project budget (manifest):

- `max_plan_files`, `max_plan_steps` — a plan past either → `NEEDS_REFINEMENT`.
- a `SPLIT NEEDED` verdict → `NEEDS_REFINEMENT`, carrying the suggested split.

This is the coupling: a ticket that passes the gate is, by construction, within the
executor's budget; an oversized one is caught here — cheaply, on the read-only planner —
instead of slowly and expensively, by the executor hitting its turn wall. It extends
[D-8] (trust to start, verify to finish) with a size dimension, and complements [D-6],
which catches scope explosion *after* the diff — this catches it *before* any code is
written.

### 4. Cost ceiling per ticket — the economic guard (opt-in, for per-token billing)

Cumulative agent spend (plan + execute + repair) is bounded by `max_cost_usd` (manifest).
Past it, the job holds (`ON_HOLD`) for a human. Turns bound a single invocation; cost bounds
the whole ticket.

This is **opt-in and off by default**, and it is only meaningful under **per-token (API)
billing**. On a **Claude subscription** the reported cost is notional (there is no
per-token charge), so a dollar ceiling does not map to real money — there, the runaway
guards that matter are the **sizing gate (§3)** and the **turn cap (§1)**. A production
client runs on a subscription and leaves `max_cost_usd` unset.

### 5. The agent never owns version control

The planner and executor are *authors*, not *publishers*. The pipeline — never the agent —
commits (as the bot), pushes the branch, and opens the PR. This boundary is enforced, not
merely instructed:

- the planner is restricted to read-only tools (`--tools Read,Grep,Glob`), so it cannot
  edit, run, or spawn subagents;
- the executor's sandbox env is scrubbed of forge (GitHub) credentials, and the cloned
  `origin` has its bot token stripped, so `git push` / `gh pr create` have nothing to use.

(This closed the gap where an executor pushed a stray branch by "helpfully" finishing the
job itself.)

## Consequences

- **Right-sized tickets by design.** Oversized work is decomposed at the planning gate, not
  discovered by a truncated executor. This aligns with smaller PRs and better review.
- **Fail fast and cheap.** An oversized ticket costs one read-only planner pass, not a full
  opus execution that dies at the turn wall.
- **Predictable spend (per-token billing).** `max_cost_usd` puts a hard economic bound per
  ticket where it applies; on a subscription it is left unset and the sizing gate + turn cap
  carry the load.
- **Opt-in per project.** All budgets default to unset (no behaviour change), consistent
  with [D-6]. A production client sets `max_plan_files: 10`, `max_plan_steps: 15` (calibrated
  from real features, ~5 files / ~6 steps, with headroom) and leaves `max_cost_usd` unset
  because it runs on a subscription.
- **The planner's estimate must be parseable.** The gate reads `files:`/`steps:` and the
  `SPLIT NEEDED` marker from the plan text; if a budget is unset or the field is absent, the
  gate simply does not fire (fail-open on parsing, fail-closed on an explicit verdict).

## Follow-ups

- Optional **continuation** on a turn-cap hit (commit WIP + resume, bounded by
  `max_cost_usd`) so a legitimately long task checkpoints instead of being lost. Deferred:
  with the sizing gate in place, a task should rarely reach the cap.
- An optional LLM second-stage on the estimate (does the plan really cover the acceptance
  criteria?), pairing the deterministic size gate with a quality judge.
