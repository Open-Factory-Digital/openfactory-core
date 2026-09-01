"""`openfactory preflight` — what is still wrong with THIS machine, before anything starts.

WHERE THIS SITS, AND WHY IT IS NOT A FOURTH OPINION. `doctor` answers *can this deployment run a
ticket for this project* — credentials, board, manifest, floor. `readiness` composes a verdict
across the laptop and the worker. Neither can be asked anything before Docker works, which is
exactly the moment the one-line install needs an answer: the user has typed one command, nothing
is running yet, and the only interesting question is what about their machine will stop this.

So this module is the HOST-level sibling of those two, and it deliberately borrows their
vocabulary rather than inventing one. `readiness.Finding` already carries `check, ok, message,
remedy, measured_on, answered` with three states rather than two — and `readiness.py` exists
BECAUSE `doctor`, `gate_reason` and `conformance` had three disagreeing notions of "ready". A
fourth, installer-private notion would re-open the exact defect that module closed. The
constructors come from there too: `_fail` makes `remedy` positional and required, so a failing
finding without one cannot be built here any more than it can be built there.

THE THIRD STATE IS THE ONE THAT EARNS ITS KEEP HERE. Almost every check below is downstream of the
Docker daemon: with no daemon there is no answer to "is the box image present", and *inventing*
one is worse than admitting it. `answered=False` renders as `----`, never counts toward the
failure count, and never reads as a pass — so a preflight that could ask almost nothing says so
instead of producing a short, cheerful, meaningless report.

`--json` IS A PUBLIC CONTRACT AND IS VERSIONED FROM THE FIRST COMMIT. The agent lane (`install.md`,
`install.sh --with-agent`) reads this document rather than inspecting the machine itself, which is
what keeps the LLM a reader and an explainer instead of an authority: it cannot surface a problem
the deterministic lane does not name, so it cannot invent a step. A document whose shape changes
silently would break every reader at once, so `SCHEMA` moves when the shape does.

WHY EVERY FACT IS AN INJECTED PROBE. The same reason `doctor.Probes` exists: a diagnostic that can
only be exercised on a healthy machine is a diagnostic nobody can prove reports illness. Every
branch below is reachable in a test with no Docker, no network and no ports.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

# THE VOCABULARY IS BORROWED, NOT COPIED, and that is the whole point of the module docstring
# above. `_fail`'s signature is the enforcement — you cannot construct a failing finding without
# saying what to do about it — so importing it is importing the rule, while re-declaring three
# one-line constructors here would be re-declaring the rule and letting it drift.
from openfactory.onboarding.readiness import LOCAL, Finding, _fail, _ok, _unanswered

log = logging.getLogger("openfactory.preflight")

#: The shape `--json` emits. MOVES WHEN THE SHAPE MOVES: `install.md` is a public contract the
#: moment it is published, and a reader that cannot tell version 1 from version 2 fails in the
#: least useful way available — by half-understanding a document it thinks it understands.
SCHEMA = "openfactory.preflight/1"

#: What the three images and their layers actually need on disk, measured against
#: `docs/ONBOARDING.md` §0's "budget ~8 GB": the worker carries a Node runtime and four agent CLIs,
#: the box image carries the toolchain. Checked as a WARNING-shaped failure with a remedy rather
#: than a refusal, because a full disk is the one prerequisite that fails halfway through a
#: multi-gigabyte pull — after twenty minutes, with a message about a layer rather than about
#: space.
DISK_HEADROOM_BYTES = 12 * 1024 * 1024 * 1024

#: The ports the stack publishes, and the variable each is overridden by. 8080 is the single most
#: contended port on a developer machine — on the machine this stack was first run on it was
#: already held by a client's own web app — which is why compose made every published port
#: configurable and why a collision is worth naming BEFORE `up` rather than after.
PUBLISHED_PORTS: tuple[tuple[str, str, int], ...] = (
    ("panel", "PANEL_PORT", 8787),
    ("engine UI", "TEMPORAL_UI_PORT", 8080),
    ("engine", "TEMPORAL_PORT", 7233),
)


@dataclass
class Probes:
    """Everything `check` needs to know about the world, as callables it can be handed.

    Each returns a PAIR wherever the reason matters. A stopped daemon and a missing `docker` CLI
    both make `docker info` fail and the remedies are opposite — `doctor.Probes.docker_running`
    carries the same comment, and the compose worker once hit the second and was told the first
    while Docker was serving the container printing the message."""

    #: `(present, detail)` — the version string, or why it could not be read.
    compose: Callable[[], tuple[bool, str]]
    #: `(reachable, detail)` — the daemon's own `os/arch`, or why it did not answer.
    daemon: Callable[[], tuple[bool, str]]
    #: This machine's architecture, as Docker spells it (`amd64`, `arm64`).
    host_arch: Callable[[], str]
    #: Whether a TCP port can be bound here. Bound-and-released, never scanned: "something answers
    #: on 8080" and "8080 is taken" are different questions and only the second one blocks `up`.
    port_free: Callable[[int], bool]
    #: Free bytes on the filesystem Docker stores images on, or None where that cannot be read.
    free_disk: Callable[[], int | None]
    #: The job workspace this deployment will use, and whether it can be created and written
    #: WITHOUT root — the property P0.4 exists to deliver, checked rather than assumed.
    work_dir: Callable[[], str]
    writable_without_root: Callable[[str], tuple[bool, str]]
    #: `True`/`False`/`None`, and the None is the point: with no daemon there is no answer, and a
    #: `False` here would send somebody to `docker pull` an image against a daemon that is not
    #: running — a remedy that cannot work, which is worse than no remedy at all.
    image_present: Callable[[str], bool | None]
    #: The box image this deployment will launch, or None when that cannot be determined here.
    #:
    #: NONE IS NOT AN OVERSIGHT AND IT COST A FALSE PASS TO LEARN. The first version fell back to
    #: `adapters/sandbox/registry.DEFAULT_BOX_IMAGE` when nothing said otherwise, and preflight —
    #: which by design runs BEFORE the stack exists, with no `OPENFACTORY_SANDBOX_IMAGE` in its
    #: environment — cheerfully reported `ok  box_image  the box image openfactory-python is on
    #: this daemon` on a machine that had that old local tag lying around and had never seen the
    #: published one the compose file actually names (measured 2026-08-30, running the command).
    #: A pass about the wrong image is worse than no answer about the right one.
    sandbox_image: Callable[[], str | None]
    #: `(exists, mode)` for `.env.compose`; mode is None when it is absent.
    env_file: Callable[[], tuple[bool, int | None]]
    #: `(visible, detail)` for the agent's credential — ONBOARDING calls it the one prerequisite
    #: that cannot be postponed, and the stack boots happily without it.
    agent_credential: Callable[[], tuple[bool, str]]
    #: The published ports this deployment will actually use, after its own overrides.
    ports: Callable[[], tuple[tuple[str, int], ...]]


@dataclass
class Report:
    """Everything measured, and a verdict that is computed from it rather than stored beside it."""

    findings: list[Finding] = field(default_factory=list)
    measured_on: str = LOCAL

    @property
    def missing(self) -> list[Finding]:
        """Answered checks that are not met. An unanswered check is never one of these."""
        return [f for f in self.findings if f.answered and not f.ok]

    @property
    def unanswered(self) -> list[Finding]:
        return [f for f in self.findings if not f.answered]

    @property
    def ok(self) -> bool:
        return not self.missing

    @property
    def verdict(self) -> str:
        """One sentence. The unanswered count is carried into it deliberately: a green report that
        asked almost nothing is not the same as a green report, and the difference is invisible
        unless the sentence says so."""
        if self.missing:
            return f"MISSING {len(self.missing)}"
        if self.unanswered:
            return f"OK, {len(self.unanswered)} could not be answered here"
        return "OK"

    def as_document(self) -> dict:
        """The state document the agent lane consumes. Versioned, flat, and complete — every
        finding, including the ones that passed, because "what is already fine" is half of what
        stops an explainer from proposing a step that is already done."""
        return {
            "schema": SCHEMA,
            "verdict": self.verdict,
            "ok": self.ok,
            "measured_on": self.measured_on,
            "findings": [
                {
                    "check": f.check,
                    "ok": f.ok,
                    "answered": f.answered,
                    "message": f.message,
                    "remedy": f.remedy,
                    "measured_on": f.measured_on,
                }
                for f in self.findings
            ],
        }


def _guarded(check: str, fn: Callable[[], Finding]) -> Finding:
    """Run one check without letting it become the thing that is broken.

    `doctor._guarded`'s rule, for the same reason and one layer lower: preflight is what somebody
    runs when nothing works, and a traceback out of the diagnostic tells them nothing about their
    machine and rather a lot about ours. A check that RAISED stays `answered=True, ok=False` with a
    remedy — a broken check is a defect to report, never an absence to shrug at."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — a failed probe is a finding, not a crash
        return _fail(check, f"could not check {check}: {exc}",
                     f"run the underlying command by hand to see the raw error, and please report "
                     f"this — `{check}` failing to run is our defect, not your machine's", on=LOCAL)


