"""S12 on a REAL daemon: on the one-machine door, S1 opens at `web--acme--12.preview.localhost`
through a panel that is a HOST PROCESS, its services published on this machine's loopback alone,
and its card says what a preview here can reach — measured, whichever way it falls (#265 slice 6;
the design's §7.2 and §11 slice 6's acceptance).

GATED like `tests/test_a_preview_starts_on_a_real_daemon.py`: it runs only where a Docker daemon
answers and the compose plugin is usable, and skips where a port S1's names derive is already taken
on this machine — never faked. The forge is the test's (the pull request is open; its branch lives
in the repository, as on `forge.local`); everything past it is what a started preview runs, each
step as an activity, and the panel is `openfactory serve` in a process of its own, reached the way
Chrome and Firefox reach `*.localhost`: at 127.0.0.1, with the preview's host in `Host:`.

WHAT IT MEASURES, AND HOW. The card's notes are the compose row's own probe (a throwaway container
on the unit's edge network). This test measures the same two things again FROM INSIDE THE EXPOSED
`web` CONTAINER — a request to a public address, and one to a listener this test opens on
127.0.0.1 through `host.docker.internal` — and requires the card to say what that container
found. Nothing is assumed about which way either falls: the card must agree with the container.
"""

from __future__ import annotations

import asyncio
import http.server
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx
import pytest

from openfactory import preview
from tests.one_live_preview import one_at_a_time

ROOT =Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "preview" / "s1" / "tree"
PR = "https://forge.local/acme/pull/12"
BRANCH = "openfactory/12"
SPAN = (42000, 42999)
#: The base images S1 builds from or pulls — removed afterwards only if this run brought them.
BASES = ("node:20-slim", "python:3.12-slim", "postgres:16")


def _docker_and_compose() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        daemon = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                                capture_output=True, timeout=20)
        plugin = subprocess.run(["docker", "compose", "version", "--short"], capture_output=True,
                                timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return daemon.returncode == 0 and plugin.returncode == 0


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not _docker_and_compose(),
                       reason="needs a Docker daemon and the compose plugin"),
]


@pytest.fixture(autouse=True)
def _the_daemon_is_taken_in_turns():
    """The live preview tests share `openfactory-pv-acme-12` on one daemon (`one_live_preview`)."""
    with one_at_a_time():
        yield


def _run(*argv: str) -> str:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=120).stdout


