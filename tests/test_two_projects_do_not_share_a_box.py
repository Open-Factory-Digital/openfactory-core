"""Two projects' ticket #12 must not be the same container (ADR-0037).

`prepare()` named the box from the BRANCH alone:

    safe = branch.replace("/", "-")     # "sdlc/12" -> "sdlc-12"
    cname = f"openfactory-{safe}"              # -> "openfactory-sdlc-12"

The branch is `sdlc/<issue>`, and issue numbers are per-repository. Project A's #12 and project B's
#12 both produce `openfactory-sdlc-12`. One deployment hosts N projects — the registry is a LIST — so this
is not exotic; it is what the second client makes certain.

AND THE COLLISION IS SILENT, WHICH IS THE ACTUAL DEFECT. `_host(run_cmd)` discards the exit code,
and `self._container = cname` is recorded unconditditionally. So when `docker run --name` fails
because the name is taken, `prepare()` returns a Workspace that looks fine and every subsequent
`docker exec` lands in **the other project's container** — a client's agent running its commands
inside another client's checkout, with that client's dependency cache and whatever their box can
reach. The same happens against a leftover container from a crashed run.

Nothing here is hypothetical about the parts: the name is deterministic, the exit code is dropped,
and the handle is assigned regardless. The tests pin both halves, because either alone leaves the
door open — a unique name with an unchecked `docker run` still attaches to a stale container after
a crash, and a checked `docker run` with a colliding name just fails the second client's job
instead of corrupting it.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from openfactory.adapters.sandbox.container import ContainerSandbox

ROOT = pathlib.Path(__file__).resolve().parent.parent


class _Daemon:
    """Records argv and refuses a `docker run --name` that is already taken, as Docker does."""

    def __init__(self, taken: set[str] | None = None, unremovable: bool = False):
        self.calls: list[list[str]] = []
        self.taken = taken or set()
        self.unremovable = unremovable

    def __call__(self, args, timeout=None):
        self.calls.append(list(args))
        if args[:2] == ["docker", "inspect"]:
            name = args[-1]
            return (0, "cid\n") if name in self.taken else (1, f"No such object: {name}")
        if args[:3] == ["docker", "rm", "-f"]:
            name = args[-1]
            if self.unremovable:
                return 1, f"cannot remove container {name}: device busy"
            self.taken.discard(name)
            return 0, name
        if args[:2] == ["docker", "run"]:
            name = args[args.index("--name") + 1]
            if name in self.taken:
                return 125, f'docker: Error response from daemon: Conflict. The container name "/{name}" is already in use.'
            self.taken.add(name)
        return 0, ""

    def names(self) -> list[str]:
        return [a[a.index("--name") + 1] for a in self.calls if a[:2] == ["docker", "run"]]


@pytest.fixture
def daemon(monkeypatch):
    import openfactory.adapters.sandbox.container as mod

    d = _Daemon()
    monkeypatch.setattr(mod, "_host", d)
    return d


def _prepare(daemon, *, project: str, issue: str = "12"):
    box = ContainerSandbox(image="img", project=project)
    return box.prepare(repo_path=ROOT, base_branch="main", branch=f"openfactory/{issue}")


# ── the collision ───────────────────────────────────────────────────────────────────────────────

def test_the_same_issue_number_in_two_projects_gets_two_boxes(daemon):
    """THE defect. One deployment, two clients, both with a ticket #12."""
    _prepare(daemon, project="acme")
    _prepare(daemon, project="globex")

    names = daemon.names()
    assert len(set(names)) == 2, f"both projects got the same container: {names}"


def test_the_project_is_in_the_name(daemon):
    """Not just unique — DIAGNOSABLE. `docker ps` during an incident has to say whose box this is."""
    _prepare(daemon, project="acme", issue="12")

    assert "acme" in daemon.names()[0], daemon.names()


def test_the_issue_is_still_in_the_name(daemon):
    """The property that made the old name useful must survive the fix."""
    _prepare(daemon, project="acme", issue="4127")

    assert "4127" in daemon.names()[0], daemon.names()


def test_a_project_name_that_is_not_docker_safe_is_sanitised(daemon):
    """Registry names are free text. Docker accepts `[a-zA-Z0-9][a-zA-Z0-9_.-]*`, so a name with a
    slash or a space would fail the run — which, before the exit-code check below, would have been
    the silent-attach path again."""
    _prepare(daemon, project="Acme Corp/Web")

    name = daemon.names()[0]
    import re

    assert re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", name), name


