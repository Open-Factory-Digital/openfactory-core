# ADR 0012 — Perfect resume after a rate-limit pause (token visibility + honoured backoff + session resume)

- **Status:** **Accepted; shipped.**
- **Date:** 2026-07-19
- **Relates to** ADR-0009 (durability — the PAUSED→resume loop), ADR-0010 (single-line strict:
  a paused job PARKS holding the floor), and the provider-agnostic principle of ADR-0001 (the
  core deals in opaque abstractions; agent specifics live behind `CodingAgentAdapter`).

## Context

A partner running the platform live reported three things, all about the same moment — the agent
hitting a usage limit:

1. **"It never rotates the token, and I can't tell which token (1/2/…/N) is active."** The pool
   *did* fail over, but the panel surfaced nothing, so from the outside it looked stuck on one
   token.
2. **"Coming back from a rate limit it restarts the flow and re-writes code."** Confirmed in the
   logs (a production client, #37): a pause re-ran `run_job` from scratch every 30 min — replanning
   and re-implementing — which **re-burned the very limited tokens it was waiting on**. A vicious
   cycle: the pause *caused* more consumption.
3. **"A rate limit is a pause, not a redo. Review every hold/pause flow."**

The decision taken with the owner was **A + B + C2**:
- **A** — token visibility on the panel.
- **B** — honour the reset: stop hammering; don't re-burn.
- **C2** — *perfect* session resume (continue the attempt), not the lighter "just restart from the
  branch" (C1).

A hard constraint framed the whole design: **the platform must stay provider-agnostic** — "tomorrow
we might use Codex or others." So nothing Claude-specific may leak into the core.

## Decision

### A — Credential visibility (agnostic telemetry)

`AgentRunResult.credential = {index, total, id, rotated}` — filled by any adapter that has a
credential pool. The Claude adapter populates it from its token pool; **the core only surfaces it**
(a panel "active token" tile that shows `2/3` and flags `↻` on failover) and **never reads the
token**. `None` for a keyless/single-credential adapter. This is proof-of-rotation, visible.

### B — Honour the reset (don't re-burn)

- `RunResult.retry_at` round-trips the agent-reported reset time (an agnostic string).
- The durable resume backoff **grows** with consecutive resumes — 30 → 60 → 90 → 120 min, capped
  at 2 h (`JobWorkflow._pause_backoff`), on **both** the main and CI-repair pause paths. A
  pool-wide exhaustion is no longer re-launched every 30 min. `retry_at` stays **advisory** (vendor
  formats vary, clocks skew); the growing backoff is what actually paces the retry.
- The pause message no longer names a vendor ("the agent's usage limit"), keeping the core agnostic.

### C2 — Perfect resume (continue, don't restart)

An **opaque `resume_handle`** round-trips through the whole durable stack without the core ever
interpreting it: `AgentRunResult.resume_handle` → `RunResult.resume_handle` → carried in the
**Temporal workflow** state → `RunJobInput` → Fargate env `SDLC_RESUME_HANDLE` → `AgentContext`
→ back to the adapter. A Claude session id or a Codex handle both fit; only the adapter knows what
is inside.

Two things are preserved across the ephemeral-container boundary on a **rate-limit** pause:

1. **The partial code** (not Claude-specific): the orchestrator commits what the agent wrote and
   **pushes the branch**. The resumed run rebuilds its worktree from that branch
   (`prepare(checkout_existing=True)`) instead of a fresh branch off base. This alone means resume
   *continues the code* rather than rewriting it.
2. **The agent session** (Claude-specific, behind the adapter): the adapter takes the CLI's session
   state **out of the box that wrote it** (`export_home_dir` on the sandbox port), keeps it in the
   deployment's **session store**, and encodes `{phase, session, state_key}` into the handle. On
   resume, if the paused **phase matches** the current one, it puts that state back into the new
   box and passes `claude --resume <id>` so the agent continues its own reasoning. Phase-scoping
   matters: an `execute` session must not be resumed into a `plan` call.

   **Amended by #118 (2026-08-15).** Both halves of that sentence used to say "S3" and "the
   orchestrator's own `~/.claude`", which are the same thing only when the whole job runs inside
   one task — the cloud shape. On the default local box the harness runs through `docker exec`, so
   its session lived in the container's HOME and died with it: a `docker compose` deployment could
   not resume at all, and one that configured a bucket anyway uploaded the WORKER's transcripts
   (the judging roles', containing client repository content) while still resuming cold. The
   session now comes from the box, and where it is kept is an axis with a free row —
   `session_store.FileSessionStore` on the machine's own disk, `s3_session_store.S3SessionStore`
   for a deployment whose boxes run where the worker cannot reach them. **A pause costs a free
   deployment exactly what it costs a paid one.**

**Why Temporal owns it:** the `resume_handle`, the resume counter, the backoff timers, and the
park/resume signals are all **durable workflow state** — they survive a worker crash or a deploy
mid-pause. Fargate is the disposable arm; Temporal is the memory of "where I stopped." The handle
is the bridge Temporal carries from a dead container to the next one.

### The failover is cyclic and continues the session (not linear, not a redo)

The credential pool's failover — the thing that runs *before* we ever pause — had two
defects a partner caught in practice:

- it was **linear**: the active index only advanced forward and stopped at the end of the
  array, so a job whose sticky index sat on the last token gave up without trying the
  earlier ones;
- it **restarted** the agent on each new token (a cold `claude -p`), replanning and
  redoing work already done — which *drains* the fresh token repeating itself.

Now the failover is **cyclic** (`i → (i+1) mod N`, wrapping back to the first) and
**continues** the session on the next token (`--resume` with the just-failed session id —
the transcript is still in the box that just ran, so this needs no store at all). Each token is
tried at most once per lap; only when a full lap finds them all exhausted does the job
PAUSE (then B's growing backoff + C2's preserve apply). "Coming back to the first"
meaningfully happens across that pause, when a token's window may have reset — retrying an
as-yet-unreset token inside the same lap would be pointless. See
[rotation-and-retention.md](../rotation-and-retention.md) for the exact rules.

### Degrade-safe by construction

Every new step is opportunistic and falls back to today's behaviour if anything is missing:
- No box to take the session from (a judging call, a box that answers `transfers_state=False`) →
  the handle carries an empty `state_key`; resume is **code-only** (the branch continues, the
  session restarts cold). A missing *bucket* is no longer one of these cases: with none, the free
  store keeps the session on this machine.
- Branch push fails → no handle returned → the resume starts fresh, never checks out a missing
  branch.
- Restore fails / snapshot missing / the transcript is not in the box afterwards → `--resume` is
  **not** passed (it would error); run cold.
- A foreign/garbled handle decodes to `None` → cold.

So C2 is a **bonus, never a new failure mode**.

### Infrastructure

**Free deployment (the default): none.** Snapshots are files under `OPENFACTORY_RESUME_DIR`
(`/var/lib/openfactory/resume`, on the state volume that already carries the registry and the
proofs), bounded two ways: a job's new snapshot replaces its older ones, and anything past a
7-day retention window is swept from the write path.

**With a cloud:** a private, encrypted S3 bucket (`<prefix>-resume-<account>`) with a matching
**7-day lifecycle expiry** (snapshots are throwaway; they must never accumulate cost the way old
images did). The sandbox task role gets read/write **only** under the bucket's `resume/` prefix
(least privilege) — which is why the key format is identical on both stores.

## Consequences

- A rate-limit pause is finally a *pause*: the agent resumes its session and its code, without
  replanning or re-burning tokens; the panel shows which token is live and that failover happened.
- The core gained no provider knowledge — `resume_handle` and `credential` are opaque; the Claude
  specifics (`--resume`, `.claude/projects`) live in `claude_code.py`, moving bytes in and out of a
  box is a neutral capability on the sandbox port (`transfers_state`), and the one vendor line is
  in `s3_session_store.py`, which the ledger names.
- Session snapshots are transcripts that can contain code → the bucket is private + encrypted +
  short-TTL. Same v1 owner-accepted posture as the bot-token-in-task tradeoff (ADR-0001 D-17).
- **Proof status:** logic is covered by unit + workflow-level tests (handle round-trip, S3
  snapshot/restore, phase-scoped resume, degrade paths, the Temporal handle-threading, and a live
  worktree-restore against a real git remote). End-to-end proof on the deployed runtime awaits the
  token pool resetting (it was exhausted at ship time) — per "validate in the cloud, not just local".
