# ADR 0037 — The box: the client's image, an injected toolbox, and a proof before any pickup

- **Status:** **Accepted** (D1–D5 decided; two options left open are named in §7)
- **Date:** 2026-08-02
- **Relates to:** ADR-0001 D-17 (the sandbox), ADR-0018 (unknown kinds raise), ADR-0022 (an axis is
  agnostic when it is born with two), ADR-0034 (extension model), C-13 (`SDLC_SANDBOX` read by
  nothing), C-16 (`init` that acts), C-29 (#65, the container box cannot obtain the repository).

## Context

The box is where a client's code is built and tested and where the agent runs. It is the one
component that must simultaneously satisfy **the client's stack** and **the framework's harness**,
and it is the only part of the onboarding with no step of its own: it first appears at the first
ticket, which is the worst possible moment to discover it is wrong.

The product owner named the stakes: *"every client will have its own specificity… this is the
heart of this product and it has to be very, VERY well done and relatively easy to configure, or
nobody will manage to use it."* Two prospects are in view — one serverless on AWS, one C#/.NET on
Azure — and neither runs Python.

**Today there is exactly one box image and it is not configurable.** `docker/base-python.Dockerfile`
is `python:3.12-slim` plus a pinned `@anthropic-ai/claude-code`; `docker/sandbox.Dockerfile` adds
`gh` and the platform. The image name is a literal in **six** places
(`adapters/sandbox/registry.py:62`, `runtime/temporal/io.py:42`, `:59`,
`runtime/temporal/activities.py:783`, and the two Dockerfiles), and `SDLC_SANDBOX_IMAGE` — set by
`docker-compose.yml` — is read by nothing. So the OSS distribution already runs an image different
from the one it declares.

`Manifest` has **no field about the box at all**. The client declares *what commands to run*
(`validate: {test: pytest}`) and nothing anywhere declares *where they run* — two things that are
inseparable in reality, because `pytest` needs Python installed, and completely unlinked in the
model. `docs/architecture.md:158-161` and `docs/core/00-vision.md:70-75` claim C#/Java/PHP work
"with nothing new". That is true of the *calling surface* — validation is a shell string and only
the exit code is read — and false of the *contents of the box*.

## Decision

### D1 — The base image belongs to the client, but the onboarding does not open with it

`deploy/registry.yaml` gains a `box:` block per project:

```yaml
box:
  image: mycorp.azurecr.io/ci-base:2026.7   # what the client's own CI already runs on
```

The framework never builds per-stack images. Stack presets may *suggest* one as an `init`-time
default; they never produce one.

**The onboarding question is not "which image does your CI use?".** That was the first draft and it
is inverted for the exact segment this decision exists for: a .NET shop on Azure Pipelines hosted
agents has **no container image at all**, so the opening question dead-ends where it matters most.
`init` detects the stack from the repository (`.csproj`, `package.json`, `go.mod`), leads with the
preset's suggested image, and offers *"or point at your own"* as the secondary path. The promise is
**"you may bring your image"**, never "you must have one".

**`box.image` is DEPLOYMENT configuration, not project configuration, and that is a security
boundary rather than a filing preference.** `.sdlc/project.yaml` lives inside the repository the
executor edits. An agent able to write `box.image` chooses its own root filesystem — it turns "the
agent wrote the wrong code" into "the agent picked the machine". The registry is operator-owned and
the agent cannot reach it. (`Manifest.permissions` already exists and is read by nothing; this ADR
does not rely on it.)

**The image contract is written down, because "any image" is false.** `prepare()` runs
`--entrypoint sleep`, every command runs through a shell, `git config --global` needs a writable
HOME, and the mounted clone must be writable by the image's uid. A distroless image has neither a
shell nor `sleep`. The contract — POSIX shell, a keep-alive, git, writable HOME, writable
`/workspace` — is checked **by name, each with its own remedy**, by D3.

**CORRECTED, 2026-08-02.** This paragraph asserted that `mcr.microsoft.com/dotnet/sdk` ships
without `git`, and concluded that the toolbox must therefore carry a static one. The claim came
from the adversarial panel and I wrote it down without checking. It is false: `8.0`, `9.0` and
`10.0` all carry git (2.39.5, 2.39.5, 2.43.0). Verified by running them.

What survives is the contract itself — a box genuinely cannot work without git, and a distroless or
scratch image has neither git nor a shell. What does not survive is the motivating example, and
with it the settled conclusion: whether the toolbox should carry a fallback `git` is now an OPEN
question, to be decided by what D3 actually finds failing rather than by an image that turned out
to be fine. Carrying one is cheap; carrying one for a reason that is not true is how a toolbox
grows without anybody being able to say why.

### D2 — The harness never lives in the client's image

It is delivered as a **toolbox**: a read-only directory of framework-owned, version-pinned binaries
— `claude`, `codex`, `kimi`, `gh`, `git` — mounted into every box.

**CORRECTED, 2026-08-02.** The first version of this section said all three ship as self-contained
native executables and none needs Node. That was measured on `claude` and *assumed* for the other
two, and the assumption is wrong. What a real `npm install -g` produces:

| harness | what the package delivers | needs Node? |
|---|---|---|
| `claude` | `bin/claude.exe`, a 260 MB native ELF (glibc) | **no** — runs under `env -i` |
| `codex`  | `bin/codex.js`, a `#!/usr/bin/env node` shim, plus a native binary hidden at `@openai/codex-linux-<arch>/vendor/<triple>-musl/bin/codex` | the shim does; the vendored binary does not |
| `kimi`   | `dist/main.mjs`, a 39 MB ESM bundle | **yes, always** |

So the toolbox carries **a Node runtime as well**, and that is the design rather than a
concession: at ~50 MB beside three harnesses it is noise, and going through Node uniformly removes
a per-harness branch about which one can be executed directly. `kimi` has no other option, and
choosing per harness would mean the toolbox works for two and silently not the third.

The entry the box executes is therefore a **wrapper** for the Node-based harnesses:

```sh
#!/bin/sh
exec /opt/sdlc-toolbox/runtime/bin/node /opt/sdlc-toolbox/pkg/.../codex.js "$@"
```

Absolute on both halves, so neither the harness nor its runtime is found through `PATH` — which is
the whole point of D2a. It needs `/bin/sh`, already part of D1's image contract.

**Measured again inside the image, 2026-08-02, and the second measurement changed the plan for the
better.** `npm install -g @anthropic-ai/claude-code@2.1.219` — which `base-python.Dockerfile:20`
already runs — does not install a Node script. It installs `claude.exe`, a **260 MB native ELF
binary**, and it runs under `env -i` with no Node anywhere:

```
$ ldd claude.exe        → linux-vdso, librt, libc.so.6, ld-linux-aarch64.so.1, libpthread, libdl, libm
$ env -i ./claude --version   → 2.1.219 (Claude Code)
```

So the toolbox is assembled from **the package the build already pins**, in a builder stage — no
second distribution source, no new version to track, no installer script to trust. That is what
makes the v1 "baked into the worker image" option cheap enough to be obviously right.

The same measurement confirms the variant key. Those dependencies are **glibc**
(`ld-linux-aarch64.so.1`), so an Alpine or musl-based client image cannot exec this binary at all —
the failure being the dynamic loader's `no such file or directory`, which names the wrong thing. A
per-arch toolbox would have shipped that; `<os>-<arch>-<libc>` is what the fact requires.

**Why not one image per harness:** that is stack × harness. Three harnesses and five stacks is
fifteen images somebody maintains. Injection makes `harness: {executor: codex, reviewer: claude_code}`
pure configuration — **rotating between harnesses, or mixing them per role, never touches an
image**, which is the property the product is sold on.

Three mechanics, each of which the first draft got wrong:

- **A named volume, not a path.** The compose worker is itself a container using
  docker-out-of-docker, so a `-v /var/lib/sdlc/toolbox:…` it issues is resolved by the **host**
  daemon against the host filesystem, where that path does not exist — Docker would create an empty
  directory and the box would get an empty toolbox, silently. A dedicated `openfactory_toolbox` volume is
  owned by the daemon and mounts identically from a containerised or a bare-metal worker. It is
  **its own** volume, never `sdlc_state`: that one holds `registry.yaml` and `metrics.db`, whose
  loss turns every job into a `KeyError`.
- **Absolute paths, never `PATH`.** `container.py` execs through a shell, and a login shell sources
  the image's `/etc/profile`, which on Debian and Alpine reassigns `PATH` unconditionally. A
  prepended `PATH` is discarded by an ordinary, entirely benign client image. The adapters emit
  `/opt/sdlc-toolbox/<ver>/<variant>/claude` — the login shell itself is removed separately
  (see §5).
- **Keyed to the IMAGE, not the host.** A glibc binary cannot exec under musl, and an amd64 image
  emulated on an arm64 host needs amd64 binaries. The variant is `<os>-<arch>-<libc>`, resolved from
  `docker image inspect` plus a libc probe, and a missing variant is a **named failure at prove
  time**, not a dynamic-loader `ENOENT` at the first ticket.

**For v1 the toolbox is baked into the worker image and copied to the volume at boot.** A
standalone, checksummed distribution channel is phase 2. This buys the whole property — client
image, harness rotation, no per-stack builds — without building an artifact-distribution pipeline
first.

**What the checksum can and cannot mean**, stated so nobody reads more into it: it is verified
**host-side by the worker at populate time**, over an artifact from the framework's own channel. A
box-side check would be the client's `sha256sum`. Read-only protects the bytes at rest; the box runs
as a process that can copy a binary out and run a patched copy. The toolbox is an **integrity**
measure against drift and tampering at rest, not a containment boundary.

### D3 — `sdlc box prove`: the box is proven before any agent runs

Pull the image (resolving the tag to a `sha256:` digest), mount the toolbox, check the image
contract item by item, then run the client's own `setup:` followed by `validate:` **against
untouched `main`** — no ticket, no agent, **zero harness tokens**.

Green here means: *your 47 tests passed inside the factory*. It is the first moment a client sees
their own work succeed inside our machine, and it costs nothing.

Two things the first draft under-specified:

- **A tag is not an image.** `docker run` passes no `--pull`, so a proven tag can be repointed
  between the proof and the job. `prove` records the **digest**, and the job path launches by
  digest.
- **`--version` proves the wrong layer.** It opens no TLS connection, so a corporate proxy, an
  intercepting CA, or an egress policy all pass the proof and kill the first real agent call. The
  proof includes a TLS handshake against the harness endpoint **from inside the box** — still zero
  tokens — and `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` join the box's env pass-through.

The failure taxonomy is explicit — image-pull/auth, daemon, contract, setup, validate,
harness-smoke, network — each with its own remedy line, to `doctor`'s standing bar: **one cause, one
actionable line**.

`box.env: [NAMES]` (names only, values resolved from the worker's environment, never stored) carries
the client's *build* secrets — Azure Artifacts, private npm — which their CI injects at runtime and
which are therefore **not** baked into the CI image. Without it, `prove` fails at step one for every
private-feed enterprise.

### D4 — The image is resolved in exactly one place

Six literals and one env var that nothing reads collapse into a single resolver:
CLI `--image` > registry `box.image` > stack preset suggestion > framework default.

The resolution happens **on the activity/CLI side of the workflow boundary** and the result is
stamped into the job input. Resolving inside a workflow body would replay differently on a worker
started with different configuration — the determinism rule `adapters/sandbox/registry.py` already
states.

**Defaults preserve the pilot exactly**: no `box:` declared → today's image, today's behaviour, zero
migration.

**`box.image` on a Fargate deployment FAILS LOUDLY.** The task definition's image is baked, and both
live deployments are Fargate. Accepting a field the deployment ignores would mint a fresh instance
of C-13 in the same release that fixes it. Until phase 2, `box.image` is container-path-only and
saying so is the whole guard.

### D5 — The proof is a precondition of pickup, and it expires

The product owner asked whether there should be a per-client box pre-configuration before pulling
from TO-DO. There should be something stronger: **configuration is a declaration, a proof is a
fact.**

The poller checks, before picking a ticket up, that the project has a **valid proof**. A proof is
valid for one `(image digest, toolbox version, hash of setup: + validate:)`. Any of the three
changing — the client republishes their image, we pin a new harness, they edit `setup:` — expires
it. That is what separates an onboarding checkbox from an invariant: a checkbox ages silently.

**The gate is never mute.** Without a valid proof the poller does not pick up **and says so once**,
in the channel and the panel, with the exact command. A gate that blocks without speaking is the
platform's headline failure wearing a new hat.

## Consequences

**Good.** Harness rotation and per-role mixing become configuration, with no image work. A client
brings the image they already trust, with their CA bundle and private-registry access in it. The
most common onboarding failure — a toolchain that is not there — is discovered by a command that
costs nothing, before any credential or any spend, instead of by a confusing test failure inside a
paid agent pass. And a fleet of clients cannot silently drift, because the proof expires when the
ground moves.

**Costs and open risks.**

- **The image contract is a real constraint and some CI images will fail it.** Distroless and
  scratch images cannot host a box. That is honest and checkable, which the status quo was not.
- **Who pulls, and with whose credential, is only half-answered.** `prove` performs the
  authenticated pull so the failure names the registry — but a *hosted* deployment would have to
  hold every client's registry credential, and under docker-out-of-docker they share one
  `~/.docker/config.json`. See §7.
- **The proof can become a new way to stall** if the announcement is ever dropped. ADR-0020's
  staleness treatment applies: a project blocked on a missing proof for long enough is forgotten,
  not waiting.
- **Fargate keeps a baked image until phase 2**, so the cloud deployments get D3/D4/D5 and not D1's
  freedom. The guard makes that visible rather than silent, but it is a real gap for exactly the
  deployments that are live today.
- **The toolbox is large** (~245 MB × harnesses × variants). D2 keeps current + previous per
  variant and prunes on populate, on its own volume, so its growth can never starve the registry.

## §7 — Left open, deliberately

1. **Toolbox delivery in phase 2**: baked into the worker image (v1, no new infrastructure, but a
   harness bump means a worker rebuild) versus a checksummed artifact channel (independent
   versioning, but a distribution pipeline to run and secure).
2. **Who holds the pull credential in a hosted deployment**: the framework authenticating outward to
   N client registries with one shared docker config, or the inverse — clients pushing into a
   per-tenant repository in the framework's own registry. The second is better isolated and worse
   for onboarding friction; it needs a decision before the first hosted multi-tenant client.

## §8 — Objections raised and answered

An adversarial panel (ops, supply-chain security, product) attacked the draft; all three returned
*amend*, none returned *breaks*. Recorded so they are not relitigated:

- *"One extra `-v` in the existing `docker run`"* — **false** under docker-out-of-docker; became the
  named volume in D2.
- *"Per-arch toolbox"* — **one dimension short and keyed to the wrong machine**; became
  `<os>-<arch>-<libc>` off the image in D2.
- *"`PATH` prepend"* — **destroyed by an ordinary Debian `/etc/profile`**; became absolute paths.
- *"Which image does your CI use?"* — **dead-ends for hosted-agent CI**, the target persona; became
  stack detection first in D1.
- *"`box.image` in the manifest"* — **agent-writable**; moved to the registry in D1.
- *"`--version` smoke"* — **proves the wrong layer**; became a TLS probe in D3.
- *"Private registry access is baked into the CI image"* — **conflates the app's dependencies with
  the image pull, and ignores runtime-injected build secrets**; became `box.env` and the pull
  credential question in §7.
- *"Any image your CI uses"* — **assumes an unstated contract**; became the written contract in D1,
  checked by D3.
