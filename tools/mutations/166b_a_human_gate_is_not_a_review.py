"""#166 (the `pr_open` half): a human merge gate is not a review."""

TEST = "tests/test_a_human_gate_is_not_a_review.py"
BASE = "openfactory/adapters/tracker/base.py"
MACHINE = "openfactory/orchestrator/machine.py"
GH = "openfactory/adapters/tracker/github.py"
GHP = "openfactory/adapters/tracker/github_project.py"
JIRA = "openfactory/adapters/tracker/jira.py"
NEUTRAL = "tests/test_tracker_is_vendor_neutral.py"

MUTATIONS = [
    ("the human gate goes back to the review column", BASE,
     '    if needs_person and state in _REVIEW:\n        return "needs_action"',
     "    pass"),

    ("…and the reverse: every review lands on a person, armed auto-merge included", BASE,
     '    if needs_person and state in _REVIEW:\n        return "needs_action"',
     '    if state in _REVIEW:\n        return "needs_action"'),

    ("a caller can talk a parked ticket out of needing anybody", BASE,
     "    if needs_person and state in _REVIEW:",
     "    if needs_person is False:\n        return \"in_review\"\n"
     "    if needs_person and state in _REVIEW:"),

    ("the default stops meaning what it meant", BASE,
     "    return STATE_KEYS.get(state)", '    return "in_review"'),

    # ── the engine's three sites ────────────────────────────────────────────────────────────────
    ("the human gate stops claiming a person", MACHINE,
     "                self._set_state(ticket, JobState.PR_OPEN, needs_person=True)",
     "                self._set_state(ticket, JobState.PR_OPEN)"),

    ("…and the armed auto-merge claims one", MACHINE,
     "        self._set_state(ticket, JobState.PR_OPEN, needs_person=False)\n        return None",
     "        self._set_state(ticket, JobState.PR_OPEN, needs_person=True)\n        return None"),

    ("the machine takes the distinction and drops it", MACHINE,
     "            self.tracker.set_state(ticket.id, state, reason=reason, "
     "needs_person=needs_person)",
     "            self.tracker.set_state(ticket.id, state, reason=reason)"),

    # ── the vendors ─────────────────────────────────────────────────────────────────────────────
    ("the GitHub tracker stops handing it to its board", GH,
     "            moved = self.board.set_status(\n                needs_person=needs_person,",
     "            moved = self.board.set_status("),

    ("the GitHub board reads the table around the resolver", GHP,
     "        from openfactory.adapters.tracker.base import column_key\n\n"
     "        key = column_key(state, needs_person=needs_person)",
     "        from openfactory.adapters.tracker.base import STATE_KEYS\n\n"
     "        key = STATE_KEYS.get(state)"),

    ("Jira does", JIRA,
     "        key = _column_key(state, needs_person=needs_person)",
     "        from openfactory.adapters.tracker.base import STATE_KEYS\n\n"
     "        key = STATE_KEYS.get(state)", NEUTRAL),
]
