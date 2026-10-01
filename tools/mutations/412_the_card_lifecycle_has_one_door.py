"""#412, proven by breaking it — a card has one door, one table of what follows, one record
(ADR-0055, slice 1).

WHAT WAS MEASURED, on main at f29b9bd: a discarded pull request, a skip and a stop sent the card back
with a note the local board dropped (`LocalTracker.set_state` ignores `reason`) and told nobody;
a removed, withdrawn or closed card left its delivery open for ever and its preview running until
its TTL; the board's close, removal and reopen never forgot the role's snapshot; a reopen of an
OPEN card threw a card in progress into Backlog; and no record of any of it existed outside the
comments, which disagree between trackers.

EACH ROW REMOVES ONE CONSEQUENCE OR ONE REFUSAL, or blinds one guard. The guards are:

  tests/test_the_life_of_a_card.py                         a card's life on real parts
  tests/test_the_card_lifecycle_does_what_its_table_says.py the door against the tables, D5
  tests/test_the_card_lifecycle_has_one_door.py            the walk, the list, the ceiling
"""

TEST = "tests/test_the_life_of_a_card.py"
TABLE_TEST = "tests/test_the_card_lifecycle_does_what_its_table_says.py"
GUARD_TEST = "tests/test_the_card_lifecycle_has_one_door.py"

TABLE = "openfactory/lifecycle/table.py"
CARD = "openfactory/lifecycle/card.py"
EXECUTOR = "openfactory/lifecycle/executor.py"
PORTS = "openfactory/lifecycle/ports.py"
LOOPS = "openfactory/lifecycle/loops.py"
FOLLOWUP = "openfactory/product/followup.py"
AGENDA = "openfactory/product/agenda.py"
CATALOG = "openfactory/actions/catalog.py"
SQLITE = "openfactory/observability/sqlite_metrics.py"

_BACKLOG_ROW = '        return (Column("backlog"), Comment(), Tell(STOPPED_WORK), Preview("stop"), Forget())\n'
_GONE = '_GONE = (Comment(), Loops("cancel"), Tell(WILL_NOT_BE_BUILT), Preview("stop"), Forget())'

