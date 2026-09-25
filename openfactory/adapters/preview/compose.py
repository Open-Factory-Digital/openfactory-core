"""The built-in `compose` preview runtime: an admitted plan, run on the deployment's own Docker
daemon through the compose CLI (ADR-0050 D4, D7, D10, D11; the design on #265, §5.2).

THE STEPS, AS FUNCTIONS THE WORKER'S ACTIVITIES CALL (slice 3 wires them into a workflow):

1. `materialise(unit, project)` — a FRESH work directory `<OPENFACTORY_WORK_DIR>/openfactory-pv-
   <slug>-<token>/`, the base of every repository cloned into `base/<dir>` by branch name (never a
   person's working tree), and, where the unit has a pull request, the head the forge reported
   checked out beside it as a worktree in `change/<dir>`. A work directory that exists is removed
   first, never reused: every `up` runs on trees admission is about to judge on disk.
2. `plan(layout, unit, project)` — the slice-1 pure core: the block and the compose files read
   from the base, pre-scanned, canonicalised, admitted, assembled.
3. `ComposeRuntime.up(plan)` — the admitted document written to `<workdir>/compose.yml` and run
   with `docker compose up -d --build` under a REDUCED environment (below); readiness judged by
   polling `docker compose ps`, then a settle watch, then the data commands by `exec`.
4. `watch`, `logs`, `down`, `running`, `prove`, `prune` — the rest of the port.

THE REDUCED ENVIRONMENT IS THE WHOLE OF WHAT THE COMPOSE PROCESS SEES (`reduced_env`). `PATH`, a
`HOME` and `TMPDIR` inside the work directory, the daemon's own `DOCKER_*`, `DOCKER_CONFIG` from
`OPENFACTORY_PREVIEW_DOCKER_CONFIG` (registry logins are client-side: the CLI reads them from that
directory, the daemon holds none), the preview's own URLs, and the VALUES of exactly the worker
variables the registry named for this unit's services. Nothing else: the harness credential, the
forge token, a box's `env`, the panel's preview secret never reach a process that interpolates a
file an agent's change sits beside.

READINESS IS NOT `--wait`, AND THAT WAS MEASURED. `up --wait` exits 1 the moment any one-shot
service exits 0 — which a developer's `migrate:` service does by design — so the flag reads the
commonest dev compose file as a failed stack. The runtime polls instead: an EXPOSED service is
ready when `healthy` if it declares a healthcheck, `running` otherwise (the card says which, since
the second proves less); a service that exited 0 ran and finished; ANY non-zero exit is the
failure, named, with its last lines.

ONE EDGE NETWORK PER UNIT. The document's `default` network is internal; the exposed services
join `<compose project>-edge` (internal too, on the compose stack) under their host labels, and
the worker — which holds the socket — connects the panel's container to it at `up` and
disconnects it at `down`. No network is shared between two units, so one unit's services can
neither resolve nor reach another's.

ON ONE MACHINE (the loopback reach, §7.2) the panel is a host process that cannot use the daemon's
DNS, so each exposed service is published on 127.0.0.1 — and only there — on a port derived from
its host label (`preview.loopback_port`, the router's own derivation). A derived port something
already answers on fails the start by name. Docker forwards no port into an internal network, so
that edge is a bridge that masquerades nothing, and what a container on it can reach is MEASURED
when the preview starts (`measure_reach`) and said on its card, whichever way it falls.

EVERY DOCKER AND GIT CALL GOES THROUGH `_host`, one module-level seam, so a test fakes the daemon
the way `adapters/sandbox/container.py::_host` is faked, and a mutation that widens what a call
receives is visible to the test that watches that one door.
"""

from __future__ import annotations

import http.server
import json
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

import yaml
from pydantic import BaseModel, ConfigDict

from openfactory import namespace, preview
from openfactory.adapters.preview.base import PREFIX, refusals
from openfactory.preview.assemble import url_var
from openfactory.preview.plan import (
    Layout,
    PreviewPlan,
    PreviewUp,
    Refused,
    RunningPreview,
    Tree,
    Unit,
)
from openfactory.preview.read import PRODUCT_REMEDY, REMEDY
from openfactory.preview.reap import MAX_TTL_HOURS

log = logging.getLogger("openfactory.preview.compose")

#: The image the daemon runs to remove what a container left owned by root in a bind-mounted tree,
#: and to check the work directory is the same directory on both sides of the socket. Small,
#: official, and nothing of the factory's is mounted into it but the directory being judged.
UTILITY_IMAGE = "alpine:3"

#: The shared network previews once lived on (one preview at a time). Every unit has its own now;
#: `doctor` says to remove this one once.
LEGACY_NETWORK = "openfactory-preview"

#: The unit token a PROOF runs as: the base product, of no card. No tracker numbers a card 0, so
#: the name can never alias a real card's preview.
PROVE_TOKEN = "0"

#: How a unit's edge network is made on the LOOPBACK reach. Docker forwards no published port into
#: an `internal` network, so the edge a service is published from cannot be one; it is a bridge
#: that MASQUERADES NOTHING instead — a packet leaving it carries its private address and, where
#: the host routes it like a Linux Engine does, gets no reply. That is a property of the daemon, not
#: of this line, which is why a loopback preview MEASURES what it can reach (`measure_reach`) and
#: its card says what was measured. Measured on Docker Desktop 29.1.3 (2026-09-24): its userland
#: network answers anyway — the internet and this machine's own loopback both reached.
LOOPBACK_EDGE_OPTS = ("--opt", "com.docker.network.bridge.enable_ip_masquerade=false")

#: The public address a loopback preview's network is asked to reach when it starts: by NUMBER, so
#: no resolver is part of the answer, and one that answers plain HTTP on port 80. Any HTTP answer
#: at all — a redirect included — is the internet reached.
EGRESS_PROBE = "http://1.1.1.1/"

#: The name Docker Desktop gives every container for the machine it runs on. A Linux Engine gives
#: none unless a container is started with `host-gateway`, which admission drops from a preview.
HOST_ALIAS = "host.docker.internal"



# ── the one door to the daemon and to git ────────────────────────────────────────────────────────


class Ran(NamedTuple):
    """What one command answered. `rc` 124 = it did not finish in time; 127 = not on PATH."""

    rc: int
    out: str
    err: str

    @property
    def said(self) -> str:
        """The last meaningful line it printed — what a sentence quotes."""
        lines = [ln.strip() for ln in f"{self.out}\n{self.err}".splitlines() if ln.strip()]
        return lines[-1] if lines else f"it exited {self.rc} and said nothing"

    def tail(self, n: int = 12) -> str:
        lines = [ln.rstrip() for ln in f"{self.out}\n{self.err}".splitlines() if ln.strip()]
        return "\n".join(lines[-n:])


def _host(argv: Sequence[str], *, env: Mapping[str, str] | None = None, timeout: float = 120,
          input: str | None = None) -> Ran:
    """Run one command on the worker and answer what it said. NEVER RAISES: a missing binary, a
    wall and an OS error are answers with a code, because every caller turns them into a sentence
    on a card rather than a crash in an activity."""
    try:
        done = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout,
                              env=dict(env) if env is not None else None, input=input,
                              check=False)
    except FileNotFoundError:
        return Ran(127, "", f"{argv[0]}: not found on PATH")
    except subprocess.TimeoutExpired:
        return Ran(124, "", f"`{' '.join(argv[:3])} …` did not finish within {int(timeout)}s")
    except OSError as exc:
        return Ran(126, "", f"{argv[0]} could not be run: {exc}")
    return Ran(done.returncode, done.stdout or "", done.stderr or "")


