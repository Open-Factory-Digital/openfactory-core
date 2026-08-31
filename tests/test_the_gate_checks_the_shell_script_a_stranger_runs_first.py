"""`install.sh` is checked by the same command the gate runs, not by a job of its own.

R6, MADE CONCRETE. `tests/test_ci_runs_what_we_run.py` exists because CI and the gate drifted by
one word — `ruff check openfactory/ tests/` here against `… addons/` there — and the add-on
packages went unlinted on the only machine where it counted, for as long as nobody looked. The
same gap is available again the moment a NEW kind of check arrives: a shellcheck step written
directly into `ci.yml` would be green on every laptop and run on exactly one machine, and the
first contributor to break the installer would find out from a CI failure they cannot reproduce.

So shellcheck goes into `make lint`, which is the line CI runs and the line a contributor runs.
This file holds that arrangement in place, and holds the two halves that make it honest: the
script really is covered, and a machine that cannot run shellcheck REFUSES rather than skipping —
`make lint` passing while checking nothing is the "absence read as compliance" shape this codebase
has paid for more than once.

THE END-TO-END JOB IS DELIBERATELY NOT HERE. It needs a published release and pulls several
gigabytes, so it runs on a release and on demand rather than on every pull request; what it may
not do is quietly stop existing, and the last test says so.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAKEFILE = (ROOT / "Makefile").read_text()
CI = ROOT / ".github" / "workflows" / "ci.yml"
E2E = ROOT / ".github" / "workflows" / "install-e2e.yml"


def _make_n_lint() -> str:
    """What `make lint` would actually run, expanded by make itself rather than by our guess —
    the same technique `test_ci_runs_what_we_run.py` uses to read the ruff line."""
    done = subprocess.run(["make", "-n", "lint"], cwd=ROOT, capture_output=True, text=True,
                          timeout=120)
    assert done.returncode == 0, done.stderr[-500:]
    return done.stdout


def test_make_lint_checks_the_installer():
    """The one artefact in this repository that no Python test can execute, and the first thing a
    stranger runs."""
    expansion = _make_n_lint()

    assert "shellcheck" in expansion, (
        "`make lint` does not run shellcheck — install.sh would be checked by nothing a "
        "contributor runs")
    assert "install.sh" in expansion, (
        "`make lint` runs shellcheck over something other than install.sh")


def test_it_checks_every_shell_script_that_ships():
    """DERIVED, not a name typed here. `docker/install-addons.sh` is the other one — it decides
    whether the public build installs the core alone or aborts, and a reviewer once replaced its
    existence test with one that is always true while 23 guards stayed green. Whichever scripts
    the tree ships, the lint line has to cover them."""
    shipped = sorted(
        str(p.relative_to(ROOT)) for p in ROOT.rglob("*.sh")
        if not any(part in {".venv", ".git", "node_modules", "__pycache__"}
                   for part in p.relative_to(ROOT).parts))
    assert len(shipped) >= 2, f"only {shipped} — this guard has almost no subject"

    expansion = _make_n_lint()
    missing = [rel for rel in shipped if rel not in expansion]
    assert not missing, (
        f"`make lint` does not shellcheck {missing}. A shell script nothing checks is the one that "
        f"breaks the first command a stranger runs.")


def test_the_scripts_it_checks_are_judged_as_POSIX_sh_and_not_as_bash():
    """`install.sh` opens `#!/bin/sh` and is POSIX on purpose — Debian's `/bin/sh` is dash, and a
    bashism that shellcheck waved through under the wrong dialect would fail on the machines this
    is most likely to be piped into. The dialect is the difference between checking the script and
    checking a script that happens to have the same text."""
    expansion = _make_n_lint()

    # EVERY invocation, not "somewhere in the recipe". There are two — a local shellcheck and the
    # container — and a mutation that widened only the LOCAL one to `-s bash` left the other
    # carrying `-s sh` and this guard green (2026-08-31). Whichever branch a given machine takes
    # is the branch that has to be judging POSIX.
    assert "-s bash" not in expansion, (
        "a shellcheck invocation judges these as bash — a bashism then passes here and fails on "
        "any Debian-family machine, where /bin/sh is dash")
    assert expansion.count("-s sh") >= 2, (
        f"only {expansion.count('-s sh')} of the shellcheck invocations name the POSIX dialect; "
        f"both branches must, or the check depends on which one your machine happens to take")


def test_a_machine_that_cannot_run_shellcheck_refuses_by_name():
    """THE half that decides whether this is a check or a decoration. shellcheck is a Haskell
    binary, not a Python dependency, so `make install` cannot supply it and most machines lack it
    (measured on the machine this was written on, 2026-08-30). Skipping quietly would make
    `make lint` pass while checking nothing."""
    recipe = _make_n_lint()

    assert "exit 1" in recipe, (
        "the shellcheck step cannot fail — a machine with neither shellcheck nor Docker would see "
        "`make lint` pass while nothing checked the installer")
    for remedy in ("shellcheck", "Docker"):
        assert remedy in recipe, f"the refusal does not name {remedy} as a way to fix it"


def test_it_prefers_a_local_shellcheck_and_falls_back_to_the_container():
    """Order matters: a contributor who installed shellcheck should not wait for a container pull,
    and a contributor who has only Docker should still be covered."""
    recipe = _make_n_lint()
    local = recipe.index("command -v shellcheck")
    container = recipe.index("koalaman/shellcheck")

    assert local < container, "the container is tried before a local shellcheck"


def test_ci_still_runs_the_line_that_carries_it():
    """The whole arrangement rests on CI running `make lint` rather than its own ruff invocation.
    If CI ever inlines the command again, shellcheck silently stops being part of the gate — which
    is the exact drift R6 is about, arriving from the other direction."""
    workflow = CI.read_text()

    assert re.search(r"^\s*-\s*run:\s*make\s+lint\s*$", workflow, re.M), (
        "ci.yml no longer runs `make lint` — anything the Makefile adds to the gate (shellcheck "
        "today, whatever comes next) stops reaching CI")


# ── the end-to-end job ──────────────────────────────────────────────────────────────────────────

def test_the_no_python_end_to_end_job_exists():
    """"Requires only Docker" is a sentence nobody has measured until something runs the real
    one-liner on a machine with no Python. This is that job, and its absence would leave the
    headline claim resting entirely on guards that read the installer's TEXT."""
    assert E2E.is_file(), (
        "there is no end-to-end install workflow — every other guard checks what install.sh SAYS, "
        "and none of them can tell you whether it works")

    workflow = yaml.safe_load(E2E.read_text())
    job = next(iter(workflow["jobs"].values()))
    steps = " ".join(str(s.get("run", "")) for s in job["steps"])

    assert "install.sh" in steps, "the job never runs the installer"
    assert "python" in steps.lower(), (
        "the job never establishes that the container has no Python, which is the claim under test")


