"""The writers of a card's state that do not go through its door YET — each with why, and the slice
that moves it in (ADR-0055 D9).

THIS LIST MAY ONLY SHRINK. `tests/test_the_card_lifecycle_has_one_door.py` holds it under a
committed ceiling on its length and a baseline of its entries: a new writer outside the door fails
the suite until somebody raises the ceiling and widens the baseline in the same change, visibly, in
review. An entry whose call is gone fails too, so the list never claims a writer that moved in.

Keyed by `(file, function, call)`. Slice 1 (#412) moved the endings a person causes. Slice 2 (#413)
moved the job's park, settle, sweeps and adjust passes, and left twelve writers it did not reach.
Slice 3 (#414) moved filing, promotion, edits and the stale-pickup healer (its first part); a
split's children and parent, the gather's question, the ready-for-you tellings, the delivery's
loop and the factory's own impediment card (B1); the box's outcomes, which it hands back for the
worker to apply (D7) — its progress marks are admitted by rule, not named here (`BOX_WRITERS`) —
and the promise one card's filing opens (B2); and the last three delivery producers: the job's exit
and the weekly sweep announced a delivery beside the door, and since every way a card reaches Done
is a door transition whose `Loops("deliver")` announces it, they announce nothing — the sweep's
second chance is the door's converge, and the questions it closes are the product role's own.

#414 IS DONE BUT FOR ONE WRITER, below, and the reason it stays. A REQUIREMENT'S DELIVERY is one
promise over several cards: the breakdown files some of them and REUSES others — open cards the
requirement verified on the board, which no transition of theirs marks as joining it — and it opens
only once every card is known (`module._open_delivery`, after the last filing). No one card's
`filed` can carry it, an all-reused requirement has no transition at all, and the closed event set
(ADR-0055 D2) has no event for "a card joins a requirement's promise". Moving it needs that event,
which is an ADR change, not a slice of this one. D9's "empty" waits on it.
"""

from __future__ import annotations

OUTSIDE_THE_DOOR: dict[tuple[str, str, str], tuple[str, str]] = {
    # ── slice 3 (#414): the promise a requirement's filing opens ─────────────────────────────────
    # One card's promise opens with its `filed` since the door's `Loops("open")`; a requirement's
    # spans several cards — the breakdown files some and REUSES others, which no transition of
    # theirs marks — so no one card's filing can carry it, and the closed event set has no event
    # for "a card joins a requirement's promise"
    ("openfactory/product/followup.py", "deliveries_to_open", "open_loop"):
        ("the delivery a requirement's cards are owed (`filed`) — one promise over several cards, "
         "the reused ones among them, which no single card's filing can open alone", "3"),
}
