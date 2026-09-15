# Engineering lessons — the defects this codebase actually produces

Not style guidance. Each section below is a failure that **happened here**, more than once, with the
guard that now catches it. They are written down because every one of them was green-tested at the
moment it shipped, which is the only thing they have in common and the reason a checklist of "write
good tests" would not have prevented any of them.

Read this before adding a capability. It is short on purpose.

---

## 1. Built, tested, and reached by nothing

**Thirteen instances by 2026-07-28.** The signature defect of this repository.

A capability is designed, implemented, unit-tested, documented in an ADR — and called by no
production entry point. It is worse than a missing feature: a missing feature is obvious, while this
has green tests and a docs page, and surfaces only as an absence (a watcher that never reports, a
channel that stays quiet) which is indistinguishable from "nothing to say".

The roll of honour:

| what | how it presented |
|---|---|
| `ensure_techlead_watch` / `ensure_product_sweeps` | rounds and sweeps that would never fire, in any deployment, ever |
| `people.mention` | shipped with the product role, tested, called by nothing — every question went to the room instead of the person |
| `role.survey` + all of `brownfield.py` | a whole module with no entry point |
| the ADR-0021 question loop | inert on arrival: `followup.py` invented the triage vocabulary instead of reading it, and one of five codes happened to match |
| `deliveries_to_open` | closed by production code, opened by nothing — so "it's done" could never be said |
| the A/B arm balancer | reported `unavailable` for a chosen arm, so one treated ticket then controls for ever |

**The guard.** Reachability, not correctness: walk the call graph transitively from real entry
points (registered activities, workflow methods, routes, `main`, module-level code) and assert the
capability is reached. `tests/test_loops_are_reachable.py::_reachable` is the reusable
implementation.

**And the guard itself is subject to the defect.** That one needed FOUR versions, each killed by its
own sabotage test:

1. counted *mentions* — a docstring satisfied it
2. substring-matched — a call split across two lines escaped it
3. checked one step of reachability — a dead caller satisfied it
4. transitive call graph — the one that bites

> **Never trust a guard that has not failed a sabotage.** Green on the sabotage means the guard is
> broken, not the code. Every structural test in this repo should be provable this way, and the
> proof takes thirty seconds: break the thing on purpose, watch it go red, restore.

---

## 2. "Could not see" and "there is nothing" must never share a value

**Four instances**, and the most expensive class after §1, because it produces *confidently wrong
action* rather than inaction.

- `_columns()` returned `{}` both for an empty board and for a GitHub throttle. Under a rate limit
  every ticket lost its column, every column-based finding vanished from triage, and the product
  role read that absence as *"the world resolved them"* — closing open questions as `resolved`
  because of a quota error.
- `_queued_tickets` read the board with no token; the empty list it got back was indistinguishable
  from an empty TO-DO, so the tech-lead's idle-floor finding could never fire.
- The remedy ledger closed a loop on *"not parked right now"*, which is also what a failed state
  query and a job mid-agent-pass look like. One false `worked` poisons the give-up rule permanently.
- A role handed `{}` for the board would report "the board is empty" to a client.

**The rule.** `None` means *unreadable*, `{}` means *genuinely nothing*. Where the distinction is
load-bearing, say so in the docstring — three of these were reintroduced by someone simplifying a
"redundant" return.

**The corollary for outcomes: only POSITIVE evidence closes.** Absence is never a verdict. See
`techlead/memory.remedy_verdicts` for the truth table, including the row that says *no verdict* —
"same failure, different wording" must be neither credit nor blame.

---

## 3. A mock cannot fail an arity check

`handle.signal("act_on_impediment", "resume", "")` raised `TypeError` on **every attempt, in every
deployment** — `args` is keyword-only in the Temporal SDK. The tech-lead's single remediation, the
one ADR-0020 is built on, never once worked.

Invisible for two reasons at once: the handler logged no exception, and every test drove a fake
handle, which accepts whatever you pass it.

**The guard.** `tests/test_temporal_call_arity.py` binds each call site against the real
`inspect.signature`. Tests written entirely against fakes prove the logic and say nothing about
whether the call would execute.

---

## 4. A string-matching test can pin a bug in place

The test "covering" that same resume asserted the literal broken call text. It proved the source
contained certain characters — not that the call was callable — and it went green while the feature
was dead.