MUTATIONS = [
    # ── the rows: one consequence each ─────────────────────────────────────────────────────────
    ("a discarded pull request leaves its card where it was (#409)", TABLE,
     _BACKLOG_ROW,
     '        return (Comment(), Tell(STOPPED_WORK), Preview("stop"), Forget())\n'),

    ("the requester is never told the work on their card stopped (#401)", TABLE,
     _BACKLOG_ROW,
     '        return (Column("backlog"), Comment(), Preview("stop"), Forget())\n'),

    ("nothing on the card says who stopped the work or why — on the local board, nothing at all",
     TABLE,
     _BACKLOG_ROW,
     '        return (Column("backlog"), Tell(STOPPED_WORK), Preview("stop"), Forget())\n'),

    ("a card that is gone keeps the promise about it open for ever", TABLE,
     _GONE,
     '_GONE = (Comment(), Tell(WILL_NOT_BE_BUILT), Preview("stop"), Forget())'),

    ("the preview of a card that is gone runs until its TTL (#405)", TABLE,
     _GONE,
     '_GONE = (Comment(), Loops("cancel"), Tell(WILL_NOT_BE_BUILT), Forget())',
     TABLE_TEST),

    ("the role's snapshot of the board is not forgotten when a card leaves it (#393)", TABLE,
     _GONE,
     '_GONE = (Comment(), Loops("cancel"), Tell(WILL_NOT_BE_BUILT), Preview("stop"))',
     TABLE_TEST),

    ("a reopened card's promise stays cancelled", TABLE,
     '        return (Reopen(), Comment(), Loops("restore"), Tell(BACK_ON_THE_BOARD), Forget())\n',
     '        return (Reopen(), Comment(), Tell(BACK_ON_THE_BOARD), Forget())\n'),

    ("closing finished work cancels its promise and tells its requester it will not be built",
     TABLE,
     '        if facts.get("delivered"):\n            return (Close(delivered=True), Comment(), Forget())\n',
     '        if facts.get("delivered"):\n            return (Close(delivered=True), *_GONE)\n',
     TABLE_TEST),

    # ── the rows: one refusal each ─────────────────────────────────────────────────────────────
    ("a reopen of an OPEN card is allowed again, and throws a card in progress into Backlog",
     TABLE,
     "ONLY_ON_A_CLOSED_CARD: frozenset[CardEvent] = frozenset({CardEvent.REOPENED})",
     "ONLY_ON_A_CLOSED_CARD: frozenset[CardEvent] = frozenset()",
     # an open card in Backlog is refused by `ALLOWED` already; the rule is what refuses a
     # finished card nobody closed, which is open in Done
     TABLE_TEST),

    ("an event no slice has decided is allowed everywhere, with nothing decided to follow it",
     TABLE,
     "    **{event: frozenset() for event in CardEvent},",
     "    **{event: frozenset(State) for event in CardEvent},",
     TABLE_TEST),

    ("a card the factory finished is removed, erasing what was done and said on it (#384)", TABLE,
     "    CardEvent.REMOVED: frozenset({State.BACKLOG, State.TODO, State.RUNNING,\n"
     "                                  State.WAITING_ON_A_PERSON}),",
     "    CardEvent.REMOVED: frozenset({State.BACKLOG, State.TODO, State.RUNNING,\n"
     "                                  State.WAITING_ON_A_PERSON, State.DELIVERED}),",
     TABLE_TEST),

    # ── the door ───────────────────────────────────────────────────────────────────────────────
    ("a refused transition is applied anyway", CARD,
     "        if refusal is not None:\n            if acted:",
     "        if False:\n            if acted:",
     TABLE_TEST),

    ("the same event arriving again is decided again, and refused for what it already did (#394)",
     CARD,
     "        if again is not None:\n",
     "        if False:\n",
     TABLE_TEST),

    ("the transition that lost the race for the card's number is applied beside the winner's",
     CARD,
     "                if not record.write(sink, ports.name, row):\n"
     "                    continue          # another transition took this number: read, decide again\n",
     "                if not record.write(sink, ports.name, row):\n"
     "                    pass\n",
     TABLE_TEST),

    ("where the requester asked is read after the cancellation closed the loop that says it, so "
     "the room hears what was theirs", CARD,
     '        known.setdefault("conversation", ports.asked_in(card))\n',
     ""),

    # ── the executor and the sweep ─────────────────────────────────────────────────────────────
    ("a close's comment is written a second time beside the note the close itself leaves (D6)",
     EXECUTOR,
     '        return "carried by the close" if carried else ports.comment(row.card, note)\n',
     "        return ports.comment(row.card, note)\n",
     TABLE_TEST),

    ("the sweep applies an older transition's late effect, moving the card backwards", EXECUTOR,
     "            if row.seq != latest.seq or tuple(name_of(e) for e in effects) != row.effects:\n",
     "            if tuple(name_of(e) for e in effects) != row.effects:\n",
     TABLE_TEST),

    ("the hourly round never announces a delivery whose last card was cancelled, so it waits a "
     "week for the catch-all", EXECUTOR,
     "    if any(_narrowed(row, now=now) for history in histories.values() for row in "
     "history.rows):\n",
     "    if False:\n"),

    ("the sweep never applies what failed again", EXECUTOR,
     "        if outcome.startswith(FAILED) or (not outcome and not recent):\n",
     "        if not outcome and not recent:\n",
     TABLE_TEST),

    # ── the ports ──────────────────────────────────────────────────────────────────────────────
    ("a card's ending moves it to the queue instead of the backlog", PORTS,
     '        states = {"backlog": JobState.SKIPPED, "todo": JobState.TODO}\n',
     '        states = {"backlog": JobState.TODO, "todo": JobState.TODO}\n'),

    ("a card nobody asked for in a conversation is announced to the product's room", PORTS,
     "        if not opened_by and not conversation:\n",
     "        if False:\n"),

    # ── the promise ────────────────────────────────────────────────────────────────────────────
    ("a delivery shared by two cards closes as cancelled when one of them goes", LOOPS,
     "            if _issues(loop) - gone:\n",
     "            if False:\n"),

    ("a delivery whose remaining card was delivered waits for the card that was cancelled",
     FOLLOWUP,
     "        issues -= cancelled_cards(loop)\n",
     ""),

    # ── what the person sees (D11) ─────────────────────────────────────────────────────────────
    ("Pending lists what the role owes beside what waits on the person", AGENDA,
     "            if item.direction == AWAITED]",
     "            if True]"),

    ("a card new to the backlog is said to have had its work stopped — the first live run's "
     "finding", CATALOG,
     "                   and back_in_the_backlog(proj, card))\n",
     "                   and True)\n"),

    ("the card's line says the role will tell them, about a card nobody is working on", CATALOG,
     "                     in_backlog=backlog, language=getattr(proj, \"language\", None))",
     "                     in_backlog=False, language=getattr(proj, \"language\", None))"),

    # ── the store ──────────────────────────────────────────────────────────────────────────────
    ("the store's conditional write overwrites, so two racing transitions both land", SQLITE,
     '                    "INSERT INTO metrics (pk, sk, kind, ts, ticket, expires_at, data)"\n',
     '                    "INSERT OR REPLACE INTO metrics (pk, sk, kind, ts, ticket, expires_at, data)"\n',
     TABLE_TEST),

    # ── the guard ──────────────────────────────────────────────────────────────────────────────
    ("the walk stops seeing a promise about a card written outside the door", GUARD_TEST,
     "            elif name in LOOP_WRITES and fn is not None and _named(fn) & CARD_LOOPS:\n",
     "            elif False:\n",
     GUARD_TEST),

    ("the walk stops seeing a card's notice told outside the door", GUARD_TEST,
     '                  and isinstance(func.value, ast.Name) and func.value.id == "events"):\n',
     '                  and isinstance(func.value, ast.Name) and func.value.id == "nobody"):\n',
     GUARD_TEST),

    ("the ceiling is raised quietly, so the list can grow", GUARD_TEST,
     "CEILING = 25\n",
     "CEILING = 26\n",
     GUARD_TEST),
]
