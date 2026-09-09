"""ADR-0049 slice 3b — the loop and the surfaces, on a forge that is a directory.

WHAT IS PROVEN HERE:

  · **a resume keeps the work.** On a forge that hosts a copy, deleting the local branch is free.
    Here the branch IS the work, and the box deleted it and then asked a remote that is this
    repository whether it still had it;
  · **nothing watches this project's code, and every answer says so** — `[]` checks, `none`
    deploy, `False` health, none of them `None`;
  · **what git refuses, the person reads.** The three sentences on the merge path were GitHub's,
    and a deployment that never had branch protection was told about it.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest


def _git(where, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True,
                          check=False)


@pytest.fixture
def repo(tmp_path):
    where = tmp_path / "myapp"
    where.mkdir()
    _git(where, "init", "-q", "-b", "main")
    _git(where, "config", "user.email", "person@example.invalid")
    _git(where, "config", "user.name", "A Person")
    (where / "app.py").write_text("print('one')\n")
    _git(where, "add", "-A")
    _git(where, "commit", "-qm", "first")
    return where


@pytest.fixture
def box(tmp_path):
    from openfactory.adapters.sandbox.worktree import WorktreeSandbox

    return WorktreeSandbox(root=tmp_path / "work")


def _commit(where, text: str, message: str) -> None:
    (pathlib.Path(where) / "app.py").write_text(text)
    _git(where, "add", "-A")
    _git(where, "-c", "user.email=bot@openfactory.local", "-c", "user.name=bot",
         "commit", "-qm", message)


# ── the worktree box, when the remote is the repository itself ──────────────────────────────────

def test_a_resume_KEEPS_the_implemented_work(box, repo):
    """MEASURED BEFORE IT WAS FIXED, by driving a publish and then a resume: the agent's commit was
    dropped and the box logged `OPENFACTORY_BRANCH_GONE` about a branch this very repository was
    holding. The runner then force-pushes the fresh start over the open pull request — the exact
    destruction the box's own comment was written to prevent, arriving through the one door it did
    not cover."""
    first = box.prepare(repo_path=repo, base_branch="main", branch="openfactory/1",
                        checkout_existing=False, remote_url=str(repo))
    _commit(first.path, "print('the agent worked')\n", "implemented")
    box.publish_branch(workspace=first, remote_url=str(repo))
    assert "the agent worked" in _git(repo, "show", "openfactory/1:app.py").stdout

    resumed = box.prepare(repo_path=repo, base_branch="main", branch="openfactory/1",
                          checkout_existing=True, remote_url=str(repo))
    assert (pathlib.Path(resumed.path) / "app.py").read_text() == "print('the agent worked')\n"


def test_a_resume_invents_no_remote_and_no_tracking_ref(box, repo):
    """A fetch would write `refs/remotes/origin/openfactory/1` into a repository that has no
    `origin` — a remote-tracking ref for a remote that does not exist."""
    first = box.prepare(repo_path=repo, base_branch="main", branch="openfactory/1",
                        checkout_existing=False, remote_url=str(repo))
    _commit(first.path, "print('work')\n", "implemented")
    box.publish_branch(workspace=first, remote_url=str(repo))
    box.prepare(repo_path=repo, base_branch="main", branch="openfactory/1",
                checkout_existing=True, remote_url=str(repo))

    assert _git(repo, "remote").stdout.strip() == ""
    assert _git(repo, "for-each-ref", "--format=%(refname)", "refs/remotes/").stdout.strip() == ""


def test_publishing_again_after_a_resume_lands(box, repo):
    """The second pass has to reach the branch, or a repaired job silently keeps the first."""
    first = box.prepare(repo_path=repo, base_branch="main", branch="openfactory/1",
                        checkout_existing=False, remote_url=str(repo))
    _commit(first.path, "print('first pass')\n", "one")
    box.publish_branch(workspace=first, remote_url=str(repo))

    second = box.prepare(repo_path=repo, base_branch="main", branch="openfactory/1",
                         checkout_existing=True, remote_url=str(repo))
    _commit(second.path, "print('second pass')\n", "two")
    box.publish_branch(workspace=second, remote_url=str(repo))
    assert "second pass" in _git(repo, "show", "openfactory/1:app.py").stdout


def test_a_branch_that_really_is_gone_still_degrades_to_a_fresh_start(box, repo, caplog):
    """The fallback the original comment protects: a lost branch degrades a resume, never bricks
    it. What changed is only that *gone* is now asked of this repository rather than of a remote
    that is this repository."""
    box.prepare(repo_path=repo, base_branch="main", branch="openfactory/1",
                checkout_existing=False, remote_url=str(repo))
    _git(repo, "worktree", "remove", "--force", str(pathlib.Path(box.root) / "openfactory-1"))
    _git(repo, "branch", "-D", "openfactory/1")

    fresh = box.prepare(repo_path=repo, base_branch="main", branch="openfactory/1",
                        checkout_existing=True, remote_url=str(repo))
    assert (pathlib.Path(fresh.path) / "app.py").read_text() == "print('one')\n"
    assert "OPENFACTORY_BRANCH_GONE" in caplog.text


def test_a_REAL_remote_keeps_todays_path_exactly(box, repo, tmp_path):
    """The contract is narrowed to a remote that IS this repository. A deployment with a hosted
    forge must take the fetch path it has always taken — including the refusal to read a failed
    fetch as an absent branch."""
    from openfactory.adapters.sandbox.worktree import _is_this_repo

    assert _is_this_repo(str(repo), repo) is True
    assert _is_this_repo(str(tmp_path / "elsewhere"), repo) is False
    assert _is_this_repo("https://github.com/o/r.git", repo) is False
    assert _is_this_repo("git@github.com:o/r.git", repo) is False
    assert _is_this_repo(None, repo) is False, "no remote at all is the ambient-origin case"


def test_an_unreachable_remote_still_RAISES_rather_than_starting_fresh(box, repo, tmp_path):
    """"Could not ask" is never "it is not there" — the audit finding the fetch path carries, and
    this slice must not have widened a hole in it."""
    with pytest.raises(RuntimeError, match="could not ask the remote"):
        box.prepare(repo_path=repo, base_branch="main", branch="openfactory/1",
                    checkout_existing=True, remote_url=str(tmp_path / "not-a-repository"))


# ── nothing watches this project's code ─────────────────────────────────────────────────────────

def test_a_project_with_no_CI_has_an_observer_rather_than_a_refusal():
    """`build_observer` REFUSES an unknown kind, on the reasoning that an observer pointed at the
    wrong system never confirms a deployment. That reasoning is right, and it left a deployment
    with no CI at all with nowhere to go."""
    from openfactory.adapters.environment.base import EnvironmentObserver
    from openfactory.adapters.environment.registry import build_observer, observer_kind

    project = type("P", (), {
        "name": "a",
        "forge": type("F", (), {"kind": "local", "options": {}})(),
        "tracker": type("T", (), {"kind": "local", "options": {}})(),
    })()
    observer = build_observer(project)
    assert observer_kind(project) == "local"
    assert isinstance(observer, EnvironmentObserver)


def test_every_answer_says_there_is_nothing_watching_rather_than_it_could_not_look():
    from openfactory.adapters.environment.none import NoObserver

    watched = NoObserver()
    assert watched.ci_status(repo="o/r", ref="abc") == [], "a fact, not a failed read"
    assert watched.deploy_status(env="staging", ref="abc") == "none"
    assert watched.health(url="http://localhost") is False, (
        "a probe nobody made must not report a healthy service")


def test_ANY_forge_may_say_that_nothing_watches_it():
    """A GitHub repository with no workflows is entitled to say so rather than being told its
    checks are pending for ever."""
    from openfactory.adapters.environment.none import NoObserver
    from openfactory.adapters.environment.registry import build_observer

    project = type("P", (), {
        "name": "b",
        "forge": type("F", (), {"kind": "github", "options": {"ci": "none"}})(),
        "tracker": type("T", (), {"kind": "github", "options": {}})(),
    })()
    assert isinstance(build_observer(project), NoObserver)


# ── what git refuses, the person reads ──────────────────────────────────────────────────────────

def test_gits_own_refusals_have_a_cause_and_a_way_out():
    """MEASURED BEFORE THE ROWS EXISTED: all three sentences git actually writes came back
    `unknown`, whose remedy is *"I could not identify the cause from the error alone, so I will not
    retry blindly"* — said to somebody standing in the repository, one command from the fix. That
    is the exact C-27 failure this classifier exists to end."""
    from openfactory.techlead.classify import TREE, classify, remedy_for

    sentences = (
        "error: Your local changes to the following files would be overwritten by merge:\n\tapp.py",
        "Please commit your changes or stash them before you merge.",
        "this repository has a merge in progress — finish or abort it, then answer again",
        "fatal: Not possible to fast-forward, aborting.",
        "the base branch main is checked out in /tmp/linked",
    )
    for note in sentences:
        verdict = classify(note)
        assert verdict.cause == TREE, f"{note[:40]!r} still reads as {verdict.cause}"
        said = remedy_for(verdict).say
        assert "commit or stash" in said and "resume" in said, said


def test_the_sentence_is_the_persons_language_too():
    from openfactory.techlead.classify import classify, remedy_for

    verdict = classify("Your local changes to the following files would be overwritten")
    assert "stash" in remedy_for(verdict, language="pt-BR").say


def test_the_auto_hold_carries_the_WHOLE_sentence_and_the_address():
    """150 characters cut the one actionable part: git opens with `error:` and names the file
    AFTER the colon, so the preamble fitted and the file name did not. And the hold carried no
    `pr_url`, so a person was told a pull request could not be merged with no way to open it."""
    import inspect

    from openfactory.orchestrator import machine

    src = inspect.getsource(machine.JobRunner._auto_merge)
    assert "str(exc)[:150]" not in src, "the sentence is truncated before the file name"
    assert "pr_url=pr" in src, "the hold names no pull request"


# ── one refusal, asked by every door ────────────────────────────────────────────────────────────

def test_a_box_that_bounds_nothing_is_refused_ONCE_for_every_door():
    """A gate one door carries is a gate, and the other two are the doors an unattended factory
    actually uses: the panel's `scan` row and the poller's own activity started the same job in the
    same box without a word."""
    from openfactory.adapters.sandbox.registry import durable_refusal

    assert durable_refusal("container") == "" and durable_refusal("fargate") == ""
    why = durable_refusal("worktree")
    assert "durable job cannot run" in why
    assert "OPENFACTORY_SANDBOX=container" in why, "the remedy is named, not implied"
    assert durable_refusal("not-a-box"), "an unknown box is refused by the registry's own words"


def test_all_three_doors_ask_it():
    import inspect

    from openfactory.actions import catalog
    from openfactory.runtime.temporal import activities

    for source, where in ((inspect.getsource(catalog._start_durable), "start --durable"),
                          (inspect.getsource(catalog._scan), "the scan row"),
                          (inspect.getsource(activities.start_jobs), "the poller's activity")):
        assert "durable_refusal(" in source, f"{where} starts a durable job without asking"


# ── the heading and the fetcher name the same system ────────────────────────────────────────────

def test_the_CI_heading_reads_the_OBSERVER_and_not_the_forge(tmp_path, monkeypatch):
    """They disagreed about the same list of checks: `build_observer` dispatches on
    `observer_kind`, which reads `forge.options.ci` first, and the heading read `forge_kind`, which
    does not. A GitHub repository whose checks come from a declared non-GitHub CI was labelled
    GitHub over checks fetched from somewhere else."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal.view import _ci_provider

    registry = ProjectRegistry()
    registry.add(Project(name="mixed", repo_path=str(tmp_path),
                         tracker=ProviderRef(kind="github", repo="o/r"),
                         forge=ProviderRef(kind="github", repo="o/r",
                                           options={"ci": "azure_pipelines"})))
    registry.add(Project(name="mine", repo_path=str(tmp_path),
                         tracker=ProviderRef(kind="local", repo="mine"),
                         forge=ProviderRef(kind="local", repo="mine")))

    assert _ci_provider("mixed") == "Azure Pipelines", "it used to say GitHub"
    assert _ci_provider("mine") == "nothing is watched", "and a dash would mean unreadable"


