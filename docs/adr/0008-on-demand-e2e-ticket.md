# ADR 0008 — On-demand e2e via a labelled ticket (not on every PR)

- **Status:** Accepted; platform shipped (label-routed e2e-check job). Per-project it needs a
  `workflow_dispatch` e2e workflow + `e2e_workflow` in the manifest + e2e off the PR CI.
- **Date:** 2026-07-17
- **Relates to:** ADR-0004 (CI-aware repair), ADR-0007 (floor-at-merge), the gate-gap noted on
  a production client's #235/#238 (the sandbox doesn't run e2e).

## Context

e2e is **heavy** — playwright + browsers + the app stack, ~5–6 min per run. Running it as a
required check on **every** PR is expensive and slow, and it can't run in the light platform
sandbox (which is exactly why e2e failures only surfaced in CI, not in the gates — the #235
gap). We do still want e2e coverage; we just don't want it gating every small change.

## Decision

**e2e leaves the every-PR CI and runs DELIBERATELY, via a labelled ticket.**

1. A ticket carrying the **`e2e` label** is NOT implemented. The machine short-circuits the
   whole plan→execute→review→PR pipeline and instead:
   - **dispatches** the project's e2e workflow (`forge.dispatch_workflow`, a
     `workflow_dispatch` GitHub Actions workflow) on the base branch,
   - **watches** the run to completion (`forge.latest_run`, bounded by a ~25 min window),
   - **reports** pass/fail as a comment on the ticket, and ends `DONE` (green) or `ON_HOLD`
     (red / didn't finish) — no code change, no PR.
2. **Opt-in, per project:** the manifest declares `e2e_workflow` (e.g. `e2e.yml`) and
   `e2e_label` (default `e2e`). No `e2e_workflow` → the label is inert (a normal ticket).
3. **e2e comes off the PR-gating CI** (the project's own CI change): it no longer runs on every
   PR, so normal tickets aren't slowed. It runs on the e2e ticket (and/or `main`).

## Consequences

- **Cheaper, faster normal flow** — small tickets don't pay the e2e tax; the floor isn't held
  ~6 min on every PR waiting for e2e.
- **Deliberate e2e** — you drop an `e2e` ticket when you want the suite run (before a release,
  after a risky series, on a schedule). The result lands as a ticket comment with the run link.
- **The trade** — e2e regressions aren't caught on the PR that introduces them; they're caught
  on the next e2e ticket / main run. Accepted: e2e-on-every-PR was too heavy, and the review +
  unit/integration gates still run on every PR.
- **Reuses CI infra** — the platform DISPATCHES the existing GitHub e2e workflow (chosen over
  running playwright in the sandbox), so the sandbox stays light and there's one e2e definition.
- **Consistent with floor-at-merge** — the e2e ticket opens no PR, so it completes at
  `DONE`/`ON_HOLD` and frees the floor immediately.

## Implementation status

- **Platform (shipped):** `Ticket.labels` (tracker fetches them); manifest `e2e_label` /
  `e2e_workflow`; `forge.dispatch_workflow` + `forge.latest_run`; `machine._is_e2e_ticket` +
  `_run_e2e_check` (dispatch → poll → report → DONE/ON_HOLD). Tested (pass→DONE, fail→ON_HOLD,
  label-without-workflow → normal pipeline).
- **Per project (the driven repo):** add a `workflow_dispatch` `e2e.yml`, remove the e2e job
  from the PR-triggered CI, set `e2e_workflow: e2e.yml` in `.sdlc/project.yaml`, and create the
  `e2e` board label. (e2e already dropped from the required status checks.)
