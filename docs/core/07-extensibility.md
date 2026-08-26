# 07 — Extensibility: how a running install gains a provider it did not ship with

The registries dispatch. They are not extensible. Those are different properties, and the
second one is what an add-on model, a community, and a paid module all need.

**Status: decided in one step, open in the other.** The in-process step — Python entry points on
every axis, the role axis included — is the extension mechanism the tree has, decided by
[ADR-0034](../adr/0034-extension-model.md)'s addendum of 2026-08-26 (§2 below is the measured
state). The out-of-process door stays open by the guard §7 describes, with its trigger unchanged.
This document frames both and records what keeps the second choice from being made by accident.

---

## 1. Two questions that keep getting merged

| | question | options |
|---|---|---|
| **Distribution** | how do the bits reach the machine | pip · docker image · tarball · git clone |
| **Extension** | how does the *running* system discover a new provider | in-process plugin · separate binary · sidecar service |

They are independent, and only the second is architectural. A factory is not a library —
it is an always-on worker, an ephemeral box per job, a panel and a durable engine. The
natural distribution unit is an image and a compose file, not a wheel. That says nothing
about how it is extended.

## 2. Where the seams stop today

ADR-0022 solved *dispatch*: `kind → builder`, resolved from configuration, unknown kind
raises, nothing outside a provider's package names a concrete class. That is what makes a
provider replaceable.

It did not, on the day this document was written, make one **addable from outside**: every
registry was a literal dict in a module (`FORGES = {"github": _github}`), adding a row meant
editing the file, and `pyproject.toml` declared one console script and no plugin group. That
is history. The state of the tree is measured, not remembered, and it is this:

- **One group, the axis in the entry-point name.** `pyproject.toml` declares the entry-point
  group `openfactory.adapters`, read by `openfactory/plugins.py`; an add-on names its axis and
  kind in the entry-point name (`forge.gitea`) and its rows join the registry's table at lookup
  time. A built-in wins any collision (an add-on that could redefine `github` for every project
  on a deployment is a supply chain, not an extension point) and an unknown kind still refuses
  by name.
- **Every registry consults the loader.** The axes that consult the loader today: `board`,
  `board_setup`, `box`, `box_runner`, `channel`, `ci`, `credential`, `event`, `forge`,
  `harness`, `identity`, `metrics`, `notifier`, `role`, `session_store`, `token_pool` and
  `tracker` — spelled exactly so in the entry-point name. `openfactory/plugins.py::AXES` is the
  published list; `tests/test_a_stranger_can_add_an_adapter.py` DERIVES the registries from
  the tree (every module that asks the loader) and holds the set they ask for equal to it, and
  `tests/test_the_extensibility_doc_names_the_real_group.py` holds this sentence to the
  registries — it caught the document saying `agent` the day the sentence was first written,
  and it counted "five registries" while nine consulted the loader until the walker learned to
  read an axis spelled as a constant. Note that the coding-agent axis asks for
  `harness.<kind>`, not `agent.<kind>`, the sandbox for `box.<kind>`, the CI observer for
  `ci.<kind>`.
- **Two shapes of row.** Most builders return an adapter. Two axes return a *value* the core
  resolves rather than a client it constructs — `role` (a `RoleSpec`) and `credential` (a
  `CredentialRow`); §3 says what each means for the package that ships one.
- **The doors in front of the registries derive from them.** `openfactory init`, `project
  init`, `conformance-adapter` and the worker's listeners read `plugins.known(axis, TABLE)`
  when they ask their questions; none keeps a hand copy of the vocabulary. Measured before the
  fix (2026-08-26): four doors did, so an add-on a registry would have built was refused one
  step earlier by a list that had never heard of it.
- **The platform's own connectors register through the same door, from their own packages** —
  the rows `addons/openfactory-aws` declares (`box_runner.fargate`, `metrics.dynamodb`,
  `session_store.s3`, `token_pool.ssm`) and the rows `addons/openfactory-slack` declares
  (`channel.slack`, `notifier.slack`, `notifier.telegram`) are exactly what a stranger's would
  be; the core's own `pyproject.toml` declares none, and §10 says what that makes true of the
  public tree.

