"""Two guards that passed or failed with the LAUNCHER, and the check that makes it impossible.

`test_walking_skeleton.py`'s two scope-cap guards declare components on `stack: python`, so they
inherit `openfactory/presets/python.yaml` — `ruff check .`, `bandit -r . -ll -q`, `mypy .` — and
the walking skeleton runs its gates for real in a WorktreeSandbox on the HOST. Those commands
resolve against the PATH of whoever started pytest: present under `source .venv/bin/activate`,
absent under `.venv/bin/python -m pytest`, where `/bin/sh` answers 127. A non-zero gate is a FAILED
gate, so the run entered `agent.repair` — which both guards assert never happens.

Measured, on one commit, one machine, minutes apart: 2 failed without the venv on PATH, 2 passed
with it. For weeks this was recorded as an intermittent flake and every full-suite result carried
a caveat naming these two tests.

ROWS 1-3 ARE THE TEST HALF. Row 1 is the fix itself: the manifest names all four roles, so nothing
is inherited from a preset. Row 2 is the mechanism it relies on — repo-wide beats a touched
component's preset — which is a property of `applicable_validations`, not of that file. Row 3 is
the trap inside the fix: the preset's role is `type`, not `types`, and a near-miss silently
restores `mypy .` for that one role while the other three look declared.

ROWS 4-11 ARE THE PRODUCTION DEFECT THE TEST HALF WAS WEARING. `passed=(rc == 0)` makes a shell's
"command not found" indistinguishable from a linter's verdict on the code, so the platform spends
the project's whole repair budget — real model calls, real money — asking an agent to fix a diff
that is not what is wrong, and then parks the job with a sentence about the code. Rows 4 and 5 are
the recognition itself (and its cheap direction: a gate may exit 127 on its own business, and that
is still a failure); 6 and 7 are who gets held and who does not; 8, 9 and 11 are what the human is
then told; row 10 is the one direction this codebase never takes — an unrun gate counted as green.

ROWS 13-16 ARE THE OTHER HALF OF "WHO IS TOLD". A hold is the right sentence for the ticket that
hit it and the wrong home for the trouble: a tool missing from the image holds every ticket
touching that component, once each, until somebody fixes the image — an outage arriving as a queue
of individually reasonable holds. `ops/impediment` is this platform's answer to that shape, and
these rows pin the wire to it: filed on the factory's own board with the cause and the command
(13), CLOSED BY OBSERVATION when the gates run again rather than by anyone's say-so (14), never
filed for a suite that ran and went red, which is the client's code and the repair loop's business
(15), and a method that exists and is called by nothing (16) — this codebase's signature defect,
and the one an impediment nobody files looks exactly like.

Every row is killed by the new check, which resolves the gates the runner would run and requires
each command to be one that cannot be missing — deterministically, on any machine, which is the
point: the defect it replaces was only visible on some.

Read the counts with that in mind. Rows 1 and 3 show `3 failed` here — the new check plus the two
scope guards, because the machine this ran on has no `ruff` on its PATH. On a machine that does,
the same rows show `1 failed`: the check alone, still red, still naming the cause. That difference
IS the change.
"""

TEST = "tests/test_a_gate_that_could_not_run.py"

_SPINE = "tests/test_walking_skeleton.py"

