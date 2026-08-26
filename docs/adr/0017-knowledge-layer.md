# ADR 0017 — The Knowledge Layer: a derived, verifiable map the agent may not trust blindly

- **Status:** **Accepted; Phase 1 + 2a shipped, OFF by default and UNPROVEN.** The design is **Revisada pela ADR-0023 (2026-07-29):** o mapa deixou de ser um cache publicado e passa a ser gerado na caixa, a partir do checkout que o agente lê — o detector de defasagem sai do caminho crítico e a publicação vira artefato de inspeção.
  accepted; the *value* is not yet established. `knowledge_map` is false for every project until
  an A/B on the cost dashboard shows cost/ticket dropping.
- **Date:** 2026-07-26
- **Relates to:** ADR-0001 (D-2/D-9/D-10 — the knowledge cascade the agent reads), ADR-0005
  (post-merge watch — the same trigger point), ADR-0007 (the floor frees at merge — which the
  pipeline must not violate), ADR-0014 (frontier-default: fewer moving parts by default).
- **Full design:** `docs/knowledge-layer.md` (the north star, the phases, and §22/§23 — the
  design decisions taken while implementing).

## Context

Every agent rediscovers the project on every ticket. It greps, opens the wrong files, narrows
down, and only then starts the work — paying tokens and latency to relearn a layout that did not
change since the last ticket. A POC (2026-07-23) gave a coding agent a hand-written repo index
and measured ~32% fewer searches and ~40% lower cost on a "locate the code" task, with both arms
reaching the same correct target.

That is a real signal, and also a dangerous one. The obvious next step — "give agents a knowledge
base so they stop reading the repo" — is the failure mode, not the goal. A map that agents trust
*instead of* the code drifts into confident wrongness, and a confidently wrong map is worse than
no map: it sends the agent to the wrong file with certainty, and the human reviewing the PR has
no signal that anything went wrong.

So the question this ADR answers is not "should we build a knowledge layer" but **under what
constraints is one safe in a factory that mutates its own repos every hour.**

## Decision

**Build the map as a derived, source-linked accelerator that is only ever served when it can be
proven to describe the exact tree the agent is about to edit — and prove its value before
adopting it.**

### 1. The code is ground truth; the map is a fast path to it

Every entry carries a `source:` link (file, optional symbol, and the commit it was generated
from). The injected header says so explicitly: use the map to *locate* code fast, then open and
verify the real files. The map is authoritative about **where** things are, never about **what**
the code does.

### 2. Deterministic-first — no LLM in the hot path

The module map is built from directory structure, Python `ast`, and regex over TS/JS
import/export statements. Zero LLM calls, so the same repo state always produces byte-identical
output and regenerating on every merge is nearly free. The fuzzy slice (business-rule prose) is
deliberately deferred to a later phase, where a human reviews it through canonical docs.

### 3. Freshness is proven per job, from the sources, against the agent's own checkout

- A `manifest.yaml` records a **sha256 per canonical source file**. Freshness is decided by
  comparing those checksums — never by comparing the map's commit stamp to HEAD, which is
  structurally always behind (see §5).
- The comparison runs against the **job's own workspace**, not a shared base clone. A map is a
  claim about the code the agent will read; verifying it against a tree nobody is looking at
  proves nothing.
- Every `source:`/key-file link must still resolve (the orphan check).
- Fresh **and** orphan-free, or **nothing is injected** and the agent searches the code as
  before. There is no "probably fine" state. This is what makes the layer safe to leave on in a
  repo that changes constantly: the worst case is the behaviour we already have.

### 4. The bundle is a versioned artifact of the CLIENT repo

It is knowledge *about* the client's code, derived from it and versioned with it — so it belongs
to the client repo, not the platform's S3/DynamoDB. Ownership, multi-tenant isolation,
portability (any tool or human with the repo has it), and the client keeping it if the platform
relationship ends all point the same way. It is regenerated **once per merge** and persisted,
rather than recomputed per job, so it exists as an inspectable, versioned artifact other agents
and humans can consume — which is the entire reason to have a shared memory rather than a
per-job trick.

