"""No `gh` call acts on a repository it was not given, and the suite has no `gh` login to act with.

MEASURED. From 2026-09-29 to 2026-10-01, 31 comments reading "Preview up: …/p/acme/preview/12"
were posted on `Open-Factory-Digital/openfactory-core#12`, an issue merged in August, under the
operator's own `gh` login. The suite's two real-daemon preview tests register
`Project(name="acme")`; its GitHub row carries `repo=""`; the step that brings a preview up
comments on the card through it; and `gh issue comment 12 --repo ""` does not fail — `gh` reads an
empty `--repo` as none, and resolves the repository from the directory it runs in, which was the
checkout the suite ran from. It stopped on 2026-10-01 only because #454 re-homed the suite, which
hid `~/.config/gh` by accident; a `GH_CONFIG_DIR` or `XDG_CONFIG_HOME` in the operator's shell
would have brought the login back.

THREE LAYERS, EACH PROVEN HERE:

  the rows     both GitHub rows refuse a `gh` call whose `--repo` is empty, before `gh` runs
  the suite    `gh` is pointed at an empty configuration of the suite's own, whatever was set
  the tests    the live preview tests tell a tracker of their own, and assert what it was told
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from openfactory.adapters.github_cli import nothing_named

ROOT = Path(__file__).resolve().parents[1]


# ═══ the rule ═══════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("args, flag", [
    (["issue", "comment", "12", "--repo", "", "--body", "x"], "--repo"),
    (["issue", "view", "12", "--repo", "  "], "--repo"),
    (["pr", "view", "12", "-R", ""], "-R"),
    (["issue", "edit", "12", "--repo="], "--repo"),
    (["issue", "comment", "12", "--repo"], "--repo"),
    # THE SAME TRAP ON EVERY FLAG `gh` FILLS IN BY GUESSING (review of #489)
    (["project", "view", "3", "--owner", "", "--format", "json"], "--owner"),
    (["pr", "create", "--repo", "acme/shop", "--head", "", "--base", "main"], "--head"),
    (["pr", "create", "--repo", "acme/shop", "--head", "openfactory/12", "--base", ""], "--base"),
    (["pr", "list", "--repo", "acme/shop", "-H", " "], "-H"),
    (["pr", "create", "--repo", "acme/shop", "--head", "x", "-B", ""], "-B"),
])
def test_an_empty_flag_gh_would_guess_is_refused_by_name(args, flag):
    said = nothing_named(args)
    assert f"`{flag}` with nothing in it" in said, said


@pytest.mark.parametrize("args", [
    ["issue", "comment", "12", "--repo", "acme/shop", "--body", "x"],
    ["issue", "edit", "12", "--repo=acme/shop"],
    ["api", "graphql", "-f", "query=…"],
    ["pr", "create", "--repo", "acme/shop", "--head", "openfactory/12", "--base", "main"],
    ["project", "view", "3", "--owner", "acme", "--format", "json"],
])
def test_named_values_or_none_asked_for_pass(args):
    assert nothing_named(args) == ""


# ═══ the rows: refused before `gh` runs ═════════════════════════════════════════════════════════

@pytest.fixture
def no_gh(monkeypatch):
    ran: list[list[str]] = []

    def run(argv, *a, **kw):
        ran.append(list(argv))
        raise AssertionError(f"gh ran: {argv}")

    monkeypatch.setattr(subprocess, "run", run)
    return ran


def test_the_tracker_with_no_repository_writes_nothing_and_says_why(no_gh):
    from openfactory.adapters.tracker.github import GitHubIssuesTracker

    with pytest.raises(RuntimeError, match="with nothing in it"):
        GitHubIssuesTracker(repo="").comment("12", "Preview up: …")
    assert no_gh == []


def test_a_bare_project_builds_that_tracker_and_it_cannot_reach_the_working_directorys_repo(
        no_gh):
    """The shape that leaked: a registry entry with no repository on a GitHub row."""
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.project import Project

    tracker = build_tracker(Project(name="acme", repo_path="/src/acme"), token=None)
    with pytest.raises(RuntimeError, match="with nothing in it"):
        tracker.comment("12", "Preview up: /p/acme/preview/12")
    assert no_gh == []


def test_the_forge_with_no_repository_reads_nothing_from_the_working_directory(no_gh):
    from openfactory.adapters.forge.github import GitHubForge

    assert GitHubForge("").pr_body(pr="12") is None
    assert no_gh == []


def test_the_board_with_no_owner_reads_nothing_of_the_logged_in_account(no_gh):
    """An empty `--owner` is the logged-in account's projects, not the client's."""
    from openfactory.adapters.tracker.github_project import _run_gh

    got = _run_gh(["project", "view", "3", "--owner", "", "--format", "json"], None)
    assert got.returncode != 0 and "`--owner` with nothing in it" in got.stderr
    assert no_gh == []


def test_a_pull_request_is_never_opened_from_a_guessed_branch(no_gh):
    """An empty `--head` is the branch checked out where the process runs."""
    from openfactory.adapters.forge.github import GitHubForge

    with pytest.raises(RuntimeError):
        GitHubForge("acme/shop").open_pr(head="", base="main", title="t", body="b")
    assert no_gh == []


# ═══ the suite: no `gh` login inside it ═════════════════════════════════════════════════════════

def test_gh_reads_an_empty_configuration_of_the_suites_own():
    import conftest

    config = Path(os.environ["GH_CONFIG_DIR"]).resolve()
    real = conftest.operators_real_home().resolve()
    assert config.is_dir() and not any(config.iterdir()), "gh has a configuration in the suite"
    assert real not in (config, *config.parents), "gh reads the operator's own configuration"
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"):
        assert name not in os.environ, f"{name} reached the suite"


# ═══ the tests that bring a preview up tell a tracker of their own ══════════════════════════════

@pytest.mark.parametrize("name", ["test_a_preview_starts_on_a_real_daemon.py",
                                  "test_a_preview_opens_on_one_machine.py"])
def test_a_live_preview_test_tells_its_own_card(name):
    src = (ROOT / "tests" / name).read_text()
    assert 'monkeypatch.setattr(activities, "_tracker_for", lambda project: card)' in src
    assert "((ref, said),) = card.said" in src, "the card's telling is installed and not asserted"