def check(probes: Probes) -> Report:
    """Every check, every time.

    STOPPING AT THE FIRST FAILURE TURNS ONE SESSION INTO SIX — `doctor.diagnose`'s rule, and it
    matters more here: this runs during an install, and a person who has to re-run an installer
    once per problem stops after the second."""
    return Report(findings=[
        _guarded("docker_daemon", lambda: _daemon(probes)),
        _guarded("docker_compose", lambda: _compose(probes)),
        _guarded("architecture", lambda: _architecture(probes)),
        _guarded("ports", lambda: _ports(probes)),
        _guarded("disk", lambda: _disk(probes)),
        _guarded("work_dir", lambda: _work_dir(probes)),
        _guarded("box_image", lambda: _box_image(probes)),
        _guarded("env_file", lambda: _env_file(probes)),
        _guarded("agent_credential", lambda: _agent_credential(probes)),
    ])


def _daemon(p: Probes) -> Finding:
    reachable, detail = p.daemon()
    if reachable:
        return _ok("docker_daemon", f"the Docker daemon answers ({detail})", on=LOCAL)
    return _fail(
        "docker_daemon", f"the Docker daemon did not answer: {detail}",
        "start Docker (Docker Desktop, or `sudo systemctl start docker`) and run this again — "
        "every other check below is downstream of it", on=LOCAL)


