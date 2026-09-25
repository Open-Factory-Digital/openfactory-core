"""A preview on the one-machine door: published on this machine's loopback on a port its name
derives, reached by a panel that is a host process, and honest about what it gives up (#265 slice
6; ADR-0049's local kind; the design's §7.2, §5.4, §8 and S12).

What these hold, without a daemon (the live run is `tests/test_a_preview_opens_on_one_machine.py`):

1. THE PORT IS THE NAME'S. `preview.loopback_port` derives it from the host label; the assembler
   publishes exactly that port and the router targets exactly that port, from the same function.
   Two services of a unit deriving one port are refused by name, and so is a loopback deployment
   that names no ports.
2. A COLLISION FAILS THE START BY NAME, before anything is built: a derived port something already
   answers on names the service, the port, the name it derives from and who holds it — another
   preview, another container, or another program — and docker's own "already allocated" is read
   into the same sentence.
3. NOTHING LISTENS ON EVERY INTERFACE. The assembler publishes on 127.0.0.1 alone; the row refuses
   a plan that publishes anywhere else, on another port or twice; the panel `up` starts binds the
   loopback unless the operator says otherwise; the probe's own listener binds the loopback.
4. THE ROUTER'S LOOPBACK TARGET is `127.0.0.1:<derived port>`, asked only after the key — a
   request without the preview's cookie never reaches the port, whatever the reach.
5. WHAT A LOOPBACK PREVIEW REACHES IS MEASURED, and the card says it whichever way it fell.
6. THE DEFAULT IS NO DOCKER: with `OPENFACTORY_PREVIEW_RUNTIME=none` on one machine the card says the
   §7.2 sentence — even with the domain still commented out — and `init` writes the four lines
   that opt in commented, with what opting in means.
7. `doctor` SAYS IT every time: Safari, who can open a preview without the key, what a preview's
   containers reach on this machine, and whether they reach the internet — the last two measured.
"""

from __future__ import annotations

import inspect
import re
import socket
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from openfactory import doctor, preview
from openfactory.adapters.preview import compose
from openfactory.adapters.preview.base import refusals
from openfactory.adapters.preview.compose import Ran, Reached
from openfactory.preview.plan import PreviewPlan, PreviewUp, Refused
from tests.test_the_compose_row_runs_what_was_admitted import Daemon, _runtime
from tests.test_the_shape_is_read_and_admitted import (
    S1_CFG,
    _canonical,
    _diff,
    _layout,
    _ok,
    _plan,
    _workdir,
)

DOMAIN = "preview.localhost"
WEB = f"web--acme--12.{DOMAIN}"
#: The live run publishes on the design's range; these tests hold ports on another one, so the two
#: can run side by side on one machine.
SPAN = (47000, 47999)


def _loopback(tmp_path, span=SPAN, **kw) -> PreviewPlan | Refused:
    wd = _workdir(tmp_path, "s1")
    return _plan(_canonical("s1", wd), S1_CFG, _layout(wd, _diff("s1")), reach="loopback",
                 loopback_range=span, **kw)


# ── 1. the port is the name's ────────────────────────────────────────────────────────────────────


def test_a_loopback_port_is_derived_from_the_name_alone():
    # pinned: a person's bookmark and the router's target must survive a restart of either side
    assert preview.loopback_port("web--acme--12", (42000, 42999)) == 42603
    assert preview.loopback_port("api--acme--12", (42000, 42999)) == 42633
    assert preview.loopback_port("web--acme--13", (42000, 42999)) != 42603
    assert preview.loopback_port("web--acme--12", (42000, 42000)) == 42000
    assert all(42000 <= preview.loopback_port(f"s{i}--acme--12", (42000, 42999)) <= 42999
               for i in range(200))


