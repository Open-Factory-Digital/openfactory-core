"""#291 — a preview reaches nothing of the machine it runs on.

AN INTERNAL NETWORK WAS NOT ENOUGH. Docker's `internal` network still gives its bridge an address
on the host, and a container on it reaches every service listening on the host's addresses through
that gateway. Measured on a Linux engine (Docker Engine 29.1.3, 2026-09-25): a listener on
`0.0.0.0` of the host answered a container on an internal network through the network's gateway.
The same network made with `com.docker.network.bridge.gateway_mode_ipv4=isolated` reached none of
the host's addresses, and its containers still reached one another by name — which is how the
panel reaches a service. So every network a unit runs on is made that way.

AND IT IS READ BACK, NOT ASSUMED. An engine that ignored the option would leave the gateway where
it was, and nothing would say so. The engine is asked first, on a network made for the purpose;
the unit's edge is read back after it is made (one left from before was made by whatever made it);
and the default network `up` makes is read back at once, the unit taken down if it has a gateway.
A preview that cannot be closed off does not start, and its card says why.

The last test measures it on the daemon this suite runs against, when there is one.
"""

from __future__ import annotations

import json
import secrets
import subprocess
from pathlib import Path

import pytest

from openfactory import preview
from openfactory.adapters.preview import compose
from openfactory.adapters.preview.base import refusals
from openfactory.adapters.preview.compose import Ran
from tests.test_a_preview_runs_on_a_real_daemon import _docker_and_compose
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

#: What `docker network inspect --format '{{json .IPAM.Config}}'` answers, recorded on Docker Engine
#: 29.1.3: an internal network, and the same network with its gateway isolated.
WITH_A_GATEWAY = json.dumps([{"Subnet": "172.21.0.0/16", "IPRange": "", "Gateway": "172.21.0.1"}])
WITHOUT = json.dumps([{"Subnet": "172.22.0.0/16", "IPRange": "", "Gateway": ""}])


class Engine(Daemon):
    """The faked daemon, answering what #291 asks it: whether it accepts the option at all, and
    whether a network it made has an address on the host. `honours=False` is an engine that takes
    the option and ignores it; `left` names networks that keep a gateway whatever they were made
    with (an edge left from before, a default network `up` made wrong)."""

    def __init__(self, *, honours: bool = True, accepts: bool = True, left=(), **kw):
        super().__init__(**kw)
        self.honours, self.accepts, self.left = honours, accepts, tuple(left)

    def __call__(self, argv, *, env=None, timeout=120, input=None):
        argv = list(argv)
        if argv[:3] == ["docker", "network", "create"]:
            self.calls.append((argv, dict(env) if env is not None else None))
            if not self.accepts and any("gateway_mode_ipv4" in a for a in argv):
                return Ran(1, "", "Error response from daemon: invalid option gateway_mode_ipv4")
            return Ran(0, secrets.token_hex(8), "")
        if argv[:3] == ["docker", "network", "inspect"]:
            self.calls.append((argv, dict(env) if env is not None else None))
            name = argv[3]
            kept = not self.honours or any(name.endswith(s) for s in self.left)
            return Ran(0, WITH_A_GATEWAY if kept else WITHOUT, "")
        return super().__call__(argv, env=env, timeout=timeout, input=input)


@pytest.fixture
def root(tmp_path, monkeypatch):
    real = Path(tmp_path).resolve()
    monkeypatch.setenv("OPENFACTORY_WORK_DIR", str(real))
    monkeypatch.setenv("OPENFACTORY_PREVIEW_DOCKER_CONFIG", str(real / "docker-config"))
    return real


def _network_plan(root):
    wd = _workdir(root, "s1")
    return _ok(_plan(_canonical("s1", wd), S1_CFG, _layout(wd, _diff("s1"))))


def _started(engine: Engine) -> bool:
    return any(Daemon.sub(a) == "up" for a, _ in engine.calls)


def _created(engine: Engine, name: str) -> list[str]:
    return next(a for a, _ in engine.calls
                if a[:3] == ["docker", "network", "create"] and a[-1] == name)


# ── what a unit's networks are made as ─────────────────────────────────────────────────────────

def test_every_network_a_unit_runs_on_is_made_with_no_gateway_on_the_host(root, monkeypatch):
    plan = _network_plan(root)
    engine = Engine()
    monkeypatch.setattr(compose, "_host", engine)

    up = _runtime().up(plan)

    assert up.ok, up.why
    assert plan.doc["networks"]["default"] == {"internal": True,
                                               "driver_opts": preview.ISOLATED_GATEWAY}
    edge = _created(engine, plan.edge_network)
    assert "--internal" in edge
    assert "com.docker.network.bridge.gateway_mode_ipv4=isolated" in edge
    read_back = [a[3] for a, _ in engine.calls if a[:3] == ["docker", "network", "inspect"]]
    assert plan.edge_network in read_back and f"{plan.compose_project}_default" in read_back, (
        "a network was trusted to be what it was asked to be, not read back")


def test_admission_refuses_a_default_network_that_keeps_its_gateway(root):
    plan = _network_plan(root)
    open_doc = {**plan.doc, "networks": {**plan.doc["networks"], "default": {"internal": True}}}

    said = refusals(plan.model_copy(update={"doc": open_doc}))

    assert any("keeps a gateway on the host" in s for s in said), said
    assert not refusals(plan), "the assembler's own plan is refused"


