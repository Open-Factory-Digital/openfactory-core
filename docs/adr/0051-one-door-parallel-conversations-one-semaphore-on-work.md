# ADR 0051 — One door, parallel conversations, one semaphore on work

- **Status:** **Accepted** (design only; 2026-09-24) — the product owner accepted the design
  together with its review's recommendations, with slice 0 the first to be built. No code changes
  with this ADR.
- **Date:** 2026-09-23
- **Relates to:** ADR-0019 (the product role and its context repository; §7 and §8 declare the
  product this record keys everything by), ADR-0021 (the open loop, closed by observation — D11
  scopes who may close one), ADR-0024 (conversational memory — **this record moves §1's partition
  key from the registry project to the product** (D2), and says so there in a dated note; §5,
  retrieval, is revised by ADR-0053, from #269), ADR-0029 (a click is not interpreted — the staging
  compare-and-swap it rests on is kept), ADR-0032 (the requirement cycle happens in the channel;
  merging is not agreeing — carried into the conversation by ADR-0047), ADR-0038 (the platform is
  complete on its own; channels are add-ons — this record finishes its product half), ADR-0047 (two
  yeses, and the subject of both is the requester — D11 is what enforces its §4 in a group, and
  extends `product.accept_on_behalf` from the second yes to the first). Issues: #266 (this record
  and slices 0–6); #267 and #268 (the owner's view, events and the agenda, every source and the
  system layer — companion record **ADR-0052**, not written yet); #269 (the guardian's memory —
  companion record **ADR-0053**, not written yet).

## Context

The product role is the part of the platform a client meets first and talks to most. It takes a
request, writes the requirement, opens the ticket, tells the requester when the work is ready and
asks whether it works. The promise of a product owner who knows the product rests on it.

Read against the code, the experience is not that of a product owner. On the panel it is a form —
a textarea, an *Ask* button, a spinner for one to three minutes, a history that refreshes every
thirty seconds — where a typed "yes" confirms nothing. In a group it would answer everyone at once,
blind to who is speaking and to its own other answers. And two conversations can turn one request
into two tickets, or two requirements into one number.

What follows was read at `main` (`0f8314c`); every `file:line` is from that tree.

### Three doors, and the complete one has no caller in the core

| Path | Called by | What it does |
|---|---|---|
| `product_ask` → `ProductAskWorkflow` → `runtime/temporal/activities.py::_product_draft` (`:2874`) | the panel (`api/panel.html::askProduct`, `:1937`) | Records, answers, and drafts when the message is a request. No `settle`: a typed "yes", "it worked" or "it did not work" is not read as a confirmation or an acceptance. No pending line, no intake case, none of the defect / ticket / reorder / queue gestures. |
| `product_say` → `ProductSayWorkflow` → `activities.py::_product_conversation` (`:3139`) | nothing — the catalog says so itself (`actions/catalog.py:2319-2321`) | Records, settles, answers. Never drafts. |
| `product/channel.py::handle` (`:214`) → `_handle` (`:453`) | no caller in this repository; only the external Slack add-on | The whole conversation: `settle` (`:286`), the intents, intake, the gestures, staging, drafting. |

The intent fast path exists a fourth time, in the catalog (`_say_as_an_intent`, `:2563`), which
routes four intents that never write (`_SAY_INTENTS`, `:2412`). The panel — the reference surface
of ADR-0038 D1 — got the reduced conversation; the full one stayed with the transport that
ADR-0038 D3 moved out of the core.

### The vendor left as code and stayed as shape

- `product/channel.py::conversation_key` (`:190-204`) parses a Slack event: the thread's timestamp,
  else the channel.
- `adapters/channel/registry.py::channel_kind` (`:46`, the inference at `:69-70`) infers that a
  project with a `channel_id` is on Slack.
- `contracts/product.py:28-38` and `contracts/project.py:261-272`: `channel_id` is an alias of
  `slack_channel`, and `admins` an alias of `slack_admins`, documented as Slack user ids in
  `contracts/product.py:34`. The bot-token migration (`contracts/project.py:326-336`) still folds
  Slack-shaped fields.
- `contracts/project.py:157` still documents Slack as the default channel, although the registry's
  default is the panel (`DEFAULT_KIND`, `adapters/channel/registry.py:21`).
- A product write is authorised by a vendor's user id, not by a person of the platform.

### Nothing orders a turn, and nothing guards what becomes work

There is no lock, queue, busy state or serialisation of product turns, and the worker runs eight
activities at once (`runtime/temporal/worker.py:342`). When two people write at the same time:

- **Two model runs start in parallel.** Each one's rendering of the transcript may or may not
  include the other's message — `channel.py:228-232` says so in its own comment — and nothing links
  a reply to the message it answers.
