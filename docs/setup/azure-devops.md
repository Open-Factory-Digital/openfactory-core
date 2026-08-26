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
2. The credential is one PAT in **`AZURE_DEVOPS_PAT`** (or any variable your registry names).
   There is no App equivalent to create — this page is shorter than the GitHub App one.
3. Two board **states** the platform uses do not exist in a stock process — §3 creates them
   once per organisation.
4. The work item **type** depends on your project's process (§4) — the wrong one is a `400` at
   the first ticket.
5. The pickup column is **`To Do`** (Azure's spelling), not `TO-DO`.

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

The platform moves cards through five states; a stock process is missing two of them:

| lifecycle | state it looks for (default) | stock process has it? |
|---|---|---|
| pickup | **To Do** | yes (Basic; Agile/Scrum equivalents resolve by category) |
| in progress | **Doing** | yes (Basic) |
| in review | **In review** | **no — create it** |
| needs action | **Needs Action** | **no — create it** |
| done | **Done** | yes |

System processes cannot be edited, so this is done once with an **inherited process**:

1. Organization settings → Boards → **Process** → your process (e.g. Basic) → *"…" →
   **Create inherited process*** — name it, say, `OpenFactory Basic`.
2. Open the inherited process → the work item type you will use (§4) → **States** → *New state*:
   - `In review` — in the **Resolved** category. The platform finds review states **by
     category**, so the category is the part that matters; the name is yours.
   - `Needs Action` — in the **In Progress** category. Azure has no category for "a human must
     look at this", so this one state the platform finds **by name** (it also recognises
     `Blocked`, `On hold`, `Waiting`, `Impediment` and their pt-BR forms).
3. Project settings → Overview → **Process** → switch the project to the inherited process.

Your own state names are fine — declare them in the registry entry and nothing else changes:

```yaml
tracker:
  options:
    state_map: '{"in_review": "Em revisão", "needs_action": "Bloqueado"}'
    columns:   '{"todo": "A Fazer", "done": "Concluído"}'   # board column labels, if renamed
```

`state_map` always beats the by-name search. A state the platform cannot find is a card that
stops moving **with the reason logged** — `openfactory doctor` checks the pickup column; the
first parked ticket exercises the rest.

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
        # state_map / columns / areas # §3 and §7
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
**`To Do`**. The factory takes it from there: branch and pull request in Azure Repos, your own
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
