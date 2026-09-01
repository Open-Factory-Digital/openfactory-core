"""`openfactory init` writes a job workspace the invoking user owns — and creates it.

THE DEFECT THIS CLOSES. `docker-compose.yml` defaulted `OPENFACTORY_WORK_DIR` to
`/var/lib/openfactory-work`, a path no ordinary user may create, so the first-run path opened with
a root command:

    sudo mkdir -p /var/lib/openfactory-work && sudo chown $(whoami) /var/lib/openfactory-work

Three things were wrong with it and only the first is obvious. It is `sudo` on the very first
command of a product that runs on your own machines. It is Linux-only, and the README said so
while `docs/ONBOARDING.md` §0 buried it in a block after the `up` line, so the macOS reader met a
step that did not apply and the Linux reader met it after the failure it prevents. And **skipping
it did not fail** — Docker answers a missing bind source by creating the directory itself, owned by
root, so the stack came up healthy and the ownership surfaced later, inside a box that could not
write. Under rootless Docker the directory cannot be auto-created at all.

WHY THE ANSWER IS A GENERATED ROW AND NOT A SMALLER `sudo`. The platform already generates this
file: `openfactory init` exists because the deployment's environment was the last thing still
hand-written. A default that needs root is a decision the file can simply make differently —
`${XDG_DATA_HOME:-$HOME/.local/share}/openfactory/work` is state this user owns, by the same
convention every other tool on the machine follows. It also fixes a macOS failure that had nothing
to do with `sudo`: `$HOME` is inside Docker Desktop's default file sharing and `/var/lib` is not.

WHAT THESE TESTS REFUSE TO LET BACK IN. A path with a `~` in it (compose does not expand a tilde in
a bind source — the host gets a literal `./~` directory and every box mounts it empty), a relative
path (compose resolves a bind source against the directory `up` ran in), a row the file names and
the command does not create, and a `sudo` anywhere on the first-run path.
"""

from __future__ import annotations

import pathlib
import re
import stat

import pytest
from typer.testing import CliRunner

from openfactory.cli import app
from openfactory.onboarding.deployment import Answers, Probes, default_work_dir, render

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _row(text: str, name: str) -> str | None:
    match = re.search(rf"^{name}=(.*)$", text, re.MULTILINE)
    return match.group(1) if match else None


# ── the row the generator writes ────────────────────────────────────────────────────────────────

def test_the_generated_file_names_a_work_directory_at_all():
    """Absence is the failure that hides: with no row the compose default applies, which is the
    `/var/lib` path this whole change exists to stop handing people."""
    text = render(Answers(), Probes(work_dir=lambda: "/home/ana/.local/share/openfactory/work")).text

    assert _row(text, "OPENFACTORY_WORK_DIR") == "/home/ana/.local/share/openfactory/work"


def test_the_work_directory_is_absolute_and_carries_no_tilde():
    """Both halves are load-bearing and neither is style. A relative source puts every job's
    workspace inside whatever checkout ran `up`; a `~` is not expanded by compose in a bind source
    at all, so the host gets a literal `./~` and the box mounts an empty directory — the "box saw
    0 entries" defect (`container.py`, 2026-08-03) reached by a new road."""
    written = _row(render(Answers()).text, "OPENFACTORY_WORK_DIR")

    assert written and written.startswith("/"), f"{written!r} is not absolute"
    assert "~" not in written, f"{written!r} carries a tilde compose will not expand"


def test_the_default_is_under_the_users_own_directory_and_not_under_var_lib():
    """The property in one sentence: this is a path the person running the command already owns."""
    chosen = default_work_dir()

    assert not chosen.startswith("/var/"), (
        f"{chosen!r} is under /var — creating it needs root, which is the line this change removes")
    assert chosen.endswith("openfactory/work"), chosen


