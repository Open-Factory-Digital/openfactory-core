"""The built-in `compose` preview runtime runs what admission passed, with nothing of the factory's
in reach, and takes it down again (#265 slice 2; ADR-0050 D4, D7, D8, D10; the design's §5.2).

What these tests hold, against a FAKED DAEMON (every docker call goes through `compose._host`, the
one seam), in the order it protects something:

- THE REDUCED ENVIRONMENT. The compose process sees `PATH`, a `HOME`/`TMPDIR` inside the unit, the
  daemon's own `DOCKER_*`, the preview pull config, the preview's URLs and the values of exactly the
  names the registry listed — never the harness credential, the forge token or the panel's key.
- ONE EDGE NETWORK PER UNIT, the panel connected by the worker, disconnected at `down`: two units
  can never resolve each other, because no network is shared.
- READINESS BY `ps`, NEVER `up --wait`: a one-shot that ran and finished is not a failed stack; a
  non-zero exit is the failure, named with its last lines; an exposed service with a healthcheck is
  ready only when healthy; one that dies while settling is the failure.
- LOGS BEFORE ANY DOWN, and a down that deletes only a work directory this runtime made.
- A PLAN ADMISSION WOULD REFUSE IS NEVER RUN, and a proof never runs a change.
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
from openfactory.adapters.preview.compose import ComposeRuntime, Ran
from openfactory.preview.assemble import assemble
from openfactory.preview.plan import PreviewPlan, Unit
from tests.test_the_shape_is_read_and_admitted import (
    POLICY,
    S1_CFG,
    _canonical,
    _diff,
    _layout,
    _ok,
    _plan,
    _workdir,
)

#: What a planted factory secret looks like wherever it could leak: env, argv, a file on disk.
PLANTED = "PLANTED-factory-secret-4417"
_REAL_HOST = compose._host


# ── the faked daemon ─────────────────────────────────────────────────────────────────────────────


class Daemon:
    """A docker daemon and compose plugin, as far as the row can tell. Records every call with the
    environment it was given; answers `ps` from a script of states per service (one entry per
    poll, the last repeating); runs git for real."""

    def __init__(self, *, states=None, up=None, exec_=None, containers=None, shared=True):
        self.calls: list[tuple[list[str], dict | None]] = []
        self.states = states or {
            "web": [("running", "", 0)], "api": [("running", "healthy", 0)],
            "migrate": [("exited", "", 0)], "db": [("running", "healthy", 0)]}
        self.polls = 0
        self.up = up or Ran(0, "", " Container api  Started\n")
        self.exec_ = exec_ or (lambda svc, argv: Ran(0, "", ""))
        self.containers = containers or []
        self.shared = shared

    # which compose subcommand an argv is
    @staticmethod
    def sub(argv):
        return next((a for a in argv[2:] if a in ("up", "ps", "logs", "exec", "down", "version",
                                                   "config")), "")

    def argvs(self, what: str = "") -> list[list[str]]:
        return [a for a, _ in self.calls if what in " ".join(a)]

    def state(self, svc):
        seq = self.states.get(svc) or [("running", "", 0)]
        return seq[min(self.polls, len(seq) - 1)]

    def __call__(self, argv, *, env=None, timeout=120, input=None):
        argv = list(argv)
        self.calls.append((argv, dict(env) if env is not None else None))
        if argv[0] == "git":
            return _REAL_HOST(argv, env=env, timeout=timeout, input=input)
        if argv[:2] == ["docker", "compose"]:
            sub = self.sub(argv)
            cp = argv[argv.index("-p") + 1] if "-p" in argv else ""
            if sub == "up":
                one_shots = [s for s, seq in self.states.items()
                             if seq[-1][0] == "exited" and seq[-1][2] == 0]
                if "--wait" in argv and one_shots:
                    # measured: `up --wait` exits 1 the moment a one-shot exits 0
                    return Ran(1, "", f'service "{one_shots[0]}" didn\'t complete successfully: '
                                      f"exit 0")
                return self.up
            if sub == "ps":
                rows = [json.dumps({"Service": s, "State": self.state(s)[0],
                                    "Health": self.state(s)[1], "ExitCode": self.state(s)[2],
                                    "Name": f"{cp}-{s}-1"}) for s in self.states]
                self.polls += 1
                return Ran(0, "\n".join(rows), "")
            if sub == "logs":
                return Ran(0, f"{argv[-1]}-1  | the last line {argv[-1]} said\n", "")
            if sub == "exec":
                at = argv.index("-T")
                return self.exec_(argv[at + 1], argv[at + 2:])
            if sub == "down":
                return Ran(0, "", f" Container {cp}-api-1  Removed\n Volume {cp}_pgdata  Removed\n")
            if sub == "version":
                return Ran(0, "2.32.4", "")
            return Ran(0, "", "")
        if argv[:3] == ["docker", "image", "inspect"]:
            return Ran(0, '["postgres@sha256:feedface"]', "")
        if argv[:3] == ["docker", "ps", "-a"]:
            want = [f.split("=", 1)[1] for f in argv if f.startswith("label=com.docker.compose.")]
            rows = [c for c in self.containers if not want or c["cp"] == want[0].split("=")[-1]]
            return Ran(0, "\n".join("\t".join(c[k] for k in compose._PS_FIELDS) for c in rows), "")
        if argv[:2] == ["docker", "ps"]:   # without -a: the running ones only
            rows = [c for c in self.containers if c["state"] == "running"]
            return Ran(0, "\n".join("\t".join(c[k] for k in compose._PS_FIELDS) for c in rows), "")
        if argv[:2] == ["docker", "version"]:
            return Ran(0, "29.1.3", "")
        if argv[:2] == ["docker", "inspect"]:
            return Ran(0, "true\n", "")
        if argv[:2] == ["docker", "run"] and "cat" in argv:
            if not self.shared:
                return Ran(1, "", "cat: can't open '/w/x': No such file or directory")
            root = argv[argv.index("-v") + 1].split(":", 1)[0]
            return Ran(0, Path(root, argv[-1].removeprefix("/w/")).read_text(), "")
        return Ran(0, "", "")


def container(cp, service, state="running", *, project="acme", unit="12", exposed="1",
              expires="1900000000", created="2026-09-24 01:13:10 +0000 UTC"):
    return {"name": f"{cp}-{service}-1", "state": state, "status": state, "cp": cp,
            "service": service, "project": project, "unit": unit, "expires": expires,
            "exposed": exposed, "created": created}


@pytest.fixture
def root(tmp_path, monkeypatch):
    """The work root: `OPENFACTORY_WORK_DIR`, so the plan's work directory is one this runtime
    made — and a log root of the test's own."""
    real = Path(os.path.realpath(tmp_path))
    monkeypatch.setenv("OPENFACTORY_WORK_DIR", str(real))
    monkeypatch.setenv("OPENFACTORY_PREVIEW_DOCKER_CONFIG", str(real / "docker-config"))
    return real


