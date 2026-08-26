# ADR 0013 — Pre-flight sizing gate, autonomous split, ticket effort budget, and stuck-recovery

- **Status:** **Accepted; shipped (Phases 1–4). Phase 5 retirement of the in-run gate awaits live catches.**
- **Date:** 2026-07-19
- **Supersedes** the *sizing* role of `max_turns` and (once proven) the in-run plan gate of
  ADR-0002. Relates to ADR-0010 (single-line strict), ADR-0012 (perfect resume / preserve),
  and the dark-factory principle: **humans decide; agents debug.**

## Context — the #37 case study

A production client's **#37 "Plan 92 — Guest-surface security hardening + rate limits"** ran on
the fixed pipeline and exposed a design incoherence end-to-end:

1. The ticket is **two features** (guest-surface hardening AND rate limiting) — it fails
   INVEST on its *text* alone. Nothing looked at that.
2. The sizing gate (ADR-0002) runs **inside the already-paid Fargate task**, *after* clone +
   setup + a planner pass — and it is only the **planner's self-estimate** (`files:`/`steps:`
   lines or a `SPLIT NEEDED` verdict it writes about itself). The planner under-estimated;
   the gate believed it; the executor ran.
3. The executor did **130 actions across ~15 files ($14)** and hit the **120-turn cap** —
   which returned `is_error` + empty result → `ON_HOLD` "agent stopped:" (blank), and the
   ephemeral container died **discarding all of it**. No branch, no PR, nothing to resume.
4. The escalation target was a **human reading code** — which breaks the lights-out essence.

Three separate defects: sizing checked **too late and too credulously**; `max_turns` acting
as a **size limit** when it can only ever be an **anti-runaway backstop**; and a stop path
that **discards work** instead of preserving and continuing (the exact sin ADR-0012 was
built to end, but only wired for rate-limit pauses).

## Decisions

### D1 — Preserve on ANY stop, not just rate-limit pauses

`_preserve_partial` (commit + push branch + session snapshot + opaque `resume_handle`)
extends to **every executor-side stop that leaves work in the tree**: turn-cap stop,
agent-stopped-empty, cost/effort-ceiling holds. A hold that carries a `resume_handle`
becomes a **resumable hold**: the operator's (or recovery's) Resume **continues** the
attempt; a hold without a handle keeps today's fresh-restart semantics (spec refinement
etc.). The handle's presence is the signal — no new state enum, no vendor leakage.

### D2 — Pre-flight sizing gate on the WORKER, before any Fargate

A new **preflight** step runs on the long-lived worker (cheap, no task spin-up) before
`run_job` ever launches Fargate. Two layers, both read-only:

- **Text layer (INVEST):** an LLM judges the *ticket text* — one outcome? small?
  independent? estimable? testable acceptance criteria? Catches "hardening + rate limits"
  (= two features) for the cost of one short prompt, with no repo at all.
- **Code layer (reality check):** using the worker's **cached checkout** (D6), a read-only
  sizer role explores the repo and estimates the real blast radius (files/steps) against the
  manifest budget (`max_plan_files`/`max_plan_steps`). Catches "sounds small, touches 15
  files" — the failure the text layer structurally cannot see.

Verdict ∈ `fit` | `split` (with a proposed decomposition) | `unclear` (→ needs_refinement
with questions). **Only a confident, both-layers-agree oversize** triggers a split; doubt
lets the ticket run — the effort budget (D4) is the backstop for gate mistakes. The
existing in-run plan gate **stays during transition** as a second net and is retired once
preflight has caught real oversizes live.

### D3 — Autonomous splitter (`.a`/`.b` nomenclature)

