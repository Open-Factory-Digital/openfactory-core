"""The census, and the sixteen ways a suite goes on reporting green while it stops testing anything.

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

ROWS 11-16 EXIST BECAUSE OF REVIEW ON #19, and every one of them is a case where the guard was
present and could not fire. Row 11 is the baseline taken against a tree that is not the base commit
— true at one call site, and true at the other whenever a job RESUMES, so pausing and resuming was
all it took to defeat this. Rows 12-13 are the CI-repair path, which never reaches `should_auto_
merge` at all and whose agent is told to make a failing CI pass. Rows 14-15 are the gate refusing in
silence: the reason with no caller, and the reason silenced by the same comparison that let the
merge through — which is exactly the case where the vanished SET is the only signal left. Row 16 is
the count taken after the truncation, which is not a count.
"""

TEST = "tests/test_a_suite_that_stopped_collecting_is_not_a_green_suite.py"

MUTATIONS = [
    # ── the measurement never happens ───────────────────────────────────────────────────────────
    ("the clean tree is never enumerated, so there is no 'before' and every change looks like the "
     "first one — the census exists and reports on nothing, for ever",
     "openfactory/orchestrator/machine.py",
     "        if at_base:\n            self._census_before = self._take_census(ws)",
     "        if False:\n            self._census_before = self._take_census(ws)"),

    ("the edited tree is never enumerated, so a project that adopted the census gets a permanent "
     "'could not measure' and, read as no news, merges everything",
     "openfactory/orchestrator/machine.py",
     "        after = self._take_census(census_ws) if (before is not None and census_ws) else None",
     "        after = None"),

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
     '        log.info("test census: %d identifiers from `%s`", len(ids), cmd)\n        return ids',
     '        log.info("test census: %d identifiers from `%s`", len(ids), cmd)\n'
     "        return ids or None"),

    ("a census that existed before the change and could not be taken after it is read as no news, "
     "so the agent breaking enumeration outright is the one thing that always merges",
     "openfactory/orchestrator/merge_policy.py",
     "    if before is not None and (after is None or after < before):",
     "    if before is not None and after is not None and after < before:"),

    # ── the false positive that would switch the guard off ──────────────────────────────────────
    ("the summary line counts as a test, so `120 tests collected in 0.52s` and the same line at "
     "0.48s are a test vanishing — on every job, for every project, until somebody disables this",
     "openfactory/policy/census.py",
     '        if not line or line.endswith(":") or (line[0].isascii() and line[0].isdigit()):',
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

    # ── found by review: present, and unable to fire ─────────────────────────────────────────────
    ("the baseline is taken wherever `_run_setup` happens to sit rather than on a tree that IS the "
     "base commit, so a RESUMED attempt censuses a checkout already carrying the agent's partial "
     "work — `after >= before` for the rest of the job, and pausing and resuming defeats the gate",
     "openfactory/orchestrator/machine.py",
     "                self._run_setup(ticket, ws, at_base=not resuming)",
     "                self._run_setup(ticket, ws, at_base=True)"),

    ("the CI-repair pass never censuses what it produced, so a repair told to make a failing CI "
     "pass deletes the failing tests and lands on an ALREADY-ARMED auto-merge — it emits no "
     "suppression token, and `should_auto_merge` is never called on that path",
     "openfactory/orchestrator/machine.py",
     "            repair_census_before = self._take_census(ws)",
     "            repair_census_before = None"),

    ("the CI-repair disarm branch stops reading the census, so the measurement is taken, paid for, "
     "and thrown away at the one gate on that path",
     "openfactory/orchestrator/machine.py",
     "            if supp or hits or unreadable or lost_tests:",
     "            if supp or hits or unreadable:"),

    ("the gate holds the merge and the pull request says nothing about it, so the person deciding "
     "cannot see WHICH tests stopped being collected — the signal that survives a count the noise "
     "moved the wrong way",
     "openfactory/orchestrator/machine.py",
     '        if census_note:\n            lines += ["", census_note]',
     '        if False:\n            lines += ["", census_note]'),

    ("`reason()` silences itself with the same comparison that let the merge through, so in the "
     "one case where the vanished SET is the only surviving signal — tests deleted, warning lines "
     "added, count UP — the pull request says nothing at all",
     "openfactory/policy/census.py",
     "    line = \"\"\n    if after_count < before_count:",
     "    line = \"\"\n    if after_count >= before_count:\n        return \"\"\n    if True:"),

    ("the vanished set is cut inside the measurement, so the true number is unrecoverable — a "
     "rename is minus-one-plus-one by this design's own argument, so the count drop cannot supply "
     "it either",
     "openfactory/policy/census.py",
     "    return tuple(t for t in before if t not in later)",
     "    return tuple(t for t in before if t not in later)[:MAX_SHOWN]"),
]
