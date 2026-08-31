# OpenFactory

**An autonomous software factory.** It takes tickets from your board and returns reviewed pull
requests — planned, implemented, validated by *your* test suite, independently reviewed, and
merged under the policy you chose. Humans stop authorising every step and start evaluating
results; production stays behind a human gate, always.

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)

It is **not a coding agent** — it orchestrates the ones you already use (Claude Code, Codex,
Kimi, OpenCode) behind one adapter contract. It is **not a SaaS** — it runs on your machines,
against your board, with your credentials, and no cloud account is required.

## Why this one

- **Policies authorise, humans evaluate.** The manifest declares the merge policy, the quality
  floor and the promotion chain; the factory refuses vacuous green — a project with no declared
  test command is *held*, not "passed".
- **The box is proven before money is spent.** `box prove` runs your own `setup:` and
  `validate:` inside the real sandbox before any ticket is picked up. A misconfigured
  environment is a named finding, not a burned agent pass.
- **Every stall speaks.** A blocked job parks with executable options for a human; a silent
  forever-wait is treated as the platform's own defect class.
- **Provider axes, not provider lock-in.** Tracker, board, forge, CI observer, notifier, coding
  agent and sandbox are independent adapters — GitHub Issues + Projects, Jira, Azure DevOps
  (work items → Azure Repos PRs, end to end), chosen per project in a registry.
- **An independent review, structurally.** The reviewer can run on a *different* engine from the
  executor, so "you did not write this code" is true by construction.
- **Honest docs.** What does not work is written down (`docs/STATUS.md`)
  before you decide anything.

## Install

**Docker. Only Docker.** No Python on the host, no `sudo`, one line:

```bash
curl -fsSL https://openfactory.digital/install.sh | sh
```

| | |
|---|---|
| **read it first** | `curl -fsSL https://openfactory.digital/install.sh -o install.sh && less install.sh && sh install.sh` |
| **no script at all** | the four commands below |
| **on your PATH** | `uv tool install openfactory` — the CLI on your own machine, for driving a deployment |

> The worker mounts the host's Docker socket — that is how `sandbox: container` starts a box, and
> it is root-equivalent on the host. It is the same trade `docker compose up` has always made here.

> The installer sends nothing anywhere. There is no telemetry in this project.

Re-running the installer is the upgrade path: it resolves the newest release, pulls it, and
restarts the stack. Your answers and your data survive it.

<a id="the-un-piped-equivalent"></a>
Prefer to do it by hand? These are the same four steps, and nothing else:

```bash
REPO=https://github.com/Open-Factory-Digital/openfactory-core
VERSION=$(curl -fsSLI -o /dev/null -w '%{url_effective}' $REPO/releases/latest); VERSION=${VERSION##*/tag/}
curl -fsSL $REPO/releases/download/$VERSION/docker-compose.yml -o docker-compose.yml
curl -fsSL $REPO/releases/download/$VERSION/SHA256SUMS | sha256sum -c --ignore-missing
docker run --rm -it -v "$PWD:/out" -u "$(id -u):$(id -g)" \
  ghcr.io/open-factory-digital/openfactory-cli:$VERSION init --out /out/.env.compose
echo "OPENFACTORY_VERSION=$VERSION" >> .env.compose
docker pull ghcr.io/open-factory-digital/openfactory-sandbox:$VERSION
docker compose --env-file .env.compose up -d
```

Three of those lines look optional and are not. The **version is resolved once** and written into
`.env.compose`, because `docker-compose.yml` defaults to `main` — right for a contributor working
on the branch, wrong for anybody running a factory. The **box image is pulled by hand** because
`docker compose up` does not fetch it: the worker launches it as a sibling container on your own
daemon. And the **checksums are verified**, which is why the files come from the release rather
than from the website — a static host can serve a file and cannot checksum one.

Then open http://localhost:8787 in a browser — the panel (8080 is the engine's own UI).

**Two credentials are irreducible for a real ticket** — the coding agent's
(`CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`, or `ANTHROPIC_API_KEY`) and a forge
credential (a PAT to try things out, a GitHub App for real use). `openfactory init` asks for
neither and names both; only the agent's cannot be postponed past the first hour.

`openfactory preflight` says what is still missing on this machine, one line each with a remedy.

Register a project **inside the worker** (the compose stack has its own registry; a
laptop-registered project is invisible to it). One command registers it and creates the board
with the platform's columns:

```bash
docker compose --env-file .env.compose exec worker \
  openfactory project init myapp https://github.com/<owner>/myapp.git   # your org or username
docker compose --env-file .env.compose exec worker openfactory doctor myapp
```

(`project add` is the variant for a board you already have, or for none at all. On Azure
DevOps, register with your `dev.azure.com` clone URL — it carries the
organisation/project/repository, and Azure Boards ships with the project, so there is no board
to create: **[docs/setup/azure-devops.md](docs/setup/azure-devops.md)**.)

`doctor` runs nine checks always and up to four more when they apply, naming every missing
prerequisite with its remedy — including the
agent credential and the forge credential. From there, the guided first hour is
**[docs/ONBOARDING.md](docs/ONBOARDING.md)**: the environment session that reads your repository
and proposes its own manifest, the box proof, a costed rehearsal on a synthetic ticket, and the
first real card.

