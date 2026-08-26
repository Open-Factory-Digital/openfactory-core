# ADR 0024 — Conversational memory: the thread is the unit, the raw log is sacred

- **Status:** Proposed
- **Date:** 2026-07-29
- **Related:** ADR-0021 (operational memory — the open loop), ADR-0019 (the requirements repo, which
  is already the facts layer), ADR-0023 (measure before caching — the same method applied here to
  RAG).

## Context

The product owner, 2026-07-29, bringing a reference document about agent memory: *"if our premise is
agents that genuinely replace a PO/BA/PM and a tech lead, then memory has to be something very, very
well structured."*

The premise is the point. A PO who does not remember the previous sentence is not a bad PO — it is
something else entirely.

### What today's audit found

The document proposes four layers with distinct life cycles. Mapped against what exists:

| layer | what it is | do we have it? | where |
|---|---|---|---|
| **0 — raw log** | every message, verbatim | ❌ **does not exist** | — |
| **1 — working memory** | the thread in progress | ❌ **does not exist** | — |
| **2 — durable facts** | what is known about the business | ✅ partial | documentation repo |
| **3 — episodic** | what happened before | ✅ partial | loop ledger (ADR-0021) |

Both absences were verified in the code, not inferred:

- `product_channel.py:215` calls `module.answer(text)` — **one argument**. The `context` parameter
  falls to its default, which is `_corpus_note()` (corpus errors and nothing else).
- `ProductModule` is constructed **fresh on every message**, deliberately.
- `_PENDING` holds **one** proposal per thread awaiting a "yes" — that is confirmation staging, not
  history.
- No harness adapter receives a session to resume on the conversational path.

**Conclusion: for the product agent, every message is turn 1.** She cannot answer *"and the second
one?"*, does not know she asked a question when the answer arrives, and cannot correct herself. This
is not graceful degradation: it is the absence of the most basic of the four layers.

### What that costs, measured

The `openfactory-job-metrics` table records `cost_usd` per agent run — one executor ticket cost
**US$10.69**. Sweeping 500 rows: `agent_run` has the roles `executor` (48) and `repair` (1).

**Conversational turns recorded for the product agent: zero.**

So: every message of hers fires an agent that opens two repositories from scratch — because it has
nowhere to remember from — and **none of it is measured**. Two product claims lose their backing at
once: *"token efficient"* (the most expensive possible way of not remembering) and *"replaces the
team"* (an amnesiac PO replaces nobody).

### Where we are already ahead of the document

Worth recording, because copying the document wholesale would be a regression in two places.

**1. Layer 3 has outcomes, not just recall.** The document models episodic memory as *"what happened,
retrievable"*. ADR-0021 models *"what I tried, and whether it worked"* — closed by **observation**,
never by self-report. `hopeless()` falls out of that: a remedy that failed twice with no success
stops being offered. That is **policy derived from memory**, a step beyond retrieval, and the
document does not go there.

**2. Layer 2 has a better home than a table.** The document suggests `user_memory(user_id, key,
value)`. Our facts live in the **documentation repository** (ADR-0019): versioned, reviewed by PR,
readable by the client, with real provenance. A table would be worse on all of those dimensions. Do
not migrate.

### And where layer 2 is wrong today

`note_fact` refuses when the term already exists — it returns what is written and stores nothing. The
document lists four possible verdicts in a conflict (replace / merge / keep both / ignore) and **we
have "ignore" in the code, permanently**. The consequence: a client who changes ERP cannot update
their own fact. Memory that cannot learn a correction is not conservative, it is broken — it just
fails on the quiet side.

## Decision

Five decisions, in the order they should be made.

### 1. Layer 0 — the raw log, in the table that already exists

Every channel message, verbatim, as `kind="message"` in `openfactory-job-metrics` (already
append-only, with a `kind` discriminator and a `by_kind` GSI — ADR-0021 built exactly that
substrate). Fields: `project, channel, thread, ts, actor, role, text`.

This **is not memory** — it is the record every memory is derived from. Write it always, even if
nothing reads it today. Three reasons, all ours:

- it is the only layer the others can be **rebuilt** from when the strategy changes;
- it answers the question we cannot answer today: *"why did she say that?"*;
- it is a real client's conversation, so **retention and deletion from day one** — partitioned by
  `project`, which is our natural client boundary.

> Derived is disposable; raw is sacred.

### 2. Layer 1 — the unit is the **thread**, not the channel

Slack already gives us the right boundary: a thread is a conversation. Read the last N turns of that
thread from layer 0 and render them into the prompt.

Three disciplines, each with a stated reason:

- **A budget in tokens, not in number of messages.** A message can be 5 or 5,000 characters.
- **The block goes LAST.** Prompt caching works by prefix: what changes invalidates what follows.
  Static (role, rules) → semi-static (facts) → volatile (the conversation). There is no cache gain to
  lose today; when there is, the order will already be right.