@pytest.fixture
def s1(root, monkeypatch) -> PreviewPlan:
    monkeypatch.setenv("ACME_PV_DATABASE_URL", "postgres://preview@db.preview:5432/shop")
    wd = _workdir(root, "s1")
    return _ok(_plan(_canonical("s1", wd), S1_CFG, _layout(wd, _diff("s1"))))


def _runtime(**kw) -> ComposeRuntime:
    kw.setdefault("panel_container", "openfactory-panel")
    kw.setdefault("reach", "network")
    kw.setdefault("settle_seconds", 0)
    kw.setdefault("poll_seconds", 0)
    kw.setdefault("start_timeout", 60)
    clock = {"t": 0.0}

    def tick(seconds):
        clock["t"] += max(seconds, 1.0)

    return ComposeRuntime(clock=lambda: clock["t"], sleep=tick, **kw)


def _daemon(monkeypatch, **kw) -> Daemon:
    daemon = Daemon(**kw)
    monkeypatch.setattr(compose, "_host", daemon)
    return daemon


# ── the reduced environment ─────────────────────────────────────────────────────────────────────

#: Every name the compose process may be handed for S1 — derived from the plan, never widened.
def _allowed(plan: PreviewPlan) -> set[str]:
    from openfactory.preview.assemble import url_var

    names = {"PATH", "HOME", "TMPDIR", "DOCKER_HOST", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY",
             "DOCKER_CONFIG"}
    for svc in plan.expose:
        names |= {f"OPENFACTORY_PREVIEW_URL_{url_var(svc)}",
                  f"OPENFACTORY_PREVIEW_INTERNAL_URL_{url_var(svc)}"}
    for table in (plan.env_names, plan.build_arg_names):
        for names_of in table.values():
            names |= set(names_of.values())
    return names


