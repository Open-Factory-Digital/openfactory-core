# ADR 0049 — The whole cycle runs on one machine: `local` is a kind, not a mode

- **Status:** **Accepted** (design; slice 0 shipped with this record)
- **Date:** 2026-09-09
- **Relates to:** ADR-0040 (the core runs on the client's own machines — this is the row it has no
  entry for), ADR-0022 / ADR-0034 (provider seams and the extension model), ADR-0037 (the box),
  ADR-0038 (the platform is complete on its own), ADR-0048 (the factory asks before it spends —
  §5 is what D7 exists to keep true), ADR-0027 (the client's board is not our test bench),
  ADR-0003 (autonomous merge on the current base).

## Context

ADR-0040 D1 placed the forge, the tracker and the board in the client's world — GitHub, Jira,
Azure DevOps — and D2 put everything that circulates on the client's own machines. Between the two
there is a person the platform has no row for: **somebody whose world IS their own machine.** They
have a repository, a coding agent they already pay for, and no wish to open an account anywhere.

That person is not a hypothetical. Two shapes of them arrived at once: a company whose code may not
leave the premises, and a developer who wants to try the factory before agreeing to anything. Both
ask the same thing of the product — *does the whole cycle work with nothing hosted?* — and on
`main` at `cd214ea` the honest answer was no, measured axis by axis:

| axis | rows | a local one |
|---|---|---|
| tracker | `github`, `jira`, `azure_devops` | none |
| board | `github`, `jira`, `azure_devops` | none |
| forge | `github`, `azure_devops` | none |
| ci | `github`/`github_actions`, `azure_devops`/`azure_pipelines` | none — `build_observer` raises |
| credential | `github`, `jira`, `azure_devops` | none — an unknown kind degrades to a token pair |
| board_setup | `github` | none — `init` prints *"brings its own"* |
| box | `worktree`, `container`, `fargate` | **yes** |
| identity | `local` (the default), `oidc` | **yes** |

The stack was already cloud-free; the WORK was not. `docker-compose.yml` lists engine, box,
telemetry, events and secrets and no forge, no tracker, no CI — while `docs/architecture.md`
defined a job as *"working on a remote repository"* and the README called two credentials
irreducible, one of them a forge's.

## Decision

**Nine decisions. `local` is a KIND on the axes that already exist, and the platform's own
vocabulary moves out of the vendors' modules so a new row can read it.**

### D1 — `local` is a kind on the existing axes, never a mode and never a new axis

Five registry keys on four axes: `tracker.local`; `board.local`, keyed by the tracker kind like the
three rows that exist; `forge.local`; and on the CI axis `none`, an honest observer any forge may
name through `forge.options.ci`, plus `local`, which maps to the same observer. `credential.local`
gains one field the row model lacks — `needs: bool` — because a row with an empty `env` is
indistinguishable from GitHub's, whose default IS the generic pair, so a local project on a
deployment that also holds `OPENFACTORY_BOT_TOKEN` would be handed it. `board_setup.local` needs
the port to carry the project, which `BoardCreator.__call__(owner, title, token)` does not.

**Why kinds and not a mode.** `plugins.AXES` stays at seventeen — four tests bind that set to
CONTRIBUTING.md, the stranger probes and the entry-point declarations — so a new axis is four
documents and a probe while a new kind is one row; and `init`'s vocabulary is read live off the
registries, so `local` is offered the day the row exists. A MODE would have been the third thing
this platform refuses: a global flag that every module has to remember to consult.

### D2 — The doors write the default; the model's literal does not flip here

`ProviderRef.kind` defaults to `"github"`, and 123 `Project(...)` calls in 49 test files inherit
it. The contract's own docstring records that removing the default broke 320 tests and defers a
strict model to *"a separate change, with its own card"*. So the default lives where a person
meets it — `openfactory init`, `project init <name> <path>`, `project add`, `POST /api/projects`
and the panel's form — and every door spells the kind on every axis. A **bare filesystem path**
registers as `local`; a path given with explicit coordinates keeps the hosted kind, because a
mounted checkout of a GitHub repository is a shape that runs today and must keep running.

### D3 — The person's repository is the forge

Job branches are pushed into it as `refs/heads/openfactory/<n>`; the merge is a **fast-forward**
into their base, refused with git's own sentence when their tree is in the way. Nothing is written
into their config or their hooks, and their working tree is written by exactly one act: the
fast-forward they asked for.

**Fast-forward, not squash.** The hosted rows squash; locally the history is the job branch's own
commits, authored as the bot, which is how a reader tells the factory's commits from the person's.
A squash would write the person's index; a fast-forward writes only the ref.

**The box, per door.** Under compose the local default's box is the container box — it is the
compose default, the durable start refuses a box that isolates nothing, and the panel's merge rows
answer a durable job. On the host door the box is the worktree box, where the harness is the one on
the person's `PATH` run with their own `HOME` — the same agent they run by hand, on their own
login. That is not a lesser posture for that door: *never for untrusted work* is about a poller
serving strangers' cards, and D9 is where the operator says whose cards these are.

**The `.github/workflows` strip stays.** It is a path in the client's repository, not a provider
kind, and the note it writes into the pull-request body rides along unchanged.

### D4 — The pull request lives in `board.db`, and the local forge speaks the loop's vocabulary

One row per pull request: number, head, base, title, body, state, review events, requested
reviewers, the diff's `patch-id` at open, at each re-push and immediately before the fast-forward,
and the merge commit. The address is a **panel route**; `pr_url` leaves the page. The loop's
control flow does not change — the local forge answers `open_pr`, `pr_for_head`, `pr_ci_status`
(`"none"`, so the loop never waits on CI), `mergeable_state` (`clean` / `behind` / `dirty` /
`unknown`, never raising), `update_branch`, `merge_pr` and the rest.

**What git refuses, the person reads.** Three sentences on the merge path are GitHub's today and
git's sentence reaches none of them. Each prints the sentence the forge put on the pull request
when there is one and today's wording otherwise, so a hosted deployment keeps its branch-protection
hint word for word.

### D5 — One SQLite file, resolved the way the registry is

`board.db` holds cards, comments, labels, columns, links and pull requests. `OPENFACTORY_BOARD_DB`
when set, else the operator's file beside `registry.yaml`; compose points both the worker and the
panel at the state volume they already share. `PRAGMA journal_mode=WAL`, `busy_timeout` 5000 ms,
`BEGIN IMMEDIATE` around every read-modify-write, one connection per port call, never `os.replace`
— the registry's own discipline detaches the journal on a WAL database, which is why it is not
simply copied.

The row keeps the port's two spellings (`#N` and bare `N`), writes `created_at`/`updated_at` as
`datetime.now(UTC).isoformat()` rather than SQLite's `CURRENT_TIMESTAMP` (the ADR-0048 sweep
compares them as strings), answers `comments()` in three ways — `None` could not read, `[]` nothing
there, oldest-first otherwise — and signs its own comments `openfactory[bot]`.