def test_a_project_less_box_still_works(daemon):
    """`project` is optional: the CLI and every existing test construct a box without one, and a
    required argument here would be a migration for no safety gain."""
    box = ContainerSandbox(image="img")
    box.prepare(repo_path=ROOT, base_branch="main", branch="openfactory/12")

    assert daemon.names() == ["openfactory-12"], daemon.names()


# ── the silence ─────────────────────────────────────────────────────────────────────────────────

def test_a_leftover_from_an_interrupted_attempt_is_removed_and_the_job_starts(daemon, capsys):
    """MEASURED ON THE PILOT (#165). A deploy SIGTERMed the worker mid-attempt; the box it had
    launched kept running on the host daemon (docker-out-of-docker: the supervisor dies, its child
    does not) — `Up 37 minutes` with nobody listening. The RESUME then collided with the corpse's
    name, `docker run` exited 125, and a self-healing retry became a second park.

    The name is derived from (project, issue) and attempts are serial by construction, so a
    container wearing it as we start cannot be a live sibling — it is debris, and it is removed
    out loud."""
    daemon.taken.add("openfactory-acme-12")

    box = ContainerSandbox(image="img", project="acme")
    box.prepare(repo_path=ROOT, base_branch="main", branch="openfactory/12")

    ops = [c[:3] for c in daemon.calls if c[0] == "docker"]
    rm_at = ops.index(["docker", "rm", "-f"])
    run_at = next(i for i, c in enumerate(ops) if c[:2] == ["docker", "run"])
    assert rm_at < run_at, "the corpse was removed only after the run had already collided"
    assert box._container == "openfactory-acme-12", "the job did not start after the reconcile"
    assert "leftover box" in capsys.readouterr().out, "the removal is silent — debris with no trail"


def test_a_fresh_start_removes_NOTHING(daemon):
    """The twin: `rm -f` against a name that exists only in this attempt's future must never run —
    a reconcile that always fires is a delete on every start, waiting for a reason."""
    _prepare(daemon, project="acme")

    assert not any(c[:3] == ["docker", "rm", "-f"] for c in daemon.calls), (
        "the reconcile fires without a leftover")


def test_an_UNREMOVABLE_corpse_still_refuses_with_the_daemons_words(monkeypatch, capsys):
    """The half that makes the collision dangerous rather than merely wrong survives the
    reconcile: a `docker run` that fails must never leave a handle behind, or every later `exec`
    runs in a stranger's container."""
    import openfactory.adapters.sandbox.container as mod

    d = _Daemon(taken={"openfactory-acme-12"}, unremovable=True)
    monkeypatch.setattr(mod, "_host", d)

    box = ContainerSandbox(image="img", project="acme")
    with pytest.raises(RuntimeError) as err:
        box.prepare(repo_path=ROOT, base_branch="main", branch="openfactory/12")

    assert "already in use" in str(err.value) or "125" in str(err.value), str(err.value)
    assert "openfactory-acme-12" in str(err.value)
    assert box._container is None, "a handle was recorded for a container that was never created"
    assert "could not remove the leftover box" in capsys.readouterr().out, (
        "the failed removal left no trail — the collision below masquerades as new")


# ── reachability: the factory must actually pass the project ────────────────────────────────────

def test_the_factory_names_the_project_when_it_builds_the_box():
    """A `project` parameter the composition root never passes is the same defect in a new place —
    the box would be uniquely named only in tests. `build_runner` holds the project; it has no
    excuse."""
    from openfactory.contracts.project import Project

    seen = {}

    import openfactory.adapters.sandbox.registry as reg
    real = reg.BOXES["container"][1]

    def _spy(**kw):
        seen.update(kw)
        return real(**kw)

    traits, _ = reg.BOXES["container"]
    reg.BOXES["container"] = (traits, _spy)
    try:
        from openfactory import factory

        project = Project(name="acme", repo_path="/tmp/acme")
        try:
            factory.build_runner(project, "#12", sandbox="container", image="img", review=False)
        except Exception:
            pass  # the rest of the wiring may fail without credentials; the box call is what counts
    finally:
        reg.BOXES["container"] = (traits, real)

    assert seen.get("project") == "acme", (
        f"build_runner did not tell the box whose it is: {seen}"
    )


# ── an empty workspace is worse than a failure ──────────────────────────────────────────────────

