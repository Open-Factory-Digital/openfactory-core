# Bringing up an OpenFactory

You have cloned the repository (or installed the package) and you have a codebase you want the
factory to work on. This document is that first session, in order — and a map of what becomes
YOURS at each step, because this is a tool for somebody who already ships with AI every day and
now wants to stop typing the code themselves: you will want to know where the prompts live,
where the model is chosen, and how the factory learns your product. All of that is below, at
the step where it becomes real.

| the moment | where | what you own after it |
|---|---|---|
| the deployment's environment | §0 | `.env.compose` — your vendors' rows and nothing else |
| the one credential you cannot postpone | §1 | the coding agent authenticated — a checkpoint, not a new task |
| the project | §2 | a registered project, its board, `doctor` green-or-named |
| **your stack** | §3 | `.openfactory/project.yaml` — how to build and validate YOUR code |
| **your context** (the backfill) | §4 | the documents that say what the product IS |
| the proof | §5–§7 | the box proven, one composed verdict, a costed rehearsal |
| the first ticket | §8 | a reviewed pull request |
| the product role | §9 | requirements as reviewed documents, a human release gate |
| **your shape** — mono or multi-repo | §10 | back + front + e2e, nothing forced |
| **your agents and models** | §11 | the role prompts, the guidelines, `set-model` |
| **who merges** | §11b | `merge_policy`, and the conditions `auto` actually checks |
| **your surfaces** — logs, secrets, boxes | §12 | where everything is, free, with no account anywhere |
| **after the merge** — deploys, stages, who approves | §13 | `environments`, `promote`, `post_merge_deploy` — or the silence you chose |

> **What this document assumes about you: nothing about infrastructure.** No cloud account, no
> deployed anything, no credential somebody else holds. Every command below runs on a laptop and
> tells you what it could not do and why. When a step needs a credential, it is named at that
> step.
>
> **And the factory itself needs no laptop at all.** Once it is running — on this machine, a
> server, a cluster — taking a card, cloning your repository, writing code, running your gates
> and opening the pull request happens entirely there. The one authoring step that still wants a
> checkout on some machine (any machine: a laptop, a CI runner, a jump host) is §3, and §3 says
> why.

**It is not a config file, it is a session.** Most codebases a team wants automated are not
greenfield — they are years old, the person who named the modules has left, and the real test
command is one of four that only work on somebody's machine. So the platform's job in this hour
is to **propose and be corrected**, not to interrogate you. Read each report with the developers
who know the repository in the room; the questions it cannot answer are the agenda.

