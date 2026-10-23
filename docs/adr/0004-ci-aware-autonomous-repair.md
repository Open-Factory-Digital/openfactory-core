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

### Amendment, 2026-09-24 — four cases, not one bit (#184)

After the table, `none` still meant two things: a pull request nothing had looked at, and one whose
checks all ran and none of them gates the merge (the case #184 was found on). The self-heal merged
on both. And the failing log was attached to every blind red check, so a required commit status
beside some other failed run was "repaired" from that run's log. The port now answers five words
for four cases — `failure` (a blocking check failed), `advisory` (checks ran, none can stop the
merge), `none` (nothing ran), `pending`, and `success` — and every row says them
the same way as the table reads its rows:

- **Only a blocking build with its own log is repaired.** `failed_ci_logs` reads the builds the
  failing blocking `code` checks name — Azure DevOps by `context.buildId`, GitHub by the workflow
  run the red required check links to — and a typed forge's log is evidence about its `code` rows
  only. A status, or another app's check run, is asked about.
- **An advisory failure is said on the card** and changes nothing.
- **Nothing ran is waited on, then said.** The machine never merges it by itself; after
  `_NOTHING_RAN_GRACE` (ten minutes) the card says no check ran and the merge is handed to a person.
- **A blocking check the repository's own rules skipped is satisfied** (review of #320). A required
  workflow a path filter leaves out of this diff had nothing to verify here, and branch protection
  reads it so: a set of blocking checks that were all skipped is `success`, not `none`. Only
  optional checks that were all skipped are `none`. Otherwise a fully autonomous deployment turned
  person-gated, silently, on one of the commonest setups there is.
- **A forge with no CI is not waited on.** A forge row that declares `checks_never_run` (the local
  forge, a directory on this machine) answers `none` as its whole answer, the way its `merge_gates`
  answers `[]`, so the decision carries `nothing_expected` and the watch merges as it always did.
- **Azure DevOps `mergeable_state` answers `blocked`, never `unstable`, for a red blocking policy** —
  `unstable` is one of the two words the self-heal merges on, there with `bypassPolicy` set.

### Amendment, 2026-10-20 — a third move: re-run what the change did not touch (#756)

§1 had one answer to a red build: an agent pass. A blocking check can fail for a reason no file of
the pull request touches, such as a flaky integration test or a busy shared environment. The agent
was paid to repair it, changed nothing, and the next attempt failed the same way until
`_CI_REPAIR_MAX` parked the card. A first attempt (#258, `ci_flake.py`) drew the review that set the
constraints below: the re-run goes through a forge seam, waits on no clock of its own, and #184's
gate stays in front of it. §1's "failure → repair" now has a cheaper first step. That is an
amendment, not a reversal: the agent still repairs every red build the step does not settle.

- **The #184 gate still decides first.** `repair_ci` asks `what_to_repair` before anything else.
  An empty log, a process check or an unreadable forge holds for a person exactly as before, so an
  empty log never reaches the rule. Only a `repair` answer, with the failing log the decision was
  made from, goes on, and that same log is what an agent is handed afterwards.
- **On the first repair attempt of the watch, the log is matched against the diff.**
  `runtime/repairable.py::changed_paths` reads the paths the pull request's diff changes, and
  `log_names_the_change` asks whether any of them appears in the failing log as its basename with
  the extension, with no letter, digit, `_`, `.` or `-` on its left. A log that names the full
  path names the basename too, after a `/` or a Windows runner's `\` alike, so Windows runner
  logs match, and the basename alone decides every case. Colour codes, as an ESC byte or as the
  `^[` that `gh run view --log-failed` prints, are dropped first: jest colours the name of a
  failing file on its own, and the code's closing `m` stood on its left. The stem alone never
  matches. When no changed file appears, the failed jobs are re-run, the pull request is told
  which checks and why, and no agent is launched.
  `repair_ci` answers `PR_OPEN` with `code_changed=False`: nothing was pushed, so the reviewer's
  verdict on the head stands, and the watch rests `_CI_POLL` and reads the checks again.
- **Once per watch, not on every attempt** (PO, 2026-10-19). The rule guesses, and it guesses wrong in the
  commonest real-regression shape: changed `src/billing/invoice_totals.ts`, failing
  `tests/checkout.spec.ts` (#258's review). So it is asked only on the first repair attempt of the
  watch. Every later attempt launches the agent whatever the log says, and a wrong "unrelated"
  costs one CI re-run, spending one of the two repair attempts.
- **"Could not see" is "related".** A diff the forge could not read, or one `truncated` cut (it
  carries `DIFF_CUT_MARKER`), launches the agent as before.
- **After a pass that changed nothing, the failed jobs are re-run once.** A pass that answered
  `PR_OPEN` with `code_changed is False` pushed nothing, so nothing would run the checks again, and
  the watch would read the same red off the same run. The re-run is said on the pull request too
  (PO, 2026-10-19). A pass that pushed, one whose change could not be measured
  (`code_changed is None`), a hold, a pause or a failure, and a person's adjust pass re-run nothing.
- **A row capability, not a port method.** `forge/base.py::rerun_failed_of` reads `rerun_failed`
  with `getattr`, like `merge_gates` and `review_comments`. Only `GitHubForge` declares it: `gh run
  rerun <id> --failed --repo <the pull request's repository>`, for every run the same
  `_failing_runs` chooses for `failed_ci_logs`: the first two, and of those only a run whose
  failing log reads (non-empty) when read again just before, so no run is re-run whose log the
  decision did not read (one more `gh run view --log-failed` per run, at most two, on the re-run
  paths only). A red check whose run is past the first two is neither read nor re-run, and is not
  a refusal (refusing would launch the agent at once on logs that named no changed file): the row
  answers it as left (`Reran.left`), and the comment and the note name it as not re-run and left
  red. Azure Repos, the local forge and every add-on declare nothing.
  Their diff is never read for this, nothing is said, and the agent repairs as before.
- **A refusal falls through to the agent, and is said** (PO, 2026-10-19). A refusal is a
  `RerunRefused` value: no `Actions: write`, a run still in progress, checks that could not be read,
  a run whose failing log did not read.
  The worker log warns, the pull request is told the forge's words and that an agent was launched
  instead, and the agent gets the gate's log. A forge that found no failed job to re-run (`[]`)
  launches the agent with a warning in the worker log and nothing on the pull request.
- **Counted against `_CI_REPAIR_MAX`** (PO, 2026-10-19). The watch counts an attempt before it
  calls `repair_ci`, so a re-run returned from it spends that attempt with no workflow change. The
  bound in §1 holds as it was. The watch's sentences still say `repair pass N of 2` while a re-run
  happens and `CI still failing after N repair attempt(s)` when it parks. Rewording them is a
  workflow change behind `workflow.patched`, and it is left to a follow-up.
- **No clock of its own.** The activity takes no wait after the re-run, and there is no new timeout.
  Measured 2026-10-20 with gh 2.102.0 on a scratch pull request: after `gh run rerun --failed` the
  check read `pending` within 3.0–3.7 s in 3 of 4 re-runs. The fourth stayed queued for 29+ minutes
  and never read red. Before `pending`, `gh pr checks` reported no checks, and the old red was read
  0 of 4 times. The watch's `_CI_POLL` (2 min) is longer than that gap. What a branch whose check is
  required reads in the gap was not measured.
- **GitHub Enterprise Server never reaches the re-run.** `_ACTIONS_RUN` matches `github.com` run
  links only, so `failed_ci_logs` reads `""` there and the #184 gate holds for a person before the
  rule is asked, as it did before this amendment.

Proven by fakes over the activity, the seam and the GitHub row (the GitHub row's `gh` argv
included), and by the measurement above against the real `gh`. It has not been run end to end on a
deployment.
