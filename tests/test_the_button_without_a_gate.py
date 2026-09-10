"""The Merge on a pull request no job is waiting on (ADR-0049 D9, slice 9).

`merge` answers a GATE: the job is parked inside its merge watch, the engine is holding it, and
the answer travels as a signal. A pull request that no job is waiting on has no gate to answer —
one `openfactory run`, one `poll` on a machine with no engine up, a card whose job ended at
`pr_open` — and asking anyway comes back *"#1 is not waiting on a merge"*, which is true and
useless: the pull request is open, the person is looking at it, and the only way to land it was
git by hand. Measured while driving the one-machine proof.

WHAT IS PROVEN HERE:

  · the row lands it, through the forge port, and the base really moves;
  · a refusal comes back in GIT'S OWN WORDS, and the person's tree is untouched;
  · a hosted forge is refused BY NAME, because there the merge belongs to the job that opened the
    pull request — the CI, the branch protection and the promotion chain are all behind it;
  · the page offers the button only where the row would accept it.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

sys.path.insert(0, "tests")
import one_machine as om  # noqa: E402

PANEL = (__import__("pathlib").Path(__file__).resolve().parents[1]
         / "openfactory" / "api" / "panel.html").read_text(encoding="utf-8")


def _act(name: str, **params):
    from openfactory import actions

    # AN ADMIN, because landing somebody's change is a decision and the row is gated like every
    # other one that writes — the CLI records the shell's own user as one, and the panel asks its
    # own people map.
    who = actions.Actor(id="me", display="Me", via="panel", admin=True)
    return asyncio.run(actions.perform(name, by=who, **params))


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A registered local project with an open pull request on its own board."""
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = om.a_repository(tmp_path)
    om.a_deployment(tmp_path, monkeypatch=monkeypatch)   # never leak into the rest of the suite
    assert om.cli("project", "init", "myapp", str(repo))[0] == 0

    om.git(repo, "checkout", "-q", "-b", "openfactory/1")
    (repo / "feature.py").write_text("VALUE = 42\n")
    om.git(repo, "add", "-A")
    om.git(repo, "commit", "-qm", "the factory's change")
    om.git(repo, "checkout", "-q", "main")

    from openfactory.adapters.forge.registry import build_forge
    from openfactory.registry import ProjectRegistry

    found = ProjectRegistry().get("myapp")
    pr = build_forge(found).open_pr(head="openfactory/1", base="main", title="Add it", body="why")
    return found, repo, pr


def test_the_row_lands_it_and_the_base_moves(project):
    found, repo, pr = project

    out = _act("pr_merge", project="myapp", pr=pr)

    assert out.ok, out.message
    assert "Add it" in om.git(repo, "log", "--oneline", "-1", "main").stdout or (
        (repo / "feature.py").exists())
    assert (repo / "feature.py").read_text().strip() == "VALUE = 42"


def test_a_refusal_comes_back_in_GITS_OWN_WORDS_and_the_tree_is_untouched(project):
    found, repo, pr = project
    (repo / "feature.py").write_text("mine, uncommitted\n")

    out = _act("pr_merge", project="myapp", pr=pr)

    assert not out.ok
    assert "overwritten by merge" in out.message and "feature.py" in out.message, out.message
    assert (repo / "feature.py").read_text() == "mine, uncommitted\n"


def test_a_hosted_forge_is_refused_BY_NAME(tmp_path, monkeypatch):
    """There the merge belongs to the job that opened the pull request."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    ProjectRegistry().add(Project(name="theirs", repo_path=str(tmp_path),
                                  tracker=ProviderRef(kind="github", repo="them/theirs"),
                                  forge=ProviderRef(kind="github", repo="them/theirs")))

    out = _act("pr_merge", project="theirs", pr="https://github.com/them/theirs/pull/1")

    assert not out.ok
    assert "github" in out.message and "merge" in out.message


def test_the_page_offers_it_only_where_the_row_would_accept_it(project):
    """The two must agree: a button the row refuses is a promise the page cannot keep."""
    from openfactory.api.app import _pr_detail

    found, repo, pr = project
    detail = _pr_detail(found, pr)

    assert detail["can_merge_here"] is True
    assert "p.can_merge_here" in PANEL and "pr_merge" in PANEL

    _act("pr_merge", project="myapp", pr=pr)
    assert _pr_detail(found, pr)["can_merge_here"] is False, "offered on a merged pull request"
