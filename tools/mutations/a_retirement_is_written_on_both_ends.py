"""A retirement is written on both ends — `SUPERSEDED_BY` on the plan that steps aside,
`SUPERSEDES` on the plan that carries its claims — and the runner and the guard refuse one end
alone (the review of #84, 2026-09-08).

THE SILENCER THE ROWS RESTORE. A plan declaring `SUPERSEDED_BY` is skipped by the anchor rule and
the `TEST` rule alike, so with nothing checked on the successor's side the declaration bought an
exit 0 over anything: the reviewer planted `SUPERSEDED_BY` naming an unrelated live plan over a
rotten anchor and a missing `TEST`, and the guard passed 5/5. The first three rows put that back
in the runner, one mechanism at a time; the last three put it back in the guard's pairing rule,
which the guard verifies on a planted directory before it asks the real one.

Run: .venv/bin/python tools/mutate.py tools/mutations/a_retirement_is_written_on_both_ends.py
"""

TEST = "tests/test_the_mutation_runner_is_not_decoration.py"

RUNNER = "tools/mutate.py"
GUARD = "tests/test_every_mutation_plan_can_run.py"

MUTATIONS = [
    # ── the runner ────────────────────────────────────────────────────────────────────────────
    ("the second end is not asked for at all — any live successor silences the plan (the "
     "reviewer's probe on #84)", RUNNER,
     "        if problem := supersession_problem(plan_path, by):",
     "        if problem := None:"),

    ("the refusal is printed and the exit code says fine", RUNNER,
     '            print(f"PLAN REFUSED — {problem}")\n            return 1\n',
     '            print(f"PLAN REFUSED — {problem}")\n            return 0\n'),

    ("a successor that is not there raises a traceback instead of refusing by name", RUNNER,
     "    if not successor.is_file():\n        return (f\"{me.name} says it is superseded by",
     "    if not successor.is_file() and False:\n        return (f\"{me.name} says it is "
     "superseded by"),

    ("HOSTILE: the refusal keeps every word and stops naming the successor — a reader is told a "
     "plan is one-ended and not which pair", RUNNER,
     '        return (f"{me.name} says it is superseded by {by}, and {by} does not name it back in "',
     '        return (f"{me.name} says it is superseded by another plan, and it does not name it '
     'back in "'),

    # ── the guard's pairing rule, verified on a planted directory ─────────────────────────────
    ("a SUPERSEDED_BY nobody names back passes the guard", GUARD,
     '            elif name not in (plans[by].get("SUPERSEDES") or ()):',
     '            elif False:', GUARD),

    ("a SUPERSEDES entry whose other end does not declare back passes the guard", GUARD,
     '            elif plans[named].get("SUPERSEDED_BY") != name:',
     '            elif False:', GUARD),

    ("a SUPERSEDES entry naming a plan that is not there passes the guard", GUARD,
     '            if named not in plans:\n                problems.append(f"{name} claims to '
     'supersede {named!r}, which is not a plan here")',
     '            if named not in plans:\n                continue', GUARD),
]