## Your first ticket

An ordinary issue, in English or Portuguese:

```markdown
## Objective
Users can export their report as CSV.

## Acceptance criteria
- a `GET /reports/{id}/export` endpoint returns text/csv
- the export respects the report's current filters
```

Drag it to **TO-DO**. The factory sizes it, proves the box, plans, implements, runs *your*
gates, opens the PR, has it independently reviewed — and with `merge_policy: human` (the
recommended start) waits for your merge. The panel at `:8787` shows every step live.

## The shape

```
openfactory/
├── contracts/     Pydantic models — the framework↔project↔agent↔board interface
├── registry.py    the set of projects one deployment drives (add one = data, not code)
├── policy/        the quality floor: stack presets + org defaults + conformance
├── adapters/      the provider axes — a project mixes them freely; the core ships GitHub,
│   │              Azure DevOps and Jira on every axis below that has a vendor, and an
│   │              add-on package adds a kind through the `openfactory.adapters` entry points
│   ├── tracker/     GitHub Issues, Jira, Azure DevOps work items
│   ├── board/       GitHub Projects, Jira status, Azure DevOps boards
│   ├── forge/       GitHub, Azure Repos — branches, PRs, merges, tags
│   ├── environment/ CI / deploy / health, read-only — GitHub Actions, Azure Pipelines
│   ├── agent/       CodingAgentAdapter — Claude Code, Codex, Kimi, OpenCode
│   ├── reviewer/    the independent review
│   ├── channel/     the panel — the reference surface; a chat channel is an add-on package (openfactory-slack)
│   └── sandbox/     container = real; worktree = local/test; a cloud box is an add-on package (openfactory-aws)
├── orchestrator/  the deterministic state machine (the spine)
├── runtime/       the durable engine (Temporal): poller, jobs, promotion tail
└── cli.py         `openfactory` — project-first commands
```

## The roles you can switch on

| role | what it is | where it lives |
|---|---|---|
| **engineering loop** | ticket → reviewed PR → merge | on by default; this README |
| **post-merge** | watch your deploy, walk your stages, gate production | opt-in per project — [ONBOARDING §13](docs/ONBOARDING.md) says what silence means |
| **tech-lead** | diagnoses parked jobs, proposes the fix, acts on your yes | the panel; a chat channel such as Slack is an add-on package (openfactory-slack), never a prerequisite |
| **product owner** | requirements as reviewed docs in a context repo; accept/queue/release | `/product/<name>` on the panel — [docs/reference/product-role.md](docs/reference/product-role.md) |
| **release gate** | production is approved by a named human with a password, always | [docs/reference/product-role.md §3](docs/reference/product-role.md) |

## Documentation

**One path, three references.** The map is [docs/README.md](docs/README.md); this is the short
form:

| read this | when |
|---|---|
| [docs/ONBOARDING.md](docs/ONBOARDING.md) | **start here** — the whole guided session on your own codebase, and the only onboarding there is |
| [docs/setup/github.md](docs/setup/github.md) | the path sends you here for GitHub: the App screen by screen, a personal account's board token, a board by hand |
| [docs/setup/azure-devops.md](docs/setup/azure-devops.md) | …or here for the all-Microsoft side: PAT scopes, board states, registration by clone URL |
| [docs/STATUS.md](docs/STATUS.md) | the honest read before deciding anything |
| [docs/reference/configuration.md](docs/reference/configuration.md) | manifest / registry / environment — who owns which setting, promotion chains |
| [docs/reference/cli.md](docs/reference/cli.md) | every command (the `env`/`box`/`product` surfaces are walked in ONBOARDING) |
| [docs/reference/product-role.md](docs/reference/product-role.md) | switching on the product owner |
| [docs/writing-an-addon.md](docs/writing-an-addon.md) | your deployment needs a provider the core does not ship — a row, end to end, editing nothing here |
| [docs/adr/](docs/adr/) | why it is built this way (43 decision records) |

## Status

Working, and honest about where. The whole loop — sizing → box proof → agent → your gates → PR
→ independent review → merge — has run end to end on four stacks (Python,
serverless TypeScript, .NET, multi-repo) against real GitHub, real Jira and real Azure DevOps.
The suite runs in both orders on every change and new guards are proven by mutation before they
count — the current size, the commit it was measured at, and everything that is NOT settled are
in [`docs/STATUS.md`](docs/STATUS.md), which is the one place any of those numbers live.

## Taking part

Issues and pull requests are welcome, and the bar is written down rather than implied:
[CONTRIBUTING.md](CONTRIBUTING.md) explains the house rules (a guard for every behaviour, a
mutation for every guard) and how to add a provider to an axis without touching the core.
**There is no CLA** — Apache-2.0 §5 already covers what you submit, and you keep the copyright
on what you write. Everyone taking part is held to the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

[Apache-2.0](LICENSE). The [NOTICE](NOTICE) file separates the free code from the defended
brand. Security reports: see [SECURITY.md](SECURITY.md). Contributions: [CONTRIBUTING.md](CONTRIBUTING.md).
