"""#348 — a change to the product's shape can be previewed before it merges, once a person allows it.

THE RULE (ADR-0050 D3). The shape is read from the base branch, never from the change: the compose
file lives in the repository the agent edits, and running the change's own would run whatever the
change declared. So a card that adds a `redis` service was previewed without `redis`, and the part
it asked for was seen only after the merge.

THE EXCEPTION, AND WHAT BOUNDS IT, PROVEN HERE on the recorded S1 shape, a real work directory and
the real reader, assembler and admission (only the compose CLI's answer is recorded):

  · nothing runs the change's shape unasked: no allowance, the base's runs, and the card carries
    the digest a product admin would allow;
  · an allowance for exactly that digest runs the change's shape, laid over the base tree;
  · a push that changes the shape is a different digest, and the base's runs again;
  · the change's shape passes the SAME admission, and a refused key is refused by name;
  · the overlay never writes through a link out of the work directory;
  · the row allows only the digest the record holds, tells the pull request, and builds again.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory import preview
from openfactory.actions.base import Actor
from openfactory.adapters.preview import compose
from openfactory.contracts.manifest import PreviewConfig
from openfactory.contracts.project import PreviewPolicy
from openfactory.preview import own, steps
from openfactory.preview.plan import PreviewPlan, Refused
from tests.test_a_preview_is_started_on_demand import ACME, Runtime, Store, _world
from tests.test_a_preview_is_started_on_demand import _plan as _a_plan
from tests.test_the_shape_is_read_and_admitted import UNIT, _canonical, _layout, _workdir

REDIS = "\n  redis:\n    image: redis:7\n"
DIFF = ("docker-compose.yml", "api/app.py")


def _project():
    # room for the card's fifth service: the memory budget is the operator's, and not the point
    return SimpleNamespace(name="acme", manifest_path=".openfactory/project.yaml",
                           preview=PreviewPolicy(memory_total="16g"), repo_path="/src/shop")


def _with_redis(wd: str, *, extra: str = "") -> None:
    """The change adds a `redis` service — the card's whole point."""
    f = Path(wd, "change", "app", "docker-compose.yml")
    text = f.read_text().replace("\nvolumes:\n", REDIS + extra + "\nvolumes:\n")
    f.write_text(text)


class _CLI:
    """The compose CLI's answer, recorded from the pinned plugin for S1 — plus whatever service the
    file it is handed at that moment declares beyond it, read from DISK, so a test can say which
    shape reached it."""

    def __init__(self, wd: str):
        self.wd = wd
        self.read: list[str] = []

    def __call__(self, argv, **_kw):
        path = argv[argv.index("-f") + 1]
        text = Path(path).read_text()
        self.read.append(text)
        doc = _canonical("s1", self.wd)
        if "redis:" in text:
            doc["services"]["redis"] = {"image": "redis:7", "networks": {"default": None}}
            if "privileged: true" in text:
                doc["services"]["redis"]["privileged"] = True
        return subprocess.CompletedProcess(argv, 0, json.dumps(doc), "")


