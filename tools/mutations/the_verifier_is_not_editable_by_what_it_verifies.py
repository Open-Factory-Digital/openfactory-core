"""The ruler, and the thirteen ways the thing being measured gets to move it again.

`roles/executor.md` asked the agent in prose not to edit the files that decide whether it passed.
Every row here restores that state — a factory that runs, merges, and reports green, with the
manifest naming its own gates editable by the worker those gates judge. None of them produces an
error; all of them produce a PASSING PULL REQUEST, which is why the plan is long for a guard this
small.

ROWS 1-3 ARE THE GUARD CEASING TO FIRE at each of the three places it has to survive on the main
path: the diff is never asked, the answer is never recorded, the gate never reads it. Rows 2 and 3
are the shape the `undeclared_paths` defect had — a question answered and then dropped on the way to
the gate that needed it.

ROWS 4-5 ARE THE OTHER PATH, AND IT IS THE ONE THAT MATTERS MOST. The CI-repair pass commits and
pushes to a pull request whose auto-merge is ALREADY ARMED, so `should_auto_merge` never runs there
and rows 1-3 cannot see it. The agent on that path is told *"the CI for this PR is FAILING, make it
pass"*, and the cheapest way to make a gate stop failing is to retune the gate in the file that
names it. Review on #18 found this path uncovered; these are the rows that would have caught it.

ROWS 6-7 ARE THE FLOOR ITSELF EVAPORATING, quietly and per-install. A deployment whose floor cannot
be read must gate everything; reading `None` as "nothing is protected" is the same inversion this
codebase names elsewhere — no concept, no objection.

ROW 8 IS THE GATE REFUSING IN SILENCE, which this module's own docstring calls a gate nobody can
argue with. ROW 9 is the count taken after the truncation, which is not a count.

ROWS 10-11 CUT THE OTHER WAY, the discipline this directory keeps. A guard that gated ordinary work
would satisfy every row above and be worse than the defect: a project that human-gates `README.md`
stops being a factory. Row 11 is the retro-gate — refusing merges on evidence that does not exist,
which is the rule `undeclared_count` already had to set once.

ROW 12 IS THE ONE THAT LOOKS LIKE A FEATURE REQUEST: giving a project a way to subtract from the
deployment floor. `floor.yaml` says it in its own words — an off switch for the floor is the first
thing that gets set.

ROW 13 IS THE UNREADABLE FLOOR ARRIVING AS A LIE ABOUT THE CLIENT'S OWN FILES, which is how it
shipped in the first revision: an arbitrary sample of changed paths, gating correctly and telling
the durable record that a real change had touched the verifier's inputs when OUR install was broken.
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
     "        result.protected_hits = list(hits[:protected_policy.MAX_SHOWN])",
     "        result.protected_hits = []"),

    ("the merge gate stops reading it, so a change to `.openfactory/project.yaml` auto-merges "
     "exactly as it did when only a paragraph of prose stood in its way",
     "openfactory/orchestrator/merge_policy.py",
     "    if result.protected_hits:\n        return False",
     "    if False:\n        return False"),

    # ── the CI-repair path, which never reaches the gate above ───────────────────────────────────
    ("the CI-repair pass never asks whether it edited the verifier's own inputs, so a repair that "
     "retunes the gate in the file that names it lands on an ALREADY-ARMED auto-merge with nothing "
     "in its way — and rows 1-3 all cut the other path, so every one of them stays red",
     "openfactory/orchestrator/machine.py",
     "            hits = protected_violations(self._pr_diff_paths(ws, base), self.manifest)",
     "            hits = ()"),

    ("the CI-repair disarm fires on suppressions alone again, which is how it shipped: a `# noqa` "
     "is caught and a deleted gate — which emits no suppression token at all — is not",
     "openfactory/orchestrator/machine.py",
     "            if supp or hits or unreadable:",
     "            if supp:"),

    # ── the floor evaporates, per-install and in silence ─────────────────────────────────────────
    ("an unreadable floor is read as a deployment with nothing to protect, so the guard disappears "
     "in exactly the installation where nobody is watching",
     "openfactory/policy/protected.py",
     "    return effective_protected_paths(manifest) is None",
     "    return False"),

    ("`None` and `()` collapse one layer up, so a build that cannot read its own floor reports the "
     "same fact as a deployment that deliberately protects nothing",
     "openfactory/policy/protected.py",
     "    floor = floor_protected_paths()\n    if floor is None:\n        return None",
     "    floor = floor_protected_paths() or ()\n    if False:\n        return None"),

    # ── the gate that holds and says nothing ─────────────────────────────────────────────────────
    ("the gate holds the merge and never names what it refused, so the human opens a pull request "
     "that reads exactly like an ordinary ready-for-review one",
     "openfactory/orchestrator/machine.py",
     "        if protected_note:\n            lines += [\"\", protected_note]",
     "        if False:\n            lines += [\"\", protected_note]"),

    ("the count is taken from the truncated list, so a change touching forty protected files "
     "reports twelve and the true number is unrecoverable",
     "openfactory/orchestrator/machine.py",
     "        result.protected_count = len(hits)",
     "        result.protected_count = len(result.protected_hits)"),

    # ── the reverse cuts: the fix doing more damage than the defect ──────────────────────────────
    ("every changed path is treated as protected, so a project human-gates its own README and "
     "stops being a factory — the guard that now refuses everything",
     "openfactory/policy/protected.py",
     "    return tuple(sorted(p for p in paths if any(_touches(p, g) for g in globs)))",
     "    return tuple(sorted(paths))"),

    ("an attempt from before the field existed is retro-gated, so every historical result is "
     "refused on evidence nobody ever recorded",
     "openfactory/orchestrator/merge_policy.py",
     "    if result.protected_hits:",
     "    if result.protected_hits is not None:"),

    # ── the off switch, which is the first thing that gets set ───────────────────────────────────
    ("a project's own list REPLACES the deployment floor instead of adding to it, so any client "
     "opts out of the guard by declaring one path of their own",
     "openfactory/policy/protected.py",
     "    for glob in (*floor, *own):",
     "    for glob in (own or floor):"),

    # ── the unreadable floor, reported as the client's fault ─────────────────────────────────────
    ("an unreadable floor is reported as a finding about the client's own change again, so the "
     "durable record says a real change touched the verifier's inputs when OUR install is broken",
     "openfactory/policy/protected.py",
     "    globs = effective_protected_paths(manifest)\n    if globs is None:\n        return ()",
     "    globs = effective_protected_paths(manifest)\n    if globs is None:\n"
     "        return tuple(sorted(paths)[:MAX_SHOWN])"),
]
