# Knowledge Layer Architecture

**Status:** **Accepted as [ADR-0017](adr/0017-knowledge-layer.md)**, Phase 1 + 2a implemented, and
since [ADR-0035](adr/0035-knowledge-layer-on-by-default.md) this is how the factory works rather
than an experiment: **`knowledge_map` defaults to `true`**, so every project gets the module map
and a project that does not want it declares `knowledge_map: false`.
[ADR-0023](adr/0023-derive-dont-cache.md) then revised how the map reaches a job — it is
**derived in that job's own checkout**, and the published branch survives as an artefact nothing
depends on in order to work.
This document remains the full design and phase history, so §21 and §23 describe the world of
their own date; where a later ADR changed what they decided, the section says so and the ADR
wins. `openfactory/contracts/manifest.py` is the only place the default actually lives.
**Authors:** OpenFactory Team
**Date:** 2026-07-23 · **Revised:** 2026-07-26 (v3 — Phase 1 audit fixes, §23 Phase 2a: the
post-merge pipeline persisted on a dedicated branch in the client repo) · v2 2026-07-24
(ground-truth principle + phased roadmap + deterministic-first + consistency + concrete OKF)

---

# 1. Motivation

The current OpenFactory is primarily an **executor**:

```
Task → Planner → Executor → Review/Gates → Merge → Deploy
```

This works once the work is defined. But as the platform grows knowledge-oriented agents
(Product Owner, Business Analyst, Architect), execution alone is not enough — they need a
**shared understanding of the project**.

Today that knowledge is fragmented across source code, product & architecture docs, ADRs, API
specs, DB schemas, business rules, and people's heads. Without a canonical representation, **every
agent rediscovers the project on every task**, which inflates latency, token cost, reasoning
effort, inconsistency, and hallucination.

**Evidence we already have** (POC, 2026-07-23): giving a coding agent a repo index cut searches
~32% and cost ~40% on a "locate the code" task, with both arms converging on the same correct
target. Directional, small-n — but it points the right way.

---

# 2. Vision

OpenFactory evolves from an **AI Software Executor** into a complete **AI Software Factory**,
composed of three layers:

```
Knowledge Layer      (current state — what EXISTS)
      ↓
Work Definition Layer (desired future — what we WANT)
      ↓
Execution Layer       (build it — what we already have)
```

Each layer has a distinct responsibility, and this document is a **north star, not a big-bang
plan**. Section 20 sequences it into phases that each earn their place with measured evidence.

---

# 3. Knowledge Layer

Represents the **current, implemented reality** of the project. It answers: what exists, how the
system works, which domains / modules / APIs exist, which architectural decisions and business
rules currently apply. It **never** represents future intentions — only what is true today.

**Responsibilities:** generate, maintain, validate, expose, and version knowledge artifacts.
It is **not** responsible for creating work.

---

# 4. Work Definition Layer

Represents the **desired future state**: Product Vision, RFCs, Discoveries, Epics, Stories, Tasks,
Feature Requests. Answers: what do we want to build, why, what problem it solves, expected outcome.
The Product Agent primarily operates here.

---

# 5. Execution Layer

Transforms work into software: Tech Lead, Planner, Executor, Quality Gates, Deployment.
Execution **consumes** knowledge but never owns it.

---

# 6. Current State vs Future State (the fundamental distinction)

- **Knowledge = reality.** "Authentication supports: Email, Google OAuth."
- **Work = intention.** "Epic: Add Microsoft OAuth."

A feature becomes knowledge **only after it is implemented and merged** — never before.

## Why the Product Agent must not edit the Knowledge Layer
The Product Agent *proposes* changes; it does not *redefine reality*. It edits **canonical
documentation** (intent, requirements); it never edits the OKF directly. The OKF only changes
after `Planner → Executor → Merge → Knowledge Builder` — so knowledge always reflects
**implemented** reality, not a promise.

---

# 7. ⭐ Ground truth: the code, not the knowledge

**The repository is the source of truth. The Knowledge Layer is a navigation accelerator, not a
replacement for reading code.**