@pytest.fixture
def unit(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PREVIEW_DOMAIN", "preview.example.com")
    wd = _workdir(tmp_path, "s1")
    cli = _CLI(wd)
    monkeypatch.setattr(compose, "_as_run", cli)
    allowances: dict[str, tuple[str, str]] = {}
    monkeypatch.setattr(own, "allowed", lambda project, token: allowances.get(token))

    def plan():
        return compose.plan(_layout(wd, DIFF), UNIT, _project(), others=[], now=1_800_000_000)

    return SimpleNamespace(wd=wd, cli=cli, allowances=allowances, plan=plan)


def _digest_of_the_change(wd: str) -> str:
    cfg = PreviewConfig(compose=["docker-compose.yml"], expose={"web": 3000, "api": 8000},
                        data={"api": "python manage.py loaddata demo"})
    found = own.of_the_change(_layout(wd, DIFF), tree="app", change_cfg=cfg)
    assert isinstance(found, own.OwnShape), found
    return found.digest


# ═══ nothing runs the change's shape unasked ════════════════════════════════════════════════════

def test_with_no_allowance_the_base_runs_and_the_card_carries_the_digest_to_allow(unit):
    _with_redis(unit.wd)

    got = unit.plan()

    assert isinstance(got, PreviewPlan), getattr(got, "reasons", got)
    assert got.shape_from == "base" and "redis" not in got.doc["services"]
    assert got.own_shape == _digest_of_the_change(unit.wd)
    (said,) = [n for n in got.notes if "this change edits" in n]
    assert own.short(got.own_shape) in said and "product admin" in said
    assert all("redis" not in t for t in unit.cli.read), "the change's compose reached the CLI"


def test_a_change_that_does_not_edit_the_shape_has_no_digest(unit, monkeypatch):
    got = compose.plan(_layout(unit.wd, ("api/app.py",)), UNIT, _project(), others=[],
                       now=1_800_000_000)
    assert isinstance(got, PreviewPlan) and got.own_shape == "" and got.shape_from == "base"


# ═══ the allowance runs exactly what was read ═══════════════════════════════════════════════════

def test_an_allowance_for_that_digest_runs_the_changes_shape_over_the_base_tree(unit):
    _with_redis(unit.wd)
    unit.allowances["12"] = (_digest_of_the_change(unit.wd), "ana")

    got = unit.plan()

    assert isinstance(got, PreviewPlan), getattr(got, "reasons", got)
    assert got.shape_from == "change" and "redis" in got.doc["services"]
    (said,) = [n for n in got.notes if "this change edits" in n]
    assert "change's own shape" in said and "allowed by ana" in said
    # laid over the BASE tree, so D4 holds: what the change did not touch still runs from the base
    assert "redis" in Path(unit.wd, "base", "app", "docker-compose.yml").read_text()
    assert got.from_change.get("web") is False


def test_a_push_that_changes_the_shape_goes_back_to_the_base(unit):
    _with_redis(unit.wd)
    unit.allowances["12"] = (_digest_of_the_change(unit.wd), "ana")
    _with_redis(unit.wd, extra="    command: redis-server --save ''\n")  # pushed after the look

    got = unit.plan()

    assert isinstance(got, PreviewPlan) and got.shape_from == "base"
    assert "redis" not in got.doc["services"]
    (said,) = [n for n in got.notes if "this change edits" in n]
    assert "has changed since ana allowed" in said


def test_the_changes_shape_passes_the_same_admission_and_a_refused_key_is_named(unit):
    _with_redis(unit.wd, extra="    privileged: true\n")
    unit.allowances["12"] = (_digest_of_the_change(unit.wd), "ana")

    got = unit.plan()

    assert isinstance(got, Refused)
    assert any("privileged" in r for r in got.reasons), got.reasons


# ═══ the digest is what was read ════════════════════════════════════════════════════════════════

def test_the_digest_moves_with_the_block_the_files_and_an_extended_file():
    cfg = PreviewConfig(compose=["c.yml"], expose={"web": 1})
    base = own.digest(cfg, {"app/c.yml": "services: {}"})
    assert own.digest(cfg, {"app/c.yml": "services: {}"}) == base
    assert own.digest(cfg, {"app/c.yml": "services: {a: {}}"}) != base
    assert own.digest(PreviewConfig(compose=["c.yml"], expose={"web": 2}),
                      {"app/c.yml": "services: {}"}) != base
    assert own.digest(cfg, {"app/c.yml": "services: {}", "app/x.yml": "y"}) != base


def test_a_change_with_no_block_has_no_shape_of_its_own(tmp_path):
    wd = _workdir(tmp_path, "s1")
    said = own.of_the_change(_layout(wd, DIFF), tree="app", change_cfg=None)
    assert isinstance(said, str) and "no `preview:` block" in said


# ═══ the overlay stays in the tree ══════════════════════════════════════════════════════════════

def test_the_overlay_replaces_a_link_and_never_writes_through_it(tmp_path):
    wd = _workdir(tmp_path, "s1")
    outside = tmp_path / "outside.yml"
    outside.write_text("the operator's own file\n")
    dest = Path(wd, "base", "app", "docker-compose.yml")
    dest.unlink()
    dest.symlink_to(outside)

    why = own.overlay(_layout(wd, DIFF), tree="app",
                      texts={"app/docker-compose.yml": "services: {}\n"})

    assert why == ""
    assert outside.read_text() == "the operator's own file\n", "the write went through the link"
    assert not dest.is_symlink() and dest.read_text() == "services: {}\n"


def test_the_overlay_refuses_a_directory_that_leads_out(tmp_path):
    wd = _workdir(tmp_path, "s1")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    Path(wd, "base", "app", ".openfactory", "out").symlink_to(elsewhere)

    why = own.overlay(_layout(wd, DIFF), tree="app",
                      texts={"app/.openfactory/out/preview.compose.yml": "services: {}\n"})

    assert "link or a file" in why and list(elsewhere.iterdir()) == []


def test_the_overlay_refuses_a_path_outside_the_repository(tmp_path):
    wd = _workdir(tmp_path, "s1")
    why = own.overlay(_layout(wd, DIFF), tree="app", texts={"other/compose.yml": "x"})
    assert "outside the repository" in why


# ═══ the record and the row ═════════════════════════════════════════════════════════════════════

def test_up_records_the_digest_and_which_shape_ran():
    store = Store(preview.Preview(project="acme", unit="12", cards=("12",),
                                  state=preview.STARTING))
    steps.up(ACME, "12", _a_plan(own_shape="d" * 64, shape_from="change"), runtime=Runtime(),
             world=_world(store))
    live = store.rows[-1]
    assert (live.own_shape, live.shape_from) == ("d" * 64, "change")


def _the_row(monkeypatch, record, *, admin=True):
    from openfactory.actions import catalog
    from openfactory.product import module

    allowed: list[tuple] = []
    told: list[tuple] = []
    rebuilt: list[str] = []

    async def rebuild(*, project, unit, by):
        rebuilt.append(unit)
        return catalog.done("being rebuilt", state=preview.STARTING)

    forge = SimpleNamespace(review_pr=lambda **kw: told.append((kw["pr"], kw["body"])))
    monkeypatch.setattr(catalog, "_preview_target",
                        lambda project, unit: (SimpleNamespace(name="acme"), "12", record, None))
    monkeypatch.setattr(own, "allow_shape", lambda *a: allowed.append(a) or True)
    monkeypatch.setattr(own, "allowed", lambda project, token: None)
    monkeypatch.setattr(catalog, "_forge_and_manifest", lambda name: (None, None, forge))
    monkeypatch.setattr(catalog, "_preview_rebuild", rebuild)
    monkeypatch.setattr(module, "may_act", lambda project, user, via="api": admin and user == "ana")
    ana = Actor(id="ana", display="ana", via="test", admin=True)
    out = asyncio.run(catalog._preview_own_shape(project="acme", unit="12", by=ana))
    return out, allowed, told, rebuilt


def test_the_row_allows_the_digest_the_record_holds_tells_the_pull_request_and_rebuilds(
        monkeypatch):
    record = preview.Preview(project="acme", unit="12", state=preview.LIVE, own_shape="e" * 64,
                             pr_urls=("https://forge/acme/shop/pull/12",))
    out, allowed, told, rebuilt = _the_row(monkeypatch, record)

    assert out.ok and allowed == [("acme", "12", "e" * 64, "ana")]
    ((pr, body),) = told
    assert pr.endswith("/pull/12") and "eeeeeeeeeeee" in body
    assert rebuilt == ["12"]


def test_only_a_product_admin_may_allow_it_not_every_panel_credential(monkeypatch):
    """On the panel every credential that got in is `admin`, a product-scoped one included. That is
    enough to start a preview, and not enough to let one run what the change declares."""
    record = preview.Preview(project="acme", unit="12", state=preview.LIVE, own_shape="e" * 64)
    out, allowed, told, rebuilt = _the_row(monkeypatch, record, admin=False)
    assert not out.ok and "product admin" in out.message
    assert allowed == [] and told == [] and rebuilt == []


def test_the_row_refuses_a_change_whose_shape_nobody_measured(monkeypatch):
    out, allowed, told, rebuilt = _the_row(
        monkeypatch, preview.Preview(project="acme", unit="12", state=preview.LIVE))
    assert not out.ok and "does not edit the product's shape" in out.message
    assert allowed == [] and told == [] and rebuilt == []


def test_an_allowance_is_recorded_and_the_newest_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    assert own.allowed("acme", "12") is None
    assert own.allow_shape("acme", "12", "a" * 64, "ana")
    assert own.allow_shape("acme", "12", "b" * 64, "rui")
    assert own.allow_shape("acme", "13", "c" * 64, "eva")
    assert own.allowed("acme", "12") == ("b" * 64, "rui")


def test_the_card_and_the_panel_offer_it_only_where_the_server_says():
    root = Path(__file__).resolve().parents[1]
    app = (root / "openfactory/api/app.py").read_text()
    panel = (root / "openfactory/api/panel.html").read_text()
    assert '"can_allow_shape": bool(found and found.own_shape and found.shape_from != "change"' \
        in app and "and _a_product_admin(owner, _actor(request))" in app
    assert "if(r.can_allow_shape)" in panel and "previewAct(btn, \"own_shape\")" in panel
    assert os.path.exists(root / "docs/adr/0050-a-preview-before-the-merge.md")
    assert "#348" in (root / "docs/adr/0050-a-preview-before-the-merge.md").read_text()


def test_a_file_an_extends_reaches_is_part_of_what_is_digested(tmp_path):
    """A shape is every file it reads: an edit to a file only an `extends:` names is an edit to
    the shape, and must move the digest an allowance names."""
    wd = _workdir(tmp_path, "s1")
    change = Path(wd, "change", "app")
    (change / "compose.yaml").write_text(
        "services:\n  api:\n    extends:\n      file: common.yml\n      service: base\n")
    (change / "common.yml").write_text("services:\n  base:\n    image: busybox\n")
    cfg = PreviewConfig(compose=["compose.yaml"], expose={"api": 8000})

    first = own.of_the_change(_layout(wd, DIFF), tree="app", change_cfg=cfg)
    (change / "common.yml").write_text("services:\n  base:\n    image: alpine\n")
    second = own.of_the_change(_layout(wd, DIFF), tree="app", change_cfg=cfg)

    assert isinstance(first, own.OwnShape) and set(first.texts) == {"app/compose.yaml",
                                                                     "app/common.yml"}
    assert isinstance(second, own.OwnShape) and second.digest != first.digest


def test_a_change_manifest_that_links_out_is_not_read_and_nothing_of_it_is_said(unit, tmp_path):
    """The change's manifest is the agent's. A link out of the checkout would hand the reader any
    file on the worker, and a parse error quotes what it could not parse."""
    secret = tmp_path / "secret.txt"
    secret.write_text("TOKEN=hunter2 : [unbalanced\n")
    manifest = Path(unit.wd, "change", "app", ".openfactory", "project.yaml")
    manifest.unlink()
    manifest.symlink_to(secret)

    got = unit.plan()

    assert isinstance(got, PreviewPlan) and got.shape_from == "base" and got.own_shape == ""
    assert not any("hunter2" in n for n in got.notes)
    assert any("not a file inside its checkout" in n for n in got.notes)
