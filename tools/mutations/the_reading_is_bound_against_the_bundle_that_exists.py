"""The reading is bound against the bundle that exists — the cuts that put the front door back."""

TEST = "tests/test_the_reading_is_bound_against_the_bundle_that_exists.py"

MUTATIONS = [
    ("the bound reads the front door again — every citation `baixa`",
     "openfactory/product/module.py",
     "        if source is not None and (source / OKF_INDEX_FILE).is_file():\n"
     "            return source\n",
     "        if False:\n            return source\n"),

    ("a bundle at the root is no longer read",
     "openfactory/product/module.py",
     "        return door if (door / OKF_INDEX_FILE).is_file() else None\n",
     "        return None\n"),

    ("the gate ignores the card's repository",
     "openfactory/orchestrator/machine.py",
     '        repo = (getattr(self, "_card_repo", "") or "").strip() or repo_of(project)\n',
     '        repo = repo_of(project)\n'),
]
