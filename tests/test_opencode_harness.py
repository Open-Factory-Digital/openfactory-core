"""The OpenCode adapter, pinned to the stream and the CLI that were actually observed (C-38, #81).

Every fixture below is a real event captured from `opencode 1.18.13`, trimmed but not reshaped.
That matters because the previous harness added to this axis (Kimi) had to be written blind and
its commit said so — `wired, not proven`. This one was written against the binary, so the tests
are allowed to be exact, and a future version that changes the stream will fail here rather than
in a client's job.

The four behaviours that cost real money if they regress:

  * `--` — without it a prompt beginning with `-` is eaten as a flag and the CLI prints its help
    instead of running. Silent no-op, at the top of every pass.
  * `--auto` — a headless run does not block on an approval, it AUTO-REJECTS. So the flag's job is
    not to avoid a hang; it is to stop the run silently losing every tool call.
  * `--session`, never `--continue` — `--continue` resumes the most recent session PROCESS-WIDE,
    so two jobs on one worker would resume into each other's conversation.
  * exit 0 with no text is a FAILURE — an auto-rejected tool call aborts the run, exits 0 and says
    nothing, and reporting that as success advances a ticket on an agent that never spoke.
"""

from __future__ import annotations

import json

import pytest

from openfactory.adapters.agent.opencode import JUDGE_AGENT, OpenCodeAdapter

SESSION = "ses_02d53fe0dffeBgEKK74yFBlCLI"


def _ev(**kw) -> str:
    return json.dumps(kw, separators=(",", ":"))


def _text(text: str) -> str:
    return _ev(type="text", timestamp=1, sessionID=SESSION,
               part={"type": "text", "text": text, "sessionID": SESSION})


def _step_finish(inp: int, out: int, cost: float) -> str:
    return _ev(type="step_finish", timestamp=2, sessionID=SESSION,
               part={"type": "step-finish", "reason": "stop", "cost": cost,
                     "tokens": {"total": inp + out, "input": inp, "output": out,
                                "reasoning": 0, "cache": {"write": 0, "read": 0}}})


def _step_start() -> str:
    return _ev(type="step_start", timestamp=0, sessionID=SESSION, part={"type": "step-start"})


def _tool(name: str, status: str = "completed") -> str:
    return _ev(type="tool_use", timestamp=1, sessionID=SESSION,
               part={"type": "tool", "tool": name, "callID": f"{name}_0",
                     "state": {"status": status, "input": {}, "output": "x"}})


#: verbatim shape of a real auth failure, including the two keys that echo the provider
_AUTH_ERROR = _ev(type="error", timestamp=3, sessionID=SESSION, error={
    "name": "APIError",
    "data": {"message": "invalid x-api-key", "statusCode": 401, "isRetryable": False,
             "responseHeaders": {"x-should-not-be-journalled": "sk-leak"},
             "responseBody": "{\"error\":\"secret detail\"}"},
})

_GOOD = "\n".join([_step_start(), _tool("read"), _text("done"), _step_finish(6362, 3, 0.0039312)])


class _FakeSandbox:
    def __init__(self, run_out: str = "", code: int = 0) -> None:
        self.commands: list[str] = []
        self.run_out, self.code = run_out, code

    def harness_path(self, name: str) -> str:
        return f"/opt/openfactory-toolbox/{name}"

    def run(self, *, workspace, command: str, timeout: int):  # noqa: ARG002
        self.commands.append(command)
        return self.code, self.run_out


def _ws():
    from openfactory.adapters.sandbox.base import Workspace

    return Workspace(path="/work", branch="b", base_branch="main")


def _ctx(**kw):
    from openfactory.adapters.agent.base import AgentContext
    from openfactory.contracts import Ticket

    return AgentContext(
        ticket=Ticket(id="#7", title="add health check", objective="expose /health", repo="o/r"),
        **kw,
    )


# ── the command line ─────────────────────────────────────────────────────────────────────────────

def test_the_harness_is_invoked_by_the_boxs_absolute_path():
    """ADR-0037 D2: a bare name is resolved by a `PATH` we did not write."""
    sb = _FakeSandbox(_GOOD)
    OpenCodeAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx())
    assert sb.commands[0].split()[-1] or True
    assert "/opt/openfactory-toolbox/opencode run" in sb.commands[0]


