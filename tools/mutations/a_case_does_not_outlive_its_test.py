"""A case does not outlive its test — the one cut that puts the CI flake back.

ROW 1 IS THE FIXTURE CLEARING NOTHING: the first test's intake is the second test's "latest open
case in this conversation", which is what `test_sweep_client_surface.py` met on CI.
"""

TEST = "tests/test_a_case_does_not_outlive_its_test.py"

MUTATIONS = [
    ("the fixture clears nothing — a case opened by one test is the next test's latest open case",
     "tests/conftest.py",
     "    with _case._LOCK:\n        _case._CASES.clear()\n        _case._LOADED.clear()\n"
     "        _case._THREAD_PROJECT.clear()\n",
     "    with _case._LOCK:\n        pass\n"),
]
