"""#414 part A (ADR-0055 slice 3), proven by breaking it — filing, the operator's moves and edits go
through the card's door, `set_state` writes no comment on any row, and a change made in the
vendor's own interface enters as an observed event.

MEASURED on the stack's head (#469) before this part:

  - the product role's three filing writers, `promote`, and the board's `card_create` and
    `card_move` wrote the column themselves (`set_column`), so a filing or a queueing reached no
    record and forgot no snapshot through the door; `card_create` with no column named left a
    hosted issue on no board at all;
  - a person could drag a card into a column a job writes, or out of one a job holds, from the
    panel or the CLI, and nothing told the job;
  - `set_state(reason=…)` wrote a comment on GitHub and Azure DevOps, on Jira for one state, on the
    local board never — and every caller that passed one also commented;
  - a card closed on GitHub as not planned kept its requester's promise open for ever, nobody told
    them, and GitHub's `get_ticket` never asked WHY a card was closed, so the stale-pickup healer
    filed every closed card on that row as finished work.
"""

TEST = "tests/test_the_life_of_a_card.py"
TABLE_TEST = "tests/test_the_card_lifecycle_does_what_its_table_says.py"
ROWS_TEST = "tests/test_every_row_writes_only_the_doors_comment.py"
GUARD_TEST = "tests/test_the_card_lifecycle_has_one_door.py"
GH_TEST = "tests/test_a_delivered_card_is_closed_by_its_tracker.py"
MAINTENANCE = "tests/test_card_maintenance.py"

TABLE = "openfactory/lifecycle/table.py"
CARD = "openfactory/lifecycle/card.py"
OBSERVED = "openfactory/lifecycle/observed.py"
CATALOG = "openfactory/actions/catalog.py"
MODULE = "openfactory/product/module.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
BASE = "openfactory/adapters/tracker/base.py"
GITHUB = "openfactory/adapters/tracker/github.py"
AZURE = "openfactory/adapters/tracker/azure_devops.py"
JIRA = "openfactory/adapters/tracker/jira.py"
LOCAL = "openfactory/adapters/tracker/local.py"

