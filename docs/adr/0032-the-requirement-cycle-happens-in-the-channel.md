# ADR 0032 — The requirement cycle happens in the channel; merging is not agreeing

- **Status:** **Accepted** (2026-07-30)
- **Date:** 2026-07-30
- **Related:** ADR-0019 (the product role and the requirements repo), ADR-0026 (what the client
  reads), ADR-0029 (the click), ADR-0031 (observing is not correcting).

## Context

The product owner, on seeing that I had opened a pull request by hand to unblock things:

> *"hold on… isn't SHE supposed to do all of that? We cannot do things 'on the side'. And does it
> make sense for her to talk about a PR to the client? Shouldn't she translate it into business
> language and do the merge herself?"*

Right on all three counts, and the investigation found more than the question asked for.

### The cycle stopped right after the proposal

| step | who did it |
|---|---|
| write the requirement | she did |
| open the review request | she did — and only since today, because `gh` never had a credential (ADR-0031) |
| **merge** | **nobody** — no code merges the documentation repo |
| **`proposed` → `accepted`** | **nobody** — the status is read in four places and written by nothing |

So a product sold as *no dev needed* required **two developer operations per requirement** —
merging a pull request and editing a field in a markdown file — over a business artefact.

### And the client received a code link

`written_up` sent the pull request URL: *"You can read it here: https://github.com/…/pull/2"*. A
diff, for somebody who runs a business and does not write code. A test even **required** that URL,
with the comment *"a link, where a path would have gone"* — treating a forge link as the acceptable
form of a file path. It is not: it is the same delivery machinery ADR-0026 hides.

### The invisible cost: she cannot see her own work

While the review request is open, the requirement lives on a branch — and she reads the
documentation branch. Asked about a requirement **she had just written herself**, she answered *"on
my side it is empty"*. She was right. The work existed somewhere she cannot see from, and every
conversation afterwards was degraded by it.

## Decision

### 1. Merging ≠ agreeing — and that is what unlocks everything

The **text** was approved by an authorised person, in the channel, in business language, before it
was written. The review request is **mechanism**. So the platform merges its own request, and the
requirement lands on the base as **`proposed`**.

Nothing becomes a promise because of that. What creates the promise is step 2.

**The merge is verified, never assumed:** `gh pr merge` prints nothing on success and the helper
turns a failure into `""`, so the return value is not evidence. We read the state back. Announcing
a merge that did not happen would be the same class of defect as ADR-0028 — and this time ours, not
hers.

### 2. Agreeing happens in the channel, and it is the only act that creates a promise

`accept_requirement` moves `proposed` → `accepted`, recording **who** and **when** in the same
commit (`corpus.py` flags an accepted requirement missing those fields — an agreement nobody can
attribute is not an agreement). Committed directly, with no pull request: the text has already been
reviewed and merged; what changes is one field, and it changes because an authorised person said so.
A second review of a word nobody disputes is ceremony, and ceremony is what teaches people to click
without reading.

**Accepting twice does not rewrite who agreed.** A later confirmation may not reattribute the
agreement to whoever clicked last.

**The confirmation explains the consequence, not the field:** *"from here on, if the product does
something different from this, I treat it as a defect and not as a new request."* Nobody confirms a
`status:`.

### 3. The client never receives a code link

`written_up` still **accepts** the URL — the team and the log use it — and **does not print it**.
Two messages, because "it is in the base" and "it is not in yet" are different facts: the second
also says that **she still cannot read** the requirement, which is true and was invisible. Both
carry the sentence that matters most: **nothing is being built yet**.

### 4. No proposal is left without an owner

`rescue_orphan_proposals` opens the review request for every `req/*` branch that lacks one, on the
sweep that already runs. The immediate cause is fixed, but the **state** comes back with a network
blip, a rate limit or a protected branch — and a failure whose recovery depends on somebody
noticing is not recovered. Nobody lists branches; everybody lists pull requests.

## Consequences

**Good.** The whole cycle — propose, record, agree — happens in the channel, in the client's own
language, without anybody opening the forge. The agent can see her own work, which improves every
conversation afterwards. And the distinction the entire platform depends on (`proposed` vs
`accepted`) stops being a field only a text editor knows how to change.

**Costs and risks, declared.**
- **An automatic merge in a client's repository.** Mitigated by what it means: the content was
  already approved by an authorised person, and the file lands as `proposed`. If the repository
  protects the branch, the merge fails, the request stays open and she **says so** — including that
  she cannot read it.
- **Accepting is the most consequential act on the surface** and now has a door. Gated like
  everything else: an authorised person, a confirmation, and the click button (ADR-0029).
- **The rescue opens review requests on its own.** Idempotent and limited to `req/*`; every rescue
  shouts `OPENFACTORY_PRODUCT_ORPHAN_RESCUED`, so that "nobody noticed" is never the explanation.
- **One hand-opened PR (#2) still exists.** It was a declared patch, made to unblock a test; the
  platform now knows how to do what I did, and the sweep would have done it by itself.