def _compose(p: Probes) -> Finding:
    present, detail = p.compose()
    if present:
        return _ok("docker_compose", f"docker compose v2 is present ({detail})", on=LOCAL)
    # NAMED AS THE PLUGIN AND NOT AS `docker-compose`, deliberately. The v1 Python script is still
    # on a great many machines and still on PATH as `docker-compose`; it cannot read `profiles:`
    # the way this compose file uses them, so "you have compose" is true and useless.
    return _fail(
        "docker_compose", f"`docker compose` (v2, the plugin) is not usable here: {detail}",
        "install the Compose v2 plugin — Docker Desktop ships it, and on Linux it is the "
        "`docker-compose-plugin` package. The old `docker-compose` script is not the same thing "
        "and cannot read this stack's profiles", on=LOCAL)


def _architecture(p: Probes) -> Finding:
    reachable, _ = p.daemon()
    arch = p.host_arch()
    if not reachable:
        return _unanswered("architecture",
                           "cannot ask which architecture the daemon runs until it answers",
                           on=LOCAL)
    # PUBLISHED FOR BOTH, so this is an informational pass rather than a gate — and it is still
    # worth a line, because an image pulled for the wrong architecture RUNS, under emulation, at a
    # speed that reads as "this product is slow" rather than as a configuration mistake.
    if arch in ("amd64", "arm64"):
        return _ok("architecture", f"{arch} — published images cover it natively", on=LOCAL)
    return _fail(
        "architecture", f"this machine is {arch}, and the published images are amd64 and arm64",
        "build from source instead: clone the repository and run `make build`, which builds the "
        "images for whatever architecture this machine is", on=LOCAL)