# ── an engine that does not close it off starts nothing ────────────────────────────────────────

def test_an_engine_that_takes_the_option_and_ignores_it_starts_nothing(root, monkeypatch):
    plan = _network_plan(root)
    engine = Engine(honours=False)
    monkeypatch.setattr(compose, "_host", engine)

    up = _runtime().up(plan)

    assert not up.ok and "did not honour" in up.why and "no preview is started" in up.why
    assert not _started(engine), "the services were started on an engine that leaves the gateway"
    probes = [a[-1] for a, _ in engine.calls if a[:3] == ["docker", "network", "create"]]
    assert probes and all(p.startswith("openfactory-pv-isolation-") for p in probes)
    assert ["docker", "network", "rm", probes[0]] in [a for a, _ in engine.calls], (
        "the network made to ask the engine was left behind")


def test_an_engine_that_refuses_the_option_starts_nothing_and_says_so(root, monkeypatch):
    plan = _network_plan(root)
    engine = Engine(accepts=False)
    monkeypatch.setattr(compose, "_host", engine)

    up = _runtime().up(plan)

    assert not up.ok and "cannot make an internal network with no gateway" in up.why
    assert "invalid option" in up.why, "the engine's own sentence is kept"
    assert not _started(engine)


def test_an_edge_left_from_before_with_a_gateway_is_not_run_on(root, monkeypatch):
    plan = _network_plan(root)
    engine = Engine(left=(plan.edge_network,))
    monkeypatch.setattr(compose, "_host", engine)

    up = _runtime().up(plan)

    assert not up.ok and f"`{plan.edge_network}` has an address on this machine" in up.why
    assert not _started(engine)
    assert not any(a[:3] == ["docker", "network", "connect"] for a, _ in engine.calls), (
        "the panel joined a network a preview could reach the host from")


def test_a_default_network_made_with_a_gateway_is_taken_down_at_once(root, monkeypatch):
    plan = _network_plan(root)
    engine = Engine(left=("_default",))
    monkeypatch.setattr(compose, "_host", engine)

    up = _runtime().up(plan)

    assert not up.ok and f"`{plan.compose_project}_default` has an address" in up.why
    subs = [Daemon.sub(a) for a, _ in engine.calls if a[:2] == ["docker", "compose"]]
    assert "up" in subs and "down" in subs[subs.index("up"):], (
        "the services stayed up on a network that reaches the host")


# ── measured on the daemon this suite runs against ─────────────────────────────────────────────

def _docker(*argv: str, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *argv], capture_output=True, text=True, timeout=timeout,
                          check=False)


@pytest.mark.slow
@pytest.mark.skipif(not _docker_and_compose(), reason="needs a Docker daemon")
def test_on_a_real_engine_a_unit_network_reaches_nothing_of_the_host():
    """A listener on every address of the host (the host's own network namespace), and two
    probes: one on a plain internal network, which must reach it — so a quiet answer from the
    other is a closed network, not a probe that sees nothing — and one on a network made the way
    a unit's edge is, which must reach none of the host's addresses."""
    import os

    env = dict(os.environ)
    unhonoured = compose.isolation_unhonoured(env)
    if unhonoured:
        pytest.skip(f"this engine does not honour the option, so no preview starts on it: "
                    f"{unhonoured}")
    tag = f"of291-{secrets.token_hex(4)}"
    label = f"{preview.LABEL}={tag}"
    port = "18291"
    try:
        assert _docker("run", "-d", "--rm", "--network", "host", "--name", f"{tag}-listener",
                       "--label", label, compose.UTILITY_IMAGE, "sh", "-c",
                       f"while true; do echo reached-the-host | nc -l -p {port}; done"
                       ).returncode == 0
        assert _docker("network", "create", "--internal", "--label", label,
                       f"{tag}-plain").returncode == 0
        assert _docker("network", "create", *compose.NETWORK_EDGE_OPTS, "--label", label,
                       f"{tag}-unit").returncode == 0
        addresses = _docker("exec", f"{tag}-listener", "sh", "-c",
                            "ip -4 -o addr show | awk '{print $4}' | cut -d/ -f1 "
                            "| grep -v '^127\\.'").stdout.split()
        gateway = _docker("network", "inspect", f"{tag}-plain", "--format",
                          "{{range .IPAM.Config}}{{.Gateway}}{{end}}").stdout.strip()
        assert gateway in addresses, (gateway, addresses)

        def probe(network: str, targets: list[str]) -> str:
            script = "; ".join(f"echo {t}=$(timeout 4 nc -w 3 {t} {port} </dev/null)"
                               for t in targets)
            return _docker("run", "--rm", "--network", network, "--cap-drop", "ALL",
                           "--label", label, compose.UTILITY_IMAGE, "sh", "-c", script,
                           timeout=120).stdout

        assert f"{gateway}=reached-the-host" in probe(f"{tag}-plain", [gateway]), (
            "the control could not reach the host, so the closed answer below would prove nothing")
        reached = [line for line in probe(f"{tag}-unit", addresses).splitlines()
                   if "reached-the-host" in line]
        assert not reached, f"a unit's network reached the host at {reached}"
    finally:
        for kind in ("container", "network"):
            ids = _docker(kind, "ls", "-aq" if kind == "container" else "-q", "--filter",
                          f"label={label}").stdout.split()
            if ids:
                _docker(kind, "rm", "-f", *ids) if kind == "container" else \
                    _docker(kind, "rm", *ids)