- **A requirement number can be issued twice.** `propose_requirement` mints the number from the
  base corpus and the unlanded `req/*` branches (`product/authoring.py:405-468`), clones at depth 1,
  commits and pushes to the base (`:622`). When two proposals run at once, each mints N; one push
  lands, and the other, rejected as not a fast-forward, lands instead on a `req/N-…` branch that
  asks for a review (`:625-638`). N now names two requirements — the corruption `next_number`'s own
  docstring (`:120`) warns about. Rebasing cannot repair it, since N was fixed before either push.
- **Direct commits to the context repository collide.** `record_fact`, `record_decision` and
  `accept_requirement` clone at depth 1 and push to the base (`:1313`, `:1428`, `:1492`). The second
  of two concurrent saves is refused, and the person is told the save failed.
- **The same request becomes two tickets.** "Was this asked before?" (`product/asked.py`) and the
  write are two separate steps. Two conversations can both find nothing, and both write.
- **Staging holds one proposal per conversation, and the last one wins** (`product/staging.py`). In
  a group, a second request displaces the first person's draft, and any admin's "yes" confirms
  whatever is staged.
- **One message closes every open decision.** `ProductModule.close_decisions_answered`
  (`product/module.py:1091`) closes every open decision loop of the project on any conversational
  message from anyone. That is a scoping defect, not a race; concurrency only makes it more likely.
- **Workflow ids are not stable.** They end in `abs(hash(text)) % 10**8` (`actions/catalog.py:2350`,
  `:2640`). Python randomises its string hash per process, so the id differs across API processes
  and restarts, two ids can collide only within one process, and a retry never deduplicates.
- **The shared workspace is rebuilt under other turns.** Every turn recomposes the same
  `{project}-view` worktree in place (`ProductModule._workspace`, `module.py:784`), so one turn can
  reset it while another turn's agent is reading it.
- **The last writer wins in two files.** `cases.json` (`product/case.py:145`) and
  `recall-index.json` (`memory/recall.py:37`) are read, changed and rewritten with a plain
  `write_text`.

Some of it is already safe and must stay so. The staging compare-and-swap (`staging.consume`,
`:319`) with its durable `answer_of` check protects a confirmation. The loop ledger only appends.

### A turn is one blocking call

`ProductRole` runs one agent to completion (`_ask`, `product/role.py:1264`) and streams nothing to
the person; the case recorded at `:1293` was two minutes and thirty-eight seconds of silence. The
activity is capped at ten minutes with one attempt (`runtime/temporal/workflow.py:233-234`,
`ProductAskWorkflow`). The panel shows a spinner and polls the room every thirty seconds
(`_CHAT_TICK=15000`, doubled — `panel.html:1125`, `:1994`). It already holds a WebSocket
(`/api/stream`, `api/app.py:1777`), but that carries the floor's messages, not the product
transcript, and `bootProduct` does not open it.

### The role does not know who is speaking

`ProductModule.answer` (`module.py:930`) and `ProductRole.answer` take no speaker. The only trace
is the transcript line `"{actor}: text"`, with `actor` a raw id, and the role's prompt
(`org_defaults/roles/product.md`) has no notion of the speaker's role.

### The role is keyed by the wrong boundary

ADR-0019 already makes people declare what a product is (§7, §8; `product/config.py::
resolve_product_link`, `:211`): the registry's `product.docs_repo` authorises which context
repository a registry project belongs to; the context repository's `.openfactory/product.yaml`
lists every source of the product under `sources:`; and a source's own manifest may claim
`docs_repo`, which confirms and never redirects — a disagreement turns the module off. A monolith
is a product with one source; a multi-repo product is one context repository listing N.

The code does not key the role by it. One `ProductModule` exists per registry project, and each
registry project has its own partition of the transcript (`memory/transcript.py:30`, `:97`). Two
registry projects that point at one context repository get two minds and two memories — and, under
any lock keyed the same way, two locks over one requirements corpus, which brings the duplicate
number straight back: numbers are minted in the context repository.

## Decision

**One door in, one engine, one way out. Conversations run in parallel, one turn at a time inside
each; what becomes work passes one semaphore per product, where checking whether it exists and
writing it are a single step.**

What the product keeps is what turns into work — a requirement, a ticket, a decision, a fact —
not the talk that led to it. The conversations are therefore left free, and the record is guarded.

```
panel (websocket) ─┐
CLI ───────────────┤
add-on ────────────┼─► receive(Message) ─► conversation workflow (serial) ─► turn engine ─┐
internal events ───┘         (one per conversation, many in parallel)                      │
                                                                                            ▼
                                                             ┌── semaphore (per product) ◄──┤ only when a turn
                                                             │   same seq → mint → write    │ turns into work
                                                             └──────────────────────────────┤
panel / add-on ◄───── publish(Reply) ◄───── transcript (recorded before delivery) ◄─────────┘
```

### D1 — One door: `receive(Message)`, with a message contract no vendor shaped

