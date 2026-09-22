# ADR 0050 — A preview before the merge, because nothing after it can be taken back

- **Status:** **Proposed** (design only — no code changes with this ADR)
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
