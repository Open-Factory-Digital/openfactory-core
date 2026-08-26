"""Push-as-bot: the forge yields an authenticated remote; the token never leaks."""

from __future__ import annotations

from openfactory.adapters.forge import GitHubForge
from openfactory.adapters.sandbox.worktree import _redact


def test_push_remote_embeds_token_github_scheme():
    f = GitHubForge("owner/app", token="ghs_secret123")
    assert f.push_remote() == "https://x-access-token:ghs_secret123@github.com/owner/app.git"


def test_push_remote_none_without_token():
    assert GitHubForge("owner/app").push_remote() is None


def test_redact_strips_credentials_from_urls():
    msg = "fatal: could not read from https://x-access-token:ghs_secret123@github.com/o/a.git"
    red = _redact(msg)
    assert "ghs_secret123" not in red
    assert "***@github.com" in red
