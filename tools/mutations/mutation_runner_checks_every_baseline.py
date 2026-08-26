"""The mutation runner verifies EVERY target's baseline, not only the plan's default — proved by
cutting the runner itself and watching its own guard go red.

The runner under test is `tools/mutate.py`; the guard drives it as a subprocess on a throwaway
victim, so cutting the runner on disk is exactly what the guard's child process picks up. The
parent runner (the one executing this plan) loaded its own code before the cut and is unaffected.

Run: .venv/bin/python tools/mutate.py tools/mutations/mutation_runner_checks_every_baseline.py
"""

TEST = "tests/test_the_mutation_runner_is_not_decoration.py"

MUTATIONS = [
    ("only the plan's default target is verified — a row's own target is cut unseen",
     "tools/mutate.py",
     "    own = sorted({row[4] for row in mutations if len(row) > 4 and row[4]} - {default_test})\n"
     "    return [default_test, *own]\n",
     "    return [default_test]\n"),
    ("a red target is reported and then cut anyway",
     "tools/mutate.py",
     "            print(baseline.stdout[-2000:])\n"
     "            return 1\n",
     "            print(baseline.stdout[-2000:])\n"
     "            continue\n"),
    ("a red target is skipped silently and the plan proceeds",
     "tools/mutate.py",
     "        if baseline.returncode != 0:\n",
     "        if False:\n"),
]
