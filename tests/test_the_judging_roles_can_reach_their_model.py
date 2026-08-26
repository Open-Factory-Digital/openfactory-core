"""A Bedrock deployment's judging roles keep their credential (C-38, #81).

THE COLLISION. `WorktreeSandbox._scrubbed_env` strips every AWS variable from the workload's
environment, and it is right to: a Fargate task inherits the ECS task role, and an agent holding
that role can reach OUR infrastructure. But when the harness authenticates THROUGH a cloud —
Claude via the client's own Bedrock account, which is the first enterprise client's exact shape —
the variables it needs to reach the MODEL are the same ones being stripped to keep it away from
the INFRASTRUCTURE.

The container box had already solved this: `box.env` names what passes through. The worktree had
no such seam. And the split is not academic, because the two sandboxes divide the roles:

    executor, reviewer          ContainerSandbox   →  box.env passes the names  →  worked
    sizer, tech-lead chat,      WorktreeSandbox    →  everything AWS stripped   →  no credential
    diagnosis, product module

So on a Bedrock deployment the code would get written and reviewed while the tech-lead answered
"could not answer" to every question and the size gate silently degraded — the failure this
codebase keeps finding, on the path of the client it was being made ready for.

These tests are mostly REACHABILITY. Proving `_scrubbed_env(keep=…)` honours its argument is easy
and proves nothing on its own: that function was never the thing that was broken. What matters is
that all four judging call sites hand it the project's declaration.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from openfactory.adapters.sandbox.registry import judging_worktree
from openfactory.adapters.sandbox.worktree import _scrubbed_env
from openfactory.contracts.project import Project

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _project(env=None) -> Project:
    return Project(name="p", repo_path="/tmp/p",
                   box={"image": "python:3.12", "env": list(env or [])})


# ── the scrub still scrubs ────────────────────────────────────────────────────────────────────────

def test_an_undeclared_deployment_is_scrubbed_exactly_as_before(monkeypatch):
    """Every deployment running today declares nothing. The security property must not move."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "/v2/creds")
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("OPENFACTORY_AGENT_TOKENS", "x")

    env = _scrubbed_env()
    for var in ("AWS_ACCESS_KEY_ID", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "GH_TOKEN",
                "OPENFACTORY_AGENT_TOKENS"):
        assert var not in env, var


def test_declaring_a_model_credential_lets_exactly_that_one_through(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "y")
    monkeypatch.setenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "/v2/creds")

    env = _scrubbed_env(("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"))
    assert env["AWS_ACCESS_KEY_ID"] == "x"
    assert env["AWS_SECRET_ACCESS_KEY"] == "y"
    # the AMBIENT task identity is a different thing and was not declared
    assert "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI" not in env


def test_declaring_a_harness_credential_does_not_hand_over_the_forge(monkeypatch):
    """The axes are independent: naming what the model needs must not widen what the agent can
    push with. Version control is the pipeline's job, not the agent's."""
    monkeypatch.setenv("AWS_REGION", "eu-west-2")
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("OPENFACTORY_AGENT_TOKENS", "pool")

    env = _scrubbed_env(("AWS_REGION",))
    assert env["AWS_REGION"] == "eu-west-2"
    assert "GH_TOKEN" not in env and "OPENFACTORY_AGENT_TOKENS" not in env


def test_a_name_that_is_not_a_name_is_refused():
    """It reaches an environment. The container validates identically, and the two must not
    disagree — a project that works in the box and is rejected here is the worse failure."""
    from openfactory.adapters.sandbox import WorktreeSandbox

    for bad in ("AWS_KEY=leak", "A B", "", "AWS-KEY"):
        with pytest.raises(ValueError):
            WorktreeSandbox(root=ROOT / ".openfactory-worktrees", extra_env=(bad,))


def test_the_two_boxes_agree_on_what_a_NAME_is():
    from openfactory.adapters.sandbox import ContainerSandbox, WorktreeSandbox

    good = ("AWS_REGION", "_X", "A1")
    ContainerSandbox(image="i", extra_env=good)
    WorktreeSandbox(root=ROOT / ".openfactory-worktrees", extra_env=good)  # neither raises


# ── the helper carries the project's declaration ─────────────────────────────────────────────────

