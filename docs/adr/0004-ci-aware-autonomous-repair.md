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

## Amendment, 2026-09-19 — what is reacted to (#184)

§1 reacted to one word. `pr_ci_status` answers `failure` and the loop repaired — and "a check
failed" turned out to be three questions with three different right answers: does it **block**
the merge, is it about the **code**, and is there **evidence** to act on. Found on a live Azure
DevOps deployment: a rejected *optional* policy (work-item linking, on a team that links none)
read `failure` on a pull request with no build at all, and two agent passes were spent on an empty
log before the card parked `CI still failing`.

This ADR's own rule already covered it — *whatever needs a human, ask* — but the port could not
say which failures those were, so each adapter had learned one cell at a time. Now:

- **The row says what each check is.** `pr_checks` rows carry `blocking`, `kind` (`code` |
  `process` | `unknown`) and, where the vendor has them, a `remedy` and a `url`. A forge declares
  it with `checks_are_typed = True`; one that does not keeps working from its aggregate, as
  `unknown`.
- **One table decides, for every forge** (`contracts/checks.py::decide`): a blocking check about
  the code **with a failing log** → repair; a blocking code check **without** one → ask a person,
  naming the check; a blocking **process** check → ask, with the check's remedy; a **non-blocking**
  check → never changes the job's path, and the panel draws it as advisory.
- **Asked where it happened.** The question is a decision inside the merge watch ("I settled it —
  re-check" / skip), so the answer goes back to reading the checks, not through an agent pass, and
  no repair attempt is spent.
- `repair_ci` asks the same table before it launches anything, so a job whose history predates
  `read_ci_checks` — and still arrives on the bare word — is held to it too.

`_CI_REPAIR_MAX` and the bound in §1 are unchanged: they now count repairs of things a repair can
fix.