def test_the_assembler_publishes_the_port_the_router_derives(tmp_path, monkeypatch):
    plan = _ok(_loopback(tmp_path))
    monkeypatch.setenv("OPENFACTORY_PREVIEW_REACH", "loopback")
    monkeypatch.setenv("OPENFACTORY_PREVIEW_PORTS", f"{SPAN[0]}-{SPAN[1]}")
    for svc, inside in S1_CFG.expose.items():
        derived = preview.loopback_port(preview.host_label("acme", "12", svc), SPAN)
        assert plan.loopback_ports[svc] == derived
        assert plan.doc["services"][svc]["ports"] == [
            {"target": inside, "published": str(derived), "host_ip": "127.0.0.1",
             "protocol": "tcp"}]
        host = preview.host_of(f"{svc}--acme--12.{DOMAIN}:8787", DOMAIN)
        assert preview.upstream(host, inside) == f"http://127.0.0.1:{derived}", \
            "the router must target the port the assembler published"
    assert "ports" not in plan.doc["services"]["db"], "a service nobody opens is never published"


def test_two_services_deriving_one_port_are_refused_by_name(tmp_path):
    result = _loopback(tmp_path, span=(47000, 47000))
    assert isinstance(result, Refused)
    assert any("derive the same loopback port 47000" in r and "OPENFACTORY_PREVIEW_PORTS" in r
               for r in result.reasons), result.reasons


def test_a_loopback_deployment_that_names_no_ports_is_refused_by_name(tmp_path):
    result = _loopback(tmp_path, span=None)
    assert isinstance(result, Refused)
    assert any("names no ports" in r and "OPENFACTORY_PREVIEW_PORTS" in r
               for r in result.reasons), result.reasons


def test_the_card_says_who_can_open_each_port_without_the_key(tmp_path):
    plan = _ok(_loopback(tmp_path))
    note = next(n for n in plan.notes if n.startswith("reached on this machine only"))
    for svc, port in plan.loopback_ports.items():
        assert f"`{svc}` at 127.0.0.1:{port}" in note
    assert "anyone on it, and the job box" in note and "without the key" in note
    assert "all interfaces of this machine are reachable from the preview" in note
    network = _ok(_plan(_canonical("s1", plan.workdir), S1_CFG, _layout(plan.workdir,
                                                                        _diff("s1"))))
    assert not any("127.0.0.1" in n for n in network.notes), "the compose stack publishes nothing"


# ── 2. a collision fails the start by name ──────────────────────────────────────────────────────


