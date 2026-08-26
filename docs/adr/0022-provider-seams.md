# ADR 0022 — Provider seams: an axis is agnostic when it is BORN with two

- **Status:** **Accepted; shipped** (tracker: github + jira · forge/CI/channel/board: seam ready,
  second provider deferred by decision — see §5).
- **Date:** 2026-07-28
- **Relates to:** ADR-0018 (harness roles — the registry this copies), ADR-0001 (the conceptual
  model's agnosticism claim), ADR-0019 (the product role, whose module was one of the coupled
  call sites), ADR-0013 D3 (parent/child linkage, which Jira implements differently).

## Context

Agnosticism is one of the three things this platform is sold on: no developer needed, more
token-efficient, **vendor-agnostic**. The first two were being measured. The third was being
assumed.

The product owner, 2026-07-28: *"the scope is not bigger, that was a premise from the start — our
production client is Python with GitHub and it is our PILOT, but I am going to sell this to many
clients with completely different structures… just as with the harness, we have to be born with
Claude Code, Codex and Kimi."*

That sets a standard, and it is harder than having a Protocol: **an axis is not agnostic because it
declares an interface — it is agnostic when it is born with more than one implementation and a seam
that dispatches between them.** The harness has had three since it shipped. An audit against that
standard found the rest of the platform failing it in a specific, measurable way:

| axis | Protocol | implementations | dispatch | verdict |
|---|---|---|---|---|
| harness | yes | claude_code · codex · kimi | registry | the model |
| tickets | yes | github | **none** | one-vendor |
| forge / repo | yes | github | **none** | one-vendor |
| CI | yes | github_actions | **none** | one-vendor |
| board | **none — not a concept at all** | github | none | one-vendor |
| conversation channel | **none** | slack | none | one-vendor |
| notification | yes | slack · telegram | factory | fine |
| sandbox | yes | container · worktree | yes | fine |
| **stack** (Java/PHP/C#/Python/serverless) | — | — | — | **already agnostic** |

Every failing row shared one shape: **the protocols were honest and the composition root was not.**
`TrackerAdapter` had always been an interface, and `GitHubIssuesTracker` was still constructed by
name in twelve places; `GitHubForge` in eleven. A Jira client would not have got a worse tracker —
they would have got an `ImportError` in the poller.

Two rows deserve their own note:

**The stack was already fine, and not by accident.** The platform names no build command anywhere —
no `mvn`, `dotnet`, `composer`, `npm`. The client's manifest declares `validate:` and the framework
runs what it is given. Java, PHP, C# and serverless deployments need nothing new. This is what a
solved axis looks like, and it is the bar the others are held to.

**The board was worse than one-vendor: it did not exist.** `TrackerAdapter` covers tickets and says
nothing about columns, so "the board" was a GitHub feature that six modules reached for directly.

## Decision

**Every provider axis gets a REGISTRY: `kind → builder`, resolved from the project's configuration,
with an unknown kind raising rather than defaulting. No module outside a provider's own package may
name a concrete class.**

Copied deliberately from `agent/registry.py` rather than invented — one rule to learn, not six.

### 1. An unknown kind RAISES

Never a fallback. The error message names what IS supported, so it is actionable at startup.

The reason is uniform across axes and worth stating once: **a wrong provider does not fail like a
missing one.** A GitLab deployment silently handed a GitHub client authenticates against the wrong
host with the wrong token and surfaces as a *permissions* problem — the most expensive shape a
configuration error takes, because it looks like something else entirely. Per axis:

- **tracker** — tickets written into a repository nobody reads
- **forge** — an auth error that is really a config error
- **CI** — a release stuck in "verifying" for ever, because nothing observes the pipeline
- **channel** — silence, which is indistinguishable from a factory with nothing to say

### 2. Protocols are `@runtime_checkable`, and tests use `isinstance`

A protocol nobody checks is documentation. This is not theoretical: when `BoardAdapter` first
landed, `isinstance(GitHubProjectBoard, BoardAdapter)` was **False** — the implementation had no
`columns()`. The contract caught its own provider the same hour it was written.

### 3. The contract is derived from what the CORE calls, never from what a provider offers

`BoardAdapter` has five methods and `ChannelAdapter` has three, and both numbers are decisions.

The channel is the clearest case. Slack's runtime is ~1,500 lines — Socket Mode, threads, mrkdwn
conversion, pending confirmations, product-channel routing. The core asked it for exactly three
things across five call sites: *post this*, *how do I address this person*, *start listening*. A
protocol built from what Slack **can** do would be a Slack API in disguise, and Telegram would have
to fake half of it. Built from what the core **needs**, Telegram implements three methods.

Two obligations are written into the channel contract itself, because they are provider-independent
rules this codebase learned the hard way:

- `say` returns whether it landed and **never raises** — its callers are scheduled rounds, where an
  exception becomes a retry storm and a silence becomes an agent that appears to have nothing to say.
- `mention` **degrades to a plain name rather than guessing** — a wrong mention is worse than none:
  it makes one person read something irrelevant and leaves the right person never asked, while the
  thread looks answered.

### 4. Jira is real, and its differences are honoured rather than flattened

`tracker/jira.py` satisfies the same seventeen-method contract. Four differences mattered:

- **Refs are the provider's.** `CONT-412` vs `#412`; the framework never parsed refs, so both work.
- **ADF is walked as a tree.** Jira stores rich text as a document model; a description written with
  a panel or a table would come back EMPTY from a naive read — and that empty body is what the
  sizing gate would judge as "this ticket says nothing".
- **JQL is escaped.** The splitter's idempotency runs through `find_ticket`; a title containing a
  quote would break the query or, worse, match a different issue and make a re-run reuse the wrong
  child.
- **Transitions are configured, never invented.** Every Jira project has its own workflow. An
  unmapped state is a no-op with a warning. The buckets mirror the GitHub board's `STATUS_MAP`
  (todo · in_progress · in_review · needs_action · done), so an operator configuring Jira answers
  the same four questions a board answers with columns — not a second vocabulary.

### 5. What is deferred, and why that is not a gap

GitLab and Telegram are **not implemented**, by decision (the product owner: Slack is what a
professional client expects; GitLab later). **No stub adapters were created**, and that is the
important half: an empty `gitlab.py` that nothing exercises would be the thirteenth instance of
this repository's signature defect — built, tested, reached by nothing (see
`built-tested-reached-by-nothing`).