def _ports(p: Probes) -> Finding:
    taken = [(what, port) for what, port in p.ports() if not p.port_free(port)]
    if not taken:
        return _ok("ports", f"the {len(p.ports())} published ports are free", on=LOCAL)
    listed = ", ".join(f"{port} ({what})" for what, port in taken)
    overrides = " ".join(
        f"{var}=<free port>" for what, var, _ in PUBLISHED_PORTS
        if any(what == name for name, _ in taken))
    return _fail(
        "ports", f"already in use: {listed}",
        f"stop whatever holds them, or put {overrides} in .env.compose — every published port is "
        f"overridable precisely so running this does not mean stopping something else", on=LOCAL)


def _disk(p: Probes) -> Finding:
    free = p.free_disk()
    if free is None:
        return _unanswered("disk", "could not read free space where Docker stores images",
                           on=LOCAL)
    gigabytes = free / (1024 ** 3)
    if free >= DISK_HEADROOM_BYTES:
        return _ok("disk", f"{gigabytes:.1f} GB free where Docker stores images", on=LOCAL)
    return _fail(
        "disk", f"{gigabytes:.1f} GB free where Docker stores images, and the three images need "
                f"about {DISK_HEADROOM_BYTES / (1024 ** 3):.0f} GB",
        "free some space, or reclaim what Docker is already holding with `docker system prune -a` "
        "— a pull that runs out part way reports a failed layer rather than a full disk", on=LOCAL)


def _work_dir(p: Probes) -> Finding:
    where = p.work_dir()
    fine, detail = p.writable_without_root(where)
    if fine:
        return _ok("work_dir", f"{where} is writable without root", on=LOCAL)
    return _fail(
        "work_dir", f"the job workspace {where} cannot be created or written here: {detail}",
        "point OPENFACTORY_WORK_DIR in .env.compose at a directory you own — an absolute path "
        "with no `~` in it, because compose does not expand a tilde in a bind source and would "
        "make a literal `./~` directory instead", on=LOCAL)


def _box_image(p: Probes) -> Finding:
    """THE failure this whole check exists for, and it is invisible until the first ticket.

    The worker is told `OPENFACTORY_SANDBOX_IMAGE` and `docker run`s it on the HOST's daemon — it
    never builds it and compose never pulls it, because `sandbox-image` is behind the build
    profile. If nothing pulled it there, box prepare dies on an image that the compose file names,
    the release publishes, and this machine has never seen: three correct-looking facts and a
    dead job."""
    image = p.sandbox_image()
    if image is None:
        return _unanswered(
            "box_image",
            "cannot tell which box image this deployment will launch — no "
            "OPENFACTORY_SANDBOX_IMAGE, and no docker-compose.yml here to read it from", on=LOCAL)
    present = p.image_present(image)
    if present is None:
        return _unanswered("box_image",
                           f"cannot ask the daemon whether {image} is present until it answers",
                           on=LOCAL)
    if present:
        return _ok("box_image", f"the box image {image} is on this daemon", on=LOCAL)
    return _fail(
        "box_image", f"the box image {image} is not on this daemon, and nothing else will pull it",
        f"docker pull {image}   (the worker launches it as a SIBLING container on this daemon, so "
        f"it has to be here — compose does not fetch it, and the job that needs it fails at the "
        f"first ticket rather than at `up`)", on=LOCAL)


def _env_file(p: Probes) -> Finding:
    exists, mode = p.env_file()
    if not exists:
        return _fail(
            "env_file", ".env.compose has not been written yet",
            "run `openfactory init` — it asks a few questions and writes the file with only the "
            "rows your answers use (by hand instead: cp .env.compose.example .env.compose)",
            on=LOCAL)
    # 0600 IS NOT TIDINESS. That file holds a forge credential with write access to somebody's
    # repositories and a harness token that costs money. `init` writes it 0600 before anything can
    # read it; a file that arrived another way (copied from the template, restored from a backup,
    # checked out) carries the umask of whoever made it.
    if mode is not None and mode & 0o077:
        return _fail(
            "env_file", f".env.compose is mode {mode:04o} — readable beyond you",
            "chmod 600 .env.compose — it holds a forge credential with write access to your "
            "repositories and a harness token that bills someone", on=LOCAL)
    return _ok("env_file", ".env.compose is present and readable only by you", on=LOCAL)