One measurement is worth keeping from how it got here, because it is the shape this whole
section exists to prevent: a probe with a real `dist-info` on the path found six registries
refusing an installed add-on by name while four built it. Every axis reading the same loader is
not tidiness — it is the difference between an extension point and a list of the axes somebody
remembered to wire.

**The mechanism a stranger uses today** is the one the distribution unit implies: `pip install
<addon>` into the worker image, then rebuild (`docker compose --env-file .env.compose up -d
--build` — the platform's code is baked into the image, so an install that skips the rebuild
changes nothing, see `docs/ONBOARDING.md`). There is no `openfactory install` verb, and §8 says
why the name stays a future one — see §4 for why an `init` that only knows how to pip-install
into its own virtualenv would be the wrong thing to build now.

**The rule ADR-0022 established has a successor:** an axis is agnostic when it is *born
with two*; a platform is extensible when a stranger can add the third **without editing
our files**.

**And the open build is never hobbled.** No capability is removed from what ships here in
order to manufacture an upgrade path, and no code in this tree asks whether a package was paid
for: there is no licence check, no disabled flag, no crippled path. An add-on a deployment does
not have is *absent* — its registry refuses that kind by name, naming what to install — never
present and switched off. A build deliberately made worse is a marketing asset wearing a
platform's name, and it would falsify the one claim this document exists to support.

## 3. Three models, with honest costs

| model | allows | cost |
|---|---|---|
| **In-process plugin** (Python entry points) | a provider in Python, on the Core's dependency versions; adding one means rebuilding the worker image | low |
| **Import path declared in config** | the same, stated explicitly rather than discovered | low |
| **Out-of-process provider** (separate binary or sidecar, gRPC/HTTP) | any language, independent versioning, plug in without rebuilding the Core | **high** — a wire protocol, serialisation for every contract type, protocol versioning, process lifecycle |

The in-process shape is one loader plus one line per registry — and it is the shape the
tree has (`openfactory/plugins.py`). One group for every axis, with the axis in the
entry-point NAME, because a group per axis would make a stranger guess which of seven to use
before knowing whether their kind is supported at all:

```python
builder = FORGES.get(kind) or plugins.builder("forge", kind, builtin=FORGES)
```

```toml
[project.entry-points."openfactory.adapters"]
"forge.gitea" = "openfactory_gitea:build_forge"
```

*Since 2026-08-24 the agent **role** is an axis of this shape too — `role.<name>` in the one
`openfactory.adapters` group — with one difference worth knowing: its builder returns a
**value** (`RoleSpec`: prompt, env names, whether a person reads its answers, default harness)
rather than an adapter, because a role is configuration the harness registry resolves, not a
client it constructs. The core resolves, configures and shows an add-on role; it does not
invoke one — the package that ships the role does, through `build_asker`. See ADR-0018's
addendum for what stays closed.*

*Since 2026-08-26 the **credential** is an axis of the same value-returning shape —
`credential.<kind>` returns an `adapters.credential.registry.CredentialRow`: the variable the
vendor's token lives in by default (`env`), what THIS deployment can mint for it when a project
names nothing (`mint`, and `provider` for a job that outlives one token), and a person's own
login on the machine for onboarding (`discover`). Measured before it existed: a `forge.gitlab`
add-on's projects were handed `OPENFACTORY_BOT_TOKEN` — the deployment's GitHub credential —
because the vendor-default table was a closed dict in core, and through `factory.build_runner`
the same add-on received the GitHub App minter as `token_provider`. The rule an add-on's
builder must follow, now that the deployment asks each vendor's own row: the `token` /
`token_provider` keyword arguments a registry row receives are the CALLER's resolution and may
still carry a credential the caller holds for another purpose; a row must read its own
`options.token_env` (or its declared `env`) first and must not treat a bare `token_provider` as
its own — the shipped Jira and Azure rows do exactly this, and the `board_setup` axis, added
the same day so `init` stops naming the vendor whose board it creates, takes only the token the
tracker axis resolved for its kind.*

**The code is small; the commitment is not.** Adopting in-process as *the* extension model
closes the door on providers written in C# or Go, and on plugging one in without a
rebuild. That door should not be closed for installation convenience.

## 4. The precedent, and why it inverts the usual worry

Terraform providers are **separate binaries** in any language, launched by the core and
spoken to over gRPC. That is why thousands of them exist, written by people who never
spoke to HashiCorp.

