# ADR 0033 — The lifecycle decides in pure code; the engine only executes

- **Status:** **Proposed** (design only — no code changes with this ADR)
- **Date:** 2026-08-02
- **Relates to:** ADR-0001 (the deterministic maestro), ADR-0009 (durability), ADR-0012 (perfect
  resume after pause), ADR-0013 (effort budget + recovery), ADR-0014 (advisory review),
  ADR-0022 (provider seams — the rule this copies one floor up),
  [`docs/core/02-boundary.md`](../core/02-boundary.md) §3 (where this came from).

## Context

The factory's most consequential rules — when to stop repairing CI, when to rebase, when to give
up and ask a human, when a review finding blocks — do not live with the rest of the domain logic.
They live inside `runtime/temporal/workflow.py`, in `@workflow.defn` classes, written under
Temporal's replay rules.

That is not an accident of tidiness. The behaviours those rules govern are *long and interruptible
by nature*: "park awaiting a production approval for three days, survive a worker deploy, never
lose the job, never double-merge" is not expressible in plain Python. Durable execution earned its
place. But it has opinions about how you write code, and those opinions have now reached the
business rules.

**The receipt is nine permanent patch gates.** `coordinator-narration`, `flag-review-findings`,
`knowledge-pipeline`, `merge-self-heal-clean`, `park-marks-needs-action`, `park-says-needs-action`,
`park-techlead-diagnosis`, `record-job-metrics`, `techlead-self-heal`. Each exists because changing
a domain rule means changing workflow code, and changing workflow code breaks replay for in-flight
jobs. None can ever be deleted while any history references them. The list only grows.

Three consequences follow, and the third is the one that matters commercially:

- **The rules are hard to test.** Verifying "after two failed CI repairs, park and ask a human"
  needs a Temporal test environment. `orchestrator/merge_policy.py` — 69 lines of pure functions
  over domain types — shows what the alternative reads like.
- **The rules cannot vary per client.** Two deployments wanting different escalation ladders means
  branching inside a replayed workflow body.
- **A Core that ships `workflow.patched("park-marks-needs-action")` is not workflow-engine-agnostic**,
  which is one of the three things this platform is sold on.

## Decision

**The Core decides in a pure function. The engine executes what it decides and owns nothing else.**

```
   Engine (Temporal today)                     Core (pure)
   ────────────────────────                    ───────────────────────────
   loop:                                       decide(state, event) -> [Effect]
     effects = core.decide(state, event)  ◄──  no I/O · no clock · no vendor
     for e in effects:                         no await · fully unit-testable
        result = await execute(e)  ──────►     (Effect is a VALUE, not a call)
        state  = core.apply(state, result)
```

The dependency arrow points at the Core; the control flow does not. The engine is the caller and
the Core is the callee, and **the Core never calls back**.

### 1. `Effect` is a value, never a call

`OpenPR(...)`, `RunValidation(...)`, `AskHuman(...)`, `Sleep(...)`, `Escalate(...)`,
`RunJob(...)`, `Notify(...)`. A pydantic model in `contracts/`, subject to the same serialisability
rule the ports already keep ([`test_ports_are_serialisable.py`](../../tests/test_ports_are_serialisable.py)).
An `Effect` that carried a callable would put the engine back inside the Core.

### 2. The state is reified LAST, not first

This is the part the design discussion keeps skipping, and the part that decides whether the
migration is safe.

The lifecycle's state is not in a struct today. It is local variables and instance attributes in
the workflow body: `attempts`, `rebases`, `pause_resumes`, `rate_resumes`, `self._paused`,
`self._skipped`, `self._signals`. A first cut that tried to define `JobState` as one object would
be a rewrite, land in one commit, and touch every gate at once.

So the order is inverted. **Each rule becomes a pure function over the values it already reads**,
called from the workflow where the rule used to be inlined:

