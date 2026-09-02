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

ROW 1 is the fix itself: the manifest names all four roles, so nothing is inherited from a preset.
ROW 2 is the mechanism it relies on — repo-wide beats a touched component's preset — which is a
property of `applicable_validations`, not of this file. ROW 3 is the trap inside the fix: the
preset's role is `type`, not `types`, and a near-miss silently restores `mypy .` for that one role
while the other three look declared.

Every row is killed by the new check, which resolves the gates the runner would run and requires
each command to be one that cannot be missing — deterministically, on any machine, which is the
point: the defect it replaces was only visible on some.

Read the counts with that in mind. Rows 1 and 3 show `3 failed` here — the new check plus the two
scope guards, because the machine this ran on has no `ruff` on its PATH. On a machine that does,
the same rows show `1 failed`: the check alone, still red, still naming the cause. That difference
IS the change.
"""

TEST = "tests/test_walking_skeleton.py"

MUTATIONS = [
    ("the manifest goes back to declaring `test` alone, so the three preset gates return and the "
     "two scope guards decide by what happens to be installed on the machine running them",
     "tests/test_walking_skeleton.py",
     '        "validate": {"test": "true", "lint": "true", "security": "true", "type": "true"},',
     '        "validate": {"test": "true"},'),

    ("a repo-wide role stops beating a touched component's stack preset, so declaring the gates "
     "in the manifest no longer keeps the host's tools out of the run",
     "openfactory/orchestrator/validation.py",
     "    # 2. repo-wide overlays the presets (the project's explicit choice wins)\n"
     "    cmds.update(manifest.validation)",
     "    # 2. repo-wide overlays the presets (the project's explicit choice wins)\n"
     "    pass"),

    ("the type gate is named `types`, the plural the preset does not use — three roles look "
     "declared, `mypy .` quietly comes back for the fourth, and the flake returns for one gate",
     "tests/test_walking_skeleton.py",
     '"lint": "true", "security": "true", "type": "true"},',
     '"lint": "true", "security": "true", "types": "true"},'),
]