The command that downloads them is `terraform init`.

So an `init` command is not the opposite of extensibility — in that model it *is* the
mechanism. What would limit us is not having an `init`; it is an `init` that only knows
how to install a Python package into its own virtualenv.

## 5. The door is open, and it was not planned

Out-of-process providers are only possible if what crosses a port can travel over a wire.

**A first pass grepped the port modules** for `Callable`, iterators, generators, file
handles, live client objects and `-> Any`, and found nothing. **That answer was wrong, and
the way it was wrong is worth keeping.** A grep tests the words a violation is usually
spelled with; it cannot see a violation spelled in the codebase's own vocabulary. Resolving
the annotations at runtime instead — `typing.get_type_hints` over every Protocol method,
against a *whitelist* of transportable types — found three real ones:

| what | verdict |
|---|---|
| `ChannelAdapter.start_listeners() -> list` returning live Socket Mode handlers, parked by the worker in a `noqa: F841` local | **fixed.** The provider owns what it opens; the caller keeps the adapter, which it had to anyway |
| `ChannelAdapter.say(project)` and `ConfirmingChannel.ask_to_confirm(project)` unannotated | **fixed.** An unannotated parameter is `Any`, and `Any` is the easiest way to smuggle a live object past a guard |
| the agent, reviewer and judgment ports taking a live `SandboxAdapter` | **kept, and it is architecture** — see below |

With those closed, every remaining port method takes and returns pydantic models,
primitives, `Path`, or containers of them. `Workspace`, `AgentContext` and `AgentRunResult`
are all `BaseModel`; `SandboxAdapter.run()` returns `tuple[int, str]`.

**So a remote transport is addable for seven of the eight axes without changing a single
contract** — the ports would not move, they would gain an implementation that speaks over a
wire instead of calling in memory.

**The eighth is the harness, and its exception answers a question this document leaves
open.** `CodingAgentAdapter.execute` receives a live `SandboxAdapter` because the harness
runs *inside* the box: it needs `sandbox.run(...)` to exec its CLI in the container. That
pair is physically co-located, so handing it an identifier instead would only move the
callback somewhere worse. The precise consequence: **the harness axis cannot go out of
process without a different contract; the other seven can.** An out-of-process harness
would take a box *identifier* and ask the Core to run things in it — a real design, not a
signature tweak.

None of this was designed for. What holds is a consequence of ADR-0022 §3 — *the contract
is derived from what the Core calls, never from what a provider offers*. A channel contract
built from what Slack offers would have handles and callbacks throughout. Built from three
calls, it is serialisable by happy accident — and the accident is now pinned by a test,
including the exception list, which cannot grow without someone claiming another pair is
co-located.

**One axis is already out-of-process and proves the shape works:** the box. Fargate
launches a task, the container sandbox launches a container, and neither runs in the
worker's process. Whatever protocol the other axes eventually need, that one has an
existing model to copy rather than a design to invent.

## 6. A worked example — should events go on a bus?

A concrete proposal, raised on 2026-08-02: make an `EventBus` the central abstraction.
Producers publish without knowing destinations; the file journal, metrics, state
projections and SSE register as subscribers; `TeeEventSink` demoted to an implementation
detail. It is a good question, and the answer is worth recording because it turns on
exactly this document's subject — which couplings are real, and where a boundary actually
falls.

### 6.1 The topology, which decides everything

```
BOX  (Fargate task — another machine, about to be destroyed)
  machine.py::_emit ──► TeeEventSink
                          ├─ FileEventSink   journal on the BOX's disk (dies with it)
                          └─ StdoutEventSink print → log driver → CloudWatch
                                                     │
WORKER  (another process, another machine)           │
  launcher.py::pump() ── _tail(CloudWatch) ◄─────────┘
                         events_from_logs(lines)
                         journal.emit(ev) → FileEventSink(dedup=True)  on the WORKER
                                                     │
PANEL  (App Runner — a third process)                │
  /api/jobs/{p}/{i}/stream ── reads the file ◄───────┘  → SSE to the browser
```

- `TeeEventSink` has **two construction sites**, both in `fargate/entrypoint.py` (133, 180),
  both with the same pair.
- There are **four real emitters**: `machine.py::_emit`, `promotion.py`,
  `activities.py:239`, and `launcher.py` re-emitting what it read back.
