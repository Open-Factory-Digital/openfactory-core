"""The chat inherited the executor's fences, and the OUTER one was the tightest (#168).

Step 1 of the tool-calling plan, and it ships first because every later claim is measured against
it. Three corrections, none of which changes anything the operator sees:

    the chat subprocess wall   4 hours   (inherited `_EXECUTE_TIMEOUT`)
    the chat turn cap          200       (inherited `self.max_turns`)
    the activity budget        6 minutes (`AskWorkflow`, `maximum_attempts=1`)

A question that thought for seven minutes therefore died at the TEMPORAL wall — the operator read
"I couldn't work that out just now", the agent kept running, and the spend kept accruing with
nobody left to hand the answer to. Adding tool-calling turns to that arrangement makes it bite
every day instead of rarely, which is why this is step one and not a footnote.

Innermost fence first: turns stop it before the wall, the wall stops it before the activity's
budget. And what a question COST is finally recorded — `MetricRecord.role` has listed `chat` as a
valid value since the day it was written, and nothing has ever produced one.
"""

from __future__ import annotations

import inspect

import pytest

from openfactory.util import scratch

# ── 1. the fences, and their ORDER ──────────────────────────────────────────────────────────────

def test_the_chat_has_its_own_wall_and_it_is_not_the_executors():
    from openfactory.adapters.agent import claude_code

    assert claude_code._CHAT_TIMEOUT != claude_code._EXECUTE_TIMEOUT, (
        "the chat is back on the executor's four-hour wall")
    assert claude_code._CHAT_TIMEOUT < claude_code._EXECUTE_TIMEOUT


def test_the_chat_has_its_own_turn_cap():
    from openfactory.adapters.agent.claude_code import _CHAT_MAX_TURNS

    assert 0 < _CHAT_MAX_TURNS <= 40, (
        f"{_CHAT_MAX_TURNS} turns is an execution budget, not a conversation")


def test_the_fences_are_ordered_INNERMOST_FIRST():
    """THE CLAIM THIS CARD EXISTS FOR. A wall outside the activity's budget is not a wall — it is
    a promise the platform cannot keep, and the operator gets the failure of the fence they cannot
    see. Read from BOTH sources so a change to either is caught by this one assertion."""
    import ast

    from openfactory.adapters.agent.claude_code import _CHAT_TIMEOUT
    from openfactory.runtime.temporal import workflow as wf

    src = inspect.getsource(wf.AskWorkflow)
    budget = next(
        (kw.value for node in ast.walk(ast.parse(inspect.cleandoc("\n" + src)))
         if isinstance(node, ast.Call)
         for kw in node.keywords if kw.arg == "start_to_close_timeout"), None)
    assert budget is not None, "AskWorkflow no longer bounds the activity — this guard is blind"
    minutes = next((k.value.value for k in getattr(budget, "keywords", [])
                    if k.arg == "minutes" and isinstance(k.value, ast.Constant)), None)
    assert minutes is not None, f"the activity budget is not in minutes: {ast.unparse(budget)}"

    assert _CHAT_TIMEOUT < minutes * 60, (
        f"the chat's own wall ({_CHAT_TIMEOUT}s) is OUTSIDE the activity's budget "
        f"({minutes * 60}s) — the agent runs on, billing, past the point anybody can be told")


@pytest.mark.parametrize("phase,expect_chat", [("chat", True), ("execute", False),
                                               ("repair", False), ("plan", False)])
def test_only_the_CHAT_phase_gets_the_chat_fences(phase, expect_chat):
    """The twin. A cap this tight applied to an execution pass would truncate real work — the
    fences are per-phase, and the phase has to travel to the place that builds the command."""
    from openfactory.adapters.agent.claude_code import _CHAT_MAX_TURNS, ClaudeCodeAdapter

    box = ClaudeCodeAdapter(max_turns=200)
    line = box._cli("p", harness="/bin/claude", tools=["Read"], model=None, phase=phase)
    turns = line.split("--max-turns")[1].split()[0]

    assert (turns == str(_CHAT_MAX_TURNS)) is expect_chat, (
        f"phase {phase!r} was given --max-turns {turns}")