MUTATIONS = [
    # ── 1. the table: filing, the operator's two columns, edits ────────────────────────────────
    ("a filed card is placed nowhere, so the queue can never see it", TABLE,
     "        return (*((Place(key),) if key else ()), Forget())\n",
     "        return (Forget(),)\n",
     TABLE_TEST),

    ("a card is filed into a column the factory writes, shown as started", TABLE,
     '    return str(key) if key in FILING_COLUMNS else ""',
     "    return str(key)",
     TABLE_TEST),

    ("a promotion places the card nowhere, so queueing it spends nothing and says it did", TABLE,
     '        return (Place("todo"), Forget())\n',
     "        return (Forget(),)\n"),

    ("a promotion is allowed out of a column a job holds", TABLE,
     "    CardEvent.PROMOTED: frozenset({State.BACKLOG, State.TODO, State.WAITING_ON_A_PERSON}),",
     "    CardEvent.PROMOTED: frozenset({State.BACKLOG, State.TODO, State.WAITING_ON_A_PERSON,\n"
     "                                   State.RUNNING}),",
     TABLE_TEST),

    ("a drag back to the backlog takes a card a job holds out from under it", TABLE,
     "    CardEvent.REORDERED: frozenset({State.BACKLOG, State.TODO}),",
     "    CardEvent.REORDERED: frozenset({State.BACKLOG, State.TODO, State.RUNNING}),"),

    ("an edit is allowed at the door after the factory read the card", TABLE,
     "    CardEvent.EDITED: frozenset({State.BACKLOG, State.TODO}),",
     "    CardEvent.EDITED: frozenset({State.BACKLOG, State.TODO, State.RUNNING}),",
     TABLE_TEST),

    ("the role's snapshot is not forgotten when a card is filed, the defect of #393", TABLE,
     "        return (*((Place(key),) if key else ()), Forget())\n",
     "        return (*((Place(key),) if key else ()),)\n",
     TABLE_TEST),

    ("the edit's note no longer says which parts moved", CATALOG,
     '        facts["note"] = card_edit_note(who=str(by), parts=changed,\n',
     '        facts["_note"] = card_edit_note(who=str(by), parts=changed,\n'),

    # ── 2. the board's rows and the product role's writers through the door ───────────────────
    ("card_move lets a person drag a card into the factory's columns", CATALOG,
     '    if key in ("backlog", "todo"):\n        return key, None',
     "    if key:\n        return key, None"),

    ("a parked card is queued by hand under a job still waiting on it", CATALOG,
     '    parked = event is CardEvent.PROMOTED and stage.key == "needs_action"',
     "    parked = False"),

    ("the product role files a card by writing its column itself again, beside the door",
     MODULE,
     "            placed = self._filed_through_the_door(str(ref), by=reported_by, "
     "tracker=tracker,\n"
     "                                                  board=board)\n"
     "            if not placed:\n"
     "                log.warning(\"OPENFACTORY_PRODUCT_TICKET_NOT_PLACED",
     "            placed = bool(board.set_column(issue=str(number), issue_url=url,\n"
     "                                           name=self.FILING_COLUMN))\n"
     "            if not placed:\n"
     "                log.warning(\"OPENFACTORY_PRODUCT_TICKET_NOT_PLACED",
     GUARD_TEST),

    ("a queueing the board refused is reported as queued", MODULE,
     '                if moved.outcome("place").startswith("placed"):',
     "                if True:",
     MAINTENANCE),

    # ── 3. one comment, the door's, on every row ──────────────────────────────────────────────
    ("GitHub writes the transition's reason as a comment of its own again", GITHUB,
     "        # `reason` IS NOT WRITTEN (ADR-0055 D6, #414): a transition's comment is the card's "
     "door's,\n",
     "        if reason:\n"
     '            self.comment(ref, f"[{state.value}] {reason}")\n'
     "        # `reason` IS NOT WRITTEN (ADR-0055 D6, #414): a transition's comment is the card's "
     "door's,\n",
     ROWS_TEST),

    ("Azure DevOps writes the transition's reason as a comment of its own again", AZURE,
     "        return bool(target)",
     "        if reason:\n"
     '            self.comment(ref, f"[{state.value}] {reason}")\n'
     "        return bool(target)",
     ROWS_TEST),

    ("Jira writes the reason for one state of all of them again", JIRA,
     '        self._call("POST", f"issue/{ref}/transitions", {"transition": {"id": match["id"]}})\n'
     "        return True",
     '        self._call("POST", f"issue/{ref}/transitions", {"transition": {"id": match["id"]}})\n'
     "        if reason and state == JobState.NEEDS_REFINEMENT:\n"
     "            self.comment(ref, reason)\n"
     "        return True",
     ROWS_TEST),

    ("the local board writes the reason too, the double comment on the one row that had none",
     LOCAL,
     "        return bool(changed)",
     "        if reason:\n"
     "            self.comment(ref, reason)\n"
     "        return bool(changed)",
     ROWS_TEST),

    ("the test of the four rows stops driving one of them, and still passes for the rest",
     ROWS_TEST,
     'ROWS = {"local": _local, "github": _github, "azure_devops": _azure_devops, "jira": _jira}',
     'ROWS = {"local": _local, "github": _github, "azure_devops": _azure_devops}',
     ROWS_TEST),

    # ── 4. a change made in the vendor's own interface (D8) ───────────────────────────────────
    # re-pinned 2026-10-04: the set of writes is public since #414's B1 (the executor reads it)
    ("an observed change writes the card again, after the vendor's interface already did", TABLE,
     "    kept = tuple(e for e in row if not isinstance(e, WRITES_THE_CARD))",
     "    kept = row",
     TABLE_TEST),

    ("an observed close is judged against the tracker, which already shows it, and refused", CARD,
     "        if observed:\n"
     "            # WHAT THE PLATFORM LAST KNEW",
     "        if False:\n"
     "            # WHAT THE PLATFORM LAST KNEW"),

    ("a closed card left in the queue stays there, re-logged every tick", TABLE,
     '    if event is CardEvent.CLOSED and str(facts.get("column") or "") == "todo":',
     "    if False:"),

    ("the board follows a close out of any column, which on Jira or Azure reopens a closed card",
     TABLE,
     '    if event is CardEvent.CLOSED and str(facts.get("column") or "") == "todo":',
     '    if event is CardEvent.CLOSED and str(facts.get("column") or "") != "":',
     TABLE_TEST),

    ("a card closed on the vendor's screen is never observed", OBSERVED,
     '    if held_open and not is_open:\n        if "closed" not in can or card in split:',
     '    if False:\n        if "closed" not in can or card in split:'),

    ("the close of a card some other card was split from is read as a withdrawal", OBSERVED,
     '        if "closed" not in can or card in split:',
     '        if "closed" not in can:'),

    ("a move into the queue on the vendor's screen is not observed", OBSERVED,
     '    if is_open and was is State.BACKLOG and key == "todo" and "promoted" in can:',
     "    if False:"),

    ("a row's declaration is ignored, so a card it cannot find is read as removed", BASE,
     "    return frozenset(str(x) for x in said) & OBSERVABLE",
     "    return OBSERVABLE"),

    ("a row that declares nothing is taken to observe everything", BASE,
     "    if not isinstance(said, set | frozenset):\n        return frozenset()",
     "    if not isinstance(said, set | frozenset):\n        return OBSERVABLE"),

    ("the hourly round never observes the board", ACTIVITIES,
     "    for line in observe(project):",
     "    for line in []:"),

    ("the healer files a split card's close as a withdrawal and cancels its promise", ACTIVITIES,
     "    if _children_safe(tracker, ref):\n"
     '        return "it was split, and its children carry its work — left where it is"',
     "    if False:\n"
     '        return "it was split, and its children carry its work — left where it is"'),

    ("GitHub's close leaves the card in its column, so a close of ours reads to the healer as "
     "one made outside", GITHUB,
     "        self._off_the_queue(ref, delivered=delivered)\n",
     "",
     GH_TEST),

    ("GitHub's read never says why a card was closed, so every close reads as finished work",
     GITHUB,
     '        ticket.state_reason = str(data.get("stateReason") or "").lower()\n',
     "",
     GH_TEST),
]
