"""The model reaches the command line, for every role and every harness (C-38, #81).

THE DEFECT THIS PINS is this codebase's signature one, in its purest form yet. Every adapter had
always accepted `model=`. Every builder in `agent/registry.py` had always forwarded a `model=`
kwarg to those adapters. Both halves had tests. And no caller anywhere ever passed one:

    factory.py:333                 build_executor(project, log_dir=...)
    factory.py:340                 build_reviewer(project)
    techlead/conversation.py:111   build_techlead(project).chat(...)
    product/module.py:460          build_product(self.project)

So the whole feature was reachable only through `OPENFACTORY_EXECUTOR_MODEL`, a process-wide variable
that is one value for every project on the worker and needs an environment change plus a roll to
move. Two per-client decisions had nowhere to live: which PROVIDER serves a client (their own
Bedrock account; an Azure or gateway endpoint) and which TIER they are paying for.

SO THESE TESTS END AT THE COMMAND STRING, not at the resolver. `model_for()` returning the right
value proves nothing on its own — that is precisely the shape the old code already had. The guard
has to be that a `Project` carrying a model produces a CLI invocation carrying that model, through
the real builders, for each harness and each role.
"""

from __future__ import annotations

import pytest

from openfactory import namespace
from openfactory.adapters.agent import registry as harnesses
from openfactory.contracts.project import Project


def _project(**kw) -> Project:
    return Project(name="p", repo_path="/tmp/p", **kw)


def _clear(monkeypatch):
    """Both axes: a leaked env var from another test would silently satisfy these assertions."""
    for var in (*harnesses.ROLES.values(), *harnesses.ROLE_MODELS.values(),
                "OPENFACTORY_PLANNER_MODEL"):
        monkeypatch.delenv(var, raising=False)


class _FakeSandbox:
    """Records the command an adapter builds. Stands in for a WORKTREE, so `harness_path` answers
    with the bare name (see test_agent_harness.py, where this double originates)."""

    def __init__(self, run_out: str = "", last_message: str = "", code: int = 0) -> None:
        self.commands: list[str] = []
        self.run_out, self.last_message, self.code = run_out, last_message, code

    def harness_path(self, name: str) -> str:
        return name

    def run(self, *, workspace, command: str, timeout: int):  # noqa: ARG002
        self.commands.append(command)
        if command.startswith("cat "):
            return 0, self.last_message
        return self.code, self.run_out


def _ws():
    from openfactory.adapters.sandbox.base import Workspace

    return Workspace(path="/work", branch="b", base_branch="main")


def _ctx():
    from openfactory.adapters.agent.base import AgentContext
    from openfactory.contracts import Ticket

    return AgentContext(
        ticket=Ticket(id="#7", title="add health check", objective="expose /health", repo="o/r"),
    )


# ── resolution: the same two shapes as `harness`, so one thing is learned, not two ───────────────

def test_nothing_configured_means_the_harnesss_own_default(monkeypatch):
    """The state every existing deployment is in. It must stay exactly where it was."""
    _clear(monkeypatch)
    assert harnesses.model_for(_project(), "executor") is None
    assert harnesses.model_for(None, "techlead") is None


def test_ONE_LINE_sets_the_model_for_every_role(monkeypatch):
    _clear(monkeypatch)
    p = _project(model="claude-fable-5")
    assert [harnesses.model_for(p, r) for r in harnesses.ROLES] == ["claude-fable-5"] * 4


def test_per_role_lets_the_expensive_model_go_where_it_earns_its_price(monkeypatch):
    """The real shape of the request: a client paying for a frontier model on the code it ships
    does not necessarily want it sizing tickets."""
    _clear(monkeypatch)
    p = _project(model={"executor": "claude-fable-5", "techlead": "claude-haiku-4-5-20251001"})
    assert harnesses.model_for(p, "executor") == "claude-fable-5"
    assert harnesses.model_for(p, "techlead") == "claude-haiku-4-5-20251001"
    assert harnesses.model_for(p, "reviewer") is None  # unset → the harness's default


def test_default_key_covers_the_unlisted_roles(monkeypatch):
    _clear(monkeypatch)
    p = _project(model={"default": "gpt-5", "reviewer": "claude-opus-5"})
    assert harnesses.model_for(p, "executor") == "gpt-5"
    assert harnesses.model_for(p, "reviewer") == "claude-opus-5"


