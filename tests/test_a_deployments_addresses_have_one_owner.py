"""A deployment's addresses have ONE owner, and the starter says what it started (#183).

WHAT HAPPENED. On a one-machine deployment (`init --runtime local`, then `openfactory up`) the
panel's **Engine ↗** button on a running card opened `http://localhost:8233/…` and answered
`ERR_CONNECTION_REFUSED`. The engine's UI was up — on 8080, where `up` had started it with a
literal — and the panel had guessed another literal. It was the third time the same defect
shipped: #163 stopped the engine ADDRESS being guessed, and the compose file patched its own copy
of the UI link by hand. Read from the code, the same cause had two more instances waiting:
`up --panel-port 9000` served the panel on 9000 while every card link said 8787, and a declared
`TEMPORAL_ADDRESS=localhost:7300` was honoured by the worker and ignored by the engine.

THE PROPERTY, NOT THE LITERALS. The guard that existed pinned `http://localhost:8233` — it locked
the guess in. What is held here is AGREEMENT: for every way a deployment is started, the port each
listener STARTS on equals the port every consumer RESOLVES in the environment that runtime hands
it. Each case reads the thing itself — the argv `up` hands the supervisor, the environment it
hands the children, the compose file parsed as YAML and interpolated as compose does, the env
file `init` renders — and resolves the consumers' own functions inside that environment.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml
from typer.testing import CliRunner

from openfactory.runtime import host

ROOT = Path(__file__).resolve().parents[1]

#: Every variable that says where a listener starts or how it is reached. Cleared before each
#: case, so a case declares exactly what it means to and the machine running it declares nothing.
_EVERY_VAR = ("TEMPORAL_ADDRESS", "TEMPORAL_ENDPOINT", "TEMPORAL_UI_URL", "OPENFACTORY_PANEL_URL",
              "TEMPORAL_PORT", "TEMPORAL_UI_PORT", "PANEL_PORT")


@pytest.fixture(autouse=True)
def _nothing_declared(monkeypatch, tmp_path):
    for var in _EVERY_VAR:
        monkeypatch.delenv(var, raising=False)
    # `up` reads `~/.openfactory/env`: a HOME of its own keeps this machine's deployment out.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)


# ── reading the thing ────────────────────────────────────────────────────────────────────────────

def _up(monkeypatch, *args: str, binary: str | None = "/usr/bin/temporal"):
    """`openfactory up`, with the supervisor captured: `(plan, children's env, output, exit)`."""
    from openfactory import cli

    monkeypatch.setattr(host, "the_engine", lambda: binary)
    monkeypatch.setattr(host, "the_client", lambda: True)
    seen: list[tuple[list, dict]] = []

    def run(plan, *, say, grace=host.GRACE_S, env=None):
        # `env=None` is a child that INHERITS — which is what every child did before #183.
        seen.append((plan, dict(os.environ if env is None else env)))
        return 0

    monkeypatch.setattr(host, "run", run)
    result = CliRunner().invoke(cli.app, ["up", *args])
    plan, env = seen[0] if seen else ([], {})
    return plan, env, " ".join(result.output.split()), result.exit_code


def _after(argv: list[str], flag: str) -> int:
    return int(argv[argv.index(flag) + 1])


def _started(plan) -> dict[str, int]:
    """The port each listener STARTS on, read off the argv the supervisor was handed."""
    ports: dict[str, int] = {}
    for name, argv in plan:
        if name == "engine":
            ports["engine"] = _after(argv, "--port")
            ports["engine UI"] = _after(argv, "--ui-port")
        if name == "panel":
            ports["panel"] = _after(argv, "--port")
    return ports


def _resolved(monkeypatch, env: dict[str, str]) -> dict[str, int | None]:
    """The port every CONSUMER resolves inside `env`, asked of the consumers' own functions."""
    from openfactory.adapters.tracker.local import LocalTracker
    from openfactory.runtime.temporal import connection, view

    with monkeypatch.context() as inside:
        for var in _EVERY_VAR:
            inside.delenv(var, raising=False)
            if var in env:
                inside.setenv(var, env[var])
        engine = urlsplit(f"//{connection.address()}").port
        ui = urlsplit(view.temporal_url("openfactory-acme-7", "run", "default")).port
        card = urlsplit(LocalTracker("acme").ticket_url("#7")).port
    return {"engine": engine, "engine UI": ui, "panel": card}


