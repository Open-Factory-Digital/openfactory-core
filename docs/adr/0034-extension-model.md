# ADR 0034 — Providers stay in-process for now, and the door stays open by a test

- **Status:** **Accepted; the in-process step is decided** (addendum 2026-08-26: entry points on every axis and on the role axis are the extension mechanism; the out-of-process door stays open by the guard, its trigger unchanged)
- **Date:** 2026-08-02
- **Relates to:** ADR-0022 (provider seams — the rule this extends),
  [`docs/core/07-extensibility.md`](../core/07-extensibility.md) (the full analysis),
  ADR-0018 (harness roles).

## Context

ADR-0022 made every provider axis *replaceable*: `kind → builder`, resolved from configuration,
unknown kind raises, no module outside a provider's package names a concrete class.

It did not make one **addable from outside**. `FORGES` is a literal dict in a module, so adding a
row means editing the file, which means being inside this repository. `pyproject.toml` declares one
console script and no plugin group. A paid add-on, a community provider, or a client's own tracker
would have nowhere to register.

> **The successor to ADR-0022's rule:** an axis is agnostic when it is *born with two*; a platform
> is extensible when a stranger can add the third **without editing our files.**

Two questions keep being merged and only the second is architectural:

| | question | options |
|---|---|---|
| **Distribution** | how do the bits reach the machine | pip · docker image · tarball |
| **Extension** | how does the *running* system discover a provider | in-process · separate binary · sidecar |

## Decision

**Do not choose the extension model yet. Ship the guard that keeps both available.**

### 1. The models, and why the cheap one is not obviously right

| model | allows | cost |
|---|---|---|
| in-process plugin (Python entry points) | a provider in Python, on the Core's dependency versions; adding one means rebuilding the worker image | low |
| out-of-process provider (separate binary, gRPC/HTTP) | any language, independent versioning, plug in without a rebuild | **high** — a wire protocol, serialisation per contract type, protocol versioning, process lifecycle |

The in-process shape is one `_discover()` helper plus one line per registry. **The code is small;
the commitment is not.** Adopting it as *the* model closes the door on a provider written in C# or
Go — which is precisely what a prospect running Azure DevOps and C# might want — and that door
should not close for installation convenience.

**Terraform inverts the usual worry.** Its providers are separate binaries in any language, spoken
to over gRPC, which is why thousands exist written by people who never spoke to HashiCorp. The
command that downloads them is `terraform init`. So an `init` is not the opposite of extensibility;
in that model it *is* the mechanism. What would limit us is an `init` that only knows how to
install a Python package into its own virtualenv.

### 2. The guard: every port signature stays serialisable

Out-of-process is possible only while what crosses a port can travel. A first pass grepped for
`Callable`, iterators, handles and `-> Any` and found nothing — **and that answer was wrong.** A
grep tests the words a violation is usually spelled with; it cannot see one spelled in this
codebase's own vocabulary.

Resolving annotations at runtime against a **whitelist** of transportable types found three
(C-09, shipped):

- `ChannelAdapter.start_listeners() -> list` returned live Socket Mode handlers, which the worker
  parked in a `noqa: F841` local. **Fixed** — the provider owns what it opens; the caller keeps the
  adapter, which it had to anyway.
- `ChannelAdapter.say(project)` and `ConfirmingChannel.ask_to_confirm(project)` were unannotated.
  An unannotated parameter is not "no type", it is `Any`. **Fixed.**
- The agent, reviewer and judgment ports take a live `SandboxAdapter`. **Kept — see §3.**

A whitelist, not a denylist: a denylist passes anything nobody thought of, starting with `Any`,
which is the widest hole and the one a hurried signature reaches for. The guard is itself guarded —
eleven signatures somebody could plausibly write must each be refused, or a green test would only
prove the check is broken.

### 3. The harness is the exception, and it is architecture

`CodingAgentAdapter.execute` receives a live `SandboxAdapter` because **the harness runs inside the
box**: it needs `sandbox.run(...)` to exec its CLI in the container. That pair is physically
co-located, so handing it an identifier instead would only move the callback somewhere worse.

The consequence is precise and worth stating, because it answers a question
[`docs/core/07`](../core/07-extensibility.md) left open:

> **The harness axis cannot go out of process without a different contract. The other seven can.**

