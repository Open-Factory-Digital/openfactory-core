"""A journal never lands at the root (issue #57) — the cuts that put `/.openfactory-logs` back.

ROW 1 IS THE 2026-09-06 SHAPE: a root-adjacent checkout is "beside the checkout" again, at `/`.
ROW 2 IS THE OVER-CORRECTION: every checkout moves under the registry — the migration the
docstring says must not happen.
"""

TEST = "tests/test_the_journal_is_where_the_deployment_says.py"

MUTATIONS = [
    ("a root-adjacent checkout journals beside itself again — at the root of the machine",
     "openfactory/paths.py",
     "    return parent == Path(parent.anchor)\n",
     "    return False\n"),

    ("every checkout moves under the registry — the migration that must not happen",
     "openfactory/paths.py",
     "    return parent == Path(parent.anchor)\n",
     "    return True\n"),
]
