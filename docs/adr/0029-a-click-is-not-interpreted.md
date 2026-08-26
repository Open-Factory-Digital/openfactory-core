# ADR 0029 — A click is not interpreted

- **Status:** **Accepted** (2026-07-30)
- **Date:** 2026-07-30
- **Related:** ADR-0028 (the model-read "yes" — this ADR is the step that one declared pending),
  ADR-0022 (provider agnosticism), ADR-0025 (acceptance), ADR-0021 (observation).

## Context

ADR-0028 fixed the recognition of "yes": the lexical gate got narrow and whatever it cannot read
goes to a model. And it stated explicitly what had **not** been done:

> *"Approval by button… a click is unambiguous, it carries the identity and it is not interpreted.
> Not done because it requires handling the `interactive` envelope in the listener, and because a
> button is a vendor capability… It deserves its own ADR."*

The product owner: *"implement everything you did not fix, and re-check whether there is more to
do."*

### Why reading is not enough

Reading solves recognition and does **not** solve the nature of the act. Between the person and an
irreversible write made in their name there is still an **interpretation** — better than matching
words, but still a judgement that can be wrong.

A click is not interpreted. It carries the identity of whoever clicked, it names exactly what was
clicked, and it cannot be a sentence about something else. For the one decision on this platform
that spends money and writes in somebody's name, that difference is the requirement.

### And the acceptance gate was worse than I had judged

ADR-0028 kept `acceptance_verdict` lexical with a stated argument: *"it errs towards
`did-not-work`, and that error costs one extra question."* That holds for **denial**. Measured
afterwards:

```
"ok, got it"   -> worked      ← acknowledgement, not acceptance
"I tested it"  -> worked      ← says it was tested; nothing about the result
"fine"         -> worked
"I checked"    -> worked
```

**Those are false acceptances**, and that is the **expensive** direction: the record now says the
client signed off on something they never confirmed — exactly the claim this platform sells and may
not manufacture. My argument was right about half the gate and wrong about the other half.

## Decision

### 1. `ConfirmingChannel` — a capability, not a fourth method

The channel protocol has three methods because that is what the **core** needs from every provider.
A button is a capability only some have, and pushing it into `ChannelAdapter` would make every
adapter and every test double fail `isinstance` over something they legitimately cannot do.

So it is a separate Protocol. The caller asks `isinstance(channel, ConfirmingChannel)` and degrades
when the answer is no. Slack implements it; a provider without buttons returns `False` **without
posting anything**, and the caller sends the prose — never both.

The justification the three-method rule demands is written into the protocol itself: *"an
irreversible decision resting on an unambiguous act"* is a core need, not a Slack feature.

### 2. The token carries a FINGERPRINT of the proposal

This is the damage the button could **introduce**. A proposal can be replaced between being shown
and being clicked (`_note_replaced` exists precisely because that happens). Without a fingerprint,
the click would approve whatever is staged at the moment of the click — and somebody would have
confirmed text they never read.

With it, the divergence is **detected** and said out loud: *"what is staged now is different from
what was on this button. I will not record something in your name that you did not read."*

### 3. Three facts, three sentences

A stale button, a replaced proposal and a refusal are different things. One message for all three
would leave the reader unable to tell which happened — the *"two facts sharing one value"* class
this codebase has already paid for four times.

### 4. Authorisation applies equally, and refusing is also an act

The click carries the real id of whoever clicked, so `may_act` applies — and **before the pop**, as
on every confirmation path: an unauthorised click must not consume the proposal, or the real
approver's click finds nothing. It holds for **refusal** too: a stranger may not throw away work an
admin was about to approve.

### 5. An approved click runs the SAME path as a typed "yes"

`confirm_by_click` delegates to `handle(text="yes")`. A second implementation of *"what a
confirmation does"* would diverge from the first — and the bare `"yes"` is accepted by the lexical
gate with no interpretation at all, which is the point.

### 6. One helper for the four staging sites

`offer_with_buttons` is a single function. Four copies of *"try a button, else prose"* is how three
of them gain the button and nobody notices the fourth — this house's defect signature. And
`confirm` comes from the listener, being `None` everywhere else (activity, test, panel), so those
degrade **by construction** and not because somebody remembered.

### 7. The acceptance gate: the lexicon keeps only what ASSERTS it worked

`solved`, `worked`, `resolved`, `yes`. Out went `ok`, `fine`, `that's it`, `I checked`, `I tested`.
Everything ambiguous goes to `judge_acceptance`, and **only when an acceptance is open** — the
ledger is read first, so an ordinary message pays for no model call.

Biased towards `neither`, asymmetrically: an open acceptance costs a reminder; a wrong `worked`
closes with a signature nobody gave.

A detail that became a test: `"did-not-work"` **contains** `"work"`, so reading the verdict tests
the negation first. The naive order would read a complaint as an acceptance.

## Consequences

**Good.** The platform's most expensive decision stops depending on interpretation on the main path.
The click carries identity, names the object and is auditable. And the acceptance gate stops
manufacturing client signatures out of an "ok".

**Costs and risks, declared.**
- **Slack now needs Interactivity enabled** on the app. Without it `chat.postMessage` with blocks
  still posts, but the click never arrives — and since the prose is not sent when the button post
  returns `ok`, the confirmation would have no path at all. Mitigation: a click that never arrives
  leaves the proposal **pending**, and the person can type the approval as before; the prose path is
  still alive and is the same `handle`. **Check the app before trusting the button.**
- **One more model call** per ambiguous acceptance (~US$0.1), only with an open loop.
- **The token travels in the button's `value`**, visible to anyone inspecting the payload. It is not
  a secret — it is a conversation id plus a hash of the content, and authorisation is checked on the
  server with the id Slack signs. A guessed token approves nothing without `may_act`.
- **The fingerprint is 6 bytes.** A collision is irrelevant here: the adversary is not random, it is
  a legitimate replacement that changes the text, and any real change changes the hash.