### D6 — The Board and the pull-request page are the panel's, through the ports

`/p/{project}/board`, `/p/{project}/card/{n}` and `/p/{project}/pr/{n}`, a `board` pill beside
`cost`, columns from `board.column_names()`, cards from the tracker. Writes are three action rows —
`card_create`, `card_move`, `card_comment` — so the shell and the page reach the same act. Reads
are one route, opened on demand; while the overlay is open it re-reads on the panel's tick **only
for the local row**, a SQLite read, so a person watches a card move as the job runs.

**Vendor-neutral by construction:** on a GitHub project the Board renders the GitHub board's
columns and a drag is the `set_column` the poller already calls.

### D7 — The requester is whoever filed the card, and the row spells them

A card carries a chat identity; the tracker needs the person in ITS namespace. ADR-0048 §5 is
explicit that **if no identity the tracker knows resolves, the factory does not ask** — so on a
deployment where nobody is registered, the ask-before-you-spend loop switches itself off. That is
the deployment this ADR is for.

The tracker port gains two **optional capabilities**, in the shape `link_child` / `children_of`
already have — called through `getattr`, with today's answer as the default:

- **`identity_of(subject_id)`** — this tracker's own spelling of a platform identity, or `""` when
  the ROW cannot say. Every hosted vendor answers `""`, and that is honest rather than a gap: a
  GitHub login, a Jira display name and an Azure `uniqueName` live in namespaces the platform's ids
  are not drawn from, so the bridge is a thing somebody DECLARES. A row answers non-empty only
  where its namespace IS the platform's — true of a board the platform itself holds, false of
  everything hosted.
- **`mention(login)`** — how this tracker addresses somebody so they are notified. GitHub answers
  `@login`; Jira and Azure answer the plain name, because neither resolves a bare `@name` in a
  comment body and *a mention nobody is notified by is decoration*. The word is not invented here:
  the channel axis has had `mention` with this meaning since ADR-0016.

**The order is the platform's existing rule.** `forge_identity_for` reads the declared
`Project.people` map first and asks the row second, and it does **not** ask the row after an
AMBIGUOUS declaration — two logins for one id is a mistake somebody has to fix, and a row answering
over it would hide the mistake behind a plausible name.

**What the shape does and does not buy, measured.** `check_tracker` asks
`isinstance(tracker, TrackerAdapter)` against a runtime-checkable Protocol, which demands every
public member — so a capability declared on the port is a capability conformance REQUIRES.
"Optional" in this house has always meant *the caller does not depend on it*, never *the port stays
silent about it*; `link_child` and `children_of` have been in exactly this position since ADR-0013.
The cost is bounded and is named rather than papered over: `check_tracker` is a REPORT, reached by
the `conformance-adapter` verb and the suite and by nothing in the build path, so a stranger's
add-on shipped against yesterday's core keeps RUNNING and its report gains one finding naming the
two methods to add.

