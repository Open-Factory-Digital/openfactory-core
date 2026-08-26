"""The default deployment is LOCAL and FREE, and the panel must not say otherwise.

The operator, reading his own floor: *"amazon caught my eye… I never set up anything on amazon, this was supposed to be 100% local —
here the client has nothing outside the local and the free… this is open source, never forget, it
cannot be a vendor locker — everything has to have an open-source option"* (2026-08-14).

His panel showed `REGION eu-west-2` and offered three buttons into an AWS console for an account
he does not have — CloudWatch, SSM, ECS — one of them naming a log group from the product's OLD
name. None of it came from anything he configured: it came from literals and from a default
region that assumed a cloud.

The rule these hold is not "no AWS". It is that a vendor appears when the DEPLOYMENT declares
it: this installation runs boxes locally, so it has no region and no console, and a Fargate or
Azure one gets the surfaces it really has. Every axis of this platform is a port with adapters
for exactly that reason.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def local(monkeypatch):
    for var in ("OPENFACTORY_FARGATE_CLUSTER", "OPENFACTORY_SANDBOX", "AWS_DEFAULT_REGION",
                "OPENFACTORY_LOG_GROUP"):
        monkeypatch.delenv(var, raising=False)


def test_a_local_deployment_links_only_to_what_it_HAS(local):
    from openfactory.api.app import _links

    links = _links("https://board", "http://localhost:8080/x", "https://console", "")

    assert set(links) == {"board", "temporal"}, (
        f"a local install is offered buttons into a cloud it does not own: {sorted(links)}")


def test_a_local_deployment_has_NO_region(local, monkeypatch):
    """`eu-west-2` is a cloud's word. An installation without a cloud has no region, and the
    gauge is dropped rather than filled with somebody else's default."""
    import openfactory.api.app as app

    assert app._region() == "", "a local install was given a cloud's region"

    # and the cloud one keeps its own
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "fargate")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "sa-east-1")
    assert app._region() == "sa-east-1"
    # the panel renders the gauge only when the value is non-empty
    panel = (app.__file__.rsplit("/", 1)[0] + "/panel.html")
    with open(panel) as fh:
        html = fh.read()
    assert '${f.region?`<div class="gauge"><span class="lbl">region</span>' in html, (
        "the region gauge prints unconditionally — an empty value shows as an empty box, and a "
        "default value shows as a cloud nobody configured")


def test_a_cloud_deployment_gets_the_surfaces_it_really_has(monkeypatch):
    """The positive twin: dropping the links for everyone would be the opposite defect."""
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "fargate")
    from openfactory.api.app import _links

    links = _links("b", "t", "https://eu-west-2.console.aws.amazon.com", "eu-west-2")

    assert set(links) == {"board", "temporal", "cloudwatch", "ssm", "ecs"}
    # the console URL is the caller's — what matters here is that all three are built ON it
    assert all(v.startswith("https://eu-west-2.console.aws.amazon.com")
               for v in (links["cloudwatch"], links["ssm"], links["ecs"]))


def test_the_cloud_links_carry_the_PRODUCTS_name_not_a_dead_one(monkeypatch):
    """`sdlc-sandbox` outlived the rename in a literal here, so even the cloud deployment's log
    button pointed at a group nothing has written to since."""
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "fargate")
    from openfactory.api.app import _links
    from openfactory.namespace import BRANCH_PREFIX

    links = _links("b", "t", "https://c", "r")

    blob = json.dumps(links)
    assert "sdlc-sandbox" not in blob, "a dead product name is still in the panel's links"
    assert f"{BRANCH_PREFIX}-sandbox" in blob


def test_the_deployment_decides_the_names(monkeypatch):
    """A deployment that names its own log group or cluster is obeyed — the literals were never
    the point, the assumption was."""
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "fargate")
    monkeypatch.setenv("OPENFACTORY_LOG_GROUP", "/acme/jobs")
    monkeypatch.setenv("OPENFACTORY_FARGATE_CLUSTER", "acme-prod")
    from openfactory.api.app import _links

    links = _links("b", "t", "https://c", "r")

    assert "$252Facme$252Fjobs" in links["cloudwatch"]
    assert "clusters/acme-prod/" in links["ecs"]


def test_the_board_link_asks_what_kind_of_owner_it_is(monkeypatch):
    """The FOURTH sighting of the organisation/user asymmetry in one week — board creation, the
    columns read, the items read, and the link. `/orgs/<user>/projects/1` is a 404, and the
    operator clicked the panel's own Board button to reach it."""
    import subprocess

    import openfactory.adapters.tracker.github_project as app

    app._OWNER_KIND.clear()
    calls: list[list[str]] = []

    class _Out:
        returncode, stdout = 0, "User\n"

    def fake_run(args, **kw):
        calls.append(args)
        return _Out()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert app._owner_kind("solo-dev") == "users"
    assert any("users/solo-dev" in " ".join(a) for a in calls), "the owner was never asked"

    app._OWNER_KIND.clear()

    class _Org(_Out):
        stdout = "Organization\n"

    monkeypatch.setattr(subprocess, "run", lambda args, **kw: _Org())
    assert app._owner_kind("acme-corp") == "orgs"


