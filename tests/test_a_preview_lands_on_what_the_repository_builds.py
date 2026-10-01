"""A preview's front door is a service the repository builds, or the one the shape declares (#435).

Found live: a job's pull request started its preview, the product role sent the link, and the
person landed on a storage emulator's root — `303 → 303 → 400` — with the application one button
further on the card. `Preview.ordered()` put the services NOT from the change first (S11), and a
service that only names an image is never from the change, so any compose document with a
backing service that exposes a port had its infrastructure as the landing page.

THE RULE IS STRUCTURAL, NEVER A NAME: built from the repository (`build:`) or pulled (`image:`
only). No image, vendor or service name decides it here — the backing service in these tests is
the fixture's `postgres:16` and an invented `blobstore`, and either could be anything."""
from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from openfactory import preview
from openfactory.contracts.manifest import PreviewConfig
from openfactory.contracts.product import ProductPreview
from openfactory.preview import demand, steps
from tests.test_a_preview_is_started_on_demand import (  # noqa: F401 — fixtures by name
    ACME,
    DOMAIN,
    HEAD,
    PR,
    Runtime,
    Store,
    _door,
    _live,
    _plan,
    _world,
    panel,
    sink,
)
from tests.test_the_shape_is_read_and_admitted import (
    S1_CFG,
    _canonical,
    _diff,
    _layout,
    _ok,
    _workdir,
)
from tests.test_the_shape_is_read_and_admitted import _plan as _assemble

# ── what the assembler records ───────────────────────────────────────────────────────────────────


@pytest.fixture
def s1_with_its_database_exposed(tmp_path, monkeypatch):
    """The s1 fixture — `web` and `api` built from the repository, `db` an image with a port —
    with `db` exposed too, the shape of the live finding."""
    monkeypatch.setenv("ACME_PV_DATABASE_URL", "postgres://admin:hunter2@db.prod:5432/shop")
    wd = _workdir(tmp_path, "s1")

    def plan(**cfg):
        shape = PreviewConfig(**{**S1_CFG.model_dump(),
                                 "expose": {"web": 3000, "api": 8000, "db": 5432}, **cfg})
        return _ok(_assemble(_canonical("s1", wd), shape, _layout(wd, _diff("s1"))))
    return plan


def test_the_plan_says_which_exposed_service_the_repository_builds(s1_with_its_database_exposed):
    plan = s1_with_its_database_exposed()
    assert plan.built == {"web": True, "api": True, "db": False}
    assert plan.entry == ""


def test_a_declared_entry_travels_on_the_plan(s1_with_its_database_exposed):
    assert s1_with_its_database_exposed(entry="api").entry == "api"


def test_the_record_carries_what_is_built_and_the_declared_entry():
    store = Store(preview.Preview(project="acme", unit="12", cards=("12",),
                                  state=preview.STARTING))
    steps.up(ACME, "12", _plan(built={"web": True, "api": True}, entry="api"),
             runtime=Runtime(), world=_world(store))
    live = store.rows[-1]
    assert live.built == {"web": True, "api": True} and live.entry == "api"


# ── the order a person is offered ────────────────────────────────────────────────────────────────


def _unit(**kw) -> preview.Preview:
    """Built `web` untouched, built `api` changed, and a pulled `blobstore` that exposes a port."""
    return _live(services={"web": 3000, "api": 8000, "blobstore": 10000},
                 from_change={"api": True, "web": False, "blobstore": False},
                 health={"web": "started", "api": "healthy", "blobstore": "started"}, **kw)


def test_a_pulled_service_is_never_the_front_door():
    order = _unit(built={"web": True, "api": True, "blobstore": False}).ordered()
    assert order[0] == "web", f"{order}: an image-only service came before what the repo builds"
    assert order[-1] == "blobstore"


def test_among_what_is_built_the_untouched_screen_still_comes_first():
    """S11 stands among the candidates: a back-end change is seen through the front end."""
    assert _unit(built={"web": True, "api": True, "blobstore": False}).ordered() == \
        ["web", "api", "blobstore"]