What ships instead is the preparation, and it is the part that costs:

    the seam dispatches             one row, not a sweep through the composition root
    nothing outside names a class   26 direct constructions routed, guarded by an AST test
    the contract is runtime-checked a future adapter cannot ship half-implemented unnoticed
    an unknown kind is an honest    `gitlab` fails at startup naming what IS supported
    error

Adding GitLab is then one module plus one row, against a suite that already knows how to hold it to
the same contract.

### 6. The CI kind defaults to the forge's

Nobody is on GitLab for code and GitHub Actions for CI. One value configures both; a deployment
that genuinely splits them says so explicitly with `forge.options.ci`. When GitLab CI lands, a
project that moved its forge gets the right observer automatically — rather than silently watching
the wrong system, where the symptom is a release that hangs in "verifying" and never errors.

## Consequences

**Good.** The claim on the tin is now structurally true rather than aspirational, and it is enforced
by tests instead of by intention. A client on Jira works today. A client on GitLab is a module, not
a project. And the seams paid for themselves immediately: routing every board read through one
place is what made the 303→1 point fix (below) a single change rather than three.

**A measured side effect worth recording.** Centralising the board read exposed that
`gh project item-list` bills **one request per card** — 303 GraphQL points on a 256-card board,
against a 5,000/hour installation ceiling, read every three minutes by the poller. The factory was
exhausting its own quota hourly, and the product role found the board unreadable at precisely the
moment somebody was talking to it. The hand-written paginated query costs **1**. Three doors read
that board — poller, product role, tech-lead bot — and only one had ever been fixed.

**Costs and open risks.**
- **Two providers is not portability.** Jira satisfies the contract and is unit-tested; it has not
  run against a live Jira instance. The contract is proven, the integration is not, and the first
  real deployment will find things — as the first real GitHub sweep did.
- **Known blockers for a live Jira deployment — the RUNTIME still speaks GitHub refs.** An audit
  traced them precisely; they are listed here so nobody discovers them as a sales-call surprise:
    - `api/app.py` validates issue ids against `^#?\d+$` — `CONT-412` is rejected at the API door;
    - several worker/box sites canonicalise refs as `f"#{issue.lstrip('#')}"` — `#CONT-412` in a
      REST URL loses everything after `#` (a fragment) and every call 404s;
    - the box's `_register` fabricates `ProviderRef(kind="github")` — `BoxConfig` does not carry
      the tracker kind, so inside the sandbox `build_tracker` always builds GitHub;
    - `machine.py` pickup vocabulary: a label with a space (illegal in Jira) and
      `set_assignees([github login])` where Jira wants an `accountId`.
  Fixing these means touching ref handling on durably-replayed workflow paths — deliberate work,
  scheduled before the first Jira client, not smuggled into a stabilisation pass.
- **A registry can rot into a lookup nobody uses.** The AST guard is what keeps it honest; if that
  guard is ever weakened, the seams decay silently back into direct construction.
- **The channel seam is narrow by design.** A future need the three methods do not cover (reactions,
  editing a posted message, file upload) means widening the contract deliberately — which is the
  correct cost, and much cheaper than a contract that guessed at them now.
- **Deferred is not free.** Every month GitLab and Telegram stay unimplemented, the seam is
  unverified by a second provider on those axes — the tracker axis is the only one where the
  abstraction has actually been tested by a real alternative.

## Addendum (2026-08-24): the role axis joins the table

The audit above graded the *provider* axes and took the harness registry as the model. The
registry has a second table beside `HARNESSES` — the **roles** (`ROLES` / `ROLE_MODELS`, ADR-0018)
— which this ADR never graded because it was not a provider: four rows, a dict literal, resolved
by name. Measured on 2026-08-24, that row failed the successor rule in [`docs/core/07`](../core/07-extensibility.md):
the harness beside it consulted the plug-in loader and the role did not, so a stranger's QA agent
could be built (`harness.<kind>`) but not *named* (`unknown role 'qa'` from a literal).

| axis | Protocol | implementations | dispatch | verdict |
|---|---|---|---|---|
| **role** | `RoleSpec` (a value, not a port) | executor · reviewer · techlead · product | registry + `role.<name>` entry point | extensible; the core resolves and shows an add-on role, it does not invoke it |

Nothing in the Decision above changes. The row is added so the table stays the inventory it
claims to be; the rules for what an add-on role may and may not be are ADR-0018's addendum.
