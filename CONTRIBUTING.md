# Contributing

Contributions are welcome, and the bar is the one the codebase already holds itself to.

## Reading the system first

The user-facing path (`docs/README.md`) deliberately calls everything else "internal". For a
contributor that is the wrong filter — those pages are your map:

| | |
|---|---|
| [README.md](README.md) §The shape | the package tree in one screen: contracts, adapters, orchestrator, runtime |
| [docs/architecture.md](docs/architecture.md) | how the pieces fit, and the vocabulary the code uses |
| the `openfactory-aws` add-on package | the durable engine realised on one cloud — poller, workflow, activities, replay — is drawn in that package's own documents, outside this tree |
| [docs/adr/](docs/adr/) | **why** — 45 decision records. Read the one nearest your change before arguing with it |
| [docs/engineering-lessons.md](docs/engineering-lessons.md) | the defects this codebase has actually paid for, with their measurements |
| [docs/STATUS.md](docs/STATUS.md) | what is proven end to end and what is not |

The single most useful habit: before changing behaviour, find the test whose NAME states the
property you are about to change. Tests here are named as sentences (`test_a_named_check_is_not_
dropped.py`) precisely so that this search works.

## The house rules, short

- **Run `ruff check openfactory/ tests/` before the suite.** A lint error here is often a
  reachability defect (an undefined name is code no test ever ran).
- **Run the suite in both orders**: `pytest tests/ -q` and `pytest tests/ -q -p no:randomly`.
  A failure that depends on ordering is a state leak, not flake — find it, don't reroll.
  Add `-n auto` (pytest-xdist, already in `[dev]`): the suite is large (the count lives in
  [`docs/STATUS.md`](docs/STATUS.md)) and drops from
  minutes to seconds. If a test passes alone and fails under `-n auto`, that is the same state
  leak, found earlier.
- **A new guard is proven by mutation, and there is a runner for it.** If you add a test that
  asserts a property, break the property on purpose and watch the test go red — a guard that
  never failed is a guard nobody has checked. Do not do it by hand:

  ```bash
  python tools/mutate.py tools/mutations/<your-plan>.py
  ```

  A plan is a `TEST` path and a list of `(label, file, old, new)` cuts (an optional 5th element
  targets a different test file). The runner checks every anchor matches **exactly once** before
  it touches anything, restores from a backup outside the tree, and leaves a `.mutate-in-flight`
  note naming the wound if it is killed mid-cut — `finally` does not survive SIGKILL, and a
  mutant once sat in a working tree through a full green suite. A surviving cut means one of
  three things: the guard is weak, the cut is aimed wrong, or **the code is dead** — that last
  one has been the answer twice.
- **Failures speak by name.** Anything a user can hit must refuse with one sentence naming the
  cause and the remedy — never a raw traceback, never a silent no-op. `openfactory doctor` is
  the bar.
- **Comments say WHY, with the measurement.** The codebase's comments carry dates, exit codes
  and the incident that earned them. Keep that: a claim without its measurement is a claim the
  next person has to re-earn.

## Card ids in comments — `#137`, `C-22`, `#106 item 4`

You will meet these everywhere: about 900 in the package and 1,300 in the tests. They are the
ids of cards on the tracker this repository had before it was public (`C-NN` is the older
scheme, `#NNN` the later one), and they are kept as **provenance**, not as links: the sentence
around the id carries the reasoning and the measurement, the id says which incident earned it.
There is nothing to open, and nothing to update — do not strip them (a purge measured on
2026-08-24 would also have eaten `#189` and `#412` where they are FORMAT EXAMPLES inside prompts),
and do not add new ones from a tracker a contributor cannot see. What a user READS is a different
matter: `--help` screens, conformance findings and log lines carry no card id, and
`tests/test_no_card_id_reaches_a_stranger.py` holds that line.

## Extending a provider axis

**The walkthrough is [docs/writing-an-addon.md](docs/writing-an-addon.md)** — the two files, the
four commands, the per-axis builder signature and the traps. What follows is the summary.