def _plant(monkeypatch):
    """The factory's own credentials in the worker's environment — and a value for a name the
    compose file reads (`SECRET_KEY`) that the registry never listed."""
    for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENFACTORY_BOT_TOKEN",
                 "GH_TOKEN", "OPENFACTORY_PREVIEW_SECRET", "OPENFACTORY_PANEL_TOKEN",
                 "AZURE_DEVOPS_PAT", "SECRET_KEY", "COMPOSE_PROJECT_NAME"):
        monkeypatch.setenv(name, f"{PLANTED}-{name}")


def test_the_compose_process_sees_only_the_reduced_environment(s1, monkeypatch):
    _plant(monkeypatch)
    daemon = _daemon(monkeypatch)

    assert _runtime().up(s1).ok

    docker = [(argv, env) for argv, env in daemon.calls if argv[0] == "docker"]
    assert docker, "the row made no docker call at all"
    up = next(env for argv, env in docker if Daemon.sub(argv) == "up")
    assert set(up) <= _allowed(s1), f"the compose process was handed {sorted(set(up) - _allowed(s1))}"
    assert up["ACME_PV_DATABASE_URL"] == "postgres://preview@db.preview:5432/shop", (
        "a name the registry listed must reach the process that interpolates `${...}`")
    assert up["HOME"] == f"{s1.workdir}/home" and up["DOCKER_CONFIG"].endswith("docker-config")
    for argv, env in docker:
        assert env is not None, f"`{' '.join(argv[:4])}` ran with the worker's whole environment"
        leaked = [k for k, v in env.items() if PLANTED in v]
        assert not leaked, f"`{' '.join(argv[:4])}` was handed the factory's {leaked}"
        assert PLANTED not in " ".join(argv)


def test_no_value_lands_on_disk_or_in_an_argument_only_names(s1, monkeypatch):
    _plant(monkeypatch)
    daemon = _daemon(monkeypatch)

    _runtime().up(s1)

    written = (Path(s1.workdir) / "compose.yml").read_text()
    assert "${ACME_PV_DATABASE_URL}" in written
    assert "db.preview" not in written and PLANTED not in written
    for path in Path(s1.workdir).rglob("*"):
        if path.is_file():
            assert PLANTED not in path.read_text(errors="replace"), path
    assert not any("db.preview" in " ".join(a) for a, _ in daemon.calls)


def test_a_name_the_registry_could_never_admit_is_not_handed_over_even_when_a_plan_names_it(
        s1, monkeypatch):
    """The registry refuses the factory's own credentials at load; a plan built some other way
    that names one anyway still does not get its value."""
    _plant(monkeypatch)
    forged = s1.model_copy(update={"env_names": {**s1.env_names,
                                                 "api": {"KEY": "ANTHROPIC_API_KEY",
                                                         "T": "OPENFACTORY_PREVIEW_SECRET"}}})

    env = compose.reduced_env(forged)

    assert "ANTHROPIC_API_KEY" not in env and "OPENFACTORY_PREVIEW_SECRET" not in env
    assert not any(PLANTED in v for v in env.values())


def test_the_preview_urls_are_what_the_plan_says(s1):
    env = compose.reduced_env(s1)
    assert env["OPENFACTORY_PREVIEW_URL_API"] == s1.urls["api"]
    assert env["OPENFACTORY_PREVIEW_INTERNAL_URL_WEB"] == "http://web:3000"


# ── readiness: `ps`, never `--wait` ─────────────────────────────────────────────────────────────


