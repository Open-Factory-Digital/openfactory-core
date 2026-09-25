"""A preview of the product is keyed, named and routed so agent-written code never reaches the
panel's credential (ADR-0050 D1, D7, D10; #265 slice 0; #271).

This build runs no preview yet — the runtime is #265's slices 2–3. What it ships, and what these
pin, is everything around one that must hold before the first can start:

1. THE NAMES. A unit (a card, or a requirement as `req0012`) and each exposed service's host,
   `<service>--<project>--<unit>.<domain>`. The panel's own host is never read as a preview, and no
   host under the preview domain ever reaches the panel.
2. THE KEY. What the panel hands out opens one unit of one project, for minutes; the cookie it
   becomes lasts as long as the preview and exists only on that host.
3. THE RECORD. The worker writes one row per card of the unit; the panel reads the unit back.
4. THE ROUTER. The target is derived from the name a person opened; the application never sees a
   cookie of the platform's or an Authorization header, never plants one the panel would receive,
   and gets the browser's own Host. The panel is never framed.
5. THE CREDENTIAL (#271). Over TLS the panel's cookie is `__Host-openfactory_token` and the plain
   name counts for nothing; everywhere, a credential cookie that arrives twice is nobody's.
6. THE END. The reaper is scheduled and answers, truthfully, that it has nothing to end.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from openfactory import preview

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "preview.localhost"
WEB = "web--acme--12.preview.localhost"
#: The real client, kept before `_upstream` replaces `httpx.AsyncClient` with a mocked one.
_ASYNC_CLIENT = httpx.AsyncClient


# ── 1. the names ─────────────────────────────────────────────────────────────────────────────────


def test_the_panels_own_host_is_never_read_as_a_preview():
    assert preview.host_of("localhost:8787", DOMAIN) is None
    assert preview.host_of("panel.example.com", "preview.example.com") is None
    assert preview.host_of("evil.preview.localhost", DOMAIN) is None
    assert preview.host_of("acme--12.preview.localhost", DOMAIN) is None, "a unit is not a service"
    assert preview.host_of("x.web--acme--12.preview.localhost", DOMAIN) is None
    assert preview.host_of(WEB, "") is None
    assert not preview.under_domain("localhost:8787", DOMAIN)
    assert preview.under_domain("evil.preview.localhost", DOMAIN)


def test_a_host_names_one_service_of_one_unit():
    h = preview.host_of(f"{WEB}:8787", DOMAIN)
    assert (h.service, h.slug, h.unit, h.label) == ("web", "acme", "12", "web--acme--12")
    r = preview.host_of("api--acme-shop--req0012.preview.localhost", DOMAIN)
    assert (r.service, r.slug, r.unit) == ("api", "acme-shop", "req0012")


def test_every_name_is_built_from_the_project_and_the_unit():
    assert preview.unit_name("Acme Shop", "12") == "acme-shop--12"
    assert preview.compose_project("Acme Shop", "req0012") == "openfactory-pv-acme-shop-req0012"
    assert preview.edge_network("acme", "12") == "openfactory-pv-acme-12-edge"
    assert preview.cookie_name("acme", "12").startswith(preview.COOKIE_PREFIX)
    label = preview.host_label("Acme Corp / Web Shop " * 5, "req0012", "Front_End")
    assert len(label) <= 63 and label.endswith("--req0012") and "---" not in label
    assert preview.host_of(f"{label}.{DOMAIN}", DOMAIN) is not None


# ── 2. the key ───────────────────────────────────────────────────────────────────────────────────


def test_a_key_opens_one_unit_of_one_project_and_nothing_else(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PREVIEW_SECRET", "s3cret")
    key = preview.mint("acme", "12", expires=int(time.time()) + 60)
    assert preview.admits(key, project="acme", token="12")
    assert not preview.admits(key, project="acme", token="13")
    # the MAC covers the EXACT project name: two projects whose slugs collide never share a key
    assert not preview.admits(key, project="Acme", token="12")
    assert not preview.admits(key[:-1] + ("0" if key[-1] != "0" else "1"), project="acme",
                              token="12")
    assert not preview.admits(preview.mint("acme", "12", expires=int(time.time()) - 1),
                              project="acme", token="12")
    monkeypatch.setenv("OPENFACTORY_PREVIEW_SECRET", "another")
    assert not preview.admits(key, project="acme", token="12")


# ── 3. the record ────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def sink(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))


def _live(**kw) -> preview.Preview:
    base = dict(project="acme", unit="12", cards=("12",), state=preview.LIVE,
                services={"web": 3000, "api": 8000}, from_change={"api": True, "web": False},
                expires_at=int(time.time()) + 3600)
    base.update(kw)
    return preview.Preview(**base)


def test_the_worker_writes_one_row_per_card_and_the_panel_reads_the_unit_back(sink):
    from openfactory.observability.query import records_of_kind

    assert preview.record(_live(unit="req0012", kind="requirement", cards=("12", "13")))
    rows = records_of_kind("acme", preview.KIND)
    assert sorted(r["ticket"] for r in rows) == ["12", "13"], "a card is the ticket column"
    back = preview.latest("acme", "req0012")
    assert back.cards == ("12", "13") and back.services == {"web": 3000, "api": 8000}
    assert preview.latest("acme", "12") is None, "a card of the unit is not the unit"
    preview.record(_live(unit="req0012", cards=("12", "13"), state=preview.ENDED, why="merged"))
    assert preview.latest("acme", "req0012").why == "merged", "the newest row is the truth"


def test_a_host_is_served_only_by_one_live_unexpired_record(sink):
    host = preview.host_of(WEB, DOMAIN)
    acme = [SimpleNamespace(name="acme")]
    assert preview.serving(host, acme) is None
    preview.record(_live())
    rec, port = preview.serving(host, acme)
    assert (rec.project, port) == ("acme", 3000)
    assert preview.serving(preview.host_of("db--acme--12.preview.localhost", DOMAIN), acme) is None
    preview.record(_live(expires_at=int(time.time()) - 1))
    assert preview.serving(host, acme) is None, "an expired preview serves nothing"


def test_two_projects_whose_slugs_collide_serve_nothing(sink):
    preview.record(_live(project="acme"))
    preview.record(_live(project="ACME"))
    both = [SimpleNamespace(name="acme"), SimpleNamespace(name="ACME")]
    assert preview.serving(preview.host_of(WEB, DOMAIN), both) is None


# ── 4. the panel and the router ──────────────────────────────────────────────────────────────────


@pytest.fixture
def panel(monkeypatch, sink):
    from openfactory.api import app as api

    monkeypatch.setenv("OPENFACTORY_PREVIEW_DOMAIN", DOMAIN)
    monkeypatch.setenv("OPENFACTORY_PREVIEW_SECRET", "s3cret")
    monkeypatch.setattr(api, "ProjectRegistry",
                        lambda: SimpleNamespace(list=lambda: [SimpleNamespace(name="acme")]))
    preview.record(_live())
    return TestClient(api.app)


def _upstream(monkeypatch, respond):
    """Stand a fake application behind the router; `respond(request)` answers each call."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return respond(request)

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return seen


