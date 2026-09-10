"""The panel's *New project* form asks only what the address needs (ADR-0049 slice 4c).

WHAT IS PROVEN HERE:

  · **the reading and the writing are the same two functions.** `/api/address` answers what
    `POST /api/projects` would write for the address a person is typing — not a second opinion
    about it. Slice 4a made the three registering doors agree; a form that showed a fourth answer
    would promise what the door then refuses;
  · **coordinates are a HOSTED idea.** A directory on this machine has no owner to name and no
    board to number, and the form asked for both under every path — so a person who filled them
    because the form asked turned their own checkout into a GitHub row;
  · **one claim, three doors.** The command line's refusal, the API's 422 and the line under the
    form's address field are all `doors.foreign_refusal`;
  · **the door's sentence reaches the person.** Every refusal used to arrive as *"not registered
    (duplicate?)"* — including the one about a credential for one system reaching another, which
    is the opposite of a duplicate and the only one that says what to do next.
"""

from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from openfactory import doors
from openfactory.api.app import app

PANEL = (pathlib.Path(__file__).resolve().parent.parent
         / "openfactory" / "api" / "panel.html").read_text(encoding="utf-8")


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "")
    return TestClient(app)


def _register_block() -> str:
    """The form and its submit, as the browser gets them — the panel is asserted as text here
    because it is served as one file and has no test harness of its own.

    WITHOUT THE COMMENTS, because the guards below are about what the code DOES: the first
    version of this failed on the comment that quotes the very string it refuses, which would
    have taught the next person to delete the note rather than keep the behaviour."""
    start = PANEL.index("function openRegister()")
    end = PANEL.index("let _sug={}")
    assert start < end
    return "\n".join(line for line in PANEL[start:end].splitlines()
                      if not line.lstrip().startswith("//"))


# ── 1. the reading is what the door would write ─────────────────────────────────────────────────

@pytest.mark.parametrize("address,repo,kind,coordinates,why", [
    ("/home/me/work/thing", "", "local", False,
     "a path on this machine: no owner anywhere, and the board is a file beside the registry"),
    ("/home/me/work/thing", "o/thing", "github", True,
     "a path WITH coordinates is the operator saying this checkout is of a hosted repository"),
    ("https://github.com/o/thing.git", "", "github", True,
     "a URL takes the kind whose host it belongs to"),
    ("https://dev.azure.com/org/proj/_git/thing", "", "azure_devops", True,
     "the same reading, by host, for the other shipped vendor"),
])
def test_the_reading_is_the_doors_own(client, address, repo, kind, coordinates, why):
    got = client.get("/api/address", params={"repo_path": address, "repo": repo}).json()

    assert got["kind"] == kind, why
    assert got["kind"] == doors.kind_for(address, repo=repo), "a second opinion, not the rule"
    assert got["coordinates"] is coordinates, why
    assert got["refusal"] == ""


def test_what_the_reading_says_is_what_the_registry_gets(client, tmp_path):
    """The point of the route, in one test: what the form showed is the row that lands."""
    path = str(tmp_path / "mine")
    reading = client.get("/api/address", params={"repo_path": path}).json()
    assert client.post("/api/projects", json={"name": "mine", "repo_path": path}).status_code == 200

    row = client.get("/api/projects").json()[0]
    assert reading["kind"] == "local" and row["forge"] == "local"
    from openfactory.registry import ProjectRegistry

    project = ProjectRegistry().get("mine")
    assert project.tracker.kind == project.forge.kind == "local"
    assert project.ci.kind == "none"


def test_the_reading_writes_nothing(client, tmp_path):
    """A GET that registered something would be a door nobody knew was one."""
    for address in (str(tmp_path), "https://github.com/o/n.git", "https://gitlab.com/o/n.git"):
        client.get("/api/address", params={"repo_path": address})

    assert client.get("/api/projects").json() == []


# ── 2. one claim, three doors ───────────────────────────────────────────────────────────────────