def test_a_one_shot_that_ran_and_finished_does_not_fail_the_stack(s1, monkeypatch):
    daemon = _daemon(monkeypatch)

    up = _runtime().up(s1)

    assert up.ok, up.why
    assert up.health == {"web": "started", "api": "healthy"}
    assert up.services == {"web": 3000, "api": 8000}
    assert not any("--wait" in a for a, _ in daemon.calls), "readiness was asked of `up --wait`"
    assert up.images == {"db": up.images["db"]} and "postgres@sha256:feedface" in up.images["db"]


def test_an_exposed_service_with_a_healthcheck_is_ready_only_once_healthy(s1, monkeypatch):
    daemon = _daemon(monkeypatch, states={
        "web": [("running", "", 0)], "api": [("running", "starting", 0)] * 3
        + [("running", "healthy", 0)], "migrate": [("exited", "", 0)],
        "db": [("running", "healthy", 0)]})

    up = _runtime().up(s1)

    assert up.ok and up.health["api"] == "healthy"
    assert daemon.polls >= 4, "the row called a starting service ready"


def test_a_healthcheck_that_never_passes_is_named_at_the_deadline(s1, monkeypatch):
    _daemon(monkeypatch, states={"web": [("running", "", 0)], "api": [("running", "unhealthy", 0)],
                                 "migrate": [("exited", "", 0)], "db": [("running", "healthy", 0)]})

    up = _runtime(start_timeout=10).up(s1)

    assert not up.ok and "`api` (unhealthy) did not become ready" in up.why


def test_a_non_zero_exit_is_the_failure_named_with_its_last_lines(s1, monkeypatch):
    _daemon(monkeypatch, states={"web": [("running", "", 0)], "api": [("running", "healthy", 0)],
                                 "migrate": [("exited", "", 3)], "db": [("running", "healthy", 0)]})

    up = _runtime().up(s1)

    assert not up.ok
    assert up.why.startswith("`migrate` exited with code 3")
    assert "the last line migrate said" in up.why


def test_an_exposed_service_that_stops_while_settling_is_the_failure(s1, monkeypatch):
    _daemon(monkeypatch, states={
        "web": [("running", "", 0), ("running", "", 0), ("exited", "", 0)],
        "api": [("running", "healthy", 0)], "migrate": [("exited", "", 0)],
        "db": [("running", "healthy", 0)]})

    up = _runtime(settle_seconds=30).up(s1)

    assert not up.ok and "`web` stopped within a minute of starting" in up.why


# ── the data step ────────────────────────────────────────────────────────────────────────────────


def test_the_data_step_runs_in_a_login_shell_then_falls_back_to_bin_sh(s1, monkeypatch):
    seen = []

    def exec_(svc, argv):
        seen.append((svc, argv))
        if argv[0] == "sh":
            return Ran(126, "", 'OCI runtime exec failed: exec: "sh": executable file not found')
        return Ran(0, "", "")

    _daemon(monkeypatch, exec_=exec_)

    assert _runtime().up(s1).ok
    assert seen == [("api", ["sh", "-lc", "python manage.py loaddata demo"]),
                    ("api", ["/bin/sh", "-c", "python manage.py loaddata demo"])]


def test_an_image_with_no_shell_is_named_and_a_list_runs_as_arguments(s1, monkeypatch):
    _daemon(monkeypatch, exec_=lambda svc, argv: Ran(
        126, "", f'exec: "{argv[0]}": executable file not found in $PATH'))

    up = _runtime().up(s1)
    assert not up.ok
    assert up.why == ("`api` has no `sh` to run its data command in — declare `data:` as a list "
                      "of arguments.")

    seen = []
    _daemon(monkeypatch, exec_=lambda svc, argv: seen.append(argv) or Ran(0, "", ""))
    as_list = s1.model_copy(update={"data": (("api", ["/app/seed", "--demo"]),)})
    assert _runtime().up(as_list).ok and seen == [["/app/seed", "--demo"]]


