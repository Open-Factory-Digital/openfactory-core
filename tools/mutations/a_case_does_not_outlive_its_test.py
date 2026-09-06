"""A case does not outlive its test — the cuts that put the CI flake back, both halves.

ROW 1 IS THE MEMORY HALF: the fixture resets nothing, and the first test's intake is the second
test's "latest open case in this conversation" — what `test_sweep_client_surface.py` met on CI.
ROW 2 IS THE DISK HALF: every test journals to the default directory, so where that is writable
(root, `/work`) a case persisted by one test — or by an earlier run — comes back through the clear.
"""

TEST = "tests/test_a_case_does_not_outlive_its_test.py"

MUTATIONS = [
    ("the fixture resets nothing — a case opened by one test is the next test's latest open case",
     "tests/conftest.py",
     "    _case._reset_for_tests()\n    own = hashlib",
     "    own = hashlib"),

    ("every test journals to the default directory — a persisted case comes back through the clear",
     "tests/conftest.py",
     '    monkeypatch.setenv("OPENFACTORY_LOG_DIR",\n'
     '                       str(tmp_path_factory.getbasetemp() / "openfactory-logs" / own))\n',
     '    monkeypatch.delenv("OPENFACTORY_LOG_DIR", raising=False)\n'),
]