def test_env_overrides_per_role(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENFACTORY_TECHLEAD_MODEL", "cheap-1")
    p = _project(model="claude-fable-5")
    assert harnesses.model_for(p, "techlead") == "cheap-1"
    assert harnesses.model_for(p, "executor") == "claude-fable-5"  # untouched


def test_an_unknown_role_raises_here_too(monkeypatch):
    _clear(monkeypatch)
    with pytest.raises(ValueError, match="unknown role"):
        harnesses.model_for(_project(), "wizard")


def test_every_role_has_an_env_override(monkeypatch):
    """A role present in one table and missing from the other would raise `KeyError` at the first
    resolution — the failure would be a crash in a live job, not a config mistake."""
    assert set(harnesses.ROLE_MODELS) == set(harnesses.ROLES)


# ── THE GUARD: the value reaches the CLI, through the real builders ──────────────────────────────

#: A model string each harness will ACCEPT. OpenCode refuses a bare name at build time — the
#: provider prefix is how it reaches an endpoint at all — so a placeholder that is fine for the
#: others is a configuration error there, and the parametrisation has to respect that.
_MODEL_FOR = {"opencode": "anthropic/chosen-9"}


@pytest.mark.parametrize(("kind", "flag"), [("claude_code", "--model"), ("codex", "-m"),
                                            ("kimi", "-m"), ("opencode", "-m")])
def test_the_executors_model_reaches_the_command_line(monkeypatch, kind, flag):
    """`build_executor` is the call site that dropped it. End at the command, not the object."""
    _clear(monkeypatch)
    chosen = _MODEL_FOR.get(kind, "chosen-9")
    p = _project(harness=kind, model=chosen)
    agent = harnesses.build_executor(p)

    sb = _FakeSandbox(last_message="done", run_out='{"type":"result","result":"done"}')
    agent.execute(sandbox=sb, workspace=_ws(), context=_ctx())

    assert sb.commands, "the adapter never ran a command"
    assert f"{flag} {chosen}" in sb.commands[0], sb.commands[0]


@pytest.mark.parametrize("kind", ["claude_code", "codex", "kimi", "opencode"])
def test_a_judging_roles_model_reaches_the_command_line(monkeypatch, kind):
    """The tech-lead is built through `_judging`, a different path from the executor's — and one
    that never forwarded a model at all, for any harness."""
    _clear(monkeypatch)
    judge = "anthropic/judge-7" if kind == "opencode" else "judge-7"
    p = _project(harness=kind, model={"techlead": judge})
    agent = harnesses._judging(kind, "techlead", p)

    sb = _FakeSandbox(last_message="ok", run_out='{"type":"result","result":"ok"}')
    agent.ask(sandbox=sb, workspace=_ws(), prompt="how bad is it?")

    assert sb.commands, "the adapter never ran a command"
    assert judge in sb.commands[0], sb.commands[0]


def test_the_native_reviewer_carries_the_projects_model(monkeypatch):
    """`build_reviewer` returned `native()` with empty parens: the one role a deployment is most
    likely to want on a different model was the one that could not have it."""
    _clear(monkeypatch)
    rev = harnesses.build_reviewer(_project(model={"reviewer": "second-opinion-3"}))
    assert getattr(rev, "model", None) == "second-opinion-3"


def test_the_product_role_carries_it_too(monkeypatch):
    _clear(monkeypatch)
    agent = harnesses.build_product(_project(harness="codex", model={"product": "po-2"}))
    assert agent.planner_model == "po-2"


# ── the regression side: an unconfigured deployment must not move ────────────────────────────────

@pytest.mark.parametrize("kind", ["claude_code", "codex", "kimi", "opencode"])
def test_no_model_configured_emits_no_model_flag(monkeypatch, kind):
    """Every live deployment today is in this state. A `--model` appearing out of nowhere would
    pin them to whatever string this code invented."""
    _clear(monkeypatch)
    agent = harnesses.build_executor(_project(harness=kind))

    sb = _FakeSandbox(last_message="done", run_out='{"type":"result","result":"done"}')
    agent.execute(sandbox=sb, workspace=_ws(), context=_ctx())

    cmd = sb.commands[0]
    assert "--model" not in cmd and " -m " not in cmd, cmd


def test_the_executors_model_does_not_leak_into_the_planners_slot(monkeypatch):
    """Claude picks its model by PHASE: `planner_model` for every read-only call, `executor_model`
    for the coding ones. Setting the single legacy `model=` fills both — so an executor build
    would silently move the model of the sizer, the reviewer and the tech-lead as well."""
    _clear(monkeypatch)
    agent = harnesses.build_executor(_project(model="coder-1"))
    assert agent.executor_model == "coder-1"
    assert agent.planner_model is None  # the judging paths keep the harness default


def test_a_judging_build_does_not_move_the_executors_model(monkeypatch):
    """The same leak in the other direction."""
    _clear(monkeypatch)
    agent = harnesses._judging("claude_code", "techlead", _project(model="judge-1"))
    assert agent.planner_model == "judge-1"
    assert agent.executor_model is None


def test_the_legacy_env_var_still_wins_exactly_as_it_did(monkeypatch):
    """`OPENFACTORY_EXECUTOR_MODEL` is read INSIDE the adapters too. Resolving it here as well must
    produce the same value, not a second answer that disagrees with the first."""
    _clear(monkeypatch)
    monkeypatch.setenv("OPENFACTORY_EXECUTOR_MODEL", "from-env")
    agent = harnesses.build_executor(_project(harness="codex", model="from-registry"))
    assert agent.model == "from-env"


# ── the review is an agent pass, and costs like one (C-38) ───────────────────────────────────────

def test_a_review_can_CARRY_its_cost():
    """The shape could not express it, so nothing could count it — no prompt and no model fixes a
    field that does not exist."""
    from openfactory.contracts import ReviewResult

    r = ReviewResult(decision="approved", score=90, cost_usd=0.12, num_turns=3,
                     input_tokens=10, output_tokens=20, model="m", harness="h")
    assert r.cost_usd == 0.12 and r.harness == "h"


def test_unknown_review_cost_stays_UNKNOWN():
    """A harness that reports tokens but no price must not read as free — it would win every cost
    comparison, which is the inverse of what the telemetry exists to do."""
    from openfactory.contracts import ReviewResult

    assert ReviewResult(decision="approved", score=90).cost_usd is None


def test_BOTH_review_call_sites_count_it():
    """The second one is the repair loop's re-review: the branch that only runs because something
    went wrong, and therefore the expensive one."""
    import ast
    import inspect

    from openfactory.orchestrator import machine

    src = inspect.getsource(machine)
    tree = ast.parse(src)
    reviews = sum(1 for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "review")
    counted = sum(1 for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "_count_review")
    assert reviews and counted >= reviews, f"{reviews} review calls, {counted} counted"


# ── a setting that loads cleanly and does nothing (C-38) ─────────────────────────────────────────

def test_a_manifest_declaring_an_INERT_key_is_told_so(tmp_path, caplog):
    """`max_plan_files` is documented as a blast-radius gate, accepted by the strict manifest, and
    read by nothing (ADR-0013 made sizing INVEST-only). A client could set a ceiling, load cleanly,
    and run with none — a setting that loads and does nothing is worse than one that is rejected,
    because the operator believes the guard is in place."""
    import logging

    from openfactory.loader import load_manifest

    repo = tmp_path / "repo"
    (repo / namespace.DIR).mkdir(parents=True)
    (repo / namespace.MANIFEST).write_text(
        "version: 1\nbase_branch: main\nmax_plan_files: 10\n"
        "validate:\n  test: pytest -q\n")
    p = _project()
    with caplog.at_level(logging.WARNING, logger="openfactory.loader"):
        load_manifest(p, repo_root=repo)
    assert "OPENFACTORY_MANIFEST_INERT" in caplog.text
    assert "max_plan_files" in caplog.text


def test_a_manifest_WITHOUT_inert_keys_says_nothing(tmp_path, caplog):
    """The positive twin — a warning that always fires is a warning nobody reads."""
    import logging

    from openfactory.loader import load_manifest

    repo = tmp_path / "repo"
    (repo / namespace.DIR).mkdir(parents=True)
    (repo / namespace.MANIFEST).write_text(
        "version: 1\nbase_branch: main\nvalidate:\n  test: pytest -q\n")
    with caplog.at_level(logging.WARNING, logger="openfactory.loader"):
        load_manifest(_project(), repo_root=repo)
    assert "OPENFACTORY_MANIFEST_INERT" not in caplog.text


# ── a deletion that deletes nothing must not report success (audit finding) ──────────────────────

def test_forgetting_REALLY_DELETES_on_the_store_the_OSS_distribution_ships(tmp_path, monkeypatch):
    """THE REFUSAL BECAME A DELETION, and that is the fix rather than a relaxation.

    This test used to assert that `forget_project` RAISES when `OPENFACTORY_METRICS_TABLE` is unset —
    correct at the time, because writing went through the configured sink while deleting reached
    for DynamoDB by hand. So the OSS distribution (`OPENFACTORY_METRICS_SINK=sqlite`, in the compose file)
    recorded a client's words and had no way to delete them: the right to be forgotten held only
    on the vendor we happen to pay for. Refusing was the honest thing to do about a hole; it was
    never the destination.

    Deletion now travels the sink axis, so the store that RECORDED is the store that deletes.
    """
    from openfactory.memory import transcript

    monkeypatch.delenv("OPENFACTORY_METRICS_TABLE", raising=False)
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))

    transcript.record("acme", thread="C1", role="person", text="o saldo vem errado", actor="U1")
    transcript.record("acme", thread="C1", role="agent", text="vou olhar")
    transcript.record("outra-firma", thread="C9", role="person", text="bom dia")
    assert transcript.recent("acme", thread="C1"), "nothing was recorded, so nothing is proved"

    gone = transcript.forget_project("acme")

    assert gone == 2, f"the client's turns were not deleted: {gone}"
    assert transcript.recent("acme", thread="C1") == [], "the conversation survived the deletion"
    # …and ONLY that client's. A deletion that took the neighbour's rows too would pass every
    # assertion above while being a far worse defect than the one this replaces.
    assert transcript.recent("outra-firma", thread="C9"), "another client's turns were deleted"


