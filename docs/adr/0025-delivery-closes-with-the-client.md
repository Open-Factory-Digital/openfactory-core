# ADR 0025 — Delivery closes with the client, not with the board

- **Status:** **Accepted** (implemented 2026-07-29)
- **Date:** 2026-07-29
- **Related:** ADR-0021 (closed by observation), ADR-0024 (conversational memory), ADR-0019 (the
  product role).

## Context

The product owner, 2026-07-29: *"looking at best practice, and at the robustness we need for the
agents to literally replace a PO/BA/PM and the tech lead — are we meeting it in full?"*

The honest answer was **no**, and the audit separated polish from what is **role-defining**. Three
things were role-defining; this ADR resolves the first and writes down the other two.

### The hole: "done" meant the board agreed with itself

`delivered()` closed the loop when **the board's issues closed**, announced, and moved on. That is
the factory agreeing with itself. It says nothing about the person who asked having received what
they wanted — and a PO whose definition of done is *"the tickets closed"* is exactly the PO nobody
wants. Selling role replacement and shipping that habit would be selling the worst of the role.

## Decision

### 1. The announcement OPENS an acceptance loop; only the client's answer closes it

A new ledger `kind`: `ACCEPTANCE`. The delivery loop still closes (so nothing is announced twice),
and alongside it the acceptance loop is born, which closes only on `worked` or `did-not-work` **in
the person's own words**. It is ADR-0021's rule — closed by observation, never by self-report —
applied where it is worth most: here the observation is the client speaking.

### 2. Silence is never acceptance

Chased **once**, after 72h (longer than an ordinary question: the person has to go and *use* the
thing before they can answer honestly), and **never closed by time**. An open acceptance loop is the
honest record of a delivery nobody confirmed, and it should stay visible.

Closing by time would turn *"nobody answered"* into *"the client accepted"* — the most expensive lie
this system could tell, because it is the one that props up a false success report.

### 3. The verdict fails to the safe side

`acceptance_verdict` reads negation **first** and requires a **short** answer in both directions:

- *"it worked but it still hangs"* → `did-not-work` (contains a positive word; a positive-first
  order would read a complaint as success);
- *"I am not sure this works well for our case because…"* → `""` (a long sentence is not a verdict);
- ambiguous → `""`, and the message continues into the normal conversation.

A loop closed by a guess is a claim of success made in the client's name.

### 4. Order in the conversation: a pending draft beats acceptance

A staged proposal is a question that has just been asked. If acceptance ran first, every confirming
*"yes"* would be swallowed — and the person would believe they had confirmed something that was
never written.

## What came with it (same pass)

- **The silence died.** An exception in the handler returned `None` — the person wrote to their own
  PO and got nothing back, indistinguishable from being ignored and invisible until they complained.
  It now answers honestly (its own sentence, **different** from "I cannot see the requirements",
  which is a different diagnosis) and logs `OPENFACTORY_PRODUCT_MUTE`, alarming on **one**
  occurrence: a client with no answer is not transient.
- **Retention and deletion.** A 180-day TTL **only** on conversation rows (`kind="message"`), via an
  `expires_at` attribute. The same table holds the agents' operational memory, which **never**
  expires — a TTL does not touch an item without the attribute, which makes this surgical rather
  than blind. Plus `openfactory project forget-conversations <project>`, because deletion is an
  obligation, not a feature.
  - A trap on record: the writer converts numbers to strings, and DynamoDB **silently ignores** a
    non-numeric TTL attribute. That would be configured retention that never deletes — a test pins
    it.
- **Recall evaluation.** 20+ hand-written cases (`tests/test_memory_recall_eval.py`). It measures the
  **retrievable** half: does the material that answers the question reach the prompt? It does not
  measure the model's judgement — saying so matters, because a suite that pretended to would be the
  dangerous artefact.

## Addendum, 2026-07-29 — the receipt, and a method error of mine