- **Metrics are a wholly separate path** — `MetricRecord`, `MetricSink`, `record()`, written
  straight to DynamoDB from the worker. It never touches the event path.
- **The panel subscribes to nothing.** It reads the file and re-serves it as SSE, with
  `id: v2-{n}` so a reconnect resumes.

### 6.2 What `TeeEventSink` actually is

Five lines of fan-out. No filtering, no ordering policy, no knowledge of its sinks. **It is
not the architecture's abstraction** — the `EventSink` Protocol is; Tee is a combinator
over it, and it exists for a local reason: the box entrypoint needs one `events=` argument
to reach two destinations.

Routing is not in the Tee. It was spread across **nine construction sites** picking a sink by
hand — the protocol-without-a-registry pattern of §2, which the `event` and `metrics` axes have
since closed. It was never a problem a bus would have solved.

### 6.3 Why a bus would not decouple what needs decoupling

**Producers already do not know their destinations.** `machine.py::_emit` calls
`self.events.emit(...)` against an injected `EventSink`; it cannot name a destination.
Dependency inversion is done. An in-process bus would swap one injected interface for
another.

**The real coupling is the transport across a process and machine boundary.** The box can
only reach the worker through stdout, because it is a different machine that is about to be
destroyed. No in-process bus crosses that. `StdoutEventSink` on one side and
`events_from_logs` + re-emit on the other would remain exactly as they are.

**And the architecture already has an event bus: Temporal.** Signals, queries, durable
history — that is where job state flows and survives a crash. The journal is a different
thing: a narrative for humans and agents. Standing up a second event backbone beside
Temporal is the actual risk in this neighbourhood, not the absence of one.

**The producer fan-in being designed for does not exist yet.** Four emit sites, and the
harness emits nothing at all — its output is captured as an `AgentRunResult`.

### 6.4 The defect the question did surface

The fan-out had no `try`/`except`. If the file journal raised — disk full, permissions — the
live stdout feed never ran and the exception propagated into `machine.py::_emit`, i.e. **into
the job. A failed journal write could kill a job.**

That is precisely the class ADR-0022 §3 legislated for `say`: *"returns whether it landed
and never raises — its callers are scheduled rounds, where an exception becomes a retry
storm and a silence becomes an agent that appears to have nothing to say."*

**Fixed, and the fix is in the fan-out rather than in each sink.**
`openfactory/observability/events.py` routes every fan-out through `_emit_isolated`, which
catches and reports: one sink that fails costs its own event and nothing else. The order the box
registers them is what makes that matter — file journal first, live stdout second — so without
isolation a full disk would also take away the only channel still capable of telling a human what
happened. It is deliberately distinct from `_never_raises`, which holds a sink we own to the
contract; this one protects the fan-out from a sink that does not honour it, which includes a
third party's.

### 6.5 Why everyone-gets-everything is currently right

Eight event kinds; the file is the journal and must hold all of them, and stdout is the
transport and must carry all of them. Filtering on write contradicts the journal's stated
purpose — *"the backbone that makes 'ask the framework how development is going'
answerable"*. **Filter on read.**

### 6.6 The trigger that would justify a bus

Recorded now so it is checkable later rather than re-argued:

> **Today every consumer is a recorder** — file, stdout, the panel's read. The day
> something must **react** to an event rather than record it — the tech-lead acting on an
> `error` live instead of polling state — there is real dispatch, and a bus earns its
> place.

### 6.7 The design, for when it does

Non-breaking by one choice: **`EventBus` satisfies `EventSink`**, so no producer changes.

```python
class EventBus:                       # is an EventSink: it has emit()
    def subscribe(self, sub: EventSink, *, kinds: frozenset[EventKind] | None = None): ...
    def emit(self, event: JobEvent) -> None:        # never raises
        for sub, kinds in self._subs:
            if kinds is None or event.kind in kinds:
                try: sub.emit(event)
                except Exception: log.warning(...)  # one consumer cannot fell the others
```

Incremental order:

1. **done** — the fan-out isolates failure and never raises (§6.4). No API change.
2. **done** — registries for `EventSink` and `MetricSink`, reached by the `event` and `metrics`
   axes of the entry-point group (§2). No API change.
3. **at the trigger** — `EventBus` drops into the two sites where the Tee is built.
   Producers untouched, because they already depend only on the Protocol.
