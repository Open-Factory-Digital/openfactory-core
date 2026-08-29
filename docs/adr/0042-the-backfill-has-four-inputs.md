# ADR 0042 — The backfill has four inputs, and a legacy system is the product

- **Status:** **Accepted** for the thesis and for input 2 (the code's history), which ships with
  this ADR. Inputs 3 and 4 are **Proposed** — named here so the shape is decided before the code,
  not discovered by it.
- **Date:** 2026-08-29
- **Relates to:** ADR-0017 / ADR-0023 / ADR-0035 (the knowledge layer, derived not cached, on by
  default — this revises what the layer is FOR, not how it is built), ADR-0019 (requirement↔code
  drift cannot be checksummed), ADR-0021 / ADR-0031 (nothing grades its own homework),
  ADR-0041 (facts reach a role as files).

## Context

`onboarding/context.py` calls itself the backfill, in its first line: *"the context an AI needs,
reverse-engineered from a legacy codebase."* It runs inside `openfactory onboard`, surveys the
source repository deterministically, spends one citation-checked agent pass, and writes five
documents into the context repository.

The mechanism is sound. `_Anchorer` is the sharpest thing in this codebase on the subject — a claim
whose citation does not resolve is demoted into a question carrying the failed citation, so *"a
model that invents a source loses the sentence, every time"*.

What is wrong is **what the backfill is allowed to look at**.

It reads the tree as it stands. That is the input that says what the code IS, and on fifteen years
of legacy it is the weakest of the four available for the decision the backfill actually has to
make: where to spend itself, and which of its own claims to trust.

This platform already knows that, in its own words. `product/brownfield.py` ranks three tiers of
evidence and puts first the one the backfill cannot reach:

> `asked` — *a person asked for it — an issue, a PR, a comment with an author and a date. Real
> provenance, and the strongest thing a brownfield pass can find. It is also the tier most often
> missed, **because it means reading the tracker's history rather than the code**.*

### Why legacy is the product and green-field is the degenerate case

The framing until now treated reverse engineering as the given and green-field as the open
question. That is inverted:

- In **green-field** the knowledge is a **by-product**. The factory wrote the code, so it can emit
  concepts as it writes: provenance is free, there are no gaps, and nothing needs discovering.
- In **legacy** the knowledge is a **prerequisite**. It must exist before the first ticket, and
  every hard problem lives there.

Build the legacy loop and green-field falls out as the same loop with an empty repository and an
incremental feed. Build green-field first and legacy is still entirely ahead.

### A measurement, so this is not an argument from taste

On a real produced bundle for a real client repository, the deterministic scan was correct about
every fact and could not reach the conclusion:

- the directory whose name every convention says holds the entry points was **100% commented out**;
  the live entry points were in a differently-named sibling.
- **six of nine test files were entirely commented out.**
- the most-changed business file in the repository — three times more churn than any other — had no
  live test, and the file that used to test it existed and was switched off.

Each fact was recorded separately and correctly. Nothing in the bundle stated the sentence *"the
most-changed, most-complex logic here has no live test"* — which is the single most important thing
to know about that repository for a factory about to change it, because it means a green suite
proves nothing exactly where the factory would work hardest.

Reaching that sentence needs the tree crossed with the history. Neither alone produces it.

## Decision

**The backfill has four inputs. Each one is named, and an input nobody read is reported as
unread — never as an absence of findings.**

| | input | state |
|---|---|---|
| 1 | the code as it stands | shipped — `context.py::survey` |
| 2 | **the code's own history** — churn, authorship, age, work items | **ships with this ADR** |
| 3 | the tracker's history | proposed |
| 4 | the humans — what only they know | proposed |

### 2 — the history, and the promise it does not break

`onboarding/history.py` runs `git` and nothing else, reaches no remote, and writes nothing.
`infer.py` forbids `subprocess` outright and that ban stands unchanged: it exists because `infer`
runs on the **client's own checkout**, on their laptop, before anybody has agreed to anything, where
running a command can truncate a shared dev database. This module runs on a clone the platform
made, in a temporary directory. Those are different acts. `survey()` keeps its own no-subprocess
promise; the caller does the impure part and hands the result over.

**A shallow clone is declared, never reported as a quiet repository.** `clone_for_proposal` clones
`--depth 1`, so every caller arriving by the ordinary route holds one commit and an honest churn
answer of *"1, everywhere"*. Read as data, that is "nothing changes here", and every area of the
repository ranks identically. So the object is three-state — never looked / looked and could not
read, with the reason / looked and found work — and `clone_for_proposal(history=True)` produces a
checkout whose log can be read, degrading to the shallow clone by name where a server offers no
partial clone.

### 4 — asking is not signing, and this is the part most easily misread

A factory that never asks is not more autonomous. It is wrong more often, silently.

| | what it is | verdict |
|---|---|---|
| **sign-off** | the machine is **blocked** until a person signs | rejected — it freezes the product |
| **asking** | the machine states what it could not determine, ranked, and **keeps working on everything else** | required |

**An unanswered question blocks nothing. It is a fact about an area** — it lowers that area's
readiness, which narrows *where* the factory works alone, never *whether* it works.

Today questions are produced in three places and answered in none: `proposal.questions` and
`Baseline.questions` are rendered into markdown and a pull request body, and nothing anywhere reads
an answer back. The loop to route them into already exists and is well designed —
`product/followup.py` closes a question when **the finding is gone from the board**, not when
somebody replies, because *"'did they answer?' is not the question a product owner cares about —
'did the thing get fixed?' is."* Connecting the two is the work; building a question loop is not.

### The one signature that stays, because it is this platform's own

`product/brownfield.py` requires a human to turn `observed` into `accepted`, and that survives
untouched:

> *"A requirement says what MUST be true. Code says what IS true — including bugs, accidents, and
> behaviour nobody ever chose. Turning the second into the first freezes bugs into promises."*

The line, and it is already the line this codebase draws:

- **a concept DESCRIBES code** → no signature. A source that moved invalidates it mechanically.
- **a requirement PROMISES product** → signature. Not because a person must approve the machine's
  reading, but because accepting a reverse-engineered behaviour makes the factory defend it.

### The unit of readiness is an area, not a project

Global readiness is why onboarding a legacy system feels like it never finishes. Per-area readiness
is what makes it shippable in weeks: a ticket touching only well-understood areas runs alone, one
touching a poorly-understood area is refused **with the reason stated and the question asked**.

`onboarding/readiness.py` composes a project-level verdict today and deliberately blocks nothing —
it names refusals other components already make. Per-area readiness has no home yet.
`ProductModule.baseline(areas=…)` already accepts a scope and no production caller passes it.

**When a gate reads that state, the gate computes the verdict and the manifest says what each
verdict authorises.** The mechanism is the platform's; the policy is a row. That is ADR-0022 and
ADR-0034's rule applied one level up, and it is what keeps a company's appetite for autonomy out of
the core.

## What this ADR does not decide

- **The bundle format.** Whether concepts with line-level provenance replace the module map, and
  where they live, revises ADR-0017 and ADR-0035 and gets its own ADR.
- **Who authors a concept in an autonomous factory.** The largest open question, unchanged.
- **Whether a job's replay against its own merged history becomes a measurement.** It would be
  external judging (the pull request a human merged, the tests a human wrote), so ADR-0021's rule
  against grading one's own homework permits it — but nothing is designed.

## Consequences

- The backfill's clone is no longer `--depth 1`. It asks for a partial clone (`--filter=blob:none`)
  — the whole commit graph, none of the historical file contents — and falls back to the shallow
  clone rather than to nothing.
- `RepoSurvey` gains a three-state `history` field, and the survey document and the agent prompt
  gain a "where the work actually lands" section placed **above** the module table, because that
  table is sorted by size and on legacy the biggest module is routinely the one nobody has opened
  in years.
- `survey()` still runs no subprocess. The composition is explicit: the caller reads the history.
- Nothing about an existing project changes until it is onboarded again. A deployment that never
  re-runs `onboard` is unaffected.
