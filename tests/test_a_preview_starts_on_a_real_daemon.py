"""S1, started on demand, on a REAL daemon, through the workflow's own activities: an offered card
becomes `live` with the change in the service it touched and the current version in the one it
did not, is looked at, and is taken down leaving nothing behind (#265 slice 3; the design's §5.2
and §11 slice 3's acceptance).

GATED like `tests/test_a_preview_runs_on_a_real_daemon.py`: it runs only where a Docker daemon
answers and the compose plugin is usable — skipped anywhere else, never faked. What is faked is
the forge: the pull request's state is a fact the test states, and its branch is fetched from the
repository itself — what `forge.local` does. Every step past that is the one a started preview
runs: `preview_materialise → preview_plan → preview_up → preview_watch → preview_logs →
preview_down`, each executed as an activity (`ActivityEnvironment`), in the order the workflow
calls them.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from openfactory import preview

FIXTURE = Path(__file__).parent / "fixtures" / "preview" / "s1" / "tree"
PR = "https://forge.local/acme/pull/12"
BRANCH = "openfactory/12"


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


def _git(repo: Path, *args: str) -> None:
    ident = ["-c", "user.email=t@example.com", "-c", "user.name=t"]
    subprocess.run(["git", "-C", str(repo), *ident, *args], check=True, capture_output=True)


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


def test_an_offered_card_is_started_watched_and_ended_on_a_real_daemon(tmp_path, monkeypatch):
    pytest.importorskip("temporalio")
    from temporalio.testing import ActivityEnvironment

    from openfactory.adapters.preview.compose import ComposeRuntime
    from openfactory.contracts.project import Project
    from openfactory.preview import steps
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal import activities
    from openfactory.runtime.temporal.io import PreviewPlanInput, PreviewStepInput, PreviewUpInput

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
    for name, value in {"OPENFACTORY_REGISTRY": str(root / "registry.yaml"),
                        "OPENFACTORY_WORK_DIR": str(work),
                        "OPENFACTORY_LOG_DIR": str(root / "logs"),
                        "OPENFACTORY_METRICS_SINK": "sqlite",
                        "OPENFACTORY_METRICS_DB": str(root / "metrics.db"),
                        "OPENFACTORY_PREVIEW_DOMAIN": "preview.localhost"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("OPENFACTORY_PREVIEW_DOCKER_CONFIG", raising=False)
    ProjectRegistry().add(Project(name="acme", repo_path=str(repo)))
    preview.record(preview.Preview(project="acme", unit="12", cards=("12",),
                                   state=preview.OFFERED, pr_urls=(PR,),
                                   branches={PR: BRANCH}))

    # the deployment's runtime, with a short settle watch; the forge above
    monkeypatch.setattr(steps.World, "forge", lambda self, project: _Forge(repo))
    real_unit = activities._preview_unit

    def unit(inp):
        project, _ = real_unit(inp)
        return project, ComposeRuntime(reach="network", panel_container="", settle_seconds=5,
                                       start_timeout=inp.start_timeout_minutes * 60)

    monkeypatch.setattr(activities, "_preview_unit", unit)

    def act(fn, arg):
        return asyncio.run(ActivityEnvironment().run(fn, arg))

    step = PreviewStepInput(project="acme", unit="12", runtime="compose", started_by="Ana",
                            start_timeout_minutes=15)
    cp = preview.compose_project("acme", "12")
    try:
        got = act(activities.preview_materialise, step)
        assert got.ok, got.why
        assert preview.latest("acme", "12").state == preview.STARTING
        planned = act(activities.preview_plan, PreviewPlanInput(step=step, layout=got.layout))
        assert planned.ok, planned.why
        up = act(activities.preview_up, PreviewUpInput(step=step, plan=planned.plan))
        live = preview.latest("acme", "12")
        assert up.ok, f"{up.why}\n{(Path(live.log_dir) / 'build.log').read_text()[-2000:]}"

        assert live.state == preview.LIVE and live.started_by == "Ana"
        assert live.from_change == {"api": True, "web": False, "migrate": True, "db": False}
        assert live.health == {"api": "healthy", "web": "started"}
        head = _run("git", "-C", str(repo), "rev-parse", BRANCH).strip()
        assert live.heads == {PR: head}, "the head it was built from is what `stale` judges"
        assert "postgres" in live.images["db"]
        states = _run("docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={cp}",
                      "--format", '{{.Label "com.docker.compose.service"}}={{.Status}}')
        assert "migrate=Exited (0)" in states, f"the one-shot failed the stack: {states}"
        in_change = subprocess.run(["docker", "exec", f"{cp}-api-1", "cat",
                                    "/app/orders/views.py"], capture_output=True, text=True)
        assert "the change" in in_change.stdout, "the service the change touched runs the change"
        in_base = subprocess.run(["docker", "exec", f"{cp}-web-1", "ls", "/app/src"],
                                 capture_output=True, text=True)
        assert in_base.returncode == 0

        assert act(activities.preview_watch, step) == "running"
        ending = step.model_copy(update={"why": "stopped by Ana"})
        kept = act(activities.preview_logs, ending)
        assert {Path(p).name for p in kept} >= {"api.log", "web.log", "migrate.log", "db.log"}
        act(activities.preview_down, ending)
        ended = preview.latest("acme", "12")
        assert ended.state == preview.ENDED and ended.why == "stopped by Ana"
    finally:
        ComposeRuntime(panel_container="").down(cp, str(work / cp))
    left = _run("docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={cp}")
    assert not left.strip(), "the preview left containers on the daemon"
    assert not (work / cp).exists(), "the preview left its checkout behind"