def test_a_failing_data_step_is_said_with_its_last_lines(s1, monkeypatch):
    _daemon(monkeypatch, exec_=lambda svc, argv: Ran(2, "", "loaddata: no fixture named demo"))

    up = _runtime().up(s1)

    assert not up.ok and "the data step of `api` failed (exit 2)" in up.why
    assert "no fixture named demo" in up.why


def test_an_unauthorized_pull_names_the_login_that_fixes_it(s1, monkeypatch):
    doc = json.loads(json.dumps(s1.doc))
    doc["services"]["db"]["image"] = "ghcr.io/acme/db:latest"
    private = s1.model_copy(update={"doc": doc})
    _daemon(monkeypatch, up=Ran(1, "", "Error response from daemon: Head "
                                       "\"https://ghcr.io/v2/acme/db/manifests/latest\": "
                                       "unauthorized — ghcr.io/acme/db:latest"))

    up = _runtime().up(private)

    assert up.why == ("`ghcr.io/acme/db:latest` could not be pulled — run `openfactory preview "
                      "login ghcr.io` on the deployment, or make the image public.")


# ── networks: one edge per unit ──────────────────────────────────────────────────────────────────


def test_each_unit_has_its_own_edge_network_and_the_panel_joins_each(root, monkeypatch):
    monkeypatch.setenv("ACME_PV_DATABASE_URL", "x")
    plans = []
    for token in ("12", "13"):
        wd = str(root / preview.compose_project("acme", token))
        for side in ("base", "change"):
            shutil.copytree(Path(__file__).parent / "fixtures" / "preview" / "s1" / "tree",
                            f"{wd}/{side}/app")
        unit = Unit(project="acme", kind="card", id=f"acme/shop#{token}", token=token)
        plans.append(_ok(assemble(_canonical("s1", wd), cfg=S1_CFG, unit=unit,
                                  layout=_layout(wd, _diff("s1")), policy=POLICY,
                                  domain="preview.example.com", expires_at=1_900_000_000)))
    daemon = _daemon(monkeypatch)

    for plan in plans:
        assert _runtime().up(plan).ok

    created = [a[-1] for a in daemon.argvs("network create")]
    joined = [a[-2:] for a in daemon.argvs("network connect")]
    assert created == ["openfactory-pv-acme-12-edge", "openfactory-pv-acme-13-edge"]
    assert all("--internal" in a for a in daemon.argvs("network create"))
    assert joined == [[e, "openfactory-panel"] for e in created]
    for plan, edge in zip(plans, created, strict=True):
        assert plan.doc["networks"]["edge"] == {"name": edge, "external": True}
        assert plan.edge_network == edge == compose.edge_of(plan.compose_project)
    assert len(set(created)) == 2, "two units share a network, so each can resolve the other"


def test_down_disconnects_the_panel_and_removes_only_this_units_edge(s1, monkeypatch):
    daemon = _daemon(monkeypatch)
    _runtime().up(s1)

    removed = _runtime().down(s1.compose_project, s1.workdir)

    assert daemon.argvs("network disconnect")[-1][-2:] == ["openfactory-pv-acme-12-edge",
                                                           "openfactory-panel"]
    assert daemon.argvs("network rm")[-1][-1] == "openfactory-pv-acme-12-edge"
    down = daemon.argvs("down")[-1]
    assert down[-4:] == ["-v", "--rmi", "local", "--remove-orphans"]
    assert "Network openfactory-pv-acme-12-edge" in removed
    assert f"the work directory {s1.workdir}" in removed and not Path(s1.workdir).exists()


# ── what `down` may delete ───────────────────────────────────────────────────────────────────────


def test_down_leaves_a_directory_this_runtime_did_not_make(root, tmp_path_factory, monkeypatch):
    _daemon(monkeypatch)
    elsewhere = Path(os.path.realpath(tmp_path_factory.mktemp("elsewhere"))) / \
        "openfactory-pv-acme-12"
    elsewhere.mkdir()
    (elsewhere / "precious").write_text("keep me")
    linked = root / "openfactory-pv-acme-13"
    linked.symlink_to(elsewhere)

    compose.ComposeRuntime(panel_container="").down("openfactory-pv-acme-12", str(elsewhere))
    compose.ComposeRuntime(panel_container="").down("openfactory-pv-acme-13", str(linked))

    assert (elsewhere / "precious").read_text() == "keep me"
    assert linked.is_symlink()
    assert not compose.workdir_is_ours(str(elsewhere)) and not compose.workdir_is_ours(str(linked))


