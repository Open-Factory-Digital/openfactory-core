# ADR 0014 — Single-agent execution + advisory review (frontier-default, still agnostic)

- **Status:** **Accepted; shipped** (manifest flags `planner_stage`, `review_mode`).
- **Date:** 2026-07-21
- **Relates to / amends:** ADR-0001 [plan→execute two-stage, D-5 independent reviewer, D-12
  merge posture], ADR-0006 (review-repair loop — now **blocking-mode only**).

## Context

Two design choices from ADR-0001 were made when the platform had to be robust across model
tiers (including weaker/cheaper models):

1. **plan → execute split.** A dedicated read-only planner investigates and drafts a text plan;
   a separate executor implements it.
2. **Blocking code review.** An independent LLM reviewer can `reject`, which triggers the
   bounded review-repair loop (ADR-0006) and gates auto-merge (`merge_policy.py`).

A measured run (#394, Plan 92b — a real security-hardening ticket) exposed the cost with a
**frontier model** (Opus for both plan and exec):

| Phase | Time | | Phase | Time |
|---|---|---|---|---|
| Spec+Prep | 56s | | **Reviewing → rejected** | 5.2 min |
| **Planning** | **18.5 min** | | **Repairing (review-repair)** | 11.4 min |
| **Code** | 16.5 min | | **Re-validating** | 10.4 min |
| Validating | 10.6 min | | Re-reviewing → approved | 4.2 min |

Total ≈ **1h23m**. Two structural taxes dominate:

- **The plan→execute handoff.** The planner reads the repo, understands it, and serialises a
  *text* plan (lossy); a second cold agent re-reads the same files and re-derives the context
  the planner already had — two cold frontier sessions. With a capable model this is redundant:
  it plans *as* it codes, in one warm context.
- **LLM-reviewing-LLM.** The review is the same class of model grading its own output — limited
  independent signal — yet one rejection cost ~31 min (37% of the run: repair + full re-validate
  + re-review). The **real** quality floor is deterministic — tests, lint, type, security, CI —
  plus the executor's own TDD (which only started working once its Bash tool was un-blocked; a
  separate fix). An LLM opinion-gate on top is fuzzy, expensive, and can reject spuriously.

## Decision

Adopt **frontier-optimised defaults, keep the tool model-agnostic** via two manifest flags:

1. **`planner_stage: bool = False`** — single agent by default. The executor investigates,
   states a short plan, then implements with TDD in one context. The dedicated planner runs only
   when a project opts in (a weaker model that flails without an explicit plan) **and** the
   adapter exposes `plan()`.

2. **`review_mode: "advisory" | "blocking" | "off" = "advisory"`** — the review still runs and
   its findings are **posted to the PR as a comment** (informational, for a human), but it
   **never** triggers the repair loop, **never** requests changes, and **never** blocks
   auto-merge. `"blocking"` restores the ADR-0006 behaviour (repair loop + request-changes +
   merge gate); `"off"` skips review entirely. Deterministic gates remain the merge floor.

The **suppression guard is unchanged** (ADR-0011): a diff that silences a gate
(`noqa`/`type: ignore`/`nosec`) is still human-gated regardless of review mode — that is a
deterministic check, not an opinion.

## The strategic fork (named, deliberately)

The split and blocking review were *scaffolding for weak models*. There is a real fork:

- **Optimise for frontier** (our default): simpler pipeline, single agent, advisory review —
  faster and cheaper, betting the model is good enough.
- **Robust multi-tier**: the scaffolding protects weaker models; slower, more guardrails.

We take the frontier default but keep both reachable **per project**, so agnosticism is
preserved — the choice moved from hard-coded to configuration.

## Consequences

- **Much less wall-clock/cost.** Removing the plan handoff and the review-repair tax targets the
  two biggest phases; #394-class tickets should drop from ~1h23m toward ~35–45 min (smaller
  tickets go further).
- **No loss of the real floor.** Tests/lint/type/security/CI + the executor's TDD still gate the
  merge. We trade an LLM opinion-gate (weak signal) for a human-visible advisory comment.
- **Reversible + agnostic.** A project that wants the old behaviour sets `planner_stage=True`
  and/or `review_mode="blocking"`. Nothing is deleted.
- **Traceability kept.** In single-agent mode the executor states its plan up front (in the
  trace), so the "what was the intended approach" record survives without a second agent.
- **Validation is empirical.** Measure the next split sibling of #37 (#395/#396 — comparable to
  #394) under these defaults and compare time, cost, and whether the deterministic gates + CI
  held.

## Follow-ups

- Panel: with no planner the `planning` station never lights — relabel/collapse the pipeline for
  single-agent projects (cosmetic).
- If advisory review proves too quiet in practice, consider **risk-gated blocking** (only
  security/auth/migration diffs) as a middle setting rather than reverting globally.
