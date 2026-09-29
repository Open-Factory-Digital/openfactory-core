"""A discard at the merge gate settles the card like every other place a person stops the factory:
the job ends SKIPPED, the card goes back to the backlog, and one comment says who decided.

Run:  .venv/bin/python tools/mutate.py tools/mutations/409_a_discard_goes_back_to_the_backlog.py

Row 1 is the defect as it shipped: the discard returned ON_HOLD with nothing settled, so the card
stayed in Needs Action after the pull request was closed. Row 2 records the discard as nobody's
decision.
"""

TEST = "tests/test_the_merge_gate_is_heard_on_every_path.py"

WORKFLOW = "openfactory/runtime/temporal/workflow.py"

MUTATIONS = [
    ("TODAY'S DEFECT: a discard leaves the card in Needs Action with nothing said", WORKFLOW,
     '            if workflow.patched("a-discard-goes-back-to-the-backlog"):',
     "            if False:"),

    ("the discard is recorded as nobody's decision", WORKFLOW,
     "                                        said, by_a_person=True)",
     "                                        said, by_a_person=False)"),
]
