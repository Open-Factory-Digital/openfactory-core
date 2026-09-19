"""#184, proven by breaking it — the repair brief states the failure it was given, or does not run.

The agent was told "The GitHub CI for this PR is FAILING. Make it pass." and then shown whatever
`ci_log` held — on the deployment that reported this, on Azure DevOps, nothing.

THREE CLAIMS:

  1. **The machine is the last door.** With no failure to show it launches nothing — before the
     card moves — and the hold carries the mark a resume reads. The brief names the forge by its
     ROW, and a person's review comment is not wrapped in a CI failure sentence.
  2. **A forge's name is a declaration on its row**, and a test double is not one.
  3. **The box goes through the gate the worker goes through**, and both hand the machine the log
     the decision was made from and say whose words fill the slot.

The guard is `tests/test_the_repair_brief_states_the_failure_it_was_given.py`.
"""

TEST = "tests/test_the_repair_brief_states_the_failure_it_was_given.py"

MACHINE = "openfactory/orchestrator/machine.py"
BASE = "openfactory/adapters/forge/base.py"
GITHUB = "openfactory/adapters/forge/github.py"
BOX = "openfactory/runtime/boxed_job.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
REPAIRABLE = "openfactory/runtime/repairable.py"

MUTATIONS = [
    # ── claim 1: the machine ──────────────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF: a repair with no failure to show runs anyway", MACHINE,
     '        if not (ci_log or "").strip():\n',
     "        if False:\n"),

    ("THE LITERAL IS BACK: the brief names one vendor on every forge", MACHINE,
     '                    f"{forge_display_name(self.forge)}. Its failing log is below — make it '
     'pass."\n',
     '                    f"GitHub. Its failing log is below — make it pass."\n'),

    ("a person's review comment is announced as a red build", MACHINE,
     "                failure_log=ci_log if human else (\n",
     "                failure_log=ci_log if False else (\n"),

    ("the machine's own hold loses the mark, so a resume pays for a whole agent pass", MACHINE,
     "                merge_refused=True, code_changed=False)\n",
     "                code_changed=False)\n"),

    # ── claim 2: the row's name ───────────────────────────────────────────────────────────────
    ("any truthy attribute is a name, so a mock forge names itself", BASE,
     '    return name.strip() if isinstance(name, str) and name.strip() else "the forge"\n',
     '    return str(name) if name else "the forge"\n'),

    ("GitHub stops saying what it is called", GITHUB,
     '    display_name = "GitHub"\n',
     '    display_name = ""\n'),

    # ── claim 3: the two callers ──────────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF, ON THE BOX: whatever the gate says, the agent runs", BOX,
     "        if held is not None:\n"
     '            print("OPENFACTORY_PHASE: ci-repair (nothing to repair)", flush=True)\n'
     "            return held\n",
     "        if held is not None:\n"
     "            pass\n"),

    ("the box does not say the words are a person's", BOX,
     "    ).repair_ci(cfg.issue, ci_log, pr_url=pr, human=human)\n",
     "    ).repair_ci(cfg.issue, ci_log, pr_url=pr)\n"),

    ("the worker does not say the words are a person's", ACTIVITIES,
     "        ).repair_ci(inp.issue, ci_log, pr_url=inp.pr_url, human=human)\n",
     "        ).repair_ci(inp.issue, ci_log, pr_url=inp.pr_url)\n"),

    ("the gate decides on a log and hands back none", REPAIRABLE,
     "        return None, decision.evidence\n",
     '        return None, ""\n'),
]
