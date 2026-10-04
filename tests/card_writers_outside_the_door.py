"""The writers of a card's state that do not go through its door YET — each with why, and the slice
that moves it in (ADR-0055 D9).

THIS LIST MAY ONLY SHRINK. `tests/test_the_card_lifecycle_has_one_door.py` holds it under a
committed ceiling on its length and a baseline of its entries: a new writer outside the door fails
the suite until somebody raises the ceiling and widens the baseline in the same change, visibly, in
review. An entry whose call is gone fails too, so the list never claims a writer that moved in.

Keyed by `(file, function, call)`. Slice 1 (#412) moved the endings a person causes. Slice 2 (#413)
moved the job's park, settle, sweeps and adjust passes, and left twelve writers it did not reach.
Slice 3's first part (#414) moved filing, promotion, edits and the stale-pickup healer; its part
B1 moved nine of those twelve: a split's children (`filed`) and parent (`closed` as split), the
gather's question (`question_asked`), the ready-for-you tellings of the watch and the round
(`pr_opened`), the delivery's loop (`Loops("deliver")`, now the lifecycle's), and the factory's own
impediment card. What remains is slice 3's to finish: the three delivery producers below, which
wait on the box's outcomes, those outcomes themselves, and the promise a filing opens. #414 is done
when this list is empty (D9), and not before.
"""

from __future__ import annotations

ACTIVITIES = "openfactory/runtime/temporal/activities.py"
MODULE = "openfactory/product/module.py"

OUTSIDE_THE_DOOR: dict[tuple[str, str, str], tuple[str, str]] = {
    # ── left by slice 2 (#413), and by #414's B1: the delivery producers the box's outcomes hold ─
    #
    # THE CARD'S DOOR ANNOUNCES A DELIVERY since B1 — `delivered` and a close of finished work carry
    # `Loops("deliver")` — and these three still reach the announcement directly, for the one path
    # the door does not hold yet: the box's promotion writes Done itself (`promotion._state`,
    # below), so a card delivered at its last declared stage has no `delivered` transition, and the
    # job's exit is its only telling, with the weekly catch-all its only second chance. They leave
    # with that outcome, when the box hands it back to the worker through the door (#414's B2).
    (ACTIVITIES, "_a_card_was_finished", "card_finished"):
        ("a job that ended with its card done announces the delivery (`delivered`) — the only "
         "announcer of a delivery the box's promotion completed, until it is handed back", "3"),
    (ACTIVITIES, "_product_followup", "deliver"):
        ("the weekly catch-all of the delivery announcement (`delivered`) — the second chance of "
         "the promotion's delivery, until it is the door's and its sweep converges it", "3"),
    (ACTIVITIES, "_product_followup", "close_by_observation"):
        ("the weekly sweep closes the product role's QUESTION loops the board resolved; named "
         "because the function counts the DELIVERY rows the catch-all closed, and it leaves with "
         "the catch-all", "3"),
    # ── slice 3 (#414): the box's outcomes (its second part), and the promise a filing opens ────
    ("openfactory/orchestrator/machine.py", "_set_state", "set_state"):
        ("the box: its outcomes are handed back to the worker; its progress marks stay, by rule",
         "3"),
    ("openfactory/orchestrator/promotion.py", "_state", "set_state"):
        ("the box's promotion: merged, staged, released — outcomes handed back", "3"),
    # one helper since #481 opens the delivery a defect and a card somebody asked for are owed
    (MODULE, "_follow_card", "open_loop"):
        ("the delivery a reported defect, or a card somebody asked for, is owed (`filed`): "
         "opened beside the door until the promise a filing opens is the door's `Loops` effect",
         "3"),
    ("openfactory/product/followup.py", "deliveries_to_open", "open_loop"):
        ("the delivery a requirement's cards are owed (`filed`) — one promise over several cards, "
         "the reused ones among them, which no single card's filing can open alone", "3"),
}
