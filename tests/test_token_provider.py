"""GitHubAppTokenProvider caches a token and re-mints ~5 min before expiry."""

from __future__ import annotations

import openfactory.adapters.github_app as ga


def test_caches_then_refreshes_near_expiry(monkeypatch):
    calls = {"n": 0}
    clock = {"t": 1000.0}

    def fake_mint(**kw):
        calls["n"] += 1
        return f"tok{calls['n']}", clock["t"] + 3600  # expires 1h from "now"

    monkeypatch.setattr(ga, "mint_installation_token", fake_mint)
    monkeypatch.setattr(ga.time, "time", lambda: clock["t"])

    p = ga.GitHubAppTokenProvider(app_id="1", private_key="k", installation_id="2")
    assert p.token() == "tok1" and calls["n"] == 1
    assert p.token() == "tok1" and calls["n"] == 1  # still fresh -> cached, no re-mint

    clock["t"] += 3400  # now within the 5-min pre-expiry window
    assert p.token() == "tok2" and calls["n"] == 2  # re-minted
