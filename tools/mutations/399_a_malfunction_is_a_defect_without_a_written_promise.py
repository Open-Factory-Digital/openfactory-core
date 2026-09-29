"""A malfunction is a defect whether or not a requirement names it (#399).

Run:  .venv/bin/python tools/mutate.py tools/mutations/399_a_malfunction_is_a_defect_without_a_written_promise.py

Row 1 is the defect as it shipped: a defect is what contradicts an accepted requirement. Row 2 drops
the sentence that stops "no requirement mentions it" being read as a wish. Row 3 drops the
malfunctions the role recognises. Row 4 lets a new capability be filed as a defect.
"""

TEST = "tests/test_a_malfunction_is_a_defect_without_a_written_promise.py"

ROLE = "openfactory/product/role.py"

MUTATIONS = [
    ("TODAY'S DEFECT: a defect is only what contradicts an accepted requirement", ROLE,
     '"DEFECT NEEDS NO WRITTEN REQUIREMENT: the promise every product makes is that it "',
     '"defect contradicts an accepted requirement: the promise every product makes is that it "'),

    ("\"no requirement mentions it\" may be read as a wish again", ROLE,
     '"it\\" is NOT a reason to call a malfunction a wish; when the person calls it a bug "',
     '"it\\" may mean it is a wish; when the person calls it a bug "'),

    ("the malfunctions the role recognises are no longer named", ROLE,
     '"or content cut off, hidden or unreachable, an error, lost or wrong data, something "',
     '"or content, something "'),

    ("a new capability may be filed as a defect", ROLE,
     '"requirement. Do NOT use the defect marker for a new capability or a change of "',
     '"requirement. Use the defect marker for anything they call a problem, even a change of "'),
]
