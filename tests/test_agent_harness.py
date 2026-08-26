"""The agent-harness seam: which harness writes code, which one judges, and how Codex is driven.

The platform was agnostic in its protocol and hardcoded in its composition root — six direct
`ClaudeCodeAdapter()` calls meant a second harness was a code change in six files. These tests pin
the seam that closed that, and the Codex adapter built on it.
"""

from __future__ import annotations

import pytest

from openfactory.adapters.agent import registry as harnesses
from openfactory.adapters.agent.codex import CodexAdapter
from openfactory.contracts.project import Project


def _project(**kw) -> Project:
    return Project(name="p", repo_path="/tmp/p", **kw)


# ── resolution: three roles, one line of config ──────────────────────────────────────────────────

def _clear(monkeypatch):
    for var in harnesses.ROLES.values():
        monkeypatch.delenv(var, raising=False)


def test_defaults_keep_todays_behaviour(monkeypatch):
    _clear(monkeypatch)
    p = _project()
    assert [harnesses.harness_kind(p, r) for r in ("executor", "reviewer", "techlead")] == \
        ["claude_code"] * 3


def test_ONE_LINE_sets_every_role(monkeypatch):
    """The common case, and the one that makes a Claude-free deployment possible: a client that
    uses a single harness declares it once instead of repeating it three times."""
    _clear(monkeypatch)
    p = _project(harness="codex")
    assert [harnesses.harness_kind(p, r) for r in ("executor", "reviewer", "techlead")] == \
        ["codex"] * 3
    assert isinstance(harnesses.build_executor(p), CodexAdapter)


def test_per_role_config_lets_the_reviewer_differ(monkeypatch):
    """The reason the axes are separate: an independent reviewer on a different engine is what
    makes the prompt's "you did NOT write this code" structurally true."""
    _clear(monkeypatch)
    p = _project(harness={"executor": "codex", "reviewer": "claude_code"})
    assert harnesses.harness_kind(p, "executor") == "codex"
    assert harnesses.harness_kind(p, "reviewer") == "claude_code"
    assert harnesses.harness_kind(p, "techlead") == "claude_code"  # unset → default


def test_default_key_covers_the_unlisted_roles(monkeypatch):
    _clear(monkeypatch)
    p = _project(harness={"default": "codex", "reviewer": "claude_code"})
    assert harnesses.harness_kind(p, "executor") == "codex"
    assert harnesses.harness_kind(p, "techlead") == "codex"
    assert harnesses.harness_kind(p, "reviewer") == "claude_code"


def test_env_overrides_per_role(monkeypatch):
    """The registry is BAKED INTO the worker image, so without an override trying another harness
    would need a rebuild and a roll — a loop slow enough that nobody runs the comparison. It is an
    escape hatch, not the normal configuration path."""
    _clear(monkeypatch)
    p = _project(harness="claude_code")
    monkeypatch.setenv("OPENFACTORY_HARNESS_EXECUTOR", "codex")
    assert harnesses.harness_kind(p, "executor") == "codex"
    assert harnesses.harness_kind(p, "reviewer") == "claude_code"


def test_an_unknown_harness_raises_instead_of_falling_back(monkeypatch):
    """Silently defaulting would let a whole run use a harness nobody chose and report clean
    numbers for the wrong thing."""
    _clear(monkeypatch)
    with pytest.raises(ValueError, match="unknown harness"):
        harnesses.build_executor(_project(harness="gpt-9000"))


def test_an_unknown_role_raises():
    with pytest.raises(ValueError, match="unknown role"):
        harnesses.harness_kind(_project(), "wizard")


def test_every_harness_can_serve_every_role(monkeypatch):
    """The parity requirement: a client with no Claude account must still get a reviewer and a
    tech-lead, not a deployment that quietly loses them."""
    _clear(monkeypatch)
    for kind in sorted(harnesses.HARNESSES):
        p = _project(harness=kind)
        assert harnesses.build_reviewer(p).name == kind or kind == "claude_code"
        assert harnesses.build_techlead(p) is not None


