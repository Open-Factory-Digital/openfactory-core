# ADR 0005 — Post-merge deploy watch (observe & notify, never block)

- **Status:** Accepted; shipped (forge deploy-status reads + the abandoned `DeployWatchWorkflow`
  + JobWorkflow spawn + per-project opt-in). Enabled for a production client (`deploy.yml` → dev).
- **Date:** 2026-07-16
- **Relates to:** ADR-0001 [D-12] (the pipeline deploys; the platform observes), ADR-0004
  (react to CI), the floor model (one job at a time, v1).

## Context

The driven repo deploys **itself**: on push to `main`, its own GitHub Actions `Deploy`
workflow ships to its own dev environment. Until now the platform's involvement ended
at the merge — it never looked at whether that deploy actually succeeded. A broken dev deploy
was invisible to the autonomy loop; you found out by checking the environment or your email.

Two forces shape the fix:

1. **We must know the deploy's outcome.** A merge that ships a broken dev is not "done" in any
   useful sense — someone needs to be told. This is the same resilience rule as ADR-0004:
   don't be blind to a failure downstream of us.
2. **Watching must not cost throughput.** v1 runs **one job at a time** (a single Claude token
   → serialized floor). A deploy takes minutes. If the job stayed alive watching the deploy,
   the floor would sit idle for the whole deploy on every ticket. The user's rule (verbatim):

   > Watch the deploy and notify, but block nothing — once the merge is done, free the floor
   > for the next task.

## Decision

**The merge completes the job. A separate, abandoned durable child watches the deploy.**

- When a job reaches **MERGED** and the project opts in (`post_merge_deploy` in its manifest),
  the JobWorkflow starts a **`DeployWatchWorkflow`** child with
  **`ParentClosePolicy.ABANDON`** and returns immediately. The parent completing **frees the
  floor** for the next ticket at the instant of merge — the watch is not on the critical path.
- The child **durably polls** the project's deploy run **on the merge commit**
  (`forge.deploy_run_status(sha, workflow)`, matched by `headSha` so a later unrelated run
  can't fool it) and, on a terminal outcome, **notifies** via the project's notifier:
  - **success** → `✅ dev deploy success` (info)
  - **failure** → `❌ dev deploy failure` + the run URL (error)
  - **timeout** (deploy stuck past `timeout_minutes`) → `⏱️ dev deploy timeout` (error) — a
    stuck deploy still produces a notification; the watch never hangs.
- The watch **can only notify** — it never merges, gates, or reopens the ticket. Worst case is
  a late or missed notification, never a stuck pipeline.
- **Opt-in per project.** No `post_merge_deploy` in the manifest → no watch is started. The
  framework stays provider-neutral: it observes *a* deploy workflow named in config, and knows
  nothing about what that workflow does.

### Why an abandoned child, not inline polling or an external poller

- **Inline** (the job polls the deploy before completing) would pin the floor for the whole
  deploy — the exact cost we're refusing.
- **An external scheduler** watching deploys is the silent-stall failure mode ADR-0004 already
  rejected: if it isn't running, the watch is silently lost.
- **An abandoned Temporal child** is durable (survives worker restarts), self-contained (its
  own timers, no compute while sleeping), and outlives its parent by design — exactly the
  "fire it and forget, but reliably" shape this needs. It runs on the **same task queue** as
  the parent (inherited), so it needs no separate worker or deployment.

## Consequences

- **Throughput unchanged.** A ticket is done at merge; the next one starts immediately. The
  deploy is watched "for free" on the side.
- **Deploy failures surface.** A red dev deploy now pings the team with the run link, instead
  of being invisible to the loop.
- **Watch ≠ repair (yet).** v1 only *notifies* a failed deploy. Auto-repairing a broken deploy
  (re-run, or open a fix ticket) is a deliberate follow-up — it would reintroduce work onto the
  floor and needs its own budget/gate design. The notification is the honest v1 boundary.
- **One more workflow type** (`DeployWatchWorkflow`) + two activities (`check_deploy_status`,
  `notify_deploy`) registered on the worker; proven against the time-skipping test env
  (success / failure / none→pending→success / timeout, and the JobWorkflow spawn-and-return).

## Implementation status

- **Shipped:** `forge.merge_commit_sha()` + `forge.deploy_run_status()` (GitHub via `gh run
  list --workflow`, matched on `headSha`; unit-tested). `DeployWatchInput`/`DeployStatusInput`/
  `DeployNotifyInput`. The `check_deploy_status` + `notify_deploy` activities. The
  `DeployWatchWorkflow` (durable poll → notify). JobWorkflow `_spawn_deploy_watch` on MERGED
  (abandoned child, best-effort start — a failed start never fails a merged job). Manifest
  `PostMergeDeploy` + `RunResult.post_merge_deploy` carried from the machine. Worker registers
  the new workflow + activities.
- **Enabled:** a production client's `.sdlc/project.yaml` →
  `post_merge_deploy: { workflow: deploy.yml, env: dev, timeout_minutes: 30 }`.
- **Not done (by design):** deploy auto-repair; prod-deploy watch (prod is tag-gated + human-
  approved, a different path).
