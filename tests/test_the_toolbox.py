"""The harness toolbox: populated once, stamped, and mounted read-only (ADR-0037 D2).

The mechanics are what this file pins. Three of them are the ones that would fail in production
and nowhere else, so each has a test that reproduces the production shape rather than the happy
path:

1. **The stamp is written LAST.** A worker killed mid-copy must leave something the next boot
   calls unpopulated, or a half-copied toolbox is mounted for ever and the failure is a harness
   that exists and does not run.
2. **The mount is by VOLUME NAME, read-only.** The compose worker is itself a container talking to
   the host's daemon, so a `-v /some/worker/path` is resolved against the HOST filesystem where
   that path does not exist — Docker silently creates an empty directory and the box gets an empty
   toolbox. A named volume is the daemon's own object and works identically either way.
3. **A missing toolbox is not an error at boot.** A development worker, or an image built without
   the toolbox stage, must still start; `sdlc box prove` is where the absence is reported, by name.
"""

from __future__ import annotations

import json

import pytest

from openfactory.runtime import toolbox


@pytest.fixture
def baked(tmp_path):
    """What the worker image really bakes — and the SYMLINK matters.

    The real `claude` entry is a symlink into `pkg/`, pointing at the IN-BOX mount point rather
    than at the volume, so it is dangling where it is copied and resolves where it is mounted.
    The first version of this fixture used plain files only, which is why the suite was green
    while the real worker failed with `[Errno 17] File exists` copying that symlink over a
    partial tree."""
    src = tmp_path / "src"
    (src / "runtime" / "bin").mkdir(parents=True)
    (src / "runtime" / "bin" / "node").write_text("#!/bin/sh\necho node\n")
    (src / "pkg").mkdir()
    (src / "pkg" / "claude.exe").write_text("#!/bin/sh\nexec true claude\n")
    (src / "claude").symlink_to("/opt/openfactory-toolbox/pkg/claude.exe")
    codex = src / "codex"
    codex.write_text("#!/bin/sh\nexec true codex\n")
    codex.chmod(0o755)
    return src


# ── populate ────────────────────────────────────────────────────────────────────────────────────

def test_it_copies_the_binaries_and_the_runtime(baked, tmp_path):
    live = tmp_path / "live"
    toolbox.populate(source=baked, live=live)

    # `claude` is a symlink to the mount point, so it is dangling here — `exists()` follows the
    # link and answers False. That is correct, and it is why the stamp cannot use `is_file()`.
    assert (live / "claude").is_symlink() and (live / "codex").exists()
    assert (live / "runtime" / "bin" / "node").exists(), "the Node runtime must come too — kimi " \
                                                         "and codex are Node entries"


def test_the_entries_stay_executable(baked, tmp_path):
    import os

    live = tmp_path / "live"
    toolbox.populate(source=baked, live=live)

    assert os.access(live / "codex", os.X_OK), "a copied harness that is not executable is a " \
                                               "toolbox that mounts and does nothing"


def test_it_completes_over_a_partial_copy(baked, tmp_path):
    """THE defect, found on the real worker. A crash mid-copy leaves entries behind; the next boot
    must finish the job, not fail on the first one that already exists.

    `shutil.copy2(..., follow_symlinks=False)` raises FileExistsError when the target symlink is
    already there, so the worker looped: partial copy, no stamp, retry, same error, for ever. The
    volume sat at 95 MB of a 701 MB toolbox with `codex`, `kimi` and `pkg` missing entirely."""
    live = tmp_path / "live"
    live.mkdir()
    (live / "claude").symlink_to("/somewhere/stale")     # what the crashed run left
    (live / "runtime").mkdir()

    stamp = toolbox.populate(source=baked, live=live)

    assert stamp.get("harnesses"), "populate could not complete over a partial copy"
    assert (live / "codex").exists() and (live / "pkg" / "claude.exe").exists()
    assert (live / "claude").readlink() == \
        __import__("pathlib").Path("/opt/openfactory-toolbox/pkg/claude.exe"), "the stale link survived"


def test_the_symlink_entry_is_copied_as_a_link_not_followed(baked, tmp_path):
    """Following it would copy a 260 MB binary to the top level and leave `pkg` unreferenced —
    twice the disk and a toolbox whose entry no longer points at the package it came from."""
    live = tmp_path / "live"
    toolbox.populate(source=baked, live=live)

    assert (live / "claude").is_symlink()


