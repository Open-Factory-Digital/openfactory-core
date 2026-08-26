"""#179 — a commit that changes nothing must not mark the review out of date.

Both directions are cut here, because the fix trades one wrong answer for the other if only one
of them is guarded: a no-op pass that still reads as stale (the defect), and a real rewrite that
stops reading as stale (the expensive twin).
"""

TEST = "tests/test_a_pass_that_changed_nothing.py"

MUTATIONS = [
    ("the pass never says whether it changed anything — every result is unmeasured",
     "openfactory/orchestrator/machine.py",
     '                return res.model_copy(update={"code_changed": changed})',
     "                return res"),

    ("the comparison is inverted: a rewrite reads as untouched and a no-op as a rewrite",
     "openfactory/orchestrator/machine.py",
     "                changed = None if (before is None or now is None) else (now != before)",
     "                changed = None if (before is None or now is None) else (now == before)"),

    ("git's error text is handed back as if it were a diff",
     "openfactory/orchestrator/machine.py",
     "        return out if rc == 0 else None",
     "        return out"),

    ("the pass that gave up is assumed to have changed nothing instead of being measured",
     "openfactory/orchestrator/machine.py",
     '                return as_left(self._hold(\n'
     '                    ticket, owner, f"ci-repair agent stopped: {rep.summary}",',
     '                return (self._hold(\n'
     '                    ticket, owner, f"ci-repair agent stopped: {rep.summary}",'),

    ("the successful pass reports nothing about what it pushed",
     "openfactory/orchestrator/machine.py",
     "            return as_left(RunResult(",
     "            return (RunResult("),

    ("an unmeasurable pass clears the marker — an unknown reads as 'nothing happened'",
     "openfactory/runtime/temporal/workflow.py",
     "        if self._verdict and result.code_changed is False:",
     "        if self._verdict and result.code_changed is not True:"),

    ("the adjust path can raise the marker and never take it down",
     "openfactory/runtime/temporal/workflow.py",
     "        self._the_reviewed_code_is_still_here(passed)",
     "        pass  # the marker stays up whatever the pass did"),

    ("the CI-repair path can raise the marker and never take it down",
     "openfactory/runtime/temporal/workflow.py",
     "                self._the_reviewed_code_is_still_here(rep)  # …or nothing was pushed at all (#179)",
     "                pass  # the marker stays up whatever the pass did"),
]
