# ADR 0038 — The platform is complete on its own; channels are add-ons

- **Status:** **Accepted**
- **Date:** 2026-08-02
- **Relates to:** ADR-0015 (the notifier), ADR-0016 (production is never released from chat),
  ADR-0022 (provider seams), ADR-0026 (two surfaces, same floor), C-23 (#51, the action layer),
  [`docs/core/07`](../core/07-extensibility.md) (the extension model).

## Context

The product owner, looking at a pull request the factory had just opened and finding nothing in the
panel to do about it:

> *"if we have a human in the loop, fine, that is perfect, the human has to approve — but **not in
> git**. That should be something in the panel, in Slack, Teams, whatever: a communication from the
> tool to the human, not a silent 'in review'. That makes no sense at all… Slack and Teams are mere
> channels; the platform has to have 100% of everything and the channels are optional, and I will
> only release those as add-ons."*

Two statements. The second is the architectural one and this ADR is about it.

**The principle was never written down, and the code does the opposite.**

```
sdlc/techlead/          3 files      the capability
sdlc/runtime/slack/     3,998 lines  the "channel"
    bot.py                1,199
    product_channel.py    1,972      ← the product role, entire
    product_intents.py      560
```

Nearly four thousand lines of conversational capability live inside a transport. The product
role — the thing that talks to a client about requirements, deliveries and acceptance — **is a
Slack module**. A deployment without Slack does not have a degraded product role; it has none.

That is not a channel being optional. It is a channel being load-bearing while the documentation
calls it one axis among nine.

**The second half of the observation is the symptom.** With `merge_policy: human`, the platform
emits `🤖 PR ready for review: <url>` and stops. The Slack bot's action set is hard-guarded to
`resume`/`skip` (`runtime/slack/bot.py:614`), and the panel has no merge endpoint at all. So the
only way to complete a human-gated merge is to open GitHub and click a button — which is precisely
the work the product exists to remove, and it is reached through a link in a message rather than
through the platform.

## Decision

**Every capability the platform offers is complete without any channel. A channel adds reach, never
function.**

Three consequences, in the order they bind:

### D1 — The panel is the reference surface

Whatever a human can do, they can do in the panel. Not "eventually" and not "the important ones":
the panel is where the platform is whole, and a capability that exists only in a channel is a
capability the platform does not have.

This is a testability claim before it is a product claim. The product owner again: *"I cannot test
as a client without looking at the panel and working there as an end client — otherwise we are not
testing, we are cheating the real tests."* A product whose acceptance path runs through a vendor's
chat app cannot be exercised end to end without that vendor.

### D2 — A wait is a question, never a state

A human-gated step must reach the human as **a question with executable options**, on a surface the
platform owns. `In review` with a link is a state; it asks nothing, it offers nothing, and the
person it depends on may never see it.

This is the platform's own headline invariant — *no silent stall; every wait self-heals or asks a
human with executable options* — which is currently enforced for impediments and **not** for the
merge gate. A PR waiting for approval is a wait. It gets the same treatment.

### D3 — Channels are transports, and they are add-ons

Slack, Teams, WhatsApp, e-mail: a channel carries a question the platform already formed and
returns an answer the platform already understands. It does not own the question, the options, the
authorisation, or the record of what was decided.

Practically: **no capability may live in `runtime/<channel>/`.** That package renders and parses;
everything it renders must exist and be answerable without it. C-23 (#51) is the mechanism — one
action layer, every action reachable from at least two transports and implemented by none of them —
and this ADR is the reason it is not optional.

## What this does NOT mean

- **Not that ADR-0016 is relaxed.** Production is still never released from chat. A channel may
  carry the *question*; the prod gate stays the panel with a password. D3 says a channel adds no
  function — it does not say every function reaches every channel.
- **Not that Slack loses features.** The tech-lead channel keeps its voice, its brevity and its
  presence (ADR-0026). What changes is where the capability lives, not how it reads.
- **Not a rewrite.** `product_channel.py` is 1,972 lines because a great deal of judgement about
  how to talk to a client is encoded in it, and that judgement is worth keeping. Moving it is a
  relocation, not a redesign — and it must be done with the guard C-23 names, because a relocation
  nobody can verify is how the two front ends drifted apart in the first place.

## Consequences

**Good.** The product becomes testable as a client experiences it, without a Slack workspace. An
add-on model becomes possible at all — `docs/core/07` observes that `openfactory install <addon>`
has nowhere to plug in today, and this is what creates the socket. And the commercial claim
("no dev needed") stops depending on a link to GitHub.

**Costs and open risks.**

- **It is a lot of code to move**, and the move is invisible to every existing test — both front
  ends were written independently and neither exercises the other's behaviour. Without C-23's
  two-transport guard landing first, this trades one coupling for a silent regression.
- **The panel becomes the critical surface** and is today the least defended one: it has no
  automated coverage of its endpoints at all, which is how it shipped a `NameError` and two
  ungated AWS calls that 2,999 tests did not see.
- **It raises the bar on the panel's own authorisation.** Today an unset `SDLC_PANEL_TOKEN` means
  the panel is open. That is defensible for an observability view and not for the surface where
  merges are approved.
- **The question of WHICH human** is now unavoidable. A merge approval needs an identity, and the
  panel has one only for production approvers (`sdlc approver`). Extending that is part of C-26.
