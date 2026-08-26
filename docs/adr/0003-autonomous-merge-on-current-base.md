# ADR 0003 — Autonomous merge on the current base

- **Status:** Accepted
- **Date:** 2026-07-16
- **Relates to:** ADR-0001 [D-5] (generic worker), [D-12] (merge posture / bounded repair),
  ADR-0002 (execution budget)

## Context

The pipeline opens a PR and, under `merge_policy: auto`, merges it once its gates pass. But
between the moment a ticket's branch is cut and the moment it merges, the base (`main`) can
move — a human lands a change, or a hotspot like `app/main.py` (the composition root every
ticket wires into) shifts. Two failure modes surfaced:

1. **A merge that can't complete used to crash the run** (an unhandled error from
   `gh pr merge`), leaving no result — which reads as an infra fault and burns re-runs.
2. **`gh pr merge --auto` arms auto-merge but does not update a behind branch.** With
   protection that requires up-to-date branches, an armed-but-behind PR sits until the
   durable wait times out (days) — it never self-heals.

More fundamentally: a PR that merges *textually* against a moved base can still be **wrong**
against the new code (a semantic conflict the text merge doesn't see). "Gates passed when
the branch was cut" is not the same as "gates pass on what will actually land."

## Decision

### 1. Merge on the CURRENT base — proactive rebase (merge-queue-lite)

Because the framework is **serial** (one ticket at a time — ADR-0001 [D-5]), it can act as a
lightweight merge queue without ordering machinery. Right before merging, `_auto_merge`:

- **rebases the branch onto the latest base** (`sandbox.rebase_onto_base`, host creds, like
  `publish_branch`):
  - `up_to_date` (base didn't move) → merge straight through;
  - `rebased` (base advanced) → **re-run every gate** on the rebased result, re-push, then
    merge — so nothing lands that wasn't validated against what it actually merges into;
  - `conflict` (textual) → `ON_HOLD` for a human (agent-assisted conflict resolution is a
    deferred, opt-in follow-up).
- **never crashes:** a rebase conflict, a failed post-rebase validation, or a forge that
  rejects the merge all resolve to a held job with a clear reason (engineering #1 — always
  emit a result).

This makes "recover from drift" the **normal path**, not an error path: it fires whenever
the base moved during a run, and re-validation is the safety net.

### 2. Branch-protection standard for driven repos

A repo the platform drives sets, on its default branch (documented in `operations.md`):

- **require a pull request before merging** (no direct pushes) — the bot always goes through
  a PR; **0 required approvals** (a required human review would break autonomy — the
  pipeline's automated review + gates are the quality bar, [D-12]);
- **require linear history** (squash/rebase merges — clean history);
- **no force-pushes, no deletions**;
- **admins not enforced** (an operator can still intervene by hand);
- **no required GitHub status checks.** The pipeline's own gates — run by the platform, not
  trusted from the agent — plus the post-rebase re-validation are the authority ([D-12],
  "policies authorize actions"). Requiring GitHub CI on top would duplicate the gates and
  couple the merge to check-context names; the up-to-date guarantee comes from §1's rebase,
  not from GitHub's `strict` setting.

## Consequences

- **Every merge lands on the current base, validated.** Semantic conflicts are caught by
  re-validation before the merge, not discovered in `main` afterwards.
- **Drift self-heals** without a human when the rebase is clean; only genuine textual
  conflicts (or a re-validation failure) stop for a person — and never as a crash.
- **Autonomy is preserved** by requiring a PR with zero approvals rather than a human review.
- **The rebase is cheap when idle**: `up_to_date` short-circuits (an ancestor check), so a
  ticket whose base didn't move pays only one `git fetch`.
- **Follow-up:** agent-assisted resolution of a *textual* conflict (rebase → hand the
  conflicted hunks to the executor → re-validate + re-review before merge), opt-in per
  project; and, if the base re-moves between rebase and the forge merge, a bounded re-try.
