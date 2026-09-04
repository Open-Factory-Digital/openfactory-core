# ADR 0045 — A fingerprint nothing reads is a promise, not a mechanism

- **Status:** **Proposed** — half of this ADR records decisions that are already implemented and
  written down nowhere; the other half decides the part that is not built. Both halves are stated
  against the tree at `68c3958`, and every measurement below was taken there.
- **Date:** 2026-09-04
- **Relates to:** ADR-0017 (the Knowledge Layer), ADR-0023 (*the map is derived, not learned* —
  kept, and load-bearing in §7 below), ADR-0035 (on by default — kept), ADR-0042 (the backfill has
  four inputs), ADR-0044 (a project declares what it is — where the budget comes from).

## Context

The knowledge bundle already has two halves, and they do not have the same provenance strength.

**The concept half is strong, and shipped.** `knowledge/contracts.py` carries `Concept` (with an
open `type` and a closed `status`), `BusinessRule` whose `cites` are `path:line` **as verified**,
`ConceptSource{repo, path, commit, fingerprint, lines}`, typed `Gap{kind, detail, path}` and
`CoverageRow`. `.okf/` is written into the **context repository** by `knowledge/okf.py::write_okf`,
and both the product owner (`product/role.py::_bundle_section`) and the tech lead
(`techlead/conversation.py::_bundle_for`) read it. The bundle is refreshed on a **schedule** rather
than only at merge, because tying a description of `main` to one ticket's outcome was a defect
(`KnowledgeRefreshWorkflow`).

**The module-map half is weak, and that is deliberate** — see §7. `SourceLink{file, symbol,
commit}` has no fingerprint and no line range.

**Reaching a reader is not the same as answering them**, and #31 is the measurement of the
difference. Three readers now have the bundle; two of them need a paragraph of caveat to use it,
and none can cite a line of it. `product/role.py::_bundle_section`'s own docstring is *"the
knowledge bundle, and — the load-bearing half — what its authority is NOT"*; the bundle's gaps have
to be re-explained to the reader as *"information, not noise"* (`role.py:843`); and
`techlead/pack.py:97` copies the whole bundle into the pack with `copytree` rather than citing into
it — copied-in-whole is what you do with something you cannot address into. A module map does not
answer *what does this system promise, and where does that promise live*, and what each reader had
to build around it is the evidence. (Raised in review by @hermesfelipe, who replaced a weaker
argument of mine with this one.)

**And the strong half's key has no reader.** Measured at `68c3958`:

```
$ grep -rn "fingerprint=" openfactory/ --include=*.py     # WRITTEN
openfactory/onboarding/concepts.py:237
openfactory/onboarding/concepts.py:285
$ grep -rn "\.fingerprint" openfactory/ --include=*.py    # READ
$
```

Two writers, zero readers. `knowledge/okf.py::render_concept`'s own docstring already names the
consumer that does not exist:

> *"a role that opens this reads the prose, and **the checker that invalidates it reads the
> fingerprints**, and neither can drift from the other because there is only one artifact"*

So *"the bytes move, the fingerprint moves, the concept is stale with nobody in the loop"* — which
`ConceptSource`'s docstring states as the whole point of the field — is **design intent, not a
mechanism**. Nothing re-verifies a published bundle. A concept whose source was rewritten last
month still reads as current to the role that opens it.

That single gap is why this ADR exists now rather than after the next slice: everything else in the
OKF is already carrying its own weight, and the promise at the centre of it is unkept.

## Decisions

### 1. What is recorded here, not decided here

These are already implemented and are written down in no ADR, so the next person to touch the OKF
would re-litigate them from scratch:

| | |
|---|---|
| the unit is a **concept**, not a module | a `contract` that ties two repositories by a shared literal is a sentence a product owner can read; *"which modules exist"* is not |
| every business rule cites `file:line` **as verified** | `onboarding/context.py::_Anchorer` demotes an unanchorable claim into a question before it can reach a `BusinessRule` |
| the concept **type** is an open set; **status** is closed | every company will have its own vocabulary; a closed enum would be the core holding one opinion about how software is described |
| **gaps are typed data** | a map that omits what it could not read is indistinguishable from one that found nothing to worry about |
| the bundle lives in the **context repository**, `.okf/`, one folder per source | source repositories are never written to |

The home deserves its reason in writing, because it is the one that looks like a preference and is
not. Writing `.okf/` into a client's source repo would fire their deploy (ADR-0005 exists to watch
exactly that), put every open pull request behind, and need push rights on a protected branch — and
then there is the reason that has nothing to do with permissions: **nobody has the checkout open.**
The agent is *handed* the bundle precisely so a ticket's `git add -A` cannot sweep it into the
commit. `knowledge/` was rejected as a name because `onboarding/onboard.py` already has to step
around clients who have a directory of that name.

### 2. The checker is a separate pass, and it is not the author

The failures that matter are the ones a language model is worst at noticing: a fingerprint that
moved, a path that no longer exists, a placeholder left in a template, one file silently dropped
from a count. Re-deriving every mechanical claim therefore **fails a run**; it is not a paragraph
in an authoring prompt.

