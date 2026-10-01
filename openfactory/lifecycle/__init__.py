"""A card has one lifecycle: one door for every change of its state, one table of what follows,
one record of what happened (ADR-0055).

THE DEFECT THIS PACKAGE EXISTS TO END. In one working day of live use, five defects had one shape:
a card changed state, and one of the things that depend on that state was not told — the product
role's snapshot of the board (#393), the board's column (#409), the role's promises, the
requester's conversation (#401), the preview (#405). Each was fixed where it was found. The cause
was in none of those places: every change of a card's state was performed at its own call site,
in four processes, through nine writers, and each site had to remember every consumer.

    the door         `card.transition` — asked first whether the event may happen, then records
                     it, then applies what follows
    the tables       `table.allowed` and `table.consequences` — pure; the one place a reader
                     answers "what happens when a card is discarded?"
    the record       `record` — one ordered row per transition, written only if no other
                     transition took the card's next number
    the executor     `executor.apply` through `ports.Ports`, and `executor.converge`, the hourly
                     sweep that applies again what failed — never backwards

NOT `test_the_lifecycle_names_no_provider`'s "lifecycle", which is the job's:
`orchestrator/machine.py` and the durable workflow. A job is one stretch of a card's life; this is
the whole of it.

Slice 1 (#412) moves the endings a person causes through the door; job endings (#413) and filing,
promotion and edits (#414) follow, and the writers they still own are named in one list that may
only shrink (`tests/card_writers_outside_the_door.py`).
"""

from __future__ import annotations

from openfactory.lifecycle.card import Transition, back_in_the_backlog, transition
from openfactory.lifecycle.executor import converge
from openfactory.lifecycle.table import CardEvent, State

__all__ = ["CardEvent", "State", "Transition", "back_in_the_backlog", "converge", "transition"]
