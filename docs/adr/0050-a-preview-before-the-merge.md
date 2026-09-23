# ADR 0050 — A preview before the merge, because nothing after it can be taken back

- **Status:** **Proposed** (design only). Revised on 2026-09-23 from a single-container preview to a
  preview of the whole product — see *History* at the end for what changed and why.
- **Date:** 2026-09-22
- **Relates to:** ADR-0001 D-6 (components: what a diff touched), ADR-0005 (post-merge deploy watch,
  and the read-only contract it gave the `environment` adapter), ADR-0025 (delivery closes with the
  client — a different gate, in a different place), ADR-0026 (a word the reader already has beats
  one you invent), ADR-0036 (ordering across repositories), ADR-0037 (the box), ADR-0038 (the panel
  is the reference surface), ADR-0040 (the core runs on the client's own machines; a cloud is an
  add-on), ADR-0048 (the preflight's `touches`), #266 (the product is the boundary: the context
  repository and its `sources:`), #268 (the system layer).

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

### D2 — What changed is read from the diff, never predicted

The factory already knows what a change touched, at three moments, and the preview reads the last:

1. **Before it starts, an estimate** — the preflight's `touches` (ADR-0048).
2. **At the breakdown, the repository** — D1's one card per repository.
3. **After it is done, the truth** — the diff, mapped to the manifest's `components:` by their
   `path:` globs (ADR-0001 D-6: *"front/back/devops are not different agents — they are different
   manuals + permissions + risk that the same worker wears depending on what the diff touches"*).

A preview is assembled from (3). An estimate that said "back end only" does not keep a front-end
change out of the preview; the diff does not lie about what it contains.

### D3 — The product's shape is declared once, by pointing at the client's own compose file

Most applications already carry a compose file for local development that says which services
exist, how each is built and what each needs. The factory is not taught a second way to say that;
it is pointed at the one that exists, and told the three things the compose file does not know:

```yaml
preview:
  compose: docker-compose.yml          # the client's own file, read from the BASE branch
  services:
    web: {component: front}            # this service is built from this component
    api: {component: back}
    db:  {}                            # no component: never taken from a change
  expose: [web, api]                   # what a person may open; everything else stays inside
  data:
    api: "python manage.py migrate && python manage.py loaddata demo"   # fresh data, every time
```

- **Where it lives.** In one repository, or a monorepo, in the project's manifest. For a product
  of several repositories, in the context repository's `.openfactory/product.yaml` — the product is
  the boundary (#266) — where each service names its **repository** and component. That is the
  same topology the system layer (#268) describes, and the two are one map, not two.
- **Read from the base branch, never from the change.** The compose file and this block are files
  in the repository the agent edits. A preview assembled from the change's own compose file would
  run whatever the change declared — a privileged service, the host's network, the host's
  filesystem, the daemon's socket. So the topology is the base branch's, and a change that alters
  the topology itself is previewed with the old one (said on the preview, not hidden). On top of
  that, the assembly refuses what no preview needs: `privileged`, `network_mode: host`, host bind
  mounts, the docker socket, added capabilities, devices, and published ports (nothing is reached
  except through D7).
- **Declare nothing, and nothing changes.** A project with no `preview:` gets no preview — the rule
  ADR-0038 and ADR-0049 D1 apply to every optional row.

### D4 — The assembly: the change where it touched, the base everywhere else, fresh data always

For one unit (D1), with the diffs of its pull requests (D2) and the topology (D3):

| service | runs |
|---|---|
| its component was touched by the change | **built from the change's validated commit, with the client's own Dockerfile** (the service's `build:` in the compose file) |
| not touched | the image the client's CI already publishes for the base branch, when the compose file names one (`image:`); otherwise built from the base branch |
| data (no component) | a fresh, empty volume, then the `data:` commands: the change's migrations when it touched them, the base's otherwise, and the seed |

**"What was tested" now means the same commit, not the same container.** The box is a development
environment — a toolchain, a harness — and not the image a service ships in; running a product out
of boxes would preview something that is neither what was tested nor what will run. The commit is
the one that passed `validate:` and the review. The caveat the first version recorded still holds:
`JobRunner._auto_merge` rebases onto a moved base and re-validates, so the commit that lands may not
be the commit previewed; the gates, re-run after the rebase, are what hold the merged result.

**Building runs the change's Dockerfile**, which the agent may have written. It is the box's trust
level and no more: built by the same daemon, with none of the factory's credentials and none of
`box.env` — only the build arguments the registry names for previews (D8).

**Data is never a copy of production.** A preview is a place where somebody clicks through code
nobody has merged yet; real people's data does not belong there (LGPD/GDPR). Realistic data comes
from the seed the client declares — a sanitised snapshot is a seed like any other, and producing
one is the client's decision, not the factory's.

### D5 — A requirement across repositories is previewed whole, and says what is missing

When D1's unit spans repositories, its preview combines the pull requests of all its cards: each
touched service from its own repository's change, the rest from base. While a sibling card's pull
request is not open yet, that part of the product runs from base, and the preview says so on its
face — *"the back end is still the current version; its change is not ready"* — rather than
presenting a half-built feature as the feature. Which change must land before which is ADR-0036's
question; it is Proposed and not built, so until it is, the preview combines whatever pull requests
of the unit are open.

### D6 — On demand, bounded, and ended

A whole product per pull request is not free: several builds, several containers, minutes to start.
So:

- **On demand.** When a pull request waits for a person, the card offers *start a preview*; nothing
  starts on its own. The person is told it takes minutes, and the card says when it is up.
- **Bounded.** A cap on previews running at once per deployment, and CPU and memory limits per
  service. A request beyond the cap is answered with the previews that are running, not queued in
  silence.
- **Ended** when its time is up (hours, set by the registry, capped at a week), when the unit's
  last pull request merges or closes, or when an exposed service stops — the whole environment
  with it: containers, network, volumes, the images built for it (D10).

### D7 — Each exposed service on a host of its own, never on the panel's

A preview runs agent-written code, and the panel's credential is deliberately readable by any
script on the panel's own origin: `openfactory_token` is not HttpOnly, and the page keeps a copy in
localStorage — the OIDC callback in `api/app.py` says so in its own words (*"a script on this
origin can read the credential"*). A preview served under the panel's address would read the
credential of whoever opened it and could act as that person: answer a gate, approve a merge,
release. A different **port** does not help: browsers send a host's cookies to every port.

- **Every exposed service gets one host** — `<service>--<project>--<unit>.<preview domain>`, one DNS
  label so a single wildcard record covers them all — answered by a router in front of the panel
  that never lets a preview host reach the panel's routes. Each service receives every exposed
  service's public address in its environment (`OPENFACTORY_PREVIEW_URL_<SERVICE>`), which is how
  the front end finds the back end.
- **The way in is a key to that preview only**, minted by the panel for somebody it already let in
  (readable by the floor and the product areas alike — the person who asked for the change is who
  the link is for), valid for hours, exchanged on the preview's host for an HttpOnly cookie that
  exists only there. A person never types the address; the card's button opens it.
- **Nor may a preview write the panel's credential.** Whenever the preview domain shares a parent
  with the panel's host — the default `preview.localhost` beside `localhost` does — a script there
  can set a cookie with `Domain=` the parent, named like the panel's, through `Set-Cookie` or
  `document.cookie`. So the router drops any `Set-Cookie` that carries a `Domain` or names a cookie
  of the platform's, and keeps host-only cookies (an application's own login works); the panel
  treats a credential cookie that arrives twice as no cookie, on the server and in the page; every
  panel response forbids framing (`frame-ancestors 'none'`); the router's target is derived from
  the preview's name, never read from a record; and a deployment reached by name gives previews a
  registrable domain of their own, the way `githubusercontent.com` is not `github.com`. The case
  those leave — a browser holding no panel cookie being handed one — closes with the `__Host-`
  prefix on the panel's cookie (#271).

### D8 — Secrets: a tier of their own, never the build's, never production's

`box.env` (ADR-0037) carries what a BUILD needs — a private registry, a scanner, the harness's
provider — and a preview runs the APPLICATION: one booted with a real payment, e-mail or staging
credential is one click from a real side effect. So a preview's secrets are their own tier, named
per service in the **registry** (operator-owned — the agent edits the manifest, so it must not pick
its own secrets), holding only non-production values a person clicking through may safely trigger.
Nothing a preview runs receives the harness's credential, `box.env`, or anything the factory itself
holds; the preview key's signing secret is scrubbed from every workload.

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

### D10 — Ending is an invariant with its own watcher

A preview nobody is looking at is reclaimed, never left running — ADR-0020's posture: a thing
blocked long enough is *forgotten*, not *waiting*. A deployment-wide reaper, its own workflow on its
own schedule (so no in-flight history's command sequence changes), ends every preview whose time is
up, whose unit's last pull request merged or closed, or whose exposed service stopped, and records
why so the card can say it. A pull request whose state could not be read keeps its preview until
the clock ends it — never the reverse. Deleting what a preview left on disk is limited to what the
factory itself created: a label is metadata anybody with the daemon can write.

### D11 — No cloud; the runtime is an adapter axis

ADR-0040 D2: everything that circulates runs on the client's own machines; D3 makes a cloud an
add-on whose absence must not hobble the platform. The core ships one preview runtime, **compose on
the client's own Docker daemon**, reached through the router of D7 — plain Docker is enough for
D1–D10. A Kubernetes namespace per preview, or a vendor's ephemeral environments, is a row on a
`preview` adapter axis delivered as an add-on, never a vendor in the core.

## What this does NOT mean

- **Not a deploy.** The factory still does not deploy (ADR-0005; ADR-0040 D1). A preview is
  disposable and never becomes an environment anybody promotes into; staging stays the client's
  pipeline's business.
- **Not a replacement for ADR-0025's acceptance loop.** Business acceptance still happens after
  delivery, in the client's own words.
- **Not a prerequisite.** No `preview:` block, no preview, no gate, no migration.
- **Not a loosening of `validate:`.** The preview happens after the quality floor is met.
- **Not production data**, ever (D4).

## Consequences

**Good.** The one point where this platform can still stop an outcome it cannot undo gains a real
check: a person who asked for something sees the product with that thing in it, before it is too
late to say no. The factory's existing knowledge — the components a diff touched, the repository a
card lands in — becomes what assembles it, instead of a second description.

**Costs and risks, declared.**

- **A preview is several builds and minutes of start-up.** Hence on demand, capped, and bounded per
  service (D6). A client whose compose file names published base images pays for the changed
  services only.
- **A change to the topology is previewed with the old topology** (D3). Honest, stated on the
  preview, and the price of never running a compose file the agent wrote.
- **Building runs a Dockerfile the agent may have written.** The box's trust level (D4), with no
  factory secret in reach.
- **A bigger attack surface than a stopped container.** D7 and D8 have to hold before any of this
  ships, not be added after.
- **Ending is a new invariant** (D10). This codebase's history (ADR-0009, ADR-0020) is that such
  invariants fail quietly unless something watches them; it has a watcher and needs its own tests.
- **Across repositories it waits on ADR-0036**, which is Proposed and not built (D5).
- **A project that requires a preview gives up auto-merge** for the cards it applies to (D9).

## Left open, deliberately

1. **Readiness.** A service starting is not a service ready to click through. The compose file's own
   `healthcheck:` is the obvious reading; whether the card says "up" on it, and whether a smoke
   test against the assembled preview runs as a `validate:` role before the link is offered, is
   open.
2. **How a project says it *requires* a preview** — a field of `preview:` or not — and whether it
   can be scoped per component the way `risk` is.
3. **WebSockets through the router** — a hot-reloading dev server or a live feed needs them.
4. **A seed that looks like production.** The mechanism is the client's seed (D4); whether the
   factory helps produce a sanitised one is a later decision, and a sensitive one.

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
