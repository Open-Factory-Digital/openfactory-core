# ADR 0011 — Suppression-repair in the sandbox + reviewer-vetted coverage pragmas

- **Status:** **Accepted; shipped.**
- **Date:** 2026-07-18
- **Refines** the gate-suppression guard (engineering.md #12, first shipped with ADR-0001's
  autonomy model and re-affirmed in ADR-0009). Relates to ADR-0006 (review-repair loop, the same
  shape) and ADR-0007/0010 (what holds the floor).

## Context

The suppression guard makes a PR go to a **human** whenever its diff adds a gate-suppression
comment (`# pragma: no cover`, `noqa`, `type: ignore`, `nosec`). It exists for a real reason
(#207/#208): an agent smuggled untested prod code hidden under `# pragma: no cover`, which passed
the 100%-coverage gate because the pragma excluded the line — the guard + the reviewer were the
only catches.

But it is far too blunt **for a codebase that enforces 100% coverage**. Live (a production
client, #69):
- The agent wrote a correct feature, all gates green, reviewer **approved (score 90)**.
- It added **4 `# pragma: no cover - thin wiring`** on composition-root lines (registering a
  router, instantiating a service) — the codebase's own convention (**227 pre-existing** such
  pragmas; `--cov-fail-under=100` is set in the project's `pyproject.toml`, so untestable wiring
  *must* be pragma'd to hit 100%).
- The guard flagged it → human-review → the PR sat **7½ hours** holding the single-slot floor,
  and — worse — the panel didn't surface "waiting for your merge" (a separate visibility gap).

So the guard fires on **nearly every feature PR** here (every new endpoint pragmas its wiring),
turning "autonomous" into "the operator merges every PR by hand" — for a person who, reasonably,
doesn't want to be the gate for a suppression mechanism they'd have to learn to audit.

Two things were wrong: (1) the platform **detected** the suppression deterministically but did
**nothing** with it except hand it to a human — it never let the agent try to *resolve* it; and
(2) it treated a coverage pragma (the house convention) exactly like a `nosec` (silencing a
security scan).

## Decision

**1. Suppression-repair loop — the sandbox resolves it, not the operator.**
When the diff adds suppression(s), a bounded loop (`suppression_repair_max_attempts`, default 1)
feeds them back to the executor before a human is ever involved: *remove* each one by making the
code properly testable, or *keep* only the genuinely-untestable ones (thin wiring, unreachable
defensive branch, external I/O) with a clear reason — and never add a new one or silence
lint/type/security. Every gate is re-run; a fix that breaks a gate (e.g. removing a pragma drops
coverage below 100%) holds with a clear reason. This is the same shape as the gate-repair and
review-repair loops (ADR-0006).

**2. Coverage pragmas are reviewer-vetted; hard suppressions stay human-gated.**
Whatever survives the loop is classified:
- **`# pragma: no cover` / `nocov`** (coverage) — the house convention for untestable wiring.
  May **auto-merge**, but *only* when an **independent review has vetted it** (approved, not
  rejected). The reviewer already judges pragmas well — it **rejected** #207 (score 30) and
  **approved** #69's legit wiring (score 90). With **no reviewer configured**, any surviving
  suppression still goes to a human.
- **`noqa` / `type: ignore` / `nosec`** (silencing a real lint / type / security error) — rare
  and genuinely suspicious. **Always human-gated**, even with an approving review.

The deterministic detection stays (it's cheap and reliable); what changed is that detection now
*triggers a repair + a reviewer judgment* instead of *dumping on a human*.

## Consequences

- **The operator stops merging legit pragmas by hand.** A thin-wiring pragma that the reviewer
  vets auto-merges; only a genuinely-suspicious suppression (or a no-reviewer project) reaches a
  human. #69's exact pain is gone.
- **The #207 protection is preserved** through defence-in-depth: the agent is first asked to
  remove the pragma (a malicious/unnecessary one often can be), then the independent reviewer
  vets what remains (it caught #207), and hard suppressions never auto-merge at all.
- **The deterministic guarantee is deliberately relaxed for coverage pragmas** — it becomes
  "agent-minimized + reviewer-approved" rather than "always human". Accepted: the reviewer is a
  credible, independent check with a track record, and the status quo (human-merge every feature
  PR) was worse for this codebase.
- **A suppression-repair that breaks a gate holds** — so the loop can never *lower* quality to
  pass; the worst case is the same human review as before, with a clear reason.
- **Alternative not taken:** lowering the project's coverage bar below 100% (so wiring wouldn't
  need pragmas at all) is a valid *project-side* lever, but it's the project team's call, not
  the platform's — the platform stays agnostic to the number.

## Implementation

`Manifest.suppression_repair_max_attempts` (default 1). `machine.run`: after computing
`_added_suppressions(diff)`, a loop calls `agent.repair(_suppression_repair_brief(details))`,
re-validates (hold on a broken gate), recomputes; survivors are noted for the reviewer.
`merge_policy.should_auto_merge`: `_hard_suppressions()` (noqa/type-ignore/nosec) → always False;
a surviving coverage pragma → False only if the review is absent or rejected. Tests cover
remove→auto-merge, keep→reviewer-vet→auto-merge, hard→human, coverage+no-reviewer→human, and the
`should_auto_merge` matrix.
