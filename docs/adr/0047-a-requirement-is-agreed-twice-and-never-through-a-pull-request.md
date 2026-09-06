# ADR 0047 — A requirement is agreed twice, in the conversation, and never through a pull request

- **Status:** **Accepted** (2026-09-06) — the product owner's decision
- **Date:** 2026-09-06
- **Amends:** ADR-0032 §1, §2 and §4.
- **Related:** ADR-0019 (the product role and the requirements repo), ADR-0026 (what the client
  reads), ADR-0029 (the click), ADR-0044/#33 (the two roles; hole 9).

## Context

ADR-0032 moved the requirement cycle into the channel and kept a pull request as the *writing*
mechanism: the role writes the requirement on a `req/*` branch, opens the review request, merges it
herself, and the file lands on the base as `proposed`. It said, correctly, that merging is not
agreeing — and then paid for the mechanism three times over: a sweep to rescue orphaned `req/*`
branches (§4), a role that *"cannot read her own requirement"* while the branch is open, and a merge
that fails on a protected branch and has to be explained. The product owner asked for the pull
request to leave the product owner's surface (issue #33, 2026-09-02): a person who runs a business
does not review diffs, and a review request nobody reads is ceremony.

On 2026-09-06 he named the half that was still undecided — what the second act is *about*:

> *"Two yeses, of course: the draft of a requirement is one thing, the official ticket after it has
> been written and become an issue is another. The requester has to confirm both, and once it is
> confirmed, the acceptance has to appear in the comments, in the requester's name."*

That is the whole decision. The two objects are different; the same person confirms each; and the
promise has to be visible where the work is picked up, not only in a field of a markdown file.

The map had already retired the same shape: D-2 of the knowledge port made the orphan
`openfactory-knowledge` branch unnecessary by writing where the reader reads. A requirement written
on a branch, to be merged by the writer, is that branch again.

## Decision

### 1. The first yes writes the document — directly

The role drafts the requirement in the conversation; the **requester** says yes; the file is
committed to the context repository's base branch as `proposed`, and the link goes to the team and
the log — never to the client (ADR-0032 §3, unchanged). No branch, no review request, nothing to
rescue. If the base is protected and the write is refused, the role says so, in the same words
ADR-0032 kept for a merge that failed: the requirement exists and she cannot read it yet.

A yes to the draft creates **no promise**. It records what was asked, in business language, where
the role and the tech-lead read from.

### 2. The second yes is on the ticket, and only it accepts

From a proposed requirement the official ticket is opened on the board (the `file_ticket` gesture,
referencing the requirement). The **requester** confirms *that* — the thing that will be worked —
in the conversation. Only this confirmation moves the requirement `proposed` → `accepted`, with
**who** and **when** in the same commit (ADR-0032 §2, unchanged: an agreement nobody can attribute is
not an agreement, and accepting twice does not rewrite who agreed).

Two confirmations because they are two different questions. *"Is this what you asked for?"* is
answered on the text. *"Do you commit the product to it?"* is answered on the ticket, when the
person can see what will be built. A distracted yes to a draft cannot become a promise.

### 3. The acceptance is visible where the work lives

When the ticket is accepted, the platform posts a comment on it **in the requester's name**: who
accepted, when, and from which conversation — the attribution the ledger already records, written
where whoever picks up the card will read it, the way a review posted "via the user" already names
the person behind the bot. The card carries its own promise; nobody has to open the context
repository to know one exists.

### 4. The subject of both acts is the requester

The person who asked confirms the draft and confirms the ticket. Authorisation stays where #33 put
it: the allowlist decides who may act at all, the conversation decides where the yes may be given.
An admin who did not ask may still accept on the requester's behalf only if the deployment's
configuration says so; the default is the requester.

## Consequences

**Good.** The cycle — propose, write, open, agree — happens in the conversation, in the client's
own language, with two explicit acts by a known person, and no forge surface anywhere in it. The
role can always read what she wrote. The `req/*` branches, the self-merge and the orphan rescue go
away with the mechanism that needed them. The promise is on the card.

**Costs and risks, declared.**
- **A direct write to the base of a client's context repository.** Mitigated by what the
  repository is — created by the platform for exactly this, holding what the platform writes — and
  by what lands: text an authorised person approved, as `proposed`, which promises nothing.
- **Two yeses are more friction than one.** Deliberately: the second is the one that costs money,
  and it is asked when the person can see the ticket.
- **A comment on the tracker in the platform's name.** The tracker shows the bot as the author; the
  attribution is in the text, as it is for reviews. A tracker that cannot comment is told, and the
  acceptance still stands in the requirement — the comment is the visible copy, not the record.

## What is NOT decided here

- The pack-gap threshold (issue #33, decision 2): the number of real tickets that stumble on a fact
  nobody gathered above which a planner is justified — still the product owner's, written before
  the measurement.
- Whether a ticket opened by hand on the board, not from a requirement, can be accepted the same
  way. Today it has no requirement to move; the comment alone would be a promise without a text.