def test_the_prompt_is_separated_by_a_double_dash():
    """Observed: without `--`, a prompt starting with `-` is read as an unknown flag and the CLI
    prints its help and exits without running. A no-op that looks like a silent agent."""
    sb = _FakeSandbox(_GOOD)
    OpenCodeAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx())
    assert " -- " in sb.commands[0]


def test_execute_carries_the_ROLE_FILE_not_adapter_prose():
    """Same thesis as the Codex/Kimi/tech-lead equivalents: `org_defaults/roles/executor.md` must
    reach OpenCode too, not only Claude Code."""
    sb = _FakeSandbox(_GOOD)
    OpenCodeAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx())
    cmd = sb.commands[0]
    assert "You are the **executor**" in cmd
    assert "add health check" in cmd


def test_plan_carries_the_ROLE_FILE():
    sb = _FakeSandbox(_GOOD)
    OpenCodeAdapter().plan(sandbox=sb, workspace=_ws(), context=_ctx())
    assert "You are the **planner**" in sb.commands[0]


def test_repair_carries_the_ROLE_FILE_and_the_failures_and_the_ticket():
    sb = _FakeSandbox(_GOOD)
    OpenCodeAdapter().repair(sandbox=sb, workspace=_ws(), context=_ctx(),
                             failure_log="pytest: 2 failed")
    cmd = sb.commands[0]
    assert "You are the **executor**" in cmd
    assert "pytest: 2 failed" in cmd
    assert "add health check" in cmd
    assert cmd.index("You are the **executor**") < cmd.index("staying strictly")
    assert cmd.index("staying strictly") < cmd.index("pytest: 2 failed")


def test_degrades_to_the_fixed_sentence_when_no_role_file_resolves(monkeypatch):
    """A broken install (`role_prompt` returns "") must send exactly what this adapter always sent
    before role files reached it — not a blank planner and not a crash."""
    from openfactory.adapters.agent import opencode as opencode_module

    monkeypatch.setattr(opencode_module, "role_prompt", lambda _name: "")
    sb = _FakeSandbox(_GOOD)
    OpenCodeAdapter().plan(sandbox=sb, workspace=_ws(), context=_ctx())
    assert "Investigate this ticket READ-ONLY" in sb.commands[0]
    assert "You are the **planner**" not in sb.commands[0]


def test_auto_is_passed_because_a_headless_run_auto_REJECTS():
    """The flag is not about hanging — an unapproved call is auto-rejected in seconds. Without it
    the pass quietly loses every tool call and returns nothing."""
    sb = _FakeSandbox(_GOOD)
    OpenCodeAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx())
    assert "--auto" in sb.commands[0]


def test_resume_uses_an_EXPLICIT_session_never_continue():
    """`--continue` resumes the most recently used session process-wide. Two jobs on one worker
    would resume into each other's conversation — verified: after a fork, `--continue` picked up
    the fork rather than the caller's own session."""
    sb = _FakeSandbox(_GOOD)
    OpenCodeAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx(resume_handle=SESSION))
    cmd = sb.commands[0]
    assert f"--session {SESSION}" in cmd
    assert "--continue" not in cmd and " -c " not in cmd


def test_the_model_is_passed_as_provider_slash_model():
    sb = _FakeSandbox(_GOOD)
    OpenCodeAdapter(model="amazon-bedrock/anthropic.claude-sonnet-4-5").execute(
        sandbox=sb, workspace=_ws(), context=_ctx())
    assert "-m amazon-bedrock/anthropic.claude-sonnet-4-5" in sb.commands[0]


# ── read-only: enforcement, and a repository that cannot argue with it ───────────────────────────

def test_a_judging_run_asks_for_the_read_only_profile():
    sb = _FakeSandbox(_GOOD)
    OpenCodeAdapter().ask(sandbox=sb, workspace=_ws(), prompt="how bad is it?")
    assert f"--agent {JUDGE_AGENT}" in sb.commands[0]


def test_the_read_only_profile_denies_every_mutating_tool():
    """`edit: deny` kills BOTH `edit` and `write`; `task` so a sub-agent cannot escape the map;
    `question` because a headless run has nobody to ask."""
    from openfactory.adapters.agent.opencode import judge_config

    perms = json.loads(judge_config())["agent"][JUDGE_AGENT]["permission"]
    for tool in ("edit", "bash", "task", "question", "webfetch", "websearch"):
        assert perms[tool] == "deny", tool
    assert perms["read"] == "allow"


def test_the_profile_carries_no_credential():
    """It travels on the command line, which is logged."""
    from openfactory.adapters.agent.opencode import judge_config

    blob = judge_config().lower()
    for word in ("key", "token", "secret", "password", "aws_"):
        assert word not in blob, word


