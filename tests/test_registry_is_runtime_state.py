"""Registering a project costs no rebuild, and no crash can empty the registry (C-12).

`docker/worker.Dockerfile:39` bakes the registry into the image:

    COPY deploy/registry.yaml /etc/sdlc/registry.yaml
    ENV OPENFACTORY_REGISTRY=/etc/sdlc/registry.yaml

So adding a second project means `docker build` and a redeploy. For a downloadable product that is
disqualifying — nobody accepts rebuilding an image to onboard a repository — and it is also a live
operational hazard already on file: a rebuild that ships without the gitignored `deploy/registry.yaml`
produces a project-less worker that raises on every job.

READING THE FILE WAS NEVER THE PROBLEM. `_load_raw` already reads from disk on every call, so the
class is runtime state and the *deployment* is not. The fix is where the file lives: a writable
location that outlives the image, seeded from the image on first boot so a fresh install is never
project-less, and never re-seeded over projects that are already there.

AND A DURABILITY BUG FOUND ON THE WAY. `_save_raw` used `write_text`, which truncates before it
writes. A crash, a full disk or a SIGTERM mid-write leaves an EMPTY registry — which is the exact
project-less-worker failure above, reachable without anyone rebuilding anything. Two processes
writing at once lose one of the two projects the same way.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest
import yaml

from openfactory.contracts.project import Project, ProviderRef
from openfactory.registry import ProjectRegistry, seed_registry


def _p(name: str) -> Project:
    return Project(name=name, repo_path=f"/tmp/{name}",
                   tracker=ProviderRef(kind="github", repo=f"acme/{name}"))


# ── seeding: a fresh install is never project-less ──────────────────────────────────────────────

def test_a_missing_runtime_registry_is_seeded_from_the_image(tmp_path):
    seed = tmp_path / "seed.yaml"
    seed.write_text(yaml.safe_dump({"projects": {"books": _p("books").model_dump(mode="json")}}))
    live = tmp_path / "data" / "registry.yaml"

    assert seed_registry(seed=seed, live=live) is True
    assert [p.name for p in ProjectRegistry(live).list()] == ["books"]


def test_seeding_never_overwrites_projects_that_are_already_there(tmp_path):
    """The property that makes a redeploy safe. Without it, every deploy silently reverts every
    project added at runtime — and the operator finds out when a board stops being polled."""
    seed = tmp_path / "seed.yaml"
    seed.write_text(yaml.safe_dump({"projects": {"books": _p("books").model_dump(mode="json")}}))
    live = tmp_path / "data" / "registry.yaml"
    ProjectRegistry(live).add(_p("added-at-runtime"))

    assert seed_registry(seed=seed, live=live) is False
    assert [p.name for p in ProjectRegistry(live).list()] == ["added-at-runtime"]


def test_an_empty_runtime_registry_IS_seeded(tmp_path):
    """An existing but empty file is what a freshly mounted volume looks like. Treating "the file
    exists" as "somebody configured this" would leave that deployment project-less for ever — the
    failure this whole card is about."""
    seed = tmp_path / "seed.yaml"
    seed.write_text(yaml.safe_dump({"projects": {"books": _p("books").model_dump(mode="json")}}))
    live = tmp_path / "registry.yaml"
    live.write_text("projects: {}\n")

    assert seed_registry(seed=seed, live=live) is True
    assert [p.name for p in ProjectRegistry(live).list()] == ["books"]


def test_a_missing_seed_is_not_an_error(tmp_path):
    """A local `docker compose up` has no seed and starts empty on purpose. Raising here would
    make the OSS distribution refuse to boot."""
    assert seed_registry(seed=tmp_path / "nope.yaml", live=tmp_path / "registry.yaml") is False


def test_a_corrupt_seed_does_not_stop_the_worker_booting(tmp_path):
    """A worker that will not start because a seed file is malformed has turned a configuration
    mistake into an outage. It boots project-less and says so."""
    seed = tmp_path / "seed.yaml"
    seed.write_text("{{{ not yaml")
    assert seed_registry(seed=seed, live=tmp_path / "registry.yaml") is False


def test_seeding_is_reported(tmp_path, caplog):
    seed = tmp_path / "seed.yaml"
    seed.write_text(yaml.safe_dump({"projects": {"c": _p("c").model_dump(mode="json")}}))
    with caplog.at_level("INFO", logger="openfactory.registry"):
        seed_registry(seed=seed, live=tmp_path / "registry.yaml")
    assert any("seed" in r.getMessage().lower() for r in caplog.records)


# ── durability: no crash can empty it ───────────────────────────────────────────────────────────

def test_a_write_is_atomic(tmp_path):
    """`write_text` truncates first. A crash between truncate and write leaves an EMPTY registry,
    which is the project-less worker — reachable without anyone rebuilding anything."""
    live = tmp_path / "registry.yaml"
    reg = ProjectRegistry(live)
    reg.add(_p("one"))

    before = live.read_text()
    code = textwrap.dedent(f"""
        import os, signal
        from openfactory.registry import ProjectRegistry
        from openfactory.contracts.project import Project, ProviderRef
        reg = ProjectRegistry({str(live)!r})
        real = os.replace
        def die(*a, **kw):       # crash at the instant the file would be swapped in
            os.kill(os.getpid(), signal.SIGKILL)
        os.replace = die
        reg.add(Project(name="two", repo_path="/tmp/two",
                        tracker=ProviderRef(kind="github", repo="a/b")))
    """)
    subprocess.run([sys.executable, "-c", code], capture_output=True)

    assert live.read_text() == before, "a crash mid-write changed the registry"
    assert [p.name for p in ProjectRegistry(live).list()] == ["one"]


def test_no_temporary_file_is_left_behind(tmp_path):
    """The lock file is expected and must persist — an inter-process `flock` needs a stable inode,
    and re-creating it per call would let two processes lock two different files. What must not
    survive is write DEBRIS, which would accumulate one file per registration for ever."""
    live = tmp_path / "registry.yaml"
    ProjectRegistry(live).add(_p("one"))
    ProjectRegistry(live).add(_p("two"))
    left = sorted(f.name for f in tmp_path.iterdir())
    assert left == ["registry.yaml", "registry.yaml.lock"], left


def test_a_failed_write_leaves_no_debris(tmp_path):
    live = tmp_path / "registry.yaml"
    reg = ProjectRegistry(live)
    reg.add(_p("one"))
    import unittest.mock as mock

    with mock.patch("os.replace", side_effect=OSError("disk full")), pytest.raises(OSError):
        reg.add(_p("two"))
    assert not [f for f in tmp_path.iterdir() if f.name.endswith(".tmp")]


def test_two_processes_adding_at_once_do_not_lose_a_project(tmp_path):
    """Read-modify-write with no lock loses one of two concurrent adds. The panel and the CLI can
    both register, and a project that silently did not land is a board nobody polls."""
    live = tmp_path / "registry.yaml"
    ProjectRegistry(live).add(_p("base"))

    # `acme/...`, matching `_p()` above. This said `a/b` — a different org from the `base` project
    # the test seeds with — which was incidental to what it tests (the lock) and became load-bearing
    # once the registry started refusing a registry that spans GitHub installations (#64). The org
    # is now consistent so this stays a test about concurrent writes, which is what it is for.
    code = textwrap.dedent("""
        import sys
        from openfactory.registry import ProjectRegistry
        from openfactory.contracts.project import Project
        from openfactory.contracts.project import ProviderRef
        ProjectRegistry(sys.argv[1]).add(Project(
            name=sys.argv[2], repo_path="/tmp/x",
            tracker=ProviderRef(kind="github", repo="acme/" + sys.argv[2])))
    """)
    procs = [subprocess.Popen([sys.executable, "-c", code, str(live), f"p{n}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for n in range(6)]
    for p in procs:
        p.wait()

    names = sorted(p.name for p in ProjectRegistry(live).list())
    assert names == ["base", "p0", "p1", "p2", "p3", "p4", "p5"], names


# ── it still behaves ────────────────────────────────────────────────────────────────────────────

def test_add_get_remove_still_work(tmp_path):
    reg = ProjectRegistry(tmp_path / "r.yaml")
    reg.add(_p("a"))
    assert reg.get("a").name == "a"
    reg.remove("a")
    with pytest.raises(KeyError):
        reg.get("a")


def test_adding_a_duplicate_still_refuses(tmp_path):
    reg = ProjectRegistry(tmp_path / "r.yaml")
    reg.add(_p("a"))
    with pytest.raises(ValueError):
        reg.add(_p("a"))


def test_a_malformed_registry_names_itself(tmp_path):
    """One deployment, N projects, one operator. 'not a dict' without the path is useless."""
    live = tmp_path / "r.yaml"
    live.write_text("{{{ not yaml")
    with pytest.raises(ValueError) as e:
        ProjectRegistry(live).list()
    assert str(live) in str(e.value)


def test_one_bad_entry_names_the_project_it_broke(tmp_path):
    """`list()` builds every Project in one comprehension and its callers catch nothing, so a
    single malformed entry stops ALL projects. That is arguably right — but a bare pydantic
    traceback does not tell the operator which registry line to open."""
    live = tmp_path / "r.yaml"
    live.write_text(yaml.safe_dump({"projects": {
        "good": _p("good").model_dump(mode="json"),
        "bad": {"repo_path": "/tmp/bad"},  # no name
    }}))
    with pytest.raises(ValueError) as e:
        ProjectRegistry(live).list()
    assert "bad" in str(e.value)


# ── the deployment shape ────────────────────────────────────────────────────────────────────────

def test_the_worker_image_does_not_bake_the_live_registry():
    """The reachability guard for the whole card. Everything above can pass while the Dockerfile
    still copies the registry to the path the worker reads — which is the state this found."""
    from pathlib import Path

    dockerfile = (Path(__file__).resolve().parent.parent / "docker" / "worker.Dockerfile").read_text()
    live = os.environ.get("OPENFACTORY_REGISTRY_LIVE_DEFAULT", "/var/lib/openfactory/registry.yaml")
    for line in dockerfile.splitlines():
        if line.startswith("COPY") and "registry.yaml" in line:
            assert live not in line, (
                "the image copies the registry to the path the worker READS, so adding a project "
                f"needs a rebuild: {line.strip()}"
            )
