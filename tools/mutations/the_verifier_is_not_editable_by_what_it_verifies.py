"""The ruler, and the eight ways the thing being measured gets to move it again.

`roles/executor.md` asked the agent in prose not to edit the files that decide whether it passed.
Every row here restores that state — a factory that runs, merges, and reports green, with the
manifest naming its own gates editable by the worker those gates judge. None of them produces an
error; all of them produce a PASSING PULL REQUEST, which is why the plan is long for a guard this
small.

ROWS 1-3 ARE THE GUARD CEASING TO FIRE at each of the three places it has to survive: the diff is
never asked, the answer is never recorded, the gate never reads it. Rows 2 and 3 are the shape the
`undeclared_paths` defect had — a question answered and then dropped on the way to the gate that
needed it.

ROWS 4-5 ARE THE FLOOR ITSELF EVAPORATING, quietly and per-install. A deployment whose floor cannot
be read must gate everything; reading `None` as "nothing is protected" is the same inversion this
codebase names elsewhere — no concept, no objection.

ROWS 6-7 CUT THE OTHER WAY, the discipline this directory keeps. A guard that gated ordinary work
would satisfy every row above and be worse than the defect: a project that human-gates `README.md`
stops being a factory. Row 7 is the retro-gate — refusing merges on evidence that does not exist,
which is the rule `undeclared_count` already had to set once.

ROW 8 IS THE ONE THAT LOOKS LIKE A FEATURE REQUEST: giving a project a way to subtract from the
deployment floor. `floor.yaml` says it in its own words — an off switch for the floor is the first
thing that gets set.
"""

TEST = "tests/test_the_verifier_is_not_editable_by_what_it_verifies.py"

MUTATIONS = [
    # ── the guard stops firing, at each seam it has to survive ───────────────────────────────────
    ("the diff is never asked the question, so the verifier's own inputs are indistinguishable "
     "from application code and the manifest is editable by the worker it judges",
     "openfactory/orchestrator/machine.py",
     "        self._protected = protected_violations(diff_paths, self.manifest)",
     "        self._protected = ()"),

    ("the answer is computed and dropped on the way to the record, so it exists for the length of "
     "one method and the gate that needs it never sees it",
     "openfactory/orchestrator/machine.py",
     '        result.protected_hits = list(getattr(self, "_protected", ()) or ())',
     "        pass"),

    ("the merge gate stops reading it, so a change to `.openfactory/project.yaml` auto-merges "
     "exactly as it did when only a paragraph of prose stood in its way",
     "openfactory/orchestrator/merge_policy.py",
     '    if getattr(result, "protected_hits", None):\n        return False',
     "    if False:\n        return False"),

    # ── the floor evaporates, per-install and in silence ─────────────────────────────────────────
    ("an unreadable floor is read as a deployment with nothing to protect, so the guard disappears "
     "in exactly the installation where nobody is watching",
     "openfactory/policy/protected.py",
     "    globs = effective_protected_paths(manifest)\n    if globs is None:",
     "    globs = effective_protected_paths(manifest) or ()\n    if False:"),

    ("`None` and `()` collapse one layer up, so a build that cannot read its own floor reports the "
     "same fact as a deployment that deliberately protects nothing",
     "openfactory/policy/protected.py",
     "    floor = floor_protected_paths()\n    if floor is None:\n        return None",
     "    floor = floor_protected_paths() or ()\n    if False:\n        return None"),

    # ── the reverse cuts: the fix doing more damage than the defect ──────────────────────────────
    ("every changed path is treated as protected, so a project human-gates its own README and "
     "stops being a factory — the guard that now refuses everything",
     "openfactory/policy/protected.py",
     "    hit = [p for p in paths if any(_touches(p, g) for g in globs)]",
     "    hit = list(paths)"),

    ("an attempt from before the field existed is retro-gated, so every historical result is "
     "refused on evidence nobody ever recorded",
     "openfactory/orchestrator/merge_policy.py",
     '    if getattr(result, "protected_hits", None):',
     '    if getattr(result, "protected_hits", None) is not None:'),

    # ── the off switch, which is the first thing that gets set ───────────────────────────────────
    ("a project's own list REPLACES the deployment floor instead of adding to it, so any client "
     "opts out of the guard by declaring one path of their own",
     "openfactory/policy/protected.py",
     "    for glob in (*floor, *own):",
     "    for glob in (own or floor):"),
]
