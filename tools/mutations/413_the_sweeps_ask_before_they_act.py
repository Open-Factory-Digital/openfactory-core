"""#413, part 1, proven by breaking it — the sweeps ask the card's door before they act.

WHAT WAS MEASURED (#411's inventory, read on `main` at f29b9bd):

  · the card-question sweep returned a card to TO-DO from the ledger alone, so a card closed — or
    removed — while its question waited was put back in the queue by the answer;
  · the stale-pickup healer moved every closed card to Done, so a card withdrawn as NOT PLANNED was
    filed as delivered work;
  · a stop terminated the workflow, which then never wrote its journal line.

The guards are the sweep's own tests, the life of a card on real parts, the table's tests and the
stop's.
"""

TEST = "tests/test_a_question_reaches_the_person_who_asked.py"
LIFE = "tests/test_the_life_of_a_card.py"
TABLE_TEST = "tests/test_the_card_lifecycle_does_what_its_table_says.py"
WEDGED = "tests/test_a_wedged_job_has_an_exit.py"

TABLE = "openfactory/lifecycle/table.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
LOCAL = "openfactory/adapters/tracker/local.py"
CATALOG = "openfactory/actions/catalog.py"

MUTATIONS = [
    ("an answer puts a card that is gone back in the queue", TABLE,
     "        if before in _GONE_STATES:\n            return (Loops(\"moot\"),)\n",
     "        if False:\n            return (Loops(\"moot\"),)\n"),

    ("an answer no longer returns the card it parked to the queue", TABLE,
     "            return (Column(\"todo\"), Comment(), Loops(\"answer\"), Forget())\n",
     "            return (Comment(), Loops(\"answer\"), Forget())\n"),

    ("an answer puts back in the queue a card somebody already moved on", TABLE,
     "        return (Comment(), Loops(\"answer\"))\n",
     "        return (Column(\"todo\"), Comment(), Loops(\"answer\"))\n",
     TABLE_TEST),

    ("the sweep moves the card itself again, around the door", ACTIVITIES,
     "        moved = transition(project, ref, CardEvent.QUESTION_ANSWERED, by=hit.author or \"\",\n",
     "        tracker.set_state(ref, JobState.TODO)\n"
     "        moved = transition(project, ref, CardEvent.QUESTION_ANSWERED, by=hit.author or \"\",\n"),

    ("the healer files every closed card under Done again", ACTIVITIES,
     "    return JobState.SKIPPED if withdrawn(ticket) else JobState.DONE\n",
     "    return JobState.DONE\n",
     LIFE),

    ("the local board stops saying how a card was closed, so withdrawn work goes to Done", LOCAL,
     "        ticket.state_reason = row[\"closed_reason\"] or \"\"\n",
     "",
     LIFE),

    ("a stopped job's journal ends one event short again", CATALOG,
     "    await asyncio.to_thread(_journal_the_stop, found, issue, by=by, why=why)\n",
     "",
     WEDGED),
]