def test_the_end_to_end_job_asserts_a_healthy_panel_and_a_preflight_that_speaks():
    """A stack that starts and serves nothing is not an install; a preflight that names nothing is
    not a diagnosis. Both halves are what the plan's success metrics are written in terms of."""
    steps = " ".join(str(s.get("run", "")) for s in
                     next(iter(yaml.safe_load(E2E.read_text())["jobs"].values()))["steps"])

    # THE FAILING ASSERTION, not the token. `8787` and `remedy` both appear in the job's prose, so
    # a cut that replaced the real checks with `true` and `pass` left this guard green
    # (2026-08-31). What is asserted now is the sentence the job would print when it fails —
    # which cannot survive the check being deleted.
    assert "the panel never answered" in steps, (
        "the job does not FAIL when the panel stays silent — it may curl it and shrug")
    assert "preflight" in steps, "the job never asks what is left on the machine"
    assert 'finding["remedy"]' in steps, (
        "the job accepts a preflight report without asserting that its refusals carry remedies")
    assert "refuses with no remedy" in steps, (
        "the job's remedy check cannot fail — there is no message it would print")


@pytest.mark.parametrize("trigger", ["release", "workflow_dispatch"])
def test_it_runs_when_there_is_something_to_prove_and_not_on_every_pull_request(trigger):
    """It needs a release that exists — the script resolves `releases/latest`, verifies against
    SHA256SUMS and pulls three images — and measured 2026-08-30 there were none. On
    `pull_request` it would make every PR red for a reason no PR caused, which is how a gate gets
    disabled and takes the real one with it."""
    workflow = yaml.safe_load(E2E.read_text())
    # PyYAML reads a bare `on:` as the boolean True (YAML 1.1's Norway problem), in the one place
    # it actually bites a CI file.
    triggers = workflow.get("on") or workflow.get(True)

    assert trigger in triggers, f"the end-to-end job cannot be started by {trigger}"
    assert "pull_request" not in triggers, (
        "the end-to-end install runs on every pull request — it pulls several gigabytes and needs "
        "a published release, so it would be red for reasons no PR caused")


def test_the_end_to_end_job_is_not_a_pytest_test():
    """It must never migrate into the suite. Collection may not depend on Docker or a network: a
    module that resolved such a thing at import took the whole suite down for fifteen days in
    2026-08 while every laptop stayed green."""
    # THIS FILE IS EXCLUDED, and it has to be: it holds the exact string it is hunting for, so a
    # scan that read itself would be its own first offender. `tests/test_the_remedy_a_refusal_
    # hands_you_can_be_followed.py` excludes itself for the same reason, and names it.
    offenders = [str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_*.py")
                 if p.name != pathlib.Path(__file__).name and "install.sh --dir" in p.read_text()]

    assert not offenders, (
        f"{offenders} run the installer for real from inside the suite — that needs a daemon, a "
        f"network and a published release, and the suite must not change what it collects based "
        f"on whether this machine has them")


def test_the_end_to_end_job_runs_as_a_user_who_could_actually_hit_the_socket_defect():
    """A TEST WHOSE ENVIRONMENT EXCLUDES THE FAILURE IS NOT COVERING IT.

    This job ran the installer as ROOT inside `debian:12-slim`, and a reviewer named the
    consequence exactly (2026-08-31): `id -u` is 0, so `install.sh`'s `-u 0:0` reads any socket
    regardless of groups, and the one job that runs the real thing was the single arrangement in
    which the supplementary-group defect CANNOT appear. Meanwhile the defect broke every ordinary
    Linux workstation, where the socket is `srw-rw---- root docker` and a user reaches it through a
    supplementary group that `-u uid:gid` discards.

    So the job now builds the shape it is meant to be testing: an unprivileged user whose PRIMARY
    group is its own, holding the socket's group as a SUPPLEMENTARY one."""
    steps = " ".join(str(s.get("run", "")) for s in
                     next(iter(yaml.safe_load(E2E.read_text())["jobs"].values()))["steps"])

    assert "useradd" in steps, (
        "the end-to-end job creates no unprivileged user — as root it cannot reproduce the "
        "supplementary-group defect that broke every ordinary Linux install")
    assert "sudo -u" in steps or "--user" in steps, (
        "the installer is still invoked as root in the end-to-end job")
    assert "usermod -aG" in steps, (
        "the user is not given the socket's group as a SUPPLEMENTARY one — a primary gid that "
        "happens to match would pass while `-u uid:gid` was still dropping the group")
