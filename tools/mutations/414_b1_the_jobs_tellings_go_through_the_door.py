"""#414 part B1 (ADR-0055 slice 3), proven by breaking it — a job's tellings, splits, questions and
deliveries go through the card's door, and nine writers leave the list that may only shrink.

MEASURED on the stack's head (#484, `63c6ca9`) before this part:

  - a split's children were queued by `_child_to_todo` and its parent closed by `close_ticket`,
    beside the door: no record, no snapshot forgotten, and nothing said that the parent's close
    was a split and not a withdrawal;
  - the gather's question parked the card with `set_state` and opened its CARD_QUESTION loop by
    hand, so a retried gather had nothing to answer it from;
  - the watch and the round told the requester "ready for you" through `events.ready_for_you` and
    `ready_at_the_gate`, with no transition recorded for the pull request a person decides;
  - the delivery's loop was closed inside `events.deliver`, reached only by the job's exit and the
    weekly catch-all — a delivery the board could not be read for waited a week;
  - the factory closed its own impediment card with `close_ticket` and a comment beside it.

THE CLAIMS, one or more rows each:

  1. a split files its children where the project asked, once per activity, and closes its parent
     KEEPING its promise — and a parent that could not be closed fails the split;
  2. a question parks the card, then opens the loop its answer closes, once — and when the park
     does not land, no loop waits on the card and the sweep never parks it later;
  3. a card closed as finished work — by its job, a person or the vendor's screen — announces the
     deliveries it completes, follows a split card to its parent, and fails (so the hourly round
     applies it again) when the board cannot be read or the conversation does not take it;
  4. a pull request a person decides is told once, keyed by the pull request, whichever of the
     watch and the round hands it over first — only on a card the factory worked on, and a telling
     not taken is applied again;
  5. the factory's own card closes with its evidence, its record apart from the product's when it
     lives on another tracker;
  6. the door stays the only writer: a split child queued beside it, or the round telling beside
     it, fails the guard.
"""

TEST = "tests/test_the_life_of_a_card.py"
TABLE_TEST = "tests/test_the_card_lifecycle_does_what_its_table_says.py"
GATHER_TEST = "tests/test_the_factory_asks_before_it_starts.py"
SPLIT_TEST = "tests/test_a_card_that_was_split_is_not_delivered_until_its_children_are.py"
GUARD_TEST = "tests/test_the_card_lifecycle_has_one_door.py"

TABLE = "openfactory/lifecycle/table.py"
EXECUTOR = "openfactory/lifecycle/executor.py"
LOOPS = "openfactory/lifecycle/loops.py"
PORTS = "openfactory/lifecycle/ports.py"
EVENTS = "openfactory/product/events.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
IMPEDIMENT = "openfactory/ops/impediment.py"

