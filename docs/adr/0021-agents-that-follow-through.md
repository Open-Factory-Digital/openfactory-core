# ADR 0021 — Agents that follow through: the open loop as the unit of memory

- **Status:** **Accepted; shipped.**
- **Date:** 2026-07-27
- **Relates to:** ADR-0019 (the product role), ADR-0020 (the tech-lead on call — this supplies the
  memory that ADR's remedies assumed), ADR-0015 (diagnosis), ADR-0014 (advisory review — a
  consequence of it is one of the loops below), ADR-0010 (park on any impediment).

## Context

The platform is sold as a factory that replaces the development and project function. Not a tool a
developer uses — the people. That claim survives or dies on three properties, and they are not
independent:

    memory        knowing what has already happened
    resilience    recovering from what goes wrong
    proactivity   acting before being asked

**Memory without resilience is note-taking. Resilience without memory is repeating the same mistake
with discipline. Proactivity without either is noise on a schedule.**

An audit of both judging roles on 2026-07-27 found the same defect in both, and it is not a missing
feature — it is a missing shape.

**The tech-lead.** Its entire memory was one number: how many distinct tickets had failed each way
lately. It could count, but not recognise. The per-ticket retry budget lived in the workflow's
memory and *died with the job*, so every ticket restarted it from zero. Nothing anywhere recorded
whether a remedy had ever worked — so a retry that has never fixed anything is indistinguishable
from one that always does, and the factory could pay for it on every ticket, for ever, with each
attempt looking like diligence.

**The product role.** Her memory is genuinely good where it was designed to be: requirements and
domain facts live in a git repository, versioned, attributed, reviewable. But she has no record of
what she *asked*. A question put to a person in the channel is fire-and-forget — if nobody answers,
it is simply gone, and the requirement it was blocking waits for ever with nobody aware. Nor does
she know whether a requirement she wrote became work, or whether that work shipped, so she can never
say "the thing you asked for is done" or "this has been stuck for three weeks".

**And a third case, observed the same day.** #478 merged with an advisory review that REJECTED it —
score 38, a critical finding stating the entire deliverable rested on a decision that was never
made. Advisory review is deliberate (ADR-0014); merging anyway is the design. Telling *nobody* is
not. That finding reached no channel, no ticket comment, and no person.

The common shape in all three: **these agents emit and forget.** They act, and nothing in the system
is left holding the question "and then what happened?"

## Decision

**An OPEN LOOP is the unit of memory. Every action that expects something back is recorded as open,
and closed only by OBSERVING the world — never by the actor reporting on itself.**

Not a log. A log is written and never read; this is written *in order to be read*, and every round
of every agent begins by reading it.

### 1. The shape

    opened    an agent did something that expects a response — a remedy, a question, a delivery
    chased    time passed and nothing came back, so somebody is reminded — bounded, never nagging
    closed    the world shows it resolved, with the outcome recorded

Four loops exist, one per real gap found:

| loop | owner | opened when | closed by observing |
|---|---|---|---|
| `remedy` | tech-lead | it retries or rotates on a parked job | the ticket is no longer parked on that signature |
| `finding` | tech-lead | something merges carrying a critical review finding | a person acknowledges, or a follow-up ticket exists |
| `question` | product | it asks a named person something it needs | the thing it asked about stops being a finding |
| `delivery` | product | a requirement becomes filed work | every issue that came from it is closed — then it says so, unprompted |

**Why the question loop does not close on a reply.** Closing on a Slack answer needs conversation
history, a token scope, and a rule for what counts as an answer — and it answers the wrong question.
A product owner does not care whether somebody typed back; they care whether the thing got fixed. A
ticket that gained its acceptance criteria is resolved whether or not anybody replied, and a polite
reply that changed nothing is not an answer at all.

**And a delivery closes only when ALL of its work is done.** Telling somebody their requirement is
delivered while half of it is still open is the fastest way to make every future "it's done"
worthless.

### 2. Outcomes are observed, never self-reported — and only POSITIVE evidence closes

An attempt writes itself down as `pending`. A later round resolves it by looking — and "looking"
means positive evidence, never absence. The first implementation read "not parked right now" as
"worked", and review produced two counterexamples the same day: a deploy mid-round makes the state
query fail, the ticket drops out of the parked set, and a still-broken remedy is credited a
success; or the resume simply un-parks the job for the ninety minutes its agent pass runs, and
every slow-recurring failure books `worked` for ever. One false `worked` poisons the give-up rule
permanently. The truth table (pure, tested row by row in `techlead/memory.remedy_verdicts`):

    parked, same signature           → did-not-work
    parked, same cause, new wording  → no verdict (string drift is neither credit nor blame)
    parked, different cause          → worked
    gone from the floor              → the workflow's terminal state decides, if it can be read
    running / unqueryable            → no verdict; absence is never an outcome

