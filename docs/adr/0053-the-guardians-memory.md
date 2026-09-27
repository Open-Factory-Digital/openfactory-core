# ADR 0053 — The guardian's memory: raw, evidence and curated truth, with time as data

- **Status:** **Proposed** (design only) — written from #269 as it was agreed on review. No code
  changes with this ADR.
- **Date:** 2026-09-24
- **Relates to:** ADR-0017 and ADR-0023 (the knowledge layer, derived and verifiable —
  `docs/knowledge-layer.md` §7, the code is the ground truth, and §10, deterministic-first, which
  D2 applies to documents), ADR-0019 (the context repository is the product's record — §8, the
  product this record keys memory by; §10, a map over the documents "later, on the Knowledge
  Layer's machinery", which D1's evidence layer builds for every document, not only the
  requirements), ADR-0021 (the open loop — the decisions the role asked for, which D7 reads whether
  open or answered), ADR-0022 and ADR-0034 (provider seams and entry points — extraction and
  embeddings are axes, D2 and D9), ADR-0024 (conversational
  memory — **this record revises §5**, by the trigger §5 wrote, and with it §4's summary and search,
  in dated notes there; §1's retention is set per client, D6), ADR-0040 (the core runs on the
  client's machines — the index is local, D9), ADR-0041 (facts are files, and unreadable is not
  absence — D8, D11), ADR-0042 (an input nobody read is reported as unread; `observed` becomes
  `accepted` only by a person — D11, D14), ADR-0049 (`local` is a kind — what Git LFS means there
  is left open), ADR-0051 (D2's product, D5's rule on names, D7–D9's semaphore, write sequence and
  anonymity, D10's save at confirmation, D14's addressing; decisions 3, 8 and 12–16, which this
  record carries), ADR-0052 (D7's events through the door, D10's registers, D11's "a new document
  ingested", D15's knowledge-source axis, D17's system layer, which the curated truth includes).
  Issues: #269 — this record; #266 (what it depends on — slice 3's door, product key and semaphore;
  slice 0's battery, which gains the years-old fixture here); #267 and #268 (ADR-0052).

## Context

The context repository is a document repository. It holds the OKF and what the platform writes —
the requirements, the glossary, the onboarding's documents — and whatever people put there:
diagrams, charts, PDFs, e-mails, meeting notes, specifications, years of them. The product role is
meant to be the guardian of the product: it has seen everything that went through it, and when
somebody asks, years later, for something that was already done, it says so and says where. That
has to hold for a two-week project and for a product with years of documents.

What follows was read at `main` (`0f8314c`) and at the head of #267's first slice (`70fc8f4`,
`feat/267-the-read-model`, which carries #266's stack through its slice 6). Code is cited by name,
because most of it sits at different lines in the two trees. What is marked *(#266)* is in #266's
stack only, and *(#267)* in #267's first slice only, as that branch carries them.

### The role forgets by construction

- Conversation rows expire after `RETENTION_DAYS` = 180 (`memory/transcript.py`), one constant for
  every deployment.
- A turn's history is rebuilt from the newest `SCAN_ROWS` = 300 rows of the partition
  (`transcript.recent`).
- ADR-0024 §4's summary per closed thread is not built: nothing in `openfactory/memory/` or in the
  sweep's follow-through (`product/followup.py`) writes one. ADR-0024 is still *Proposed*.
- Nothing distils a conversation into the context repository. Of a conversation, what outlives the
  180 days is what a confirmation wrote — a requirement, a decision row, a fact, a card — and the
  ledger's loops, which carry no expiry.

### A lexical search exists, over conversations only

- `memory/recall.py` keeps an inverted index over the transcript and the factory's channel
  messages, persisted as `recall-index.json` per registry project (`paths.project_memory_dir`). It
  is derived — deleted, it is rebuilt from the stores — and it forgets what they forget. A hit from
  a private conversation comes back only to that conversation's person.
- It is read two ways: by the explicit recall, `product_recall`
  (`actions/catalog.py::_product_recall`), and by a block attached to a turn's prompt, *what was
  said about this elsewhere* (`_with_elsewhere`). On `main` the worker's two turn paths attach it
  (`_product_draft` and `_product_conversation`, `runtime/temporal/activities.py`); in the stack
  every turn of the one engine does, and the block names nobody (`product/engine.py` *(#266)*).
- In the stack, a line said in a group to somebody else is indexed and marked, found by the
  explicit recall, and left out of that block (`recall.recall`, `overheard=False` by default;
  `product/addressing.py` *(#266)*).

So ADR-0024 §5's "start with lexical search" has happened for conversations, since #33 — in the
shape §4 ruled out: the top hits attached to the turn, automatically.

### "Was this asked before?" reads three places, and one of them is a window

`product/asked.py::already_asked` is a token-overlap read with no model, returning at most `LIMIT`
= 3 matches from:

- the board as `ProductModule._board_cards()` hands it: the 300 most recently updated cards
  (`product/board.py::_LIMIT`). The sweep now keeps the whole board and the read model asks for all
  of it; this caller still gets the window *(#267)*;
- the whole requirement corpus — superseded and dropped requirements included, a superseded one
  marked with its successor;
- the ledger's decision loops that are still open (`waiting(…, kind=DECISION)`).

It never reads a closed card outside the window, a decision already answered, a document or a
conversation. In the stack the per-product semaphore makes the check and the write one step: inside
it, only what the write log holds after the turn's sequence is compared
(`product/semaphore.py::check_and_write` *(#266)*). What the turn reads before the lock is still
`already_asked`'s three places.

### The context repository is read with grep

- The role reads its workspace — the context repository and a source, composed by
  `product/workspace.py::compose` — through a read-only harness; on Claude Code that is `Read`,
  `Grep` and `Glob` (`adapters/agent/claude_code.py::_READONLY_TOOLS`).
- That works for markdown and code. Grep finds nothing inside a PDF or an image; whether a harness
  can open one at all is that harness's feature, which ADR-0041 does not count as the platform's;
  and no model reads thousands of files on a turn.
- Nothing in `openfactory/` extracts text from a PDF, runs OCR, parses an e-mail, computes an
  embedding, uses SQLite's full-text search or knows Git LFS; the one search index is the recall
  index above. The panel has no upload — its forms are read urlencoded
  (`api/app.py::_form_fields`) — and the stack's `Message` has no attachment
  (`product/engine.py::Message` *(#266)*).

### Supersession is data for requirements, and for nothing else

- A requirement carries `date`, `supersedes` and `superseded_by` (`product/corpus.py::Requirement`).
  `superseded` and `dropped` are statuses it keeps, not deletions; `is_live` is false for both, and
  the prompt's index leaves both out unless the question is about history
  (`product/role.py::requirement_index`).
- A decision recorded in a requirement's register is a row of day, decision and who
  (`product/authoring.py::add_decision_row`). Nothing says which earlier decision it replaces.
- A requirement read off the code, `observed`, becomes a promise only when a person accepts it
  (`Requirement.is_promise`; ADR-0042).

### What the owner does instead

A person remembers. The role answers from the last months of conversation and from what grep finds.

## Decision

**Three layers: a raw record that is never lost, evidence derived from it that can be rebuilt at
any time, and a small curated truth that only a person promotes into. Documents are read
deterministically first, once per version, behind an interface that can be replaced. Time and
supersession are data. The engine retrieves and the role reads files. One architecture, local by
default, from a two-week project to a product of years.**

```
┌─ RAW (never lost, versioned) ──────────────────────────────────────────────────┐
│ context repo: documents, diagrams, e-mails, notes, PDFs, the OKF, distillates  │
│ + everything through the role: conversations, tickets, PRs, deliveries         │
└──────────────┬─────────────────────────────────────────────────────────────────┘
               ▼  incremental ingestion, one file per event (D2, D13)
┌─ EVIDENCE (derived, rebuildable at any time) ──────────────────────────────────┐
│ each document → normalised text + a record: date, authors, type, area,         │
│   audience, entities, requirements/cards cited, decisions mentioned, summary   │
│ hybrid index: metadata filters → lexical → semantic → re-rank;                 │
│   every hit carries its citation (D9)                                          │
└──────────────┬─────────────────────────────────────────────────────────────────┘
               ▼  the role proposes, a person confirms (observed ≠ accepted, D14)
┌─ CURATED TRUTH (small, always within reach) ───────────────────────────────────┐
│ requirements, decisions with their date and what they supersede, glossary,     │
│ system map (ADR-0052 D17), the product's timeline                              │
└────────────────────────────────────────────────────────────────────────────────┘
```

### D1 — Three layers: raw, evidence, curated truth

- **Raw** is never lost and is versioned: the context repository — its documents, diagrams,
  e-mails, notes, PDFs, the OKF, what the platform writes — and everything that went through the
  role: conversations (ADR-0024's layer 0), tickets, pull requests, deliveries.
- **Evidence** is derived from the raw and can be rebuilt from it at any time: each document's
  normalised text and its record (D2), and the index over them and over the conversations (D9).
  Every hit carries its citation.
- **Curated truth** is small and always within reach: the requirements, the decisions with their
  date and what they supersede, the glossary, the system map (ADR-0052 D17), the product's
  timeline. It lives in the context repository, where ADR-0019 put the product's record, and only
  a person promotes into it (D14).

A distillate (D4) is a file in the context repository, so it is raw: nothing derives it again.
What it says is a reading, and is cited as evidence.

*Why:* ADR-0024's rule — *derived is disposable; raw is sacred* — one layer wider. Evidence that can
be rebuilt can be read again when an extractor improves; truth that only a person promotes cannot
rot into the "confident fiction" ADR-0019 warns a corpus becomes.

### D2 — Deterministic-first ingestion, once per file version, behind a replaceable interface

- Text, markdown, mermaid, drawio and `.eml` are parsed without a model.
- A PDF's text is extracted, with OCR when the PDF is scanned.
- A diagram or chart image is described by a vision model, **once per file version**.
- The record — summary, decisions mentioned, entities, requirements and cards cited — is also
  generated once per file version, **never per question**. A file version is its content, so a
  file moved or renamed is not read again.
- The record says how each part was read — parsed, extracted, recognised by OCR, described from an
  image — and by which extractor.
- **Extraction goes through a replaceable interface**, of the same kind as embeddings (D9): a
  provider axis in ADR-0022's sense — a registry, `kind → builder`, an unknown kind raising — with
  ADR-0034's entry points for a row added outside the core. A lighter or specialised OCR or vision
  model is then configuration, not a redesign.

*Why:* `docs/knowledge-layer.md` §10 — generation runs often, so it must be cheap and reliable, and
a model reads only the fuzzy slice. Reading a product's documents per question is the cost ADR-0019
§10 refused for requirements alone. And which OCR or vision model is best changes faster than this
design: the reviewer's point on #266 was that the interface must outlive the choice.

### D3 — Time is data, and supersession is a relation

- Every item of evidence carries a date and a source. Its date is the date of what it says — an
  e-mail's header, the minutes' own date — where the document states one, and otherwise the commit
  that brought it in; the record says which.
- Every extracted decision has a date, a source and a *supersedes / superseded by* relation. In the
  evidence a relation is a reading, with its citation — the later document that says so. In the
  curated truth it is confirmed, as a requirement's `superseded-by` already is.
- Retrieval never hands over a superseded item as current. A superseded hit comes with what
  superseded it, and "what holds today about X?" is answered with the latest — as
  `requirement_index` already leaves superseded requirements out unless the question is about
  history.
- The role answers with the timeline: *"In 2021 X was decided (e-mail of …). In 2023 it became Y
  (minutes of 12 March, requirement 41). Y holds."*

*Why:* retrieval by similarity alone brings back a 2021 decision reversed in 2023 with the same
confidence as its reversal. A guardian that cites the superseded decision is worse than one that
says it does not know (*What would make it wrong*).

### D4 — Saved when confirmed; distilled as the catch-all

- A requirement, a decision, a ticket or a fact is written the moment it is confirmed — ADR-0051
  D10's rule, which this record takes as given. Conversations run side by side (ADR-0051 D3), so
  the saved record is the only way one of them learns what another decided.
- When a conversation ends, what was agreed, asked or decided in it and that no confirmation
  captured is distilled into the context repository: permanent, versioned, and cited with its date
  and where it came from.
- A distillate is a reading, and readings are wrong sometimes (ADR-0024, *Consequences*). The role
  cites it; it never becomes a requirement or a decision except by D14.
- What a confirmation already saved is not distilled a second time.

*Why:* a distillation at the end of a conversation is too late for the conversation running beside
it; a confirmation is not. And a conversation holds what no confirmation caught — an option
refused, a preference, a question left open — which a permanent distillate keeps after the raw rows
are gone (D6).

### D5 — Memory is partitioned by product

- Every layer is keyed by the product ADR-0051 D2 declares — its authorised context repository —
  and never by the registry project: the index, the distillates, the curated truth and the
  "done before?" check (D7).
- The curated truth and the distillates live in the product's context repository already. The index
  is built per product. The stack keys the transcript by product and reads its members' old
  partitions through (`memory/transcript.py::partition` *(#266)*); the recall index is kept per
  registry project in both trees (`paths.project_memory_dir`), and joins the product's index.
- No row, hit or document crosses from one product to another.

*Why:* decision 1 — every repository of one product shares one memory. A product with two registry
projects and two indexes would answer "was this done?" from half of itself.

### D6 — Retention per client; the distillate is permanent

- The raw conversation's retention is set per client. The default is unchanged: `RETENTION_DAYS`,
  180 days.
- The distillate is permanent in the context repository (decision 12).
- Evidence derived from a conversation forgets what the conversation forgets. When a row expires or
  is deleted (`openfactory project forget-conversations`), what the index holds of it goes too — as
  the recall index already forgets what its stores forget.
- A document in the context repository is kept as the repository keeps it; the retention of
  conversations does not apply to it.

*Why:* this is how "never forgets" coexists with deleting personal data. What the product needs to
remember is distilled into its repository; what a person said, word for word, is kept as long as
the client decides.

### D7 — "Done before?" reaches the whole memory, and the search stays outside the semaphore

- The duplicate check that ADR-0051 D7–D9 made part of the per-product semaphore reads, besides
  saved requirements, decisions, tickets and staged drafts: live, **dropped and superseded**
  requirements; cards of any age, closed ones included; decisions whether open or answered;
  documents; and distilled conversations.
- The search, and the model's judgement over it, happen **before** the lock. Inside it only the
  write log's items after the turn's sequence are compared (ADR-0051 D8). This record adds nothing
  under the lock.
- What is found in another conversation, in a distillate or in a document is referred to by what it
  is — "this was asked for in March 2024 and dropped; it is requirement 17" — never by who asked
  (ADR-0051 D5, D9).

*Why:* the guardian's first question is whether the thing was already done, or already refused.
Today's check reads a window of 300 cards and the decisions still open. Widening what it reads
leaves the lock exactly as short as ADR-0051 made it, because the reading is not in the lock.

### D8 — The engine retrieves; the role reads files; `[[BUSCA: …]]` asks for more

- **Before the turn,** the engine searches from the message and the conversation, and writes the
  hits, each with its citation, as files in the role's facts pack — beside `board.md`, `loops.md`
  and `decisions.md` (`product/facts.py::FILES`) — with the manifest naming every file and every
  gap (ADR-0041).
- **When the role needs more,** it asks through a marker, `[[BUSCA: <what to look for>]]`, in the
  family of `[[DECISAO: …]]` (`product/role.py`). The engine searches, writes the hits as files,
  and the turn continues. The marker never reaches the person.
- **Every search is recorded:** who formulated it — the engine or the role — the query and the hits.
- The recall block of #33 (`_with_elsewhere`) is this retrieval's first form, over conversations
  only. It becomes part of it and keeps its two rules: a private conversation's hit goes only to its
  person, and nobody is named.
- The searches of a turn stay within the turn's bound (ADR-0051 D6).

*Why:* a marker works on every harness, because it is text the model writes, as every other
declaration it makes already is — no tool protocol (ADR-0041). The engine's search before the turn
spares a round for the obvious; the marker is the search "formulated by whoever knows what they are
looking for" that ADR-0024 §4 asked for. A recorded search makes a wrong answer traceable to what
was found.

### D9 — Small and huge, one architecture, on the client's machine

- In a small product the curated truth fits the prompt and retrieval is barely used. In a large one
  the curated truth sits on top and the evidence comes in by search. One code path for both.
- The index is hybrid: **metadata filters** (product, audience, date, type, area) → **lexical** →
  **semantic** → **re-rank**. Every hit carries its citation. Lexical comes before semantic:
  *requirement 41*, *card #512* and a client's name are what embeddings miss and lexical search
  finds.
- It runs on the client's machine (ADR-0040): SQLite's full-text search and a vector extension in
  the same database. No cloud vector database.
- **Embeddings go through an adapter.** A local model is the default; an external API is used only
  when the client turns it on (decision 14). With none turned on, no text leaves the machine to be
  embedded.

*Why:* ADR-0024 §5's order holds — lexical before vector, and a metadata filter before any
similarity, which is what separates useful retrieval from retrieval that returns rubbish with
confidence. Whatever circulates runs on the client's machine (ADR-0040 D2); a cloud vector
database would be the first thing in the core that needs a cloud. And two architectures, one for
the small and one for the huge, is how the small one ends up the only one that works (ADR-0052
D14).

### D10 — Visibility per document

- Every document carries an audience label — client, product admin, engineer (decision 8) —
  recorded with it at ingestion.
- The label is a metadata filter, applied **before** ranking: a hit the conversation may not read is
  never a hit. An internal e-mail never surfaces in an answer to a client.
- The filter is the conversation's. In a room everyone in it reads the reply (ADR-0052 D10), so a
  hit there is one that every reader of the room may see; a private conversation is filtered for its
  person.
- A private conversation keeps its own rule: what it holds comes back only to its person, as
  `memory/recall.py` already does.

*Why:* the role knows more than some of the people it talks to may open (ADR-0052,
*Consequences*), and a disclosure through retrieval is a disclosure. A filter applied after ranking
leaks through the answer built from the hits; one applied before it has nothing to leak.

### D11 — Never silent

- A file that cannot be read — a protected PDF, an unknown format, an illegible image — is shown on
  the panel as unreadable, with the reason.
- The role knows that it exists and could not be read: it is a gap in the manifest (ADR-0041), and
  asked about it, the role says so.
- "Could not read" never becomes "nothing there" (ADR-0042: an input nobody read is reported as
  unread, never as an absence of findings).

*Why:* a guardian that passes over what it cannot read, and answers as if it had read everything,
gives confidence exactly where none is due.

### D12 — Group context is searchable, never prompted

- What was said in a group without being addressed to the role (ADR-0051 D14, decision 3) is indexed
  like any conversation, and marked as not addressed (`transcript.ADDRESSED_MARK` *(#266)*).
- The engine's search before a turn leaves it out, as the stack's recall block does. It is reached
  only by a search somebody asks for — a person's explicit recall, or the role's `[[BUSCA: …]]` —
  and then as cited hits, never as the room's transcript.
- It is never added to a turn's prompt wholesale.

*Why:* a room's chatter in every prompt costs the tokens ADR-0051 D3 saves by keeping conversations
apart; and what the room said is still the product's, and must be findable.

### D13 — How documents arrive

- **Upload from the panel first.** The panel commits the file to the context repository, so an
  upload is a commit like any other.
- **A commit always works,** with no panel involved.
- **Connectors** — mail, wiki, drive — are add-ons, on ADR-0052 D15's knowledge-source axis.
- **Large files go through Git LFS by default,** with object storage as an adapter (decision 13).
  Either way the repository holds the file or its pointer, so the raw layer stays the repository.
- An arrival is an event through the door (ADR-0052 D7), which ingests that one file; "a new
  document ingested" is one of the events ADR-0052 D11 tells a person.

*Why:* the context repository is the product's record (ADR-0019), and a document kept anywhere else
is a second record. Upload comes first because the panel is the reference surface (ADR-0038 D1),
and a client who holds a contract should not need git to hand it over.

### D14 — Evidence is not truth until a person confirms it

- A document's content is cited: *"according to the PDF 'SLA contract v3', March 2024, page 4 …"*.
- It becomes curated truth — a requirement, a decision, a glossary entry — only when a person
  confirms it (decision 15). The role proposes the promotion; the confirmation is the one every
  write of the record takes, and the write passes the product's semaphore (ADR-0051 D7).
- It is the line the corpus already draws between `observed` and `accepted` (ADR-0042), drawn for
  every document.

*Why:* a document says what somebody wrote, on a day; the product's truth is what a person with the
authority to agree it agreed. Text recognised by OCR, and numbers read off a chart's pixels, can be
wrong in ways a person notices and an index does not.

### How each decision is held

Each decision is a behaviour a test can observe; the slices' acceptance criteria are drawn from
these.

- **D1:** the evidence, deleted, is rebuilt from the raw with the same entries; no curated entry
  exists without a recorded confirmation.
- **D2:** text, markdown and `.eml` are ingested with no model call; a file version ingested twice
  calls no model the second time; replacing the extraction row changes no other code.
- **D3:** on the years-old fixture, "what holds today about X?" returns the superseding decision,
  never the superseded one.
- **D4:** a decision confirmed in one conversation is found from another before the first one
  ends; a conversation that ends on an agreement nobody confirmed leaves a dated distillate in the
  context repository.
- **D5:** two registry projects of one product search one index and find each other's documents
  and conversations; no search returns another product's item.
- **D6:** a retention set for one client expires that client's rows at its age and leaves
  another's at the default; once a conversation is forgotten, no search returns any of its words.
- **D7:** "was this asked before?" finds a request dropped two years earlier; no search runs while
  the semaphore is held.
- **D8:** a turn in which the role writes `[[BUSCA: x]]` continues with the hits for x as files,
  and the reply carries no marker; every search leaves a record with its hits.
- **D9:** the index builds and answers with every cloud SDK blocked, ADR-0040 D4's method; with no
  external embedding turned on, no embedding request leaves the machine; the one-source fixture
  and the years-old fixture run the same code.
- **D10:** an internal-only document never appears in an answer to a client, in a private
  conversation or in a room.
- **D11:** an unreadable PDF is on the panel as unreadable, and asked about it, the role says it
  exists and could not be read.
- **D12:** an unaddressed line is found by a search for it, and is in no prompt and no facts file
  that no search asked for.
- **D13:** a file committed to the context repository is ingested with no panel involved; an
  upload from the panel lands as a commit and is ingested; a large file is stored through LFS by
  default.
- **D14:** an answer that rests on a document cites it as a document, never as the product's
  decision, until a person has confirmed it.

## What happens when someone drops a PDF or a chart into the context repository

- It is stored as it is — a commit, or an upload that becomes one; through LFS when it is large —
  and an event ingests that file alone (D2, D13).
- It gets its record, with its date, its audience and how it was read, and enters the index. Within
  minutes the role can cite it — *"according to the PDF 'SLA contract v3', March 2024, page 4 …"* —
  or it is on the panel as unreadable, and the role says it could not read it (D11).
- A chart image is the weakest case. Its message is understood, but exact numbers read from pixels
  may be wrong, and the record says the content came from an image. The source spreadsheet put
  beside it makes the numbers exact.
- Entering the knowledge is not becoming truth. The file is evidence the role cites; it is promoted
  to curated truth only when a person confirms it (D14).

## ADR-0024 §5, revised by its own trigger

ADR-0024 §5 refused retrieval and wrote down when to revisit it: when a channel's summaries exceed
about 1,500 injected tokens — and then start with lexical search, not vector. Its criterion was
volume, *does the distillate fit in the prompt?*, over a scope that was narrow by construction: one
project, one channel, about 360 summaries a year.

- **The scope it measured is gone.** Memory is the product's (ADR-0051 D2), its conversations run
  side by side (ADR-0051 D3), and the context repository's documents — which §5 did not count — are
  part of what the role must remember. For a product of years, the answer to §5's question is no.
- **The threshold could not fire as written.** It counts summaries, and the summaries of §4 were
  never built.
- **Its prescription was followed anyway, for conversations.** The recall index of #33 is lexical;
  its top hits are attached to the turn automatically, which §4 had ruled out.

So this record revises §5 the way §5 said to: retrieval, **yes**; lexical first; a metadata filter
before any similarity; and the vector stage local, second, and measured by the battery rather than
argued. What §5 adds up to becomes three layers with time as data (D1, D3) and a hybrid index on the
client's machine (D9). §4 moves with it, in its two retrieval halves. Its summary per closed
thread, never built, becomes the distillate (D4), found by search rather than injected by recency.
Its search becomes the engine's before the turn, written as files the role opens rather than as
text in the prompt, and the role's own through the marker (D8). Both sections carry a dated note
saying so.

## What this record carries from #266

| #266 | Decision | Here |
|---|---|---|
| decision 1 | The role's boundary is the product; memory is the product's | D5 |
| decision 3 | Group context is stored and searchable, never prompted | D12 |
| decision 8 | Three audiences — client, product admin, engineer — client by default | D10 |
| decision 12 | The distillate is permanent; raw retention per client, default unchanged | D4, D6 |
| decision 13 | Large files: Git LFS by default, an adapter for object storage | D13 |
| decision 14 | Embeddings: a local model by default; an external API only when turned on | D9 |
| decision 15 | Document content is cited, and is truth only after a person confirms | D14 |
| decision 16 | Panel upload first; a commit always works; connectors are add-ons | D13 |
| the review | Saving at confirmation is the rule; the distillation is the catch-all | D4 |
| the review | The "done before?" check reads staged drafts, and is the semaphore's | D7 |
| the review | A replaceable interface for extraction, as for embeddings | D2 |
| the review | No names across conversations | D7, D8 |
| slice 0 | The evaluation battery; the years-old fixture joins it here | slice 2 |

## What would make it wrong

**Retrieval confidently wrong.** A guardian that cites a superseded decision is worse than one that
says it does not know. That is why time and supersession are data (D3), why nothing from a document
becomes truth without a person (D14) — and why **the battery's first-class metric is the
superseded-decision trap**: questions on the years-old fixture whose right answer is a decision
that reversed an earlier one, with the earlier one in the question's `must_not`, the format #281
builds. A retrieval that raises the battery's score while it fails a trap is the wrong idea in the
shape written here, and this record is the one to revise.

**Cost per turn grows.** The hits are paid for on every turn that reads them, and the marker adds
rounds. That is measured, not assumed, with #266's battery: the same questions, with and without
retrieval, recording per turn the score (correct, cited, abstained correctly), the tokens and the
files opened — the measurement ADR-0052 applies to its briefing. Retrieval that raises the tokens
per turn without raising the score, on the fixture where it should matter most, is the wrong idea.

## Not decided here

- **Choosing and tuning the OCR and vision models** — a later discussion, as the review asked. The
  interface is in scope (D2); the choice is not.
- **Knowledge-source connectors** — add-ons, on ADR-0052 D15's axis.
- **The owner's view, every source and the system layer** — ADR-0052. This record uses its events
  (D13) and counts its system map among the curated truth (D1).

## What this does NOT mean

- **Not a cloud vector database,** and not an external embedding API by default (D9).
- **Not that a document is the product's truth once it is indexed** (D14).
- **Not a tool protocol** (ADR-0041). The marker is text the role writes (D8).
- **Not that the role reads everything on every turn.** The curated truth is on top; the evidence
  comes in by search (D9).
- **Not that the raw is ever rewritten.** Evidence is rebuilt from it; the raw is not touched (D1).
- **Not a longer lock.** The search is outside the semaphore, as ADR-0051 D8 put the judgement (D7).
- **Not a room's chatter in a prompt** (D12).
- **Not a guess at what an unreadable file says** (D11).
- **Not that conversations are kept forever.** A conversation keeps its client's retention; the
  distillate is what is permanent (D6).
- **Not a vendor in the core** for any source of documents (D13).

## Slices

Each merges on its own and carries its acceptance criteria. All three depend on #266's slice 3 —
the door, the product key and the semaphore. The years-old fixture joins #266's battery (ADR-0051,
slice 0) with slice 2.

**#269, slice 1. Ingestion** (D2, D11): text, PDF, OCR, images and e-mail, behind the replaceable
extraction interface, with unreadable files reported.
*Acceptance:*
- a dropped PDF is in the index within minutes;
- an unreadable one appears on the panel as unreadable;
- a chart image's record states that its content came from an image;
- a file version ingested twice calls no model the second time.

**#269, slice 2. The hybrid index with time and supersession, and the retrieval step with its
marker** (D3, D5, D8, D9, D12).
*Acceptance:*
- on #266's years-old fixture, "what holds today about X?" returns the superseding decision, never
  the superseded one;
- the battery's record carries the superseded-decision traps, and the score, tokens and files
  opened per turn with retrieval and without;
- the index builds and answers with every cloud SDK blocked;
- two registry projects of one product search one index.

**#269, slice 3. Memory writes** (D4, D6, D7, D10, D14): save-at-confirmation as a rule,
conversation distillation, the mandatory "done before?" step including staged drafts, and
visibility labels.
*Acceptance:*
- "was this asked before?" finds a request dropped two years earlier;
- an internal-only document never appears in an answer to a client;
- a retention set for one client leaves another's at the default;
- nothing is promoted to curated truth without a person's confirmation.

## Consequences

**Good.** The role remembers the product for as long as the product exists — across every
conversation and every document — says when something was already done or already refused, and
where, and says what holds today with the history that led to it. A product of years is handled the
way a two-week project is.

**Costs and risks, declared.**

- **The backlog is read once, and it is large.** Once per file version keeps the steady state cheap,
  but the first pass over a product of years is thousands of files, and each image is a model call.
  It is paid once, and is to be measured on a real repository, not on a fixture alone.
- **A reading of an image or a scan can be wrong.** The record says how each part was read (D2), and
  nothing read becomes truth without a person (D14).
- **Every turn may pay for hits** — the measurement above.
- **A local model costs the client's machine** disk, memory and time at ingestion. That is the price
  of no text leaving it by default (D9).
- **Git LFS needs a forge that hosts it and a box that has it.** A forge without LFS is what the
  object-storage adapter is for.
- **The panel gains a write into the context repository.** Who may upload is a gate the panel's
  credential areas have to answer.
- **A label is one more thing a person sets.** A document nobody labelled is a question (*Left
  open*), and a wrong label is a disclosure or a blind spot.
- **A distillate is a reading.** It is cited with its date, as evidence, never as a decision (D4).

## Left open

- **The vector extension, the local embedding model and the re-rank** — slice 2, measured on the
  years-old fixture.
- **The rows each axis is born with.** ADR-0022: an axis is agnostic when it is born with two.
  Embeddings have the two decision 14 names; extraction's are slice 1's.
- **A document nobody labelled, who may set or change a label, and whether the audiences nest.**
  Decision 8 makes client the default audience of a person, and a document read as client-visible
  by default is the internal e-mail D10 exists to keep out — slice 3.
- **Where a client's retention is declared,** and what a client is in the registry — slice 3.
- **What ends a conversation, and what a distillate keeps of the people in it.** A conversation's
  workflow is long-lived (ADR-0051 D3). Decision 12 makes the distillate permanent and the raw
  conversation deletable, so a distillate that quoted people would keep what the retention deletes
  — slice 3, with the rule on names (ADR-0051 D5).
- **How a decision row names the decision it supersedes.** The register has a day, a decision and
  who (D3).
- **Where the index lives and how it is rebuilt** — per product under the journal root, as the
  semaphore's write log is (`product/semaphore.py` *(#266)*), or elsewhere.
- **The size over which a file goes to LFS,** what LFS means on the `local` kind (ADR-0049), and
  git-lfs in the box.
- **Which slice builds the panel's upload and the LFS default** (D13). #269's three slices name
  ingestion, the index and memory writes; a commit is enough for all three.
- **How many `[[BUSCA: …]]` rounds a turn gets** within its bound (ADR-0051 D6).
- **Whom "a new document ingested" is told to** (ADR-0052 D11).

## History

- **2026-09-22 — inside #266.** The first version of #266 carried the guardian's memory as its part
  C and its slice 9: any document in the context repository ingested, a hybrid index with time and
  supersession, and ADR-0024 §5 revisited. It distilled every conversation into the context
  repository, and its item on blind spots and the gap signal went later to #268 (ADR-0052 D21,
  D22).
- **2026-09-22/23 — the review of #266.** The reviewer asked for the swappable interface planned for
  embeddings to cover text extraction as well — PDF, OCR, image description — so lighter or
  specialised models can be added later without a redesign, and left the choice of those models to
  a later discussion. The review also made saving at confirmation the rule, with the distillation a
  catch-all; put staged drafts in the "done before?" search; and had group context stored and
  searchable, never added to the prompt. Decisions 8 to 16 were taken as recommended. The memory
  became #269.
- **2026-09-23 — the boundary became the product,** agreed on #266: memory is the product's, not a
  registry project's.
- **2026-09-24 — this record,** written from #269; design only. Two readings of the code sharpen
  #269's account of it. `already_asked` reads the whole corpus, dropped and superseded requirements
  included, so what it misses is the closed cards outside its window, the answered decisions, the
  documents and the conversations. And a lexical search over conversations already exists — the
  recall index of #33, its top hits attached to the turn — so ADR-0024 §5's "start lexical" had
  happened, in the shape its §4 ruled out. This record also revises §4's summary and search, which
  are retrieval as well, so that ADR-0024 does not say the opposite of the record that revises it.
- **2026-09-25 — everybody reads everything the product exposes.** The product owner, seeing the
  documents a client was not shown: the product role is the product's owner, and whoever talks to
  it — a co-owner, an engineer, a client — may read everything the product exposes. #266 decision
  8 had been taken on review, without the product owner's confirmation, and D10 had applied it
  to documents; for what the role reads it is replaced. Every turn reads every document, the panel
  lists every document to every credential that may read the product, and the room is told of an
  internal document as of any other. A document keeps its label as what it says of itself. What
  stays private is a person's conversation — its lines and its summary — which the product does
  not expose.