MUTATIONS = [
    # ── 1. a split's children and its parent ───────────────────────────────────────────────────
    ("a split's children are filed in the backlog whatever the project asked, so the queue never "
     "sees them", ACTIVITIES,
     '                                     column="todo" if to_todo else "backlog")',
     '                                     column="backlog")'),

    ("a retried split files its children again, as a new transition each time", ACTIVITIES,
     '                       event_id=_this_activitys_event("filed"))',
     '                       event_id="")'),

    ("a split's parent is closed as GONE: its promise cancelled, its requester told it will not "
     "be built", TABLE,
     '        if facts.get("split_into"):\n',
     "        if False:\n"),

    ("a split whose parent could not be closed is reported done", ACTIVITIES,
     '    if closed.refused or closed.outcome("close").startswith("failed"):\n',
     "    if False:\n",
     SPLIT_TEST),

    # ── 2. the question before the plan ────────────────────────────────────────────────────────
    ("a question's loop opens beside a park that did not land", TABLE,
     "STOPS_AT_A_FAILED_WRITE: frozenset[CardEvent] = frozenset({CardEvent.QUESTION_ASKED})",
     "STOPS_AT_A_FAILED_WRITE: frozenset[CardEvent] = frozenset()",
     GATHER_TEST),

    ("a failed write stops nothing, so the question's loop opens anyway", EXECUTOR,
     "            if stops and outcome.startswith(FAILED) and isinstance(effect, WRITES_THE_CARD):\n",
     "            if False:\n",
     GATHER_TEST),

    ("the hourly sweep parks a card its job went on with", EXECUTOR,
     "    if _stops(row) and any(",
     "    if False and any(",
     TABLE_TEST),

    ("the question opens no loop, so its answer is never read", TABLE,
     '        return (Comment(), Column("needs_refinement"), Loops("ask"), Forget())\n',
     '        return (Comment(), Column("needs_refinement"), Forget())\n'),

    ("a question applied again opens a second loop", LOOPS,
     '        return "already waiting on an answer"\n',
     "        pass\n"),

    ("a question is asked on a card that is gone", TABLE,
     "    CardEvent.QUESTION_ASKED: frozenset({State.TODO, State.RUNNING, "
     "State.WAITING_ON_A_PERSON}),",
     "    CardEvent.QUESTION_ASKED: frozenset({State.TODO, State.RUNNING, "
     "State.WAITING_ON_A_PERSON,\n"
     "                                         State.CLOSED}),"),

    # ── 3. the delivery a finished card completes ──────────────────────────────────────────────
    ("a delivered card announces nothing: its requester waits for the weekly catch-all", TABLE,
     '        return (Column("done"), Comment(), Loops("deliver"), Forget())\n',
     '        return (Column("done"), Comment(), Forget())\n'),

    ("finished work closed by a person or on the vendor's screen announces nothing", TABLE,
     '            return (Close(delivered=True), Comment(), Loops("deliver"), Forget())\n',
     '            return (Close(delivered=True), Comment(), Forget())\n',
     TABLE_TEST),

    ("a split card's delivery is never followed to the card it was split from", LOOPS,
     '    mine = {_bare(card), split_parent_of(title)} - {""}\n',
     "    mine = {_bare(card)}\n"),

    ("a board that could not be read is taken for nothing to announce, and nobody tries again",
     LOOPS,
     '        raise RuntimeError("the board could not be read to see what it delivered")\n',
     '        return "the board could not be read"\n'),

    ("an announcement the conversation did not take is taken for said", LOOPS,
     '        raise RuntimeError(f"{missed} announcement(s) the conversation did not take")\n',
     '        return "not all announced"\n'),

    # ── 4. the pull request a person decides ───────────────────────────────────────────────────
    ("the watch and the round key the pull request apart, so the round decides it again", ACTIVITIES,
     "                       tracker=tracker, ports=ports, event_id=_gate_event(pr_url))",
     "                       tracker=tracker, ports=ports)"),

    ("the requester is never told the change is theirs to try", TABLE,
     "        return (Tell(READY_FOR_YOU), Forget())\n",
     "        return (Forget(),)\n"),

    ("a card nobody is working on is handed to its requester to try", TABLE,
     "    CardEvent.PR_OPENED: frozenset({State.RUNNING, State.WAITING_ON_A_PERSON}),",
     "    CardEvent.PR_OPENED: frozenset({State.BACKLOG, State.RUNNING, "
     "State.WAITING_ON_A_PERSON}),"),

    ("a telling the conversation did not take is taken for told, and nobody tries again", EVENTS,
     "preview_starts_itself=_preview_starts_itself(project)))):\n"
     '        return "told"\n'
     '    if said in _read(_store_path(project))["told"]:\n'
     '        return "told already"\n'
     "    raise RuntimeError(\"the conversation's door did not take it\")\n",
     "preview_starts_itself=_preview_starts_itself(project)))):\n"
     '        return "told"\n'
     '    if said in _read(_store_path(project))["told"]:\n'
     '        return "told already"\n'
     '    return "not told"\n'),

    ("the door's port says a change ready to try as a card that moved", PORTS,
     "        if notice == READY_FOR_YOU:\n",
     "        if False:\n"),

    # ── 5. the factory's own card ──────────────────────────────────────────────────────────────
    ("the factory's own card is recorded as the product's card with the same number", IMPEDIMENT,
     '    if declared is None or getattr(declared, "tracker", None) == getattr(project, "tracker", '
     "None):\n",
     "    if True:\n"),

    ("the impediment closes with the bare word, and the evidence that closed it is lost",
     IMPEDIMENT,
     '        note = "completed"\n        if evidence:\n',
     '        note = "completed"\n        if False:\n'),

    # ── 6. the door stays the only writer ──────────────────────────────────────────────────────
    ("a split child is queued beside its door again", ACTIVITIES,
     "    if moved.refused:\n"
     '        activity.logger.warning("split child %s: its door refused the filing (%s)", ref,\n',
     "    tracker.set_state(ref, JobState.TODO)\n"
     "    if moved.refused:\n"
     '        activity.logger.warning("split child %s: its door refused the filing (%s)", ref,\n',
     GUARD_TEST),

    ("the round tells the requester beside the door again", ACTIVITIES,
     "        events.pull_requests_at_the_gate(project, gates)\n    except Exception as exc:",
     "        events.ready_at_the_gate(project, gates)\n"
     "        events.pull_requests_at_the_gate(project, gates)\n    except Exception as exc:",
     GUARD_TEST),
]