### D8 — The runner, the workflow and the activities compare no provider kind

`activities._mention_for` read `project.tracker.kind` and compared it to `"github"`. Every other
row on that axis — Jira, Azure Boards, a client's own, a stranger's, the platform's own board — was
rendered as *not GitHub* by a module with no way to ask any of them. It is retired by D7, and
`tests/test_the_lifecycle_names_no_provider.py` holds the property over
`orchestrator/machine.py`, `runtime/temporal/workflow.py` and `runtime/temporal/activities.py`: no
comparison reading a provider's kind on either side, and no string that IS a provider's name.

Deliberately **not** forbidden, because a ratchet that fires on honest code teaches people to widen
its exemptions: `.kind ==` in general (the activities compare eight DOMAIN kinds — an open
question, a ledger loop, a stall, a notification level); passing a kind on to somebody who records
it; `.github/workflows`, a path in the client's repository; and vendor URLs, which
`test_the_board_says_where_it_lives.py` already owns with its `# vendor-url-ok:` marker rule. Two
guards owning one rule is how one of them rots.

### D9 — One question decides where the factory runs, and `local` needs nothing but this machine

Compose is four processes in a file: the engine and its database, the worker and the panel.
Unpacked, three of them run on the host as they are — the worker is a module, the panel is
`openfactory serve` (the very command compose runs), and the engine's address already defaults to a
dev server on `localhost:7233`, which Temporal's own CLI runs as a single binary over SQLite. **What
Docker alone provides is the box's isolation**, and that is the one thing the `local` answer gives
up, out loud.

So `init`'s first question is `runtime`: **`local`** (this machine, nothing hosted — the default at
a terminal), **`compose`** (Docker on this machine — exactly today's file and today's flow), or
**a kind an installed add-on declares** (`fargate`, as today). `local` renders the operator's env
file and switches four things on:

1. **The rows** — local forge, tracker and CI, the worktree box, the dev engine's address, the
   operator's paths. **No PAT, no token, no account is asked for**: the harness credential line
   says the person's own agent login IS the credential on this runtime.
2. **`openfactory up`** — the host's `docker compose up`: the dev engine when its binary is on
   `PATH`, the worker and the panel, stopped together.
3. **`OPENFACTORY_OWN_WORK=1`** — the durable start refuses a box that isolates nothing, on the
   reasoning that *a durable job runs an agent on the worker itself*. On this runtime the worker IS
   the person's machine, where their agent runs anyway, so the refusal accepts this declaration in
   its place. Never written on `compose`, where a deployment that wants it says so by hand, in one
   line it can grep for.
4. **The proof and the merge without Docker** — `box prove` on the worktree box runs the project's
   own `setup:` and `validate:` and asks the harness to answer once, stamped by the manifest's
   commands and the harness's version rather than an image digest, and says out loud that it is the
   weaker of the two proofs.

## What this does NOT mean

- **Not that compose or the cloud lose anything.** No row of theirs is edited. `fargate` and its
  runner are untouched, `compose` renders the file it renders today, and every slice's pull request
  carries one line saying what changes for a hosted deployment — *nothing*, or which row moved.
- **Not that `local` is air-gapped.** The coding agent's traffic to its model leaves the machine,
  and that is the product rather than a dependency. An on-prem OpenAI-compatible endpoint is a
  route on the harness axis and has its own issue.
- **Not that the local box isolates anything.** It isolates the code state and nothing else. A
  deployment serving cards it did not write wants the container box, which is why the declaration
  in D9 exists and why it is not the default.

## Consequences

**The platform's own vocabulary was living at a vendor's address, and that is why neutral code
spelled literals.** Six column names and six neutral keys were written down three times under
`adapters/tracker/github_*` and compared in four more places — the product role's filing and queue
columns, the triage's three arguments, the poller's pickup fallback. Every one of those callers is
neutral, and each spelled a string because asking meant importing a vendor's module to learn the
platform's own word. They now read `adapters/board/columns.py`; the names did not change, and a
test pins them against the values `main` held rather than deriving them from the module it checks.

**A capability declared on a Protocol is a capability conformance requires,** and the issue that
led here asserted the opposite. Measuring it changed what this ADR promises: not *nothing breaks*,
but *nothing stops running, and the report names the two methods*. The difference matters to
exactly one reader — a stranger with an add-on in the wild — and they are the reader least able to
find out by experiment.

**The `local` row is what will prove D7 rather than assert it.** Every hosted row answers `""` to
`identity_of`, so slice 0 ships a capability whose only honest answer today is *cannot say*. That is
deliberate: the port learns the question before the row that answers it arrives, so the row is one
line rather than a second migration. The guard in D8 is what keeps the retired comparison retired
in the meantime.
