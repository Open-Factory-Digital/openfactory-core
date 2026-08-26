"""`openfactory/onboarding/context.py` is reachable by a human. Asserted, because it was not.

THE SIGNATURE DEFECT OF THIS REPOSITORY, occurrence twenty-one. The module was written, tested and
merged with 1,800 lines and its own author measured the truth in the handover:

    grep -rn "onboarding.context|propose_context" --include=*.py sdlc/  →  zero hits outside the
    module itself. By this repository's own rule this capability DOES NOT EXIST for a user yet.

Green tests over dead code is the failure mode this file exists to make impossible, and behaviour
tests cannot see it: every one of them imports the module directly, which is exactly what no door
did. So the assertions here are about REACH — a CLI command a tech-lead can type in front of a
client, and a catalogue row the panel and the API dispatch generically.

EACH GUARD HAS A POSITIVE TWIN, because "nothing reaches X" and "X reaches nothing" are both
absence-shaped claims, and absence reads as compliance: a scanner that quietly stopped matching
would report a clean tree either way.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

def _names_called_in(path: str, func: str) -> set[str]:
    """Every attribute and bare name CALLED inside one function — `ctx.survey(...)` → `survey`."""
    tree = ast.parse((ROOT / path).read_text())
    node = next((n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func),
                None)
    assert node is not None, f"{func} vanished from {path} — this guard now guards nothing"
    out: set[str] = set()
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        if isinstance(call.func, ast.Attribute):
            out.add(call.func.attr)
        elif isinstance(call.func, ast.Name):
            out.add(call.func.id)
    return out


def test_a_human_can_type_the_command():
    """The CLI is the door that matters here: onboarding happens in a terminal, beside the
    client's developers, and a capability only the API can reach is one nobody demonstrates."""
    from typer.testing import CliRunner

    from openfactory.cli import app

    result = CliRunner().invoke(app, ["env", "context", "--help"])
    assert result.exit_code == 0, result.output
    # ANSI-STRIPPED BEFORE MATCHING, and this cost a full debug round the first time it happened
    # in this repository: typer styles the flag as `ESC[1;36m-ESC[0mESC[1;36m-askESC[0m`, so a
    # plain `"--ask" in output` reports the flag missing on a CLI that has it.
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "--ask" in plain and "--write" in plain, (
        "`sdlc env context` lost its two halves — the semantic pass and the write — and what is "
        f"left proposes documents nobody can act on:\n{result.output}"
    )


def test_the_command_is_a_mapping_and_nothing_more():
    """It calls the ACTION, and it does not reach the module itself.

    `openfactory/actions/__init__.py`'s table is the rule: a front end that does the work is a second
    implementation, and the two drift without either side noticing. The first draft of this command
    surveyed and proposed inline — which worked, and put the decision of when an agent runs in two
    places at once.
    """
    called = _names_called_in("openfactory/cli.py", "env_context_cmd")
    assert "_perform" in called, f"the command does not reach the action layer: {sorted(called)}"
    trespass = {"survey", "propose_context", "write_documents", "agent_ask"} & called
    assert not trespass, (
        f"`sdlc env context` calls {sorted(trespass)} itself — that belongs to the `env_context` "
        f"action, and a second copy here is how the panel and the terminal come to disagree"
    )


def test_the_semantic_pass_is_wired_to_a_harness():
    """`--ask` without `agent_ask` is a flag that spends nothing and proposes nothing.

    Named separately from the reach test because this is the half that costs money and the half a
    client is told about: an `--ask` that silently ran the deterministic path would be a promise
    the output cannot keep.
    """
    called = _names_called_in("openfactory/actions/catalog.py", "_semantic_pass")
    assert "agent_ask" in called and "build_asker" in called, (
        "`ask` does not bind a harness into the proposal — it calls: " + str(sorted(called))
    )
    assert "which" in called, (
        "the pass no longer checks that the harness is INSTALLED on the machine being asked — the "
        "panel would start an agent it has no binary for and report a model failure"
    )


