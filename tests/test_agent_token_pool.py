"""Agent credential pool with rate-limit / auth failover (claude_code adapter).

One exhausted or revoked token must fail over to the next instead of halting the job;
only when the whole pool is spent does the pause survive. A single token behaves exactly
as before.
"""

from __future__ import annotations

import json
import os

from openfactory.adapters.agent.claude_code import ClaudeCodeAdapter, _load_agent_token_pool
from openfactory.contracts import AgentRunResult


def test_pool_parses_json_array(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_AGENT_TOKENS", json.dumps(
        [{"id": "a", "token": "tok-a"}, {"id": "b", "token": "tok-b", "type": "api"}]))
    pool = _load_agent_token_pool()
    assert [p["id"] for p in pool] == ["a", "b"]
    assert pool[0]["type"] == "subscription"  # default
    assert pool[1]["type"] == "api"


def test_pool_falls_back_to_single_subscription(monkeypatch):
    monkeypatch.delenv("OPENFACTORY_AGENT_TOKENS", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "solo")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert _load_agent_token_pool() == [{"id": "single", "token": "solo", "type": "subscription"}]


def test_pool_malformed_degrades_to_single(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_AGENT_TOKENS", "{not json")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "solo")
    assert _load_agent_token_pool()[0]["token"] == "solo"


def test_pool_empty_when_nothing(monkeypatch):
    for v in ("OPENFACTORY_AGENT_TOKENS", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    assert _load_agent_token_pool() == []


def test_failover_rotates_on_rate_limit(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_AGENT_TOKENS", json.dumps(
        [{"id": "a", "token": "ta"}, {"id": "b", "token": "tb"}]))
    a = ClaudeCodeAdapter()
    seen: list[str] = []

    def fake_once(sandbox, workspace, prompt, phase, *, tools, model, context, resume_session=""):
        seen.append(os.environ["CLAUDE_CODE_OAUTH_TOKEN"])  # active token this attempt
        return (AgentRunResult(ok=False, pause_reason="rate_limit") if len(seen) == 1
                else AgentRunResult(ok=True, summary="done"))

    monkeypatch.setattr(a, "_invoke_once", fake_once)
    res = a._invoke(None, None, "p", "execute", tools=[], model=None, context=None)
    assert res.ok
    assert seen == ["ta", "tb"]  # rotated a → b, applying each token in turn
    assert a._ti == 1


def test_failover_exhausts_then_pauses(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_AGENT_TOKENS", json.dumps(
        [{"id": "a", "token": "ta"}, {"id": "b", "token": "tb"}]))
    a = ClaudeCodeAdapter()
    monkeypatch.setattr(a, "_invoke_once",
                        lambda *a, **k: AgentRunResult(ok=False, pause_reason="rate_limit"))
    res = a._invoke(None, None, "p", "execute", tools=[], model=None, context=None)
    assert res.pause_reason == "rate_limit"  # every token spent → pause survives
    assert a._ti == 1  # tried both


def test_single_token_no_rotation(monkeypatch):
    monkeypatch.delenv("OPENFACTORY_AGENT_TOKENS", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "solo")
    a = ClaudeCodeAdapter()
    monkeypatch.setattr(a, "_invoke_once",
                        lambda *a, **k: AgentRunResult(ok=False, pause_reason="rate_limit"))
    res = a._invoke(None, None, "p", "execute", tools=[], model=None, context=None)
    assert res.pause_reason == "rate_limit"
    assert a._ti == 0  # nothing to rotate to


def test_failover_is_cyclic_wraps_back_to_the_first(monkeypatch):
    # The rotation must be a CYCLE, not linear (user-reported): a job whose sticky index is on
    # the LAST token must still wrap around and try the earlier ones in the same lap, rather than
    # giving up immediately because "there's no next token".
    monkeypatch.setenv("OPENFACTORY_AGENT_TOKENS", json.dumps(
        [{"id": "a", "token": "ta"}, {"id": "b", "token": "tb"}, {"id": "c", "token": "tc"}]))
    a = ClaudeCodeAdapter()
    a._ti = 2  # start on the LAST token (a prior phase left us here)
    seen: list[str] = []

    def fake_once(*ar, **k):
        seen.append(os.environ["CLAUDE_CODE_OAUTH_TOKEN"])
        return AgentRunResult(ok=False, pause_reason="rate_limit")

    monkeypatch.setattr(a, "_invoke_once", fake_once)
    res = a._invoke(None, None, "p", "execute", tools=[], model=None, context=None)
    assert res.pause_reason == "rate_limit"
    assert seen == ["tc", "ta", "tb"]  # c → wrap to a → b — a full lap, every token once
    # and never retries a token within the lap (retrying an as-yet-unreset one is pointless)
    assert len(seen) == 3


def test_failover_continues_the_session_on_the_next_token(monkeypatch):
    # The heart of the user's ask: rotating must CONTINUE the work (--resume the same session),
    # never replan/redo — otherwise the fresh token is drained repeating what's already done.
    monkeypatch.setenv("OPENFACTORY_AGENT_TOKENS", json.dumps(
        [{"id": "a", "token": "ta"}, {"id": "b", "token": "tb"}]))
    a = ClaudeCodeAdapter()
    resumes: list[str] = []

    def fake_once(sandbox, workspace, prompt, phase, *, tools, model, context, resume_session=""):
        resumes.append(resume_session)
        if len(resumes) == 1:  # token a did most of the work, then hit the limit
            return AgentRunResult(ok=False, pause_reason="rate_limit", resume_handle="sess-80pct")
        return AgentRunResult(ok=True, summary="finished the remaining 20%")

    monkeypatch.setattr(a, "_invoke_once", fake_once)
    res = a._invoke(None, None, "p", "execute", tools=[], model=None, context=None)
    assert res.ok
    # token a started cold; token b RESUMED a's session instead of starting over
    assert resumes == ["", "sess-80pct"]


def test_credential_reports_active_token_no_rotation(monkeypatch):
    # A (partner-requested visibility): every result carries WHICH credential of the pool
    # produced it, so the panel can show "credential 1/2" and prove which token is live.
    monkeypatch.setenv("OPENFACTORY_AGENT_TOKENS", json.dumps(
        [{"id": "a", "token": "ta"}, {"id": "b", "token": "tb"}]))
    a = ClaudeCodeAdapter()
    monkeypatch.setattr(a, "_invoke_once",
                        lambda *a, **k: AgentRunResult(ok=True, summary="done"))
    res = a._invoke(None, None, "p", "execute", tools=[], model=None, context=None)
    assert res.credential == {"index": 1, "total": 2, "id": "a", "rotated": False}


def test_credential_marks_rotation_after_failover(monkeypatch):
    # When a token rotates mid-invocation, the credential telemetry reflects the token that
    # actually SUCCEEDED and flags that failover happened (proof rotation is real).
    monkeypatch.setenv("OPENFACTORY_AGENT_TOKENS", json.dumps(
        [{"id": "a", "token": "ta"}, {"id": "b", "token": "tb"}]))
    a = ClaudeCodeAdapter()
    calls = {"n": 0}

    def fake_once(*a, **k):
        calls["n"] += 1
        return (AgentRunResult(ok=False, pause_reason="rate_limit") if calls["n"] == 1
                else AgentRunResult(ok=True, summary="done"))

    monkeypatch.setattr(a, "_invoke_once", fake_once)
    res = a._invoke(None, None, "p", "execute", tools=[], model=None, context=None)
    assert res.credential == {"index": 2, "total": 2, "id": "b", "rotated": True}


def test_credential_absent_for_keyless_adapter(monkeypatch):
    # No pool (keyless/other adapter shape) → no credential telemetry, never a crash.
    for v in ("OPENFACTORY_AGENT_TOKENS", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    a = ClaudeCodeAdapter()
    monkeypatch.setattr(a, "_invoke_once",
                        lambda *a, **k: AgentRunResult(ok=True, summary="done"))
    res = a._invoke(None, None, "p", "execute", tools=[], model=None, context=None)
    assert res.credential is None


def test_mixed_lap_rate_limit_survives_over_auth(monkeypatch):
    # Audit HIGH: token a rate-limits (resumable), token b is REVOKED (auth). Last-writer-wins
    # would end the lap as "auth" → ON_HOLD forever, discarding a job that would auto-resume on
    # a's reset. Any rate-limited token in the lap must keep the pause resumable.
    monkeypatch.setenv("OPENFACTORY_AGENT_TOKENS", json.dumps(
        [{"id": "a", "token": "ta"}, {"id": "b", "token": "tb"}]))
    a = ClaudeCodeAdapter()
    calls = {"n": 0}

    def fake_once(*ar, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return AgentRunResult(ok=False, pause_reason="rate_limit", retry_at="17:00")
        return AgentRunResult(ok=False, pause_reason="auth")

    monkeypatch.setattr(a, "_invoke_once", fake_once)
    res = a._invoke(None, None, "p", "execute", tools=[], model=None, context=None)
    assert res.pause_reason == "rate_limit"  # resumable wins over the revoked token
    assert res.retry_at == "17:00"  # the rate-limited token's reset survives too


def test_lap_snapshot_uses_accumulated_session_when_last_attempt_has_none(monkeypatch):
    # Audit HIGH: token a pauses WITH a session id; token b dies before emitting any JSON (no
    # session). The exit must still encode a's session into the handle — not throw it away.
    monkeypatch.setenv("OPENFACTORY_AGENT_TOKENS", json.dumps(
        [{"id": "a", "token": "ta"}, {"id": "b", "token": "tb"}]))
    monkeypatch.delenv("OPENFACTORY_RESUME_BUCKET", raising=False)  # snapshot off; handle still encodes
    a = ClaudeCodeAdapter()
    calls = {"n": 0}

    def fake_once(*ar, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return AgentRunResult(ok=False, pause_reason="rate_limit", resume_handle="sess-80")
        return AgentRunResult(ok=False, pause_reason="rate_limit", resume_handle="")

    monkeypatch.setattr(a, "_invoke_once", fake_once)
    from openfactory.adapters.agent.base import AgentContext
    from openfactory.contracts import AcceptanceCriterion, Ticket
    ctx = AgentContext(ticket=Ticket(id="#9", title="x", objective="x", repo="o/app",
                                     acceptance_criteria=[AcceptanceCriterion(text="c")]))
    res = a._invoke(None, None, "p", "execute", tools=[], model=None, context=ctx)
    from openfactory.adapters.agent.claude_code import _decode_handle
    d = _decode_handle(res.resume_handle)
    assert d and d["session"] == "sess-80"  # the lap-accumulated session survived


def test_pause_not_detected_in_successful_result_text():
    # Audit CRITICAL: a HEALTHY run whose summary/plan legitimately mentions rate limits (e.g.
    # a ticket about implementing 429 handling) must NOT be classified as a pause — that would
    # lap the whole pool and park a healthy job.
    from openfactory.adapters.agent.claude_code import _parse_stream

    out = json.dumps({
        "type": "result", "subtype": "success", "is_error": False,
        "result": "Done — the API now returns 429 when the rate limit is exceeded.",
    })
    res = _parse_stream(0, out, allowed_tools=[])
    assert res.ok and res.pause_reason is None
    # and an auth-sounding healthy summary must not ON_HOLD the job either
    out2 = json.dumps({"type": "result", "subtype": "success", "is_error": False,
                       "result": "tests cover the 401 unauthorized path"})
    res2 = _parse_stream(0, out2, allowed_tools=[])
    assert res2.ok and res2.pause_reason is None


def test_pause_not_scanned_on_clean_exit_without_result_event():
    # rc == 0 with no result event: odd, but NOT a limit — scanning the whole transcript would
    # false-match any 429/quota the agent merely read (audit).
    from openfactory.adapters.agent.claude_code import _parse_stream

    out = json.dumps({"type": "system", "subtype": "init", "session_id": "s"}) + \
        "\nsome tool output mentioning quota and 429 limits\n"
    res = _parse_stream(0, out, allowed_tools=[])
    assert not res.ok and res.pause_reason is None


def test_max_turns_surfaces_a_readable_reason_not_an_empty_hold():
    # A too-big ticket hits the turn cap: the CLI returns is_error with an EMPTY result. The
    # on_hold must explain WHY (max turns → split it), not read as a blank "agent stopped:".
    from openfactory.adapters.agent.claude_code import _parse_stream

    out = json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True,
                      "result": "", "num_turns": 120, "total_cost_usd": 14.17})
    res = _parse_stream(0, out, allowed_tools=[])
    assert res.ok is False and res.pause_reason is None  # NOT a pause → no rotation, on_hold
    assert "turn" in res.summary.lower() and "too big" in res.summary.lower()
    assert res.cost_usd == 14.17  # the cost still surfaces


def test_generic_error_result_surfaces_the_subtype():
    from openfactory.adapters.agent.claude_code import _parse_stream

    out = json.dumps({"type": "result", "subtype": "error_during_execution",
                      "is_error": True, "result": ""})
    res = _parse_stream(1, out, allowed_tools=[])
    assert not res.ok and "error_during_execution" in res.summary


def test_session_limit_message_is_detected_as_rate_limit():
    # REGRESSION (partner-reported): the subscription session-cap message must classify as
    # rate_limit — so the pool ROTATES and, if exhausted, PAUSES with auto-resume — instead of
    # slipping through undetected to "agent stopped" → on_hold (no failover, no resume).
    from openfactory.adapters.agent.claude_code import _detect_pause

    reason, retry = _detect_pause("You've hit your session limit · resets 10:30pm (UTC)")
    assert reason == "rate_limit"
    assert retry == "10:30pm"  # the reset time is surfaced for the pause note
    # sibling phrasings stay covered
    assert _detect_pause("Claude usage limit reached")[0] == "rate_limit"
    assert _detect_pause("You have reached your usage limit")[0] == "rate_limit"
    # a normal plan/answer must NOT be mistaken for a limit
    assert _detect_pause("here is the plan: add a /healthz endpoint")[0] is None


def test_session_limit_result_envelope_pauses_not_stops():
    # end-to-end through the stream parser: a result event carrying the session-limit message
    # yields pause_reason=rate_limit (→ PAUSED), never a plain ok=False stop.
    import json

    from openfactory.adapters.agent.claude_code import _parse_stream

    out = json.dumps({
        "type": "result", "subtype": "error", "is_error": True,
        "result": "You've hit your session limit · resets 10:30pm (UTC)",
    })
    res = _parse_stream(1, out, allowed_tools=[])
    assert res.pause_reason == "rate_limit"
    assert res.retry_at == "10:30pm"