def test_down_of_a_project_that_is_not_a_preview_touches_nothing(monkeypatch):
    daemon = _daemon(monkeypatch)

    assert _runtime().down("openfactory", "/var/lib/openfactory") == []
    assert daemon.calls == []


def test_residue_a_container_left_owned_by_root_is_removed_through_the_daemon(s1, monkeypatch):
    daemon = _daemon(monkeypatch)
    real_rmtree = compose.shutil.rmtree
    attempts = []

    def stubborn(path, ignore_errors=False):
        attempts.append(path)
        if len(attempts) > 1:
            real_rmtree(path, ignore_errors=ignore_errors)

    monkeypatch.setattr(compose.shutil, "rmtree", stubborn)

    removed = compose._remove_workdir(s1.workdir)

    run = daemon.argvs("docker run")[-1]
    assert run[:5] == ["docker", "run", "--rm", "-v", f"{s1.workdir}:/w"]
    assert removed == [f"the work directory {s1.workdir}"]


# ── what is never run ────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("cut, said", [
    (lambda d: d["services"]["api"].update(privileged=True), "`api` carries `privileged:`"),
    (lambda d: d["volumes"]["pgdata"].update(name="openfactory_openfactory_state"),
     "the volume `pgdata` is not named"),
    (lambda d: d["services"]["web"].update(cap_drop=[]), "`web` keeps capabilities"),
    (lambda d: d["networks"].update(host={"name": "host", "external": True}),
     "the network `host` is neither"),
    (lambda d: d["services"]["web"]["volumes"][0].update(source="/var/run/docker.sock"),
     "`web` mounts `/var/run/docker.sock`"),
])
def test_a_plan_admission_would_refuse_is_never_run(s1, monkeypatch, cut, said):
    daemon = _daemon(monkeypatch)
    doc = json.loads(json.dumps(s1.doc))
    cut(doc)

    up = _runtime().up(s1.model_copy(update={"doc": doc}))

    assert not up.ok and up.why.startswith("refused before anything ran")
    assert said in up.why
    assert daemon.calls == [], "the row ran something before refusing"


def test_prove_keeps_the_logs_before_it_takes_the_stack_down(root, monkeypatch):
    wd = _workdir(root, "s1", change=False)
    base_only = _ok(_plan(_canonical("s1", wd), S1_CFG, _layout(wd, change=False), prove=True))
    daemon = _daemon(monkeypatch, containers=[
        container(base_only.compose_project, s) for s in ("web", "api", "migrate", "db")])

    up = _runtime().prove(base_only)

    assert up.ok, up.why
    order = [Daemon.sub(a) for a, _ in daemon.calls if a[:2] == ["docker", "compose"]]
    assert "logs" in order and "down" in order
    assert max(i for i, s in enumerate(order) if s == "logs") < order.index("down"), (
        f"the stack was taken down before its logs were kept: {order}")
    kept = sorted(p.name for p in Path(up.log_dir).glob("*.log"))
    assert kept == ["api.log", "build.log", "db.log", "migrate.log", "web.log"]
    assert daemon.argvs("network connect") == [], "a proof connected the panel"
    assert not Path(wd).exists(), "the proof left its checkout behind"


def test_a_proof_never_runs_a_change(s1, monkeypatch):
    daemon = _daemon(monkeypatch)

    up = _runtime().prove(s1)

    assert not up.ok and "a proof runs the base product only" in up.why
    assert daemon.calls == []


# ── reading what runs ────────────────────────────────────────────────────────────────────────────


