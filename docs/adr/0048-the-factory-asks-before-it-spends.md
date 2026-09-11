# ADR 0048 — The factory asks before it spends, and the question goes to the person who asked

- **Status:** **Accepted** (2026-09-06) — the product owner's decision, designed against the code
- **Date:** 2026-09-06
- **Related:** ADR-0044/#33 (the two roles; decision 2), ADR-0046 (the knowledge gate), ADR-0047
  (two yeses, the requester), ADR-0040/0041 (the plan is sized before it is started), ADR-0042
  (the backfill records what it could not establish).

## Context

Issue #33 left one decision to the product owner: *when is a planner justified?* The first draft
of it was a threshold — count the real tickets that stumble on a fact nobody had gathered, and
build a planner when more than one in five do. On 2026-09-04 he refused the premise:

> *"Build a planner out of stumbles? That makes no sense for a serious factory that intends to be
> autonomous, replacing the developer. Either it has a planner or it does not. Now — triggering a
> planner by the complexity of the task, that is a reasonable approach. When a TODO comes in there
> is already an intelligence that does the split; would it not be better to add more intelligence
> to that layer?"*

And he said where the intelligence talks to people:

> *"It has to be recorded — as a comment on the ticket, for instance — so that the factory's
> planner talks to the product owner."* … *"If the product owner (the role) does not know the
> answer — whether or not it wrote the ticket — it has to call the requester, and everything is
> recorded on the ticket."*

The layer he means exists: the preflight sizes every card before the plan starts (ADR-0040/0041),
and the knowledge gate already knows which files nothing describes (ADR-0046). What was missing
is the step between the two — the factory noticing, *before it spends a budget*, that the change
it is about to make touches ground nobody mapped, gathering what the repository can tell, and
asking a person only for what the repository cannot.

The first design of this step was put to three independent critics with the code open and was
refuted in most of its mechanics. This record is the design that survived; the refutations are
listed at the end because each one is a rule the implementation has to keep.

## Decision

### 1. Two activities, not one

The preflight stays the cheap sizing decision. The sizer's verdict gains the list of areas it
expects the change to touch (`touches`, paths — never a sizing criterion). A second activity,
**gather**, runs after it with its own timeout, its own heartbeat, one attempt, and its own
degrade path: a gather that runs out of time proceeds as today and must not have left a
half-written card behind. Nothing of it moves into the workflow body, so no history has to be
patched.

### 2. Opt-in, and only where the gate is enforced

`preflight.gather` defaults to **false** (the manifest schema stays at version 1; a default that
changes behaviour for a file that does not mention it would need a bump). The gather runs only
when all four hold: the project opted in; `okf_gate` is `enforce`; a bundle was published for the
**card's** repository and could be read (nothing published, or a context repository that could not
be read, both proceed as today — the second is logged, never bounced); and the expanded list of
touched files is not empty.

### 3. What triggers a gather

A touched *file* the bundle has **no concept** for — the same `no-concept` verdict the in-box gate
authors on. Directories the sizer names are expanded to files through the bundle's inventory
before judging; an empty expansion is "nothing to judge", never dark. A `new-file` verdict is
green. An open question recorded on the area triggers a gather **only** when the gate itself would
hold on it — the rule is imported from the gate, never restated — and only once open questions can
be retired (§7), so the 40 offers the first live bundle recorded stay offers, not tolls.

### 4. Gather first, ask last

For each triggering file the factory authors and publishes concepts the way the backfill does,
bounded by the project's concept budget, from the card's repository, into that repository's folder
of the bundle. Then it puts each remaining question to the product role. An answer counts as
**established** only when everything it cites is verified — every concept fresh, every requirement
real. The collapsed confidence grade is not the gate: a fabricated requirement number grades
"média". The honest cost is stated: a ticket may spend up to twice the concept budget — once here
over the predicted paths, once at pull-request time over the real diff — mitigated by publishing,
so the second pass finds nothing left when the prediction was good.

### 5. The question is one comment, to a person the tracker knows

What the repository could not answer becomes **one** consolidated comment on the card, in the
project's language, carrying a plain-text marker as its first line, addressed to the requester.
The requester is written on the card when it is opened, as an identity **in the tracker's own
namespace** (a forge login on GitHub, a `uniqueName` on Azure DevOps, a display name on Jira), and
kept beside the chat identity the platform already records; the mention is rendered only where the
vendor can resolve it. Fallbacks, in order: the requester keys, the "Pedido por / Reportado por"
line, the card's author. **If no identity the tracker knows resolves, the factory does not ask** —
it proceeds as today. A card with a question is parked in Needs Action; the exit is a new job
state, `skipped`, short-circuited beside `done`, and the placement is made explicitly by the
gather (the state cannot carry it). If the park does not land — two vendors have no such bucket
unless mapped — the factory says so on the card, opens no loop, and proceeds as today.

