"""A project nobody registered is answered in a sentence — never a 500 (#204).

    GET /api/promote/no-such-project/7   →   500 Internal Server Error
    KeyError: "project not registered: 'no-such-project'"

`promote_info` wrapped its lookup in a `try` that caught only `FileNotFoundError` (the deployed
panel, whose `repo_path` is a placeholder); the registry's refusal for a name it does not hold is a
`KeyError`, and it escaped. The route feeds the production-approval dialog, which prints the
server's sentence for a non-2xx — so a 404 reads "no project named …" and a 500 reads "the panel's
own API answered 500", about a release somebody is trying to approve. A project removed or renamed
while a card waits for its approval is how a person gets here.

FOUR ROUTES ALREADY SPELLED THE LOOKUP BY HAND, in three different sentences, and the fifth forgot.
The cure is one helper, and THE GUARD IS A SWEEP, never a list: it enumerates `app.routes`, calls
every route that takes `{project}` with a name nobody registered, and refuses a 5xx from any of
them — so the next route to need the lookup cannot forget it quietly. A route may legitimately
answer something else for an unknown project (an empty conversation, a floor that says the engine
is absent, the page shell); the rule is only "never a 500".

THE ACTION LAYER IS SWEPT THE SAME WAY. Every POST route is a mapping onto `actions.perform`, and
every catalogued row resolves its project through `catalog._project` — except `promote`, which
went straight to `_forge_and_manifest` and let the `KeyError` reach `perform`'s catch-all: FAILED,
a 500 whose sentence was the exception's repr.
"""

from __future__ import annotations

import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from openfactory import actions
from openfactory.api import app as panel
from openfactory.contracts.project import Project, ProviderRef
from openfactory.registry import ProjectRegistry

NOBODY = "no-such-project"
SENTENCE = f"no project named {NOBODY!r} in this deployment"

#: A plausible value for every path parameter and body field these routes take. `action` and
#: `answer` are words their routes validate BEFORE they look the project up, so a filler there
#: would prove nothing about the lookup.
_PLAUSIBLE = {"project": NOBODY, "issue": "7", "ref": "7", "version": "1.2.0", "approver": "ana",
              "password": "a-password", "action": "resume", "answer": "approve",
              "token": "stage|7", "reason": "no longer wanted", "requirement": "7"}


def _takes_a_project(method: str) -> list[APIRoute]:
    return [r for r in panel.app.routes
            if isinstance(r, APIRoute) and method in r.methods and "{project}" in r.path]


def _url(route: APIRoute) -> str:
    return re.sub(r"{(\w+)(?::\w+)?}", lambda m: _PLAUSIBLE.get(m.group(1), "x"), route.path)


def _body(route: APIRoute) -> dict:
    """The route's own body model, filled — so a 422 cannot stand in for an answer."""
    field = route.body_field
    model = getattr(field, "type_", None) if field is not None else None
    fields = getattr(model, "model_fields", None)
    if fields is None:                       # `body: dict` — free-form, the route reads what it needs
        return dict(_PLAUSIBLE)
    return {name: _PLAUSIBLE.get(name, "x") for name, f in fields.items() if f.is_required()}