def test_the_remote_transports_can_reach_it_too():
    """One row in the catalogue is what gives the panel, the API and `sdlc act` this capability.

    They dispatch generically over `CATALOG`, so a row is the whole integration — and its absence
    is invisible, because a missing row does not fail, it simply never appears on the screen.
    """
    from openfactory import actions

    assert "env_context" in actions.CATALOG, (
        "no `env_context` action — `POST /api/act/env_context`, `sdlc act env_context` and the "
        f"panel's action list all lose the capability. The catalogue has: {sorted(actions.CATALOG)}"
    )
    spec = actions.CATALOG["env_context"]
    assert spec.required == ("target",), spec.required
    assert set(spec.optional) == {"ask", "write", "yes"}, (
        f"the row lost a parameter the CLI passes: {spec.optional}. `perform` rejects an unknown "
        f"one, so a dropped name is a command that fails on its own flag"
    )
    assert not spec.needs_admin, (
        "reading somebody's repository and proposing documents is a QUESTION, and a question is "
        "not authority — `env_read` beside it takes the same position"
    )


def test_the_action_proposes_and_writes_nothing(tmp_path):
    """The whole verb, end to end, on a real repository — and the filesystem is checked after.

    `write_documents` is one import away inside the same module; a row that reached for it would
    put files in a client's repository as a side effect of being asked a question.
    """
    import asyncio

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "cobranca.py").write_text('"""Cobrança de mensalidades."""\n\n\ndef go():\n    return 1\n')
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    before = {p for p in tmp_path.rglob("*")}

    from openfactory import actions
    from openfactory.actions.base import Actor

    outcome = asyncio.run(actions.perform("env_context", target=str(tmp_path),
                                          by=Actor(id="t", display="t", admin=True)))
    assert outcome.ok, f"{outcome.code}: {outcome.message}"
    assert outcome.data.get("semantic") is False, (
        "the panel has no harness, so the action must SAY the semantic layer is absent rather "
        "than let a reader assume the deterministic survey is the whole answer"
    )
    assert "report" in outcome.data and outcome.data["report"].strip()
    assert {p for p in tmp_path.rglob("*")} == before, (
        "`env_context` wrote into the repository it was asked to read"
    )


def test_the_semantic_pass_is_refused_where_the_harness_is_not_installed(monkeypatch):
    """`ask` on a machine with no harness binary must REFUSE, before the walk, naming the machine.

    Not a quiet no-op: a transport that accepted the flag and returned the deterministic survey
    would present it as though a model had been consulted. And not a slow failure either — the
    panel's image has no coding agent in it, so starting the pass there costs a hung HTTP request
    and then reports a MODEL failure, which is a claim about the model and not about us.
    """
    import asyncio
    import shutil
    import tempfile

    from openfactory import actions
    from openfactory.actions.base import Actor

    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    with tempfile.TemporaryDirectory() as tmp:
        outcome = asyncio.run(actions.perform("env_context", target=tmp, ask="1",
                                              by=Actor(id="t", display="t", admin=True)))
    assert not outcome.ok, "the action claimed to have run an agent pass with no harness installed"
    assert outcome.code == "unavailable", outcome.code
    assert "env context" in outcome.message and "--ask" in outcome.message, (
        f"the refusal does not say where the pass CAN be run: {outcome.message!r}"
    )


