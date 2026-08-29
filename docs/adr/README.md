# Architecture Decision Records

Short, numbered documents that capture a significant technical decision: its
context, the decision itself, and the consequences. One file per decision,
append-only — supersede an old ADR with a new one rather than rewriting history.

| # | Title | Status |
|---|---|---|
| [0001](0001-foundational-conceptual-model.md) | Foundational conceptual model of the platform | Accepted |
| [0002](0002-task-sizing-and-execution-budget.md) | Task-sizing gate & execution budget | Accepted |
| [0003](0003-autonomous-merge-on-current-base.md) | Autonomous merge on the current base | Accepted |
| [0004](0004-ci-aware-autonomous-repair.md) | CI-aware autonomous repair | Accepted |
| [0005](0005-post-merge-deploy-watch.md) | Post-merge deploy watch | Accepted |
| [0006](0006-review-repair-loop.md) | Bounded review-repair loop (1 attempt) | Accepted |
| [0007](0007-floor-frees-at-merge.md) | The floor frees at merge, not agent-done | Accepted |
| [0008](0008-on-demand-e2e-ticket.md) | On-demand e2e via a labelled ticket | Accepted |
| [0009](0009-durability-and-resilience-hardening.md) | Durability & resilience hardening (post-audit) | Accepted; shipped |
| [0010](0010-single-line-strict-park-on-impediment.md) | Single-line strict: park on any impediment (revises 0007) | Accepted; shipped |
| [0011](0011-suppression-repair-and-reviewer-vetted-pragmas.md) | Suppression-repair in the sandbox + reviewer-vetted coverage pragmas | Accepted; shipped |
| [0012](0012-perfect-resume-after-pause.md) | Perfect resume after a rate-limit pause (token visibility + honoured backoff + session resume) | Accepted; shipped |
| [0013](0013-preflight-sizing-effort-budget-recovery.md) | Pre-flight sizing gate, autonomous split, ticket effort budget, stuck-recovery | Accepted; shipped (P1–4) |
| [0014](0014-single-agent-execution-and-advisory-review.md) | Single-agent execution + advisory review (frontier-default, still agnostic) | Accepted; shipped |
| [0015](0015-tech-lead-diagnosis-and-slack.md) | The tech-lead: impediment diagnosis + Slack (one brain, two triggers) | Accepted; v1 shipped |
| [0016](0016-slack-actions-authorization.md) | Acting from Slack: read for all, write behind an allowlist | Accepted; v3 shipped |
| [0017](0017-knowledge-layer.md) | The Knowledge Layer: a derived, verifiable map the agent may not trust blindly | Accepted; Phase 1+2a shipped, off by default |
| [0018](0018-harness-roles.md) | Three harness roles: executor, reviewer, techlead | Accepted; shipped |
| [0019](0019-product-role-and-requirements-repo.md) | The product role: requirements are authored documents, in their own repo | Accepted; core implemented |
| [0020](0020-techlead-on-call.md) | The tech-lead is on call: classify by remedy, resolve what it can | Accepted; shipped |
| [0021](0021-agents-that-follow-through.md) | Agents that follow through: the open loop as the unit of memory | Accepted; shipped |
| [0022](0022-provider-seams.md) | Provider seams: an axis is agnostic when it is BORN with two | Accepted; shipped |
| [0023](0023-derive-dont-cache.md) | The map is derived, not learned: generate it where the checkout is (revises 0017) | Accepted |
| [0024](0024-conversational-memory.md) | Conversational memory: the thread is the unit, the raw log is sacred | Proposed |
| [0025](0025-delivery-closes-with-the-client.md) | Delivery closes with the client, not with the board | Accepted (implemented 2026-07-29) |
| [0026](0026-shared-vocabulary-beats-an-invented-word.md) | A word the reader already has beats one you invent | Accepted (implemented 2026-07-29) |
| [0027](0027-the-clients-board-is-not-our-test-bench.md) | The client's board is not our test bench | Accepted (2026-07-29) |
| [0028](0028-a-yes-is-read-a-done-is-not-asserted.md) | A "yes" is read; a "done" is not asserted | Accepted (2026-07-30) |
| [0029](0029-a-click-is-not-interpreted.md) | A click is not interpreted | Accepted (2026-07-30) |
| [0030](0030-what-the-parallel-audit-found.md) | What the parallel audit found, and the inversion it exposed | Accepted (2026-07-30) |
| [0031](0031-observing-is-not-correcting.md) | Observing is not correcting: when the safety net becomes the damage | Accepted (2026-07-30) |
| [0032](0032-the-requirement-cycle-happens-in-the-channel.md) | The requirement cycle happens in the channel; merging is not agreeing | Accepted (2026-07-30) |
| [0033](0033-decision-kernel.md) | The lifecycle decides in pure code; the engine only executes | Proposed (design only — no code changes with this ADR) |
| [0034](0034-extension-model.md) | Providers stay in-process for now, and the door stays open by a test | Accepted; the in-process step is decided (addendum 2026-08-26: entry points on every axis and on the role axis are the extension mechanism; the out-of-process door stays open by the guard, its trigger unchanged) |
| [0035](0035-knowledge-layer-on-by-default.md) | The knowledge layer becomes the behaviour, not an experiment | Accepted (2026-08-02) |
| [0036](0036-cross-repo-ordering.md) | Ordering across repositories: the product declares it, the floor enforces it | Proposed (design only) |
| [0037](0037-the-box.md) | The box: the client's image, an injected toolbox, and a proof before any pickup | Accepted |
| [0038](0038-the-platform-is-complete-channels-are-add-ons.md) | The platform is complete on its own; channels are add-ons | Accepted |
| [0039](0039-the-action-layer.md) | The action layer: what a human can ask the factory to do, written once | Accepted |
| [0040](0040-the-core-runs-on-the-clients-own-machines.md) | The core runs on the client's own machines; a cloud is an add-on | Accepted |
| [0041](0041-facts-are-files-not-a-protocol.md) | The roles read facts as files, not through a tool protocol | Accepted |
| [0042](0042-the-backfill-has-four-inputs.md) | The backfill has four inputs, and a legacy system is the product | Accepted for the thesis and input 2 (the code's history, shipped); inputs 3 and 4 proposed |