def _redact(text: str) -> str:
    """A fetch URL may carry a credential as an argument; it never reaches a sentence."""
    return re.sub(r"(https?://)[^@/\s]+@", r"\1***@", text or "")


# ── the deployment's facts ──────────────────────────────────────────────────────────────────────


def work_root() -> str:
    """Where every unit's work directory lives: `OPENFACTORY_WORK_DIR`, bound at the SAME absolute
    path on both sides of the socket on the compose stack (a path the daemon resolves for a bind
    mount must be the path the worker wrote), else the temporary directory."""
    root = (os.environ.get("OPENFACTORY_WORK_DIR") or "").strip() or tempfile.gettempdir()
    return os.path.realpath(root)


def docker_config() -> str:
    """The directory the compose CLI reads registry logins from — the operator's, for previews:
    `OPENFACTORY_PREVIEW_DOCKER_CONFIG`, else `~/.docker` (the one-machine kind, where Docker
    Desktop also keeps its compose plugin there)."""
    named = (os.environ.get("OPENFACTORY_PREVIEW_DOCKER_CONFIG") or "").strip()
    return named or os.path.expanduser("~/.docker")


def reach_kind() -> str:
    """How the panel reaches an exposed service: `network` (it joins the unit's edge network) or
    `loopback` (a port on 127.0.0.1 of this host). `OPENFACTORY_PREVIEW_REACH`, default network —
    read by `preview.reach`, the one reader the router shares."""
    return preview.reach()


def loopback_range() -> tuple[int, int] | None:
    """`OPENFACTORY_PREVIEW_PORTS=lo-hi`, or None when it is not set as one (`preview.ports`)."""
    return preview.ports()


def panel_name() -> str:
    """The panel's container on this daemon (`OPENFACTORY_PANEL_CONTAINER`), which the worker
    connects to each unit's edge network so the panel can proxy to it."""
    return (os.environ.get("OPENFACTORY_PANEL_CONTAINER") or "").strip()


def panel_address() -> tuple[str, int | None]:
    """(scheme, port) previews are served on: the panel's own, since the panel proxies them."""
    from urllib.parse import urlsplit

    url = urlsplit((os.environ.get("OPENFACTORY_PANEL_URL") or "").strip())
    scheme = url.scheme if url.scheme in ("http", "https") else "http"
    try:
        port = url.port
    except ValueError:
        port = None
    return scheme, port


def log_root() -> str:
    """`OPENFACTORY_LOG_DIR` — the journal directory the panel tails — else beside the registry."""
    named = (os.environ.get("OPENFACTORY_LOG_DIR") or "").strip()
    if named:
        return os.path.expanduser(named)
    from openfactory.registry import ProjectRegistry

    return str(ProjectRegistry().path.parent / "logs")


def workdir_for(project: str, token: str, *, root: str | None = None) -> str:
    """`<work root>/openfactory-pv-<slug>-<token>` — named after the unit's compose project, so
    the reaper can derive it from a name rather than read it from a label."""
    return os.path.join(root or work_root(), preview.compose_project(project, token))


def workdir_is_ours(path: str) -> bool:
    """Whether `path` is a directory this runtime made and may therefore delete.

    A label is metadata anybody with the daemon can write, so what is checked is what
    `materialise` itself makes: a real directory (not a link) named `openfactory-pv-…`, DIRECTLY
    under the work root. Anything else is left where it is, whatever names it."""
    if not path:
        return False
    p = Path(path)
    try:
        return (p.name.startswith(PREFIX) and not p.is_symlink() and p.is_dir()
                and p.parent.resolve() == Path(work_root()).resolve())
    except OSError:
        return False


def edge_of(compose_project: str) -> str:
    """A unit's edge network, derived from its compose project — `down` has nothing else."""
    return f"{compose_project}-edge"


def log_dir_for(project: str, token: str, *, root: str | None = None) -> str:
    """`<log root>/preview--<slug>--<token>/`, one `<service>.log` per service."""
    return os.path.join(root or log_root(), f"preview--{preview.slug(project) or 'project'}--"
                                            f"{token}")


def _base_env(home: str) -> dict[str, str]:
    """What any compose or docker call needs to find itself and the daemon, and nothing else."""
    env = {k: os.environ[k] for k in ("PATH", "DOCKER_HOST", "DOCKER_CERT_PATH",
                                      "DOCKER_TLS_VERIFY") if os.environ.get(k)}
    env["HOME"] = home
    env["TMPDIR"] = home
    env["DOCKER_CONFIG"] = docker_config()
    return env


def reduced_env(plan: PreviewPlan, *, workdir: str | None = None) -> dict[str, str]:
    """The environment `docker compose up` runs in — the whole of it (see the module docstring).

    The VALUES of registry-named variables are read here, from the worker's environment, and go
    nowhere but this process: the document on disk carries `${WORKER_NAME}` references, the plan
    carries names. A name the registry could never have admitted (the factory's own credentials)
    is skipped even if a plan names it."""
    from openfactory.contracts.project import preview_name_refused

    wd = workdir or plan.workdir
    env = {k: os.environ[k] for k in ("PATH", "DOCKER_HOST", "DOCKER_CERT_PATH",
                                      "DOCKER_TLS_VERIFY") if os.environ.get(k)}
    env["HOME"] = os.path.join(wd, "home")
    env["TMPDIR"] = os.path.join(wd, "tmp")
    env["DOCKER_CONFIG"] = docker_config()
    for svc in plan.expose:
        env[f"OPENFACTORY_PREVIEW_URL_{url_var(svc)}"] = plan.urls.get(svc, "")
        env[f"OPENFACTORY_PREVIEW_INTERNAL_URL_{url_var(svc)}"] = plan.internal_urls.get(svc, "")
    for names in (*plan.env_names.values(), *plan.build_arg_names.values()):
        for worker in names.values():
            if worker in os.environ and not preview_name_refused(worker):
                env[worker] = os.environ[worker]
    return env


# ── the loopback reach: what is taken, and what a preview can reach ──────────────────────────────


def _listening(port: int) -> bool:
    """Whether something already answers on 127.0.0.1:`port`. A CONNECT, not a bind: a listener on
    every interface answers here too and would take the port from the daemon just the same, and a
    connect leaves nothing behind that could itself hold the port for a moment."""
    try:
        with socket.create_connection((preview.LOOPBACK_ADDRESS, port), timeout=1):
            return True
    except OSError:
        return False


def _holder(port: int, env: Mapping[str, str]) -> str:
    """Who holds a published port on this daemon, in words — a preview by its project and unit,
    another container by its name — or "" when no container does (another program on the machine
    does)."""
    r = _host(["docker", "ps", "--filter", f"publish={port}", "--format",
               "{{.Names}}\t" + '{{.Label "' + preview.LABEL_PROJECT + '"}}\t'
               + '{{.Label "' + preview.LABEL_UNIT + '"}}\t'
               + '{{.Label "com.docker.compose.service"}}'], env=env, timeout=30)
    for line in r.out.splitlines() if r.rc == 0 else []:
        name, project, unit, service = (line.split("\t") + ["", "", "", ""])[:4]
        if project and unit:
            return f"the preview of {project} {unit} (`{service}`)"
        if name:
            return f"the container `{name}`"
    return ""


def taken(plan: PreviewPlan, service: str, port: int, *, env: Mapping[str, str]) -> str:
    """The sentence for a derived port somebody else holds — BY NAME: which service, which port,
    the name it is derived from, and who holds it, so the remedy is the right one."""
    label = preview.host_label(plan.project, plan.unit.token, service)
    head = (f"`{service}`'s port {port} on {preview.LOOPBACK_ADDRESS} — derived from its name "
            f"`{label}` — is")
    who = _holder(port, env)
    if who:
        return (f"{head} held by {who}: stop that one, or widen OPENFACTORY_PREVIEW_PORTS so the "
                f"two names derive different ports.")
    return (f"{head} in use by another program on this machine: stop it, or move "
            f"OPENFACTORY_PREVIEW_PORTS to a range nothing else listens on.")