def _rows(text: str) -> dict[str, str]:
    rows = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            rows[key.strip()] = value.strip()
    return rows


def _what_init_writes() -> dict[str, str]:
    """The address rows `openfactory init --runtime local` writes, from its own renderer."""
    from openfactory.onboarding import deployment

    answers = deployment.Answers(runtime="local", forge="local", tracker="local")
    written = _rows(deployment.render(answers).text)
    return {var: written[var] for var in _EVERY_VAR if var in written}


# ── 1. every way `up` starts: what starts is what is reached ─────────────────────────────────────

_WAYS = {
    "a clean machine": ((), {}),
    "--panel-port": (("--panel-port", "9000"), {}),
    "a declared engine port": ((), {"TEMPORAL_ADDRESS": "localhost:7300"}),
    "the other name for the engine": ((), {"TEMPORAL_ENDPOINT": "127.0.0.1:7301"}),
    "a moved UI port": ((), {"TEMPORAL_UI_PORT": "8081"}),
    "a declared UI address": ((), {"TEMPORAL_UI_URL": "http://localhost:9090"}),
    "a moved panel port": ((), {"PANEL_PORT": "9001"}),
    "a declared panel address": ((), {"OPENFACTORY_PANEL_URL": "http://127.0.0.1:9002/"}),
}


@pytest.mark.parametrize("way", sorted(_WAYS))
def test_what_up_STARTS_is_what_its_children_REACH(monkeypatch, way):
    args, declared = _WAYS[way]
    for var, value in declared.items():
        monkeypatch.setenv(var, value)

    plan, env, said, code = _up(monkeypatch, *args)

    assert code == 0, said
    started = _started(plan)
    assert set(started) == {"engine", "engine UI", "panel"}, plan
    assert _resolved(monkeypatch, env) == started, (
        f"{way}: `up` started {started} and what it started reaches "
        f"{_resolved(monkeypatch, env)} — a listener on one port with its consumers on another")


@pytest.mark.parametrize("name", ["TEMPORAL_ADDRESS", "TEMPORAL_ENDPOINT"])
def test_a_declared_engine_port_is_where_the_engine_STARTS(monkeypatch, name):
    """The second instance, read from the code: the worker honoured the declaration and `up`
    started the engine on its literal anyway — the worker found nothing and took the set down.

    UNDER EITHER NAME. Agreement alone cannot see a name the definition forgot: `up` and its
    children would agree with each other on the default, and the deployment's line would be
    ignored by all of them at once."""
    monkeypatch.setenv(name, "localhost:7300")

    plan, _, _, _ = _up(monkeypatch)

    assert _started(plan)["engine"] == 7300


def test_the_panel_port_reaches_the_card_links(monkeypatch):
    """The first: `--panel-port 9000` printed the right address and changed nobody's links."""
    plan, env, said, _ = _up(monkeypatch, "--panel-port", "9000")

    assert _started(plan)["panel"] == 9000
    assert "http://localhost:9000" in said
    from openfactory.adapters.tracker.local import LocalTracker

    with monkeypatch.context() as inside:
        inside.setenv("OPENFACTORY_PANEL_URL", env["OPENFACTORY_PANEL_URL"])
        assert LocalTracker("acme").ticket_url("#7") == "http://localhost:9000/p/acme/card/7"


def test_a_deployment_init_wrote_starts_where_its_file_says(monkeypatch):
    """`init` writes its three address lines from the same definition `up` starts on."""
    written = _what_init_writes()
    assert {"TEMPORAL_ADDRESS", "TEMPORAL_UI_URL", "OPENFACTORY_PANEL_URL"} <= set(written), (
        f"init declares {sorted(written)} — an address it leaves out is one a panel started by "
        f"hand has nobody to tell it")
    for var, value in written.items():
        monkeypatch.setenv(var, value)

    plan, env, said, code = _up(monkeypatch)

    assert code == 0, said
    assert _resolved(monkeypatch, env) == _started(plan)
    assert "this run was asked" not in said, f"nothing was moved, so nothing is announced: {said}"


def test_the_panel_port_wins_over_the_line_init_wrote_and_says_so(monkeypatch):
    """The file `init` wrote says 8787 and the person just asked for 9000, about the same listener
    on the same machine: this run follows the command line, out loud, and its links follow it."""
    for var, value in _what_init_writes().items():
        monkeypatch.setenv(var, value)

    plan, env, said, code = _up(monkeypatch, "--panel-port", "9000")

    assert code == 0, said
    assert _started(plan)["panel"] == 9000
    assert _resolved(monkeypatch, env)["panel"] == 9000
    assert "OPENFACTORY_PANEL_URL" in said and "9000" in said, (
        f"a declaration this run did not follow is said, not swallowed: {said}")


