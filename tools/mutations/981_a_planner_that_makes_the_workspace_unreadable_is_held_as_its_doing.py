"""#981: a planner that makes the workspace unreadable is held as its own doing, not the box's.

A planner that runs `git init sub` in the job's workspace leaves an embedded repository with no
commit, and the fingerprint's `git add -A` exits 128 on the second asking ("'sub/' does not have
a commit checked out", git 2.43.0). The before-mark was read, so git was usable in the box when
the pass began. On main the after-pass hold reused `_unaskable` with `hold_cause=ENVIRONMENT` and
told the person to "Make git usable in the box", which names the wrong party. The hold now says
the workspace became unreadable during the planner's pass, names the planner as the likely
cause, keeps git's exit and words, and declares `unknown`, the cause the planner-wrote hold
declares. The hold before the pass is unchanged.

The guard is `tests/test_a_kimi_planner_that_writes_holds_the_job_before_its_edit_reaches_a_commit
.py` (T1, #788's module, whose fixtures it reuses). The cuts:

  N1. **The new branch removed**: the after-pass hold is #788's again (`_unaskable(after, "after
      the planner ran")` with `hold_cause=ENVIRONMENT`). The `git init sub` row goes red.
  N2. **The cause not declared** (#788's C3, moved here): the after-pass hold declares no cause,
      so its prose is left to `classify`. The row whose second asking is refused goes red.
"""

TEST = "tests/test_a_kimi_planner_that_writes_holds_the_job_before_its_edit_reaches_a_commit.py"

GIT_INIT = TEST + "::test_a_planner_that_runs_git_init_in_the_workspace_is_held_as_its_doing"
AFTER = TEST + "::test_a_workspace_unreadable_only_after_the_pass_is_held_as_the_planners_doing"

MACHINE = "openfactory/orchestrator/machine.py"

_HOLD_AFTER = (
    '                        return self._hold(ticket, owner, '
    'self._unreadable_after_planner(after),\n'
    '                                          JobState.ON_HOLD, branch=branch, '
    'hold_cause=UNKNOWN)\n'
)

MUTATIONS = [
    ("N1 the new branch removed: the after-pass hold is the environment's, \"Make git usable\"",
     MACHINE,
     _HOLD_AFTER,
     '                        return self._hold(ticket, owner, self._unaskable(after, "after the '
     'planner "\n'
     '                                          "ran"), JobState.ON_HOLD, branch=branch,\n'
     '                                          hold_cause=ENVIRONMENT)\n',
     GIT_INIT),
    ("N2 the after-pass hold declares no cause: git's refusal is left to `classify`",
     MACHINE,
     _HOLD_AFTER,
     _HOLD_AFTER.replace(", hold_cause=UNKNOWN)", ")"),
     AFTER),
]