def test_the_judging_sandbox_carries_what_the_project_declared():
    box = judging_worktree(_project(["AWS_REGION", "CLAUDE_CODE_USE_BEDROCK"]), root=ROOT / ".x")
    assert box.extra_env == ("AWS_REGION", "CLAUDE_CODE_USE_BEDROCK")


def test_a_project_with_no_box_block_declares_nothing():
    """The pilot case, and every deployment today."""
    assert judging_worktree(Project(name="p", repo_path="/tmp/p"), root=ROOT / ".x").extra_env == ()
    assert judging_worktree(None, root=ROOT / ".x").extra_env == ()


def test_the_worktree_BUILDER_forwards_it_too():
    """`factory.py` forwards `box.env` for every box. A worktree that dropped it would honour the
    declaration in one sandbox and silently ignore it in the other."""
    from openfactory.adapters.sandbox.registry import build_sandbox

    box = build_sandbox("worktree", root=str(ROOT / ".x"), extra_env=("AWS_REGION",))
    assert box.extra_env == ("AWS_REGION",)


# ── THE GUARD: every judging role actually asks for it ───────────────────────────────────────────

#: Where a judging role builds its own host sandbox. Each of these ran the harness with every AWS
#: variable stripped, so each is a place a Bedrock deployment lost its tech-lead.
JUDGING_SITES = [
    "openfactory/techlead/conversation.py",   # the chat in the panel
    "openfactory/techlead/diagnosis.py",      # impediment diagnosis
    "openfactory/runtime/temporal/activities.py",  # the sizer, and the coordinator's advice
    "openfactory/product/module.py",          # the product role, all of it
]


@pytest.mark.parametrize("rel", JUDGING_SITES)
def test_no_judging_role_builds_a_bare_worktree(rel):
    """AST, not substring: the docstrings in these files legitimately discuss `WorktreeSandbox`
    while explaining why it must not be constructed directly."""
    offenders = []
    for node in ast.walk(ast.parse((ROOT / rel).read_text())):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
        if name == "WorktreeSandbox":
            offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], (
        "a judging role builds its own worktree, so it scrubs the harness credential a Bedrock "
        f"deployment declared: {offenders}"
    )


@pytest.mark.parametrize("rel", JUDGING_SITES)
def test_each_judging_role_reaches_the_shared_helper(rel):
    assert "judging_worktree" in (ROOT / rel).read_text(), rel


def test_the_tech_lead_chat_really_passes_the_project():
    """The end of the chain for the surface a human watches: not "the helper works" but "the chat
    hands it this project". `judging_worktree(root=…)` with no project would satisfy every other
    test in this file and still ship a credential-less tech-lead."""
    import openfactory.techlead.conversation as conv

    tree = ast.parse(inspect.getsource(conv))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "judging_worktree"]
    assert calls, "the chat no longer builds its sandbox through the helper"
    for call in calls:
        assert any(isinstance(a, ast.Name) and a.id == "project" for a in call.args), \
            "a judging sandbox is built without telling it which project"


# ── the warning must not contradict the code ─────────────────────────────────────────────────────

def test_a_worktree_does_not_warn_that_the_credential_is_IGNORED(caplog):
    """`extra_env` was container-only, so `_warn_unhonoured_knobs` named it whenever the box could
    not honour an image. When the worktree learned it, the warning kept firing — telling an
    operator their Bedrock credential was "IGNORED" at the moment it was being passed."""
    import logging

    from openfactory.factory import _warn_unhonoured_knobs

    with caplog.at_level(logging.WARNING, logger="openfactory.factory"):
        _warn_unhonoured_knobs(_project(["AWS_REGION"]), "worktree", {"extra_env": ("AWS_REGION",)})
    assert caplog.text == "", caplog.text


def test_a_knob_the_worktree_REALLY_cannot_apply_is_still_reported(caplog):
    """The positive twin: silencing the false alarm must not silence the true one. A `network:`
    nobody applies means an egress restriction somebody believes is in place is not."""
    import logging

    from openfactory.factory import _warn_unhonoured_knobs

    with caplog.at_level(logging.WARNING, logger="openfactory.factory"):
        _warn_unhonoured_knobs(_project([]), "worktree",
                               {"network": "none", "extra_env": ("AWS_REGION",)})
    assert "`network`" in caplog.text
    assert "extra_env" not in caplog.text  # named alongside, it would read as ignored too