This is the load-bearing correction to the vision. A coding agent must ultimately act on **real
files** — it edits actual source, and it must **verify against the actual source** before it does.
In the POC, the agents *with* the index still opened and read the real files to confirm; the index
made them faster, it did not let them skip reality.

Therefore:
- The OKF is **derived and verifiable**: every fact links back to its source (file path + symbol +
  the commit it was generated from). An agent can — and on anything load-bearing, should — follow
  the link and confirm.
- The OKF is **authoritative about *where* things are, never about *what* the code does** in a way
  that overrides reading it. It is a map, not the territory.
- We explicitly **reject** "the repository becomes an implementation detail." The repo stays
  ground truth; the Knowledge Layer is the fast path to it. A knowledge layer that agents trust
  *instead of* the code would drift into confident wrongness — worse than no layer at all.

The value is **less searching to find the right code**, measured on the cost dashboard — not
"agents stop touching the repo."

---

# 8. Canonical Sources

The Knowledge Layer is **built from** canonical, version-controlled sources — never hand-authored:

- Source code · Architecture documents · Product documentation · Business rules
- OpenAPI specs · Database schemas · ADRs · Deployment configuration

---

# 9. Open Knowledge Format (OKF) — concretely

OpenFactory adopts an **OKF Bundle** as its canonical knowledge representation: a set of
**generated, version-controlled, source-linked** artifacts. It is *generated, never hand-edited.*

**Concrete shape (v1 proposal — pin this before building):** a `knowledge/` bundle per project:

```
knowledge/
  manifest.yaml     # bundle version, generated-at, source commit, and a CHECKSUM per canonical
                    #   source (the staleness detector — see §12)
  modules.yaml      # the module map: each module → path, purpose, key files, dependencies,
                    #   public surface. Deterministic (structure + import/AST graph).
  api.yaml          # endpoints → handler → service, from the OpenAPI spec / route decorators.
  schema.yaml       # tables, columns, relationships, from DB introspection / migrations.
  adr-index.yaml    # ADRs + the area each governs, from docs/adr/.
  domains.md        # business domains + rules — the FUZZY part (LLM-summarized from canonical
                    #   docs, human-reviewed via the doc the Product Agent edits).
```

**Every entry carries a `source:` link** (file + symbol + commit) so it is traceable and
verifiable (§7). Format is provider-neutral YAML/Markdown — not a Claude-, Codex-, or
Gemini-specific artifact (see §18). (Note: this is our own bundle format inspired by the OKF idea;
it is not the Google "Open Knowledge Format" for data sharing — different problem.)

---

# 10. Knowledge Builder

Transforms canonical sources into the OKF Bundle. Responsibilities: parse repositories, inspect
project structure / APIs / DB schemas / architecture & product docs, generate OKF documents,
maintain source links, and **validate consistency** (§12).

## ⭐ Deterministic-first
Generation must be **cheap and reliable**, because it runs often (§11). So:
- **Deterministic (no LLM):** module map (structure + AST/import graph), `api.yaml` (OpenAPI /
  route parse), `schema.yaml` (introspection / migrations), `adr-index.yaml` (file scan). These
  are the bulk, and they are exact and near-free.
- **LLM (only the fuzzy):** `domains.md` business-rule/prose summaries — and even these are
  seeded from human-reviewed canonical docs, not invented.

A repo that merges every ~hour cannot afford an LLM pass on every merge for the whole bundle;
deterministic-first keeps regeneration fast and trustworthy, and confines cost to the small fuzzy
slice.

---

# 11. Knowledge Pipeline (separate from execution)

Knowledge evolves **independently** from software execution. The trigger is **"a canonical source
changed"**, *not* deployment:

```
Canonical source changed (code / docs / ADR / schema / api / business rule)
      ↓
Knowledge Builder (deterministic-first; LLM only for the fuzzy slice)
      ↓
Consistency validation (§12)
      ↓
OKF Bundle updated  (deployment NOT required)
```