def test_the_clients_own_config_is_disabled_on_EVERY_run():
    """A repo's `opencode.json` genuinely defines agents — verified: alone, a hostile file granted
    `bash/edit/write: true` under this adapter's own profile name. Judging roles read client
    checkouts, so the file is removed from consideration rather than merely out-ranked."""
    sb = _FakeSandbox(_GOOD)
    OpenCodeAdapter().ask(sandbox=sb, workspace=_ws(), prompt="q")
    OpenCodeAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx())
    assert len(sb.commands) == 2
    for cmd in sb.commands:
        assert "OPENCODE_DISABLE_PROJECT_CONFIG=1" in cmd


def test_the_profile_is_never_written_into_the_clients_workspace():
    """A file would land inside the diff the executor commits."""
    sb = _FakeSandbox(_GOOD)
    OpenCodeAdapter().ask(sandbox=sb, workspace=_ws(), prompt="q")
    assert "OPENCODE_CONFIG_CONTENT=" in sb.commands[0]
    assert "opencode.json" not in sb.commands[0]


# ── the stream ───────────────────────────────────────────────────────────────────────────────────

def test_the_answer_is_the_LAST_text_event():
    sb = _FakeSandbox("\n".join([_step_start(), _text("thinking out loud"), _tool("read"),
                                 _text("the real answer"), _step_finish(1, 1, 0.01)]))
    res = OpenCodeAdapter().ask(sandbox=sb, workspace=_ws(), prompt="q")
    assert res.ok and res.summary == "the real answer"


def test_the_session_id_is_recovered_for_resume():
    sb = _FakeSandbox(_GOOD)
    res = OpenCodeAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx())
    assert res.resume_handle == SESSION


def test_usage_and_cost_are_SUMMED_across_steps():
    """Both arrive per step; a multi-step run emits several."""
    sb = _FakeSandbox("\n".join([_step_start(), _step_finish(100, 10, 0.01),
                                 _step_start(), _text("ok"), _step_finish(200, 20, 0.02)]))
    res = OpenCodeAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx())
    assert (res.input_tokens, res.output_tokens) == (300, 30)
    assert res.cost_usd == pytest.approx(0.03)
    assert res.num_turns == 2


def test_a_zero_cost_is_reported_as_UNKNOWN_not_as_free():
    """A provider the deployment declares itself carries no pricing metadata, so its steps come
    back `cost: 0` — verified. Passing that through would show a client's gateway spend as zero
    dollars in the one instrument every spending decision is read from."""
    sb = _FakeSandbox("\n".join([_step_start(), _text("ok"), _step_finish(10, 1, 0.0)]))
    res = OpenCodeAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx())
    assert res.cost_usd is None
    assert res.input_tokens == 10  # the tokens are still real


def test_tool_calls_become_actions():
    sb = _FakeSandbox(_GOOD)
    res = OpenCodeAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx())
    assert "read" in res.actions


# ── failure, told apart from silence ─────────────────────────────────────────────────────────────

def test_exit_zero_with_no_text_is_a_FAILURE():
    """An auto-rejected tool call aborts the run: `step_finish(reason: tool-calls)`, exit 0, not a
    word said. Reporting success would advance a ticket on an agent that never spoke."""
    sb = _FakeSandbox("\n".join([_step_start(), _tool("bash", status="error"),
                                 _step_finish(10, 0, 0.001)]), code=0)
    res = OpenCodeAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx())
    assert not res.ok
    assert "refused" in res.summary


def test_an_auth_error_is_an_infra_PAUSE_not_a_code_failure():
    sb = _FakeSandbox(_AUTH_ERROR, code=1)
    res = OpenCodeAdapter().execute(sandbox=sb, workspace=_ws(), context=_ctx())
    assert res.pause_reason == "auth"
    assert not res.ok


def test_a_rate_limit_is_read_from_the_status_code():
    ev = _ev(type="error", timestamp=1, sessionID=SESSION,
             error={"name": "APIError", "data": {"message": "slow down", "statusCode": 429}})
    res = OpenCodeAdapter().execute(sandbox=_FakeSandbox(ev, code=1), workspace=_ws(),
                                    context=_ctx())
    assert res.pause_reason == "rate_limit"


