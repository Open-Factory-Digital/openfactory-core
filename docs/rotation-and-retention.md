# Rotation & retention — the exact rules

> **§2 drives `infra/`, which is not in this tree.** The image registry and its lifecycle
> policies belong to the reference deployment on one cloud, which ships with the
> `openfactory-aws` **add-on package** ([STATUS.md](STATUS.md) lists what leaves with it); every
> `infra/…` path here is a path inside that package's checkout. §1, §3 and §4 are the platform's
> own and hold on any deployment, cloud or none.

Four things that expire, and each must be unambiguous, because getting one wrong either drains
credits, deletes an image that is still in use, or loses the record of what shipped. This is the
authoritative reference; ADR-0012 records *why* the pause/resume rules exist.

- [1. Token-pool rotation & pauses](#1-token-pool-rotation--pauses) — how a rate limit is handled
- [2. Image retention & prune](#2-image-retention--prune) — what deletes which images, and what is protected
- [3. The conversation and its staged decisions](#3-the-conversation-and-its-staged-decisions) — how long a thread and a proposed action last
- [4. The engine's memory, and the record that outlives it](#4-the-engines-memory-and-the-record-that-outlives-it) — how long a finished job is answerable for

---

## 1. Token-pool rotation & pauses

The coding-agent adapter (e.g. Claude Code) is given a **credential pool** — a JSON
array in `OPENFACTORY_AGENT_TOKENS` (`[{id, token, type}]`), falling back to a single
`CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY`. The pool exists so one exhausted or
revoked credential doesn't halt a job.

The pool is **provider-agnostic to the core**: the orchestrator never sees a token. It
only round-trips two opaque values the adapter fills — `credential` (which one is live,
for the panel) and `resume_handle` (how to continue a paused session). All Claude
specifics live in the adapter.

### The rules

**R1 — Failover is CYCLIC, not linear.** On a rate-limit/auth stop the active index
advances **wrapping around** (`i → (i+1) mod N`). A job whose sticky index sits on the
last token still comes back to the first. (The old behaviour stopped at the end of the
array and gave up — a bug.)

**R2 — Rotation CONTINUES the session; it never replans.** When we move to the next
token we hand it the just-failed **session id** (`--resume`), so it picks up where the
previous one stopped — e.g. at 80% — instead of running `claude -p` cold and redoing
work. Redoing would drain the fresh token repeating what's already done. The session
transcript is still in the box that just ran, so same-run rotation needs **no store at
all** (a store only backs the *cross-box* durable resume — R6).

**R3 — One lap, then pause.** Each token is tried **at most once per lap** (`attempts <
N`). Retrying a token that was rate-limited 200 ms ago is pointless — its window hasn't
reset. So when a full lap finds **every** token exhausted, the failover stops and the
outcome survives:
- **any** token in the lap was rate-limited → **PAUSED** (auto-resumes durably) — even if
  another token failed auth. A revoked token seen last must not turn a job that would
  self-heal on the other token's reset into a human-only hold (mixed-lap rule);
- **every** failure in the lap was auth → **ON_HOLD** (a human must fix the tokens;
  auto-retrying revoked credentials is futile).

**R3b — A pause is only believed from an ERROR.** Limit/auth detection runs **only on
error envelopes** (`is_error` / non-zero exit). The result text of a *successful* run is
the agent's own summary — a ticket about rate limiting legitimately says "429" there, and
classifying that as a pause would lap the pool and park a healthy job.

**R4 — "Come back to the first" happens across the pause, with a wait.** The meaningful
return to token 0 is **after the backoff**, not inside a lap: the durable resume starts a
fresh lap later, when a token's limit window may actually have reset. Waiting happens in
the **durable pause** (zero compute), never by sleeping inside a Fargate task.

**R5 — Backoff GROWS while the whole pool stays down.** The resume backoff is
`30 → 60 → 90 → 120 min`, capped at **2 h** (`JobWorkflow._pause_backoff`), on both the
main and the CI-repair pause paths. A pool-wide exhaustion is not re-launched every
30 min re-burning the tokens it's waiting on. The agent-reported reset time (`retry_at`)
is **advisory only** — surfaced on the panel, never trusted as a precise sleep (vendor
formats vary, clocks skew); the growing backoff paces the retry.

**R6 — Perfect resume across the pause (C2).** When a rate-limit pause finally parks the
job, the work is preserved so the resume *continues* instead of restarting:
- the **partial code** is committed and the branch pushed; the resumed run rebuilds its
  worktree from that branch (`checkout_existing`),
- the **agent session** is taken out of the box that wrote it, kept in the deployment's
  session store, and continued with `--resume` on resume (phase-scoped: an `execute`
  session is only resumed into an `execute` call).
The store is **free by default** — a directory on this machine (`OPENFACTORY_RESUME_DIR`,
swept after 7 days). A deployment whose boxes run where the worker cannot reach them sets
`OPENFACTORY_RESUME_BUCKET` and the session crosses through S3 instead. Neither is a switch:
**a pause costs a free deployment exactly what it costs a paid one** (#118).
Every part **degrades safely**: no box to take it from / push fails / restore fails / the
transcript is not in the box afterwards / foreign handle → a fresh restart, never a new
failure mode.

**R7 — Panel visibility.** The panel shows the **active token** as `index/N (id·fp)` — e.g.
`1/2 (secondary·a1b2c3)` — and flags `↻` when a failover happened (proof the pool rotates).
`fp` is a non-reversible fingerprint (last 6 hex of `sha256(token)`) so two tokens with
similar ids stay distinguishable **without ever exposing the secret** — the credential is
computed by the adapter (which holds the token); the core only surfaces the opaque dict. The
tile updates at **phase boundaries** (plan/execute complete), not mid-phase. A paused job shows
`⏸ paused (usage limit) — resumes after …` and holds the floor (single-line strict, ADR-0010).

### One picture

```
execute on token 1 ─ 80% done ─ rate limit
        │  R1 cyclic + R2 continue (--resume, no redo)
        ▼
token 2 continues @80% ─ rate limit ─┐
        │  R1 wrap                    │ R3: one lap, all tried
        ▼                             │
token 0 continues ─ rate limit ──────┘ → whole lap exhausted
        │  R3 → PAUSED, R6 preserves code+session
        ▼
   durable pause ─ R5 backoff 30→60→90→120m (R4: token windows reset here)
        │
        ▼
   resume: fresh lap from token 0, R6 --resume → continues where it stopped
```

### Where it lives

- `openfactory/adapters/agent/claude_code.py` — `_invoke` (cyclic failover + continue),
  `_snapshot_session`/`_restore_session`/`_encode_handle` (C2), `_detect_pause` (regex).
- `openfactory/runtime/temporal/workflow.py` — `_pause_backoff`, the `_lifecycle` pause loop.
- `openfactory/orchestrator/machine.py` — `_paused`, `_preserve_partial`, `_emit_credential`.

---

## 2. Image retention & prune

Every deploy pushes a new immutable-sha image, and without a lifecycle policy they accumulate
until something fails on a full disk. Two counts bound that, and the difference between them is
arithmetic rather than taste.

| repository | keeps the last | why that number |
|---|---|---|
| `<prefix>-python` — the box image | **20** | one push per deploy, so 20 images is 20 deploys of history |
| `<prefix>-worker` — worker **and** panel | **30** | TWO images per deploy (worker `sha` + panel `sha-amd64`), so 30 is 15 deploys |

`prefix` is the terraform variable that names every resource of a deployment; it is `openfactory`
unless that deployment's `deployment.tfvars` pins another (an installation made before 2026-08-24
pins the platform's former name, and that pin is the only place it survives).

**Why the slack matters, and why a keep-10 was raised.** `deploy.sh` pushes **before**
`terraform apply`, so consecutive failed applies leave the live pins — the worker's task
definition, the panel's service — on aging tags, and a pruned pinned tag is a
`CannotPullContainerError` on the next task start (audit finding). Ten images was five deploys of
slack for a repository that holds two per deploy. The operator's local Docker gets a
dangling-only `docker image prune -f` at the end of each deploy.

**Where a reader checks these, since they are not in this tree.** Each is a `countNumber` on an
`aws_ecr_lifecycle_policy` in `infra/terraform/alerting.tf` — one for `sandbox`, one for
`worker` — which ships with the `openfactory-aws` add-on package rather than with the core
(`docs/STATUS.md`'s table). What is actually live is a different question from what is declared,
and during an incident it is the one that matters:

```
aws ecr get-lifecycle-policy --repository-name <prefix>-worker
```

**The rule that outlives the numbers: a retention rule must match how images are TAGGED.** A
count rule acts only on its **own** tag filter, and a registry ranks by recency — so a catch-all
"keep last N" over a repository whose tags have different cadences ranks the rare ones as old and
evicts them. Scope each rule to a tag prefix that can only select the cadence it is for, and
**preview before changing one**:

```
aws ecr start-lifecycle-policy-preview --repository-name <repo>
aws ecr get-lifecycle-policy-preview   --repository-name <repo> \
  --query "previewResults[].imageTags[]"     # <-- must NOT list a tag you release from
```

That preview is what caught a catch-all policy marking release tags for expiry before the
registry acted on it.

### Where it lives

- the add-on package's `infra/terraform/alerting.tf` — both lifecycle policies and their counts.
- the add-on package's `infra/deploy.sh` — the push, the local dangling prune, and the ordering
  the slack above exists for.

---

## 3. The conversation and its staged decisions

The tech-lead thread on the panel — what a person asked, what the factory answered, and what it
proposed doing about it — is kept in the **same store as everything else the factory says**
(`openfactory/memory/messages.py`, a sqlite sink under `OPENFACTORY_STATE_DIR`). No database to
provision, no account, no cloud: a deployment that buys nothing keeps its conversation.

Before this, the thread lived in a JavaScript array in whichever browser tab produced it. A
refresh lost it; a second screen never had it; and a **staged suggestion** — the one concrete
action the tech-lead proposes, which a person approves by pressing it — vanished with it. That is
a wait ending in nothing, the one shape this platform is not allowed to have.

### The rules

| what | how long | why |
|---|---|---|
| a thread's messages | the **last 500 rows per project** (`messages.READ_LAST`) | it is an operator's inbox, not an archive. Older turns are still in the metrics store; they are simply not part of the conversation any more. |
| a **staged suggestion** | **12 hours** (`messages.SUGGESTION_TTL_HOURS`) | it is advice about a floor, and floors move. Long enough to survive a refresh, a second screen and stepping away; short enough that nobody presses a button whose reasoning was about yesterday. |

A suggestion also retires **before** its clock runs out, in two other ways — both folds over the
same append-only rows, decided server-side in `messages.staged`:

- **superseded** — the tech-lead has proposed something newer. Only the latest can be live: two
  buttons in one thread is a person choosing between two pieces of advice, one of which was
  written first and is therefore about a floor that has since changed.
- **answered** — somebody already pressed it. A second click on a stale page is refused rather
  than read as a second decision.

**A retired suggestion is shown with its reason, never removed.** A button that silently stops
working teaches the same wrong lesson as one that disappears — the person concludes the platform
forgot, when in fact it decided. `expired` says to ask again so the tech-lead can look at the
floor as it is now.

### Where it lives

- `openfactory/memory/messages.py` — `READ_LAST`, `SUGGESTION_TTL_HOURS`, and the `staged` fold.
- `openfactory/api/app.py` — `GET /api/messages/{project}` serves the thread and whether the
  suggestion may still be pressed; `POST /api/messages/{project}/suggestion` performs it through
  the action layer, with the credential that pressed the button, and records the decision.

---

## 4. The engine's memory, and the record that outlives it

Two places remember a job, and only one of them forgets.

| what | how long | where |
|---|---|---|
| the **engine's** history (Temporal) | `OPENFACTORY_ENGINE_RETENTION_DAYS`, **30 days** by default | the namespace's `WorkflowExecutionRetentionTtl` |
| the **journal** — every event a run emitted, and how it ended | until the volume is deleted | `OPENFACTORY_LOG_DIR/<project>/<issue>-events.jsonl` |

**The image's own default is 24 hours, and that is what this section exists to correct.**
`temporalio/auto-setup` creates the namespace with a one-day retention. The pilot ran two tickets
on 2026-08-16, opened the panel ~26h later, and the floor said **"nothing shipped yet"** — a
claim, and a false one, about a day on which it shipped two. A history that evaporates overnight
cannot answer the question a floor exists to answer.

`DEFAULT_NAMESPACE_RETENTION` in `docker-compose.yml` sets it **when the namespace is created**;
auto-setup will not change one that already exists. So the worker **reconciles** it at boot
(`runtime/temporal/schedule.ensure_retention`) — a value the deployment declares and the platform
makes true, the same shape the schedules use. It only ever **raises**: an operator who set a longer
window, or a Temporal Cloud namespace under somebody's retention policy, must not have it cut by a
default they never asked for, and a boot-time reconciler must never delete history. A namespace
this credential may not administer logs `OPENFACTORY_RETENTION_NOT_RAISED` and the worker starts.

### The journal is the answer after the window closes

`GET /api/jobs` and the **Logs** page read the journals, not the engine — which is why they still
had both of the pilot's runs when the engine had neither. For that to be worth anything the record
has to include **how a job ended**, and until #131 it did not: the journal is written by the
in-box orchestrator, while the terminal state is decided by the workflow after that box is gone.
`#89`'s file stopped at `reviewing`, so a parked job read as still-reviewing for ever. Every exit
of `JobWorkflow.run` now records its outcome (`record_outcome`), appended — the run's own states
stay true, and what it became is added after them.

### Where it lives

- `docker-compose.yml` — `DEFAULT_NAMESPACE_RETENTION` on the `temporal` service.
- `openfactory/runtime/temporal/schedule.py` — `RETENTION_DAYS`, `ensure_retention`.
- `openfactory/runtime/temporal/workflow.py` — `JobWorkflow._journal_outcome`, at the one exit.
- `openfactory/runtime/temporal/activities.py` — `record_outcome`, the append itself.
