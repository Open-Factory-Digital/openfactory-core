# ADR 0046 — A file nothing describes is the least safe to change

- **Status:** **Accepted** — implemented in the same change that records it. Every claim below is
  stated against the tree at `3fa673c` (with #42 the checker, #48 the inventory, and this).
- **Date:** 2026-09-05
- **Relates to:** ADR-0017 (the Knowledge Layer), ADR-0045 (the fingerprint gains a reader — the
  checker this gate stands on), ADR-0044 (a project declares what it is — where `okf_gate` lives),
  ADR-0001 D-6 and `orchestrator/risk.py` (a path no component declares needs a human — the same
  stance one level up).

## Context

The bundle now holds three mechanical answers about any file of a repository: **what it is** (the
inventory, one row per file with the rule that placed it), **whether its kind was excused from
description** (the coverage table's `excused` flag, one row per kind), and **whether what describes
it still holds** (the checker, one verdict per citation against the bytes on disk). Nothing read
the three together, and the job pipeline opened every pull request in the same words whether the
change touched a file three concepts describe or a file nothing has ever said a word about.

The reference framework's gate (`okfgate.py`, a per-file verdict as an exit code) carries the one
sentence this ADR is named for: *a file nothing describes is the least safe file to change, not the
freest — reading the gate as "no concept, no objection" inverts it.* The core already holds that
stance for the manifest's components (`risk.py`: a change matching no declared component walked an
empty list, found no `high`, and merged; now it needs a person). The same inversion was waiting one
level down, against the knowledge.

The port's first decision (ADR-0045 §1, *no human sign-off in the core*) removes the reference's
most common verdict, `needs-signoff`: a citation that moved is refused by a fingerprint, not by a
missing signature, and the checker is the mechanism that replaced the signature.

## Decision

**One verdict per file the change touches**, judged against the published bundle and the base
checkout — the base, because the question is whether the knowledge covers the file *as it was*;
against the branch every file the agent just edited would be stale by construction.

| verdict | when | blocks |
|---|---|---|
| `clear` | at least one concept cites the file and its citation still holds | no |
| `exempt` | the file's kind is excused by the coverage table (tests, docs, configuration…) | no |
| `new-file` | not in the inventory the bundle was built from — nothing recorded can be missing about a file that did not exist yet | no |
| `stale` | described, and the concept read bytes that are no longer there | with a person |
| `gap-blocked` | a recorded unknown on the file that blocks: a **high** credential risk, a file no rule could place, an open question | yes |
| `no-concept` | of a kind nothing excuses, and nothing describes it | **yes, on purpose** |
| `no-bundle` | nothing is published for the repository — every file | yes |

A recorded unknown outranks a description (a described file with a high credential risk is
blocked, not clear); a low credential risk — a placeholder in an example file — is listed and does
not block.

**The stance is the change's, and the worst file decides it:** `green` (every file clear, exempt or
new) may run alone; `amber` (something stale) merges with a person; `dark` (no-concept,
gap-blocked, no-bundle) is refused with the question asked. The question names the files and both
ways out — author the knowledge first (the backfill, or a larger `okf_concept_budget` so the
renewal reaches them), or accept the risk and merge by hand.

**What a stance does is the project's to declare** — `okf_gate` in the manifest:

- `advise` (**the default**): the verdicts, the stance and the question go into the pull request
  body; nothing else moves. The default is advise for the reason the concept budget's default is
  small: every project is dark before its first backfill, and a default that refused every change
  on day one would get the gate switched off exactly where it is most needed.
- `enforce`: an amber change is never merged unattended (`merge_policy`); a dark one is opened as a
  pull request — the work is not lost and a person can still merge it by hand — and the job is
  parked with the question on the ticket, so nobody merges it by habit.
- `off`: the gate does not run.

**The gate never fails a job.** A bundle that cannot be fetched or read is a sentence in the body
("could not run — nothing was judged"), because a gate that crashed the job it was informing would
be the strongest possible argument for switching it off.

**A bundle from before the inventory existed** is judged by classifying each path by name — a test
file is still exempt, a code file still owed — and cannot tell a new file from an old one; it does
not pretend to.

## Consequences

- The pull request body gains a **Knowledge** section every reader of the change sees: the stance,
  what this project's mode makes of it, one line per file with the verdict and its reason, and the
  question when the change is dark. `openfactory knowledge gate <bundle> <repo> [--changed]` gives
  the same answer from a shell, as an exit code (0 green, 1 amber, 2 dark), and `--changed` reads
  `git status` — staged, unstaged and untracked — rather than a `diff --name-only` pipe, which drops
  most of what a change *adds*.
- `RunResult` carries the stance, the question, one summary line and the per-file verdicts, so the
  panel and the events can show what the body shows.
- The gate costs no model call: the published bundle (one shallow clone of the context repository,
  the same fetch the tech-lead makes), the checker, and the inventory's tables.
- A project that turns on `enforce` before its first backfill parks every change. That is the
  setting working as declared, and the reason the default is not `enforce`.

## What is NOT decided here

- **The factory authoring the missing concept itself** before opening the pull request — the
  natural next step for a dark change under `enforce`, and the one that turns "refused with the
  question asked" into "answered and merged". It is a spend decision and belongs with the budget.
- **Per-area budgets.** The question that reveals which areas are dark most often is now asked on
  every change; what to do with the answer is a later decision.
- **Kinds of gap beyond the three that block.** `open-question` blocks and nothing writes it yet;
  `dead-code` and `unreadable` are recorded and do not block, and may need to.
