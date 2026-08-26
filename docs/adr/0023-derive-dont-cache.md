# ADR 0023 — The map is derived, not learned: generate it where the checkout is

- **Status:** **Accepted** (control-arm decision: (b), below)
- **Date:** 2026-07-29
- **Related:** ADR-0017 (the Knowledge Layer, which this ADR revises), ADR-0021 (the agents'
  memory — the contrast this one is named against), ADR-0005 (post-merge, today the only trigger).

## Context

The product owner, 2026-07-29: *"does this 'learning phase' make sense only at merge? Should there
be a learning pipeline? This is too important for us to have a hole in it — analyse it as an
architect."*

The question came from a real hole. Ticket #478 — precisely the one the A/B existed to measure —
ran with **"map unavailable"**. The investigation:

| commit on main | map regenerated? | who merged |
|---|---|---|
| 26/07 21:53 `50fd9344` | ✅ 21:55 | the factory |
| **26/07 22:40 `dbf0e11f`** | ❌ **no** | a person (PR #508) |
| 27/07 21:14 `f92d7c2f` | ✅ 21:16 | the factory |

#478 started 27/07 00:36 — inside the window where the map described `50fd9344` and the checkout was
`dbf0e11f`. The checksums did not match, and injection degraded to nothing. **The degradation was
correct; the trigger was incomplete.** The map is regenerated after a merge *by the factory*, and
main moves for many other reasons — a person merging a PR, a hotfix, a dependency bump, another
developer. It was 22 hours stale.

### Why an hourly schedule would be a patch

The reflex fix — and the one I started writing — is an hourly schedule. It **shrinks the window from
22h to 1h and does not close it**: a job that starts five minutes after any push still picks up a
stale map. A webhook shrinks it further and adds an inbound endpoint, a secret, a retry path and one
more way to fail silently.

Each fix makes the cache *more correct* without making it *correct*. That is the shape of a patch.

### The question nobody had asked

All of that machinery — a publishing branch, a checksum manifest, a staleness detector, an
`unavailable` arm, a trigger — exists to make a **cache** correct. And a cache is only justified if
computing is expensive.

**Measured 2026-07-29:** generating the full bundle (module map + sha256 of every file) takes
**0.24 s** for 215 files — ~1.1 ms per file. For the client's repository (~225 sources): **~0.3 s**.

The manifest that exists purely to detect whether the cache is still valid is **186 KB**. We spent a
branch, a detector and a whole class of defects to save a third of a second.

### The distinction that answers the "learning" question

Two things in this system are frequently confused, and the difference is exactly what decides each
one's trigger:

| | the module map | the agents' memory (ADR-0021) |
|---|---|---|
| nature | **derived** — a pure function of the checkout | **learned** — an observation of the world |
| same input | always the same output | may change (the remedy worked this time) |
| how it becomes correct | by recomputing | by accumulating and observing outcomes |
| the right trigger | **at the point of use** | **at the event** that produces the observation |
| does a cache make sense? | only if computing is expensive | it is not a cache, it is a history |

**The map learns nothing.** Calling it a "learning phase" is what makes the question "should there be
a learning pipeline?" feel natural — and the honest answer is: a *pipeline* is the right structure
for learning (ADR-0021 has one) and the wrong structure for derivation. Derivation does not need a
pipeline; it needs to be near the data.

## Decision

**Generate the map inside the box, from the very checkout the agent is going to read. Publishing
stays — as a readable artefact that nothing depends on in order to work.**

### 1. Fresh by construction, not by verification

The box already clones the repository at the exact commit it will work on. A map generated there
describes **the tree the agent is about to open** — no drift is possible. Gone with it:

- the staleness detector *as a critical path* (the checksums stay in the published artefact, for
  whoever inspects it);
- the `unavailable` arm caused by staleness — `unavailable` goes back to meaning only what it
  should: the feature is off, or generation failed;
- the trigger question, entirely. There is no cache to invalidate.

### 2. Generated OUTSIDE the working tree

In a temporary directory, never inside the workspace. The reason is in today's code and still holds:
a bundle planted in the workspace would be swept into the ticket's commit by `git add -A`, and every
PR would carry a copy of the map. The injection function already takes a separate `bundle_dir` — it
is the same path, with a different origin.

### 3. Publishing survives, without being load-bearing

It still happens post-merge, on the dedicated branch. What changes is its **status**: today the job
*depends* on it; it becomes an artefact for a human to read and for auditing the A/B. If it fails,
nobody goes without a map — only without the published copy.

That preserves what publishing actually delivers (inspection, history) and returns correctness to
where it is cheap.

### 4. Explicit limits, because 0.3 s is not zero in every repository

- **A time bound**, with a log when it is reached: a 10,000-file monorepo would take ~11 s.
  Acceptable next to a 20-minute job — but the number has to appear, not be discovered.
- **A generation failure degrades to no map**, as today, and says why. It never fails the job: it is
  a navigation aid (ADR-0017 §7 — the code is the truth).
- **Determinism preserved**: same input, same output.

### 4b. The control arm GENERATES and discards (decided 2026-07-29)

There were two options, and it is a product decision, not a technical one:

- **(a)** the control does not generate — cheaper, but the arms would then differ in **two**
  variables: the injection *and* 0.3 s of CPU;
- **(b)** the control generates and discards — arms identical in everything but the injection.

**(b) was chosen.** The A/B exists to support a commercial claim: *"with the map, you spend fewer
tokens"*. An experiment whose arms differ in two variables supports no claim at all — any measured
difference would have two possible explanations, and the convenient one would be chosen. 0.3 s
wasted per control job is a cheap price for a number that is defensible in a sale.

### 5. What this does to the A/B

This is the point that motivated all of it. Today the treated arm **is not treated** whenever main
moved from outside — and that does not show up as an error, it shows up as `unavailable` on a
dashboard. The A/B measures two control arms and calls one of them the treatment.

With generation at the point of use, treated is treated in 100% of cases, and `unavailable` goes
back to signalling a real defect. **Only then do the numbers mean anything** — which is the
condition for selling token savings with proof.

## Consequences

**Good.** The hole closes by construction, not by frequency. A whole class of defects (staleness,
trigger, window) disappears instead of being managed. And the token-efficiency promise becomes
genuinely measurable, because the treated arm stops being treated only when it gets lucky.

**Costs and risks, declared.**
- **0.3 s of CPU per job in the box** — irrelevant today, but it is a new cost on a hot path, and in
  a much larger repository it grows linearly. Hence the bound and the log.
- **Sharing between jobs is lost.** Two jobs on the same commit generate the same map twice. That is
  exactly the waste a cache would avoid — and it costs 0.3 s, against the class of defects the cache
  brought.
- **The published branch can still go stale.** That stops being a bug and becomes a declared
  property of the artefact: it is a post-merge snapshot, not what the agent used.
- **The migration has to be observable.** Switching over without measuring would repeat the A/B's
  mistake: the transition phase records which path served the map, so that "it improved" is
  verifiable rather than assumed.

## Migration

1. **Generate in the box and inject from there**, leaving publishing as it is.
2. **Record the map's origin** in telemetry (`in-box` vs `branch`) for a window — without that the
   change is a belief.
3. **Retire the branch-reading path** when telemetry shows `in-box` at 100% and `unavailable` only
   for a real reason.
4. **Do not remove** checksums or the manifest from the published artefact: they stop being a
   critical path and remain what makes a snapshot auditable.