def test_a_harness_that_cannot_judge_is_rejected_at_BUILD_time(monkeypatch):
    """Surfaces when the job starts, not hours later when it parks and the diagnosis silently
    produces nothing."""
    _clear(monkeypatch)
    monkeypatch.setitem(harnesses.HARNESSES, "mute", lambda **kw: object())
    with pytest.raises(ValueError, match="cannot serve the techlead role"):
        harnesses.build_techlead(_project(harness="mute"))


def test_adding_a_harness_is_one_table_entry():
    assert set(harnesses.HARNESSES) >= {"claude_code", "codex", "kimi", "opencode"}


def test_no_call_site_instantiates_a_concrete_harness():
    """The regression guard for the actual bug: concrete adapters hardcoded across factory /
    activities / the Slack bot. Everything outside the adapter packages must resolve."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "openfactory"
    offenders = []
    for path in root.rglob("*.py"):
        if path.parent.name in ("agent", "reviewer") or "testing" in path.parts:
            continue
        if "ClaudeCodeAdapter(" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"hardcoded harness back in: {offenders}"


# ── the Codex adapter: command construction, verified against `codex exec --help` ─────────────────

class _FakeSandbox:
    """Captures the commands an adapter builds; returns canned output for each."""

    def __init__(self, run_out: str = "", last_message: str = "", code: int = 0) -> None:
        self.commands: list[str] = []
        self.run_out, self.last_message, self.code = run_out, last_message, code

    def harness_path(self, name: str) -> str:
        """The box says where the harness is (ADR-0037 D2). A double stands in for a WORKTREE —
        the harness is on the host's PATH — so the bare name is the honest answer here. Adding it
        was not optional: `harness_path` is part of `SandboxAdapter`, and a double that lacks a
        port method is a double that no longer stands for the thing."""
        return name

    def run(self, *, workspace, command: str, timeout: int):  # noqa: ARG002
        self.commands.append(command)
        if command.startswith("cat "):
            return 0, self.last_message
        return self.code, self.run_out


def _ctx(**kw):
    from openfactory.adapters.agent.base import AgentContext
    from openfactory.contracts import Ticket

    return AgentContext(
        ticket=Ticket(id="#7", title="add health check", objective="expose /health", repo="o/r"),
        **kw,
    )


def _ws():
    from openfactory.adapters.sandbox.base import Workspace

    return Workspace(path="/work", branch="b", base_branch="main")


def test_plan_is_read_only_by_SANDBOX_POLICY_not_by_instruction():
    """Codex has no per-tool allowlist, so `-s read-only` is what actually makes the planner
    incapable of editing rather than merely told not to."""
    sb = _FakeSandbox(last_message="the plan")
    CodexAdapter(model="gpt-5").plan(sandbox=sb, workspace=_ws(), context=_ctx())
    cmd = sb.commands[0]
    assert cmd.startswith("codex exec ")
    assert "-s read-only" in cmd
    assert "workspace-write" not in cmd


def test_execute_builds_the_verified_flag_set():
    sb = _FakeSandbox(last_message="done")
    CodexAdapter(model="gpt-5").execute(sandbox=sb, workspace=_ws(), context=_ctx())
    cmd = sb.commands[0]
    for flag in ("codex exec", "--json", "-o .openfactory-codex-last-message",
                 "--skip-git-repo-check", "-s workspace-write", "-m gpt-5"):
        assert flag in cmd, flag
    assert " -- " in cmd  # a prompt starting with '-' must not be read as a flag


def test_full_access_is_opt_in_only(monkeypatch):
    """`--dangerously-bypass-approvals-and-sandbox` is legitimate in an externally-sandboxed box
    (our Fargate task is exactly that) but must never be the default."""
    sb = _FakeSandbox(last_message="x")
    CodexAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx())
    assert "--dangerously-bypass" not in sb.commands[0]

    monkeypatch.setenv("OPENFACTORY_CODEX_FULL_ACCESS", "1")
    sb2 = _FakeSandbox(last_message="x")
    CodexAdapter().execute(sandbox=sb2, workspace=_ws(), context=_ctx())
    assert "--dangerously-bypass-approvals-and-sandbox" in sb2.commands[0]
    assert "-s workspace-write" not in sb2.commands[0]  # the two are alternatives, not both


def test_resume_uses_the_resume_SUBCOMMAND():
    sb = _FakeSandbox(last_message="x")
    CodexAdapter().execute(sandbox=sb, workspace=_ws(),
                           context=_ctx(resume_handle="sess-abc"))
    assert sb.commands[0].startswith("codex exec resume sess-abc ")


def test_the_summary_comes_from_the_FILE_not_the_event_stream():
    """The event schema is undocumented; `--output-last-message` is a documented contract. The
    load-bearing output must not depend on a shape we are guessing at."""
    sb = _FakeSandbox(run_out='{"type":"noise"}\nnot json at all\n', last_message="THE ANSWER")
    res = CodexAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx())
    assert res.summary == "THE ANSWER"
    assert res.ok is True
    assert res.harness == "codex"
    # and the file is cleaned up in the same call, so it can't leak into the ticket's commit
    assert any(c.startswith("cat ") and "rm -f" in c for c in sb.commands)


def test_unparseable_events_degrade_instead_of_raising():
    sb = _FakeSandbox(run_out="plain text\n{broken json\n[]\n", last_message="ok")
    res = CodexAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx())
    assert res.ok is True and res.summary == "ok"
    assert res.cost_usd is None and res.num_turns is None  # unknown, not invented


# The exact events codex-cli 0.145.0 emits, captured from real runs (a probe that ran a shell
# command and edited a file). Tests parse THIS, so a schema change breaks a test instead of
# silently emptying the job journal.
_REAL_EVENTS = "\n".join([
    '{"type":"thread.started","thread_id":"019f9eef-2cc2-7a11-9dae-d2998ce9bdeb"}',
    '{"type":"turn.started"}',
    '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"I will run it."}}',
    '{"type":"item.completed","item":{"id":"item_1","type":"command_execution",'
    '"command":"/bin/zsh -lc \'echo hello\'","aggregated_output":"hello","exit_code":0}}',
    '{"type":"item.completed","item":{"id":"item_3","type":"file_change",'
    '"changes":[{"path":"/w/sample.py","kind":"update"}]}}',
    '{"type":"turn.completed","usage":{"input_tokens":67207,"cached_input_tokens":48384,'
    '"output_tokens":269,"reasoning_output_tokens":0}}',
])


def test_session_id_comes_from_thread_started():
    """`codex exec resume <ID>` takes the `thread_id` from `thread.started` — the real key, which
    is NOT called session_id."""
    res = CodexAdapter().execute(sandbox=_FakeSandbox(run_out=_REAL_EVENTS, last_message="done"),
                                 workspace=_ws(), context=_ctx())
    assert res.resume_handle == "019f9eef-2cc2-7a11-9dae-d2998ce9bdeb"


def test_actions_read_like_the_other_harness():
    """The journal shows what the agent DID. Built from the observed item types, not from a
    generic key hunt that would have produced an empty trace against this schema."""
    res = CodexAdapter().execute(sandbox=_FakeSandbox(run_out=_REAL_EVENTS, last_message="done"),
                                 workspace=_ws(), context=_ctx())
    assert any(a.startswith("Bash: ") and "echo hello" in a for a in res.actions)
    assert any(a.startswith("Update ") and a.endswith("/w/sample.py") for a in res.actions)
    assert not any("I will run it" in a for a in res.actions)  # prose is not an action


def test_tokens_are_read_and_cost_is_left_UNKNOWN():
    """Codex reports tokens but no cost and no turn count. Cost stays None (the dashboard renders
    unknown) and turns are DERIVED by counting completed turns — inventing a cost would poison the
    A/B this harness exists to be compared in."""
    res = CodexAdapter().execute(sandbox=_FakeSandbox(run_out=_REAL_EVENTS, last_message="done"),
                                 workspace=_ws(), context=_ctx())
    assert res.input_tokens == 67207 and res.output_tokens == 269
    assert res.cost_usd is None
    assert res.num_turns == 1


def test_a_nonzero_exit_is_not_ok():
    sb = _FakeSandbox(run_out="boom", last_message="", code=1)
    assert CodexAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx()).ok is False


def test_the_ticket_and_the_knowledge_cascade_reach_the_prompt():
    """The adapter formats; it never decides behaviour. Everything the project declared has to
    survive the trip (ADR-0001 D-2/D-9)."""
    sb = _FakeSandbox(last_message="x")
    ctx = _ctx(constraints=["money is Decimal"], guidelines=["100% coverage"],
               knowledge_map="### app", doc_index="docs/x.md — a thing",
               decision="DECISION A — go")
    CodexAdapter().execute(sandbox=sb, workspace=_ws(), context=ctx)
    cmd = sb.commands[0]
    for expected in ("add health check", "expose /health", "money is Decimal",
                     "100% coverage", "### app", "docs/x.md", "DECISION A"):
        assert expected in cmd, expected


def test_codex_declares_the_capabilities_it_does_not_have():
    """The orchestrator probes with hasattr and degrades. Codex has no cross-container session
    restore, so it must NOT advertise continue/recover — a turn-capped run parks for a human
    instead of silently restarting from scratch."""
    a = CodexAdapter()
    assert hasattr(a, "execute") and hasattr(a, "repair") and hasattr(a, "plan")
    assert not hasattr(a, "continue_execute")
    assert not hasattr(a, "recover")


# ── the Kimi adapter: verified command shape, UNVERIFIED stream ──────────────────────────────────

def test_kimi_uses_auto_not_yolo():
    """`-y/--yolo`'s own help says the agent "may still ask questions". In a headless job there
    is nobody to answer, and a run that stops to ask burns its budget and returns nothing. Only
    `--auto` promises it will not ask."""
    from openfactory.adapters.agent.kimi import KimiAdapter

    sb = _FakeSandbox(run_out="done")
    KimiAdapter(model="k3").execute(sandbox=sb, workspace=_ws(), context=_ctx())
    cmd = sb.commands[0]
    assert "--auto" in cmd
    assert "--yolo" not in cmd and " -y " not in cmd
    assert "--output-format stream-json" in cmd
    assert "-m k3" in cmd and "-p " in cmd


def test_kimi_plan_mode_is_a_MODE_not_an_enforced_policy():
    """Unlike Codex's `-s read-only`, Kimi exposes no sandbox policy — so this is the weaker
    guarantee, and the test says so rather than implying parity."""
    from openfactory.adapters.agent.kimi import KimiAdapter

    sb = _FakeSandbox(run_out="the plan")
    KimiAdapter().plan(sandbox=sb, workspace=_ws(), context=_ctx())
    cmd = sb.commands[0]
    assert "--plan" in cmd
    assert "read-only" not in cmd  # no such flag exists in `kimi --help`


def test_kimi_resume_uses_dash_S():
    from openfactory.adapters.agent.kimi import KimiAdapter

    sb = _FakeSandbox(run_out="x")
    KimiAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx(resume_handle="sess-77"))
    assert "-S sess-77" in sb.commands[0]


def test_kimi_degrades_to_raw_output_when_the_stream_is_unrecognized():
    """Its schema is UNKNOWN until someone runs the binary. An unparseable stream must leave a
    usable summary and no invented telemetry — not an empty result and not a fabricated cost."""
    from openfactory.adapters.agent.kimi import KimiAdapter

    sb = _FakeSandbox(run_out="some plain text the CLI printed")
    res = KimiAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx())
    assert res.ok is True
    assert "plain text" in res.summary
    assert res.cost_usd is None and res.input_tokens is None
    assert res.harness == "kimi"


def test_kimi_is_registered_but_carries_no_cost_claim():
    """Wired into the seam; NOT proven. Cost stays unknown so it can never quietly win or lose an
    A/B on a number nobody measured."""
    assert "kimi" in harnesses.HARNESSES


# ── the wall-clock wall (4h) — an OUTCOME, never a silent kill ────────────────────────────────────

def test_a_timeout_becomes_a_non_zero_exit_not_an_exception(tmp_path):
    """`subprocess.TimeoutExpired` used to propagate out of the whole job, so a hung agent parked
    as a generic "errored" crash and the reason was lost — the tech-lead then diagnosed a crash
    that never happened. It is converted at the sandbox, in one place."""
    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.adapters.sandbox.timeouts import TIMEOUT_EXIT, timed_out
    from openfactory.adapters.sandbox.worktree import WorktreeSandbox

    ws = Workspace(path=tmp_path, host_path=tmp_path, branch="b", base_branch="main")
    code, out = WorktreeSandbox(root=tmp_path).run(
        workspace=ws, command="sleep 5", timeout=1)
    assert code == TIMEOUT_EXIT
    assert timed_out(code, out)
    assert "killed after 1s" in out


def test_the_wall_is_four_hours_and_shared_by_every_harness():
    """One concept, one number. It matters most for a harness with no turn cap: Claude stops on
    `--max-turns` first, Codex has no equivalent so this wall IS its bound."""
    from openfactory.adapters.agent import claude_code, codex, kimi, opencode
    from openfactory.adapters.sandbox.timeouts import AGENT_TIMEOUT

    assert AGENT_TIMEOUT == 4 * 60 * 60
    assert claude_code._EXECUTE_TIMEOUT == AGENT_TIMEOUT
    assert codex._TIMEOUT == AGENT_TIMEOUT
    assert kimi._TIMEOUT == AGENT_TIMEOUT
    assert opencode._TIMEOUT == AGENT_TIMEOUT


def test_hitting_the_wall_is_an_IMPEDIMENT_not_a_pause():
    """A rate-limit pause auto-resumes on a timer because the limit lifts by itself. A run that
    burned four hours does NOT get better by waiting — it must park for a human, with the cause
    in the text the tech-lead reads as the raw failure."""
    from openfactory.adapters.sandbox.timeouts import timeout_result

    code, out = timeout_result("codex exec ...", 4 * 60 * 60, "partial work")
    sb = _FakeSandbox(run_out=out, code=code)
    res = CodexAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx())

    assert res.ok is False
    assert res.pause_reason is None, "a wall-clock stop must not auto-resume on a timer"
    assert "4h wall" in res.summary
    assert "stuck, looping" in res.summary  # tells the human what to actually consider
    assert res.harness == "codex"


def test_the_partial_output_survives_the_wall():
    """On a four-hour run that partial output is often the only record of how far it got."""
    from openfactory.adapters.sandbox.timeouts import timeout_result

    _, out = timeout_result("kimi -p ...", 60, "IMPORTANT partial trace")
    assert "IMPORTANT partial trace" in out


# ── cost must read as UNKNOWN, never as free ─────────────────────────────────────────────────────

def _runner_with_runs(*costs):
    from openfactory.contracts import AgentRunMetric
    from openfactory.orchestrator import JobRunner

    r = JobRunner.__new__(JobRunner)
    r._agent_runs = [AgentRunMetric(role="executor", cost_usd=c) for c in costs]
    return r


def test_a_harness_that_reports_no_cost_shows_UNKNOWN_not_zero():
    """Codex reports tokens but no price. Summing with `cost or 0.0` made its tickets read
    $0.00 — free — so it would silently win every cost comparison. Unknown must read unknown."""
    assert _runner_with_runs(None, None, None)._reported_cost() is None


def test_partial_reporting_sums_only_what_was_reported():
    assert _runner_with_runs(0.5, None, 0.25)._reported_cost() == 0.75


def test_no_call_site_reintroduces_the_or_zero_accumulator():
    """The accessor is only half the fix if a later line overwrites what it returned.

    Two post-repair assignments still wrote the raw `cost or 0.0` accumulator back onto the result,
    so a cost-less harness read $0.00 again on exactly the jobs that needed a repair — the long,
    expensive ones. Every write of the ticket's cost has to go through the accessor.
    """
    import re
    from pathlib import Path

    src = Path("openfactory/orchestrator/machine.py").read_text()
    # the raw accumulator is the local `total_cost`; `result.total_cost_usd` is already the fixed
    # value being forwarded, which is fine
    offenders = re.findall(r"total_cost_usd\s*=\s*total_cost\b", src)
    assert not offenders, f"raw accumulator written back onto the ticket cost: {offenders}"


def test_a_genuinely_free_run_is_still_zero():
    """A reported 0.0 is a real measurement and must survive — the None case is the absence of a
    measurement, which is a different thing."""
    assert _runner_with_runs(0.0)._reported_cost() == 0.0


# ── the judging roles are ONE implementation over ask(), for every harness ───────────────────────

class _RecordingHarness:
    """A harness that only implements the read-only primitive — which is all a judging role
    needs. Records the prompts so the tests can assert the ROLE FILES reach the model."""

    name = "recording"

    def __init__(self, answer: str = "ok") -> None:
        self.prompts: list[str] = []
        self.answer = answer

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        from openfactory.contracts import AgentRunResult

        self.prompts.append(prompt)
        return AgentRunResult(ok=True, summary=self.answer)


def test_the_techlead_roles_carry_the_ROLE_FILES_not_adapter_prose():
    """The platform's opinion about how a tech lead behaves lives in org_defaults/roles/*.md and
    must reach every harness — otherwise a non-Claude deployment gets a different tech-lead."""
    from openfactory.adapters.agent.techlead import HarnessTechLead

    h = _RecordingHarness()
    tl = HarnessTechLead(h)
    tl.diagnose(sandbox=_FakeSandbox(), workspace=_ws(), situation="the push was rejected")
    tl.advise(sandbox=_FakeSandbox(), workspace=_ws(), situation="a parked decision")
    tl.chat(sandbox=_FakeSandbox(), workspace=_ws(), question="what is job 12 doing?")

    diagnose, advise, chat = h.prompts
    assert "Tech Lead" in diagnose or "tech lead" in diagnose
    assert "the push was rejected" in diagnose
    assert "a parked decision" in advise
    assert "what is job 12 doing?" in chat
    assert "fenced JSON" in chat or "no fenced" in chat  # a Slack answer is prose, not JSON


def test_the_sizer_sees_the_SPEC_only():
    """It judges the REQUEST, so it must not be handed plans, knowledge maps or guidelines — those
    would make a big ticket look small because the map made it look easy."""
    from openfactory.adapters.agent.techlead import HarnessTechLead

    h = _RecordingHarness()
    ctx = _ctx(plan="a detailed plan", knowledge_map="### app", guidelines=["100% coverage"])
    HarnessTechLead(h).size(sandbox=_FakeSandbox(), workspace=_ws(), context=ctx)

    prompt = h.prompts[0]
    assert "add health check" in prompt and "expose /health" in prompt
    assert "a detailed plan" not in prompt
    assert "### app" not in prompt
    assert "100% coverage" not in prompt


def test_any_harness_can_review_and_the_verdict_parses():
    from openfactory.adapters.reviewer.base import ReviewInput
    from openfactory.adapters.reviewer.harness import HarnessReviewer
    from openfactory.contracts import Ticket

    verdict = '{"decision": "rejected", "score": 40, "findings": [], "summary": "schema drift"}'
    h = _RecordingHarness(answer=f"Here you go:\n```json\n{verdict}\n```")
    ri = ReviewInput(ticket=Ticket(id="#1", title="t", objective="o", repo="o/r"),
                     diff="--- a\n+++ b\n+x = 1")
    res = HarnessReviewer(h).review(sandbox=_FakeSandbox(), workspace=_ws(), review_input=ri)

    assert res.decision == "rejected" and res.score == 40
    assert "You did NOT write this code" in h.prompts[0]
    assert "+x = 1" in h.prompts[0]  # the diff travels as TEXT — no workspace read needed


def test_an_unreadable_verdict_REJECTS_rather_than_approves():
    """A review that silently became an approval because the model rambled is how an unreviewed
    change lands looking reviewed."""
    from openfactory.adapters.reviewer.base import ReviewInput
    from openfactory.adapters.reviewer.harness import HarnessReviewer
    from openfactory.contracts import Ticket

    h = _RecordingHarness(answer="I think it's probably fine, honestly")
    ri = ReviewInput(ticket=Ticket(id="#1", title="t", objective="o", repo="o/r"), diff="x")
    res = HarnessReviewer(h).review(sandbox=_FakeSandbox(), workspace=_ws(), review_input=ri)
    assert res.decision == "rejected"
    assert "could not be parsed" in res.summary


def test_claude_keeps_its_PROVEN_role_implementations():
    """The generic `ask()` roles must not displace an implementation that already runs in production.

    Regression guard for a real near-miss: routing every harness through `HarnessReviewer` swapped
    the reviewer's invocation (`--output-format json`, envelope["result"]) for the generic one
    (`--output-format stream-json`, `_parse_stream`) — a different command AND a different parser on
    the path that had just caught 12 real findings on a live PR. Uniform code is not worth an
    unproven production path; the generic implementations exist for harnesses that have NOTHING.
    """
    from openfactory.adapters.agent import build_reviewer, build_techlead
    from openfactory.adapters.agent.claude_code import ClaudeCodeAdapter
    from openfactory.adapters.reviewer.claude_code import ClaudeCodeReviewer

    class P:
        harness = "claude_code"

    assert isinstance(build_techlead(P()), ClaudeCodeAdapter)
    assert isinstance(build_reviewer(P()), ClaudeCodeReviewer)


def test_a_harness_without_native_roles_still_gets_them():
    """…and the flip side: parity for everyone else is what the generic path is FOR."""
    from openfactory.adapters.agent import build_reviewer, build_techlead
    from openfactory.adapters.agent.techlead import HarnessTechLead
    from openfactory.adapters.reviewer.harness import HarnessReviewer

    class P:
        harness = "codex"

    assert isinstance(build_techlead(P()), HarnessTechLead)
    assert isinstance(build_reviewer(P()), HarnessReviewer)


def test_product_is_its_own_harness_axis(monkeypatch):
    """ADR-0019: the product module is opt-in AND separately configurable. The tech-lead reasons
    about a failure in a codebase; the product role about whether a request contradicts something
    the product already promises. A deployment may reasonably want a different engine for each."""
    _clear(monkeypatch)
    p = _project(harness={"executor": "claude_code", "product": "codex"})
    assert harnesses.harness_kind(p, "executor") == "claude_code"
    assert harnesses.harness_kind(p, "product") == "codex"
    assert type(harnesses.build_product(p)).__name__ == "CodexAdapter"


def test_a_harness_that_cannot_judge_cannot_be_the_product_role(monkeypatch):
    """Same build-time check as the other judging roles: a misconfiguration must surface when the
    module starts, not when someone asks a question in Slack and gets silence."""
    _clear(monkeypatch)

    class _Mute:
        name = "mute"

    monkeypatch.setitem(harnesses.HARNESSES, "mute", lambda **kw: _Mute())
    with pytest.raises(ValueError, match="cannot serve the product role"):
        harnesses.build_product(_project(harness="mute"))


def test_every_phase_whose_output_a_HUMAN_reads_is_localised():
    """A phase missing from this set produces its prose in whatever language the model prefers.
    `product_triage` returns JSON, which looks exempt — but its `reason` and `fix` are pasted
    straight into a comment a person reads, so it produced an English sentence inside a Portuguese
    template."""
    import re
    from pathlib import Path

    from openfactory.adapters.agent.roles import HUMAN_PHASES

    src = Path("openfactory/product/module.py").read_text() + Path("openfactory/product/role.py").read_text()
    used = set(re.findall(r'phase="(product_\w+)"', src))
    assert used, "no product phases found — the scan is looking in the wrong place"
    assert used <= HUMAN_PHASES, f"not localised: {sorted(used - HUMAN_PHASES)}"


def test_an_auth_failure_the_pool_cannot_SEE_is_a_pool_that_cannot_fail_over():
    """Observed in production 2026-07-27, and the reason a two-token pool behaved like no pool.

    Rotation is gated on the failure being classified:

        paused = res.pause_reason in ("rate_limit", "auth")
        if not (paused and attempts < n): break

    So an auth failure nobody recognises does not merely produce a bad message — it ends the loop
    after ONE attempt and the remaining credentials are never tried. The message that did it says
    nothing about tokens, keys or 401s.
    """
    from openfactory.adapters.agent.claude_code import _detect_pause

    real = ("Your organization has disabled Claude subscription access for Claude Code · "
            "Use an Anthropic API key instead, or ask your admin to enable access")
    assert _detect_pause(real) == ("auth", None)


@pytest.mark.parametrize("message", [
    "Invalid API key · Please run /login",
    "401 Unauthorized",
    "your credit balance is too low",
    "expired token",
    "Use an Anthropic API key instead",
    "ask your admin to enable access",
])
def test_every_shape_of_auth_failure_reaches_the_failover(message):
    from openfactory.adapters.agent.claude_code import _detect_pause

    assert _detect_pause(message)[0] == "auth", message


def test_an_agents_own_prose_about_auth_is_not_a_pause():
    """`_detect_pause` runs only on error envelopes precisely so a ticket ABOUT authentication does
    not park the job that implements it — widening the pattern must not break that."""
    from openfactory.adapters.agent.claude_code import _parse_stream

    healthy = ('{"type":"result","subtype":"success","result":'
               '"Added the login screen and handled an expired token","is_error":false}')
    assert _parse_stream(0, healthy).pause_reason is None


# ── the false pause, swept across the class (C-38) ───────────────────────────────────────────────

def test_no_adapter_reads_a_STREAM_EVENT_when_it_looks_for_a_rate_limit():
    """Found on OpenCode by replaying a real run, then found identical in `codex` and `kimi` —
    copied between adapters exactly as the bug was.

    Each text-matched `429`/`401`/`403` over the RAW output, which carries generated ids
    (`prt_fd2a429fe...`, codex's `thread_id`) AND the agent's own tool output. A client whose code
    handles HTTP 429 — any rate-limiting library — would park its own jobs by writing about the
    number, and the retry would be scheduled against a limit nobody hit.

    The guard follows the ASSIGNMENT, not the call site: every adapter searches a local named
    `tail`, so checking the argument alone would pass whatever that name was bound to."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for kind in sorted(harnesses.HARNESSES):
        path = root / f"openfactory/adapters/agent/{kind}.py"
        src = path.read_text()
        if "_RATE_RE" not in src and "_AUTH_RE" not in src:
            continue  # this adapter detects pauses structurally; nothing to guard
        tree = ast.parse(src)

        # names bound to something that went through the filter
        cleaned = {
            t.id
            for node in ast.walk(tree) if isinstance(node, ast.Assign)
            for t in node.targets
            if isinstance(t, ast.Name) and "prose_only" in ast.unparse(node.value)
        }
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "search"):
                continue
            if getattr(getattr(node.func, "value", None), "id", "") not in ("_RATE_RE", "_AUTH_RE"):
                continue
            text = ast.unparse(node.args[0]) if node.args else ""
            # safe: already filtered, bound to a filtered name, or a field of a PARSED event
            if "prose_only" in text or text in cleaned or "message" in text:
                continue
            offenders.append(f"{kind}.py:{node.lineno} — searches {text!r}")
    assert offenders == [], (
        "a pause detector reads the raw stream, so an id or the agent's own output can park a "
        "healthy job:\n  " + "\n  ".join(offenders)
    )
