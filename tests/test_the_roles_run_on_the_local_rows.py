"""The roles run on the local rows — a context repository, a board, and the truth at the end (7).

The product role needs somewhere to write requirements, the factory needs somewhere to file its
own impediments, and on one machine there is no second organisation to put either in. Both were
answered by silence: `ProductConfig` was never written, so the role was off; and the impediment
path logged `OPENFACTORY_OPS_NO_BOARD` and dropped what it had to say — measured while driving the
one-machine proof, where a gate that could not run reported itself to a log nobody reads.

WHAT IS PROVEN HERE:

  · the context repository is a BARE repository this installation owns, created idempotently, and
    a push into it is accepted — which is the whole reason it is bare;
  · the person's own repository is never what a context name resolves to;
  · the factory's own board on this row is the project's own tracker with the `fabrica` label, and
    a declared board still wins on every row;
  · `project init` writes the `product:` section for a path and not for a hosted registration;
  · the manifest is scaffolded with the branch this checkout is REALLY on, and the closing lines
    name the one thing no command can do — which is not the same thing on both doors.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

sys.path.insert(0, "tests")
import one_machine as om  # noqa: E402


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """A person's repository, and an operator directory of their own."""
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = om.a_repository(tmp_path)
    # THROUGH MONKEYPATCH, ALWAYS, IN THIS PROCESS. Writing `os.environ` here leaves
    # `OPENFACTORY_SANDBOX=worktree` set for everything that runs after this file, and the action
    # layer's own tests then fail on whatever order the suite happens to use — which is what CI
    # caught while eight local blocks stayed green (2026-09-10).
    om.a_deployment(tmp_path, monkeypatch=monkeypatch)
    return repo


@pytest.fixture
def forge(deployment):
    from openfactory.adapters.forge.local import LocalForge

    return LocalForge("myapp", str(deployment), base="main")


# ── the context repository ──────────────────────────────────────────────────────────────────────

def test_the_local_forge_can_create_a_repository_at_all():
    """Asked, never assumed: `RepositoryCreatingForge` is a separate protocol precisely so a
    caller can say plainly that this forge cannot."""
    from openfactory.adapters.forge.base import RepositoryCreatingForge
    from openfactory.adapters.forge.local import LocalForge

    assert isinstance(LocalForge("x", "/tmp", base="main"), RepositoryCreatingForge)


def test_the_context_repository_is_BARE_and_the_installations_own(forge, deployment, tmp_path):
    import pathlib

    name, created = forge.create_repository(name="myapp-context")
    where = pathlib.Path(forge.clone_url(name))

    assert created and (where / "HEAD").exists(), "not a repository"
    assert not (where / ".git").exists(), "not bare — a push into it would be refused"
    assert str(tmp_path) in str(where) and str(deployment) not in str(where), (
        f"the context repository is inside the person's own checkout: {where}")


def test_creating_it_twice_is_the_EXPECTED_case(forge):
    assert forge.create_repository(name="myapp-context") == ("myapp-context", True)
    assert forge.create_repository(name="myapp-context") == ("myapp-context", False)


def test_a_PUSH_into_it_is_accepted_which_is_why_it_is_bare(forge, tmp_path):
    """The knowledge pipeline pushes into a clone's `origin` and the requirement authoring pushes
    straight at `clone_url`. Git refuses a push into a branch that is checked out, so a non-bare
    repository here would work until the first push and then fail inside the product role's first
    requirement, in a message about `receive.denyCurrentBranch`."""
    forge.create_repository(name="myapp-context")
    clone = tmp_path / "clone"

    subprocess.run(["git", "clone", "-q", forge.clone_url("myapp-context"), str(clone)],
                   capture_output=True, text=True, check=True)
    (clone / "REQ-1.md").write_text("# a requirement\n")
    om.git(clone, "config", "user.email", "a@b.c")
    om.git(clone, "config", "user.name", "a")
    om.git(clone, "add", "-A")
    om.git(clone, "commit", "-qm", "the first requirement")
    pushed = om.git(clone, "push", "-q", "origin", "HEAD:main")

    assert pushed.returncode == 0, pushed.stderr


def test_a_refusal_RAISES_rather_than_reporting_a_repository_nobody_can_push_to(forge, tmp_path):
    """The protocol's own rule. A refusal read as success would have the onboarding report a
    repository that is not there, and the first sign would be the product role failing to write a
    requirement an hour later, in a message about something else."""
    import pathlib

    where = pathlib.Path(forge.clone_url("blocked-context"))
    where.parent.mkdir(parents=True, exist_ok=True)
    where.write_text("a file is standing where the repository would go\n")

    with pytest.raises(RuntimeError, match="context repository"):
        forge.create_repository(name="blocked-context")


