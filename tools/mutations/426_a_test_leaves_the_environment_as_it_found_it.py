"""Every test leaves `os.environ` as it found it, whatever the code under test wrote (#426).

Run:  .venv/bin/python tools/mutate.py tools/mutations/426_a_test_leaves_the_environment_as_it_found_it.py

Row 1 is the defect as it shipped: nothing removes a variable the code under test added. Row 2 puts
nothing back that the code changed or removed. Row 3 takes the snapshot after the test instead of
before, which restores nothing.
"""

TEST = "tests/test_a_test_leaves_the_environment_as_it_found_it.py"

CONFTEST = "tests/conftest.py"

MUTATIONS = [
    ("TODAY'S DEFECT: a variable the code under test added outlives the test", CONFTEST,
     "        del os.environ[name]\n",
     "        pass\n"),

    ("a variable the code changed or removed is not put back", CONFTEST,
     "            os.environ[name] = value\n",
     "            pass\n"),

    ("the snapshot is taken after the test, so it restores nothing", CONFTEST,
     "    before = dict(os.environ)\n    yield\n",
     "    yield\n    before = dict(os.environ)\n"),
]
