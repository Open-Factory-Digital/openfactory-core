# The pipeline stations — what each stage actually does

This is the **semantic** companion to [`autonomous-flow.md`](autonomous-flow.md). That doc
gives the timing, deadlines, and where each step runs; this one explains **what each station
is for, why it exists, and where it can route a ticket** — the same seven stations you see on
the panel's machine card, plus what happens after the PR.

One ticket = one PR = one run through these stations. A human only creates the GitHub issue
and drops it in **TO-DO**; everything below happens on its own (ADR-0001 D-11/D-12).

```
Spec → Prep → Plan → Code → Test → Review → PR → (merge → deploy-watch + knowledge → promotion)
```

At every station the **platform** owns the decision — it runs the commands and reads the exit
codes; it never trusts the agent's claim that it did (ADR-0001 D-11). A station can always
route a ticket sideways: back to the owner (`needs_refinement` / `on_hold`), into a bounded
repair loop, or forward.

---

## The seven stations

### 1. Spec — is this ticket workable?
Checks the ticket has a real **objective + acceptance criteria**. Without them there is
nothing to build against or to verify, so the ticket is sent back as `needs_refinement`
(→ Backlog) instead of guessing. This is the cheapest possible gate: reject an under-specified
ticket before spending a cent on an agent.

### 2. Prep — an isolated, real workspace
Clones the repo into a **fresh, isolated sandbox** (an ephemeral container)
and runs the project's `setup` commands. Every ticket gets a clean checkout — no shared state,
no leftovers from a previous run. This is also where the project's own config
(`.openfactory/project.yaml`) is loaded, so the rest of the run is driven by *that project's* gates,
docs, and components (nothing project-specific lives in the framework).

### 3. Plan — a short, testable plan (read-only)
The **planner** (a coding agent restricted to `Read`/`Grep`/`Glob` — it *cannot* edit or run
anything) investigates the codebase and writes a concise, test-first plan: the approach, the
files to touch, and the steps as *behaviour → test → code*.

It is also the **sizing estimator** (ADR-0002): if delivering the ticket well would touch too
many files/steps or bundle unrelated concerns, it emits `SPLIT NEEDED` instead of a plan and
the ticket goes back for refinement — *before* the expensive executor runs. Splitting here,
cheaply, beats the executor discovering it the hard way mid-work.

### 4. Code — implement the plan (TDD)
The **executor** (a coding agent that *can* edit and run commands, but has **no git/GitHub
credentials** on purpose) implements the plan test-first. It writes tests and code; it does
**not** commit, push, or open PRs — the platform owns all of that. Bounded by a turn cap
(runaway breaker, not a task-size limit).

### 5. Test — the project's own gates, run by the platform
The **platform** runs the project's declared validation commands and reads their exit codes:
typically **lint · security · type · tests · migrations** (whatever the manifest maps). These
are *mechanical* — they prove the change **runs and passes**. A failing gate triggers the
**bounded repair loop** (ADR-0001 D-12): the executor gets a few attempts to fix it from the
real failure output; still failing after that → `on_hold` for a human, carrying the logs.

### 6. Review — does it actually solve the ticket, correctly? (ADR-0001 D-5)
The gates prove *"it runs"*; the **review** is the *semantic* judgement: **an independent
reviewer** — a **separate** agent that sees **only the ticket spec + the diff + the gate
results, never the executor's conversation**. That context independence is the whole point: it
judges the code on its own merits, not the author's narrative, and its job is to find
**evidence the solution is wrong or incomplete**.

It checks what the gates cannot:
- **Are the acceptance criteria actually met?** — each one marked passed/failed/unknown, with
  concrete **evidence** (a test name, a `file:line`).
- **Correct and complete**, or does it pass the tests without solving the problem?
- **In scope?** — no opportunistic refactors, no "while I'm here".
- **Gaming the gates?** — e.g. a mock that asserts nothing, a test that can't fail.

It emits a structured **`ReviewResult`** — `decision` (approved / approved_with_findings /
rejected), a **score** (0–100), the per-criterion **acceptance** list, **findings**
(severity + file:line), and a human-readable **summary** — which is posted to the PR as a
**real review** (approve / request-changes). You read the *report*, not the raw diff, and dig
in only when a flag is raised.