A kind with NO observable close — a review finding on a ticket that already merged has no reply to
read and no state change to watch — is closed by the one thing that genuinely means "somebody has
this": a person typing `ack #N`. Inventing an observation there would be a memory that lies.

This is the load-bearing rule. A remedy that grades its own homework is exactly what a memory exists
to stop believing, and "I fixed it" followed by the same failure is how an operator learns to ignore
the channel (ADR-0020 already names this risk; it had no mechanism against it).

`pending` is therefore not a failure state. It is an honest "we have not looked yet", and counting it
as either success or failure is where a memory starts lying.

### 3. The store is append-only

Resolving an attempt writes a second row rather than editing the first. History that can be revised
on a later pass is not history; it is an opinion with a timestamp. Folding takes the latest known
outcome per attempt, and a late-arriving `pending` can never un-resolve a settled one.

### 4. Memory may only make the factory MORE cautious

History can withdraw a remedy that has failed; it can never propose one that classification did not
offer, and it never shortens a wait. A memory that could talk the factory *into* acting would be a
way for a bad week to become a policy.

This is the same asymmetry the rest of the system already runs on: `observed` is not `accepted`,
`learned` is not `confirmed`, `unknown` never degrades toward action. **"It worked once" is not "it
works."**

Concretely: a remedy that has failed twice on the same signature with no successes stops being
offered, and the escalation says what was learned — "I have seen this on 4 tickets and resuming
resolved none of the 4" is somewhere to look; "I could not" is a shrug.

### 5. Chasing is bounded, and it names a person

An unanswered question is chased — once, after a real interval, addressed to the person who can
answer (`people.py` already resolves the mention, and falls back to a plain name rather than
notifying the wrong human). After that it becomes a visible open item rather than a repeated ping.

Two failure modes, and the design refuses both: a question that evaporates, and an agent that asks
the same thing every hour until somebody mutes the channel.

### 6. What is NOT in scope

- **No learned model, no embeddings, no summarisation of the past.** Everything read back is
  arithmetic over rows, so every claim the agents make about their own history is one a person can
  recount by hand. That is what makes "this never works" checkable rather than an impression.
- **No new authority.** Nothing here lets either role do something it could not already do. It lets
  them stop doing things that have never worked, and finish things they started.
- **The executor is untouched.** Its memory question is different (the knowledge layer, ADR-0017,
  and per-commit decisions) and mixing them would produce a worse answer to both.
- **The workflow's own self-heal keeps its in-job budget, deliberately.** `JobWorkflow`'s park
  path retries with a counter that dies with the job — and that boundary is chosen, not missed.
  Within one job the budget is small and bounded (and already halved when a retry costs an agent
  pass); across jobs, every resume goes through the rounds, which consult the durable history and
  withdraw remedies that have never worked. Injecting a history lookup into the in-flight park
  path would add a new command to a durably-replayed workflow (the `patched()` class of risk this
  codebase has been bitten by) to protect against at most a couple of bounded retries.
- **The reachability walk is permissive by construction.** Name-based call-graph merging errs
  toward "reachable", so it can miss a dead module whose function names collide with a live one.
  It is a guard against the twelve-times-observed defect (built, tested, called by nothing), not
  a proof of liveness — pairing it with sabotage tests is what keeps it honest.

## Consequences

**Good.** The tech-lead stops paying for remedies that do not work, and its escalations carry
evidence instead of apology. The product role stops losing questions, and can finally say the two
sentences a product owner exists to say: *this is stuck on you*, and *this is done*. A critical
finding on something that shipped reaches a person on the day it ships. All three are the same
mechanism, which is why they are one ADR and not three.

**Costs and open risks.**
- **A wrong signature groups unrelated failures.** Two different problems folded into one signature
  would let a success on A vouch for B. Signatures are therefore conservative — noise stripped,
  first 120 characters kept — and the counts are always stated with the ticket numbers so a person
  can see what was grouped.
- **Chasing can become nagging.** Bounded to one reminder by design; if that proves wrong the
  correct fix is a longer interval, never a second chase.
- **The store grows.** Bounded read (last 200 episodes) and the same telemetry table everything else
  uses. If it ever needs its own store, that is a migration, not a redesign.
- **Observation can be wrong.** A ticket that moved on for an unrelated reason is recorded as the
  remedy working. Accepted deliberately: the alternative is self-reporting, which is worse, and the
  error is conservative — it keeps a remedy available rather than withdrawing a good one.
- **The open list must be VISIBLE, or bounded chasing is abandonment.** Chasing stops at one
  reminder by design; the ledger answers continued silence with "a person looking at the list".
  That list is a real surface — the panel's `/api/loops/{project}` and the product role's status
  line — because a finding whose only close is a human `ack` needs a place where a human can see
  it is still open. Review found the first implementation had the policy and no list.
- **This memory must itself be reachable.** Nine capabilities in this codebase have been built,
  tested and called by nothing. Every loop here ships with a reachability guard asserting a
  production caller, because a memory nothing reads is the most convincing form of this defect.