def test_an_address_behind_another_name_is_left_as_declared(monkeypatch):
    """A proxy or a tunnel in front of this machine: `up` cannot know the mapping, so what the
    operator declared explicitly is what the children are handed — never overwritten."""
    monkeypatch.setenv("OPENFACTORY_PANEL_URL", "https://factory.example")
    monkeypatch.setenv("TEMPORAL_UI_URL", "https://engine.example/ui")

    _, env, said, code = _up(monkeypatch)

    assert code == 0, said
    assert env["OPENFACTORY_PANEL_URL"] == "https://factory.example"
    assert env["TEMPORAL_UI_URL"] == "https://engine.example/ui"


# ── 2. a declaration `up` cannot start on is a sentence, never a split ───────────────────────────

@pytest.mark.parametrize("declared,names", [
    ({"TEMPORAL_ADDRESS": "engine.example:7233"}, ["TEMPORAL_ADDRESS", "--no-engine"]),
    ({"TEMPORAL_ADDRESS": "localhost:abc"}, ["TEMPORAL_ADDRESS", "localhost:abc"]),
    ({"TEMPORAL_ADDRESS": "localhost"}, ["TEMPORAL_ADDRESS", "no port"]),
    ({"TEMPORAL_ADDRESS": "localhost:7233", "TEMPORAL_PORT": "7300"},
     ["TEMPORAL_ADDRESS", "TEMPORAL_PORT"]),
    ({"TEMPORAL_UI_URL": "localhost:8080"}, ["TEMPORAL_UI_URL", "http://"]),
    ({"PANEL_PORT": "eighty"}, ["PANEL_PORT", "eighty"]),
])
def test_a_declaration_up_cannot_honour_is_REFUSED_in_a_sentence(monkeypatch, declared, names):
    for var, value in declared.items():
        monkeypatch.setenv(var, value)

    plan, _, said, code = _up(monkeypatch)

    assert code == 1 and not plan, (
        f"`up` started {_started(plan)} beside {declared} — one port started while its consumers "
        f"look at another is the split this refuses")
    assert "Traceback" not in said
    for name in names:
        assert name in said, f"the refusal does not name {name!r}: {said}"


def test_an_engine_declared_elsewhere_is_left_alone_when_no_engine_starts(monkeypatch):
    """`--no-engine` is the remedy the refusal names, so it has to work: the panel serves against
    the engine that was declared, and nothing is said about one this run does not own."""
    monkeypatch.setenv("TEMPORAL_ADDRESS", "engine.example:7233")

    plan, env, said, code = _up(monkeypatch, "--no-engine")

    assert code == 0, said
    assert [name for name, _ in plan] == ["panel"]
    assert env["TEMPORAL_ADDRESS"] == "engine.example:7233"
    assert "TEMPORAL_UI_URL" not in env, "no engine UI was started, so none is announced"


# ── 3. the children really are handed it ─────────────────────────────────────────────────────────

def test_the_supervisor_starts_its_children_IN_the_environment_it_was_given(tmp_path):
    """The real `Popen`, a real child: what `deployment` resolved is what the child reads."""
    out = tmp_path / "said.txt"
    child = [sys.executable, "-c",
             "import os, pathlib, sys; "
             f"pathlib.Path({str(out)!r}).write_text(os.environ.get('TEMPORAL_UI_URL', 'UNSET'))"]

    host.run([("probe", child)], say=lambda _line: None, grace=2.0,
             env={**os.environ, "TEMPORAL_UI_URL": "http://localhost:8099"})

    assert out.read_text() == "http://localhost:8099"


# ── 4. no guess for an address a person clicks ───────────────────────────────────────────────────

def test_nobody_said_where_the_UI_is_so_there_is_NO_link(monkeypatch):
    from openfactory.runtime.temporal import view

    monkeypatch.setenv("TEMPORAL_ADDRESS", "localhost:7233")

    assert view.ui_base() == ""
    assert view.temporal_url("openfactory-acme-7", "run", "default") == "", (
        "a path appended to nothing is still a link — to the page the person is already on")