## Where it hooks in
For code, the natural trigger is **post-merge** (the moment reality changed) — the same lifecycle
point the deploy-watch already uses. For docs/ADRs, the same: a merge to a canonical doc
regenerates the bundle. Incremental where possible (only rebuild the touched module) to stay cheap.

---

# 12. ⭐ Consistency & staleness (the part with teeth)

A **wrong or stale OKF misleads agents — worse than no OKF.** So the bundle is only trustworthy if
we can *detect* drift:

- **Staleness:** `manifest.yaml` records the source commit + a checksum per canonical source. If
  the bundle's source-commit ≠ repo HEAD (or a checksum differs), the bundle is **stale → regenerate
  before use** (or flag it). No silent serving of old knowledge.
- **Orphan/consistency check:** every OKF `source:` link must still resolve — file exists, symbol
  exists. A link that no longer resolves is an **orphan** → flagged, and that entry is dropped or
  rebuilt. This catches "the code moved but the map didn't."
- **Fail-safe posture:** if validation can't confirm freshness, the agent is told the bundle may be
  stale and falls back to searching the code directly (§7) — degrade, never mislead.

This is what makes the knowledge layer safe for an *autonomous* factory that mutates the repo
constantly.

---

# 13. Product & Developer Workflows

**Product** (edits intent, never the OKF):
```
Slack → Product Agent → Draft → Human Approval → Canonical Documentation → Merge
      → Knowledge Pipeline → OKF Updated
```

**Developer** (reality changes on merge):
```
Task → Planner → Executor → Merge → Knowledge Pipeline → OKF Updated → Deploy
```

---

# 14. Relationship between the layers

```
                 Knowledge Layer  (current state)
                          ▲  built by
                 Knowledge Builder
                          ▲  from
   Canonical Sources: code · APIs · DB · ADRs · architecture · product docs
──────────────────────────────────────────────────────────────────────────
                 Work Definition Layer   (Product Agent · BA · Architect)
                 RFC → Epic → Story → Task
──────────────────────────────────────────────────────────────────────────
                 Execution Layer
                 Tech Lead → Planner → Executor → Gates → Merge → Deploy
```

Execution **consumes** knowledge · Product **evolves** it (via canonical docs) · the Knowledge
Builder **synchronizes** it with reality.

---

# 15. Benefits (and how we PROVE each)

Every benefit is a **measurable claim on the cost dashboard** (`/api/metrics`), not a promise:

| Benefit | How we prove it |
|---|---|
| Reduced context discovery | fewer searches/turns per ticket |
| Lower token consumption | tokens & **cost/ticket** down (dashboard, before/after) |
| Better planning | planner starts from structured knowledge |
| Better product decisions | Product Agent sees the real system before proposing |
| Vendor independence | the same bundle feeds Claude / Codex / Gemini / Cursor |
| Versioned knowledge | each project version has a matching bundle version |

No phase advances unless its benefit shows up in the numbers.

---

# 16. Vendor independence

The Knowledge Layer is independent of any AI provider. The OKF Bundle (provider-neutral
YAML/Markdown) is consumed identically by Claude Code, Codex, Gemini, Cursor, Kimi — matching the
factory's existing agnostic-adapter philosophy (ADR-0014 direction).

---

# 17. Core principle

> Knowledge is not documentation. Knowledge is **infrastructure** — the shared, versioned memory
> of OpenFactory. Execution consumes it; Product evolves it; the Knowledge Builder keeps it
> in sync with reality. **The OKF represents the current truth of the project — and the code
> remains the ground truth it is derived from and verified against.**

---

# 18. Future vision (with the ground-truth caveat)

Long-term, agents lean on the Knowledge Layer to **navigate** instead of rediscovering the repo
each time:

```
Repository → Knowledge Builder → OKF Bundle → AI Agents (navigate fast) → verify against Repository
```

Knowledge becomes the **fast interface** to the project — but (per §7) the repository stays the
ground truth agents ultimately act on and verify against. Knowledge is the map; code is the
territory.

---

# 19. Open questions to settle before Phase 2+

