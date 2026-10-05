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
and the promise one card's filing opens (B2); the last three delivery producers: the job's exit
and the weekly sweep announced a delivery beside the door, and since every way a card reaches Done
is a door transition whose `Loops("deliver")` announces it, they announce nothing; and the last
writer, a REQUIREMENT'S DELIVERY — one promise over several cards, some the breakdown reused —
which needed an event ADR-0055 did not have. The ADR gained it (`promised`, amended 2026-10-04):
every card of the breakdown, filed or reused, carries the whole promise through its own door, and
the door's `Loops("open")` opens it once (`module._open_delivery`).

#414 IS DONE, AND SO IS D9's "slice 3 ends with it empty". Only the box's progress marks remain
outside the door, allowed by rule. The list stays, empty, so that a writer added later is a
visible change of the ceiling in review — never a quiet line here.
"""

from __future__ import annotations

OUTSIDE_THE_DOOR: dict[tuple[str, str, str], tuple[str, str]] = {}