def test_the_xdg_variable_is_honoured_when_the_machine_sets_one(monkeypatch, tmp_path):
    """`XDG_DATA_HOME` is how a machine says where user state goes. Ignoring it would put the
    factory's workspaces somewhere the operator has already told every other tool not to use."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    assert default_work_dir() == str(tmp_path / "xdg" / "openfactory" / "work")


def test_without_the_xdg_variable_it_falls_back_to_the_conventional_place(monkeypatch, tmp_path):
    """The twin. A fallback that quietly produced an empty prefix would write `/openfactory/work`
    — absolute, tilde-free, and needing root, which passes both checks above."""
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "ana"))

    assert default_work_dir() == str(tmp_path / "ana" / ".local" / "share" / "openfactory" / "work")


def test_the_generator_is_told_the_directory_rather_than_reading_the_machine():
    """This module's one promise is that it is PURE — answers in, file text out — so every branch
    is reachable in a test with no TTY, no network and no `gh`. A `$HOME` read at render time would
    make the generated file depend on whose shell ran it, and this test on whose laptop ran it."""
    somewhere = "/srv/factory/workspaces"

    text = render(Answers(), Probes(work_dir=lambda: somewhere)).text

    assert _row(text, "OPENFACTORY_WORK_DIR") == somewhere


def test_the_directory_is_named_as_something_filled_without_asking():
    """`obtained` is the list the CLI prints as "filled without asking". A value the factory chose
    on the operator's behalf and never mentioned is a directory appearing on their disk with no
    trail — and this one is not a secret, so the NAME can be printed at no cost."""
    rendered = render(Answers())

    assert "OPENFACTORY_WORK_DIR" in rendered.obtained


# ── the command that has to make it real ────────────────────────────────────────────────────────

def test_init_creates_the_directory_it_names(tmp_path, monkeypatch):
    """THE half that turns a row into the removal of a `sudo` line. Docker does not fail on a
    missing bind source — it creates the directory as ROOT and the stack starts looking healthy.
    So a file that merely NAMES a user-owned path, without anybody making it, leaves the original
    defect in place wearing a better address."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    dest = tmp_path / ".env.compose"

    result = CliRunner().invoke(app, [
        "init", "--out", str(dest), "--forge", "github", "--tracker", "github",
        "--github-auth", "token", "--harness", "claude_code", "--claude-auth", "subscription",
        "--channel", "panel", "--panel-local"])

    assert result.exit_code == 0, result.output
    made = tmp_path / "xdg" / "openfactory" / "work"
    assert made.is_dir(), (
        f"init named a workspace directory and did not create it — Docker will, owned by root, "
        f"and the operator meets that at a git clone inside a box that cannot write. {result.output}")
    assert _row(dest.read_text(), "OPENFACTORY_WORK_DIR") == str(made), (
        "the directory created and the directory written into the file are not the same path")


def test_a_directory_that_cannot_be_created_refuses_by_name_with_a_remedy(tmp_path, monkeypatch):
    """The house rule, on the one failure this new step can actually hit: a read-only or
    unwritable location. One sentence, the cause and the remedy — never a traceback, and never a
    file written as though the workspace existed."""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(stat.S_IRUSR | stat.S_IXUSR)  # readable, not writable
    monkeypatch.setenv("XDG_DATA_HOME", str(blocked / "xdg"))
    dest = tmp_path / ".env.compose"

    try:
        result = CliRunner().invoke(app, [
            "init", "--out", str(dest), "--forge", "github", "--tracker", "github",
            "--github-auth", "token", "--harness", "claude_code", "--claude-auth", "subscription",
            "--channel", "panel", "--panel-local"])
    finally:
        blocked.chmod(stat.S_IRWXU)

    if result.exit_code == 0:
        pytest.skip("this process can write where it should not be able to — running as root")
    assert "Traceback" not in result.output, result.output
    assert str(blocked / "xdg" / "openfactory" / "work") in result.output, result.output
    assert "OPENFACTORY_WORK_DIR" in result.output, (
        f"the refusal does not name the row a person would edit to fix it: {result.output}")


# ── the documents that used to carry the root command ───────────────────────────────────────────

@pytest.mark.parametrize("rel", ["README.md", "docs/ONBOARDING.md"])
def test_no_document_still_tells_a_first_time_reader_to_run_sudo(rel):
    """The measurable form of "zero `sudo` invocations on the first-run path". ONBOARDING keeps a
    paragraph ABOUT the old line, for the reader upgrading an install that still needs it — so the
    test is that no document hands anybody a runnable `sudo mkdir`, not that the word is gone."""
    text = (ROOT / rel).read_text()

    offenders = [line.strip() for line in text.splitlines()
                 if re.search(r"^[>\s#]*sudo\s+(mkdir|chown)\b", line)]
    assert not offenders, (
        f"{rel} still instructs a reader to run root commands for the job workspace: {offenders}")
