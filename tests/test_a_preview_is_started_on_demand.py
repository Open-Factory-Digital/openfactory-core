"""A preview is started on demand from its card, watched while it lives, and ended on purpose
(#265 slice 3; ADR-0050 D6; the design's §4.3, §5.2 and §5.5).

1. ONE CLICK OPENS EVERY EXPOSED SERVICE. Each host needs a cookie of its own, so the enter door
   chains: it sets this host's cookie and hands the browser to the next exposed service's door of
   the SAME unit — the hops read from the record, never the query string — ending on the page the
   button was for. It cannot be steered to another unit, another project or a URL.
2. THE CARD SAYS WHAT CAN BE DONE, judged when it is read: `can_start` from the deployment (a
   runtime named) and the forge (an open pull request of the unit), `stale` from the head the
   forge reports now against the head the preview was built from.
3. THE FOUR ROUTES are the catalog's rows, reachable by the product-scoped person who asked for the
   change; a second start answers `starting`; stop and rebuild reach a running workflow only.
4. THE STEPS, with a faked runtime and forge: a fresh materialise after the old stack is taken
   down (logs first), the cap refused BY NAME, `live` with the heads it was built from, a failed
   start kept for a person to read unless nothing of it reached the daemon, a crashed service
   `failed` with its last lines.
5. THE WORKFLOW, on Temporal's own test engine: stop, rebuild, expiry, a failed step, a step that
   died, the watch continued as new — and a second start of one unit refused by the engine.
6. THE OFFER, through the walking skeleton: `offered` at the human gate, never a runtime called,
   never a live record overwritten.
7. THE CLI's twins.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from openfactory import preview
from openfactory.preview import demand, steps
from openfactory.preview.plan import (
    Layout,
    PreviewPlan,
    PreviewUp,
    Refused,
    RunningPreview,
    Tree,
    Unit,
)

DOMAIN = "preview.localhost"
PR = "https://forge/acme/shop/pull/12"
HEAD, MOVED = "a" * 40, "d" * 40


@pytest.fixture
def sink(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    demand._CACHE.clear()
    yield
    demand._CACHE.clear()


def _live(**kw) -> preview.Preview:
    base = dict(project="acme", unit="12", cards=("12",), state=preview.LIVE,
                services={"web": 3000, "api": 8000, "admin": 9000},
                from_change={"api": True, "web": False, "admin": False},
                health={"api": "healthy", "web": "started", "admin": "started"},
                heads={PR: HEAD}, branches={PR: "openfactory/12"}, pr_urls=(PR,),
                expires_at=int(time.time()) + 3600)
    base.update(kw)
    return preview.Preview(**base)


# ── 1. one click opens every exposed service ─────────────────────────────────────────────────────


@pytest.fixture
def panel(monkeypatch, sink, tmp_path):
    from openfactory.api import app as api
    from openfactory.contracts.project import Project
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_PREVIEW_DOMAIN", DOMAIN)
    monkeypatch.setenv("OPENFACTORY_PREVIEW_SECRET", "s3cret")
    monkeypatch.setenv("OPENFACTORY_PREVIEW_RUNTIME", "compose")
    for env in ("OPENFACTORY_PANEL_TOKEN", "OPENFACTORY_PANEL_TOKENS", "OPENFACTORY_PRODUCT_TOKENS"):
        monkeypatch.delenv(env, raising=False)
    reg = ProjectRegistry()
    reg.add(Project(name="acme", repo_path=str(tmp_path / "acme")))
    reg.add(Project(name="other", repo_path=str(tmp_path / "other")))
    preview.record(_live())
    return TestClient(api.app)


def _key(unit: str = "12", project: str = "acme") -> str:
    return preview.mint(project, unit, expires=int(time.time()) + 300)


def _door(panel, service: str, query: str, unit: str = "12"):
    return panel.get(f"{preview.ENTER_PATH}?{query}",
                     headers={"host": f"{service}--acme--{unit}.{DOMAIN}:8787"},
                     follow_redirects=False)


def test_the_order_offers_what_the_change_did_not_touch_first():
    assert _live().ordered() == ["admin", "web", "api"]


def test_one_click_walks_every_exposed_services_door_and_lands_on_the_one_pressed(panel):
    key = _key()
    r = _door(panel, "web", f"t={key}&next=api&to=web")
    assert r.status_code == 303
    assert r.headers["set-cookie"].startswith(preview.cookie_name("acme", "12") + "=")
    assert "domain=" not in r.headers["set-cookie"].lower(), "each host keeps its own cookie"
    hops = [r.headers["location"]]
    for _ in range(5):
        url = httpx.URL(hops[-1])
        if url.path != preview.ENTER_PATH:
            break
        service = url.host.split("--", 1)[0]
        nxt = _door(panel, service, url.query.decode())
        assert nxt.status_code == 303 and preview.cookie_name("acme", "12") in \
            nxt.headers["set-cookie"]
        hops.append(nxt.headers["location"])
    hosts = [httpx.URL(h).host for h in hops]
    assert hosts == [f"api--acme--12.{DOMAIN}", f"admin--acme--12.{DOMAIN}",
                     f"web--acme--12.{DOMAIN}"], hops
    last = httpx.URL(hops[-1])
    assert last.path == "/" and last.port == 8787, "the chain ends on the page the button was for"
    assert all(f"t={key}" in h for h in hops[:-1]), "every door checks the same key again"


def test_the_link_the_card_hands_out_is_the_start_of_that_chain(panel, monkeypatch):
    monkeypatch.setattr(demand, "forge_state", lambda *a, **k: demand.ForgeState(
        open=(PR,), heads={PR: HEAD}, branches={}))
    body = panel.get("/api/preview/acme/12").json()
    assert [s["name"] for s in body["services"]] == ["admin", "web", "api"]
    url = httpx.URL(body["services"][1]["url"])
    assert url.host == f"web--acme--12.{DOMAIN}" and url.path == preview.ENTER_PATH
    assert (url.params["next"], url.params["to"]) == ("api", "web")
    assert preview.admits(url.params["t"], project="acme", token="12")


def test_a_door_with_no_chain_lands_on_its_own_page(panel):
    r = _door(panel, "api", f"t={_key()}")
    assert r.status_code == 303 and r.headers["location"] == "/"


@pytest.mark.parametrize("steer", [
    "next=https://evil.example/x", "next=//evil.example", "next=db", "next=api--other--12",
    "next=web--acme--13", "to=https://evil.example", "next=api%0d%0aLocation:%20https://evil",
])
def test_the_chain_cannot_be_steered_off_the_unit(panel, steer):
    r = _door(panel, "web", f"t={_key()}&{steer}")
    assert r.status_code == 303
    where = r.headers["location"]
    allowed = {f"{s}--acme--12.{DOMAIN}" for s in ("web", "api", "admin")}
    assert where == "/" or httpx.URL(where).host in allowed, where
    assert "evil" not in where and "other" not in where and "--13" not in where


def test_the_chain_never_leaves_the_project_the_record_names(panel):
    preview.record(_live(project="other"))
    r = _door(panel, "web", f"t={_key()}&next=api&to=web")
    assert httpx.URL(r.headers["location"]).host == f"api--acme--12.{DOMAIN}"


def test_a_key_for_another_unit_opens_no_door_of_this_one(panel):
    preview.record(_live(unit="13", cards=("13",)))
    r = _door(panel, "web", f"t={_key('13')}&next=api&to=web")
    assert r.status_code == 403 and "set-cookie" not in r.headers


def test_the_router_waits_as_long_as_the_operator_said_for_that_project():
    from openfactory.api.app import _PREVIEW_UPSTREAM_TIMEOUT_S, _upstream_timeout
    from openfactory.contracts.project import PreviewPolicy

    slow = SimpleNamespace(name="acme", preview=PreviewPolicy(upstream_timeout_seconds=600))
    other = SimpleNamespace(name="other", preview=PreviewPolicy(upstream_timeout_seconds=5))
    assert _upstream_timeout([other, slow], _live()) == 600.0
    assert _upstream_timeout([SimpleNamespace(name="acme")], _live()) == \
        _PREVIEW_UPSTREAM_TIMEOUT_S


def test_the_chain_is_derived_from_the_record_alone():
    rec = _live()
    assert preview.next_door(rec, "web", next_="api", to="web") == ("api", "admin", "web")
    assert preview.next_door(rec, "api", next_="admin", to="web") == ("admin", "", "web")
    assert preview.next_door(rec, "admin", to="web") == ("web", "", "")
    assert preview.next_door(rec, "web", next_="api") == ("api", "admin", "web"), \
        "a chain begun without `to` ends where it began, every other door visited on the way"
    assert preview.next_door(rec, "admin", next_="web") == ("web", "api", "admin"), \
        "from the first service offered, it ends on the first service's page"
    assert preview.next_door(rec, "web", next_="nope", to="nope") == ("web", "", "")
    assert preview.next_door(rec, "db", next_="api") == ("db", "", "")
    assert preview.first_hop(rec, "web") == "api" and preview.first_hop(rec, "api") == "admin"
    assert preview.first_hop(_live(services={"web": 3000}), "web") == ""


# ── 2. what the card says, judged when it is read ────────────────────────────────────────────────


class Forge:
    """A forge that answers about one branch and one pull request."""

    def __init__(self, *, pr: str = PR, status: str = "open", remote: str | None = None):
        self.pr, self.status, self.remote = pr, status, remote
        self.asked: list[str] = []

    def pr_for_head(self, head, **_):
        self.asked.append(head)
        return self.pr

    def pr_status(self, *, pr, **_):
        if self.status == "unreadable":
            raise RuntimeError("the forge is down")
        return self.status

    def push_remote(self):
        return self.remote


def test_a_card_can_start_when_a_runtime_is_named_and_its_pull_request_is_open(sink):
    offered = preview.Preview(project="acme", unit="12", cards=("12",), state=preview.OFFERED,
                              pr_urls=(PR,), branches={PR: "openfactory/12"})
    project = SimpleNamespace(name="acme", repo_path="/r")
    state = demand.forge_state(project, "12", offered, forge_of=lambda p: Forge(),
                               heads_of=lambda remote, branch: HEAD)
    assert state.open == (PR,)
    judged = demand.judge(offered, kind="compose", forge=state)
    assert judged.can_start and judged.why == ""

    none = demand.judge(offered, kind="none", forge=state)
    assert not none.can_start and "OPENFACTORY_PREVIEW_RUNTIME" in none.why
    required = demand.judge(offered, kind="none", forge=state, required=True)
    assert "wait for a person" in required.why

    closed = demand._forge_state(project, "12", offered, forge_of=lambda p: Forge(status="closed"),
                                 heads_of=None)
    assert not demand.judge(offered, kind="compose", forge=closed).can_start


def test_can_start_is_never_read_off_what_the_job_offered(sink):
    """An offer written on a runtime-less deployment says why; once a runtime is named the card
    can start one — the answer is the deployment's NOW, not the record's then."""
    stale_offer = preview.Preview(project="acme", unit="12", state=preview.OFFERED,
                                  pr_urls=(PR,), why="no preview can run on this deployment")
    state = demand.ForgeState(open=(PR,), heads={}, branches={})
    assert demand.judge(stale_offer, kind="compose", forge=state).can_start


def test_a_card_nobody_offered_finds_its_pull_request_by_the_jobs_branch(sink):
    forge = Forge()
    state = demand._forge_state(SimpleNamespace(name="acme", repo_path="/r"), "12", None,
                                forge_of=lambda p: forge, heads_of=lambda r, b: HEAD)
    assert forge.asked == ["openfactory/12"] and state.open == (PR,)
    nothing = demand._forge_state(SimpleNamespace(name="acme", repo_path="/r"), "12", None,
                                  forge_of=lambda p: Forge(pr=""), heads_of=None)
    judged = demand.judge(None, kind="compose", forge=nothing)
    assert not judged.can_start and "no open pull request" in judged.why


def test_a_forge_that_cannot_answer_is_not_a_closed_pull_request(sink):
    offered = preview.Preview(project="acme", unit="12", state=preview.OFFERED, pr_urls=(PR,))
    unread = demand._forge_state(SimpleNamespace(name="acme", repo_path="/r"), "12", offered,
                                 forge_of=lambda p: Forge(status="unreadable"), heads_of=None)
    assert unread.open is None
    assert demand.judge(offered, kind="compose", forge=unread).can_start, \
        "an offered unit may still be started; the plan activity asks the forge again"


def test_a_moved_branch_shows_stale_on_the_card(panel, monkeypatch):
    monkeypatch.setattr(demand, "_forge_of", lambda project: Forge())
    monkeypatch.setattr(demand, "ls_remote", lambda remote, branch: MOVED)
    body = panel.get("/api/preview/acme/12").json()
    assert body["live"] is True
    assert body["stale"] == [f"built from {HEAD[:7]}; the pull request is now at {MOVED[:7]} — "
                             f"rebuild."]
    demand._CACHE.clear()
    monkeypatch.setattr(demand, "ls_remote", lambda remote, branch: HEAD)
    assert panel.get("/api/preview/acme/12").json()["stale"] == []


def test_the_forge_is_asked_once_a_minute_per_unit_at_most(sink):
    calls = []

    def forge_of(project):
        calls.append(project.name)
        return Forge()

    project = SimpleNamespace(name="acme", repo_path="/r")
    rec = _live()
    for _ in range(3):
        demand.forge_state(project, "12", rec, forge_of=forge_of, heads_of=lambda r, b: HEAD,
                           now=1000.0)
    assert calls == ["acme"]
    demand.forge_state(project, "12", rec, forge_of=forge_of, heads_of=lambda r, b: HEAD,
                       now=1000.0 + demand.FORGE_TTL_SECONDS)
    assert calls == ["acme", "acme"]


def test_the_body_carries_what_the_card_renders(panel, monkeypatch):
    preview.record(_live(images={"db": "postgres@sha256:1 pulled today"},
                         base_moved={"acme/shop": "branched from 1111111, now 2222222"},
                         notes=("`ports:` is not used in a preview.",), log_dir="/logs/acme--12",
                         commits={"acme/shop": HEAD}, started_by="Ana"))
    monkeypatch.setattr(demand, "forge_state", lambda *a, **k: demand.ForgeState(
        open=(PR,), heads={PR: HEAD}, branches={}))
    body = panel.get("/api/preview/acme/12").json()
    for key in ("state", "services", "images", "base_moved", "notes", "missing", "stale",
                "proposal_url", "why", "log_dir", "expires_at", "commits", "can_start"):
        assert key in body, key
    assert body["can_start"] is False, "a live preview is not started again"
    assert body["images"] == {"db": "postgres@sha256:1 pulled today"}
    assert body["started_by"] == "Ana" and body["log_dir"] == "/logs/acme--12"


def test_a_card_of_a_requirement_is_read_as_the_requirement(panel, monkeypatch):
    preview.record(_live(unit="req0012", kind="requirement", cards=("12", "13")))
    monkeypatch.setattr(demand, "forge_state", lambda *a, **k: demand.ForgeState(
        open=(PR,), heads={}, branches={}))
    body = panel.get("/api/preview/acme/13").json()
    assert body["unit"] == "req0012" and body["live"] is True
    assert "--req0012." in body["services"][0]["url"]


# ── 3. the four routes ──────────────────────────────────────────────────────────────────────────


class Engine:
    """The durable engine the rows start and signal, held in a list."""

    def __init__(self):
        from temporalio.client import WorkflowExecutionStatus

        self.status = WorkflowExecutionStatus
        self.started: list[tuple[str, object]] = []
        self.running: set[str] = set()
        self.signals: list[tuple[str, str, str]] = []

    async def start_workflow(self, run, params, *, id, task_queue):
        from temporalio.exceptions import WorkflowAlreadyStartedError

        if id in self.running:
            raise WorkflowAlreadyStartedError(id, "PreviewWorkflow")
        self.running.add(id)
        self.started.append((id, params))

    def get_workflow_handle(self, wf_id):
        engine = self

        class Handle:
            async def describe(self):
                return SimpleNamespace(status=engine.status.RUNNING if wf_id in engine.running
                                       else engine.status.COMPLETED)

            async def signal(self, sig, by):
                engine.signals.append((wf_id, sig.__name__, by))

        return Handle()


@pytest.fixture
def engine(monkeypatch):
    pytest.importorskip("temporalio")
    from openfactory.runtime.temporal import view

    held = Engine()

    async def connect():
        return held

    monkeypatch.setattr(view, "connect", connect)
    return held


def test_start_starts_the_units_one_workflow_and_a_second_start_answers_starting(panel, engine):
    preview.record(preview.Preview(project="acme", unit="14", cards=("14",),
                                   state=preview.OFFERED, pr_urls=(PR,)))
    first = panel.post("/api/preview/acme/14/start")
    assert first.status_code == 200 and first.json()["state"] == "starting"
    (wf_id, params), = engine.started
    assert wf_id == "preview--acme--14" == preview.workflow_id("acme", "14")
    assert (params.project, params.unit, params.runtime) == ("acme", "14", "compose")
    again = panel.post("/api/preview/acme/14/start")
    assert again.status_code == 200 and again.json()["state"] == "starting"
    assert len(engine.started) == 1, "a second start is the engine refusing a duplicate"


def test_start_on_a_live_preview_answers_live_and_starts_nothing(panel, engine):
    r = panel.post("/api/preview/acme/12/start")
    assert r.json()["state"] == "live" and engine.started == []


def test_start_is_refused_by_name_where_no_runtime_is_named(panel, engine, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PREVIEW_RUNTIME", "none")
    r = panel.post("/api/preview/acme/14/start")
    assert r.status_code == 409 and "OPENFACTORY_PREVIEW_RUNTIME" in r.json()["message"]
    assert engine.started == []


def test_stop_and_rebuild_reach_a_running_workflow_only(panel, engine):
    assert panel.post("/api/preview/acme/12/stop").status_code == 409, \
        "a stop over nothing is refused, never reported done"
    engine.running.add("preview--acme--12")
    assert panel.post("/api/preview/acme/12/stop").json()["ok"] is True
    assert panel.post("/api/preview/acme/12/rebuild").json()["state"] == "starting"
    assert [s for _, s, _ in engine.signals] == ["stop", "rebuild"]
    assert all(wf == "preview--acme--12" and by for wf, _, by in engine.signals), \
        "each signal reaches the unit's one workflow, saying who asked"


def test_a_rebuild_with_nothing_running_is_a_start(panel, engine):
    preview.record(_live(state=preview.FAILED, why="`api` exited with code 1"))
    r = panel.post("/api/preview/acme/12/rebuild")
    assert r.json()["state"] == "starting" and engine.started[0][0] == "preview--acme--12"


def test_the_routes_are_the_product_areas_and_refuse_what_they_cannot_act_on(
        panel, engine, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PRODUCT_TOKENS", "ba-token:bia:Bia")
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "op-token:ana:Ana")
    preview.record(preview.Preview(project="acme", unit="14", state=preview.OFFERED,
                                   pr_urls=(PR,)))
    ba = {"authorization": "Bearer ba-token"}
    ok = panel.post("/api/preview/acme/14/start", headers=ba)
    assert ok.status_code == 200 and engine.started[0][1].started_by == "Bia"
    assert panel.post("/api/preview/acme/14/start").status_code == 401
    # A COOKIE ALONE STARTS NOTHING: the page sends its Bearer header, and a cross-site form post
    # carries only the cookie — the gate reads it, the mutating routes do not.
    cookie_only = panel.post("/api/preview/acme/14/stop",
                             headers={"cookie": "openfactory_token=ba-token"})
    assert cookie_only.status_code == 401 and engine.signals == []
    assert panel.post("/api/preview/nobody/14/start", headers=ba).status_code == 404
    assert panel.post("/api/preview/acme/x/start", headers=ba).status_code == 400


def test_a_record_naming_another_project_is_never_acted_on(panel, engine):
    from openfactory.observability.metrics import MetricRecord
    from openfactory.observability.registry import deployment_metrics_sink

    forged = preview.Preview(project="other", unit="15", state=preview.OFFERED, pr_urls=(PR,))
    deployment_metrics_sink().record(MetricRecord(
        project="acme", ticket="15", ts="2026-09-24T10:00:00+00:00", kind=preview.KIND,
        role=preview.OFFERED, state=preview.OFFERED, extra=forged.model_dump(mode="json")))
    r = panel.post("/api/preview/acme/15/start")
    assert r.status_code == 403 and "names the project 'other'" in r.json()["message"]
    assert engine.started == []


def test_every_row_is_a_product_row_with_a_word_for_the_unit():
    from openfactory import actions

    for name in ("preview_start", "preview_stop", "preview_rebuild"):
        row = actions.CATALOG[name]
        assert row.scope == actions.PRODUCT and row.required == ("project", "unit")
        assert row.prose_for("unit")


# ── 4. the steps, with a faked runtime and forge ─────────────────────────────────────────────────


class Runtime:
    """A runtime that answers from fields and remembers what it was asked, in order."""

    def __init__(self, *, up: PreviewUp | None = None, on_daemon: str | None = None,
                 running: list[RunningPreview] | None = None, log_dir_files: dict | None = None):
        self.calls: list[str] = []
        self.result = up or PreviewUp(ok=True, services={"web": 3000, "api": 8000},
                                      health={"web": "started", "api": "healthy"},
                                      images={"db": "postgres@sha256:9 pulled"}, log_dir="/l")
        self.on_daemon = on_daemon
        self._running = running or []
        self.files = log_dir_files or {}

    def prerequisites(self):
        return []

    def up(self, plan):
        self.calls.append("up")
        return self.result

    def watch(self, cp):
        self.calls.append("watch")
        if self.on_daemon is None:
            return None
        return RunningPreview(compose_project=cp, unit="12", project="acme", state=self.on_daemon)

    def logs(self, cp, log_dir):
        self.calls.append("logs")
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        for name, text in self.files.items():
            (Path(log_dir) / name).write_text(text)
        return [str(Path(log_dir) / n) for n in self.files]

    def down(self, cp, workdir):
        self.calls.append("down")
        return [cp]

    def running(self):
        return self._running

    def prove(self, plan):
        return self.result


class Store:
    """The record store the steps write to, as a list."""

    def __init__(self, *seed: preview.Preview):
        self.rows = list(seed)

    def record(self, p):
        self.rows.append(p)

    def latest(self, project, token):
        mine = [r for r in self.rows if r.project == project and r.unit == token]
        return mine[-1] if mine else None

    @property
    def states(self):
        return [r.state for r in self.rows]


def _world(store: Store, forge=None, **kw) -> steps.World:
    return steps.World(record=store.record, latest=store.latest,
                       forge_of=lambda p: forge or Forge(), clock=lambda: 1_900_000_000.0, **kw)


@pytest.fixture
def unit_dirs(monkeypatch, tmp_path):
    from openfactory.adapters.preview import compose

    monkeypatch.setenv("OPENFACTORY_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    made: dict = {}

    def sources_of(project):
        return [compose.TreeSource(repo="acme/shop", dir="shop", source="/src/shop")]

    def materialise(unit, project, *, trees, fetch):
        made.update(unit=unit, trees=trees, fetch=fetch)
        tree = Tree(repo="acme/shop", dir="shop", base_commit="b" * 40, merge_base="c" * 40,
                    branch=trees[0].branch, change_commit=HEAD, pr_url=trees[0].pr_url,
                    diff_paths=("api/app.py",))
        return Layout(workdir=compose.workdir_for("acme", unit.token), trees={"shop": tree})

    monkeypatch.setattr(compose, "sources_of", sources_of)
    monkeypatch.setattr(compose, "materialise", materialise)
    return made


ACME = SimpleNamespace(name="acme", repo_path="/src/shop")


def test_a_start_takes_the_old_stack_down_logs_first_then_checks_out_the_open_pull_request(
        unit_dirs):
    store = Store(preview.Preview(project="acme", unit="12", cards=("12",),
                                  state=preview.FAILED, pr_urls=(PR,),
                                  branches={PR: "openfactory/12"}, notes=("old",)))
    runtime = Runtime(on_daemon="exited")
    layout = steps.materialise(ACME, "12", runtime=runtime, world=_world(store, Forge(remote="R")),
                               started_by="Ana")
    assert isinstance(layout, Layout)
    assert runtime.calls == ["watch", "logs", "down"], "logs BEFORE any down"
    assert (unit_dirs["trees"][0].branch, unit_dirs["trees"][0].pr_url) == ("openfactory/12", PR)
    assert unit_dirs["fetch"] == {"acme/shop": "R"}, "the forge's remote, as an argument"
    starting = store.rows[1]
    assert starting.state == preview.STARTING and starting.started_by == "Ana"
    assert starting.notes == (), "a fresh start says nothing the last one said"


def test_a_unit_with_no_open_pull_request_is_refused_before_anything_is_checked_out(unit_dirs):
    store = Store()
    layout = steps.materialise(ACME, "12", runtime=Runtime(), world=_world(store, Forge(pr="")))
    assert isinstance(layout, Refused) and "no pull request" in layout.reasons[0]
    assert store.states == [preview.STARTING, preview.FAILED] and "trees" not in unit_dirs

    closed = Store(preview.Preview(project="acme", unit="12", state=preview.OFFERED,
                                   pr_urls=(PR,), branches={PR: "openfactory/12"}))
    layout = steps.materialise(ACME, "12", runtime=Runtime(),
                               world=_world(closed, Forge(status="merged")))
    assert isinstance(layout, Refused) and "no open pull request" in layout.reasons[0]


def test_the_cap_refuses_by_name_and_counts_nothing_of_the_units_own(unit_dirs, monkeypatch):
    from openfactory.adapters.preview import compose

    monkeypatch.setattr(compose, "plan", lambda *a, **k: pytest.fail("planned past the cap"))
    up = [RunningPreview(compose_project="openfactory-pv-acme-13", unit="13", project="acme",
                         state="running"),
          RunningPreview(compose_project="openfactory-pv-beta-req0012", unit="req0012",
                         project="beta", state="running")]
    store, runtime = Store(), Runtime(running=up)
    layout = Layout(workdir=compose.workdir_for("acme", "12"), trees={})
    refused = steps.plan(ACME, "12", layout, runtime=runtime, world=_world(store, cap=2))
    assert isinstance(refused, Refused)
    why = store.rows[-1].why
    assert store.rows[-1].state == preview.FAILED
    assert "acme 13" in why and "beta req0012" in why and "OPENFACTORY_PREVIEW_MAX" in why
    assert runtime.calls == ["down"], "the fresh checkout goes with the refusal"

    own = [*up[:1], RunningPreview(compose_project="openfactory-pv-acme-12", unit="12",
                                   project="acme", state="exited")]
    monkeypatch.setattr(compose, "plan", lambda *a, **k: Refused(reasons=("planned",)))
    again = steps.plan(ACME, "12", layout, runtime=Runtime(running=own),
                       world=_world(Store(), cap=2))
    assert again.reasons == ("planned",), "the unit's own leftover is not another preview"


def _plan(layout: Layout | None = None, **kw) -> PreviewPlan:
    layout = layout or Layout(workdir="/w/openfactory-pv-acme-12", trees={"shop": Tree(
        repo="acme/shop", dir="shop", base_commit="b" * 40, merge_base="c" * 40,
        branch="openfactory/12", change_commit=HEAD, pr_url=PR)})
    base = dict(unit=Unit(project="acme", kind="card", id="12", token="12"), project="acme",
                compose_project="openfactory-pv-acme-12", workdir=layout.workdir, layout=layout,
                doc={"services": {"web": {}, "api": {}}}, paths={}, expose={"web": 3000,
                                                                          "api": 8000},
                from_change={"api": True, "web": False}, commits={"acme/shop": HEAD},
                env_names={}, build_arg_names={}, urls={}, internal_urls={},
                edge_network="openfactory-pv-acme-12-edge", expires_at=1_900_086_400,
                pr_urls=(PR,), notes=("`ports:` is not used in a preview.",))
    base.update(kw)
    return PreviewPlan(**base)


def test_up_records_live_with_the_heads_it_was_built_from():
    store = Store(preview.Preview(project="acme", unit="12", cards=("12",),
                                  state=preview.STARTING, started_by="Ana"))
    result = steps.up(ACME, "12", _plan(), runtime=Runtime(), world=_world(store))
    live = store.rows[-1]
    assert result.ok and live.state == preview.LIVE and live.started_by == "Ana"
    assert live.heads == {PR: HEAD} and live.commits == {"acme/shop": HEAD}
    assert live.base_moved == {"acme/shop": "branched from ccccccc, now bbbbbbb"}
    assert live.expires_at == 1_900_086_400 and live.health["api"] == "healthy"
    assert live.from_change == {"api": True, "web": False}


def test_a_failed_start_is_kept_to_read_unless_nothing_reached_the_daemon():
    broke = PreviewUp(ok=False, why="`api` exited with code 1", log_dir="/l")
    kept, gone = Runtime(up=broke, on_daemon="exited"), Runtime(up=broke)
    store = Store()
    steps.up(ACME, "12", _plan(), runtime=kept, world=_world(store))
    assert store.rows[-1].state == preview.FAILED and "exited with code 1" in store.rows[-1].why
    assert "down" not in kept.calls, "the reaper takes it down after keep_failed_minutes"
    steps.up(ACME, "12", _plan(), runtime=gone, world=_world(Store()))
    assert gone.calls[-1] == "down", "a build that left nothing leaves no work directory either"


def test_a_crashed_exposed_service_is_failed_with_its_last_lines(unit_dirs):
    store = Store(_live(services={"web": 3000, "api": 8000}))
    runtime = Runtime(on_daemon="failed",
                      log_dir_files={"api.log": "booting\nTraceback: boom\n", "web.log": "ok\n"})
    assert steps.watch(ACME, "12", runtime=runtime, world=_world(store)) == steps.FAILED
    failed = store.rows[-1]
    assert failed.state == preview.FAILED and "Traceback: boom" in failed.why
    assert runtime.calls == ["watch", "logs"], "kept for a person to read — no down here"

    quiet = Store(_live())
    assert steps.watch(ACME, "12", runtime=Runtime(on_daemon="running"),
                       world=_world(quiet)) == steps.RUNNING
    assert len(quiet.rows) == 1
    gone = Store(_live())
    assert steps.watch(ACME, "12", runtime=Runtime(), world=_world(gone)) == steps.GONE
    assert gone.rows[-1].state == preview.ENDED


def test_down_records_ended_with_why_unless_the_unit_is_about_to_start_again(unit_dirs):
    store = Store(_live())
    steps.down(ACME, "12", runtime=Runtime(), world=_world(store), why="stopped by Ana")
    assert store.rows[-1].state == preview.ENDED and store.rows[-1].why == "stopped by Ana"
    rebuilt = Store(_live())
    steps.down(ACME, "12", runtime=Runtime(), world=_world(rebuilt), why="rebuilt", record=False)
    assert rebuilt.states == [preview.LIVE]


# ── 5. the workflow, on Temporal's own test engine ───────────────────────────────────────────────

temporalio = pytest.importorskip("temporalio")

from temporalio import activity  # noqa: E402
from temporalio.contrib.pydantic import pydantic_data_converter  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from openfactory.runtime.temporal import TASK_QUEUE  # noqa: E402
from openfactory.runtime.temporal.io import (  # noqa: E402
    PreviewParams,
    PreviewPlanInput,
    PreviewStepInput,
    PreviewStepResult,
    PreviewUpInput,
)
from openfactory.runtime.temporal.workflow import PreviewWorkflow  # noqa: E402

CALLS: list[tuple[str, str]] = []
BEHAVE: dict[str, object] = {}


@activity.defn(name="preview_materialise")
async def m_materialise(inp: PreviewStepInput) -> PreviewStepResult:
    CALLS.append(("materialise", inp.started_by))
    return PreviewStepResult(ok=True, layout=_plan().layout)


@activity.defn(name="preview_plan")
async def m_plan(inp: PreviewPlanInput) -> PreviewStepResult:
    CALLS.append(("plan", ""))
    if BEHAVE.get("plan") == "refuse":
        return PreviewStepResult(ok=False, why="refused")
    expires = int(activity.info().current_attempt_scheduled_time.timestamp()) + int(
        BEHAVE.get("ttl", 3600))
    return PreviewStepResult(ok=True, plan=_plan(expires_at=expires), expires_at=expires)


@activity.defn(name="preview_up")
async def m_up(inp: PreviewUpInput) -> PreviewStepResult:
    CALLS.append(("up", ""))
    if BEHAVE.get("up") == "raise":
        raise RuntimeError("the worker went away")
    return PreviewStepResult(ok=True, expires_at=inp.plan.expires_at)


@activity.defn(name="preview_watch")
async def m_watch(inp: PreviewStepInput) -> str:
    CALLS.append(("watch", ""))
    return str(BEHAVE.get("watch", "running"))


@activity.defn(name="preview_logs")
async def m_logs(inp: PreviewStepInput) -> list[str]:
    CALLS.append(("logs", inp.why))
    return []


@activity.defn(name="preview_down")
async def m_down(inp: PreviewStepInput) -> list[str]:
    CALLS.append(("down" if inp.record else "down-quietly", inp.why))
    return []


MOCKS = [m_materialise, m_plan, m_up, m_watch, m_logs, m_down]


@pytest.fixture
async def env():
    CALLS.clear()
    BEHAVE.clear()
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


async def _start(env, **kw):
    params = PreviewParams(project="acme", unit="12", started_by="Ana", runtime="compose", **kw)
    return await env.client.start_workflow(PreviewWorkflow.run, params,
                                           id=f"preview-{uuid.uuid4()}", task_queue=TASK_QUEUE)


async def _until(handle, state: str):
    for _ in range(1500):
        if await handle.query(PreviewWorkflow.state) == state:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"the preview never became {state}: {CALLS}")


async def _result(handle):
    """The workflow's answer, BOUNDED in wall-clock time. The test engine skips timers, so a
    workflow that never ends (a watch that starts the preview again on every run) would spin
    forever rather than fail — this makes that a failure with the calls it made."""
    try:
        return await asyncio.wait_for(handle.result(), timeout=60)
    except TimeoutError:
        raise AssertionError(f"the preview's workflow never ended: {len(CALLS)} calls, the "
                             f"first {CALLS[:8]}") from None


def _names() -> list[str]:
    return [c for c, _ in CALLS if c != "watch"]


@pytest.mark.owns_its_engine
async def test_a_stop_takes_it_down_logs_first_and_says_who(env):
    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[PreviewWorkflow],
                      activities=MOCKS):
        h = await _start(env)
        await _until(h, "live")
        await h.signal(PreviewWorkflow.stop, "Bia")
        assert await _result(h) == "ended"
    assert _names() == ["materialise", "plan", "up", "logs", "down"]
    assert CALLS[-1] == ("down", "stopped by Bia")


@pytest.mark.owns_its_engine
async def test_a_rebuild_takes_it_down_quietly_and_brings_it_up_from_a_fresh_checkout(env):
    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[PreviewWorkflow],
                      activities=MOCKS):
        h = await _start(env)
        await _until(h, "live")
        await h.signal(PreviewWorkflow.rebuild, "Carl")
        for _ in range(1500):
            if [c for c, _ in CALLS].count("up") == 2:
                break
            await asyncio.sleep(0.02)
        await _until(h, "live")
        await h.signal(PreviewWorkflow.stop, "Bia")
        assert await _result(h) == "ended"
    assert _names() == ["materialise", "plan", "up", "logs", "down-quietly", "materialise",
                        "plan", "up", "logs", "down"]
    assert ("materialise", "Carl") in CALLS, "the rebuild is started by whoever asked for it"


@pytest.mark.owns_its_engine
async def test_its_time_up_ends_it(env):
    BEHAVE["ttl"] = 150
    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[PreviewWorkflow],
                      activities=MOCKS):
        h = await _start(env)
        assert await _result(h) == "ended"
    assert CALLS[-1] == ("down", "its time was up")
    assert 1 <= [c for c, _ in CALLS].count("watch") <= 3, "a look a minute while it lived"


@pytest.mark.owns_its_engine
async def test_a_refused_plan_ends_it_with_nothing_brought_up(env):
    BEHAVE["plan"] = "refuse"
    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[PreviewWorkflow],
                      activities=MOCKS):
        assert await _result(await _start(env)) == "failed"
    assert _names() == ["materialise", "plan"]


@pytest.mark.owns_its_engine
async def test_a_step_that_died_is_ended_logs_first_by_name(env):
    BEHAVE["up"] = "raise"
    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[PreviewWorkflow],
                      activities=MOCKS):
        assert await _result(await _start(env)) == "ended"
    assert _names() == ["materialise", "plan", "up", "logs", "down"]
    assert "the worker may have restarted during the build" in CALLS[-1][1]


@pytest.mark.owns_its_engine
async def test_a_crashed_service_ends_the_watch_and_leaves_the_stack_to_read(env):
    BEHAVE["watch"] = "failed"
    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[PreviewWorkflow],
                      activities=MOCKS):
        assert await _result(await _start(env)) == "failed"
    assert "down" not in _names()


@pytest.mark.owns_its_engine
async def test_a_long_watch_continues_as_new_without_starting_anything_again(env):
    BEHAVE["ttl"] = 380
    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[PreviewWorkflow],
                      activities=MOCKS):
        h = await _start(env, watch_seconds=1)
        assert await _result(h) == "ended"
        latest = await env.client.get_workflow_handle(h.id).describe()
        assert latest.run_id != h.first_execution_run_id, "one run held the whole watch"
    assert _names() == ["materialise", "plan", "up", "logs", "down"]
    assert [c for c, _ in CALLS].count("watch") > 360, "the watch went on past one run's rounds"


@pytest.mark.owns_its_engine
async def test_a_second_start_of_one_unit_is_refused_by_the_engine(env):
    from openfactory.runtime.temporal import view

    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[PreviewWorkflow],
                      activities=MOCKS):
        params = PreviewParams(project="acme", unit="12", runtime="compose")
        wf_id = await view.start_preview(env.client, params)
        with pytest.raises(view.PreviewAlreadyStarted):
            await view.start_preview(env.client, params)
        await _until(env.client.get_workflow_handle(wf_id), "live")
        assert await view.signal_preview(env.client, "acme", "12", "stop", "Ana")
        await _result(env.client.get_workflow_handle(wf_id))
        assert not await view.signal_preview(env.client, "acme", "12", "stop", "Ana"), \
            "a stop sent to a finished workflow is refused, never reported done"


def test_the_worker_runs_the_workflow_and_every_step_it_calls():
    from openfactory.runtime.temporal import activities, worker

    for step in ("preview_materialise", "preview_plan", "preview_up", "preview_watch",
                 "preview_logs", "preview_down"):
        assert getattr(activities, step) in worker.WORKER_ACTIVITIES, step
    src = Path(worker.__file__).read_text()
    assert "PreviewWorkflow" in src.split("workflows=[")[1].split("]")[0]


def test_an_activity_heartbeats_the_step_it_is_on(monkeypatch):
    from temporalio.testing import ActivityEnvironment

    from openfactory.runtime.temporal import activities

    monkeypatch.setattr(activities, "PREVIEW_HEARTBEAT_SECONDS", 0.01)
    beats: list = []
    env = ActivityEnvironment()
    env.on_heartbeat = lambda *details: beats.append(details)

    async def slow():
        return await activities._heartbeating("up", lambda: time.sleep(0.1) or "done")

    assert asyncio.run(env.run(slow)) == "done"
    assert beats and beats[0] == ("up",)


# ── 6. the offer, through the walking skeleton ───────────────────────────────────────────────────

from tests.test_walking_skeleton import (  # noqa: E402
    FakeReviewer,
    FakeTracker,
    _runner,
    repo,  # noqa: F401 — the fixture
)


def _no_runtime(monkeypatch):
    """Any door to a runtime or a daemon, made to fail the test by name."""
    from openfactory.adapters.preview import compose, registry

    def refuse(*_a, **_k):
        raise AssertionError("the job called a preview runtime")

    monkeypatch.setattr(registry, "build_runtime", refuse)
    monkeypatch.setattr(compose, "_host", refuse)
    monkeypatch.setattr(compose, "materialise", refuse)


def _job(repo_path: Path, tmp_path: Path, *, body: str = "", ticket_id: str = "#8"):
    from openfactory.contracts import AcceptanceCriterion, Manifest, Ticket
    from openfactory.contracts.manifest import PreviewConfig
    from openfactory.contracts.project import Project

    ticket = Ticket(id=ticket_id, title="add feature", objective="add a feature", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")], raw=body)
    manifest = Manifest(validate={"test": "true", "security": "true"}, reviewers=["alice"],
                        preview=PreviewConfig(compose=["compose.yaml"], expose={"web": 3000}))
    runner = _runner(repo_path, FakeTracker(ticket), manifest, tmp_path, reviewer=FakeReviewer())
    runner.project = Project(name="acme", repo_path=str(repo_path))
    return runner


def test_the_human_gate_offers_a_preview_and_calls_no_runtime(repo, tmp_path, sink,  # noqa: F811
                                                              monkeypatch):
    from openfactory.contracts import JobState

    monkeypatch.setenv("OPENFACTORY_PREVIEW_RUNTIME", "compose")
    _no_runtime(monkeypatch)
    runner = _job(repo, tmp_path)

    result = runner.run("#8")

    assert result.state is JobState.PR_OPEN
    offered = preview.latest("acme", "8")
    assert offered.state == preview.OFFERED and offered.cards == ("8",)
    assert offered.pr_urls == ("https://forge/pr/1",)
    assert offered.branches == {"https://forge/pr/1": "openfactory/8"}
    assert offered.why == "", "whether one CAN start is judged when the card is read"


def test_the_offer_says_why_on_a_deployment_that_runs_none(repo, tmp_path, sink,  # noqa: F811
                                                           monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PREVIEW_RUNTIME", "none")
    _no_runtime(monkeypatch)
    _job(repo, tmp_path).run("#8")
    assert "OPENFACTORY_PREVIEW_RUNTIME" in preview.latest("acme", "8").why


def test_the_offer_never_overwrites_a_live_preview(repo, tmp_path, sink,  # noqa: F811
                                                   monkeypatch):
    from openfactory.preview import demand

    monkeypatch.setenv("OPENFACTORY_PREVIEW_RUNTIME", "compose")
    _no_runtime(monkeypatch)
    # a requirement's unit needs a product that can be read (#265 slice 5, §6.1): on here
    monkeypatch.setattr(demand, "product_context",
                        lambda project: SimpleNamespace(available=True, reason=""))
    preview.record(_live(unit="req0012", kind="requirement", cards=("7",),
                         pr_urls=("https://forge/pr/0",)))
    body = "## Source\n\nExecutes **REQ-0012** in the product's register.\n"

    _job(repo, tmp_path, body=body).run("#8")

    now = preview.latest("acme", "req0012")
    assert now.state == preview.LIVE, "a sibling's gate never relabels a live unit"
    assert now.cards == ("7", "8") and "https://forge/pr/1" in now.pr_urls
    assert any("#8 opened its pull request after this preview started" in s for s in now.stale)
    assert preview.unit_of_card("acme", "8") == "req0012"


def test_a_project_that_declares_no_preview_is_told_what_would_give_it_one(
        repo, tmp_path, sink, monkeypatch):  # noqa: F811
    """§4.3, since slice 4: a base with no `preview:` is still offered the one sentence that says
    what would give this change a preview. The job writes what its own checkout says a draft could
    be read from (`shape`) and runs nothing; which proposal is open is asked when the card is
    read. It never says a preview can start."""
    _no_runtime(monkeypatch)
    runner = _job(repo, tmp_path)
    runner.manifest = runner.manifest.model_copy(update={"preview": None})
    runner.run("#8")
    offered = preview.latest("acme", "8")
    assert offered is not None and offered.state == preview.OFFERED
    assert offered.shape.get("case") in ("compose", "dockerfiles", "draft", "nothing"), offered
    assert offered.why == "", "the sentence is computed when the card is read"


def test_with_no_checkout_to_read_a_project_that_declares_no_preview_is_offered_nothing(sink):
    """Declare nothing, and with nothing to read, nothing is written (D3)."""
    from types import SimpleNamespace

    from openfactory.contracts.project import Project

    made = demand.offer(project=Project(name="acme", repo_path="/nowhere"),
                        manifest=SimpleNamespace(preview=None),
                        ticket=SimpleNamespace(id="#8", repo="o/app", raw=""),
                        pr_url="https://forge/pr/1", branch="openfactory/8", shape_root=None)
    assert made is None and preview.latest("acme", "8") is None


# ── 7. the CLI's twins ───────────────────────────────────────────────────────────────────────────


def test_the_cli_starts_stops_and_restarts_through_the_rows(monkeypatch, tmp_path):
    from openfactory import actions, cli

    asked = []

    async def perform(name, *, by, **params):
        asked.append((name, params, by.via))
        return actions.base.done("ok", state="starting")

    monkeypatch.setattr(actions, "perform", perform)
    runner = CliRunner()
    for verb, row in (("start", "preview_start"), ("stop", "preview_stop"),
                      ("restart", "preview_rebuild")):
        out = runner.invoke(cli.app, ["preview", verb, "acme", "12"])
        assert out.exit_code == 0, out.output
        assert asked[-1] == (row, {"project": "acme", "unit": "12"}, "cli")


def test_the_cli_reads_the_record_and_its_logs(panel, tmp_path):
    from openfactory import cli

    logs = tmp_path / "logs" / "acme--12"
    logs.mkdir(parents=True)
    (logs / "api.log").write_text("line 1\nTraceback: boom\n")
    preview.record(_live(log_dir=str(logs), notes=("`ports:` is not used in a preview.",)))
    runner = CliRunner()
    read = runner.invoke(cli.app, ["preview", "read", "acme", "12"])
    assert read.exit_code == 0, read.output
    assert "acme 12: live" in read.output and "api: this change, healthy" in read.output
    assert "note: `ports:` is not used in a preview." in read.output
    shown = runner.invoke(cli.app, ["preview", "logs", "acme", "12", "api"])
    assert shown.exit_code == 0 and "Traceback: boom" in shown.output
    missing = runner.invoke(cli.app, ["preview", "logs", "acme", "12", "web"])
    assert missing.exit_code == 1
