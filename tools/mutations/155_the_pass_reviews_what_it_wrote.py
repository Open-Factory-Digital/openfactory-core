"""#155: a repair pass reviews what it pushed, so the merge gate has a reading of the code in hand.

The stale marker from #153 stays as the fallback, and the reverses check that it does: a platform
that always looked fresh would be back where this pair of cards started.
"""

TEST = "tests/test_a_review_belongs_to_the_code_it_read.py"
WORKFLOW = "openfactory/runtime/temporal/workflow.py"
MACHINE = "openfactory/orchestrator/machine.py"
CONV = "openfactory/techlead/conversation.py"

MUTATIONS = [
    # ── the pass reads back what it wrote ───────────────────────────────────────────────────────
    ("the repair pass pushes and never reads it back — the original dead end", MACHINE,
     '            if self.reviewer is not None and self.manifest.review_mode != "off":\n'
     "                self._set_state(ticket, JobState.REVIEWING)\n"
     "                review = self.reviewer.review(",
     "            if False:\n"
     "                self._set_state(ticket, JobState.REVIEWING)\n"
     "                review = self.reviewer.review("),

    ("the reading is taken and dropped on the floor", MACHINE,
     "                auto_merge=True, total_cost_usd=rep.cost_usd, review=review,",
     "                auto_merge=True, total_cost_usd=rep.cost_usd,"),

    ("…and the reverse: it reviews even where the deployment turned review off", MACHINE,
     '            if self.reviewer is not None and self.manifest.review_mode != "off":\n'
     "                self._set_state(ticket, JobState.REVIEWING)\n"
     "                review = self.reviewer.review(",
     "            if self.reviewer is not None:\n"
     "                self._set_state(ticket, JobState.REVIEWING)\n"
     "                review = self.reviewer.review("),

    # ── the workflow publishes it ───────────────────────────────────────────────────────────────
    ("the adjust path keeps the stale marker instead of the fresh verdict", WORKFLOW,
     "        self._reviewed_again(passed)\n", ""),

    ("the CI-repair path keeps the stale marker instead of the fresh verdict", WORKFLOW,
     "                self._reviewed_again(rep)  # the pass's own reading of what it pushed (#155)"
     "\n", ""),

    ("a pass with no review is published as one, so the marker is lost for nothing", WORKFLOW,
     '        if getattr(result, "review", None) is None:\n            return False',
     "        if False:\n            return False"),

    # ── and the gates are not claimed ───────────────────────────────────────────────────────────
    ("the fresh verdict says nothing about the gates it did not run", WORKFLOW,
     '        if self._verdict is not None:\n'
     '            self._verdict = {**self._verdict,\n'
     '                             "gates_note": "the forge\'s own CI is the live check"}',
     "        if False:\n"
     "            pass"),

    ("…and the reader prints nothing where the gates used to be", CONV,
     '    if not gates and v.get("gates_note"):', "    if False:"),
]
