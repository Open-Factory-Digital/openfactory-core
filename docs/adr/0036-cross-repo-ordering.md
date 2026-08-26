# ADR 0036 — Ordering across repositories: the product declares it, the floor enforces it

- **Status:** **Proposed** (design only — no code changes with this ADR)
- **Date:** 2026-08-02
- **Relates to:** ADR-0007 (the floor frees at merge — the rule this extends),
  ADR-0010 (strict single line), ADR-0013 D3 (parent/child linkage),
  ADR-0019 (the requirements repo), ADR-0033 (the decision kernel).

## Context

ADR-0007 established the rule that makes autonomous merging safe: **the floor frees at merge, not
at agent-done**, so the next ticket builds on a base that already contains the last one. It is
dependency safety by construction, and it works because the platform runs one line at a time
*within a project*.

A product that spans several repositories has no such guarantee. *"Change the API contract in the
back end, then consume it in the front end"* is two tickets in two repositories, and today nothing
connects them:

- **Grouping exists at the product layer.** The queue already proposes what only means something
  delivered together, and `link_child` / `children_of` (ADR-0013 D3) record a parent/child
  relation the tracker understands.
- **Ordering does not exist at the execution layer.** Two projects are two boards, two pollers and
  two independent floors. Nothing prevents the front-end ticket merging first, against an API that
  does not exist yet.

This is not an edge case for the deployments in view. Serverless with separate function
repositories, and C# with Azure Functions, are multi-repository with inter-repository dependencies
almost by construction.

**What C-17 already gave it is a home.** The context repository is the product entity: it owns the
board, the specification and the list of source repositories. A dependency between two of them is
declared where the product's shape is declared, so this ADR does not have to invent a third place
for it to live.

## Decision

**A dependency is declared in the context repository, and the floor refuses to free while an
unmet one exists.**

### 1. The declaration is a fact about the WORK, not about the repositories

The tempting shape is wrong:

```yaml
# NO. This says the front end always waits for the back end.
sources:
  - repo: acme/web
    depends_on: [acme/api]
```

A standing repository-level dependency is false most of the time — most front-end work touches no
contract — and a rule that is usually false gets routed around. What is true is narrower:

```yaml
# .sdlc/product.yaml, in the context repository
deliveries:
  - name: customer-sees-their-orders
    requirement: 0001
    steps:                       # ORDERED. Each waits for the one before it to MERGE.
      - repo: acme/api
        ticket: "#412"
      - repo: acme/web
        ticket: "#77"
```

A delivery is the unit the product role already reasons about — *what only means something
delivered together* — so this adds ordering to a grouping that exists rather than a new concept.

### 2. The floor rule extends rather than changes

ADR-0007 says a project's floor frees at merge. This adds one clause:

> **A ticket may not be picked up while an earlier step of its delivery is unmerged.**

Not "the other project's floor is held" — that would stall unrelated work in that repository, which
is a much larger cost than the problem. Only the *dependent ticket* waits, and the rest of its
board keeps moving.

The poller already asks "may I pick this up?"; this is one more question in that check, and it is a
pure predicate over declared state — which makes it a decision in the sense of ADR-0033 rather than
something new in the engine.

### 3. Waiting is VISIBLE, never silent

This platform's headline invariant is that no stall is silent. A ticket blocked on another
repository is a stall with a cause nobody can see from its own board, which makes it the worst
shape available: the card sits in TO-DO looking merely unstarted.

So a blocked step:

- moves to **Needs Action** with a comment naming what it waits for, the other repository, and the
  other ticket;
- is announced once in the product's channel, not on every poll;
- appears in the panel's attention list with the dependency as its reason.

"Waiting correctly" and "forgotten" must never look the same.

### 4. A cycle is refused at declaration time

`api → web → api` is a deadlock that would present as two tickets waiting for ever. The context
repository is validated when it is read — `resolve_product_link` is already the place — and a cycle
turns the product module OFF with the cycle named, exactly as a `docs_repo` mismatch does today.

### 5. What is deliberately NOT decided here

- **Automatic dependency detection.** Inferring "this front-end change needs that API change" from
  a diff is a research problem. Declared beats inferred, and the product role is already the thing
  that writes declarations.
- **Cross-repository rollback.** If step 2 fails after step 1 merged, the platform parks and asks a
  human. Automatic revert across repositories is a much larger promise, and one nobody asked for.
- **Ordering across PRODUCTS.** Out of scope: a dependency between two clients' products is a
  business relationship, not a delivery.

## Consequences

**Good.** The one thing that makes multi-repository products unsafe today gets an answer that costs
one predicate in the pickup path and one field in a file the client already owns. The declaration
is versioned and reviewable, and it lives with the product's shape rather than in a vendor's
configuration.

**Costs and open risks.**

- **A declared order is only as good as the declaration.** Nothing detects a dependency somebody
  did not write down, so the first cross-repository breakage will still be one nobody declared.
  This narrows the failure to "we did not say", which is at least diagnosable.
- **A step that never merges blocks its successor for ever.** The dependency needs the same
  staleness treatment a park gets (ADR-0020: three hours unanswered is forgotten, not waiting), or
  it becomes a new way to stall quietly — the exact failure §3 exists to prevent, arriving through
  the back door.
- **It presumes the delivery is known before the work starts.** A dependency discovered mid-flight
  means editing the context repository while a job is running, and the poller must read the
  declaration fresh each tick rather than caching it — a cache goes stale at its own write.
- **Two boards still show two half-truths.** Each repository's board shows its own ticket blocked;
  only the product's board shows why. That is an argument for C-18 (the product owns the board)
  landing first, and this ADR is much weaker without it.

## Addendum (2026-08-26): the statement of the gap, inlined

The Relates-to header above pointed at a document that stays private, so the sentence it was
borrowing is written here instead. The record's reasoning is untouched; this only stops the
pointer dangling.

**What exists.** `link_child` / `children_of` (ADR-0013 D3), and the floor that frees at merge so
the next ticket builds on a base that includes the last — **serial within one project**. At the
product layer the queue already proposes what only means something delivered together.

**What does not exist.** Any execution-level guarantee of merge order *across* repositories.
Grouping is a product-role concept; sequencing is not an executor one. This has to be designed
rather than assumed, and it is not optional for the shapes already in view: separate function
repositories per service, and stacks whose deployment unit is naturally one repository per
component, are multi-repository with inter-repository dependencies almost by definition.

**What the product's declared shape gives it is a home.** Once the product's repositories are
declared in one place, the dependency between two of them is declared in that same place — so
designing this later does not also mean inventing a third location for it to live. That is the
premise the decision below rests on, and it is why this ADR is much weaker without the product
owning the board.
