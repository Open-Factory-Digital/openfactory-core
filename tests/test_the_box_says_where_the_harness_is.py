"""The harness is invoked by a path the BOX chooses, never by a bare name (ADR-0037 D2).

All three adapters built their command line the same way:

    cmd = ["claude", "-p", ...]          claude_code.py:423
    cmd = ["codex", "exec"]              codex.py:145
    cmd = ["kimi", "--auto", ...]        kimi.py:130

A bare name is resolved by `PATH` inside the box, and under ADR-0037 D1 that box is built from the
CLIENT's image. Debian's and Alpine's stock `/etc/profile` assign `PATH` unconditionally, so a
toolbox mounted by the framework and announced through `PATH` is discarded by an ordinary,
entirely benign base image — the harness is simply not found. No malice required; it is what those
files do.

WHY THE SANDBOX ANSWERS AND NOT THE ADAPTER. `AgentAdapter.execute(sandbox=, workspace=, context=)`
already receives the box, so the question costs no plumbing — and the knowledge belongs there. A
worktree runs on the host, where the harness is whatever the operator installed and `PATH` is
correct; a container mounts a framework-owned toolbox at a fixed point and must say so absolutely.
The adapter should know neither fact. Asking the box also means a THIRD box — an SSH runner, a
remote VM — answers the question when it joins, instead of the adapters growing a branch each.

This lands before the toolbox itself is built, deliberately. The seam is what makes the mount safe
to add: with the adapters still emitting bare names, mounting a toolbox would work on some images
and silently not on others, which is the worst of the three possible states.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _registered() -> list[str]:
    from openfactory.adapters.agent.registry import HARNESSES

    return sorted(HARNESSES)


# DERIVED FROM THE REGISTRY, not listed by hand. Both of these were hardcoded triples, so a fourth
# harness could join `HARNESSES` — and be invoked in real jobs — while remaining invisible to the
# guard whose entire job is to keep harness invocation honest. The list this protects is exactly
# the list of harnesses that exist, or it protects the wrong thing.
HARNESS_BINARIES = tuple(__import__(
    "openfactory.adapters.agent.registry", fromlist=["harness_binary"]).harness_binary(k)
    for k in _registered())
ADAPTERS = [f"openfactory/adapters/agent/{k}.py" for k in _registered()]


def test_every_registered_harness_has_an_adapter_module_named_after_it():
    """The guard below finds adapters by convention, so the convention has to hold — otherwise a
    missing file makes the check pass by having nothing to read."""
    missing = [p for p in ADAPTERS if not (ROOT / p).exists()]
    assert missing == [], f"registered but no module: {missing}"


# ── the port ────────────────────────────────────────────────────────────────────────────────────

def test_the_sandbox_port_declares_harness_path():
    from openfactory.adapters.sandbox.base import SandboxAdapter

    assert hasattr(SandboxAdapter, "harness_path")


def test_a_worktree_answers_with_the_bare_name():
    """On the host the operator installed the harness and `PATH` is theirs to own. Returning an
    absolute path here would break every local run and every test."""
    from openfactory.adapters.sandbox import WorktreeSandbox

    box = WorktreeSandbox(root=ROOT / ".openfactory-worktrees")
    assert box.harness_path("claude") == "claude"


def test_a_container_answers_with_an_absolute_toolbox_path():
    from openfactory.adapters.sandbox.container import TOOLBOX_MOUNT, ContainerSandbox

    box = ContainerSandbox(image="mycorp/ci:1")
    path = box.harness_path("claude")

    assert path.startswith("/"), path
    assert path == f"{TOOLBOX_MOUNT}/claude"


def test_the_mount_point_is_the_framework_s_own_directory():
    """It is grafted into an image the framework does not control, so it must not collide with
    anything a client might reasonably have."""
    from openfactory.adapters.sandbox.container import TOOLBOX_MOUNT

    assert TOOLBOX_MOUNT.startswith("/opt/"), TOOLBOX_MOUNT
    assert "openfactory" in TOOLBOX_MOUNT


@pytest.mark.parametrize("name", ["claude/../../bin/sh", "../etc/passwd", "cl aude", ""])
def test_a_harness_name_that_is_not_a_bare_name_is_refused(name):
    """The name reaches an absolute path that is then executed. It comes from configuration today,
    but `harness:` is a registry string and the cost of being wrong here is arbitrary execution —
    so it is validated where it is used rather than trusted from where it came."""
    from openfactory.adapters.sandbox.container import ContainerSandbox

    with pytest.raises(ValueError):
        ContainerSandbox(image="img").harness_path(name)


# ── the adapters must ask ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", ADAPTERS)
def test_no_adapter_emits_a_bare_harness_name(rel):
    """The guard, in the positive-twin shape: not "nothing is wrong here" but "the command starts
    with something the box gave us"."""
    offenders: list[str] = []
    for node in ast.walk(ast.parse((ROOT / rel).read_text())):
        if not isinstance(node, ast.List) or not node.elts:
            continue
        # ANY element, not just the first. It checked only `elts[0]`, which silently stopped
        # guarding the moment an adapter put anything before the binary — the OpenCode adapter
        # prefixes `VAR=value` assignments, so `[*env, "opencode", …]` sailed straight through a
        # test whose whole purpose is to catch exactly that string in exactly that position.
        for el in node.elts:
            if isinstance(el, ast.Constant) and el.value in HARNESS_BINARIES:
                offenders.append(f"{rel}:{node.lineno} — cmd contains bare {el.value!r}")
    assert not offenders, (
        "a harness is invoked by bare name, so it depends on PATH inside the client's image:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("rel", ADAPTERS)
def test_every_adapter_asks_the_box(rel):
    assert "harness_path" in (ROOT / rel).read_text(), (
        f"{rel} never asks the sandbox where its harness is"
    )


# ── and the answer must actually be used ────────────────────────────────────────────────────────

class _Box:
    """A box that puts the harness somewhere unmistakable."""

    def harness_path(self, name: str) -> str:
        return f"/opt/openfactory-toolbox/{name}"

    def run(self, *, workspace, command, timeout):
        self.command = command
        return 0, ""


@pytest.mark.parametrize("module,cls,name,kwargs", [
    ("claude_code", "ClaudeCodeAdapter", "claude", {"tools": [], "model": None}),
    ("codex", "CodexAdapter", "codex", {"model": None, "sandbox_mode": "workspace-write"}),
    ("kimi", "KimiAdapter", "kimi", {"model": None, "plan_mode": False}),
])
def test_the_command_starts_with_the_path_the_box_gave_it(module, cls, name, kwargs):
    """Behavioural, at the end of the chain — the assertion my first attempt got wrong by inventing
    a method. What matters is not that `_cli` takes a parameter but that the string finally handed
    to the shell begins with the box's answer."""
    import importlib

    adapter_cls = getattr(importlib.import_module(f"openfactory.adapters.agent.{module}"), cls, None)
    if adapter_cls is None:
        pytest.skip(f"{cls} not present")

    command = adapter_cls()._cli("do the thing", harness=_Box().harness_path(name), **kwargs)

    assert command.startswith(f"/opt/openfactory-toolbox/{name} "), command[:80]


def test_a_real_box_and_a_real_adapter_agree_on_the_path():
    """The two halves were built in the same commit and could still disagree — the container's
    mount point and the adapter's consumption of it are only connected by this test."""
    from openfactory.adapters.agent.claude_code import ClaudeCodeAdapter
    from openfactory.adapters.sandbox.container import ContainerSandbox

    box = ContainerSandbox(image="mycorp/ci:1")
    command = ClaudeCodeAdapter()._cli(
        "x", harness=box.harness_path("claude"), tools=[], model=None
    )

    assert command.startswith("/opt/openfactory-toolbox/claude "), command[:80]
