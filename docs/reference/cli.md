# The CLI

`openfactory` is the whole control surface. The panel is the other one — the reference surface,
always present — and a chat bot is a third where a deployment installed that connector as an
add-on package. All of them are views onto the same thing; anything you can do from them you can
do here, and a few things only exist here.

Everything takes a **project handle** — the name you registered. The framework drives many projects
and adding one is data, not code.

In a compose deployment the same commands run inside the worker:

```bash
docker compose --env-file .env.compose exec worker python -m openfactory.cli <command>
```

---

## Running work

### `openfactory run <project> <issue>`

Drive one ticket through the state machine, right now, in this process. This is the direct path —
no durable engine, no queue.

| option | default | |
|---|---|---|
| `--sandbox` | `worktree` | `worktree` \| `container` |
| `--image` | *unset* | the box image; unset → the project's `box.image`, then `OPENFACTORY_SANDBOX_IMAGE`, then the framework's |
| `--review` / `--no-review` | on | the independent reviewer |

Exits non-zero unless the job ends in `PR_OPEN`, `MERGED` or `DONE`, so it composes in a script.

### `openfactory poll <project>`

Resume any rate-limit-paused tickets whose reset has passed, then take the board's TO-DO column —
**one at a time**, stopping when one pauses or parks. This is the scheduler's shape; run it on a
cron or a loop. There is no parallelism by design: the floor frees at merge, so the next ticket
builds on a base containing the last one.

---

## Finding out what is wrong

### `openfactory doctor <project>`

Nine checks, each producing **one distinct, actionable line**: Docker, the harness on PATH, the
manifest, forge access, the board's columns, a `merge_policy: auto` against branch protection that
requires review, and the product-module link.

Run this first. Before the first ticket there is no invariant protecting you — a mis-named board
column, an App without Projects permission and a missing harness all produce the same symptom,
which is nothing happening.

### `openfactory conformance <project>`

Whether the **manifest** is complete: the floor requires `validate.test` and `validate.security`.

> Note: this is a command somebody runs, **not a gate on the job path**. A project that skips it and
> declares no `validate:` block will run and pass every gate vacuously. That is a known gap, not a
> feature.

---

## Projects

| | |
|---|---|
| `openfactory project add <name> <path-or-url>` | register one. GitHub: `--repo owner/name` (inferred from a clone URL), `--board-owner`, `--board-number`. Azure DevOps: a `dev.azure.com` clone URL carries the coordinates ([the guide](../setup/azure-devops.md)); `--work-item-type`, `--token-env` |
| `openfactory project list` | what this deployment drives |
| `openfactory project init <name>` | register + create the board with the platform's columns + scaffold `.openfactory/project.yaml` (converges; each half runs only if missing). The board half is GitHub-only — other trackers bring their own board |
| `openfactory project set-model <name> <model> [--role r]` | which model the coding agent runs, per project — no YAML editing inside the worker. Passed to the harness verbatim; the command asks it about the name and WARNS when it does not recognise it, never refuses ([ONBOARDING §11](../ONBOARDING.md)) |
| `openfactory project remove <name>` | unregister |
| `openfactory project forget-conversations <name>` | delete every recorded conversation turn — a data-deletion request. Irreversible, asks first, and touches only the client's conversation, never the platform's operational memory |

The registry is **operator-owned**; the agent cannot reach it. That is why the harness choice, the
credentials and the box configuration live there rather than in the manifest inside the repository
the agent edits.

**First-time setup** — `openfactory onboard <name> --yes` (worker) does the whole of it,
measured: per repository it reads the manifest out of the code, **proves it in the real box**,
generates the module map, and opens one pull request carrying all three with the proof's
verdict in the body; then creates-or-uses the context repository and proposes the backfill the
same way (a context repository born empty gets the declaration as its first commit instead —
no pull request can target a commitless base). `--source owner/repo` (repeatable) names the repositories of a multi-repo product —
N repositories, N proofs, N pull requests; `--skip-context` leaves the context half out. A
failing proof does not withhold the pull request — it is quoted in it. Walked in [ONBOARDING §3](../ONBOARDING.md).

**The environment session** — `env read <path-or-name>` proposes the manifest and writes
nothing; `env apply <path-or-name> --yes` writes it into that checkout (`--accept`, `--set`,
`--force`, `--out`). With **no checkout anywhere**, `env apply <name> --yes --pr` has the worker
clone the repository and propose the manifest as a pull request instead — the whole session is
walked in [ONBOARDING §3](../ONBOARDING.md).

**The context repository** — `product declare <name> <repo>` names one the client ALREADY has
(GitHub `owner/repo`; Azure `repo`, or `Project/repo` across projects) and reads it back with
both credentials that will open it. `product init <name> --create-context --write` creates one
where the credential may. A credential that may NOT create says so and names `declare` — the
enterprise shape where repository creation is somebody else's process.

**The box proof** — `box prove <name>` runs the project's own `setup:` and `validate:` inside
the real box and saves the verdict; `box status <name>` says whether it still holds, what moved
if not, and **what the proof is pinned to** (the box's toolchain — a rebuild that leaves it
unchanged does not expire the proof). Both take `--repo owner/repo` for a multi-repo product's
other repositories — the proof and the pickup gate are per repository
([ONBOARDING §5](../ONBOARDING.md)).

---

## The rest

| | |
|---|---|
| `openfactory serve` | the panel, `--host`/`--port`. An unset `OPENFACTORY_PANEL_TOKEN` means **open** — fine on a laptop, wrong for anything reachable |
| `openfactory bot-token` | mint a GitHub App installation token (~1h). On the onboarding path this is **the App smoke test** and nothing else: a printed `ghs_…` proves App ID, key and Installation ID agree, and there is nothing to save — the factory mints its own per job ([the guide](../setup/github.md) §5). The `export OPENFACTORY_BOT_TOKEN=$(openfactory bot-token)` form is for a shell that needs a token for a one-off `gh` command. Reads the key from `OPENFACTORY_GH_APP_KEY` (a path) or `OPENFACTORY_GH_APP_KEY_CONTENT` (the PEM itself) |
| `openfactory knowledge build \| check` | build and inspect the Knowledge Layer bundle — a module map the agents are handed. On by default ([ADR-0035](../adr/0035-knowledge-layer-on-by-default.md)). For a project the factory cloned itself, `build --publish` pushes the map to the repository's knowledge branch — without it the map lands in a disposable clone and the command says so. `--repo owner/repo` targets a multi-repo product's other repositories |
| `openfactory approver add \| list \| remove` | manage who may authorise a production release. Identity plus password; production is never released from chat ([ADR-0016](../adr/0016-slack-actions-authorization.md)) |

---

## One thing that is not obvious

`openfactory` is not on your `PATH` after a plain clone — it lives in the virtualenv
(`.venv/bin/openfactory`). Every document, including this one, writes `openfactory <command>` as though it were
installed. It is the first command a new adopter runs and the first one that fails, and it is
listed here because saying so costs a line and discovering it costs an evening.