def test_the_phase_actually_reaches_the_command_builder():
    """Reachability: `_cli` grew a `phase` parameter that the caller must pass, or every phase
    silently takes the default and the per-phase fences are decoration."""
    import ast

    from openfactory.adapters.agent import claude_code

    src = inspect.getsource(claude_code.ClaudeCodeAdapter._invoke_once)
    call = next((n for n in ast.walk(ast.parse(inspect.cleandoc("\n" + src)))
                 if isinstance(n, ast.Call)
                 and getattr(getattr(n.func, "attr", None), "__str__", str)() == "_cli"), None)
    assert call is not None, "_invoke_once no longer builds the command — this guard is blind"
    assert "phase" in {k.arg for k in call.keywords}, (
        "the phase never reaches `_cli`, so every pass gets the same fences again")


# ── 2. what a question costs is recorded ────────────────────────────────────────────────────────

def test_the_answer_carries_what_the_pass_cost():
    from openfactory.techlead.conversation import _spent

    class _Res:
        cost_usd, num_turns, input_tokens, output_tokens = 0.42, 3, 900, 120
        model, harness = "sonnet", "claude_code"

    assert _spent(_Res()) == {"cost_usd": 0.42, "num_turns": 3, "input_tokens": 900,
                              "output_tokens": 120, "model": "sonnet", "harness": "claude_code"}


def test_an_ABSENT_number_stays_absent_rather_than_becoming_zero():
    """A zero reads as "this was free", which is the one thing an agent pass never is."""
    from openfactory.techlead.conversation import _spent

    class _Res:
        cost_usd = num_turns = input_tokens = output_tokens = model = harness = None

    assert _spent(_Res()) == {}


def test_the_chat_pass_records_the_row_its_own_contract_documents(monkeypatch):
    """`MetricRecord.role` lists `chat` among its valid values and nothing has ever produced one —
    so the single role an operator talks to most was the one pass nobody could price."""
    from openfactory.observability import metrics
    from openfactory.runtime.temporal import activities
    from openfactory.techlead import conversation

    written: list[object] = []
    monkeypatch.setattr(activities, "_metrics_sink",
                        lambda: type("S", (), {"record": lambda self, r: written.append(r) or True})())

    conversation._record_chat_spend(type("P", (), {"name": "demo"})(),
                                    {"cost_usd": 0.1, "num_turns": 2, "model": "sonnet"})

    assert len(written) == 1, "the chat pass still records nothing"
    rec = written[0]
    assert isinstance(rec, metrics.MetricRecord)
    assert rec.role == "chat" and rec.project == "demo" and rec.cost_usd == 0.1


def test_a_sink_that_refuses_costs_the_ROW_and_not_the_answer(monkeypatch):
    from openfactory.runtime.temporal import activities
    from openfactory.techlead import conversation

    def _boom():
        raise RuntimeError("no sink here")

    monkeypatch.setattr(activities, "_metrics_sink", _boom)
    conversation._record_chat_spend(type("P", (), {"name": "demo"})(), {"cost_usd": 0.1})


def test_nothing_measured_writes_nothing(monkeypatch):
    """An empty row is worse than no row: it says a pass happened and cost nothing."""
    from openfactory.runtime.temporal import activities
    from openfactory.techlead import conversation

    written: list[object] = []
    monkeypatch.setattr(activities, "_metrics_sink",
                        lambda: type("S", (), {"record": lambda self, r: written.append(r) or True})())

    conversation._record_chat_spend(type("P", (), {"name": "demo"})(), {})
    assert written == []


# ── 3. two people asking the same thing get two answers ─────────────────────────────────────────

def test_the_workflow_id_is_FRESH_rather_than_a_hash_of_the_question():
    """`abs(hash(text)) % 10**8` reads as idempotency and is neither idempotent nor unique:
    Python's `hash` is salted per PROCESS, so the same question twice in one panel deduplicates
    against itself — the second asker silently receives the first one's answer — while the same
    question after a restart does not. `maximum_attempts=1` one file over already says a question
    is not idempotent spend."""
    import re as _re

    from openfactory.actions import catalog

    # COMMENTS STRIPPED FIRST. The comment beside the fix QUOTES the defect it replaced, so a
    # guard reading raw source fails on the sentence explaining the rule it protects — fourth
    # time in this session ([[strip-the-prose-before-asserting]]).
    src = inspect.getsource(catalog._ask)
    code = "\n".join(_re.sub(r"(^|\s)#.*$", "", ln) for ln in src.splitlines())

    assert "hash(text)" not in code, "the id is a hash of the question again"
    assert "uuid" in code, "the id is not fresh per question"