def test_running_reads_exited_stacks_too_and_groups_them_by_project(monkeypatch):
    a, b, c = "openfactory-pv-acme-12", "openfactory-pv-acme-13", "openfactory-pv-acme-14"
    daemon = _daemon(monkeypatch, containers=[
        container(a, "web"), container(a, "db", exposed=""),
        container(b, "web", "exited"), container(b, "db", exposed=""),
        container(c, "web", "exited", unit="14"), container(c, "db", "exited", exposed="",
                                                            unit="14"),
        container("somebody-else", "web")])

    found = {p.compose_project: p for p in _runtime().running()}

    assert set(found) == {a, b, c}, "an exited stack is invisible to the reaper"
    assert (found[a].state, found[b].state, found[c].state) == ("running", "failed", "exited")
    assert found[c].unit == "14" and found[a].project == "acme"
    assert found[a].expires_at == 1_900_000_000 and found[a].started_at > 0
    assert all("-a" in argv for argv in daemon.argvs("docker ps"))


def test_watch_is_one_poll_and_never_raises(monkeypatch):
    def broken(*a, **kw):
        raise RuntimeError("the socket went away")

    monkeypatch.setattr(compose, "_host", broken)
    rt = _runtime()
    assert rt.watch("openfactory-pv-acme-12") is None
    assert rt.running() == [] and rt.logs("openfactory-pv-acme-12", "/tmp/x") == []
    assert rt.down("openfactory-pv-acme-12", "") == []


# ── materialise: fresh, by branch name, the change at the forge's head ──────────────────────────


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path_factory):
    """A person's repository: `main` with the S1 tree, a pull request branch that touched the API,
    `main` moved on since, and uncommitted work in the working tree."""
    path = Path(os.path.realpath(tmp_path_factory.mktemp("repo")))
    subprocess.run(["cp", "-R", str(Path(__file__).parent / "fixtures" / "preview" / "s1" / "tree")
                    + "/.", str(path)], check=True)
    _git(path, "init", "-q", "-b", "main")
    ident = ["-c", "user.email=t@example.com", "-c", "user.name=t"]
    _git(path, "add", "-A")
    _git(path, *ident, "commit", "-qm", "base")
    _git(path, "checkout", "-q", "-b", "openfactory/12")
    (path / "api" / "orders.py").write_text("ORDERS = 1\n")
    _git(path, "add", "-A")
    _git(path, *ident, "commit", "-qm", "the change")
    head = _git(path, "rev-parse", "HEAD")
    (path / "api" / "orders.py").write_text("ORDERS = 2  # pushed after the forge reported\n")
    _git(path, *ident, "commit", "-qam", "a later push")
    _git(path, "checkout", "-q", "main")
    (path / "web" / "later.txt").write_text("main moved on\n")
    _git(path, "add", "-A")
    _git(path, *ident, "commit", "-qm", "main moves on")
    (path / "UNCOMMITTED").write_text("a person's work in progress\n")
    return path, head


def test_materialise_checks_out_base_by_name_and_the_change_at_the_reported_head(root, repo):
    path, head = repo
    unit = Unit(project="acme", kind="card", id="acme/shop#12", token="12")
    source = compose.TreeSource(repo="acme/shop", dir="app", source=str(path), base_branch="main",
                                branch="openfactory/12", head=head, pr_url="https://x/pr/12")

    layout = compose.materialise(unit, trees=[source])

    tree = layout.trees["app"]
    base, change = Path(layout.root("app", "base")), Path(layout.root("app", "change"))
    assert layout.workdir == str(root / "openfactory-pv-acme-12")
    assert (base / "web" / "later.txt").exists() and not (base / "UNCOMMITTED").exists()
    assert (change / "api" / "orders.py").read_text() == "ORDERS = 1\n", (
        "the change was checked out at the branch's tip, not at the head the forge reported")
    assert tree.change_commit == head and tree.base_commit == _git(path, "rev-parse", "main")
    assert tree.diff_paths == ("api/orders.py",), "the diff is the change's own, merge base to head"
    assert tree.merge_base != tree.base_commit
    loose = [p for p in (base / ".git" / "objects").rglob("*")
             if p.is_file() and len(p.parent.name) == 2]
    assert loose and all(p.stat().st_nlink == 1 for p in loose), (
        "the checkout shares object files with the source: a container writing through one would "
        "write into every later checkout")