**What it gates (ADR-0001 D-12):**
- `rejected` → **not** auto-merged; handed to a human.
- The diff **adds a gate-suppression** (`# noqa`, `pragma: no cover`, `type: ignore`,
  `nosec`)? → **forced to human review** regardless of the reviewer's verdict — you cannot
  pass a quality gate by silencing it (detected deterministically from the diff).
- `approved` **+** green gates **+** policy allows → cleared for auto-merge.

### 7. PR — open the pull request
Opens the PR as the bot (idempotent — a re-run reuses the same PR, never a duplicate). The
reviewer's verdict is posted on it. From here the merge posture decides: **auto-merge** (when
policy = auto and it's safe) or **hand to humans** (request reviewers + comment the ticket).

---

## After the PR

- **Merge — on the current base (ADR-0003).** Before merging, the branch is rebased onto the
  latest base; if the base moved, **every gate re-runs** on the rebased result and the branch
  is re-pushed, then squash-merged. A real textual conflict or a failed re-validation →
  `on_hold` for a human. It **never crashes**.
- **CI-aware merge (ADR-0004).** When required GitHub checks gate the merge, a durable loop
  watches CI: green → merge; **red → a bounded autonomous repair** (re-invoke the executor on
  the branch with the failing CI logs) → re-push → re-check. Only a genuinely unfixable CI (or
  the deadline) holds for a human. React and fix, don't just block.
- **Deploy-watch (ADR-0005).** The moment a job merges it **completes** — the floor frees for
  the next ticket immediately. An **abandoned durable child** then watches the project's own
  deploy (its `deploy` workflow on the merge commit) and **notifies** the outcome
  (deployed / failed / timeout). Watching only informs; it never gates the floor.
- **Knowledge Pipeline (ADR-0017).** Also on merge, and only when the project sets
  `knowledge_map: true`: the module map is regenerated from the base branch's new state and
  published as one commit on a dedicated `openfactory-knowledge` branch in the project's own repo. It
  writes nothing when no source changed, so it converges instead of re-triggering itself; it is
  single-attempt and its result is swallowed, so a merged ticket can never be held or failed by
  a navigation aid. The map goes to a dedicated branch, never `main` — a commit there would fire
  the project's deploy and put every open PR behind.
- **Promotion (ADR-0001 D-12).** Only if the manifest declares environments: after the *real*
  merge, an ephemeral task observes the staging deploy, then parks at **`awaiting_prod_approval`**
  — the **one mandatory human gate** — until an authenticated approver signs off. Prod is never
  automatic.

---

## Where a ticket can go sideways

| Outcome | Meaning | Set by |
|---|---|---|
| `needs_refinement` | Under-specified spec, or the plan is too large (`SPLIT NEEDED` / over the sizing budget) | Spec, Plan (ADR-0002) |
| `on_hold` | Gates unfixable after the repair loop, an unresolvable merge conflict, or the merge/approval deadline elapsed | Test, Merge, Wait-for-merge |
| `paused` → resumes | The agent hit a usage/rate limit — the workflow sleeps durably and retries | Code (any agent stage) |
| forced human review | The diff silences a gate (suppression), or policy = human, or a high-risk component was touched | Review, PR |

None of these crash the run — a station either advances the ticket, fixes it autonomously, or
hands it back to a human with the reason (the standing rule: **react and fix; escalate only
when genuinely stuck**).

---

## See also
- [`autonomous-flow.md`](autonomous-flow.md) — the same flow with every timing, deadline, and timeout.
- [`architecture.md`](architecture.md) — how the panel, the durable engine and the boxes fit
  together; the one cloud realisation worked through ships with the `openfactory-aws` add-on package.
- ADRs [0002](adr/0002-task-sizing-and-execution-budget.md) (sizing gate), [0003](adr/0003-autonomous-merge-on-current-base.md) (merge on current base), [0004](adr/0004-ci-aware-autonomous-repair.md) (CI repair), [0005](adr/0005-post-merge-deploy-watch.md) (deploy-watch), [0017](adr/0017-knowledge-layer.md) (the knowledge map).
