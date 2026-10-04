"""#414, its second part, proven by breaking it — the box hands its outcomes back and the worker
applies them through the card's door; one card's filing opens the promise it makes through it.

WHAT WAS MEASURED (the head of the ADR-0055 stack, 63c6ca9):

  · the box — `JobRunner._set_state`, `PromotionRunner._state` — wrote every state it reached on the
    card itself: the pull request, the merge, the delivery, the refusal, the park. Those reached the
    board and nothing else, and the exemption list named both writers;
  · `_follow_card` opened the delivery a defect or a card asked for is owed beside the door, and a
    promise the ledger refused was a line in the log.

THE CLAIMS, each a row below:

  · the box writes only its progress marks, and the guard admits exactly those (`PROGRESS_MARKS`);
  · every outcome is handed back on the result, with who the blocker is, by every public entry of
    both runners, and only what THIS call reached;
  · the worker — every activity that runs a box, and the attended CLI — applies each outcome
    through the door, as the event it is, once, in order, saying nothing the box already said;
  · the park it applied is the one the workflow's reconcile finds, by its id;
  · the table decides where `refused`, `pr_opened` and `merged` may happen and what follows;
  · one card's filing opens the promise it makes, once, and the hourly round opens one the ledger
    refused.
"""

TEST = "tests/test_the_box_hands_its_outcomes_back.py"
GUARD = "tests/test_the_card_lifecycle_has_one_door.py"
WORKFLOW = "tests/test_temporal_workflow.py"
PLAIN = "tests/test_a_plain_card_reaches_the_person_who_asked.py"

MACHINE = "openfactory/orchestrator/machine.py"
PROMOTION = "openfactory/orchestrator/promotion.py"
OUTCOMES_PY = "openfactory/orchestrator/outcomes.py"
STATE = "openfactory/contracts/state.py"
HANDED = "openfactory/lifecycle/handed_back.py"
TABLE = "openfactory/lifecycle/table.py"
EXECUTOR = "openfactory/lifecycle/executor.py"
PORTS = "openfactory/lifecycle/ports.py"
LOOPS = "openfactory/lifecycle/loops.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
WORKFLOW_PY = "openfactory/runtime/temporal/workflow.py"
CLI = "openfactory/cli.py"
MODULE = "openfactory/product/module.py"

