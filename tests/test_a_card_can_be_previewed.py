"""A card can be looked at, running, before its pull request merges (ADR-0050 and its amendment).

What these pin, in the order a preview lives:

1. THE HOST. A preview is served on `<project>--<card>.<domain>`, never on the panel's host: the
   panel's credential is readable by any script there, and a preview runs agent-written code. The
   panel's host is never read as a preview, and no host under the preview domain ever reaches the
   panel.
2. THE KEY. What the panel hands out opens one preview host, for a few hours — never the panel.
3. THE BOX. The validated box is frozen with the factory's credentials overwritten and the
   harnesses' state removed, and the preview is a NEW container from it that receives only
   `box.preview_env`; it wears a name a repair of its own card cannot take down.
4. THE END. Time up, pull request merged or closed, or `serve:` stopped — and a checkout is only
   deleted when it is one the worker made.
5. THE JOB. A preview is offered where a person was handed the pull request, and a preview that
   cannot start never fails the job.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from openfactory import preview
from openfactory.adapters.sandbox import container as box_mod
from openfactory.adapters.sandbox.container import ContainerSandbox, reap_previews, stop_preview
from openfactory.adapters.sandbox.worktree import WorktreeSandbox
from openfactory.contracts import AcceptanceCriterion, JobState, Ticket
from openfactory.contracts.manifest import Manifest
from openfactory.contracts.project import BoxConfig
from tests.test_walking_skeleton import (
    FakeReviewer,
    FakeTracker,
    repo,  # noqa: F401 — the fixture
)
from tests.test_walking_skeleton import _runner as skeleton_runner

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "preview.localhost"


# ── 1. the host ──────────────────────────────────────────────────────────────────────────────────


def test_the_panels_own_host_is_never_read_as_a_preview():
    assert preview.label_of_host("localhost:8787", DOMAIN) == ""
    assert preview.label_of_host("panel.example.com", "preview.example.com") == ""
    # a name under the domain that is not `<slug>--<card>` names no preview
    assert preview.label_of_host("evil.preview.localhost", DOMAIN) == ""
    assert preview.label_of_host("a.acme--12.preview.localhost", DOMAIN) == ""
    assert preview.label_of_host("acme--12.preview.localhost:8787", DOMAIN) == "acme--12"
    # no domain configured → nothing is a preview
    assert preview.label_of_host("acme--12.preview.localhost", "") == ""


def test_a_label_is_a_dns_label_whatever_the_project_is_called():
    label = preview.host_label("Acme Corp / Web Shop " * 5, "123456")
    assert len(label) <= 63 and label.endswith("--123456")
    assert preview.label_of_host(f"{label}.{DOMAIN}", DOMAIN) == label


# ── 2. the key ───────────────────────────────────────────────────────────────────────────────────


def test_a_key_opens_its_own_preview_and_nothing_else(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PREVIEW_SECRET", "s3cret")
    token = preview.mint("acme--12", expires=int(time.time()) + 60)
    assert preview.admits(token, label="acme--12")
    assert not preview.admits(token, label="acme--13")
    assert not preview.admits(token[:-1] + ("0" if token[-1] != "0" else "1"), label="acme--12")
    assert not preview.admits(preview.mint("acme--12", expires=int(time.time()) - 1),
                              label="acme--12")
    monkeypatch.setenv("OPENFACTORY_PREVIEW_SECRET", "another")
    assert not preview.admits(token, label="acme--12")


# ── 3. the box ───────────────────────────────────────────────────────────────────────────────────


class _Daemon:
    """Records argv; answers `inspect` for the containers it knows, and nothing else."""

    def __init__(self, fail_run_of: str = ""):
        self.calls: list[list[str]] = []
        self.labels: dict[str, str] = {}
        self.fail_run_of = fail_run_of
        self.ps = ""

    def __call__(self, args, timeout=None):
        self.calls.append(list(args))
        if args[:2] == ["docker", "inspect"]:
            name = args[-1]
            return (0, self.labels[name]) if name in self.labels else (1, "No such object")
        if args[:2] == ["docker", "run"]:
            name = args[args.index("--name") + 1]
            if self.fail_run_of and name.startswith(self.fail_run_of):
                return 125, "no such network"
            clone = next((a.split("=", 1)[1] for a in args if a.startswith(preview.LABEL_CLONE)),
                         "")
            self.labels[name] = clone
        if args[:3] == ["docker", "rm", "-f"]:
            self.labels.pop(args[-1], None)
        if args[:2] == ["docker", "ps"]:
            return 0, self.ps
        return 0, ""

    def of(self, *head: str) -> list[list[str]]:
        return [c for c in self.calls if c[: len(head)] == list(head)]


@pytest.fixture
def daemon(monkeypatch, tmp_path):
    d = _Daemon()
    monkeypatch.setattr(box_mod, "_host", d)
    monkeypatch.setenv("OPENFACTORY_WORK_DIR", str(tmp_path / "work"))
    recorded: list = []
    monkeypatch.setattr(preview, "record_live", lambda p: recorded.append(("live", p)) or True)
    monkeypatch.setattr(preview, "record_ended",
                        lambda project, card, why: recorded.append(("ended", project, card, why)))
    d.recorded = recorded
    return d


def _validated_box(daemon, **kw) -> tuple[ContainerSandbox, object]:
    box = ContainerSandbox(image="client-image", project="acme",
                           extra_env=("AWS_SECRET_ACCESS_KEY", "NPM_TOKEN"), **kw)
    ws = box.prepare(repo_path=ROOT, base_branch="main", branch="openfactory/12")
    daemon.calls.clear()
    return box, ws


def _keep(box, **kw):
    args = dict(project="acme", card="12", command="npm start", port=3000,
                env_names=("PREVIEW_API_KEY",), network="openfactory-preview", hours=24,
                pr_url="https://forge/pr/7")
    args.update(kw)
    return box.keep_for_preview(**args)


def test_the_box_is_frozen_without_the_factorys_credentials_or_the_harness_state(
        daemon, monkeypatch):
    monkeypatch.setenv("PREVIEW_API_KEY", "sandbox-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "the-harness-token")
    box, _ = _validated_box(daemon)

    made, why = _keep(box)

    assert made is not None and why == ""
    execs = [c for c in daemon.calls if c[:2] == ["docker", "exec"]]
    commit = daemon.of("docker", "commit")[0]
    # the harness state is cleared BEFORE the freeze, so it is not in the frozen image
    assert daemon.calls.index(execs[-1]) < daemon.calls.index(commit)
    assert all(f'"$HOME/{rel}"' in execs[-1][-1] for rel in box_mod.HARNESS_STATE)
    # every credential the job box was started with is overwritten in the image's configuration
    for var in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY",
                "NPM_TOKEN"):
        assert f"ENV {var}=" in commit


def test_the_preview_is_a_new_container_that_receives_only_the_preview_tier(daemon, monkeypatch):
    monkeypatch.setenv("PREVIEW_API_KEY", "sandbox-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "the-harness-token")
    monkeypatch.setenv("NPM_TOKEN", "a-build-secret")
    box, _ = _validated_box(daemon)

    _keep(box)

    run = daemon.of("docker", "run")[0]
    name = run[run.index("--name") + 1]
    assert name == "openfactory-preview-acme-12"
    assert name != box._container or box._container is None
    passed = [run[i + 1] for i, a in enumerate(run) if a == "-e"]
    assert "PREVIEW_API_KEY" in passed and "PORT=3000" in passed and "HOST=0.0.0.0" in passed
    assert "ANTHROPIC_API_KEY" not in passed and "NPM_TOKEN" not in passed
    assert run[run.index("--network") + 1] == "openfactory-preview"
    assert preview.LABEL in run
    assert run[-3:] == [preview.image_name("acme", "12"), "-c", "npm start"]


def test_the_checkout_now_belongs_to_the_preview(daemon):
    box, ws = _validated_box(daemon)
    clone = box._host_clone
    job_box = box._container

    _keep(box)
    box.cleanup(workspace=ws)

    assert clone.exists(), "the job's cleanup deleted the tree the preview is serving"
    assert ["docker", "rm", "-f", job_box] in daemon.calls
    assert daemon.recorded and daemon.recorded[-1][0] == "live"


def test_a_preview_that_cannot_start_leaves_the_job_exactly_as_it_was(daemon, monkeypatch):
    daemon.fail_run_of = "openfactory-preview-"
    box, ws = _validated_box(daemon)
    clone = box._host_clone

    made, why = _keep(box)

    assert made is None and "could not start the preview" in why
    assert ["docker", "rm", "-f", "openfactory-preview-acme-12"] in daemon.calls
    assert ["docker", "image", "rm", "-f", preview.image_name("acme", "12")] in daemon.calls
    box.cleanup(workspace=ws)
    assert not clone.exists(), "a preview that never started must not keep the checkout"
    assert not daemon.recorded


def test_a_name_that_is_not_a_name_never_reaches_the_daemon(daemon):
    box, _ = _validated_box(daemon)
    made, why = _keep(box, env_names=("OK", "X=1 --privileged"))
    assert made is None and "NAMES" in why
    made, why = _keep(box, network="bridge --privileged")
    assert made is None
    assert not daemon.of("docker", "commit") and not daemon.of("docker", "run")


def test_a_later_run_of_the_same_card_replaces_its_preview(daemon):
    box, _ = _validated_box(daemon)
    _keep(box)
    first_clone = daemon.labels["openfactory-preview-acme-12"]
    box2, _ = _validated_box(daemon)

    _keep(box2)

    assert not Path(first_clone).exists(), "the replaced preview's checkout was left behind"
    assert len(daemon.of("docker", "run")) == 1


# ── 4. the end ───────────────────────────────────────────────────────────────────────────────────


def test_a_checkout_is_deleted_only_when_the_worker_made_it(daemon, tmp_path):
    elsewhere = tmp_path / "somebody-elses"
    elsewhere.mkdir()
    daemon.labels["openfactory-preview-acme-12"] = str(elsewhere)

    assert stop_preview("acme", "12", why="test")

    assert elsewhere.exists()
    assert daemon.recorded[-1] == ("ended", "acme", "12", "test")


def _ps(*rows: tuple[str, str, str, str, str, str]) -> str:
    return "\n".join("|".join(r) for r in rows)


def test_the_reaper_ends_what_should_end_and_keeps_what_should_not(daemon):
    later, earlier = str(int(time.time()) + 3600), str(int(time.time()) - 1)
    for card in ("1", "2", "3", "4", "5"):
        daemon.labels[preview.container_name("acme", card)] = ""
    daemon.ps = _ps(
        (preview.container_name("acme", "1"), "running", "acme", "1", earlier, "pr/1"),
        (preview.container_name("acme", "2"), "running", "acme", "2", later, "pr/2"),
        (preview.container_name("acme", "3"), "running", "acme", "3", later, "pr/3"),
        (preview.container_name("acme", "4"), "exited", "acme", "4", later, "pr/4"),
        (preview.container_name("acme", "5"), "running", "acme", "5", later, "pr/5"),
    )

    def status(project, pr_url):
        if pr_url == "pr/5":
            raise RuntimeError("forge unreachable")
        return {"pr/2": "merged", "pr/3": "open"}.get(pr_url, "open")

    ended = reap_previews(pr_status=status)

    assert sorted(e.split(":")[0] for e in ended) == ["acme #1", "acme #2", "acme #4"]
    assert any("time was up" in e for e in ended)
    assert any("merged" in e for e in ended)
    assert any("serve command stopped" in e for e in ended)
    # an unread pull request is not a closed one
    assert preview.container_name("acme", "5") in daemon.labels


# ── 5. the job ───────────────────────────────────────────────────────────────────────────────────


def _runner(manifest, sandbox, box=None):
    from openfactory.orchestrator.machine import JobRunner

    said: list[str] = []
    fake = SimpleNamespace(manifest=manifest, sandbox=sandbox,
                           project=SimpleNamespace(name="acme", box=box or BoxConfig()),
                           _emit=lambda _t, _k, text, **_kw: said.append(text))
    return fake, said, JobRunner._offer_preview


def test_no_serve_no_preview_and_nothing_said():
    sandbox = SimpleNamespace(keep_for_preview=lambda **kw: pytest.fail("kept"))
    fake, said, offer = _runner(Manifest(), sandbox)
    offer(fake, SimpleNamespace(id="#12"), "pr/7")
    assert said == []


def test_the_preview_is_kept_with_the_registrys_tier_and_hours(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PREVIEW_NETWORK", "openfactory-preview")
    got: dict = {}

    def keep(**kw):
        got.update(kw)
        return preview.Preview(project="acme", card="12", label="acme--12", container="c",
                               port=3000, expires_at=int(time.time()) + 6 * 3600), ""

    manifest = Manifest.model_validate({"serve": {"command": "npm start", "port": 3000}})
    fake, said, offer = _runner(manifest, SimpleNamespace(keep_for_preview=keep),
                                BoxConfig(preview_env=["PREVIEW_API_KEY"], preview_hours=6))
    offer(fake, SimpleNamespace(id="acme#12"), "pr/7")

    assert got["card"] == "12" and got["env_names"] == ("PREVIEW_API_KEY",)
    assert got["hours"] == 6 and got["network"] == "openfactory-preview"
    assert "preview of this change is up" in said[-1]


@pytest.mark.parametrize("sandbox,network,expect", [
    (SimpleNamespace(), "net", "only the container box"),
    (SimpleNamespace(keep_for_preview=lambda **kw: (None, "")), "", "OPENFACTORY_PREVIEW_NETWORK"),
])
def test_a_preview_that_cannot_be_offered_says_why(monkeypatch, sandbox, network, expect):
    monkeypatch.setenv("OPENFACTORY_PREVIEW_NETWORK", network)
    manifest = Manifest.model_validate({"serve": {"command": "npm start", "port": 3000}})
    fake, said, offer = _runner(manifest, sandbox)
    offer(fake, SimpleNamespace(id="#12"), "pr/7")
    assert expect in said[-1]


def test_a_preview_that_raises_never_fails_the_job(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PREVIEW_NETWORK", "net")

    def keep(**kw):
        raise RuntimeError("daemon went away")

    manifest = Manifest.model_validate({"serve": {"command": "npm start", "port": 3000}})
    fake, said, offer = _runner(manifest, SimpleNamespace(keep_for_preview=keep))
    offer(fake, SimpleNamespace(id="#12"), "pr/7")
    assert "daemon went away" in said[-1]


class _KeptBox(WorktreeSandbox):
    """A worktree box that records being asked to keep itself — the wiring, not the freezing."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.kept: list[dict] = []

    def keep_for_preview(self, **kw):
        self.kept.append(kw)
        return None, "recorded"


