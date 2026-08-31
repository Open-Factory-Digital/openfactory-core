"""The census, and the ten ways a suite goes on reporting green while it stops testing anything.

Every row here produces a PASSING PULL REQUEST. None produces an error. That is the whole nature of
the hole: an exit code cannot tell forty tests that passed from forty tests that stopped being
collected, so a guard that quietly stops working is indistinguishable from one that has nothing to
report.

ROWS 1-3 ARE THE MEASUREMENT NEVER HAPPENING — the "before" that is never taken, the "after" that
is never taken, and the pair that is never recorded. Rows 2 and 3 are the shape `undeclared_paths`
and `protected_hits` both had: a question answered and dropped on the way to the gate.

ROWS 4-6 ARE THE THREE STATES COLLAPSING, which is the failure this design spends most of its words
on. `None` becoming `0` gates every project that never adopted the feature; `0` becoming `None`
hides a suite that emptied completely; a missing "after" read as no news hides the agent breaking
enumeration outright.

ROW 7 IS THE FALSE POSITIVE THAT WOULD HAVE KILLED THE GUARD IN A WEEK — the summary line whose
DURATION changes between two runs of an unchanged suite, reported as a vanished test on every job.

ROWS 8-9 CUT THE OTHER WAY, the discipline this directory keeps. Gating on the SET rather than the
count human-gates every rename, and refusing a suite that GREW is the guard that now refuses
everything.

ROW 10 IS THE ORDERING ONE: a census taken before `setup:` runs enumerates a suite whose
dependencies are not installed, which is a census of the empty set — a green light over exactly the
hole this closes.
"""

TEST = "tests/test_a_suite_that_stopped_collecting_is_not_a_green_suite.py"

MUTATIONS = [
    # ── the measurement never happens ───────────────────────────────────────────────────────────
    ("the clean tree is never enumerated, so there is no 'before' and every change looks like the "
     "first one — the census exists and reports on nothing, for ever",
     "openfactory/orchestrator/machine.py",
     "        self._census_before = self._take_census(ws)",
     "        self._census_before = None"),

    ("the edited tree is never enumerated, so a project that adopted the census gets a permanent "
     "'could not measure' and, read as no news, merges everything",
     "openfactory/orchestrator/machine.py",
     "        self._census_after = self._take_census(ws)",
     "        self._census_after = None"),

    ("the counts are computed and dropped on the way to the record, so they exist for the length "
     "of one method and the gate that needs them never sees them",
     "openfactory/orchestrator/machine.py",
     "        result.test_census_before = None if before is None else len(before)",
     "        result.test_census_before = None"),

    # ── the three states collapse ───────────────────────────────────────────────────────────────
    ("'no census' becomes 'a census of zero', so every project that never declared an inventory "
     "command is human-gated for a feature it has not adopted",
     "openfactory/orchestrator/merge_policy.py",
     "    if before is not None and (after is None or after < before):",
     "    if (before or 0) >= 0 and ((after or 0) < (before or 0) or after is None):"),

    ("a suite that emptied completely reads as a suite nobody measured, which is the one result "
     "that must never be silent — `collected nothing` is an alarming ANSWER, not an absence",
     "openfactory/orchestrator/machine.py",
     "        return inventory_of(out)",
     "        return inventory_of(out) or None"),

    ("a census that existed before the change and could not be taken after it is read as no news, "
     "so the agent breaking enumeration outright is the one thing that always merges",
     "openfactory/orchestrator/merge_policy.py",
     "    if before is not None and (after is None or after < before):",
     "    if before is not None and after is not None and after < before:"),

    # ── the false positive that would switch the guard off ──────────────────────────────────────
    ("the summary line counts as a test, so `120 tests collected in 0.52s` and the same line at "
     "0.48s are a test vanishing — on every job, for every project, until somebody disables this",
     "openfactory/policy/census.py",
     '        if not line or line.endswith(":") or line[0].isdigit():',
     "        if not line:"),

    # ── the reverse cuts ────────────────────────────────────────────────────────────────────────
    ("the gate moves from the count to the SET, so every renamed test holds a merge and the guard "
     "is switched off within a week for human-gating ordinary refactors",
     "openfactory/orchestrator/merge_policy.py",
     "    if before is not None and (after is None or after < before):",
     "    if before is not None and (after is None or after != before):"),

    ("a suite that GREW is refused, which is the guard that now refuses everything",
     "openfactory/orchestrator/merge_policy.py",
     "    if before is not None and (after is None or after < before):",
     "    if before is not None and (after is None or after != before):",
     # aimed at the same suite; kept separate from row 8 because the two describe different
     # failures a reader has to be able to tell apart even though one cut reproduces both.
     "tests/test_a_suite_that_stopped_collecting_is_not_a_green_suite.py"),

    # ── the ordering one ────────────────────────────────────────────────────────────────────────
    ("the 'before' is taken before `setup:` installs anything, so the inventory command runs "
     "against a tree with no dependencies, collects nothing, and every later census looks like "
     "growth — a green light over exactly the hole this closes",
     "openfactory/orchestrator/machine.py",
     "        for cmd in self.manifest.setup:\n"
     "            rc, out = self.sandbox.run(workspace=ws, command=cmd, timeout=_SETUP_TIMEOUT)",
     "        self._census_before = self._take_census(ws)\n"
     "        for cmd in self.manifest.setup:\n"
     "            rc, out = self.sandbox.run(workspace=ws, command=cmd, timeout=_SETUP_TIMEOUT)\n"
     "            self._census_before = getattr(self, '_census_before', None)"),
]