### 6. The answer comes back through the card, and is recorded in the requester's name

An hourly sweep of its own (not the weekly read-only product sweep, not a second command inside
the tech-lead's watch) reads the card's comments, paged and oldest-first, and accepts an answer
only from a comment newer than the question, whose author is the requester in the same namespace
and is not the platform's own posting identity. The answer is written into the product context
through a provenance seam — the factory recording what a person wrote on the factory's own card,
not an authorised act by that person — with the author stored verbatim; a term the context already
holds counts as recorded. The card returns to the pick-up state by state, never by column name,
and the loop closes only when the recording and the move both succeeded. One chase after N days,
in the same voice.

### 7. A question, once answered, retires

An open question in a bundle gains a stable key and an answered state; the sweep writes the answer
back into the published bundle, the gate stops naming it, the cover pass stops re-authoring on it,
and the author is told what was already answered so it does not mint the same question in new
words. The answered question stays in the bundle as the record. When the question was about a
file nothing described — the trigger this record ships with — the answer becomes a **concept about
that file, in the person's name** (`generated_by: human:<id>`), published where the gate reads: the
next card touching it finds the file described, and asks nobody.

## Consequences

**Good.** The intelligence is added to the layer that already decides — the preflight — instead
of a second planner beside it. The factory reads before it asks, asks once, asks the person who
can answer, and writes the answer where the next card will find it. Every step is on the ticket.

**Costs and risks, declared.**
- **Up to twice the concept budget on a ticket.** Said above; paid only by projects that opted in
  under `enforce`, and only on cards that touch unmapped ground.
- **A card leaves the pick-up column on the factory's own judgement.** Only after the publish,
  the answers and the question are on it, only when the park landed, and only with a loop that
  brings it back.
- **A comment visible to the client on all three vendors, marker included.** An HTML comment would
  survive escaped and visible; the marker is short, ASCII, and first.
- **Chat identity and tracker identity are two namespaces.** Where the card was opened from a chat
  and the tracker cannot name that person, the factory does not ask. Mapping the two is a later
  decision, not an inference.

## What is NOT decided here

- A size-based `large` verdict; the breakdown reading concepts; mention capability on Azure DevOps
  and Jira (they render the plain name).
- A card opened from chat with nobody the tracker can name — today the factory proceeds as it did
  before this record.

## The refutations this design keeps as rules

Three critics, one synthesis, 2026-09-06, every point verified against the tree:

1. `record_decision` is gated on the product allowlist and writes a chat mention — hence the
   provenance seam and the verbatim author (§6).
2. The product role's bound reading looked at the bundle's front door, not the per-repository
   folder, so nothing could ever be "alta" — fixed first, in its own change.
3. "Média" admits a fabricated citation — hence *verified*, not a grade (§4).
4. Any open question as a trigger reverses the owner's 2026-09-06 call on offers versus tolls —
   hence the gate's own rule, imported (§3).
5. An open question had no retirement path, so the gather would never terminate — hence §7.
6. Without the `okf_gate` check every card of every un-onboarded project would bounce — hence §2.
7. A default of true is a manifest break, and a nested field ships undocumented — hence opt-in and
   the census that walks nested fields.
8. One preflight activity cannot hold a clone, an authoring pass, a publish and N answers in
   twenty minutes with one attempt — hence two activities (§1).
9. The requester written today is a chat id; no tracker resolves it — hence the namespaces (§5).
10. `requester: @login` is invalid YAML and would have crashed every read on three vendors — hence
    bare identities, and a parser that survives a malformed fence.
11. Front matter does not survive a person editing the card in a vendor's rich editor — hence the
    body line beside it.
12. Moving a card by column *name* is the bug the platform already paid for — hence by state.
13. The park is a no-op on two vendors unless mapped — hence the read-back (§5).
14. The exit cannot be `done` (the panel would read "shipped") nor a new state carrying the column.
15. The gate cannot judge a directory — hence the expansion (§3).
16. `new-file` is green, not dark.
17. The bundle subpath was resolved from the project's default repository, not the card's.
18. `note_fact` refuses a term it already holds — an existing term is success (§6).
19. The spend is two budgets, not one — said (§4).
20. There was no "product round" to fold the sweep into, and registering an activity does not
    schedule it — hence its own schedule (§6).
21. The tech-lead's watch would need a patched history for a second command — hence not there.
22. Card comments must go through the voice, in both languages.
23. A new loop kind must be opened and closed from reachable code.
24. Azure DevOps comments were read one page at a time despite the docstring.
25. "Comment after the question" is unsound without the platform's own identity and the loop's
    own timestamp.
26. The in-memory tracker of the suite could host neither half as it stood.