def _card(n: str) -> Ticket:
    return Ticket(id=f"#{n}", title="add feature", objective="add a feature", repo="o/app",
                  acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])


@pytest.mark.parametrize("policy,offered", [("human", True), ("auto", False)])
def test_the_preview_is_offered_where_a_person_was_handed_the_pull_request(
        repo, tmp_path, monkeypatch, policy, offered):  # noqa: F811 — the fixture
    monkeypatch.setenv("OPENFACTORY_PREVIEW_NETWORK", "openfactory-preview")
    manifest = Manifest.model_validate({
        "merge_policy": policy, "validate": {"test": "true", "security": "true"},
        "serve": {"command": "npm start", "port": 3000}})
    sandbox = _KeptBox(root=tmp_path / "wt")
    runner = skeleton_runner(repo, FakeTracker(_card("21")), manifest, tmp_path,
                             reviewer=FakeReviewer(), sandbox=sandbox)
    runner.project = SimpleNamespace(name="app", box=BoxConfig())

    result = runner.run("#21")

    assert result.pr_url
    assert bool(sandbox.kept) is offered
    if offered:
        assert result.state is JobState.PR_OPEN
        assert sandbox.kept[0]["card"] == "21" and sandbox.kept[0]["pr_url"] == result.pr_url


# ── 6. the panel ─────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def panel(monkeypatch):
    from openfactory.api import app as api

    monkeypatch.setenv("OPENFACTORY_PREVIEW_DOMAIN", DOMAIN)
    monkeypatch.setenv("OPENFACTORY_PREVIEW_SECRET", "s3cret")
    live = preview.Preview(project="acme", card="12", label="acme--12",
                           container="openfactory-preview-acme-12", port=3000,
                           expires_at=int(time.time()) + 3600)
    monkeypatch.setattr(preview, "latest",
                        lambda project, card: live if (project, card) == ("acme", "12") else None)
    monkeypatch.setattr(api, "ProjectRegistry",
                        lambda: SimpleNamespace(list=lambda: [SimpleNamespace(name="acme")]))
    return TestClient(api.app)