# ── 4. the fences REACH the subprocess, and the numbers REACH the answer ────────────────────────
#
# Three mutations survived the first round and all three were the same gap: the guards above
# assert the CONSTANTS and the command string, and nothing drove the two places that use them.
# Deleting the per-phase timeout, or the two lines that price the pass, left every assertion
# green. That is this repository's most expensive recurring shape, so these drive.

class _Sandbox:
    """Captures what the adapter actually hands the subprocess."""

    def __init__(self):
        self.seen: dict[str, object] = {}
        self.harness = "claude"

    def harness_path(self, name):
        return f"/bin/{name}"

    def run(self, *, workspace, command, timeout=None):
        self.seen = {"command": command, "timeout": timeout}
        return 0, '{"type":"result","result":"ok","total_cost_usd":0.5,"num_turns":2}'


@pytest.mark.parametrize("phase", ["chat", "execute"])
def test_the_wall_that_reaches_the_SUBPROCESS_is_the_phases_own(phase, monkeypatch):
    from openfactory.adapters.agent import claude_code
    from openfactory.adapters.agent.base import AgentContext
    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.contracts import Ticket

    box = claude_code.ClaudeCodeAdapter(max_turns=200)
    monkeypatch.setattr(box, "_write_transcript", lambda *a, **k: None)
    sandbox = _Sandbox()

    box._invoke_once(sandbox, Workspace(path="/tmp", branch="b", base_branch="main"),
                     "prompt", phase, tools=["Read"], model=None,
                     context=AgentContext(ticket=Ticket(id="t", title="t", objective="o", repo="")))

    expected = claude_code._CHAT_TIMEOUT if phase == "chat" else claude_code._EXECUTE_TIMEOUT
    assert sandbox.seen["timeout"] == expected, (
        f"phase {phase!r} ran under {sandbox.seen['timeout']}s — the fence never reached the "
        f"subprocess, so both constants above are decoration")


def test_the_ANSWER_carries_the_spend_the_pass_reported(monkeypatch):
    """Reachability for the pricing: `_spent` and `_record_chat_spend` are both tested in
    isolation above, and deleting the two lines that CALL them left that green."""
    import openfactory.adapters.agent as agent_registry
    from openfactory.contracts.run import AgentRunResult
    from openfactory.techlead import conversation

    class _Harness:
        def chat(self, *, sandbox, workspace, question, context):
            return AgentRunResult(ok=True, summary="ok", cost_usd=0.42, num_turns=3,
                                  input_tokens=900, output_tokens=120)

    monkeypatch.setattr(conversation, "gather_jobs", lambda p: [])
    # A SCRATCH DIR, NEVER "/tmp". `_answer` owns what `clone_repo` hands back and deletes it
    # recursively in a `finally`; this line used to say "/tmp", so the suite ran
    # `rmtree("/tmp")`. Harmless-looking on macOS, where pytest keeps its files under
    # /private/var/folders — on Linux it deleted pytest's own temp root and failed 898 later
    # tests (2026-08-21). `util/scratch.discard` now refuses it; this keeps the stub honest.
    monkeypatch.setattr(conversation, "clone_repo",
                        lambda p: (scratch.make("test-chat"), False))
    monkeypatch.setattr(conversation, "comment_digest", lambda jobs: "")
    monkeypatch.setattr(conversation, "answer_text", lambda res: "an answer")
    monkeypatch.setattr(conversation, "_record_chat_spend", lambda *a, **k: None)
    monkeypatch.setattr(agent_registry, "build_techlead", lambda p: _Harness())

    out = conversation._answer(type("P", (), {"name": "demo", "repo_path": "/tmp"})(),
                               "why?", cap=None, can=())

    assert out.spend, "the answer came back with no idea what it cost"
    assert out.spend["cost_usd"] == 0.42 and out.spend["num_turns"] == 3