```python
# in the Core, testable with no temporalio import
def decide_ci_repair(*, attempts: int, ci: str, max_attempts: int) -> CiDecision: ...
def decide_merge(*, mergeable: str, rebases: int, max_rebases: int) -> MergeDecision: ...
def decide_escalation(*, resumes: int, max_resumes: int, retry_at: str | None) -> Escalation: ...
```

That is exactly the shape `merge_policy.py` and `validation.py` already have, and it is why they
are the two cleanest modules in the tree. Only once every rule is a function does a state object
have an honest definition — it is the union of what those functions ask for, discovered rather than
guessed.

### 3. A job pins its policy version at start

The payoff, and the reason this is worth doing at all.

Once the workflow body is a **generic interpreter over effects**, it stops changing when a rule
changes — so it stops needing a new gate. Better: the job records which policy version it began
under, and the interpreter resolves rules through that version. An in-flight job keeps the rules it
started with; a new job gets the new ones. Both are correct, and neither needs a patch gate.

This is impossible while the policy *is* the workflow code, because there is nothing to version.

### 4. Migration order — smallest blast radius first

Each step lands **behind an existing patch gate**, leaves observable behaviour identical, and
*removes* a reason to add a future gate.

1. the escalation ladder (`_MAX_PAUSE_RESUMES`, backoff) — self-contained, well bounded
2. the merge decision loop (`behind` / `dirty` / `clean` / `unstable`, `_REBASE_MAX`)
3. the CI-repair loop and `_CI_REPAIR_MAX`
4. park → diagnose → needs-action → notify
5. review-finding severity gating

**The reachability guard:** the extracted policy has tests that import no `temporalio`, and a test
asserts the Core package's transitive import set excludes it. Without that, the rules can be moved
and still be unreachable — this repository's signature defect.

### 5. What stays in the engine, explicitly

Durability, retries, signals, queries, timers, the three-day park, continue-as-new, heartbeats,
the child-workflow tree, and **where a job runs**. `if sandbox == "fargate"` inside the workflow
body ([`docs/core/02-boundary.md`](../core/02-boundary.md) E4) is an engine concern that leaked
into the lifecycle; under this model the Core emits `RunJob(...)` and the engine picks the box.
That is why removing those branches is not preparation for this ADR — it is its first and cheapest
increment.

### 6. Do it now, not later

The cost of touching `workflow.py` is a function of how many jobs are in flight and how many
deployments share the history. Today that is one deployment with a paused poller. With three
clients it is three histories, three sets of in-flight jobs, and three clients wanting different
ladders.

**The cheapest this will ever be is while the floor is empty.**

## Consequences

**Good.** The factory's most consequential rules become unit-testable without a Temporal test
environment. The `workflow.patched()` tax stops compounding. Policy can vary per deployment without
branching inside replayed code. And `docs/core/02-boundary.md` E3 — the `Execution` capability that
has nothing to implement against — becomes writable, because the list of effects the Core emits
*is* the engine contract, derived from what the Core calls rather than from Temporal's surface
(ADR-0022 §3, one floor up).

**Costs and open risks.**

- **It is a real refactor of ~2,600 lines on the hottest path in the product**, with live jobs in
  flight. There is no version of this that is small.
- **The first `Effect` vocabulary will be wrong somewhere.** That is normal and cheap to correct
  while there is exactly one engine — which is another argument for doing it before a second one
  exists rather than after.
- **The nine existing gates never go away.** This stops the list growing; it cannot shorten it.
- **A generic interpreter is harder to read than an explicit workflow.** The gain is that the thing
  it interprets is readable, testable and versioned; the loss is that "what happens next" is no
  longer answerable by reading one function top to bottom. Worth stating plainly rather than
  discovering in review.
- **Policy versioning adds a migration surface of its own.** A version that no longer resolves —
  because somebody deleted an old rule — must fail loudly at job start, not silently fall through
  to current behaviour. That is the same rule ADR-0022 gives unknown provider kinds, and it needs
  the same discipline.
