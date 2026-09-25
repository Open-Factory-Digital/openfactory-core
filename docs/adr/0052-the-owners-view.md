# ADR 0052 — The owner's view: what the product is doing, and the whole map of it

- **Status:** **Proposed** (design only) — written from #267 (Part I) and #268 (Part II) as they
  were agreed on review. No code changes with this ADR.
- **Date:** 2026-09-24
- **Relates to:** ADR-0017 and ADR-0023 (the knowledge layer, derived and never learned — the
  concepts and module maps Part II hands the role), ADR-0019 (the product role — §6, where it meets
  the tech-lead through the diagnosis on the ticket, which D8 keeps; §7, a product spans N source
  repositories and keeps one board, which D1 and D16 finally key by; §8, the declaration of those
  sources), ADR-0020 (the tech-lead on call — the diagnosis D8 has the role consume), ADR-0021 (the
  open loop — §5 leaves an unanswered question as a visible open item, which D12 makes visible),
  ADR-0025 (delivery closes with the client — the announcement D11 moves from the sweep to the
  delivery), ADR-0034 (entry points are the extension mechanism on every axis — D15's knowledge
  source), ADR-0038 (the panel is the reference surface; a vendor is an add-on), ADR-0041 (facts
  are files — D6), ADR-0045 (the fingerprint gains a reader — the check D20 moves to the product
  role's turn), ADR-0046 (`no-concept` — the gap D22 signals), ADR-0049 (D6, the board and the
  pull-request page are the panel's, through the ports; D7, the requester of a card), ADR-0050 (the
  preview — *Proposed*, #264; its state joins the *now* layer once it is built), ADR-0051 (one door
  — D1's `receive` and its internal events, D2's product, D3's queue per conversation, D5's rule on
  names, D11's workspace per turn, D13's `publish`; decisions 1, 7, 8, 10 and 11, which this record
  carries). Issues: #267 (Part I) and #268 (Part II) — this record; #266 (what both depend on —
  slice 2's workspace per turn, slice 3's door, conversations and product key); #269 (not decided
  here).

## Context

The product role is meant to know the product the way the person who owns it does: what is
moving, what has stopped and on whom it waits, what was delivered and when, what is in production,
and what each card promises — and the whole of what the product is built from: every repository,
and how the parts talk to each other. The panel shows most of the first to whoever opens it. The
role sees a part of it, and hears of the rest late; and of the second it reads one source of N.

What follows was read at `main` (`0f8314c`) and at the head of #266's stack (`a6cd347`, the branch
of its slice 6, which carries #290, #294 and #295). A `file:line` with no mark is the same in both
trees; one marked *(#266)* is in the stack only. The first four subsections are Part I's (#267);
the two after them are Part II's (#268).

### The role reads three files and a budgeted board

- The role's facts pack is `board.md`, `loops.md` and `decisions.md` (`product/facts.py:46`),
  written for one registry project by `ProductModule._write_facts` from `_board_cards()`. It has no
  floor: no running or parked job, no reason a job parked, no pull request, CI result or review
  verdict, no release and no version in production.
- `board.md` renders each card's number, column, title and state (`facts.py::render_board`,
  `:51`). The ticket it renders from carries more — the body, labels, assignees, whether a pull
  request is open, parent and children (`product/triage.py:50-72`) — and none of it is rendered.
- The board is a window: the 300 most recently updated issues (`product/board.py:65`), because a
  full read of a large board "would otherwise cost minutes on every triage" (`:57-58`). A card
  moved between columns without its issue changing is seen at the next full sweep, up to six hours
  later (`_FULL_AFTER`, `:76`).
- The requirements index in the prompt has the columns req, status, title, affects and file
  (`product/role.py::requirement_index`). A requirement's `Asked by` is in its file, not in the
  index.