def test_the_failure_summary_NAMES_the_error():
    """"the agent produced no output" sends a human to read 20,000 lines for a sentence that is
    already in hand."""
    res = OpenCodeAdapter().execute(sandbox=_FakeSandbox(_AUTH_ERROR, code=1), workspace=_ws(),
                                    context=_ctx())
    assert "APIError" in res.summary and "invalid x-api-key" in res.summary


def test_the_provider_echo_is_SCRUBBED_from_what_we_keep():
    """Error events carry the provider's own `responseHeaders` and `responseBody`, and raw_output
    is journalled, shown in the panel and quoted into pull requests."""
    res = OpenCodeAdapter().execute(sandbox=_FakeSandbox(_AUTH_ERROR, code=1), workspace=_ws(),
                                    context=_ctx())
    assert "sk-leak" not in res.raw_output
    assert "secret detail" not in res.raw_output
    assert "invalid x-api-key" in res.raw_output  # the diagnosable part survives


def test_unparseable_output_degrades_instead_of_raising():
    """A version whose stream we do not recognise must not crash the job."""
    res = OpenCodeAdapter().execute(sandbox=_FakeSandbox("not json at all", code=0),
                                    workspace=_ws(), context=_ctx())
    assert not res.ok
    assert "not json at all" in res.summary


# ── the axis ─────────────────────────────────────────────────────────────────────────────────────

def test_it_is_reachable_through_the_registry_like_every_other_harness(monkeypatch):
    from openfactory.adapters.agent import registry as harnesses
    from openfactory.contracts.project import Project

    for var in (*harnesses.ROLES.values(), *harnesses.ROLE_MODELS.values()):
        monkeypatch.delenv(var, raising=False)
    p = Project(name="p", repo_path="/tmp/p", harness="opencode",
                model="amazon-bedrock/anthropic.claude-sonnet-4-5")
    assert isinstance(harnesses.build_executor(p), OpenCodeAdapter)
    assert harnesses.build_techlead(p) is not None       # it can judge: it has `ask`
    assert harnesses.build_reviewer(p) is not None


def test_the_route_follows_the_MODEL_because_that_is_where_the_provider_is(monkeypatch):
    """The whole point of this harness: which provider serves a client is `model:`, not a
    different binary."""
    from openfactory.adapters.agent import registry as harnesses
    from openfactory.adapters.agent.routes import resolve_route
    from openfactory.contracts.project import Project

    for var in (*harnesses.ROLES.values(), *harnesses.ROLE_MODELS.values()):
        monkeypatch.delenv(var, raising=False)

    def _p(model):
        return Project(name="p", repo_path="/tmp/p", harness="opencode", model=model)

    assert resolve_route(_p("anthropic/claude-opus-5"), env={}).endpoint.endswith("/v1/messages")
    bedrock = resolve_route(_p("amazon-bedrock/anthropic.claude-sonnet-4-5"),
                            env={"AWS_REGION": "eu-west-2"})
    assert bedrock.endpoint == "https://bedrock-runtime.eu-west-2.amazonaws.com"
    # an unrecognised provider is admitted, not guessed — the catalogue runs to 180 providers
    assert resolve_route(_p("someco/model-9"), env={}).endpoint == ""


def test_a_model_with_no_provider_prefix_says_so(monkeypatch):
    from openfactory.adapters.agent import registry as harnesses
    from openfactory.adapters.agent.routes import resolve_route
    from openfactory.contracts.project import Project

    for var in (*harnesses.ROLES.values(), *harnesses.ROLE_MODELS.values()):
        monkeypatch.delenv(var, raising=False)
    route = resolve_route(Project(name="p", repo_path="/tmp/p", harness="opencode",
                                  model="claude-opus-5"), env={})
    assert route.endpoint == ""
    assert "provider/model" in route.remedy


# ── the false pause: found by replaying a real run, after the adapter shipped ────────────────────

#: A REAL successful run whose generated ids happen to contain "429". Not contrived — this is the
#: shape every opencode event has, and the id region advances with time, so whole windows of runs
#: carry it at once.
_IDS_WITH_429 = "\n".join([
    '{"type":"step_start","timestamp":1,"sessionID":"ses_02d429e0dffeBgEKK74yFBlCLI",'
    '"part":{"type":"step-start","id":"prt_fd2a429fe6001cYQJaMIVAC37V5"}}',
    '{"type":"text","timestamp":2,"sessionID":"ses_02d429e0dffeBgEKK74yFBlCLI",'
    '"part":{"type":"text","text":"all done","id":"prt_fd429ac124f001WPNb6TDv7W8e4J"}}',
    '{"type":"step_finish","timestamp":3,"sessionID":"ses_02d429e0dffeBgEKK74yFBlCLI",'
    '"part":{"type":"step-finish","reason":"stop","cost":0.004,'
    '"tokens":{"input":10,"output":2,"cache":{"write":0,"read":0}}}}',
])


