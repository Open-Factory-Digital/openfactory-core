"""#980: a walled Kimi planner holds the job before the executor runs, so a write it makes after
the second reading cannot reach the executor's commit.

The guard is `tests/test_a_kimi_planner_that_writes_holds_the_job_before_its_edit_reaches_a_commit
.py`, its #980 section. The box's wall kills only the shell it started (`run_and_stream`, the
`TimeoutExpired` branch), so a walled harness may still be running; the #788 reading sees only the
tree at its second asking. The fix lives in two places: `wall_result` in `adapters/agent/base.py`
marks the result `walled`, and `JobRunner.run` holds a measured pass that was walled. One cut per
property, each aimed at the row that holds it:

  W1 **The hold is removed.** The walled pass goes on to the executor, and the T1 row's orphan
     writes `late.txt` into the tree `_commit` sweeps and pushes; the double row reaches PR_OPEN.
  W2 **`wall_result` no longer marks the pass walled.** The orchestrator cannot tell a walled pass
     from one that ended on its own, so nothing is held.
  W3 **The gate widens to any walled pass.** A walled `codex` planner, whose CLI holds it
     read-only, is held too, and criterion 2's reverse row goes red.
"""

TEST = "tests/test_a_kimi_planner_that_writes_holds_the_job_before_its_edit_reaches_a_commit.py"

MARKED = TEST + "::test_a_walled_result_says_it_was_walled"
HELD = TEST + "::test_a_walled_kimi_planner_holds_the_job_before_the_executor_runs"
CODEX = TEST + "::test_a_walled_planner_whose_cli_holds_it_read_only_runs_on_as_today"
LATE = TEST + ("::test_a_kimi_planner_that_outlives_its_timeout_and_writes_later_reaches_no"
               "_commit")

BASE = "openfactory/adapters/agent/base.py"
MACHINE = "openfactory/orchestrator/machine.py"

_GATE = "                if before is not None and plan_result.walled:\n"

MUTATIONS = [
    ("W1 the walled-planner hold is removed: the job goes on to the executor", MACHINE,
     _GATE, "                if False:\n",
     LATE),
    ("W1 the walled-planner hold is removed (the double row)", MACHINE,
     _GATE, "                if False:\n",
     HELD),
    ("W2 `wall_result` no longer marks the pass walled", BASE,
     "        walled=True,\n", "",
     MARKED),
    ("W2 `wall_result` no longer marks the pass walled (the hold row)", BASE,
     "        walled=True,\n", "",
     HELD),
    ("W3 the gate widens to any walled pass: a walled codex planner is held", MACHINE,
     _GATE, "                if plan_result.walled:\n",
     CODEX),
]