`receive(Message)` is the single entry point of the core. Every transport (the panel, the CLI, any
add-on) and every internal event goes through it. It validates the message, deduplicates it by its
id, enqueues it on its conversation and returns an acknowledgement at once. **No model is
called at the door.**

`Message{id, project, conversation, speaker: Person, text, in_reply_to, addressed_to_role,
context: {page, card?, …}, attachments}`. The `speaker` is a person of the platform, never a vendor
id; mapping a vendor's user to a person is the add-on's job. The `context` carries what the speaker
is looking at, so "why did this stop?" asked on card #42's page is about card #42.

`project` is the **registry project** the speaker is on — the panel page's project, or the one an
add-on's channel is configured for — and the door resolves the product from it through ADR-0019's
link (`product/config.py::resolve_product_link`, the normalised `product.docs_repo`,
`normalize_repo`, `:93`). Past the door, nothing keys a conversation, a memory, a check or the
semaphore by `project`: keying by it is the two-locks defect D2 exists to prevent. A registry
project with no active product link has no role to talk to, and the door says so.

*Why:* three doors drifted apart because each was written for one caller, and the complete one
ended up with the only caller the core does not own. One door is the only shape that cannot drift
that way.

### D2 — The boundary of the role is the product

The role's boundary is the **product** that ADR-0019 §8 declares, identified by its authorised
context repository (the normalised registry `product.docs_repo`). The role, its conversations, its
memory, the duplicate check and the semaphore are keyed by product. The registry project stays
**the factory's unit** — board, box, pipeline — and a ticket the role files names the source it
lands in (`ProductModule._sources`, `module.py:1968`, as `break_down` already does).

Keying memory by product moves ADR-0024 §1, which partitions the raw log by registry project; this
record amends that section, and the deletion path moves with it (*Consequences*).

*Why:* requirement numbers and decisions are written in the context repository, so anything that
guards them must be keyed by it; a key per registry project gives a multi-repo product two locks
over one corpus. No configuration is added — the boundary is what ADR-0019 already has people
declare. A product built from one repository, registered once, is its own product, and nothing
changes for whoever declared it.

### D3 — One role per product; one serial queue per conversation; conversations in parallel

- **One role per product:** one identity, one body of knowledge.
- **Each conversation** — a private chat, a group room — has its own long-lived Temporal workflow,
  `po-{product}-{conversation}`, started with signal-with-start. Each message is a signal carrying
  its own id. Ordering, durability across a worker restart and deduplication are per conversation.
  The `hash(text)` ids go away.
- **Inside a conversation, one turn at a time.** Across conversations, nothing is ordered.

*Why:* a single queue per product would put every conversation's messages in one context, paying
tokens for words that add nothing to the product, and would make every person wait on everyone
else. What one conversation must learn from another is what was decided or asked for, and that is
saved (D10), not queued. Someone thinking out loud in one conversation never holds up someone
asking for work in another.

### D4 — A ceiling on concurrent turns, which orders nothing

A cap on concurrent turns per product and per deployment, enforced by the engine. It bounds cost
and exposure to a provider's rate limits; it orders nothing.

*Why:* ten parallel conversations are ten model runs at once, on a worker that runs eight
activities. Parallel by default needs a ceiling that is declared, not discovered.

### D5 — Inside a conversation: debounce, coalesce, and a busy role is shown busy

1. **Debounce.** A turn starts a few seconds after the last message, because people write in
   bursts.
2. **Coalesce per speaker.** Everything one person wrote while the role was busy in that
   conversation is answered in a single turn.

**Busy is shown, never refused.** In a group every message is accepted and seen. The sender
is acknowledged within two seconds — the role has the message and the sender is next — **with no
name** of whoever the role is answering. More generally, the role never names a person from
outside the current conversation, in any message — including the requester a saved record names,
when the role cites that record as a match found from another conversation (D9).

Inside a group, no one jumps the queue.

*Why:* an acknowledgement is what makes a wait bearable; a name in it tells one person who else is
talking to the product, which is not theirs to know.

### D6 — A bounded turn, and a fast path that is not a turn

A turn is bounded (about ninety seconds). Long work — a breakdown, a baseline, a large reading of
the code — becomes an asynchronous task the role starts and reports back on; the result comes back
through the same door. The read-only fast path (status, triage, what is waiting on me) is answered
without a model turn, and is the only thing that bypasses a turn.

*Why:* a turn that holds a conversation for minutes holds everyone behind it in a group room;
per-conversation queues shrink that to one room, and the bound removes the rest.

### D7 — One semaphore per product on what becomes work; inside it, check and write are one step

One lock per product — per context repository, where numbers and decisions are written — around
every act that creates or changes the product's record: a requirement, a ticket, a decision, a
fact, an acceptance. What the lock makes one step is the duplicate check and the write: the write
goes ahead only if nothing that could become work was written or staged after the check was made.