It reads what is already written: `ConceptSource.fingerprint` against the bytes on disk, every
`BusinessRule.cites` against the file and the line, `CoverageRow` against the inventory. `_Anchorer`
is the same act at authoring time and is the right thing to extend rather than to reimplement
beside.

### 3. No human sign-off. The ratchet replaces it

Sign-off protected three different things, and only one of them is human-shaped:

| what it protected | who protects it here |
|---|---|
| the source moved and the concept went stale | the fingerprint — **once §2 exists**, mechanical |
| nothing describes this file | the gate's stance (§4), not anyone's signature |
| the concept claims something the code does not | the doctrine this platform already holds |

For the third the answer is ADR-0017 §7 and ADR-0023: **the code is ground truth and the map only
says where to look.** Every rule citing `file:line` makes any claim one hop from verification,
which is what makes this affordable rather than optimistic. The ratchet is *generate → the checker
passes → publish*. If a second opinion is ever wanted, the reviewer role already exists and its
prompt already says *"you did NOT write this code"*.

### 4. `no-concept` blocks

A file nothing describes is the least safe one to change, not the freest. Reading a gate as *"no
concept, no objection"* inverts the meaning of the artefact.

This one is **stated and not yet buildable**: it needs an inventory with a per-file `kind` and a
visible `unclassified` remainder, so that "nothing describes this file" is a fact rather than an
absence of evidence. The stance is recorded now so the inventory is built toward it.

### 5. What a verdict AUTHORISES is policy, not mechanism

The format, the scanner, the checker and the gate *mechanism* are generic. Which change class a
verdict permits, and who may override it, is a row in a configuration — never an axis in the core.

### 6. The `openfactory-knowledge` orphan branch stays retired — ratified, not decided

This one is **already done and is recorded here for the same reason as §1**: it lives in a
docstring rather than in a decision record. `knowledge/pipeline.py`'s header carries the UPDATE
note that superseded it, no `KNOWLEDGE_BRANCH` survives anywhere in `openfactory/`, and
`docs/knowledge-layer.md` carries dated UPDATE notes at D-2 and D-6 saying the same thing.

What this ADR adds is **which document is authoritative**: the decision lives here, and
`knowledge-layer.md`'s two UPDATE notes now point at this ADR rather than at a planning document
that is not part of this repository. A source repo that wants its own copy for a CI hook becomes a
**publish target**, never the bundle's home.

### 7. The module map keeps its weaker link, on purpose

`SourceLink` gets no fingerprint. The module map is **derived in 0.24s for 215 files** (ADR-0023),
so per-claim invalidation buys nothing there: when it is stale you regenerate the whole thing. The
fingerprint earns its cost only for what is **expensive to author** — a concept, which an agent
wrote once under a budget the project declared. Spending the mechanism where it is not needed would
make the two halves look symmetric and hide the fact that only one of them is.

## Consequences

- **The checker becomes the next slice**, and it has a measurable definition of done: `.fingerprint`
  acquires a reader, and a bundle whose sources moved can be told from one whose sources did not.
- **A published bundle can be refused**, which the pipeline cannot express today.
- **Authoring is already budgeted** (ADR-0044), and this ADR's first version got that wrong:
  `onboarding/concepts.py::score` ranks by `churn × radius × uncertainty` and cuts at
  `MAX_CONCEPT_BUDGET`, where `radius` IS `depended_on_by` — it is not an input waiting for a
  consumer, it is the consumer. `ProductModule.baseline(areas=…)` is likewise read, from
  `runtime/temporal/activities.py`. `propose_context`'s docstring refuses a cost that scales with
  repository size, and that refusal stands. (Corrected after review by @hermesfelipe; the sentence
  that produced the error is fixed in the same change.)
- **`docs/knowledge-layer.md`'s D-2 and D-6 UPDATE notes now cite this ADR**, so one document is
  authoritative about the bundle's home rather than two that do not know about each other.
- **Four references to planning documents that are not in this repository survive** —
  `knowledge/pipeline.py:4`, `docs/knowledge-layer.md:560-561` and
  `tools/mutations/the_knowledge_bundle_lives_in_the_context_repo.py:3` still cite `OKF-PORT-PLAN.md`
  and `BACKFILL.md` by name. A public reader cannot follow any of them. This ADR is the public home
  those citations should point at; repointing them touches code and is deliberately left out of a
  docs-only change. **Repointed since:** all three now cite this ADR's §6, and no file in the
  repository names either planning document.

## What is NOT decided here

- **The inventory's shape** — per-file `kind`, comment/string liveness, the secret scan, the
  `unclassified` remainder. It is the prerequisite for §4 and is its own slice.
- **The gate's verdict names and their thresholds.**
- **Any prompt or template text.** What the authoring agent is told is not an architectural
  decision.
- **Nothing is copied.** A reference implementation was studied in a private tree as a
  specification only; this ADR reproduces none of it.
