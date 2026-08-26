# ADR 0019 — The product role: requirements are authored documents, in their own repo

- **Status:** **Accepted; core implemented, chat surface pending.** Shipped: the authorization
  reconciliation, the requirements corpus and its rot detector, the context loader, the role over
  `ask()`, requirement pull requests, and issue filing into Backlog — all off unless a project has
  a `product:` section. NOT yet wired: the Slack listener for the product channel and the
  `Needs Action` watcher, so today the module is callable but nothing calls it.
- **Date:** 2026-07-26
- **Relates to:** ADR-0018 (the harness roles this adds a fourth to), ADR-0013 (the sizing gate,
  reused as the acceptance contract for an authored ticket), ADR-0015 (the tech-lead, whose
  diagnoses this role reads), ADR-0016 (read for all, write behind an allowlist — the authority
  model extended here), ADR-0017 (the Knowledge Layer, whose machinery the requirements map will
  reuse), ADR-0005 (the post-merge deploy watch — the reason docs must not live in the code repo).

## Context

The factory can take a well-formed ticket to a merged PR without a developer. It cannot take a
conversation to a well-formed ticket. That gap is staffed by a human today: someone listens to what
is wanted, decides whether it is one thing or five, writes acceptance criteria the sizing gate will
accept, notices that it contradicts something decided three weeks ago, and files it.

The obvious shape — an agent that chats and creates issues — fails on memory. A per-conversation
agent has no idea what the product already promises, so it cannot do the one thing that makes this
role worth having: **push back**. "You asked for X, but that breaks the rule we wrote for Y" is
the output that pays for the role, and it requires knowing everything, permanently.

The first design attempted to *derive* that knowledge from the issue history, mirroring how the
Knowledge Layer derives a module map from code. That was the wrong shape, for a reason worth
stating: **code exists before its map, so the map is derived. Requirements do not exist before
they are written.** There is no prior truth to derive from — a requirement is *declared*. Deriving
one from the exhaust of past execution (issue bodies, comments, PR descriptions) reconstructs a
blurry copy of something nobody ever wrote down.

## Decision

**Requirements are authored documents in a repository of their own; issues are units of execution
that cite them; and a `product` role owns the documents while a human owns the spending.**

### 1. `product` — the fourth harness role

Alongside `executor` (writes code), `reviewer` (reviews the diff) and `techlead` (judges), a role
that decides **what** to build. PO, BA and project manager collapse into one because they share a
technical nature: read over documents, board and code; write **only** to the requirements repo and
the tracker. Never to a source repo.

It runs on the worker, in its own Slack channel per project (`slack_product_channel`, beside the
existing `slack_channel`) — requirements discussion does not belong in the channel where parked
jobs and impediments arrive, and the two usually have different people in them.

### 2. The document is the requirement; the issue is an execution of it

Every issue the product role files **cites its source**: document path, section, and the commit it
was written from — the same source-linking discipline ADR-0017 imposes on the code map, for the
same reason. Nothing may appear in an issue that is not in a document.

This inverts what the issue *is*. It stops being the requirement and becomes what it always
actually was: one unit of work derived from a requirement that outlives it.

### 3. Execution writes back — the loop that decides whether this lives

When a job parks and the decision is made, when scope is cut, when an approach is rejected, the
product role **updates the document**. Without that loop a requirements repository becomes fiction
within weeks: a wish-list that describes a product nobody built, confidently contradicting the
code. This is not an implementation detail, it is the difference between memory and a museum, and
it is the single most likely way this design fails.

### 4. A separate repository, not a folder in the code repo

Requirements live in their own repo. Three reasons, in ascending order of how much they have
already cost us:

1. A requirements edit must not queue behind, or trigger, a code deploy.
2. The code repo's gates are about code — CI, tests, coverage. A document does not pass or fail them.
3. **This platform has already paid for this lesson.** The Knowledge Layer had to publish its
   bundle to a dedicated branch precisely because a commit on `main` fires the client's post-merge
   deploy watch (ADR-0005) and puts every open PR behind it. A separate repo is the stronger form
   of the same fix.

And it buys something free: **sign-off on a requirement is a pull request in the docs repo.** Not
a Slack button. The product role opens a PR carrying the change, who asked for it, and when; a
human reviews and merges. Auditable, versioned, familiar, and no CI to pay for. It also settles
the two-writers problem — git arbitrates between the human and the agent.

Requirements carry a number and a status (proposed · accepted · superseded-by), the same
discipline these ADRs use. No new machinery.

### 5. Authority: the role owns requirements, the human owns spending

The board's TO-DO column is a **spending trigger** — the poller pulls from it and every promotion
starts a job that costs real money. So the line is drawn at cost, not at content:

| | who |
|---|---|
| Rewrite an ambiguous criterion, clarify scope, split, relate, close a duplicate | product, on its own |
| Act on a `Needs Action` item whose cause is a requirement defect | product, on its own |
| Merge a requirement change | human (PR review in the docs repo) |
| Promote to TO-DO | human (the sign-off) |

"On its own" means: once authorized in the project's allowlist (ADR-0016), it acts without asking
per action. Requiring a human for every wording decision would put a person back in the loop the
factory exists to remove; requiring one before money is spent keeps the only gate that matters.

Every action it takes leaves a comment on the issue saying what changed and why — not
bureaucracy, but what makes the sign-off real rather than a rubber stamp.

### 6. `Needs Action` is where it meets the tech-lead — no agent-to-agent channel

The column already exists and already holds exactly what needs a decision. The product role watches
it, reads the diagnosis the tech-lead has already left on the issue, and decides whether the cause
is a requirement defect (its own) or technical/environmental (not). No new field, no classifier,
no routing layer.

**No feasibility RPC between the two agents.** It would be a false need: every harness role is built
on the same read-only `ask()` primitive, so the product role reads the code itself rather than
asking another agent to read it and relay. And two agents conversing with no human in the loop is
where two mistakes compound with nobody owning the result. They communicate through artifacts — the
document, the issue, the board — exactly as people do.

### 7. A product spans N source repos; a job targets exactly one

A product's requirements describe back-end and front-end, or a fleet of services. The product
context is therefore multi-repo, while a job stays single-repo — a job is one PR in one repository,
and that must not change.

- The **product context** spans N source repos.
- A **ticket carries its target repo** — the field that does not exist today.
- The **board stays one per product**, spanning repos. It is the product's board, not a
  repository's.

### 8. The link is declared twice and authorized once

Each source repo declares its documentation repo in the `.sdlc/project.yaml` it already has; the
documentation repo declares its member sources. The **registry authorizes** — a claim by a repo
that the deployment's registry does not confirm is ignored and logged, the same shape as ADR-0001
D-2, where a project manifest may tighten permissions but never loosen them.

Two directions because each answers a question the other cannot. The source→docs pointer gives
discoverability (clone a repo, find the requirements) and lets a new service join a product by
changing that service, not a central file. The docs→sources list gives the product role the
**complete membership set** — you cannot discover a repository you do not know exists.

And two independent declarations must agree, so disagreement is a *detectable inconsistency*
rather than a silently wrong answer. A one-way pointer fails quietly.

### 9. The sizing gate is the acceptance contract

A ticket the product role authors is judged by ADR-0013's sizer **at authoring time**, in the
conversation, rather than at pre-flight hours later. A ticket that is not one cohesive, independent,
testable outcome gets fixed while the person who asked for it is still there. Same `size()`
primitive, no new judgment machinery — and every ticket entering the pipeline is INVEST-shaped,
which incidentally strengthens the cost comparison the Knowledge Layer's A/B depends on.

### 10. A map over the documents — later, on the Knowledge Layer's machinery

Reading every requirement on every question is impossible and would contradict the efficiency the
platform sells. The corpus needs an index: same bundle, same staleness proof, same
inject-only-when-provable rule as ADR-0017 — with a different extractor (requirement ids, sections,
status, cross-references, instead of modules and imports).

This waits for the Knowledge Layer's A/B. If the architecture demonstrably saves tokens on code, it
is applied to a second corpus with that confidence already bought; if it does not, far better to
have learned it once. Nothing else here depends on that: authored requirements, the docs repo, the
PR sign-off and the role itself can all ship before the map exists.

## Consequences

**Good.** The role that was staffed by a person — turning a conversation into a well-formed,
non-contradictory ticket — becomes part of the factory, without handing an agent the ability to
spend money unsupervised. Requirements gain version control, authorship and dates for free, because
they are files in git rather than rows in a tool. A product can span a fleet of repositories while
each job stays as simple as it is today.

**Costs and open risks.**
- **The write-back loop is the failure mode.** If execution outcomes stop reaching the documents,
  the corpus rots into confident fiction. Worth instrumenting early: a merged ticket whose document
  was never updated is a measurable defect, not an invisible one.
- **Requirement↔code drift cannot be checksummed.** A document citing code in another repo does not
  go stale when that repo changes, and "is this requirement still true of the code?" is a semantic
  judgment. Deliberately not automated: a citation that no longer resolves is *flagged for review*,
  never treated as an error, and never silently repaired.
- **Multi-repo is modelled before it is exercised.** The first product has one source repo, so the
  target-repo field and the membership set will be built against N=1. Cheap to model now, but it
  will not be proven until a second repository exists.
- **The role can be wrong about whose problem an item is.** A technical impediment misread as a
  requirement defect costs a message and a redirect. The path back must exist from the start rather
  than being discovered.
