"""Every container whose PID 1 is one of our processes has an init that reaps orphans (#532).

PID 1 inherits every orphan in its PID namespace, and only an init reaps processes it did not
start. Python waits for the children it started and for nothing else, so on v0.5.0-rc.1 every
orphan in the worker and the panel stayed a zombie for the container's life: git's detached
auto-maintenance after each commit, fetch or merge, measured at about 7 a minute. A panel held
17,420 of them after 39 hours, against a `pids.max` of 17,435, could no longer start a thread,
and the floor then read the engine as unreachable. Nothing in the stack reported the count.

Where the class lives, and what holds each place:

  docker-compose.yml   every service that runs one of our images declares `init: true`
  the box              `docker run --init`: its PID 1 is `sleep`, and the image is the client's
  the images           the worker's and the sandbox's ENTRYPOINT is `tini -s --`, for a runtime
                       that starts them with no init at all — `-s` keeps it reaping as a
                       subreaper when the daemon's own init is PID 1 above it

THE CLI IMAGE IS NOT ASKED: it runs one command — `preflight`, `init` — and exits with it, as
`install.sh` runs it (`docker run --rm`), so whatever it orphans goes with the container. Its
compose service still declares `init: true`, because the rule there is about the image's owner,
not its lifetime, and a rule with no exception is one a reader can check by eye.
"""

from __future__ import annotations

import json
import pathlib

import pytest
import yaml

from openfactory.adapters.sandbox.container import ContainerSandbox

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "docker-compose.yml"

#: Our images, by the registry path the release publishes them under.
OURS = "ghcr.io/open-factory-digital/"

#: The init every image whose PID 1 is long-lived and ours starts as its ENTRYPOINT.
INIT = ["tini", "-s", "--"]


def _services() -> dict[str, dict]:
    return yaml.safe_load(COMPOSE.read_text())["services"]


def _ours() -> dict[str, dict]:
    return {name: svc for name, svc in _services().items()
            if str(svc.get("image", "")).startswith(OURS)}


# ── docker-compose.yml ──────────────────────────────────────────────────────────────────────────

def test_the_guard_sees_the_two_long_lived_services():
    """THE SCOPE IS ASSERTED, so a renamed image or a moved registry cannot empty it: a guard over
    no service passes for ever."""
    assert {"worker", "panel"} <= set(_ours()), sorted(_ours())


@pytest.mark.parametrize("name", sorted(_ours()))
def test_every_service_that_runs_one_of_our_images_declares_an_init(name):
    assert _ours()[name].get("init") is True, (
        f"the `{name}` service runs one of our images with no `init: true`: its PID 1 is our "
        f"process, which reaps no orphan, and every one stays a zombie until the container's "
        f"pids run out (#532)")


def test_the_panel_runs_the_worker_image_so_it_runs_the_worker_entrypoint():
    """The panel overrides only the COMMAND, so its process runs under the worker image's init —
    the property `test_the_long_lived_images_start_an_init` checks holds for both."""
    services = _services()
    assert services["panel"]["image"] == services["worker"]["image"]
    assert "entrypoint" not in services["panel"], "the panel would bypass the image's init"


# ── the box ─────────────────────────────────────────────────────────────────────────────────────

class _Daemon:
    """Records argv; every docker call succeeds."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args, timeout=None):
        self.calls.append(list(args))
        if args[:2] == ["docker", "inspect"]:
            return 1, "No such object"
        return 0, ""

    def run_cmd(self) -> list[str]:
        return next(a for a in self.calls if a[:2] == ["docker", "run"])


def test_the_box_is_started_with_an_init(monkeypatch):
    """Its PID 1 is `sleep`, and every command the agent and the gates run comes in through
    `docker exec`: what they orphan is adopted by `sleep`. The image is the client's (ADR-0037
    D1), so the init is the daemon's — and it must come before the image, where `docker run`
    reads its options."""
    import openfactory.adapters.sandbox.container as mod

    daemon = _Daemon()
    monkeypatch.setattr(mod, "_host", daemon)
    ContainerSandbox(image="client/box:1", project="acme").prepare(
        repo_path=ROOT, base_branch="main", branch="openfactory/1")

    argv = daemon.run_cmd()
    assert "--init" in argv, argv
    assert argv.index("--init") < argv.index("client/box:1"), argv


# ── the images ──────────────────────────────────────────────────────────────────────────────────

def _entrypoint(dockerfile: str) -> list[str]:
    """The ENTRYPOINT the image ends with — the last one in the file, as Docker reads it."""
    lines = [line for line in (ROOT / "docker" / dockerfile).read_text().splitlines()
             if line.startswith("ENTRYPOINT ")]
    assert lines, f"{dockerfile} declares no ENTRYPOINT"
    return json.loads(lines[-1].removeprefix("ENTRYPOINT "))


def _installs(dockerfile: str, package: str) -> bool:
    """Whether an `apt-get install` of the file names `package` — read across continued lines."""
    text = (ROOT / "docker" / dockerfile).read_text().replace("\\\n", " ")
    return any("apt-get install" in line and f" {package} " in f" {line} "
               for line in text.splitlines())


@pytest.mark.parametrize(("dockerfile", "installed_by"), [
    ("worker.Dockerfile", "worker.Dockerfile"),
    # built FROM the base image, which installs it
    ("sandbox.Dockerfile", "base-python.Dockerfile"),
])
def test_the_long_lived_images_start_an_init(dockerfile, installed_by):
    """For a runtime that starts the image with no init of its own — a cluster's default — the
    image carries one. Installed where the image gets its packages, so the ENTRYPOINT names a
    binary that is there."""
    assert _entrypoint(dockerfile) == INIT, dockerfile
    assert _installs(installed_by, "tini"), f"{installed_by} does not install tini"
