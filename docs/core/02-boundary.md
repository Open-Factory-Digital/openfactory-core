# 02 — The boundary

Where the Core/Engine/Application line actually falls, the six things that resist it,
and the one design move that unlocks the rest.

---

## 1. The test for "is this Core?"

Three questions. A module is Core only if all three answer yes.

1. **Would it be identical for a client on Jira + GitLab + Teams + Codex?**
   If a provider's name, format, or quirk changes the code, it is not Core.
2. **Can it be executed with no I/O, no clock, and no network?**
   Core decides; it does not act. A module that awaits, sleeps, retries, or writes is
   Engine or Provider.
3. **Would deleting it change what the factory *means*, rather than how it runs?**
   If the answer is "it would just run differently", it is Engine.

Applied to the current tree:

| Module | Q1 | Q2 | Q3 | Verdict |
|---|:-:|:-:|:-:|---|
| `contracts/` | yes | yes | yes | **Core** — and the vendor-name AST guard is on |
| `orchestrator/machine.py` | yes | no — subprocess, timeouts, polling | yes | **Core policy + Engine execution, currently fused** |
| `orchestrator/merge_policy.py`, `validation.py` | yes | yes | yes | **Core** — the cleanest examples in the tree |
| `orchestrator/promotion.py` | yes | no | yes | Core policy + Engine |
| `policy/` | yes | yes | yes | **Core** |
| `runtime/temporal/workflow.py` | no | no | **yes** | **The entanglement** — §3 |
| `runtime/temporal/activities.py` | no | no | no | **Engine** |
| `adapters/*/base.py` | yes | yes | — | **Core** (the ports) |
| `adapters/*/<vendor>.py` | no | no | no | **Provider** |
| `product/`, `api/`, `techlead/` | ~ | no | no | **Application** |
| `knowledge/` | yes | no | no | **Application**, port-worthy later |

`merge_policy.py` (69 lines) and `validation.py` (34 lines) are worth reading as the
reference shape: pure functions over domain types, no adapters, no clock, decisions only.
That is what the extracted lifecycle should look like at ten times the size.

## 2. The six entanglements

Ranked by cost to resolve.

### E1 — Durable execution shapes the lifecycle *(largest)*

Domain policy is written inside `@workflow.defn` code under replay rules, and the permanent
`workflow.patched()` gates are the receipt: a Core that ships
`workflow.patched("park-marks-needs-action")` is not engine-agnostic, whatever its Protocols say.
`tests/test_the_core_boundary.py` holds the line the other way — no `workflow.patched()` may
appear in a module the Core test below admits.

The reason this is not simply bad design: the factory's most valuable behaviours are
*long and interruptible by nature*. "Park awaiting a human's production approval for
three days, survive a worker deploy, never lose the job, never double-merge" is not
expressible in plain Python. It requires durable execution, and durable execution has
opinions about how you write code.

Resolution: §3.

### E2 — The runtime speaks GitHub refs *(medium, already scoped)*

ADR-0022 §5 lists these precisely: `^#?\d+$` at the API door, `f"#{issue.lstrip('#')}"`
in worker and box sites, `ProviderRef(kind="github")` fabricated inside the sandbox
because `BoxConfig` does not carry the tracker kind. A survey found roughly fifteen sites
outside the GitHub adapter, plus a class ADR-0022 missed: **`int(str(ref).lstrip("#"))` raises
rather than degrades** on any ref that is not a bare number — `openfactory/contracts/refs.py` is
where that parsing lives now, and where a second tracker's spelling is a supported input rather
than an exception.

ADR-0022 prices this as *"touching ref handling on durably-replayed workflow paths"*, and
that turns out to overstate it: `issue` crosses the workflow boundary as a plain `str` in
every typed input in `runtime/temporal/io.py`, and a Jira ref is still a string. **No
workflow-visible type changes**, so this does not interact with E1 the way the ADR feared.
It is a ref-handling discipline plus a guard, and the ADR's judgment that it is deliberate
work scheduled before the first Jira client stands.

### E3 — The engine is not behind a contract *(medium)*