4. **only when it hurts** — `kinds`, once a subscriber exists that is harmed by receiving
   everything.
5. **never** — the bus does not cross a process. Stdout out, `events_from_logs` in. That is
   transport, and it is §3's decision, not this one.

One note for whoever implements step 3: `FileEventSink` is conceptually already a
persistent subscriber, but it carries behaviour a naive one would drop — dedup on
`(ts, job_id, kind, message)`, which exists because the launcher re-reads a task's log from
the head on a retry.

## 7. The decision made in one step, not in the other — and the guard that keeps the second open

**The in-process step is decided** (ADR-0034, addendum of 2026-08-26): entry points on every
axis are how a stranger adds a provider, and §2 measures it. **The out-of-process model is
not**, and the recommendation for it is unchanged: do not choose it now; keep the guard that
keeps it available.

> Every port method signature stays serialisable — pydantic models, primitives, or
> compositions of them. No callable, file handle or live object crosses a port.

Enforced as a test in the existing style, this costs almost nothing and does the one thing
that matters: **a limitation can no longer arrive by accident.** Closing the door would
require making a test go red, which is a decision, not a drift.

With that in place, entry points become a cheap and *reversible* first step: start there
because it is small, knowing that moving to out-of-process later costs no contract change.

## 8. Distribution — the half of §1 this document owes an answer to

§1 separates *distribution* (how the bits reach the machine) from *extension* (how the running
system discovers a provider) and then spends nine sections on the second. The first is short,
and it is short because the extension model made it short:

    install <the core>                     a public index, Apache-2.0, the whole core
    install <an add-on> + rebuild          any package that declares rows in the group (§2)

**Neither line is a command to type yet.** Nothing in this repository is published to any index:
the core and both add-on packages are built from the tree as wheels and installed from a path,
which is why a refusal names the package that carries a row rather than an install command
(`openfactory/plugins.py::install_hint`). An add-on is installed into the worker image and the
image is rebuilt; the platform's code is baked into the image, so an install that skips the
rebuild changes nothing. That is the whole procedure, for every add-on, from any index a
deployment can reach — nothing in the core asks which index a package came from, and §2's rule is
what makes that answer stable rather than a current convenience.

There is no `openfactory install` verb, and the name is reserved rather than built. It waits on
§7's out-of-process question, because a verb written now would be the pip-only `init` §4 warns
against: it would know how to install into its own virtualenv and nothing about the image the
worker actually runs.

## 9. What would foreclose the option

Recorded so it is recognisable if it starts happening:

- a port method that takes a callback, a stream, or an open handle
- a port that returns an object the caller then calls methods on (a live client rather than
  data)
- a registry builder that receives the worker's own objects instead of configuration
- widening a port because a provider has a feature — the failure ADR-0022 §3 already names

## 10. The ledger — what is core, what is an add-on, and what is still mixed

The rule this document already states — *an axis is agnostic when it is born with two; a platform
is extensible when a stranger can add the third without editing our files* — needs a LIST to be
checkable, and the list needs a test so it stays true rather than becoming documentation of an
earlier tree. `tests/test_the_core_addon_ledger.py` derives the core→vendor edges from the code
two ways — a lazy `boto3`/`slack_sdk` import is a vendor dependency wherever it sits, and so is
an import BY PATH of one of the vendor-owned modules below — and fails when this ledger and the
tree disagree, in either direction.

**Core** is everything not listed below: the orchestrator, the contracts, the policy floor, the
action catalog, the panel, the durable runtime's spine, every `registry.py` on every axis, and
the namespace/environ migrations. Core imports no vendor SDK, even lazily — the test holds that
line.

**Vendor-owned** (an adapter file or a vendor package; deletable without touching core
behaviour). OWNERSHIP IS BY PATH, not by SDK import: most of the files below import no vendor
SDK at all — they reach GitHub, Azure DevOps and Jira through `gh`, `requests` and `httpx` — so
the test does not ratchet this list on an import it mostly does not have. It ratchets it on
EXISTENCE (measured 2026-08-25: two phantom entries passed, and every listed file could be
deleted with the guard green) and uses it as the map for the by-path scan below.
`adapters/agent/claude_code.py` is not here on purpose: the harness, its model and its
credential are configuration and therefore core (ADR-0040), and its only cloud-SDK lines moved to
`adapters/agent/s3_session_store.py`, which is on the vendor side.

