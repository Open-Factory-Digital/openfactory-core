# Azure DevOps, start to first work item

The all-Microsoft scenario, end to end: work items on **Azure Boards**, code and pull requests
on **Azure Repos**, builds observed on **Azure Pipelines** — no GitHub anywhere, and the `gh`
CLI is not needed. Each of those is an **adapter**: the platform ships at least two for every
axis, so this page is one connector's setup rather than a requirement, and
[github.md](github.md) is the same walkthrough for the other side. Everything below was exercised against a live Azure DevOps organisation
(fx-ado, 2026-08-06); where a screen name could still drift with Microsoft's UI, the step says
what you are looking for rather than only where it was.

The five differences from the GitHub path, up front:

1. Coordinates nest one level deeper: **organisation / project / repository**. The tracker
   works in the *project* (work items live there); the forge works in one *repository* inside
   it. `openfactory project add` reads all three out of your clone URL.
2. The credential is one PAT in **`AZURE_DEVOPS_PAT`** (or any variable your registry names),
   or, on a hosted worker, the identity its machine already has (§1). There is no App
   equivalent to create — this page is shorter than the GitHub App one.
3. Three board **states** the platform uses do not exist in a stock process — §3 creates them
   once per organisation.
4. The work item **type** depends on your project's process (§4) — the wrong one is a `400` at
   the first ticket.
5. The pickup column is **`Ready`**, a state of its own (§3). Azure files every new work item in
   `To Do`, so `To Do` is the **backlog**: a card filed there waits until a person queues it.

---

## 1 · The PAT

`dev.azure.com` → User settings (top-right avatar) → **Personal access tokens** → New token,
scoped to the organisation the project lives in. Grant, by what the factory actually does:

| scope family | level | what breaks without it |
|---|---|---|
| Work Items | Read & write | reading the queue, moving cards, commenting the ticket |
| Code | Read & write | fetching the repo, pushing branches, opening and completing PRs |
| Build | Read & execute | reading pipeline verdicts; triggering the deploy watch's runs |
| Environment | Read | the declared-environment watch — a PAT *without* it makes those reads **raise** (401), it does not degrade |
| Project and Team | Read | resolving the project's teams and identities |

