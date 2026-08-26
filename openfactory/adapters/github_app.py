"""GitHub App auth — mint short-lived installation tokens, with auto-refresh.

GitHub-specific *token acquisition*, deliberately kept out of the core: the
framework only ever holds the opaque token (BotIdentity). App installation tokens
last ~1h, so a long-running server stores the durable **private key** and mints
fresh tokens on demand — never a stored token. Other providers differ (GitLab
tokens are long-lived; Jira uses API tokens), each in their own adapter.
"""

from __future__ import annotations

import os
import time
from datetime import datetime

import httpx
import jwt


def token_from_env() -> str | None:
    """Resolve a bot token: an explicit OPENFACTORY_BOT_TOKEN, else mint from GitHub App env
    (OPENFACTORY_GH_APP_ID/KEY/INSTALLATION_ID). None if neither is configured."""
    if os.environ.get("OPENFACTORY_BOT_TOKEN"):
        return os.environ["OPENFACTORY_BOT_TOKEN"]
    from openfactory.credentials import app_id, app_installation_id, app_private_key

    aid, key, inst = app_id(), app_private_key(), app_installation_id()
    if not (aid and key and inst):
        return None
    return mint_installation_token(app_id=aid, private_key=key, installation_id=inst)[0]


def mint_installation_token(
    *, app_id: str, private_key: str, installation_id: str
) -> tuple[str, float]:
    """Sign an App JWT (RS256), exchange it for an installation token. Returns
    (token, expires_at_epoch)."""
    now = int(time.time())
    app_jwt = jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": app_id}, private_key, algorithm="RS256"
    )
    r = httpx.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp()
    return data["token"], expires


class GitHubAppTokenProvider:
    """Caches an installation token and re-mints ~5 min before it expires. This is
    what an always-on worker holds; a single short `openfactory run` needs only one token."""

    def __init__(self, *, app_id: str, private_key: str, installation_id: str) -> None:
        self.app_id = app_id
        self.private_key = private_key
        self.installation_id = installation_id
        self._token: str | None = None
        self._expires: float = 0.0

    def token(self) -> str:
        if self._token and time.time() < self._expires - 300:
            return self._token
        self._token, self._expires = mint_installation_token(
            app_id=self.app_id, private_key=self.private_key, installation_id=self.installation_id
        )
        return self._token
