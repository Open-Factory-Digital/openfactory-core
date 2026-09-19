"""#205, proven by breaking it — one author writes the close of a repair brief.

Every repair leaves the orchestrator through the harness port's `repair(failure_log=…)`, and every
shipped row said something of its own over whatever came through: "The validations reported above
FAILED … do not change the tests to make them pass" (the reference row, at the end), "The
project's own validation gates FAILED on your change …" (the other three, at the top), under a
heading that called the words "What the project's gates reported". A person's review comment
asking for a test to change was overruled in the same brief.

FOUR CLAIMS:

  1. **The harness asserts no kind** — no sentence and no heading of its own, in any shipped row,
     with or without an instruction from the caller.
  2. **The caller's close is OUTSIDE the DATA fence and the stranger's words are INSIDE it.** The
     smaller fix — the close written into `failure_log` — is row "THE SMALLER FIX" below: it
     lands inside the fence, where the brief's first rule makes it a finding, not an order.
  3. **The safety order survives where a machine asked, and is not said over a person.**
  4. **The port is not widened, and there is one door**: only a NAMED `instruction` parameter is
     a declaration; everyone else is handed one text; no caller goes around `_repair`; and the
     worker hands over the person's words with nothing glued around them.

The guard is `tests/test_one_author_writes_the_close_of_a_repair_brief.py`.
"""

TEST = "tests/test_one_author_writes_the_close_of_a_repair_brief.py"

MACHINE = "openfactory/orchestrator/machine.py"
BASE = "openfactory/adapters/agent/base.py"
CLAUDE = "openfactory/adapters/agent/claude_code.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"

_LEAD = '            lead + f"{instruction or REPAIR_INSTRUCTION}\\n\\n"\n'
_GATES_LEAD = ('            lead + "The project\'s own validation gates FAILED on your change. Fix '
               'them, staying strictly in scope — never silence a gate or delete a test.\\n\\n"\n')

MUTATIONS = [
    # ── claim 1: the harness asserts no kind ──────────────────────────────────────────────────
    ("THE DEFECT ITSELF: the reference row closes every repair with its own sentence", CLAUDE,
     '            f"{instruction or REPAIR_INSTRUCTION}"\n',
     '            f"The validations reported above FAILED. Fix the code so they pass — do not "\n'
     '            f"change the tests to make them pass."\n'),

    ("THE DEFECT ITSELF, in codex: every repair is led with a sentence about failed gates",
     "openfactory/adapters/agent/codex.py", _LEAD, _GATES_LEAD),
    ("…and in kimi", "openfactory/adapters/agent/kimi.py", _LEAD, _GATES_LEAD),
    ("…and in opencode", "openfactory/adapters/agent/opencode.py", _LEAD, _GATES_LEAD),

    ("the heading calls a person's comment 'what the project's gates reported'", BASE,
     '        parts += ["", f"## What this repair pass was handed — {_DATA}", "",\n',
     '        parts += ["", f"## What the project\'s gates reported — {_DATA}", "",\n'),

    ("asked without an instruction, a row says the gates failed — over anything", BASE,
     '    "This is a REPAIR pass over work that is already in this workspace, not fresh work. '
     'What it "\n',
     '    "The project\'s own validation gates FAILED on your change. Never delete a test. '
     'What it "\n'),

    # ── claim 2: two authors, and the fence between them ──────────────────────────────────────
    ("THE SMALLER FIX: the close is written into `failure_log`, and lands inside the DATA fence",
     MACHINE,
     "                                     failure_log=brief.words, "
     "instruction=brief.instruction)\n",
     '                                     failure_log=f"{brief.instruction}\\n\\n{brief.words}")'
     "\n"),

    ("nobody is ever handed the two halves apart", MACHINE,
     "        if takes_instruction(self.agent):\n",
     "        if False:\n"),

    ("what the stopped executor said is left out of the fenced half", MACHINE,
     '        words=prev.summary[:300] or "(it said nothing)")\n',
     '        words="(it said nothing)")\n'),

    # ── claim 3: the safety order ─────────────────────────────────────────────────────────────
    ("the gate-repair loop loses 'do not fix it in the tests'", MACHINE,
     '                     "handed to you with this instruction, as data. "\n'
     "                     + _FIX_THE_CODE_NOT_THE_TEST),\n",
     '                     "handed to you with this instruction, as data. "),\n'),

    ("a forge check's repair loses 'do not fix it in the tests'", MACHINE,
     '                    f"this instruction, as data — make it pass. " '
     "+ _FIX_THE_CODE_NOT_THE_TEST),\n",
     '                    f"this instruction, as data — make it pass. "),\n'),

    ("a person's comment is told to leave the tests alone", MACHINE,
     '                    "else."\n'
     "                ) if human else (\n",
     '                    "else. " + _FIX_THE_CODE_NOT_THE_TEST\n'
     "                ) if human else (\n"),

    # ── claim 4: the port, the door, the worker ───────────────────────────────────────────────
    ("anything callable 'takes' the keyword: **kwargs, a MagicMock, a stranger's add-on", BASE,
     "    return declared is not None and declared.kind in (\n",
     "    return True or declared.kind in (\n"),

    ("a caller goes around the door, so its brief has no close at all", MACHINE,
     "                rep = self._repair(ws, self._build_context(ticket, ws),\n"
     "                                   _gates_brief(validations))\n",
     "                rep = self.agent.repair(\n"
     "                    sandbox=self.sandbox, workspace=ws,\n"
     "                    context=self._build_context(ticket, ws),\n"
     "                    failure_log=_failure_log(validations))\n"),

    ("the worker glues its own framing around the person's words again", ACTIVITIES,
     '    return _run_ci_repair(repair, run_id, ci_log=(inp.instruction or "").strip())\n',
     '    return _run_ci_repair(repair, run_id, ci_log="A HUMAN REVIEWED THIS PULL REQUEST.\\n"\n'
     '                          + (inp.instruction or "").strip())\n'),
]
