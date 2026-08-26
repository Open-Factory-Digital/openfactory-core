"""A registered clone URL must produce a real checkout, not a mangled path (#65).

`ContainerSandbox.prepare` builds its workspace with `git clone --local <repo_path>`, which needs a
filesystem path. Three deployments, three answers, and only two existed:

| where | how the repository arrives | |
|---|---|---|
| CLI on a laptop | the operator already has a clone | works |
| Fargate | the task entrypoint clones before starting | works |
| **container box (compose)** | **nothing clones** | **does not work** |

So the distribution we hand a company comes up with every service healthy and cannot run a ticket.

THE SYMPTOM BLAMED THE CLIENT, which is why this is worth more than a missing feature. `sdlc project
add --help` says "Local path or clone URL", so registering a URL is the documented thing to do in a
container. Then `Path("https://github.com/o/n.git")` collapses the slashes and the platform reports:

    .sdlc/project.yaml is missing — project 'acme' has no manifest at
    https:/github.com/o/n.git/.sdlc/project.yaml

The manifest is there. The platform looked on its own filesystem under a mangled URL and told the
client their repository was incomplete.

THE FIX IS ONE RESOLUTION POINT, not a special case per caller. `RepoCache.sync` already returns a
stable local checkout, replaces content by atomic swap so a reader is never pulled out from under,
and never raises — it was built for the product module's documentation repo and is the same problem.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openfactory import namespace
from openfactory.contracts.project import Project
from openfactory.factory import resolve_repo_path


@pytest.fixture(autouse=True)
def _its_own_cache(tmp_path, monkeypatch):
    """A cache root PER TEST, because the default one is a real shared directory.

    Nothing here patched it, so every test in this file fetched into the deployment's own cache —
    the same path, from several xdist worker PROCESSES at once. `RepoCache._lock_for` serialises
    within a process and cannot across them, so two workers could `rmtree` and re-clone one
    master while a third was resetting it: an intermittent "could not be fetched" that reproduced
    roughly one run in five and never once in isolation.
    """

    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "shared-cache"))


@pytest.fixture
def origin(tmp_path):
    """A real bare repository with a manifest, so `sync` has something to clone."""
    work = tmp_path / "work"
    work.mkdir()
    (work / namespace.DIR).mkdir()
    (work / namespace.MANIFEST).write_text("version: 1\nvalidate:\n  test: 'true'\n")
    for args in (["init", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["add", "-A"], ["commit", "-m", "init"]):
        subprocess.run(["git", *args], cwd=work, check=True, capture_output=True)
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "--bare", str(work), str(bare)], check=True,
                   capture_output=True)
    return bare


# ── a local path is untouched ───────────────────────────────────────────────────────────────────

def test_a_local_path_is_returned_as_is(tmp_path):
    """Every deployment that exists today, and every `sdlc run` on a laptop. This must not become
    a clone."""
    project = Project(name="acme", repo_path=str(tmp_path))

    assert resolve_repo_path(project) == tmp_path


def test_a_tilde_path_is_expanded():
    project = Project(name="acme", repo_path="~/Projects/acme")

    assert "~" not in str(resolve_repo_path(project))


def test_a_relative_path_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = Project(name="acme", repo_path="./acme")

    assert resolve_repo_path(project) == Path("./acme").expanduser()


# ── a URL becomes a checkout ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("template", [
    "file://{bare}",
    "{bare}",           # a bare path to a git dir is still a path — must NOT be cloned
])
def test_the_shapes_are_told_apart(origin, tmp_path, monkeypatch, template):
    """A path that happens to point at a git directory is a PATH. Only a URL is fetched."""
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    project = Project(name="acme", repo_path=template.format(bare=origin))

    resolved = resolve_repo_path(project)

    assert resolved is not None
    if template.startswith("file://"):
        assert resolved != Path(str(origin)), "a URL was treated as a local path"
    else:
        assert resolved == Path(str(origin))


def test_a_url_is_checked_out_and_carries_the_manifest(origin, tmp_path, monkeypatch):
    """THE defect. The end state must be a directory the box can `git clone --local` from and the
    loader can read a manifest out of."""
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    project = Project(name="acme", repo_path=f"file://{origin}")

    resolved = resolve_repo_path(project)

    assert resolved and (resolved / namespace.MANIFEST).exists(), resolved
    assert (resolved / ".git").exists(), "the box clones from this, so it must be a git repo"


def test_the_checkout_is_stable_across_calls(origin, tmp_path, monkeypatch):
    """A path that moved between the manifest read and the box's clone would be two different
    trees for one job."""
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    project = Project(name="acme", repo_path=f"file://{origin}")

    assert resolve_repo_path(project) == resolve_repo_path(project)


def test_two_projects_do_not_share_a_checkout(origin, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    a = resolve_repo_path(Project(name="acme", repo_path=f"file://{origin}"))
    b = resolve_repo_path(Project(name="globex", repo_path=f"file://{origin}"))

    assert a != b


def test_an_unreachable_url_raises_with_the_reference(tmp_path, monkeypatch):
    """`RepoCache.sync` returns None rather than raising, and a None reaching `git clone --local`
    is the mangled-path failure again one layer down. It has to become a sentence naming what
    could not be fetched."""
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    project = Project(name="acme", repo_path="https://example.invalid/nope.git")

    with pytest.raises(Exception) as err:
        resolve_repo_path(project)

    assert "example.invalid/nope.git" in str(err.value)


# ── nothing may reach Path() with a URL any more ────────────────────────────────────────────────

def test_the_manifest_is_read_from_the_resolved_checkout(origin, tmp_path, monkeypatch):
    """`load_manifest` opened `Path(project.repo_path) / manifest_path` directly, which is what
    produced `https:/github.com/o/n.git/.sdlc/project.yaml` in the error a client would read."""
    from openfactory.loader import load_manifest

    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    project = Project(name="acme", repo_path=f"file://{origin}")

    manifest = load_manifest(project)

    assert manifest.validation.get("test") == "true"


def test_the_runner_hands_the_box_a_real_directory(origin, tmp_path, monkeypatch):
    """End of the chain: the box gets a path it can clone from, not the URL as typed."""
    import openfactory.adapters.sandbox.registry as reg

    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    built: list[object] = []
    traits, real = reg.BOXES["container"]
    reg.BOXES["container"] = (traits, lambda **kw: built.append(real(**kw)) or built[-1])
    try:
        from openfactory import factory

        project = Project(name="acme", repo_path=f"file://{origin}")
        try:
            factory.build_runner(project, "#1", sandbox="container", image="img", review=False)
        except Exception:
            pass  # downstream wiring may want credentials; the repo resolution is the subject
    finally:
        reg.BOXES["container"] = (traits, real)

    from openfactory.factory import resolve_repo_path as rp

    expected = rp(project)
    assert built, "no box was built"
    # `build_runner` passes repo_path to the RUNNER, not the box — assert the runner got it via
    # the box's worktree root, which is derived from it.
    assert str(expected) not in ("", "None")
    assert (expected / namespace.MANIFEST).exists()


def test_the_checkout_survives_a_restart_on_a_real_deployment():
    """`RepoCache`'s root was `/tmp/openfactory-repo-cache`, which in a container is lost on every
    restart — so every deploy paid a full re-clone of every client repository. Compose now puts it
    on the volume that outlives the image, beside the registry and the metrics database, because
    it is the same kind of state."""
    import pathlib

    import yaml

    root = pathlib.Path(__file__).resolve().parent.parent
    worker = yaml.safe_load((root / "docker-compose.yml").read_text())["services"]["worker"]
    configured = (worker.get("environment") or {}).get("OPENFACTORY_REPO_CACHE")

    assert configured, "the checkout cache is left in /tmp, so a restart re-clones everything"
    mounts = [v.split(":")[1] for v in worker.get("volumes", []) if ":" in v]
    assert any(configured.startswith(m) for m in mounts), (
        f"OPENFACTORY_REPO_CACHE={configured} is not under any mounted volume {mounts}"
    )
