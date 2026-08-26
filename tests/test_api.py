"""The web panel API — reads registry + journal, serves the panel (self-contained)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openfactory.api.app import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    return TestClient(app)


def test_serves_self_contained_panel(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    # THE UNBRANDED DEFAULT IS THE PRODUCT'S NAME. It was "Dark Factory" — the internal one — so
    # every deployment that did not set `OPENFACTORY_PLATFORM_NAME` shipped it to the client's screen.
    assert "OpenFactory" in r.text
    # BOTH TRANSPORTS, because the second is the floor under the first. `EventSource` carries the
    # job feed; the WebSocket pushes the agent conversation, and a page that lost either would
    # still render perfectly while quietly receiving nothing.
    assert "EventSource" in r.text
    assert "new WebSocket(" in r.text


def test_factory_cockpit(client: TestClient):
    r = client.get("/api/factory/demo")  # per-project cockpit
    assert r.status_code == 200
    d = r.json()
    assert d["project"] == "demo"
    assert d["harness"] == "Claude Code"  # the DEFAULT harness, now resolved rather than asserted
    assert "count" in d["tokens"]  # pool metadata, never token values
    assert all("token" not in k for k in d["tokens"])  # no value leaked
    # The four roles the harness registry actually knows. It used to be {planner, executor} read
    # from two env vars, which is why the cockpit said the same thing for every project.
    from openfactory.adapters.agent.registry import ROLES

    assert set(d["models"]) == set(ROLES)
    assert d["auth_format"]  # the ROUTE (anthropic/bedrock/gateway), not "unknown"
    # The buttons are what THIS deployment can honour. A free/local install has no cloud
    # console, so a console link there is a 404 the operator is invited to click; the cloud
    # keys appear if and only if the boxes really run in that cloud (see
    # test_a_local_deployment_names_no_vendor.py for both directions).
    from openfactory.api.app import _boxes_are_remote

    assert d["links"]["temporal"].startswith("http")
    cloud = {"cloudwatch", "ecs", "ssm"} & set(d["links"])
    assert bool(cloud) is _boxes_are_remote()
    assert all(d["links"][k].startswith("https://") for k in cloud)


def test_project_page_serves_spa(client: TestClient):
    assert client.get("/p/books").status_code == 200


def test_register_and_list_projects(client: TestClient, tmp_path: Path):
    assert client.get("/api/projects").json() == []
    r = client.post(
        "/api/projects",
        json={"name": "demo", "repo_path": str(tmp_path / "repo"), "repo": "o/demo"},
    )
    assert r.status_code == 200
    ps = client.get("/api/projects").json()
    assert ps[0]["name"] == "demo" and ps[0]["forge"] == "github"


def test_enable_toggle_controls_pickup(client: TestClient, tmp_path: Path):
    client.post("/api/projects", json={"name": "d", "repo_path": str(tmp_path), "repo": "o/d"})
    assert client.get("/api/projects").json()[0]["enabled"] is True  # default on
    r = client.post("/api/projects/d/enabled", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert client.get("/api/projects").json()[0]["enabled"] is False
    assert client.post("/api/projects/ghost/enabled", json={"enabled": True}).status_code == 404


def test_jobs_derived_from_journal(client: TestClient, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    client.post("/api/projects", json={"name": "demo", "repo_path": str(repo), "repo": "o/demo"})
    # write a journal the panel should surface (log dir = repo.parent/.openfactory-logs/demo)
    log = tmp_path / ".openfactory-logs" / "demo"
    log.mkdir(parents=True)
    events = [
        {"ts": "2026-07-12T10:00:00+00:00", "job_id": "#5", "ticket_id": "#5",
         "kind": "state", "message": "implementing", "data": {}},
        {"ts": "2026-07-12T10:01:00+00:00", "job_id": "#5", "ticket_id": "#5",
         "kind": "pr", "message": "opened", "data": {"url": "https://forge/pr/5"}},
        {"ts": "2026-07-12T10:01:01+00:00", "job_id": "#5", "ticket_id": "#5",
         "kind": "state", "message": "pr_open", "data": {}},
    ]
    (log / "5-events.jsonl").write_text("\n".join(json.dumps(e) for e in events))

    jobs = client.get("/api/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["issue"] == "5"
    assert jobs[0]["state"] == "pr_open"
    assert jobs[0]["pr_url"] == "https://forge/pr/5"

    evs = client.get("/api/jobs/demo/5/events").json()
    assert len(evs) == 3