def test_a_heading_never_takes_the_cockpit_down():
    from openfactory.runtime.temporal.view import _ci_provider

    assert _ci_provider("no-such-project") == "", "no name is better than the wrong name"


# ── both halves can reach the person's repositories ─────────────────────────────────────────────

def test_the_worker_AND_the_panel_mount_the_repositories_directory():
    """The worker clones and pushes into it; the panel's pull-request page reads `git diff` there.
    Source and target are identical, because a path one side names has to be a path the other can
    open."""
    compose = (pathlib.Path(__file__).resolve().parent.parent / "docker-compose.yml").read_text()
    mounts = [ln for ln in compose.splitlines() if "OPENFACTORY_REPOS_DIR:-" in ln and "- $" in ln]
    assert len(mounts) == 2, f"expected the worker and the panel to mount it, found {mounts}"
    for line in mounts:
        left, _, right = line.strip().lstrip("- ").partition("}:")
        assert left + "}" == right, f"the mount is not identity-mapped: {line.strip()}"


def test_an_older_env_file_still_boots():
    """Tolerated absent: the default is under `$HOME`, which exists on every machine that runs
    compose, and a deployment with no local project never looks inside it."""
    compose = (pathlib.Path(__file__).resolve().parent.parent / "docker-compose.yml").read_text()
    assert "${OPENFACTORY_REPOS_DIR:-${HOME}/openfactory/repos}" in compose


def test_an_unknown_CI_is_still_refused_by_name():
    """The row was added; the refusal it exists beside was not weakened."""
    from openfactory.adapters.environment.registry import build_observer

    project = type("P", (), {
        "name": "c",
        "forge": type("F", (), {"kind": "github", "options": {"ci": "jenkins"}})(),
        "tracker": type("T", (), {"kind": "github", "options": {}})(),
    })()
    with pytest.raises(ValueError, match="unknown CI 'jenkins'"):
        build_observer(project)