def test_and_the_cockpit_draws_the_button_GREYED_with_the_variable_to_set(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from openfactory.api import app as panel

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "worktree")
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)

    # NOTHING DECLARED AT ALL — not even an engine. This drew a working button to a cloud console
    # that is not this deployment's, under a log line saying the engine links were "hidden".
    cockpit = TestClient(panel.app).get("/api/factory/acme").json()
    assert not cockpit["links"]["temporal"], f"an engine link with no engine: {cockpit['links']}"

    monkeypatch.setenv("TEMPORAL_ADDRESS", "localhost:7233")
    cockpit = TestClient(panel.app).get("/api/factory/acme").json()

    assert not cockpit["links"]["temporal"], f"an engine link nobody declared: {cockpit['links']}"
    assert "TEMPORAL_UI_URL" in cockpit["engine_ui_hint"]
    # THE SENTENCE RIDES BESIDE THE BUTTONS, NOT AMONG THEM: every key of `links` is a button the
    # how-to owes a paragraph (`test_the_panel_says_where_to_change_things.py`).
    assert set(cockpit["links"]) == {"board", "temporal"}

    monkeypatch.setenv("TEMPORAL_UI_URL", "http://localhost:8099/")
    cockpit = TestClient(panel.app).get("/api/factory/acme").json()
    assert cockpit["links"]["temporal"].startswith(
        "http://localhost:8099/namespaces/default/workflows?")
    assert cockpit["engine_ui_hint"] == ""


def test_every_engine_frame_says_whether_the_UI_is_known(monkeypatch):
    from openfactory.api import app as panel
    from openfactory.runtime.temporal import view

    unknown = panel._engine_ui(view)
    assert unknown["ui_base"] == "" and "TEMPORAL_UI_URL" in unknown["ui_hint"]

    monkeypatch.setenv("TEMPORAL_UI_URL", "http://localhost:8099")
    assert panel._engine_ui(view) == {"ui_base": "http://localhost:8099", "ui_hint": ""}


def test_the_page_draws_an_unknown_engine_address_as_a_sentence_not_an_empty_href():
    """Read off the page's own script: every engine link goes through the one renderer, and no
    anchor is built straight from a job's `temporal_url` — an empty `href` is the current page."""
    page = (ROOT / "openfactory" / "api" / "panel.html").read_text(encoding="utf-8")
    script = re.sub(r"^\s*//.*$", "", page, flags=re.M)   # comments describe the old shape

    assert not re.search(r'href="\$\{[^}]*temporal_url', script), (
        "an anchor is built from `temporal_url` directly")
    assert len(re.findall(r"engineLink\([jd]\.temporal_url", script)) == 3
    assert "jump(L.temporal,\"Engine\",f.engine_ui_hint)" in script


def test_nobody_said_where_the_PANEL_is_so_a_card_link_is_the_route_alone():
    from openfactory.adapters.tracker.local import LocalTracker, panel_url

    assert panel_url() == ""
    assert LocalTracker("acme").ticket_url("#7") == "/p/acme/card/7"


# ── 5. the doctor checks every address the panel links to ────────────────────────────────────────

def _processes_finding(answered):
    from openfactory import doctor
    from tests.pinned_probes import a_fully_pinned_probe_set

    report = doctor.diagnose(a_fully_pinned_probe_set(processes=lambda: answered))
    return next(f for f in report.findings if f.check == "processes")


def test_the_doctor_FAILS_on_an_engine_UI_that_does_not_answer():
    finding = _processes_finding({"engine": (True, "localhost:7233"),
                                  "engine UI": (False, "http://localhost:8080"),
                                  "panel": (True, "http://localhost:8787")})

    assert not finding.ok
    assert "http://localhost:8080" in finding.message and "Engine" in finding.message
    assert "TEMPORAL_UI_URL" in finding.remedy


def test_the_doctor_names_the_variable_when_nobody_said_where_the_UI_is():
    finding = _processes_finding({"engine": (True, "engine.example:7233"),
                                  "engine UI": (False, ""),
                                  "panel": (True, "http://localhost:8787")})

    assert not finding.ok
    assert "TEMPORAL_UI_URL" in finding.remedy and "no **Engine" in finding.message


def test_the_doctor_says_where_the_UI_answers_when_it_does():
    finding = _processes_finding({"engine": (True, "localhost:7233"),
                                  "engine UI": (True, "http://localhost:8080"),
                                  "panel": (True, "http://localhost:8787")})

    assert finding.ok and "http://localhost:8080" in finding.message