MUTATIONS = [
    # ── the box ──────────────────────────────────────────────────────────────────────────────
    ("the box writes its outcomes on the card again", MACHINE,
     "        if state in PROGRESS_MARKS:\n            try:\n",
     "        if True:\n            try:\n"),

    ("the box writes its outcomes on the card again — and the walk finds it", MACHINE,
     "        if state in PROGRESS_MARKS:\n            try:\n",
     "        if state in PROGRESS_MARKS or state:\n            try:\n",
     GUARD),

    ("the box hands nothing back", MACHINE,
     "            vars(self).setdefault(\"_handed_back\", []).append(\n"
     "                HandedBack(state=state, needs_person=needs_person, reason=reason or \"\"))\n",
     "            pass\n"),

    ("the box forgets who the blocker of its pull request is", MACHINE,
     "                HandedBack(state=state, needs_person=needs_person, reason=reason or \"\"))\n",
     "                HandedBack(state=state, reason=reason or \"\"))\n"),

    ("the job's entries stamp nothing on their results", MACHINE,
     "for _entry in (\"run\", \"repair_ci\", \"review_pr\"):\n",
     "for _entry in ():\n"),

    ("a second call hands back what an earlier call reached", OUTCOMES_PY,
     "        self._handed_back = []\n",
     ""),

    ("the promotion writes its outcomes on the card again", PROMOTION,
     "        if state in PROGRESS_MARKS:\n            self.tracker.set_state(ticket_ref, state)\n",
     "        if True:\n            self.tracker.set_state(ticket_ref, state)\n"),

    ("the promotion's entries stamp nothing on their results", PROMOTION,
     "for _entry in (\"promote\", \"release_prod\"):\n",
     "for _entry in ():\n"),

    ("an outcome becomes a progress mark, written by the box", STATE,
     "    JobState.PAUSED,\n",
     "    JobState.PAUSED, JobState.ON_HOLD,\n",
     GUARD),

    # ── the worker ───────────────────────────────────────────────────────────────────────────
    ("a refusal is applied as a park", HANDED,
     "    JobState.NEEDS_REFINEMENT: CardEvent.REFUSED,\n",
     "    JobState.NEEDS_REFINEMENT: CardEvent.PARKED,\n"),

    ("the door says on the card what the box already said", HANDED,
     "\"note\": \"\", \"reason\": why}",
     "\"note\": why, \"reason\": why}"),

    ("two outcomes of one box share one transition id", HANDED,
     "                               event_id=f\"{event_id}-{index}\" if event_id else \"\")\n",
     "                               event_id=event_id)\n"),

    ("the result does not say which transition applied an outcome", HANDED,
     "            back.event_id = moved.event_id\n",
     "            pass\n"),

    ("the workflow is never handed the park the worker applied", HANDED,
     "        if back.state == state:\n            return back.event_id\n",
     "        if False:\n            return back.event_id\n"),

    ("the reconcile parks the card a second time", ACTIVITIES,
     "                           event_id=inp.event_id or _this_activitys_event(\"parked\"))",
     "                           event_id=_this_activitys_event(\"parked\"))"),

    ("the workflow drops the id of the park the worker applied", WORKFLOW_PY,
     "                                          event_id=recorded_park(parked)),\n",
     "                                          ),\n",
     WORKFLOW),

    ("the worker applies nothing the box handed back", ACTIVITIES,
     "    if not getattr(result, \"handed_back\", None):\n        return result\n    try:\n",
     "    if True:\n        return result\n    try:\n"),

    ("run_job no longer applies its box's outcomes", ACTIVITIES,
     "        lambda: _the_worker_applies(inp.project, inp.issue, applied,\n"
     "                                    _do_run_job(inp, run_id, watch=watch)),\n",
     "        lambda: _do_run_job(inp, run_id, watch=watch),\n"),

    ("repair_ci no longer applies its box's outcomes", ACTIVITIES,
     "        lambda: _the_worker_applies(inp.project, inp.issue, applied, "
     "_run_ci_repair(inp, run_id)),\n",
     "        lambda: _run_ci_repair(inp, run_id),\n"),

    ("adjust_pr no longer applies its box's outcomes", ACTIVITIES,
     "        lambda: _the_worker_applies(inp.project, inp.issue, applied, "
     "_run_adjust(inp, run_id)),\n",
     "        lambda: _run_adjust(inp, run_id),\n"),

    ("review_pr no longer applies its box's outcomes", ACTIVITIES,
     "        lambda: _the_worker_applies(inp.project, inp.issue, applied,\n"
     "                                    _run_review_pass(inp, run_id)),\n",
     "        lambda: _run_review_pass(inp, run_id),\n"),

    ("promote_staging no longer applies its box's outcomes", ACTIVITIES,
     "        lambda: _the_worker_applies(inp.project, inp.issue, applied, _run_promotion(\n"
     "            inp.project, inp.issue, \"staging\", {}, run_id, sandbox=inp.sandbox)),\n",
     "        lambda: _run_promotion(\n"
     "            inp.project, inp.issue, \"staging\", {}, run_id, sandbox=inp.sandbox),\n"),

    ("release_prod no longer applies its box's outcomes", ACTIVITIES,
     "        lambda: _the_worker_applies(inp.project, inp.issue, applied, _run_promotion(\n"
     "            inp.project, inp.issue, \"release\",\n",
     "        lambda: (lambda r: r)(_run_promotion(\n"
     "            inp.project, inp.issue, \"release\",\n"),

    ("the attended driver leaves the card at its last progress mark", CLI,
     "    the_outcomes_go_through_the_door(view, issue, result)\n",
     ""),

    # ── the table, the executor, the port ────────────────────────────────────────────────────
    ("a pull request a person decides is filed under review", TABLE,
     "        return (Column(\"pr_open\", needs_person=facts.get(\"needs_person\")), *_said(facts),\n",
     "        return (Column(\"pr_open\"), *_said(facts),\n"),

    ("a pull request is refused for a card the job is running", TABLE,
     "    CardEvent.PR_OPENED: frozenset({State.TODO, State.RUNNING, State.WAITING_ON_A_PERSON}),\n",
     "    CardEvent.PR_OPENED: frozenset({State.TODO, State.WAITING_ON_A_PERSON}),\n"),

    ("a merge is refused for a card the job is running", TABLE,
     "    CardEvent.MERGED: frozenset({State.RUNNING, State.WAITING_ON_A_PERSON}),\n",
     "    CardEvent.MERGED: frozenset({State.WAITING_ON_A_PERSON}),\n"),

    ("a refusal leaves the card nowhere the table knows", TABLE,
     "    if event in (CardEvent.PARKED, CardEvent.ADJUSTED, CardEvent.REFUSED):\n",
     "    if event in (CardEvent.PARKED, CardEvent.ADJUSTED):\n"),

    ("a delivery the box said comments an empty line on the card", TABLE,
     "        return (Column(\"done\"), *_said(facts), Forget())\n",
     "        return (Column(\"done\"), Comment(), Forget())\n"),

    ("the executor drops who the blocker is", EXECUTOR,
     "        return ports.column(row.card, effect.key, needs_person=effect.needs_person)\n",
     "        return ports.column(row.card, effect.key)\n"),

    ("the tracker port drops who the blocker is", PORTS,
     "                 self.tracker.set_state(card, state, needs_person=needs_person))\n",
     "                 self.tracker.set_state(card, state))\n"),

    # ── the promise one card's filing opens ──────────────────────────────────────────────────
    ("a filing opens no promise", TABLE,
     "        owed = (Loops(\"open\"),) if facts.get(\"owed\") else ()\n",
     "        owed = ()\n"),

    ("the executor opens a promise without what the filing carried", EXECUTOR,
     "            return ports.loops(row.card, effect.action, owed=dict(facts.get(\"owed\") or {}))\n",
     "            return ports.loops(row.card, effect.action)\n"),

    ("a promise already waiting is opened again", LOOPS,
     "    if subject in {x.subject for x in waiting(loop_store.read(name)) if x.kind == DELIVERY}:\n",
     "    if False:\n",
     PLAIN),

    ("a promise the ledger refused is said to be owed, and never opened", LOOPS,
     "        raise RuntimeError(\"the ledger did not take the promise\")\n",
     "        pass\n"),

    ("a card asked for in a conversation is filed owing nothing", MODULE,
     "                                                  board=board, owed=owed)\n",
     "                                                  board=board)\n"),

    ("a defect is filed owing nothing", MODULE,
     "                owed=self._track_defect(key, conversation=conversation, requester=requester))\n",
     ")\n"),

    ("the filing does not carry the promise to its door", MODULE,
     "                                      **({\"owed\": owed} if owed else {})},\n",
     "                                      },\n"),
]
