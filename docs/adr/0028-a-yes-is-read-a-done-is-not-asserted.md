# ADR 0028 — A "yes" is read; a "done" is not asserted

- **Status:** **Accepted** (2026-07-30)
- **Date:** 2026-07-30
- **Related:** ADR-0021 (closed by observation, never by self-report), ADR-0025 (acceptance),
  ADR-0026 (what the client reads), ADR-0019 (the write gate).

## Context

The product owner approved a staged requirement with:

> *"Yes — record it.*
> *And two things before the decisions. You were right and I was wrong…"*

`is_yes` requires **every** word of the message to be an approval token. It returned `False`. The
draft was never consumed, the message fell through to the conversational model — and her answer said:

> *"Requirement 1 recorded … Going to the team to check."*
> *"#321 and #135 closed in #136."*

**Nothing was recorded. Nothing was closed.** The documentation repository had one PR, from the day
before. He believed for hours that five requirements existed.

These are **two independent defects**, and the second is the serious one.

### Defect A — the gate does not read human sentences

`is_yes`'s own comment already carried this lesson: *"ignoring an emphatic yes is how an owner comes
to believe they confirmed something that was never written."* The previous fix had been to **add
tokens** to a "the whole message must match" rule — which does not survive a sentence.

I tried to widen it: let the first sentence decide. That accepted the product owner's message **and**
*"right — and who audits that?"*, which is a question. **No vocabulary separates an assertion from a
word appearing inside one.** Reading does.

The product owner, on seeing the narrow fix: *"having to be a 'yes - record it' every time makes no
sense, she has to understand affirmations in different forms."*

### Defect B — she asserted an outcome she does not observe

The write happens on a code path she **never sees**, and only after an authorised confirmation. She
has no way to know whether it succeeded. And in the cards' case it is worse: **she cannot close any
card** — that capability does not exist. She asserted an action she cannot perform.

It is ADR-0021's rule broken at the agent level: an outcome by self-report, not by observation.

## Decision

### 1. The lexical gate stays NARROW — and stops growing

`is_yes` accepts the unambiguous (`yes`, `go ahead and record it`, `approved`) and nothing that needs
interpretation. It no longer becomes a larger vocabulary with every new sentence, because it is no
longer the only path.

### 2. What it cannot read goes to the MODEL

`judge_confirmation` returns `approve` | `reject` | `neither` for the answer, given what is on the
table. A small call, only when a proposal is pending — rare by construction.

**Biased towards `neither`.** This gate opens a write in somebody's name: doubt leaves the proposal
pending, which costs one message. A wrong `approve` records a requirement nobody agreed to, which
costs trust. A judgement failure (harness down, unreadable answer) is `neither` — never an invented
approval.

**A conditional yes is `reject`.** *"yes, but change the deadline first"* did not approve what is on
the table.

### 3. She never asserts that something happened

A voice rule, with the real examples from this failure:

```
NEVER   "Requirement 1 recorded. Going to the team to check."
say     "Confirm and I will record it."

NEVER   "#321 and #135 closed in #136."
say     "My proposal is to close #321 and #135 in #136 — confirm and I will file the request."
```

And never claim an action she **cannot** take: she does not close, move or edit a card. She proposes;
a person decides; the platform acts.

### 4. The false claim is DETECTED, not corrected

`claims_a_write(text)` finds the completion assertion; the channel logs
`OPENFACTORY_PRODUCT_FALSE_CLAIM` when it appears on a turn that wrote nothing.

Detecting and not editing is deliberate: rewriting what the agent said puts the platform in the
business of editing an agent's speech, and a wrong edit is worse than a flagged sentence. What
actually happened was worse than both — nobody knew.

A function over **text**, not a method on the module: what it inspects is a sentence, and hanging it
on the module forced every test double to know about it.

## Audit of 2026-07-30 — what the sweep found, with judgement

The product owner: *"no patches, root-cause fixes… nearly hard-coding your way through approvals is
serious, and saying you did what you did not do is worse."*

### Axis 1 — does every write report the truth?

**Yes.** The channel's six write paths (`propose`, `promote`, `file_defect`, `note_fact`,
`break_down`, `baseline`) compose their message from the real `WriteResult`, including counting
partial failures. The platform has **one honest channel** for outcomes.

**The hole is that a second, unrestricted one exists: the model's prose.** The lie was only possible
because her prose was allowed to talk about outcomes.

