"""A command that spends money runs in the box the DEPLOYMENT configured, not in a literal.

FOUND BY RUNNING IT, not by reading it. A real ticket was driven through a real `docker compose`
install — the OSS distribution, with no cloud at all — and the log said:

    project 'fx-py-simple' declares box `toolbox`, but this deployment's box is 'worktree'

while the compose file two directories away says, under a comment calling the container "the real,
production path":

    OPENFACTORY_SANDBOX: container

`default_sandbox()` has read that variable since C-13 and its own docstring names this exact
failure — *"a configuration that looks configured and is ignored is this repository's signature
defect"*. The durable path was fixed then. The CLI was not: `run` and `poll` carried
`typer.Option("worktree")`, and `poll` is the command whose own docstring says *"run this on a
cron/loop as the scheduler"*. So on every compose install the agent's arbitrary code ran in the
worker's own filesystem, beside the scheduler that launched it.

AND IT MADE A PROOF POINT AT THE WRONG THING, which is the worse half. `box prove` holds pickup
until the CONTAINER box has run the project's own gates (ADR-0037 D5) — the job then ran in a
worktree. A proof about a box nothing uses is not a weaker proof; it is a statement about
somewhere else, delivered in the voice of one about here.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLI = ROOT / "openfactory/cli.py"


# ── the resolution itself ───────────────────────────────────────────────────────────────────────

def test_the_deployments_box_wins_when_the_flag_is_not_given(monkeypatch):
    from openfactory.cli import _box_kind

    monkeypatch.setenv("OPENFACTORY_SANDBOX", "container")
    assert _box_kind(None) == "container"
    # …and the empty string is "not given" too: typer hands one over for `--sandbox ''`, and a
    # truthiness test that missed it would silently ask the box registry for `""`.
    assert _box_kind("") == "container"
    assert _box_kind("   ") == "container"


def test_an_EXPLICIT_flag_still_wins(monkeypatch):
    """The operator override has to survive, or the fix trades one ignored configuration for
    another — and this is the flag somebody reaches for to debug a box that will not start."""
    from openfactory.cli import _box_kind

    monkeypatch.setenv("OPENFACTORY_SANDBOX", "container")
    assert _box_kind("worktree") == "worktree"
    assert _box_kind("WorkTree") == "worktree", "the box registry keys are lower-case"


def test_with_nothing_configured_it_infers_rather_than_guessing(monkeypatch):
    """`default_sandbox`'s rule, reached through this helper rather than restated: the box the
    deployment DECLARES (`OPENFACTORY_SANDBOX`), else the local container. Never `worktree`, which
    isolates the code state and nothing else — and never a vendor's box inferred from that vendor's
    cluster variable, which is what this used to pin."""
    from openfactory.cli import _box_kind

    monkeypatch.delenv("OPENFACTORY_SANDBOX", raising=False)
    monkeypatch.delenv("OPENFACTORY_FARGATE_CLUSTER", raising=False)
    assert _box_kind(None) == "container"

    monkeypatch.setenv("OPENFACTORY_FARGATE_CLUSTER", "openfactory-cluster")
    assert _box_kind(None) == "container"

    monkeypatch.setenv("OPENFACTORY_SANDBOX", "fargate")
    assert _box_kind(None) == "fargate"


# ── reachability: the resolution has to be what the runner is actually built with ───────────────

def _cli_tree() -> ast.Module:
    return ast.parse(CLI.read_text())


def _commands_building_a_runner() -> dict[str, ast.FunctionDef]:
    """Every top-level function in `cli.py` that constructs a `JobRunner`, DERIVED.

    Named by what they DO rather than by a list of command names: the next command that learns to
    run a ticket is covered on the day it is written, which is the only way this guard survives
    the person who adds it."""
    out = {}
    for node in _cli_tree().body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "build_runner"
               for c in ast.walk(node)):
            out[node.name] = node
    return out


def test_the_scan_finds_the_commands_that_spend_money():
    """The positive twin, first — every assertion below is satisfied by a scan that found
    nothing, and this repository has shipped three guards that were green for exactly that
    reason."""
    found = set(_commands_building_a_runner())

    assert {"run", "poll"} <= found, (
        f"the scan found {sorted(found)} — `run` and `poll` are the two commands that drive a "
        f"ticket through an agent, and a scan that cannot see them proves nothing")


@pytest.mark.parametrize("name", sorted(_commands_building_a_runner()))
def test_no_command_hardcodes_the_box_it_runs_in(name):
    """The defect, structurally. A string default here is a deployment's configuration overruled
    by whoever typed the command first."""
    fn = _commands_building_a_runner()[name]
    literal = [d for arg, d in zip(fn.args.kwonlyargs + fn.args.args[-len(fn.args.defaults or []):]
                                   if fn.args.defaults else fn.args.kwonlyargs,
                                   list(fn.args.kw_defaults or []) + list(fn.args.defaults or []),
                                   strict=False)
               if arg.arg == "sandbox" and d is not None
               and isinstance(d, ast.Call) and any(
                   isinstance(a, ast.Constant) and isinstance(a.value, str) for a in d.args)]

    assert not literal, (
        f"`{name}` defaults its box to a literal, so `OPENFACTORY_SANDBOX` — which the compose file sets "
        f"and the durable path honours — is ignored on the path an operator actually uses")


@pytest.mark.parametrize("name", sorted(_commands_building_a_runner()))
def test_every_command_resolves_its_box_before_building_the_runner(name):
    """The other half, and the one that would have caught the original defect on its own: a
    command may declare the flag correctly and still hand the RAW value to `build_runner`.

    Asserted on the argument the runner is built with, because that is the value that decides
    where an agent's code executes — everything upstream of it is intention."""
    fn = _commands_building_a_runner()[name]
    resolved = {t.id for n in ast.walk(fn) if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name)
                and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "_box_kind"}

    assert resolved, f"`{name}` never calls `_box_kind` — it cannot be honouring OPENFACTORY_SANDBOX"

    for call in [c for c in ast.walk(fn)
                 if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "build_runner"]:
        passed = {k.value.id for k in call.keywords
                  if k.arg == "sandbox" and isinstance(k.value, ast.Name)}
        assert passed <= resolved and passed, (
            f"`{name}` builds a runner with sandbox={sorted(passed) or 'a non-name'} — the "
            f"resolved box is {sorted(resolved)}. The flag was fixed and the value handed to the "
            f"runner was not, which is the same defect wearing the fix")