`runtime/` is 9,550 lines with no `EngineAdapter` port. There is no `Execution`
capability, so *"implement the Workflow capability and no Core changes are required"* has
nothing to implement against. The contract cannot be written honestly
before E1, because until the lifecycle is separable you cannot know what the Core asks an
engine for — and writing it early would produce a Temporal API in disguise, which
principle 5 forbids.

Order matters here: **E1 before E3.**

### E4 — The box axis has no seam, and infra selection sits in the lifecycle *(medium)*

ADR-0022's audit graded eight axes and marked **sandbox** as "fine": two implementations, a
Protocol, dispatch. That is the one row it got wrong, and the reason it escaped is that
**Fargate does not look like an adapter.**

It is not an implementation of `SandboxAdapter`. It is a parallel path:

    if inp.sandbox == "fargate":  <launch a task>   else:  <use SandboxAdapter>

selected by roughly eight sites — `factory.py`, `activities.py` (3×), `api/app.py` (2×) —
and, worst, **three of them inside the workflow body** (`workflow.py` 444, 486, 728), with
`sandbox: str = "fargate"` as the default in three places in `io.py`. The non-Fargate path
is treated as dev/test rather than a supported runtime: `activities.py:771` comments
*"local dev/test: run the repair inline"*.

Two consequences:

- **It blocks a local distribution.** Running without the cloud means taking a path the code
  itself calls dev/test — so the shape a stranger runs first is the one nobody supports.
- **It is the same disease as E1, in miniature.** *Where a job runs* is an engine concern
  that has leaked into the lifecycle. Under §3's model the Core emits `RunJob(…)` and the
  engine picks Fargate or Docker — so removing these branches is not preparation for the
  decision kernel, it is the decision kernel's first and cheapest win.

**Closed, and measured (2026-08-24).** The sites above are gone: `activities.py`, `view.py`,
`io.py` and `api/app.py` compare a box to a provider's name at **zero** sites (guarded, by AST:
`test_the_engine_never_compares_a_box_to_a_providers_name`), the workflow body asks
`params.traits()` and never the table, the default box is `OPENFACTORY_SANDBOX` or the
container, and the `fargate` runner arrives through the `box_runner.fargate` entry point — the
core describes that box and no longer implements it ([07](07-extensibility.md) §10). What
remains is written down rather than hidden: the promotion phases have no local implementation
yet and refuse by name on a local box.

### E5 — a chat vendor was in the domain model *(small)*

The domain model carried one vendor's name in its own field names — `slack_channel`,
`slack_admins`, `handoff_to_slack()`. Small diffs, and the value of closing it was never the
code: an AST guard banning vendor names in the Core kernel can only be *turned on* once they are
gone, and an unenforced principle decays.

**Closed, and enforced.** The fields are `channel_id` and `admins`; the old spellings survive
only as pydantic `validation_alias` entries, so a registry written before the rename still loads.
`tests/test_kernel_names_no_vendor.py` is the guard, and it is an AST walk over identifiers
rather than a text search — comments and docstrings may name the vendor that taught a lesson,
which is why the guard reads the tree the way the interpreter does. Its second half is the one
that matters more: a reader that still asks for a renamed field does not raise after a rename, it
returns `None` and the factory goes quiet with every test green, so the guard hunts those readers
by name too.

### E6 — Every action was written twice, once per transport *(large)*

`contracts/decision.py` opens with *"API-FIRST: this model is transport-agnostic. The panel
renders it as buttons, but a chat surface…"*. That was **true of the model and false of the
system** — the same shape as ADR-0022's opening line, one floor up: *the protocols were
honest and the composition root was not.*

Measured when this page was written:

    the chat front end calling the HTTP API   zero httpx / requests / aiohttp
    a shared action or service module          did not exist

                        the panel   the chat bot
        resume              12            29
        skip                21            42
        approve             36            14
        promote              8             0     ← panel only
        enabled              7             0     ← panel only

Two independent front ends, each wired straight into the internals — the chat one imported the
board builder, the tech-lead builder, the sandbox, the project registry and the key materialiser,
and never an API client.