def test_a_host_under_the_preview_domain_never_reaches_the_panel(panel):
    for host in ("evil.preview.localhost", "acme--99.preview.localhost"):
        r = panel.get("/", headers={"host": host})
        assert r.status_code == 404 and "OpenFactory" not in r.text.split("<title>")[0]
        assert "panel.html" not in r.text
    assert panel.get("/api/whoami", headers={"host": "evil.preview.localhost"}).status_code == 404


def test_the_link_is_on_the_preview_host_and_carries_a_key_to_it_alone(panel):
    body = panel.get("/api/preview/acme/12").json()
    assert body["live"] is True
    url = httpx.URL(body["url"])
    assert url.host == "acme--12.preview.localhost"
    assert url.path == preview.ENTER_PATH
    assert preview.admits(url.params["t"], label="acme--12")
    assert not panel.get("/api/preview/acme/13").json()["live"]


def test_a_product_scoped_person_can_open_a_preview(panel, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PRODUCT_TOKENS", "ba-token:bia:Bia")
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "op-token:ana:Ana")
    r = panel.get("/api/preview/acme/12", headers={"authorization": "Bearer ba-token"})
    assert r.status_code == 200 and r.json()["live"] is True
    assert panel.get("/api/preview/acme/12").status_code == 401


def test_the_key_becomes_a_cookie_on_the_preview_host_only(panel):
    host = {"host": "acme--12.preview.localhost"}
    token = preview.mint("acme--12", expires=int(time.time()) + 600)

    r = panel.get(f"{preview.ENTER_PATH}?t={token}", headers=host, follow_redirects=False)

    assert r.status_code == 303
    cookie = r.headers["set-cookie"].lower()
    assert cookie.startswith(f"{preview.COOKIE}=") and "httponly" in cookie
    assert "domain=" not in cookie, "a cookie with a Domain would reach sibling hosts"
    wrong = preview.mint("acme--13", expires=int(time.time()) + 600)
    assert panel.get(f"{preview.ENTER_PATH}?t={wrong}", headers=host,
                     follow_redirects=False).status_code == 403
    panel.cookies.clear()  # the client kept the cookie from the 303, as a browser would
    assert panel.get("/", headers=host).status_code == 401