Every axis is an adapter behind a registry, and an add-on plugs in through the
`openfactory.adapters` entry-point group without editing this repository: a package declares
`<axis>.<kind> = package:builder` (the role axis as `role.<name>`), its rows join the registry's
table at lookup time, a built-in row wins a collision, and an unknown kind still refuses by
name. The axis names an entry point may use are `openfactory/plugins.py::AXES` (board,
board_setup, box, box_runner, channel, ci, credential, event, forge, harness, identity,
metrics, notifier, role, session_store, token_pool, tracker), and
`tests/test_a_stranger_can_add_an_adapter.py` holds that list equal to what the registries ask
for — see [docs/core/07-extensibility.md](docs/core/07-extensibility.md), including §10's
ledger of what is core and what is vendor-owned. The core ships GitHub, Azure DevOps and Jira;
the maintainers' own cloud box and chat channel are add-on packages of exactly this shape
(`openfactory-aws`, `openfactory-slack`), and [docs/STATUS.md](docs/STATUS.md) says which paths
of this tree leave with them. Run your adapter against the
conformance suite: `openfactory conformance-adapter <kind> <pkg.module:attr>`, where `<kind>`
is any row of `openfactory/conformance/adapters.py::CHECKS` (every port has one — the
`--help` text lists them) and the target may be an instance, a class, or a zero-argument
factory function. An instance that does not satisfy its port is refused by name, listing the
methods it lacks — it is never called.

## Four ways to break a seam, none of which look wrong at the time

Each of these is a real failure mode this codebase is exposed to, and each has been proposed
here at least once.

**Stub adapters, written to "prove" agnosticism.** ADR-0022 refused to create an empty
`gitlab.py` precisely because *"an empty module nothing exercises is this repository's
signature defect."* The pressure is real — a shelf of half-adapters reads well in a README —
and two working providers beat eight stubs. The conformance suite is what makes the refusal
legible: no green run, no listing.

**Widening a port because a provider has a feature.** The channel port has three methods
because the core calls three things. When someone asks for reactions or message editing, the
question is not *does that provider support it* but *does the core call it*. A capability that
grows because a provider has a feature is a leak with a Protocol on it.

**Freezing a port's shape before its second implementation.** A port with one implementation is
that implementation's shape wearing a general name. An axis is agnostic when it is born with
two, which is the ADR-0022 bar — and it is why `openfactory conformance-adapter` exists before
any interface here is called settled.

**Splitting a change across repositories so the split can be announced.** Two repositories
multiply the cost of every cross-cutting change. The add-on packages are separate because their
code belongs to one provider and the entry-point group already carries them, not because a
second URL reads as more modular.

## Pull requests

Small and focused beats large and mixed. State what you measured, not just what you changed.
CI runs the same ruff + pytest you ran locally.

**Your machine is not the reference.** Anything optional that lives outside the clone — a
directory of sample projects, a credential, a running daemon — must make a test SKIP at run
time, never change what is collected. A module that resolves such a thing at import can raise
during collection, and one module raising takes the whole suite with it: that happened here on
2026-08-06 and CI executed zero tests for fifteen days while every laptop stayed green.
`tests/test_ci_runs_what_we_run.py` is the guard, and `tests/demo_projects.py` is the pattern.
The identity guards follow it: they scan for synthetic shapes on every machine and union a
gitignored real list (`tests/.identity-forbidden.txt`) when a maintainer's machine has one — the
list is optional on every run, a fork never holds it, and writing it in CI from a repository
secret is a later, optional convenience rather than a gate.

## Licensing, and why there is no CLA to sign

This project is Apache-2.0 (`LICENSE`), and **Apache-2.0 §5 already settles what happens to your
contribution**: unless you say otherwise in the pull request, anything you submit for inclusion is
under those same terms. That is the whole agreement — there is no contributor licence agreement to
sign here, and none is planned.

**You keep the copyright on what you write.** The line in `LICENSE` and `NOTICE` reads
*"Copyright 2026 The OpenFactory Authors"*, which is a collective label for everyone who has
written part of this — not a transfer to anybody. Nothing is assigned to a company, and there is
no company holding it.

Two things travel with the code and may not be dropped from a fork (§4(c) and §4(d)): the
copyright notices, and the `NOTICE` file. `NOTICE` is also where the name is reserved — the code
is free, the mark is not — and that split is deliberate rather than an oversight. A restrictive
licence would buy protection against a hyperscaler reselling this, which is a problem the
project does not have, at the cost of the adoption it is trying to buy. What is worth defending
is the mark, and the mark is only worth defending because the conformance suite gives it
meaning. So anyone may fork; only a build that passes the published suite
(`openfactory conformance`, `openfactory conformance-adapter`) may be called OpenFactory.
