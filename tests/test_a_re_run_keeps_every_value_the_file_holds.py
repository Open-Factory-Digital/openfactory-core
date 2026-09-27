"""A re-run of `openfactory init --force` keeps every value the file it replaces already holds.

THE DEFECT, MEASURED BEFORE IT WAS FIXED. The README and the installer both say the upgrade is to
re-run the installer with `--force`, and that "your answers survive it". On 2026-09-27, `install.sh`
from `main` installed v0.2.1 into an isolated directory. Three credentials were then filled in, a
published port moved and a row added, and the installer was re-run with `--version v0.3.0 --force`.
Afterwards `OPENFACTORY_BOT_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN` and `OPENFACTORY_PANEL_TOKEN` were
empty, `PANEL_PORT` was back at 8787 and the added row was gone. No copy was left, and the stack
restarts without them. `init --force` wrote the answers' file over the one that held them.

These tests hold what a regression would cost:

  1. a row the person filled keeps its value, and a row only the old file had is kept too;
  2. a row the person left empty takes what this run generates or discovers;
  3. the pinned version is never carried, because the installer pins the release it installs;
  4. what was kept is named, and a value never reaches the terminal;
  5. a file that exists and cannot be read is refused, never written over;
  6. a first run, with no file to keep from, is unchanged;
  7. the work directory the file ends with is the one that is made (review of #366);
  8. the to-do list drops a sentence only when every row it names was kept (review of #366).
"""

from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from openfactory.cli import app
from openfactory.onboarding.deployment import Answers, carry_over, render, still_to_do

#: The installer's own answers (`install.sh` states the runtime; the rest is what an unattended
#: install passes after `--`).
_FLAGS = ["--runtime", "compose",
          "--forge", "github", "--tracker", "github", "--harness", "claude_code",
          "--github-auth", "token", "--claude-auth", "subscription", "--channel", "panel"]

_BOT = "ghp_UPGRADEMARKERbot000000000000000000000"
_CLAUDE = "sk-ant-oat01-UPGRADEMARKERclaude"
_PANEL = "UPGRADEMARKERpanel"


@pytest.fixture(autouse=True)
def _no_login_on_this_machine(monkeypatch, tmp_path):
    """No forge login of whoever runs the suite is read into a test file, and the job workspace is
    this test's own."""
    monkeypatch.setattr("openfactory.credentials.discover_forge_token", lambda kind: None)
    monkeypatch.setenv("OPENFACTORY_WORK_DIR", str(tmp_path / "work"))


