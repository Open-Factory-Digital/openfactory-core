# ADR 0043 — A project declares what it is: profiles as a cascade layer

- **Status:** **Accepted; shipped** (the mechanism, two worked examples, and the guideline and
  merge-gate surfaces that read it).
- **Date:** 2026-08-31
- **Relates to:** ADR-0001 (D-2 the cascade, D-6 risk, D-12 merge policy), ADR-0011
  (suppressions), and `orchestrator/risk.py`, whose `RiskLevel.LOW` note names the mechanism this
  ADR is half of.

## Context

Ask what the platform can **say** about the nature of a project and the entire vocabulary is two
booleans: `components[].risk` (`normal | high`, read by exactly one caller) and `merge_policy`
(`human | auto`). On the other side, `orchestrator/context.py::_org_defaults` was documented as
injecting every framework guideline *"into EVERY job regardless of project"*.

Put the two together and the platform's position was:

> A throwaway proof-of-concept and a regulated bank's legacy monolith receive the same executor
> prompt, the same twelve engineering rules, and the same TDD mandate.

That is not a gap in customisation. It is a statement that the factory holds one opinion about how
software is built and applies it to everything — and it leaves an operator with **nothing to tune
toward**. Publishing all seven role prompts would not have helped, because the platform never asked
what the project IS.

## Decisions

### 1. A profile is a CLASS, and it is not a waiver

Three different things look like "override" and must not share a mechanism. The existing design
already names `extend`, `replace` and `waive`, and `waive` is the load-bearing one: a named reason,
an approver, an expiry, stamped on every PR. That is right, and it is **the wrong instrument here**.

| | |
|---|---|
| **waiver** | *this project is like the others, except here* — costs a name, expires, is reviewed |
| **profile** | *this project is not like the others* — costs a declaration, and the set that follows is coherent by construction |

A proof-of-concept does not want to waive TDD with a written reason, a named approver and an expiry
date. That is bureaucracy applied to something that is not an exception: it is what the POC **is**.
Twelve signed waivers are paperwork; declaring what the project is and having a coherent set follow
is engineering.

### 2. The name is an OPEN SET — a layer that composes, never an enum

`poc | legacy | greenfield | mobile` is wrong at the first client with a nature nobody anticipated
— the identical mistake the OKF port plan refuses for the concept taxonomy (*"every company will
have its own"*). So `name` is a plain string, a profile composes through `extends`, and resolution
is a cascade: `openfactory/org_defaults/profiles/` ships worked examples, `.openfactory/profiles/`
in the client's repo wins.

**The project layer winning is the opposite of `role_prompt`'s rule, on purpose.** There, a
third-party ADD-ON offering a `techlead.md` is refused, because a package silently changing what the
tech-lead means for every project on the deployment is a supply-chain problem. Here the overriding
layer is the client's own repository declaring their own policy. The two rules disagree because the
threat models do.

### 3. The core ships the mechanism, not a vocabulary

Two worked examples ship (`prototype`, `regulated`) because a mechanism with no example is a feature
nobody can start from. What a profile *authorises* is company policy and stays the client's.

### 4. Which direction a profile may move — the rule that keeps this from becoming a hole

ADR-0001 D-2 is that a project may tighten, never loosen. A profile keeps it, with one deliberate
line drawn by what a rule IS rather than by who wrote it:

| | may a profile remove it? | why |
|---|---|---|
| **guidelines** | **yes** — waive and replace | prose is the WEAK form of a rule by this platform's own thesis. Dropping `tdd.md` for a prototype is the declaration doing its job. |
| **gates** | **no** — additive only | a gate is the STRONG form. The floor stays unconditional; removing a floor gate is an exception, which is a waiver, with a name and an expiry. |
| **the merge gate** | **no** — `human` is the only accepted value | a profile may send a risk level to a person that the manifest would have auto-merged. There is no value that would do the reverse. |

### 5. A name that does not resolve is a HOLD, not a shrug

If the manifest says `profile: regulated` and nothing defines it, the honest reading is that this
project believes it runs under rules the platform never applied. Resolution raises `ProfileError`,
and `should_auto_merge` refuses when a manifest names a class the caller did not resolve. The
failure direction is closed, the same way the floor's is: a broken install stops the queue instead
of quietly widening what may run.

## Consequences

- `_org_defaults` no longer ends its docstring with *"regardless of project"*, and that sentence
  going away is the measurable result of this ADR.
- **With no profile, nothing moves.** A dimension that quietly re-rules existing projects would be
  a migration disguised as a feature, and a test holds that line.
- `pyproject.toml` needed `org_defaults/**/*.yaml` **added to** `org_defaults/*.yaml`, not
  substituted for it. Profiles live one directory deeper than `floor.yaml`, so the one-level glob
  alone would have shipped the mechanism with no worked example — resolvable on the tree that
  wrote it, a `ProfileError` on every `pip install`. Replacing it was worse and the floor's own
  guard caught it: `**` here does not match the ZERO-directory case, so the fix for one packaging
  hole silently reopened #99's and dropped `floor.yaml` from the wheel. Two entries, and the pair
  is the point.

## What is NOT decided here

`RiskLevel.LOW` is still read by nothing. `orchestrator/risk.py` says making `low` mean something is
**loosening** and needs *"a waiver or a profile"* — this ADR is the profile half, and the half that
arrived cannot loosen. `low` becomes meaningful when the waiver object exists to carry the name and
the expiry.

The deployment-overlay layer (the cascade's layer 2) does not exist yet. Profiles resolve across the
two layers that do, and the design assumes nothing that would make the third expensive: a profile
addresses framework guidelines **by filename**, never by path, precisely so the resolution point can
move.
