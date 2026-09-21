"""A staged proposal does not outlive its test — the isolation this suite was missing.

`product/staging.py::_PENDING` is keyed by conversation and twenty-five files share `C1`, so a
leftover proposal is judged as a confirmation of the NEXT test's sentence: one model call nobody
asked for, and `2 == 1` on CI (PR #261 run 502). The cuts break the reset, the call to it, and
each half of what it clears — and the pair guard's own vacuity is cut too, since a guard that can
pass having measured nothing is how this class survived.
"""

TEST = "tests/test_a_staged_proposal_does_not_outlive_its_test.py"
STAGING = "openfactory/product/staging.py"
CONFTEST = "tests/conftest.py"

MUTATIONS = [
    ("the reset forgets the proposals — the leak itself, back", STAGING,
     "        _PENDING.clear()\n        _EXPIRED_TOMBSTONES.clear()\n",
     "        _EXPIRED_TOMBSTONES.clear()\n"),

    ("…and the tombstones, so the next test's first yes is told 'that expired'", STAGING,
     "        _PENDING.clear()\n        _EXPIRED_TOMBSTONES.clear()\n",
     "        _PENDING.clear()\n"),

    ("the suite stops calling the reset, and every file's `C1` is shared again", CONFTEST,
     "    _staging._reset_for_tests()\n",
     "    pass\n"),

    ("THE REAL FAILURE, in the file that met it: the chat gesture is judged against a proposal "
     "an earlier test in the same process staged", CONFTEST,
     "    _staging._reset_for_tests()\n",
     '    _staging._PENDING.setdefault("C1", {"kind": "fact", "term": "erp", "body": "x",\n'
     '                                        "channel": "C1", "staged_at": __import__("time").time()})\n',
     "tests/test_accepting_what_the_code_already_does_files_nothing.py"),
]
