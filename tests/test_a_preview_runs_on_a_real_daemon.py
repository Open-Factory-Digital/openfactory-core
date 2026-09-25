"""The S1 fixture comes up through `prove` on a REAL daemon, with nothing of the factory's in any
container or image, and leaves nothing behind; and two live units cannot resolve each other
(#265 slice 2; the design's §5.2, §8 "Secrets", §11 slice 2's acceptance).

THE ONE LIVE TEST OF THE COMPOSE ROW, gated: it runs only where a Docker daemon answers and the
compose plugin is usable — skipped anywhere else, never faked. Everything it proves is also held
against a faked daemon in `tests/test_the_compose_row_runs_what_was_admitted.py`; what only a daemon
can show is that the reduced environment, admission and the runtime TOGETHER keep a planted secret
out of every container's environment and every built image's history, that a one-shot `migrate`
does not fail a real stack, and that the edge networks really are separate.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from openfactory import preview
from openfactory.adapters.preview import compose

FIXTURE = Path(__file__).parent / "fixtures" / "preview" / "s1" / "tree"
PLANTED = "PLANTED-factory-secret-9031"


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


def _run(*argv: str) -> str:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=120).stdout


def _leftovers(cp: str) -> list[str]:
    return [line for what in ("ps -a", "network ls", "volume ls")
            for line in _run("docker", *what.split(), "-q", "--filter",
                             f"label=com.docker.compose.project={cp}").split()] + \
        [n for n in _run("docker", "network", "ls", "--format", "{{.Name}}").split()
         if n.startswith(cp)] + \
        [n for n in _run("docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}").split()
         if n.startswith(f"{cp}-")]


def test_the_s1_product_comes_up_through_prove_with_nothing_of_the_factory_in_it(
        tmp_path, monkeypatch):
    from openfactory.contracts.project import PreviewPolicy, Project
    from openfactory.preview.assemble import assemble
    from openfactory.preview.plan import Layout, Tree, Unit

    root = Path(os.path.realpath(tmp_path))
    repo = root / "repo"
    shutil.copytree(FIXTURE, repo)
    ident = ["-c", "user.email=t@example.com", "-c", "user.name=t"]
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], [*ident, "commit", "-qm", "s1"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    work = root / "work"
    work.mkdir()
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(root / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_WORK_DIR", str(work))
    monkeypatch.delenv("OPENFACTORY_PREVIEW_DOCKER_CONFIG", raising=False)
    # The factory's own credentials, and values for names the compose file itself reads
    # (`SECRET_KEY`, `SENTRY_DSN`) that the registry never listed.
    for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENFACTORY_BOT_TOKEN",
                 "OPENFACTORY_PREVIEW_SECRET", "SECRET_KEY", "SENTRY_DSN"):
        monkeypatch.setenv(name, f"{PLANTED}-{name}")

    project = Project(name="acme", repo_path=str(repo))
    cp = preview.compose_project("acme", compose.PROVE_TOKEN)
    seen: dict[str, str] = {}
    real = compose._host

    def before_the_down(argv, **kw):
        """What was running, read the instant before the proof takes it down."""
        if list(argv[:2]) == ["docker", "compose"] and "down" in argv and not seen:
            ids = _run("docker", "ps", "-aq", "--filter",
                       f"label=com.docker.compose.project={cp}").split()
            seen["env"] = _run("docker", "inspect", "--format", "{{json .Config.Env}}", *ids)
            seen["states"] = _run("docker", "ps", "-a", "--filter",
                                  f"label=com.docker.compose.project={cp}", "--format",
                                  '{{.Label "com.docker.compose.service"}}={{.Status}}')
            # Generated build tags survive on engines where Compose does not label the image.
            expected = [f"{cp}-{service}:latest" for service in ("web", "api", "migrate")]
            images = [name for name in expected if _run(
                "docker", "image", "inspect", "--format", "{{.Id}}", name).strip()]
            seen["images"] = " ".join(images)
            seen["history"] = "".join(_run("docker", "history", "--no-trunc", "--format",
                                           "{{.CreatedBy}}", i) for i in images)
            seen["inspect"] = "".join(_run("docker", "image", "inspect", i) for i in images)
            seen["compose.yml"] = (work / cp / "compose.yml").read_text()
        return real(argv, **kw)

    monkeypatch.setattr(compose, "_host", before_the_down)
    runtime = compose.ComposeRuntime(reach="network", panel_container="", settle_seconds=5)

    result = compose.prove_project(project, runtime)

    assert result.ok, f"{result.why}\n{Path(result.log_dir, 'build.log').read_text()[-2000:]}"
    assert result.health == {"web": "started", "api": "healthy"}
    assert "postgres" in result.images["db"]
    assert "migrate=Exited (0)" in seen["states"], (
        f"the one-shot did not run and finish: {seen['states']}")
    assert set(seen["images"].split()) == {
        f"{cp}-{service}:latest" for service in ("web", "api", "migrate")
    }, "the proof did not build all three S1 services"
    env = json.dumps(seen["env"])
    assert "SECRET_KEY=dev-only" in env, "the file's own default did not reach the container"
    for where in ("env", "history", "inspect", "compose.yml"):
        assert PLANTED not in seen[where], f"a factory secret reached the {where}"
    assert sorted(p.name for p in Path(result.log_dir).glob("*.log")) == [
        "api.log", "build.log", "db.log", "migrate.log", "web.log"]
    assert _leftovers(cp) == [], "the proof left something on the daemon"
    assert not (work / cp).exists(), "the proof left its checkout behind"

    # ── two live units: neither can resolve the other ──
    monkeypatch.setattr(compose, "_host", real)
    plans = []
    for token in ("12", "13"):
        wd = work / preview.compose_project("acme", token)
        (wd / "base" / "app").mkdir(parents=True)
        layout = Layout(workdir=str(wd), trees={"app": Tree(repo="acme/shop", dir="app",
                                                            base_commit="b" * 40)})
        unit = Unit(project="acme", kind="card", id=f"acme/shop#{token}", token=token)
        from openfactory.contracts.manifest import PreviewConfig

        plans.append(assemble(
            {"services": {"app": {"image": "alpine:3", "command": ["sleep", "300"]}}},
            cfg=PreviewConfig(compose=["compose.yaml"], expose={"app": 8000}), unit=unit,
            layout=layout, policy=PreviewPolicy(), expires_at=1_900_000_000, prove=True))
    live = compose.ComposeRuntime(reach="network", panel_container="", settle_seconds=0)
    try:
        for plan in plans:
            up = live.up(plan)
            assert up.ok, up.why
        mine = f"{plans[0].compose_project}-app-1"
        own = subprocess.run(["docker", "exec", mine, "getent", "hosts",
                              preview.host_label("acme", "12", "app")], capture_output=True)
        other = subprocess.run(["docker", "exec", mine, "getent", "hosts",
                                preview.host_label("acme", "13", "app")], capture_output=True)
        assert own.returncode == 0, "a unit cannot resolve its own exposed service"
        assert other.returncode != 0, "one unit resolved another's service: a network is shared"
    finally:
        for plan in plans:
            live.down(plan.compose_project, plan.workdir)
    for plan in plans:
        assert _leftovers(plan.compose_project) == []