GETS = _takes_a_project("GET")
POSTS = _takes_a_project("POST")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """An empty deployment: no registry, no home, no panel token, no engine."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENFACTORY_HOME", str(tmp_path / ".openfactory"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    for name in ("OPENFACTORY_PANEL_TOKEN", "OPENFACTORY_PROD_APPROVERS", "OPENFACTORY_APPROVERS"):
        monkeypatch.delenv(name, raising=False)
    return TestClient(panel.app, raise_server_exceptions=False)


# ── the sweep ───────────────────────────────────────────────────────────────────────────────────

def test_the_sweep_found_the_routes_it_is_for():
    """An enumeration that quietly finds nothing passes every case below."""
    gets = {r.path for r in GETS}
    assert {"/api/promote/{project}/{issue}", "/api/board/{project}",
            "/api/jobs/{project}/{issue}/events", "/p/{project}"} <= gets
    assert "/api/promote/{project}/{issue}" in {r.path for r in POSTS}


@pytest.mark.parametrize("route", GETS, ids=lambda r: r.path)
def test_no_GET_route_answers_5xx_for_a_project_nobody_registered(client, route):
    r = client.get(_url(route))
    assert r.status_code < 500, f"GET {_url(route)} → {r.status_code}: {r.text[:200]}"


@pytest.mark.parametrize("route", POSTS, ids=lambda r: r.path)
def test_no_POST_route_answers_5xx_for_a_project_nobody_registered(client, route):
    r = client.post(_url(route), json=_body(route))
    assert r.status_code < 500, f"POST {_url(route)} → {r.status_code}: {r.text[:200]}"
    assert r.status_code != 422, f"the sweep's own body was refused: {r.text[:200]}"


# ── one helper, one sentence ────────────────────────────────────────────────────────────────────

def test_the_approval_dialogs_prefetch_is_a_404_in_the_house_sentence(client):
    r = client.get(f"/api/promote/{NOBODY}/7")
    assert r.status_code == 404
    assert r.json() == {"detail": SENTENCE}


def test_every_GET_route_that_refuses_an_unknown_project_says_it_the_same_way(client):
    """`no project called …`, `no project called … here`, `no project named … in this deployment`:
    three spellings of one refusal, because each route wrote its own."""
    said = {r.path: client.get(_url(r)) for r in GETS}
    refused = {path: a.json()["detail"] for path, a in said.items() if a.status_code == 404}
    assert {"/api/promote/{project}/{issue}", "/api/board/{project}",
            "/api/jobs/{project}/{issue}/events", "/api/jobs/{project}/{issue}/stream"} <= set(refused)
    assert set(refused.values()) == {SENTENCE}, refused


def test_a_staged_answer_for_an_unknown_project_is_refused_in_that_sentence_too(
        client, monkeypatch):
    """The fourth hand-written lookup: the panel's answer to a STAGED proposal (`<stage>|<n>`).
    It sits behind "is that question still open", so the store is made to say yes — the shape of
    a proposal staged for a project somebody then removed."""
    from types import SimpleNamespace

    monkeypatch.setattr("openfactory.memory.messages.pending",
                        lambda project, **kw: [SimpleNamespace(token="stage|7")])
    r = client.post(f"/api/messages/{NOBODY}/answer", json={"token": "stage|7", "answer": "approve"})
    assert r.status_code == 404
    assert r.json() == {"detail": SENTENCE}


def test_a_registered_project_is_still_served(client, tmp_path):
    """The helper hands the project back — it is not only a refusal."""
    ProjectRegistry().add(Project(name="alpha", repo_path=str(tmp_path / "no-checkout"),
                                  tracker=ProviderRef(kind="local", repo="alpha")))
    assert panel._project_or_404("alpha").name == "alpha"
    r = client.get("/api/jobs/alpha/7/events")
    assert r.status_code == 200 and r.json() == []
    assert client.get(f"/api/jobs/{NOBODY}/7/events").status_code == 404


# ── the action layer: every row refuses by name ─────────────────────────────────────────────────

def _rows_that_take_a_project() -> list[str]:
    return sorted(key for key, row in actions._catalog().items() if "project" in row.parameters)


def test_the_catalog_sweep_found_the_rows_it_is_for():
    rows = _rows_that_take_a_project()
    assert {"promote", "approve_prod", "scan", "start"} <= set(rows)


@pytest.mark.parametrize("key", _rows_that_take_a_project())
async def test_no_catalogued_action_FAILS_for_a_project_nobody_registered(client, key):
    """FAILED is the code the panel maps to 500. `perform`'s catch-all is for what nobody thought
    of; a name that is not registered is the first thing anybody thinks of."""
    row = actions._catalog()[key]
    params = {name: _PLAUSIBLE.get(name, "x") for name in row.required}
    params["project"] = NOBODY
    out = await actions.perform(key, by=actions.SYSTEM, **params)
    assert out.code != actions.FAILED, f"{key}: {out.message}"
    if out.code == actions.NOT_FOUND:
        assert repr(NOBODY) in out.message


async def test_promote_refuses_a_project_nobody_registered_by_name(client):
    out = await actions.perform("promote", by=actions.SYSTEM, project=NOBODY, issue="7",
                                version="1.2.0", approver="ana", password="a-password")
    assert out.code == actions.NOT_FOUND
    assert repr(NOBODY) in out.message and "KeyError" not in out.message


def test_the_approval_dialogs_submit_is_a_404_too(client):
    r = client.post(f"/api/promote/{NOBODY}/7",
                    json={"approver": "ana", "password": "a-password", "version": "1.2.0"})
    assert r.status_code == 404
    assert repr(NOBODY) in r.json()["detail"]