Same shape elsewhere: a guard that substring-matched `ast.unparse` output passed because a
**docstring** mentioned the name it was looking for.

**The rule.** Assert via AST (a `Call` node, a `Name` node the code evaluates, membership in the
real list object) or against a real signature. Never against source text that a comment can satisfy.

---

## 5. Write both sides of a boundary from the source, never from memory

`followup.py` invented the triage vocabulary — five plausible finding codes, of which triage emits
one — and read a `.code` attribute that `Observation` does not have. Fixture and code agreed with
each other and both were wrong about triage, so the tests were green while the loop was inert.

**The rule.** A fixture for another module's type **is** that module's type. And where one module
must know another's vocabulary, derive it from the source in a test:
`test_ASKABLE_speaks_triages_actual_vocabulary`.

---

## 6. Silence is a failure mode with a cost

**33 bare `except: pass` plus 32 handlers returning `None`/`[]`/`{}` after swallowing.** Notable
finds: the agent-token pool — today `OPENFACTORY_AGENT_TOKENS`, and
[ADR-0009](adr/0009-durability-and-resilience-hardening.md) §8 records the same incident under the
variable's name at the time — unreadable, falling back to a *single* credential, with no failover
and no warning; `to_todo = True` after a failed config read, a default that spends money.

*(A lesson names the variable a reader can go and set; the decision record names the one that was
there on the day. Restating the old name here would put two accounts of one event in the tree
disagreeing, and an ADR is history — it does not get edited to agree with a summary.)*

**The rule** (`tests/test_no_silent_failures.py`), aimed only at catch-all `except Exception` —
naming a specific exception is itself a statement that you expect it:

> A handler must **say something**, or **carry the exception onward** (a result object the caller
> reports is louder than a log), or **argue the silence in the source** with `# not-a-failure:`.

Two exemptions exist today, both "a stream carries non-JSON lines by design". Logging per line would
bury every real message under thousands.

---

## 7. Local green is not cloud working

Both of the worst defects this session were found by *running the thing in production*, not by any
test: the resume TypeError, and the board read exhausting its own quota. See
`validate-in-the-cloud-not-just-local`.

Cheap habits that pay: trigger the schedule by hand instead of waiting for it; measure the real API
cost with a before/after delta; read the actual logs after a deploy rather than assuming a rollout.

---

## 8. What the client reads is what the client GETS

*(The channel below is a chat connector, shipped as an add-on package — the lesson is that a
connector's own rendering rules are part of the boundary, and it does not become less true for
the panel, which is the surface that always exists.)*

- `**#478**` reached the channel with the asterisks printed: Slack renders `mrkdwn`, not Markdown.
  Nothing failed; it just looked like a broken bot.
- The product role's questions shipped the triage `detail` **verbatim** — English platform prose,
  two of the four containing words from the banned-jargon list.
- A chase said *"perguntei há dois dias"*, hardcoded, on a **weekly** schedule. Every reminder a
  client would ever read stated an interval that never happened.
- The first real sweep produced **thirteen questions in one burst**.

**The rules.** Convert at the boundary, not per author (two functions post to Slack; both convert).
Judge client-facing tests **after** that boundary — asserting on the raw string flagged a non-bug
and would have missed the real one. Compute intervals, never hardcode them: a message caught once in
a small lie discredits the true ones. And cap bursts counting what is *already open* — three new a
week on top of ten unanswered is the same flood arriving slowly.

---

## 9. Announce what happened, not what you intend

The channel read *"vou tentar de novo agora"* on a retry that had already failed. ADR-0020 names
this risk — "a confident wrong remedy is worse than no remedy" — and had no mechanism against it.

**The rule.** Act first, then report the outcome; pass results into the message builder rather than
predicting them. And keep **action decoupled from speech**: a failed resume once went six hours
without a retry because the *deduplication of messages* suppressed the finding. Whether to act is
the memory's decision; how often to talk about it is the channel's.

---

## 10. Measure the API cost before assuming it

`gh project item-list` bills **one request per card** — 303 GraphQL points on a 256-card board,
against a 5,000/hour ceiling, read every three minutes. The hand-written query costs **1**.

Nobody had looked. The measurement is four lines: read `rateLimit.remaining`, do the thing, read it
again.