def test_it_stamps_what_it_is(baked, tmp_path):
    live = tmp_path / "live"
    stamp = toolbox.populate(source=baked, live=live)

    assert stamp["harnesses"] == ["claude", "codex"], (
        "the stamp must list the symlinked entry too — it is the main harness"
    )
    assert stamp["variant"] == toolbox.variant()
    assert json.loads((live / toolbox.STAMP).read_text()) == stamp


def test_a_second_boot_does_not_copy_again(baked, tmp_path):
    """This runs on every worker start. Re-copying ~800 MB each time would add a minute to every
    restart, and a restart happens on every deploy."""
    live = tmp_path / "live"
    toolbox.populate(source=baked, live=live)
    marker = live / "codex"          # a plain file; `claude` is a symlink in the real toolbox
    marker.write_text("#!/bin/sh\nexec true TOUCHED\n")

    toolbox.populate(source=baked, live=live)

    assert "TOUCHED" in marker.read_text(), "it re-copied over an already-populated toolbox"


def test_force_copies_again(baked, tmp_path):
    """The harness version bump path."""
    live = tmp_path / "live"
    toolbox.populate(source=baked, live=live)
    (live / "codex").write_text("stale")

    toolbox.populate(source=baked, live=live, force=True)

    assert "stale" not in (live / "codex").read_text()


# ── the crash-safety story ──────────────────────────────────────────────────────────────────────

def test_a_directory_with_binaries_but_no_stamp_is_not_populated(baked, tmp_path):
    """The state a worker killed mid-copy leaves behind. It has files in it and is NOT a toolbox;
    reading the directory would call it done and mount something incomplete for ever."""
    live = tmp_path / "live"
    live.mkdir()
    (live / "codex").write_text("half a binary")

    assert toolbox.is_populated(live) is False

    toolbox.populate(source=baked, live=live)
    assert toolbox.is_populated(live) is True


