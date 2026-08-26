"""The agent's stream-json parser — the anti-black-box path (visibility + no silent
hangs). Verifies we extract the terminal result/cost and treat a missing/errored
result as a failure rather than a silent success."""

from __future__ import annotations

from openfactory.adapters.agent.claude_code import _detect_pause, _parse_stream


def test_detect_pause_rate_limit_with_reset():
    reason, retry = _detect_pause("You've reached your usage limit. Resets at 3:00pm.")
    assert reason == "rate_limit" and retry is not None


def test_detect_pause_auth():
    assert _detect_pause("Error: invalid api key")[0] == "auth"
    assert _detect_pause("401 Unauthorized")[0] == "auth"


def test_detect_pause_none_for_normal_output():
    assert _detect_pause("added the endpoint and its test") == (None, None)


def test_extracts_result_and_cost_from_terminal_event():
    out = "\n".join(
        [
            '{"type":"system","subtype":"init"}',
            '{"type":"assistant","message":{"content":"editing app/health.py"}}',
            '{"type":"result","is_error":false,"result":"added endpoint","total_cost_usd":0.12}',
        ]
    )
    r = _parse_stream(0, out)
    assert r.ok is True
    assert r.cost_usd == 0.12
    assert "added endpoint" in r.summary
    assert r.raw_output == out  # full transcript retained


def test_missing_result_event_is_failure_not_silent_success():
    r = _parse_stream(0, '{"type":"assistant","message":{"content":"..."}}')
    assert r.ok is False


def test_error_result_event_is_failure():
    out = '{"type":"result","is_error":true,"result":"hit max turns","total_cost_usd":0.4}'
    r = _parse_stream(0, out)
    assert r.ok is False
    assert r.cost_usd == 0.4


def test_nonzero_rc_is_failure_even_with_result():
    out = '{"type":"result","is_error":false,"result":"ok","total_cost_usd":0.1}'
    assert _parse_stream(1, out).ok is False


def test_parse_stream_drops_ungranted_tool_attempts():
    """A read-only invocation whose model probed Edit (blocked) must NOT show it as a
    done action — that once read as "the planner edited" and caused a false alarm."""
    import json as _json
    stream = "\n".join([
        _json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "a.py"}},
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "a.py"}},
            {"type": "tool_use", "name": "Write", "input": {"file_path": "a.py"}},
        ]}}),
        _json.dumps({"type": "result", "result": "the plan", "subtype": "success"}),
    ])
    r = _parse_stream(0, stream, allowed_tools=["Read", "Grep", "Glob"])
    assert r.actions == ["Read: a.py"]  # Edit/Write attempts filtered out


def test_parse_stream_keeps_all_actions_when_unrestricted():
    import json as _json
    stream = "\n".join([
        _json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "a.py"}},
        ]}}),
        _json.dumps({"type": "result", "result": "done", "subtype": "success"}),
    ])
    r = _parse_stream(0, stream)  # no allowed_tools → no filtering (executor-style)
    assert r.actions == ["Edit: a.py"]