Nothing below writes to your repository without `--yes` — with one named exception:
`project init` scaffolds a starter manifest into a LOCAL checkout when none exists (it never
overwrites, and §3's session is the better way to get that file anyway).

---

## 0 · The floor

```bash
python3 --version         # 3.12 or newer — if yours is older, read the note below FIRST
docker --version          # the box a job runs in
git --version
gh --version              # GitHub deployments ONLY — Azure DevOps and Jira never need it
```

**The virtualenv must be built by a 3.12+ interpreter, and on many machines `python3` is not
one.** macOS with Homebrew and most Debian/Ubuntu images ship an older `python3`; a venv built
on it is created happily and fails four commands later, at `pip install`, with an error about a
version you thought you had just checked. The venv itself is not optional either: modern
pythons refuse a bare `pip install` (PEP 668), and the CLI lands in `.venv/bin/`.

So pick the interpreter deliberately — one of these three, whichever matches your machine:

```bash
python3 -m venv .venv          # if `python3 --version` above said 3.12 or newer
python3.13 -m venv .venv       # or whichever versioned binary you DO have (3.12 / 3.13 / 3.14)
uv venv --python 3.12 .venv    # or let uv fetch one — it installs the interpreter if missing
```

Then, whichever you used:

```bash
source .venv/bin/activate
python --version          # ← confirm 3.12+ HERE. This is the check that saves the next four commands
pip install -e '.[dev]'   # from a clone
openfactory --help
```

Nothing 3.12+ on the machine and no `uv`? `brew install python@3.12` (macOS) or your
distribution's package, then use that binary in the first block.

Give the stack its environment BEFORE starting it — compose bakes variables in at creation, so
a credential exported afterwards never reaches an already-created worker. Let the CLI write it:

```bash
openfactory init      # a few questions; writes .env.compose (0600) with YOUR rows, nothing else
```

It asks where the code lives, where the tickets live, how the factory signs in there, which
coding agent writes the code and how it is paid for, whether the tech-lead should ALSO speak in
a Slack channel (the panel always works), and whether the panel will be reachable beyond this
machine. Then it fills in what it can obtain on its own (on GitHub, your `gh` login; a panel
secret when exposed) and prints, in order, the credentials only you can fetch — the one you
cannot postpone first — each with the page or command that produces it. Every answer is also a
flag (`--forge`, `--harness`, …) for a scripted install; without a terminal it refuses naming
the flag rather than waiting for an answer nobody can give.

Two of its answers have their own walkthrough — open it when the printed list points you there:

- a **GitHub App** is [docs/setup/github.md](setup/github.md), every screen to the
  smoke test;
- an **Azure DevOps** deployment is [docs/setup/azure-devops.md](setup/azure-devops.md). Do its
  **§§1–4 now** (the PAT, the two board states, the work-item type); **§2 of this document will
  send you to its §5** (registration) once the stack below is up — two visits, and that is the
  honest itinerary.

Prefer to do it by hand? `cp .env.compose.example .env.compose` and read the comments — the
template carries the same recipes, plus the rows for the vendors you did not choose.

The whole stack runs locally — Postgres, the durable engine, the worker and the panel. Budget
**~8 GB of disk**: the worker image carries all three harness CLIs and a Node runtime, plus the
box image.

```bash
docker compose --env-file .env.compose up -d --build
```

> **`--env-file .env.compose`, never `.env`, and it is not a style preference.** Docker Compose
> reads `.env` from the working directory automatically. On a machine that has ever run the CLI
> against a real deployment, that file holds live credentials — a client's App installation with
> write access to their repositories — and the local stack would inherit them. `--env-file`
> replaces `.env` outright, so the stack sees only what you meant to give it.

Seven containers come up; two of them build and exit on purpose (`base-image` and
`sandbox-image` produce the box your jobs run in — before that existed, the stack came up green
and every job died on "image not found", one layer away from its cause).

> **Updating later — `--build`, always.** The platform's code is **baked into the worker
> image**, not mounted from your checkout. So `git pull` changes your disk and nothing else:
> `docker compose … up -d` restarts the PREVIOUS build, and every command inside the worker
> keeps answering from it, identically, with no sign that anything is stale. The whole update
> is one line:
>
> ```bash
> git pull && docker compose --env-file .env.compose up -d --build
> ```
>
> Your registered projects, journals and proofs live in a named volume and survive it. To check
> which code actually answered, `openfactory doctor <project>` opens with the build it is
> running and when that build was made.

Then open http://localhost:8787 in a browser — the panel, the product's reference surface
(http://localhost:8080 is the durable engine's own UI, useful for debugging). On a fresh
install the panel is an **empty floor** with "+ New project" — that is correct; §2 fills it.

> **One extra line on Linux hosts — skip this on macOS and Windows.**
>
> ```bash
> sudo mkdir -p /var/lib/openfactory-work && sudo chown $(whoami) /var/lib/openfactory-work
> ```
>
> That directory is where a job's files live while it runs. It has to be a real directory on
> the host — not a Docker volume — because the worker and the container it launches for the job
> are siblings on the same Docker daemon, and both must find the workspace at the *same path*.
> Skip the line and Docker auto-creates it **owned by root** — the stack still starts, and the
> ownership surprises you later (and rootless Docker cannot auto-create it at all). Docker
> Desktop creates it inside its own VM automatically, which is why macOS and Windows have
> nothing to do here.

**Commands run in two places, and every step from here on tells you which.** Some run against
the stack you just started; some run on your laptop, against your own checkout. When a step
says *"Runs on: the WORKER"*, it means this prefix:

```bash
docker compose --env-file .env.compose exec worker openfactory <command>
```

When it says *"Runs on: your LAPTOP"*, type the command plain. That is the whole rule — §2
explains what goes wrong if you mix them up, at the moment it can.

Everything so far ran on your own machine, and it stays that way: no cloud account is required,
now or later. Running this on AWS, Azure or a Kubernetes cluster is supported and is a choice
you make later, never a prerequisite.

---

## 1 · One credential, and what it buys — a checkpoint, not a new task

The platform runs a **coding agent** in a sandbox. That agent's credential is the only one you
cannot postpone — which is why `openfactory init` already asked about it in §0 and put it at the
top of your "still yours to do" list. If you filled that list, there is nothing to do here.

If the row is still empty: fill it now (subscription: `CLAUDE_CODE_OAUTH_TOKEN` from
`claude setup-token`; or `ANTHROPIC_API_KEY`) and **recreate** the stack with `--env-file` as in
§0 — compose bakes the environment in at container creation, so editing the file alone changes
nothing.

Four agents are supported behind one contract (`claude_code`, `codex`, `kimi`, `opencode`) and the
choice is a value in your registry entry, not a code change — and so is **which model** each one
runs (§11). If your security team requires model traffic to stay inside your own cloud account,
that is a route setting — same binary, same build.

Everything else — a forge token, a board, a Slack workspace — is needed only for the parts of the
loop you actually turn on, and each is named at the step that needs it.

---

## 2 · Register the project

**Runs on: the WORKER** — the §0 prefix, and here is why it matters: the list of projects lives
*inside* the stack, and the laptop CLI keeps a separate list of its own. Register only on the
laptop and the factory never sees the project; nothing errors, no ticket is ever picked up, and
there is nothing to read that would tell you why. (You will also register a laptop copy further
down, for §3 — different list, different job.)

On **GitHub**, one command registers the project, creates the board with the platform's
columns, and points at the manifest step:

```bash
docker compose --env-file .env.compose exec worker \
  openfactory project init myapp https://github.com/<owner>/myapp.git
# <owner> = your organisation or your username — both work
# --language pt-BR  · the human-facing voices speak English unless you name another
```

**The URL is only for the first time.** This command CONVERGES: each half runs only if its
result is missing, so if one half fails — the board, typically, when a credential is not in
place yet — you fix that and re-run with the name alone:

```bash
docker compose --env-file .env.compose exec worker openfactory project init myapp
```

It says what it skipped (`· myapp is already registered`) and does what is left.

(`project add` is the variant when you already have a board — attach it with
`--board-owner`/`--board-number`, GitHub Projects coordinates — or want no board at all: the
factory still works, you just name tickets directly. On **Azure DevOps**, register with your
`dev.azure.com` clone URL instead — it carries the organisation/project/repository, and Azure
Boards ships with the project, so there is no board to create:
[docs/setup/azure-devops.md](setup/azure-devops.md) §5 is that step.)

**The board's columns are the platform's vocabulary**: six on GitHub Projects
(`Backlog · TO-DO · In progress · In review · Needs Action · Done` — created for you, in that
order, by the command above), five states on Azure Boards (the guide's §3 table). Already have
a board, or want to build one by hand? [docs/setup/github.md](setup/github.md) §7.

**The forge credential.** The first real ticket (§8) needs the factory to write to your
repository. On the token path, `openfactory init` already wrote the `OPENFACTORY_BOT_TOKEN`
row. On the App path it wrote the App trio — and on a **personal account** the board
additionally needs the classic PAT in `OPENFACTORY_TRACKER_TOKEN`
([github.md](setup/github.md) §6): that is the token the board creation above uses. On
Azure DevOps, the PAT from the guide's §1 is the whole story — there is no App equivalent.

Registering a project does **not** release it to pick up work. It cannot: the box has not been
proven yet, and §5 is what changes that.

Close the step with the diagnostic — now it has something to diagnose:

```bash
docker compose --env-file .env.compose exec worker openfactory doctor <project>
```

One line per check, each with its remedy — the agent credential, the forge credential and the
box proof included. It is the cheapest failure in the whole sequence; run it before anything
that costs more.

**It will say NOT ready here, and that is the correct answer.** Everything derived from
`.openfactory/project.yaml` — `manifest`, `quality_floor`, `merge_policy`, `post_merge`,
`ci_declared` — is red because §3 has not written that file yet, and `box_proof` is red because
§5 is what proves the box. What must be green at THIS point is everything registration can
settle: docker, the harness, the agent credential, forge access and the board's columns. The
command says so when those are the only red lines, and it names the next step rather than a
generic one — it is the same command you run after §3 and after §5, and it is what tells you
when you are actually ready.

**`api_budget` may be red here too, and it is in the same category.** It reports how much of
your tracker's API quota the board reads can still spend — a safety net for the poller, which
pauses pickups before the quota runs out. Until §5 releases pickup, nothing is scanning your
board and nothing is spending it, so a quota this machine cannot read is a fact about a step you
have not reached and the command says so. It becomes a real finding once the box is proven: at
that point the poller IS reading your board, and a budget nobody can read is a safety net that
is off. (A tracker that publishes no quota at all — Jira, Azure Boards — reads green and always
will; there is nothing to pause on.)

**`box_proof` is the check that decides whether work is picked up at all**, and it asks the
poller's own question rather than a second version of it: whatever it says here is exactly what
would hold a card in the pickup column.

---

## 3 · Your STACK: let it read the repository, then correct it

This is the step that matters on a codebase nobody documented — where the factory learns how to
**build and validate** your code, whatever the stack.

**Three different things get written for three different readers, and mixing them up is the
usual confusion.** This step is only the first:

| | what it says | who reads it | where it lives |
|---|---|---|---|
| **the manifest** — `.openfactory/project.yaml` | how to install and validate: `setup:`, `validate:`, the base branch, the merge policy | the platform, on every ticket | your repository — **this step** |
| **the context** — requirements, glossary, invariants | what the product *is* and *promises* | the product role (§4, §9) | the context repository |
| **the module map** — `knowledge/` | where things live in the code, so an agent jumps instead of hunting | the coding agents | your repository, generated |

The manifest is the same shape for Python, .NET, TypeScript or Terraform, because the platform
runs the commands **you** declare and reads their exit codes — it knows no stack. Roughly:

```yaml
setup:
  - "uv sync"                              # how to get a working toolchain
validate:
  test: "uv run pytest tests/unit -q"      # how to know the code is good — no default exists
  security: "bandit -r . -ll -q"
base_branch: main
merge_policy: human
```

The **module map** is not yours to write: it is parsed from the code with no model call and no
token cost, refreshed automatically after every merge, and left one merge behind rather than
ever failing a job. `knowledge_map: true` is the default the manifest above carries, so this
step is where it gets switched ON.

### The recommended path: one command, everything above, MEASURED

**Runs on: the WORKER.** The factory does the whole first-time setup itself — and instead of
proposing a manifest it merely *read*, it **proves** it: the proposed `setup:` and `validate:`
are executed inside the real box (the same container your tickets will use, streamed live)
before the proposal ever reaches you.

```bash
docker compose --env-file .env.compose exec worker \
  openfactory onboard myapp --yes
```

Per repository it opens **one pull request** carrying the manifest AND the module map, with
the proof's verdict in the body — "your proposed test command ran green in the box", or
exactly what failed — plus the questions only your team can answer. It also creates-or-uses
the context repository and proposes the backfill (§4's work) in the same run. A repository
that already declares its manifest is proven as-is, and only what is missing is proposed.

**Running it again is safe, and sometimes it is exactly what you want.** An open proposal is
FOUND, never duplicated — no second pull request, no second branch — and the box is re-proven
on the way, so a proof that failed for a reason you have since fixed (a missing tool, a
credential) clears without any other command. What re-running does not do is merge: that is
the next step, and it is yours.

### Then YOUR step: review and merge

**The factory never merges its own proposals, and that is the design, not a limitation.** The
manifest declares what this platform will run against your repository — the install commands,
the gates it reads exit codes from, the merge policy. Somebody who knows the codebase reading
that *before it is true* is the entire reason it arrives as a pull request instead of a commit.
The same holds for the module map and for the context backfill.

So nothing further happens until you merge, and the platform says so by name: **`openfactory
doctor <project>` reports the manifest as PROPOSED, with the pull request's link**, and keeps
reporting it until the merge lands. What to look at while reviewing:

- `validate.test` — the one field with no safe default. A command that exits 0 having tested
  nothing is worse than none at all;
- `setup:` — the proof in the PR body says whether it ran green in the box;
- the questions in the body: they are the ones nothing in the repository could answer.

**A pipeline you switched off is not proposed as a gate.** On disk a retired workflow is
byte-identical to a living one, so reading files alone cannot tell them apart — but `onboard` has
your forge and asks it which CI definitions are disabled (GitHub workflow `state`, Azure Pipelines
`queueStatus`). A command found only in a disabled file is not written into the manifest; it
becomes a question naming the file and its state, so re-adopting it stays your decision. If
another, living pipeline offers the same command, that one is taken and the swap is stated.

If your forge cannot answer — a provider without the read, a credential without the scope —
nothing is demoted and every command is taken at face value, which is exactly the behaviour that
existed before. "Could not find out" is never treated as "nothing is disabled".

Correct anything wrong in the pull request itself, then merge. Re-run `doctor` after it — it is
the same command all the way through, and it is what tells you when a ticket can run.

A product that spans repositories — front and back, say — names them once:

```bash
docker compose --env-file .env.compose exec worker \
  openfactory onboard myapp --source <owner>/web --source <owner>/api --yes
```

Each repository gets its own manifest, its own proof, its own map, its own pull request —
which is exactly how the runtime treats them (§10).

### The manual session — when the developers are in the room

`onboard` reads the repository; it cannot ask the person who knows it. When you have a
checkout and the people, this is the richer form of the same step — it shows every field WITH
the file and line it was read from, and lets the room correct it before anything is written:

**Runs on: your LAPTOP**, against your own checkout — the worker cannot see your filesystem,
and this session belongs in a room with the developers anyway.

```bash
openfactory env read ~/Projects/myapp     # LAPTOP — no docker prefix, just the path
```

**Why here and not in the stack:** the manifest is YOUR repository's file. It is written into
your checkout, read in your diff, and committed by you — the worker's copy of the repository is
a disposable cache, and a file written there would be reviewed by nobody and replaced by the
next fetch.

**No checkout anywhere?** That is the normal case for a project **registered by clone URL** —
the §2 shape, where you handed the factory a URL and it clones the code itself, so there is no
checkout on your laptop for `env read` to read. For that shape, `onboard` above IS this step.
The narrower worker-side form still exists when you only want to set one field without the
box run:

```bash
docker compose --env-file .env.compose exec worker \
  openfactory env apply myapp --yes --pr --set validate.test="<the real command>"
```

It clones the repository, proposes the manifest, and opens a **pull request** on
`openfactory/manifest` for you to correct and merge — the same review the local path gets from
your diff, in the place a team without a laptop in the loop can actually do it. Re-running is
safe: an existing proposal is found rather than duplicated.

It writes nothing. It reports every field it could work out, **with the file and line it read it
from and how sure it is**, in three blocks:

| block | what it means for you |
|---|---|
| `PROPOSED` | read out of your repository. Check it, it is usually right |
| `INFERRED` | a guess from your CI file. *"Right, or what is the real one?"* |
| `ONLY YOUR DEVELOPERS CAN ANSWER` | nothing in the repository decides these — **this is the agenda** |

It also names what it could not read at all, and what the platform's own schema cannot express
about your stack. Those are our gaps, stated as ours.

When the room agrees, write it — same machine, same path, and then you COMMIT the file, which
is how it reaches the worker's clones:

```bash
openfactory env apply ~/Projects/myapp --yes                          # the observed fields
openfactory env apply ~/Projects/myapp --yes --accept validate.test   # take an inferred one as-is
openfactory env apply ~/Projects/myapp --yes --set validate.test="<the real command>"
```

That produces `.openfactory/project.yaml` in **your** repository. Commit it — the sandbox clones the
repository fresh, so the manifest has to be on the branch. The one field with no default is
`test`: there is no command that runs every project's tests, and a guessed one that exits 0
having tested nothing is worse than none.

A repository that holds MORE than one stack — back-end and front-end side by side — declares
`components:` with a path each; a product split ACROSS repositories registers once and routes
by card. Both shapes are first-class and neither is forced: **§10**.

### The module map — STRONGLY recommended, and it is not the backfill

Two artefacts sound alike and are not. The **backfill** (§4) is prose about what the product
IS — written once, reviewed by humans, read by the product role. The **module map**
(`knowledge/modules.yaml`) is an index of where things LIVE in the code — parsed
deterministically, zero model calls, zero token cost, refreshed after every merge — and it is
what lets a coding agent jump to the right module instead of spending its first minutes (and
your tokens) hunting. Every project should have one before its first real ticket; without it
the first ticket still works, it just pays an exploring tax the map exists to remove.

If you ran `onboard`, the map is already in that pull request — merging it is this step.
Otherwise, one command, in the form matching how the project is registered:

```bash
# registered by a local path — writes into the checkout; commit it like any file:
openfactory knowledge build myapp

# registered by clone URL — the factory's own clone is disposable, so publish it
# to the repository's knowledge branch, where jobs actually read it:
docker compose --env-file .env.compose exec worker \
  openfactory knowledge build myapp --publish
```

From then on it maintains itself: every merge refreshes it, and a refresh that fails leaves
the map one merge behind rather than ever failing a job.

---

## 4 · Your CONTEXT: create it or reuse it — the backfill

§3 settled how to *build* the project. This step is where the factory learns what the product
**IS** — its vocabulary, its entry points, the rules it enforces, the questions only somebody
who worked there can answer. Two halves: WHERE that knowledge lives, and the **backfill** that
writes the first version of it from your code.

**If you ran `onboard` (§3), this step already happened on the worker**: it used the context
repository you declared or created one (both cases below), ran the backfill there, and opened
a pull request carrying the declaration and the documents — the PR body says which backfill
mode ran and why. (A context repository born EMPTY — typically one just created — gets them
as its **first commit on the base branch** instead: no pull request can target a base with no
commits, and the command says so in those words.) Review and merge it, then read on only for what the documents mean and the
`docs:` wiring at the end of this section. The rest of this section is the LAPTOP form of the
same work, for when you want the room in the loop:

**Runs on: your LAPTOP** — `--ask` runs the coding agent on this machine (it needs the harness
CLI on PATH, beside your checkout).

**First, the place. Two cases:**

- **You already keep a documentation / context repository** — it is USED, not replaced.
  Declare it (**runs on: the WORKER**):

  ```bash
  docker compose --env-file .env.compose exec worker \
    openfactory product declare myapp <owner>/docs-repo
  ```

  From then on `onboard` (or §9's `openfactory product init myapp --write`) clones it, reads
  what is there, and proposes the declaration as a pull request on it. On Azure DevOps it may
  live in a different project of the same organisation — qualify it
  (`SharedDocs/product-context`) and every step follows the qualifier.
- **You do not** — `onboard` (§3) creates it for you, in your own organisation, and records it;
  `openfactory product init myapp --create-context --write` is the same act on its own. One
  command, GitHub or Azure Repos.
- **You do not, AND your company does not let a bot create repositories** — the normal
  enterprise shape, and it is fully supported: create it however your company does (the portal,
  your provisioning process), then declare it with the command above. When the factory's
  credential is refused, that is exactly what it tells you to do — the provider's own refusal
  stays visible as the diagnosis, and the way forward is named. Nothing else about the
  onboarding changes.

**Declared is not the same as reachable, so `declare` reads it back** — with both credentials
that will ever open it (the onboarding one and the product role's own, which on some GitHub
setups are different). A name with a typo, an Azure qualifier pointing at the wrong project, or
a repository outside a GitHub App installation's selection all record perfectly and then go
silent hours later. The command says so while you are still watching, and the declaration
stands — fix the access, nothing needs re-declaring.

A deployment normally has BOTH kinds of project at once; the difference is one flag, and the
command says whether it created a repository or found one. Until §9, writing the backfill into
any local folder is fine for reading it.

**And then the one line the platform will NOT write for you.** The declaration goes both ways:
the context repository lists the code it serves (`sources:`, proposed for you in that pull
request), and each SOURCE repository says where its requirements live. That second half is one
top-level line in the source repo's own `.openfactory/project.yaml`:

```yaml
docs_repo: <owner>/<product>-context      # top level, beside `setup:` and `validate:`
```

Commit it on the base branch — the factory reads the repository, not your laptop, so any route
that lands it there is fine. It is deliberately yours rather than proposed with the rest: a
source repository that could point itself at any documentation repository is a client-isolation
breach, so the platform refuses to write the pointer that redirects it. `openfactory onboard`
prints this as a named todo with the exact value; until it is committed the module still works
for your deployment, and anyone else cloning the repository has no way to find its requirements.

**Then, the backfill:**

```bash
openfactory env context ~/Projects/myapp                       # deterministic, spends nothing
openfactory env context ~/Projects/myapp --ask                 # + ONE read-only agent pass
openfactory env context ~/Projects/myapp --write ~/ctx --yes   # write the documents
```

It produces five documents — a survey, an architecture overview, a glossary, the invariants,
and the open questions (named in the project's language — with `--language pt-BR`,
`docs/levantamento.md`,
`docs/arquitetura/visao-geral.md`, `docs/glossario.md`, `docs/invariantes.md`,
`docs/perguntas-abertas.md`; an English layout is adopted automatically when the target
directory already uses one). With `--ask`, every sentence the agent produces must carry a
`file:line` that is **checked against your filesystem before it is allowed to exist** — a claim
whose citation does not resolve is demoted into a question carrying both, so you can tell a
wrong belief from a mistyped path.

**It also reads your repository's own history**, and that is a separate input from the code: which
files the last year of work actually landed on, how many people touched each, and which work items
are named in those commits. It reaches the survey and the agent's evidence as *"where the work
actually lands"*, and the **module table is ordered by how much each module changes** rather than by
how big it is — on a long-lived codebase the biggest module is routinely the one nobody has opened
in years, and that table is capped, so its order decides which modules you ever see. Which ordering
is in force is printed above it.

Crossing the two gives you the section worth reading first: **areas that change and that no test
names**. Both halves were always in the survey and nothing joined them, so the most-changed
undefended part of a codebase read exactly like its quietest. Naming is not covering — this says
nobody could find those tests by looking, not that the code is unexercised — and the section says so
itself.

Reading a log needs more than one commit, so `openfactory onboard` clones for history on purpose.
**A checkout that cannot answer says so by name** rather than reporting a repository that never
changes — point `env context` at a shallow clone and it prints exactly that, with the rest of the
survey unaffected.

Three facts about `--write`, so it never surprises you: it writes into a plain directory
(point it at a **checkout of the context repository** — it does not clone, create or verify
one); it **never commits or pushes** — reviewing the diff and pushing is deliberately yours;
and it **never overwrites** — an existing document is kept, so re-running refreshes nothing.

**The sentence that saves you an afternoon:** the context repository feeds the **product
role** (§9) — requirements, glossary, domain facts. The **coding agents** read only what your
SOURCE repository's manifest points them at: `docs.constraints` (ADRs — always loaded),
`docs.architecture`, `docs.guidelines`. If you want the executor to see the backfill's
invariants or overview, commit them (or a copy) in the source repo and name them there —
`.openfactory/project.yaml`:

```yaml
docs:
  constraints: docs/adr/**
  architecture: docs/arquitetura/**
  guidelines: [docs/invariantes.md]
```

---

## 5 · Prove the box — and watch it

Nothing is picked up until the box is proven. The box is your image, your dependencies, your
gates. **Runs on: the WORKER** for the compose deployment (its Docker, its volumes):

```bash
openfactory box prove myapp
```

It resolves the image to a digest, checks the agent toolbox can execute inside it, then runs your
own `setup:` and your own `validate:` against untouched `main` — **streaming each line as it
happens**. Green means *your tests passed inside the factory*, and it costs zero agent tokens.

**If you ran `onboard`, each repository was already proven** — that is the verdict in each
pull request's body — and the proof was saved, so a green onboard means this step is done.
Note the freshness contract below still applies: if the reviewer edits `setup:`/`validate:`
before merging, the commands' hash changes and the proof expires with it — re-prove after
merging in that case.

The result is a fact with a lifetime, not a checkbox: it expires when the world it was taken
against moves — your `setup:` or `validate:` change, the harness toolbox changes, or the box image
changes **in a way your commands can feel**. `openfactory box status myapp` says what changed, and
the panel carries the same verdict beside every project.

> **Updating the platform does NOT expire your proof, and that is worth knowing before you update
> often.** A local install builds its own box image, so every `up -d --build` gives it a new
> content id — including builds that carry nothing but a newer version of OpenFactory. What your
> commands actually depend on is the TOOLCHAIN, so the image writes it down and the proof records
> it: python, node, git, gh, uv and the OS. Same toolchain after a rebuild → the proof stands, no
> hold, no re-prove. `box status` prints exactly what it is pinned to:
>
> ```
> podbeam: proven at 2026-08-15T20:56 on openfactory-python:sandbox (sha256:3a3e990bff79…)
>   toolchain os="debian 13" · python=Python 3.12.14 · node=v20.19.2 · git=git version 2.47.3 …
>   a rebuild that leaves these unchanged does NOT expire this proof
> ```
>
> A box image that carries no such line — your own toolbox image, for instance — has only its
> digest to compare, so any rebuild of it does expire the proof. `box status` says which case you
> are in.

### When the proof fails on a command you need to CHANGE

This is a normal step, not a detour — the first proof is often what shows a declared command
does not fit the box (the pilot's first: an install read from a CI job that runs in a
subdirectory, proposed at the root). **The manifest is your file, in your repository**: edit
`.openfactory/project.yaml`, commit to the base branch, and re-run the proof — it notices the
new commands by their hash and runs against them; nothing else needs re-declaring. When
choosing replacements, take lines your own CI already runs (that is where the proposal read
them from) rather than inventing new ones. The review ceremony is available when you want it —
`openfactory env apply <name> --yes --pr --set validate.test="…"` proposes the change as a
pull request instead — but a manifest already merged is yours to edit directly.

**One proof per repository.** A product that spans repositories (§10) proves each on its own
manifest — the default repository with the bare command above, every other one by name:

```bash
openfactory box prove myapp --repo <owner>/web
openfactory box status myapp --repo <owner>/web
```

A card on a repository whose box was never proven is **held, by name**, while cards on proven
repositories keep flowing — the hold message is exactly the command above.

---

## 6 · One verdict before anybody waits on it

**Runs on: the WORKER.**

```bash
openfactory env check myapp
```

One composed verdict — Docker, the agent's credential, the manifest, forge access, board columns, the quality floor,
the role prompts, the auth route — composed into a single answer, and it tells you **where it was
measured**: a laptop is not the machine that runs your tickets, and a credential can differ there.

Exit code 0 only when pickup is genuinely unblocked.

---

## 7 · The rehearsal

**Runs on: the WORKER.** The first round is about the **environment**, not about a ticket:

```bash
openfactory env rehearse myapp             # prints what it would cost, runs nothing
openfactory env rehearse myapp --yes       # the whole loop, for real
```

A box, an agent pass, a diff, your own gates and an independent reviewer — on a synthetic ticket
the platform owns, in a throwaway clone with every git remote removed. It touches no tracker, no
branch, no pull request and no board. When it fails it tells you **where a real ticket would have
died**.

If your test suite must not run on this machine (a fifteen-year-old suite that talks to a shared
database will truncate that database), say so and the round still runs:

```bash
openfactory env rehearse myapp --yes --no-gates
```

---

## 8 · The first real ticket

Write an issue with an **objective** and **acceptance criteria** — a ticket with neither is
refused by the spec gate before an agent is paid, and it says so on the card. Headings are
matched by meaning, English or Portuguese (`## Objetivo`, `## Critérios de aceite` work), and a
refusal names the headings it DID find:

```markdown
## Objective
Users can export their report as CSV.

## Acceptance criteria
- a `GET /reports/{id}/export` endpoint returns text/csv
- the export respects the report's current filters
```

Move it to the pickup column: **`TO-DO`** on the platform's GitHub board, **`To Do`** on Azure
Boards (each vendor's own spelling; `columns:` in the registry if yours differ).

The poller takes it from there. Watch it in the panel: spec → box → code → your gates → pull
request → an independent review by a *second* agent that never saw the author's reasoning.

`merge_policy: human` opens the pull request and waits. `auto` merges when the gates are green
and no high-risk component was touched; the independent review blocks an auto-merge only if you
set `review_mode: blocking` — by default it is **advisory** and lands as a comment on the
PR. Production promotion always requires a human action.

---

## 9 · The product role, when you bring a product owner

Everything above is the ENGINEERING loop. The product role — requirements written in a context
repository, a surface at `/product/<name>` on the panel for the person who owns WHAT gets built —
is switched on separately, and its whole chain (context repo, `openfactory product init`,
per-person product tokens, who may accept and release) is one page:
[docs/reference/product-role.md](reference/product-role.md).

Two honest notes from the live runs: `product init --create-context --write` creates the repo,
records it in the registry and opens the PR — the **source repo's** `docs_repo:` pointer is
printed as a todo, not written, so that one line is yours to commit. And a legacy corpus of
existing requirements is adopted with `openfactory product baseline` — everything it writes
arrives as `observed`, and a human flipping entries to `accepted` **is** the deliverable, not a
formality.

---

## 10 · Your SHAPE: one repo, many repos — nothing is forced

Back-end and front-end, with e2e that needs both? Both shapes below are first-class today;
pick the one your team already lives in.

**Monorepo** — one repository, `components:` with a path each. Diffs map back to components,
each can carry its own gates and `risk:` level, and a `risk: high` component stays human-gated
even on `merge_policy: auto`. Your e2e is simply a `validate:` command — everything is in one
checkout:

```yaml
components:
  api: { path: api/,  stack: python }
  web: { path: web/,  stack: node }
  infra: { path: terraform/, stack: terraform, risk: high }
```

**Multi-repo, one product** — register ONCE (the "main" repository is the default) and put all
the repos' cards on the same board. **The card carries its repository**: on GitHub Projects a
card IS an issue in a repo, and the factory follows it — clone, box, branch, PR, CI watch, all
against the card's repo (on Azure Boards the card's **Area Path** names the repo — leaf name by
default, or the `areas:` map in the guide's §7). Each repository carries its own manifest, so
each declares its own gates. Tickets named directly are qualified the same way:
`owner/web#123`. The product's membership is declared once, in the context repo's
`sources:` list (§9's `product init` infers it; add `--source` for the rest).

The whole first-time setup for this shape is the §3 command with the repositories named:

```bash
docker compose --env-file .env.compose exec worker \
  openfactory onboard myapp --source <owner>/web --source <owner>/api --yes
```

— one registration, one board, one context repository; per repository its own manifest, its
own box proof, its own module map, its own pull request. The proof gate is per repository too:
a card on a repo whose box was never proven is held by name (§5's `--repo` command is the
remedy) while every proven repo's cards keep flowing — front never waits on back's paperwork.

**e2e that needs BOTH repos** — the supported shape is an **e2e-labelled ticket**:
the factory does not implement it; it dispatches YOUR OWN e2e workflow (which may check out as
many repositories as it likes), watches the run, and reports pass/fail on the card. Declare
`e2e_label:` and `e2e_workflow:` in the manifest.

**Named limits, so you plan around them instead of discovering them:** merge ORDERING between
repositories does not exist — nothing stops a front-end card merging before the API it depends
on — it is designed and not built, so sequence dependent cards yourself with Backlog vs
TO-DO.
The one-job-at-a-time floor is **deployment-wide** (`OPENFACTORY_MAX_CONCURRENT_JOBS`, default
1), which incidentally serializes across repos today. Promotion chains (`promote:`) are per
repository.

---

## 11 · Your AGENTS: the prompts, the guidelines, the models

You already tune agents — here is exactly where this factory's live:

**Every job, every project** reads `openfactory/org_defaults/engineering.md` and `tdd.md` —
the deployment's engineering standards, injected into the coding agent's context ahead of the
project's own. Edit them and every job inherits it.

**Each role's prompt** is a file: `openfactory/org_defaults/roles/{executor, planner, sizer,
techlead, coordinator, recovery, product}.md`. (The independent REVIEWER deliberately has no
file here — its instructions live in the reviewer adapter, so a deployment cannot soften the
one voice that judges the work.)

> **The compose trap, same as §0's:** these files are **baked into the worker image**. Editing
> them changes nothing until `docker compose --env-file .env.compose up -d --build` rebuilds it
> — an edit that "did nothing" is a rebuild you skipped.

**Per project, additively**: the manifest's `docs.guidelines` (and per-component `guidelines:`)
append YOUR rules after the deployment's — a project can add, never silently remove, the
baseline. Each file is truncated at 8,000 characters. A named guideline missing from the
checkout, or a `docs.constraints`/`docs.architecture` glob matching nothing, logs one warning
and the agent runs without it — worth grepping the worker's log for `docs.` after a rename.

**The model each role runs** is a registry value with a CLI — no YAML editing inside the
worker:

```bash
docker compose --env-file .env.compose exec worker \
  openfactory project set-model myapp claude-fable-5                    # every role
docker compose --env-file .env.compose exec worker \
  openfactory project set-model myapp gpt-5 --role executor             # per role
```

(Also `project add --model` at registration.) The string is the harness's own — a Bedrock
inference profile ARN is a legitimate value — and takes effect on the next job; the registry is
read per run.

**The command asks your harness about the name, and answers in one of three ways.** It never
refuses: what you type is passed through verbatim, because the platform cannot know your route.

| what you see | what it means |
|---|---|
| nothing after the `✓` | the harness read the name and did not object |
| `⚠ the harness does not recognise …` | **a warning, not a verdict.** A typo looks exactly like a Bedrock inference-profile ARN or a gateway alias from here — both are names the harness's own catalogue has never heard of. Nothing is blocked |
| `· the model was not checked …` | it could not be asked (no CLI on this machine, a harness that has no such capability — `codex`, `kimi` and `opencode` do not — or one that would not start). **Not the same as approval**, which is why it is said out loud |

The authority is the first job either way: a model your harness will not run fails the ticket
naming that model and this command, rather than looking like an agent that produced nothing. One precedence warning: the `OPENFACTORY_*_MODEL` environment variables **beat**
the registry for the whole worker — a stale one in `.env.compose` silently overrides every
per-project choice.

---

## 11b · WHO MERGES: the decision is yours, the execution is the factory's

The default is `merge_policy: human` — every pull request waits for you. That is right for a
pilot and wrong for most teams after it, so the policy is one line in
`.openfactory/project.yaml`:

```yaml
merge_policy: auto      # "human" (default) | "auto"
```

**`auto` is not "merge whatever comes out."** It lands a PR only when ALL of these hold, and each
is a line of code in `orchestrator/merge_policy.py` rather than an intention:

| the condition | what it stops |
|---|---|
| every gate passed | your own `test`, `lint`, `types`, `security` — a red gate is never merged |
| the review did not reject | only when `review_mode: blocking`; an `advisory` review informs and does not block |
| no HARD suppression survived | a `noqa` / `type: ignore` / `nosec` the repair loop could not remove always goes to a human — silencing a real error never merges itself |
| a coverage pragma was VETTED | `pragma: no cover` may pass, but only if an independent review looked at it; with no reviewer, any surviving suppression stays human-gated |
| nothing high-risk was touched | a component declared `risk: high` always waits for a person, whatever the policy says |

So the useful shape is usually not all-or-nothing: leave `merge_policy: auto` and mark the areas
you want your eyes on — authentication, billing, migrations — as `risk: high` in `components:`.

**And with `human`, saying so counts.** The panel's attention bar carries `Merge`, `Adjust…` and
`Discard` for a job that is waiting, and the tech-lead chat reaches the SAME rows: typing
"pode fazer o merge" (or `merge`, `descarta`, `ajusta: <what to change>`) performs them, through
the same credential check the buttons go through. A QUESTION never acts — "posso mergear?" is
answered, not executed — and if two jobs are waiting it asks which one rather than choosing.

**When the reading you have is out of date, ask for a new one.** A repair pass rewrites the pull
request the reviewer read, so the verdict on the card says it is out of date rather than pretending
otherwise. `Re-review` reads the pull request as it stands and REPLACES that verdict — it changes
no code, and it costs one model pass, so the platform never spends it for you. Typing works too:
"review it again", "revisa de novo". It appears only where it can run: this job reviewed, a
reviewer answered, and the per-job limit is not spent.

---

## 12 · Your SURFACES: logs, secrets, boxes — all free, none of them a cloud

A default deployment costs nothing beyond the harness credential and runs entirely on your
machine. Every operational thing you would go to a cloud console for has a local answer here,
and the cloud is an **addition** you may never make:

| you want to see | free, and already running | if you later add a cloud |
|---|---|---|
| **every job's log** | the **Logs** button on the project bar opens a page of its own (`/logs`, or `/logs/<project>`): every run this deployment has made, read from the journals on this machine — including runs the engine has already forgotten. Filter by project, by the state a run ended in, or by text; each run has its own address (`/logs/<project>/<ticket>`) you can send to somebody, and its log has its own search | the button opens the cloud's log console instead |
| **what one job did** | click the job on the floor. A running one streams live; a finished one shows the same log in its briefing, replayed from the journal | the run's output goes to the cloud's log service |
| **the whole stack's output** | `docker compose --env-file .env.compose logs -f worker` — the services are `worker`, `panel`, `temporal` (the poller is a schedule inside the worker, not its own container) | unchanged — the stack still logs where it runs |
| **the engine's own history** | the Temporal UI — every workflow, every retry, every activity. The panel's **Temporal** button opens it; it is published on `TEMPORAL_UI_PORT` (default `http://localhost:8080`) | Temporal Cloud, optional |
| **parameters & secrets** | one file: `.env.compose`, `chmod 600`, git-ignored. Nothing leaves the machine | a parameter store (AWS SSM today) |
| **where the work runs** | throwaway Docker containers here — `OPENFACTORY_SANDBOX=container`, `docker ps` while a job runs | declare it: `OPENFACTORY_SANDBOX=fargate` plus the add-on's cluster coordinates (the coordinates alone change nothing — the box is never inferred from them) |
| **the board** | your tracker — GitHub Projects, Azure DevOps Boards or Jira, whichever you registered | unchanged |
| **a paused job continuing** | it already does. When the agent hits its usage limit the job pauses, and the resumed run continues the same session instead of replanning — the session is kept in `OPENFACTORY_RESUME_DIR` on this machine for 7 days (a stale one is refused and deleted, exactly as the cloud twin's bucket expires it) | the session crosses through an object store instead, because the box runs where this worker cannot reach it |

The panel shows a button only for what **this** deployment can actually honour, so a local
install has no cloud buttons — not because it lost anything, but because a link to a console you
do not have is a 404 with your name on it. Its own `how to change any of this` block repeats this
table beside each fact.

Journals live under `OPENFACTORY_LOG_DIR` (a named volume by default, so they survive
`docker compose down`), one file per job.

---

## 13 · AFTER THE MERGE: what the factory does next, and what it will not do

**The factory never deploys anything.** It merges, it tags, and it *watches* — your pipeline
does the deploying, with your secrets, exactly as it does today. That is deliberate: the deploy
credential for your production is the last thing an autonomous system should hold.

**And by default it does not even watch.** A project whose manifest says nothing about
environments is finished at the merge: the card moves to Done and the ticket says, in as many
words, that nothing here is watching a deploy and nobody will be asked to validate one. That
sentence exists because the alternative is worse than a missing feature — a factory that quietly
does nothing looks exactly like a factory whose next step has not arrived yet, and you would sit
waiting for a validation request that was never coming.

Three levers turn the post-merge half on. Each is independent, and each is one block in
`.openfactory/project.yaml`:

### a) Watch my deploy and tell me how it went — `post_merge_deploy:`

```yaml
post_merge_deploy:
  workflow: deploy.yml       # YOUR CI workflow, by file name or display name
  env: staging               # what to call it in the message ("staging deploy ok")
  timeout_minutes: 30        # it says "timeout" rather than hanging for ever
  url: https://stg.example.com   # where a PERSON looks once it is green
```

The factory finds that workflow's run **on the merge commit**, follows it, and reports
`success` / `failure` / `timeout` on the panel and to your notifier. It never blocks: the ticket
is done at the merge and the report arrives after. Use this when you deploy on push to main and
you only want to know.

**`url:` is what turns the report into a request.** With it, a green deploy asks somebody to look
— on the panel, and, if the project has a product channel (§9), in the client's own words and
their own language. Without it the deploy is still reported and nobody is sent anywhere: a message
saying "it's in the test environment, go and have a look" with no address costs the reader a reply
to find out where, which is worse than saying nothing.

This is the lever most repositories can actually use, and it is the honest one to try first. The
promotion chain below observes **deployments the provider recorded** — a GitHub environment, an
Azure Pipelines environment — and a repository that simply deploys from a workflow records none of
those, however real its deploys are.

### b) Walk my stages and stop at production — `environments:` + `promote:`

```yaml
environments:
  dev:      { deploy_ref: dev, health_url: https://dev.example.com/health,
              url: https://dev.example.com }
  qa:       { deploy_ref: qa,  health_url: https://qa.example.com/health,
              url: https://qa.example.com, validate_with: product }
  producao: { deploy_ref: producao }

promote: [dev, qa, producao]     # in order; the LAST one is production, whatever you call it
```

`health_url` is where a **machine** checks — probed with a GET, only the status code is read.
`url` is where a **person** looks. They are usually different pages and the difference matters:
sending somebody to `/api/v1/health` to confirm a feature is sending them to the wrong screen.

`validate_with: product` marks **the stage a person is asked to confirm**. You rarely need to
write it: with nothing declared it is the last stage before production, which is what most teams
mean by "the test environment". Write it when the stage you want somebody to look at is not that
one — a `dev` you demo from, a `qa` that is really the client's.

After the merge the chain is walked in the order you wrote it. Each stage before the last is
**observed** — the deployment status of `deploy_ref`, then a GET on `health_url` if you gave one
— and a red stage parks the ticket with the stage's name on it. The last name is production **by
definition**, and it is never automatic: the job parks at a human gate, the panel shows it, and
somebody approves with a version. The approval tags `<prod_tag_prefix><version>`, and production
is observed the same way.

Your names are yours: `[dev, qa, producao]` works exactly like `[staging, prod]`. Declare a stage
with neither `deploy_ref` nor `health_url` and it passes through unchecked — which is allowed,
and is why the ticket says which stages were actually verified rather than claiming all of them.

**No production at all?** Declare the environments you do have and leave them out of `promote:`,
or omit `promote:` entirely. The ticket then finishes at the merge saying this project declares
no production environment, so there is no release step — a state this platform treats as ordinary,
not as a misconfiguration. Something under construction has nowhere to release to yet.

You are still **asked to confirm** the last stage. There is no gate behind it, so a person saying
the change is right is the whole of what is left — the ticket names the stage and its `url:`, and
the panel shows it as needing action. Skipping that ask was the older behaviour and it had the
shape backwards: the shops with the shortest pipelines were the only ones never asked to look at
anything (#122).

### c) Ask a person to try it — the product role

Declare a `url:` above and a green deploy asks somebody to look at it. The **operator** is always
asked — on the panel, whatever else is configured. If the project also has a product channel (§9),
the **client** is asked too, in their own language, naming what changed rather than a ticket
number, and carrying the same address. One event, two readings.

That second half is silent when there is nobody to tell: no product module, no channel, no client
— no message, and the operator still gets theirs.

**With no `url:` declared, nothing pretends there is a place to look.** The stage is reported
green, the ticket says plainly that nobody can be sent to it, and it names the field that would
fix that. A message telling somebody to go and try something, with nowhere to go, is worse than
one that admits the project never said where.

When a job reaches the **production gate** the client is asked to confirm before the release, and
that ask now carries the same address: the stage's own `url:`, read from your manifest. The
deployment-wide `product.staging_url` still works if you already set it — it is the fallback, it
is **deprecated**, and it cannot name more than one stage, which is why an address belongs in the
manifest beside the environment it is about.

### What each lever costs you if you skip it

| you declare | after a merge you get | you do NOT get |
|---|---|---|
| nothing | the card reaches Done and the ticket says nothing is watching | any deploy signal at all |
| `post_merge_deploy:` | your deploy run followed and its outcome reported | stages, gates, or an approval |
| `environments:` + `promote:` | every stage observed in order, production human-gated in the panel | a deploy — your pipeline still does that |
| a product channel too | the client asked to look before the release | a validation ask for a flow that ends before production |

---

## Where the platform's opinions live, and how to make them yours

Three layers, in the order they win:

| | |
|---|---|
| **the framework floor** | non-negotiable: every project runs a `test` and a `security` gate. `test` is yours to declare — there is no default that tests nothing; `security` is inherited from the deployment when you don't declare your own. There is no switch |
| **the deployment's defaults** | `openfactory/org_defaults/` — §11: engineering standards, the role prompts, and the inherited advisory secret-scan above |
| **your project** | `.openfactory/project.yaml` — your gates, your components, your guidelines. Yours always wins |

The escape hatch for a noisy gate is `advisory: true` — it runs, it reports, it never blocks a
merge. It is never an absent gate: a job whose gates are empty reports green having proven
nothing.

---

## If something does not work

**Runs on: the WORKER** — prefix each with the §0 `exec worker` form. Typed on the laptop they
answer for THIS machine: the laptop's registry entry without the worker's box proofs, Docker or
credentials — a green or red there says nothing about the machine that runs your tickets.

Every refusal in this platform is meant to name one cause and one thing to do about it. If you hit
one that does not, that is a defect worth reporting — it is the bar the whole product is held to.

- `openfactory doctor <project>` — prerequisites, one line each
- `openfactory env check <project>` — the composed verdict, and where it was measured
- `openfactory box status <project>` — whether the box proof is still valid, and what moved
- `openfactory conformance <project>` — whether the manifest satisfies the contract

(`openfactory env read` is the exception — a LAPTOP command, §3, against your checkout.)

Deploying this onto your own infrastructure — a cloud, a cluster, your own machines — starts
from the same `docker compose` stack you just ran; a cloud reference deployment, with its worked
walkthrough, ships with the `openfactory-aws` add-on package rather than in this tree
([`STATUS.md`](STATUS.md) lists what that package carries). The full annotated manifest reference is
[`docs/project.yaml.example`](project.yaml.example).
