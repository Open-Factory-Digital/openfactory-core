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
`merged`, Done `delivered`, a card the factory will not build as written `refused`, a production
gate `staged` (#448 slice 6 — a park until then), and every other stop that waits on a person
`parked` — a hold, a block, a failure. A release that lands is the delivery at the last declared
stage; `released` is the person's yes before it, given through the door by whoever releases.

NOTHING IS SAID TWICE. The box said each outcome on the card as it reached it (`_say_on_ticket`),
in words that carry the owner's mention and what to do next; so the door is handed an empty note
and writes no comment of its own, and the box's reason travels as a fact for the record.

A PULL REQUEST A PERSON DECIDES IS ONE TRANSITION, keyed by the pull request (`gate_event`): the
box that opened it hands it back first, and the merge watch and the hourly round that tell its
requester (#401) hand the same event in after it, answered from the card's record. So the telling
travels with the box's outcome — the review's word read from the result (`verdict.of_result`), as
the watch read it from the workflow. A LATER PASS that brings the card back to the same gate — a
re-review, a repair the person must look at again, a job re-picked that finds its pull request
open — is a transition of its own: the box's progress marks moved the card meanwhile, and only a
new transition writes its column again. Its telling is answered once per card and pull request by
the conversation's own record (`events.ready_to_try`).

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
    # A PRODUCTION GATE IS A STAGE (#448 slice 6): the change waits there to be tried before it
    # reaches everyone, and the record says so — no column can (`table.READ_FROM_THE_RECORD`)
    JobState.AWAITING_PROD_APPROVAL: CardEvent.STAGED,
}

#: Who the record says caused an outcome: the job, wherever its box ran.
BY = "the job"


def gate_event(pr_url: str) -> str:
    """The id of `pr_opened` for one pull request a person decides — the box's hand-back, the merge
    watch's and the round's alike, so whichever hands it to the card's door after the first is
    answered from the record, never applied or told twice (D5)."""
    import hashlib

    return f"pr_opened-{hashlib.sha256(str(pr_url or '').encode()).hexdigest()[:20]}"


def merged_event(pr_url: str) -> str:
    """The id of `merged` as the job's TELLING hands it in (#448 slice 6) — the one hand that knows
    whether stages follow, so the one whose row tells the requester it went in. Keyed by the pull
    request, like `gate_event`: a retried or replayed telling is answered from the card's record,
    and the requester hears it once per card and pull request. The box's hand-back and the job's
    settle hand their `merged` in with ids of their own, and tell nobody."""
    import hashlib

    return f"merged-{hashlib.sha256(str(pr_url or '').encode()).hexdigest()[:20]}"


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
        own = f"{event_id}-{index}" if event_id else ""
        if event is CardEvent.PR_OPENED:
            facts.update(_at_the_gate(project, card, result, back, own))
        if event is CardEvent.STAGED:
            # WHICH STAGE AND WHERE A PERSON LOOKS, as the box read them from the manifest (#122)
            facts.update(stage=str(getattr(result, "look_stage", "") or ""),
                         where=str(getattr(result, "look_at", "") or ""))
        try:
            moved = transition(project, card, event, by=BY, why=why, facts=facts,
                               tracker=tracker, event_id=_this_outcomes_id(project, card, facts,
                                                                           own))
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


def _at_the_gate(project, card: str, result, back, own: str) -> dict:
    """What `pr_opened` tells the requester when a person decides the pull request (#401): the pull
    request the result names, the review's word from the same result the workflow's verdict query
    reads (`verdict.of_result`), and the live preview's link when one is already up (#405). `own`
    travels with it, so a retried activity finds its own transition (`_this_outcomes_id`). An
    armed merge waits on a build, not a person: nothing to tell, only where the card is."""
    pr_url = str(getattr(result, "pr_url", "") or "")
    if not (back.needs_person and pr_url):
        return {}
    from openfactory.review.verdict import headline, of_result

    seen = of_result(result)
    facts: dict[str, object] = {"pr_url": pr_url, "handed_back": own,
                                "review": str(headline(seen).get("stance") or "") if seen else ""}
    try:
        from openfactory.preview.live import link_for

        facts["preview_url"] = link_for(project, card)
    except Exception:  # noqa: BLE001 — a link is a courtesy; "start it from the card" is said
        log.info("no live preview's link for #%s", card, exc_info=True)
    return facts


def _this_outcomes_id(project, card: str, facts, own: str) -> str:
    """The id an outcome goes through the door with: the activity's own (`own`), so a retried one
    is answered from the record — EXCEPT the pull request a person decides, which is one event
    whoever hands it in (`gate_event`). That one is `own` again only when the card's record already
    holds the pull request's transition from ANOTHER hand-back: a later pass brought the card back
    to the same gate, and the column its progress marks moved must be written again."""
    pr_url = str(facts.get("pr_url") or "")
    if not pr_url:
        return own
    from openfactory.contracts.refs import canonical_ref
    from openfactory.lifecycle import record

    gate = gate_event(pr_url)
    try:
        held = record.read(record.keyed_sink(), getattr(project, "name", "") or "",
                           canonical_ref(card)).by_event_id(gate)
    except Exception:  # noqa: BLE001 — the door reads the record too, and says so if it cannot
        log.info("could not read #%s's record to tell a later pass from the first — the pull "
                 "request's own event is used", card, exc_info=True)
        held = None
    if held is None or (own and str((held.facts or {}).get("handed_back") or "") == own):
        return gate
    return own


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