### 5. It is persisted on a dedicated branch, not on `main`

`sdlc-knowledge` — platform-prefixed so it cannot collide with a client branch, holding only the
bundle, accumulating one commit per source-changing merge. Not `main`, for three reasons found
while implementing (the design doc had leaned toward `main`):

1. A commit on `main` would **fire the client's deploy** — ADR-0005 exists to watch exactly that
   — for a change that touches no product code.
2. It would **put every open PR behind**, and the merge loop would spend rebases catching them
   up. The pipeline would manufacture the base-churn starvation that `_REBASE_MAX` exists to
   survive.
3. It removes any dependency on the bot being able to push to a protected branch.

A job therefore consumes the map from a temp checkout **outside** its workspace. Planting it
inside would let `git add -A` sweep it into the ticket's commit, and every PR would carry a copy
of the map.

### 6. Regeneration must converge

The bundle is generated from commit X and then committed, which creates commit Y — so its
provenance stamps differ on **every** run by construction. Rebuilding on "the stamp moved" is a
self-feeding loop that commits to the client's repo forever. So the pipeline compares the
*derived* content (map + checksums, stamps blanked) and writes nothing when no source changed.
One commit per real change, then silence.

### 7. Nothing about it may endanger a ticket

The refresh runs post-merge, single-attempt, bounded, with its result swallowed; the new workflow
command is behind `workflow.patched()` so in-flight jobs replay deterministically. The ticket has
already merged and the floor must free (ADR-0007). Worst case the map is one merge stale and the
next job runs without it.

### 8. Built ≠ adopted

`knowledge_map` defaults to false. The gate is **cost/ticket on the dashboard** — the instrument
was built first (Phase 0) precisely so this decision could be made with numbers. If the A/B does
not show a drop, the honest outcome is to stop and rethink, not to keep building on top of it.

## Consequences

**Good**

- The map cannot silently mislead: unprovable freshness means no injection, and every fact links
  to a file the agent can open.
- Regenerating is cheap enough to run on every merge, so the map is normally exactly current.
- The artifact is the client's, portable and provider-neutral — the same YAML feeds any agent.
- Existing behaviour is untouched until someone flips a flag per project.

**Costs / risks accepted**

- **A new branch in the client's repo.** It is disposable (delete it and the next merge
  republishes) but it is visible in their branch list, and it is one more thing an operator can
  be surprised by.
- **A map that is often not injected.** Any merge the pipeline has not caught up with makes the
  published map stale for the next job, which then runs without it. Fail-safe, but it means the
  measured benefit will be smaller than the POC's best case.
- **Coverage is capped.** The injected map has a size budget; large repos shed detail (public
  surface, then key files, then dependencies) to keep every module listed. Depth degrades before
  coverage — but depth does degrade.
- **The pipeline writes into the shared repo cache without holding its lock,** so a concurrent
  pre-flight sync for another ticket of the same project can clean the materialized bundle
  mid-build. The outcome is a benign no-op (the publish finds nothing to push), and it is
  documented rather than defended against.
- **Two more things to reason about on every merge**: an activity that can fail, and a branch
  that can diverge. Both were made unable to affect the ticket, which is the mitigation, not the
  absence of the cost.

**Rejected alternatives**

- **Generate the map per job, ephemerally.** Always fresh and needs no store — but it never
  becomes an artifact (never versioned, never inspectable, never consumable by another agent or a
  human without running a coding job), and it isn't even cheaper: build-once-per-merge beats
  rebuild-per-ticket.
- **Store it in the platform's own S3/DynamoDB.** Wrong owner, breaks multi-tenant isolation,
  breaks portability, and the client loses it if the relationship ends.
- **Let the map substitute for reading code.** The stated long-term vision in some framings; we
  explicitly reject it (§1). The value is *less searching*, not *less verifying*.
- **A query tool the agent calls instead of prompt injection.** Possible later if the size budget
  becomes the binding constraint; injection is what the POC actually measured, so it ships first.