On a `split` verdict the platform **acts, not asks**: it creates child tickets via the
tracker — titled with the plan-suffix convention already in use (`Plan 92a — …`,
`Plan 92b — …`, mirroring the manual #72 → 88.4a/88.4b split) — each with a full INVEST
body (objective, acceptance criteria, out-of-scope, explicit ordering/dependency note),
comments on the original linking the children, and closes the original as an epic.

**Conservative default:** children land in **Backlog + a notification** — the operator
drags them to TO-DO in the order they want (sequencing is a *decision*, so it stays human
by default). A manifest flag (`split_autorun: true`) can later drop the first child
straight into TO-DO for full lights-out. Requires a new `create_ticket` on the
`TrackerAdapter` Protocol (GitHub impl: `gh` issue create + board add + status column).

### D4 — `max_turns` demoted; a ticket-wide EFFORT BUDGET replaces its sizing role

- The per-invocation `max_turns` stops being a size limit: it rises to a loose
  **anti-runaway backstop** (default 200) whose only job is "the agent is spinning".
  Hitting it is no longer a bare hold — it flows into D5 recovery, with D1 preservation.
- A new **cumulative effort budget per ticket** (`effort_budget_turns`, manifest, default
  ~400) sums turns across executor + repairs + recoveries + resumes (turn counts come from
  the result envelope's `num_turns`; the workflow carries the running total across
  attempts). Breaching it is the real "this ticket is consuming too much" signal →
  preserve + hold with an explicit reason ("effort budget exhausted after N turns /
  M recoveries — the preflight gate under-sized this; split the remainder"). On
  subscriptions cost-USD is notional, so *turns* are the honest effort currency.

### D5 — Stuck → autonomous RECOVERY, humans only for decisions

When the executor stops without finishing (turn-cap, empty stop) the job does **not** go
to a human. Bounded recovery ladder, all inside the effort budget:

1. **Attempt 1 — continue:** resume the same session (`resume_handle`) with a "you were
   cut off — continue and finish" brief. Cheapest; the in-flight reasoning survives.
2. **Attempt 2 — fresh recovery agent:** a new `recovery` role with clean context: the
   diff so far, the last N actions, the failure shape — instructed to *assess, then finish
   or simplify* (it may cut scope to reach a mergeable state, noting what it cut).
3. **Exhausted → resumable hold (D1)** whose message is **decision-shaped** ("finished 80%,
   preserved on branch `sdlc/37`; remaining: X — split remainder or raise budget?") — never
   "go read the code".

Recovery reuses the existing repair-loop shape (CI-repair / review-repair / suppression-
repair) — same bounded-attempts pattern, one new role file. `recovery_max_attempts`
(manifest, default 2, 0 disables).

### D6 — Worker repo cache (clone once, sync per use)

The worker keeps **one cached checkout per project** for read-only work (preflight's code
layer): clone on first touch, then `git fetch origin <base> && git reset --hard
origin/<base> && git clean -fdx` per use (reset, never pull — a cache must be identical to
base, not merged into). Corrupt cache → delete + reclone; reclone fails → **skip the code
layer** and gate on text alone (degrade, never block). Worker restarts (deploys) simply
re-clone on first touch — acceptable; no EFS until proven needed. The **executor's fresh
isolated clone in Fargate is unchanged** — the cache is only ever read.

### D8 — A degraded gate must be LOUD (live lesson from #37)

The gate is degrade-safe by design (D7-1) — any failure runs the ticket as before. But the
first live run exposed the flip side: **the worker ran the sizer's agent with no credential**
(the worker task-def carried the Temporal + bot-key secrets but not the agent token pool — the
worker never ran the agent before this ADR), so every pre-flight silently DEGRADED to `fit` and
`#37` ran unsized. Degrade-safe hid a broken gate.

Fix, two parts: (1) the worker task-def now injects the same agent credentials as the sandbox
(`CLAUDE_CODE_OAUTH_TOKEN` + `SDLC_AGENT_TOKENS` from SSM) and the planner model, and its
execution role can read those params. (2) **A FAILURE to size is no longer silent:** an
error-degrade (missing token, clone/sizer error, unparseable verdict) posts a ⚠️ warning
*comment on the ticket* ("pre-flight sizing did not run (<reason>) — this ticket proceeds
UNSIZED") and logs it; only *intentional* skips (`enabled: false`, e2e tickets) stay quiet.
So a broken gate is always visible, never a silent "ran as fit." General rule: degrade-safe
must be paired with degrade-VISIBLE, or a broken safety net looks identical to a working one.

### D7 — Implementation invariants (binding for the implementer)

1. **Degrade-safe everywhere:** preflight activity error → log + run the ticket anyway
   (today's path); splitter error → needs_refinement with the reason; cache error →
   text-only verdict; recovery error → next rung of the ladder. **No new step may become a
   new way to block the pipeline.**
2. **Agnostic:** sizer/recovery are roles behind `CodingAgentAdapter`; the core sees
   verdicts and opaque handles, never vendor specifics. The preflight verdict is a plain
   Pydantic model.
3. **Single-line strict (ADR-0010) preserved:** a split completes the epic's workflow only
   after children exist + the original is closed/commented — the floor frees deliberately,
   never silently. Every non-progressing outcome still parks.
4. **Never discard work:** preservation (D1) runs before ANY terminal report.
5. **Temporal determinism:** all LLM/git/API work in activities; the workflow only routes
   on returned values. Turn totals accumulate as workflow-local state from activity results.
6. **Bounded:** every loop has a cap; the effort budget caps the sum of all of them.
7. **Secrets:** the worker's agent invocations use the same pool/scrub machinery as the
   sandbox (`SDLC_AGENT_TOKENS` never reaches child processes; only the active token env).

---

## Implementation plan (phased — each phase ships alone, tested, deployable)

> Verified starting facts: `TrackerAdapter` has **no** `create_ticket`;
> `docker/worker.Dockerfile` has git+gh but **no node/claude CLI** (the base sandbox image
> pins `@anthropic-ai/claude-code@2.1.219`); the in-run plan gate reads the planner's
> self-reported `files:/steps:`; turn counts are available as `num_turns` in the CLI's
> result envelope (already parsed file: `claude_code.py::_parse_stream`).

### Phase 1 — Preserve-on-any-stop (stop the bleeding first)
*Small, uses existing ADR-0012 machinery, kills the "#37 lost $14" failure mode.*

- `machine.py`: on executor `not ok` with work in tree (diff non-empty) and on
  cost/effort-ceiling holds → call `_preserve_partial` before `_hold`; carry the returned
  handle on the hold's `RunResult.resume_handle`.
- `workflow.py::_lifecycle`: impediment Resume threads `result.resume_handle` when present
  (resumable hold) instead of always clearing it; absent → today's fresh restart.
- `claude_code.py`: (already shipped) turn-cap stops surface a readable reason.
- **Tests:** stop-with-partial pushes the branch + carries the handle; resume continues
  (worktree restored + handle to agent); spec-refinement hold still restarts fresh.
- **Risk:** pushing a broken tree — acceptable: it's a work branch, CI/gates rerun on
  resume; never merged un-validated.

### Phase 2 — Worker repo cache + pre-flight gate (text + code)
- New `sdlc/runtime/repo_cache.py` (`RepoCache.sync(project) -> Path`) with the D6
  semantics + a lock per project (two pollers must not fetch concurrently).
- `docker/worker.Dockerfile`: add nodejs/npm + the **same pinned** claude CLI as the base
  image (worker now runs read-only agent calls).
- New role `sdlc/org_defaults/roles/sizer.md`: INVEST text judgment + (when a checkout is
  provided) read-only blast-radius estimate; output a strict structured verdict
  (`verdict: fit|split|unclear`, `estimated_files`, `children:[{title,objective,criteria}]`,
  `reasons`). Parsing must tolerate prose around the block (regex the fenced YAML/JSON).
- `io.py`: `PreflightInput{project,issue}` / `PreflightVerdict` models.
  `activities.py`: `preflight_check` (worker-side; RepoCache + sizer via the existing
  adapter on a `WorktreeSandbox` over the cache — read-only tools only).
- `workflow.py`: call `preflight_check` before the first `run_job` **only** (never on
  resumes/repairs); route: `fit` → run_job as today; `unclear` → needs_refinement park with
  the questions; `split` → Phase 3 activity (until Phase 3 lands: park as needs_refinement
  with the proposed decomposition in the comment — still a strict improvement).
- Manifest: `preflight: {enabled: bool = true, code_check: bool = true}`.
- **Tests:** cache clone-once/reset/corrupt-reclone/fallback; verdict parsing (all three +
  garbage → `fit` with a warning, degrade-safe); workflow routing per verdict; preflight
  activity failure → job runs anyway; no preflight on attempt > 0.
- **Risk:** worker image grows (node) — one-time; gate false-positives — mitigated by
  "confident-only splits" + effort budget as the backstop + `preflight.enabled` kill-switch.

### Phase 3 — Splitter
- `TrackerAdapter.create_ticket(title, body, labels?) -> ref` + GitHub impl (issue create,
  add to board, set column Backlog).
- `activities.py`: `split_ticket` — derive `Plan Na/Nb` titles from the parent's plan
  number, create children with full INVEST bodies + ordering note, comment on + close the
  parent, notify. Idempotent: re-running must not duplicate children (search-first by
  title).
- `workflow.py`: `split` verdict → `split_ticket` → workflow completes (floor frees; the
  panel shows "split into #Xa #Xb" as the final state note).
- Manifest: `split_autorun: bool = false` (reserved; not wired in this phase).
- **Tests:** idempotent creation; parent closed + commented; children in Backlog; failure →
  needs_refinement park (degrade); nomenclature (`92a`, `92b`) derived correctly including
  when the parent title has no `Plan N` (fallback: `#37a`).

### Phase 4 — Effort budget + recovery ladder
- `manifest.py`: `effort_budget_turns: int = 400`, `recovery_max_attempts: int = 2`;
  `SDLC_MAX_TURNS` default raised to 200 (backstop only).
- `claude_code.py`: surface `num_turns` on `AgentRunResult` (agnostic int).
- `machine.py`: accumulate turns across plan/execute/repairs; on executor stop-without-
  finish → recovery ladder (continue-session, then `recovery` role) while under budget;
  budget breach → preserve + resumable hold with the decision-shaped message.
  `workflow.py`: carry the cumulative total across resumes (input field, like
  `resume_handle`).
- New role `sdlc/org_defaults/roles/recovery.md` (assess → finish or simplify; may cut
  scope, must say what it cut; never widen scope).
- **Tests:** turn accounting sums across phases/attempts; ladder order + caps; budget
  breach preserves + holds with reason; recovery disabled (=0) reproduces today's path;
  a recovery that finishes proceeds to validate/PR normally.

### Phase 5 — Retirement + docs + live validation
- After ≥2 live oversize catches by preflight: remove the in-run plan gate (ADR-0002 note),
  and drop `max_turns` mentions as a sizing device everywhere
  (`rotation-and-retention.md`, `operations.md`, role files).
- Live validation checklist: (a) an obvious épico in TO-DO → split to `.a/.b` in Backlog,
  floor freed, no Fargate launched; (b) a fit ticket → preflight `fit` note in the feed,
  normal run; (c) a turn-cap stop → recovery continues and lands the PR; (d) budget breach
  → resumable hold, Resume continues from the preserved branch.

### Immediate actions (independent of the phases)
- Deploy the two pending commits (`2fbca5d` fp tile, `1982105` readable turn-cap reason) —
  held back to not disturb #37's live run, which is now parked.
- **#37 disposition (owner decision):** redo it — the operator skipped it to free the floor;
  re-dropping it into TO-DO makes it the splitter's first live case (the preflight gate will
  judge it `split` and emit Plan 92a/92b autonomously).

## Consequences

- Sizing moves to the **cheapest possible point** (worker, pre-Fargate) and becomes
  two-layered (text + code) instead of one self-estimate inside a paid task.
- `max_turns` stops masquerading as a size policy; effort is governed by a **ticket-wide
  budget** that preserves instead of discarding.
- Humans exit the debug loop: oversize → **split** (autonomous), stuck → **recovery**
  (autonomous); a person is consulted only for *decisions*, keeping the factory dark.
- The worker gains read-only agent duties (node + CLI in its image; repo cache on disk) —
  a deliberate erosion of "worker = pure orchestrator" traded for killing per-ticket
  Fargate spin-up on the cheap path.
- New failure surfaces (cache, splitter, recovery) are all degrade-safe by construction
  (D7-1): their worst case is today's behavior.
