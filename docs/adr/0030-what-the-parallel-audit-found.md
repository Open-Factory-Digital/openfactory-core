# ADR 0030 — What the parallel audit found, and the inversion it exposed

- **Status:** **Accepted** (2026-07-30)
- **Date:** 2026-07-30
- **Related:** ADR-0028 (the read "yes"), ADR-0029 (the click), ADR-0025 (acceptance), ADR-0021
  (observation), ADR-0026 (what the client reads).

## Context

The product owner: *"do a deeper audit, no patches, fix at the root cause."* Six independent
dimensions swept the product role's surface in parallel, and every finding went through a verifier
instructed to **refute** it first. **23 candidates, 20 survived** — 4 critical, 15 high, 1 medium.

## The inversion that organises all of it

| gate | input | consequence | reversible? |
|---|---|---|---|
| markers (`[[DECISION]]`, `[[DEFECT]]`) | **a declaration** | opens a defect, records a decision | yes |
| intents | prose | picks a capability | yes |
| acceptance | prose | **declares the client signed off** | no |
| confirmation | prose | **writes in somebody's name** | no |

**Consequence and evidence were inverted.** The two irreversible decisions read prose; the
reversible ones received an explicit declaration. ADR-0029 fixed both (a click, and model reading
where there is no click).

## The four critical findings

### 1. Closed ≠ delivered

`_closed_issue_numbers` read `state != "open"`, so an issue closed as a **duplicate** or as
**not_planned** counted as a delivery, and the client heard *"what was asked for in requirement N is
ready"* about **cancelled** work. Eleven cards were closed as `not_planned` on 29/07 in one sitting:
one sweep away.

The board now fetches `stateReason`, and `not_planned` is excluded **by name** rather than requiring
`completed` — a tracker that omits the field keeps announcing real deliveries. Trading a false
delivery for a **lost** one would be the worse bargain: a delivery nobody announces is work the
client never knew existed.

### 2. Any message closed every decision

`close_decisions_answered` ran on **every** message, resting on *"a partial answer is safe because
she re-asks what is missing"*. That only holds if she **reads** the message — and the intent
shortcuts (`status`, `triage`) answer from data in hand and never reach the model. A `"status"`
closed three chased decisions as `answered` and nobody would ever ask again.

Now it runs only on the conversational path, the only one she reads.

### 3. A new proposal silently evicted another

`_PENDING` holds one entry per conversation, last one wins — that is the design. **Announcing** it
was not: only the fact and defect sites warned. A requirement draft or a queue proposal would throw
away a pending defect in silence: the client had heard *"I will record this as a problem"*, nobody
contradicted it, and the next *"yes"* recorded something else.

Two callers out of four learning the lesson is the shape this codebase has already paid for
(`final_text`, `BoundedDict`). The warning moved **inside** `remember()`, which returns it — and an
AST guard fails when any caller discards the return value. Alongside: the cap evicted a stranger's
proposal even when **replacing** an existing key.

### 4. A post with a button read as an intent that failed

`None` already meant *"I could not answer, fall through to the conversation"*, and I overloaded it to
mean *"I already posted"*. A proposal posted with buttons **also** reached the model: the client saw
the buttons plus a stray answer, and we paid for it. Fixed with `Posted(str)` — it **is** the text
(for the transcript) and is **truthy even when empty**.

## The high findings that were fixed

- **`claims_a_write` could not see the platform's own success sentence.** Built from a list I
  invented, it missed *"Noted"* — the exact word `fact_noted` uses when the write really happens —
  plus *"Queued it"* and *"Filed it"*. The agent echoing the platform's own confirmation was the most
  likely false claim of all. Coverage became **derived**: a test requires every real success sentence
  to be detected.
- **Filed work never reached a column.** `board=None` by default in `file_issues`, `file_defect` and
  `break_down`; every placement behind `if board is not None`; `board=` passed **only by tests**. So
  `FILING_COLUMN = "Backlog"` was unreachable, and a card with no column is invisible to `readiness`
  and `propose_queue` — the agent would never surface it again, while the answer asserted *"They are
  in the Backlog"*. An optional argument only tests pass is the definition of dead code: the default
  became the real board, with an `_UNSET` sentinel so `None` still means *"do not place it"* —
  `None` alone had to express both things.