def _inside() -> str:
    """The Cookie header of a browser that came in through the panel's link."""
    kept = preview.mint("acme", "12", expires=int(time.time()) + 600)
    return f"{preview.cookie_name('acme', '12')}={kept}"


def test_a_host_under_the_preview_domain_never_reaches_the_panel(panel):
    for host in ("evil.preview.localhost", "web--acme--99.preview.localhost", "preview.localhost"):
        r = panel.get("/", headers={"host": host})
        assert r.status_code == 404
        assert "OpenFactory" not in r.text.split("</title>")[0]
    assert panel.get("/api/whoami", headers={"host": "evil.preview.localhost"}).status_code == 404


def test_the_link_names_each_service_on_its_own_host_with_a_key_for_minutes(panel):
    body = panel.get("/api/preview/acme/12").json()
    assert body["live"] is True and body["can_start"] is False
    assert [s["name"] for s in body["services"]] == ["web", "api"], \
        "the service the change did not touch comes first"
    url = httpx.URL(body["services"][0]["url"])
    assert url.host == WEB and url.path == preview.ENTER_PATH
    key = url.params["t"]
    assert preview.admits(key, project="acme", token="12")
    assert preview.expiry_of(key) <= time.time() + preview.LINK_TTL_SECONDS + 1


def test_the_link_says_why_when_there_is_nothing_to_open(panel, monkeypatch):
    # slice 3: the reason is the deployment's, judged at read time — here it names no runtime
    monkeypatch.delenv("OPENFACTORY_PREVIEW_RUNTIME", raising=False)
    none = panel.get("/api/preview/acme/13").json()
    assert none["live"] is False and none["can_start"] is False
    assert "OPENFACTORY_PREVIEW_RUNTIME" in none["why"]
    assert "req0012" in panel.get("/api/preview/acme/x").json()["why"]


