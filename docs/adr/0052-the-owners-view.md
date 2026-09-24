# ADR 0052 — The owner's view

- **Status:** **Proposed** (design only) — written from #267 as it was agreed on review. No code
  changes with this ADR.
- **Date:** 2026-09-24
- **Relates to:** ADR-0019 (the product role — §6, where it meets the tech-lead through the
  diagnosis on the ticket, which D8 keeps; §7, one board per product, which D1 finally keys by),
  ADR-0020 (the tech-lead on call — the diagnosis D8 has the role consume), ADR-0021 (the open loop
  — §5 leaves an unanswered question as a visible open item, which D12 makes visible), ADR-0025
  (delivery closes with the client — the announcement D11 moves from the sweep to the delivery),
  ADR-0038 (the panel is the reference surface), ADR-0041 (facts are files — D6), ADR-0049 (D6, the
  board and the pull-request page are the panel's, through the ports; D7, the requester of a card),
  ADR-0050 (the preview — *Proposed*, #264; its state joins the *now* layer once it is built),
  ADR-0051 (one door — D1's `receive` and its internal events, D2's product, D3's queue per
  conversation, D5's rule on names, D13's `publish`; decisions 1, 7 and 8, which this record
  carries). Issues: #267 (this record); #266 (what it depends on — slice 3's door and
  conversations); #268 and #269 (not decided here).

## Context

The product role is meant to know the product the way the person who owns it does: what is
moving, what has stopped and on whom it waits, what was delivered and when, what is in production,
and what each card promises. The panel shows most of that to whoever opens it. The role sees a
part of it, and hears of the rest late.

What follows was read at `main` (`0f8314c`) and at the head of #266's stack (`a6cd347`, the branch
of its slice 6, which carries #290, #294 and #295). A `file:line` with no mark is the same in both
trees; one marked *(#266)* is in the stack only.

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

### What the owner does instead

Answers for themselves whatever touches the floor, a release, a card's content or a card outside
the window; and learns of a delivery from the sweep, or by opening the panel.

## Decision

**One read model of the product, read by the panel and by the role. The role can know whatever
the panel shows about the product, except what an explicit list excludes, and spend is on it.
What the role needs on every turn is a short briefing with the source and age of each line; the
rest stays in files. The model is kept by events that come through #266's door, and an event told
to a person waits its turn in their conversation.**

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
- **It is short, and bounded.** Its budget is set in slice 2 and held by the measurement in *What
  would make it wrong*.
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

## What this record carries from #266

| #266 | Decision | Here |
|---|---|---|
| decision 1 | The role's boundary is the product, not the registry project | D1 |
| decision 7 | The role does not see spend | D2, D3 |
| decision 8 | Three audiences — client, product admin, engineer — client by default | D10 |
| the review | No names across conversations | D9 |
| slice 3 | The door, and one serial queue per conversation | D7, D11 |

## What would make it wrong

A briefing is paid on every turn. It is right only if it replaces the exploration the role does
today — opening `board.md`, reading again what the last turn already read. That is measured, not
assumed, with #266's evaluation battery (slice 0, #281): the same questions on the same fixture,
with and without the briefing, recording per turn the score (correct, cited, abstained correctly),
the tokens and the files opened. A briefing that raises the tokens per turn without raising the
score is the wrong idea in the shape written here, and this record is the one to revise.

The same measurement decides whether the prompt's budgeted board section (`role.py::_board_section`)
stays beside the briefing or is folded into it.

## Not decided here

- **#268 — every source of the product, and the system layer across them,** with ADR-0051's
  decisions 10 and 11. ADR-0051 names this record as the companion for #267 and #268; this record
  takes #267 only, and #268's decisions wait for a record of their own.
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

## Slices

Ordered. Each merges on its own and carries its acceptance criteria. All three depend on #266's
slice 3 (the door and the conversations).

**1. The read model** (D1–D4, D6). One projection per product, over its member projects, consumed
by the panel and the role, with the exclusion list.
*Acceptance:*
- every fact a panel screen shows about the product is reachable by the role, except the excluded
  ones — the guard of D3 compares the two and reads the list;
- spend is not reachable;
- two registry projects of one product give one model, holding both boards.

**2. The briefing** (D5, D9, D10).
*Acceptance:*
- on a fixture project, the briefing lists the moving, parked and waiting cards and the version in
  production;
- each line states its source and age;
- rendered for a conversation the requester is not in, it names nobody;
- the battery's record, with and without the briefing, states the score, the tokens and the files
  opened per turn.

**3. Events and the agenda** (D7, D8, D11–D13).
*Acceptance:*
- a delivered card is announced to its requester's conversation when it is delivered, not at the
  next sweep;
- a proactive message never interleaves with a turn in progress;
- the agenda is visible on the panel, and an item owed in a private conversation is shown to its
  person only;
- nothing proactive calls `channel.say` outside the door.

## Consequences

**Good.** The role answers what an owner asks — why did this stop, when did that ship, what is in
production, what did we promise on #42 — from the facts the panel shows, and says how old they
are. The person who asked hears of a delivery when it happens, in their own conversation. The
tech-lead and the product role look at one world.

**Costs and risks, declared.**

- **The panel moves onto the projection.** Its screens read the ports directly today
  (`api/app.py::board_view`, ADR-0049 D6). Moving them is the largest part of slice 1, and a screen
  left on the ports is what D3's fourth check catches.
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
  needs a model call of its own, once the diagnosis is a fact of the model, is for slice 3 to
  measure.

## Left open

- **How events reach the model** — applied at the door, or by one workflow per product that the
  door signals — within D7's rule: in the door's order, deduplicated by id, never rebuilt by a
  turn.
- **The briefing's budget and wording** — slice 2, measured.
- **The files' layout** under the manifest (D6).
- **Which conversation a delivery goes to** when the request came from no conversation — a card
  filed on the board, whose requester is whoever filed it (ADR-0049 D7).
- **Which kinds are told by a fixed sentence and which by a turn** (D11).
- **The reconciliation's cadence** once events flow (D7, D13).
- **The preview's facts,** named when ADR-0050 is built.

## History

- **2026-09-22 — inside #266.** The first version of #266 carried this as one of its slices: what
  the panel shows, the role can know, held by an automated check.
- **2026-09-22/23 — the review of #266.** The reviewer asked for an explicit exclusion list,
  starting with spend, because otherwise the check would demand it; for no names across
  conversations; and for the scope to be split. The product owner confirmed decision 7: the role
  does not see spend. The owner's view became #267, with events and the agenda.
- **2026-09-23 — the boundary became the product,** agreed on #266. The read model is the union of
  the member projects' boards, jobs and releases.
- **2026-09-24 — this record,** written from #267; design only.