Completing PRs past a branch policy (`merge_policy: auto` with `bypass`) additionally needs the
policy-bypass permission on the repository. The checkbox labels above are Azure's vocabulary at
the time of writing; the definitive set is re-dictated from a live installation before each
release (#115) — if a label moved, match by the family.

An `az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798` JWT works in
place of a PAT everywhere — the adapter detects which shape you pasted. Useful for a first
try with no secret created; it expires in about an hour.

Or leave the variable empty on a machine where `az login` has been run: the adapter then mints
that JWT itself at each use and renews it before it expires, so a job longer than an hour still
pushes. `openfactory doctor` counts the login as the forge's credential. This is the path for a
tenant where a person cannot create a PAT, on a machine where a person works.

### A hosted worker: the identity its machine already has

A hosted worker uses its machine's own identity where the organisation accepts one, and a stored
token where it does not. On an Azure VM (or scale set) with a managed identity, nothing needs
storing or rotating:

1. Add the identity to the organisation as a user (Organisation settings → Users → Add, and
   search by the identity's name), with access to the project and **Contributors** on it. The
   table above lists what each permission family is for; the identity needs the same ones.
2. **Declare it** on both axes in the registry, because nothing uses an identity that nobody
   chose. Nothing asks the metadata endpoint for an axis that does not say so:

   ```yaml
   tracker:
     kind: azure_devops
     options: {organization: acme-ai, project: Deskline, identity: workload}
   forge:
     kind: azure_devops
     repo: api
     options: {organization: acme-ai, project: Deskline, identity: workload}
   ```

   Add `identity_client_id: <client id>` to use a **user-assigned** identity. Without it, the
   identity the platform assigned to the machine is used. An axis that declares an identity uses
   it and nothing else, never a PAT or a login beside it. `token_env` next to it is refused by
   name.
3. Leave `AZURE_DEVOPS_PAT` empty. The worker asks the machine's metadata endpoint
   (`169.254.169.254`) for a token at each use, without going through a proxy. It renews the
   token before it expires, the same way it renews the `az` login's.
4. Run `openfactory doctor`. The forge line names the credential it reached the forge with:
   *a stored secret*, *this machine's `az` login*, or *the identity the platform gave this
   machine*. That is the answer the adapter uses, not a second guess.

**The box is the thing to check.** Once an identity is declared, the metadata endpoint is a
credential: anything on the machine that can reach it can mint the identity's token. The worker
mints the token and hands a job the value it minted, never the declaration. A job must also be
kept from reaching the endpoint itself, so `openfactory doctor` adds a `box_identity` line:

- **container box**: the doctor *measures* whether a container on the box's network reaches
  the endpoint. If it does, the doctor prints the host rule that closes it for that network
  only (`iptables -I DOCKER-USER -s <box subnet> -d 169.254.169.254/32 -j DROP`), so the
  worker, on its own network, keeps its identity.
- **worktree box**: the agent's code runs as this machine and can ask the endpoint directly.
  The doctor reports this in red. Run those jobs in the container box, or give the axis a
  stored secret instead.
- **remote box**: it receives the minted token and never the declaration. What the remote
  machine can reach is for its own platform to bound.

## 2 · Tell `init`, fill one row

Already ran `openfactory init` from ONBOARDING §0 (it is what sent you here)? **Skip the
command** — the `AZURE_DEVOPS_PAT=` row is already in your `.env.compose`; just paste the PAT.
Starting from this page instead:

```bash
openfactory init          # answer azure_devops for code and tickets
```

The generated `.env.compose` carries the `AZURE_DEVOPS_PAT=` row — paste the PAT there. One
deployment driving several ADO projects with **different** credentials names a variable per
project instead (`--token-env ACME_ADO_PAT` at registration writes the name into the
registry; the value still goes only in `.env.compose`). Every row of that file reaches the
worker — including variables you invent.

## 3 · The board states, once per organisation

The platform moves cards through six states, and a seventh it uses only when you name it; a
stock process is missing three of the six:

| lifecycle | state it looks for | stock process has it? |
|---|---|---|
| backlog — where a filed card waits | **To Do** (declared, step 5) | yes — **required** |
| pickup — the queue the factory takes work from | **Ready** (declared, step 5) | **no — create it** |
| in progress | **Doing** | yes (Basic) |
| in review | **In review** | **no — create it** |
| needs action | **Needs Action** | **no — create it** |
| needs review — a pull request waiting on a person's review or merge click | the state `state_map` names, the column `columns` names | optional — unnamed, those pull requests go to **Needs Action** |
| done | **Done** | yes |

**The backlog is required, and it is not the queue.** Azure gives a new work item its type's
first state — `To Do` on Basic — and nothing the platform sends changes where a person's own new
card lands. On a board where `To Do` is also the pickup column, every card the product role
files is picked up and paid for with nobody queueing it (#536). So the queue gets a state of its
own, `Ready`, and `To Do` is the backlog: a card the factory files, and one a person creates on
the board, waits there until a person moves it to `Ready` — or asks the product role to queue it.
`openfactory doctor` **fails** `board_intake` on a board where a filed card would start in the
pickup column, naming this fix, and until it is fixed the product role files nothing there and
says why in the conversation.

System processes cannot be edited, so this is done once with an **inherited process**:

1. Organization settings → Boards → **Process** → your process (e.g. Basic) → *"…" →
   **Create inherited process*** — name it, say, `OpenFactory Basic`.
2. Open the inherited process → the work item type you will use (§4) → **States** → *New state*:
   - `Ready` — in the **Proposed** category, after `To Do`. This is the queue.
   - `In review` — in the **Resolved** category. The platform finds review states **by
     category**, so the category is the part that matters; the name is yours.
   - `Needs Action` — in the **In Progress** category. Azure has no category for "a human must
     look at this", so this one state the platform finds **by name** (it also recognises
     `Blocked`, `On hold`, `Waiting`, `Impediment` and their pt-BR forms).
3. Project settings → Overview → **Process** → switch the project to the inherited process.
4. The team's board → Board settings → **Columns**: a `Ready` column right after `To Do`, mapped
   to the `Ready` state. Every column must map to one of the states above — a card in a
   column the platform does not map cannot be queued, edited or closed through it.
5. In the project's registry entry (§5), under the tracker's `options` — quoted, each a string of
   JSON:

```yaml
tracker:
  options:
    columns:   '{"backlog": "To Do", "todo": "Ready"}'     # the board's columns
    state_map: '{"backlog": "To Do", "todo": "Ready"}'     # the states the tracker writes
```

`columns` is what the poller reads and where a card is placed; `state_map` is what the tracker
writes: a filed card is **created** in the `backlog` state, a stopped or skipped card goes back
to it, and an answered question puts a card back in `todo`. Both are needed — without
`state_map` the tracker has no state for the backlog at all.

Your own state names are fine — declare them the same way and nothing else changes:

```yaml
tracker:
  options:
    state_map: '{"backlog": "A Fazer", "todo": "Pronto", "in_review": "Em revisão", "needs_action": "Bloqueado"}'
    columns:   '{"backlog": "A Fazer", "todo": "Pronto", "done": "Concluído"}'   # board column labels
```

**A column for pull requests waiting on a reviewer is optional.** Without it, a pull request
that waits only on a person (their review or merge click) goes to Needs Action beside the cards that are stuck, as it
always did. To give it its own, add a state — `Needs Review`, in the **In Progress** category
as Needs Action is — and a column mapped to it, and name both for the `needs_review` key:

```yaml
tracker:
  options:
    state_map: '{"backlog": "To Do", "todo": "Ready", "needs_review": "Needs Review"}'
    columns:   '{"backlog": "To Do", "todo": "Ready", "needs_review": "Needs Review"}'
```

The platform finds this state **only through these maps**: no category and no name answers for
it. A board column already called `Needs Review` that `columns` names for no key is read as the
review wait (one it names for another key, `needs_action` say, is read as that key) when a person puts a card there, but the factory moves no card into it.

A backlog state of its own works too — `Backlog` in the Proposed category, a column for it, and
`state_map: '{"backlog": "Backlog"}'` with `columns: '{"backlog": "Backlog"}'`: the product role
then asks Azure to create its cards directly in `Backlog`. A card a person creates on the board
still starts in `To Do`, which is then the queue, so the shape above is the one to prefer.

`state_map` always beats the by-name search. A state the platform cannot find is a card that
stops moving **with the reason logged** — `openfactory doctor` checks the pickup column and where
a filed card starts; the first parked ticket exercises the rest. **Upgrading a deployment set up
before this section had the backlog row:** until the two lines are in, `doctor` fails
`board_intake` and the product role files nothing.

**A column no stage is.** Azure files every new work item in the board's first column — `New` on
the stock Agile and Scrum processes — and no stage is `New` until you say so. A card there cannot
be queued, edited or closed through the platform, and a card the product role files is placed in
no column, until `columns` names it — `'{"backlog": "New"}'` beside whatever else you map, when
`New` is where cards wait to be queued. `openfactory doctor` names every column no stage is
(`board_stages`), with that line.

## 4 · The work item type

| your project's process | pass at registration |
|---|---|
| Basic | nothing — `Issue` is the default |
| Agile | `--work-item-type "User Story"` |
| Scrum | `--work-item-type "Product Backlog Item"` |

The wrong type is a `400` from Azure at the first ticket the factory writes, so this is worth
ten seconds now: Project settings → Overview → Process names yours.

## 5 · Register the project — the URL is the registration

**This step needs the stack UP** — it runs inside the worker, so if you came here straight from
`init`, go back to [ONBOARDING §0](../ONBOARDING.md)'s `docker compose … up -d --build` first.
The honest itinerary through this page is two visits: §§1–4 while setting up the environment,
§5 onward once the stack is running.

**On the worker** (the compose stack reads the worker's registry, not your laptop's):

```bash
docker compose --env-file .env.compose exec worker \
  openfactory project add dsk https://dev.azure.com/<org>/<project>/_git/<repo> \
  --work-item-type "User Story"        # per §4; omit on Basic
docker compose --env-file .env.compose exec worker openfactory doctor dsk
```

The clone URL carries the organisation, the project and the repository — no coordinate flags.
(SSH and legacy `visualstudio.com` URLs parse too; flags `--organization` / `--ado-project` /
`--repository` override the URL if you must.) `doctor` then names anything missing, one line
with its remedy, `AZURE_DEVOPS_PAT` included.

What it wrote, in full — this is also the shape you would hand-edit for the options §3 and §7
describe (the worker's registry lives at `/var/lib/openfactory/registry.yaml`, on the
`openfactory_state` volume; `docker compose --env-file .env.compose exec worker vi
/var/lib/openfactory/registry.yaml` reaches it):

```yaml
projects:
  dsk:
    name: dsk
    repo_path: https://dev.azure.com/acme-ai/Deskline/_git/dsk-api
    tracker:
      kind: azure_devops
      repo: Deskline              # the ADO PROJECT — work items live here, not in a repo
      options:
        organization: acme-ai
        work_item_type: "User Story"
        # token_env: ACME_ADO_PAT # only when this project has its own credential
        # team: "DSK Core"            # a specific team's board; default: the project's default team
        # columns / state_map         # §3 — REQUIRED: the backlog and the queue, apart
        # areas                       # §7
    forge:
      kind: azure_devops
      repo: dsk-api                   # the git REPOSITORY inside the project
      options: {organization: acme-ai, project: Deskline}
    # ci is inherited from the forge: azure_devops ⇒ Azure Pipelines, observed read-only
```

**The context repository, when your PAT may not create one.** Many organisations route
repository creation through their own provisioning process — `onboard` handles that: create the
repository in the Azure DevOps portal, then declare it before (or after) onboarding:

```bash
docker compose --env-file .env.compose exec worker \
  openfactory product declare <project> <repo>          # or Project/repo, in another project
```

A declared repository is USED, never replaced, and the command reads it back with both
credentials that will open it, so a wrong qualifier fails now rather than silently at runtime.
If you let onboarding try first and the PAT is refused, the refusal names this same command.

From here the path is the same as everyone's — [`docs/ONBOARDING.md`](../ONBOARDING.md) §3
onward. The recommended form is one command on the worker, `openfactory onboard <name> --yes`:
per repository it proposes the manifest **proven in the real box** and the module map as a
pull request in Azure Repos, and proposes the context backfill the same way. A product split
across repositories — front and back — names them once, `--source <project>/<repo>` each
(the same qualifier a card carries; the organisation comes from the registration), and gets
one proven pull request per repository. The session form (`env read`/`env apply`
against a checkout, `box prove`, `env rehearse`) is walked in the same section.

## 6 · The first work item

Create a work item of the §4 type with an **objective** and **acceptance criteria** in its
description (English or Portuguese — headings are matched by meaning), and move it to
**`Ready`**. The factory takes it from there: branch and pull request in Azure Repos, your own
`validate:` gates, an independent review, and your pipelines observed after the merge.

```markdown
## Objective
Users can export their report as CSV.

## Acceptance criteria
- a `GET /reports/{id}/export` endpoint returns text/csv
- the export respects the report's current filters
```

## 7 · Several repositories under one project

An ADO work item lives in a *project*, which says nothing about which of its git repositories
the work belongs to. The platform reads the card's **Area Path** and matches its leaf to a
repository name — a client whose areas are named after their repos configures nothing; anyone
else declares the mapping:

```yaml
tracker:
  options:
    areas: '{"Portal": "dsk-ui", "Backoffice": "dsk-api"}'   # area leaf → repository
```

A card whose area resolves to nothing falls back to the forge's single `repo` — fine for a
one-repo product, wrong for three; declare the map before the second repository, not after the
first mis-aimed diff.

## 8 · One Epic of a shared team

A team's backlog is not always one product's. When the repository you registered is the work of one
Epic of a team that keeps several, the pickup queue is wider than the project: it is every card in
the queue column across the team's area paths, so a card another person puts in that column is one
the poller may claim and pay an agent for, in a repository it has nothing to do with.

`scope_epic` narrows every read to the work items under one Epic:

```yaml
tracker:
  options:
    scope_epic: "70133"        # the id of the Epic: a number. A title is not accepted
```

It is the id, not the title, because two work items can share a title. Quote it in YAML.

The hierarchy root's work item type is not checked: a readable Feature id also scopes to its
descendants, and a readable leaf id produces an empty board. Check that the id names the intended
Epic before enabling pickup.

**What it limits.** The pickup queue, the board the panel and the product role read, the list of
the project's cards, and the search for an already filed card of the same title. Each is the query
it was without the option with `[System.Id] IN (…every work item under the Epic…)` added, so the
scope only narrows what the team's area paths already select; it never widens it. "Under" means at
any depth, whatever levels the process has (Epic → Feature → Product Backlog Item here, Epic →
Issue → Task on Basic). Unset, or blank, the queries are exactly those of a project without it.

**Where the cockpit's Board link opens.** With `scope_epic`, it opens the panel's own board, which
shows this project's scoped slice. A Jira project with `scope_jql` follows the same rule. Every
other project opens its provider's board.

**What it costs.** One extra request per board or tracker instance, a recursive link query that
returns the Epic's subtree; it is not repeated for each column. An Epic can name at most 1,500 work
items under it, because they travel in one query; past that the board is unreadable and the warning
says how many there are.

**It fails closed.** An id that is not a number, an id that names no work item this credential can
read, a subtree past the ceiling and a request that failed all read as an unreadable board, never as
a project without a scope, which would hand the factory the whole team. `openfactory doctor` reports
the board as unreadable and its remedy names `scope_epic` beside the credential, and the worker's
log names the option and the id. An Epic with nothing under it is a readable, empty board.

**A scoped project refuses, by name, to edit, close, remove, queue or rank a card that is not under
its Epic.** Those acts reach a card by its number, so the board asks whether the card is in the
slice, and answers "it is not this project's" or, when it could not tell, as for an unreadable
board. A project without `scope_epic` makes no extra request.

Three acts are **not** held to the scope and reach any work item by its number: starting a job on a
card (`openfactory run <project> <card>`, the floor's `start`), reopening a closed card, and
commenting on one. Name only cards under the Epic to them.

**Two limits to plan around.**

- **A card the factory files itself is not under the Epic.** A split's children, the product role's
  cards and an impediment are created in the project and linked to nothing above them, and in an
  Epic → Feature → Item hierarchy there is no obvious parent to attach them to. Outside the scope,
  the poller does not pick them up, the panel does not show them, and a retry files another because
  the search for an earlier filing does not find them. The scoped project refuses to edit, close,
  remove, queue or rank them until they are under the Epic. File the cards you want worked under a
  Feature of the Epic yourself.
- **Every project on a shared team needs its own `scope_epic`.** The scope narrows only the project
  that declares it: a project left without one still reads the whole team. A work item has one
  parent, so two different Epics never overlap; two projects naming the same Epic read the same
  cards.
