"""The writers of a card's state that do not go through its door YET — each with why, and the slice
that moves it in (ADR-0055 D9).

THIS LIST MAY ONLY SHRINK. `tests/test_the_card_lifecycle_has_one_door.py` holds it under a
committed ceiling on its length and a baseline of its entries: a new writer outside the door fails
the suite until somebody raises the ceiling and widens the baseline in the same change, visibly, in
review. An entry whose call is gone fails too, so the list never claims a writer that moved in.

Keyed by `(file, function, call)`. Slice 1 (#412) moved the endings a person causes. Slice 2 (#413)
moved the job's park, settle, sweeps and adjust passes, and left twelve writers it did not reach.
Slice 3's first part (#414) moved filing, promotion, edits and the stale-pickup healer. Its part
B1 moved nine of those twelve: a split's children (`filed`) and parent (`closed` as split), the
gather's question (`question_asked`), the ready-for-you tellings of the watch and the round
(`pr_opened`), the delivery's loop (`Loops("deliver")`, now the lifecycle's), and the factory's own
impediment card. Its part B2 moved the box's outcomes, which the box hands back in its result and
the worker applies through the door (D7) — the box's progress marks are admitted by rule, not
named here (`BOX_WRITERS`) — and the promise one card's filing opens, which the door's `filed`
opens with it (`Loops("open")`). What remains is slice 3's to finish: the three delivery producers
below and a requirement's delivery. #414 is done when this list is empty (D9), and not before.
"""

from __future__ import annotations

ACTIVITIES = "openfactory/runtime/temporal/activities.py"

OUTSIDE_THE_DOOR: dict[tuple[str, str, str], tuple[str, str]] = {
    # ── left by slice 2 (#413), and by #414's B1: the last direct delivery producers ──────────
    #
    # THE CARD'S DOOR ANNOUNCES A DELIVERY since B1 — `delivered` and a close of finished work carry
    # `Loops("deliver")` — and since B2 the box hands its promotion's Done back, so every way a job
    # delivers a card is a `delivered` transition. These three still reach the announcement
    # directly, beside it, until the change after B2 makes them the door's.
    (ACTIVITIES, "_a_card_was_finished", "card_finished"):
        ("a job that ended with its card done announces the delivery (`delivered`) — beside the "
         "door's own announcement, which now holds every way a job delivers a card", "3"),
    (ACTIVITIES, "_product_followup", "deliver"):
        ("the weekly catch-all of the delivery announcement (`delivered`) — a second announcer, "
         "until the door's sweep is the one second chance", "3"),
    (ACTIVITIES, "_product_followup", "close_by_observation"):
        ("the weekly sweep closes the product role's QUESTION loops the board resolved; named "
         "because the function counts the DELIVERY rows the catch-all closed, and it leaves with "
         "the catch-all", "3"),
    # ── slice 3 (#414): the promise a requirement's filing opens ─────────────────────────────────
    # One card's promise opens with its `filed` since the door's `Loops("open")`; a requirement's
    # spans several cards — the breakdown files some and REUSES others, which no transition of
    # theirs marks — so no one card's filing can carry it, and the closed event set has no event
    # for "a card joins a requirement's promise"
    ("openfactory/product/followup.py", "deliveries_to_open", "open_loop"):
        ("the delivery a requirement's cards are owed (`filed`) — one promise over several cards, "
         "the reused ones among them, which no single card's filing can open alone", "3"),
}