def test_the_persons_own_repository_is_never_a_context_name(forge, deployment):
    """The cut this slice's plan aims at: `clone_url` answering the person's path for a context
    name would have the product role committing requirements into their source repository."""
    assert forge.clone_url("myapp") == str(deployment)
    assert forge.clone_url("myapp-context") != str(deployment)


# ── the factory's own board ─────────────────────────────────────────────────────────────────────

def _project(**over):
    from openfactory.contracts.project import Project, ProviderRef

    row = {"name": "myapp", "repo_path": "/tmp/myapp",
           "tracker": ProviderRef(kind="local", repo="myapp")}
    row.update(over)
    return Project(**row)


def test_the_factory_files_its_own_impediments_where_there_IS_a_board():
    from openfactory.ops import impediment

    board = impediment._board(_project())

    assert board is not None and board.tracker.kind == "local"
    assert board.label == "fabrica", "nothing would tell the factory's cards from the person's"


def test_a_hosted_project_that_declared_none_still_has_none():
    """ADR-0027's reasoning stands where there ARE two boards: a client's board carries the
    client's product."""
    from openfactory.contracts.project import ProviderRef
    from openfactory.ops import impediment

    assert impediment._board(_project(tracker=ProviderRef(kind="github", repo="o/n"))) is None


def test_a_DECLARED_board_wins_on_every_row():
    from openfactory.contracts.project import FactoryBoard, ProviderRef
    from openfactory.ops import impediment

    mine = FactoryBoard(tracker=ProviderRef(kind="github", repo="us/ops"), label="ours")

    assert impediment._board(_project(factory_board=mine)).label == "ours"


# ── what `project init` writes, and what it says ────────────────────────────────────────────────

def test_a_path_gets_the_product_section_and_a_hosted_row_does_not(deployment, tmp_path):
    from openfactory.registry import ProjectRegistry

    assert om.cli("project", "init", "myapp", str(deployment))[0] == 0
    mine = ProjectRegistry().get("myapp")

    assert mine.product is not None and mine.product.docs_repo == "myapp-context"

    hosted = tmp_path / "hosted"
    hosted.mkdir()
    om.git(hosted, "init", "-q", "-b", "main")
    om.git(hosted, "config", "user.email", "a@b.c")
    om.git(hosted, "config", "user.name", "a")
    (hosted / "README.md").write_text("x\n")
    om.git(hosted, "add", "-A")
    om.git(hosted, "commit", "-qm", "first")
    # THE SAME DOOR, so the mutation that widens `project init`'s local branch is visible here:
    # registering through `project add` exercises different code and let that cut survive.
    om.cli("project", "init", "theirs", str(hosted), "--repo", "them/theirs")

    assert ProjectRegistry().get("theirs").product is None, (
        "a hosted project was switched on without an operator deciding where its requirements go")


def test_the_manifest_is_scaffolded_with_the_branch_this_checkout_is_ON(tmp_path, monkeypatch):
    """`git init` still yields `master` on plenty of machines while the template says `main` — so
    the manifest named a branch that does not exist, and the pickup gate hashed it there and held
    every card without saying why."""
    monkeypatch.setenv("HOME", str(tmp_path))
    om.a_deployment(tmp_path, monkeypatch=monkeypatch)
    repo = tmp_path / "onmaster"
    repo.mkdir()
    om.git(repo, "init", "-q", "-b", "master")
    om.git(repo, "config", "user.email", "a@b.c")
    om.git(repo, "config", "user.name", "a")
    (repo / "README.md").write_text("x\n")
    om.git(repo, "add", "-A")
    om.git(repo, "commit", "-qm", "first")

    code, out = om.cli("project", "init", "onmaster", str(repo))

    assert code == 0, out
    assert "base_branch: master" in (repo / ".openfactory" / "project.yaml").read_text()


def test_the_closing_lines_say_the_one_thing_no_command_can_do(deployment):
    """On a local project there is no forge credential to grant — the repository is theirs — and
    the thing that really is left is committing the manifest where the gate reads it."""
    code, out = om.cli("project", "init", "myapp", str(deployment))

    assert code == 0
    assert "commit `.openfactory/project.yaml` on `main`" in out
    assert "grant the forge credential access" not in out