class Reached(NamedTuple):
    """What a container on a loopback preview's network reached. None: not measured, with why."""

    internet: bool | None
    loopback: bool | None
    why: str = ""


class _Answer(http.server.BaseHTTPRequestHandler):
    """Answers every GET with the probe's token — which only a request that really reached this
    listener can carry back."""

    token = ""

    def do_GET(self):  # noqa: N802 — the stdlib's name
        body = self.token.encode()
        self.send_response(200)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def measure_reach(network: str, *, env: Mapping[str, str]) -> Reached:
    """What a container on `network` reaches, MEASURED (§7.2): the internet (`EGRESS_PROBE`, by
    number), and this machine's own loopback through `HOST_ALIAS` — a listener this call opens on
    127.0.0.1 for the length of the probe, answering a token nobody else knows.

    A throwaway `alpine:3` with no capability and no way to gain one, on the unit's network and
    nothing else — where a preview's exposed services are — so what it reaches is what they reach.
    Never raises: a probe that could not run is `None`, and the card says it was not measured
    rather than claiming anything."""
    token = secrets.token_hex(12)
    handler = type("_Token", (_Answer,), {"token": token})
    try:
        server = http.server.ThreadingHTTPServer((preview.LOOPBACK_ADDRESS, 0), handler)
    except OSError as exc:
        return Reached(None, None, f"no listener could be opened on this machine's loopback: "
                                   f"{exc}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        script = (f'if wget -S -q -T 5 -O /dev/null {EGRESS_PROBE} 2>&1 | grep -q "HTTP/"; '
                  f'then echo internet=yes; else echo internet=no; fi; '
                  f'if wget -q -T 5 -O - http://{HOST_ALIAS}:{port}/ 2>/dev/null '
                  f'| grep -q {token}; then echo loopback=yes; else echo loopback=no; fi')
        ran = _host(["docker", "run", "--rm", "--network", network, "--cap-drop", "ALL",
                     "--security-opt", "no-new-privileges", "--label",
                     f"{preview.LABEL}.probe={network}", UTILITY_IMAGE, "sh", "-c", script],
                    env=env, timeout=120)
    finally:
        server.shutdown()
        server.server_close()
    said = dict(ln.strip().split("=", 1) for ln in ran.out.splitlines() if "=" in ln)
    if ran.rc or set(said) != {"internet", "loopback"}:
        return Reached(None, None, f"the probe on `{network}` could not run: {ran.said}")
    return Reached(said["internet"] == "yes", said["loopback"] == "yes")


def measure_reach_now(*, env: Mapping[str, str] | None = None) -> Reached:
    """`measure_reach` on a network made for the purpose, the way a unit's edge is made on the
    loopback reach, and removed after — what `doctor` asks when no preview is running."""
    env = env if env is not None else _base_env(work_root())
    name = f"{PREFIX}reach-probe-{secrets.token_hex(4)}"
    made = _host(["docker", "network", "create", *LOOPBACK_EDGE_OPTS, "--label",
                  f"{preview.LABEL}.probe={name}", name], env=env, timeout=60)
    if made.rc:
        return Reached(None, None, f"a network to measure on could not be made: {made.said}")
    try:
        return measure_reach(name, env=env)
    finally:
        _host(["docker", "network", "rm", name], env=env, timeout=60)


def reach_notes(r: Reached) -> tuple[str, ...]:
    """What a card says a loopback preview can reach — whichever way the measurement fell, and
    that it was not measured when it could not be."""
    if r.internet is None:
        return (f"what this preview can reach outside itself could not be measured when it "
                f"started ({r.why}) — nothing here claims it reaches nothing.",)
    out = [f"this preview can reach the internet: measured when it started, a container on its "
           f"network reached {EGRESS_PROBE} — on one machine a preview's network is not closed "
           f"the way the compose stack's is." if r.internet else
           f"measured when it started, a container on this preview's network did not reach the "
           f"internet ({EGRESS_PROBE}) — a measurement of this machine, not a promise."]
    if r.loopback:
        out.append(f"its services can also reach what listens on this machine's own loopback, "
                   f"through {HOST_ALIAS} — the panel, the engine and other previews included "
                   f"(measured when it started).")
    return tuple(out)


# ── 1. materialise ───────────────────────────────────────────────────────────────────────────────


class TreeSource(BaseModel):
    """Where one repository of a unit is checked out FROM. `source` is a local path — the worker's
    `RepoCache` snapshot on a hosted forge, the person's repository on the local one — and is
    cloned by BRANCH NAME, so a person's uncommitted work is never in a preview. `branch`/`head`
    are the unit's pull request in this repository, `head` the sha the FORGE reported open (never
    the branch's tip); empty for a repository that contributes its base only."""

    model_config = ConfigDict(frozen=True)

    repo: str
    dir: str
    source: str
    base_branch: str = ""
    #: tokenless, for a row that materialises the trees elsewhere
    clone_url: str = ""
    branch: str = ""
    head: str = ""
    pr_url: str = ""


def _git(*args: str, timeout: float = 600) -> Ran:
    return _host(["git", *args], env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, timeout=timeout)