def _hold(port: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
    except OSError:
        s.close()
        pytest.skip(f"127.0.0.1:{port} is already in use on this machine")
    s.listen(1)
    return s


class Probe(Daemon):
    """The faked daemon, plus what the loopback reach asks it: who publishes a port, and the reach
    probe — answered by really fetching the probe's listener, as a container that reached this
    machine's loopback would."""

    def __init__(self, *, publish: str = "", internet: str = "no", loopback: bool = True,
                 **kw):
        super().__init__(**kw)
        self.publish, self.internet, self.loopback = publish, internet, loopback

    def __call__(self, argv, *, env=None, timeout=120, input=None):
        argv = list(argv)
        if argv[:2] == ["docker", "ps"] and any(a.startswith("publish=") for a in argv):
            self.calls.append((argv, dict(env) if env is not None else None))
            return Ran(0, self.publish, "")
        if argv[:2] == ["docker", "run"] and "sh" in argv:
            self.calls.append((argv, dict(env) if env is not None else None))
            script = argv[-1]
            port = re.search(r"host\.docker\.internal:(\d+)/", script).group(1)
            token = re.search(r"grep -q ([0-9a-f]+);", script).group(1)
            reached = "no"
            if self.loopback:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
                    reached = "yes" if token in r.read().decode() else "no"
            return Ran(0, f"internet={self.internet}\nloopback={reached}\n", "")
        return super().__call__(argv, env=env, timeout=timeout, input=input)


@pytest.fixture
def root(tmp_path, monkeypatch):
    real = Path(tmp_path).resolve()
    monkeypatch.setenv("OPENFACTORY_WORK_DIR", str(real))
    monkeypatch.setenv("OPENFACTORY_PREVIEW_DOCKER_CONFIG", str(real / "docker-config"))
    return real


def _built(daemon) -> bool:
    return any(Daemon.sub(a) == "up" or a[:3] == ["docker", "network", "create"]
               for a, _ in daemon.calls)


def test_a_port_another_program_holds_fails_the_start_by_name_before_anything_is_built(
        root, monkeypatch):
    plan = _ok(_loopback(root))
    port = plan.loopback_ports["web"]
    held = _hold(port)
    daemon = Probe()
    monkeypatch.setattr(compose, "_host", daemon)
    try:
        result = _runtime(reach="loopback", panel_container="").up(plan)
    finally:
        held.close()
    assert not result.ok
    assert (f"`web`'s port {port} on 127.0.0.1 — derived from its name `web--acme--12` — is in "
            f"use by another program on this machine") in result.why
    assert "OPENFACTORY_PREVIEW_PORTS" in result.why
    assert not _built(daemon), "a collision was found after the build had started"


def test_a_port_another_preview_holds_names_that_preview(root, monkeypatch):
    plan = _ok(_loopback(root))
    port = plan.loopback_ports["api"]
    held = _hold(port)
    daemon = Probe(publish="openfactory-pv-acme-13-web-1\tacme\t13\tweb\n")
    monkeypatch.setattr(compose, "_host", daemon)
    try:
        result = _runtime(reach="loopback", panel_container="").up(plan)
    finally:
        held.close()
    assert f"`api`'s port {port} on 127.0.0.1" in result.why
    assert "held by the preview of acme 13 (`web`): stop that one" in result.why
    asked = [a for a, _ in daemon.calls if a[:2] == ["docker", "ps"]]
    assert asked and f"publish={port}" in asked[0]


def test_dockers_own_already_allocated_is_the_same_sentence(root, monkeypatch):
    plan = _ok(_loopback(root))
    port = plan.loopback_ports["web"]
    daemon = Probe(up=Ran(1, "", f"Error response from daemon: Bind for 127.0.0.1:{port} failed: "
                                 f"port is already allocated"))
    monkeypatch.setattr(compose, "_host", daemon)
    monkeypatch.setattr(compose, "_listening", lambda p: False)

    result = _runtime(reach="loopback", panel_container="").up(plan)

    assert not result.ok
    assert f"`web`'s port {port} on 127.0.0.1 — derived from its name `web--acme--12`" in result.why


# ── 3. nothing listens on every interface ───────────────────────────────────────────────────────


@pytest.mark.parametrize("ports, said", [
    ([{"target": 3000, "published": "{p}", "host_ip": "0.0.0.0", "protocol": "tcp"}], "0.0.0.0"),
    ([{"target": 3000, "published": "{p}", "protocol": "tcp"}], "published as"),
    ([{"target": 3000, "published": "80", "host_ip": "127.0.0.1", "protocol": "tcp"}], "'80'"),
    ([{"target": 3000, "published": "{p}", "host_ip": "127.0.0.1", "protocol": "tcp"},
      {"target": 3000, "published": "{p}", "host_ip": "0.0.0.0", "protocol": "tcp"}], "0.0.0.0"),
    ([{"target": 22, "published": "{p}", "host_ip": "127.0.0.1", "protocol": "tcp"}], "22"),
])
def test_the_row_refuses_a_plan_published_anywhere_but_the_derived_loopback_port(
        tmp_path, ports, said):
    plan = _ok(_loopback(tmp_path))
    assert refusals(plan) == [], "the assembler's own plan must pass"
    p = str(plan.loopback_ports["web"])
    doc = {**plan.doc, "services": {**plan.doc["services"], "web": {
        **plan.doc["services"]["web"],
        "ports": [{**e, "published": e["published"].replace("{p}", p)} for e in ports]}}}
    why = refusals(plan.model_copy(update={"doc": doc}))
    assert any("`web` is published as" in w and said in w for w in why), why


def test_a_service_nobody_opens_is_never_published_and_the_compose_stack_publishes_nothing(
        tmp_path):
    plan = _ok(_loopback(tmp_path))
    db = {**plan.doc["services"]["db"], "ports": [
        {"target": 5432, "published": "5432", "host_ip": "127.0.0.1", "protocol": "tcp"}]}
    forged = plan.model_copy(update={"doc": {**plan.doc, "services": {**plan.doc["services"],
                                                                      "db": db}}})
    assert "`db` carries `ports:`, which admission never passes." in refusals(forged)
    network = plan.model_copy(update={"reach": "network"})
    assert "`web` carries `ports:`, which admission never passes." in refusals(network)


def test_the_panel_up_starts_binds_the_loopback_unless_the_operator_says_otherwise(tmp_path):
    from openfactory import cli
    from openfactory.runtime import host

    assert inspect.signature(cli.serve).parameters["host"].default.default == "127.0.0.1"
    panel = next(argv for name, argv in host.processes(panel_port=8787, state=tmp_path,
                                                       engine=None) if name == "panel")
    assert "--host" not in panel, "`up` widened where the panel listens"


def test_the_probes_listener_binds_the_loopback_alone(monkeypatch):
    bound: list[tuple] = []
    real = compose.http.server.ThreadingHTTPServer

    class Recorded(real):
        def __init__(self, address, handler):
            bound.append(address)
            super().__init__(address, handler)

    monkeypatch.setattr(compose.http.server, "ThreadingHTTPServer", Recorded)
    monkeypatch.setattr(compose, "_host", Probe(internet="yes"))

    assert compose.measure_reach("openfactory-pv-acme-12-edge", env={}) == Reached(True, True)
    assert bound == [("127.0.0.1", 0)]


# ── 4. the router's loopback target, and the key ────────────────────────────────────────────────


@pytest.fixture
def panel(monkeypatch, tmp_path):
    from openfactory.api import app as api

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    monkeypatch.setenv("OPENFACTORY_PREVIEW_DOMAIN", DOMAIN)
    monkeypatch.setenv("OPENFACTORY_PREVIEW_SECRET", "s3cret")
    monkeypatch.setenv("OPENFACTORY_PREVIEW_REACH", "loopback")
    monkeypatch.setenv("OPENFACTORY_PREVIEW_PORTS", "42000-42999")
    for env in ("OPENFACTORY_PANEL_TOKEN", "OPENFACTORY_PANEL_TOKENS", "OPENFACTORY_PRODUCT_TOKENS"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(api, "ProjectRegistry",
                        lambda: SimpleNamespace(list=lambda: [SimpleNamespace(name="acme")]))
    preview.record(preview.Preview(project="acme", unit="12", cards=("12",), state=preview.LIVE,
                                   services={"web": 3000, "api": 8000},
                                   from_change={"api": True, "web": False},
                                   expires_at=int(time.time()) + 3600))
    return TestClient(api.app)


def _upstream(monkeypatch, respond):
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return respond(request)

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return seen


def _inside(unit: str = "12") -> str:
    kept = preview.mint("acme", unit, expires=int(time.time()) + 600)
    return f"{preview.cookie_name('acme', unit)}={kept}"


def test_on_one_machine_the_router_targets_the_derived_loopback_port(panel, monkeypatch):
    seen = _upstream(monkeypatch, lambda req: httpx.Response(
        302, headers={"location": "http://127.0.0.1:42603/login?next=/"},
        stream=httpx.ByteStream(b"")))

    r = panel.get("/orders?page=2", headers={"host": f"{WEB}:8787", "cookie": "; ".join(
        [_inside(), "openfactory_token=panel-secret", "app_session=abc"])},
        follow_redirects=False)

    sent = seen[-1]
    assert str(sent.url) == "http://127.0.0.1:42603/orders?page=2", \
        "the target is the port the name derives, on the loopback"
    assert sent.headers["host"] == f"{WEB}:8787", "the browser's Host is forwarded unchanged"
    assert sent.headers.get("cookie") == "app_session=abc", "the panel's credential never travels"
    assert r.headers["location"] == f"http://{WEB}:8787/login?next=/", \
        "a redirect naming the loopback target is the preview's own address"


@pytest.mark.parametrize("cookie", ["", "app_session=abc", "__other__"])
def test_on_one_machine_the_key_is_checked_before_the_port_is_asked_anything(
        panel, monkeypatch, cookie):
    seen = _upstream(monkeypatch, lambda req: httpx.Response(200, stream=httpx.ByteStream(b"x")))
    if cookie == "__other__":
        cookie = _inside("13").replace("acme_13", "acme_12")   # another unit's key, our name

    r = panel.get("/", headers={"host": WEB, "cookie": cookie})

    assert r.status_code == 401 and not seen, "the loopback port was reached without the key"
    enter = panel.get(f"{preview.ENTER_PATH}?t={preview.mint('acme', '13', expires=2**31)}",
                      headers={"host": WEB}, follow_redirects=False)
    assert enter.status_code == 403 and not seen


def test_a_loopback_deployment_with_no_ports_routes_nowhere_and_says_why(panel, monkeypatch):
    seen = _upstream(monkeypatch, lambda req: httpx.Response(200, stream=httpx.ByteStream(b"x")))
    monkeypatch.delenv("OPENFACTORY_PREVIEW_PORTS")

    r = panel.get("/", headers={"host": WEB, "cookie": _inside()})

    assert r.status_code == 502 and "OPENFACTORY_PREVIEW_PORTS" in r.text and not seen


def test_the_compose_stack_still_targets_the_alias(panel, monkeypatch):
    seen = _upstream(monkeypatch, lambda req: httpx.Response(200, stream=httpx.ByteStream(b"x")))
    monkeypatch.setenv("OPENFACTORY_PREVIEW_REACH", "network")

    panel.get("/", headers={"host": WEB, "cookie": _inside()})

    assert str(seen[-1].url) == "http://web--acme--12:3000/"


# ── 5. what a loopback preview reaches is measured, and said ────────────────────────────────────


def test_the_probe_says_what_it_reached_and_what_it_could_not_measure(monkeypatch):
    monkeypatch.setattr(compose, "_host", Probe(internet="yes", loopback=True))
    assert compose.measure_reach("n", env={}) == Reached(True, True)
    monkeypatch.setattr(compose, "_host", Probe(internet="no", loopback=False))
    assert compose.measure_reach("n", env={}) == Reached(False, False)
    monkeypatch.setattr(compose, "_host", lambda argv, **kw: Ran(125, "", "Unable to find image"))
    got = compose.measure_reach("n", env={})
    assert got.internet is None and got.loopback is None and "Unable to find image" in got.why


def test_the_probe_runs_on_the_units_network_with_nothing_to_gain(monkeypatch):
    daemon = Probe()
    monkeypatch.setattr(compose, "_host", daemon)

    compose.measure_reach("openfactory-pv-acme-12-edge", env={"PATH": "/usr/bin"})

    argv, env = next((a, e) for a, e in daemon.calls if a[:2] == ["docker", "run"])
    at = argv.index("--network")
    assert argv[at + 1] == "openfactory-pv-acme-12-edge" and argv.count("--network") == 1
    assert "--rm" in argv and argv[argv.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges" in argv and compose.UTILITY_IMAGE in argv
    assert compose.EGRESS_PROBE in argv[-1] and "host.docker.internal" in argv[-1]
    assert env == {"PATH": "/usr/bin"}


@pytest.mark.parametrize("reached, says, never", [
    (Reached(True, True), ["this preview can reach the internet", "http://1.1.1.1/",
                           "this machine's own loopback", "the panel"], ["did not reach"]),
    (Reached(False, False), ["did not reach the internet", "not a promise"],
     ["can reach the internet", "own loopback"]),
    (Reached(None, None, "no alpine"), ["could not be measured", "no alpine",
                                        "nothing here claims it reaches nothing"],
     ["can reach the internet", "did not reach"]),
])
def test_the_card_says_what_was_measured_whichever_way_it_fell(reached, says, never):
    text = " ".join(compose.reach_notes(reached))
    for s in says:
        assert s in text, text
    for s in never:
        assert s not in text, text


def test_a_loopback_preview_measures_its_reach_when_it_starts_and_the_stack_does_not(
        root, monkeypatch):
    plan = _ok(_loopback(root))
    monkeypatch.setattr(compose, "_listening", lambda p: False)
    daemon = Probe(internet="yes")
    monkeypatch.setattr(compose, "_host", daemon)

    up = _runtime(reach="loopback", panel_container="").up(plan)

    assert up.ok, up.why
    assert any("this preview can reach the internet" in n for n in up.notes), up.notes
    assert any("own loopback" in n for n in up.notes)
    made = next(a for a, _ in daemon.calls
                if a[:3] == ["docker", "network", "create"] and a[-1] == plan.edge_network)
    assert "com.docker.network.bridge.enable_ip_masquerade=false" in made
    assert "--internal" not in made, "Docker forwards no published port into an internal network"
    probe = next(a for a, _ in daemon.calls if a[:2] == ["docker", "run"] and "sh" in a)
    assert probe[probe.index("--network") + 1] == plan.edge_network

    network = Probe(internet="yes")
    monkeypatch.setattr(compose, "_host", network)
    s1 = _ok(_plan(_canonical("s1", plan.workdir), S1_CFG, _layout(plan.workdir, _diff("s1"))))
    assert _runtime().up(s1).notes == ()
    assert not any(a[:2] == ["docker", "run"] and "sh" in a for a, _ in network.calls)


def test_what_the_runtime_measured_reaches_the_live_card(tmp_path):
    from openfactory.preview import steps

    plan = _ok(_loopback(tmp_path))
    written: list[preview.Preview] = []
    world = steps.World(record=written.append, latest=lambda p, t: written[-1] if written else None,
                        clock=lambda: 1_800_000_000)
    runtime = SimpleNamespace(up=lambda p: PreviewUp(
        ok=True, services={"web": 3000, "api": 8000}, health={"web": "started", "api": "healthy"},
        notes=("measured: this preview can reach the internet",)))

    assert steps.up(SimpleNamespace(name="acme"), "12", plan, runtime=runtime, world=world).ok

    live = written[-1]
    assert live.state == preview.LIVE
    assert "measured: this preview can reach the internet" in live.notes
    assert any(n.startswith("reached on this machine only") for n in live.notes), \
        "the plan's own notes were lost"


# ── 6. no Docker by default, and init's commented lines ─────────────────────────────────────────


def test_on_one_machine_with_no_runtime_the_card_says_how_to_opt_in(panel, monkeypatch):
    from openfactory.adapters.preview.none import ONE_MACHINE

    monkeypatch.setenv("OPENFACTORY_OWN_WORK", "1")
    monkeypatch.setenv("OPENFACTORY_PREVIEW_RUNTIME", "none")
    with_domain = panel.get("/api/preview/acme/13").json()
    monkeypatch.delenv("OPENFACTORY_PREVIEW_DOMAIN")
    commented = panel.get("/api/preview/acme/13").json()

    sentence = ("No preview on this deployment — the one-machine runtime names no preview "
                "runtime; with Docker installed, set OPENFACTORY_PREVIEW_RUNTIME=compose, "
                "OPENFACTORY_PREVIEW_REACH=loopback, OPENFACTORY_PREVIEW_PORTS=42000-42999 and "
                "OPENFACTORY_PREVIEW_DOMAIN=preview.localhost")
    assert ONE_MACHINE == sentence
    for body in (with_domain, commented):
        assert body["why"] == sentence + "." and body["can_start"] is False


def test_a_server_with_no_runtime_says_the_general_sentence(panel, monkeypatch):
    monkeypatch.delenv("OPENFACTORY_OWN_WORK", raising=False)
    monkeypatch.setenv("OPENFACTORY_PREVIEW_RUNTIME", "none")
    monkeypatch.delenv("OPENFACTORY_PREVIEW_DOMAIN")
    body = panel.get("/api/preview/acme/13").json()
    assert body["why"].startswith("no preview can run on this deployment: this deployment names "
                                  "no preview runtime")
    assert "one-machine" not in body["why"]


def test_the_job_offers_the_one_machine_sentence_too(monkeypatch):
    from openfactory.preview import demand

    monkeypatch.setenv("OPENFACTORY_OWN_WORK", "1")
    said = demand.why_not_here("none", required=True)
    assert said.startswith("No preview on this deployment — the one-machine runtime")
    assert "previews are required and none can run here" in said
    assert demand.why_not_here("compose", required=True) == ""


def test_init_writes_the_opt_in_commented_and_what_opting_in_means():
    from openfactory.onboarding.deployment import Answers, Probes, render

    text = render(Answers(), Probes(secret=lambda: "K3Y")).text
    block = text[text.index("# ── A preview of the product"):]
    active = re.findall(r"^(OPENFACTORY_PREVIEW_[A-Z_]+)=(.*)$", block, re.M)
    assert dict(active) == {"OPENFACTORY_PREVIEW_SECRET": "K3Y",
                            "OPENFACTORY_PREVIEW_RUNTIME": "none"}, "no Docker, by default"
    for line in ("# OPENFACTORY_PREVIEW_RUNTIME=compose", "# OPENFACTORY_PREVIEW_REACH=loopback",
                 "# OPENFACTORY_PREVIEW_PORTS=42000-42999",
                 "# OPENFACTORY_PREVIEW_DOMAIN=preview.localhost"):
        assert f"\n{line}\n" in block
    prose = " ".join(ln.lstrip("# ").strip() for ln in block.splitlines())
    for said in ("published on 127.0.0.1 of this machine and nowhere else",
                 "can open one without the key", "reach services listening on all interfaces",
                 "the internet and this machine's own loopback", "not measured on a Linux Engine",
                 "`openfactory doctor <project>` measures", "Safari"):
        assert said in prose, said
    compose_stack = render(Answers(runtime="compose", forge="github", tracker="github")).text
    assert "loopback" not in compose_stack.split("# ── A preview of the product")[1], \
        "the loopback reach is never rendered for the compose stack"


# ── 7. doctor says it ────────────────────────────────────────────────────────────────────────────


def _one_machine(**kw) -> doctor.PreviewState:
    base = dict(kind="compose", reach="loopback", ports="42000-42999", domain=DOMAIN,
                hosts=["web--acme--<card>", "api--acme--<card>"], sample=f"web--acme--1.{DOMAIN}",
                resolves=False, internet=True, loopback=True)
    base.update(kw)
    return doctor.PreviewState(**base)


def _lines(state) -> dict[str, doctor.Finding]:
    from tests.pinned_probes import a_fully_pinned_probe_set

    report = doctor.diagnose(a_fully_pinned_probe_set(preview=lambda: state))
    return {f.check: f for f in report.findings if f.check.startswith("preview")}


def test_doctor_says_the_four_lines_of_the_loopback_reach_and_none_is_red():
    lines = _lines(_one_machine())
    assert set(lines) == {"preview", "preview_safari", "preview_keyless", "preview_ifaces",
                          "preview_egress"}
    assert all(f.ok for f in lines.values()), "a line nobody can clear teaches people to skip"
    safari = lines["preview_safari"].message
    assert ("`127.0.0.1 web--acme--<card>.preview.localhost api--acme--<card>.preview.localhost`"
            in safari) and "Safari needs a line in /etc/hosts" in safari
    keyless = lines["preview_keyless"].message
    assert "127.0.0.1, ports 42000-42999" in keyless and "without the key" in keyless
    assert "job box" in keyless
    ifaces = lines["preview_ifaces"].message
    assert "all interfaces of this machine" in ifaces and "its own loopback too" in ifaces
    egress = lines["preview_egress"].message
    assert egress.startswith("measured now: a container on a loopback preview's network reached "
                             "the internet (http://1.1.1.1/)")


def test_doctor_says_each_measurement_whichever_way_it_fell():
    closed = _lines(_one_machine(internet=False, loopback=False, resolves=True))
    assert "did not reach the internet" in closed["preview_egress"].message
    assert "its loopback was not reached" in closed["preview_ifaces"].message
    assert "resolver sends `web--acme--1.preview.localhost` to itself" in \
        closed["preview_safari"].message
    assert "127.0.0.1 web--acme--<card>.preview.localhost" in closed["preview_safari"].message
    unknown = _lines(_one_machine(internet=None, loopback=None, unmeasured="no daemon"))
    assert "could not be measured now: no daemon" in unknown["preview_egress"].message
    assert "nothing here claims it reaches nothing" in unknown["preview_egress"].message
    assert "could not be measured now: no daemon" in unknown["preview_ifaces"].message


def test_doctor_says_nothing_of_the_loopback_where_previews_reach_a_network():
    assert set(_lines(doctor.PreviewState(kind="compose"))) == {"preview"}
    named = _lines(_one_machine(domain="preview.example.com"))
    assert "preview_safari" not in named, "a named domain is DNS's, not the browser's"


def test_doctor_measures_on_this_machine_when_the_runtime_is_ready(monkeypatch, tmp_path):
    from openfactory.adapters.preview import registry
    from openfactory.contracts.project import PreviewPolicy, Project
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_PREVIEW_RUNTIME", "compose")
    monkeypatch.setenv("OPENFACTORY_PREVIEW_REACH", "loopback")
    monkeypatch.setenv("OPENFACTORY_PREVIEW_PORTS", "42000-42999")
    monkeypatch.setenv("OPENFACTORY_PREVIEW_DOMAIN", DOMAIN)
    acme = Project(name="acme", repo_path=str(tmp_path), preview=PreviewPolicy())
    ProjectRegistry().add(acme)
    ready = SimpleNamespace(prerequisites=lambda: [])
    monkeypatch.setattr(registry, "build_runtime", lambda kind, **kw: ready)
    monkeypatch.setattr(compose, "legacy_network_present", lambda: False)
    monkeypatch.setattr(compose, "measure_reach_now", lambda **kw: Reached(True, False))
    asked: list[str] = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *a, **k: asked.append(host) or [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))])

    state = doctor.probes_for(acme).preview()

    assert (state.reach, state.ports, state.domain) == ("loopback", "42000-42999", DOMAIN)
    assert (state.internet, state.loopback) == (True, False)
    assert state.resolves is True and asked == [state.sample]
    assert state.sample.endswith(f"--acme--1.{DOMAIN}")

    monkeypatch.setattr(registry, "build_runtime",
                        lambda kind, **kw: SimpleNamespace(prerequisites=lambda: ["no daemon"]))
    monkeypatch.setattr(compose, "measure_reach_now", lambda **kw: pytest.fail("measured"))
    unready = doctor.probes_for(acme).preview()
    assert unready.internet is None and "not ready" in unready.unmeasured


@pytest.mark.parametrize("answer", [
    [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))],
    [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 0, 0, 0)),
     (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.9", 0))],
    socket.gaierror("nodename nor servname provided"),
])
def test_a_resolver_that_sends_the_name_anywhere_else_is_not_this_machine(monkeypatch, tmp_path,
                                                                          answer):
    from openfactory.adapters.preview import registry
    from openfactory.contracts.project import PreviewPolicy, Project

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_PREVIEW_RUNTIME", "compose")
    monkeypatch.setenv("OPENFACTORY_PREVIEW_REACH", "loopback")
    monkeypatch.setenv("OPENFACTORY_PREVIEW_DOMAIN", DOMAIN)
    monkeypatch.setattr(registry, "build_runtime",
                        lambda kind, **kw: SimpleNamespace(prerequisites=lambda: ["no daemon"]))
    monkeypatch.setattr(compose, "legacy_network_present", lambda: False)

    def resolve(host, port, *a, **k):
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    acme = Project(name="acme", repo_path=str(tmp_path), preview=PreviewPolicy())

    assert doctor.probes_for(acme).preview().resolves is False