**The divergence was a live defect, not untidiness.** A human in the chat surface — the one that
is always watching, and the one ADR-0016 built an authorization model for — could not promote a
release or enable a project. Two front ends do not drift because someone was careless; they drift
because the second implementation of an action is written by whoever needs it next.

**And it put an application inside a provider.** The chat connector's runtime was about 3,800
lines, of which the bot (1,071) and the product conversation (1,931) were not transport at all:
they built boards, constructed a tech-lead agent, cloned a repository into a sandbox, and read
the memory ledger. In the layer model of [00](00-vision.md) §5, applications consume the SDK and
providers implement capabilities. **The tech-lead was an application living inside a provider**,
which is the stack upside down — and it *acted*: resume, skip and release approval were product
actions locked inside a chat vendor.

*(Closed. The product conversation is `openfactory/product/channel.py`, history kept; the shared
settling stage the panel's turn and the chat handler both call lives there, and
`tests/test_the_product_conversation_is_core.py` is the guard this page said D3 lacked. What
remains of the connector is transport, and it is an add-on package —
[`../STATUS.md`](../STATUS.md) lists the paths that leave with it.)*

This is the same disease `ask()` already cured on the harness axis, where every judging role was
hand-written into one vendor's adapter until it collapsed into a single primitive that takes the
role as a parameter. Same cure: the conversational tech-lead becomes neutral code that a channel
*delivers*, and the channel adapter goes back to being transport.

**What was missing has a name: the action layer** — everything the factory can be asked to do,
expressed once, transport-free.

    resume(project, issue, by) -> Outcome        promote(project, issue)
    skip(project, issue, by)                     enable(project, bool)
    approve_prod(project, issue, version, by)    scan(project)
    ask(project, question) -> answer             diagnose(project, issue) -> HandOff

Values in, values out. No HTTP, no markup dialect, no button. Authorization (ADR-0016) is a
parameter — *who asked* — not a property of the transport. Then the HTTP app is a thin HTTP
mapping, a chat bot a thin chat mapping, the panel-as-channel a third, and CLI, MCP and webhook
come free.

**Closed, and it is where the SDK layer became concrete.** `openfactory/actions/` is that layer:
`base.py` holds three types and nothing else — `Actor` (who asked), `Outcome` (values out, with a
shared `code` each front end renders its own way, and never an exception) and `ActionSpec` (a row
in a table, so *which actions exist* is data a test can walk). `catalog.py` holds the rows. Every
implementation is `async`, so the transports share one calling convention, and lazy-imports its
dependencies, so the panel keeps working without the durable engine's client on the path.

**The bar, in the style of "born with two":**

> **Every action the factory can perform is reachable through at least two transports, and
> none of them implements it.**

That is a property a test can walk, which is what separates a standard from an intention: the
catalog is data, the transports are mappings over it, and an action added to one front end alone
has nowhere to live.

#### E6b — the same gap seen from the security side: there is no "who"

Authorization living in the transport produces one authorization model per transport. There were
two, and they did not know about each other:

| | model | what it actually was |
|---|---|---|
| the panel | `OPENFACTORY_PANEL_TOKEN` | **a shared password, not an identity.** Gated every `/api/*` when set; **unset meant fully open** |
| the chat surface | `project.admins` | an allowlist of user ids per project; empty = read-only for everyone (ADR-0016) |

**The deepest problem was never the absence of SSO, it was the absence of a subject.** With one
shared token everybody holding it is the same person, so *who approved that production release*
has no answer at all. One surface had a notion of who and the other did not, so the same action
had two different meanings of "permitted", one of which did not exist.

**The action layer's `by` parameter is the fix, and it splits cleanly:**

- **Identity — *who is this?* — is a capability.** A provider axis: a local token, OIDC, SAML, a
  directory, a forge's OAuth. A transport's only job is to *establish* the subject.
- **Authorization — *may they do this?* — is Core policy.** It is a decision about a domain action
  and belongs beside the rest of the policy, not inside each front end.

**Identity is a derived capability, not an invented one** — derived from the fact that **an action
needs an actor.** That is the test principle 5 applies to every capability, and identity passes it
for exactly that reason rather than because a platform is expected to have one.

