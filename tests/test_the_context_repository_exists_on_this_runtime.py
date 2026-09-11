"""The product role's context repository exists the moment the project does (ADR-0049 slice 7).

ENABLED AND UNUSABLE was the state a fresh one-machine install landed in, and it was measured by
running the whole first hour rather than by reading it: `project init` wrote the `product:` section
that switches the module on, the repository behind it did not exist, and `openfactory doctor` said
*"the product module is enabled but unusable — could not read `.openfactory/product.yaml`"* on a
machine where nothing was wrong except that nobody had made the repository yet.

On this runtime that repository is a directory the installation owns: there is nobody to ask and
nothing to decide, so registration makes it — and SEEDS it, because an empty bare repository has
no commits and a checkout of its base branch fails in exactly the same way a missing one does.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

sys.path.insert(0, "tests")
import one_machine as om  # noqa: E402


@pytest.fixture
def registered(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = om.a_repository(tmp_path)
    om.a_deployment(tmp_path, monkeypatch=monkeypatch)
    code, out = om.cli("project", "init", "myapp", str(repo))
    assert code == 0, out
    return repo, out


def test_the_context_repository_is_made_AND_SEEDED(registered, tmp_path):
    repo, out = registered
    from openfactory.adapters.forge.registry import build_forge
    from openfactory.registry import ProjectRegistry

    forge = build_forge(ProjectRegistry().get("myapp"))
    where = forge.clone_url("myapp-context")

    assert "context repository created" in out
    shown = subprocess.run(["git", "-C", where, "show", "main:.openfactory/product.yaml"],
                           capture_output=True, text=True, check=False)
    assert shown.returncode == 0, "the repository has no commit — a checkout of `main` still fails"
    assert "product: myapp" in shown.stdout and "sources:" in shown.stdout


def test_the_doctor_finds_the_module_USABLE_on_a_fresh_install(registered):
    """The whole point: the first `doctor` a person runs must not report a module the platform
    itself switched on as broken."""
    from openfactory import doctor
    from openfactory.registry import ProjectRegistry

    report = doctor.diagnose(doctor.probes_for(ProjectRegistry().get("myapp")))
    product = next(f for f in report.findings if f.check == "product_link")

    assert product.ok, product.message


def test_BOTH_ENDS_declare_the_pair(registered):
    """The module reads it from both: the registry names the documentation repository and the
    source repository's manifest names it back. Declaring one end leaves a note about the other,
    and on this runtime both are ours to write."""
    repo, _ = registered
    from openfactory.registry import ProjectRegistry

    assert ProjectRegistry().get("myapp").product.docs_repo == "myapp-context"
    assert "docs_repo: myapp-context" in (repo / ".openfactory" / "project.yaml").read_text()


def test_a_second_run_makes_nothing_and_says_nothing(registered, tmp_path):
    """`project init` converges: the repository is already there and re-running must not report a
    creation that did not happen."""
    repo, _ = registered

    code, again = om.cli("project", "init", "myapp", str(repo))

    assert code == 0
    assert "context repository created" not in again
    assert "seeded" not in again, "a repository with a commit was seeded again"


def test_a_FAILED_seed_is_finished_by_the_next_run(tmp_path, monkeypatch):
    """A failed seed used to be a dead end (review of #106): the repository existed with no
    commit, `project init` did not retry — it ran the seed only on the branch that registers —
    and the other route into a context repository is gated on `if not docs_repo`, which
    registration had just set. The doctor then said "enabled but unusable" for ever on a machine
    whose only problem was one failed push."""
    import subprocess

    monkeypatch.setenv("HOME", str(tmp_path))
    repo = om.a_repository(tmp_path)
    om.a_deployment(tmp_path, monkeypatch=monkeypatch)

    real = subprocess.run
    state = {"failed": False}

    def one_bad_push(args, *a, **kw):
        if isinstance(args, list) and "push" in args and not state["failed"]:
            state["failed"] = True
            raise subprocess.CalledProcessError(1, args, stderr="no room on the disk")
        return real(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", one_bad_push)
    assert om.cli("project", "init", "myapp", str(repo))[0] == 0
    monkeypatch.setattr(subprocess, "run", real)

    from openfactory.adapters.forge.registry import build_forge
    from openfactory.registry import ProjectRegistry

    where = build_forge(ProjectRegistry().get("myapp")).clone_url("myapp-context")
    assert real(["git", "-C", where, "rev-parse", "--verify", "main"],
                capture_output=True).returncode != 0, "the push did not fail"

    code, again = om.cli("project", "init", "myapp", str(repo))

    assert code == 0
    assert "seeded" in again, "the second run said nothing about finishing the job"
    assert real(["git", "-C", where, "rev-parse", "--verify", "main"],
                capture_output=True).returncode == 0, "still no commit — the dead end stands"

    from openfactory import doctor

    product = next(f for f in doctor.diagnose(
        doctor.probes_for(ProjectRegistry().get("myapp"))).findings if f.check == "product_link")
    assert product.ok, product.message


def test_a_hosted_project_is_left_alone(tmp_path, monkeypatch):
    """Creating a repository in somebody's organisation is the most consequential thing this
    platform asks of a credential — it stays an operator's decision, on a hosted row."""
    monkeypatch.setenv("HOME", str(tmp_path))
    om.a_deployment(tmp_path, monkeypatch=monkeypatch)
    hosted = tmp_path / "hosted"
    hosted.mkdir()
    om.git(hosted, "init", "-q", "-b", "main")
    om.git(hosted, "config", "user.email", "a@b.c")
    om.git(hosted, "config", "user.name", "a")
    (hosted / "README.md").write_text("x\n")
    om.git(hosted, "add", "-A")
    om.git(hosted, "commit", "-qm", "first")

    # THE CALL ITSELF, not its output. A hosted forge would REFUSE without a credential and the
    # command would print the same nothing — so the assertion has to be that nobody asked.
    asked: list[str] = []
    monkeypatch.setattr("openfactory.adapters.forge.github.GitHubForge.create_repository",
                        lambda self, **kw: (asked.append(kw.get("name", "?")), ("x", True))[1],
                        raising=False)

    code, out = om.cli("project", "init", "theirs", str(hosted), "--repo", "them/theirs")

    assert asked == [], f"a repository was made in somebody's organisation: {asked}"
    assert "context repository created" not in out
    from openfactory.registry import ProjectRegistry

    assert ProjectRegistry().get("theirs").product is None


def test_a_failure_to_seed_does_not_lose_the_REGISTRATION(tmp_path, monkeypatch):
    """The project is registered before this runs and is worth keeping — but the person is told
    here rather than in a doctor line an hour later."""
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = om.a_repository(tmp_path)
    om.a_deployment(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setattr("openfactory.adapters.forge.local.LocalForge.create_repository",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no room on the disk")))

    code, out = om.cli("project", "init", "myapp", str(repo))
    from openfactory.registry import ProjectRegistry

    assert ProjectRegistry().get("myapp").name == "myapp", "the registration was lost"
    assert "could not be created" in out and "no room on the disk" in out
    # AND WHAT IT COSTS THEM, in the same breath: the module is on and unusable until somebody
    # makes that repository, and the doctor is where they will otherwise meet it.
    assert "doctor" in out and "unusable" in out