### Axis 2 — which control gates read prose, and what an error costs

| gate | input | consequence | reversible? |
|---|---|---|---|
| `_DECISION_RE`, `_DEFECT_RE` | **a declared marker** | opens a defect, records a decision | yes |
| intents | free prose | picks a capability | yes |
| `_WORKED`/`_DID_NOT_WORK` | free prose | **declares the client accepted** | no |
| `_YES_TOKENS`/`_NO` | free prose | **writes in somebody's name, spends** | no |

**Consequence and evidence are inverted.** The two irreversible decisions are the ones reading loose
prose; the reversible ones receive an explicit declaration.

### Axis 3 — the root cause of the lie was NOT blindness about the world

This is the discovery that changed the fix. Her prompt **already contained** the requirements index,
saying in these words: *"(this product has no requirements written down yet)"*. She read that and
still wrote *"Requirement 1 recorded"*.

So information about the product was not missing. **Information about herself was.** The prompt
described the world and never described the turn: nothing said that this answer writes nothing, that
the write depends on an authorised confirmation on a path she cannot see, nor — the decisive fact —
**whether the proposal she made last time was still pending**.

With no model of her own agency, she narrated the conversation's intended end state. It is the most
useful thing to say and the only thing she could not know.

A voice rule (*"never say it is done"*) treats this as an education problem. **It is an information
problem.**

## Decision (added by the audit)

### 5. The prompt describes the turn, not only the world

`_agency_section()` goes into every client prompt: this answer **writes nothing**; the write only
happens after an authorised confirmation, on a path whose result does not come back to her; and,
when something is staged, **which proposal is waiting** — with the sentence that the honest thing is
to say it is still pending, never that it is done.

### 6. The false claim is corrected IN THE CHANNEL

Before: a log. A log reaches an operator days later; the false claim reaches the client now — and the
product owner believed for hours that five requirements existed because the only record of the lie
was a line nobody was reading.

The platform now **appends** the correction, in its own voice. Appends and does not edit: what the
agent said stays visible, and the disagreement between the two voices is exactly what the reader
needs to see.

> **Superseded by ADR-0031.** In production this net fired twice, both times on correct sentences,
> with zero true positives — so the correction in the channel was withdrawn and the detection kept.
> Read ADR-0031 before restoring anything here.

## What was NOT fixed, and why

Declared, because silence here would be the same defect in another shape.

**1. Approval by button.** The fix for the "hard-coded" gate was to replace pattern matching with
**reading** (§2), and that resolves the axis the product owner pointed at. An Approve/Reject button
would be better still — a click is unambiguous, it carries the identity and it is not interpreted.
Not done because it requires handling the `interactive` envelope in the listener (today only
`events_api`) **and** because a button is a vendor capability: pushing it into the channel protocol
would leak Slack into a 3-method contract that exists to be agnostic (ADR-0022). The right design is
an optional capability — *"ask for confirmation in the most unambiguous way you support"* — degrading
to text plus reading. It deserves its own ADR. *(It got one: ADR-0029.)*

**2. The acceptance gate stays lexical.** `acceptance_verdict` reads prose and closes an irreversible
loop, so by Axis 2's table it should change too. Kept for a stated reason, not by oversight: it tests
**negation first** and requires a **short** answer, so it fails towards `did-not-work` — and that
error costs one extra question, while the write gate's symmetric error costs a requirement nobody
agreed to. An asymmetry of cost justifies an asymmetry of rigour. If it errs in practice, the path is
the same model reading, not a looser lexicon. *(It did err, and ADR-0029 §7 fixed it.)*

**3. The claim detector is lexical** and catches known vocabulary. A new completion sentence gets
through. It makes the class **visible**, not impossible; what reduces the frequency is §5, which
removes the reason to invent.

## Consequences

**Good.** The write gate starts behaving the way a human speaks, without loosening in the direction
that matters. And the most dangerous assertion an agent can make — *"it is done"* — stops being
possible in silence.

**Costs and risks, declared.**
- **One model call per confirmation** (~US$0.1). Only when a proposal is pending. The price of
  reading instead of pattern matching.
- **The judgement is a model, and models are wrong sometimes.** The bias towards `neither` chooses the
  cheap error: asking again. A false `approve` is still possible — the mitigation is the bias and the
  prompt, not a guarantee.
- **More latency on confirmation** — one extra turn before the write. Acceptable: writing is the step
  that spends money.