def test_materialise_never_reuses_a_work_directory(root, repo):
    path, _ = repo
    unit = Unit(project="acme", kind="card", id="acme/shop#12", token="12")
    stale = root / "openfactory-pv-acme-12" / "base" / "app"
    stale.mkdir(parents=True)
    (stale / "left-by-a-crash").write_text("x")

    layout = compose.materialise(unit, trees=[compose.TreeSource(
        repo="acme/shop", dir="app", source=str(path), base_branch="main")])

    assert not (Path(layout.root("app", "base")) / "left-by-a-crash").exists()


def test_a_head_the_branch_no_longer_holds_is_refused_by_name(root, repo):
    path, _ = repo
    unit = Unit(project="acme", kind="card", id="acme/shop#12", token="12")

    got = compose.materialise(unit, trees=[compose.TreeSource(
        repo="acme/shop", dir="app", source=str(path), base_branch="main",
        branch="openfactory/12", head="0" * 40)])

    assert "was reported open at 000000000000, which is not on its branch" in got.reasons[0]
    assert not (root / "openfactory-pv-acme-12").exists()


# ── what the deployment lacks ────────────────────────────────────────────────────────────────────


def test_prerequisites_are_empty_when_nothing_is_missing(root, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PREVIEW_DOMAIN", "preview.localhost")
    _daemon(monkeypatch)

    assert _runtime().prerequisites() == []


def test_prerequisites_name_each_thing_missing(root, monkeypatch):
    monkeypatch.delenv("OPENFACTORY_PREVIEW_DOMAIN", raising=False)
    _daemon(monkeypatch, shared=False)

    said = " | ".join(_runtime(panel_container="").prerequisites())

    assert "OPENFACTORY_PANEL_CONTAINER is not set" in said
    assert "OPENFACTORY_PREVIEW_DOMAIN is not set" in said
    assert "is not the same directory on the daemon's side of the socket" in said
    loopback = " | ".join(_runtime(reach="loopback").prerequisites())
    assert "OPENFACTORY_PREVIEW_PORTS is not set as `lo-hi`" in loopback


def test_a_daemon_that_does_not_answer_is_one_sentence(root, monkeypatch):
    monkeypatch.setattr(compose, "_host", lambda argv, **kw: Ran(1, "", "Cannot connect to the "
                                                                        "Docker daemon"))
    said = _runtime().prerequisites()
    assert len(said) == 1 and said[0].startswith("the Docker daemon does not answer this worker")


def test_login_puts_the_password_on_stdin_and_the_credential_in_the_previews_own_config(
        root, monkeypatch):
    daemon = _daemon(monkeypatch)
    seen = {}

    def spy(argv, **kw):
        seen.update(argv=argv, input=kw.get("input"))
        return daemon(argv, **kw)

    monkeypatch.setattr(compose, "_host", spy)

    assert compose.login("ghcr.io", username="bot", password="s3cret").rc == 0
    assert seen["argv"] == ["docker", "--config", str(root / "docker-config"), "login", "ghcr.io",
                            "--username", "bot", "--password-stdin"]
    assert seen["input"] == "s3cret" and "s3cret" not in " ".join(seen["argv"])
    assert (root / "docker-config").is_dir()


def test_prune_removes_only_images_of_previews_nothing_runs(monkeypatch):
    daemon = _daemon(monkeypatch, containers=[container("openfactory-pv-acme-12", "web")])
    real = daemon.__call__

    def with_images(argv, **kw):
        if argv[:3] == ["docker", "image", "ls"]:
            return Ran(0, "aaa\topenfactory-pv-acme-12\topenfactory-pv-acme-12-api:latest\n"
                          "bbb\topenfactory-pv-acme-9\topenfactory-pv-acme-9-api:latest\n"
                          "ccc\tsomebody-else\tsomebody-else-api:latest\n", "")
        return real(argv, **kw)

    monkeypatch.setattr(compose, "_host", with_images)

    pruned = _runtime().prune()

    assert [a[-1] for a in daemon.argvs("image rm")] == ["bbb"]
    assert "the image openfactory-pv-acme-9-api:latest of openfactory-pv-acme-9" in pruned
