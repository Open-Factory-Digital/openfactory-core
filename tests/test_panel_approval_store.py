"""The deployed panel's prod-approval gate must be satisfiable by the cloud environment.

In the cloud the registry's repo_path is a placeholder (no checkout exists in the panel
container) and the ONLY possible password store is the OPENFACTORY_APPROVERS env seam (an
SSM-injected SecureString, same delivery as TEMPORAL_API_KEY). These tests drive the real
routes through that exact shape: approval must WORK from the injected store, a missing
store must refuse LOUDLY (503 + SDLC_ log line), and a bad password must stay a 403 —
never a button that accepts and does nothing, never a 500.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from openfactory import namespace
from openfactory.api import app as app_module
from openfactory.approvals import hash_password
from openfactory.contracts.project import Project, ProviderRef
from openfactory.registry import ProjectRegistry
from openfactory.runtime.temporal import view as tv


@pytest.fixture
def client():
    return TestClient(app_module.app)


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """No panel token, no env allowlist, and NO laptop store leaking in: the file-store
    path points at a nonexistent file so only OPENFACTORY_APPROVERS (when a test sets it) counts."""
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)
    monkeypatch.delenv("OPENFACTORY_PROD_APPROVERS", raising=False)
    monkeypatch.delenv("OPENFACTORY_APPROVERS", raising=False)
    monkeypatch.setenv("OPENFACTORY_APPROVERS_FILE", str(tmp_path / "no-approvers.json"))


def _register(tmp_path, monkeypatch, *, with_manifest: bool, prod_approvers=()):
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    repo = tmp_path / "repo"  # NOT created unless with_manifest — the cloud placeholder shape
    if with_manifest:
        (repo / namespace.DIR).mkdir(parents=True)
        body = "version: 1\nbase_branch: main\n"
        if prod_approvers:
            body += "prod_approvers: [" + ", ".join(prod_approvers) + "]\n"
        (repo / namespace.MANIFEST).write_text(body)
    ProjectRegistry().add(
        Project(name="p", repo_path=str(repo), tracker=ProviderRef(kind="github", repo="o/p"))
    )


@pytest.fixture
def engine(monkeypatch):
    """Fake durable engine: records the approve signal instead of dialing Temporal."""
    signals: list[dict] = []

    async def connect():
        return object()

    async def approve_job(client, project, issue, **kw):
        signals.append({"project": project, "issue": issue, **kw})

    monkeypatch.setattr(tv, "connect", connect)
    monkeypatch.setattr(tv, "approve_job", approve_job)
    return signals


def _store(monkeypatch, login="alice", password="s3cret"):
    monkeypatch.setenv("OPENFACTORY_APPROVERS", json.dumps({login: hash_password(password)}))


# --- the cloud loop, closed: one injected secret arms the gate ---
def test_cloud_approve_succeeds_from_the_injected_store(
    client, clean_env, engine, monkeypatch, tmp_path, caplog
):
    # registry placeholder path, no checkout, no OPENFACTORY_PROD_APPROVERS — the deployed reality
    _register(tmp_path, monkeypatch, with_manifest=False)
    _store(monkeypatch)
    r = client.post(
        "/api/temporal/approve/p/5",
        json={"approver": "alice", "password": "s3cret", "version": "1.2.0", "comment": "ok"},
    )
    assert r.status_code == 200 and r.json()["signaled"] is True
    assert engine == [
        {"project": "p", "issue": "5", "version": "1.2.0", "approver": "alice", "comment": "ok"}
    ]
    # the allowlist derivation is explicit in the log, not silent
    assert "OPENFACTORY_PROD_ALLOWLIST_FROM_STORE" in caplog.text


def test_cloud_bad_password_is_403_and_signals_nothing(
    client, clean_env, engine, monkeypatch, tmp_path
):
    _register(tmp_path, monkeypatch, with_manifest=False)
    _store(monkeypatch)
    r = client.post(
        "/api/temporal/approve/p/5",
        json={"approver": "alice", "password": "wrong", "version": "1.2.0"},
    )
    assert r.status_code == 403
    assert engine == []


def test_env_allowlist_still_narrows_the_store(client, clean_env, engine, monkeypatch, tmp_path):
    _register(tmp_path, monkeypatch, with_manifest=False)
    _store(monkeypatch)
    monkeypatch.setenv("OPENFACTORY_PROD_APPROVERS", "someone-else")
    r = client.post(
        "/api/temporal/approve/p/5",
        json={"approver": "alice", "password": "s3cret", "version": "1.2.0"},
    )
    assert r.status_code == 403
    assert engine == []


# --- the missing store refuses loudly: 503 + SDLC_ line, never a dead 403/500 ---
def test_missing_store_in_the_cloud_is_a_loud_503(
    client, clean_env, engine, monkeypatch, tmp_path, caplog
):
    _register(tmp_path, monkeypatch, with_manifest=False)  # and no OPENFACTORY_APPROVERS either
    r = client.post(
        "/api/temporal/approve/p/5",
        json={"approver": "alice", "password": "s3cret", "version": "1.2.0"},
    )
    assert r.status_code == 503
    assert "OPENFACTORY_APPROVERS" in r.json()["detail"]  # the refusal names the missing secret
    assert "OPENFACTORY_APPROVER_STORE_MISSING" in caplog.text
    assert engine == []


def test_missing_store_with_a_manifest_is_also_503_not_bad_password(
    client, clean_env, engine, monkeypatch, tmp_path, caplog
):
    # a LISTED approver on a laptop-shaped deployment with no store: the old code answered
    # 403 "bad password" — a config error disguised as a typo
    _register(tmp_path, monkeypatch, with_manifest=True, prod_approvers=["alice"])
    r = client.post(
        "/api/temporal/approve/p/5",
        json={"approver": "alice", "password": "s3cret", "version": "1.2.0"},
    )
    assert r.status_code == 503
    assert "OPENFACTORY_APPROVER_STORE_MISSING" in caplog.text
    assert engine == []


# --- the dialog prefetch serves without a checkout instead of 500ing ---
def test_promote_info_serves_the_dialog_without_a_checkout(
    client, clean_env, monkeypatch, tmp_path
):
    _register(tmp_path, monkeypatch, with_manifest=False)
    _store(monkeypatch)

    class _Forge:
        def latest_tag(self):
            return "v1.4.0"

    import openfactory.adapters.forge.registry as forge_registry
    import openfactory.adapters.github_app as github_app

    monkeypatch.setattr(forge_registry, "build_forge", lambda p, token=None: _Forge())
    monkeypatch.setattr(github_app, "token_from_env", lambda: "tok")
    r = client.get("/api/promote/p/5")
    assert r.status_code == 200
    body = r.json()
    assert body["latest_tag"] == "v1.4.0"
    assert body["approvers"] == ["alice"]
    assert body["tag_prefix"] == "v"