The first real conversation after the deploy: the product owner sent *"organise our backlog"* and
saw nothing. Telemetry shows **everything worked** — received 14:33, answered 14:36:03, posted with
no error, US$0.53, 21 turns, `expires_at` written as a number. It even refused to prioritise because
no requirements were written down, which is the designed behaviour.

**The defect was 2min38s of silence.** From outside, "thinking", "ignored you" and "crashed" are the
same experience. Slack's typing indicator expires in ~5s, so it is useless for a two-minute answer —
the fix is a sentence, sent **before** any work, at zero token cost. It applies to every slow path
(conversation, drafting, triage, requirement breakdown, survey) and **not** to the instant ones: a
"let me look" followed immediately by the answer is noise, and a channel that cries wolf is a
channel people mute.

The receipt does **not** go into layer 0. That layer stores what was *said*; a receipt carries no
information for auditing or for recall, and storing it would inject it into every future prompt,
teaching the agent to repeat it.

Alongside: `wall_s` on the meter. I had the cost; **how long the person waited** I had to infer from
timestamps — and a number you reconstruct is a number nobody looks at.

### The method error, recorded because it is the most repeated one

I "fixed" the receipt's ordering three times by reading the file and convincing myself it was right —
`grep -n` and `inspect.getsourcelines` showed `_on_it()` before the model call. The behaviour said
otherwise. Only a line-execution trace settled it, and the final fix was to move the receipt to
**before all the work**, verified by the observed order of events.

**Reading the code is a hypothesis; running it is the evidence.** Every time the two disagree in this
repository, the code was right and the reading was wrong — and the test that counts is the one that
observes, not the one that inspects.

## What is left pending, and why

These are **incremental** — large, useful, and none of them blocks talking to the agent today.

### 5. Forecasting: *"when will it be ready?"*

**State:** does not exist. It does not answer the question every client asks.

**What we already have:** telemetry records `wall_s` per ticket, the final `state` and the cost.
Throughput and cycle time are derivable from what is stored — **nobody computes them**.

**Proposed shape:** a percentile (p50/p85) of cycle time over the last N completed tickets, presented
as a range and never as a single date — *"items this size usually take 2 to 5 days"*. With the number
of items ahead in the queue, that becomes a queue forecast.

**The rule that may not be broken:** never promise a date. A PO who gives a date with no basis is
worse than one who says *"I do not know yet"*, and this whole platform is built on not asserting what
it cannot support.

### 6. Value, dependencies and factual conflict

- **Ordering by value.** Today it orders *"by business value"* with no value model — no deadline, no
  cost of delay, no target. It is well-formatted LLM opinion. A PO defends the order with numbers, so
  it needs business input (what waiting costs) that nobody captures today.
- **Dependencies between items.** Nothing models *"42 blocks 51"*. A PM without a dependency graph
  does not manage, they hope. Probably a field on the ticket plus a read on the board.
- **Factual conflict** (ADR-0024, step 4). `note_fact` refuses when the term already exists —
  *"ignore"*, fixed, one of four possible verdicts. A client who changes ERP does not correct their
  own fact. The fix is to show both and **ask which one holds**, with *"keep both"* among the
  options — the human reconciles, as everywhere else in the factory.
- **Code health over time (tech lead).** The reviewer judges *one diff*; nobody watches the trend —
  hotspots, recurring debt, the same module breaking. A TL who cannot see a trend only fights fires.

## Consequences

**Good.** "Delivered" starts meaning what the word means to whoever asked. Unconfirmed deliveries
stay visible instead of being counted as successes — which is uncomfortable on purpose, and is the
difference between a report and the truth.

**Costs and risks, declared.**
- **One more question per delivery.** Mitigated by chasing only once, with an explicit way out.
- **The verdict reader is lexical, not semantic.** It errs towards "not accepted", which costs one
  extra question; erring the other way would cost a falsely accepted delivery. If it errs too often
  in practice, the path is for the agent to ask back — not to loosen the lexicon.
- **Acceptance loops accumulate** if nobody answers. That is information, not litter: they are
  exactly the deliveries nobody confirmed. If the list grows, the problem belongs to the process, and
  the panel should show it.
