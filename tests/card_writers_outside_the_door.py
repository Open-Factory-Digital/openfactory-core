"""The writers of a card's state that do not go through its door YET — each with why, and the slice
that moves it in (ADR-0055 D9).

THIS LIST MAY ONLY SHRINK. `tests/test_the_card_lifecycle_has_one_door.py` holds it under a
committed ceiling on its length and a baseline of its entries: a new writer outside the door fails
the suite until somebody raises the ceiling and widens the baseline in the same change, visibly, in
review. An entry whose call is gone fails too, so the list never claims a writer that moved in.

Keyed by `(file, function, call)`. Slice 1 (#412) moved the endings a person causes. Slice 2 (#413)
moved the job's park, settle, sweeps and adjust passes, and LEFT the twelve writers below that it
did not reach: a split's children and parent, the gather's question, the delivery announcements
and the ready-for-you tellings. Slice 3's first part (#414) moved filing, promotion, edits and the
stale-pickup healer; its second moved the box's outcomes, which the box hands back in its result
and the worker applies through the door (D7) — the box's progress marks are admitted by rule, not
named here (`BOX_WRITERS`) — and the promise one card's filing opens, which the door's `filed`
opens with it (`Loops("open")`). What remains is slice 3's to finish (#414's second part): those
twelve, and a requirement's delivery. #414 is done when this list is empty (D9), and not before.
"""

from __future__ import annotations

ACTIVITIES = "openfactory/runtime/temporal/activities.py"

OUTSIDE_THE_DOOR: dict[tuple[str, str, str], tuple[str, str]] = {
    # ── left by slice 2 (#413), moved by slice 3's second part (#414): the job's endings ──────
    (ACTIVITIES, "_child_to_todo", "set_state"):
        ("a split's children queued, on a tracker with no board", "3"),
    (ACTIVITIES, "_child_to_todo", "set_status"):
        ("a split's children queued, on the board", "3"),
    (ACTIVITIES, "_do_split", "close_ticket"):
        ("the split parent closed as not delivered: its work lives in its children", "3"),
    (ACTIVITIES, "_do_gather", "set_state"):
        ("a question to the requester before the plan: the card parks (`question_asked`)", "3"),
    (ACTIVITIES, "_do_gather", "open_loop"):
        ("the CARD_QUESTION that question opens (`question_asked`)", "3"),
    (ACTIVITIES, "_a_card_was_finished", "card_finished"):
        ("a job that ended with its card done announces the delivery (`delivered`)", "3"),
    (ACTIVITIES, "_product_followup", "deliver"):
        ("the weekly catch-all of the delivery announcement (`delivered`)", "3"),
    (ACTIVITIES, "_product_followup", "close_by_observation"):
        ("the weekly sweep closes the loops the board resolved (`delivered`)", "3"),
    (ACTIVITIES, "_tell", "ready_for_you"):
        ("a pull request a person must decide entered the merge watch (`pr_opened`)", "3"),
    (ACTIVITIES, "_pull_requests_waiting", "ready_at_the_gate"):
        ("the hourly round's catch-all of the same (`pr_opened`)", "3"),
    ("openfactory/product/events.py", "deliver", "close_by_observation"):
        ("a delivery announced closes its loop (`delivered`)", "3"),
    ("openfactory/ops/impediment.py", "resolved", "close_ticket"):
        ("the factory closes its own impediment card when the impediment is gone — a platform "
         "ending", "3"),
    # ── slice 3 (#414): the promise a requirement's filing opens ─────────────────────────────────
    # One card's promise opens with its `filed` since the door's `Loops("open")`; a requirement's
    # spans several cards — the breakdown files some and REUSES others, which no transition of
    # theirs marks — so no one card's filing can carry it, and the closed event set has no event
    # for "a card joins a requirement's promise"
    ("openfactory/product/followup.py", "deliveries_to_open", "open_loop"):
        ("the delivery a requirement's cards are owed (`filed`) — one promise over several cards, "
         "the reused ones among them, which no single card's filing can open alone", "3"),
}
