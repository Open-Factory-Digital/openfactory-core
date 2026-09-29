# ADR 0054 — A card the product role opens is drafted, judged against a rubric, and shown whole before the yes

- **Status:** Accepted (implemented with #383)
- **Date:** 2026-09-28
- **Relates to:** ADR-0001 D-8 (the spec-quality gate: a deterministic filter first, then an
  optional model judge. **This record implements that judge where the card is written**, not at
  pickup. The `TODO(next)` at `machine.py` `_spec_gate` stays, because pickup still reads cards a
  person wrote on the board), ADR-0006 (a bounded review → repair loop, one repair, reacting to the
  decision rather than the score, which D4 reuses), ADR-0019 §9 (a ticket the product role authors
  is judged at authoring time, in the conversation, never implemented until now), ADR-0028 (a yes is
  read, so the yes must be to what is written, D5), ADR-0051 D8 (no model under the product's
  semaphore, D6). Issues: #383.

## Context

The card is the only thing the coding agent reads. On v0.4.1 a person reported a layout defect with
a screenshot. The product role read the image, found the earlier card about the same page, restated
the defect precisely and proposed a title. The person said *"pode criar um card novo e siga para a
correção"* and confirmed the title. The card that landed had that sentence as its whole body and its
title cut at 80 characters. Triage then flagged it as having nothing that says when it is done.

Four causes, each in the code:

- The ticket gesture wrote the **current message** as the body (`engine.py`, `described = text`).
  In a real conversation the description comes first and the gesture last.
- The confirmation showed the **title alone**, so the person approved one thing and the board got
  another.
- The title was sliced blind, twice (`[:80]`).
- `ticket_body` wrote no objective and no criteria, so **every card the role opened was refused by
  the pickup gate** until somebody ran `refine`.

The fix direction in #383 (restate, confirm what is written, tell the bound, never file the gesture)
is necessary, but not sufficient on its own. A restatement is still one model's first draft, and
nothing checks it before a person is asked to approve it. The platform's other judged artefacts all
run a bounded judge loop: the code review → repair, and the evaluation battery's judge. The
product's most consequential write had none.

## Decision

**D1. The card is drafted from the conversation, never from the message that asked for it.** The
engine keeps this conversation's transcript and the typed intake on the exchange. It keeps only this
conversation: what memory recalls from other conversations never reaches a card. The role drafts the
card as JSON from the transcript, its own reply and the triggering message: title, objective,
description, done when, out of scope, related cards, and the person's own words as a quote. The
triggering message is kept as the source, never as the body.

**D2. A deterministic floor runs first, and no rubric can switch it off.** It checks:

- a title of at most `TITLE_LIMIT` (80) characters, never cut;
- a description that is not the request to open a card;
- at least one statement that says when the work is done;
- a quote that was really said in the conversation;
- the **pickup gate's own verdict** (`spec_verdict`) on the rendered body.

A draft that fails the floor is redrafted with the floor's problems, and the judge is not spent on
it.

**D3. A judge scores, and the code decides.** The judge sees the rubric, the conversation and the
card, and nothing else: it stands in an empty directory. It returns one level per criterion, the
evidence for each, any critical failure, its findings, and the one question to ask the person when
something the card needs was never said. The average, the per-criterion floor and the verdict are
computed in code. A partial scoring is no scoring: a missing criterion is never read as a default
level. The judge runs on the **reviewer** axis, so a deployment can give it a different engine from
the product role: a judge on its author's model shares its author's blind spots.

**D4. One draft, one redraft, then a question.** The redraft receives the floor's problems or the
judge's findings. If the second attempt also fails, nothing is staged, and the role asks the person
the judge's question (or the draft's own). A third attempt at the same conversation is a loop: what
is missing then is information only the person has.

**D5. The confirmation shows the whole card, and the yes writes that card.** The staged entry keeps
the rendered card, and the yes files it as it was shown. It is never re-rendered at confirmation,
when a template changed in between would write a body nobody read. The lines above it (who asked,
where, the card's kind that `correct_card` reads) stay the code's.

**D6. No model runs under the semaphore.** Drafting and judging happen before staging, and the
write at the yes is the same checked write as before.

**D7. The bar is the product's, and it lives in the context repository.** The template and the rubric
ship in `org_defaults/cards/`. A product replaces either by committing `cards/template.md` or
`cards/rubric.yaml` to `product.docs_repo`. A card is product guidance: a product of several source
repositories has one context repository, and that is where the role already reads and writes
requirements. A code repository's `.openfactory/` stays technical (profiles, gates).

- A template is measured before it is used: rendered with a sample card, it must keep every field,
  pass the pickup gate, and keep the section a correction rewrites.
- A file that cannot be used is refused by name in the log, and the shipped one is used.

**D8. Every verdict is a log line that recomputes it.** `OPENFACTORY_CARD_JUDGED` carries the rubric
id, version and source, the attempt, the scores and the verdict. A floor refusal carries its
problems. The judge's calls are metered as `product_card_judge`, and the draft's as
`product_card_draft`.

## Consequences

- A card the role opens now passes the pickup gate by construction, and triage no longer flags it.
- A card request costs two to four model calls instead of none: one or two drafts, one or two
  judgements. The person waits through them after the receipt.
- An unjudged card (no judging harness, or an answer that could not be read) is still shown, with a
  line saying it was not reviewed. The person is then the only reader, and is told so. This is the
  cheap direction: the floor still ran, and nothing is written without the yes.
- Card bodies are pt-BR, as `ticket_body` has always been. The day the writers follow the project's
  language, the shipped template becomes one per language.

## Not decided here

- ~~**The defect path** (`[[DEFEITO]]`) still stages the person's message as its restatement.~~
  *Decided 2026-09-29 (#392, in #390): measured live, a report read as a broken promise reached the
  board as the person's own words, titled "…nao estao responsivos se minimiz". A defect now runs the
  same loop: drafted from the conversation, the same floor and rubric, the whole card before the
  yes, the held question. Its layout is `defect-template.md` (its description under "O que está
  acontecendo", the section a correction rewrites), and the promise it breaks stays the code's.
  The same day the rule became ONE DOOR FOR EVERY CARD: the cards a requirement is broken into
  (`_file_one`) are checked by the floor and the judge against the requirement, redrafted once,
  and not filed when still blocked — no person is in that loop to ask. A guard fails on any
  `create_ticket` in the product module outside the three checked writers.*
- **Calibration against people.** The log lines are the record. Measuring agreement between the
  judge's verdicts and what people later corrected or closed is the next step. A golden set and a
  runner of their own belong with the evaluation battery (ADR-0051), not with the runtime.
- **Ensemble judging and weighted criteria.** Both wait until verdict data shows they would change a
  decision.