def test_the_doctor_reports_a_declaration_up_would_refuse():
    finding = _processes_finding({"refused": (False, "`TEMPORAL_PORT=7300` and … disagree")})

    assert not finding.ok and "TEMPORAL_PORT=7300" in finding.message


def _probe(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from openfactory import doctor

    monkeypatch.setenv("OPENFACTORY_OWN_WORK", "1")
    project = SimpleNamespace(name="acme", repo_path=str(tmp_path), forge=None, tracker=None)
    probe = doctor.probes_for(project).processes
    assert probe is not None
    return probe


def test_the_doctors_probe_looks_where_up_STARTS_each_listener(monkeypatch, tmp_path):
    """The real probe, against real sockets: it finds the UI on the port `up` would start it on in
    THIS environment — a moved port included — and not on a literal of its own."""
    import socket

    listening = []
    for _ in range(3):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        listening.append(sock)
    engine, ui, panel = (s.getsockname()[1] for s in listening)
    try:
        monkeypatch.setenv("TEMPORAL_ADDRESS", f"127.0.0.1:{engine}")
        monkeypatch.setenv("TEMPORAL_UI_URL", f"http://127.0.0.1:{ui}")
        monkeypatch.setenv("PANEL_PORT", str(panel))

        answered = _probe(monkeypatch, tmp_path)()
    finally:
        for sock in listening:
            sock.close()

    assert answered == {"engine": (True, f"127.0.0.1:{engine}"),
                        "engine UI": (True, f"http://127.0.0.1:{ui}"),
                        "panel": (True, f"http://localhost:{panel}")}


def test_without_the_engines_library_a_DECLARED_engine_is_not_called_undeclared(
        monkeypatch, tmp_path):
    """The probe read the engine's address by importing `connection`, which imports `temporalio`,
    inside a `try` that reported every failure as `not declared (…)`. So an install without the
    `runtime` extra was told `not declared (No module named 'temporalio')` about an engine its
    own file declared — the missing thing was the library, and the sentence sent the reader to
    set a variable that was already set. Where the engine is was never the library's to say."""
    import sys

    probe = _probe(monkeypatch, tmp_path)
    for name in [m for m in sys.modules if m.split(".")[0] == "temporalio"
                 or m.startswith("openfactory.runtime.temporal.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "temporalio", None)

    monkeypatch.setenv("TEMPORAL_ADDRESS", "127.0.0.1:1")
    _, where = probe()["engine"]
    assert where == "127.0.0.1:1", f"a declared engine was reported as {where!r}"

    monkeypatch.delenv("TEMPORAL_ADDRESS")
    answers, where = probe()["engine"]
    assert not answers and "not declared" in where and "TEMPORAL_ADDRESS" in where
    assert "module" not in where.lower(), f"an undeclared engine blamed on a library: {where!r}"


def test_the_doctors_probe_hands_back_what_up_would_refuse(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMPORAL_ADDRESS", "localhost:7233")
    monkeypatch.setenv("TEMPORAL_PORT", "7300")

    answered = _probe(monkeypatch, tmp_path)()

    assert set(answered) == {"refused"} and "TEMPORAL_PORT" in answered["refused"][1]


# ── 6. the compose file agrees with itself, and with the definition ──────────────────────────────

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^${}]*))?\}")


def _interpolate(text: str, env: dict[str, str]) -> str:
    """Compose's `${A:-default}`, innermost first — the file nests one default inside another."""
    previous = None
    while previous != text:
        previous = text
        text = _VAR.sub(lambda m: env.get(m.group(1)) or (m.group(2) or ""), text)
    return text


def _compose(env: dict[str, str]) -> dict:
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    out: dict = {"published": {}, "container": {}, "reach": {}}
    for name, service in services.items():
        for mapping in service.get("ports") or []:
            published, _, container = _interpolate(str(mapping), env).rpartition(":")
            out["published"][name], out["container"][name] = int(published), int(container)
        for var, value in (service.get("environment") or {}).items():
            if var in _EVERY_VAR:
                out["reach"].setdefault(var, {})[name] = _interpolate(str(value), env)
    out["panel argv"] = [str(part) for part in services["panel"]["command"]]
    return out


