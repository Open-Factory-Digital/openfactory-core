"""The box's outcomes, handed back in its result and applied by the worker through the card's door
(ADR-0055 D7, #414).

THE DEFECT THIS ENDS. The box — the job's runner, on a remote machine, in a worker thread or under
`openfactory run` — wrote every state it reached on the card itself: a pull request opened, a
merge, a delivery, a refusal, a park. Those writes reached the board and nothing else. No record
of the card's life held them, the role's snapshot of the board did not forget, and the one writer
of a transition's comment could not be the door's while the box wrote its own (D6). The box cannot
call the door: it may run with no ledger, no conversation and no store of the record.

THE SPLIT, AND WHERE IT IS HELD.
    the box     writes its PROGRESS MARKS (`contracts/state.py::PROGRESS_MARKS`), which say how far
                a job is and have no consequences, and hands every other state back on its result
                (`RunResult.handed_back`, `orchestrator/outcomes.py`)
    the worker  the activity that ran the box — or the attended CLI, or the panel's in-process
                release — hands that result to `apply`, which takes each outcome through the door
                in the order the box reached it
    the guard   admits the box's `set_state` only under `if <state> in PROGRESS_MARKS`, and an
                outcome written from the box fails it (`test_the_card_lifecycle_has_one_door.py`)

WHAT EACH OUTCOME IS, in the card's life (`OUTCOMES`): a pull request is `pr_opened`, a merge
`merged`, Done `delivered`, a card the factory will not build as written `refused`, and every
other stop that waits on a person `parked` — a hold, a block, a failure, the production gate.
The promotion's `staged` and `released` are slice 4's (#448 slices 4–5); until then a production
gate is a park and a release that lands is a delivery, as the board already showed them.

NOTHING IS SAID TWICE. The box said each outcome on the card as it reached it (`_say_on_ticket`),
in words that carry the owner's mention and what to do next; so the door is handed an empty note
and writes no comment of its own, and the box's reason travels as a fact for the record.

A RESULT FROM BEFORE THIS, OR FROM AN OLDER BOX, carries `handed_back=None`: that box wrote its
outcomes itself, and nothing is applied — the worker does exactly what it did.
"""

from __future__ import annotations

import logging

from openfactory.contracts.state import JobState
from openfactory.lifecycle.table import CardEvent

log = logging.getLogger("openfactory.lifecycle.handed_back")

#: What each state a box can REACH is, in the card's life. A state not named here, and not a
#: progress mark, is one no box writes; it is logged and applied as nothing, never guessed.
OUTCOMES: dict[JobState, CardEvent] = {
    JobState.PR_OPEN: CardEvent.PR_OPENED,
    JobState.MERGED: CardEvent.MERGED,
    JobState.DONE: CardEvent.DELIVERED,
    JobState.NEEDS_REFINEMENT: CardEvent.REFUSED,
    JobState.ON_HOLD: CardEvent.PARKED,
    JobState.BLOCKED: CardEvent.PARKED,
    JobState.FAILED: CardEvent.PARKED,
    JobState.AWAITING_PROD_APPROVAL: CardEvent.PARKED,
}

#: Who the record says caused an outcome: the job, wherever its box ran.
BY = "the job"


def apply(project, card: str, result, *, event_id: str = "", tracker=None) -> list:
    """Take each outcome `result`'s box handed back through `card`'s door, in order, and stamp each
    with the id of the transition the door recorded. Returns the transitions.

    `event_id` is the caller's — the activity that ran the box, so a retried activity is answered
    from the card's record and never applies an outcome twice (D5); each outcome is that id and its
    place in the order. `""` lets the door derive one (a direct call: the CLI, the panel).

    NEVER RAISES: the job has ended and its result is the workflow's to act on; an outcome the
    door could not apply is logged, and a failed effect is the hourly sweep's to converge."""
    from openfactory.lifecycle.card import transition

    handed = getattr(result, "handed_back", None)
    if not handed:
        return []
    moved_all = []
    for index, back in enumerate(handed):
        event = OUTCOMES.get(back.state)
        if event is None:
            log.warning("OPENFACTORY_CARD_OUTCOME_UNKNOWN card=%s state=%s — the box handed back "
                        "a state that is no outcome; nothing applied", card, back.state)
            continue
        # the reason as the record's own, bounded like the workflow's notes: a merge the forge
        # refused carries the forge's whole sentence, and the box already wrote it on the card
        why = str(back.reason or "")[:400]
        facts: dict[str, object] = {"job_state": back.state.value, "note": "", "reason": why}
        if back.needs_person is not None:
            facts["needs_person"] = back.needs_person
        try:
            moved = transition(project, card, event, by=BY, why=why, facts=facts,
                               tracker=tracker,
                               event_id=f"{event_id}-{index}" if event_id else "")
        except Exception:  # noqa: BLE001 — see the docstring
            log.warning("OPENFACTORY_CARD_OUTCOME_UNAPPLIED card=%s event=%s — the box's outcome "
                        "could not go through the card's door", card, event.value, exc_info=True)
            continue
        if moved.refused:
            log.info("OPENFACTORY_CARD_OUTCOME_REFUSED card=%s event=%s — %s", card, event.value,
                     moved.refused[:200])
        elif moved.recorded:
            back.event_id = moved.event_id
        moved_all.append(moved)
    return moved_all


def recorded_park(result) -> str:
    """The id of the park the worker already applied for `result`, when its box handed it back —
    `""` for a park the workflow made itself, and for a result from before the hand-back.

    WHAT THE WORKFLOW HANDS `mark_needs_action`. That activity reconciles the board to a park the
    box could not write — a crash, a timeout. For a park the box DID reach, the worker applied it
    already, and with this id the door answers the reconcile from the card's record: one park, one
    row, nothing said twice. Pure: it reads the result and nothing else, so the workflow may call
    it."""
    state = getattr(result, "state", None)
    for back in reversed(getattr(result, "handed_back", None) or []):
        if back.state == state:
            return back.event_id
    return ""