def test_the_stamp_is_invalidated_before_the_copy_starts(baked, tmp_path, monkeypatch):
    """A stale stamp sitting over freshly-written bytes is the one arrangement that LIES. So the
    stamp goes first and is rewritten last — if the copy dies in between, the next boot sees no
    stamp and redoes it."""
    live = tmp_path / "live"
    toolbox.populate(source=baked, live=live)

    import shutil as _shutil

    def _die(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(_shutil, "copy2", _die)
    with pytest.raises(OSError):
        toolbox.populate(source=baked, live=live, force=True)

    assert not (live / toolbox.STAMP).exists(), "a stamp survived a failed copy"
    assert toolbox.is_populated(live) is False


def test_a_toolbox_built_for_another_variant_is_not_populated(baked, tmp_path, monkeypatch):
    """A worker rebuilt for a different architecture must not inherit the old volume's contents —
    the binaries in it cannot execute, and the failure would be a dynamic-loader error naming the
    wrong thing."""
    live = tmp_path / "live"
    toolbox.populate(source=baked, live=live)

    monkeypatch.setattr(toolbox, "variant", lambda: "linux-riscv64-glibc")
    assert toolbox.is_populated(live) is False


# ── absence is a condition, not a crash ─────────────────────────────────────────────────────────

def test_no_baked_toolbox_is_not_an_error(tmp_path):
    """A development worker, or an image built without the toolbox stage. It must still boot; the
    absence is reported by `box prove`, not by refusing to start."""
    assert toolbox.populate(source=tmp_path / "nope", live=tmp_path / "live") == {}


def test_an_unreadable_stamp_degrades_to_absent(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    (live / toolbox.STAMP).write_text("{not json")

    assert toolbox.read_stamp(live) == {}
    assert toolbox.is_populated(live) is False


# ── the variant ─────────────────────────────────────────────────────────────────────────────────

def test_the_variant_names_os_arch_and_libc():
    parts = toolbox.variant().split("-")

    assert len(parts) == 3, toolbox.variant()
    assert parts[2] in ("glibc", "musl"), toolbox.variant()


# ── the mount ───────────────────────────────────────────────────────────────────────────────────

def _argv(monkeypatch, **box_kwargs):
    import openfactory.adapters.sandbox.container as mod
    from openfactory.adapters.sandbox.container import ContainerSandbox

    calls: list[list[str]] = []
    monkeypatch.setattr(mod, "_host",
                        lambda args, timeout=None: (calls.append(list(args)), (0, ""))[1])
    ContainerSandbox(image="img", **box_kwargs).prepare(
        repo_path=__import__("pathlib").Path("."), base_branch="main", branch="sdlc/1"
    )
    return next(a for a in calls if "run" in a)


def test_the_toolbox_is_mounted_read_only(monkeypatch):
    """Read-only bounds the accident, not the adversary: a process at uid 0 in the box can copy a
    binary out and run a patched copy, and ADR-0037 says so plainly. What `:ro` buys is that the
    toolbox one job leaves behind is the toolbox the next job gets."""
    from openfactory.adapters.sandbox.container import TOOLBOX_MOUNT

    argv = _argv(monkeypatch, toolbox="openfactory_toolbox")

    assert f"openfactory_toolbox:{TOOLBOX_MOUNT}:ro" in argv, argv


def test_a_box_with_no_toolbox_mounts_nothing(monkeypatch):
    """The worktree-era default and every existing test. A bare `-v :/opt/openfactory-toolbox:ro` would
    be a docker error, and mounting an empty host path would be worse — a toolbox that exists and
    is empty."""
    from openfactory.adapters.sandbox.container import TOOLBOX_MOUNT

    argv = _argv(monkeypatch)

    assert not any(TOOLBOX_MOUNT in part for part in argv), argv


def test_the_mount_point_matches_what_the_adapters_are_told(monkeypatch):
    """The two halves are connected by nothing but agreement: `harness_path` tells the adapter
    where to look, and `prepare` decides where to mount. This is the only thing that checks they
    are the same place."""
    from openfactory.adapters.sandbox.container import ContainerSandbox

    argv = _argv(monkeypatch, toolbox="openfactory_toolbox")
    mount = next(p for p in argv if p.startswith("openfactory_toolbox:")).split(":")[1]
    told = ContainerSandbox(image="img").harness_path("claude")

    assert told.startswith(mount + "/"), (told, mount)


# ── reachability: the deployment's volume must reach the box ────────────────────────────────────

def test_the_factory_hands_the_deployment_volume_to_the_box(monkeypatch):
    """`OPENFACTORY_TOOLBOX_VOLUME` is a DEPLOYMENT fact — one volume for every project on this worker —
    so it comes from the environment, not from `box:`. A client naming the framework's volume
    would be a client naming what gets mounted into their own container.

    Asserted at the end of the chain, because the last three times this shape appeared the value
    was accepted somewhere in the middle and dropped before it arrived."""
    import openfactory.adapters.sandbox.registry as reg
    from openfactory.contracts.project import Project

    monkeypatch.setenv("OPENFACTORY_TOOLBOX_VOLUME", "openfactory_toolbox")
    built: list[object] = []
    traits, real = reg.BOXES["container"]
    reg.BOXES["container"] = (traits, lambda **kw: built.append(real(**kw)) or built[-1])
    try:
        from openfactory import factory

        try:
            factory.build_runner(Project(name="acme", repo_path="/tmp/acme"), "#1",
                                 sandbox="container", image="img", review=False)
        except Exception:
            pass
    finally:
        reg.BOXES["container"] = (traits, real)

    assert built and built[0].toolbox == "openfactory_toolbox", built


def test_no_volume_configured_mounts_nothing(monkeypatch):
    """Every deployment that exists today, and every local `sdlc run`."""
    import openfactory.adapters.sandbox.registry as reg
    from openfactory.contracts.project import Project

    monkeypatch.delenv("OPENFACTORY_TOOLBOX_VOLUME", raising=False)
    built: list[object] = []
    traits, real = reg.BOXES["container"]
    reg.BOXES["container"] = (traits, lambda **kw: built.append(real(**kw)) or built[-1])
    try:
        from openfactory import factory

        try:
            factory.build_runner(Project(name="acme", repo_path="/tmp/acme"), "#1",
                                 sandbox="container", image="img", review=False)
        except Exception:
            pass
    finally:
        reg.BOXES["container"] = (traits, real)

    assert built and built[0].toolbox is None


def test_the_worker_populates_the_toolbox_on_boot():
    """The population is on the worker's boot path or it is a function nobody calls — which is the
    defect this repository is named for. Asserted structurally: `main()` must reach it."""
    import pathlib

    src = (pathlib.Path(__file__).resolve().parent.parent
           / "openfactory/runtime/temporal/worker.py").read_text()
    assert "populate_toolbox" in src or "toolbox import populate" in src, (
        "the worker never populates the toolbox, so the volume the boxes mount stays empty"
    )