def test_forgetting_on_a_store_that_CANNOT_delete_still_refuses(monkeypatch):
    """The half of the old guard that must survive, driven by a store that genuinely cannot.

    Every sink in the registry implements deletion today, so this plants one that does not —
    otherwise the refusal branch is unreachable and the guard would be asserting the absence of
    something nothing produces. A store that recorded a client's words and cannot delete them must
    say so: returning 0 tells an operator answering a legal request that it is done."""
    import pytest as _pytest

    from openfactory.memory import transcript

    class _WriteOnly:
        """Records, and has no `forget` — the shape of a sink somebody adds later."""

        def record(self, rec):
            return None

    monkeypatch.setattr(transcript, "_sink_for", lambda **_kw: _WriteOnly())
    with _pytest.raises(NotImplementedError, match="nothing was deleted"):
        transcript.forget_project("acme")


def test_forgetting_where_NOTHING_WAS_EVER_STORED_answers_zero(monkeypatch):
    """The third case, and the old guard could not tell it from the second.

    With metrics off the sink is Null: it dropped every record it was ever given, so there is no
    trace of this client anywhere in it and 0 is the TRUE answer — the one an operator needs to
    hear. What must never return 0 is a store that kept something, which is the test above."""
    from openfactory.memory import transcript

    monkeypatch.delenv("OPENFACTORY_METRICS_TABLE", raising=False)
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "null")

    assert transcript.forget_project("acme") == 0