- **Recent turns verbatim, no summary.** Summarising the last turns is what makes an agent sound
  "politely amnesiac" — it needs the exact phrasing to keep the thread.

### 3. Layer 2 — stays in the repo; the update path gets fixed

A factual conflict stops being a refusal and becomes **a decision by whoever knows**: the agent shows
what is written, what was just said, and asks which one holds — with "keep both, they are different
things" among the options.

That is the reconciliation step the document calls essential, with a deliberate difference: **the
human reconciles, not the LLM.** It is the same rule as the rest of the factory (the human decides,
the factory executes) and it produces provenance an automatic merge does not.

### 4. Layer 3 — the loops we have, plus a per-thread summary

The ledger covers commitments (*"I asked this and I am waiting"*). What is missing is the plain
episodic (*"in that conversation we decided X"*).

One summary per closed thread, written by the **sweep that already exists** (`_product_followup`
already runs periodically and already knows what is live). Inject the N most recent for that channel.

**Search comes later, and as a tool** — a `search_conversations(query)` the agent calls when it needs
it, never top-k attached automatically. It only costs when used, the query is formulated by whoever
knows what they are looking for, and it stays inspectable.

### 5. RAG: **no**, and the trigger to revisit is written down

By the document's own criterion, the trigger is not "has long memory" — it is **volume**: does the
distillate fit in the prompt?

Our scope is narrow by construction: **one project, one channel**. At 30 threads/month, a year is
~360 summaries. It fits. And there is a natural metadata filter before any similarity — which is
precisely what the document says separates useful RAG from RAG that returns rubbish with high
confidence.

It is ADR-0023's method: **measure before building the machine**. Revisit when a channel's summaries
exceed ~1,500 injected tokens, and then start with **lexical search**, not vector.

## Consequences

**Good.** The agent becomes capable of the things that define the role: following a line of
reasoning, receiving a correction, knowing that it asked. The raw log makes every future decision
reversible. And her turns get a measured cost — today they are zero rows, which means we do not know
what a conversation costs.

**Costs and risks, declared.**

- **Every turn gets bigger.** That is the real cost: injected history is paid for on every turn. The
  bet is that it **replaces** repository exploration — today she re-reads files because she does not
  remember. That has to be **measured**, not assumed: without decision 5's `agent_run` rows,
  "it improved" is a belief.
- **A client's conversation becomes persisted data.** Retention, partitioning and a deletion path go
  in with it, not afterwards.
- **A summary is a reading, and readings are wrong sometimes.** Which is why recent turns are not
  summarised, and a summary never becomes a fact or a requirement — ADR-0019's boundary
  (`observed` ≠ `accepted`) holds here too.
- **Two memories, and they may not merge.** ADR-0021's loop is a commitment with an outcome; a
  message is what was said. A sentence is not a commitment, and a commitment is not a sentence.
  Mixing them would produce a factory that believes itself responsible for everything anyone
  mentioned.

## Audit of 2026-07-29 — two holes in the first implementation, and why the approach stands

Audited the same day, with the question "is the approach the best one?". Two real holes, both in the
**conversation key**, none in the architecture:

1. **Memory never activated in real use.** The listener used `thread_ts or ts`: correct inside a
   thread, but the fallback for a standalone message is *its own* ts — so every standalone message
   was a new conversation, and the client talks to the agent in standalone messages. Ten green tests
   with a fixed thread hid it: the 14th instance of the signature defect, this time in the tests of
   the fix itself. The same hole, latent, in confirmation staging: a standalone "yes" never found the
   proposal from two messages earlier.
2. **Her proactive messages were not recorded.** The sweep posted through a bare `channel.say` — a
   question, a chase, a delivery, none of it entered layer 0. The person answered her question and
   the conversation's first turn (*her* question) was the only one memory did not have.

Fix: `conversation_key` — a standalone message belongs to the **channel's** rolling conversation; a
threaded message belongs to the thread; `recent()` reads the union of both; the sweep records what it
posts (`_product_post`); confirmation looks for and consumes on both keys. Tests now key the way the
listener keys, and both fixes are sabotaged individually.

**The approach holds up against the alternatives.** A harness session (`--resume` per conversation)
would give multi-turn "for free", and was refused as a foundation: it couples to the harness (we were
born claude/codex/kimi — ADR-0018), dies on a worker restart, and is neither auditable nor
reconstructible — a checkpointer does not replace layer 0 (§6 of the reference document). It can come
later as a per-harness optimisation, *on top of* the transcript, which remains the source. What was
wrong was not the architecture; it was the conversation's identity.

## Migration

1. **Layer 0**, writing and read by nobody. Cheap, and it is what makes the rest reconstructible.
2. **Layer 1** on the conversational path, with a configurable budget and the block last.
3. **Measure** — product turns with `agent_run` and cost. Without that, step 2 is a belief.
4. **Layer 2**: a conflict becomes a question.
5. **Layer 3**: a per-thread summary on the existing sweep.
6. **Only then** re-evaluate search, starting with lexical, at the threshold written above.
