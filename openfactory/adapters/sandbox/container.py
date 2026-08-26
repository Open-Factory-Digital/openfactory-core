"""ContainerSandbox — the real ephemeral environment (Docker).

Production path (ADR-0001 D-4): the container is where isolation is actually kept.

Design (clone-based, self-contained):
- On the host, make an ephemeral local clone of the repo (fast, self-contained
  `.git` — avoids the git-worktree-in-container path problem) on a fresh branch.
- Bind-mount that clone into a container built from a per-stack base image that
  already has the toolchain + git + the `claude` CLI. The container sees only
  `/workspace`, nothing else of the host.
- A dep-cache volume can be mounted so we don't pay a full install per job
  (`cache_volume`; unset by default, because sharing a cache across projects is a
  deployment's decision, not this class's).
- Auth is injected as env at run time (subscription token or API key), never baked.
- CPU and memory limits bound the blast radius: `--cpus` and `--memory`, applied on
  every run.

WHAT THIS BOX DOES **NOT** DO, stated because it used to claim the opposite. These
lines, and the matching ones in `base.py` and `registry.py`, said the box denied
egress unless allowed. It does not, and it cannot: `network` defaults to `bridge`,
which is **full outbound internet**, and it has to be — the harness dials its API and
the manifest's `setup:` runs `pip install` / `dotnet restore` / `npm ci`. Cutting the
box off from the internet would break every job.

A false security claim is worse than no claim, because it is consumed as a control:
somebody deciding what a client's box may touch reads a promise of egress control and
stops thinking. The true statement is the useful one — **anything the box's network can
reach is reachable by code the agent wrote** — and a deployment that needs that
bounded sets `network` to its own egress-restricted network or proxy, which is now a
knob the registry can actually pass (it constructed this class with `image=` alone,
so all four of the others were unreachable).

ADR-0037 makes the image the CLIENT's, which turns "what can this box reach?" from a
theoretical question into one somebody will genuinely ask.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from openfactory.adapters.sandbox.base import (
    OutputBuffer,
    SandboxAdapter,
    Workspace,
    run_and_stream,
)

log = logging.getLogger("openfactory.sandbox.container")

_AUTH_ENV_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
_WORKDIR = "/workspace"

#: Where the framework's harness toolbox is mounted inside the box (ADR-0037 D2).
#:
#: Under `/opt` and namespaced, because it is grafted into an image the framework does not control
#: and must not collide with anything a client could reasonably already have there.
TOOLBOX_MOUNT = "/opt/openfactory-toolbox"


def _redact(text: str) -> str:
    return re.sub(r"(https://)[^@/\s]+@", r"\1***@", text)


def _container_name(project: str | None, safe_branch: str) -> str:
    """A box name that is unique per project and readable in `docker ps`.

    Was `f"sdlc-{safe_branch}"` with the branch `sdlc/<issue>` — so project A's #12 and
    project B's #12 were both `sdlc-sdlc-12`. One deployment hosts N projects, which makes that
    a certainty the day a second client is onboarded rather than an edge case.

    Docker accepts `[a-zA-Z0-9][a-zA-Z0-9_.-]*`; registry project names are free text, so anything
    else collapses to `-`. Readable matters as much as unique: `docker ps` during an incident has
    to say whose box this is, which is also why the branch's own prefix is dropped rather than
    repeated — `openfactory-acme-12`, not `openfactory-acme-openfactory-12`. The one thing this
    name must stay is STABLE across every entry of the same job (a fresh run, a repair, a resume):
    the panel and `docker ps` find a job's box by it."""
    tail = safe_branch.removeprefix("openfactory-") or safe_branch
    parts = [p for p in ("openfactory", re.sub(r"[^a-zA-Z0-9_.-]+", "-", project or "").strip("-"),
                         tail) if p]
    return "-".join(parts)