def _rows(text: str) -> dict[str, str]:
    return dict(re.findall(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", text, re.MULTILINE))


def _the_file_a_person_has(dest) -> None:
    """What an install's `.env.compose` looks like once somebody has used it: the file the answers
    produced, with the credentials filled in, a port moved, a row added and the installer's pin."""
    text = render(Answers(runtime="compose", forge="github", tracker="github",
                          harness="claude_code", github_auth="token",
                          claude_auth="subscription", channel="panel",
                          panel_exposed=True)).text
    text = (text.replace("OPENFACTORY_BOT_TOKEN=\n", f"OPENFACTORY_BOT_TOKEN={_BOT}\n")
                .replace("CLAUDE_CODE_OAUTH_TOKEN=\n", f"CLAUDE_CODE_OAUTH_TOKEN={_CLAUDE}\n")
                .replace("PANEL_PORT=8787\n", "PANEL_PORT=8899\n"))
    text = re.sub(r"^OPENFACTORY_PANEL_TOKEN=.*$", f"OPENFACTORY_PANEL_TOKEN={_PANEL}", text,
                  flags=re.MULTILINE)
    text += "OPENFACTORY_MAX_CONCURRENT_JOBS=2\nOPENFACTORY_VERSION=v0.3.0\n"
    dest.write_text(text)
    dest.chmod(0o600)


# ── 1-4. the upgrade, through the command the installer runs ────────────────────────────────────

def test_an_upgrade_keeps_every_value_the_file_holds(tmp_path):
    dest = tmp_path / ".env.compose"
    _the_file_a_person_has(dest)

    result = CliRunner().invoke(app, ["init", *_FLAGS, "--panel-exposed", "--out", str(dest),
                                      "--force"])

    assert result.exit_code == 0, result.output
    rows = _rows(dest.read_text())
    assert rows["OPENFACTORY_BOT_TOKEN"] == _BOT, "the forge credential was emptied"
    assert rows["CLAUDE_CODE_OAUTH_TOKEN"] == _CLAUDE, "the harness credential was emptied"
    assert rows["OPENFACTORY_PANEL_TOKEN"] == _PANEL, (
        "the panel's token was regenerated, locking out everyone who holds the old one")
    assert rows["PANEL_PORT"] == "8899", "a port the person moved went back to the default"
    assert rows["OPENFACTORY_MAX_CONCURRENT_JOBS"] == "2", "a row the person added was dropped"
    assert "OPENFACTORY_VERSION" not in rows, (
        "the old pin was carried over, and the installer only writes one when there is none")
    assert (dest.stat().st_mode & 0o777) == 0o600


def test_what_was_kept_is_named_and_never_shown(tmp_path):
    dest = tmp_path / ".env.compose"
    _the_file_a_person_has(dest)

    out = CliRunner().invoke(app, ["init", *_FLAGS, "--panel-exposed", "--out", str(dest),
                                   "--force"]).output

    kept = next((line for line in out.splitlines() if "kept from the file it replaced" in line),
                "")
    for name in ("OPENFACTORY_BOT_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "OPENFACTORY_PANEL_TOKEN",
                 "PANEL_PORT", "OPENFACTORY_MAX_CONCURRENT_JOBS"):
        assert name in kept, f"{name} was kept and the output does not say so: {out}"
    for value in (_BOT, _CLAUDE, _PANEL):
        assert value not in out, "a kept secret was echoed to the terminal"
    assert "fill OPENFACTORY_BOT_TOKEN" not in out, (
        "the to-do list still asks for a credential the file already holds")


def test_a_row_left_empty_takes_what_this_run_generates(tmp_path):
    """Rotation, and a first answer: the person empties a line, or never filled it, and the run
    fills it now, which is also how a token is rotated."""
    dest = tmp_path / ".env.compose"
    dest.write_text("OPENFACTORY_PANEL_TOKEN=\nOPENFACTORY_BOT_TOKEN=mine\n")
    dest.chmod(0o600)

    result = CliRunner().invoke(app, ["init", *_FLAGS, "--panel-exposed", "--out", str(dest),
                                      "--force"])

    assert result.exit_code == 0, result.output
    rows = _rows(dest.read_text())
    assert len(rows["OPENFACTORY_PANEL_TOKEN"]) >= 16, "an emptied token was not generated again"
    assert rows["OPENFACTORY_BOT_TOKEN"] == "mine"


# ── 5. a file that cannot be read ───────────────────────────────────────────────────────────────

def test_a_file_that_cannot_be_read_is_not_written_over(tmp_path):
    dest = tmp_path / ".env.compose"
    dest.write_text(f"OPENFACTORY_BOT_TOKEN={_BOT}\n")
    dest.chmod(0o000)
    try:
        if dest.stat().st_mode & 0o400 or _readable(dest):
            pytest.skip("this user reads a 0000 file (root), so the refusal cannot be provoked")
        result = CliRunner().invoke(app, ["init", *_FLAGS, "--panel-local", "--out", str(dest),
                                          "--force"])
    finally:
        dest.chmod(0o600)

    assert result.exit_code == 2, result.output
    assert "could not read" in result.output and "Nothing was changed" in result.output
    assert dest.read_text() == f"OPENFACTORY_BOT_TOKEN={_BOT}\n"


def test_a_file_that_is_not_text_is_not_written_over(tmp_path):
    """The same refusal through a door no user can read past, so it holds when the suite runs as
    root, where the permission test above stands down (review of #366)."""
    dest = tmp_path / ".env.compose"
    dest.write_bytes(b"OPENFACTORY_BOT_TOKEN=" + _BOT.encode() + b"\nBINARY=\xff\xfe\n")

    result = CliRunner().invoke(app, ["init", *_FLAGS, "--panel-local", "--out", str(dest),
                                      "--force"])

    assert result.exit_code == 2, result.output
    assert "could not read" in result.output and "Nothing was changed" in result.output
    assert dest.read_bytes().endswith(b"BINARY=\xff\xfe\n")


def _readable(path) -> bool:
    try:
        path.read_bytes()
    except OSError:
        return False
    return True


# ── 6. a first run ──────────────────────────────────────────────────────────────────────────────

def test_a_first_run_has_nothing_to_keep(tmp_path):
    dest = tmp_path / ".env.compose"

    result = CliRunner().invoke(app, ["init", *_FLAGS, "--panel-local", "--out", str(dest)])

    assert result.exit_code == 0, result.output
    assert "Kept from the file this one replaced" not in dest.read_text()
    assert "kept from the file it replaced" not in result.output


# ── 7. the work directory the file ends with is the one that is made ────────────────────────────

def test_a_kept_work_directory_is_made_like_any_other(tmp_path, monkeypatch):
    """A previous file's work directory is kept, so it is made, or the file names a bind source
    nothing created and Docker makes it as root (review of #366)."""
    monkeypatch.delenv("OPENFACTORY_WORK_DIR")
    theirs = tmp_path / "a-work-directory-that-is-gone"
    dest = tmp_path / ".env.compose"
    dest.write_text(f"OPENFACTORY_WORK_DIR={theirs}\n")
    dest.chmod(0o600)

    result = CliRunner().invoke(app, ["init", *_FLAGS, "--panel-local", "--out", str(dest),
                                      "--force"])

    assert result.exit_code == 0, result.output
    assert _rows(dest.read_text())["OPENFACTORY_WORK_DIR"] == str(theirs)
    assert theirs.is_dir(), "the file names a work directory nothing made"


def test_a_kept_work_directory_compose_cannot_bind_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENFACTORY_WORK_DIR")
    dest = tmp_path / ".env.compose"
    dest.write_text("OPENFACTORY_WORK_DIR=~/work\n")
    dest.chmod(0o600)

    result = CliRunner().invoke(app, ["init", *_FLAGS, "--panel-local", "--out", str(dest),
                                      "--force"])

    assert result.exit_code == 2, result.output
    assert "OPENFACTORY_WORK_DIR" in result.output and "Nothing was changed" in result.output
    assert dest.read_text() == "OPENFACTORY_WORK_DIR=~/work\n"


def test_a_declared_work_directory_is_the_one_written(tmp_path):
    """The installer declares the directory it resolved and mounts; the file must name that one,
    not an older one, or the directory made and the directory written part ways."""
    dest = tmp_path / ".env.compose"
    dest.write_text(f"OPENFACTORY_WORK_DIR={tmp_path / 'an-older-one'}\n")
    dest.chmod(0o600)

    result = CliRunner().invoke(app, ["init", *_FLAGS, "--panel-local", "--out", str(dest),
                                      "--force"])

    assert result.exit_code == 0, result.output
    assert _rows(dest.read_text())["OPENFACTORY_WORK_DIR"] == str(tmp_path / "work")
    kept = next((line for line in result.output.splitlines() if "kept from" in line), "")
    assert "OPENFACTORY_WORK_DIR" not in kept


# ── 8. the to-do list ───────────────────────────────────────────────────────────────────────────

def test_a_sentence_is_done_only_when_every_row_it_names_was_kept():
    remaining = [
        "fill SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_SIGNING_SECRET — the channel add-on reads them",
        "fill OPENFACTORY_BOT_TOKEN — a classic token, and NEVER `workflow`",
        "create the GitHub App and INSTALL it (two separate pages)",
        "OPENFACTORY_BOT_TOKEN was taken from your `gh` login, so the factory commits as you",
        "fill CLAUDE_CODE_OAUTH_TOKEN — run `claude setup-token`",
    ]

    left = still_to_do(remaining, ["SLACK_BOT_TOKEN", "NEVER", "INSTALL",
                                   "CLAUDE_CODE_OAUTH_TOKEN"])

    assert left == remaining[:4], left
    assert still_to_do(remaining, ["OPENFACTORY_BOT_TOKEN"]) == [
        remaining[0], remaining[2], remaining[4]]


def test_a_kept_row_named_like_a_word_leaves_the_forge_token_on_the_list(tmp_path):
    """Measured on review: with `NEVER=…` in the previous file the list showed only the Claude
    token, while `OPENFACTORY_BOT_TOKEN=` was still empty in the file."""
    dest = tmp_path / ".env.compose"
    dest.write_text("NEVER=some-value-of-mine\n")
    dest.chmod(0o600)

    out = CliRunner().invoke(app, ["init", *_FLAGS, "--panel-local", "--out", str(dest),
                                   "--force"]).output

    assert "fill OPENFACTORY_BOT_TOKEN" in out, out


# ── the rule, on its own ────────────────────────────────────────────────────────────────────────

def test_the_rule_row_by_row():
    previous = ("# a comment of the person's\n"
                "A=old\n"
                "B=\n"
                "C=first\n"
                "C=second\n"
                "EXTRA=mine\n"
                "EMPTY_EXTRA=\n"
                "OPENFACTORY_VERSION=v0.1.0\n")
    rendered = "# this run's comment\nA=\nB=generated\nC=default\nD=new\n"

    text, kept = carry_over(previous, rendered)

    rows = _rows(text)
    assert rows == {"A": "old", "B": "generated", "C": "second", "D": "new", "EXTRA": "mine"}
    assert text.startswith("# this run's comment\n"), "the comments are this run's"
    assert "# a comment of the person's" not in text
    assert kept == ["A", "C", "EXTRA"]


def test_a_value_is_carried_byte_for_byte():
    """Trailing spaces are part of what compose read; a line's end and indentation are not, and
    `export NAME=` is compose's own spelling of `NAME=` (review of #366)."""
    previous = ("OPENFACTORY_BOT_TOKEN=ghp_mine   \r\n"
                "  PANEL_PORT=8899\r\n"
                "export JIRA_API_TOKEN=a=b+c/d#e\n")
    rendered = "OPENFACTORY_BOT_TOKEN=\nPANEL_PORT=8787\n"

    text, kept = carry_over(previous, rendered)

    assert "OPENFACTORY_BOT_TOKEN=ghp_mine   \n" in text
    assert "PANEL_PORT=8899\n" in text
    assert "JIRA_API_TOKEN=a=b+c/d#e\n" in text
    assert "\r" not in text
    assert kept == ["OPENFACTORY_BOT_TOKEN", "PANEL_PORT", "JIRA_API_TOKEN"]
