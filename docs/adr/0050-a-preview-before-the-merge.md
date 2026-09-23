# ADR 0050 — A preview before the merge, because nothing after it can be taken back

- **Status:** **Proposed** (design only) — amended 2026-09-23 while the first slice was being
  implemented (#270): see *Amendment* below, which supersedes D3's and D7's addressing
- **Date:** 2026-09-22
- **Relates to:** ADR-0005 (post-merge deploy watch, and the read-only contract it gave the
  `environment` adapter), ADR-0025 (delivery closes with the client — a different gate, in a
  different place, and not to be confused with this one), ADR-0026 (a word the reader already has
  beats one you invent), ADR-0037 (the box), ADR-0038 (the platform is complete on its own; the
  panel is the reference surface), ADR-0040 (the core runs on the client's own machines; a cloud is
  an add-on).

## Context

A real client scenario, 2026-09-22: the client runs OpenFactory on their own server — exactly the
README's second door, Docker, a hosted forge, several people watching the same panel. A card goes
to TO-DO, the box implements it, `validate:` goes green, the independent review approves, a pull
request opens. The client wants to see the change **running**, functionally, before that pull
request merges.

That is not a nicety, and the reason is in the code, not in taste. `openfactory/adapters/environment/
azure_pipelines.py`'s own docstring states the shape plainly: *"the platform triggers a merge or a
tag and then OBSERVES the client's own pipeline; it never deploys"* — no deploy credential exists on
that axis, every route is a GET. Once a pull request merges, the client's own CI/CD promotes to
staging on its own, outside anything this platform holds or can undo (ADR-0005; ADR-0040 D1: *"the
platform triggers; the client's pipeline executes"*). The merge is the only door here that does not
open back up. Asking to look before it closes is asking for the one point of leverage this platform
still has.

### The false start, recorded so it is not retried

The first name for this was "a hybrid forge". Wrong, in the exact way ADR-0026 already wrote down:
`forge` already names something in this codebase — the adapter axis that opens and merges pull
requests (`openfactory/adapters/forge/`). Naming a new thing "forge" does not describe the gap, it
invents a name that maps the reader onto the wrong adapter. And the deployment shape it seemed to
reach for — Docker, on a server, in front of a real forge, several people watching one panel — is
not missing either: it is the README's own second quickstart door, already documented, already what
this client's scenario is. What is actually missing sits one layer in: not *where* OpenFactory runs,
but what the box does between "tests are green" and "the box is gone".

## Decision

### D1 — A third manifest verb, `serve:`, alongside `setup:` and `validate:`

`Manifest` (`openfactory/contracts/manifest.py`) already carries `setup: list[str]` — how to install
dependencies — and `validation: dict[str, str | Gate]`, YAML key `validate:`. Neither says how a
project *runs*, only how it is prepared and how it is checked. `serve:` is the same shape as
`setup:`: a start command and, once one exists, a port and a health check, declared by the client's
own manifest the same way `validate:` already is. The factory is not taught how any given stack
runs; it is told — exactly as it is already told how to test one.

A project that declares no `serve:` gets no preview link. That is the same "declare nothing, keep
today's behaviour" rule this codebase already applies everywhere it adds an optional row (ADR-0038;
ADR-0049 D1): purely additive, never a new prerequisite.

### D2 — The box that is previewed is the box that was tested and reviewed, never a rebuild

ADR-0037 D3 already proves the box against the client's own image **by digest**, specifically so
what runs inside it is not an approximation ("a tag is not an image… `prove` records the digest, and
the job path launches by digest"). A preview that rebuilt the artefact to serve it would throw that
guarantee away — the client could be looking at something *adjacent to*, not identical to, what
`validate:` ran and the reviewer read. So: the same box, kept alive past `validate:` instead of torn
down, runs `serve:` in place. What is previewed is bit-for-bit what was tested.

**Bit-for-bit is a promise about the branch head, not about the merge result**, and the record says
so rather than let the sentence above claim more than it holds. `JobRunner._auto_merge`
(`orchestrator/machine.py`) rebases onto the current base before it merges and, if the base moved,
re-validates and re-pushes — so the commit that lands is not the commit that was served. A person
merging by hand on the forge is in the same position whenever the base has moved. The preview shows
the change as it stands on its branch; the gates, re-run after the rebase, are still what holds the
merged result. A preview that must also show the rebased result is a second `serve:` on the rebased
box, and nothing in D1–D8 asks for one.

### D3 — One more link on a surface that already exists: the panel

ADR-0038 settled that the panel is complete on its own and already shows the Board, the job and the
pull request for a card. A `Preview` link beside them is the fourth item on a list that already has
three, not a new surface. No new authentication model — it sits behind whatever already gates the
panel.

> **Amended (A1 below):** the link is on the panel; the preview is **not**. It is served on a host
> of its own and opened with a short-lived key the panel mints — "behind whatever already gates the
> panel" would have put agent-written code on the panel's origin, next to its credential.

### D4 — A pre-merge check, and explicitly not ADR-0025's acceptance loop

ADR-0025 closes a *delivery*: a conversational confirmation, in the client's own words, chased once
at 72h, never closed by silence — necessarily after the thing exists somewhere stable enough to use
for real. Reusing that machinery here would break its own invariant: a merge cannot sit open for up
to 72 hours waiting on a chased reply without stalling every card behind it. What belongs before
merge is smaller and synchronous — closer to what the reviewer role already does, an independent
look before the thing is trusted, than to product acceptance: a functional look, gate the merge,
done.

**Decided: the person who merges is the acknowledgement.** A project that requires a preview is
never merged by the factory on its own; its pull request goes to a human, who looks at the preview
and merges — or does not. Nothing new is built to record a "looks right": the merge click on the
forge already is that record, carried by the forge's own branch protection, which is where this
platform already leaves the question of who may merge.

Under `merge_policy: human` that is already today's behaviour: the preview is one more link for the
person who was going to merge anyway, and gates nothing. Under `merge_policy: auto` it is one more
refusal in `orchestrator/merge_policy.py::should_auto_merge`, which is where every other reason an
auto-merge is refused already lives and which, by its own comments, *"can only subtract from the
answer, never add to it"*. A refusal there sends the pull request down the ordinary
`forge.request_reviewers` branch (`JobRunner`'s merge posture, D-12) — no new state, no new resume
path.

Three alternatives were read in full and rejected, recorded so they are not retried:

- **`RiskPolicy.gates` promotion** (`contracts/profile.py`, via `ResolvedProfile.promoted_gates`,
  read by `JobRunner._validate`). A gate there is a shell command whose exit code is the verdict,
  run by `_run_validations`; a profile cannot declare a command, only promote one that already
  runs; and `_run_validations` is deliberately kept reusable against `onboarding.firstrun._GateHost`
  with nothing on `self` but `sandbox`, `manifest` and `_emit`. A human looking at a running
  application is not an exit code. What *does* fit there is the automated half — a smoke or health
  check against the served application is a command with an exit code, and can be an ordinary
  `validate:` role like any other (§7, item 3).
- **A third `merge_policy` value** beside `human | auto`. `merge_policy` answers *who merges*; a
  preview answers *what must have been seen first*. A value that meant both would read, under
  `human`, as a gate that gates nothing, and would leave no way to say "auto-merge this project, but
  not the cards that need a look".
- **Park the job with the box alive, and auto-merge on the click.** The job is serial and synchronous
  — `_auto_merge`'s own docstring: *"merge-queue-lite; the framework is serial"* — so waiting in the
  job stalls every card behind it, which is the invariant this section opens by refusing to break.
  Parking instead needs a resume path the merge posture does not have, a box kept alive across a
  hold, and the rebase of D2 after the click, so the merged commit would again not be the one
  looked at. It buys "merge without a person clicking merge" at the price of a person clicking
  something else. Not worth it until a client asks for exactly that.

### D5 — Teardown is not optional: a TTL, and closed on merge or on PR-close, whichever is first

A preview kept alive forever is exactly the silent drift this codebase already refuses elsewhere —
ADR-0020's staleness treatment: a project blocked long enough is *forgotten*, not *waiting*. The same
posture applies here in reverse: a box nobody is looking at any more is reclaimed, not left running.

### D6 — Preview secrets are their own tier — never the box's build-time env, never staging's

`box.env` (ADR-0037 D3) carries **build-time** secrets — private registries, private feeds —
resolved from the worker's own environment, by name, never stored. `serve:` runs the application, not
the build, and an application that boots with real payment, email or staging credentials is one
accidental preview away from a real side effect. `serve:` gets its own declared, non-production
secret scope; nothing here inherits `box.env`, and nothing here reaches toward the client's staging
credentials — which this platform does not hold in the first place (ADR-0040 D1; the `environment`
adapter's read-only contract, §Context).

### D7 — One path per card, never a fixed port

More than one card can be in review at once. The preview address is per-card —
`/p/{project}/card/{n}/preview`, or a subdomain keyed the same way — never a fixed host port. The
same shape the panel already uses for `/p/{project}/pr/{n}`.

> **Amended (A1 below):** the subdomain, never the path.

### D8 — No cloud requirement

ADR-0040 D2 is explicit: everything that circulates runs on the client's own machines; D3 makes a
cloud an add-on whose absence must not hobble the platform. The reverse proxy that exposes a preview
has to work over plain Docker on the client's own server — a routing container keyed by path or by
`Host:` header is enough for D1–D7 to hold. A load balancer or CDN in front of it stays exactly what
Fargate already is on this platform: an optional, paid add-on for a hosted multi-tenant deployment,
never the only way this works — the same symmetry `tests/test_the_core_does_not_need_a_cloud.py`
already holds the platform to (ADR-0040 D4).

## What this does NOT mean

- **Not a new adapter axis, and not the forge.** `openfactory/adapters/forge/` is untouched; pull
  requests still open and merge exactly as they do today.
- **Not a replacement for ADR-0025's acceptance loop.** Business acceptance still happens after
  delivery, in the client's own words, on its own schedule. This is a narrower pre-merge look —
  answered by the person who merges (D4) — and the two must not be collapsed into one mechanism.
- **Not a deployment prerequisite.** A project with no `serve:` declared behaves exactly as today —
  no preview link, no new gate, zero migration — matching ADR-0038's and ADR-0049's own rule for
  every optional row.
- **Not a loosening of `validate:`.** The preview happens *after* the existing quality floor is met,
  never instead of it.
- **Not a second deploy target.** The factory still does not deploy (ADR-0005; ADR-0040 D1) —
  staging stays entirely the client's own pipeline's business. The preview is disposable and never
  becomes an environment anybody promotes into.

## Consequences

**Good.** The one point where this platform can still stop an outcome it cannot undo gains a real
check, not just a diff to read. A card in review has something a non-technical client can click —
the same audience ADR-0038 already designed the panel for. The box's existing digest discipline
(ADR-0037) is reused rather than duplicated, so "what you're looking at" and "what was tested" are
the same object by construction, not by convention.

**Costs and risks, declared.**

- **A live process is a bigger attack surface than a stopped container.** `serve:`'s own secret tier
  (D6) and the panel's existing auth (D3) are the only things standing between a preview and a real
  side effect; both have to hold before this ships, not be added after.
- **Resource cost of boxes kept alive.** Bounded by D5's TTL, but a TTL set too generously is the
  same failure mode with a delay rather than a fix.
- **Teardown correctness is a new invariant.** This codebase's own history (ADR-0009, ADR-0020) is
  that invariants like this one fail quietly unless something watches them; it needs its own test,
  not a hope that D5 is enough on paper.
- **A project that requires a preview gives up auto-merge for the cards it applies to** (D4). That
  is the honest price of a human look: the look is the human. A project that wants both declares no
  preview requirement, and gets the link without the gate.

## Amendment (2026-09-23) — found while implementing, and changed before any code shipped

Reading the code the first slice touches (#270) turned up one security defect in this record's design
and three statements that were not true of the code. All four are corrected here, in the record,
before any implementation lands — a Proposed ADR is what somebody implements from, so it must never
describe the insecure version.

### A1 — A preview is served on a host of its own, never on the panel's (amends D3 and D7)

D3 put the preview "behind whatever already gates the panel" and D7 offered
`/p/{project}/card/{n}/preview` as its address. Together they would have served **agent-written
code on the panel's origin**, and the panel's credential is deliberately readable there: the
`openfactory_token` cookie is not HttpOnly, and the page keeps a copy in localStorage — the OIDC
callback in `api/app.py` says so in its own words (*"a script on this origin can read the
credential"*). A preview's JavaScript would read the credential of whoever opened it and could act
as that person: answer a gate, approve a merge, release. A different **port** on the same host does
not help, because browsers send a host's cookies to every port.

So:

- **The preview is served at `<project>--<card>.<OPENFACTORY_PREVIEW_DOMAIN>`**, on the panel's own
  port, by a router in front of the panel that answers every host under that domain and never lets
  one reach the panel's routes. The panel's cookie is host-only, so it never reaches the preview's
  host. `preview.localhost` needs no DNS on one machine; a server sets a domain with a wildcard
  record. The app also gets the root path it was written for, which a sub-path proxy would not give
  most front ends.
- **The way in is a key to that host only.** `GET /api/preview/<project>/<card>` (behind the panel's
  gate, readable by the floor and the product areas alike) mints an HMAC token for that one label,
  valid for at most eight hours and never past the preview's own end. The preview's host exchanges
  it for an HttpOnly cookie that exists only there.
- **The proxy forwards neither the preview's key nor the panel's credential** to the application.
- **Nor may the preview write the panel's credential** (the other direction, found on review of
  #270). Whenever the preview's host shares a registrable domain with the panel's —
  `preview.example.com` beside `panel.example.com`, and the default `preview.localhost` beside
  `localhost` — a script there can set a cookie with `Domain=` the shared parent, named like the
  panel's, through `Set-Cookie` or `document.cookie`, and the browser sends it to the panel beside
  the real one. So the proxy drops any `Set-Cookie` that carries a `Domain` or a panel cookie's name;
  the panel treats a credential cookie that arrives more than once as no cookie at all, on the
  server and in the page; the panel refuses to be framed (`frame-ancestors 'none'`); and a
  deployment reached by name puts previews under a registrable domain of its own, the way
  `githubusercontent.com` is not `github.com`. The one case those leave — a browser holding no
  panel cookie at all being handed one — closes with the `__Host-` prefix on the panel's cookie,
  which no sibling host can set (#271).

### A2 — The preview is a NEW container from the frozen box (sharpens D2 and D6)

D2's promise is "what is previewed is what was tested", and D6's is that `serve:` inherits none of
the build's secrets. Both cannot hold in the SAME container: its environment was fixed at
`docker run` with the harness token and every `box.env` credential, and any process inside it can
read PID 1's environment from `/proc`, whatever its own environment says. So the validated box is
**frozen** with `docker commit` — after the harnesses' state is removed from its HOME, and with every
harness and `box.env` name overwritten to empty in the image's configuration — and the preview is a
new container from that image, with the same checkout mounted, receiving `PORT`, `HOST=0.0.0.0` and
the registry's `box.preview_env` and nothing else. The filesystem and the tree are what was tested;
the process space and the credentials are not carried over.

### A3 — Three statements corrected

- **"The job path launches by digest" (D2) is not what the code does.** `resolve_box_image` returns a
  tag or a name and `docker run` uses it as given; the digest is compared only by the box-proof
  freshness gate. D2's guarantee does not rest on it any more: A2 freezes the very container that
  ran `validate:`, so no image is resolved again.
- **The preview cannot wear the job box's name.** The box is `openfactory-<project>-<issue>`, and a CI
  repair or a re-review of the same card prepares a box under that name and removes whatever wears
  it as debris (#165). The preview is `openfactory-preview-<project>-<card>`, labelled
  `openfactory.preview`, and a later run of the same card replaces it.
- **The preview's secret names live in the registry, not in the manifest.** `box:` is registry
  configuration because the agent edits the manifest (`contracts/project.py::BoxConfig`); D6's tier
  is `box.preview_env` beside `box.env`, and `serve:` in the manifest carries only the command and the
  port.

### A4 — How it ends (makes D5 concrete)

A deployment-wide `PreviewReapWorkflow` runs every ten minutes on the worker, which holds the daemon.
It ends a preview whose time is up (`box.preview_hours`, 24 by default, clamped to a week), whose pull
request merged or closed, or whose `serve:` command stopped — removing the container, the frozen image
and the checkout, and recording the end so the panel says why. It is its own workflow rather than a
step in `JobWorkflow`'s merge loop or the poller's tick, because either would change the command
sequence of histories already in flight. A preview's end may therefore trail its merge by up to ten
minutes.

### What the first slice does not do

- **No gate on auto-merge yet.** A preview is offered only where the pull request was handed to a
  person; D4's refusal in `should_auto_merge` for projects that *require* a look is the next slice,
  with §7 item 2's spelling.
- **Container box only.** A worktree box is the worker's own filesystem; there is nothing to freeze.
- **No WebSocket proxying.** An application whose page needs a socket (a dev server's hot reload,
  a live feed) loads, and that part of it does not work through the preview yet.
- **Readiness (§7 item 3) is unchanged:** the link is offered once the container runs; a server
  still starting answers "the preview is not answering — try again in a moment".

## §7 — Left open, deliberately

1. ~~**Where the pre-merge gate actually plugs in.**~~ **Settled in D4**, after a full reading of
   `JobRunner._validate`/`_run_validations`, `policy/conformance.py`, `policy/profiles.py` and
   `merge_policy.should_auto_merge`: one refusal in `should_auto_merge`, neither `RiskPolicy.gates`
   nor a new `merge_policy` value.
2. ~~**Who is authorised to click "looks right".**~~ **Dissolved by D4.** There is no separate click:
   whoever the forge lets merge is who acknowledges. `ProductConfig.admins` authorises the product
   role's *writes* (`docs/AGENTS.md`) and is not reused here. What remains open is only the
   manifest's spelling of "this project requires a preview" — a field, or a `serve:` sub-key — and
   whether it can be scoped per component the way `risk` is.
3. **Readiness, not just liveness.** `serve:` starting is not the same fact as the application being
   ready to click through. Whether the panel's `Preview` link waits on a declared health check or
   only on the process existing is unresolved. D4 narrows it: a readiness check is a command with
   an exit code, so it can be an ordinary `validate:` role run against the served box rather than a
   new mechanism — whether it runs before the link is shown, or blocks like any other gate, is what
   is left.
