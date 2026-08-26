# ADR 0004 — CI-aware autonomous repair (react, don't block)

- **Status:** Accepted; parts 1–2 shipped (forge CI reading + the durable CI-watch/repair
  loop). Part 3 (per-project require-CI) is repo config, applied per project.
- **Date:** 2026-07-16
- **Relates to:** ADR-0001 [D-12] (bounded repair), ADR-0003 (merge on the current base)

## Context

The platform runs its own gates in the sandbox before merging, and repairs failures there
(the bounded repair loop). But once the PR is open, it does **not** watch GitHub CI. Two
problems follow:

1. **Divergence.** The sandbox gates and GitHub CI can run in different environments (OS,
   Python), so "green in sandbox" ≠ "green in CI". A real case: a `pathlib` `**` glob
   behaved differently on 3.11 (sandbox author's machine) vs 3.12 (CI + the sandbox image),
   silently dropping every project's constraints — green locally, red in CI.
2. **Blocking is not resilience.** Even if we *notice* a red CI, stopping there and waiting
   for a human is not what a developer does. The standing rule (the user's words):

   > A failure — CI red, a lint/test criterion, anything — is **not** a reason to sit
   > blocked. **React and fix it, like a developer would.** Whatever can be done
   > **autonomously, do it**; whatever needs a human, **ask**. Never just block.

## Decision

### 1. React to CI with the same repair loop, extended to a new signal

The bounded repair loop ([D-12]) already embodies "fail → fix → re-check → escalate only if
stuck" for sandbox gates. Extend it to the **GitHub CI** signal — same philosophy, new
source:

- After the PR is open under `merge_policy: auto`, a **durable** loop (Temporal, survives
  worker restarts — CI can take minutes) watches CI:
  - **success** → merge → proceed.
  - **failure** → pull the failing job logs (`forge.failed_ci_logs`) and run a **repair**
    (re-invoke the executor on the *existing* branch with those logs as the failure input) →
    push → CI re-runs → loop.
  - **pending** → durable sleep, re-check.
- **Bounded**: mirror `repair_max_attempts` (2). Still red after that → `ON_HOLD` carrying
  the CI logs, so the human starts from the actual failure, not a mystery.
- **Post-merge** regressions (main goes red later) → open a fix ticket (follow-up).

### 2. Require CI as a merge gate (revises ADR-0003)

ADR-0003 chose "no required GitHub checks — the pipeline is the authority". This incident
shows that was too optimistic: the pipeline's gates can diverge from CI. So the driven-repo
standard (operations.md) now **requires the CI status checks** (strict/up-to-date). The
proactive rebase (ADR-0003 §1) keeps the branch up-to-date so `--auto` isn't stuck; §1 above
keeps a red CI from becoming a dead block. Together: **the merge waits for the *real* CI to
be green, and a red CI triggers a fix rather than a stall.**

## Consequences

- **No more "green in sandbox, red in main".** A divergence can't merge — and usually
  self-heals via the repair, without a human.
- **Consistent mental model.** One rule everywhere: fail → autonomous fix → escalate only
  when stuck. CI is just another gate the loop reacts to.
- **Durability required.** The loop lives in the Temporal workflow (not inline in the
  machine), because CI latency is minutes-to-hours and must survive worker restarts.
- **Cost.** A merge now waits for CI (~1–2 min typically) instead of trusting the sandbox
  alone — an accepted price for closing the divergence gap.

## Implementation status

- **Part 1 (shipped):** `forge.pr_ci_status()` + `forge.failed_ci_logs()` (GitHub via `gh`;
  `_ci_status_from_checks` unit-tested).
- **Part 2 (shipped):** `sandbox.prepare(checkout_existing=True)` + `JobRunner.repair_ci()` +
  the `repair_ci`/`check_ci_status` activities + the durable `_ci_merge_loop` in the workflow
  (runs for `auto` jobs regardless of environments). The machine now arms `--auto` and returns
  `PR_OPEN + auto_merge=True` when the merge is pending CI (instead of falsely claiming
  MERGED), handing the loop to the workflow.
- **Part 3 (per project):** require the CI checks in the repo's branch protection — see
  `operations.md`. It is deliberately NOT framework code: the platform reacts to *whatever*
  checks a PR has (`pr_ci_status`), so requiring specific contexts is per-project repo config,
  chosen to include only every-PR, deterministic checks (never path-conditional or flaky ones).
