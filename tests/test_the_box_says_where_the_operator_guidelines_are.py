"""The agent has to be able to OPEN an operator `reference/` document the index names (#318).

The index entry used to be labelled relative to the operator directory — `reference/big.md`, the
way `docs.architecture`'s repo-relative entries read. The agent works from the CHECKOUT, so that
label was wrong in two different ways at once: on a container box the operator directory is not
mounted at all (the box mounts *"the checkout, the toolbox and nothing else"*), and on a worktree
box the label resolves inside the repository, where the agent finds nothing — or, worse, a
different file, when the project has a `reference/` directory of its own. Found in review of the
pull request that added the tier.

So the BOX answers where those documents are readable from inside it, the same seam as
`harness_path`, and a box that cannot reach them answers None — the caller then indexes nothing
rather than advertising a path that resolves nowhere.
"""

from __future__ import annotations

import pathlib

import pytest

from openfactory.adapters.sandbox.container import GUIDELINES_MOUNT, ContainerSandbox
from openfactory.adapters.sandbox.worktree import WorktreeSandbox
from openfactory.orchestrator import operator_guidelines as og

ROOT = pathlib.Path(__file__).resolve().parent.parent


class _Daemon:
    """Records argv; every docker call succeeds."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args, timeout=None):
        self.calls.append(list(args))
        if args[:2] == ["docker", "inspect"]:
            return 1, "No such object"
        return 0, ""

    def run_cmd(self) -> list[str]:
        return next(a for a in self.calls if a[:2] == ["docker", "run"])


@pytest.fixture
def daemon(monkeypatch):
    import openfactory.adapters.sandbox.container as mod

    d = _Daemon()
    monkeypatch.setattr(mod, "_host", d)
    return d


# ── the worktree box: it IS the host ────────────────────────────────────────────────────────────

def test_the_worktree_box_answers_with_the_host_path(tmp_path: pathlib.Path):
    box = WorktreeSandbox(root=tmp_path / "wt")
    assert box.guidelines_path(tmp_path) == str(tmp_path.resolve())


def test_the_worktree_box_resolves_a_symlinked_spelling(tmp_path: pathlib.Path):
    """The agent opens a path; two spellings of one directory must not read as two directories."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    box = WorktreeSandbox(root=tmp_path / "wt")
    assert box.guidelines_path(link) == str(real.resolve())


# ── the container box: mounted, read-only, and named by its mount ───────────────────────────────

def test_a_container_told_about_the_directory_mounts_it_READ_ONLY(daemon, tmp_path):
    box = ContainerSandbox(image="img", project="acme", guidelines=str(tmp_path))
    box.prepare(repo_path=ROOT, base_branch="main", branch="openfactory/1")

    cmd = daemon.run_cmd()
    assert f"{tmp_path}:{GUIDELINES_MOUNT}:ro" in cmd, cmd
    # read-only is the claim, so the bare form must NOT be what was passed
    assert f"{tmp_path}:{GUIDELINES_MOUNT}" not in cmd


def test_a_container_told_about_the_directory_answers_with_the_mount(tmp_path):
    box = ContainerSandbox(image="img", guidelines=str(tmp_path))
    assert box.guidelines_path(tmp_path) == GUIDELINES_MOUNT


def test_a_container_that_mounted_NOTHING_answers_None(daemon, tmp_path):
    """The deployment configured a directory and this box was built without it — so the agent
    cannot open those documents, and saying a mount point would be a lie the index acts on."""
    box = ContainerSandbox(image="img", project="acme")
    box.prepare(repo_path=ROOT, base_branch="main", branch="openfactory/1")

    assert box.guidelines_path(tmp_path) is None
    assert not any(GUIDELINES_MOUNT in part for part in daemon.run_cmd())


def test_a_container_mounted_with_a_DIFFERENT_directory_answers_None(tmp_path):
    """Asked about a directory it did not mount, the box says no rather than pointing at the one
    it did — the agent would open the wrong organisation's standards and never know."""
    other = tmp_path / "other"
    other.mkdir()
    box = ContainerSandbox(image="img", guidelines=str(tmp_path / "mounted"))
    assert box.guidelines_path(other) is None


