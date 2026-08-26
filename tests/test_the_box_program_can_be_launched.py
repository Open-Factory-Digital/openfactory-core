"""The command that starts a box named a module that does not exist.

    command = ["python", "-m", "openfactory.runtime.fargate.entrypoint"]     # sandbox_task.tf
    CMD     ["python", "-m", "openfactory.runtime.fargate.entrypoint"]       # sandbox.Dockerfile

`runtime/fargate/entrypoint.py` moved to `runtime/boxed_job.py` — deliberately, and with a long
docstring explaining that the box program touches no cloud. The two places that LAUNCH it were not
moved with it, so `python -m` exited 1 before the container ran a line of the platform and no
Fargate job could start at all.

Nothing could see it: the Python suite never reads terraform, and terraform never imports Python.
Found by an adversarial review asking whether a fix to the box's credential resolution closed
anything — and the honest answer was that nothing could launch the box to find out.
"""

from __future__ import annotations

import importlib
import importlib.util
import re
from pathlib import Path

import add_ons
import pytest

ROOT = Path(__file__).parent.parent
LAUNCHERS = {
    "infra/terraform/sandbox_task.tf": r'command\s*=\s*\[([^\]]*)\]',
    "docker/sandbox.Dockerfile": r'^CMD\s*\[([^\]]*)\]',
}


def _modules_named(text: str, pattern: str) -> list[str]:
    """Every `python -m <module>` in a launch command, as the file spells it."""
    out: list[str] = []
    for match in re.finditer(pattern, text, re.M):
        parts = [p.strip().strip('"').strip("'") for p in match.group(1).split(",")]
        if "-m" in parts:
            out.append(parts[parts.index("-m") + 1])
    return out


@pytest.mark.parametrize("where,pattern", sorted(LAUNCHERS.items()))
def test_every_launch_command_names_a_module_that_EXISTS(where, pattern):
    named = _modules_named(add_ons.source(where).read_text(), pattern)

    assert named, f"{where} no longer launches anything with `python -m` — this guard is blind now"
    for module in named:
        assert importlib.util.find_spec(module) is not None, (
            f"{where} starts the box with `python -m {module}` and no such module exists — the "
            f"container exits 1 before the platform runs")


@pytest.mark.parametrize("where,pattern", sorted(LAUNCHERS.items()))
def test_and_that_module_is_RUNNABLE_as_a_program(where, pattern):
    """`find_spec` is satisfied by a package with no `__main__`. `python -m` is not."""
    for module in _modules_named(add_ons.source(where).read_text(), pattern):
        mod = importlib.import_module(module)
        source = Path(mod.__file__).read_text()
        assert '__name__ == "__main__"' in source, (
            f"`python -m {module}` imports and then does nothing — the box would exit 0 having "
            f"run no job")


def test_the_two_launchers_agree_with_each_other():
    """A task definition and an image CMD that disagree is a box that behaves differently
    depending on which one wins, which is decided by the cloud rather than by this repository."""
    said = {where: _modules_named(add_ons.source(where).read_text(), pattern)
            for where, pattern in LAUNCHERS.items()}

    assert len({tuple(v) for v in said.values()}) == 1, f"the launchers disagree: {said}"


def test_the_guard_can_SEE_a_dead_module(tmp_path):
    """Verify the verifier: fed the exact line that was live in the tree."""
    dead = 'command = ["python", "-m", "openfactory.runtime.fargate.entrypoint"]'

    named = _modules_named(dead, LAUNCHERS["infra/terraform/sandbox_task.tf"])

    assert named == ["openfactory.runtime.fargate.entrypoint"]
    try:
        spec = importlib.util.find_spec(named[0])
    except ModuleNotFoundError:
        # the whole `runtime.fargate` package is absent — the public tree, where the cloud box
        # left with its package (docs/STATUS.md); a module under a missing package is dead too
        spec = None
    assert spec is None, "the module this card is about exists again — the guard is measuring nothing"


# `infra/terraform/terraform.tfstate` also names `fargate.entrypoint`, under the pre-rename
# `sdlc.` package. It is NOT asserted here and must not be: state records what is deployed, so it
# is expected to lag the source until the next apply — asserting on it would fail this suite for
# the correct reason and give somebody a red test they can only fix by deploying.
