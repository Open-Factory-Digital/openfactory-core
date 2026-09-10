# One machine, and nothing else

The shortest way to see this platform work: your own repository, your terminal, and the coding
agent you already pay for. No account at GitHub or Jira, no personal access token, no Docker, no
server. The factory writes a branch, opens a pull request **in your repository**, reviews it, and
fast-forwards your base when you say so — all on the machine you are sitting at.

The other door — Docker, a hosted forge, a board at your vendor — is [the GitHub
guide](github.md), and nothing here forecloses it: the same install runs both, and a project
registered one way does not disturb a project registered the other.

## What you need

| | |
|---|---|
| a git repository with at least one commit | the factory branches from it and merges back into it |
| Python 3.12+ | the platform itself |
| a coding agent on your PATH, signed in | `claude`, `codex`, `kimi` or `opencode` — **the one credential you cannot postpone** |

That last row is the whole list of credentials. The harness signs in as **you**, with the login it
already has on this machine, and nothing else here asks for a token.

## Install

```bash
git clone https://github.com/Open-Factory-Digital/openfactory-core.git && cd openfactory-core
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
openfactory init          # press Enter twice: your code and your tickets live HERE
```

`init` writes a file for this deployment. Answered with its defaults it asks for no credential at
all — the two axes read `local`, and the file says in words what that means.

## Register your repository

```bash
openfactory project init myapp ~/code/myapp
```

A filesystem path registers as itself: the forge is your own repository, the board is a file
beside the registry, and there is no CI to observe. The command scaffolds
`.openfactory/project.yaml` — **commit it on your base branch**, because that file is what the
factory reads to know how to build and check your project.

Then check the machine:

```bash
openfactory doctor myapp
```

On this door a green report is the whole prerequisite list: no container runtime is needed, no
token is missing, and the agent's credential is the login you already have.

## Write a card and run it

```bash
openfactory act card_create -p myapp -P title="Add a health endpoint" -P body="## Objective
Serve 200 at /health

## Acceptance criteria
- GET /health returns 200
- a test covers it"

openfactory act card_move -p myapp -i 1 -P column=TO-DO
openfactory poll myapp
```

`poll` takes what is in TO-DO, one card at a time. The card walks the columns as the job moves —
In progress while the agent works, In review when the pull request is open, **Done** when the merge
lands and nothing follows it.

The panel shows the same thing in a browser, including the Board and the pull request:

```bash
openfactory panel        # http://localhost:8787
```

## What happens to your working tree

Nothing you did not ask for. The job runs in a git worktree of its own; your checkout is only
touched by the fast-forward itself, and only when it is safe:

- **an unrelated edit of yours** — the merge lands and your edit stays;
- **an edit over the same lines** — the merge is refused, in git's own words, on the card. Your
  file is exactly as you left it and the pull request stays open;
- **a base you have checked out somewhere else** — refused for the same reason, by name.

## What this door does not do

- **Nothing is hosted, so nothing is shared.** The board, the pull requests and the journal live in
  files on this machine. A second person cannot see them without the other door.
- **No CI is observed**, because there is none to observe: the manifest's `validate:` commands are
  the gate, and they run in the box before the pull request is opened.
- **The agent still reaches its own endpoint.** That is the product: the model runs remotely and
  you pay for it. Everything else stays here.

When you outgrow it, [the GitHub guide](github.md) is the same platform with the hosted axes
switched on — and `docs/ONBOARDING.md` is the long walk through both.