- On a card's page the stack puts that card in the turn: its title, state, labels and last four
  comments, each with its author (`product/page.py::looking_at`, `:127`, and `_the_card`, `:154`
  *(#266)*). It is the one card the person is looking at, and it has no floor either.

### The tech-lead looks at another world

The tech-lead's pack is `floor.md`, `board.md`, `thread.md`, and a file per ticket under
`comments/`, `verdicts/` and `diffs/` (`techlead/pack.py:80-85`). When a job parks, the tech-lead
posts its diagnosis — a `HandOff` (`contracts/decision.py:149`) — as a comment on the ticket
(`runtime/temporal/activities.py::_do_diagnose`). The product role meets it only there:
`ProductModule.review_needs_action` reads that comment for each parked card, up to a cap, and asks
the role's own model, one call per card, whether the cause is a requirement defect (ADR-0019 §6).

### What the panel shows that the role cannot see

The panel has two areas. `/api/product/` and `/api/act/product_` are the product area; everything
else under `/api/` is the floor (`_PRODUCT_ROUTES`, `api/app.py:349`). The floor carries the jobs,
the board, the card and pull-request pages (ADR-0049 D6), the inbox of human gates with their
review verdicts, the prod-approval dialog with the current release tag (`app.py::promote_info`,
which returns `latest_tag`) — and spend: the cost pill and its dashboard (`GET /api/metrics`,
`api/panel.html::openCosts`), and `cost_usd` on the job rows (`GET /api/jobs`). The ledger's open
loops — what the agents wait on a person for — are served at `/api/loops/{project}`
(`app.py::open_loops`), and no panel page reads that route.

### The role hears late, and in one room

- Proactive messages come from `ProductSweepWorkflow`, weekly (`PRODUCT_EVERY_HOURS = 24 * 7`,
  `runtime/temporal/schedule.py:51`). The delivery announcement is in the sweep's follow-through
  (`activities.py:3994`, inside `_product_followup`, `:3948`), whose only caller is the sweep: a
  card delivered on Monday is announced when the sweep next runs.
- The sweep's messages go through `activities.py::_product_post`, to the product's one room. On
  `main` it calls `channel.say` on `cfg.channel_id`; in the stack it calls `channel.say` on the
  product's room (`activities.py:3937` *(#266)*) — outside the door #266 built, and outside every
  conversation's queue. The deploy watch's invitation to the client
  (`activities.py::_invite_the_client_to_look`) is said when the deploy happens, and goes the same
  way; so does the notice about orphaned cards (`_repoint_product_orphans`).
- The panel's channel adapter is pull: `say` records, and a person is reached by looking
  (`adapters/channel/panel.py:13`). The stack's chat socket pushes what a conversation publishes
  (`product/door.py::watch`, `:389` *(#266)*); `_product_post` publishes nothing to a
  conversation.
- In the stack, an internal event through the door carries replies already written, and the
  conversation publishes them the moment they arrive, whatever turn is running
  (`runtime/temporal/conversation.py:173`, in `admit`, `:161` *(#266)*; "An event starts no turn
  and reaches no stage", `product/engine.py:184-187` *(#266)*). That is right for the late answer
  a person is waiting for, and it would put anything else in the middle of a turn in progress.

### The role mounts one source of N

- A product declares its sources in its context repository's `.openfactory/product.yaml` →
  `sources:` (`product/config.py`, reconciled by `resolve_product_link`, `:211`), and
  `product/workspace.py::compose` takes any number of them, keeping one it could not place in
  `missing` instead of dropping it.
- The conversation mounts one. `ProductModule._workspace` calls `compose(docs_checkout=docs,
  sources={repo: source}, root=root)`, where `repo` is the project's `forge.repo` or `tracker.repo`
  (`_source_repo`). `_sources()` reads all N from the manifest, and its one caller uses them to name
  the repository a ticket lands in (`issues_for`, in the breakdown). In a multi-repo product the
  role can read the other sources' concepts, which live in the context repository, and cannot open
  their code to check them.
- The confidence bound on an answer (`product/reading.py::bound`, `:60`) reads one bundle: the one
  `_okf_dir` resolves from `okf_subpath(repo_of(project))`, the project's own source's folder
  (`knowledge/pipeline.py:95`, `.okf/repos/<owner>--<name>/`).
- Nothing in `openfactory/` checks out sparsely: `_source_checkout` syncs a whole cached clone.

### There is no system layer

- The knowledge bundle is per source. Nothing records which components exist, which calls which,
  which events flow or which database is shared, and a business flow that crosses services has no
  concept of its own.
- `api.yaml`, `schema.yaml` and `adr-index.yaml` are designed in `docs/knowledge-layer.md` §9 and
  left to its Phase 2b; nothing in `openfactory/` names them.
- The deterministic module map reaches the coding agent only:
  `knowledge/service.py::load_agent_knowledge` (`:21`) has one caller,
  `orchestrator/context.py:219`.
- Concepts are a published snapshot, refreshed every six hours (`OKF_EVERY_HOURS`,
  `runtime/temporal/schedule.py:72`) and after a merge. The tech-lead checks them against the
  source it cloned, at turn time (`techlead/conversation.py::_bundle_for`, `:455`, calling
  `knowledge/check.py::check_concepts` at `:524`). The product role checks nothing at turn time.
- Coverage and gaps are measured in each bundle's `okf.yaml` (`knowledge/okf.py:56`) and rendered
  into its index (`render_index`, `:300`); the role's prompt tells it that a bundle's gaps section
  "is information, not noise" (`product/role.py::_bundle_section`).
- The onboarding writes `docs/architecture/`, `docs/invariants.md`, `docs/open-questions.md` and
  `docs/survey.md` into the context repository (`onboarding/context.py:1572-1580`, the English
  layout), and neither the role's prompt (`product/role.py`) nor its role file
  (`org_defaults/roles/product.md`) names them.

### What the owner does instead

Answers for themselves whatever touches the floor, a release, a card's content or a card outside
the window; learns of a delivery from the sweep, or by opening the panel; and answers whatever spans
services, or lives in a repository other than the project's own.

## Decision

**Part I — what the product is doing (#267).** One read model of the product, read by the panel
and by the role. The role can know whatever the panel shows about the product, except what an
explicit list excludes, and spend is on it. What the role needs on every turn is a short briefing
with the source and age of each line; the rest stays in files. The model is kept by events that
come through #266's door, and an event told to a person waits its turn in their conversation.

**Part II — the whole map of it (#268).** The product, not the repository: every declared source
is mounted, read-only and sparse on demand, and a system layer derived without a model says which
components there are and how they talk. The code stays the ground truth, checked at turn time; a
blind spot is said out loud, and code no concept covers is signalled to the knowledge pipeline.
Repositories and the context repository are the core's; any other source is an add-on.

## Part I — What the product is doing (#267)

```
factory events ──┐  a card moved · a job parked · CI · a review · a merge · a deploy · a release
                 │
                 ▼
          receive(Message) ──► the product's read model ──────────────► the panel's screens
          (ADR-0051 D1)           now · history · meaning                (its own gate, unchanged)
                 │                          │
                 │                          └── minus the exclusion list (spend) ──► the role:
                 │                                                          briefing, every prompt
                 ▼                                                          + files (ADR-0041)
     the conversation it concerns
     (queued; never beside a turn)
```

### D1 — One read model of the product, and two consumers

The read model is one projection of the **product** (ADR-0051 D2): the boards, jobs, pull
requests and releases of its member registry projects — the projects whose product key is the
product's, the membership `memory/transcript.py::partition` (`:145` *(#266)*) already reads from
the registry — together with its context repository's requirements and decisions and its ledger.
It has two consumers: the panel's screens that show the product, and the role. Each applies its
own gate on the way out: the panel its credential areas (`_PRODUCT_ROUTES`), unchanged; the role
the exclusion list (D2), the rule on names (D9) and the registers (D10).

Facts about the factory rather than the product — credentials and the token pool, the trackers'
API budget (`/api/budget`), the boxes, the workers, the schedules — are the tech-lead's and the
operator's, and are not in the model. They reach the product only through a diagnosis (D8).

*Why:* two readers of the ports drift apart, and the drift is what #267 found: the panel and the
role each read their own way, and the role's reading came out smaller. One projection is the only
shape in which "the role sees what the panel sees" can be checked (D3). Keying it by product is
ADR-0019 §7's "the board stays one per product", which the code never did: `_write_facts` writes
one registry project's board.

### D2 — The invariant, and its exclusion list

*Anything a human can see about the product in the panel, the role can know — except what is on
an explicit exclusion list.*

- **"A human" is the widest view the panel gives of the product:** the floor and the product area
  together, as an operator sees them. The role knows floor facts that a product-only credential
  cannot open, because translating the floor for that person is its job; what it tells whom is
  D10's.
- **The list is one declaration in the code.** Each entry names the fact, why it is excluded and
  the decision that put it there. The role's rendering reads it and leaves the fact out; the guard
  reads it too (D3).
- **It starts with spend** (ADR-0051 decision 7): what any run, job or product cost, in money or
  in tokens — the cost dashboard, a job's cost on its row and in its detail. Cost does not help
  build the product, so the role does not see it. What is excluded is the amount, not the rule:
  the role still knows that moving a card to TO-DO starts spending (ADR-0019 §5), because that is
  what it asks a person to confirm.
- **An entry is added by amending this record**, with a dated note (the house style), never by
  editing the list alone.
- **Amended 2026-09-24, when #267's first slice built the list** (`product/model.py::EXCLUDED`).
  Building the guard over every panel route that takes a project showed facts that are not the
  product's to know, beside spend. Two are D1's facts about the factory, now named in the list so
  the guard reads them rather than a comment; four are new entries, each with its reason:
  - *a run's raw log* (`/events`, `/stream`): the tech-lead's evidence — reading it would be
    diagnosing again (D8) — and it carries a credential id and per-call spend;
  - *the factory's thread with its operators* (`/api/messages`): another conversation, not
    addressed to this role (ADR-0051 decision 3), and it names who answered (D9);
  - *who may approve a release, and the approval form's inputs*: releasing is not the role's
    (ADR-0016); the version in production is in the model;
  - *the sealed digests on the ledger's loops* (`asked_of`, `asked_in`): kept to compare who was
    asked, never to be shown (ADR-0051, slice 4);
  - under D1: *the cockpit* (`/api/factory`: the credential pool, and which credential pays) and
    *the operators' controls* on the floor (`cmd`, `actions`, `poll_seconds`, `can_merge_here`).
- **Amended 2026-09-24, when #269's first slice put documents on the panel.** *An internal
  document's name, path, type and reason*, as the documents screen lists it to a credential that
  may read the floor: a document labelled internal is for the product's own people (ADR-0053, #266
  decision 8), and its name is content. It is named only to a turn that answers an engineer or a
  product admin in a conversation of their own; every other turn, a room's included, is told how
  many there are and nothing else — as a product credential is, on the same screen.

*Why:* without the list, the check that holds the invariant would demand spend — the one fact
decided the role must not see (the review of #266). With it, the check holds in both directions:
the role is not missing what it should see, and does not see what is excluded.

### D3 — A guard compares the two surfaces and reads the list

One test, over a fixture product with every kind of fact recorded, spend included:

1. every fact the panel renders from the model is reachable by the role — in the briefing, or in
   a file the manifest names — or is on the exclusion list;
2. nothing on the list is reachable by the role: no rendering the role reads carries it;
3. every entry on the list names a fact the panel still shows, so the list cannot grow into a
   blanket;
4. every field a panel route returns under a registry project is either read from the model or
   declared the factory's (D1), with its reason — so a new screen that reads a port directly for a
   fact about the product fails the check until it is moved or declared.

*Why:* an invariant written in a document and held by nothing drifts with the next screen. Reading
the list is what keeps the check from ever demanding an excluded fact (#267).

### D4 — Three layers: now, history, meaning

| Layer | Answers | Holds |
|---|---|---|
| **Now** | what is moving, what has stopped, and on whom it waits | running and parked jobs, and why they parked (the tech-lead's diagnosis, D8); pull requests, CI results and review verdicts; the ADR-0050 preview, once that record is built; what waits on whom — the ledger's open loops, and the questions the factory asked on cards (ADR-0048) |
| **History** | what was done, when, by whom and why | each card's timeline; deliveries; releases and the version in production; who asked for what; the whole board, closed cards included — not the 300-card window |
| **Meaning** | what each card promises | each ticket's body and comments; the requirements, with `Asked by` in the index (rendered as D9 says) |

Every fact carries its source and the time it was read or reported.

Neither port has a timeline read today — `TrackerAdapter` (`adapters/tracker/base.py:272`) and
`BoardAdapter` (`adapters/board/base.py:156`) answer the present state — so a card's timeline is
what D7's events write from the day they flow, and before that what the ports can still say
(comments, closed cards). A timeline read added to a port is added for every vendor at once
(ADR-0041, *Consequences*).

*Why:* the three answer different questions and go stale at different speeds. *Now* is stale in
hours; history, once written, does not change; meaning changes when somebody edits a card or a
requirement. Named apart, each can be kept at its own cost.

### D5 — A briefing, always in the prompt, with its source and age on every line

The briefing is what a human owner carries in their head in the morning, and it is in every
turn's prompt. For example:

```
3 cards are moving.                                        (board — 12 min ago)
#42 has waited 2 days on a decision from its requester.    (ledger — asked 2 days ago)
1.4 went to production yesterday.                          (release tag and deploy — 1 day ago)
#38's preview is up.                                       (preview — 40 min ago)
```

- **Every line states its source and its age.** A fact that could not be read is a line that says
  so, never a silence (ADR-0041, *Consequences*: unreadable is not absence).
- **It is short, and bounded.** Its budget is set in #267's second slice and held by the
  measurement in *What would make it wrong*.
  *Set 2026-09-24 by that slice* (`product/briefing.py`): at most 12 lines and 2,000 characters,
  each line's text cut at 280 with its source and age never cut; lines leave from the bottom of
  a fixed order (gaps first, then moving, production, parked, gates, waits, preview, delivered)
  and the last line counts, by kind, what left. It replaces the board section in an answer's
  prompt when the facts pack is mounted. `OPENFACTORY_PRODUCT_BRIEFING=off` restores the prompt as
  it was, the two arms of the measurement; every answer logs which arm it ran and the briefing's
  size.
- **It is rendered for the conversation it goes to** (D9), and carries nothing on the exclusion
  list (D2).
- **It points at the files** (D6) for the detail behind any line.

*Why:* a fact the role has to go and open is a fact it opens on some turns and not on others, and
pays for in exploration each time. The few facts an owner answers almost anything from should
cost one short block. The age is what lets the role say "as of two hours ago" instead of asserting
a present it did not see.

### D6 — The details stay files

Everything in the model beyond the briefing reaches the role as files in its workspace, beside
`board.md`, `loops.md` and `decisions.md`, with the manifest naming every file and every gap
(ADR-0041). The role opens what the question needs. No tool protocol is added.

*Why:* ADR-0041's measurement stands — a filesystem is the one tool every harness has. A briefing
that tried to carry the detail would be the digest ADR-0041 retired.

### D7 — The model is kept by events that come through the door

The model is kept current by events — a card moved; a job started, parked or resumed; a pull
request opened, reviewed or merged; a CI result; a deploy; a release; a preview up or ended. Each
is sent through #266's door (`receive`, `product/door.py:249` *(#266)*) as a message of kind
*event*, with an id of its own. The door deduplicates events by id as it does messages, and the
model applies them in the order the door took them. **A turn reads the model; it never rebuilds
it.**

A full reading of the ports stays, as reconciliation. Some changes produce no event — a card
dragged between columns without its issue changing, the case `product/board.py`'s own docstring
names — and an event can die with the process that should have sent it. What the reconciliation
finds that no event reported is logged as a missed event, so the gap is counted, not absorbed.

*Why:* the role is current without reading the board, the floor and the forge on every turn, and
the events are what D11 tells people. Through the door they get the door's durability and
deduplication, and every producer has one way in.

### D8 — The tech-lead diagnoses; the role translates, and never re-diagnoses

Both roles read the same model. The tech-lead diagnoses the factory; its diagnosis — the
`HandOff` it posts on the ticket when a job parks — is a fact of the *now* layer, with its source.
The product role takes that diagnosis and says what it means for the product: "#42 stopped because
X has to be decided". It never arrives at a cause of its own — from a job's log, the code, a CI
output or the card — and a parked card with no diagnosis yet is briefed as parked, diagnosis
pending.

ADR-0019 §6 stays: the role reads the diagnosis and decides whether the cause is a requirement
defect it can fix. That is a decision about what it owns, taken on the tech-lead's diagnosis, not a
second diagnosis.

*Why:* two roles diagnosing one park make two truths about it, and leave the person reading both
to choose which agent to believe. The tech-lead is on call for the factory (ADR-0020); the product
role is the one that can say what a stop means to the people who asked for the work.

### D9 — Nobody from outside the conversation is named

ADR-0051 D5's rule holds for everything the model renders: the role never names a person from
outside the current conversation (as the stack's role file already says,
`org_defaults/roles/product.md:40` *(#266)*).

- **The model keeps who did what,** as the records do — a requirement's front matter names its
  requester — and the files keep it too; the rule on speech covers what the role says from them.
- **What reaches the prompt is rendered for the conversation:** the briefing, the requirements
  index, and the card a person is looking at once it is read from the model. The person being
  spoken to is "you"; anyone else is named by their relation to the thing — its requester, the
  person a decision was asked of, the reviewer. "#42 has waited two days on a decision from its
  requester" — unless the requester is the person being spoken to.
- **`Asked by` joins the index under that rendering,** not as a copied column: #294 took the
  teller's name out of the glossary index for the same reason — an index is read in every
  conversation of the product.

*Why:* the briefing is read in every conversation of the product, so a name in it crosses into
conversations its owner was never in — the leak ADR-0051 D5 and D9 close for the acknowledgement
and for the duplicate check.

### D10 — One knowledge, three registers

The model and the briefing are the same for everyone. How the role says what it knows depends on
who is speaking — client, product admin or engineer, client by default (ADR-0051 decision 8) — as
the stack resolves it from the registry (`product/speaker.py:44`, `person`, `:58` *(#266)*).

- **Client:** what a stop, a delivery or a release means for the product. Never a raw technical
  diagnosis.
- **Product admin:** the same, and what is needed from them to move it.
- **Engineer:** the diagnosis's reasoning, in technical depth.
- **A raw diagnosis goes only to an engineer, in a private conversation.** In a room, everyone in
  it reads the reply.
- **`AUDIENCE_RULES` is unchanged** (`product/voice.py:83`). It holds in every register, as the
  engineer's description in the stack already says (`speaker.py::_SAID`, `:137` *(#266)*).

*Why:* one knowledge keeps the three from growing into three truths; the register is what makes
one fact useful to three readers.

### D11 — An event told to a person goes through their conversation's queue

Some events are told to someone, not only recorded:

- a card delivered;
- CI red;
- a pull request waiting 48 hours;
- a preview up;
- a new document ingested (from #269).

Each kind names whom it concerns — a delivery, its requester — and is queued on that person's
conversation as an item of kind *event*, like a message.

- **It waits its turn.** It is handled when no turn is running in that conversation, and never in
  the middle of one. For these kinds this changes what the stack does with an internal event
  (published at once, `conversation.py:173` *(#266)*); the late answer of a handed-off turn keeps
  its own path (ADR-0051 D6).
- **It is told when it happens.** A card delivered on Monday is announced to its requester's
  conversation on Monday, not at the next sweep.
- **It is recorded before it is delivered** (ADR-0051 D13), so whoever answers it is answered by a
  role that knows what it said.
- **Each kind declares how it is told:** by a fixed sentence, as a delivery is today
  (`product/followup.py:601`, `delivered_text`), or by a turn. Either way it takes its place in the
  queue.
- **`_product_post` and its callers move onto the door.** Nothing proactive calls `channel.say`.

*Why:* the person who asked is the one who wants to know, and the moment is when it happens; a
weekly report to one room tells everyone, late. A message that lands in the middle of a turn is
two voices at once in one conversation, which the order ADR-0051 D3 gave each conversation exists
to prevent.

### D12 — The agenda

The ledger's open loops (ADR-0021) become a visible **agenda**: what the role owes to whom — a
decision it asked for, a delivery awaiting a verdict (ADR-0025), a question, a chase. It is a view
of the model, keyed by product, and it is shown on the panel. An item owed in a private
conversation is shown to that conversation's person only, the rule the stack's chat socket applies
to every frame (`api/product_chat.py::may_receive`, `:98` *(#266)*). An item's due time is an
event (D11): a chase at 48 hours happens at 48 hours, not at the next sweep.

*Why:* ADR-0021 §5 bounds a chase to one and then leaves the question "a visible open item". The
items are served (`open_loops`), and no page shows them.

### D13 — The weekly sweep stays only as a catch-all

The sweep's work — announcing deliveries, closing what the board resolved, asking what is new,
chasing — moves onto events (D11, D12). `ProductSweepWorkflow` stays as the reconciliation of D7:
it says only what no event said, and in a week when every event arrived it says nothing.

*Why:* a report on a schedule is late by construction. Kept as a catch-all, it is the net under a
missed event rather than the channel for everything.

## Part II — Every source, and the system layer across them (#268)

```
product ──► system ──► component ──► concept ──► code
            (topology)  (a service    (the bundle,  (the ground truth,
                        or a module)   per source)   checked at turn time)
```

### D14 — One shape: components distributed over the product's sources

A monolith, a monorepo, several repositories and a microservice system are one shape to the role:
components distributed over the sources the product declares (ADR-0019 §7, §8). The map has five
levels — product, system, component, concept, code. The prompt carries the top of it, and the role
goes down a level when the question needs it. A product of one source is the same shape with one
source, on the same code path.

- **Product:** the requirements, the glossary and the business capabilities (D19).
- **System:** the components and how they talk to each other (D17).
- **Component and concept:** the knowledge bundles that exist today, and the module map (D18).
- **Code:** every declared source, mounted (D16) and checked (D20).

*Why:* for an owner, knowing everything is knowing the whole map, knowing where to look, and
confirming before asserting (#268). Two code paths — one for a repository, one for a system — is
how the one-repository case stays the only one that works.

### D15 — Repositories and the context repository are in the core; any other source is an add-on

The sources the core reads are the product's repositories and its context repository (ADR-0051
decision 10). Any other kind of knowledge source — a wiki, a design tool, another tracker's history
— is an add-on axis, *a knowledge source*, extended the way every axis is (ADR-0034's entry
points). No vendor enters the core.

*Why:* every product has repositories and a context repository; everything else is somebody's
product. It is ADR-0038's shape, one layer down: the core complete on its own, a vendor an add-on.

### D16 — Every declared source is mounted, read-only, and sparse on demand

Every source in `.openfactory/product.yaml` → `sources:` is mounted in the role's workspace,
read-only (ADR-0051 decision 11). Each is checked out sparsely: what the role reads of it is
fetched when a question goes down into it, so mounting every source does not cost a full clone of
each.

- **A source that cannot be mounted is named in the prompt, with the reason.** `compose` already
  keeps it in `missing`; the prompt says it, so the role never concludes anything about code it
  could not see.
- **Each turn reads its own view** (#266 slice 2; `product/workspace.py::turn_view`, `:203`
  *(#266)*), so N sources are never recomposed under a turn that is reading them.

*Why:* a question about a multi-repo product lands in whichever service it is about, and today
the role can open one of them. A role that can read a service's concepts and not its code can
repeat the map and cannot check it.

### D17 — The system layer, derived without a model

Components, and how they talk to each other — the APIs, the events, the databases, the queues —
across repositories, derived **deterministically** from what the repositories already contain:
OpenAPI, AsyncAPI and proto files, migrations, and compose, Kubernetes or Terraform files. No model
draws the topology.

- **Every entry links to the file and the commit it was derived from,** as every fact in the
  knowledge layer does (`docs/knowledge-layer.md` §7).
- **What could not be derived is said.** A system that hides its interfaces — reflection, runtime
  configuration — gets a map that names what it could not see, never a guess.
- **This is where `api.yaml`, `schema.yaml` and `adr-index.yaml` are built**
  (`docs/knowledge-layer.md` §9), across the sources rather than inside one.
- It is published in the context repository, beside the per-source bundles, because it belongs to
  no one source.

*Why:* a topology a model inferred is a guess that reads like a fact, and the map is where the
role goes to know where to look. The repositories already declare most of it; reading it is
arithmetic, and it can be checked again on every refresh.

### D18 — Components and concepts: the bundles as they are, and the module map given to the role

The per-source bundles stay what they are. The deterministic module map, which today reaches the
coding agent only, is given to the role for every mounted source, verified against the source it
describes before it is read — as `load_agent_knowledge` verifies it for the agent, which injects
nothing it cannot trust. The onboarding documents — the architecture, the invariants, the open
questions, the survey — are named in the prompt, with where they are.

*Why:* the module map is regenerated in a quarter of a second, by the tech-lead's own account
(`_bundle_for`), and checked against the code; it is the cheapest true thing the platform knows
about a source, and the role is the one reader that does not get it. The onboarding documents
were written into the role's own context repository, and nothing tells it they exist.

### D19 — A business capability links concepts across sources

At the product level, beside the requirements and the glossary, a capability names the concepts
that carry one business flow across sources — checkout is the web front end, orders and payments.
A flow that crosses services has a concept of its own. A capability cites what it links, as every
concept does; a link to a concept that no longer exists is reported, never kept silently.

*Why:* a question a client asks is about a flow, and a flow spans services. Without a record that
joins the parts, the role answers about each part and leaves the person to add them up.

### D20 — The code is the ground truth, checked at turn time

What the role asserts about how the product behaves now, it checks in the code
(`docs/knowledge-layer.md` §7: the map is not the territory).

- **A concept the role cites is checked against its source at turn time,** with the check the
  tech-lead already runs (`check_concepts`, ADR-0045's fingerprint). A stale concept is named as
  stale and never used as current.
- **The confidence bound reads every source's bundle,** not the project's own alone.

*Why:* concepts are a snapshot, refreshed every six hours and after a merge; the code is what runs.
The tech-lead already holds both halves at the moment it answers, and the product role, once D16
mounts every source, does too.

### D21 — Blind spots are said out loud

Coverage and gaps are measured per source, in each bundle's `okf.yaml`, and the role says them
when an answer rests on them: "the notifications service has no map yet; what I say about it comes
from reading the code just now, medium confidence." The same holds for a source that could not be
mounted (D16), a part of the system the layer could not derive (D17) and a concept found stale
(D20).

*Why:* an answer that does not say where it is thin gives confidence exactly where it is not due —
the rule `docs/AGENTS.md` states for the first survey of a codebase, applied to every answer.

### D22 — Code that no concept covers raises a gap signal

When the role answers by reading code that no concept covered, it raises a gap signal for the
knowledge pipeline, in ADR-0046's vocabulary (`no-concept`, `knowledge/gate.py:55`). It does not
write the bundle: the knowledge layer changes only through its pipeline, and the product role
proposes, it never redefines what the code is (`docs/knowledge-layer.md` §6). The signal is a
request; the pipeline decides what to describe.

*Why:* the role's questions are a measure of where the map is missing, taken from what people
actually ask. Dropped, that measurement is lost at the end of each turn.

### D23 — The traceability chain

`request → requirement → ticket → pull request → release`, crossed with `concept ↔ component ↔
code`. Part I's *history* layer holds the first chain and Part II's map the second; the role reads
them together. It answers what no single tool answers:

- Is requirement 17 in production, and in which version?
- If the freight calculation changes, which services and which requirements are touched?
- Is what the client reported a defect, or a new request?

*Why:* each link already exists somewhere — a requirement's number on its ticket, a ticket's pull
request, a release's tag, a concept's file — and an owner answers these questions by walking them.
Held as one chain, the walk is a lookup rather than a search across four tools.

## What this record carries from #266

| #266 | Decision | Here |
|---|---|---|
| decision 1 | The role's boundary is the product, not the registry project | D1, D14 |
| decision 7 | The role does not see spend | D2, D3 |
| decision 8 | Three audiences — client, product admin, engineer — client by default | D10 |
| decision 10 | Repositories and the context repository are in the core; any other source is an add-on axis | D15 |
| decision 11 | Very large products: every source mounted, sparse checkout on demand | D16 |
| the review | No names across conversations | D9 |
| slice 2 | A workspace per turn | D16 |
| slice 3 | The door, and one serial queue per conversation | D7, D11 |

## What would make it wrong

**The briefing (Part I).** A briefing is paid on every turn. It is right only if it replaces the
exploration the role does today — opening `board.md`, reading again what the last turn already
read. That is measured, not assumed, with #266's evaluation battery (slice 0, #281): the same
questions on the same fixture, with and without the briefing, recording per turn the score
(correct, cited, abstained correctly), the tokens and the files opened. A briefing that raises the
tokens per turn without raising the score is the wrong idea in the shape written here, and this
record is the one to revise. The same measurement decides whether the prompt's budgeted board
section (`role.py::_board_section`) stays beside the briefing or is folded into it.

**Mounting N sources (Part II).** Every source mounted costs disk and time. Sparse checkout on
demand is the mitigation, and it is measured on a real multi-repo product before #268's first slice
is called done — not on a fixture alone.

**A topology derived without a model (Part II).** It can be incomplete where a system hides its
interfaces — reflection, runtime configuration. The map says what it could not derive rather than
guessing (D17); how much that is on a real system is part of what #268's second slice measures.

## Not decided here

- **#269 — documents and long memory** (ADR-0053). "A new document ingested" is one of D11's kinds;
  nothing else about it is decided here.
- **Spend, in any form.** The role does not see it (D2); what the panel shows of it, and to whom,
  is unchanged.

## What this does NOT mean

- **Not that the role acts on the floor.** It reads the floor. Every write stays behind the
  confirmation it has today, and releasing to production from a conversation stays refused
  (ADR-0016).
- **Not that the panel shows anything new, or to anyone new.** Its areas and its gate are
  unchanged; it reads its facts about the product from the model instead of from the ports. The
  agenda (D12) is the one new screen.
- **Not a tool protocol** (ADR-0041).
- **Not a second diagnosis** (D8).
- **Not that people are hidden from the role.** The model keeps who did what; what is rendered
  into a prompt names nobody from outside the conversation.
- **Not that the sweep goes away** (D13).
- **Not a change to `AUDIENCE_RULES`** (D10).
- **Not a topology a model drew** (D17).
- **Not that a concept outranks the code** (D20). The map says where to look; the code says what
  is true.
- **Not that the role writes the knowledge layer** (D22). It signals a gap; the pipeline writes.
- **Not a vendor in the core for any other kind of source** (D15).

## Slices

Each merges on its own and carries its acceptance criteria. Part I's are #267's, ordered; Part
II's are #268's, ordered. All of them depend on #266's slice 3 (the door, the conversations and the
product key); Part II's also on its slice 2 (a workspace per turn). The fixtures #268's slices
name — multi-repo and microservice — join #266's battery with them (ADR-0051, slice 0).

### #267 — what the product is doing

**#267, slice 1. The read model** (D1–D4, D6). One projection per product, over its member
projects, consumed by the panel and the role, with the exclusion list.
*Acceptance:*
- every fact a panel screen shows about the product is reachable by the role, except the excluded
  ones — the guard of D3 compares the two and reads the list;
- spend is not reachable;
- two registry projects of one product give one model, holding both boards.

**#267, slice 2. The briefing** (D5, D9, D10).
*Acceptance:*
- on a fixture project, the briefing lists the moving, parked and waiting cards and the version in
  production;
- each line states its source and age;
- rendered for a conversation the requester is not in, it names nobody;
- the battery's record, with and without the briefing, states the score, the tokens and the files
  opened per turn.

**#267, slice 3. Events and the agenda** (D7, D8, D11–D13).
*Acceptance:*
- a delivered card is announced to its requester's conversation when it is delivered, not at the
  next sweep;
- a proactive message never interleaves with a turn in progress;
- the agenda is visible on the panel, and an item owed in a private conversation is shown to its
  person only;
- nothing proactive calls `channel.say` outside the door.

### #268 — every source and the system layer

**#268, slice 1. All sources mounted** (D14, D16, D18, and D20's bound). Sparse checkout on
demand; the confidence bound over every source's bundle; the module map and the onboarding
documents named in the prompt.
*Acceptance:*
- on the multi-repo fixture, the role opens code in every declared source, and the prompt names
  every source that is missing, with the reason;
- the disk and time of mounting every source are measured on a real multi-repo product.

**#268, slice 2. The system layer** (D17): the deterministic topology, `api`, `schema` and
`adr-index`.
*Acceptance:*
- on the microservice fixture, the system map lists every component and every declared interface
  between them, each entry linked to its source file and commit;
- what the map could not derive is listed in it.

**#268, slice 3. Capabilities, turn-time checks, blind spots and the gap signal** (D19–D23).
*Acceptance:*
- on the microservice fixture, a question whose answer spans three services is answered
  correctly, with citations into all three;
- a cited concept whose source has moved is named stale in the answer;
- an answer read from code that no concept covers raises a `no-concept` signal;
- once #267's first slice has built the *history* layer, "is requirement N in production, and in
  which version?" is answered from the chain.

## Consequences

**Good.** The role answers what an owner asks — why did this stop, when did that ship, what is in
production, what did we promise on #42 — from the facts the panel shows, and says how old they
are. The person who asked hears of a delivery when it happens, in their own conversation. The
tech-lead and the product role look at one world. And the role answers about the product whatever
repository the question lands in, checks what it asserts against the code, and says where its map
is thin.

**Costs and risks, declared.**

- **The panel moves onto the projection.** Its screens read the ports directly today
  (`api/app.py::board_view`, ADR-0049 D6). Moving them is the largest part of #267's first slice,
  and a screen left on the ports is what D3's fourth check catches.
- **Every producer has to send its event.** The job workflow, the deploy watch, the tech-lead's
  diagnosis, the release and the board poller each gain a call to the door. One that forgets leaves
  the model stale until the reconciliation, which logs it (D7).
- **The whole board costs a full read once.** The 300-card window exists because a full read is
  expensive (`board.py:57-58`); the model pays it once and keeps it by events, and after that the
  reconciliation's cadence is its cost.
- **The role knows more than some of the people it talks to may open.** A product-only credential
  cannot read the floor; the role knows it. What reaches that person is D10's to govern, and a
  mistake there is a disclosure — which is why client is the default register and a raw diagnosis
  goes only to an engineer in private.
- **A briefing on every turn.** Its cost is the measurement above.
- **`review_needs_action` spends a model call per parked card** on a diagnosis the tech-lead
  already wrote. D8 keeps it as a decision about what the role owns; whether that decision still
  needs a model call of its own, once the diagnosis is a fact of the model, is for #267's third
  slice to measure.
- **N sources mounted.** Disk, and the time of keeping N caches current; sparse checkout bounds
  it, and the measurement above says by how much.
- **A reader per interface format.** OpenAPI, AsyncAPI, proto, migrations, compose, Kubernetes and
  Terraform each need a deterministic reader the platform keeps. A format it does not read is a
  gap the map names (D17), never a component silently missing.
- **A check on every turn that cites a concept.** `check_concepts` runs on what is cited, not on
  the whole bundle; its time is part of the turn.

## Left open

- **How events reach the model** — applied at the door, or by one workflow per product that the
  door signals — within D7's rule: in the door's order, deduplicated by id, never rebuilt by a
  turn.
- **The briefing's budget and wording** — #267's second slice, measured.
- **The files' layout** under the manifest (D6).
- **Which conversation a delivery goes to** when the request came from no conversation — a card
  filed on the board, whose requester is whoever filed it (ADR-0049 D7).
- **Which kinds are told by a fixed sentence and which by a turn** (D11).
- **The reconciliation's cadence** once events flow (D7, D13).
- **The preview's facts,** named when ADR-0050 is built.
- **The sparse mechanism** — git's sparse checkout, a partial clone, or both — chosen by #268's
  first slice on its measurement (D16).
- **The system layer's layout** in the context repository, and which interface formats it reads
  first (D17).
- ~~How a capability is written, and who confirms it~~ (D19). *Decided 2026-09-24 by #268's third
  slice.* The pipeline OBSERVES flows (an accepted or observed requirement whose `Affects` names two
  or more sources) and writes them to `.okf/flows/`, regenerated on every refresh and never curated
  truth — the prompt lists them as observed and not confirmed. A capability is CURATED at product
  level, `capabilities/<slug>.md` beside `requirements/` and `domain/`, never under `.okf/`; it
  counts as confirmed only with `confirmed_by` and `confirmed_at`, written by one act a person who
  may act takes (`product_confirm_capability`, under the semaphore), and the prompt never names who
  confirmed. A link that no longer resolves is listed beside it and never repaired on its own.
- ~~How the gap signal reaches the pipeline~~ (D22). *Decided 2026-09-24 by #268's third slice.*
  Code a turn read — from the reply's evidence and the harness stream's reads — is judged by the
  knowledge gate's own ladder; a `no-concept` verdict becomes a request in a per-product inbox under
  the state directory the worker and the panel share (repository, path and time; never the question
  or the person), deduplicated by gap key. The pipeline takes it at its own entry, after a merge or
  every six hours, merges it into the manifest and publishes: the pipeline stays the only writer of
  a bundle, and whether the file is then described is the budgeted paths' call (ADR-0046).

## History

- **2026-09-22 — inside #266.** The first version of #266 carried both parts as slices of its
  own: what the panel shows, the role can know, held by an automated check; and every source of
  the product mounted, with a system layer across them.
- **2026-09-22/23 — the review of #266.** The reviewer asked for an explicit exclusion list,
  starting with spend, because otherwise the check would demand it; for no names across
  conversations; and for the scope to be split. The product owner confirmed decision 7: the role
  does not see spend. The owner's view became #267, with events and the agenda; every source and
  the system layer became #268, carrying decisions 10 and 11.
- **2026-09-23 — the boundary became the product,** agreed on #266. The read model is the union of
  the member projects' boards, jobs and releases, and the sources the role mounts are the product's,
  as its context repository declares them.
- **2026-09-24 — this record,** written from #267 and #268 as Parts I and II; design only.