- **Two deliveries waiting: she closed the most recent without saying which.** A comment in the code
  promised to name it and the code never did. It names it now **when there is ambiguity** — with only
  one open it would be noise.
- **Raw diagnostics reached the client.** `WriteResult.detail` serves the team's log **and** the
  channel, the "two facts in one value" class. Sanitised at the boundary (once) instead of at every
  `raise` (a dozen), with the real text preserved in the log. The guard found a **fifth** site I had
  missed, inside a response builder — a per-site fix would have shipped looking complete.

## Refutations worth recording

- **A question triggering a write** — verified: `"can you break down requirement 8?"` matches no
  intent; they all require the imperative.
- **Orphaned `ProductLink.warnings`** — the inconsistency ADR-0019 §8 detects reaches a human by
  another route.
- **A typed refusal without authorisation** — partly refuted: it was deliberate and tested. But the
  fix ended up **better than either**: a stranger cannot destroy the proposal, and **whoever asked**
  can correct their own — which was the point of the draft loop, and what a blind admin check would
  have broken.

## Fixed afterwards (the four I had left)

The product owner: *"I want everything fixed before the deploy, so we go in with it all ready."*

- **A message with an attachment was dropped.** The listener discarded **every** message with a
  `subtype`, and Slack marks two common human actions with one: `file_share` (a client attaching the
  month-end PDF and asking a question in the same message) and `thread_broadcast` (a thread reply
  also sent to the channel). In both cases, silence — this platform's invariant broken in the one
  place the client sees. Fixed with an **allow-list** of the two, not with a longer deny-list: the
  deny-list is Slack's to grow, and every future addition would start being answered without anybody
  deciding.
- **A staged proposal never expired.** Two consequences: a "yes" days later confirmed something
  nobody remembered reading — the same damage the click's fingerprint prevents, arriving through time
  instead of through replacement; and, because the acceptance path is barred by `not waiting`,
  **while any forgotten draft was staged, a client answering "it worked" was ignored**. A 2-hour TTL,
  charged on **read** (there is no hangable clock inside a listener, and a stale entry is only
  harmful at the instant somebody acts on it).
- **`refine` got a door.** It is the only capability here that **edits the client's ticket**, it was
  written, tested and reached by nothing — while `triage` already finds exactly the tickets it fixes
  (`no-criteria`). The agent could see the problem it exists to solve and had no way to act. Wired as
  an intent (*"write the acceptance criteria for #412"*), with the same rigour as the others that
  write: it requires the imperative, requires the number, and the answer is composed from the real
  `WriteResult`.
- **`ProductLink.warnings` was written in three places and read by none.** I had classified it as
  refuted and was **wrong** — a `grep` in production comes back empty. A project whose source repo
  does not declare where the requirements live produced a warning that existed only in memory. It now
  goes into `health()`'s line, which the panel and the log read. Recording my wrong classification
  matters more than the defect: a misfiled finding is a lost finding.

### A defect in my own tests, found by sabotage

The TTL test computed the timestamp as `now - PROPOSAL_TTL_SECONDS - 1`. Sabotaging the constant to a
billion seconds moved the **test's input with it**, and the sabotage passed. **An input derived from
the value under test does not test that value.** Rewritten with an absolute one month, plus a separate
assertion that the TTL is within a sane range — because "two hours" and "a billion seconds" satisfy
the same expiry test and nothing else would notice.

## Declared and NOT fixed

None of the 20 findings is left open. What remains is declared by decision, not by omission:

- **A test of mine leaked 200 entries** into the global `_PENDING` and broke another through
  ordering. Fixed, and recorded because global state in a test is the same class as the rest of this
  ADR.
- **The acceptance gate stays lexical on the fast path**, with model judgement on whatever is left
  ambiguous (ADR-0029 §7). A deliberate asymmetry: it errs towards "not accepted", which costs a
  reminder.
- **Click confirmation depends on Interactivity being enabled in the Slack app**, which this code
  cannot verify. Mitigated in the message's own text, which always offers the typed path.