def test_a_product_scoped_person_can_open_a_preview(panel, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PRODUCT_TOKENS", "ba-token:bia:Bia")
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "op-token:ana:Ana")
    r = panel.get("/api/preview/acme/12", headers={"authorization": "Bearer ba-token"})
    assert r.status_code == 200 and r.json()["live"] is True
    assert panel.get("/api/preview/acme/12").status_code == 401


def test_the_key_becomes_a_cookie_of_its_own_on_that_host_only(panel):
    link = preview.mint("acme", "12", expires=int(time.time()) + 60)
    r = panel.get(f"{preview.ENTER_PATH}?t={link}",
                  headers={"host": WEB, "x-forwarded-proto": "https"}, follow_redirects=False)
    assert r.status_code == 303
    cookie = r.headers["set-cookie"]
    name, value = cookie.split(";", 1)[0].split("=", 1)
    assert name == preview.cookie_name("acme", "12")
    low = cookie.lower()
    assert "httponly" in low and "secure" in low and "domain=" not in low
    # a key of its own, living as long as the preview — not the link's, which lives minutes
    assert value != link and preview.admits(value, project="acme", token="12")
    assert preview.expiry_of(value) == preview.latest("acme", "12").expires_at
    wrong = preview.mint("acme", "13", expires=int(time.time()) + 60)
    assert panel.get(f"{preview.ENTER_PATH}?t={wrong}", headers={"host": WEB},
                     follow_redirects=False).status_code == 403
    panel.cookies.clear()
    assert panel.get("/", headers={"host": WEB}).status_code == 401


def test_the_application_sees_none_of_the_platforms_cookies_and_the_browsers_own_host(
        panel, monkeypatch):
    seen = _upstream(monkeypatch, lambda req: httpx.Response(
        302, headers={"location": "http://web--acme--12:3000/login?next=/"},
        stream=httpx.ByteStream(b"")))
    cookie = "; ".join([_inside(), "openfactory_token=panel-secret",
                        "__Host-openfactory_token=panel-secret",
                        "openfactory_preview_other_7=someone-elses", "app_session=abc"])

    r = panel.get("/orders?page=2", headers={"host": f"{WEB}:8787", "cookie": cookie,
                                             "authorization": "Bearer panel-secret"},
                  follow_redirects=False)

    sent = seen[-1]
    assert str(sent.url) == "http://web--acme--12:3000/orders?page=2", "the target is the name"
    assert sent.headers["host"] == f"{WEB}:8787", "the browser's Host is forwarded unchanged"
    assert sent.headers.get("cookie") == "app_session=abc"
    assert "authorization" not in sent.headers
    assert r.headers["location"] == f"http://{WEB}:8787/login?next=/", "the alias is rewritten"