**The vendor side is two sides now, and the public cut is the line between them** (the owner's
decision, 2026-08-24/26; [`docs/STATUS.md`](../STATUS.md) carries the path list a reader
checks). The public repository receives the tracked tree minus the AWS realisation and the chat
connectors; those paths are marked `leaves` below and reach a deployment as add-on packages.
Everything marked `stays` is a **reference provider the core ships**: GitHub, Azure DevOps and
Jira on the board, tracker, forge and CI axes — *"not a lock-in, an option, like GitHub"* — and
the three harness adapters beside the default. `tests/test_the_public_cut_is_written_down.py`
holds the two documents to each other and to the tree: every path STATUS excludes is on this
list, every entry that stays is still imported by a module that stays, and every entry that
leaves is reached by nothing that stays except the doors named in the next paragraph.

```yaml
vendor_modules:
  - openfactory/adapters/agent/s3_session_store.py  # leaves — the S3 face of the session store; its free twin is session_store.py
  - openfactory/adapters/agent/codex.py             # stays — a harness beside the default
  - openfactory/adapters/agent/kimi.py              # stays
  - openfactory/adapters/agent/opencode.py          # stays
  - openfactory/adapters/board/azure_devops.py      # stays
  - openfactory/adapters/board/jira.py              # stays
  - openfactory/adapters/channel/slack.py           # leaves — the chat channel
  - openfactory/adapters/environment/azure_pipelines.py  # stays
  - openfactory/adapters/environment/github_actions.py   # stays
  - openfactory/adapters/forge/azure_devops.py      # stays
  - openfactory/adapters/forge/github.py            # stays
  - openfactory/adapters/notify/slack.py            # leaves — the chat channel's push half
  - openfactory/adapters/notify/telegram.py         # leaves — the deployment-wide chat fallback
  - openfactory/adapters/tracker/azure_devops.py    # stays
  - openfactory/adapters/tracker/github.py          # stays
  - openfactory/adapters/tracker/github_project.py  # stays
  - openfactory/adapters/tracker/github_board_setup.py  # stays — the `board_setup.github` row
  - openfactory/adapters/tracker/jira.py            # stays
  - openfactory/adapters/azure_devops.py            # stays — shared ADO plumbing for the three ADO adapters
  - openfactory/adapters/github_app.py              # stays — GitHub App token minting, the `credential.github` row's mint
  - openfactory/observability/dynamo.py             # leaves — the DynamoDB face of the metrics axis; the `metrics.dynamodb` entry point
vendor_packages:
  - openfactory/runtime/slack/                      # leaves — the chat channel's runtime (ADR-0038)
  - openfactory/runtime/fargate/                    # leaves — the AWS box: box.py (the `box_runner.fargate` entry point), launcher.py, observe.py (the CloudWatch event tail, the `token_pool.ssm` entry point)
```

**How each side that leaves is reached today — measured, and since 2026-08-26 the two are alike:
both are a directory delete, and both are packages.**

- *The AWS realisation is a directory delete.* Its rows register through the `openfactory.adapters`
  entry-point group — `box_runner.fargate`, `metrics.dynamodb`, `session_store.s3`,
  `token_pool.ssm`, declared by `addons/openfactory-aws/pyproject.toml` — exactly as a stranger's
  would; the core DESCRIBES the `fargate` box (its traits are a pure row in
  `adapters/sandbox/registry.py`, so a job in flight can ask about it with no I/O) and no longer
  implements it; the engine dispatches on `installed_box_traits(kind).remote` and
  `remote_box(kind)`, never on a provider's name; the panel asks the box's traits, never a
  cluster variable; the metrics readers ask `isinstance(sink, ReadableSink)` and never fall
  through to a table name. Delete `runtime/fargate/`, `observability/dynamo.py` and
  `adapters/agent/s3_session_store.py` and the core imports, every registry answers, a missing
  add-on is refused naming the entry point and the package, and the gate is green —
  `tests/test_the_cloud_is_a_directory_delete.py` holds every line of that (an AST import-graph
  guard with its positive twin, the trait dispatch driven with a synthetic remote box, the
  declared entry points resolved for real). It was not always so: before 2026-08-25 the core
  imported those modules by name at fourteen sites, and the same delete gave 50 failures and 10
  collection errors. The four rows lived in the core's own `pyproject.toml` for two days after
  that, which made the delete true of the code and false of the metadata — the public wheel
  would have declared four entry points naming modules it does not contain; the core declares
  no row in the group now.
