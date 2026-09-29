# ADR 0055 — A card has one lifecycle: one door for every change of its state, one table of what follows, one record of what happened

- **Status:** Proposed (design only — no code changes with this ADR; the slices below implement it)
- **Date:** 2026-09-29
- **Milestone:** 0.5.0. It is built on `main` after 0.4.2 is released: the slices touch the files
  the 0.4.2 fixes touch, and a lifecycle built beside unmerged fixes would be rebuilt on merge.
- **Relates to:**
  - ADR-0033, the decision kernel: `decide(state, event) -> [Effect]`. This record is its first real use, for the card. ADR-0033 is still Proposed and has no code.
  - ADR-0010, single-line strict: every non-progressing outcome parks.
  - ADR-0019 §5: cards land in Backlog, and a person spends.
  - ADR-0021 and ADR-0025, the open loop and delivery: the ledger.
  - ADR-0050: previews.
  - ADR-0051: the door, the semaphore, and events through the door.
  - ADR-0052, the owner's view: **D11 below amends its agenda**.
  - Issues: #411 (this record), and its slices #412, #413, #414. The defects that led here: #384, #393, #401, #405, #409.

## Context

On one working day of live use on a single deployment, a person hit five defects with one shape:

| What the person saw | Which consumer the change did not reach |
|---|---|
| The product role went on describing a card the person had removed (#393) | the product role's board snapshot |
| A discarded pull request left its card in *Needs Action* (#409) | the board column |
| The agenda kept "I will tell you when it is fixed" for a removed card and a discarded one | the product role's ledger |
| The product role said nothing when the card's pull request was ready for the person (#401) | the requester's conversation |
| The preview did not start when the pull request opened (#405) | the preview |

Each was fixed where it was found. The cause is not in any of those five places. **A card has no lifecycle of its own.** Every change of a card's state (filed, promoted, picked up, refused, pull request opened, parked, merged, delivered, discarded, skipped, stopped, closed, withdrawn, removed, reopened) is performed at its own call site. Each call site must remember every consumer of that change:
- the board column;
- the ledger's loops;
- the requester's conversation;
- the preview;
- a comment on the card;
- the caches of the board.

An inventory of the tree at the head of the 0.4.2 integration found the following.

**Where the writes live.** Card state is written from four processes (the box, the workflow, the worker's activities, and the panel's actions), through at least:
- nine different writers of the column (`set_state`, `set_column`, `close_ticket`, `remove_ticket`, `reopen_ticket`, `mark_needs_action`, `settle_ticket`, the box's `_set_state`, and PromotionRunner);
- three separate "one door" helpers (`_hold`, `_settle`, `withdraw_card`), each covering part of the space.

**Where the consequences are missing.** Of the matrix *event × consumer*, the inventory marks these gaps:

| Consumer | Events that do not reach it |
|---|---|
| **ledger** | discarded, skipped, stopped, closed, removed and reopened. A DELIVERY loop whose card will never ship stays open for ever. |
| **conversation** | discarded, skipped, stopped, closed (not through the product role), removed, reopened, promoted, parked |
| **preview** | skipped, stopped, closed, withdrawn, removed (it runs until its TTL), and adjusted (it is not rebuilt) |
| **cache** | every workflow and box write, and every write not done by the product module |
| **column** | a merge decision that is resumed leaves the card in *Needs Action* |

**Behaviour that depends on the tracker.**
- A state change's comment travels through `set_state(reason=…)`. GitHub and Azure DevOps write it, Jira writes it only for one state, and the local board never writes it. The "one comment saying who decided" is lost on two of four rows, and doubled on two others where a caller also comments.
- A `stop` terminates the workflow, and no journal line is written.

**Outright errors found by the same read.**
- The stale-pickup healer moves a card closed as *not planned* into **Done**.
- The card-question sweep puts a card back in *To Do* without checking whether the card is still open.

The inventory also found the templates for the fix, already in the tree:
- `ProductModule.withdraw_card` is the one place that fans a change out to tracker, cache and conversation.
- `product/events.py` has the idempotent, keyed, once-only notice (`_once`, `_event_id`).
- `JobWorkflow.run` → `record_outcome` is "the one exit" for a job.
- `TrackerAdapter.set_state` says it is "the one writer of its card's state", but the manual paths bypass it.

Nothing here is a storage problem. Every read measured on the live deployment is milliseconds: the board, the ledger, the transcript. A second database or a message broker would carry the same scattered calls to a new place. **The defect is that no code owns the question "what follows when a card changes?"**

## Decision

### D1. One door: `card_transition`

`openfactory/lifecycle/card.py`:

```python
transition(project, card, event: CardEvent, *, by, why="", facts=None) -> Transition
```

It is the only way a card changes state. `CardEvent` is a closed set, named from what happened, not from the column it lands in:

`filed` · `promoted` · `reordered` · `picked_up` · `refused` · `question_asked` · `question_answered` · `pr_opened` · `parked` · `resumed` · `adjusted` · `merged` · `delivered` · `accepted` · `discarded` · `skipped` · `stopped` · `closed` · `withdrawn` · `removed` · `reopened` · `edited`

`facts` carries what the event knows: the PR URL, the verdict, `delivered=True/False`, the note.

### D2. The door decides whether the event is allowed, before it decides what follows

`allowed(state, event) -> Refusal | None` is **pure**, and exhaustive over *(lifecycle state ×
`CardEvent`)*. The door asks it first, and a refused transition changes nothing and says why, in
the person's language.

Centralising the consequences alone would leave half the defect in place. Two of the three errors
the inventory found are **legality** errors, not missing consequences: the sweep that puts a closed
card back in *To Do*, and the healer that files a *not planned* card under Done. Today the rules
for "may this happen now?" are scattered exactly as the consequences are (`_stage_refusal`,
`has_started`, `_product_owned_refusal`, checks inside each action). They move into this table,
and the scattered checks become callers of it.

The lifecycle **state** the table reads is the card's own, derived from the record (D4), in a
closed set: `backlog` · `todo` · `running` · `waiting_on_a_person` · `delivered` · `closed` ·
`removed`. It is not the column's name, which is the tracker's spelling of it.

### D3. The consequences are a table, decided in pure code

`consequences(event, card) -> list[Effect]` is **pure** (ADR-0033): no I/O, and exhaustive over `CardEvent`. An `Effect` is one of:
- `Column(key)`
- `Close(delivered)`, `Remove`, `Reopen`
- `Comment(text)`
- `Loops(close=…, outcome=…)`, `Loops(open=…)`
- `Tell(requester|room, notice)`
- `Preview(start|stop|rebuild)`
- `Forget(board)`

The table is the one place a reader answers *"what happens when a card is discarded?"*. Every event has an entry, and "nothing" is written as an explicit empty list, never as an absent key.

An executor applies the effects through the existing ports:
- tracker: `set_state` / `close_ticket` / `remove_ticket` / `reopen_ticket` / `comment`;
- ledger;
- `events.py`, for notices through the door;
- the preview registry;
- the board-snapshot invalidation.

### D4. One record of what happened

Every transition appends one row, `kind="card_transition"`, to the product's store. The row carries:
- the event and its facts;
- who, why, and when;
- the column before and after;
- each effect with its outcome.

The row is keyed by an **event id**, so a retried activity or a double click is one transition, not two (#394's lesson).

Each row also carries the card's **sequence number**: the previous transition's, plus one. The panel's card history and the product role read this record. Today each derives the card's story from comments, columns and journal lines, which disagree.

### D5. One transition at a time per card, recorded first, converged after

**One at a time.** Two transitions can race on one card: a person closes it while its job ends.
The door writes the record row **only if no row holds that card's next sequence number**. This
is a conditional write, which the store's port gains (`record_if_absent`). The shipped SQLite
store does it with a plain insert. A store added from outside declares the capability, and one
that cannot do it is refused for this use, by name. The writer that loses re-reads the card's state and asks `allowed` again, against what
the winner made true. So a card has one history, in one order, and the second decision is judged
against the first, never applied beside it.

**Recorded first.** The transition is recorded before any effect is applied, and each effect is
keyed by *(event id, effect)*. A person's decision is never lost because the tracker blinked, and
a half-applied transition is visible, never silent.

**Converged after, and never backwards.** An effect that fails is recorded as failed, and the
hourly sweep re-applies failed effects idempotently, the way `events.py` already does for notices.
Before re-applying, the sweep checks that the effect's transition is **still the card's latest**.
If a newer transition exists, the late effect is marked `superseded` and is not applied. Without
this rule the sweep would move a card back to a column a person has since moved it out of, which
is the defect this record exists to end, produced by its own repair.

### D6. The comment is the door's, not the tracker's

`Comment(text)` is an explicit effect, written the same way on every row. `set_state` stops writing comments of its own. Today the comment exists on two of four trackers, and is doubled where a caller also comments.

### D7. Who calls the door

- **Actions** (panel, chat, CLI): the catalog rows call `transition`. `withdraw_card` becomes a caller, not a second door.
- **The workflow and the worker**: job endings (`record_outcome`, `_settle`, `_skip`, `mark_needs_action`, the merge-gate answers) call `transition` from an activity.
- **The box** runs remotely, possibly with no ledger and no conversation. Every **outcome** it
  reaches (refused, pull request opened, parked, merged) is handed back in its result and applied
  by the worker through the door. The box never tells a conversation or closes a loop.
- **The box's progress marks are not card events.** While a job runs, the card is in one
  lifecycle state, `running`. What the box writes meanwhile (`in_progress`, `repairing`,
  `reviewing`, `validating`) says how far the job is, for the board to show. Those writes stay in
  the box, through `set_state`, for a closed set of **progress states** the guard allows by rule
  (D9). They have no consequences, by definition: a write that needs one is an outcome, and goes
  through the door.

### D8. A change made outside the platform enters through the same door

On a hosted tracker a person can drag, close or delete a card in the vendor's own interface, and
no code of ours runs. The board sweep already reads the tracker; when it finds a card whose state
differs from its record's, it hands the door an **observed** event (`closed`, `reopened`,
`removed`, `promoted`… with `by="observed"` and the tracker's own actor when the row reports
one). The consequences then follow exactly as for a change made through the platform, minus the
write to the tracker, which already happened.

So the coherence this record promises holds for every row, and not only for the local board,
where every change is ours. A row that cannot report a kind of change (a deletion, on most hosted
trackers today) says so in its capabilities, and the record states what it cannot see.

### D9. The guard, and the three kinds of test

A test walks the tree. Outside `openfactory/lifecycle/`, it fails on any call that:
- writes a card's state (`set_state`, `set_column`, `close_ticket`, `remove_ticket`, `reopen_ticket`);
- opens or closes a ledger loop keyed to a card;
- produces a card notice.

It allows two things:
- the box's **progress marks** (D7), by rule: `set_state` with a state in the closed progress
  set, from the box;
- an explicit **exemption list**, each entry with its reason and the slice that removes it. The
  list may only shrink, and slice 3 ends with it empty.

A second test is **derived from the table**. For every `CardEvent`, it drives the door against doubles of every port and asserts that exactly the table's effects happened. So adding an event without deciding its consequences fails, and so does deciding a consequence nobody applies. The same derivation covers `allowed`: every *(state, event)* pair is either driven through the door or asserted refused.

A third kind of test is **the life of a card, on real parts**. Every defect in the Context table
was a defect *between* components that each passed their own tests. A suite on doubles would have
passed all five: the local board that writes no comment is a property of the real row, not of a
double of it. So each slice ships scenario tests that drive a card through a whole life (filed →
promoted → picked up → pull request → discarded → promoted again → merged → delivered; filed →
removed; pull request → closed outside the platform) against the **real local tracker, the real
ledger, the real event path and the real snapshot**, in two processes' worth of state, and assert
the story every consumer tells at each step. Doubles stand in only for what spends or leaves the
machine: the model, the forge, the container runtime.

### D10. What a cancellation means for a promise

Two groups of events end the work on a card, and they mean different things for what the product
role promised.

**The card is gone: `closed(delivered=False)`, `withdrawn`, `removed`.** The ledger gains an
outcome **`cancelled`**, and these events close the card's DELIVERY and CARD_QUESTION loops with
it. A DELIVERY loop that spans several cards closes only when its **remaining** cards are
delivered or cancelled. The requester is told, once, that the promise will not be kept, and why.

**The work stopped and the card is back in the backlog: `discarded`, `skipped`, `stopped`.** The
work is still possible, so nothing is cancelled. The loop stays open, labelled "back in the
backlog", until the card is delivered or cancelled. The requester is told, once, that the work
stopped and where the card is.

### D11. The agenda shows what the person must do (amends ADR-0052)

What the product role **owes** stays in its memory, the ledger. The panel shows it only as one line **on the card itself** (*"the product role will tell you in the conversation when this is delivered"*), because the person cannot act on it.

The tab becomes **Pending**: only what the product role **waits for from the person** (a decision, an answer, a "did it work?"). Each item names its card and opens the conversation or the card where it is answered.

## Slices

| Slice | What | Done when |
|---|---|---|
| 1 | The door, the record, the pure table, and the executor with its ports. The person-driven endings through it: `discarded`, `skipped`, `stopped`, `closed`, `withdrawn`, `removed`, `reopened`. `cancelled` loops. Preview stop on cancel. The conversation notice. Cache invalidation. The comment as the door's own. The Pending tab. The guard, with its exemption list. | Every live defect of the Context table has a table row and a derived test. The exemption list names only slice 2 and 3 writers. |
| 2 | **Every change to `JobWorkflow` is behind `workflow.patched`**, so a job in flight replays its old ending. Job endings through the door: `merged`, `delivered`, `parked`, `resumed` (a resumed merge decision leaves *Needs Action*), `pr_opened` (ready-for-you and the preview start move into the table), `refused`, `question_asked/answered` (the sweep checks the card is open). The stale-pickup healer no longer maps *not planned* to Done. `stop` writes its journal line. | The workflow and the worker hold no card write outside the door. |
| 3 | `filed`, `promoted`, `reordered`, `edited`. The box's outcomes are applied by the worker. `set_state` stops commenting. Observed events from the board sweep (D8). | **The exemption list is empty.** Only the box's progress marks remain, allowed by rule. |

## Consequences

- **The question "what follows when a card changes?" has one answer, in one file.** A consumer added later (a chat add-on, a hosted tracker's removal) is one column of the table and one port, not a hunt through four processes.
- **Every card has a history that agrees with itself**, because it is written by the only thing that changes it.
- **The cost:** every state change becomes a call to the door, and the job path pays one activity per outcome. The box's hand-back (D7) changes the shape of its result.
- **One port grows:** the store gains a conditional write (`record_if_absent`), declared as a
  capability.
- **What does not change:** the columns, the trackers, the storage engine, and the person's gestures. No new infrastructure.

## Not decided here

- Whether the record replaces the job journal (`record_outcome`'s lines), or only sits beside it. Slice 2 measures the overlap first.
- Which hosted rows can report a deletion or a transfer made in the vendor's interface (#389's
  review). D8 gives the event its door; each row's capability to observe it is that row's change.
- A person's edits to a card's text outside the platform, on a hosted row: whether `edited` is
  observed like the state changes of D8, or left to the tracker's own history.
