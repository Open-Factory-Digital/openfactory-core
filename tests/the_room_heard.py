"""What the product role says without being asked, heard IN PROCESS — for a test about what is SAID,
not about the queue it waits in (#267 slice 3).

WHY THIS EXISTS. Every proactive message leaves the core through one function — `events._tell`,
which hands it to `door.announce`: recorded, then in line on its conversation. The suites that pin
what the sweep says (a delivery, a question, a chase) and what it remembers only when it was said
drove a channel double's `say`, and a double that returns False was how they said "the post did
not land". That double is still theirs: `through` hands it the door's side, so what the door was
told reaches `channel.say`, and a `say` that answers False is a door that did not take it.

WHAT IT IS NOT: a conversation. Nothing waits its turn here. The queue, and an event never
interleaving with a turn, are driven on an engine of their own in
`tests/test_events_and_the_agenda.py`.
"""

from __future__ import annotations


def through(monkeypatch, channel) -> list[dict]:
    """Hand what the product role tells to `channel.say`; returns every telling, as told —
    `{"id", "conversation", "text"}` — so a test can read WHERE each went."""
    told: list[dict] = []

    def _tell(project, *, id: str, conversation: str, text: str) -> bool:
        told.append({"id": id, "conversation": conversation, "text": text})
        return bool(channel.say(project=project, channel=conversation, text=text))

    monkeypatch.setattr("openfactory.product.events._tell", _tell)
    return told


def taken_at_the_door(monkeypatch) -> list:
    """The door TAKES everything the factory tells it — its enqueue stood in for (`door._admit`),
    everything before and after it real: `door.announce` records what it took in the product's
    memory. Returns every message the door took, as it took it. For a test about what the
    announcement leaves behind, not about the queue."""
    from openfactory.product import door

    taken: list = []

    async def _admit(message, **kw):
        taken.append(message)
        return door.Ack(accepted=True, id=message.id, conversation=message.conversation)

    monkeypatch.setattr(door, "_admit", _admit)
    return taken


def delivered_through_the_door(project, card: str, *, tickets, monkeypatch) -> str:
    """What a card's `delivered` transition does for the promises about it — its `Loops("deliver")`
    effect, the one announcer of a delivery since #414 — with the board a test says it read
    (`events._delivered_now` reads it fresh). Returns the effect's outcome as the door records it:
    `failed: …` when the board could not be read or the conversation did not take it, which the
    door's converge applies again.

    FOR THE SUITES THAT HELD THE ANNOUNCEMENT'S RULES WHEN THE WEEKLY SWEEP ANNOUNCED BESIDE THE
    DOOR: the sentence, the acceptance it opens, never twice, closed is not delivered. The rules
    are the announcement's; who reaches it is the door, whose wiring from a transition is held in
    `tests/test_the_life_of_a_card.py`."""
    from openfactory.lifecycle import loops
    from openfactory.lifecycle.executor import FAILED
    from openfactory.product import events
    from openfactory.product.triage import delivered_numbers

    monkeypatch.setattr(events, "_delivered_now",
                        lambda project: delivered_numbers(list(tickets or [])))
    try:
        return loops.announce_what_it_completes(project, card)
    except Exception as exc:  # noqa: BLE001 — recorded as the door records it
        return f"{FAILED}: {exc}"
