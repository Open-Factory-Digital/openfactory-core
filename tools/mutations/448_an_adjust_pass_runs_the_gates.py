"""A person's adjust pass is gated the way the first pass was, and a red one is never pushed (#448).

Run:  .venv/bin/python tools/mutate.py tools/mutations/448_an_adjust_pass_runs_the_gates.py

Row 1 is the defect as it shipped: the adjust path runs no gate. Rows 2-4 break the hold: a red
pass pushed anyway, a held pass reported as having changed the pull request, a hold a resume
sends through an agent pass. Rows 5-7 break the repair loop: no repair at all, a gate that could
not run handed to an agent, a repair never re-validated. Rows 8-9 lose the gates on the way out:
not handed to the re-review, not carried on the result. Row 10 gates a check's repair as well.
Row 11 is the verdict still claiming the gates were not re-run.
"""

TEST = "tests/test_an_adjust_pass_runs_the_gates.py"

M = "openfactory/orchestrator/machine.py"
WF = "openfactory/runtime/temporal/workflow.py"

GATED = ("            if human:\n"
         "                validations, held = self._the_adjusted_change_passes_its_gates(")

MUTATIONS = [
    ("TODAY'S DEFECT: the adjust pass runs no gate and pushes what it wrote", M,
     GATED,
     GATED.replace("if human:", "if False:")),

    ("a pass still red is pushed under the requester's preview", M,
     "                if held is not None:\n",
     "                if False:\n"),

    ("a held pass is reported by the workspace, which holds the unpushed commits", M,
     '                    return held.model_copy(update={"code_changed": False})\n',
     "                    return as_left(held)\n"),

    ("a resume of the hold goes through an agent pass, not back to the merge watch", M,
     "JobState.ON_HOLD, branch=branch, validations=validations, merge_refused=True)",
     "JobState.ON_HOLD, branch=branch, validations=validations)"),

    ("a red pass is held without a repair", M,
     "            and attempts < self.manifest.repair_max_attempts\n"
     "            and not self._over_cost_ceiling(spent)\n",
     "            and attempts < 0\n"
     "            and not self._over_cost_ceiling(spent)\n"),

    ("a gate that could not run is handed to an agent to fix", M,
     "            and not _never_ran(validations)\n"
     "            and attempts < self.manifest.repair_max_attempts\n"
     "            and not self._over_cost_ceiling(spent)\n",
     "            and attempts < self.manifest.repair_max_attempts\n"
     "            and not self._over_cost_ceiling(spent)\n"),

    ("a repair is never validated again, so the gate it fixed still reads red", M,
     "            self._commit(ws, ticket)\n"
     "            _, validations = self._validate(ws, ticket)\n"
     "        if _all_passed(validations):\n",
     "            self._commit(ws, ticket)\n"
     "        if _all_passed(validations):\n"),

    ("the re-review is handed no gates, so it can only read NOT VERIFIED", M,
     "review_input=ReviewInput(ticket=ticket, diff=diff, validations=validations),",
     "review_input=ReviewInput(ticket=ticket, diff=diff, validations=[]),"),

    ("the gates the pass ran are not on its result", M,
     "                auto_merge=True, review=review, validations=validations,\n",
     "                auto_merge=True, review=review,\n"),

    ("a check's repair is gated too, though the forge re-runs that check on the push", M,
     GATED,
     GATED.replace("if human:", "if True:")),

    ("the verdict of a gated pass still says the gates were not re-run", WF,
     'if self._verdict is not None and not getattr(result, "validations", None):',
     "if self._verdict is not None:"),
]
