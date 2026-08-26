# ADR 0006 — Bounded review-repair loop (react to a rejection, once)

- **Status:** **Accepted; shipped** (the machine's review-repair loop). Live-log streaming is
  still separate/pending.
- **Date:** 2026-07-16
- **Relates to:** ADR-0004 (CI-aware autonomous repair — the objective-failure analog),
  ADR-0001 [D-5] (independent reviewer) & [D-12] (bounded repair / merge posture), and the
  standing rule *react and fix, don't just block*.

## Context

Today a `rejected` review does **not** loop back to the executor. `should_auto_merge`
(`merge_policy.py`) treats the reviewer's **decision** as a gate: `rejected` → the PR is handed
to a human (posted as `request-changes`, reviewers requested, ticket commented) and parks at
`PR_OPEN`. The **score is not a threshold** — only the decision matters; `approved` and
`approved_with_findings` both auto-merge (findings are non-blocking comments).

The autonomous repair loops we *do* have — the gate/validation loop (Test) and the CI-repair
loop (ADR-0004) — react to **objective** failures (exit codes). The review verdict is
**subjective** (an LLM's judgement), so it was left as a human-escalation, not a repair trigger.

But a rejection is exactly the "a failure happened — react and fix it like a developer would"
situation the standing rule is about. A developer whose review is rejected reads the findings
and fixes them; they don't stop. The platform should be able to do the same — **carefully**.

## Decision

Add a **bounded review-repair loop**, modelled on the CI-repair loop:

1. On a `rejected` review, feed the reviewer's **findings** (severity + `file:line` +
   description — the same structured `ReviewResult`) to the **executor** as the fix input,
   re-run it on the *existing* branch, then run an **independent re-review** (a fresh reviewer
   pass, same context-independence as the first).
2. **Default: exactly 1 attempt** (`review_repair_max_attempts: 1`, per-project, opt-in-tunable).
   The review is subjective, so more than one round risks the executor and reviewer
   **ping-ponging** (the executor tweaking to satisfy a moving target, or superficial
   "fixes"). One honest attempt, then stop.
3. Still `rejected` after that one attempt → **hand to a human**, exactly as today (no worse
   than the current behaviour — the loop only ever *adds* one autonomous fix chance).

### Guards (why this won't degrade into ping-pong or gaming)

- **Bounded at 1 by default** — the whole point. The cap is the anti-ping-pong mechanism.
- **React to the *decision*, not the score** — never loop to chase a higher number; only a
  `rejected` verdict triggers a repair. `approved_with_findings` still merges (findings are
  advisory).
- **Only actionable findings** — if a rejection carries no concrete `file:line` findings (just
  a vague verdict), don't repair; escalate — there's nothing precise to fix.
- **Suppression guard still wins** — a repair that silences a gate (`# noqa`, `type: ignore`,
  …) is forced to human review regardless (existing rule, engineering #12).
- **Fresh independent re-review** — the second review is a new context, not the same reviewer
  "grading its own feedback".

## Consequences

- **More tickets clear autonomously** — a rejection with a clear, fixable finding gets one
  real fix attempt instead of always waiting for a human.
- **No new failure mode** — worst case is identical to today (still rejected → human), plus one
  executor run's cost. The 1-attempt cap makes the extra cost predictable.
- **Consistent philosophy** — the same shape everywhere: fail → one bounded autonomous fix →
  escalate only when still stuck. Review joins gates and CI as a signal the loop reacts to.
- **Deliberately conservative** — 1 attempt, decision-only, actionable-findings-only. If real
  usage shows it helps, the cap is already a per-project knob to raise; we do **not** start
  high.

## Implementation sketch (for when it's built)

- Manifest: `review_repair_max_attempts: int = 1` (0 disables — today's behaviour).
- Machine: after `REVIEWING`, if `decision == "rejected"` and attempts remain and findings are
  actionable → `REPAIRING` with the findings as input (reuse the executor-on-existing-branch
  path from CI-repair) → re-validate gates → re-review → re-evaluate `should_auto_merge`.
- Journal a `review_repair` event so the panel shows the extra round (and the live-log work
  makes it visible in real time).
