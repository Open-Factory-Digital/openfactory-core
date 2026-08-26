"""The suite must pass the way CI RUNS it, not only the way a developer runs it.

FOUND 2026-08-05, with five commits already landed on a red `main`. `pytest -q` — the exact
command `.github/workflows/ci.yml` runs — died in COLLECTION:

    ImportError: Error importing plugin "tests.test_walking_skeleton": No module named 'tests'

`tests/test_a_failing_setup_is_not_silent.py` declares `pytest_plugins = [...]`, which pytest
imports by name, so the `tests` package must be importable. `python -m pytest` prepends the
current directory to `sys.path` and it was; the bare `pytest` console script does not. Every
developer ran the first form and saw 3599 green; CI ran the second and saw one error, on every
push, for days — the platform that enforces gates on other repositories shipping past its own.

That is `validate-in-the-cloud-not-just-local` in its cheapest possible form: the difference was
not the cloud, the OS or a dependency. It was the first two words of the command.

The fix is `pythonpath = ["."]` in the pytest config, so both invocations are identical. This
file is the guard that keeps them that way — it runs the CI invocation, in a subprocess, and
fails loudly when collection does.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _console_script() -> str:
    """THIS environment's `pytest` console script, not whatever `PATH` happens to find.

    The point of these tests is one difference — console script vs `python -m` — so every OTHER
    difference has to be held still. A bare `"pytest"` picks up the system interpreter's copy,
    which has none of this project's dependencies, and then reports a pile of import errors that
    look exactly like the bug and are not it."""
    return str(Path(sys.executable).parent / "pytest")


def test_the_bare_pytest_console_script_can_COLLECT_the_suite():
    """THE regression, run for real. Collection is enough: an import-time failure (a plugin, a
    conftest, a missing package) is the whole class this guard exists for, and collecting the
    full suite costs ~2s while running it twice would cost minutes."""
    proc = subprocess.run(
        [_console_script(), "-q", "--collect-only"],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )

    assert proc.returncode == 0, (
        "the suite does not COLLECT under the bare `pytest` console script — which is exactly "
        "what CI runs, so CI is red no matter how green this machine looks:\n"
        f"{(proc.stdout + proc.stderr)[-1500:]}"
    )


def test_that_invocation_sees_the_same_tests_this_one_does():
    """A collection that succeeds while seeing FEWER tests is the same failure wearing a green
    tick — `testpaths`, an import mode or a rootdir difference silently hiding a directory."""
    proc = subprocess.run(
        [_console_script(), "-q", "--collect-only"],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )
    match = re.search(r"(\d+) tests? collected", proc.stdout)
    assert match, f"could not read the collected count from:\n{proc.stdout[-800:]}"

    collected = int(match.group(1))
    # this process was itself started by pytest, so its own count is the reference
    mine = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only"],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )
    mine_match = re.search(r"(\d+) tests? collected", mine.stdout)
    assert mine_match, "could not read the reference count"

    assert collected == int(mine_match.group(1)), (
        f"`pytest` collects {collected} tests and `python -m pytest` collects "
        f"{mine_match.group(1)} — CI and this machine are running different suites"
    )


def test_collection_survives_a_machine_without_THE_OPTIONAL_TOY_PROJECTS():
    """AND IT HAPPENED AGAIN, for fifteen days — the two guards above ran in a subprocess but
    INHERITED THIS MACHINE'S ENVIRONMENT, where `~/Projects/…` holds the toy projects. So both
    collected fine, on the one machine where the missing piece is not missing.

    On 2026-08-06 `88139ad` added, at module scope, `FIXTURES = demo_projects()` followed by
    `FIXTURES / "fx-dsk-flows"`. `demo_projects()` answers None where there is nothing to read —
    correctly, and its docstring says so — and None divided by a string raises `TypeError` at
    IMPORT. One module raising during collection aborts the ENTIRE run: `Interrupted: 1 error
    during collection`. Every CI run from that commit until 2026-08-21 executed ZERO tests and
    reported failure. 253 of them. The platform that refuses to merge a client's red branch had
    been shipping past its own gate for a fortnight, and the tree was genuinely green here.

    THE PROPERTY, stated so it outlives the toy projects: collection must not depend on OPTIONAL
    WORKING STATE. A contributor with a fresh clone and none of the author's directories must
    collect the same suite this machine does — the tests that need those directories skip at RUN
    time, which is a decision each test makes, not one that deletes everybody else's.
    """
    stripped = {**os.environ, "OPENFACTORY_FIXTURES": str(ROOT / "no-such-toy-projects")}
    proc = subprocess.run(
        [_console_script(), "-q", "--collect-only"],
        cwd=ROOT, capture_output=True, text=True, timeout=300, env=stripped,
    )

    assert proc.returncode == 0, (
        "collection needs optional working state that no other machine has — CI collects nothing "
        "and every run is red while this laptop stays green:\n"
        f"{(proc.stdout + proc.stderr)[-1500:]}"
    )

    #: THE POSITIVE TWIN, and the half that matters most. A module can also fail SOFTLY: wrap the
    #: import in a try/except, or call `pytest.skip(allow_module_level=True)`, and it stops raising
    #: — it just stops EXISTING, and the suite shrinks without a word. Absence read as compliance.
    #:
    #: ASKED OF THIS ONE COLLECTION, not of a second reference run. Comparing two collections taken
    #: seconds apart makes the guard depend on the tree holding still, and under `-n auto` it does
    #: not: the first version of this test failed once in three full runs and passed alone every
    #: time. A guard that flakes is a guard somebody deletes, and it would have taken the fifteen
    #: days of evidence above with it.
    #:
    #: THE MODULES ARE DERIVED, never listed by hand — whoever adds the fifth caller of
    #: `demo_projects_root` is covered without knowing this file exists.
    dependents = sorted(p.name for p in (ROOT / "tests").glob("test_*.py")
                        if "demo_projects" in p.read_text())
    assert len(dependents) >= 4, (
        f"only {dependents} read the toy projects — this guard has lost its subject")

    missing = [name for name in dependents if name not in proc.stdout]
    assert not missing, (
        f"{missing} vanish from collection on a machine without the toy projects, instead of "
        f"skipping at run time — every contributor and CI silently loses those tests, and the "
        f"suite reports green about coverage that did not run")


@pytest.mark.skipif(not CI.exists(), reason="no CI workflow in this checkout")
def test_ci_still_runs_the_command_this_guard_protects():
    """If CI's command changes, this guard is protecting the wrong thing — and would keep
    passing while saying nothing, which is the failure shape it was written against."""
    workflow = CI.read_text()

    assert re.search(r"^\s*-\s*run:\s*.*\bpytest\b", workflow, re.M), (
        "ci.yml no longer runs pytest — update this guard to whatever it runs now, or it is "
        "asserting a property nobody depends on"
    )


# ── the linter, too ─────────────────────────────────────────────────────────────────────────────
#
# FOUND 2026-08-26 by the review of the chat cut: the gate ran `ruff check openfactory/ tests/
# addons/` and CI ran `ruff check openfactory/ tests/` — the add-on packages were never linted
# where it counts. Same class as the collection defect above: the command differed by one word.
# The roots are DERIVED (the package by its installed name, the first segment of every pytest
# testpath, kept to what the tree holds — `addons/` leaves the export), and the line CI runs is
# resolved the way CI resolves it: `make -n <target>` when CI names a Makefile target, so the
# Makefile's own expansion (`$(wildcard addons)`) is what gets read, not our guess at it.


def _lint_roots_the_suite_covers() -> set[str]:
    import openfactory

    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    roots = {Path(openfactory.__file__).resolve().parent.name}
    roots |= {p.split("/", 1)[0] for p in config["tool"]["pytest"]["ini_options"]["testpaths"]}
    return {r for r in roots if (ROOT / r).is_dir()}


def _ruff_line_ci_runs() -> str:
    """The `ruff check …` CI ends up running: a `run:` line of its own, or the Makefile target
    it names, expanded by make itself."""
    runs = re.findall(r"^\s*-\s*run:\s*(.+?)\s*$", CI.read_text(), re.M)
    direct = [r for r in runs if re.search(r"\bruff check\b", r)]
    if direct:
        return direct[0]
    for run in runs:
        m = re.fullmatch(r"make\s+(\S+)", run)
        if not m:
            continue
        shown = subprocess.run(["make", "-n", m.group(1)], cwd=ROOT, capture_output=True,
                               text=True, timeout=60)
        for line in shown.stdout.splitlines():
            if re.search(r"\bruff check\b", line):
                return line.strip()
    return ""


def _ruff_targets(line: str) -> set[str]:
    words = line.split()
    assert words[:2] == ["ruff", "check"], line
    return {w.rstrip("/") for w in words[2:] if not w.startswith("-")}


@pytest.mark.skipif(not CI.exists(), reason="no CI workflow in this checkout")
def test_ci_lints_every_root_the_suite_covers():
    line = _ruff_line_ci_runs()
    assert line, "ci.yml runs no `ruff check` — directly or through a Makefile target"
    roots = _lint_roots_the_suite_covers()
    assert {"openfactory", "tests"} <= roots, roots
    missing = sorted(roots - _ruff_targets(line))
    assert not missing, (
        f"CI lints {sorted(_ruff_targets(line))} and the suite covers {sorted(roots)} — {missing} "
        f"are never linted where it counts (`ruff check` runs as `{line}`)")


def test_the_roots_follow_the_tree_and_the_line_reader_can_SEE_a_target():
    """Verify the verifier: the derived set holds the add-on packages exactly when the tree does,
    and the reader distinguishes a target from a flag."""
    roots = _lint_roots_the_suite_covers()
    assert ("addons" in roots) == (ROOT / "addons").is_dir()
    assert _ruff_targets("ruff check openfactory/ tests/ --fix addons") == {"openfactory", "tests",
                                                                            "addons"}
