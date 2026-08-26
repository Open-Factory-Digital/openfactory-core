# ADR 0020 — The tech-lead is on call: classify by remedy, resolve what it can, speak while doing it

- **Status:** **Accepted; shipped.** Supersedes no ADR — it changes what "impediment"
  means in ADR-0010 and extends ADR-0015 from diagnosis to remediation.
- **Date:** 2026-07-27
- **Relates to:** ADR-0010 (park on any impediment — narrowed here), ADR-0015 (the tech-lead's
  diagnosis — extended), ADR-0012 (the rate-limit pause and resume — the proven precedent this
  generalises), ADR-0013 D4 (the effort budget — the shape a retry budget takes), ADR-0019 §6
  (requirement-caused parks belong to the product role).

## Context

On 2026-07-26 job #478 stopped because GitHub throttled the App installation. Throttling is the most
trivially self-healing failure a system can have: the window resets, and the same call succeeds. The
factory instead treated it as an impediment, parked the ticket, held the single-line floor for
**eighteen hours**, ran nothing else, and told nobody — the one Slack message for a park was a side
effect of a diagnosis that could not run, so the channel stayed silent.

Every part of that is a symptom of one thing: **the tech-lead reports, it does not resolve.**

It has four capabilities — size, advise, diagnose, chat — and all four are invoked by something
else. It never watches, never retries, never fixes. When a job stops it writes a good paragraph and
leaves. That is not a tech lead; it is a status report with a vocabulary.

And this is not a polish item. What the platform sells is that work continues without a developer
standing over it. A factory that stops all night on a rate limit does not fail to be clever — it
fails to be trustworthy, which is the only thing anybody is buying.

## Decision

**Classify every failure by WHAT RESOLVES IT, resolve the classes the factory owns, and say so while
doing it. A human is asked only for what a human can actually change.**

### 1. The taxonomy is the remedy, not the symptom

Today's classification is symptom-shaped and mostly implicit: `rate_limit` pauses and auto-resumes,
`auth` rotates a token, and everything else becomes an impediment for a person. The classes that
matter are the ones that differ in what fixes them:

| class | example | who resolves it |
|---|---|---|
| `transient` | API throttling, a network blip, a busy runner | **the factory** — wait the window, retry |
| `credential` | one token revoked or exhausted | **the factory** — rotate; escalate only if the whole pool is bad |
| `environment` | a missing permission, a broken image, a wedged dependency | a human, named, with the specific thing to change |
| `requirement` | the ticket is ambiguous or contradicts itself | the **product** role (ADR-0019 §6) |
| `code` | the change is genuinely wrong | a human engineer, with the diagnosis |
| `unknown` | it cannot tell | a human, told plainly that it cannot tell |

**`unknown` never degrades toward retry.** Retrying a failure nobody understands is how a token pool
gets burned on something structurally broken, and how a loop looks like progress. The bias is
always toward escalation, exactly as `observed` never degrades to `accepted` and `learned` never to
`confirmed`.

### 2. A cheap retry and an expensive retry are different decisions

This is the distinction that keeps autonomy from becoming spend.

- **Waiting costs nothing.** A throttled API call retried after its window consumes no agent, no
  tokens, no money. The bound here can be generous.
- **Re-running an agent costs a full pass.** A flaky gate, a failed execution, a timed-out run — each
  retry is real money, and three "helpful" retries on a ticket that was never going to pass is how a
  factory quietly triples its bill.

So the budget is per class, not global, and an expensive retry is always the smaller number. A
remedy that has not worked twice is not a remedy; it is a loop with a good story.

### 3. It watches the floor

Being invoked is not being on call. A schedule — the same shape as the product role's sweep — looks
for what no single diagnosis can see:

- a park nobody has answered for hours, holding the floor
- the floor idle while TO-DO is not empty
- the same failure recurring across different tickets, which is a systemic cause wearing three
  ticket numbers
- a job running far beyond its peers

The split with the product role is clean and worth stating: **she watches the BOARD, he watches the
FLOOR.** She cares whether the right things are queued; he cares whether the machine is moving.

### 4. It speaks while it works

"Isso é throttling do GitHub — tento de novo às 03h40" is the difference between a factory that
looks broken and one that is visibly handling something. A channel that goes quiet during an
incident teaches people to go and check the panel, which is the habit this whole layer exists to
remove.

And the inverse: when it gives up, it escalates with what it TRIED. "I retried twice after the
window and the limit is still exhausted; the App installation looks capped" is actionable.
"Impediment: box failed" is not.

### 5. What it may never do

- Resurrect work a human skipped. A person who pressed Skip has decided.
- Retry anything classified `unknown`, `code`, or `requirement`.
- Exceed its budget, silently or otherwise — an exhausted budget is itself an escalation.
- Touch production. Releases stay human-authenticated (ADR-0001 D-12), and nothing here changes it.

### 6. What "impediment" now means (narrowing ADR-0010)

ADR-0010 said: park on any impediment. That was right against the failure it was written for — jobs
completing while quietly abandoning a ticket. But "any non-progressing outcome parks" turned out to
include a class the factory can resolve alone, and parking those is not strictness, it is idleness
with paperwork.

The rule becomes: **park on any impediment the factory cannot resolve itself, and resolve the rest —
visibly, bounded, and never in silence.** Single-line strict is preserved: the floor is still held
by exactly one ticket, and a ticket still never completes without either progressing or parking.

## Consequences

**Good.** The most common stoppages — throttling, a bad credential, a transient runner failure —
stop consuming a human and stop consuming a night. The channel shows work being handled rather than
work having stopped, which is the thing a buyer is actually paying for. And the escalations that do
arrive are worth reading, because they are the ones nothing automatic could fix.

**Costs and open risks.**
- **Classification will be wrong.** Wrong toward retry wastes money and delays a real escalation;
  wrong toward escalation wastes a person's attention. The bias is deliberate and asymmetric, and
  the cheap-first ordering means the common misclassification costs a wait rather than a bill.
- **A retry loop is a spend loop.** Budgets are per class and every attempt is recorded; an
  exhausted budget escalates rather than resetting. This is the risk to instrument first.
- **New workflow commands need `patched()`.** Retries live in the durable workflow, which already
  carries jobs in flight — this codebase has been bitten by that before.
- **Recurrence detection needs memory across tickets**, which is a new read of the journal. Same
  shape as the product sweep's, and the same failure mode if it silently fails: it stops noticing
  patterns while appearing to work.
- **A confident wrong remedy is worse than no remedy.** "I fixed it" followed by the same failure is
  how an operator learns to ignore the channel. Every action says what it did and what it will do
  next if that fails.