1. **OKF format spec** — lock the concrete schema of each `knowledge/*.yaml` (§9) before it grows.
2. ~~Where the bundle lives~~ — **DECIDED + SHIPPED (§22, §23 D-6): the PUBLISHED copy is
   persisted per-commit in the CLIENT repo, on a dedicated `openfactory-knowledge` branch** —
   never the platform's storage, and deliberately NOT `main` (it would fire the client's deploy
   and starve in-flight PRs — see §23 D-6). ADR-0023 then separated the two questions: the copy a
   JOB reads is per-job and ephemeral, derived from that job's checkout, and the published branch
   is the readable snapshot.
3. **Incremental vs full rebuild** — module-scoped rebuild to keep the post-merge trigger cheap.
4. ~~How the agent consumes it~~ — **DECIDED + SHIPPED: injection** (as in the POC), from a temp
   checkout handed to the injector rather than a file planted in the agent's tree (§23 D-7). A
   query-tool interface remains a later option if injection's size budget becomes the limit.

---

# 20. ⭐ Phased roadmap (each phase earns the next)

**Principle: prove value with numbers before building the next layer. No big bang.**

- **Phase 0 — instrument (DONE).** The cost dashboard (`/api/metrics`, per-project) — the ruler
  we measure every phase with. The POC established a directional signal. ✅

- **Phase 1 — minimal Knowledge Layer. ✅ IMPLEMENTED (see §21).** Generate `modules.yaml`
  (deterministic module map) per project, injected into the executor/planner's investigate step.
  **Gate:** cost/ticket on the dashboard drops vs the pre-index baseline. If it doesn't, stop and
  rethink — cheap to try, honest to measure. **Passed** (ADR-0035, 2026-08-02), which is why the
  flag's default is now `true` and this is behaviour rather than an experiment.

- **Phase 2a — the Knowledge Pipeline. ✅ IMPLEMENTED (see §23).** Post-merge regeneration,
  persisted per-commit in the client repo.

- **Phase 2b — expand the deterministic bundle.** Add `api.yaml`, `schema.yaml`, `adr-index.yaml`
  (all deterministic, cheap). Extend the staleness manifest + orphan check (§12) to cover them.
  **Gate:** further cost/quality improvement. (The manifest + orphan check already ship in
  Phase 1 for `modules.yaml`; Phase 2 broadens them.)

- **Phase 3 — the fuzzy slice.** `domains.md` business-rule summaries (LLM, human-reviewed via
  canonical docs). **Gate:** better planning/product decisions, no drift introduced.

- **Phase 4 — Work Definition Layer + knowledge agents.** Product / BA / Architect agents, the
  RFC→Epic→Story flow (§4), Product Agent editing canonical docs → Knowledge Pipeline. Only once
  the Knowledge Layer is proven and stable underneath.

Each phase is small, measured, and reversible. The cathedral gets built one proven stone at a time.

---

# 21. Phase 1 — implemented

Phase 1 ships the deterministic, LLM-free module map and its consistency guards. It lives in the
`openfactory/knowledge/` package (typed pydantic contracts, best-effort helpers that never crash the
caller). It shipped behind a flag while the cost/ticket A/B ran; ADR-0035 ended that window and
made the flag's default `true`, so what this section calls "opting in" is now what a project gets
without asking.

**What exists**

- **Generator (`openfactory/knowledge/generator.py`).** Parses a repo DETERMINISTICALLY — directory
  structure + Python `ast` (imports/defs/`__all__`) + regex over TS/JS import/export statements —
  with **zero LLM calls**. Groups source by directory into modules, each with `path`, `purpose`
  (inferred from a dir README → package docstring → dir name; never invented), `key_files`,
  `dependencies` (from the in-repo import graph), and `public_surface` (exported symbols). Every
  entry carries a `source:` link (file + optional symbol + the commit it was generated from — §7).
  Same input → byte-identical output.
- **Bundle (`openfactory/knowledge/bundle.py`).** Writes two YAML files under a project's `knowledge/`
  dir: `modules.yaml` (the map) and `manifest.yaml` (bundle version, generated-at, source commit,
  and a **sha256 per canonical source** — the §12 staleness detector). Deterministic serialization
  (sorted keys, pre-sorted lists).