def test_a_failed_clone_raises_instead_of_mounting_an_empty_directory(monkeypatch):
    """Found by running `sdlc box prove` inside the compose worker (2026-08-03).

    `prepare` does `git clone --local <repo_path>` into a fresh temp dir and never looked at the
    exit code. A clone that fails leaves that temp dir EMPTY, and it gets bind-mounted as
    /workspace regardless — so `setup:` "succeeds" against nothing, `pytest` collects nothing and
    exits 5, and an agent would be asked to implement a ticket in an empty directory.

    The same shape as the `docker run` exit code fixed earlier: the failure is silent and the
    thing that follows it looks almost plausible, which is the worst combination available."""
    import openfactory.adapters.sandbox.container as mod

    def _host(args, timeout=None):
        if args[:2] == ["git", "clone"]:
            return 128, "fatal: repository 'https://github.com/o/n.git' not found"
        return 0, ""

    monkeypatch.setattr(mod, "_host", _host)

    box = ContainerSandbox(image="img", project="acme")
    with pytest.raises(RuntimeError) as err:
        box.prepare(repo_path=ROOT, base_branch="main", branch="openfactory/12")

    assert "not found" in str(err.value)
    assert box._container is None, "a box was started over a workspace that has nothing in it"


def test_a_failed_checkout_of_an_existing_branch_also_raises(monkeypatch):
    """The CI-repair path fetches an already-pushed branch. A fetch that fails leaves the clone on
    the base branch, so the repair would be attempted against code that does not contain the
    change it is repairing."""
    import openfactory.adapters.sandbox.container as mod

    def _host(args, timeout=None):
        if "fetch" in args or "checkout" in args:
            return 1, "fatal: couldn't find remote ref openfactory/12"
        return 0, ""

    monkeypatch.setattr(mod, "_host", _host)

    with pytest.raises(RuntimeError) as err:
        ContainerSandbox(image="img", project="acme").prepare(
            repo_path=ROOT, base_branch="main", branch="openfactory/12", checkout_existing=True)

    assert "openfactory/12" in str(err.value)


# ── docker-out-of-docker: a path the worker makes must mean the same to the daemon ──────────────

def test_the_workspace_is_created_where_the_daemon_can_see_it(monkeypatch, tmp_path):
    """THE defect, measured on the running compose stack (2026-08-03):

        worker creates: /tmp/probe-Eguu
        the box sees  : 0 entries

    `prepare` clones into `tempfile.mkdtemp()` — a path inside the WORKER container — and hands it
    to `docker run -v`, which the HOST's daemon resolves against the HOST filesystem. That path
    does not exist there, so Docker creates an EMPTY directory and mounts it. Every job in the
    compose deployment would have run against nothing, with the agent asked to implement a ticket
    in an empty workspace.

    Same class the toolbox mount was fixed for, sitting one line away. The fix is a directory bound
    at the SAME absolute path on both sides, which is the standard docker-out-of-docker idiom."""
    import openfactory.adapters.sandbox.container as mod

    monkeypatch.setenv("OPENFACTORY_WORK_DIR", str(tmp_path / "work"))
    d = _Daemon()
    monkeypatch.setattr(mod, "_host", d)

    ContainerSandbox(image="img", project="acme").prepare(
        repo_path=ROOT, base_branch="main", branch="openfactory/12")

    run_argv = next(a for a in d.calls if a[:2] == ["docker", "run"])
    mount = next(p for p in run_argv if p.endswith(":/workspace"))
    assert mount.startswith(str(tmp_path / "work")), (
        f"the workspace was created outside the shared directory: {mount}"
    )


def test_without_the_setting_it_is_todays_behaviour(monkeypatch):
    """A bare-metal worker and every `openfactory run` on a laptop share a filesystem with the daemon, so
    the temp directory is already addressable by both. Nothing there moves."""
    import openfactory.adapters.sandbox.container as mod

    monkeypatch.delenv("OPENFACTORY_WORK_DIR", raising=False)
    d = _Daemon()
    monkeypatch.setattr(mod, "_host", d)

    ContainerSandbox(image="img", project="acme").prepare(
        repo_path=ROOT, base_branch="main", branch="openfactory/12")

    run_argv = next(a for a in d.calls if a[:2] == ["docker", "run"])
    assert any(p.endswith(":/workspace") for p in run_argv)