MUTATIONS = [
    ("the manifest goes back to declaring `test` alone, so the three preset gates return and the "
     "two scope guards decide by what happens to be installed on the machine running them",
     "tests/test_walking_skeleton.py",
     '        "validate": {"test": "true", "lint": "true", "security": "true", "type": "true"},',
     '        "validate": {"test": "true"},',
     _SPINE),

    ("a repo-wide role stops beating a touched component's stack preset, so declaring the gates "
     "in the manifest no longer keeps the host's tools out of the run",
     "openfactory/orchestrator/validation.py",
     "    # 2. repo-wide overlays the presets (the project's explicit choice wins)\n"
     "    cmds.update(manifest.validation)",
     "    # 2. repo-wide overlays the presets (the project's explicit choice wins)\n"
     "    pass",
     _SPINE),

    ("the type gate is named `types`, the plural the preset does not use — three roles look "
     "declared, `mypy .` quietly comes back for the fourth, and the flake returns for one gate",
     "tests/test_walking_skeleton.py",
     '"lint": "true", "security": "true", "type": "true"},',
     '"lint": "true", "security": "true", "types": "true"},',
     _SPINE),

    # ── the product half: who is asked to act ───────────────────────────────────────────────────
    ("the exit code alone decides, so a gate that exits 127 on its own business is read as a "
     "command that was never there — and a job repair could have fixed is parked instead",
     "openfactory/orchestrator/validation.py",
     '    for line in (output or "").splitlines():\n'
     "        if any(said in line.lower() for said in _NEVER_RAN_SAID):\n"
     "            return line.strip()[:200]\n"
     '    return ""',
     '    return (output or "").strip().splitlines()[-1][:200] if output else "missing command"'),

    ("nothing is ever recognised as unrunnable, which is the state this change found: the shell's "
     "'command not found' and a linter's verdict on the code are one fact again",
     "openfactory/orchestrator/validation.py",
     "    if exit_code not in _NEVER_RAN_CODES:\n"
     '        return ""',
     '    return ""\n'
     "    if exit_code not in _NEVER_RAN_CODES:\n"
     '        return ""'),

    ("the repair loop stops refusing to start, so the project's whole repair budget goes on paid "
     "attempts to fix a diff that is not what is wrong",
     "openfactory/orchestrator/machine.py",
     "                and not _never_ran(validations)",
     "                and True"),

    ("an advisory gate whose tool is missing holds the job — the exact inversion of what advisory "
     "means, and the first thing a client would turn off",
     "openfactory/orchestrator/machine.py",
     "    return [v for v in validations if v.unrunnable and not v.advisory]",
     "    return [v for v in validations if v.unrunnable]"),

    ("the hold goes back to blaming the diff, so the operator reads 'validations failed after 0 "
     "repair attempt(s)' and goes to look at the code",
     "openfactory/orchestrator/machine.py",
     "                reason = (_never_ran_reason(validations)\n"
     '                          or f"validations failed after {attempts} repair attempt(s)")',
     '                reason = f"validations failed after {attempts} repair attempt(s)"'),

    ("the repair brief carries the missing tool again, so an agent is handed 'bandit: not found' "
     "as something to fix and edits whatever it can",
     "openfactory/orchestrator/machine.py",
     "        if not v.passed and not v.unrunnable",
     "        if not v.passed"),

    ("a gate that could not run is counted as PASSED — the dangerous direction, and the one this "
     "codebase never takes: an unrun gate proves nothing, so a green built on it is a claim "
     "nobody earned",
     "openfactory/orchestrator/machine.py",
     "                name=name, command=cmd, exit_code=rc, passed=(rc == 0),",
     "                name=name, command=cmd, exit_code=rc, passed=(rc == 0 or bool(unrunnable)),"),

    ("the journal says FAIL for a gate that never ran, which is what sends the operator to the "
     "diff instead of to the box",
     "openfactory/orchestrator/machine.py",
     "                f\"{name}: {'PASS' if vr.passed else "
     "('COULD NOT RUN' if unrunnable else 'FAIL')}\"",
     "                f\"{name}: {'PASS' if vr.passed else 'FAIL'}\""),

    ("the pull request tells the reader a missing tool 'reported findings' — a claim about a "
     "reading nobody made, on the only surface an unrunnable gate can still reach a person",
     "openfactory/orchestrator/machine.py",
     "        reported = [v for v in result.validations\n"
     "                    if v.advisory and not v.passed and not v.unrunnable]",
     "        reported = [v for v in result.validations if v.advisory and not v.passed]"),

    # ── the factory's own board ─────────────────────────────────────────────────────────────────
    ("the impediment is never filed, so a missing tool lives only in one ticket's hold — and the "
     "next ticket's, and the next, with nothing that counts them or owns them",
     "openfactory/orchestrator/machine.py",
     "        if _never_ran(validations):\n"
     "            impediment.report(self.project, impediment.GATE_CANNOT_RUN,\n"
     "                              _never_ran_reason(validations))",
     "        if _never_ran(validations):\n"
     "            pass"),

    ("nothing ever closes it, so the ticket outlives the trouble and the board stops meaning "
     "anything — the one thing ADR-0021's close-by-observation rule exists to prevent",
     "openfactory/orchestrator/machine.py",
     "            impediment.resolved(\n"
     "                self.project, impediment.GATE_CANNOT_RUN,\n"
     '                evidence="; ".join(f"`{v.name}`: {v.command} (exit {v.exit_code})"\n'
     "                                   for v in validations[:4]))",
     "            pass"),

    ("a suite that ran and went red is filed as a platform failure too, which turns a board that "
     "has to stay countable into a copy of every job that ever failed a gate",
     "openfactory/orchestrator/machine.py",
     "        if _never_ran(validations):\n"
     "            impediment.report(self.project, impediment.GATE_CANNOT_RUN,",
     "        if not _all_passed(validations):\n"
     "            impediment.report(self.project, impediment.GATE_CANNOT_RUN,"),

    ("the accounting is built and reached by nothing — this codebase's signature defect, and the "
     "shape an impediment nobody files is indistinguishable from",
     "openfactory/orchestrator/machine.py",
     "            self._account_for_gates_that_could_not_run(validations)",
     "            pass"),

    # ── the independent reviewer ────────────────────────────────────────────────────────────────
    ("the shared reviewer prompt reports a gate that never ran as FAIL, so the one reader whose "
     "job is independence is handed evidence the diff broke something nobody checked",
     "openfactory/adapters/reviewer/harness.py",
     '        f"- {v.name}: "\n'
     "        f\"{'PASS' if v.passed else ('COULD NOT RUN' if v.unrunnable else 'FAIL')} \"",
     '        f"- {v.name}: "\n'
     "        f\"{'PASS' if v.passed else 'FAIL'} \""),

    ("the Claude Code reviewer's own copy of that rendering keeps saying FAIL — the duplication is "
     "older than this change, and one of the two learning the distinction is how they drift",
     "openfactory/adapters/reviewer/claude_code.py",
     '            f"- {v.name}: "\n'
     "            f\"{'PASS' if v.passed else ('COULD NOT RUN' if v.unrunnable else 'FAIL')} \"",
     '            f"- {v.name}: "\n'
     "            f\"{'PASS' if v.passed else 'FAIL'} \""),
]