- **Staleness & orphan guards (`openfactory/knowledge/staleness.py`).** `is_stale()` (checksum-driven and
  git-free — sources only, never the commit stamp; see §22 D-4), `orphan_links()` (every
  `source:`/key-file link still resolves — file exists, symbol still a top-level def/class), and
  `is_trustworthy()` — the fail-safe gate: serve the map only when fresh **and** orphan-free, else
  degrade to searching the code (§7/§12). Never raises.
- **Injection.** The manifest flag `knowledge_map` makes `build_context` load the bundle **from
  the job's own checkout** (§22 D-3) via `load_agent_knowledge()` and inject the rendered map into
  the agent's context (alongside the existing constraints/guidelines/doc-index assembled in
  `openfactory/adapters/agent/base.py`). Its default is `true` (ADR-0035); it was `false` while
  Phase 1 was being measured. The injected header states the ground-truth rule explicitly: *use
  the map to locate code faster, then open and verify the real files.* A
  missing/stale/orphaned/corrupt bundle injects nothing.

**How to build + consume**

```
openfactory knowledge build <project>   # generate knowledge/modules.yaml + manifest.yaml (deterministic)
openfactory knowledge check <project>   # report staleness + orphan links (non-zero exit if not fresh)
```

Both are for inspecting a bundle by hand. Nothing has to be set for a job to get the map: since
ADR-0035 the manifest's `knowledge_map` defaults to `true`, and a project that wants the old
behaviour declares `knowledge_map: false` in its `.openfactory/project.yaml`. Since ADR-0023 a job
does not read a bundle from its checkout at all — it derives one, in a temporary directory beside
the checkout, at the moment it runs (§23).

**Deliberately left for Phase 2+**

- ~~Post-merge auto-regeneration → persisted in the CLIENT repo~~ — **SHIPPED, see §23.**
- **The rest of the bundle.** `api.yaml`, `schema.yaml`, `adr-index.yaml` (Phase 2b,
  deterministic) and `domains.md` (Phase 3, the LLM fuzzy slice).

---

# 22. ⭐ Design decisions (2026-07-24 review) — how the bundle is persisted & owned

A design conversation stress-tested "how does the bundle stay fresh across many tasks, in an
ephemeral-clone + branch-per-job factory?" and settled two things that supersede the earlier
open questions. **Freshness judgment moved to the clean checkout is already SHIPPED** (see below);
the persistence model is the Phase-2 plan.

### D-1. The bundle is PERSISTED per-commit, not generated ephemerally per-job

We considered generating the map fresh inside each job's sandbox (per-job, ephemeral) — it's
always fresh and needs no store. **Rejected**, for two reasons:
- **It never becomes an artifact.** The OKF would be a throwaway computation inside one job's box —
  never versioned, never inspectable ("what was the map at commit X?"), never consumable by OTHER
  agents (Product/BA/architect) or humans or another tool without running a coding job. That
  sacrifices the whole point of §17 (a *shared, versioned* memory).
- **It isn't even cheaper.** Per-job rebuilds on every task; build-once-per-merge builds once and
  every job on that commit reuses it. Fewer builds, and you get the artifact.

So: **regenerate post-merge (once, when reality changed) and PERSIST it, versioned by commit.**
The deterministic map is cheap to build, but we still persist it — precisely so it is *born* as a
versioned artifact, not a per-job trick.

### D-2. The bundle is an artifact of the CLIENT repo, NOT the platform's storage