An out-of-process harness would take a box *identifier* and ask the Core to run things in it — a
real design, not a signature tweak. The exception is pinned by two tests: one asserting the list
has not grown, one asserting it applies to the harness/box pair only and cannot be used to pass a
box into the tracker or the forge.

### 4. The trigger that would settle it

Recorded now so it is checkable later rather than re-argued:

> **Today every consumer of a port is a recorder** — it writes, posts, or reads. The day a provider
> must be written in a language this repository does not run, or plugged into a running deployment
> without a rebuild, the out-of-process model has earned its cost.

Until then, entry points remain a cheap and **reversible** first step: start there because it is
small, knowing that moving later costs no contract change.

### 5. The commercial mechanism needs no code either way

    pip install openfactory          public index, Apache-2.0, everything open
    openfactory install techlead     private index, token required

**The token is the licence.** No licence check in the code, no disabled flag, no crippled path —
either the package downloads or it does not. That keeps literally true the rule that the open build
is never hobbled: the add-on is simply absent, not switched off. The mechanism is identical whether
an add-on is paid or free; only the index differs.

## Consequences

**Good.** The decision cannot now be made by accident. Closing the door requires making a test go
red, which is a decision; without the guard it happens by drift, in a signature that looks
harmless. And the property held today for free — it fell out of ADR-0022 §3, *the contract is
derived from what the Core calls, never from what a provider offers*. A channel contract built from
what Slack offers would have handles and callbacks throughout; built from three calls, it is
serialisable by happy accident.

**Costs and open risks.**

- **`Path` passes the guard and is semantically machine-local.** A filesystem path means nothing to
  a provider on another host; `Workspace.host_path` already carries that lesson. Serialisability is
  *necessary* for a remote transport and not *sufficient*, and the test only claims the former.
- **Bare `dict` and `list` are allowed.** In this codebase they mean "JSON from a provider", and
  demanding `dict[str, object]` everywhere would be churn for no safety. It is a deliberate
  weakening, recorded here rather than hidden in the test.
- **Deferring has a cost that compounds.** Every month without an extension model is a month a
  prospective contributor cannot contribute, and the first external provider will be written
  against whatever exists then.
- **One reasoned hole can become two.** `_CO_LOCATED` is pinned by a test precisely because an
  exception list that grows quietly is indistinguishable from no guard at all.

## Addendum (2026-08-26): the in-process step is decided; the out-of-process door stays open

The Decision above declined to choose. The public-core cut (waves 1 and 2, 2026-08-25/26) made
the in-process step a fact of the tree rather than a first step somebody might take, and this
addendum records it as **decided for that step**:

- **Every registry on every axis consults the `openfactory.adapters` entry-point group** — the
  published list is `openfactory/plugins.py::AXES` (seventeen axes on the day of this addendum,
  counted from that tuple), and `tests/test_a_stranger_can_add_an_adapter.py` DERIVES the
  registries from the tree and holds the set they ask for equal to it. Measured before the cut
  with a real `dist-info` on the path: four registries built an installed add-on and six refused
  it by name; measured after, every one builds it.
- **The role axis is one of them** (`role.<name>`, ADR-0022's and ADR-0018's addenda), with the
  one difference §3 of [`docs/core/07`](../core/07-extensibility.md) records: its builder returns
  a value, not an adapter. The credential axis (`credential.<kind>`) has the same shape.
- **The platform's own cloud connector registers through the same door** — `box_runner.fargate`,
  `metrics.dynamodb`, `session_store.s3`, `token_pool.ssm` in `pyproject.toml` — and
  `tests/test_the_cloud_is_a_directory_delete.py` proves the core imports, every registry
  answers and the gate is green with those paths deleted from the tree.
- **A built-in row wins a collision and an unknown kind still refuses by name.** Neither rule
  changed; both are what keep an add-on an extension point rather than a supply chain.

**What is NOT decided, and the door is exactly where §2–§4 left it.** The out-of-process model
is still open, and its trigger is unchanged: a provider that must be written in a language this
repository does not run, or plugged into a running deployment without a rebuild. The
serialisability guard (`tests/test_ports_are_serialisable.py`) still holds every port, the
harness exception of §3 included, so the move still costs no contract change — which is the
property that made the in-process step safe to decide. §5's `openfactory install` remains a
future name: today an add-on is `pip install`ed into the worker image and the image rebuilt.
