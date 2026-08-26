# The core's design rationale

Three documents, and between them they answer one question: **why is the core shaped like this,
and what is a stranger allowed to change?**

They are design rationale, not instructions. If you are installing the platform, start at
[`../ONBOARDING.md`](../ONBOARDING.md); if you are changing it, start at
[`../../CONTRIBUTING.md`](../../CONTRIBUTING.md). Read these when you want to know why an answer
there is the answer.

## Read in this order

| | | |
|---|---|---|
| [Vision](00-vision.md) | what the platform is trying to become | the thesis, the six principles, and the layer model — applications, core, engine, providers — that every other page here is arranged against |
| [The boundary](02-boundary.md) | where the line actually falls | a three-question test for "is this core?", the six entanglements that resisted it and what closed each, and the decision kernel that is the one move still outstanding |
| [Extensibility](07-extensibility.md) | how a running install gains a provider it did not ship with | the entry-point group, what a package declares, the door that is deliberately kept open to out-of-process providers, and the ledger of what is core and what is vendor-owned |

The file names are numbered because five guards, an architecture decision record and a dozen
mutation cuts cite them by number, and a stable citation is worth more than a tidy sequence.
Numbers that are absent were documents about this project's own history rather than about the
core, and they are not part of what ships.

## The bar these three hold themselves to

This codebase has one signature defect, recorded repeatedly in
[`../engineering-lessons.md`](../engineering-lessons.md) §1: **built, tested, reached by
nothing** — green tests and zero behaviour. A design document is exposed to the same defect one
level up, so a claim on these pages is expected to name the guard, the module or the measurement
that holds it. Where one of them says a thing is closed, there is a test whose name says so.

What works today is not here. It is in [`../STATUS.md`](../STATUS.md), which is the one place a
count of this repository is written down and the one page a guard holds to the tree.