def test_a_foreign_host_is_refused_in_the_SAME_words_at_every_door(client):
    from openfactory.cli import _foreign_refusal

    got = client.get("/api/address",
                     params={"repo_path": "https://gitlab.com/o/n.git"}).json()

    assert got["kind"] == "" and got["coordinates"] is False
    assert got["refusal"] == doors.foreign_refusal("gitlab.com")
    # the door the form submits to, and the command line beside it — the same sentence, once
    refused = client.post("/api/projects",
                          json={"name": "n", "repo_path": "https://gitlab.com/o/n.git"})
    assert refused.status_code == 422
    assert refused.json()["detail"] == got["refusal"]
    assert doors.foreign_refusal("gitlab.com") in _foreign_refusal("gitlab.com", None)


def test_a_kind_nobody_implements_is_a_REFUSAL_the_form_can_show(client, tmp_path):
    """`foreign_host` raises this one for the command line to print. A form asking the same
    question must read it as a refusal, not as a 500 with an empty modal in front of it."""
    got = client.get("/api/address",
                     params={"repo_path": str(tmp_path), "provider": "nosuchforge"})

    assert got.status_code == 200
    assert "nosuchforge" in got.json()["refusal"] and got.json()["kind"] == ""


@pytest.fixture
def gated(tmp_path, monkeypatch) -> TestClient:
    """A panel that configured a credential — where every `/api/` read is gated."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "shared")
    return TestClient(app)


def test_the_reading_is_closed_on_a_panel_that_configured_a_credential(gated):
    """`_panel_gate` is the read gate — the same one over `/api/projects` and the board."""
    assert gated.get("/api/address", params={"repo_path": "/tmp/x"}).status_code == 401
    assert gated.get("/api/address", params={"repo_path": "/tmp/x"},
                     headers={"Authorization": "Bearer shared"}).status_code == 200


def test_A_COOKIE_THE_GATE_ADMITS_REACHES_THE_READING(gated):
    """MEASURED, and it is why this route carries no `require_auth` of its own: that dependency
    reads the Authorization header ALONE, while the middleware in front of it accepts a Bearer
    token, a same-origin cookie or `?token=`. With both gates on, a cookie-authenticated browser
    got `/api/projects` 200 and `/api/address` 401 in the same page — the form's reading blank
    with no way to tell why, on the deployments that authenticate by cookie.

    The mutation that removes the dependency SURVIVES a test that only checks the 401, because
    the middleware answers first; this is the direction that can see it."""
    gated.cookies.set("openfactory_token", "shared")  # on the client: what a browser does

    assert gated.get("/api/projects").status_code == 200, "the gate admits the cookie"
    assert gated.get("/api/address", params={"repo_path": "/tmp/x"}).status_code == 200


# ── 3. the form ─────────────────────────────────────────────────────────────────────────────────

def test_the_form_asks_the_RULE_instead_of_carrying_a_copy():
    """A JavaScript reading of an address would be a fourth door — and the one that only SHOWS
    what the others do is how a surface comes to promise what the door refuses. The kind's own
    name appears once, to pick the sentence for an answer the server gave; nothing here decides
    which vendor an address belongs to."""
    block = _register_block()

    assert "/api/address" in block
    for tell in ("://", "git@", ".com", "azure_devops", "github"):
        assert tell not in block, f"{tell!r} is the rule being read in the browser"


def test_the_coordinates_are_hidden_until_they_apply():
    block = _register_block()
    coords = block.index('<div id="np_coords" style="display:none">')
    buttons = block.index('<div style="display:flex;gap:8px;margin-top:16px">')

    for field in ("np_repo", "np_bo", "np_bn"):
        assert coords < block.index(field) < buttons, f"{field} is outside the hidden block"


def test_a_hosted_checkout_is_ONE_CLICK_away_never_gone():
    """A mounted checkout of a hosted repository is a shape that runs today (D2), and the
    coordinates are how the operator says so — hiding them must not remove them."""
    block = _register_block()

    assert "npHosted" in block
    assert "this checkout is of a hosted repository" in block


def test_what_is_hidden_is_not_sent():
    """A coordinate typed before the address became a path would otherwise still be submitted,
    and a repo the person cannot see is what makes their own checkout hosted."""
    block = _register_block()

    assert "hosted?np_repo.value.trim():\"\"" in block


def test_the_doors_sentence_reaches_the_person():
    block = _register_block()

    assert "duplicate?" not in block, "every refusal read as a duplicate, including #162's"
    assert "d.detail" in block
