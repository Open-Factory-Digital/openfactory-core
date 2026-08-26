# ADR 0039 — The action layer: what a human can ask the factory to do, written once

- **Status:** **Accepted**
- **Date:** 2026-08-03
- **Implements:** C-23 (#51)
- **Relates to:** ADR-0010 (single-line strict / park on impediment), ADR-0022 (provider seams),
  ADR-0026 (two surfaces, same floor), ADR-0038 (the platform is complete; channels are add-ons),
  C-24 (#52), C-25 (#54), C-26 (#55), C-32 (#68).

## Context

The Slack bot never calls the HTTP API — zero `httpx`, `requests` or `aiohttp` anywhere in
`sdlc/runtime/slack/`. Both front ends were therefore written independently against the same
domain, and by August 2026 they had drifted in ways nobody chose:

| action | panel | Slack |
|---|---|---|
| `resume` | passes `choice` — the key of the option the parked job **offered** | hard-codes `""` |
| `skip` | ✓ | ✓ |
| `ack` (close a review finding) | — | ✓ |
| `enable`, `scan` | ✓ | — |
| `approve_prod` | two implementations, one durable and one in-process | — |
| the ticket ref | validated and normalised | passed through as typed |

The `resume` row is the one that matters most. A job parks with a `DecisionRequest` — a question
with two to four options — and posts it to the channel. The channel could then only resume it
**blindly**, because the parameter carrying the answer existed on the other front end.

The `#`-stripping row is the one that had a silent failure mode: `skip #250` and `skip 250` built
different Temporal workflow ids, and only one of them existed.

None of this is a bug anybody wrote. It is what happens when a capability has no home. It is also
the manifesto's empty SDK box: there was no layer for a third front end to be written against, so a
third front end would have made it three.

## Decision

**One table of actions.** `sdlc/actions/` holds every capability a human can ask for. Each row
takes values plus `by: Actor` and returns an `Outcome`. The front ends become mappings.

### 1. Values in, values out — never an exception, never a transport

```python
Outcome(ok: bool, message: str, data: Mapping, code: str)
```

`code` is a closed set: `invalid`, `denied`, `not_found`, `conflict`, `unavailable`, `failed`,
`unimplemented`. Each front end maps it to its own surface — an HTTP status, an emoji, a shell exit
code — and a test asserts every code has a row in **every** rendering table, because both lookups
are total and a missing row therefore reports a refusal as something else, silently.

`message` is one plain-text human sentence. No mrkdwn, no HTML, no provider link syntax: a message
pre-decorated for one surface renders as literal asterisks on the others.

**`ok` describes the platform, not the answer.** `scan` finding nothing in TO-DO is `ok=True` —
nothing went wrong, the queue is empty. Getting this backwards would make an idle factory look like
an outage in whatever reads these.

**`perform` never raises.** Both front ends already had a must-always-reply rule and both
implemented it by wrapping every call themselves. Doing it once means an action author cannot
forget, and means the real message survives: `first_message` walks `__cause__`/`__context__`,
because an error crossing a Temporal activity boundary otherwise arrives as the fixed string
`"Activity task failed"` (#66).

### 2. Every action takes who asked — and this layer does not yet decide

`Actor(id, display, via, admin)`. `admin` is answered **by the transport**: Slack knows
`project.admins`, the panel's answer is "did they hold the panel token", the CLI's is "they have a
shell on the host, which outranks every gate here". The layer *enforces* `needs_admin` and writes
one audit line per call — the first time this platform can answer *who approved that*.

This is deliberately half a design. **C-26 (#55) is where the decision itself moves into a policy
the Core owns.** Carrying it as a parameter now makes that a rename rather than a migration across
three front ends, which is the entire reason C-26 is scheduled after C-23 rather than before.

### 3. Two universal transports, so reachability is structural

```
POST /api/act/{name}     the panel, and anything holding its token
sdlc act <name> …        a shell where the factory runs
```

Both dispatch the whole catalog by name. A new action is reachable from both **the moment it is
catalogued**, rather than the moment somebody remembers to write a route and a verb for it — and
"the moment somebody remembers" is precisely the discipline that failed and produced this card.

The named paths (`/api/temporal/act`, `/api/projects/{n}/enabled`, the Slack verbs) keep their URLs
and their response shapes, because ADR-0010 publishes some of them and `panel.html` reads them.
They are mappings, and a test asserts each reaches the row it claims.

### 4. A surface may offer less than the catalog — that is policy, not a gap

An operator's Slack channel exposes `resume`, `skip`, `ack` and nothing else. A production release
genuinely *can* be driven from Slack — from the **product** channel, by the client, through
`product/release.py`'s own gate (ADR-0026) — and none of that is reachable from the tech-lead path.
The allow-list is a constant in the Slack package and its value is pinned by a test.

### 5. The messages are English

The tech-lead's channel speaks pt-BR today and these sentences read colder there. Accepted, on
ADR-0026's rule: the **client's** channel owes a voice, the **operator's** owes an answer. Terse and
technical is allowed there; silence never is. Writing every sentence twice, or building an i18n
layer, would be exactly the voice work that rule says to cut. A front end that wants warmth
decorates; it must not have to translate to be correct.

### 6. A not-yet-moved action is a row that refuses, not an absent row

Six of the ten are catalogued with a placeholder that returns `unimplemented` and **names where the
capability still works**. An action left out until somebody moves the code is invisible: no test can
assert it is missing and the migration has no measurable end. A row that refuses appears in the
panel's catalogue, in `sdlc actions`, and in a test — and its refusal is a sentence somebody can act
on, which is the same bar every other wait in this platform is held to (ADR-0038 D2).

## The guards, and why they are shaped this way

`tests/test_the_action_layer.py`. The acceptance criterion in #51 is a *reachability* guard, not a
behaviour test, because the card knew the failure mode in advance: this repository's signature
defect is a layer built, tested and reached by nothing — seventeen instances. A behaviour test on
`perform()` would have passed on day one with both front ends carrying on unchanged.

| guard | shape |
|---|---|
| **reachability** | every catalogued action, driven through the real FastAPI router **and** the real Typer app, parametrised over the whole catalog |
| **non-duplication** | no front-end module *uses* (attribute access or import — not its own definitions) a capability a moved action owns |
| **coverage of that table** | every moved action must be named as the owner of at least one marker, so the negative guard cannot silently stop covering the migration |
| **mapping** | each named legacy route reaches the row it claims |
| **bookkeeping** | every code has an HTTP status and a Slack mark; every declared parameter is one the runner accepts; the not-moved list matches what the catalog reports |

The second is a negative guard, so it has a positive twin by construction — the first. That pairing
is not decoration: ADR-0037 D4 shipped with `image=` missing from all four launch sites while a
guard forbidding the *wrong value* passed thirteen times, because absence has no pattern to scan
for.

## Consequences

- **`sdlc/api/temporal_view.py` moved to `sdlc/runtime/temporal/view.py`.** The filename was the
  lie: the Slack bot and `product/release.py` had both been importing "the panel's module". A guard
  that must carve out *a front-end file that is not really a front-end file* is a guard the next
  person deletes.
- **The panel gained `ack`; Slack gained ref validation and the shared parked-job check.** Both are
  fixes that fell out of having one implementation, not features anybody asked for.
- **#68 (a human-gated merge must be a question in the panel) is unblocked.** Its `merge` and
  `adjust` become rows here, which is the card's own stated requirement — *"build `merge` there or
  it exists twice and drifts, which is exactly how the two front ends came to disagree already."*
- **C-24 and C-25 get a target.** The conversational tech-lead leaving the Slack package means
  `ask` and `diagnose` stop being placeholders; the panel becoming a `ChannelAdapter` means the
  question side gets the same treatment the action side just got.
- **What this does not do:** it does not authenticate anybody (C-26), it does not move the
  tech-lead's brain (C-24), and four of the ten actions are still implemented in `api/app.py`. All
  three are visible in the catalog rather than in somebody's head.