def test_an_unaskable_owner_links_as_a_USER(monkeypatch):
    """The failure that costs least: a personal board is the shape this platform got wrong, and
    an org login typed as a user redirects rather than 404s."""
    import subprocess

    import openfactory.adapters.tracker.github_project as app

    app._OWNER_KIND.clear()
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("no gh here")))

    assert app._owner_kind("whoever") == "users"


def test_the_cockpit_ASKS_THE_BOARD_where_it_lives(monkeypatch):
    """BEHAVIOUR, where a source-text assertion stood. The panel spelled
    `https://github.com/{orgs|users}/{owner}/projects/{n}` by hand — GitHub Projects v2 vocabulary
    on the reference surface of a vendor-agnostic product, so an Azure or Jira operator got a
    github.com link to a page that does not exist (#162)."""
    import openfactory.api.app as app

    asked: list = []

    class _Board:
        def url(self):
            asked.append("asked")
            return "https://dev.azure.com/contoso/Payments/_boards"

    monkeypatch.setattr("openfactory.adapters.board.factory.build_board",
                        lambda project, **kw: _Board())

    got = app._board_url(object())

    assert asked and got == "https://dev.azure.com/contoso/Payments/_boards"


def test_and_the_panel_spells_no_vendor_URL_of_its_own():
    """The weld, asserted on code with the prose stripped — the paragraphs explaining the rule name
    the very host they forbid."""
    import inspect

    from conftest import code_only

    import openfactory.api.app as app

    assert "github.com" not in code_only(inspect.getsource(app)), (
        "the panel spells one vendor's host again")


def test_the_board_link_costs_NO_CREDENTIAL(monkeypatch):
    """None of the three `url()` implementations reads a token. Resolving one anyway meant an App
    deployment minted an installation token — an HTTPS round trip to GitHub — on every cockpit
    load, to compose a string; and a mint that failed removed a link needing no credential."""
    import openfactory.api.app as app

    def _never(*a, **k):
        raise AssertionError("the panel resolved a credential to build a URL")

    monkeypatch.setattr("openfactory.credentials.tracker_token_for", _never)
    monkeypatch.setattr("openfactory.credentials.deployment_tracker_token", _never)
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", _never)
    monkeypatch.setattr("openfactory.adapters.board.factory.build_board",
                        lambda project, **kw: type("B", (), {"url": lambda self: "https://x"})())

    assert app._board_url(object()) == "https://x"


def test_the_ENDPOINT_puts_that_answer_on_the_page(monkeypatch):
    """Reachability. Every guard here calls `_board_url` directly, so deleting the line that calls
    it from the cockpit route would leave them green and the Board button gone — the shape this
    codebase calls "built, tested, reached by nothing"."""
    import ast
    import inspect

    import openfactory.api.app as app

    src = inspect.getsource(app)
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_board_url"
                      for c in ast.walk(n)))
    assigned = {t.id for node in ast.walk(fn) if isinstance(node, ast.Assign)
                for t in node.targets if isinstance(t, ast.Name)}

    assert "board" in assigned, "`_board_url`'s answer is not bound to the name the page renders"

    # …AND THE WHOLE CHAIN, one honest step at a time: the endpoint hands the value on, and the
    # payload builder puts it under the key the page reads. Two functions, so a guard that stopped
    # at the first would prove only that a local variable was set.
    passed = {a.id for c in ast.walk(fn) if isinstance(c, ast.Call)
              for a in c.args if isinstance(a, ast.Name)}
    assert "board" in passed, "the endpoint computes the link and never passes it anywhere"

    builder = next(n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == "_links")
    assert '"board": board' in (ast.get_source_segment(src, builder) or ""), (
        "the links payload no longer carries the board under the key the page reads")


def test_a_board_that_cannot_say_leaves_the_button_OFF(monkeypatch):
    """No button is honest. A wrong link is a person clicking through to a 404 and concluding the
    platform has lost their board."""
    import openfactory.api.app as app

    monkeypatch.setattr("openfactory.adapters.board.factory.build_board",
                        lambda project, **kw: None)

    assert app._board_url(object()) == ""


def test_and_a_board_that_RAISES_does_not_take_the_cockpit_down(monkeypatch, caplog):
    import openfactory.api.app as app

    def _boom(project, **kw):
        raise RuntimeError("no tracker configured")

    monkeypatch.setattr("openfactory.adapters.board.factory.build_board", _boom)

    with caplog.at_level("WARNING"):
        assert app._board_url(object()) == ""

    assert "board link" in caplog.text