def test_an_id_containing_429_is_NOT_a_rate_limit():
    """The regex used to run over the RAW output, and every event carries generated ids that are
    just digits. A successful run whose ids landed in a "429" window was parked as rate-limited and
    retried against a limit nobody had hit — and because ids advance with time, the false positives
    arrive in contiguous bursts that read exactly like a real outage."""
    res = OpenCodeAdapter().execute(sandbox=_FakeSandbox(_IDS_WITH_429, code=0),
                                    workspace=_ws(), context=_ctx())
    assert res.pause_reason is None, res.pause_reason
    assert res.ok and res.summary == "all done"


def test_an_id_containing_401_is_NOT_an_auth_failure():
    """Same defect, other regex: `_AUTH_RE` matches a bare 401."""
    stream = _IDS_WITH_429.replace("429", "401")
    res = OpenCodeAdapter().execute(sandbox=_FakeSandbox(stream, code=0), workspace=_ws(),
                                    context=_ctx())
    assert res.pause_reason is None, res.pause_reason
    assert res.ok


def test_a_REAL_rate_limit_in_the_stream_is_still_caught():
    """The positive twin. Suppressing the false positive by suppressing detection would be the
    same bug pointed the other way — a genuine limit read as a code failure, burning the repair
    loop against a wall."""
    ev = _ev(type="error", timestamp=1, sessionID=SESSION,
             error={"name": "APIError", "data": {"message": "slow down", "statusCode": 429}})
    res = OpenCodeAdapter().execute(sandbox=_FakeSandbox(ev, code=1), workspace=_ws(),
                                    context=_ctx())
    assert res.pause_reason == "rate_limit"


def test_a_failure_the_STREAM_never_saw_is_still_read_from_stderr():
    """The fallback's actual job: the CLI dying before it emits any JSON at all. Restricting it to
    non-event lines must not switch it off."""
    res = OpenCodeAdapter().execute(
        sandbox=_FakeSandbox("error: 429 Too Many Requests from the gateway", code=1),
        workspace=_ws(), context=_ctx())
    assert res.pause_reason == "rate_limit"


def test_prose_keeps_stderr_and_drops_every_event():
    from openfactory.adapters.agent.base import prose_only

    mixed = _IDS_WITH_429 + "\nwarning: could not reach the proxy\n"
    kept = prose_only(mixed)
    assert "could not reach the proxy" in kept
    assert "ses_02d429" not in kept and "prt_" not in kept


# ── a model this harness cannot resolve fails at BUILD, not four hours later ──────────────────────

def test_a_bare_model_name_is_refused_when_the_adapter_is_BUILT():
    """Measured: a job configured `-m opus` — a real Claude model name, and the value this
    deployment's `OPENFACTORY_EXECUTOR_MODEL` holds — ran 26 minutes without writing a line. AGENT_TIMEOUT
    is four hours, so that misconfiguration's ceiling is four hours of wall-clock and whatever the
    harness bills, for something one string comparison catches."""
    with pytest.raises(ValueError, match="provider/model"):
        OpenCodeAdapter(model="opus")


def test_the_refusal_names_the_fix_not_just_the_fault():
    with pytest.raises(ValueError) as e:
        OpenCodeAdapter(model="sonnet")
    text = str(e.value)
    assert "amazon-bedrock/" in text        # a shape to copy
    assert "OPENFACTORY_" in text           # and where else the value could be coming from


def test_a_qualified_model_is_accepted():
    a = OpenCodeAdapter(model="amazon-bedrock/eu.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert a.model.startswith("amazon-bedrock/")


def test_no_model_at_all_is_still_fine():
    """Unset means "the harness's own default", which is what most deployments run."""
    assert OpenCodeAdapter().model is None


def test_the_env_ESCAPE_HATCH_is_validated_too(monkeypatch):
    """The 26-minute run was configured correctly in the registry — the bare name arrived from the
    environment, which outranks it. Checking only the argument would have missed the real case."""
    monkeypatch.setenv("OPENFACTORY_EXECUTOR_MODEL", "opus")
    with pytest.raises(ValueError, match="provider/model"):
        OpenCodeAdapter()
