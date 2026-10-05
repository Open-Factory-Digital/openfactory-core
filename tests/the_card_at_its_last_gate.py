"""Where the card's door reads a card a test parked at its last gate — one name (#448 slice 6).

THE RELEASE QUESTION IS ANSWERED THROUGH THE CARD'S DOOR since #448 slice 6 (ADR-0055 amended
2026-10-05): the round's asking is `staged`, a "not yet" `stage_rejected`, a release `released`, and
the requester's yes their word does not release `accepted`. The door reads the card before it
decides anything, and refuses one nobody can read (`Ports.seen`, D2) — so a test about the
CONVERSATION or the ROUND, whose project has no tracker anybody could read (no `tracker:` in its
registry, a card number the job's id names), hands the door the one answer a real board gives for
a job parked at its production gate: open, in the column a person's gate is in.

A DOUBLE OF ONE READ, NOT OF THE DOOR: the record, the table, the ledger the question lives in and
the tellings stay real. A test about where the card is reads a real board instead
(`tests/test_the_requesters_loop_walks_through_the_door.py`).
"""

from __future__ import annotations

SEEN = "openfactory.lifecycle.ports.Ports.seen"


def at_its_last_gate(monkeypatch) -> None:
    """Every card the door reads in this test is open at its production gate (`needs_action`)."""
    from openfactory.lifecycle.ports import Seen
    from openfactory.lifecycle.table import State

    monkeypatch.setattr(SEEN, lambda self, card: Seen(state=State.WAITING_ON_A_PERSON))