def test_a_declared_entry_wins_over_both_rules():
    assert _unit(built={"web": True, "api": True, "blobstore": False},
                 entry="blobstore").ordered()[0] == "blobstore"
    assert _unit(built={"web": True, "api": True, "blobstore": False},
                 entry="api").ordered() == ["api", "web", "blobstore"]


def test_an_entry_the_record_does_not_expose_is_ignored_rather_than_invented():
    assert _unit(built={"web": True, "api": True, "blobstore": False},
                 entry="gone").ordered()[0] == "web"


def test_a_record_that_does_not_say_what_is_built_keeps_the_old_order():
    """Written before `built` was kept: nothing to judge by, so S11 alone, as it always was."""
    assert _unit().ordered() == ["blobstore", "web", "api"]


def test_a_shape_that_builds_nothing_keeps_the_old_order():
    assert _unit(built={"web": False, "api": False, "blobstore": False}).ordered() == \
        ["blobstore", "web", "api"]


# ── where the card's first button and the comment's link land ────────────────────────────────────


def _walk(panel, first: str) -> list[str]:  # noqa: F811
    hops, url = [first], httpx.URL(first)
    for _ in range(6):
        if url.path != preview.ENTER_PATH:
            break
        r = _door(panel, url.host.split("--", 1)[0], url.query.decode())
        assert r.status_code == 303
        hops.append(r.headers["location"])
        url = httpx.URL(hops[-1])
    return hops


def test_the_first_button_and_the_comment_link_land_on_the_built_service(panel, monkeypatch):  # noqa: F811
    preview.record(_unit(built={"web": True, "api": True, "blobstore": False}))
    monkeypatch.setattr(demand, "forge_state", lambda *a, **k: demand.ForgeState(
        open=(PR,), heads={PR: HEAD}, branches={}))
    body = panel.get("/api/preview/acme/12").json()
    # the card's primary button AND `openPreviewNow` (the comment's link) both take services[0]
    assert body["services"][0]["name"] == "web"
    hops = _walk(panel, body["services"][0]["url"])
    end = httpx.URL(hops[-1])
    assert end.host == f"web--acme--12.{DOMAIN}" and end.path == "/", hops
    assert {httpx.URL(h).host for h in hops} >= {f"blobstore--acme--12.{DOMAIN}"}, (
        "the chain still opens every exposed service's door — only where it ends changed")


def test_a_declared_entry_is_where_the_link_lands(panel, monkeypatch):  # noqa: F811
    preview.record(_unit(built={"web": True, "api": True, "blobstore": False}, entry="api"))
    monkeypatch.setattr(demand, "forge_state", lambda *a, **k: demand.ForgeState(
        open=(PR,), heads={PR: HEAD}, branches={}))
    body = panel.get("/api/preview/acme/12").json()
    end = httpx.URL(_walk(panel, body["services"][0]["url"])[-1])
    assert end.host == f"api--acme--12.{DOMAIN}" and end.path == "/"


# ── the declaration ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("model,extra", [
    (PreviewConfig, {"compose": ["docker-compose.yml"]}),
    (ProductPreview, {"compose": "docker-compose.yml"}),
])
def test_an_entry_must_be_a_service_a_person_may_open(model, extra):
    ok = model(expose={"web": 3000}, entry="web", **extra)
    assert ok.entry == "web"
    with pytest.raises(ValidationError, match="preview.entry names 'db'"):
        model(expose={"web": 3000}, entry="db", **extra)


def test_a_products_declared_entry_reaches_the_assembler():
    """A product of several repositories declares its shape in the context repository; the
    assembler reads it through `ProductShape.config()`, the same `PreviewConfig` the manifest's
    block is — so the entry must cross that one line."""
    from openfactory.preview.product import ProductShape

    shape = ProductShape(context="acme/context", context_dir="context", shape_dir="context",
                         members={"context": "acme/context"},
                         preview=ProductPreview(compose="docker-compose.yml",
                                                expose={"web": 3000, "api": 8000}, entry="api"))
    assert shape.config().entry == "api"