**The rule.** Any call in a loop or on a schedule gets measured once, and the number goes in a
comment next to it. `tests/test_board_read_cost.py` then guards it — including the clause that
matters most, that the **agents are handed** the board rather than given the command to fetch it:
an agent with a terminal will reach for the expensive call, uncapped, as often as it feels like
looking.

---

## 11. A connection is a resource, not a derived value

`view.connect()` opened a fresh gRPC client to the durable engine on every call, and every read-side
caller resolves through it — `/api/floor` and `/api/floor/{project}`, one of which the panel page
re-reads on every engine frame (`panel.html::applyEngine`, so the SSE stream's 2 s tick plus a 20 s
safety refresh), plus `/api/inbox`, `/api/temporal/jobs`, `/api/decisions` and the action catalog.
Nothing released one.

Measured by the reporter on **2026-09-15** (GitHub issue #134), on a freshly restarted panel with
**no browser attached**:

| | |
|---|---|
| six sequential `/api/floor` requests | 20 → **32** open gRPC connections to the engine |
| the same panel overnight | **41** connections, 7-13 % CPU while idle |
| `/api/floor` at that point | **20-27 s** per request |
| the same `gather(EVERYTHING)` in-process | **0.18 s** |
| after a restart | ~2 s |

The route was not slow. The process was full. Nothing in the code looked wrong at any single call
site: `await connect()` is what every other caller writes, and the leak is only visible in the sum.

**Why it is not the caching ADR-0023 refused.** That record is about a *derived value*, where
recomputing is cheap and a stale copy is a wrong answer. A client is a **resource**: holding one
asserts nothing about the world, and the thing being avoided is not 0.3 s of CPU but an unbounded
socket count. The two decisions are not the same decision and should not be argued as one.

**The rule.** Anything that opens a socket on a request path names, in a comment beside it, either
where it is released or where it is reused. Neither is a detail: `temporalio` 1.33.0 exposes no
`close` on `Client` or on its service client at all (checked 2026-09-15), so "released" was never
available here — which is exactly why the fix is *stop opening them* rather than *close them*.

**And the reuse has to say which loop it belongs to.** The tech-lead's gatherer runs `asyncio.run`
once per question, so a pooled client is a client of a loop that has since closed; reuse that
ignores that trades a panel fix for a worker regression.
`tests/test_the_panel_holds_one_engine_client.py` drives all of it — N requests through the real
route, one client — and `tools/mutations/134_one_engine_client_per_panel.py` is the proof that the
guard can see each claim fail.

**Two things reuse takes away, both found in review (#145) by driving the pool rather than reading
the diff, both on 2026-09-15.** *A lock is single flight on success only.* Six concurrent callers
against a `connection.connect` that takes 0.5 s to refuse failed at 0.5/1.0/1.5/2.0/2.5/3.0 s —
each one took the lock, found no client and made the same failing attempt again — where the
unpooled code failed all six at 0.5 s. An outage is when that bites: the refusal is not 0.5 s but
the SDK's 40 s cap, and requests arrive faster than the queue drains. A pooled resource has to
share a FAILURE with the callers queued behind it, not only a success, and the one retained
exception is re-raised with `.with_traceback(None)` or it grows a frame per waiter (5 / 23 / 2003
frames after 1 / 10 / 1000 re-raises). *And reuse silently drops whatever the per-request path
re-read.* The pool key digested the TLS **paths**; `_auth()` reads the **contents**. Connecting per
request had re-read both files every time, so rewriting a cert in place at an unchanged path used
to be picked up and stopped being: `first b'CERT-BEFORE' | second b'CERT-BEFORE'`, where the
unpooled code showed the rotated bytes. What a cache is keyed on has to be what the work it skips
would have read.

---

## Repository conventions these produce

- **Comments say WHY, and name the incident.** "This costs 303 points, measured 2026-07-28" is
  worth ten lines of prose about efficiency.
- **Bounds are logged when hit.** A silent truncation reads as "that was everything".
- **Unknown kinds raise.** Falling back to a default runs the wrong provider under a clean-looking
  report (ADR-0018, ADR-0022).
- **Memory may only make the factory more cautious.** History withdraws a failed remedy; it never
  proposes one classification did not offer (ADR-0021 §4).
