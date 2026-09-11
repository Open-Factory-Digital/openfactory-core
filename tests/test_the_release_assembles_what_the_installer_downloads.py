"""The release's asset assembly is RUN here, in both directions, on every pull request.

WHY THIS FILE EXISTS. The assembly used to be eleven lines inside `.github/workflows/release.yml`,
and nothing outside a real tag could execute them. A shell bug there therefore cost a version
number to discover, and two of them did:

  v0.1.1  the env template was attached as `.env.compose.example`. GitHub does not permit a release
          asset name to begin with a dot and silently rewrites it to `default.…`, so `install.sh`
          fetched a 404 and every install died at the interview step. The same dot hid the file
          from `sha256sum ./*` — which does not match dotfiles — so it was never checksummed
          either. One character, two failures, in opposite halves of the release.
  v0.1.2  the guard added for that was `for f in dist/.*`, and an unmatched glob is left LITERAL by
          the shell. With no dotfiles present the loop ran once, over the string `dist/.*`, and
          reported it: the release job exited 1, no Release was created, and the end-to-end install
          was skipped for the third tag running.

THE SECOND ONE IS THE INTERESTING ONE, because the check WAS the failure rather than what it
watched — the fourth time in this work that something present and correct-reading could not do its
job. It is also why this is a script (`scripts/collect-release-assets.sh`) rather than a `run:`
block: a workflow whose logic can only be exercised by tagging is the same circularity that was
removed from the end-to-end job, one layer down.

WHAT IS ASSERTED IS BEHAVIOUR, NOT TEXT. Every test below executes the real script and reads what
it produced. Text-matching is what let both defects through — the v0.1.1 guard was even satisfied
by a comment describing the defect it was written to catch.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "collect-release-assets.sh"

_TOOLS = ("sh", "sha256sum", "find", "sed")
_MISSING = [tool for tool in _TOOLS if shutil.which(tool) is None]
needs_a_posix_shell = pytest.mark.skipif(
    bool(_MISSING), reason=f"this machine has no {_MISSING} — the assembly cannot be run here")


def _assemble(dist: pathlib.Path) -> subprocess.CompletedProcess[str]:
    """Run the real assembly script against `dist`, from the repository root as CI does."""
    return subprocess.run(["sh", str(SCRIPT), str(dist)],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)


def _assets_the_installer_downloads() -> set[str]:
    """The names `install.sh` fetches, read out of its own `ASSETS` list."""
    text = (ROOT / "install.sh").read_text()
    match = re.search(r'^ASSETS="([^"]+)"', text, re.M)
    assert match, "install.sh no longer declares ASSETS — this guard cannot see what it fetches"
    return set(match.group(1).split())


def test_the_script_is_the_one_the_workflow_runs():
    """Verify the premise. A script the suite exercises and the workflow does not is theatre — and
    it is precisely the arrangement that let the v0.1.2 defect ship."""
    import yaml

    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())
    steps = " ".join(str(s.get("run", "")) for s in workflow["jobs"]["release"]["steps"])

    assert SCRIPT.is_file(), f"{SCRIPT} does not exist"
    assert "scripts/collect-release-assets.sh" in steps, (
        "release.yml does not run the assembly script, so what this file proves is not what a tag "
        "would do")


@needs_a_posix_shell
def test_a_clean_tree_assembles_and_the_v0_1_2_guard_does_not_fire_on_itself(tmp_path):
    """THE v0.1.2 FAILURE, as the ordinary case. There are no dotfiles in a freshly assembled
    `dist/`, which is exactly when the old `for f in dist/.*` loop reported its own unexpanded
    pattern and exited 1."""
    done = _assemble(tmp_path / "dist")

    assert done.returncode == 0, (
        f"the assembly refused a clean tree — this is the v0.1.2 failure:\n{done.stderr}")
    assert (tmp_path / "dist" / "SHA256SUMS").is_file(), done.stdout


@needs_a_posix_shell
def test_it_attaches_every_asset_the_installer_downloads(tmp_path):
    """The two sides of the contract, executed rather than compared as strings. `install.sh` asks
    for these names; if the assembly does not produce them, the release 404s — which is v0.1.1."""
    dist = tmp_path / "dist"
    _assemble(dist)

    produced = {p.name for p in dist.iterdir()}
    missing = sorted(_assets_the_installer_downloads() - produced)

    assert not missing, (
        f"install.sh downloads {missing}, which the release does not assemble. Against a real "
        f"release that is a 404 and a dead install.")


@needs_a_posix_shell
def test_every_asset_it_attaches_is_covered_by_the_checksums(tmp_path):
    """`sha256sum -c --ignore-missing` succeeds when it matches nothing, so coverage has to be
    asserted separately from verification. In v0.1.1 the template was fetched over the network and
    never checked, because `sha256sum ./*` does not match dotfiles."""
    dist = tmp_path / "dist"
    _assemble(dist)

    covered = {line.split()[-1].lstrip("*")
               for line in (dist / "SHA256SUMS").read_text().splitlines() if line.strip()}
    downloaded = _assets_the_installer_downloads() - {"SHA256SUMS"}
    uncovered = sorted(downloaded - covered)

    assert not uncovered, (
        f"{uncovered} are attached and not in SHA256SUMS, so `--ignore-missing` skips them and "
        f"they are never verified. Covered: {sorted(covered)}")


@needs_a_posix_shell
def test_the_checksum_names_are_bare_so_verification_works_where_a_user_runs_it(tmp_path):
    """`sha256sum -c` resolves names relative to the working directory. A `./` prefix would make
    verification fail in the one directory a person actually runs it from."""
    dist = tmp_path / "dist"
    _assemble(dist)

    for line in (dist / "SHA256SUMS").read_text().splitlines():
        if line.strip():
            assert not line.split()[-1].startswith("./"), line


@needs_a_posix_shell
def test_no_asset_it_attaches_begins_with_a_dot(tmp_path):
    """The v0.1.1 property, checked on what was produced rather than on the script's text. GitHub
    renames such an asset to `default.…` on upload, and the checksum glob skips it — both
    silently."""
    dist = tmp_path / "dist"
    _assemble(dist)

    dotted = sorted(p.name for p in dist.iterdir() if p.name.startswith("."))
    assert not dotted, (
        f"{dotted} would be attached with a leading dot: GitHub renames those and the checksums "
        f"miss them")


@needs_a_posix_shell
def test_a_dotfile_in_the_destination_is_refused_by_name(tmp_path):
    """THE OTHER DIRECTION, and the one the v0.1.2 bug made unreachable: the guard has to fire when
    there IS something to catch. A guard that only ever passes is indistinguishable from no guard,
    and a guard that only ever fails — which is what shipped — is worse than both."""
    dist = tmp_path / "dist"
    assert _assemble(dist).returncode == 0
    (dist / ".env.compose.example").write_text("planted")

    done = _assemble(dist)

    assert done.returncode == 1, (
        f"a dotfile in the destination was accepted; GitHub would rename it silently:\n"
        f"{done.stdout}\n{done.stderr}")
    assert ".env.compose.example" in done.stderr, (
        f"the refusal does not name the offending file: {done.stderr}")
    assert "leading dot" in done.stderr, (
        f"the refusal does not say what is wrong or what to do: {done.stderr}")


@needs_a_posix_shell
def test_the_refusal_never_reports_an_unexpanded_pattern(tmp_path):
    """TODAY'S DEFECT, PINNED. The v0.1.2 release died reporting `dist/.*` — its own glob, left
    literal because nothing matched. Bash 5.2's `globskipdots` (on by default, and `ubuntu-latest`
    has it) stops `.*` matching `.` and `..`, so the entries the loop's `case` was written to skip
    never appear and the pattern matches nothing at all. Verified locally: with `globskipdots` on
    the loop reports `dist/.*`; with it off, or under dash, it is silent.

    So whatever the assembly says, it may never name a path containing a glob character — that is
    a message about the script rather than about the release."""
    dist = tmp_path / "dist"
    _assemble(dist)
    (dist / ".oops").write_text("x")

    done = _assemble(dist)
    output = done.stdout + done.stderr

    assert "*" not in output, (
        f"the assembly reported an unexpanded glob rather than a real path — this is the v0.1.2 "
        f"failure:\n{output}")
    assert ".oops" in done.stderr, done.stderr


@needs_a_posix_shell
def test_a_destination_whose_own_name_starts_with_a_dot_still_assembles(tmp_path):
    """`find` reports its starting point at depth 0, so a destination like `.dist` matched the
    pattern and the script refused to assemble anything. Found by running it (2026-09-01) — which
    is the whole argument for the assembly being a script the suite can execute."""
    done = _assemble(tmp_path / ".dist")

    assert done.returncode == 0, (
        f"the assembly refused a destination whose own name begins with a dot:\n{done.stderr}")