def _default_branch(source: str) -> str:
    """The branch a repository's base is, when nobody named one: its remote's HEAD, else `main` or
    `master` when it has one — never whatever a person happens to have checked out."""
    r = _git("-C", source, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if r.rc == 0 and r.out.strip():
        return r.out.strip().split("/", 1)[-1]
    for name in ("main", "master"):
        if _git("-C", source, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}").rc == 0:
            return name
    return ""


def sources_of(project) -> list[TreeSource]:
    """The project's own repository at its base branch — what a proof needs, and the base every
    single-repository unit starts from."""
    from openfactory.factory import looks_like_a_clone_url, resolve_repo_path
    from openfactory.loader import load_manifest_base_branch

    forge = getattr(project, "forge", None)
    repo = (getattr(forge, "repo", "") or "") or project.name
    short = re.sub(r"[^A-Za-z0-9._-]+", "-", repo.rstrip("/").rsplit("/", 1)[-1]).strip(".-")
    source = str(resolve_repo_path(project))
    raw = (project.repo_path or "").strip()
    return [TreeSource(repo=repo, dir=short or "app", source=source,
                       base_branch=load_manifest_base_branch(project, default=""),
                       clone_url=raw if looks_like_a_clone_url(raw) else "")]


def source_for(project, repo: str, *, dir: str = "") -> TreeSource:
    """Another repository of a product, at its base — cloned from the checkout its OWN cards are
    worked from (C-18: `card_repo._runner_view`, a cache key of its own), so two repositories of
    one project never share a tree. Its base is the repository's own default branch: the
    registry's base branch is the project's own repository's."""
    from openfactory.factory import looks_like_a_clone_url, resolve_repo_path
    from openfactory.preview.product import short
    from openfactory.runtime.card_repo import _runner_view

    view, key = _runner_view(project, f"{repo}#1")
    source = str(resolve_repo_path(view, cache_key=key))
    raw = (view.repo_path or "").strip()
    return TreeSource(repo=repo, dir=dir or short(repo) or "app", source=source,
                      clone_url=raw if looks_like_a_clone_url(raw) else "")


def _remove_workdir(workdir: str) -> list[str]:
    """Remove a unit's work directory — ONLY when `workdir_is_ours` says so — including what a
    container left behind owned by root in a bind-mounted tree (the daemon removes that, since the
    worker's user may not)."""
    if not workdir_is_ours(workdir):
        if workdir and os.path.lexists(workdir):
            log.warning("OPENFACTORY_PREVIEW %s is not a work directory this runtime made — left "
                        "where it is", workdir)
        return []
    shutil.rmtree(workdir, ignore_errors=True)
    if os.path.lexists(workdir):
        _host(["docker", "run", "--rm", "-v", f"{workdir}:/w", UTILITY_IMAGE, "find", "/w",
               "-mindepth", "1", "-maxdepth", "1", "-exec", "rm", "-rf", "{}", "+"], timeout=300)
        shutil.rmtree(workdir, ignore_errors=True)
    if os.path.lexists(workdir):
        return [f"part of the work directory {workdir} (the rest could not be removed)"]
    return [f"the work directory {workdir}"]


def materialise(unit: Unit, project=None, *, trees: Sequence[TreeSource] | None = None,
                fetch: Mapping[str, str] | None = None, root: str | None = None,
                more: Callable[[Layout], Sequence[TreeSource] | Refused] | None = None,
                context: str = "") -> Layout | Refused:
    """The unit's trees on disk, fresh, as a `Layout` — or every reason they are not.

    `trees` defaults to the project's own repository at its base (`sources_of`): a proof, or a
    unit with no pull request anywhere. `fetch` maps a repository to the URL its pull request's
    branch is fetched from — the forge's authenticated push remote, passed as an ARGUMENT so git
    never stores it; the clone's own origin stays the tokenless source.

    A PRODUCT'S LAYOUT IS KNOWN ONLY ONCE ITS SHAPE IS READ: which sibling repositories a compose
    file reaches (`../api`) is in the file, on the base of the repository that holds it. `more` is
    asked, once `trees` are on disk, for the rest — or refuses, and nothing more is cloned.
    `context` is the directory of the context repository's tree, carried on the layout."""
    workdir = workdir_for(unit.project, unit.token, root=root)
    if os.path.lexists(workdir):
        _remove_workdir(workdir)
        if os.path.lexists(workdir):
            return Refused(reasons=(f"the work directory {workdir} exists and could not be "
                                    f"removed — a preview never reuses a checkout.",))
    sources = list(trees) if trees is not None else sources_of(project)
    for sub in ("base", "change", "home", "tmp"):
        os.makedirs(os.path.join(workdir, sub), exist_ok=True)
    out: dict[str, Tree] = {}
    try:
        _checkout(sources, out, workdir=workdir, fetch=fetch)
        if more is not None:
            rest = more(Layout(workdir=workdir, trees=dict(out), context=context))
            if isinstance(rest, Refused):
                _remove_workdir(workdir)
                return rest
            _checkout([s for s in rest if s.dir not in out], out, workdir=workdir, fetch=fetch)
    except _Refusal as refusal:
        _remove_workdir(workdir)
        return Refused(reasons=(str(refusal),))
    return Layout(workdir=workdir, trees=out, context=context)


def _checkout(sources: Sequence[TreeSource], out: dict[str, Tree], *, workdir: str,
              fetch: Mapping[str, str] | None) -> None:
    """Clone each source's base beside the others — and its change, where it has one — into
    `out`, keyed by directory. Raises `_Refusal` with the first reason one cannot be."""
    for s in sources:
        base = os.path.join(workdir, "base", s.dir)
        branch = s.base_branch or _default_branch(s.source)
        # `--no-hardlinks`, NOT git's default: a preview container may mount the whole tree,
        # `.git` included, as root with DAC_OVERRIDE — and a hardlinked object is the SAME
        # inode as the cache's, so a write through it would reach every later job's checkout.
        r = _git("clone", "--local", "--no-hardlinks", "--quiet",
                 *(["--branch", branch] if branch else []), s.source, base)
        if r.rc:
            raise _Refusal(f"`{s.repo}`'s base branch `{branch or 'HEAD'}` could not be "
                           f"checked out: {_redact(r.said)}")
        base_commit = _git("-C", base, "rev-parse", "HEAD").out.strip()
        tree = Tree(repo=s.repo, dir=s.dir, clone_url=s.clone_url,
                    base_branch=branch or _git("-C", base, "rev-parse", "--abbrev-ref",
                                               "HEAD").out.strip(),
                    base_commit=base_commit)
        if s.branch:
            tree = _change(s, tree, base=base, workdir=workdir,
                           url=(fetch or {}).get(s.repo) or s.source)
        out[s.dir] = tree


class _Refusal(Exception):
    pass


def _change(s: TreeSource, tree: Tree, *, base: str, workdir: str, url: str) -> Tree:
    """The pull request's head beside the base, as a worktree of the same clone — one object
    store, two working trees — and the change's OWN diff, merge base to head."""
    r = _git("-C", base, "fetch", "--quiet", "--no-tags", url,
             f"+{s.branch}:refs/remotes/origin/{s.branch}")
    if r.rc:
        raise _Refusal(f"the pull request's branch `{s.branch}` could not be fetched from "
                       f"`{s.repo}`: {_redact(r.said)}")
    head = s.head or _git("-C", base, "rev-parse", f"refs/remotes/origin/{s.branch}").out.strip()
    if _git("-C", base, "cat-file", "-e", f"{head}^{{commit}}").rc:
        raise _Refusal(f"`{s.repo}`'s pull request was reported open at {head[:12]}, which is not "
                       f"on its branch `{s.branch}` any more — rebuild once the forge has caught "
                       f"up.")
    change = os.path.join(workdir, "change", s.dir)
    r = _git("-C", base, "worktree", "add", "--quiet", "--detach", change, head)
    if r.rc:
        raise _Refusal(f"the change of `{s.repo}` could not be checked out: {r.said}")
    merge_base = _git("-C", base, "merge-base", tree.base_commit, head).out.strip()
    diff = _git("-C", base, "-c", "core.quotepath=off", "diff", "--name-only",
                f"{merge_base}..{head}")
    paths = tuple(p for p in diff.out.splitlines() if p.strip())
    return tree.model_copy(update=dict(merge_base=merge_base, branch=s.branch, change_commit=head,
                                       pr_url=s.pr_url, diff_paths=paths))


# ── 2. plan ─────────────────────────────────────────────────────────────────────────────────────


def _as_run(argv, *, capture_output=True, text=True, env=None, timeout=120, check=False):
    """`read.canonicalise`'s `run` seam, routed through `_host` — the compose CLI is a docker
    call like every other."""
    r = _host(list(argv), env=env, timeout=timeout)
    return subprocess.CompletedProcess(list(argv), r.rc, r.out, r.err)


def slug_twins(project: str, names: Sequence[str]) -> list[str]:
    """The OTHER projects whose names slug like this one's — a compose project, a host and a
    cookie cannot tell them apart, so a preview of either is refused until one is renamed."""
    mine = preview.slug(project)
    return sorted(n for n in names if n != project and preview.slug(n) == mine)


def _product_shape(layout: Layout, project):
    """The product's `ProductShape`, read from the context repository's base tree in `layout` —
    or every reason it will not be used: the file unreadable, the product module not agreeing with
    it any more, no `preview:` in it, a tree on disk that is not the member its directory names,
    or a source whose own manifest declares a second shape."""
    from openfactory.preview import product
    from openfactory.product.config import resolve_product_link

    docs, error = product.read_docs(layout.root(layout.context, "base"))
    if docs is None:
        return Refused(reasons=(f"the product's shape could not be read: {error}.",))
    link = resolve_product_link(project=project, docs=docs)
    if not link.active:
        return Refused(reasons=(f"the product module is off — {link.reason}",))
    context = str(getattr(getattr(project, "product", None), "docs_repo", "") or link.docs_repo)
    shape_ = product.shape_of(docs, context=context)
    if shape_ is None:
        return Refused(reasons=(f"`{product.PRODUCT_YAML}` on the context repository's base "
                                f"branch declares no `preview:`.",))
    if isinstance(shape_, Refused):
        return shape_
    reasons = product.strangers(layout, shape_)
    two = product.both_declared(layout, manifests=(getattr(project, "manifest_path", ""),
                                                   namespace.MANIFEST))
    if two:
        reasons.append(two)
    return Refused(reasons=tuple(reasons)) if reasons else shape_


def plan(layout: Layout, unit: Unit, project, *, cfg=None, policy=None, now: float | None = None,
         prove: bool = False, others: Sequence[str] | None = None) -> PreviewPlan | Refused:
    """The unit's plan, from the BASE tree's block and compose files — or every reason not.

    `cfg` defaults to the manifest's `preview:` read from the base checkout (never the change's);
    `policy` to the registry's. `others` are the deployment's other project names, for the slug
    refusal (read from the registry when not given)."""
    from openfactory.contracts.project import PreviewPolicy
    from openfactory.preview.assemble import assemble
    from openfactory.preview.read import shape

    shape_tree = next(iter(layout.trees), "")
    if not shape_tree:
        return Refused(reasons=("the unit has no repository checked out.",))
    if others is None:
        try:
            from openfactory.registry import ProjectRegistry

            others = [p.name for p in ProjectRegistry().list()]
        except Exception as exc:  # noqa: BLE001 — an unreadable registry refuses nothing extra
            log.warning("could not read the registry for slug collisions (%s)", exc)
            others = []
    twins = slug_twins(project.name, others)
    if twins:
        return Refused(reasons=(f"`{project.name}` and {', '.join(f'`{t}`' for t in twins)} share "
                                f"the name `{preview.slug(project.name)}` in a preview's host and "
                                f"compose project — rename one with `openfactory project add` "
                                f"under a distinct name.",))
    remedy = REMEDY
    if layout.context:
        # A PRODUCT'S SHAPE, read from the context repository's BASE tree in this layout — the
        # same checkout the rest of the unit was materialised beside, never the module's cache —
        # and every tree re-judged against the membership it declares (§6.3, §8)
        found_shape = _product_shape(layout, project)
        if isinstance(found_shape, Refused):
            return found_shape
        cfg, shape_tree, remedy = found_shape.config(), found_shape.shape_dir, PRODUCT_REMEDY
    if cfg is None:
        from openfactory.loader import load_manifest

        try:
            manifest = load_manifest(project, repo_root=Path(layout.root(shape_tree, "base")))
        except Exception as exc:  # noqa: BLE001 — an unreadable manifest is a refusal, said
            return Refused(reasons=(f"the manifest on `{layout.trees[shape_tree].repo}`'s base "
                                    f"branch could not be read: {str(exc).splitlines()[0]}",))
        cfg = getattr(manifest, "preview", None)
    if cfg is None:
        return Refused(reasons=(f"`{layout.trees[shape_tree].repo}` declares no `preview:` on its "
                                f"base branch — a preview is the product's own compose file, named "
                                f"by the `preview:` block of `.openfactory/project.yaml` "
                                f"(docs/project.yaml.example shows it).",))
    policy = policy or getattr(project, "preview", None) or PreviewPolicy()
    found = shape(layout, cfg, tree=shape_tree, run=_as_run,
                  of="this product" if layout.context else "this preview", remedy=remedy)
    if isinstance(found, Refused):
        return found
    scheme, port = panel_address()
    now = time.time() if now is None else now
    return assemble(found.doc, cfg=cfg, unit=unit, layout=layout, policy=policy,
                    shape_tree=shape_tree, manifest_path=project.manifest_path,
                    domain=preview.domain(), scheme=scheme, public_port=port,
                    reach="loopback" if reach_kind() == "loopback" else "network",
                    loopback_range=loopback_range(),
                    expires_at=int(now) + policy.hours * 3600, prove=prove)


# ── 3–4. the runtime ─────────────────────────────────────────────────────────────────────────────

#: One row per container of a preview, TAB-separated: a label value never holds a tab.
_PS_FIELDS = ("name", "state", "status", "cp", "service", "project", "unit", "expires", "exposed",
              "created")
_PS_FORMAT = "\t".join([
    "{{.Names}}", "{{.State}}", "{{.Status}}",
    '{{.Label "com.docker.compose.project"}}', '{{.Label "com.docker.compose.service"}}',
    *('{{.Label "' + k + '"}}' for k in (preview.LABEL_PROJECT, preview.LABEL_UNIT,
                                          preview.LABEL_EXPIRES, preview.LABEL_EXPOSED)),
    "{{.CreatedAt}}",
])


def _epoch(created: str) -> int:
    """`2026-09-24 01:13:10 +0000 UTC` → seconds; 0 when it is not that shape."""
    try:
        return int(datetime.strptime(created[:25], "%Y-%m-%d %H:%M:%S %z").timestamp())
    except ValueError:
        return 0


def _compose_rows(text: str) -> list[dict]:
    """`docker compose ps --format json`: one object per line on the pinned plugin, an array on
    older ones — both read."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        if text.startswith("["):
            rows = json.loads(text)
            return [r for r in rows if isinstance(r, dict)]
        return [json.loads(ln) for ln in text.splitlines() if ln.strip().startswith("{")]
    except ValueError:
        return []


def _has_healthcheck(svc: dict) -> bool:
    check = svc.get("healthcheck") or {}
    return bool(check) and not check.get("disable") and check.get("test") not in (["NONE"], "NONE")


def _registry_of(image: str) -> str:
    first = image.split("/", 1)[0]
    return first if "/" in image and ("." in first or ":" in first or first == "localhost") \
        else "docker.io"


class ComposeRuntime:
    """The `compose` row. `clock`/`sleep`/`poll_seconds`/`settle_seconds` exist so readiness is
    testable with a faked daemon and no wall-clock waiting."""

    def __init__(self, *, reach: str | None = None, panel_container: str | None = None,
                 start_timeout: float = 30 * 60, settle_seconds: float = 60,
                 poll_seconds: float = 2, log_root: str | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.reach = reach or reach_kind()
        self.panel_container = panel_container if panel_container is not None else panel_name()
        self.start_timeout = float(start_timeout)
        self.settle_seconds = float(settle_seconds)
        self.poll_seconds = float(poll_seconds)
        self.log_root = log_root
        self.clock, self.sleep = clock, sleep

    # ── what this deployment lacks ──

    def prerequisites(self) -> list[str]:
        home = work_root()
        env = _base_env(home)
        version = _host(["docker", "version", "--format", "{{.Server.Version}}"], env=env,
                        timeout=30)
        if version.rc:
            # everything below is downstream of the daemon; one sentence, not six
            return [f"the Docker daemon does not answer this worker: {version.said} — previews "
                    f"run on the daemon the worker reaches through its socket"]
        out: list[str] = []
        plugin = _host(["docker", "compose", "version", "--short"], env=env, timeout=30)
        if plugin.rc:
            out.append(f"the compose plugin is not usable with DOCKER_CONFIG={docker_config()}: "
                       f"{plugin.said} — the worker image carries it at /usr/local/lib/docker/"
                       f"cli-plugins; a worker on the host needs Docker Desktop's, or the "
                       f"`docker-compose-plugin` package")
        if self.reach == "network":
            if not self.panel_container:
                out.append("OPENFACTORY_PANEL_CONTAINER is not set — the panel cannot join a "
                           "preview's network, so nobody could open one (`openfactory-panel` on "
                           "the compose stack)")
            else:
                seen = _host(["docker", "inspect", "--format", "{{.State.Running}}",
                              self.panel_container], env=env, timeout=30)
                if seen.rc or seen.out.strip() != "true":
                    out.append(f"the panel container `{self.panel_container}` "
                               f"(OPENFACTORY_PANEL_CONTAINER) is not running on this daemon")
        elif self.reach == "loopback":
            if loopback_range() is None:
                out.append("OPENFACTORY_PREVIEW_PORTS is not set as `lo-hi` — a loopback preview "
                           "needs the ports its services may be published on (e.g. 42000-42999)")
        else:
            out.append(f"OPENFACTORY_PREVIEW_REACH={self.reach!r} is neither `network` nor "
                       f"`loopback`")
        if not preview.domain():
            out.append("OPENFACTORY_PREVIEW_DOMAIN is not set — a preview has no host to be opened "
                       "at (`preview.localhost` needs no DNS on one machine)")
        out += self._work_dir_is_shared(home, env)
        return out

    def _work_dir_is_shared(self, root: str, env: dict) -> list[str]:
        """The marker check: a file the worker writes under the work root must be the file the
        DAEMON sees there, or every bind mount of a preview is an empty directory."""
        name = f".openfactory-preview-probe-{secrets.token_hex(4)}"
        token = secrets.token_hex(8)
        try:
            os.makedirs(root, exist_ok=True)
            with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
                fh.write(token)
        except OSError as exc:
            return [f"the work directory {root} (OPENFACTORY_WORK_DIR) cannot be written: {exc}"]
        try:
            seen = _host(["docker", "run", "--rm", "-v", f"{root}:/w:ro", UTILITY_IMAGE, "cat",
                          f"/w/{name}"], env=env, timeout=180)
        finally:
            try:
                os.remove(os.path.join(root, name))
            except OSError:
                pass
        if seen.rc == 0 and seen.out.strip() == token:
            return []
        if seen.rc and ("Unable to find image" in seen.err or "pull" in seen.err.lower()):
            return [f"the check that the work directory is shared with the daemon needs "
                    f"`{UTILITY_IMAGE}`, which could not be run: {seen.said}"]
        return [f"the work directory {root} (OPENFACTORY_WORK_DIR) is not the same directory on "
                f"the daemon's side of the socket — bind it at the same absolute path on both "
                f"sides, or every preview mounts an empty tree"]

    # ── bringing a plan up ──

    def log_dir(self, plan: PreviewPlan) -> str:
        return log_dir_for(plan.project, plan.unit.token, root=self.log_root)

    def _compose(self, compose_project: str, workdir: str) -> list[str]:
        return ["docker", "compose", "-p", compose_project, "--project-directory", workdir,
                "-f", os.path.join(workdir, "compose.yml"), "--env-file", os.devnull]

    def up(self, plan: PreviewPlan) -> PreviewUp:
        return self._up(plan, connect_panel=True)

    def _up(self, plan: PreviewPlan, *, connect_panel: bool) -> PreviewUp:
        why = refusals(plan)
        if why:
            return PreviewUp(ok=False, why="refused before anything ran: " + " ".join(why))
        if not workdir_is_ours(plan.workdir):
            return PreviewUp(ok=False, why=f"refused before anything ran: {plan.workdir} is not a "
                                           f"work directory this runtime made.")
        log_dir = self.log_dir(plan)
        os.makedirs(log_dir, exist_ok=True)
        env = reduced_env(plan)
        for sub in ("home", "tmp"):
            os.makedirs(os.path.join(plan.workdir, sub), exist_ok=True)
        with open(os.path.join(plan.workdir, "compose.yml"), "w", encoding="utf-8") as fh:
            yaml.safe_dump(plan.doc, fh, sort_keys=False)

        def failed(why: str) -> PreviewUp:
            return PreviewUp(ok=False, why=why, log_dir=log_dir)

        if plan.reach == "loopback":
            # A COLLISION FAILS THE START BY NAME (§7.2, §8), before anything is built: a port the
            # name derives that something already answers on would otherwise be minutes of build
            # and then docker's own sentence about a port nobody chose.
            held = [taken(plan, svc, port, env=_base_env(work_root()))
                    for svc, port in sorted(plan.loopback_ports.items()) if _listening(port)]
            if held:
                return failed(" ".join(held))
        if "edge" in (plan.doc.get("networks") or {}):
            problem = self._edge(plan, env, connect_panel=connect_panel)
            if problem:
                return failed(problem)
        base = self._compose(plan.compose_project, plan.workdir)
        ran = _host([*base, "up", "-d", "--build"], env=env, timeout=self.start_timeout)
        with open(os.path.join(log_dir, "build.log"), "w", encoding="utf-8") as fh:
            fh.write(ran.out + ran.err)
        if ran.rc:
            return failed(self._why_up_failed(plan, ran))
        health, problem = self._ready(plan, base, env)
        if problem:
            return failed(problem)
        problem = self._settle(plan, base, env)
        if problem:
            return failed(problem)
        problem = self._data(plan, base, env)
        if problem:
            return failed(problem)
        # ON ONE MACHINE, WHAT THE PREVIEW CAN REACH IS MEASURED, NOT CLAIMED: the edge a service
        # is published from cannot be internal, and whether its packets come back is the daemon's
        # to decide — so the card says what a container on it reached when it started.
        notes = (reach_notes(measure_reach(plan.edge_network, env=_base_env(work_root())))
                 if plan.reach == "loopback" and plan.loopback_ports else ())
        return PreviewUp(ok=True, services=dict(plan.expose), health=health,
                         images=self._images(plan, env), log_dir=log_dir, notes=notes)

    def _edge(self, plan: PreviewPlan, env: dict, *, connect_panel: bool) -> str:
        """The unit's own edge network, and the panel on it. Internal on the network reach; on
        loopback it must publish to the host, so it is a bridge that masquerades nothing."""
        edge = plan.edge_network
        opts = ["--internal"] if plan.reach == "network" else list(LOOPBACK_EDGE_OPTS)
        made = _host(["docker", "network", "create", *opts, "--label",
                      f"{preview.LABEL}={plan.compose_project}", edge], env=env, timeout=60)
        if made.rc and "already exists" not in f"{made.out}{made.err}":
            return f"the unit's network `{edge}` could not be created: {made.said}"
        if connect_panel and plan.reach == "network" and self.panel_container:
            joined = _host(["docker", "network", "connect", edge, self.panel_container], env=env,
                           timeout=60)
            if joined.rc and "already exists" not in f"{joined.out}{joined.err}":
                return (f"the panel container `{self.panel_container}` could not join `{edge}`: "
                        f"{joined.said}")
        return ""

    def _why_up_failed(self, plan: PreviewPlan, ran: Ran) -> str:
        text = f"{ran.out}\n{ran.err}"
        lowered = text.lower()
        if plan.reach == "loopback" and any(s in lowered for s in (
                "port is already allocated", "address already in use", "bind for",
                "ports are not available")):
            # the port was taken between the check and the daemon's bind: the same sentence
            for svc, port in sorted(plan.loopback_ports.items()):
                if re.search(rf":{port}\b", text):
                    return taken(plan, svc, port, env=_base_env(work_root()))
        if any(s in lowered for s in ("unauthorized", "pull access denied", "denied: requested",
                                      "authentication required")):
            for spec in (plan.doc.get("services") or {}).values():
                image = str((spec or {}).get("image") or "")
                if image and (spec or {}).get("pull_policy") == "always" and image in text:
                    return (f"`{image}` could not be pulled — run `openfactory preview login "
                            f"{_registry_of(image)}` on the deployment, or make the image public.")
        if ran.rc == 124:
            return (f"the stack did not come up within {int(self.start_timeout // 60)} minutes "
                    f"(the build log is in {self.log_dir(plan)}/build.log).")
        return f"`docker compose up` failed (exit {ran.rc}):\n{ran.tail()}"

    def _ps(self, base: list[str], env: dict) -> dict[str, dict] | None:
        r = _host([*base, "ps", "-a", "--format", "json"], env=env, timeout=60)
        if r.rc:
            return None
        return {str(row.get("Service")): row for row in _compose_rows(r.out) if row.get("Service")}

    def _tail(self, base: list[str], env: dict, svc: str) -> str:
        r = _host([*base, "logs", "--no-color", "--tail", "20", svc], env=env, timeout=60)
        return r.tail(20)

    def _ready(self, plan: PreviewPlan, base: list[str], env: dict
               ) -> tuple[dict[str, str], str]:
        """Poll `ps` until every exposed service is ready, or say which one never was."""
        services = plan.doc.get("services") or {}
        checked = {s for s in plan.expose if _has_healthcheck(services.get(s) or {})}
        deadline = self.clock() + self.start_timeout
        while True:
            rows = self._ps(base, env) or {}
            for svc in services:
                row = rows.get(svc)
                if not row or row.get("State") not in ("exited", "dead"):
                    continue
                code = int(row.get("ExitCode") or 0)
                if code != 0:
                    return {}, (f"`{svc}` exited with code {code}:\n"
                                f"{self._tail(base, env, svc)}")
                if svc in plan.expose:
                    return {}, (f"`{svc}` exited (code 0) — an exposed service has to keep "
                                f"serving:\n{self._tail(base, env, svc)}")
            waiting = []
            for svc in plan.expose:
                row = rows.get(svc) or {}
                if svc in checked:
                    if row.get("Health") != "healthy":
                        now = row.get("Health") or row.get("State") or "not created"
                        waiting.append(f"`{svc}` ({now})")
                elif row.get("State") != "running":
                    waiting.append(f"`{svc}` ({row.get('State') or 'not created'})")
            if not waiting:
                return {s: ("healthy" if s in checked else "started") for s in plan.expose}, ""
            if self.clock() >= deadline:
                return {}, (f"{', '.join(waiting)} did not become ready within "
                            f"{int(self.start_timeout // 60)} minutes.")
            self.sleep(self.poll_seconds)

    def _settle(self, plan: PreviewPlan, base: list[str], env: dict) -> str:
        """A service that starts and dies a few seconds later is the commonest way a stack looks
        up and is not: watch the exposed ones for a while before calling it live."""
        end = self.clock() + self.settle_seconds
        while self.clock() < end:
            self.sleep(self.poll_seconds)
            rows = self._ps(base, env) or {}
            for svc in plan.expose:
                row = rows.get(svc) or {}
                if row.get("State") != "running":
                    return (f"`{svc}` stopped within a minute of starting "
                            f"({row.get('State') or 'gone'}):\n{self._tail(base, env, svc)}")
        return ""

    def _data(self, plan: PreviewPlan, base: list[str], env: dict) -> str:
        """`data:` in declaration order, by `exec` into the running service — a login shell
        first, then `/bin/sh`, then, for an image with no shell, the argument list the manifest
        declared."""
        def no_shell(r: Ran) -> bool:
            said = f"{r.out}{r.err}"
            return r.rc in (126, 127) and ('"sh"' in said or '"/bin/sh"' in said
                                           or "executable file not found" in said)

        for svc, command in plan.data:
            exec_ = [*base, "exec", "-T", svc]
            if isinstance(command, list):
                ran = _host([*exec_, *command], env=env, timeout=self.start_timeout)
            else:
                ran = _host([*exec_, "sh", "-lc", command], env=env, timeout=self.start_timeout)
                if no_shell(ran):
                    ran = _host([*exec_, "/bin/sh", "-c", command], env=env,
                                timeout=self.start_timeout)
                    if no_shell(ran):
                        return (f"`{svc}` has no `sh` to run its data command in — declare "
                                f"`data:` as a list of arguments.")
            if ran.rc:
                return f"the data step of `{svc}` failed (exit {ran.rc}):\n{ran.tail()}"
        return ""

    def _images(self, plan: PreviewPlan, env: dict) -> dict[str, str]:
        """Each PULLED service's digest and when it was pulled — the card says which version of
        the base a person is looking at."""
        out: dict[str, str] = {}
        when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        for svc, spec in (plan.doc.get("services") or {}).items():
            spec = spec or {}
            image = str(spec.get("image") or "")
            if not image or spec.get("pull_policy") != "always":
                continue
            r = _host(["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image],
                      env=env, timeout=60)
            try:
                digests = json.loads(r.out) if r.rc == 0 else []
            except ValueError:
                digests = []
            digest = next((d for d in digests or [] if isinstance(d, str)), image)
            out[svc] = f"{digest} pulled {when}"
        return out

    # ── reading what runs ──

    def _containers(self, *filters: str) -> list[dict] | None:
        argv = ["docker", "ps", "-a", "--filter", f"label={preview.LABEL}"]
        for f in filters:
            argv += ["--filter", f]
        r = _host([*argv, "--format", _PS_FORMAT], env=_base_env(work_root()), timeout=60)
        if r.rc:
            log.warning("OPENFACTORY_PREVIEW could not list previews on this daemon (%s)",
                        r.said[:160])
            return None
        rows = []
        for line in r.out.splitlines():
            parts = line.split("\t")
            if len(parts) == len(_PS_FIELDS):
                row = dict(zip(_PS_FIELDS, parts, strict=True))
                if row["cp"].startswith(PREFIX):
                    rows.append(row)
        return rows

    @staticmethod
    def _group(rows: list[dict]) -> dict[str, RunningPreview]:
        by: dict[str, list[dict]] = {}
        for row in rows:
            by.setdefault(row["cp"], []).append(row)
        out: dict[str, RunningPreview] = {}
        for cp, members in sorted(by.items()):
            exposed = [r for r in members if r["exposed"] == "1"] or members
            if all(r["state"] == "running" for r in exposed):
                state = "running"
            elif any(r["state"] == "running" for r in members):
                state = "failed"
            else:
                state = "exited"
            expires = [int(r["expires"]) for r in members if r["expires"].isdigit()]
            created = [e for e in (_epoch(r["created"]) for r in members) if e]
            first = members[0]
            out[cp] = RunningPreview(compose_project=cp, unit=first["unit"],
                                     project=first["project"], state=state,
                                     expires_at=min(expires) if expires else 0,
                                     started_at=min(created) if created else 0)
        return out

    def watch(self, compose_project: str) -> RunningPreview | None:
        try:
            if not compose_project.startswith(PREFIX):
                return None
            rows = self._containers(f"label=com.docker.compose.project={compose_project}")
            return self._group(rows or []).get(compose_project)
        except Exception as exc:  # noqa: BLE001 — one poll; its failure is a line, never a raise
            log.warning("OPENFACTORY_PREVIEW could not watch %s (%s)", compose_project, exc)
            return None

    def running(self) -> list[RunningPreview]:
        try:
            return list(self._group(self._containers() or []).values())
        except Exception as exc:  # noqa: BLE001
            log.warning("OPENFACTORY_PREVIEW could not list the running previews (%s)", exc)
            return []

    # ── ending ──

    def logs(self, compose_project: str, log_dir: str) -> list[str]:
        """Every service's log, written BEFORE any down — `docker compose logs -t` per service,
        by project name, so it works whether or not the work directory is still there."""
        try:
            if not compose_project.startswith(PREFIX):
                return []
            rows = self._containers(f"label=com.docker.compose.project={compose_project}") or []
            services = sorted({r["service"] for r in rows if r["service"]})
            if not services:
                return []
            os.makedirs(log_dir, exist_ok=True)
            env = _base_env(work_root())
            written = []
            for svc in services:
                r = _host(["docker", "compose", "-p", compose_project, "logs", "--no-color", "-t",
                           svc], env=env, timeout=120)
                path = os.path.join(log_dir, f"{re.sub(r'[^A-Za-z0-9._-]+', '-', svc)}.log")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(r.out + (r.err if r.rc else ""))
                written.append(path)
            return written
        except Exception as exc:  # noqa: BLE001 — a log that could not be kept is a line
            log.warning("OPENFACTORY_PREVIEW could not keep the logs of %s (%s)", compose_project,
                        exc)
            return []

    def down(self, compose_project: str, workdir: str) -> list[str]:
        """Containers, the volumes the unit named, the images it built, its edge network, its work
        directory — each only when it is DERIVABLY the unit's. Never raises."""
        try:
            return self._down(compose_project, workdir)
        except Exception as exc:  # noqa: BLE001
            log.warning("OPENFACTORY_PREVIEW could not take %s down (%s)", compose_project, exc)
            return []

    def _down(self, compose_project: str, workdir: str) -> list[str]:
        if not compose_project.startswith(PREFIX):
            return []
        env = _base_env(work_root())
        removed: list[str] = []
        built_images: list[str] = []
        if workdir and os.path.basename(workdir.rstrip("/")) == compose_project \
                and workdir_is_ours(workdir):
            document = Path(workdir) / "compose.yml"
            if document.is_file() and not document.is_symlink():
                try:
                    services = (yaml.safe_load(document.read_text(encoding="utf-8")) or {}).get(
                        "services", {})
                except (OSError, yaml.YAMLError, AttributeError):
                    services = {}
                if isinstance(services, dict):
                    built_images = [f"{compose_project}-{name}:latest"
                                    for name, spec in services.items()
                                    if isinstance(name, str) and isinstance(spec, dict)
                                    and "build" in spec and "image" not in spec]
        ran = _host(["docker", "compose", "-p", compose_project, "--env-file", os.devnull, "down",
                     "-v", "--rmi", "local", "--remove-orphans"], env=env, timeout=600)
        for line in f"{ran.out}\n{ran.err}".splitlines():
            line = line.strip()
            if line.endswith(" Removed"):
                removed.append(line[: -len(" Removed")].strip())
        # Compose versions differ on whether their generated, tagged build images carry the
        # compose-project label or count as "local" for --rmi. The admitted document names exactly
        # the services this unit built; no pulled image is removed here.
        for image in built_images:
            if _host(["docker", "image", "rm", image], env=env, timeout=120).rc == 0:
                removed.append(f"Image {image}")
        edge = edge_of(compose_project)
        if self.panel_container:
            _host(["docker", "network", "disconnect", "-f", edge, self.panel_container], env=env,
                  timeout=60)
        if _host(["docker", "network", "rm", edge], env=env, timeout=60).rc == 0:
            removed.append(f"Network {edge}")
        if workdir and os.path.basename(workdir.rstrip("/")) == compose_project:
            removed += _remove_workdir(workdir)
        elif workdir and os.path.lexists(workdir):
            log.warning("OPENFACTORY_PREVIEW %s is not %s's work directory — left where it is",
                        workdir, compose_project)
        return removed

    def prove(self, plan: PreviewPlan) -> PreviewUp:
        """Up, wait, down — the base product only; logs kept before the down, as always."""
        if any(t.has_change for t in plan.layout.trees.values()) or any(plan.from_change.values()):
            return PreviewUp(ok=False, why="a proof runs the base product only, and this plan "
                                           "carries a change — nothing was built.")
        try:
            result = self._up(plan, connect_panel=False)
        finally:
            self.logs(plan.compose_project, self.log_dir(plan))
            self.down(plan.compose_project, plan.workdir)
        return result

    def prune(self) -> list[str]:
        """Images a preview built that no running unit still uses (a failed build leaves them,
        and `--rmi local` only reaches a unit that was taken down), and the build cache older than
        the longest a preview may live — the one thing `down` never touches."""
        env = _base_env(work_root())
        pruned: list[str] = []
        active = {p.compose_project for p in self.running()}
        r = _host(["docker", "image", "ls", "-a", "--filter", "label=com.docker.compose.project",
                   "--format", '{{.ID}}\t{{.Label "com.docker.compose.project"}}\t'
                               '{{.Repository}}:{{.Tag}}'], env=env, timeout=60)
        for line in r.out.splitlines() if r.rc == 0 else []:
            parts = line.split("\t")
            if len(parts) == 3 and parts[1].startswith(PREFIX) and parts[1] not in active:
                if _host(["docker", "image", "rm", parts[0]], env=env, timeout=120).rc == 0:
                    pruned.append(f"the image {parts[2]} of {parts[1]}")
        cache = _host(["docker", "builder", "prune", "-f", "--filter",
                       f"until={MAX_TTL_HOURS}h"], env=env, timeout=600)
        if cache.rc == 0 and cache.out.strip():
            pruned.append(f"the build cache older than {MAX_TTL_HOURS}h ({cache.said})")
        return pruned


def legacy_network_present() -> bool:
    """Whether the shared network previews used before each unit had its own is still here."""
    return _host(["docker", "network", "inspect", LEGACY_NETWORK], env=_base_env(work_root()),
                 timeout=30).rc == 0


# ── the doors: prove and login ──────────────────────────────────────────────────────────────────


def prove_project(project, runtime, *, now: float | None = None,
                  draft: Mapping[str, str] | None = None, cfg=None) -> PreviewUp:
    """Bring the project's BASE product up once, wait for it, take it down — through the same
    reader, admission and runtime a card's preview goes through. Builds nothing an agent wrote:
    the unit has no change, and the plan says so.

    `draft` and `cfg` prove a PROPOSAL (`openfactory preview propose --prove`, #265 slice 4): the
    drafted files — repository path → text — are written into the fresh base checkout, and `cfg`
    is the `preview:` block that names them. They are the base branch as it will be once a person
    merges the proposal, and nothing else: no change of any card is in the checkout. A drafted
    path that climbs out of the checkout is refused, never written."""
    unit = Unit(project=project.name, kind="card", id="the base product", token=PROVE_TOKEN)
    layout = materialise(unit, project)
    if isinstance(layout, Refused):
        return PreviewUp(ok=False, why=" ".join(layout.reasons))
    try:
        if draft:
            root = os.path.realpath(layout.root(next(iter(layout.trees)), "base"))
            for rel, text in sorted(draft.items()):
                target = os.path.realpath(os.path.join(root, rel))
                if not target.startswith(root + os.sep):
                    return PreviewUp(ok=False, why=f"the drafted `{rel}` is not a path inside "
                                                   f"the repository — nothing was built.")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "w", encoding="utf-8") as fh:
                    fh.write(text)
        planned = plan(layout, unit, project, cfg=cfg, now=now, prove=True)
        if isinstance(planned, Refused):
            return PreviewUp(ok=False, why=" ".join(planned.reasons))
        return runtime.prove(planned)
    finally:
        _remove_workdir(layout.workdir)


def login(registry: str, *, username: str, password: str) -> Ran:
    """`docker login` into the directory previews pull with — the operator's, never the worker's
    own — with the password on stdin, never in an argument list."""
    config = docker_config()
    os.makedirs(config, mode=0o700, exist_ok=True)
    return _host(["docker", "--config", config, "login", registry, "--username", username,
                  "--password-stdin"], env=_base_env(work_root()), input=password, timeout=120)
