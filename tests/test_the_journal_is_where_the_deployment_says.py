"""Where a job's journal is written is the DEPLOYMENT's business, not the client checkout's (#67).

    def project_log_dir(project):
        return Path(project.repo_path).expanduser().parent / ".openfactory-logs" / project.name

The journal lands beside the client's repository, wherever that happens to be. Three things follow,
and only the first was noticed:

1. **The panel cannot tail a local job.** `docker-compose.yml` mounts `openfactory_logs:/root/.openfactory-logs`
   into the worker and the panel, and the panel reads from there. Those are the same directory only
   if `repo_path`'s parent is `/root`, which it never is — so the volume is empty and always would
   be, for every project on every deployment. Measured on the running stack: 0 files.

2. **A rate-limit-paused job is never resumed.** `scheduler.ready_to_resume` globs this directory
   for `*-events.jsonl` to find jobs whose backoff has elapsed. Point it at a directory that does
   not exist and it returns `[]` for ever — the pause becomes permanent, silently, which is the
   failure mode this platform is built to not have.

3. **A clone URL produces nonsense.** `repo_path` is documented as "local path or clone URL", and
   `Path("https://github.com/o/n.git").parent` is `https:/github.com/o`. So a URL-registered
   project writes its journal into a directory literally named `https:`.

THE INPUT WAS ALWAYS WRONG. `repo_path` describes where the CLIENT's code is; the journal is the
DEPLOYMENT's operational record, with the same lifetime as the registry and the metrics database —
both of which already live under `/var/lib/openfactory` because they are the installation's, not the
client's. `OPENFACTORY_LOG_DIR` puts it with them.

DEFAULTING TO TODAY'S BEHAVIOUR IS DELIBERATE. Unset means beside the repo, exactly as now, so no
deployed installation moves and no journal in flight is orphaned. Compose sets the variable; that
is the whole migration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openfactory.contracts.project import Project
from openfactory.paths import events_file, project_log_dir


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("OPENFACTORY_LOG_DIR", raising=False)


def _project(repo_path="/srv/acme"):
    return Project(name="acme", repo_path=repo_path)


# ── the deployment decides ──────────────────────────────────────────────────────────────────────

def test_the_log_dir_is_configurable(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path))

    assert project_log_dir(_project()) == tmp_path / "acme"


def test_the_project_still_gets_its_own_subdirectory(monkeypatch, tmp_path):
    """Two clients' journals must not mix — the subdirectory is what keeps them apart, and it is
    the property most easily lost when a path is made configurable."""
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path))

    a = project_log_dir(Project(name="acme", repo_path="/srv/a"))
    b = project_log_dir(Project(name="globex", repo_path="/srv/b"))

    assert a != b and a.parent == b.parent


def test_UNSET_and_a_clone_url_still_never_produces_a_directory_named_https(monkeypatch):
    """THE HALF THAT WAS LEFT (found as debris in the repository root, 2026-08-14). The guard
    below asserted the configured case, where the URL cannot reach the path at all — so the one
    combination that actually wrote `./https:/github.com/o/...` was never asserted: env unset,
    project registered by clone URL, journal written relative to whatever the working directory
    happened to be. "Unset keeps today's behaviour" has nothing to keep here; there was no
    working behaviour to preserve."""
    monkeypatch.delenv("OPENFACTORY_LOG_DIR", raising=False)

    path = project_log_dir(Project(name="acme", repo_path="https://github.com/o/n.git"))

    assert "https:" not in str(path), path
    assert path.is_absolute(), (
        f"the journal lands relative to the working directory: {path}")
    assert path.name == "acme", "the per-project subdirectory was lost"


def test_UNSET_and_a_local_checkout_is_unchanged(monkeypatch):
    """The migration that must not happen: a deployment with a checkout keeps its journals
    exactly where they are."""
    monkeypatch.delenv("OPENFACTORY_LOG_DIR", raising=False)

    path = project_log_dir(Project(name="acme", repo_path="/srv/acme"))

    assert path == Path("/srv") / ".openfactory-logs" / "acme"


def test_a_clone_url_no_longer_produces_a_directory_named_https(monkeypatch, tmp_path):
    """`repo_path` is documented as "local path or clone URL"; the URL half made
    `https:/github.com/o/.openfactory-logs/acme`."""
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path))

    path = project_log_dir(Project(name="acme", repo_path="https://github.com/o/n.git"))

    assert "https:" not in str(path), path
    assert path == tmp_path / "acme"


def test_unset_keeps_todays_behaviour_exactly():
    """Every deployment that exists right now. A journal in flight must not be orphaned by this
    change, and the pilot must not move."""
    assert project_log_dir(_project("/srv/acme")) == \
        __import__("pathlib").Path("/srv/.openfactory-logs/acme")


def test_events_file_follows(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path))

    assert events_file(_project(), "42").parent == tmp_path / "acme"


# ── the consequence that is not about the panel ─────────────────────────────────────────────────

def test_a_paused_job_is_found_where_the_deployment_writes(monkeypatch, tmp_path):
    """`ready_to_resume` globs the log dir. Pointed at a directory that does not exist it returns
    [] for ever, so a rate-limit pause becomes permanent — silently."""
    import json
    import time
    from datetime import UTC, datetime, timedelta

    from openfactory.scheduler import ready_to_resume

    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path))
    project = _project("https://github.com/o/n.git")   # the shape that produced `https:/…`
    journal = project_log_dir(project)
    journal.mkdir(parents=True)
    # `retry_at` is an ISO string, not an epoch — the scheduler parses it with fromisoformat.
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    (journal / "7-events.jsonl").write_text("\n".join(json.dumps(e) for e in [
        {"ts": "2026-08-02T00:00:00+00:00", "kind": "state", "message": "paused",
         "data": {"state": "paused"}},
        {"ts": "2026-08-02T00:00:01+00:00", "kind": "warning", "message": "rate limited",
         "data": {"retry_at": past}},
    ]))

    assert ready_to_resume(project, time.time()) == ["7"], (
        "a paused job was not found, so its backoff never elapses and the pause is permanent"
    )


# ── the compose file must mount what the code writes ────────────────────────────────────────────

def test_compose_mounts_the_directory_it_configures():
    """The panel reads a volume and the worker writes a path, and NOTHING connected them — the
    comment on the mount said it was "shared with the panel so it tails the local file instead of
    reaching for CloudWatch", which was true of the intent and false of the paths."""
    import pathlib

    import yaml

    root = pathlib.Path(__file__).resolve().parent.parent
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    services = compose["services"]

    for name in ("worker", "panel"):
        env = services[name].get("environment") or {}
        configured = env.get("OPENFACTORY_LOG_DIR")
        assert configured, f"{name} does not configure OPENFACTORY_LOG_DIR, so it uses the repo-relative " \
                           "default and the mount below is decorative"
        mounts = [v.split(":")[1] for v in services[name].get("volumes", []) if ":" in v]
        assert configured in mounts, (
            f"{name} configures OPENFACTORY_LOG_DIR={configured} and mounts {mounts} — the journal would "
            "be written inside the container and lost on restart"
        )

    worker_env = (services["worker"].get("environment") or {}).get("OPENFACTORY_LOG_DIR")
    panel_env = (services["panel"].get("environment") or {}).get("OPENFACTORY_LOG_DIR")
    assert worker_env == panel_env, (
        f"the worker writes to {worker_env} and the panel reads {panel_env}"
    )


def test_the_unset_url_fallback_follows_the_registry_this_process_drives(monkeypatch, tmp_path):
    """Not a constant, and not somebody's home: the journals of a URL-registered project land
    beside the registry actually in use, so a deployment (or a test) that redirects one
    redirects the other."""
    monkeypatch.delenv("OPENFACTORY_LOG_DIR", raising=False)
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "reg" / "registry.yaml"))

    path = project_log_dir(Project(name="acme", repo_path="https://github.com/o/n.git"))

    assert path == tmp_path / "reg" / "logs" / "acme", path