def _agent_credential(p: Probes) -> Finding:
    visible, detail = p.agent_credential()
    if visible:
        return _ok("agent_credential", f"an agent credential is visible ({detail})", on=LOCAL)
    # A FAILURE AND NOT A WARNING, because the stack BOOTS without it and no ticket can run — the
    # exact shape `doctor` was given this check for: a fresh install with zero credentials read
    # "OK — can run a ticket" and failed at the first paid job.
    return _fail(
        "agent_credential", "no agent credential is visible to this deployment",
        "run `claude setup-token` and put the result in CLAUDE_CODE_OAUTH_TOKEN in .env.compose "
        "(or ANTHROPIC_API_KEY if you bill per token). The stack starts without it and no ticket "
        "can run — this is the one credential that cannot be postponed", on=LOCAL)


# ── the probes a real machine answers with ──────────────────────────────────────────────────────
#
# EVERY ONE OF THESE IS I/O AND NONE OF THE LOGIC ABOVE IS. That split is what lets the whole
# report be exercised in a test with no Docker, no ports and no filesystem — and it is why the
# checks take a `Probes` rather than reaching for `subprocess` themselves.


def _run(argv: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, f"{argv[0]}: not found on PATH"
    except subprocess.TimeoutExpired:
        return 124, f"{' '.join(argv)} did not answer within {timeout}s"
    return done.returncode, (done.stdout or done.stderr).strip()


def _probe_daemon() -> tuple[bool, str]:
    code, out = _run(["docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"])
    return (code == 0 and bool(out)), out or "docker gave no answer"


def _probe_compose() -> tuple[bool, str]:
    code, out = _run(["docker", "compose", "version", "--short"])
    return code == 0, out or "the compose plugin gave no answer"


def _probe_port_free(port: int) -> bool:
    """BOUND AND RELEASED, never scanned. "Something answers on 8080" and "8080 cannot be bound"
    are different questions, and only the second one stops `docker compose up`."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _probe_free_disk() -> int | None:
    code, out = _run(["docker", "info", "--format", "{{.DockerRootDir}}"])
    root = out if code == 0 and out else "/var/lib/docker"
    for candidate in (root, "/"):
        try:
            return shutil.disk_usage(candidate).free
        except OSError:
            continue
    return None


def _probe_image_present(image: str) -> bool | None:
    reachable, _ = _probe_daemon()
    if not reachable:
        return None
    code, _ = _run(["docker", "image", "inspect", image])
    return code == 0


def _probe_writable(where: str) -> tuple[bool, str]:
    import pathlib
    import tempfile

    path = pathlib.Path(where)
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path):
            pass
    except OSError as exc:
        return False, exc.strerror or str(exc)
    return True, "created and written as this user"


def _probe_env_file(path: str = ".env.compose") -> tuple[bool, int | None]:
    import pathlib

    file = pathlib.Path(path)
    if not file.exists():
        return False, None
    return True, file.stat().st_mode & 0o777


def _probe_agent_credential() -> tuple[bool, str]:
    # THE NAMES THE CONTAINER SANDBOX ACTUALLY FORWARDS, not a list invented here — the same two
    # `openfactory/onboarding/deployment.py` calls `HARNESS_ENV_CREDENTIAL`'s reason for existing.
    for name in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        if os.environ.get(name):
            return True, f"{name} is set"
    return False, "neither CLAUDE_CODE_OAUTH_TOKEN nor ANTHROPIC_API_KEY is set"


def _probe_ports() -> tuple[tuple[str, int], ...]:
    out = []
    for what, variable, default in PUBLISHED_PORTS:
        raw = (os.environ.get(variable) or "").strip()
        out.append((what, int(raw) if raw.isdigit() else default))
    return tuple(out)


#: `${NAME}` / `${NAME:-default}` / `${NAME-default}` — the whole of compose's interpolation
#: syntax that `docker-compose.yml` uses.
_INTERPOLATION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}")


def _interpolate(text: str, env: dict[str, str]) -> str:
    """Compose's own rules. The colon matters: `${A:-d}` falls back when A is unset OR empty,
    `${A-d}` only when it is unset — and `.env.compose.example` ships the version row empty."""
    def one(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        value = env.get(name)
        if match.group(0).startswith(f"${{{name}:-"):
            return value if value else (default or "")
        return default or "" if value is None else value
    return _INTERPOLATION.sub(one, text)


def _env_file_rows(path: str = ".env.compose") -> dict[str, str]:
    """The `KEY=value` rows of the env file, for interpolating the compose file the way compose
    will. Never raises: a missing or unreadable file is an ordinary state here."""
    import pathlib

    rows: dict[str, str] = {}
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        rows[key.strip()] = value.strip().strip('"').strip("'")
    return rows


def _probe_sandbox_image() -> str | None:
    """Which box image this deployment will launch, asked in the order the truth actually lives in.

    NO FALLBACK TO THE FRAMEWORK DEFAULT, deliberately — see `Probes.sandbox_image`. The framework
    default exists for a process that is ALREADY running inside a configured deployment; preflight
    runs before there is one, so borrowing that constant here answers a question nobody asked with
    a name that is probably wrong. `docker-compose.yml` in the working directory is the real source
    (it is what `install.sh` has just downloaded and what `up -d` will read), interpolated with the
    same `.env.compose` compose itself will use."""
    import pathlib

    from_env = (os.environ.get("OPENFACTORY_SANDBOX_IMAGE") or "").strip()
    if from_env:
        return from_env

    compose = pathlib.Path("docker-compose.yml")
    if not compose.is_file():
        return None
    try:
        import yaml

        services = (yaml.safe_load(compose.read_text()) or {}).get("services") or {}
        declared = ((services.get("worker") or {}).get("environment")
                    or {}).get("OPENFACTORY_SANDBOX_IMAGE")
    except Exception as exc:  # noqa: BLE001 — an unreadable compose file is "cannot tell"
        # SAID OUT LOUD, because "best effort" is the reason to log rather than the reason not to.
        # The finding this feeds renders as `----  box_image  cannot tell which box image …`, which
        # is honest about the CONCLUSION and silent about the cause — and the cause here is almost
        # always a compose file that is truncated or half-downloaded, which is worth one line to
        # whoever is looking at why their install is odd.
        log.warning("could not read docker-compose.yml to find the box image (%s); "
                    "preflight will report that it cannot tell", exc)
        return None
    if not declared:
        return None
    return _interpolate(str(declared), {**_env_file_rows(), **os.environ}) or None


def _probe_work_dir() -> str:
    from openfactory.onboarding.deployment import default_work_dir

    return (os.environ.get("OPENFACTORY_WORK_DIR") or "").strip() or default_work_dir()


def probes_for_this_machine() -> Probes:
    """The real world, wired to the checks above. The one place `subprocess` and `socket` appear."""
    return Probes(
        compose=_probe_compose,
        daemon=_probe_daemon,
        host_arch=lambda: _probe_daemon()[1].split("/")[-1] or "unknown",
        port_free=_probe_port_free,
        free_disk=_probe_free_disk,
        work_dir=_probe_work_dir,
        writable_without_root=_probe_writable,
        image_present=_probe_image_present,
        sandbox_image=_probe_sandbox_image,
        env_file=_probe_env_file,
        agent_credential=_probe_agent_credential,
        ports=_probe_ports,
    )


def as_json(report: Report) -> str:
    """Stable key order, because a document a person diffs between two runs is a document whose
    keys must not move for reasons that are not about their machine."""
    return json.dumps(report.as_document(), indent=2, sort_keys=True)