def test_the_application_never_sees_the_panels_credential_or_the_preview_key(panel, monkeypatch):
    from openfactory.api import app as api

    seen: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        # a STREAM, as a real upstream answers: a Response built from `text=` counts as read
        return httpx.Response(200, stream=httpx.ByteStream(b"hello from the app"),
                              headers={"x-app": "1"})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(upstream), **kw))
    token = preview.mint("acme--12", expires=int(time.time()) + 600)
    panel.cookies.set(preview.COOKIE, token, domain="acme--12.preview.localhost")

    r = panel.get("/orders?page=2", headers={
        "host": "acme--12.preview.localhost",
        "cookie": f"{preview.COOKIE}={token}; openfactory_token=panel-secret; app_session=abc",
        "authorization": "Bearer panel-secret"})

    assert r.status_code == 200 and r.text == "hello from the app" and r.headers["x-app"] == "1"
    sent = seen[-1]
    assert str(sent.url) == "http://openfactory-preview-acme-12:3000/orders?page=2"
    assert sent.headers.get("cookie") == "app_session=abc"
    assert "authorization" not in sent.headers
    assert api is not None


def test_a_workload_never_holds_the_key_previews_are_signed_with(monkeypatch):
    """A worktree workload holding the preview key could mint its own way into every preview —
    and `box.env` cannot hand it over either, because no harness authenticates with it."""
    from openfactory.adapters.sandbox.worktree import _scrubbed_env

    monkeypatch.setenv("OPENFACTORY_PREVIEW_SECRET", "s3cret")
    assert "OPENFACTORY_PREVIEW_SECRET" not in _scrubbed_env()
    assert "OPENFACTORY_PREVIEW_SECRET" not in _scrubbed_env(keep=("OPENFACTORY_PREVIEW_SECRET",))


