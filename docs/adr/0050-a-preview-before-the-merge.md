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

The natural home for a blocking pre-merge check is the mechanism this codebase already has for
exactly that shape: `RiskPolicy.gates` (`openfactory/contracts/profile.py`), which promotes an
already-running, advisory check into a blocking one per risk level (`ResolvedProfile.promoted_gates`,
read by `JobRunner._validate`) — `gates: [security]` is the existing example, and the rule already
written down is that gates may only ever be *added*, never used to weaken anything. Whether a preview
acknowledgement fits that same promotion path, or needs its own field beside `merge_policy: human |
auto`, is genuinely open: this record has read the promotion machinery far enough to know the shape
exists, not far enough to commit to reusing it sight unseen. Left to §7.

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
  delivery, in the client's own words, on its own schedule. This is a narrower, synchronous,
  pre-merge gate, and the two must not be collapsed into one mechanism.
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
- **D4's exact wiring is the least settled part of this record.** Shipping it against the wrong
  mechanism — a bespoke field where the existing promotion path would have done, or the reverse — is
  far cheaper to get wrong here, in writing, than in code.

## §7 — Left open, deliberately

1. **Where the pre-merge gate actually plugs in** — `RiskPolicy.gates` promotion, a new
   `merge_policy` value, or a slot `orchestrator/machine.py::_validate` and
   `openfactory/policy/conformance.py` do not have yet. Needs a full reading of both before D4 moves
   from *proposed* to *decided*.
2. **Who is authorised to click "looks right".** The product role already has exactly this shape of
   list for authorising a write — `ProductConfig.admins`, the registry's `product.admins`
   (`docs/AGENTS.md`). Whether a preview acknowledgement reuses that list or needs its own is open.
3. **Readiness, not just liveness.** `serve:` starting is not the same fact as the application being
   ready to click through. Whether the panel's `Preview` link waits on a declared health check or
   only on the process existing is unresolved.
