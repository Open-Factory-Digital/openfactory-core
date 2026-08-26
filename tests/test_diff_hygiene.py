"""Hardening: an agent must not silence a quality gate, nor inherit ambient AWS creds.

Covers the two deterministic guards added after a live job (#207) smuggled an
out-of-scope, coverage-suppressed change past every automated gate (engineering.md
#11/#12).
"""

from __future__ import annotations

from openfactory.adapters.sandbox.worktree import (
    _AGENT_CRED_VARS,
    _AWS_CRED_VARS,
    _FORGE_CRED_VARS,
    _scrubbed_env,
)
from openfactory.orchestrator.machine import _added_suppressions


def test_detects_added_suppression_comments():
    diff = (
        "+++ b/app/main.py\n"
        "+            except ClientError:  # pragma: no cover - production path\n"
        "+    x = untyped()  # type: ignore\n"
        "+    y = 1  # noqa: E501\n"
        "+    subprocess.run(cmd)  # nosec\n"
    )
    found = _added_suppressions(diff)
    assert "pragma: no cover" in found
    assert "type: ignore" in found
    assert "noqa" in found
    assert "nosec" in found


def test_ignores_context_and_removed_lines_and_headers():
    # only ADDED lines count — a pre-existing pragma (context ' ' or removed '-') or the
    # +++ file header must never trip the gate.
    diff = (
        "+++ b/app/x.py\n"
        " existing = 1  # pragma: no cover\n"
        "-old = 2  # type: ignore\n"
        "+clean = 3\n"
    )
    assert _added_suppressions(diff) == []


def test_clean_diff_has_no_suppressions():
    diff = "+++ b/app/main.py\n+@app.get('/autonomy')\n+def autonomy():\n+    return {'ok': True}\n"
    assert _added_suppressions(diff) == []


def test_scrubbed_env_removes_ambient_aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "/v2/creds/abc")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA...")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "tok")
    monkeypatch.setenv("PATH", "/usr/bin")  # unrelated var survives
    env = _scrubbed_env()
    for var in _AWS_CRED_VARS:
        assert var not in env, f"{var} leaked into the sandbox env"
    assert env["PATH"] == "/usr/bin"


def test_scrubbed_env_removes_forge_push_credentials(monkeypatch):
    # the agent must not be able to push/PR with the bot's GitHub creds — version control
    # is the pipeline's job (an unscrubbed token let #232's executor push a stray branch).
    for var in _FORGE_CRED_VARS:
        monkeypatch.setenv(var, "secret")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "keep-me")  # the agent's own token stays
    env = _scrubbed_env()
    for var in _FORGE_CRED_VARS:
        assert var not in env, f"{var} leaked into the sandbox env — agent could push"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "keep-me"


def test_scrubbed_env_removes_the_claude_token_pool(monkeypatch):
    # The whole failover pool is the crown jewels: the workload (agent, or the project's own
    # app/tests booting in the sandbox) must never read OPENFACTORY_AGENT_TOKENS and exfiltrate EVERY
    # token. The framework picks the active one and delivers it via CLAUDE_CODE_OAUTH_TOKEN.
    monkeypatch.setenv("OPENFACTORY_AGENT_TOKENS", '[{"id":"a","token":"tok-a"}]')
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "active-token")  # the active token survives
    env = _scrubbed_env()
    for var in _AGENT_CRED_VARS:
        assert var not in env, f"{var} leaked into the sandbox env — whole pool exposed"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "active-token"