def _git(repo: Path, *args: str) -> None:
    ident = ["-c", "user.email=t@example.com", "-c", "user.name=t"]
    subprocess.run(["git", "-C", str(repo), *ident, *args], check=True, capture_output=True)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _answers(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _lan_address() -> str:
    """This machine's address on its outbound interface — a UDP `connect` sends nothing — or ""
    when it has none but the loopback."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            found = s.getsockname()[0]
    except OSError:
        return ""
    return "" if found.startswith("127.") else found


class _Forge:
    """The pull request is open; its branch lives in the repository itself."""

    def __init__(self, repo: Path):
        self.repo = repo

    def pr_for_head(self, head, *, repo=""):
        return PR if head == BRANCH else ""

    def pr_status(self, *, pr, repo=""):
        return "open"

    def push_remote(self):
        return str(self.repo)


def _browse(url: str, jar: dict[str, dict[str, str]], *, hops: int = 8) -> tuple[str, httpx.Response]:
    """Open `url` as a browser that sends every `*.localhost` to this machine does: connect to
    127.0.0.1 on the URL's port, name the URL's host in `Host:`, follow redirects, and keep each
    host's cookies to that host. Answers the last URL and its response."""
    for _ in range(hops):
        u = httpx.URL(url)
        cookies = jar.get(u.host, {})
        headers = {"host": f"{u.host}:{u.port}"}
        if cookies:
            headers["cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
        r = httpx.get(f"http://127.0.0.1:{u.port}{u.raw_path.decode()}", headers=headers,
                      follow_redirects=False, timeout=180)
        for set_cookie in r.headers.get_list("set-cookie"):
            name, _, rest = set_cookie.partition("=")
            jar.setdefault(u.host, {})[name.strip()] = rest.split(";", 1)[0]
        if r.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, r.headers["location"])
            continue
        return url, r
    raise AssertionError(f"more than {hops} redirects from {url}")


class _Token(http.server.BaseHTTPRequestHandler):
    token = secrets.token_hex(8)

    def do_GET(self):  # noqa: N802 — the stdlib's name
        self.send_response(200)
        self.end_headers()
        self.wfile.write(self.token.encode())

    def log_message(self, *args):
        pass


def _from_web(cp: str, url: str) -> str:
    """What the exposed `web` container gets for `url` — its own node, no tool added: the body's
    first 200 characters, or `unreached: <why>`."""
    script = ("const u=process.argv[1];const m=u.startsWith('https')?require('https'):"
              "require('http');const q=m.get(u,r=>{let b='';r.on('data',d=>b+=d);r.on('end',()=>"
              "{console.log('reached '+r.statusCode+' '+b.slice(0,200));process.exit(0)})});"
              "q.on('error',e=>{console.log('unreached: '+e.code);process.exit(0)});"
              "q.setTimeout(8000,()=>{console.log('unreached: timeout');process.exit(0)})")
    done = subprocess.run(["docker", "exec", f"{cp}-web-1", "node", "-e", script, url],
                          capture_output=True, text=True, timeout=60)
    return (done.stdout or done.stderr).strip()


def test_s1_opens_at_its_preview_host_through_a_host_process_panel(tmp_path, monkeypatch):
    pytest.importorskip("temporalio")
    from temporalio.testing import ActivityEnvironment

    from openfactory.adapters.preview.compose import ComposeRuntime
    from openfactory.contracts.project import Project
    from openfactory.preview import steps
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal import activities
    from openfactory.runtime.temporal.io import PreviewPlanInput, PreviewStepInput, PreviewUpInput

    derived = {s: preview.loopback_port(preview.host_label("acme", "12", s), SPAN)
               for s in ("web", "api")}
    if any(_answers(p) for p in derived.values()):
        pytest.skip(f"a port S1's names derive is already in use on this machine: {derived}")

    root = Path(os.path.realpath(tmp_path))
    repo = root / "repo"
    shutil.copytree(FIXTURE, repo)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "s1")
    _git(repo, "checkout", "-qb", BRANCH)
    (repo / "api" / "orders").mkdir()
    (repo / "api" / "orders" / "views.py").write_text("ORDERS = 'the change'\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "the change")
    _git(repo, "checkout", "-q", "main")
    work = root / "work"
    work.mkdir()
    panel_port = _free_port()
    # THE ONE-MACHINE DOOR, OPTED IN: the four lines `init` writes commented, uncommented.
    deployment = {
        "OPENFACTORY_OWN_WORK": "1",
        "OPENFACTORY_PREVIEW_RUNTIME": "compose",
        "OPENFACTORY_PREVIEW_REACH": "loopback",
        "OPENFACTORY_PREVIEW_PORTS": f"{SPAN[0]}-{SPAN[1]}",
        "OPENFACTORY_PREVIEW_DOMAIN": "preview.localhost",
        "OPENFACTORY_PREVIEW_SECRET": secrets.token_hex(16),
        "OPENFACTORY_PANEL_URL": f"http://localhost:{panel_port}",
        "OPENFACTORY_REGISTRY": str(root / "registry.yaml"),
        "OPENFACTORY_WORK_DIR": str(work),
        "OPENFACTORY_LOG_DIR": str(root / "logs"),
        "OPENFACTORY_METRICS_SINK": "sqlite",
        "OPENFACTORY_METRICS_DB": str(root / "metrics.db"),
    }
    for name, value in deployment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("OPENFACTORY_PREVIEW_DOCKER_CONFIG", raising=False)
    monkeypatch.delenv("OPENFACTORY_PANEL_CONTAINER", raising=False)
    ProjectRegistry().add(Project(name="acme", repo_path=str(repo)))
    preview.record(preview.Preview(project="acme", unit="12", cards=("12",),
                                   state=preview.OFFERED, pr_urls=(PR,),
                                   branches={PR: BRANCH}))
    monkeypatch.setattr(steps.World, "forge", lambda self, project: _Forge(repo))
    real_unit = activities._preview_unit

    def unit(inp):
        project, _ = real_unit(inp)
        return project, ComposeRuntime(reach="loopback", panel_container="", settle_seconds=5,
                                       start_timeout=inp.start_timeout_minutes * 60)

    monkeypatch.setattr(activities, "_preview_unit", unit)

    def act(fn, arg):
        return asyncio.run(ActivityEnvironment().run(fn, arg))

    # THE PANEL AS A HOST PROCESS: this branch's code (the checkout first on the path), the
    # deployment above, nothing of the person's own configuration, no panel token (a laptop's).
    panel_env = {**os.environ, **deployment, "HOME": str(root / "home"), "PYTHONPATH": str(ROOT),
                 "OPENFACTORY_PANEL_TOKEN": "", "OPENFACTORY_PANEL_TOKENS": "",
                 "OPENFACTORY_PRODUCT_TOKENS": ""}
    (root / "home").mkdir()
    before = set(_run("docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}").split())
    step = PreviewStepInput(project="acme", unit="12", runtime="compose", started_by="Ana",
                            start_timeout_minutes=15)
    cp = preview.compose_project("acme", "12")
    panel = subprocess.Popen([sys.executable, "-m", "openfactory.cli", "serve", "--port",
                              str(panel_port)], cwd=str(ROOT), env=panel_env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    listener = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Token)
    threading.Thread(target=listener.serve_forever, daemon=True).start()
    measured: dict[str, str] = {}
    try:
        got = act(activities.preview_materialise, step)
        assert got.ok, got.why
        planned = act(activities.preview_plan, PreviewPlanInput(step=step, layout=got.layout))
        assert planned.ok, planned.why
        assert planned.plan.loopback_ports == derived, "the ports are the names'"
        up = act(activities.preview_up, PreviewUpInput(step=step, plan=planned.plan))
        live = preview.latest("acme", "12")
        assert up.ok, f"{up.why}\n{(Path(live.log_dir) / 'build.log').read_text()[-2000:]}"
        assert live.state == preview.LIVE

        # ── published on the loopback, and only there ──
        for svc, inside in (("web", 3000), ("api", 8000)):
            bound = _run("docker", "port", f"{cp}-{svc}-1").split("\n")
            assert [b for b in bound if b] == [f"{inside}/tcp -> 127.0.0.1:{derived[svc]}"], bound
        lan = _lan_address()
        if lan:
            with pytest.raises(OSError):
                socket.create_connection((lan, derived["web"]), timeout=3).close()
            measured["lan"] = f"{lan}:{derived['web']} refused or unanswered"

        # ── the panel, a host process, serves the card and the preview ──
        deadline = time.monotonic() + 60
        while not _answers(panel_port):
            assert panel.poll() is None, panel.stdout.read().decode()[-2000:]
            assert time.monotonic() < deadline, "the panel never listened"
            time.sleep(0.5)
        card = httpx.get(f"http://127.0.0.1:{panel_port}/api/preview/acme/12",
                         headers={"host": f"localhost:{panel_port}"}, timeout=60).json()
        assert card["live"] is True, card
        web = next(s for s in card["services"] if s["name"] == "web")
        assert httpx.URL(web["url"]).host == "web--acme--12.preview.localhost"

        jar: dict[str, dict[str, str]] = {}
        where, page = _browse(web["url"], jar)
        assert httpx.URL(where).host == "web--acme--12.preview.localhost"
        assert httpx.URL(where).path == "/"
        assert page.status_code == 200, page.text
        assert page.text.strip() == (f"web: the api is at http://api--acme--12.preview.localhost:"
                                     f"{panel_port}/"), "web answered through the panel"
        assert set(jar) == {"web--acme--12.preview.localhost", "api--acme--12.preview.localhost"}, \
            "one click let the browser into both services"
        _, health = _browse(f"http://api--acme--12.preview.localhost:{panel_port}/health", jar)
        assert (health.status_code, health.text.strip()) == (200, "ok")

        # ── the key, on the loopback too ──
        _, keyless = _browse(f"http://web--acme--12.preview.localhost:{panel_port}/", {})
        assert keyless.status_code == 401, "the panel let a request without the key through"

        # ── what the card says this preview reaches, against the exposed container itself ──
        internet = _from_web(cp, "http://1.1.1.1/")
        mine = _from_web(cp, f"http://host.docker.internal:{listener.server_address[1]}/")
        measured["internet"], measured["loopback"] = internet, mine
        notes = " ".join(card["notes"])
        if internet.startswith("reached"):
            assert "this preview can reach the internet" in notes, (internet, notes)
        else:
            assert "did not reach the internet" in notes, (internet, notes)
        if mine.startswith("reached") and _Token.token in mine:
            assert "this machine's own loopback" in notes, (mine, notes)
        else:
            assert "this machine's own loopback" not in notes, (mine, notes)
        assert f"`web` at 127.0.0.1:{derived['web']}" in notes and "without the key" in notes

        assert act(activities.preview_watch, step) == "running"
        ending = step.model_copy(update={"why": "stopped by Ana"})
        act(activities.preview_logs, ending)
        act(activities.preview_down, ending)
        assert preview.latest("acme", "12").state == preview.ENDED
    finally:
        listener.shutdown()
        listener.server_close()
        panel.terminate()
        try:
            panel.wait(timeout=20)
        except subprocess.TimeoutExpired:
            panel.kill()
        ComposeRuntime(panel_container="").down(cp, str(work / cp))
        for image in BASES:
            if image not in before and image in _run("docker", "image", "ls", "--format",
                                                     "{{.Repository}}:{{.Tag}}").split():
                _run("docker", "image", "rm", image)
        print(f"\nS12 measured from inside `web`: {measured}")
    left = [line for what in ("ps -a", "volume ls")
            for line in _run("docker", *what.split(), "-q", "--filter",
                             f"label=com.docker.compose.project={cp}").split()]
    left += [n for n in _run("docker", "network", "ls", "--format", "{{.Name}}").split()
             if n.startswith(cp)]
    left += _run("docker", "ps", "-aq", "--filter", "label=openfactory.preview.probe").split()
    left += [i for i in _run("docker", "image", "ls", "--format",
                             "{{.Repository}}:{{.Tag}}").split() if i.startswith(cp)]
    assert not left, f"the preview left {left} on the daemon"
    assert not (work / cp).exists(), "the preview left its checkout behind"
    assert not any(_answers(p) for p in derived.values()), "a derived port is still published"
