# ADR 0031 — Observing is not correcting: when the safety net becomes the damage

- **Status:** **Accepted** (2026-07-30)
- **Date:** 2026-07-30
- **Related:** ADR-0028 (the agent does not assert what it did not observe), ADR-0026 (what the
  client reads), ADR-0029 (the click).

## Context

ADR-0028 installed two defences against the agent claiming a write that never happened:

1. **the prompt** — every turn tells it that this answer writes nothing, that the result does not
   come back to it, and what is still pending;
2. **the correction in the channel** — if its text claimed a write on a turn that wrote nothing,
   the platform appended, in its own voice: *"nothing was recorded with this message."*

The second one was the safety net, because a prompt is probabilistic.

## What happened in production

The net fired **twice**, and both times on sentences that were **correct**:

| # | what it wrote | why it was right |
|---|---|---|
| 1 | *"I said 'Requirement 1 recorded', '#321 and #135 closed in #136'. **It was not.** I do not see the result of any write"* | a **retraction** — it was quoting itself in order to take it back |
| 2 | *"the text **was recorded**, the review request did not open, and I had no way to see the failure"* | an **exact history** of the previous turn |

**True positives over the same period: zero.**

I tried to fix the first one by adding a negation detector. The second went straight under it — and
the reason is not vocabulary: *"I recorded it just now"* and *"it was recorded last time"* differ
only by **tense and temporal reference**, which a word list does not read.

### Why the error is asymmetric

A **wrong** correction costs more than a **missed** one:

- it contradicts the agent in front of the client, so the reader learns to distrust **both** voices;
- and it lands precisely on the honest, self-correcting messages — punishing the behaviour the rule
  exists to produce.

A missed correction costs one line in a log somebody reads later.

## Decision

**The detection stays; the action in the channel goes.** `claims_a_write` keeps running and
`OPENFACTORY_PRODUCT_FALSE_CLAIM` keeps being logged — a false claim stays **visible to us**. What
the platform stops doing is appending text that contradicts the agent in the client's own
conversation.

This is a retreat, and it is declared as one. What removed the original damage was not the net: it
was the **prompt**. The agent began saying, unprompted, *"I am not the one who opens the review
request; the result never comes back to me"*, and retracting without being asked. The net was
designed for a failure mode the first defence appears to have eliminated.

### What would reverse this decision

One line of `OPENFACTORY_PRODUCT_FALSE_CLAIM` **without** a matching write — that is, a true
positive. Then the correction comes back, and it comes back with a **model reading the sentence**,
not a regex matching a word. That is the lesson: the judgement that needs tense and temporal
reference is the same kind of judgement already sent to the model in `judge_confirmation` and
`judge_acceptance` (ADR-0028/0029), and insisting on a lexicon here treated a reading problem as a
vocabulary problem.

*Addendum, 2026-08-25.* The correction's phrasebook entry (`voice.nothing_was_written` and its two
sentence tables) was deleted as code reached by nothing — a dead-code sweep before the public
release. This does not reverse the decision above: when the correction comes back it comes back
with a model reading the sentence, and it re-authors what it says over the agent then. Keeping a
sentence nobody could reach was the built-reached-by-nothing class, not a reservation.

## Consequences

**Good.** The client stops watching the platform argue with its own agent, and the agent stops
being punished for correcting itself. Observability does not change: every claim is still seen.

**Costs and risks, declared.**
- **A genuinely false claim reaches the client with no immediate contradiction.** Mitigated, not
  eliminated: by the prompt, and by the fact that a real write produces a sentence composed **by
  the platform** (with a URL, in the requirement case) — the absence of that sentence is the signal
  for whoever is reading.
- **The decision rests on a small sample** (two firings). What reverses it is written above, so the
  reversal is an observation rather than an opinion.
- **The log stays at `ERROR`** with no alarm attached, deliberately: it is meant to be read during
  an investigation, not to wake somebody at three in the morning over a sentence in the past tense.