def test_the_registry_passes_the_knob_by_name():
    """`build_sandbox(..., guidelines=…)` must reach the box: an unknown key is a TypeError at
    construction here, which is the whole reason that registry passes knobs by name."""
    from openfactory.adapters.sandbox.registry import build_sandbox

    box = build_sandbox("container", image="img", guidelines="/srv/standards")
    assert box.guidelines_path(pathlib.Path("/srv/standards")) == GUIDELINES_MOUNT


# ── what the caller does with the answer ────────────────────────────────────────────────────────

def _tier_with_a_reference(tmp_path: pathlib.Path) -> og.OperatorTier:
    ref = tmp_path / "reference"
    ref.mkdir(parents=True)
    (ref / "big.md").write_text("# Big")
    return og.gather(env={og.ENV_VAR: str(tmp_path)})


def test_readable_root_asks_the_box(tmp_path: pathlib.Path):
    tier = _tier_with_a_reference(tmp_path)
    assert tier.reference_docs, "fixture should produce a reference tier"
    assert og.readable_root(WorktreeSandbox(root=tmp_path / "wt"), tier) == str(tmp_path.resolve())


def test_a_box_that_never_heard_of_the_capability_answers_None(tmp_path: pathlib.Path):
    """An add-on box written before this existed must not fail a contract check — it simply says
    nothing, and its jobs index no document they cannot open."""

    class _Stranger:
        pass

    assert og.readable_root(_Stranger(), _tier_with_a_reference(tmp_path)) is None


def test_a_box_that_RAISES_degrades_rather_than_failing_the_job(tmp_path: pathlib.Path, caplog):
    class _Angry:
        def guidelines_path(self, host_dir):
            raise RuntimeError("the daemon is not there")

    with caplog.at_level("WARNING"):
        assert og.readable_root(_Angry(), _tier_with_a_reference(tmp_path)) is None
    assert "not indexed" in caplog.text


def test_nothing_is_asked_when_there_is_no_reference_tier(tmp_path: pathlib.Path):
    """No documents, no question: a box is not consulted about an empty tier."""
    (tmp_path / "top.md").write_text("# Inlined, not indexed")
    tier = og.gather(env={og.ENV_VAR: str(tmp_path)})

    class _Counting:
        asked = 0

        def guidelines_path(self, host_dir):
            type(self).asked += 1
            return "/somewhere"

    assert og.readable_root(_Counting(), tier) is None
    assert _Counting.asked == 0


# ── and the compose stack hands the worker the same directory, at the same path ─────────────────

def test_compose_binds_the_guidelines_directory_READ_ONLY_at_the_same_path():
    """The worker READS those documents and the box MOUNTS the same directory — and the daemon
    resolves the box's `-v` by the HOST's path, so source and target have to be identical. This is
    the work directory's rule, applied to the second directory that crosses the same boundary; an
    operator who sets the variable and gets no mount sees the "no such directory" warning with
    nothing saying why (review of #328)."""
    import re

    import yaml

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    worker = compose["services"]["worker"]
    bind = next(v for v in worker["volumes"] if "OPENFACTORY_GUIDELINES_DIR" in v)

    assert bind.endswith(":ro"), f"{bind!r} is writable — one job would edit the next job's rules"
    source, target = bind[: -len(":ro")].split("}:", 1)
    assert source + "}" == target, f"{source + '}'!r} is mounted at {target!r}"
    # the worker is TOLD the same variable, or it reads a directory nothing mounted
    assert "OPENFACTORY_GUIDELINES_DIR" in worker["environment"]
    # …and with nothing set it still resolves to an absolute path, so the stack boots
    # `${HOME}` first: the outer default CONTAINS it, so resolving the outer one first would
    # stop at the inner `}` — the same nested-default trap `test_the_oss_distribution` records.
    resolved = re.sub(r"\$\{OPENFACTORY_GUIDELINES_DIR:-(.*)\}$", r"\1",
                      target.replace("${HOME}", "/home/someone"))
    assert resolved.startswith("/") and "~" not in resolved, resolved