# ── 7. the other direction: a preview may not write the panel's credential (review of #270) ─────


def test_a_preview_cannot_plant_a_cookie_the_panels_host_would_receive(panel, monkeypatch):
    def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=httpx.ByteStream(b"ok"), headers=[
            ("set-cookie", "openfactory_token=ATTACKER; Domain=localhost; Path=/"),
            ("set-cookie", "openfactory_token=ATTACKER; Path=/"),
            ("set-cookie", "tracking=1; Domain=preview.localhost; Path=/"),
            ("set-cookie", f"{preview.COOKIE}=forged; Path=/"),
            ("set-cookie", "app_session=abc; Path=/; HttpOnly"),
        ])

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(upstream), **kw))
    token = preview.mint("acme--12", expires=int(time.time()) + 600)

    r = panel.get("/", headers={"host": "acme--12.preview.localhost",
                                "cookie": f"{preview.COOKIE}={token}"})

    assert r.status_code == 200
    assert r.headers.get_list("set-cookie") == ["app_session=abc; Path=/; HttpOnly"]


def test_a_credential_cookie_that_arrives_twice_is_nobodys():
    from starlette.requests import Request

    from openfactory.api.app import _credential_of

    def asked(cookie: str) -> str:
        return _credential_of(Request({"type": "http", "method": "GET", "path": "/api/x",
                                       "query_string": b"", "headers": [
                                           (b"cookie", cookie.encode())]}))

    assert asked("openfactory_token=mine") == "mine"
    assert asked("openfactory_token=mine; openfactory_token=planted") == ""
    assert asked("openfactory_token=planted; x=1; openfactory_token=mine") == ""


def test_the_page_adopts_a_credential_cookie_only_when_there_is_one():
    """The page copies the cookie into localStorage on boot — so the rule has to hold there too,
    or a planted cookie becomes the browser's stored credential for good."""
    page = (ROOT / "openfactory" / "api" / "panel.html").read_text(encoding="utf-8")
    line = next(ln for ln in page.splitlines() if ln.startswith("function cookieToken()"))
    assert "matchAll" in line and "all.length===1" in line


def test_the_panel_refuses_to_be_framed(panel):
    r = panel.get("/", headers={"host": "localhost:8787"})
    assert r.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert r.headers["x-frame-options"] == "DENY"


def test_the_proxy_target_is_derived_never_read_from_the_record(monkeypatch):
    forged = preview.Preview(project="acme", card="12", label="acme--12",
                             container="metadata.internal", port=80,
                             expires_at=int(time.time()) + 3600)
    monkeypatch.setattr(preview, "latest", lambda project, card: forged)
    assert preview.serving("acme--12", [SimpleNamespace(name="acme")]) is None