def _host(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _materialize_workspace(*, repo_path: Path, host_clone: Path, base_branch: str,
                           branch: str, checkout_existing: bool,
                           remote_url: str | None = None) -> None:
    """Clone `repo_path` into `host_clone` and put it on `branch` — the box's working tree.

    EVERY GIT STEP IS CHECKED. None of these exit codes was looked at once, and the failure that
    produces is the quietest one available: a clone that fails leaves `host_clone` EMPTY, it is
    bind-mounted as /workspace anyway, `setup:` succeeds against nothing, `pytest` collects
    nothing and exits 5 — and an agent would be asked to implement a ticket in an empty
    directory. Found by running `openfactory box prove` inside the compose worker.

    Module-level, docker-free, so the branch topology is testable against real git repos."""
    def _must(args: list[str], what: str) -> None:
        rc, out = _host(args)
        if rc != 0:
            raise RuntimeError(f"{what} failed ({rc}): {_redact(out).strip()[:300]}")

    _must(["git", "clone", "--local", "--no-hardlinks", str(repo_path), str(host_clone)],
          f"cloning {repo_path} into the box's workspace")
    if checkout_existing:
        # FETCH THE PR BRANCH FROM THE FORGE, NOT FROM THE CACHE. This clone's `origin` is the
        # worker's cache DIRECTORY (`--local` above), which only ever holds the base branch its
        # syncs check out — the PR branch lives one hop upstream. And the cache's own origin
        # deliberately carries no credential (agents read that checkout), so reaching through it
        # cannot work on a private repository either.
        #
        # `remote_url` is the forge's authenticated URL, passed as an ARGUMENT so git does not
        # persist it — the same discipline `publish_branch` uses for the push, and the same one
        # RepoCache uses for its fetches. It matters here specifically: this clone is
        # bind-mounted into the box, where untrusted code runs.
        #
        # FOUND LIVE (fx-mono#1's adjust, 2026-08-04): "couldn't find remote ref sdlc/1" on a
        # branch sitting right there on the forge — every container-sandbox CI repair and human
        # adjust on a private repository failed this way, blaming the branch for a missing
        # password.
        source = remote_url or "origin"
        # A failed fetch here would leave the clone on the BASE branch, so a CI repair would run
        # against code that does not contain the change it is repairing — hence `_must`.
        _must(["git", "-C", str(host_clone), "fetch", source,
               f"+{branch}:refs/remotes/origin/{branch}"],
              f"fetching the existing branch {branch!r}")
        _must(["git", "-C", str(host_clone), "checkout", "-B", branch, f"origin/{branch}"],
              f"checking out {branch!r}")
    else:
        _must(["git", "-C", str(host_clone), "checkout", "-b", branch, base_branch],
              f"creating {branch!r} from {base_branch!r}")


class ContainerSandbox(SandboxAdapter):
    def __init__(
        self,
        *,
        image: str,
        #: WHOSE box this is. One deployment hosts N projects and issue numbers are
        #: per-repository, so the container name needs the project or two clients' ticket #12 are
        #: the same container. Optional because the CLI and the tests construct boxes without a
        #: project and a required argument would be a migration for no safety gain — the exit-code
        #: check in `prepare` is what makes a collision loud either way.
        project: str | None = None,
        #: The docker VOLUME (or host path) holding the framework's harness toolbox, mounted
        #: read-only at `TOOLBOX_MOUNT`. A NAME rather than a path by default, and that is not a
        #: preference: the compose worker is itself a container issuing `docker run` against the
        #: HOST's daemon, so a `-v /var/lib/openfactory-toolbox` it passes is resolved on the host,
        #: where
        #: that path does not exist — Docker creates an empty directory and the box gets an empty
        #: toolbox, in silence. A named volume is the daemon's own object and behaves identically
        #: from a containerised or a bare-metal worker.
        toolbox: str | None = None,
        cache_volume: str | None = None,
        cpus: str = "2",
        memory: str = "4g",
        network: str = "bridge",
        #: NAMES of extra environment variables to pass through (registry `box.env`) — the
        #: harness-provider and scanner credentials a deployment's own auth shape needs. Values
        #: travel by docker's `-e VAR` pass-through form, exactly like `_AUTH_ENV_VARS`: never on
        #: a command line, never in a log. VALIDATED because each name becomes a `docker` argument
        #: — a "name" with a space or an `=` would smuggle a value (or an option) into the
        #: command, and this list is configuration, not code review.
        extra_env: tuple[str, ...] = (),
    ) -> None:
        bad = [v for v in extra_env if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v or "")]
        if bad:
            raise ValueError(
                f"box.env entries must be environment variable NAMES, got {bad!r} — a value or "
                "an option here would ride straight into the docker command line")
        self.image = image
        self.project = project
        self.toolbox = toolbox
        self.cache_volume = cache_volume
        self.cpus = cpus
        self.memory = memory
        self.network = network
        self.extra_env = tuple(extra_env)
        # concurrency = 1 for now, so a single-job handle on the instance is fine.
        self._container: str | None = None
        self._host_clone: Path | None = None
        self._repo_path: Path | None = None
        #: The box's own HOME, ASKED once per container (see `_box_home`). `None` = not asked yet,
        #: `""` = asked and unanswerable.
        self._home: str | None = None
        #: What the command currently running has written — the buffer `tail()` reads (C-39). One
        #: per box for the same reason as the handle above: one job at a time.
        self._output = OutputBuffer()


    def _passthrough_env(self) -> list[str]:
        """Which variable NAMES cross into the box right now: the harness defaults plus this
        project's own `box.env`, deduplicated, only when PRESENT in the worker's environment.

        Presence is re-checked at every call on purpose — the token pool rotates os.environ
        between execs, and a snapshot taken at prepare() would keep exec'ing with a dead
        credential (the audit that made run() re-read _AUTH_ENV_VARS applies to these too)."""
        seen: list[str] = []
        for var in (*_AUTH_ENV_VARS, *self.extra_env):
            if var not in seen and os.environ.get(var):
                seen.append(var)
        return seen

    def prepare(
        self, *, repo_path: Path, base_branch: str, branch: str, checkout_existing: bool = False,
        remote_url: str | None = None,
    ) -> Workspace:
        """See `_materialize_workspace` for the git steps — factored out so the branch topology
        is testable without a docker daemon."""
        safe = branch.replace("/", "-")
        self._repo_path = repo_path
        # WHERE the clone lives decides whether the box can see it at all. `docker run -v <path>`
        # is resolved by the DAEMON, and under docker-out-of-docker the worker is itself a
        # container: a `mkdtemp()` path exists in the worker and NOT on the host, so Docker
        # creates an empty directory and mounts that. Measured on the compose stack — the worker
        # made /tmp/probe-Eguu and the box saw 0 entries — which means every job would have run
        # against an empty workspace, with the agent asked to implement a ticket in nothing.
        #
        # `OPENFACTORY_WORK_DIR` is a directory bound at the SAME absolute path on both sides, so a
        # path
        # the worker creates means the same thing to the daemon. Unset is today's behaviour and is
        # correct for a bare-metal worker, which shares a filesystem with its daemon.
        work_dir = (os.environ.get("OPENFACTORY_WORK_DIR") or "").strip()
        if work_dir:
            Path(work_dir).mkdir(parents=True, exist_ok=True)
        host_clone = Path(tempfile.mkdtemp(prefix=f"openfactory-{safe}-", dir=work_dir or None))
        _materialize_workspace(repo_path=repo_path, host_clone=host_clone,
                               base_branch=base_branch, branch=branch,
                               checkout_existing=checkout_existing, remote_url=remote_url)

        cname = _container_name(self.project, safe)
        # A LEFTOVER WEARING OUR NAME IS DEBRIS, NOT A NEIGHBOUR (#165). The worker dying under an
        # attempt — a deploy's SIGTERM, an OOM kill — orphans the box on the host daemon
        # (docker-out-of-docker: the supervisor dies, its child does not), and the NEXT attempt
        # then collides with the corpse's name and refuses. The refusal below is right for every
        # other cause; for this one it turned a self-healing resume into a second park on the
        # pilot, with the orphan still burning an agent unsupervised. The name is derived from
        # (project, issue) and attempts are serial by construction (single-line floor), so a
        # container wearing it as we start CANNOT be a live sibling. Reattaching is not an option
        # on a non-idempotent box (it may be mid-write on the same branch this attempt will use) —
        # remove it, out loud.
        probe_rc, _ = _host(["docker", "inspect", "--format", "{{.Id}}", cname])
        if probe_rc == 0:
            print(f"OPENFACTORY: removing the leftover box {cname!r} from an interrupted "
                  f"attempt before starting fresh", flush=True)
            rm_rc, rm_out = _host(["docker", "rm", "-f", cname])
            if rm_rc != 0:
                # An unremovable corpse still refuses below with the daemon's own words — this
                # only adds WHY to the trail instead of letting the collision masquerade as new.
                print(f"OPENFACTORY: could not remove the leftover box {cname!r} "
                      f"({rm_out.strip()[:200]})", flush=True)
        run_cmd = [
            "docker", "run", "-d", "--name", cname,
            "--cpus", self.cpus, "--memory", self.memory,
            "--network", self.network,
            # override any image ENTRYPOINT so the keep-alive command runs as-is
            "--entrypoint", "sleep",
            "-v", f"{host_clone}:{_WORKDIR}", "-w", _WORKDIR,
        ]
        if self.toolbox:
            # READ-ONLY, which bounds the accident rather than the adversary: a process at uid 0
            # inside the box can copy a binary out and run a patched copy, and ADR-0037 says so
            # plainly instead of implying otherwise. What `:ro` buys is that the toolbox one job
            # leaves behind is the toolbox the next job gets.
            run_cmd += ["-v", f"{self.toolbox}:{TOOLBOX_MOUNT}:ro"]
        if self.cache_volume:
            run_cmd += ["-v", f"{self.cache_volume}:/cache"]
        for var in self._passthrough_env():
            run_cmd += ["-e", var]  # value inherited from the daemon client env
        run_cmd += [self.image, "infinity"]
        rc, out = _host(run_cmd)
        if rc != 0:
            # NEVER record a handle for a container that was not created. This used to be a bare
            # `_host(run_cmd)` with `self._container = cname` below it regardless, so a refused
            # run — a name collision, a leftover container from a crash, an unpullable image —
            # produced a Workspace that looked fine while every later `docker exec` landed in
            # SOMEBODY ELSE'S container: another client's checkout, cache and network.
            raise RuntimeError(
                f"could not start the box {cname!r} (docker run exited {rc}): {out.strip()[:300]}"
            )
        _host(["docker", "exec", cname, "git", "config", "--global",
               "--add", "safe.directory", _WORKDIR])

        self._container, self._host_clone = cname, host_clone
        # A NEW container is a new HOME: the image may differ from the last job's (ADR-0037 D4
        # resolves it per project) and the answer is cached per container, so a stale one would
        # send a session snapshot to a path that does not exist in this box.
        self._home = None
        # `path` is the IN-CONTAINER mount point; `host_path` is the same checkout as the
        # orchestrator sees it (the bind-mounted clone) — what host-side readers must use.
        return Workspace(path=Path(_WORKDIR), host_path=host_clone,
                         branch=branch, base_branch=base_branch)

    def harness_path(self, name: str) -> str:
        """An absolute path into the mounted toolbox — never a bare name.

        `PATH` cannot be relied on here: the image is the client's, and a login shell or a
        `/etc/profile.d` snippet reassigns `PATH` before the command runs. An absolute path is also
        what makes the toolbox's integrity mean anything — a checksum over bytes nobody is required
        to execute checks nothing.

        VALIDATED, because the result is executed. `name` comes from the registry's `harness:`
        today, which is operator-owned, but the cost of being wrong is arbitrary execution inside
        the box, so it is checked where it is used rather than trusted from where it came."""
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", name or ""):
            raise ValueError(
                f"{name!r} is not a harness name — expected a bare lowercase binary name like "
                "'claude', 'codex' or 'kimi'"
            )
        return f"{TOOLBOX_MOUNT}/{name}"

    @staticmethod
    def _quiet_host(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
        """`_host`, except a wall is an ANSWER. The transfer methods promise the port they never
        raise; `_host` raises `TimeoutExpired`, and a `docker cp` of a large session is exactly
        where that happens — turning a resumable pause into a failed job for the sake of a
        snapshot nobody would have missed."""
        try:
            return _host(cmd, timeout=timeout)
        except (subprocess.TimeoutExpired, OSError) as exc:
            log.warning("a docker step of the session transfer did not finish (%s) — the resumed "
                        "run will start cold", str(exc)[:160])
            return 1, str(exc)[:200]

    #: `docker cp` of a harness session, and the two probes around it. Ten times `_host`'s default,
    #: because the default was written for `docker run`/`rm` and this one moves bytes.
    _TRANSFER_TIMEOUT = 1200

    def _box_home(self) -> str:
        """The HOME of this box — ASKED, never assumed, because the image is the client's.

        `/root` is right for the images this platform ships and wrong for any image with a
        non-root `USER`, which is what a hardened client image is. Asked once per container
        (`prepare` clears the cache) through the same `_host` call every other docker step uses.

        THE ANSWER IS TAGGED because `_host` returns stdout and stderr interleaved and `printf`
        writes no trailing newline: a client image whose shell says anything on stderr would have
        it glued to the end of the path, and the box would silently stop being able to carry a
        session. The tag makes the answer findable rather than positional."""
        if self._home is not None:
            return self._home
        self._home = ""
        if not self._container:
            return self._home
        rc, out = self._quiet_host(
            ["docker", "exec", self._container, "sh", "-c", 'printf "OFHOME:%s\\n" "$HOME"'])
        answer = next((ln[len("OFHOME:"):].strip() for ln in (out or "").splitlines()
                       if ln.startswith("OFHOME:")), "")
        if rc == 0 and answer.startswith("/"):
            self._home = answer
        else:
            log.warning("the box %s did not answer where its HOME is (%s) — anything that has to "
                        "cross out of it will be skipped",
                        self._container, (out or "").strip()[:120])
        return self._home

    @staticmethod
    def _under_home(home: str, relative: str) -> str:
        """`home/relative`, or "" when `relative` is not a plain relative path.

        It becomes an argument to a copy the orchestrator issues against the client's box; `..`
        would reach outside the harness's own state, and an absolute path would ignore the box's
        HOME entirely. Configuration is not code review — the same rule `harness_path` applies to
        the name it executes."""
        rel = (relative or "").strip()
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            log.warning("refusing %r as a path inside the box's HOME — it must be relative and "
                        "must not climb out of it", relative)
            return ""
        return f"{home.rstrip('/')}/{rel}"

    def export_home_dir(self, *, workspace: Workspace, relative: str, dest: Path) -> bool:
        """See the port. `docker cp` rather than a mount, and that is the whole reason this works
        under docker-out-of-docker: the CLIENT of the daemon reads and writes the local side, so
        the bytes land in the WORKER's filesystem. A `-v` path the worker invents is resolved by
        the HOST daemon instead, which creates an empty directory rather than failing — the same
        trap `prepare` documents, measured again in both directions before this was written."""
        home = self._box_home()
        src = self._under_home(home, relative) if home else ""
        if not (self._container and src):
            return False
        # `-d` follows symlinks, so ask for the directory AND that it is not a link: a box whose
        # `projects` is `ln -s /` would otherwise copy the box's whole filesystem out.
        rc, _ = self._quiet_host(["docker", "exec", self._container, "sh", "-c",
                                  f'[ -d "{src}" ] && [ ! -L "{src}" ]'])
        if rc != 0:
            return False  # nothing to take — the harness never wrote it (a cold pass)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        rc, out = self._quiet_host(["docker", "cp", f"{self._container}:{src}", str(dest)],
                                   timeout=self._TRANSFER_TIMEOUT)
        if rc != 0:
            log.warning("could not take %s out of the box %s (%s)", src, self._container,
                        (out or "").strip()[:160])
            return False
        return dest.is_dir() and not dest.is_symlink()

    def import_home_dir(self, *, workspace: Workspace, src: Path, relative: str) -> bool:
        """See the port. MERGES, via `docker cp <src>/. <box>:<target>` — the trailing `/.` is
        what makes docker copy the CONTENTS into an existing directory instead of nesting the
        source inside it (`projects/projects/…`, where the harness never looks). The target is
        created first so the contents have somewhere to land, and never removed: on a box whose
        HOME belongs to the process rather than to the job, removing it deletes somebody else's
        work."""
        home = self._box_home()
        target = self._under_home(home, relative) if home else ""
        if not (self._container and target and src.is_dir()):
            return False
        self._quiet_host(["docker", "exec", self._container, "mkdir", "-p", target])
        rc, out = self._quiet_host(["docker", "cp", f"{src}/.", f"{self._container}:{target}"],
                                   timeout=self._TRANSFER_TIMEOUT)
        if rc != 0:
            log.warning("could not put %s back into the box %s (%s)", relative, self._container,
                        (out or "").strip()[:160])
            return False
        rc, _ = self._quiet_host(["docker", "exec", self._container, "test", "-d", target])
        return rc == 0

    def run(self, *, workspace: Workspace, command: str, timeout: int,
            on_output: Callable[[str], None] | None = None) -> tuple[int, str]:
        """THE PRODUCTION BOX THREW THE TRANSCRIPT AWAY AT THE WALL, and only the production box.

        This used to end `except subprocess.TimeoutExpired: return timeout_result(command,
        timeout)` — two arguments where the function has always taken three. The worktree passed
        its partial output; the container passed none. So the four-hour wall arrived on the box
        that matters most with the whole stream already discarded, and every reader downstream got
        an empty one: `read_harness([])` correctly refuses to call that an idle agent, which means
        the honest answer to "what was it doing for four hours?" was *nothing can be said* — for
        the one run nobody can re-observe. `run_and_stream` keeps what was written, both boxes,
        one code path.

        `docker exec` IS A LOCAL SUBPROCESS AND THAT IS WHY THIS BOX CAN STREAM. Its stdout is a
        pipe on the worker carrying the container process's output as it is produced, so the
        `streams` trait can honestly answer True here (`registry.BOXES`).

        WHAT KILLING IT DOES AND DOES NOT REACH, said out loud because a reader will assume the
        stronger thing: killing the `docker exec` CLIENT does not stop the process inside the
        container — the daemon owns that one. It is bounded, not leaked: `cleanup()` issues
        `docker rm -f`, which takes the whole box with it. That was equally true of the
        `subprocess.run(timeout=…)` this replaces; what changes is that we no longer wait on it —
        the previous code could block past its own wall inside `communicate()`."""
        assert self._container, "prepare() must be called first"
        # Pass the auth vars PER EXEC (the `-e VAR` pass-through form — value comes from the
        # client env, never the command line). The container's own env was frozen at `docker
        # run`, so without this a token-pool ROTATION (which mutates os.environ between
        # invocations) would silently keep exec'ing with the ORIGINAL token — the lap would
        # burn n identical attempts on one dead credential (audit CRITICAL). Also covers a
        # pool-only deploy where no auth var existed yet at prepare() time.
        env_flags: list[str] = []
        for var in self._passthrough_env():
            env_flags += ["-e", var]
        return run_and_stream(
            subprocess.Popen(
                # `sh -c`, NEVER `sh -lc`. A login shell sources the CLIENT IMAGE's /etc/profile
                # and /etc/profile.d/* before the command — arbitrary third-party code running
                # ahead of everything the platform issues, with the harness token already in the
                # environment from the `-e` flags above. Under ADR-0037 the image is the client's,
                # which turns that from an oddity into a credential exposure.
                #
                # It also silently broke the toolbox: Debian's and Alpine's stock /etc/profile
                # ASSIGN PATH unconditionally, so any PATH the framework sets is discarded before
                # the command runs. That is why ADR-0037 D2 addresses the harness by absolute path
                # and why the two land together — fixing only the paths would leave the exposure.
                #
                # `-l` bought nothing: setup:/validate: are client-written strings run in a
                # container whose environment this adapter sets explicitly.
                ["docker", "exec", *env_flags, "-w", _WORKDIR, self._container,
                 "sh", "-c", command],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, errors="replace", bufsize=1,
            ),
            command=command, timeout=timeout, buffer=self._output, on_output=on_output,
        )

    def tail(self) -> list[str] | None:
        """Never None: `docker exec` is a local subprocess and the daemon relays the container
        process's output through its pipe live — which is what `streams=True` claims for this box
        in the registry, and what the docker-backed test in
        `tests/test_the_box_transmits_while_it_runs.py` proves against a real daemon rather than
        against a substituted `Popen`."""
        return self._output.take()

    def diff_paths(self, *, workspace: Workspace) -> list[str]:
        # committed changes on the branch vs base (orchestrator commits after execute)
        rc, out = self.run(
            workspace=workspace,
            command=f"git diff --name-only {workspace.base_branch}..HEAD",
            timeout=60,
        )
        return [line for line in out.splitlines() if line.strip()] if rc == 0 else []

    def publish_branch(self, *, workspace: Workspace, remote_url: str | None = None) -> None:
        # commits live in the host-side ephemeral clone; push from the HOST (never the
        # container). Prefer the authenticated bot remote; else the repo's origin URL.
        assert self._host_clone and self._repo_path, "prepare() must be called first"
        target = remote_url
        if not target:
            rc, url = _host(["git", "-C", str(self._repo_path), "remote", "get-url", "origin"])
            if rc != 0:
                raise RuntimeError(f"could not resolve origin remote: {url}")
            target = url.strip()
        # --force: the bot's dedicated openfactory/<id> branch, unique per job, serial execution
        # — a retry after a partial failure must overwrite, not dead-lock on non-ff.
        rc, out = _host(
            ["git", "-C", str(self._host_clone), "push", "--force", target, workspace.branch]
        )
        if rc != 0:
            raise RuntimeError(f"push failed: {_redact(out)}")

    def rebase_onto_base(
        self, *, workspace: Workspace, base: str, remote_url: str | None = None
    ) -> str:
        # commits live in the host-side clone; fetch + rebase there (never in the container).
        # "up_to_date" / "rebased" / "conflict" — see the worktree adapter for the contract.
        assert self._host_clone and self._repo_path, "prepare() must be called first"
        hc = str(self._host_clone)
        target = remote_url
        if not target:
            rc, url = _host(["git", "-C", str(self._repo_path), "remote", "get-url", "origin"])
            if rc != 0:
                raise RuntimeError(f"could not resolve origin remote: {url}")
            target = url.strip()
        rc, out = _host(["git", "-C", hc, "fetch", target, base])
        if rc != 0:
            raise RuntimeError(f"fetch failed: {_redact(out)}")
        rc, _ = _host(["git", "-C", hc, "merge-base", "--is-ancestor", "FETCH_HEAD", "HEAD"])
        if rc == 0:
            return "up_to_date"
        rc, out = _host(["git", "-C", hc, "rebase", "FETCH_HEAD"])
        if rc != 0:
            _host(["git", "-C", hc, "rebase", "--abort"])
            return "conflict"
        return "rebased"

    def cleanup(self, *, workspace: Workspace) -> None:
        if self._container:
            _host(["docker", "rm", "-f", self._container])
        if self._host_clone and self._host_clone.exists():
            shutil.rmtree(self._host_clone, ignore_errors=True)
        self._container, self._host_clone = None, None