```
seq, match ← search and judge, noting the write sequence        # before the lock (D8)
repeat at most N times, while match is none:
  acquire(product)
    if the write sequence is still seq:                          # nothing arrived since
      mint the number → commit → push → bump the write sequence
      release(product); done
    new ← what was written or staged after seq;  seq ← the sequence now
  release(product)
  match ← judge(the saved items in new)                          # outside the lock (D8, D9)
match found → do not write; link to it and tell the person
N spent     → nothing is written unchecked (Left open)
```

An act with nothing to duplicate — an acceptance — skips the judgement and takes the lock for its
write alone.

*Why:* a lock around the write alone still lets two conversations both find nothing and both
write the same ticket; the check and the write have to be one step. They are one because, inside
the lock, the write is refused whenever the sequence the check saw has moved, and the turn goes
back to judge what moved it. And the number is part of the write: minted outside the lock, it is
minted twice (see *Context*), so *mint → commit → push* is inside. The lock gives mutual exclusion
and nothing else, which is exactly what saves need — ordering between them does not matter.

### D8 — The model judges before the lock: the write sequence

"Is this the same as something that exists?" is a model call, and the lock is never held for one.
The turn searches and judges **before** it asks for the semaphore, and notes the product's
**write sequence** as it searches; every write and every staging bumps it. A staged draft keeps
the sequence of the search it was drafted from, so its confirmation, up to two hours later, judges
only what arrived after it was staged. Inside the lock nothing is judged — the sequence is
compared with the one the turn noted:

- **unchanged** (the usual case): the judgement still holds, and the turn writes;
- **moved**: the turn releases the lock, judges only what arrived after its sequence — a handful of
  items, of which only saved ones can stop the write (D9) — and asks for the lock again with the
  new sequence.

The retry is bounded. A turn whose sequence moves on every round does not write unchecked and does
not judge under the lock; what it does instead, and the bound itself, are slice 3's (*Left open*).
The hold is a comparison and a write: seconds, most of it the push.

*Why:* the semaphore is a single point of contention per product, and it stays cheap only if what
is expensive happens before it. A re-check judged inside the lock would hold every other write of
the product for a model call exactly when two conversations are busy at once — which is when the
lock is contended.

### D9 — Staged drafts are checked, only a saved record stops a write, and nobody is named

The check reads saved requirements, decisions and tickets, **and drafts staged but not yet
confirmed in any other conversation**. The two count differently:

- **When a draft is staged,** a saved match is linked instead of staged. A staged twin in another
  conversation is reported without a name — someone asked for something close to this a few
  minutes ago — and the person's own draft is staged anyway: an unconfirmed draft is nobody's yet.
  Staging takes no lock; two twins staged in the same moment may both miss that notice, and lose
  nothing by it, because of the next rule.
- **When a draft is written,** only saved records stop it. The first confirmation through the
  semaphore writes; its twin's confirmation finds that record among what moved its sequence (D8),
  writes nothing, and its requester is told the work exists and is linked to it. A staged draft
  never blocks a write: it has no number to link to, and two people who had each staged the same
  request would otherwise hold each other off until one of the drafts expired, two hours later
  (`PROPOSAL_TTL_SECONDS`, `product/staging.py:44`).
- **Nobody is named.** What is found from another conversation is cited by what it is — this was
  just asked for, and it is requirement 41 — and never by who asked, **even when the saved record
  names its requester**, as a requirement's front matter does
  (`authoring.py::_requester_front_matter`, `:741`). The citation is the number and what it says.

*Why:* a draft can sit in staging for up to two hours before it is confirmed, so two people asking
for the same thing minutes apart would otherwise both see nothing saved. Counting staged drafts is
cheap — the set is small, it is about the product, and it shares no one's history.

### D10 — Written the moment it is confirmed

A requirement, a decision or a ticket is written at the moment it is confirmed, not when the
conversation ends. `record_decision` already does this; this record makes it the rule.