The OKF is knowledge *about* the client project, derived from its code and
versioned with its code. It belongs to the **client's repository**, not to any store of ours.
Putting it in the platform's storage would be wrong on four counts: **ownership** (it's the
client's knowledge, not the tool's), **multi-tenant isolation** (don't mix each tenant's knowledge
into shared platform infra — same principle as per-project Slack/registry), **portability /
vendor-independence** (any tool/agent/human with the repo has it — a store only serves whoever has
that store's access), and **the client keeps it** if the platform relationship ends.

**Where in the client repo** (decide at implementation): `knowledge/` committed to `main` if the
bot can push there (cleanest — the agent's clone already has it, zero fetch); else a **dedicated
unprotected `knowledge` branch** to sidestep `main`'s branch protection (the bot merges via PR and
usually can't push straight to protected `main`). Both are git-versioned and client-owned.

### D-3. Freshness is judged on the JOB'S OWN CHECKOUT, once, while it is clean (SHIPPED)

Two separate mistakes, both fixed 2026-07-24:

**Which tree.** The bundle was read from `repo_path` — the shared, long-lived base-branch clone —
while the agent works in the sandbox *workspace*. A map is a claim about the code the agent is
about to read, so it must be loaded and verified against **that** tree, or we vouch for a tree
nobody is looking at. Fixed: `Workspace` now carries `host_path` (the checkout as the
orchestrator sees it — the worktree itself, or the container's bind-mounted host clone), and
`build_context` takes `knowledge_path`. No workspace → degrade to `repo_path`.

**When.** Staleness compared the bundle to a working tree that, during repair/recovery, already
holds the agent's OWN uncommitted edits — spuriously flagging it stale exactly when it is still
valid. Fixed: freshness is decided ONCE on the clean initial checkout and reused for every
repair/recovery context (`build_context` takes an optional `knowledge_map`; the JobRunner
memoizes the clean-pass value).

### D-4. Freshness comes from the SOURCES, never from `source_commit` vs HEAD (SHIPPED)

A bundle generated from commit X and then *committed* creates commit Y — so its `source_commit`
is one commit behind HEAD **by construction, permanently**. Any HEAD comparison would therefore
report every correctly persisted bundle as stale and the map would never be served once. So
`source_commit` is provenance ("which commit was this derived from"), and the per-file checksums
are the freshness test — exact, git-free, and true under persistence. The `head_commit` parameter
was removed rather than left as a foot-gun.

### D-5. Regeneration is a NO-OP when only the stamps moved (SHIPPED)

The same asymmetry is a live hazard for the post-merge trigger: build@X → commit Y → the trigger
fires on Y → build@Y (identical map, new stamps) → commit Z → … a self-feeding loop of real
commits on the client's `main`. Fixed at the root: `write_bundle` compares a `derived_key` — the
module map and checksums with every provenance stamp blanked — against what is already on disk,
and writes **nothing** when the sources are unchanged (returning `None` so the caller knows there
is nothing to commit). The pipeline now converges to exactly one commit per real source change.

### Net effect on the model

The Knowledge Pipeline (§11) regenerates on merge and writes the bundle **into the client repo**
(main or a `knowledge` branch). A job clones the client repo and already has (or fetches) the
bundle for its base commit; freshness is judged on that clean checkout. The bundle is a
first-class, versioned, portable artifact of the client — the map the whole multi-agent vision
(§4, §16, §18) can consume — not a platform-owned store nor a per-job throwaway.

---

# 23. ⭐ Phase 2a — the Knowledge Pipeline (IMPLEMENTED)

§22 settled *that* the bundle is persisted per-commit in the client repo. This is how, and what
implementing it changed about the plan. (Phase **2b** — `api.yaml` / `schema.yaml` /
`adr-index.yaml` — is still open; this section is only about the pipeline.)

> **[ADR-0023](adr/0023-derive-dont-cache.md) revised the last line of this loop.** Generating the
> bundle takes ~0.3 s for a repository this size, so the branch, the checksum manifest and the
> staleness detector were a cache bought with a class of defects to save a third of a second — and
> ticket #478, the one the A/B existed to measure, ran with no map because a person had merged to
> `main` in between. A job now **derives its own map from its own checkout**
> (`openfactory/orchestrator/machine.py` → `_knowledge_bundle`, into a temporary directory
> outside the workspace), so it is fresh by construction and there is no trigger to get right.
> Everything
> below still happens — it is how the published artefact is produced — but nothing a job does
> depends on it, and D-7's "hand it to the agent, never plant it in the checkout" is the part
> that survived intact.

## The loop

```
merge lands on main
   → JobWorkflow (post-merge, behind workflow.patched("knowledge-pipeline"))
   → refresh_knowledge activity
        sync the worker's repo cache to the base branch      (the new reality)
        pull down the currently PUBLISHED bundle             (so "changed?" is meaningful)
        rebuild deterministically + write only if changed    (§22 D-5)
        publish → one commit on the openfactory-knowledge branch
   → the artefact a person can read and audit the A/B against
      (the NEXT JOB does not read it — ADR-0023: it derives its own)
```

## D-6. The bundle lives on a dedicated branch, NOT on `main` (supersedes §22 D-2's leaning)

§22 left "where in the client repo" to implementation and leaned toward `main` ("cleanest — the
agent's clone already has it"). Implementing it showed `main` is the wrong target, and for reasons
that have nothing to do with the branch-protection question that framing focused on:

1. **It would fire the client's deploy.** A project's own CI deploys on push to `main` — ADR-0005
   exists to watch exactly that. Committing a derived YAML map there triggers a real deployment
   for a change that touches no product code.
2. **It would starve in-flight PRs.** Every commit to `main` puts open PRs BEHIND, and the merge
   loop then burns rebases catching them up (`_REBASE_MAX` exists because a busy base already
   starves jobs). The pipeline would manufacture that starvation on every single merge.
3. **Protection stops being load-bearing.** A dedicated branch works whether or not the bot can
   push to a protected `main`, so the capability question no longer gates the design.

The branch is **`openfactory-knowledge`** — platform-prefixed so it cannot collide with a client branch
called `knowledge`. It holds ONLY the `knowledge/` directory (created from an empty init, never
branched off `main`, so it can never conflict with client code) and accumulates one commit per
source-changing merge — which is what keeps "what was the map at commit X?" answerable, the whole
point of persisting rather than generating per-job.

## D-7. The bundle is handed to the agent, never planted in its checkout

A job consumes the published bundle from a temp checkout OUTSIDE its workspace
(`load_agent_knowledge(..., bundle_dir=…)`), and freshness is still verified against the
workspace tree. The alternative — writing `knowledge/` into the workspace — is a trap: `git add
-A` would sweep it into the ticket's commit and every PR would carry a copy of the map. For the
same reason the pipeline deletes the bundle it materialized into the shared repo cache, since
that cache is what every job's worktree is cut from.

A project that prefers to keep `knowledge/` committed in its own repo still works unchanged: with
nothing published, the injector falls back to reading the bundle from the checkout (Phase 1's
shape).

## What makes it safe to run on every merge

- **It converges.** Guaranteed by §22 D-5 (`derived_key`), and pinned by tests that run the
  refresh repeatedly against a real git remote and assert the branch stays at one commit.
- **It cannot fail a job.** The activity is single-attempt, bounded (10 min), and its result is
  swallowed. The ticket has already merged; the floor must free (ADR-0007). Worst case the map
  stays one merge behind and the next job runs without it — the §12 fail-safe.
- **It cannot break replay.** The new workflow command is gated behind
  `workflow.patched("knowledge-pipeline")`, so a job in flight during the deploy replays
  deterministically.
- **It leaves nothing behind.** Every throwaway checkout is deleted in a `finally`, and each has
  its tokened remote scrubbed first.

## The A/B is now measurable (2026-07-26)

The gate was unmeasurable until this shipped: nothing recorded which arm a ticket ran in, so the
dashboard could not tell the groups apart. Now every job records **what the agent actually saw**:

| arm | meaning |
|---|---|
| `off` | the map was withheld ON PURPOSE — the project declared `knowledge_map: false`, or an open A/B window assigned this ticket to the control |
| `injected` | the module map was in the agent's context |
| `unavailable` | the map was meant to be there and could not be trusted for that checkout — the ticket ran **without** it, so it is a control by accident rather than by choice |

That third value is why this is not a boolean. Bucketing by the *flag* would put stale-map runs in
the treatment group and dilute the very effect we are trying to see; and a high `unavailable` rate
is its own signal — it means the pipeline isn't keeping up and the experiment is measuring noise.

It flows `RunResult.knowledge` → `JobMetricsInput` → the metrics sink → `/api/metrics`, and the
panel shows a per-arm table (**n, mean and median** for cost, wall-clock and turns) plus the arm on
each task row. Median alongside mean deliberately: ticket sizes vary enormously, and one big ticket
in a small arm moves a mean without proving anything. Pre-instrumentation tickets are **excluded**
rather than counted as `off` — padding the control group with unknowns would bias it.

The readout computes **no verdict**. Comparing arms is only valid if the ticket mix is comparable,
and nothing in the code can know that — the numbers plus n are for a human to judge.

### What it measured (scan of 2026-09-01)

A human's reading of that readout, on **one production codebase**, `n = 8` tickets per arm,
**medians**:

| measure | control (`off`) | treatment (`injected`) | delta |
|---|---|---|---|
| **tokens** | 75,175 | 58,655 | **−22.0%** |
| cost (USD) | 11.70 | 7.47 | −36.2% |
| turns | 138 | 95.5 | −30.8% |
| wall-clock (s) | 3,272 | 3,309 | **+1.1%** |

**Tokens are the headline, not cost.** `openfactory/api/metrics_view.py::_knowledge_ab` is
where these arms are computed, and it says why in its own comment: cost is a
function of which model ran, so it moves when somebody switches model and says nothing about the
map. Tokens are the thing the map is supposed to change. −36.2% is the larger and more flattering
figure and it is the one to distrust.

**The map makes runs cheaper, not faster, and that is a result rather than an omission.**
Wall-clock is **+1.1%** — unchanged, within noise. Three improvements published with the flat
measure quietly dropped would be selective reporting, and this project's position is that what does
not work is written down. It also answers the obvious question before it is asked.

**`n = 8` per arm is a directional signal, not a proof.** Eight is one codebase, one ticket mix and
one team's habits, and the paragraph above on comparability is the caveat that applies to this
table: nothing here knows whether the two arms drew similar work.

**The scan date is part of the number.** These are medians as at **2026-09-01**; the experiment
accrues, so a later scan is a different number and this line has to move with it — the same rule
[`docs/STATUS.md`](STATUS.md) states for its own counts.

**No identity, and the raw rows stay private.** The per-ticket records are a client's data: they
carry the repository, the tickets and the spend of a real deployment, so they live in that
deployment's own metrics table and are not published here or anywhere. Medians of tokens and turns
are the platform's own consumption and carry nothing about whose codebase it was — which is why
these four rows can be public when the rows behind them cannot.

**This is not the POC figure near the top of this page.** The *"~32% and cost ~40% on a 'locate the
code' task"* (2026-07-23) is a different measurement of a different thing: one task, not a
per-ticket A/B across eight. Reading either as the other is exactly how a general claim gets built
out of a single-task result, so they are stated separately and dated separately on purpose.

## Still open

- ~~**Run the A/B.**~~ **Settled by [ADR-0035](adr/0035-knowledge-layer-on-by-default.md)**
  (2026-08-02): the cost per ticket fell on this repository's ticket mix, and the flag's default
  became `true`. `experiment.py` stays and is a no-op while no window is open — it is the
  instrument for measuring Phase 2b, and the number that justified this was measured on one
  repository, so the first enterprise deployment should retake it rather than inherit it.
- **Phase 2b:** `api.yaml`, `schema.yaml`, `adr-index.yaml` + extending the manifest/orphan checks
  to cover them. Note the extractors are **stack-specific** (an OpenAPI
  parse, route-decorator AST, or migration introspection — which one depends on the project), so
  writing them before there is a measured reason means guessing at the shape too.
- ~~**The agent-adapter seam.**~~ **Closed.** Which harness serves a role is a registry entry
  (`openfactory/adapters/agent/registry.py` → `HARNESSES`), and no call site names an adapter
  class; adding one is that entry plus its module. See [ADR-0018](adr/0018-harness-roles.md) and
  `docs/agents.md`, which lists what ships.