@pytest.mark.parametrize("env", [
    {},
    {"PANEL_PORT": "9000", "TEMPORAL_UI_PORT": "8081", "TEMPORAL_PORT": "7300"},
], ids=["as shipped", "every port moved"])
def test_the_compose_file_links_to_the_ports_it_PUBLISHES(env):
    compose = _compose(env)

    for service, url in compose["reach"]["TEMPORAL_UI_URL"].items():
        assert urlsplit(url).port == compose["published"]["temporal-ui"], (
            f"{service} links the engine UI at {url}; it is published on "
            f"{compose['published']['temporal-ui']}")
    for service, url in compose["reach"]["OPENFACTORY_PANEL_URL"].items():
        assert urlsplit(url).port == compose["published"]["panel"], (service, url)
    # Inside the compose network a client dials the CONTAINER's port, whatever is published.
    for service, where in compose["reach"]["TEMPORAL_ADDRESS"].items():
        assert urlsplit(f"//{where}").port == compose["container"]["temporal"], (service, where)
    assert _after(compose["panel argv"], "--port") == compose["container"]["panel"]


def test_the_compose_file_publishes_the_definitions_ports_under_the_definitions_names():
    from openfactory.listeners import ENGINE, ENGINE_UI, PANEL

    raw = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    for service, listener in (("temporal", ENGINE), ("temporal-ui", ENGINE_UI), ("panel", PANEL)):
        mapping = str(raw[service]["ports"][0])
        assert f"${{{listener.port_var}:-{listener.default_port}}}:" in mapping, (
            f"{service} publishes {mapping}; the definition says `{listener.port_var}`, default "
            f"{listener.default_port}")
    assert _compose({})["container"]["temporal"] == ENGINE.default_port


def test_a_declared_UI_address_survives_compose(monkeypatch):
    """`OPENFACTORY_PANEL_URL` could be declared past compose and `TEMPORAL_UI_URL` could not: the
    file overwrote it, so a stack behind a proxy had engine links nobody could correct."""
    compose = _compose({"TEMPORAL_UI_URL": "https://engine.example"})

    assert set(compose["reach"]["TEMPORAL_UI_URL"].values()) == {"https://engine.example"}


# ── 7. one table: preflight and init read it, and no literal grows back ──────────────────────────

def test_preflight_reads_the_same_table():
    from openfactory import listeners, preflight

    assert preflight.PUBLISHED_PORTS == tuple(
        (one.name, one.port_var, one.default_port) for one in listeners.LISTENERS)


def _port_literals(source: str, ports: set[int]) -> list[tuple[int, str]]:
    """`(line, literal)` for every deployment port spelled in CODE — never in a docstring or a
    comment, which explain at length the very literals this forbids."""
    tree = ast.parse(source)
    prose = {id(node.value) for node in ast.walk(tree)
             if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
             and isinstance(node.value.value, str)}
    spelled = re.compile(r"(?<![\d.])(" + "|".join(str(p) for p in sorted(ports)) + r")(?!\d)")
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or id(node) in prose:
            continue
        value = node.value
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value in ports:
            found.append((node.lineno, repr(value)))
        elif isinstance(value, str) and spelled.search(value):
            found.append((node.lineno, value.strip()[:60]))
    return found


def test_the_literal_scan_can_FAIL():
    """The scan is pointed at the shapes this defect shipped in, and at what it must not flag."""
    ports = {7233, 8080, 8787}

    assert _port_literals('argv = ["--port", "7233", "--ui-port", "8080"]', ports) == [
        (1, "7233"), (1, "8080")]
    assert _port_literals("port: int = Option(8787)", ports) == [(1, "8787")]
    assert _port_literals('url = f"http://localhost:8787/p/{x}"', ports)
    assert _port_literals('"""The default was localhost:7233."""\nx = 1  # 8080', ports) == []
    assert _port_literals("timeout = 80800; build = '1.8080.2'", ports) == []


def test_no_deployment_port_is_spelled_outside_the_one_definition():
    from openfactory.listeners import LISTENERS

    ports = {one.default_port for one in LISTENERS}
    package = ROOT / "openfactory"
    spelled = []
    for path in sorted(package.rglob("*.py")):
        if path == package / "listeners.py":
            continue
        for line, literal in _port_literals(path.read_text(encoding="utf-8"), ports):
            spelled.append(f"{path.relative_to(ROOT)}:{line}: {literal}")

    assert not spelled, (
        "a deployment port is spelled outside `openfactory/listeners.py` — that is a second copy "
        "of an address, which agrees with the first only until somebody moves one. Ask the "
        "definition (`ENGINE`, `ENGINE_UI`, `PANEL`) instead:\n  " + "\n  ".join(spelled))
