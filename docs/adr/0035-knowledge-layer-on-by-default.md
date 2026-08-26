# ADR 0035 — The knowledge layer becomes the behaviour, not an experiment

- **Status:** **Accepted** (2026-08-02) — revises ADR-0017 §"gate" and ADR-0023
- **Related:** ADR-0017 (the Knowledge Layer), ADR-0023 (the map is derived, not learned),
  ADR-0014 (frontier by default)

## Context

ADR-0017 shipped the knowledge layer **opt-in and switched off everywhere**, behind an explicit
rule: *the layer does not advance until the cost per ticket actually falls*. `knowledge_map`
existed to be A/B'd on the cost dashboard, and `docs/architecture.md` §9 called that dashboard
"the instrument that opens the next step".

The step was opened. The product owner, 2026-08-02:

> *"this has already proved it is very efficient — I do not even want to keep it as something you
> announce. With the code as ground truth, the freshness is in theory already there. We had left it
> in A/B mode, but now it is for real."*

## Decision

**`knowledge_map` becomes `true` by default.** It stops being an option a project switches on and
becomes how the factory works.

### 1. A default is only safe because of freshness, and the freshness already exists

This is not optimism — it is a property ADR-0017 §12 already built, and which is only now being
collected on. The bundle is injected **exclusively** when the checksums prove it describes the
checkout of *that job*. A map that is missing, stale or orphaned degrades to *inject nothing*,
never to an error.

So switching it on cannot make a run worse than leaving it off. That guarantee is what makes a
default defensible; without it, defaulting to on would be transferring risk to every client at
once.

### 2. The code is still the truth

The map says **where to look**, not what is true. ADR-0017 §7 already requires the agent to verify
against the real files, and ADR-0023 already guarantees the map is **derived in the checkout**, not
learned and not cached somewhere else.

Defaulting to on loosens neither. If it did, this ADR would be trading reliability for speed, which
is exactly the trade this repository does not make.

### 3. `false` still exists

A project that wants it off declares `knowledge_map: false`. What changes is the default and, with
it, who carries the burden: it used to take a justification to switch on, and now it takes one to
switch off.

### 4. The A/B machinery stays, with no window open

`openfactory/knowledge/experiment.py` stays where it is and is **a no-op while no window is open**.
It was not ripped out for two reasons: it is the instrument for measuring the *next* phase
(APIs/schema/ADRs — `architecture.md` §9), and removing it in the same commit that changes the
default would mix a product decision with a code deletion.

The `knowledge` field on `MetricRecord` also stays: it now records the arm *"injected"* or
*"unavailable"*, which is precisely how you find a project whose bundle never becomes fresh.

## Consequences

**Good.** A capability that was built and measured is now used by every new project without anybody
needing to know it exists — which is what "no dev needed" means. And the open-source distribution
is born with it on, so the behaviour a stranger experiences is the behaviour we operate.

**Costs and open risks.**

- **A default is a stronger commitment than an option.** A bundle that never becomes fresh in a
  large repository is now a silent problem for *every* client, not only for whoever opted in. The
  degradation is to "injects nothing", which is correct — but the `unavailable` line on the
  dashboard now deserves an alarm, and today nobody looks at it.
- **The cost per ticket fell on our mix of tickets, in our repository.** A client's C# monorepo is a
  different population, and the number that justified this decision was not measured there. The
  first enterprise deployment should retake the measurement before assuming the gain.
- **Generation runs on every merge that changes sources.** It already did when switched on; the
  difference is that now it always is. Worth watching the post-merge time on the first large
  repository.
- **This revises a rule, not just a value.** ADR-0017 said the layer does not advance without a
  number. It advanced with a number — but the rule is weaker by precedent, and the next phase should
  be held to the same rigour rather than inheriting this decision.