def test_a_preview_cannot_plant_a_cookie_the_panels_host_would_receive(panel, monkeypatch):
    _upstream(monkeypatch, lambda req: httpx.Response(200, stream=httpx.ByteStream(b"ok"),
                                                      headers=[
        ("set-cookie", "openfactory_token=ATTACKER; Domain=localhost; Path=/"),
        ("set-cookie", "openfactory_token=ATTACKER; Path=/"),
        ("set-cookie", "__Host-openfactory_token=ATTACKER; Path=/; Secure"),
        ("set-cookie", "tracking=1; Domain=preview.localhost; Path=/"),
        ("set-cookie", "openfactory_preview_acme_12=forged; Path=/"),
        ("set-cookie", "app_session=abc; Path=/; HttpOnly"),
    ]))
    r = panel.get("/", headers={"host": WEB, "cookie": _inside()})
    assert r.status_code == 200
    assert r.headers.get_list("set-cookie") == ["app_session=abc; Path=/; HttpOnly"]


def test_a_service_that_does_not_answer_is_named_with_what_to_check(panel, monkeypatch):
    def refused(request):
        raise httpx.ConnectError("refused")

    _upstream(monkeypatch, refused)
    r = panel.get("/", headers={"host": WEB, "cookie": _inside()})
    assert r.status_code == 502 and "0.0.0.0:3000" in r.text


def test_a_slow_first_page_is_still_starting_not_dead(panel, monkeypatch):
    def slow(request):
        raise httpx.ReadTimeout("slow")

    _upstream(monkeypatch, slow)
    r = panel.get("/", headers={"host": WEB, "cookie": _inside()})
    assert r.status_code == 504 and "still starting" in r.text


def test_a_header_the_application_wrote_in_utf8_reaches_the_browser_as_it_was_sent(
        panel, monkeypatch):
    """A download named in Japanese is an ordinary thing for an application to send, and the
    application here is agent-written. Re-encoding httpx's decoded form of the header as latin-1
    raised past every handler, and the person got a 500 from the panel instead of the preview."""
    import asyncio

    from openfactory.api import app as api

    named = 'attachment; filename="請求書.pdf"'.encode()
    _upstream(monkeypatch, lambda req: httpx.Response(
        200, headers=[(b"content-disposition", named)], stream=httpx.ByteStream(b"%PDF")))

    async def ask() -> httpx.Response:
        # STRAIGHT TO THE APP, NOT THROUGH `panel`: the TestClient decodes every response header
        # as UTF-8 and re-encodes it as ASCII, so a non-ASCII header cannot cross it at all.
        async with _ASYNC_CLIENT(transport=httpx.ASGITransport(app=api.app),
                                 base_url=f"http://{WEB}") as client:
            return await client.get("/invoice", headers={"host": WEB, "cookie": _inside()})

    r = asyncio.run(ask())
    assert r.status_code == 200 and r.content == b"%PDF"
    assert (b"content-disposition", named) in r.headers.raw, "the bytes the application sent"


def test_a_response_past_the_cap_is_declined_before_it_is_read_to_the_end(panel, monkeypatch):
    """The cap exists to spare the worker the cost of a huge answer, so it has to stop the READ —
    checked after a whole body is buffered, a preview answering 2 GB is held in memory first."""
    from openfactory.api import app as api

    monkeypatch.setattr(api, "_PREVIEW_BODY_CAP", 1024)
    produced: list[int] = []

    async def endless():
        for _ in range(10_000):
            produced.append(512)
            yield b"x" * 512

    _upstream(monkeypatch, lambda req: httpx.Response(200, content=endless()))
    r = panel.get("/big.iso", headers={"host": WEB, "cookie": _inside()})
    assert r.status_code == 502 and "too large" in r.text
    assert len(produced) <= 4, "the read stops at the cap, not at the end of the body"


def test_the_panel_refuses_to_be_framed(panel):
    r = panel.get("/", headers={"host": "localhost:8787"})
    assert r.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert r.headers["x-frame-options"] == "DENY"


# ── 5. the credential (#271) ─────────────────────────────────────────────────────────────────────


