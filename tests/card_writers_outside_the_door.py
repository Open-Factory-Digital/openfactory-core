"""The writers of a card's state that do not go through its door YET — each with why, and the slice
that moves it in (ADR-0055 D9).

THIS LIST MAY ONLY SHRINK. `tests/test_the_card_lifecycle_has_one_door.py` holds it under a
committed ceiling on its length and a baseline of its entries: a new writer outside the door fails
the suite until somebody raises the ceiling and widens the baseline in the same change, visibly, in
review. An entry whose call is gone fails too, so the list never claims a writer that moved in.

Keyed by `(file, function, call)`. Slice 1 (#412) moved the endings a person causes; slice 2 (#413)
moves the job's endings; slice 3 (#414) moves filing, promotion, edits and the box's outcomes, and
ends with this list empty.
"""

from __future__ import annotations

ACTIVITIES = "openfactory/runtime/temporal/activities.py"
MODULE = "openfactory/product/module.py"

OUTSIDE_THE_DOOR: dict[tuple[str, str, str], tuple[str, str]] = {
    # ── slice 2 (#413): the job's endings, from the workflow and the worker ─────────────────────
    (ACTIVITIES, "settle_ticket", "set_state"):
        ("the job's own settle — `skipped` and `delivered` at the merge", "2"),
    (ACTIVITIES, "_apply", "set_state"):
        ("`mark_needs_action`: a job parked on an impediment or a merge decision", "2"),
    (ACTIVITIES, "_child_to_todo", "set_state"):
        ("a split's children queued, on a tracker with no board", "2"),
    (ACTIVITIES, "_child_to_todo", "set_status"):
        ("a split's children queued, on the board", "2"),
    (ACTIVITIES, "_do_split", "close_ticket"):
        ("the split parent closed as not delivered: its work lives in its children", "2"),
    (ACTIVITIES, "_do_gather", "set_state"):
        ("a question to the requester before the plan: the card parks (`question_asked`)", "2"),
    (ACTIVITIES, "_do_gather", "open_loop"):
        ("the CARD_QUESTION that question opens (`question_asked`)", "2"),
    (ACTIVITIES, "_do_card_question_sweep", "set_state"):
        ("an answered question returns the card to the queue — without asking whether it is "
         "still open, one of the two errors the inventory found (`question_answered`)", "2"),
    (ACTIVITIES, "_do_card_question_sweep", "close_by_observation"):
        ("the CARD_QUESTION closed as answered (`question_answered`)", "2"),
    (ACTIVITIES, "scan_todo", "set_status"):
        ("the stale-pickup healer, which files a card closed as not planned under Done — the "
         "other error the inventory found", "2"),
    (ACTIVITIES, "_a_card_was_finished", "card_finished"):
        ("a job that ended with its card done announces the delivery (`delivered`)", "2"),
    (ACTIVITIES, "_product_followup", "deliver"):
        ("the weekly catch-all of the delivery announcement (`delivered`)", "2"),
    (ACTIVITIES, "_product_followup", "close_by_observation"):
        ("the weekly sweep closes the loops the board resolved (`delivered`)", "2"),
    (ACTIVITIES, "_tell", "ready_for_you"):
        ("a pull request a person must decide entered the merge watch (`pr_opened`)", "2"),
    (ACTIVITIES, "_pull_requests_waiting", "ready_at_the_gate"):
        ("the hourly round's catch-all of the same (`pr_opened`)", "2"),
    ("openfactory/product/events.py", "deliver", "close_by_observation"):
        ("a delivery announced closes its loop (`delivered`)", "2"),
    ("openfactory/ops/impediment.py", "resolved", "close_ticket"):
        ("the factory closes its own impediment card when the impediment is gone — a platform "
         "ending", "2"),
    # ── slice 3 (#414): filing, promotion, edits, and the box's outcomes ───────────────────────
    ("openfactory/orchestrator/machine.py", "_set_state", "set_state"):
        ("the box: its outcomes are handed back to the worker; its progress marks stay, by rule",
         "3"),
    ("openfactory/orchestrator/promotion.py", "_state", "set_state"):
        ("the box's promotion: merged, staged, released — outcomes handed back", "3"),
    ("openfactory/actions/catalog.py", "_open", "set_column"):
        ("a card opened on the board (`filed`)", "3"),
    ("openfactory/actions/catalog.py", "_card_move", "set_column"):
        ("a person moves a card between columns (`promoted`, `reordered`)", "3"),
    (MODULE, "file_ticket", "set_column"): ("the product role files a card (`filed`)", "3"),
    (MODULE, "file_defect", "set_column"): ("the product role files a defect (`filed`)", "3"),
    (MODULE, "_file_one", "set_column"): ("the product role files a requirement's card", "3"),
    (MODULE, "promote", "set_column"): ("the product role queues a card (`promoted`)", "3"),
    # one helper since #481 opens the delivery a defect and a card somebody asked for are owed
    (MODULE, "_follow_card", "open_loop"):
        ("the delivery a reported defect, or a card somebody asked for, is owed (`filed`)", "3"),
    ("openfactory/product/followup.py", "deliveries_to_open", "open_loop"):
        ("the delivery a requirement's cards are owed (`filed`)", "3"),
}