def test_a_manifest_declaring_PERMISSIONS_is_told_it_bounds_nothing(tmp_path, caplog):
    """manifest.py calls it "project-level tightening of permissions (never loosening)". Nothing
    reads it — and a security-shaped promise is the worst kind to leave silently inert, because a
    client's reviewer writes it into their onboarding document."""
    import logging

    from openfactory.loader import load_manifest

    repo = tmp_path / "r"
    (repo / namespace.DIR).mkdir(parents=True)
    (repo / namespace.MANIFEST).write_text(
        "version: 1\nbase_branch: main\npermissions: {write: false}\n"
        "validate:\n  test: pytest -q\n")
    with caplog.at_level(logging.WARNING, logger="openfactory.loader"):
        load_manifest(_project(), repo_root=repo)
    assert "OPENFACTORY_MANIFEST_INERT" in caplog.text and "permissions" in caplog.text


def test_the_install_contract_carries_no_unused_heavy_dependency():
    """An ORM, its migration tool and a Redis client were hard dependencies of every install, for
    two four-line TODO placeholders. The first thing a stranger's dependency resolver sees."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent
    text = (root / "pyproject.toml").read_text()
    deps = re.search(r"dependencies = \[(.*?)\]", text, re.S).group(1)
    for unused in ("sqlalchemy", "alembic", "arq"):
        assert unused not in deps, f"{unused} is installed for every user and imported by nothing"
