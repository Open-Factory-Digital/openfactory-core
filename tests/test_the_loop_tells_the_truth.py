"""ADR-0049 slice 3c — the merge path stops asserting what nobody measured.

THREE SENTENCES ON THIS PATH WERE GITHUB'S, and a deployment whose forge is a directory on this
machine was told about branch protection it does not have. One was fixed in 3b (the runner's auto
hold). The two here are the workflow's:

  · the refused human gate, which named a cause — "most likely branch protection this App cannot
    satisfy" — that nothing had read;
  · the `dirty` decision, which called every unmergeable pull request "a textual merge conflict".

AND THE PAGE THE PERSON READS THEM ON. `/p/{project}/pr/{n}` renders the pull request through the
forge port, so a GitHub pull request renders as readily as one that lives in a file — with the
forge's own refusal, where it left one, above everything else.
"""

from __future__ import annotations

import subprocess

import pytest


def _git(where, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True,
                          check=False)


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """A registered local project with a job branch and one commit on it."""
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    repo = tmp_path / "myapp"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "person@example.invalid")
    _git(repo, "config", "user.name", "A Person")
    (repo / "app.py").write_text("print('one')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "first")
    _git(repo, "checkout", "-q", "-b", "openfactory/1")
    (repo / "app.py").write_text("print('two')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "the change")
    _git(repo, "checkout", "-q", "main")

    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    registry = ProjectRegistry()
    registry.add(Project(name="myapp", repo_path=str(repo),
                         tracker=ProviderRef(kind="local", repo="myapp"),
                         forge=ProviderRef(kind="local", repo="myapp")))
    return registry.get("myapp"), repo


@pytest.fixture
def opened(deployment):
    from openfactory.adapters.forge.registry import build_forge

    project, repo = deployment
    forge = build_forge(project)
    url = forge.open_pr(head="openfactory/1", base="main", title="Make it two", body="why")
    return forge, url, repo


# ── the activity that says why ──────────────────────────────────────────────────────────────────

async def test_the_merge_activity_answers_the_forges_own_sentence(opened, monkeypatch):
    """`""` is *it landed*; anything else is what the forge said, verbatim."""
    from openfactory.runtime.temporal.activities import merge_pr_saying_why
    from openfactory.runtime.temporal.io import MergeCheckInput

    forge, url, repo = opened
    (repo / "app.py").write_text("print('mine')\n")      # an overlapping edit

    said = await merge_pr_saying_why(MergeCheckInput(project="myapp", pr_url=url))
    assert "app.py" in said, "the file name is the whole of what the person can act on"
    assert forge.pr_status(pr=url) == "open", "a refused merge is still open"

    _git(repo, "checkout", "--", "app.py")
    assert await merge_pr_saying_why(MergeCheckInput(project="myapp", pr_url=url)) == ""
    assert forge.pr_status(pr=url) == "merged"


async def test_the_old_activity_is_untouched(opened):
    """It stays for the jobs that parked at this gate before the patch: activity results are
    recorded in history, so a `false` there cannot be read back as a string."""
    from openfactory.runtime.temporal.activities import merge_pr_now
    from openfactory.runtime.temporal.io import MergeCheckInput

    _forge, url, _repo = opened
    assert await merge_pr_now(MergeCheckInput(project="myapp", pr_url=url)) is True


def test_both_activities_are_registered_on_the_worker():
    """An unregistered activity fails the loop and parks the job — which is how a workflow test
    once reported 'the gate never opened'."""
    from openfactory.runtime.temporal import worker

    src = (worker.__file__ and open(worker.__file__).read()) or ""
    assert "merge_pr_now" in src and "merge_pr_saying_why" in src


# ── the two sentences ───────────────────────────────────────────────────────────────────────────

def test_the_refused_gate_prints_what_the_forge_said_and_keeps_todays_wording_otherwise():
    """A hosted row leaves no sentence, so a GitHub deployment keeps its branch-protection hint
    word for word. A row that left one gets that instead — and the guess is not printed beside a
    fact that contradicts it.

    THE PROSE IS STRIPPED FIRST, and a mutation is what taught why: the paragraph above this code
    QUOTES the wording it is about, so an assertion over the raw source was satisfied by the
    comment explaining the change while the code itself had lost it. `code_only` is the house's
    own answer to exactly that, and it exists because hand-written versions kept failing this
    way."""
    import inspect
    import textwrap

    from conftest import code_only
    from openfactory.runtime.temporal.workflow import JobWorkflow

    # DEDENTED FIRST: `code_only` parses, and a method's source is indented, so it is not a module.
    src = code_only(textwrap.dedent(inspect.getsource(JobWorkflow._answer_merge_gate)))
    assert "the forge refused it:" in src, "the forge's own sentence is never printed"
    assert "most likely branch " in src, "today's wording is gone rather than kept as the fallback"
    assert "if refusal else" in src, "the two are not one-or-the-other"


def test_the_new_command_is_behind_a_replay_gate():
    """A new activity on a path in-flight jobs already replay must be patched, or a replaying
    workflow emits a command its history does not contain — TMPRL1100, which this file has hit."""
    import inspect

    from openfactory.runtime.temporal.workflow import JobWorkflow

    src = inspect.getsource(JobWorkflow._answer_merge_gate)
    assert 'workflow.patched("merge-refusal-says-what-the-forge-said")' in src
    assert src.index("workflow.patched") < src.index("merge_pr_saying_why"), (
        "the activity is reached before the gate that guards it")


def test_the_dirty_decision_stops_naming_a_cause_nobody_read():
    """`dirty` is the forge's word for *not mergeable right now*, and this called all of them a
    textual conflict. On a forge that is a directory it is at least as often an edit in the
    person's own tree, a merge left half done, or a branch that is gone."""
    import inspect

    from openfactory.runtime.temporal.workflow import JobWorkflow

    src = inspect.getsource(JobWorkflow._decide_merge)
    assert "A textual merge conflict" not in src, "the cause is still asserted"
    assert "The forge reports it will not merge" in src
    assert 'DecisionOption(key="resume"' in src and 'DecisionOption(key="skip"' in src, (
        "the two ways out are still offered")


# ── the pull request's own page ─────────────────────────────────────────────────────────────────

def test_the_page_reads_the_pull_request_through_the_port(opened):
    from openfactory.api.app import board_view

    _forge, url, _repo = opened
    got = board_view("myapp", pr=url)["pr"]
    assert got["readable"] and got["state"] == "open"
    assert got["body"] == "why"
    assert "print('two')" in (got["diff"] or "")


def test_the_forges_own_refusal_is_what_the_page_shows(opened):
    from openfactory.api.app import board_view

    forge, url, repo = opened
    (repo / "app.py").write_text("print('mine')\n")
    forge.mergeable_state(pr=url)

    got = board_view("myapp", pr=url)["pr"]
    assert "app.py" in got["refused"], "the page would print a paraphrase without the file name"


def test_the_review_events_reach_the_page(opened):
    from openfactory.api.app import board_view

    forge, url, _repo = opened
    forge.review_pr(pr=url, event="approve", body="looks right")
    events = board_view("myapp", pr=url)["pr"]["events"]
    assert [(e["event"], e["body"]) for e in events] == [("approve", "looks right")]


def test_a_diff_that_could_not_be_READ_is_not_a_pull_request_that_changes_nothing(opened,
                                                                                  monkeypatch):
    """The port's own rule, carried to the browser. `None` is *could not look* — no credential,
    refused, unreachable — and `""` is *looked, and there are no changes*. Collapsing them makes a
    failed read into a claim about somebody's pull request."""
    from openfactory.adapters.forge.local import LocalForge
    from openfactory.api.app import board_view

    _forge, url, _repo = opened
    monkeypatch.setattr(LocalForge, "pr_diff", lambda self, **kw: None)
    assert board_view("myapp", pr=url)["pr"]["diff"] is None

    monkeypatch.setattr(LocalForge, "pr_diff", lambda self, **kw: "")
    assert board_view("myapp", pr=url)["pr"]["diff"] == "", "and an empty diff stays empty"


def test_a_pull_request_that_cannot_be_read_is_an_answer_and_not_a_500(deployment):
    from openfactory.api.app import board_view

    got = board_view("myapp", pr="http://localhost:8787/p/myapp/pr/404")["pr"]
    assert got["readable"] is False, "a stale bookmark must not read as the panel being broken"


def test_the_page_is_not_read_for_a_pull_request_nobody_asked_for(deployment):
    from openfactory.api.app import board_view

    assert board_view("myapp")["pr"] is None


def test_a_hosted_row_is_asked_the_same_way_and_answers_what_it_has():
    """`pr_events` and `pr_refusal` are asked through `getattr`, so a row that keeps its review
    timeline behind its own API answers neither and the page renders what it has. A page that
    demanded them of the port would be a page only one row could serve."""
    from openfactory.adapters.forge.github import GitHubForge

    for name in ("pr_events", "pr_refusal"):
        assert not hasattr(GitHubForge, name), (
            f"the GitHub row grew {name}; then the port should carry it rather than `getattr`")


def test_the_deeper_address_is_served(deployment):
    from fastapi.testclient import TestClient

    from openfactory.api.app import app

    got = TestClient(app).get("/p/myapp/pr/1")
    assert got.status_code == 200 and "<html" in got.text.lower()


def test_the_page_tells_a_diff_it_could_not_read_from_one_that_is_empty():
    """`None` and `""` are opposite facts, and the page renders them as different things."""
    PANEL = __import__("pathlib").Path(__file__).resolve().parent.parent / "openfactory" \
        / "api" / "panel.html"
    src = PANEL.read_text(encoding="utf-8")
    page = src.split("function paintPR()")[1].split("function _bevents")[0]
    assert "p.diff === null" in page and 'p.diff === ""' in page
