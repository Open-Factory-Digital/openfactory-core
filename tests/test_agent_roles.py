"""Two-stage coding agent: planner (read-only) → executor (TDD), a model per role.

The neutral role prompts (openfactory/org_defaults/roles/*.md) are rendered by the Claude Code
adapter; a different harness adapter would render the same roles its own way.
"""

from __future__ import annotations

from openfactory.adapters.agent.base import AgentContext
from openfactory.adapters.agent.claude_code import ClaudeCodeAdapter
from openfactory.contracts import AgentRunResult, Ticket


def _ctx(**kw) -> AgentContext:
    ticket = Ticket(id="#1", title="Add beacon", objective="Add GET /beacon", repo="o/r")
    return AgentContext(ticket=ticket, **kw)


def _capture(adapter) -> list[dict]:
    calls: list[dict] = []

    def fake_invoke(sandbox, workspace, prompt, phase, *, tools, model, context):
        calls.append({"prompt": prompt, "phase": phase, "tools": tools, "model": model})
        return AgentRunResult(ok=True, summary=("the plan" if phase == "plan" else "done"))

    adapter._invoke = fake_invoke
    return calls


def test_planner_is_read_only_and_uses_planner_model(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PLANNER_MODEL", "planner-model")
    a = ClaudeCodeAdapter()
    calls = _capture(a)
    a.plan(sandbox=None, workspace=None, context=_ctx())
    c = calls[0]
    assert c["phase"] == "plan"
    assert c["tools"] == ["Read", "Grep", "Glob"]  # investigates, never edits
    assert c["model"] == "planner-model"
    assert "Role: Planner" in c["prompt"]  # the neutral planner role prompt was rendered


def test_executor_gets_the_plan_and_executor_model(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_EXECUTOR_MODEL", "exec-model")
    a = ClaudeCodeAdapter()
    calls = _capture(a)
    a.execute(sandbox=None, workspace=None,
              context=_ctx(plan="STEP 1: test /beacon", allowed_tools=["Edit", "Bash"]))
    c = calls[0]
    assert c["phase"] == "execute"
    assert c["model"] == "exec-model"
    assert c["tools"] == ["Edit", "Bash"]
    assert "## Plan\nSTEP 1: test /beacon" in c["prompt"]  # the plan is threaded in
    assert "Role: Executor" in c["prompt"]


def test_per_role_models_are_configurable():
    a = ClaudeCodeAdapter(planner_model="p", executor_model="e")
    assert a.planner_model == "p"
    assert a.executor_model == "e"


def test_machine_runs_plan_then_execute_with_roles():
    """The orchestrator calls plan() then execute(), tagging each event with the role."""
    events: list[tuple[str, str, str | None]] = []

    class TwoStageAgent:
        def plan(self, *, sandbox, workspace, context):
            return AgentRunResult(ok=True, summary="do X then Y", actions=["Read: main.py"])

        def execute(self, *, sandbox, workspace, context):
            # the plan must have been threaded into the context
            assert context.plan == "do X then Y"
            return AgentRunResult(ok=True, summary="done", actions=["Edit: main.py"])

    # drive the two methods directly with a shared context (unit-level, no full JobRunner)
    ctx = _ctx()
    agent = TwoStageAgent()
    pr = agent.plan(sandbox=None, workspace=None, context=ctx)
    ctx.plan = pr.summary
    for a in pr.actions:
        events.append(("agent_action", a, "planner"))
    er = agent.execute(sandbox=None, workspace=None, context=ctx)
    for a in er.actions:
        events.append(("agent_action", a, "executor"))

    assert events == [
        ("agent_action", "Read: main.py", "planner"),
        ("agent_action", "Edit: main.py", "executor"),
    ]


def test_readonly_cli_denies_mutating_tools():
    from openfactory.adapters.agent.claude_code import _READONLY_TOOLS
    c = ClaudeCodeAdapter()._cli("p", harness="claude", tools=_READONLY_TOOLS, model="sonnet")
    assert "--tools Read,Grep,Glob" in c
    # belt-and-braces: mutating tools explicitly denied so read-only holds across CLI versions
    assert "--disallowedTools" in c
    for t in ("Edit", "Write", "Bash"):
        assert t in c.split("--disallowedTools", 1)[1]


def test_executor_cli_does_not_deny_its_granted_mutating_tools():
    tools = ["Read", "Edit", "Write", "Bash", "Grep", "Glob"]
    c = ClaudeCodeAdapter()._cli("p", harness="claude", tools=tools, model="opus")
    # Edit/Write/Bash are granted → they must NOT be in the deny list (exact tokens)
    denied: list[str] = []
    if "--disallowedTools" in c:
        denied = c.split("--disallowedTools", 1)[1].strip().split()[0].split(",")
    for t in ("Edit", "Write", "Bash"):
        assert t not in denied


def test_granted_tools_are_auto_approved_so_bash_actually_runs():
    # Regression guard: acceptEdits auto-accepts EDITS only; without --allowedTools, Bash
    # prompts and is denied in headless -p mode, killing the executor's test/lint runs.
    tools = ["Read", "Edit", "Write", "Bash", "Grep", "Glob"]
    c = ClaudeCodeAdapter()._cli("p", harness="claude", tools=tools, model="opus")
    assert "--allowedTools" in c
    allowed = c.split("--allowedTools", 1)[1].strip().split()[0].split(",")
    assert "Bash" in allowed  # the coder can genuinely run its own gates


def test_readonly_role_auto_approves_only_read_tools():
    from openfactory.adapters.agent.claude_code import _READONLY_TOOLS
    c = ClaudeCodeAdapter()._cli("p", harness="claude", tools=_READONLY_TOOLS, model="sonnet")
    allowed = c.split("--allowedTools", 1)[1].strip().split()[0].split(",")
    assert "Bash" not in allowed and "Write" not in allowed  # read-only stays read-only
