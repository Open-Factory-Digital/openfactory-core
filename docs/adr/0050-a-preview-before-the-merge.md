# ADR 0050 — A preview before the merge, because nothing after it can be taken back

- **Status:** **Accepted** — designed on 2026-09-22 and revised on 2026-09-23 from a
  single-container preview to a preview of the whole product; built on 2026-09-24 in slices 0–7 of
  #265 (#270, #277, #278, #287, #288, #293, #292, #296), and merged together on 2026-09-25 with the
  host closed off (#291). The decisions below say what was built, and each one that moved from the
  design on #265 says where and why — see *History* at the end.
- **Date:** 2026-09-22
- **Relates to:** ADR-0001 D-6 (components: what a diff touched), ADR-0005 (post-merge deploy watch,
  and the read-only contract it gave the `environment` adapter), ADR-0025 (delivery closes with the
  client — a different gate, in a different place), ADR-0026 (a word the reader already has beats
  one you invent), ADR-0036 (ordering across repositories), ADR-0037 (the box), ADR-0038 (the panel
  is the reference surface), ADR-0040 (the core runs on the client's own machines; a cloud is an
  add-on), ADR-0048 (the preflight's `touches`), ADR-0049 (the whole cycle on one machine), #265
  (the design these decisions were built from, and its slices), #266 (the product is the boundary:
  the context repository and its `sources:`), #268 (the system layer), #271 (`__Host-` on the
  panel's credential), #291 (an internal network reached the host through its gateway; closed).

## Context

A real client scenario, 2026-09-22: the client runs OpenFactory on their own server — exactly the
README's second door, Docker, a hosted forge, several people watching the same panel. A card goes
to TO-DO, the box implements it, `validate:` goes green, the independent review approves, a pull
request opens. The client wants to see the change **running**, functionally, before that pull
request merges.

That is not a nicety, and the reason is in the code, not in taste.
`openfactory/adapters/environment/azure_pipelines.py`'s own docstring states the shape plainly:
*"the platform triggers a merge or a tag and then OBSERVES the client's own pipeline; it never
deploys"* — no deploy credential exists on that axis, every route is a GET. Once a pull request
merges, the client's own CI/CD promotes to staging on its own, outside anything this platform holds
or can undo (ADR-0005; ADR-0040 D1: *"the platform triggers; the client's pipeline executes"*). The
merge is the only door here that does not open back up. Asking to look before it closes is asking
for the one point of leverage this platform still has.

### What a person validates is the product, not the part that changed

Almost no application runs in one process. The least a real one is: a front end, a back end and a
database, often more — a cache, a queue, a second service, sometimes in separate repositories. A
change is rarely visible where it was made: a field's type changed in an endpoint is seen on a
screen the front end draws, over data the database holds. A preview of the back end alone would be
a running service nobody outside the team can look at; for the person who asked for the change it
shows nothing at all.

So the thing previewed is **the product**, assembled for one change: every part of it running, the
parts the change touched taken from the change, the rest as they are on the base branch.

### The false starts, recorded so they are not retried

**"A hybrid forge."** The first name for this. Wrong, in the exact way ADR-0026 already wrote down:
`forge` already names the adapter axis that opens and merges pull requests
(`openfactory/adapters/forge/`), so the name maps the reader onto the wrong thing. And the
deployment shape it reached for — Docker, on a server, in front of a real forge, several people
watching one panel — is not missing: it is the README's own second quickstart door.

**"The box, kept alive and served."** This record's first version: a `serve:` command in the
manifest, and the one container that passed `validate:` started again as the preview. It is right
for an application that runs in one container, and that is the rare case; for everything else it
previews a fragment (see *History*). What survives of it is the machinery around the container —
how a preview is exposed, who may open it, what secrets it sees, how it ends — and that is D7–D10
below.

## Decision

### D1 — The unit is what the person asked for; it may become one pull request or several

A person asks for one thing: a requirement, or a bug. It may be narrow — change the type of one
field of one endpoint — or wide — a new capability, with layout, behaviour and data. Its size does
not change the unit; it changes **how many technical changes it becomes, and where**, and that is
the factory's business, not the person's:

- **One repository, or a monorepo:** one card, one job, one pull request, whose diff may touch any
  part — front end, back end, migrations — at once.
- **Several repositories:** the product role breaks a wide requirement into one card per
  repository it lands in (`product/role.py::issues_for` — *"must name which source repository it
  lands in"*), so the one thing asked for becomes N pull requests, one per repository.

**A preview is keyed by the unit the person asked for**: the requirement when the card cites one,
the card itself when it does not (a bug, or a card opened on the board). Never by the pull request:
a preview of one repository's pull request out of three is a fragment, not the thing asked for.
How a requirement's cards are found, and what a card says when they cannot be, is D5.

### D2 — What changed is read from the diff, never predicted

The factory already knows what a change touched, at three moments, and the preview reads the last:

1. **Before it starts, an estimate** — the preflight's `touches` (ADR-0048).
2. **At the breakdown, the repository** — D1's one card per repository.
3. **After it is done, the truth** — the change's own diff, per repository: from the point where the
   change branched (the merge base) to the head the forge reports open.

A preview is assembled from (3), and the diff is mapped to the product's services by **what each
service is made from**: its build context, its Dockerfile when that lies outside the context, and
the sources of its bind mounts, each in its repository. A service is from the change when a path of
that repository's diff falls under one of them; a service made of nothing in any repository — an
image with nothing mounted — is never from the change. Nothing is declared for this: a single
Dockerfile at the root is one service whose input is the whole repository, and a monorepo's
`web/` and `api/` contexts divide the diff between them on their own. An estimate that said "back
end only" does not keep a front-end change out of the preview; the diff does not lie about what it
contains.

**Amended (2026-09-24, #277):** the first text mapped the diff to the manifest's `components:` by
their `path:` globs (ADR-0001 D-6). A repository with one stack declares no `components:`, so the
map had nothing to read there, and a map declared for the preview alone would have been a second
description of the product beside its compose file, which D3 refuses. And a diff of the two trees,
rather than from the merge base, would have put every commit the base gained since the branch point
into the change. Built as `openfactory/preview/assemble.py::inputs` and `is_from_change`.
`.dockerignore` is not consulted, so a change to a file a build ignores still rebuilds that
service.

### D3 — The product's shape is the client's own compose file, read from the base and admitted key by key

Most applications already carry a compose file for local development that says which services
exist, how each is built and what each needs. The factory is not taught a second way to say that:
the Compose Specification is the only description of how a product runs that the core reads, and
the block beside it says only what that file does not know:

```yaml
preview:
  compose: [docker-compose.yml]        # one file or several, merged the compose way — from the BASE
  expose: {web: 3000, api: 8000}       # what a person may open: service -> its port in its container
  data:
    api: "python manage.py migrate && python manage.py loaddata demo"   # fresh data, every time
  exclude: [mailhog]                   # services a preview does not run
```

- **Where it lives.** One repository or a monorepo: the manifest's `preview:`. A product of several
  repositories: the context repository's `.openfactory/product.yaml` `preview:` — the product is the
  boundary (#266) — which also says which repository holds the compose file
  (`compose: {repository, paths}`; the context repository itself when only paths are given) and,
  in `dirs:`, which repository a `../<dir>` the file reaches is, when the directory is not the
  repository's short name. Every repository either names must be in `sources:`; a compose file that
  reaches a directory outside them is refused by name, and nothing outside the product is ever
  cloned. A project whose product and one of whose repositories both declare a shape is refused by
  name — keep one — and in a product that declares one, every unit of every source is previewed
  with it.
- **Read from the base branch, never from the change.** The compose file and this block are files
  in the repository the agent edits. A preview assembled from the change's own compose file would
  run whatever the change declared — a privileged service, the host's network, the host's
  filesystem, the daemon's socket. So the files are read from a checkout of the base, the change's
  compose file is never opened, and a change that alters the shape itself is previewed with the old
  one (said on the preview, not hidden).
- **Merged by the compose CLI, admitted by the core.** The listed files are merged, validated and
  normalised by `docker compose config --no-interpolate --format json`, under an environment reduced
  to what the CLI needs to find itself (it contacts no daemon for this); the core reimplements no
  merge. Before that a pre-scan refuses `include`, `provider`, an `extends.file` that is absent,
  absolute, `~`-rooted, `$`-bearing or outside the unit's trees, and any path that is absolute,
  `~`-rooted or `$`-bearing. After it, admission (`openfactory/preview/admit.py`, the one place a
  compose key is judged) reads the document key by key with four outcomes: **pass** it verbatim;
  **set** it from the operator's policy, dropping the client's value and saying so (`restart`,
  `cap_add`, `cap_drop`, `security_opt`, the limits, `labels`, `networks`); **drop** it and say so
  (`ports`, `container_name`, `extra_hosts`, `deploy`, `logging`, …); **refuse** the whole preview
  by name (`privileged`, `devices`, `network_mode`, `pid`, `ipc`, `sysctls`, `secrets`, `configs`,
  `volumes_from`, `gpus`, …). A key in no set is refused. Every path is judged on disk: its real
  path must lie inside the unit's own trees, so a committed symlink to the daemon's socket is refused
  rather than mounted. A volume must be declared, and is named under the unit's compose project; a
  top-level volume that names itself (`name:`), is `external` or names a `driver` is refused,
  because compose writes a `name:` un-prefixed, which is how a document could mount the factory's
  own state. Every `${X}` the file reads is resolved by admission: a name the preview is given
  stays, any other becomes its default or empty (said), and `${X:?}` on a name nobody gives is
  refused with the remedy. An `env_file` that is not in the repository (a git-ignored `.env`) is
  read as optional, and said.
- **A repository with no compose file gets one proposed, never guessed** — D12.
- **The shape is on the floor.** The compose specification's four file names at a repository's root
  are protected paths in every project, preview declared or not; so is everything under
  `.openfactory/` (where the drafts of D12 live, and `product.yaml`); a project's declared
  `preview.compose` paths are added. A change to any of them is never merged by the factory on its
  own, and its pull request lists every file a preview would read once it merges, with a hash. For
  a product, the context repository's base is also written by the factory itself, so its direct
  writers are held to what git actually staged: nothing they commit may land under `.openfactory/`
  or outside the writer's own folder, the requirements sweep leaves open a `req/*` branch that
  carries a shape file, and the knowledge pipeline writes under `.okf/` only.
- **Declare nothing, and nothing changes** — no `preview:` block, no preview and no start button.
  The floor above is the one thing every project gets.

**Amended (2026-09-24, #277, #288 and slice 5):** the first text declared
`services: {web: {component: front}}` and `expose: [web, api]`, and refused a short list of keys
(`privileged`, `network_mode: host`, host bind mounts, the socket, added capabilities, devices,
published ports). A list of what somebody thought of lets everything else through unexamined, so
admission became a whitelist with four outcomes. `ports` is dropped rather than refused, because
nearly every development compose file publishes ports and nothing is reached except through D7; a
bind mount is admitted when its real path is inside the unit's trees. The block lost `services:`
(D2 derives which service is from the change) and gained `exclude:`; `compose:` became a list and
`expose:` a map, because the port is what the router targets. The file names are floored in every
project, not only where a preview is declared, because a floor that followed the declaration let a
hostile shape land in one auto-merged change and be pointed at by a one-line second one; the
product owner accepted that price (a change to `docker-compose.yml` now waits for a person under
`merge_policy: auto`, in a project that never asked for a preview). The writer guard is wider than
the design, which named the sweep, `record_fact` and the knowledge pipeline: every direct writer to
the context repository is held to it. Two measurements on the pinned compose plugin (v2.32.4, the
version the worker image carries) changed the reader: `--no-env-resolution`, which the design named,
is an unknown flag there and is not passed (without it no env file is read into `environment`,
measured on 2.32.4 and 2.40); and an override's relative paths resolve against the directory of the
first file, not its own, so the drafted override for a compose file at the root says `context: .`.
And admission runs after the services from the change are moved into the change's tree, so the
on-disk checks see the tree each service runs from.

### D4 — The assembly: the change where it touched, the base everywhere else, fresh data always

For one unit (D1), with the diffs of its pull requests (D2) and the shape (D3):

| service | runs |
|---|---|
| made of files the change touched | **built from the change's tree, at the head the forge reported open, with the Dockerfile that tree holds.** Its `image:` is dropped, so the build is tagged under the unit's compose project and removed with it — never the client's `ghcr.io/acme/api:latest` retagged on a shared daemon and handed to the next preview as "base" |
| not touched, naming an `image:` | that image, pulled `always`, so the base is what the client's CI publishes today; its digest and when it was pulled go on the card |
| not touched, `build:` only | built from the base branch |
| a data store | a fresh volume named after the unit, then the `data:` commands the base declares, run by `exec` inside the services once they are ready — so a changed service migrates with the change's own migrations |

**"What was tested" now means the same commit, not the same container.** The box is a development
environment — a toolchain, a harness — and not the image a service ships in; running a product out
of boxes would preview something that is neither what was tested nor what will run. The commit is
the one that passed `validate:` and the review. The caveat the first version recorded still holds:
`JobRunner._auto_merge` rebases onto a moved base and re-validates, so the commit that lands may not
be the commit previewed; the gates, re-run after the rebase, are what hold the merged result.

**Building runs the change's Dockerfile**, which the agent may have written. It is the box's trust
level and no more: built by the same daemon, by a compose process whose environment is reduced to
`PATH`, a `HOME` and `TMPDIR` inside the unit's work directory, the daemon's own `DOCKER_*`
variables, the operator's pull-credential directory, the preview's URLs, and the values of exactly
the worker variables the registry names for the unit's services. None of the factory's credentials
and none of `box.env`; a build receives as arguments only the public URLs and what the operator
listed under `build_args` (D8).

**Each service is told where the others are.** Every service receives, for each exposed service,
`OPENFACTORY_PREVIEW_URL_<SERVICE>` (the address a browser opens) and
`OPENFACTORY_PREVIEW_INTERNAL_URL_<SERVICE>` (`http://<service>:<port>`, for a server-side call); a
built service receives the first as a build argument too, so a bundler that bakes it in at build
time gets it.

**Ready is judged, and said.** An exposed service is ready when its healthcheck passes (`healthy`)
or, with none, when it runs (`started`) — the card says which, because the second proves less; a
service that exits 0 ran and finished (a `migrate:` one-shot); any non-zero exit is the failure,
named, with its last lines. Then a settle window, then the data commands. Nothing restarts a
service on its own (`restart: "no"`); the workflow watches (D6).

**Contained by the operator's policy**: `cap_drop: [ALL]` plus the capabilities the registry
leaves, `no-new-privileges`, a process limit, CPU and memory per service, a service count and a
memory total per unit, `tmpfs` sizes.

**Data is never a copy of production.** A preview is a place where somebody clicks through code
nobody has merged yet; real people's data does not belong there (LGPD/GDPR). Realistic data comes
from the seed the client declares — a sanitised snapshot is a seed like any other, and producing
one is the client's decision, not the factory's.

**Refused, by name, rather than shown wrong:** a unit with no pull request open; a change in no
service's inputs (every service runs a published image and mounts nothing, or the diff touches only
files no service is made from — the refusal names the paths and the services, and the fix is a
`build:` for the service the repository builds); a unit over the operator's service or memory
budget.

**Amended (2026-09-24, #277, #278, #287):** the first text said a base service's image is pulled
with "the daemon's" credentials. A registry login is client-side — the compose CLI reads it from its
configuration directory, and the daemon holds none — so the credentials are the operator's, in
`OPENFACTORY_PREVIEW_DOCKER_CONFIG`, written by `openfactory preview login <registry>`, and a pull
refused as unauthorized fails by name with that command. Readiness (Left open 1) was measured before
it was chosen: `docker compose up --wait` exits 1 the moment a one-shot exits 0, which reads the
commonest development compose file as a failed stack, so readiness is read from `docker compose ps`,
never `--wait`. The record calls it `health`, not the design's `readiness`, because the action
layer's guard reserves that word. Measured live on Docker Desktop (#278): six planted values —
factory credentials, and two names the compose file reads — appear in no container's environment,
in no image's history or inspect output, and not in the compose file the runtime wrote.

### D5 — A requirement across repositories is previewed whole, and says what is missing

When D1's unit spans repositories, its preview combines the pull requests of all its cards: each
touched service from its own repository's change, the rest from base. A requirement's token is
`req0012`, a card's its number, and every name a preview wears — its hosts, its key, its cookie, its
compose project — carries it.

- **Its cards are found on the board**, by what each card says it executes: its `## Source` line,
  or, on a defect card, the heading naming the promise it breaks. A card is a sibling only if its
  repository is one of the product's `sources:` and its pull request is the one the factory opened
  on its own branch in that repository, open as the forge reports it. A card in a repository
  outside `sources:` that cites the same requirement is never joined, and the preview says so.
- **While a sibling's pull request is not open yet**, that part of the product runs from base, and
  the preview says so on its face — *"the back end is still the current version; its change is not
  ready"* — rather than presenting a half-built feature as the feature.
- **When the product context cannot be used at the offer** (the product module off, or its context
  unavailable), a card that cites a requirement is previewed alone, and its card says why. A
  board that cannot be read at the start does not change a unit whose key was fixed at the offer:
  the preview holds the cards that offered themselves, and says what it could not find.
- **Filing in the right repository** is built beside it: the tracker port files a card in another
  repository of the product when the product role names one inside `sources:`, and in the default
  repository, said, when it names one outside.

Which change must land before which is ADR-0036's question; it is Proposed and not built, so the
preview combines whatever pull requests of the unit are open.

**Amended (2026-09-24, slice 5):** the first text left the siblings' search and its bound unsaid. It
is bounded by `sources:` and by the factory's own branch because a card anyone can add to a board,
citing a requirement, would otherwise have its repository checked out beside the product's.
Measured limits, not fixed: preview records are keyed by card number, so two cards of one
requirement with the same number in two repositories would collide; a card filed in another
repository gets a qualified reference the delivery ledger skips, so no "it's done" follows it; and
a `sources:` entry spelled in full on Azure DevOps (`org/project/repo`) does not match the board's
`Project/repo`, so that sibling is left out, and said.

### D6 — On demand, bounded, and ended

A whole product per pull request is not free: several builds, several containers, minutes to start.
So:

- **On demand.** When a pull request waits for a person, the job records the preview as offered —
  it never starts one and never touches a runtime — and the card offers *start a preview*. The
  person is told it takes minutes, and the card says when it is up. `start` is refused while the
  unit has no pull request open, before anything is cloned.
- **One workflow per unit** (`preview--<project>--<unit>`): materialise, plan, bring up, then a look
  every minute while it lives; `stop` and `rebuild` are signals; a second start of a unit that is
  already running is refused by the engine rather than becoming a second stack. Every step runs
  once, with a heartbeat and no retry: a failure is recorded on the card, never retried into a
  half-created stack.
- **A fresh checkout for every start.** The base of every repository the unit needs is cloned by
  branch name, and the change checked out beside it at the head the forge reported; a work
  directory that exists is removed first, never reused. What the card shows is judged when it is
  read: a pull request whose branch has moved past the head the preview was built from makes it
  **stale** — *"rebuild"* — and the merge gate shows the same badge.
- **Bounded.** A cap on previews running at once per deployment (`OPENFACTORY_PREVIEW_MAX`, 4 when
  unset); a start beyond it is refused naming the previews that are up, never queued in silence.
  Per unit, a service count and a memory total; per service, CPU and memory limits (D4).
- **Ended** when its time is up (hours, set by the registry, clamped to a week), when every pull
  request of the unit has merged or closed, or when an exposed service stops — the whole environment
  with it: containers, networks, volumes, the images built for it (D10).
- **The same doors from a shell**: `openfactory preview start|stop|restart|read|logs|ls`.

**Amended (2026-09-24, #287):** made concrete as above. Four choices the design did not make: the
head of a pull request is read with `git ls-remote` on the forge's own remote, because the forge
port has no method for it (the port is unchanged), and a forge that cannot be read is never taken
to mean "no pull request"; a unit with more than one pull request open in the same repository is
refused by name; the cap's default of 4 was chosen here, from the 8g memory total one unit may
reserve by default, and is the operator's to change; and a start that failed after something reached
the daemon is kept, so its logs can be read, and removed by the reaper after `keep_failed_minutes`.

### D7 — Each exposed service on a host of its own, never on the panel's

A preview runs agent-written code, and the panel's credential is deliberately readable by any
script on the panel's own origin: `openfactory_token` is not HttpOnly, and the page keeps a copy in
localStorage — the OIDC callback in `api/app.py` says so in its own words (*"a script on this
origin can read the credential"*). A preview served under the panel's address would read the
credential of whoever opened it and could act as that person: answer a gate, approve a merge,
release. A different **port** does not help: browsers send a host's cookies to every port.

- **Every exposed service gets one host** — `<service>--<project>--<unit>.<preview domain>`, one DNS
  label so a single wildcard record covers them all; a long project name is shortened in the middle
  and the unit is never the part cut. It is answered by a router in front of the panel that never
  lets a host under the preview domain reach the panel's routes, even one that names no preview.
- **The way in is a key to that unit only**, minted by the panel for somebody it already let in
  (readable by the floor and the product areas alike — the person who asked for the change is who
  the link is for). The key in a link lives ten minutes, because a URL is kept by access logs and
  browser history; on the service's host it becomes an HttpOnly cookie that exists only there and
  holds a fresh key lasting as long as the preview. One click opens every exposed service: the
  doors chain through the unit's hosts, each hop chosen among the unit's own services only. A
  person never types the address; the card's button opens it.
- **The router's target is derived from the name**, never read from a record: the service's alias
  on its unit's own edge network on the compose stack, `127.0.0.1:<port its name derives>` on one
  machine. The browser's `Host` is forwarded unchanged, so an application's absolute URLs and
  redirects are the preview's own; a `Location` naming the alias is rewritten. A first page that
  does not answer in time is *"still starting"* (504); a refused connection asks whether the service
  listens on `0.0.0.0:<port>` (502).
- **One edge network per unit.** The worker, which holds the daemon's socket, connects the panel's
  container to that unit's network when it comes up and disconnects it when it goes down; no network
  is shared between two units, so one unit's services can neither resolve nor reach another's
  (measured live).
- **Nor may a preview write the panel's credential.** Whenever the preview domain shares a parent
  with the panel's host — the default `preview.localhost` beside `localhost` does — a script there
  can set a cookie with `Domain=` the parent, named like the panel's, through `Set-Cookie` or
  `document.cookie`. So the router drops any `Set-Cookie` that carries a `Domain` or names a cookie
  of the platform's, keeps host-only cookies (an application's own login works), and never sends
  the platform's cookies or an `Authorization` header upstream — the per-unit preview cookies
  matched by prefix; the panel treats a credential cookie that arrives twice as no cookie, on the
  server and in the page; every panel response forbids framing (`frame-ancestors 'none'`,
  `X-Frame-Options: DENY`). Over TLS — the scheme, or `x-forwarded-proto: https` from a terminator —
  the panel's credential is `__Host-openfactory_token` (#271), which no sibling host can set, and
  over TLS the panel reads no other spelling. On plain http the prefix cannot be used, and there a
  preview domain that shares the panel's registrable domain is refused by `openfactory doctor`,
  which reads the panel's scheme from `OPENFACTORY_PANEL_URL` (a panel on `localhost` or an IP
  address, and a preview domain under `localhost`, are excepted): a deployment reached by name gives
  previews a registrable domain of their own, the way `githubusercontent.com` is not `github.com`,
  or serves its panel over https.
- **On one machine the port is a second door.** ADR-0049's local kind has no Docker by default, and
  previews there are off until a person opts in. Opted in, the panel is a process on the host that
  cannot use the daemon's DNS, so each exposed service is published on `127.0.0.1` alone, on a port
  derived from its host label within `OPENFACTORY_PREVIEW_PORTS`; a derived port something already
  holds fails the start by name, before anything is built. Anyone on that machine, and the job box,
  can open that port without the key. What a preview there reaches is measured at every start and
  said on its card (D8).

**Amended (2026-09-24, #270, #287, #292):** the first text gave the link's key hours; it lives
minutes, and the cookie carries a key of its own. The shared `openfactory-preview` network was
written for one preview at a time and is gone: one edge network per unit, the panel joined by the
worker (`doctor` says to remove the old network once). `__Host-` landed before any preview could
start, as the design required. The loopback reach is new: the first text had one reach, the
design on #265 proposed a second for one machine, opted into, and the product owner accepted it
over keeping previews off that door altogether.

### D8 — Secrets: a tier of their own, never the build's, never production's

`box.env` (ADR-0037) carries what a BUILD needs — a private registry, a scanner, the harness's
provider — and a preview runs the APPLICATION: one booted with a real payment, e-mail or staging
credential is one click from a real side effect. So a preview's secrets are their own tier, in the
**registry** (operator-owned — the agent edits the manifest, so it must not pick its own secrets),
holding only non-production values a person clicking through may safely trigger:

- **`preview.env`, per service** (`*` for every service), names what a service may receive, and in
  its map form which WORKER variable holds the value — `{api: {DATABASE_URL: ACME_PV_DATABASE_URL}}`
  — so two projects on one worker can hold different values under one name. A value reaches a
  container as a reference the compose process resolves, never on disk, in argv or in a label.
- **`preview.build_args`**, a separate list, empty by default: the names that also reach a build of
  a service from the change. An unmerged Dockerfile with internet access can read a build argument,
  and it lands in the image's history.
- **The factory's own credentials are refused** in either list, on either side of a mapping, at the
  write and at the read: `OPENFACTORY_*`, `TEMPORAL_*`, `ANTHROPIC_*`, `CLAUDE_*`, the known vendor
  tokens and every project's `token_env`. Dropped and said, never fatal, because the registry is
  baked into the worker.
- **The operator's door** is `openfactory project set-preview`, read back with `openfactory project
  show`; nobody edits a file on a volume.
- **Nothing else reaches a preview's process.** Admission rewrites every `${X}` the file reads that
  the registry does not name, the project's own `.env` is never used for interpolation, and the
  compose process's environment is the reduced one of D4. An `env_file` the base commits is read as
  base-tier data — it is the client's merged file — and the drafter of D12 flags credential-looking
  rows in it. The preview key's signing secret is scrubbed from every workload.
- **Egress is closed.** A unit's own network and, on the compose stack, its edge network are
  internal: a preview reaches its own services and the panel, and nothing outside — not the
  internet, the engine, the worker, another unit, or the host itself (the gateway, amended below
  for #291). Reaching out is the
  registry's `preview.network`, an operator network the services also join (`bridge` and `host`
  refused), and the card says so.

**Amended (2026-09-25, #291): internal was not closed.** An `internal` network keeps its bridge's
address on the host, and a container on it reached a listener on `0.0.0.0` of the host through
that gateway — measured on Docker Engine 29.1.3, from a plain internal network. Every network a
unit runs on (its default network, and its edge on the compose stack) is now made with
`com.docker.network.bridge.gateway_mode_ipv4=isolated`, which gives the bridge no address on the
host: measured the same way, it reached none of the host's fifteen addresses nor the internet, and
its containers still reached one another by name. Admission refuses a default network without it.
The option is READ BACK rather than trusted, because an engine that took it and ignored it would
say nothing: the worker asks the engine on a network made for the purpose before a unit starts,
reads back the edge it made (one left from before was made by whatever made it), and reads back the
default network `up` made, taking the unit down at once if it has a gateway. A preview that cannot
be closed off does not start, and its card says why. The engine accepts the option on internal
networks only, so the one-machine reach (D8), whose published edge cannot be internal, keeps saying
what it reaches.

**Amended (2026-09-24, #277, #292):** the tier moved from `box:` to its own registry block, and
gained the container→worker mapping, the separate build list and the denylist. The product owner
kept egress closed by default: an application that needs an identity provider or a package at
start does not come up until the operator names a network. **One machine is not closed.** Docker
forwards no published port into an internal network, so a loopback preview's edge network is a
bridge that masquerades nothing, which the design expected to leave its outbound packets
unanswered. Measured on Docker Desktop 29.1.3 (compose v2.40.3, macOS
26.6.2), it stops nothing: a preview container reached the internet, and the Mac's own services
bound to `127.0.0.1` through `host.docker.internal` — the panel (which a laptop's `init` leaves
without a token), the engine and other previews' ports among them; the Mac's LAN address timed out.
It is not a new capability on that door — the job box there already runs the agent's code as the
person, with the same reach, and previews are opted into — so the card and `doctor` measure it
and say it, every time, rather than claim it. Linux was not measured.

### D9 — A pre-merge look, gated where auto-merge already is, and not ADR-0025's acceptance loop

ADR-0025 closes a *delivery*: a conversational confirmation, in the client's own words, chased once
at 72h, never closed by silence — necessarily after the thing exists somewhere stable enough to use
for real. Reusing that machinery here would break its own invariant: a merge cannot sit open for up
to 72 hours waiting on a chased reply without stalling every card behind it.

**The person who merges is the acknowledgement.** A project that requires a preview is never merged
by the factory on its own; its pull request goes to a person, who looks at the preview and merges —
or does not. Nothing new records a "looks right": the merge click on the forge already is that
record, carried by the forge's own branch protection. Under `merge_policy: human` that is today's
behaviour and the preview is one more link for the person who was going to merge anyway. Under
`merge_policy: auto` it is one more refusal in `orchestrator/merge_policy.py::should_auto_merge`,
where every other reason an auto-merge is refused already lives and which *"can only subtract from
the answer, never add to it"*; the pull request then goes down the ordinary
`forge.request_reviewers` branch.

**How a project requires one** (Left open 2 of the first text): `preview.required` in the
registry, set by the operator with `openfactory project set-preview <name> --required` — never the
manifest, which the agent edits. It reaches the merge gate as a declared hold on the run's result
(`preview_required`), and the pull request's body names it. A project that requires previews on a
deployment whose runtime is `none` is said by `doctor` and on the card: its pull requests wait for a
person who can never look. The merge gate shows whether the preview is live or stale, so what a
person acknowledges is a commit somebody previewed.

Rejected, and recorded so they are not retried:

- **`RiskPolicy.gates` promotion.** A gate there is a shell command whose exit code is the verdict,
  run by `_run_validations`, kept reusable against `onboarding.firstrun._GateHost` with nothing on
  `self` but `sandbox`, `manifest` and `_emit`. A person looking at a running product is not an
  exit code. The automated half — a smoke test against the assembled preview — is one, and can be
  an ordinary `validate:` role (§ Left open, 1).
- **A third `merge_policy` value.** `merge_policy` answers *who merges*; a preview answers *what
  must have been seen first*. One value meaning both would, under `human`, be a gate that gates
  nothing.
- **Park the job with the preview up, and merge on a click.** The job is serial — `_auto_merge`'s
  own docstring: *"merge-queue-lite; the framework is serial"* — so waiting in it stalls every card
  behind it; parking needs a resume path the merge posture does not have. It buys "merge without a
  person clicking merge" at the price of a person clicking something else.

**Amended (2026-09-24, #277):** the design passed `preview_required` to `should_auto_merge` as a
keyword; it was built as a field of the run's result, like the gate's other declared holds, so the
function still receives no registry object.

### D10 — Ending is an invariant with its own watcher

A preview nobody is looking at is reclaimed, never left running — ADR-0020's posture: a thing
blocked long enough is *forgotten*, not *waiting*. A deployment-wide reaper, its own workflow on its
own schedule (`openfactory-preview-reaper`, every ten minutes, so no in-flight history's command
sequence changes), asks the deployment's runtime what it holds — exited stacks included, because a
crashed preview is exactly the one nobody else will take down — and ends every preview whose time
is up, whose every pull request merged or closed, whose exposed service stopped (recorded `failed`
at once, removed after the operator's `keep_failed_minutes`, so its logs can be read first), or
whose start never finished (a worker restarted mid-build), and records why so the card can say it.
A pull request whose state could not be read keeps its preview until the clock ends it — never the
reverse.

**Logs before every down** — every service's log and the build's are kept where the card links to
them (`openfactory preview logs`), because a stack taken down first leaves nobody able to say why it
failed. Then the stack, its volumes and the images built for it; a work directory left with no
stack behind it once the longest a preview may live has passed; and, where the runtime keeps caches
between units, the images and build cache previews left.

**Deleting is limited to what the factory derives**: compose projects, networks and work
directories whose names start with `openfactory-pv-`, directly under the work root and never
through a symlink. A label is metadata anybody with the daemon can write, so it is read to find a
preview and never to authorise a delete. Files a container left owned by root in a mounted tree are
removed through the daemon, under the same rule.

**Amended (2026-09-24, #278):** pruning is an optional capability of a runtime rather than an
eighth method of the port, because a runtime that keeps nothing between units has nothing to prune.
Images are pruned by the compose-project prefix — measured, built images carry only compose's own
labels — and the build cache by age (older than a week), because `--keep-storage` is deprecated in
newer CLIs.

### D11 — No cloud; the runtime is an adapter axis

ADR-0040 D2: everything that circulates runs on the client's own machines; D3 makes a cloud an
add-on whose absence must not hobble the platform. The core ships the `preview` axis with two rows:
**`compose`**, on the client's own Docker daemon through the compose CLI the worker image carries
(pinned to v2.32.4), and **`none`**, which runs nothing and says so by name on every card, in
`doctor` and in `preview prove`. A Kubernetes namespace per preview, or a vendor's ephemeral
environments, is a `preview.<kind>` row an add-on declares, never a vendor in the core.

- **The kind is the deployment's**, like the box's: `OPENFACTORY_PREVIEW_RUNTIME`, `none` when
  unset — the compose stack's file sets `compose`, one machine writes `none` until its person opts
  in, and a cloud worker, which holds no daemon, is `none`. Nothing a repository declares moves it;
  it is resolved on the activity side, and the workflow reads it as data.
- **What crosses the port is data.** A row receives a `PreviewPlan` — the admitted compose document
  plus its provenance: the layout of every tree (clone URL, base branch and commit, branch and
  change commit) and every path the document carries as `(tree, side, rel)` — enough for a row on a
  machine the worker cannot see to check out the same trees itself. It answers data. A row
  re-judges what it is handed with `refusals(plan)` (`openfactory/adapters/preview/base.py`), and
  the conformance suite (`openfactory conformance-adapter preview …`) hands it a plan no assembler
  produces, to see that it refuses to run it.
- **Every binding** the other axes carry: `plugins.AXES`, the stranger add-on's row and its
  conformance forms, `conformance.CHECKS`, the serialisable-port guard, CONTRIBUTING.md's list,
  `docs/core/07-extensibility.md`'s ledger and `docs/writing-an-addon.md`'s table;
  `docs/architecture.md` §6 stays at eight rows. There is no reader axis: the compose reader is the
  one reader, and a second (a Helm chart) waits until one exists.

**Amended (2026-09-24, #278):** the design's `compose` row was built with two deviations. The base
is cloned with `--no-hardlinks`, not git's default: a container running as root that mounts the tree
could otherwise write through a shared object into the repository cache every later job reads (a
test checks each object has one link). And git runs with the worker's environment plus
`GIT_TERMINAL_PROMPT=0`; only the compose process gets the reduced environment of D4.

### D12 — A drafted shape is a proposal, never a guess at run time or a build on the operator's machine

A repository that cannot say how it runs — no compose file, or one that names only published
images, or no Dockerfile at all — gets that said *for it*, as a draft that restates only what the
factory read, on a pull request a person merges:

- **Read, not invented.** `openfactory preview propose <project>` drafts from a checkout of the
  base, and the drafter reads files only — it runs nothing, opens no socket, and follows nothing out
  of the tree through a symlink. Every line of the draft is tiered `observed`, `inferred` or
  `unknown`, cited to the file and line it came from. An `unknown` carries the question a person
  answers; observed lines are written, inferred ones with `--accept`, and
  `--set preview.expose.app=8000` answers one. `openfactory preview draft <project or path>` shows
  the same draft and writes nothing.
- **What is read.** A compose file that exists: the `preview:` block for it, and an override that
  adds a `build:` where the file names only an image a Dockerfile of the repository builds. No
  compose file: one service per Dockerfile at the root or one directory down — deeper ones and two
  in one directory are asked about, never guessed — each with the port its `EXPOSE` names; a data
  store read from a dependency marker, with that image's own healthcheck and the application waiting
  on it; the preview URL names written only where `.env.example` reads them. No Dockerfile: one is
  drafted only when a start command is anchored in a file actually read (a `Procfile`, a
  `package.json` start script, a `Makefile` target, `manage.py`), copying the paths the survey read
  rather than the whole tree, beside an ignore file that keeps `.git` and `.env*` out of the image.
  Nothing anchored, no draft: the questions only, and `--as-card` files them as a card instead.
- **Where it goes.** Under `.openfactory/` (`preview.compose.yml`, `preview/<service>.Dockerfile`,
  `preview/<service>.Dockerfile.dockerignore`), so it never collides with the team's own files; the
  block is appended to the manifest with every comment kept, and a file that cannot take an append
  is rewritten whole with that said. For a product, `--product` drafts into the context repository,
  from every source's Dockerfile side by side.
- **Its own pull request**, on `openfactory/preview` — never part of the first manifest's
  (`onboard --with-preview` opens it after that one, and where the manifest is itself only proposed
  in the same run, says to propose the preview once it merges) — whose body says what merging it
  lets the factory do, service by service, and that anyone the panel lets into the project can
  start it on the factory's daemon. Values that are secrets go to a list *for the registry, not this
  file*, and a literal that looks like a credential is flagged by name, never quoted. For a project
  registered by a local path, the one-machine shape, the files are written into the checkout,
  *"commit these"*.
- **Never built before a person merges it, unless `--prove` asks, and never on the operator's
  machine.** Nothing from the repository runs where the command was typed. `--prove`, where the
  deployment names a runtime, brings the base branch with the draft applied up once on the
  deployment's own daemon, through the same reader, admission and runtime a card's preview uses,
  takes it down, and puts the result in the pull request; without it the body says *"Not built"*.
- **The factory never opens a proposal from a card.** A card whose base declares no `preview:` says
  so, and names the open proposal or the command that opens one; that sentence is computed when the
  card is read, because the proposal is merged after the job ran, and once it merges the pull
  request someone was waiting on can be started.
- **No implicit preview.** A repository with one root Dockerfile is the one case that could be
  previewed with no declaration. It is not: *declare nothing, and nothing changes* (D3) is what
  keeps a project that never asked from growing a button that runs agent-written code on the
  operator's daemon, and that repository's draft is wholly observed — one merge.

**Added (2026-09-24, #288 and slice 5)**, with the product owner's decisions that the factory may
draft a Dockerfile under the anchoring rule and that no implicit preview exists. Built beyond the
design: credential detection also matches `PASSWORD`, `PASSWD`, `PASS`, `PRIVATE`, `CREDENTIAL`
and whole lines, and a Dockerfile or `Procfile` line holding a secret is never quoted or copied; the
service drafted for a root Dockerfile is named after the repository's short name; a data question is
asked only for a service that depends on a store; `--as-card` files a card in every case; `--prove`
runs through the deployment's runtime row in the process that ran the command, refused unless the
runtime's prerequisites hold — which is why it runs inside the worker on the compose stack. The
ignore file is `<service>.Dockerfile.dockerignore`, not the design's `<service>.dockerignore`: measured on
Docker Desktop 29.1.3, BuildKit honours the first beside a Dockerfile and ignores the second. A
draft that is the only compose file resolves against `.openfactory/`, so its `..` is the repository
root (measured on v2.32.4). The card reads the job's own checkout — inside the tree, never executed
— while `preview propose` reads the base. For a product: `--product` works on hosted repositories
only (refused on the one-machine kind, and with `--prove`, `--source` or `--as-card`), and a source
with no Dockerfile is asked about in the product's pull request instead of getting one of its own.

## What this does NOT mean

- **Not a deploy.** The factory still does not deploy (ADR-0005; ADR-0040 D1). A preview is
  disposable and never becomes an environment anybody promotes into; staging stays the client's
  pipeline's business.
- **Not a replacement for ADR-0025's acceptance loop.** Business acceptance still happens after
  delivery, in the client's own words.
- **Not a prerequisite.** No `preview:` block, no preview, no gate of its own, no migration. The one
  thing every project gets is the compose file names on the floor (D3).
- **Not a loosening of `validate:`.** The preview happens after the quality floor is met.
- **Not production data**, ever (D4).
- **Not a guess.** A preview runs only a shape a person merged (D3); a draft is built before its
  merge only when `--prove` asks, and only on the deployment (D12).

## Consequences

**Good.** The one point where this platform can still stop an outcome it cannot undo gains a real
check: a person who asked for something sees the product with that thing in it, before it is too
late to say no. The factory's existing knowledge — what a diff touched, the repository a card lands
in, the client's own compose file — becomes what assembles it, instead of a second description.

**Costs and risks, declared.**

- **A preview is several builds and minutes of start-up.** Hence on demand, capped, and bounded per
  unit and per service (D6). A client whose compose file names published base images pays for the
  changed services only.
- **A change to the shape is previewed with the old shape** (D3). Honest, stated on the preview, and
  the price of never running a compose file the agent wrote.
- **A change to a compose file at a repository's root waits for a person in every project** (D3),
  under `merge_policy: auto` too.
- **Building runs a Dockerfile the agent may have written, with egress.** The box's trust level
  (D4): what is bounded is what a build can read — no factory credential, only the preview's URLs
  and the operator's `build_args`.
- **Egress is closed by default** (D8): an application that needs something outside to start does
  not come up until the operator names a network.
- **The panel's listener is reachable from an exposed service** over the unit's edge network — the
  panel must be on it to proxy. Its routes are authenticated and its credential never reaches a
  preview, but a preview can talk to its HTTP surface from inside the daemon. On one machine,
  measured on Docker Desktop, a preview reaches the internet and the machine's own loopback (D8).
- **A bigger attack surface than a stopped container.** D7 and D8 held before any of this could
  start, not added after.
- **Ending is a new invariant** (D10). This codebase's history (ADR-0009, ADR-0020) is that such
  invariants fail quietly unless something watches them; it has a watcher and its own tests.
- **Across repositories it waits on ADR-0036**, which is Proposed and not built (D5).
- **A project that requires a preview gives up auto-merge** for the cards it applies to (D9).
- **Pull credentials are the deployment's**, not a project's: the registries a preview may pull
  from are the ones `OPENFACTORY_PREVIEW_DOCKER_CONFIG` holds.
- **Disk**: two working trees per repository per unit plus the images built, bounded only by the
  cap and the reaper.

## Left open, deliberately

1. **Readiness.** *Closed (2026-09-24):* judged from `docker compose ps` and said on the card (D4).
   Whether a smoke test against the assembled preview runs as a `validate:` role before the link is
   offered is still open.
2. **How a project says it *requires* a preview.** *Closed (2026-09-24):* `preview.required` in the
   registry (D9). Whether it can be scoped per component, the way `risk` is, is still open.
3. **WebSockets through the router** — a hot-reloading dev server or a live feed needs them. The
   router does not carry an upgrade today.
4. **A seed that looks like production.** The mechanism is the client's seed (D4); whether the
   factory helps produce a sanitised one is a later decision, and a sensitive one.
5. **A proxy per unit.** The panel's listener reachable from an exposed service (Consequences), and
   what a loopback preview reaches on Docker Desktop (D8), close only with a proxy container per unit
   that keeps exposed services off any network the panel or the host is on. That is a design change,
   left for a decision.
6. **Closed (2026-09-25): a Linux engine** (#291). Measured on Docker Engine 29.1.3: a container on
   an internal network reached a listener on `0.0.0.0` of the host through the network's gateway.
   Every unit network now has no gateway on the host, and that is read back, not assumed (the
   *Egress is closed* amendment above).
7. **A reader-side proof that a shape was merged by a person.** On a squash-merging forge the base
   commit's author is the platform's identity even when a person merged, so the context repository's
   shape is guarded at the factory's writers (D3), not proven from history; the proof waits for a
   forge-port method that answers which pull request landed a commit.
8. **What D5 measured and did not fix**: card numbers that collide across a requirement's
   repositories, a card filed in another repository that is not followed up, and fully spelled Azure
   DevOps `sources:`.
9. **Smaller**, each its own record when it is taken up: `.dockerignore` in D2's inputs; a service
   the change adds does not exist in its preview; per-project pull credentials; `doctor` does not
   yet print the compose version, the registries the pull directory holds, the disk a full cap would
   take, or the factory's own volume names.

## History

- **2026-09-22 — first version.** A `serve:` command in the manifest; the one container that passed
  `validate:` kept alive and served as the preview.
- **2026-09-23 — security amendment** (found while implementing, #270). Serving the preview under
  the panel's address would have exposed the panel's credential to agent-written code; a preview
  got a host of its own and a key to it, and — from Hermes's review — the panel's credential was
  protected in the other direction too. Now D7.
- **2026-09-23 — the product, not the container.** The product owner's review: an application is at
  least a front end, a back end and a database; a preview of the part that changed shows the person
  who asked for it nothing. The single-container design was replaced by this one — the unit the
  person asked for (D1), the diff as the truth of what changed (D2), the client's compose file as
  the shape (D3), the product assembled from change and base (D4–D5), on demand (D6). #270 had
  implemented the single-container version; its host, key, cookie, framing, secret-tier and reaper
  machinery is D7–D10 and carries over, and its `serve:` manifest field is replaced by `preview:`
  before anything ships.
- **2026-09-24 — built, and amended to say what was built.** The design on #265 took this record's
  decisions to an implementable form, and the product owner accepted its recommendation on each of
  its six open decisions: no implicit preview; the factory may draft a Dockerfile, anchored and
  person-merged; egress closed by default; one machine may opt in; the compose file names floored in
  every project; the proposal before the multi-repository slice. Slices 0–6 built it on open pull
  requests — #270 (names, key, record, router; `__Host-`, #271), #277 (the contracts and the pure
  reader, admission and assembler), #278 (the axis and its two rows), #287 (on demand), #288 (the
  proposal), slice 5's (several repositories) and #292 (one machine) — none merged. D2–D11 are
  amended in place and D12 is added, each saying where the build departed from the design and why.
  What measurement during the build found that the design did not expect: the compose plugin the
  worker carries refuses a flag the design named (D3); an override resolves against the first file's
  directory (D3); BuildKit reads a different ignore file name (D12); on Docker Desktop the
  one-machine edge network stops nothing (D8); and an internal network's packets reach its bridge's
  gateway, which is #291.
- **2026-09-25 — merged, and the host closed off.** The eight pull requests landed together, one
  commit each, with #291 closed on the way: an internal network reached the host through its
  gateway on a Linux engine, and every network a unit runs on is now made with no gateway on the
  host, read back before anything runs.