#: `${NAME}` / `${NAME:-default}` / `${NAME-default}`, which is all compose interpolation this file
#: uses. Written here rather than imported because the property being measured is precisely that
#: the compose file's own text resolves correctly — borrowing a resolver from the code under test
#: would be the guard reading the answer off the thing it is checking.
_INTERPOLATION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}")


def _interpolate(text: str, env: dict[str, str]) -> str:
    """Compose's own rules, and the colon is not decoration: `${A:-d}` falls back when A is unset
    OR empty, `${A-d}` only when it is unset. `.env.compose.example` ships the version row EMPTY
    and relies on the first form."""
    def one(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        value = env.get(name)
        if match.group(0).startswith(f"${{{name}:-"):
            return value if value else (default or "")
        return default or "" if value is None else value
    return _INTERPOLATION.sub(one, text)


def _worker_service() -> dict:
    import pathlib

    import yaml

    root = pathlib.Path(__file__).resolve().parent.parent
    return yaml.safe_load((root / "docker-compose.yml").read_text())["services"]["worker"]


def test_compose_binds_the_work_directory_at_the_same_path_on_both_sides():
    """A NAMED VOLUME would not do: the daemon cannot address a volume by the worker's path either.
    It has to be a host bind whose source and target are identical, or the mount the worker asks
    for means something different to the thing performing it.

    RAW-STRING EQUALITY USED TO BE THE WHOLE TEST, and on 2026-08-30 it stopped being enough. The
    work directory became `${OPENFACTORY_WORK_DIR:-/var/lib/openfactory-work}` on both sides so a
    new install could put it somewhere the invoking user already owns and drop the `sudo` line
    from the first-run path. The old assertion compared the literal strings — which the byte-
    identical expressions still satisfy — but two identical expressions are not the property. The
    property is that the two RESOLVE to the same usable path, and this guard now interpolates them
    with three different environments to say so."""
    worker = _worker_service()
    configured = (worker.get("environment") or {}).get("OPENFACTORY_WORK_DIR")

    assert configured, "the worker does not configure OPENFACTORY_WORK_DIR, so every job's workspace is " \
                       "created at a path the host daemon cannot resolve"
    assert f"{configured}:{configured}" in worker.get("volumes", []), (
        f"OPENFACTORY_WORK_DIR={configured} must be bound source:target identically; found "
        f"{worker.get('volumes')}")


@pytest.mark.parametrize("env", [
    pytest.param({}, id="an-env-file-with-no-row-at-all"),
    pytest.param({"OPENFACTORY_WORK_DIR": ""}, id="the-row-present-and-empty"),
    pytest.param({"OPENFACTORY_WORK_DIR": "/home/ana/.local/share/openfactory/work"},
                 id="the-row-init-writes"),
])
def test_the_bound_work_directory_is_absolute_and_the_same_on_both_sides_after_interpolation(env):
    """The half raw-string equality cannot see. Three environments, because the three are what a
    real machine actually presents: no row (every install written before 2026-08-30), an empty row
    (the shipped template), and the row `init` writes.

    ABSOLUTE, because Compose resolves a bind source against the directory the command ran in, so a
    relative work dir silently makes the workspace a subdirectory of the user's checkout — and
    NO `~`, because **compose does not expand a tilde in a bind source**. A `~`-relative value
    creates a literal `./~` directory on the host and mounts an empty box: exactly the defect
    `container.py`'s comment records as "the box saw 0 entries" (2026-08-03), which is invisible
    until an agent is asked to implement a ticket in an empty directory."""
    worker = _worker_service()
    configured = _interpolate((worker["environment"])["OPENFACTORY_WORK_DIR"], env)
    bind = next(v for v in worker["volumes"] if "openfactory-work" in v or "OPENFACTORY_WORK_DIR" in v)
    source, _, target = _interpolate(bind, env).partition(":")

    assert source == target == configured, (
        f"with {env or 'no row'} the worker is told {configured!r} and the bind resolves "
        f"{source!r}:{target!r} — the daemon would mount a directory the worker never writes to")
    assert configured.startswith("/"), (
        f"{configured!r} is not absolute; compose resolves a bind source against the invoking "
        f"directory, so every job's workspace would land inside whatever checkout ran `up`")
    assert "~" not in configured, (
        f"{configured!r} contains a tilde and compose does NOT expand one in a bind source — the "
        f"host would get a literal `./~` directory and every box would mount it empty")