def _asked(cookie: str, *, https: bool = False) -> str:
    from openfactory.api.app import _credential_of

    headers = [(b"cookie", cookie.encode())]
    if https:
        headers.append((b"x-forwarded-proto", b"https"))
    return _credential_of(Request({"type": "http", "method": "GET", "path": "/api/x",
                                   "query_string": b"", "headers": headers}))


def test_a_credential_cookie_that_arrives_twice_is_nobodys():
    assert _asked("openfactory_token=mine") == "mine"
    assert _asked("openfactory_token=mine; openfactory_token=planted") == ""
    assert _asked("openfactory_token=planted; x=1; openfactory_token=mine") == ""


def test_over_tls_only_the_host_prefixed_cookie_counts():
    assert _asked("__Host-openfactory_token=mine", https=True) == "mine"
    # a plain cookie planted by a sibling cannot sign in a browser that holds none
    assert _asked("openfactory_token=planted", https=True) == ""
    assert _asked("__Host-openfactory_token=a; __Host-openfactory_token=b", https=True) == ""
    # and on plain http the prefix is not the panel's spelling
    assert _asked("__Host-openfactory_token=mine") == ""


def test_the_login_sets_the_spelling_the_gate_reads_and_the_logout_clears_both():
    from starlette.responses import Response

    from openfactory.api.app import _clear_credential_cookies, _session_response

    def cookie(https: bool) -> str:
        headers = [(b"host", b"panel.example.com")]
        if https:
            headers.append((b"x-forwarded-proto", b"https"))
        req = Request({"type": "http", "method": "POST", "path": "/auth/login", "scheme": "http",
                       "query_string": b"", "headers": headers})
        return _session_response(req, "/", "tok").headers["set-cookie"]

    assert cookie(True).startswith("__Host-openfactory_token=tok") and "Secure" in cookie(True)
    assert cookie(False).startswith("openfactory_token=tok") and "Secure" not in cookie(False)
    out = Response()
    _clear_credential_cookies(out)
    cleared = out.headers.getlist("set-cookie")
    assert any(c.startswith("openfactory_token=") for c in cleared)
    assert any(c.startswith("__Host-openfactory_token=") and "Secure" in c for c in cleared)


def test_the_page_adopts_the_cookie_in_the_panels_spelling_and_only_when_there_is_one():
    """The page copies the cookie into localStorage on boot — so the rule has to hold there too,
    or a planted cookie becomes the browser's stored credential for good."""
    page = (ROOT / "openfactory" / "api" / "panel.html").read_text(encoding="utf-8")
    assert 'const TOKEN_COOKIE=location.protocol==="https:"?"__Host-openfactory_token"' in page
    line = next(ln for ln in page.splitlines() if ln.startswith("function cookieToken()"))
    assert "TOKEN_COOKIE" in line and "all.length===1" in line


def test_a_workload_never_holds_the_key_previews_are_signed_with(monkeypatch):
    """A worktree workload holding the preview key could mint its own way into every preview —
    and `box.env` cannot hand it over either, because no harness authenticates with it."""
    from openfactory.adapters.sandbox.worktree import _scrubbed_env

    monkeypatch.setenv("OPENFACTORY_PREVIEW_SECRET", "s3cret")
    assert "OPENFACTORY_PREVIEW_SECRET" not in _scrubbed_env()
    assert "OPENFACTORY_PREVIEW_SECRET" not in _scrubbed_env(keep=("OPENFACTORY_PREVIEW_SECRET",))


# ── 6. the end ───────────────────────────────────────────────────────────────────────────────────


def test_the_reaper_is_scheduled_and_says_it_has_nothing_to_end():
    pytest.importorskip("temporalio")
    import asyncio

    from temporalio.testing import ActivityEnvironment

    from openfactory.runtime.temporal import activities, schedule, worker

    assert activities.reap_previews in worker.WORKER_ACTIVITIES
    assert schedule.PREVIEW_REAP_SCHEDULE_ID == "openfactory-preview-reaper"
    assert asyncio.run(ActivityEnvironment().run(activities.reap_previews)) == []