*Why:* once conversations run side by side, nothing but the saved record carries a decision from
one of them to another. The end-of-conversation distillation that ADR-0053 (#269) designs is the
catch-all for what no confirmation captured, never the path a confirmed decision takes.

### D11 — What parallel turns need besides the lock

- **A workspace per turn.** Each turn gets its own view, or an immutable snapshot — never the
  shared `{project}-view` recomposed in place.
- **Atomic stores.** `cases.json` and `recall-index.json` get an atomic replace and a lock of
  their own — not the product semaphore, which is only for what becomes work — or move to the
  database. Both are kept per registry project today (`product/case.py::_path`, `:104`;
  `memory/recall.py::refresh`, `:221`), and the recall index also reads the tech lead's messages,
  which stay per registry project; slice 3 says which key each file takes once the transcript is
  the product's (D2).
- **Staging keyed by `(conversation, person)`,** with the confirmation bound to the requester
  (ADR-0047 §4). Another admin's "yes" confirms it only where `product.accept_on_behalf` says so —
  which this record **extends**: at `0f8314c` that key governs the second yes alone, the
  acceptance (`contracts/product.py:52-57`; `module.py::_not_the_requester`, `:415`), and here it
  governs the first as well, the draft's confirmation. ADR-0047 §4 names both acts, and one key
  gives one answer to whether an admin may speak for the requester.
- **A decision closes only by the person it was asked of,** in the conversation it was asked in —
  `close_decisions_answered` scoped accordingly (ADR-0021: closed by observation, and the
  observation has to be the right person's).

*Why:* each of these is shared state the *Context* found unprotected; the semaphore covers the
product's record, and these are the rest.

### D12 — One turn engine

One implementation, with explicit stages that can each be tested on their own:

`settle → intents → answer → gestures (defect / ticket / request / reorder / queue) → staging`

What is spread today across `channel.handle`, `_product_draft`, `_product_conversation` and
`_say_as_an_intent` becomes this engine. It takes a `Message` and returns `Reply`s, with no
callbacks and no vendor shape. `product_ask` and `product_say` become one action row. Nothing
outside the engine calls `ProductModule.answer` or `ProductRole.answer`, and a guard says so.

*Why:* four partial copies of one conversation is how a typed "yes" came to work in one transport
and not in the reference surface. ADR-0032 put the requirement cycle in the channel and ADR-0047
carried it into the conversation; today it runs whole only in the conversation the core does not
own.

### D13 — One way out: `publish(Reply)`

The engine never calls `channel.say`. It records the reply in the transcript and publishes
`Reply{id, in_reply_to, conversation, addressed_to, text, options?}`; the transports subscribed to
that conversation render it. A question with buttons is a `Reply` with options, which each
transport renders its own way (ADR-0038 D2); a click stays what ADR-0029 made it — never
interpreted. The `notify` and `confirm` callbacks (`channel.py:215`) disappear.

*Why:* a reply that is recorded before it is delivered is a reply memory has — the lesson of
ADR-0024's audit, where a proactive message sent by a bare `say` was the one turn memory lacked.

### D14 — Addressing in a group

The core defines what *addressed to the role* means: a mention, a reply inside a conversation it
takes part in, or a direct conversation. Each transport only detects the mention its own way. What
is not addressed to the role is stored and searchable (ADR-0053's), and **never added to a turn's
prompt**.

*Why:* a role that reads every line of a busy room pays for chatter on every turn — the cost D3
avoids by keeping conversations apart.

### D15 — The panel is a chat

The panel's existing WebSocket carries the product transcript and the role's presence (idle,
thinking, answering, position in the queue), filtered per subscriber so a private conversation
never reaches anyone else. Tokens stream. The chat is present on every panel page, not only on
`/product/<project>`, and each message carries the page it was written on.

*Why:* ADR-0038 D1 makes the panel the reference surface; a surface where a confirmation does not
confirm and an answer arrives by polling is not one.

### D16 — No vendor in the core

These leave the core: `conversation_key(event)` and `is_product_channel`; the Slack-shaped
`channel_id` and the inference that a `channel_id` means Slack; vendor-id `admins`. **A product
admin is a person of the platform.** The old keys (`slack_channel`, `slack_admins`) are read as
aliases, with a deprecation warning, for one minor version. The Slack add-on adapts to the new door
outside the core; its current version breaks, so the core ships this as a minor version.

*Why:* the transport left the core in ADR-0038 and its shape stayed in the contract. A core whose
contract a vendor shaped is a core with a default vendor.

### D17 — The judgement is kept, written down before the old code goes

What is rebuilt is the structure the judgement runs in, not the judgement. Kept, and turned into
characterisation tests **before** the code that holds it is deleted:

- the requirement corpus, the glossary and authoring, including the number adoption and bump rules
  for retries and unlanded branches (`authoring.py:405-468`);
- the staging compare-and-swap and its durable `answer_of` check;
- the conduct rules: cite or say you do not know; no forge vocabulary to a client; the two yeses of
  ADR-0047; one confirmation per write; the click of ADR-0029;
- every rule in `channel.py`'s 1,463 lines that came from an incident — the conversation-key defect
  and the standalone "yes" of ADR-0024's audit, and the proactive turn memory did not have.

The pull request that brings a slice in also removes the path that slice replaces.

*Why:* the three doors drifted apart because old and new paths stayed live side by side; and a
deletion nobody can verify is how judgement is lost on the way.

## The decisions taken on review

The sixteen questions #266 put to review, as answered. Two of them (2 and 7) were confirmed by the
product owner during the review, and on 2026-09-24 the product owner accepted the design with the
review's recommendations, which settles the rest as answered here. Those that bind #267, #268 and
#269 are recorded here because they were taken here; ADR-0052 and ADR-0053 carry them.

| # | Question | Decision | Lands in |
|---|---|---|---|
| 1 | Scope of the role | One per **product** (the ADR-0019 context repository), not per registry project | D2, D3 |
| 2 | Queues | One serial queue per conversation, conversations in parallel; cross-conversation duplicates are caught by the semaphore's check, which reads staged drafts — never by a shared queue | D3, D7–D9 |
| 3 | Group conversations | The role answers only when addressed; the rest is stored and searchable, never prompted | D14 |
| 4 | Longest turn before a hand-off | About ninety seconds | D6 |
| 5 | Jumping the queue | No one, inside a group; only the read-only fast path bypasses a turn | D5, D6 |
| 6 | Old configuration keys | `slack_channel` / `slack_admins` read as aliases, with a deprecation warning, for one minor version | D16 |
| 7 | Spend | The role does not see it | #267 (ADR-0052) |
| 8 | Audiences | Three — client, product admin, engineer — with client the default | slice 4; #267, #269 |
| 9 | Evaluation questions | Written by the product owner; expected answers and automation by the implementer | slice 0 |
| 10 | Sources | Repositories and the context repository are in the core; any other source is an add-on axis | #268 (ADR-0052) |
| 11 | Very large products | Every source mounted, sparse checkout on demand | #268 (ADR-0052) |
| 12 | Retention | The distillate is permanent in the context repository; raw conversation retention is configurable per client, default unchanged | #269 (ADR-0053) |
| 13 | Large files | Git LFS by default, an adapter for object storage | #269 (ADR-0053) |
| 14 | Embeddings | A local model by default; an external API only when the client turns it on | #269 (ADR-0053) |
| 15 | Document content | Cited, and promoted to curated truth only after a person confirms | #269 (ADR-0053) |
| 16 | How documents arrive | Panel upload first; a commit always works; connectors are add-ons | #269 (ADR-0053) |

## Slices

Ordered. Each merges on its own and carries its acceptance criteria.

**0. Evaluation first, on one fixture.** A battery of real product-owner questions, each with an
expected answer and an expected source, measuring whether the answer is correct, whether it is
cited, and whether the role says it does not know when it should. It starts with **one** fixture
project and records today's baseline; the other fixtures (a monorepo, multi-repo services, a
product years old) arrive with the slices of #268 and #269.
*Acceptance:* the battery runs from `make`, and today's role has a recorded score.

**1. Characterisation of the conversation** (D17). Tests that pin `channel.handle` flow by flow —
confirmation, intents, gestures, intake, expiry, rejection by the requester — driven through a
transport-neutral harness.
*Acceptance:* the suite is green on today's `channel.handle`; each test is shown red against a
targeted sabotage.

**2. One turn engine, and a workspace per turn** (D11, D12). The panel switches to the engine;
`product_ask`, `product_say`, `_product_draft`, `_product_conversation` and `_say_as_an_intent`
are deleted.
*Acceptance:* slice 1 is green against the engine; a typed "yes" on the panel confirms a staged
draft; a guard fails if anything outside the engine calls `module.answer` / `role.answer`; two
concurrent turns never share a workspace.

**3. Conversations and the semaphore** (D1–D10, and D11's stores): the door, resolving each
message's product; the product as the key of the role, its conversations, its memory and the
semaphore, with the transcript re-keyed as ADR-0024 §1 now says and the deletion path following
it; the per-conversation workflows with debounce, coalescing and an anonymous acknowledgement; the
bounded turn with its hand-off; the concurrency cap; the per-product semaphore with check-and-write
as one step and the write sequence; staged drafts in the duplicate check; saving at confirmation;
the atomic stores.
*Acceptance:*
- two messages in different conversations run concurrently;
- two messages in the same conversation run one after the other;
- the second sender in a group is acknowledged in under two seconds, without anyone's name;
- no message is lost across a worker restart mid-turn;
- two concurrent requirement proposals never get the same number;
- two concurrent decision saves both land;
- two conversations asking for the same thing at the same time produce **one** ticket, and the
  second requester is told it exists and is linked to it — also when both had staged a draft
  before either confirmed;
- a draft staged in one conversation is found, anonymously, from another;
- no model call is made while the semaphore is held: a turn whose write sequence moved releases it
  before it judges what arrived;
- two registry projects of one product share one role, one memory and one semaphore: concurrent
  proposals from both never get the same number;
- forgetting a registry project's conversations forgets its product's, the rows written before the
  re-keying included, and names the registry projects that share them before it asks.

**4. Speaker, reply and addressing** (D1's `speaker` and `in_reply_to`, D11's staging and
decision scoping, D14). `speaker` is a person with a role per product; `in_reply_to` is kept in the
transcript.
*Acceptance:* in a room, a second request no longer displaces the first person's draft; another
admin's "yes" does not confirm it unless `accept_on_behalf` is set; one person's message does not
close another person's decision; a message in a room that is not addressed to the role is stored
and found by recall, starts no turn and is not in the next turn's prompt, while a mention, a reply
inside a conversation the role takes part in, or a direct message starts one.

**5. The panel as a chat** (D13, D15), driven end to end on the e2e bed.
*Acceptance:* no polling on the product page; a private conversation is never delivered to another
subscriber; asked on card #42's page, "why did this stop?" is answered about #42.

**6. A core without a vendor** (D16).
*Acceptance:* a guard fails on a vendor name outside comments in `openfactory/`; the whole
conversation works with no add-on installed; an existing configuration with the old keys still
loads, and warns.

## What this does NOT mean

- **Not one queue per product.** No conversation is ever ordered against another. Only what
  becomes work is serialised, and only for the seconds it takes to compare a sequence and write.
- **Not a lock around a turn or a model call.** The semaphore covers a comparison of the write
  sequence and a write (D8); a turn that holds it while it thinks is a defect, and a moved sequence
  is judged after the lock is released.
- **Not that a conversation becomes the record.** The record is still what ADR-0019 made it: the
  context repository and the board. The transcript is what the role remembers from, not what the
  product is.
- **Not a revision of ADR-0024 beyond its partition key.** This record moves ADR-0024 §1's
  partition from the registry project to the product (D2), with a dated note in that section, and
  the deletion path and the rows written so far move with it (*Consequences*). The rest it takes as
  it stands: the raw log recorded on arrival, the conversation as the unit of working memory. What
  changes besides is who names the conversation — the transport, through `Message.conversation`,
  instead of the core parsing a vendor's event. ADR-0024 §5 (retrieval) and a retention set per
  client (decision 12) are ADR-0053's, from #269.
- **Not a new configuration.** The product boundary is ADR-0019's declaration; no key is added for
  it.
- **Not that the registry project goes away.** It stays the factory's unit: its board, its box, its
  pipeline.
- **Not a rewrite of the judgement.** The conduct rules, the staging compare-and-swap, the two
  yeses and the click are kept, and pinned by tests before anything is moved (D17).
- **Not that ADR-0016 is relaxed.** Releasing to production from a conversation stays refused.
- **Not any specific add-on.** How Slack, or any other transport, maps its users to people and
  detects a mention is the add-on's, outside the core.

## Consequences

**Good.** One conversation, the whole of it, on every surface — the panel included, where a typed
"yes" finally confirms. People talk to the role at the same time without waiting on each other, and
without the role mixing their words. What becomes work is checked and written once: one number per
requirement, one ticket per request, a save that lands. The role knows who is speaking and which
message it is answering. The core's contract stops naming a vendor.

**Costs and risks, declared.**

- **Every write of one product queues on one lock.** That is cheap only while the model's
  judgement happens before the lock. Inside it are a comparison and a push, so a lock held for long
  points at the push to the context repository; a turn that goes round the retry often points at a
  product whose writes arrive faster than one judgement takes, which is contention to measure, not
  a reason to judge under the lock.
- **A large surface change.** More than ever rests on the panel, and the Slack add-on's current
  version stops working. The evaluation battery (slice 0) and the characterisation suite (slice 1)
  are there so that an improvement is a measured number, not a belief.
- **A bounded turn splits long answers in two.** Work over the bound comes back later, as a second
  message through the same door; the person sees a promise and then a result, not one reply.
- **The cap turns load into waiting.** Past it, a turn waits for a slot; the person sees that as
  presence, not as silence, but it is still a wait.
- **A workspace per turn costs a composition per turn.** Disk and time that the shared view saved
  by being wrong; how much has to be measured in slice 2.
- **Memory changes its key.** The transcript rows written so far are partitioned by registry
  project (`memory/transcript.py:30`); reading them under the product needs a mapping or a
  migration, which slice 3 has to state. For a product with one registry project the mapping is
  one to one; for a product with several, it joins conversations that were kept apart, which is a
  real move of client data.
- **The deletion path moves with the key.** `openfactory project forget-conversations <project>`
  (`cli.py:394`) deletes one partition (`memory/transcript.py::forget_project`, `:190`). Once the
  partition is the product, forgetting a registry project's conversations forgets its product's,
  which every registry project of that product shares: the command names those registry projects
  before it asks, and until the old rows are migrated it also deletes the ones still under each
  member's registry-project key — a deletion that left them would report as done a request whose
  data is still there. Retention does not change: `RETENTION_DAYS` (`memory/transcript.py:64`)
  expires each row whatever its key, and a retention set per client is decision 12, ADR-0053's.
- **Anonymous is not invisible.** Telling a person that something close was asked minutes ago
  reveals that someone asked. That is the purpose of the check (D9); what crosses the boundary is
  that a request exists and what it is about, never who made it.

## Left open

- **The numbers.** The debounce ("a few seconds"), the turn's bound (about ninety seconds, decision
  4) and the concurrency caps per product and per deployment are to be set in slice 3 and
  measured, not argued.
- **How the semaphore is held.** Its scope (per product), what it covers (a comparison of the
  write sequence, and the write) and its duration (seconds) are decided, and so is the rule for a
  moved sequence (D8: release, judge outside, ask again). Its mechanism, where the write sequence
  is stored, what happens to a holder that dies mid-write, how many rounds a turn gets before it
  stops, and what the person is told when it does are slice 3's to specify and prove — within the
  rule that nothing is written unchecked and nothing is judged under the lock.
- **A view or a snapshot per turn** (D11) — slice 2 chooses; either satisfies the rule.
- **An atomic replace with a lock of their own, or the database,** for `cases.json` and
  `recall-index.json`, and which key each takes (D11) — slice 3 chooses.
- **Where a person's role per product is declared** (decision 8's three audiences) — slice 4, with
  #267.
- **The shape of `Message.context`** beyond the page and the card.
- **The companion records.** ADR-0052 (#267, #268: the owner's view, events and the agenda, every
  source and the system layer) and ADR-0053 (#269: the guardian's memory, revising ADR-0024 §5)
  are not written yet. The exclusion of spend from what the role may know (decision 7) is
  #267's to write into its read model and into the check that holds it.

## History

- **2026-09-22 — first version (#266).** The design put the whole product role on one serial queue
  per project, kept a rule that let a turn see the messages queued behind it (so the role could
  tell a person that someone had just asked the same thing), and rejected a database lease because
  a lease gives mutual exclusion without ordering. Its acknowledgement named the person the role
  was busy with. It also covered what is now #267, #268 and #269.
- **2026-09-22/23 — the review.** The reviewer read the design against the code and moved its
  centre:
  - **A queue per conversation instead of one per product.** Keeping every conversation in one
    context spends tokens on words that add nothing to the product and makes everybody wait, while
    what one conversation must learn from another is what was saved. The rule that showed a turn
    the queue behind it was dropped, and its purpose moved to the duplicate check.
  - **The lease had been rejected for the wrong reason.** Saves need mutual exclusion and no
    ordering, so the review proposed a per-project lock on saves. The product owner widened it to
    cover the duplicate check and the write as one step — a lock on the write alone still lets two
    conversations both find nothing and both write — and kept it short by moving the judgement out
    and re-checking only what arrived after the turn's write sequence.
  - **The mechanism behind a duplicate requirement number was corrected, not the conclusion.** The
    review placed the race between `next_number` and the `req/*` branches; `propose_requirement` in
    fact pushes to the base and falls back to a branch when refused, so two requirements carry the
    same number either way, and minting has to be inside the lock.
  - Also taken from the review: no names across conversations, the acknowledgement included; the
    role does not see spend; group context stored and searchable but never prompted; a workspace
    per turn; atomic JSON stores; a concurrency cap; saving at confirmation as the rule, with
    staged drafts in the duplicate check; the `hash(text)` defect restated as a per-process
    randomisation rather than a cross-process collision; a replaceable extraction interface
    (moved to #269); and the scope split into #267, #268 and #269, with slice 0 starting on one
    fixture.
- **2026-09-23 — the boundary became the product.** Asked on review what bounds the role when a
  product spans several repositories or services, the answer was that the design had been using
  the wrong unit: the boundary is the product ADR-0019 §8 already declares, keyed by its context
  repository, with the registry project kept as the factory's unit. Agreed on review, and carried
  into the semaphore, slices 3 and 4, #267 and #269.
- **2026-09-23 — this record,** written from #266 as revised; design only.
- **2026-09-24 — the record reviewed, and accepted.** A review of this record against the code
  found it contradicting itself in two places, and both were settled here:
  - **The re-check left the lock.** As first written, what arrived after the turn's write sequence
    was checked again inside the lock, which is the same judgement D8 keeps out of it. The lock now
    compares the sequence and writes; a moved sequence sends the turn out to judge what arrived and
    back to ask again, a bounded number of times (D7, D8).
  - **The partition of memory is this record's.** It had left ADR-0024 untouched while keying memory
    by product; it now amends ADR-0024 §1, with a dated note there, and says what happens to the
    deletion path and to retention. Only ADR-0024 §5 is left to ADR-0053.
  - Also settled: only a saved record stops a write, and a staged twin is linked to what the first
    confirmation wrote (D9); the requester of a cross-conversation match is not named even when the
    record names them (D5, D9); `product.accept_on_behalf` is extended to the first yes (D11); the
    stores' locks are their own, not the semaphore (D11); `Message.project` is the registry project,
    resolved to its product at the door (D1); D14 is built in slice 4, with a criterion. The
    product owner then accepted the design with the review's recommendations, slice 0 first.
