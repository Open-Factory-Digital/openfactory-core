"""The mutation runner refuses a plan aimed at a path this checkout does not carry — by name,
before any baseline, and without a raw traceback (pre-launch audit, 2026-08-26).

Point-in-time proof; anchors rot as code moves and fail loudly on rerun.
"""

TEST = "tests/test_the_mutation_runner_is_not_decoration.py"

MUTATIONS = [
    ("the missing path raises instead of refusing by name (the defect as it was)",
     "tools/mutate.py",
     "        try:\n            text = (ROOT / rel).read_text()\n        except FileNotFoundError:",
     "        try:\n            text = (ROOT / rel).read_text()\n        except ZeroDivisionError:"),
    ("the refusal stops saying where the removed paths are listed",
     "tools/mutate.py",
     '                f"public cut removes are listed in docs/STATUS.md\'s excluded-paths table")',
     '                f"public cut removes are listed elsewhere")'),
    ("the refusal stops naming the path it could not read",
     "tools/mutate.py",
     '                f"  [{label}] {rel} is not in this tree — the plan targets a path this checkout "',
     '                f"  [{label}] a file is not in this tree — the plan targets a path this checkout "'),
    ("a missing path is skipped in silence instead of refused",
     "tools/mutate.py",
     "            problems.append(\n                f\"  [{label}] {rel} is not in this tree",
     "            _ = (\n                f\"  [{label}] {rel} is not in this tree"),
]