def test_the_semantic_pass_is_NOT_refused_where_the_harness_IS_installed(monkeypatch, tmp_path):
    """The positive twin, and the one that matters: a check that always refused would pass the
    test above while making `--ask` impossible everywhere.

    The harness is faked at the last seam — the bound `ask` callable — so this exercises the real
    resolution (`build_asker`, the sandbox, the workspace) and spends nothing.

    IT STILL NEEDS THE BINARY ITSELF, and that is the one thing a fake cannot supply: the seam
    below is downstream of `_semantic_pass`'s `shutil.which(binary)`, which runs first and raises.
    So the harness is an OPTIONAL EXTERNAL THING here and this skips when it is absent, naming it.
    """
    import asyncio
    import shutil

    from openfactory import actions
    from openfactory.actions.base import Actor
    from openfactory.adapters.agent.registry import harness_binary, harness_kind
    from openfactory.onboarding import context as ctx

    # MEASURED 2026-08-21 on a fresh `ubuntu-latest` runner with no coding harness installed: this
    # failed with `AssertionError: unavailable: the semantic pass needs the claude_code harness and
    # 'claude' is not on this process's PATH.` — the action's own refusal, arriving as a red test
    # because the author's laptop has `claude` at ~/.local/bin and CI has nothing.
    #
    # DERIVED, NOT SPELLED `claude`. `repo_for` answers `project=None` for a path target, so
    # `_semantic_pass` resolves `harness_kind(None, "techlead")` — exactly this line. Hardcoding
    # the binary would skip for a harness this deployment does not use the moment `DEFAULT_KIND`
    # or `OPENFACTORY_HARNESS_TECHLEAD` moves, which is a test going dark for a reason nobody said.
    #
    # THE REFUSAL BRANCH NEVER GOES DARK WITH IT: the negative twin above fakes `shutil.which` to
    # None, needs no binary, and runs on every machine. What is gated here is only the half that
    # cannot be faked — so "the check is not unconditional" is still asserted wherever a harness is
    # installed, and CI says which one it wanted instead of vanishing.
    binary = harness_binary(harness_kind(None, "techlead"))
    if shutil.which(binary) is None:
        pytest.skip(f"{binary!r} is not on PATH — `env context --ask` resolves its harness before "
                    f"the seam this test fakes, so there is nothing to exercise here. Install the "
                    f"harness and this test runs and asserts.")

    (tmp_path / "cobranca.py").write_text('"""Cobrança."""\n\n\ndef go():\n    return 1\n')
    monkeypatch.setattr(ctx, "agent_ask", lambda *_a, **_k: (
        lambda _prompt: '{"does": [{"text": "cobra mensalidades", "cites": ["cobranca.py:1"]}]}'))

    outcome = asyncio.run(actions.perform("env_context", target=str(tmp_path), ask="1",
                                          by=Actor(id="t", display="t", admin=True)))
    assert outcome.ok, f"{outcome.code}: {outcome.message}"
    assert outcome.data.get("semantic") is True and outcome.data.get("asked") == 1, outcome.data
    assert "cobra mensalidades" in outcome.data["report"], outcome.data["report"]


def test_build_asker_answers_with_something_ask_can_be_called_on():
    """The reason `build_asker` exists at all, stated as a test rather than as a docstring.

    `agent_ask` needs the read-only primitive itself. `build_techlead` returns `HarnessTechLead`
    on every harness without native tech-lead methods, and that wrapper exposes `_ask` — so
    `can_judge` answers False and `--ask` would refuse on exactly the harnesses the generic path
    exists to serve. Checked on `codex`, which is one of them.
    """
    from openfactory.adapters.agent import build_asker, build_techlead
    from openfactory.adapters.agent.roles import can_judge

    class _P:
        name = "t"
        harness = "codex"

    assert can_judge(build_asker(_P())), (
        "`build_asker` returned something with no `ask()` — `env context --ask` cannot bind it"
    )
    # THE POSITIVE TWIN, and the defect this function was written for. If this ever starts
    # passing, `build_asker` has become redundant and should go — but until then, deleting it and
    # using `build_techlead` would break `--ask` on three of the four harnesses.
    assert not can_judge(build_techlead(_P())), (
        "`build_techlead` now exposes `ask()` on a wrapped harness — re-read whether `build_asker` "
        "still earns its place"
    )


@pytest.mark.parametrize("role", ["techlead", "product", "reviewer", "executor"])
def test_build_asker_resolves_the_role_it_was_asked_for(role):
    """The other half of the same argument: `build_product` HAS `ask`, so it was the tempting
    shortcut — and it would have resolved the product role's harness and model on a deployment
    that pointed that role at a cheaper engine."""
    from openfactory.adapters.agent import build_asker

    class _P:
        name = "t"
        harness = {"techlead": "codex", "product": "kimi", "reviewer": "opencode",
                   "executor": "claude_code"}

    if role == "executor":  # no `ask()` on this axis by contract — it writes, it does not judge
        pytest.skip("the executor is not a judging role")
    agent = build_asker(_P(), role=role)
    expected = _P.harness[role]
    assert type(agent).__module__.endswith(expected), (
        f"asked for the {role} harness ({expected}) and got {type(agent).__module__}"
    )
