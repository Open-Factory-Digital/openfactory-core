"""#413, part 2, proven by breaking it — the job's park and settle go through the card's door.

WHAT WAS MEASURED, on `main` + #455 + #458:

  · on the local row a job settled DONE left its card OPEN in Done, and `Ticket.delivered` asks for a
    closed card, so the requester was never told "it is ready" until a person closed the card by
    hand — #411's inventory had marked it "to verify";
  · the job's settle of a skip a person had already made through the door wrote the card again,
    with a second comment on the rows that write `set_state`'s reason;
  · a park's reason travelled as `set_state(reason=…)`, which the local row drops;
  · a caller that handed the door only its tracker had no board read, so every card read as one no
    board places, where the table is permissive.
"""

TEST = "tests/test_the_life_of_a_card.py"
TABLE_TEST = "tests/test_the_card_lifecycle_does_what_its_table_says.py"
GUARD_TEST = "tests/test_the_card_lifecycle_has_one_door.py"

TABLE = "openfactory/lifecycle/table.py"
CARD = "openfactory/lifecycle/card.py"
PORTS = "openfactory/lifecycle/ports.py"
LOCAL = "openfactory/adapters/tracker/local.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"

MUTATIONS = [
    # re-pinned 2026-10-04: main's `move_card` (#506) replaced the inline close at Done (review of
    # #458)
    ("a local card settled DONE stays open, and its delivery is never announced", LOCAL,
     "            return move_card(conn, self.project, _number(ref), key, closes_at_done=True)\n",
     "            return move_card(conn, self.project, _number(ref), key, closes_at_done=False)\n"),

    # re-pinned 2026-10-04: the row announces what the card completes since #414's B1
    ("a delivered card is not moved to Done, so nothing closes it", TABLE,
     # re-pinned 2026-10-04: the comment is the caller's note when it has one (#414's B2)
     '        return (Column("done"), *_said(facts), Loops("deliver"), Forget())\n',
     '        return (*_said(facts), Loops("deliver"), Forget())\n'),

    ("the settle of a DONE job no longer goes through the door", ACTIVITIES,
     "    event = {JobState.SKIPPED: CardEvent.SKIPPED, JobState.DONE: CardEvent.DELIVERED}"
     ".get(state)\n",
     "    event = {JobState.SKIPPED: CardEvent.SKIPPED}.get(state)\n"),

    ("a park drops its reason", TABLE,
     '        said = (Comment(),) if facts.get("note") else ()\n',
     "        said = ()\n"),

    ("a park moves the card to the queue instead of where its state belongs", TABLE,
     '        return (Column(str(facts.get("job_state") or "on_hold")), *said, Forget())\n',
     '        return (Column("todo"), *said, Forget())\n'),

    ("a decision the job's own ending already carried out is refused again", CARD,
     "        if refusal is not None and acted and seen.state is after(event, {**(facts or {}),\n",
     "        if False and acted and seen.state is after(event, {**(facts or {}),\n",
     TABLE_TEST),

    ("a caller that hands only its tracker judges the card without its column", PORTS,
     # RE-PINNED 2026-10-02 (#414): a caller that hands `columns` has read its board already
     "        self._board_known = board is not None or columns is not None\n",
     "        self._board_known = True\n"),

    ("the ceiling is raised quietly, so the list can grow", GUARD_TEST,
     # RE-PINNED 2026-10-02 (#414): the ceiling is 16 since #414's first part
     # re-pinned 2026-10-04: and 1 since its B1 and B2, merged, and the last delivery producers (#414)
     # re-pinned 2026-10-04: and 0 since a requirement's promise goes through its cards' doors (#414)
     "CEILING = 0\n",
     "CEILING = 1\n",
     GUARD_TEST),
]
