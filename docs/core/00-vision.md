# 00 — Vision

> The operating model of AI software factories, not another AI coding tool.

This is the north star: what the platform is trying to become, and the layer model everything
else in this repository is arranged against. It states principles, not status — what works today
is measured in [`../STATUS.md`](../STATUS.md), which is the one place a count of this repository
is written down.

---

## 1. The thesis

Kubernetes did not win because it ran containers. Docker already ran containers.
Kubernetes won because it defined a **declarative resource model** for "what a running
system should look like", a **reconcile loop** as the one extension pattern everyone
learns once, and a **conformance suite** that let a hundred vendors claim compatibility
and be checked on it. The clouds became implementations of somebody else's vocabulary.

OpenFactory should do the same to AI software factories. Not "the best harness
orchestrator" — the **vocabulary and operating model** that harness orchestrators are
built in.

The operating model itself is not a proposal: tickets are picked up, implemented, validated,
reviewed, merged and deployed with no human approving each step, with per-task cost telemetry and
more than one deployment behind it. What that evidence does not by itself make it is a *platform
other people build on*, and this document is about the difference.

## 2. What separates a product from a platform

Three things, and only the third is hard:

1. **A stable vocabulary.** Frozen deliberately — ADR-0001, extended by ADR-0026.
   Organization, project, board, ticket, job, run, gate, park, handoff, promotion,
   acceptance.
2. **Replaceable everything else.** Every provider axis sits behind a registry, no module
   outside a provider's own package names a concrete vendor class, and an AST test enforces
   it (ADR-0022). The axis names are published by `openfactory/plugins.py::AXES` and an
   add-on joins them from outside through an entry point ([07](07-extensibility.md) §2).
3. **A way for a stranger to prove their implementation is correct.** This is the actual
   platform deliverable. `openfactory conformance-adapter <kind> <target>` is the first
   instalment of it; the bar is a suite complete enough that a green run is what "compatible"
   means, and the claim is checkable by someone with no access to this repository.

## 3. Principles

Six, and the last two are the ones a stranger writing an adapter most needs to be told —
they are what made the existing seams survive contact with production.

1. **The Core names no vendor** — no AWS, Slack, Claude, GitHub, Postgres, Temporal. A vendor
   is reached through a port, chosen by a registry, from configuration.
2. **Everything outside the Core is replaceable**, and replaceable means *replaced by someone
   who is not us* — an entry point, not a pull request.
3. **An application built on this is not the Core**, whoever builds it. It consumes the same
   SDK surface a stranger's application would, and gets no private door.
4. **The Core is useful by itself.** Open source is not a demo: nothing that ships here is
   removed to manufacture an upgrade path ([07](07-extensibility.md) §2).
5. **A contract is derived from what the Core *calls*, never from what a provider *offers*.**
   §4 is why this is the whole design.
6. **An axis is agnostic when it is *born with two*, not when it declares an interface**
   (ADR-0022).

## 4. Why principle 5 is the whole design

Take the channel axis. A chat connector is a large thing — sockets, threads, its own markup
dialect, pending confirmations, channel routing — and the Core asks it for **three** things:
*post this*, *how do I address this person*, *start listening*.

A `ChannelAdapter` derived from what one chat vendor **can do** would be that vendor's API
wearing a protocol, and the second connector would have to fake half of it. Derived from what
the Core **needs**, the second connector implements three methods. That is why the chat channel
could later leave the tree entirely and become an add-on package without the port moving.

The same law explains the axis that was never a problem: the **stack**. The platform
names no build command anywhere — no `mvn`, `dotnet`, `composer`, `npm`. The client's
manifest declares `validate:` and the framework runs what it is given, so Java, PHP, C#,
Python and serverless deployments already work with nothing new. That is what a solved
axis looks like, and it was solved by asking what the Core calls rather than what a
toolchain offers.

Every capability in the Core is held to this. A capability that grows because a provider
has a feature is a leak with a Protocol on it.

## 5. The corrected layer model

The obvious drawing of a factory stacks seven layers with Capabilities and Providers as two of
them. That is one layer too many and one relationship inverted. Capabilities are not a *layer* —
they are the *boundary*, and the same boundary appears at more than one height. And the execution
engine is not below the Core in control flow: it is the **caller**.

```
   APPLICATIONS        product role · tech-lead · panel · board · CS · metrics
        │                                      business logic, not Core
        │ consume
   ═════╪═══════════════════════════════════════  SDK  (the stable API surface)
        │
   CORE                domain model · lifecycle policy · contracts · conformance
        ▲                        knows WHAT · pure · no I/O · no vendor · no clock
        │ drives (calls in, never called back)
   ENGINE              durability · scheduling · budgets · routing · recovery
        │                                  knows HOW · vendor-shaped by nature
   ═════╪═══════════════════════════════════════  CAPABILITIES  (ports)
        │
   PROVIDERS           temporal · claude_code · github · slack · postgres · s3
```

Two corrections carry weight:

**The Engine drives the Core; the Core never calls back.** In the code today, Temporal's
workflow *is* the driver: it calls activities, which call the `JobRunner`. Inverting that
on paper does not change it. The honest formulation is that the Core exposes a pure
decision — `decide(state, event) → effects` — and the Engine executes those effects
durably. That keeps the dependency arrow pointing at the Core while admitting the Engine
holds the control flow. It is also the concrete unlock for everything else; see
[02](02-boundary.md) §3.

**Capabilities are a boundary, drawn twice.** The Core reaches providers through ports.
The Engine reaches providers through ports. It is the same discipline applied at two
heights, not two layers stacked.

**And the SDK layer has a concrete meaning: it is the action layer.** Drawn on a diagram and
left empty, "SDK" is a box that means whatever the reader supplies. Here it
is the set of everything the factory can be *asked* to do, expressed once and free of
transport — `resume`, `skip`, `approve_prod`, `promote`, `enable`, `scan`, `ask`,
`diagnose`. Values in, values out; authorization is a parameter naming who asked, not a
property of the transport carrying the request.

That closes the Core's surface from both sides. `decide()` is what the factory resolves on
its own; the actions are what a human may ask of it. Everything above — panel, chat,
CLI, MCP, webhook — is then a mapping, and none of them may implement an action. Where that
stands, and the guard that holds it, is [02](02-boundary.md) E6.

## 6. Domain concepts

The Core owns the business language, and this language is **already frozen** — ADR-0001
fixed it, ADR-0026 extended it for the product role. It is not up for redesign: a renamed
vocabulary would invalidate every decision record that reasons in it, for cosmetics.
[`../adr/`](../adr/) is where those records are.

    Organization · Project · Board · Ticket · Job · Run · Gate · Validation
    Review · Decision · HandOff · Park · Promotion · Acceptance · Manifest
    Role · Harness · Budget · Policy · Event · Artifact

Words that look missing usually are not. *Approval* is a `Decision` with an authorization gate
(ADR-0016); *Handoff* is `HandOff`; *Dependency* is the ordering a board already carries. Adding
synonyms to a frozen vocabulary is how a shared language dies. A genuinely new concept enters by
ADR, as they always have.

## 7. The long-term goal

    "I built my AI software factory on OpenFactory."

Said the way people say it about Kubernetes: not as praise, as a boring statement of what
the substrate is.

The measurable form of that goal — the one that can be checked rather than admired — is:
**someone outside this project ships an adapter nobody here wrote, proves it with the published
conformance suite, and runs a factory nobody here deployed.** That sentence is also the
definition of done for this whole line of work: a piece of it is finished when it has moved that
sentence closer to being sayable by a stranger, and not when it has been merged.
