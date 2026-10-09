# OpenFactory

**An autonomous software factory.** It takes tickets from your board and returns reviewed pull
requests — planned, implemented, validated by *your* test suite, independently reviewed, and
merged under the policy you chose. Humans stop authorising every step and start evaluating
results; production stays behind a human gate, always.

It is **not a coding agent** — it orchestrates the ones you already use behind one adapter
contract. It is **not a SaaS** — it runs on your machines, against your board, with your
credentials, and no cloud account is required.

[Website](https://openfactory.digital) ·
[Source](https://github.com/Open-Factory-Digital/openfactory-core) ·
[What works today](https://github.com/Open-Factory-Digital/openfactory-core/blob/main/docs/STATUS.md) ·
[Releases](https://github.com/Open-Factory-Digital/openfactory-core/releases)

## One machine, from PyPI

Your own repository and the coding agent you already pay for: **one credential, no Docker, no
account anywhere**. The factory branches from your repository, opens a pull request in it, reviews
the change and fast-forwards your base.

Prerequisites: git, Python 3.12+, and a coding agent's CLI on your PATH, already signed in
(`claude`, `codex` or `opencode` — the coding agents, below, say where each one stands).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install 'openfactory[runtime]'            # the durable engine's worker runs on the extra

openfactory init                              # the defaults: your code and your tickets live HERE
openfactory project init myapp ~/code/myapp   # a path registers as itself — no owner, no board
openfactory doctor myapp                      # on this door, green IS the prerequisite list
openfactory box prove myapp                   # nothing is picked up until this is green
openfactory up                                # the panel, the worker and the durable engine
```

`init` answered with its defaults writes `~/.openfactory/env` and asks for no credential at all:
the harness signs in as you, with the login it already has. `project init` scaffolds
`.openfactory/project.yaml` in your repository — commit it on your base branch, because that file
is what the factory reads to know how to build and check your project.

`up` serves the panel at `http://localhost:8787` — the Board, the job, the pull request. It starts
the durable engine only when the `temporal` binary is on your PATH as well, and names whatever is
missing. Without the engine everything attended still works — the panel, and
`openfactory poll myapp`, which takes what is in TO-DO one card at a time — and what waits for it
is the human merge gate, park/resume and every deadline.

The whole door, including what happens to your working tree when a merge lands, is
[docs/setup/one-machine.md](https://github.com/Open-Factory-Digital/openfactory-core/blob/main/docs/setup/one-machine.md).

## A team deployment, with Docker

The other door: the compose stack, a real forge and a real board, several people watching the same
panel. **Docker, and only Docker** on the host — no Python, no `sudo`, one line:

```bash
curl -fsSL https://openfactory.digital/install.sh | sh
```

The installer resolves the newest release, checks the release's files against their published
checksums, pulls the published images (`ghcr.io/open-factory-digital/openfactory-worker`,
`openfactory-sandbox` and `openfactory-cli`, pinned to that release) and starts the stack. It
sends nothing anywhere; there is no telemetry in this project.

**Two credentials are irreducible for a real ticket** — the coding agent's
(`CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`, or `ANTHROPIC_API_KEY`) and a forge
credential (a PAT to try things out, a GitHub App for real use). `openfactory preflight` says what
is still missing, one line each with a remedy. Register a project inside the worker:

```bash
cd openfactory && docker compose --env-file .env.compose exec worker \
  openfactory project init myapp https://github.com/<owner>/myapp.git
```

**Upgrading** is the same installer with `--force` (and the same `--dir`, if you gave one): it
resolves the newest release, pulls it and restarts the stack. Every value in your `.env.compose`
survives, credentials included, and only the pinned version moves. Your data lives in named
volumes, which only `--uninstall` removes.

```bash
curl -fsSL https://openfactory.digital/install.sh | sh -s -- --force
```

The guided first hour on your own codebase is
[docs/ONBOARDING.md](https://github.com/Open-Factory-Digital/openfactory-core/blob/main/docs/ONBOARDING.md).

## The coding agents

One adapter contract, chosen per project and per role in the registry (`harness:`), and so is the
model each one runs.

| agent | `harness:` | where it stands |
|---|---|---|
| Claude Code | `claude_code` | the default |
| Codex | `codex` | has completed real tickets; its plumbing is not at parity yet (no credential pool, no durable resume across containers) |
| OpenCode | `opencode` | proven end to end; one binary that reaches several model providers, so the provider is a `model:` |
| Kimi Code | `kimi` | **does not run yet** — the adapter is wired and `kimi-code` refuses the way it is started ([#362](https://github.com/Open-Factory-Digital/openfactory-core/issues/362)) |

## Optional extras

| extra | what it adds | without it |
|---|---|---|
| `openfactory[runtime]` | the durable engine's client library, which the worker runs on | `run`, `poll` and the panel work; the merge gate, park/resume and the deadlines wait for it |
| `openfactory[ingest]` | the product role reads the PDFs in a product's context repository (their text layer; scanned ones need `tesseract` and `pdftoppm` on the machine) | every PDF is recorded as unreadable, by name, and everything else is read |
| `openfactory[embed]` | the product's memory index searches by meaning, with a model in a folder on your machine — nothing is downloaded | the index answers by exact words, metadata and date, and every search says so |

## Why this one

- **Policies authorise, humans evaluate.** The manifest declares the merge policy, the quality
  floor and the promotion chain; a project with no declared test command is *held*, not "passed".
- **The box is proven before money is spent.** `openfactory box prove` runs your own `setup:` and
  `validate:` inside the real sandbox before any ticket is picked up.
- **Every stall speaks.** A blocked job parks with executable options for a human; a silent
  forever-wait is treated as the platform's own defect.
- **Provider axes, not provider lock-in.** Tracker, board, forge, CI observer, notifier, coding
  agent and sandbox are independent adapters — GitHub Issues and Projects, Jira, Azure DevOps, or
  the local rows that need no account — chosen per project.
- **An independent review, structurally.** The reviewer can run on a different engine from the
  executor, so "you did not write this code" is true by construction.
- **Honest docs.** What does not work is written down before you decide anything.

## Documentation

- [The documentation map](https://github.com/Open-Factory-Digital/openfactory-core/blob/main/docs/README.md),
  and [every command](https://github.com/Open-Factory-Digital/openfactory-core/blob/main/docs/reference/cli.md)
- [What works today, and what does not](https://github.com/Open-Factory-Digital/openfactory-core/blob/main/docs/STATUS.md)
- [Releases and their notes](https://github.com/Open-Factory-Digital/openfactory-core/releases)
- [Security policy](https://github.com/Open-Factory-Digital/openfactory-core/blob/main/SECURITY.md) — report a vulnerability privately, never in a public issue
- [Contributing](https://github.com/Open-Factory-Digital/openfactory-core/blob/main/CONTRIBUTING.md)
- Licence: [Apache-2.0](https://github.com/Open-Factory-Digital/openfactory-core/blob/main/LICENSE);
  the [NOTICE](https://github.com/Open-Factory-Digital/openfactory-core/blob/main/NOTICE) separates
  the free code from the defended brand
