# ADR 0026 — A word the reader already has beats one you invent

- **Status:** **Accepted** (implemented 2026-07-29)
- **Date:** 2026-07-29
- **Related:** ADR-0019 (the product role), ADR-0025 (acceptance).

## Context

The second real conversation after the deploy. The product agent answered — with memory, cheaper and
faster — and the client did not understand what she said:

> The product owner: *"her questions, I cannot identify them. For example, 11 diagnostic points?
> What is that? Would they be items in the review column? She can mention our project board, she is
> a PO, honestly — the message was very confusing, putting myself in a client's shoes."*

Her message contained *"the 11 diagnostic points in review"*, *"the work-progress channel (item
297)"* and *"Bands 1 and 2"*. None of those exist. They are names she **invented**.

### The cause: we banned the word and the concept stayed

`AUDIENCE_RULES` said, literally: *"Never mention pull requests, branches, commits, **repositories,
boards or tickets**."*

And her prompt **contains the board**, with the real column names. So: she had "Review" in her hand
and was forbidden from saying "Review". Banning the word does not remove the thing — it **forces an
invention**.

And the invented name is strictly worse than the technical one:

- the reader cannot map it to anything they can open;
- it sounds precise while meaning nothing verifiable;
- it forces them to ask *"what is that?"* — which is exactly what happened.

The rule already knew this for requirements (*"Requirement numbers ARE shared vocabulary"*). It had
simply drawn the line in the wrong place.

### The second defect, from the same family

The same message was in **European Portuguese** — for a Brazilian reader. `project.language =
"pt-BR"` exists and is used by `voice.py`'s fixed sentences, but **never reached the model**, which
writes every free sentence the client reads. It inferred the dialect from context and got it wrong.

Both are the same class: **the platform had the information and did not hand it to the agent.**

## Decision

### 1. The line moves: machinery hidden, artefacts shared

- **Hidden** — pull request, branch, commit, repository, file path, code identifier. None of it
  reaches the channel.
- **Shared** — the requirement number, the **project's board**, the **column names exactly as they
  are written on it**, and the card number. The board is the client's; they open it. Use their
  words.

### 2. The rule that generalises: never invent a name for something that already has one

It matters more than any jargon rule, and it is written with the real examples from this message:

```
NEVER   "the 11 diagnostic points in review"
say     "the 11 cards sitting in the Review column"

NEVER   "the work-progress channel"
say     "#297 — <the card's real title>"

NEVER   "Bands 1 and 2"
say     the requirement numbers, or describe the group in one plain sentence
```

A word the reader recognises, even a technical one, beats an invented one **every time**.

### 3. The dialect is stated explicitly, with the words that differ

*"Write in Portuguese"* is the instruction that produced European Portuguese. So the variants are
named with the terms that give the dialect away, in pairs, and the rule generalises to any language
a deployment configures.

A language with no written rule returns **""** — letting the model read the room beats an invented
instruction.

### 4. The team's prompt receives neither

An issue body is read by the executor and by the team. Softening it into business prose, or fixing
its dialect, removes the detail from whoever is about to act. Two surfaces, not one vague voice.

### 5. What she asks of a person becomes a tracked commitment

The same report exposed a second, larger hole. Her message ended with **three decisions requested**
— and the ledger recorded none of them. Loops were only born on the **board sweep**; a request made
in conversation lived in a chat message and died when she scrolled up. Nobody would be chased — the
"no silent wait" invariant broken in the one place the client sees.

**A new ledger type: `DECISION`**, and the reason it is not a `QUESTION` is a trap that would have
bitten silently: `followup.answered()` closes every `QUESTION` whose `subject:about` no longer
appears among the board's live findings. A decision asked for in a chat **has no finding at all**,
so the next sweep would close it as "resolved" minutes after it was raised. Its own type is what
keeps it out of that rule.

**Declared by the model, not guessed from prose.** A `[[DECISION: …]]` marker, the same pattern as
`[[REQUEST]]` and `[[DEFECT]]`. Inferring "was that a question?" from free text produces both
failures: a lost request and a phantom commitment.

**It closes when the person speaks.** The observation is the human answering — the same pattern as
the acceptance loop. Closing happens **before** the new answer opens others, or it either erases the
ones she just opened or leaves the previous round's open for ever. A partial answer is safe: she has
the conversation in memory and re-asks what is missing, opening a new loop.

**Chased once, at 48h, repeating the decision.** A reminder days later has to carry the question
with it: *"coming back to what I asked you"* is only a reminder for somebody who already remembers —
exactly the person who does not need one. With an explicit way out, and **never** closed by time.

## Consequences

**Good.** The client can now **verify** what she says: *"11 cards in the Review column"* can be
checked by opening the board; *"11 diagnostic points"* cannot. And she stops sounding like a
different person writing from a different country.

**Costs and risks, declared.**
- **More technical vocabulary in the channel.** Deliberate, and only vocabulary the reader already
  has. If a future client uses no board, the rule has to follow what THEY see — this is deployment
  configuration, not a universal truth.
- **The dialect list is short and human.** It covers the terms that give it away most; it is not a
  proofreader. If another one shows up, it joins the list.
- **Text guards age.** The tests pin the REAL invented phrases from this conversation, so they are
  about this defect and not about a mood — but no test prevents a new invention. What prevents that
  is the explicit rule, and the client's next report is what corrects it.