**Closed, and the sequencing was the whole point.** `openfactory/identity/` is the axis: a port, a
registry, a local implementation, and `identity.<kind>` in the entry-point group, so a directory
or an SSO provider is a row somebody installs rather than a rewrite. A `Subject` is deliberately
not an `Actor`: a subject is who a credential turned out to belong to and carries no decision,
while an actor carries one — which is what stops a provider from being able to grant itself
permission. Identity answers *who*, policy answers *may they*, and only the second is allowed to
say yes. Adding SSO before the action layer would have implemented identity twice, independently,
in the one layer where that is most expensive to undo.

## 3. The unlock: the Core as a decision kernel

One move resolves E1 and makes E3 writable, and it pays for itself on any single engine before
a second one exists.

**Today** the shape is:

```
   Temporal workflow  ──►  activity  ──►  JobRunner  ──►  adapters
   (policy + control)      (side effects)  (policy + execution)
        ▲
        └── domain rules live here, under replay rules, behind patch gates
```

**Proposed:**

```
   Engine (Temporal today)                     Core (pure)
   ────────────────────────                    ───────────────────────────
   loop:                                       decide(state, event) -> [Effect]
     effects = core.decide(state, event)  ◄──  no I/O · no clock · no vendor
     for e in effects:                         no await · fully unit-testable
        result = await execute(e)  ──────►     (Effect is a value, not a call)
        state  = core.apply(state, result)
```

The Engine keeps everything it is good at — durability, retries, signals, timers, the
three-day park. The Core keeps everything it should own — *what to do next, and when to
give up*. `Effect` is a value object (`OpenPR`, `RunValidation`, `AskHuman`, `Sleep`,
`Escalate`), never a call.

**Four consequences, each independently worth the work:**

1. **The escalation ladder becomes testable with no Temporal import.** Today, verifying
   "after N failed CI repairs, park and ask a human" means a workflow test environment.
   After, it is a pure function over a state value — the same thing `merge_policy.py`
   already is.

2. **`workflow.patched()` stops multiplying — and this is the big one.** The gates exist
   because policy lives in workflow code. Once the workflow body is a *generic
   interpreter over effects*, it stops changing when policy changes, so it stops needing
   new gates. Better: the job can **pin its policy version at start**, so an in-flight
   job keeps the rules it began under and a new job gets the new ones. That is impossible
   while the policy *is* the workflow code, and it directly retires the recurring pain
   recorded as *"workflow changes need patched()"*.

3. **The `Execution` capability becomes writable.** With a real list of effects the Core
   emits, the engine port is derived from what the Core *calls* — satisfying principle 5
   — rather than guessed from Temporal's surface.

4. **The Core becomes ordinary Python.** No `temporalio` import, no determinism rules, no
   sandbox restrictions on the standard library. That is the difference between something
   a stranger can read and something only this team can safely edit.

**The honest costs.** This is a real refactor of ~2,600 lines across `workflow.py` and
`machine.py`, on the hottest path in the product, with live jobs in flight. It must be
done incrementally behind the existing patch gates — the last set of gates the platform
should ever need. And the first version will get the `Effect` vocabulary wrong somewhere;
that is normal and cheap to correct while there is exactly one engine, which is another
argument for doing it *before* a second engine exists rather than after.

## 4. What the Core is, concretely

If all of the above lands, the Core is roughly 3,000–4,000 lines:

    domain model          contracts/, held vendor-free by a vendor-name AST guard
    lifecycle kernel      decide/apply extracted from machine.py + workflow.py
    policy                gates, floors, merge policy, escalation ladders, budgets-as-policy
    ports                 the capability Protocols, incl. a new Execution port
    conformance           the suite a third party runs against their adapter

And the Core is *not*: durability, scheduling, retries, cost tracking, harness routing,
the product role, the tech-lead, the panel, the knowledge layer, or any provider.

Note the asymmetry, and take it as encouraging rather than deflating: the Core is the
**smallest** part of the platform. That is what a good core looks like — most of what a factory
does is engine, provider or application, and the part that decides what the factory *means* fits
in a few thousand lines somebody can read in an afternoon.