- *The chat connectors are a directory delete too.* Until 2026-08-26 their rows were built-in
  rows of two core registries — `adapters/channel/registry.py` (`slack`) and
  `adapters/notify/registry.py` (`slack`, and `telegram` as the deployment-wide fallback) — each
  importing its module lazily inside the row, so with those modules absent a project declaring
  `channel: slack` got a `ModuleNotFoundError` out of the row rather than a refusal by name. The
  three rows are `addons/openfactory-slack`'s entry points now (`channel.slack`,
  `notifier.slack`, `notifier.telegram`); the two tables hold `panel` and nothing else; a
  project declaring `channel: slack` on a deployment without the package is refused BY NAME
  with the package to install (`plugins.SHIPS_IN` maps each of the platform's own rows to the
  package that ships it — a package name, not a vendor's product); and the deployment-wide
  fallback is DECLARED (`OPENFACTORY_NOTIFIER_FALLBACK=<kind>`, a row on the notifier axis)
  rather than inferred from a vendor's two variables — the same inference the cloud cut removed
  from the box axis. `tests/test_the_chat_is_a_directory_delete.py` holds every line of that,
  and the guard above holds the set of modules that stay and reach a leaving path to EMPTY.

**The packages.** `addons/openfactory-aws` and `addons/openfactory-slack` are tracked in the
private repository and leave the public export with the paths they carry. Each is an OVERLAY:
its wheel carries the leaving modules byte-for-byte at their original import paths, copied from
this tree at build time (`addons/overlay_build.py` says why an overlay rather than a shim, which
would have nothing to import in the public tree, or a re-rooted copy, which would need every
internal import and path-string rewritten). `tests/test_the_add_on_packages_install.py` proves
it the way a stranger meets it: the public tree built into a wheel, installed into a scratch
environment, `channel: slack` and `remote_box("fargate")` refused naming the packages; the
packages installed; the rows resolving through the registries.

**Mixed — core modules that still reach a vendor.** The SDK half is paid: no core module
imports `boto3`/`slack_sdk`/`telegram`, lazily or otherwise — the Dynamo
sink/query/scan went to `observability/dynamo.py`, and the panel's CloudWatch feed + SSM
token-pool reads went to `runtime/fargate/observe.py`, the package that IS the AWS box add-on.
The BY-PATH half was not being measured until 2026-08-25, when the scan was widened to imports of
the vendor-owned modules above: ten core modules imported one by name, outside the places that
are allowed to — the registries (`adapters/<axis>/registry.py`, `observability/registry.py`, and
the board axis's, called `factory.py`), the composition root `factory.py`, and the per-axis seam
`adapters/agent/session_store.py`. Each is listed with what it reaches. The RATCHET is the point:
an entry whose import is gone must leave (the test fails on it), and a new vendor edge anywhere
in core must either move behind a registry or be added here with a reason — visibly, in a review,
never by drift. The notifier axis's registry (`adapters/notify/registry.py`, 2026-08-26) is one of
those registries, and since the chat cut the same day it dispatches to no vendor module at all:
its table is the panel, and the chat rows arrive as `openfactory-slack`'s entry points.

```yaml
mixed_modules:
  - openfactory/cli.py                          # adapters/github_app — `bot-token`, the deployment-level proof of the App trio (docs/setup/github.md)
```

Nine entries left this list between 2026-08-25 and 2026-08-26. Four went with the cloud cut,
when the DynamoDB and CloudWatch reads moved behind the metrics port and the box registry. Five
went when the API budget became a question on the tracker port (`TrackerAdapter.budget()`: a
`Budget`, the declared `NOT_REPORTED`, or `BudgetUnreadable` raised — never a `None` meaning
both) and the forge credential became a question on the credential registry: `actions/catalog.py`,
`api/app.py`, `doctor.py`, `floor/reading.py` and `runtime/temporal/activities.py` no longer
import a vendor module by name. What `cli.py` keeps is the one command that IS about the
reference vendor's App by name.
