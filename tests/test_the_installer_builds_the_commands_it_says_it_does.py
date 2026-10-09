"""The installer is RUN here, with a stub `docker` on PATH, and its argv is read.

WHY THIS FILE EXISTS, AND WHY READING THE SCRIPT WAS NEVER GOING TO BE ENOUGH. The one command this
whole installer exists for failed on every machine, and three separate mechanisms were watching:

  · `test_the_installer_knows_exactly_two_facts_the_package_does_not.py` and its siblings read the
    script's TEXT. The defect was that `in_the_cli -t init …` put `"$@"` after the image name, so
    `-t` became the first argument to the entrypoint instead of a flag to `docker run`. Every
    string those guards look for was present and correct.
  · shellcheck read it too, and cannot know which words are docker's and which are the command's —
    `docker run IMAGE -t init` is impeccable shell.
  · `install-e2e` would have caught it, and fires on `release: published` — so the first thing that
    exercises the installer is the tag itself.

The property that was violated is not textual. It is *what argv does `docker run` actually
receive*, and the only way to know is to build it and look. So this drives the real
`install.sh` — the real argument parsing, the real version resolution, the real socket resolution,
the real `set -e` — with `docker` and `curl` replaced by stubs that record what they were called
with. Nothing here reaches a network or a daemon.

WHAT THE STUBS DO NOT DO IS DECIDE THE ANSWER. They record and succeed; every assertion below is
about the script's own construction. A stub that fabricated a plausible command line would be this
file failing the same way the guards it replaces failed.

THE SUITE MUST STILL COLLECT WITHOUT `sh`. Everything optional is resolved at RUN time and skips —
`tests/demo_projects.py`'s rule, and the one this repository lost fifteen days of CI to.
"""

from __future__ import annotations

import ast
import os
import pathlib
import shutil
import subprocess
import tempfile
import textwrap

import installer_script
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "install.sh"

#: A `docker` that records its argv, answers `context inspect` the way a stock Linux daemon does,
#: and succeeds at everything. `$*` rather than `$@` because the log is read line-per-invocation.
_DOCKER_STUB = """#!/bin/sh
printf '%s\\n' "$*" >> "$ARGV_LOG"
if [ "$1" = context ]; then echo "unix://${FAKE_SOCKET}"; fi
exit 0
"""

#: A `curl` that records every URL and writes the file it was told to write.
#:
#: SHA256SUMS IS GENERATED THE WAY THE RELEASE GENERATES IT — `sha256sum ./*` over whatever is
#: already in the directory — rather than over a list of names typed here. That is deliberate: a
#: stub carrying its own copy of the asset names would agree with an installer that had drifted
#: from the release, which is precisely the defect this file exists to catch. It also reproduces
#: the release's own glob, so a dotted asset is invisible here exactly as it was there.
_CURL_STUB = """#!/bin/sh
for a in "$@"; do case "$a" in http*) printf '%s\\n' "$a" >> "$URL_LOG" ;; esac; done
out=""; prev=""
for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
[ -n "$out" ] || exit 0
case "$out" in
  */SHA256SUMS) d=$(dirname "$out"); ( cd "$d" && sha256sum ./* > SHA256SUMS \
    && sed 's| \\./| |' SHA256SUMS > SHA256SUMS.rewritten && mv SHA256SUMS.rewritten SHA256SUMS ) ;;
  *) : > "$out" ;;
esac
exit 0
"""

_TOOLS = ("sh", "sha256sum", "stat", "id")
_MISSING = [tool for tool in _TOOLS if shutil.which(tool) is None]
needs_a_posix_shell = pytest.mark.skipif(
    bool(_MISSING), reason=f"this machine has no {_MISSING} — the installer cannot be driven here")


#: Where `_socket_dir` makes its directories instead of `/tmp`, when set. Read by the helper and
#: set by exactly one caller: the leak guard in `test_the_suite_runs_where_a_maintainer_sits.py`.
SOCKET_ROOT_ENV = "OPENFACTORY_TEST_SOCKET_ROOT"


def _socket_dir() -> pathlib.Path:
    """A directory short enough to hold a bindable `AF_UNIX` path (#121).

    NOT `tmp_path`, AND THAT IS THE WHOLE POINT. `sun_path` is capped at 104 bytes on macOS and
    108 on Linux, and pytest's base temp on macOS is already ~90 before the test's own directory
    is appended:

        /private/var/folders/9n/cxsb_lqj7gn7q4vj3zdpmydh0000gn/T/pytest-of-<user>/pytest-<N>/…

    Both binds in this file exceeded it, so every test here raised `OSError: AF_UNIX path too
    long` — and because the fixture below is module-scoped, one failed bind took the whole file
    with it. Green in CI, unrunnable on a maintainer's machine, which is the shape
    `test_ci_runs_what_we_run.py` exists to refuse. It cost three separate confusions on
    2026-09-13, one of them a CI failure nobody could reproduce locally.

    `/tmp` rather than `tempfile.gettempdir()`: on macOS that reads `TMPDIR`, which is the long
    path this exists to avoid.

    EVERY CALLER RELEASES IT, and that is measured rather than asked for: this line first said the
    caller owned the cleanup and no caller did, so a maintainer running the suite — the person this
    whole change is for — accumulated two directories under `/tmp` per run, for good. A comment
    assigning an owner nobody plays is the defect this repository keeps paying for, so
    `test_the_suite_runs_where_a_maintainer_sits.py` now counts them around a real run.

    `SOCKET_ROOT_ENV` MOVES THE PARENT, AND ONLY THE GUARD THAT COUNTS SETS IT (#423). `/tmp` is
    shared by every xdist worker, and other tests hold `ofsock*` directories there for the length
    of one test each; a guard that counts `/tmp/ofsock*` around a subprocess counted THEIRS
    as this file's leak — 8 of 15 runs of this area at `-n 4`, with nothing left in `/tmp` after.
    Given a directory of its own, the count is of this run's directories and nobody else's. It
    must stay short for the same reason `/tmp` was chosen: the guard makes it under `/tmp`.
    """
    return pathlib.Path(tempfile.mkdtemp(prefix="ofsock", dir=os.environ.get(SOCKET_ROOT_ENV,
                                                                            "/tmp")))


@pytest.fixture(scope="module")
def install_run(tmp_path_factory):
    """Run `install.sh` once, with stubs, and hand every test the argv it produced.

    MODULE-SCOPED because it is one subprocess and every assertion is about the same run — and
    because a per-test run would make this file slower than the rest of the suite put together."""
    home = tmp_path_factory.mktemp("install")
    binaries, target = home / "bin", home / "target"
    binaries.mkdir()
    target.mkdir()

    # A DIRECTORY THAT ALREADY HAS A `.gitignore`, because that is the case the protection is FOR:
    # the target is very often inside somebody's own repository, and a repository has one. A fresh
    # empty directory is the one shape in which the shipped defect — write the file only when there
    # is not one — looks identical to the fix. Same mistake as the reviewer found in `install-e2e`
    # running as root: a fixture whose environment excludes the failure is not covering it.
    (target / ".gitignore").write_text("node_modules\n*.log\n")

    # A REAL SOCKET, so the installer's own `[ -S … ]` check passes for the right reason. `stat`
    # then reads a real gid off it, which is what `--group-add` is built from.
    # RELEASED AT TEARDOWN, NOT AT THE END OF THIS BODY: a test below `os.stat`s this socket long
    # after the fixture returns, so the directory has to outlive the function and die with the
    # module. That is what a yielding fixture is for, and `return` could not have expressed it.
    socket_home = _socket_dir()
    socket_path = socket_home / "docker.sock"
    import socket as socketlib

    with socketlib.socket(socketlib.AF_UNIX, socketlib.SOCK_STREAM) as sock:
        sock.bind(str(socket_path))
        # ITS GROUP IS NOT THIS PROCESS'S PRIMARY GROUP, and that is the whole point of the
        # arrangement. On a stock Linux host the socket is `srw-rw---- root docker` and the user
        # reaches it through a SUPPLEMENTARY group — the thing `-u uid:gid` drops. With the
        # socket's gid equal to `id -g`, `--group-add "$(id -g)"` and `--group-add <socket gid>`
        # are the same string, and the guard below cannot tell a correct installer from one that
        # passes its own group. A mutation proved exactly that (2026-08-31).
        supplementary = [g for g in os.getgroups() if g != os.getgid()]
        if supplementary:
            os.chown(socket_path, -1, supplementary[0])

        log = home / "argv.log"
        urls = home / "url.log"
        for name, body in (("docker", _DOCKER_STUB), ("curl", _CURL_STUB)):
            stub = binaries / name
            stub.write_text(body)
            stub.chmod(0o755)

        done = subprocess.run(
            ["sh", str(INSTALLER), "--version", "v9.9.9", "--dir", str(target)],
            cwd=home, capture_output=True, text=True, timeout=180,
            env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}",
                 "ARGV_LOG": str(log), "URL_LOG": str(urls),
                 "FAKE_SOCKET": str(socket_path)})

    lines = log.read_text().splitlines() if log.exists() else []
    fetched = urls.read_text().splitlines() if urls.exists() else []
    every_run = [line.split() for line in lines if line.startswith("run ")]
    yield {
        "returncode": done.returncode,
        "stdout": done.stdout,
        "stderr": done.stderr,
        "argv": lines,
        # THE `openfactory` INVOCATIONS: every `docker run` whose entrypoint is the image's own.
        # The one that replaces it asks which group the socket has inside a container (#529) and
        # is held to its own shape below — where any other `--entrypoint` is refused, so this split
        # cannot hide a second one.
        "runs": [argv for argv in every_run if "--entrypoint" not in argv],
        "asked": [argv for argv in every_run if "--entrypoint" in argv],
        "urls": fetched,
        "socket": str(socket_path),
        "target": target,
    }
    shutil.rmtree(socket_home, ignore_errors=True)


@needs_a_posix_shell
def test_the_installer_runs_to_completion_under_the_stubs(install_run):
    """The premise every other test rests on. THIS is the assertion that would have caught the
    blocker: with `-t` in the entrypoint's arguments the real `openfactory` exits 2, `run_init` had
    no `|| die`, and `set -e` ended the script — so a run that completes is itself the property."""
    assert install_run["returncode"] == 0, (
        f"install.sh did not finish:\n{install_run['stdout'][-2000:]}\n"
        f"{install_run['stderr'][-2000:]}")
    assert install_run["runs"], "the installer issued no `docker run` at all"



def _flags_the_cli_accepts(command: str) -> set[str]:
    """Every option `openfactory <command>` declares, asked of the CLI itself.

    This used to be the hand-written tuple `("--out",)`, and `--runtime` — a flag the installer
    had to start passing after ADR-0049 — went red against it. A list that must be widened by
    hand whenever the thing it describes grows is the shape this codebase keeps paying for, so
    the question is put to `click` instead."""
    import typer.main

    group = typer.main.get_command(_the_app())
    found = group.commands.get(command)
    if found is None:
        return set()
    return {opt for param in found.params for opt in getattr(param, "opts", [])}


def _the_app():
    from openfactory.cli import app

    return app


@needs_a_posix_shell
def test_every_docker_run_puts_its_flags_before_the_image(install_run):
    """THE defect, as a property rather than a string.

    `docker run` takes `<flags> <image> <command>`. Anything after the image is the CONTAINER's,
    and `docker/cli.Dockerfile` sets `ENTRYPOINT ["openfactory"]`, so a stray `-t` there is not a
    docker flag — it is `openfactory -t`, which exits 2 with a usage box."""
    for argv in install_run["runs"]:
        image = next((i for i, word in enumerate(argv) if "openfactory-cli:" in word), None)
        assert image is not None, f"no image in `docker run` argv: {argv}"

        after_the_image = argv[image + 1:]
        accepted = _flags_the_cli_accepts(after_the_image[0]) if after_the_image else set()
        stray = [word for word in after_the_image if word.startswith("-")
                 and word not in accepted]
        assert not stray, (
            f"{stray} sit AFTER the image, so they are arguments to `openfactory` rather than "
            f"flags to `docker run`. This is the defect that shipped: `openfactory -t init` exits "
            f"2 with `No such option: -t`. Full argv: {argv}")


@needs_a_posix_shell
def test_the_entrypoint_receives_exactly_the_command_the_installer_meant(install_run):
    """Both invocations, by name. `preflight` takes no arguments and `init` takes exactly its
    output path — anything else arriving there is something that failed to be a docker flag."""
    commands = []
    for argv in install_run["runs"]:
        image = next(i for i, word in enumerate(argv) if "openfactory-cli:" in word)
        commands.append(argv[image + 1:])

    assert ["preflight"] in commands, f"the installer never runs preflight: {commands}"
    assert ["init", "--out", "/out/.env.compose", "--runtime", "compose"] in commands, (
        f"the installer never runs init with exactly its output path: {commands}")


@needs_a_posix_shell
def test_the_socket_and_its_group_reach_docker_run(install_run):
    """Tasks F and J, executed. `-u uid:gid` drops supplementary groups, so without `--group-add`
    the container cannot read the socket it was handed — measured on this machine:
    `groups=1000` and SOCKET: DENIED, against `groups=1000,1001` and readable+writable. And the
    socket comes from `docker context inspect`, because a hardcoded path is wrong under rootless
    Docker and Docker Desktop, where Docker would CREATE the missing source as a directory."""
    for argv in install_run["runs"]:
        image = next(i for i, word in enumerate(argv) if "openfactory-cli:" in word)
        flags = argv[:image]

        assert "--group-add" in flags, (
            f"no --group-add, so the container drops the supplementary group that owns the socket "
            f"and preflight reports a daemon this script just proved was up: {argv}")
        gid = flags[flags.index("--group-add") + 1]
        assert gid.isdigit(), f"--group-add was passed {gid!r}, which is not a gid"
        assert gid == str(os.stat(install_run["socket"]).st_gid), (
            "--group-add carries a gid that is not the socket's")

        mounts = [flags[i + 1] for i, word in enumerate(flags) if word == "-v"]
        assert f"{install_run['socket']}:/var/run/docker.sock" in mounts, (
            f"the socket mounted is not the one `docker context inspect` reported: {mounts}")


# ── Docker Desktop: the group a container sees is not the host file's (#529) ───────────────────
#
# Measured on macOS with Docker Desktop (2026-10-05): the context's socket is
# `~/.docker/run/docker.sock`, `501:20 0755` on the host, and a container handed it sees
# `/var/run/docker.sock` as `0:0 0660` — the VM's socket, not the file. `--group-add 20` was
# refused, `--group-add 0` answered `linux/arm64`. The installer passed 20, preflight said "start
# Docker" while the daemon was serving that install's pulls, and Linux (where the two numbers are
# the same) never showed it.

#: Docker Desktop as the installer can see it: a context naming a socket on the host, and a
#: container that, asked about that socket, answers with the gid the TEST chose for the inside.
_DESKTOP_DOCKER_STUB = """#!/bin/sh
printf '%s\\n' "$*" >> "$ARGV_LOG"
if [ "$1" = context ]; then echo "unix://${FAKE_SOCKET}"; fi
case " $* " in *" --entrypoint stat "*) printf '%s\\n' "$SOCKET_GID_INSIDE" ;; esac
exit 0
"""


def _an_install_where_a_container_sees_the_socket_as(tmp_path, inside: str, *args: str) -> dict:
    """The real installer, with `docker` answering the socket question with `inside`.

    THE HOST'S GID IS MADE TO DIFFER FROM `inside`, or the guard could not tell the group asked
    for from the group read off the file — the module fixture's lesson about `id -g`, again. It
    matters on the very machine #529 is about: macOS gives a new file its DIRECTORY's group, and
    `/tmp` is `wheel`, 0 — the same number Docker Desktop answers with."""
    binaries, target = tmp_path / "bin", tmp_path / "target"
    binaries.mkdir()
    target.mkdir()
    log = tmp_path / "argv.log"
    for name, body in (("docker", _DESKTOP_DOCKER_STUB), ("curl", _CURL_STUB)):
        stub = binaries / name
        stub.write_text(body)
        stub.chmod(0o755)

    import socket as socketlib

    socket_home = _socket_dir()
    socket_path = socket_home / "docker.sock"
    try:
        with socketlib.socket(socketlib.AF_UNIX, socketlib.SOCK_STREAM) as sock:
            sock.bind(str(socket_path))
            if str(os.stat(socket_path).st_gid) == inside:
                mine = [g for g in (os.getgid(), *os.getgroups()) if str(g) != inside]
                if os.geteuid() == 0 or mine:
                    os.chown(socket_path, -1, mine[0] if mine else 4242)
            host_gid = str(os.stat(socket_path).st_gid)
            done = subprocess.run(
                ["sh", str(INSTALLER), "--version", "v9.9.9", "--dir", str(target), *args],
                cwd=tmp_path, capture_output=True, text=True, timeout=180,
                env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}",
                     "ARGV_LOG": str(log), "URL_LOG": str(tmp_path / "url.log"),
                     "OPENFACTORY_WORK_DIR": str(tmp_path / "work"),
                     "FAKE_SOCKET": str(socket_path), "SOCKET_GID_INSIDE": inside})
    finally:
        shutil.rmtree(socket_home, ignore_errors=True)
    lines = log.read_text().splitlines() if log.exists() else []
    return {"done": done, "host_gid": host_gid, "argv": lines,
            "runs": [line.split() for line in lines
                     if line.startswith("run ") and "--entrypoint" not in line.split()]}


def _groups_added(argv: list[str]) -> list[str]:
    image = next(i for i, word in enumerate(argv) if "openfactory-cli:" in word)
    return [argv[i + 1] for i, word in enumerate(argv[:image]) if word == "--group-add"]


@needs_a_posix_shell
def test_on_docker_desktop_every_cli_run_gets_the_group_a_container_sees(tmp_path):
    """THE FIX, executed. The container answers 0, as Docker Desktop's did; the host file's group
    (20 on that Mac) is the one that was refused, so it must not be what is passed."""
    run = _an_install_where_a_container_sees_the_socket_as(tmp_path, "0")

    assert run["done"].returncode == 0, run["done"].stdout + run["done"].stderr
    assert run["host_gid"] != "0", "premise: the host's gid must differ from the one inside"
    assert run["runs"], f"the installer ran nothing in the cli image: {run['argv']}"
    for argv in run["runs"]:
        assert _groups_added(argv) == ["0"], (
            f"a cli run carries {_groups_added(argv)} where the container sees the socket as gid "
            f"0 — on Docker Desktop the host's {run['host_gid']} grants nothing in there, and "
            f"preflight says `start Docker` about a daemon that is serving this install: {argv}")


@needs_a_posix_shell
def test_an_answer_that_is_not_a_number_keeps_the_hosts_group(tmp_path):
    """No answer keeps what Linux has always had, and a sentence on stdout is no answer: it would
    otherwise reach `--group-add` and `docker run` would refuse the whole install over it."""
    run = _an_install_where_a_container_sees_the_socket_as(
        tmp_path, "stat: cannot statx '/var/run/docker.sock'")

    assert run["done"].returncode == 0, run["done"].stdout + run["done"].stderr
    for argv in run["runs"]:
        assert _groups_added(argv) == [run["host_gid"]], (
            f"an answer that is not a gid replaced the host's {run['host_gid']}: {argv}")


@needs_a_posix_shell
def test_the_socket_question_is_asked_as_you_of_the_socket_you_were_handed(install_run):
    """The one `docker run` that is not `openfactory`, held to its shape: `stat` of the socket's
    gid, run as the invoking user (never root), from this release's cli image (no third host),
    with the socket `docker context inspect` named mounted where every cli run mounts it — and
    BEFORE preflight, which is the first run that needs the answer."""
    asked = install_run["asked"]

    assert len(asked) == 1, (
        f"expected exactly one `docker run` with its own entrypoint — the socket question — and "
        f"found {len(asked)}: {asked}")
    argv = asked[0]
    image = next(i for i, word in enumerate(argv) if "openfactory-cli:" in word)
    flags = argv[:image]

    assert flags[flags.index("--entrypoint") + 1] == "stat", argv
    assert argv[image].endswith("/openfactory-cli:v9.9.9"), argv
    assert argv[image + 1:] == ["-c", "%g", "/var/run/docker.sock"], argv
    assert "-u" in flags and flags[flags.index("-u") + 1] == f"{os.getuid()}:{os.getgid()}", (
        f"the socket question is not asked as the invoking user: {argv}")
    mounts = [flags[i + 1] for i, word in enumerate(flags) if word == "-v"]
    assert mounts == [f"{install_run['socket']}:/var/run/docker.sock"], (
        f"the socket asked about is not the one every cli run is handed: {mounts}")

    order = [line for line in install_run["argv"] if line.startswith("run ")]
    preflight_at = next(i for i, line in enumerate(order) if line.endswith(" preflight"))
    assert order.index(" ".join(argv)) < preflight_at, (
        f"the socket's group is asked after preflight has already run without it: {order}")


@needs_a_posix_shell
def test_a_dry_run_asks_no_container_anything(tmp_path):
    """--dry-run pulled nothing, and `docker run` of an image that is not there PULLS it — so the
    socket question would break the one promise that mode makes."""
    run = _an_install_where_a_container_sees_the_socket_as(tmp_path, "0", "--dry-run")

    assert run["done"].returncode == 0, run["done"].stdout + run["done"].stderr
    assert not [line for line in run["argv"] if line.startswith(("run ", "pull "))], (
        f"--dry-run ran or pulled an image: {run['argv']}")


@needs_a_posix_shell
def test_no_tty_is_requested_where_no_terminal_can_be_opened(install_run):
    """`docker run -t` against a pipe fails with `the input device is not a TTY`, and the headline
    command is a pipe. This run has no controlling terminal, so `-t` must be absent — the two
    earlier attempts at this test in the script itself both got it wrong (`[ -r /dev/tty ]` is true
    with no terminal; `{ : < /dev/tty; }` EXITS the shell, because `:` is a special built-in and
    POSIX says a redirection error on one is fatal)."""
    for argv in install_run["runs"]:
        image = next(i for i, word in enumerate(argv) if "openfactory-cli:" in word)
        assert "-t" not in argv[:image], (
            f"`-t` was requested with no terminal to attach; docker refuses that: {argv}")


@needs_a_posix_shell
def test_the_env_file_is_kept_out_of_whatever_repository_it_lands_in(install_run):
    """Task I, executed rather than read: the target directory is very often inside somebody's own
    repository, and the file holds a forge token with write access to it."""
    ignore = install_run["target"] / ".gitignore"

    assert ignore.is_file(), "no .gitignore was written beside the credentials file"
    lines = ignore.read_text().splitlines()
    assert ".env.compose" in lines, (
        f"the credentials file is committable. The directory already had a .gitignore — which is "
        f"what a directory inside somebody's repository looks like, and exactly the case the "
        f"protection is for: {lines}")
    # what was already there is still there, and the line is not duplicated
    assert "node_modules" in lines and lines.count(".env.compose") == 1, lines


@needs_a_posix_shell
def test_the_stubs_recorded_a_real_run_and_did_not_fabricate_one(install_run):
    """VERIFY THE VERIFIER. Every assertion above reads a log the stubs wrote; a stub that answered
    plausibly without the script having done anything would make this file fail exactly the way the
    text-reading guards it replaces failed. So: the installer really resolved a version, really
    verified checksums against the real `sha256sum`, and really pulled before it ran."""
    assert any(line.startswith("pull ") for line in install_run["argv"]), install_run["argv"]
    assert any("version --format" in line for line in install_run["argv"]), install_run["argv"]
    assert (install_run["target"] / "SHA256SUMS").is_file(), (
        "the checksum file was never fetched, so the verification step did not run")
    assert "v9.9.9" in install_run["stdout"], "the resolved version never reached the output"


# ── the URLs it builds, which are commands too ─────────────────────────────────────────────────

def _release_assets() -> set[str]:
    """The names the release attaches — read from `scripts/collect-release-assets.sh`.

    IT USED TO PARSE THE WORKFLOW STEP, and on 2026-09-01 the assembly moved into a script so the
    suite could execute it. The step now reads `sh scripts/collect-release-assets.sh dist` and this
    parser found nothing there — an empty set, against which every comparison below passes. Read in
    one place (`tests/installer_script.py`) so the next move cannot leave three copies behind."""
    return installer_script.release_assets()


@needs_a_posix_shell
def test_every_asset_the_installer_downloads_is_one_the_release_attaches(install_run):
    """THE BLOCKER THIS WAS ADDED FOR, and it is the same class as the `-t` defect: two sides of a
    contract, each correct on its own, disagreeing about a name.

    Measured against the real v0.1.1 release (2026-08-31): `install.sh` fetched
    `.env.compose.example` and got **404**, because GitHub does not permit a release asset name to
    begin with a dot and had silently published it as `default.env.compose.example`. The install
    died on the second file it fetches, before the CLI image was pulled — every v0.1.1 install.

    The URLs are read from what the script actually requested, not from its text, for the same
    reason the docker argv is."""
    attached = _release_assets()
    assert attached, "no assets parsed out of release.yml — this guard has no subject"

    downloaded = {url.rsplit("/", 1)[-1] for url in install_run["urls"]
                  if "/releases/download/" in url}
    assert downloaded, f"the installer downloaded no release assets: {install_run['urls']}"

    missing = sorted(downloaded - attached)
    assert not missing, (
        f"install.sh downloads {missing}, which release.yml does not attach. Against the real "
        f"release that is a 404 and a dead install — v0.1.1 failed on exactly this.")


def test_no_release_asset_name_begins_with_a_dot():
    """WHY THE TEMPLATE TRAVELS AS `env.compose.example`. GitHub replaces a leading `.` in a release
    asset name with `default.`, silently, at upload — so the name the workflow believes it attached
    is not the name that exists. The same dot also made the file invisible to the release's own
    `sha256sum ./*`, so it went unchecksummed: one character, two defects, in opposite halves.

    Offline and deterministic, because this is the property that must never again be discovered by
    tagging."""
    dotted = sorted(name for name in _release_assets() if name.startswith("."))

    assert not dotted, (
        f"{dotted} would be attached with a leading dot. GitHub renames those to `default.…` and "
        f"the release's checksum glob skips them — both silently. Attach without the dot and let "
        f"the installer restore the name locally.")


@needs_a_posix_shell
def test_the_template_lands_under_the_name_the_documents_tell_people_to_copy(install_run):
    """The other half of travelling without a dot: `docker-compose.yml`'s own header and the README
    both say `cp .env.compose.example .env.compose`, so the file has to arrive dotted even though
    it cannot be published that way."""
    assert (install_run["target"] / ".env.compose.example").is_file(), (
        "the template did not land as `.env.compose.example`, so every instruction that tells a "
        "person to copy it is wrong")
    assert not (install_run["target"] / "env.compose.example").exists(), (
        "the undotted download was left behind beside the dotted one")


@needs_a_posix_shell
def test_every_asset_it_downloads_is_covered_by_the_checksums(install_run):
    """`sha256sum -c --ignore-missing` SUCCEEDS WHEN IT MATCHES NOTHING, which is how the template
    was fetched and never verified: it was absent from SHA256SUMS because the release's
    `sha256sum ./*` does not match dotfiles (measured: 162 bytes, two entries, for
    `docker-compose.yml` and `install.sh`). Coverage has to be asserted separately from the check,
    because the check cannot tell you what it skipped."""
    sums = (install_run["target"] / "SHA256SUMS").read_text().splitlines()
    covered = {line.split()[-1].lstrip("*") for line in sums if line.strip()}

    downloaded = {url.rsplit("/", 1)[-1] for url in install_run["urls"]
                  if "/releases/download/" in url} - {"SHA256SUMS"}
    uncovered = sorted(downloaded - covered)

    assert not uncovered, (
        f"{uncovered} are downloaded and are not in SHA256SUMS, so `--ignore-missing` skips them "
        f"and they are never verified: {sorted(covered)}")


def test_the_cli_image_carries_the_docker_client_preflight_shells_out_to():
    """`openfactory preflight` runs `docker version` and `docker compose version`, and it runs
    INSIDE `openfactory-cli` — which shipped without a docker client at all. Measured on the
    published openfactory-cli:v0.1.3 (2026-09-02), which is what the first `verify_the_install` run
    reported:

        FAIL  docker_daemon   the Docker daemon did not answer: docker: not found on PATH
        FAIL  docker_compose  `docker compose` (v2, the plugin) is not usable here: docker: not found

    `install.sh` mounts the socket and adds the socket's group to that container specifically so
    preflight can ask the daemon — and there was nothing in it to ask with. Both halves are needed:
    the client for `docker version`, the compose plugin for `docker compose version`."""
    dockerfile = (ROOT / "docker" / "cli.Dockerfile").read_text()
    instructions = "\n".join(line for line in dockerfile.splitlines()
                             if not line.lstrip().startswith("#"))

    assert "/usr/local/bin/docker" in instructions, (
        "the cli image has no docker client, so every preflight check about the daemon answers "
        "`docker: not found on PATH` inside a container that was handed the socket")
    assert "cli-plugins/docker-compose" in instructions, (
        "the cli image has no compose plugin, so `docker compose version` cannot answer")
    for source in ("docker:", "docker/compose-bin:"):
        assert f"FROM {source}" in instructions, (
            f"the client is not copied from a pinned official image ({source}…)")


def test_an_unattended_install_can_answer_the_questions_init_must_ask():
    """`openfactory init` REFUSES rather than blocking on a prompt nobody can answer — the house
    rule, and it is right. But until 2026-09-02 there was no way to supply the answers either, so
    the one-liner could only ever complete at a terminal. That is what the first
    `verify_the_install` run reported, after everything else had worked:

        ✗ --forge is required when this does not run in a terminal (one of: azure_devops, github)

    QUOTED AS OBSERVED, and the product no longer phrases it that way: #117 replaced the
    one-flag-per-run refusal with a single list of every missing flag. The record stays because it
    is what that run actually printed; only do not expect to grep for it.

    Everything after `--` goes to `init`, which is the ordinary shell convention for exactly this
    and keeps the installer's own flags and the command's apart — the distinction whose absence
    caused the `-t` defect."""
    script = installer_script.SCRIPT
    code = "\n".join(installer_script.code_lines())

    assert "INIT_ARGS" in code, (
        "install.sh has no way to pass answers to `openfactory init`, so an unattended install "
        "cannot get past the interview")
    assert '--) shift; INIT_ARGS="$*"; break ;;' in code, (
        "the passthrough is not the `--` convention, so a caller cannot tell where the "
        "installer's flags end and init's begin")
    forwarded = [line for line in code.splitlines()
                 if "in_the_cli_asking_questions init" in line]
    assert forwarded, "init is not invoked at all"
    for line in forwarded:
        assert "$INIT_ARGS" in line, (
            f"the answers are collected and never handed to init: {line.strip()}")
    assert "--" in script[:script.index("set -eu")], (
        "the header does not document the passthrough, which is the only way anybody would find it")


# ── the two modes that promise not to write ─────────────────────────────────────────────────────
#
# `git grep -l 'dry.run' -- tests/` WAS EMPTY. The two run modes carrying the strongest promises in
# the whole script — "print what would happen; touch nothing" and a refusal that changes nothing —
# were the two nothing executed, and a defect lived in both for four releases. `mkdir -p` is
# idempotent, so on any machine that has installed once it is a silent no-op; it appears exactly on
# the machine where a stranger runs `--dry-run` first to decide whether to trust the script.

def _run_installer(tmp_path, *args, home=None, extra_env: dict[str, str] | None = None):
    """Run the real `install.sh` with a stub `docker`, in an environment of our own making.

    `env -i` DELIBERATELY: the point is to know what the script writes given a HOME it has never
    seen, and inheriting this machine's environment would let a pre-existing work directory hide
    the very thing being measured. `extra_env` is what a test declares on top, by name."""
    binaries = tmp_path / "bin"
    binaries.mkdir(exist_ok=True)
    stub = binaries / "docker"
    stub.write_text('#!/bin/sh\n[ "$1" = context ] && echo "unix://${FAKE_SOCKET}"\nexit 0\n')
    stub.chmod(0o755)
    house = home or (tmp_path / "home")
    house.mkdir(exist_ok=True)
    socket_home = _socket_dir()
    try:
        import socket as socketlib

        with socketlib.socket(socketlib.AF_UNIX, socketlib.SOCK_STREAM) as sock:
            socket_path = socket_home / "docker.sock"
            sock.bind(str(socket_path))
            done = subprocess.run(
                ["env", "-i", f"PATH={binaries}:/usr/bin:/bin", f"HOME={house}",
                 f"FAKE_SOCKET={socket_path}",
                 *[f"{k}={v}" for k, v in (extra_env or {}).items()],
                 "sh", str(INSTALLER), *args],
                cwd=tmp_path, capture_output=True, text=True, timeout=180)
    finally:
        shutil.rmtree(socket_home, ignore_errors=True)
    return done, house


def _everything_under(root: pathlib.Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


@needs_a_posix_shell
def test_dry_run_writes_nothing_at_all(tmp_path):
    """THE PROMISE THE HEADER MAKES IN ITS OWN WORDS: *print what would happen; touch nothing*.

    Measured before the fix (Roberto, 2026-09-04): the target was correctly NOT created, and
    `$HOME/.local/share/openfactory/work` was — the one write this script performed outside `$DIR`,
    on the one path that promises none."""
    done, home = _run_installer(tmp_path, "--dry-run", "--version", "v0.1.9",
                                "--dir", str(tmp_path / "target"))

    assert done.returncode == 0, done.stdout + done.stderr
    assert _everything_under(home) == set(), (
        f"--dry-run wrote inside HOME: {sorted(_everything_under(home))}")
    assert not (tmp_path / "target").exists(), "--dry-run created the target directory"
    assert "would run: mkdir -p" in done.stdout, (
        "--dry-run does not even SAY it would create the work directory, so the reader cannot "
        "tell what a real run would do")


@needs_a_posix_shell
def test_a_refused_uninstall_changes_nothing(tmp_path):
    """A refusal that writes is not a refusal. `--uninstall` against a directory holding no install
    says so by name — and used to create the work directory on its way out."""
    done, home = _run_installer(tmp_path, "--uninstall", "--dir", str(tmp_path / "nothing-here"))

    assert done.returncode != 0, "an uninstall with nothing to uninstall reported success"
    assert "no OpenFactory install" in done.stderr, done.stderr
    assert _everything_under(home) == set(), (
        f"a refused --uninstall wrote inside HOME: {sorted(_everything_under(home))}")


@needs_a_posix_shell
def test_the_work_directory_is_the_only_thing_made_outside_the_target_and_only_on_a_real_run(
        tmp_path):
    """The positive twin, so the guards above cannot be satisfied by never creating it at all. A
    real run DOES make it — it has to exist before `run_preflight` bind-mounts it into a container
    — and it is the only thing this script makes outside `$DIR`."""
    done, home = _run_installer(tmp_path, "--dry-run", "--version", "v0.1.9",
                                "--dir", str(tmp_path / "target"))
    target = str(tmp_path / "target")
    made = [line.split("mkdir -p", 1)[1].strip()
            for line in done.stdout.splitlines() if "would run: mkdir -p" in line]
    outside = [path for path in made if not path.startswith(target)]

    assert made, "a real run would create nothing at all, not even the target"
    assert len(outside) == 1, (
        f"the script makes more than one directory outside the target it was given: {outside}")
    assert outside == [str(home / ".local/share/openfactory/work")], outside


def test_the_work_directory_is_created_after_the_uninstall_branch():
    """Read as CONTROL FLOW. The creation used to sit inside `resolve_the_work_directory`, which
    `main()` calls before the `--uninstall` branch and before every `run`-wrapped step — so both
    promise-keeping modes passed through it. Its position is the fix."""
    # COMMENTS STRIPPED FIRST. Written naively, this guard read the whole file as text and failed
    # on the word `mkdir` inside the comment explaining that the mkdir had moved out — a guard
    # satisfied by prose ABOUT the thing rather than the thing, which is the defect CONTRIBUTING
    # names by name. `code_lines()` is what makes it read code.
    code = "\n".join(installer_script.code_lines())
    main = code[code.index("main() {"):]
    main = main[:main.index("\n}")]
    lines = [line.strip() for line in main.splitlines() if line.strip()]

    made = next(i for i, line in enumerate(lines) if line.startswith("run mkdir -p"))
    uninstalled = next(i for i, line in enumerate(lines) if "UNINSTALL" in line)
    preflighted = next(i for i, line in enumerate(lines) if line == "run_preflight")

    assert uninstalled < made < preflighted, (
        f"the work directory is created outside the window between the uninstall branch and the "
        f"first step that needs it: {lines}")
    resolving = code[code.index("resolve_the_work_directory() {"):]
    resolving = resolving[:resolving.index("\n}")]
    assert "mkdir" not in resolving, (
        "resolve_the_work_directory creates the directory again, so --dry-run and --uninstall "
        "write it once more; it only resolves")


# ── the interview has to finish where there is NO TERMINAL AT ALL ───────────────────────────────
#
# v0.2.0's `verify_the_install` died here, and nothing in this suite could have caught it:
#
#     ✗ --runtime is required when this does not run in a terminal (one of: local, compose, fargate)
#
# QUOTED AS IT WAS AT v0.2.0. #117 replaced that per-flag sentence with one refusal listing every
# missing flag, so the wording above is history rather than something to assert against — which is
# exactly what #123 caught, one guard below.
#
# `--runtime` became required off a terminal when the `local` door shipped (ADR-0049). The belief
# that `_cli tty` covered it was wrong, and the reason is worth keeping: `_cli` passes `-t` only
# when `(exec < /dev/tty)` succeeds, and where there is no CONTROLLING TERMINAL that open fails, so
# `docker run` gets `-i` and no `-t`. Measured 2026-09-11, including the part that is easy to get
# backwards — `-t` WITHOUT `-i` does give the container a tty on stdin, so the missing `-t` was the
# cause and the missing `-i` was not.
#
# `curl … | sh` AT A TERMINAL was never broken: `/dev/tty` is reachable around the pipe. What broke
# is every arrangement with no controlling terminal — CI, cron, `ssh host sh -s`, a Dockerfile RUN.
# Nothing here drove one, so the defect shipped.

def _init_flags_the_installer_builds(run) -> list[str]:
    """The flags off the REAL argv this installer produced — not a copy of them."""
    for argv in run["runs"]:
        if "init" in argv:
            return argv[argv.index("init") + 1:]
    raise AssertionError(f"the installer never ran `init`: {run['argv']}")


@needs_a_posix_shell
def test_the_installer_states_the_runtime_it_is_obviously_setting_up(install_run):
    """It fetched a compose file, checksummed it and pulled four images before this line. `local`
    is a different door with no Docker at all, so the answer is known and asking would offer a
    choice that contradicts what the person already typed."""
    flags = _init_flags_the_installer_builds(install_run)

    assert "--runtime" in flags, (
        f"the installer does not state a runtime, so `init` refuses wherever there is no "
        f"controlling terminal — CI, cron, a piped `ssh`: {flags}")
    assert flags[flags.index("--runtime") + 1] == "compose", flags


@needs_a_posix_shell
def test_a_user_can_still_override_the_runtime_the_installer_states(install_run):
    """Stated, not forced. `--runtime` sits BEFORE `$INIT_ARGS` so a later one wins — verified
    against the published v0.2.0 image, where `--runtime compose --runtime local` took `local`."""
    flags = _init_flags_the_installer_builds(install_run)
    code = "\n".join(installer_script.code_lines())
    # EVERY line that invokes `init`, not the first one. Written with `next(...)` this guard read
    # only the `--force` branch, and a mutation moved the stated runtime after `$INIT_ARGS` on the
    # OTHER branch without going red — two invocations, one of them unmeasured.
    invocations = [row for row in code.splitlines() if "init --out" in row and "$INIT_ARGS" in row]

    assert len(invocations) == 2, (
        f"install.sh no longer has exactly the two `init` invocations this guard checks: "
        f"{invocations}")
    for line in invocations:
        assert "--runtime compose" in line, (
            f"one of the two `init` invocations states no runtime: {line.strip()}")
        assert line.index("--runtime compose") < line.index("$INIT_ARGS"), (
            f"the stated runtime comes after the user's own flags, so `-- --runtime local` is "
            f"silently ignored: {line.strip()}")
    assert flags, flags


@needs_a_posix_shell
def test_the_interview_the_installer_builds_completes_with_no_terminal(install_run, tmp_path):
    """THE PROPERTY, AGAINST THE REAL CLI RATHER THAN A DESCRIPTION OF IT.

    `CliRunner` gives `init` a stdin that is not a tty — precisely the arrangement CI has and the
    one that refused. The flags come off the installer's own argv and out of `e2e-in-container.sh`,
    so neither is copied here: if either drifts, this guard follows it. A NEW required flag breaks
    this test instead of the next release, which is the whole point — that is exactly what
    `--runtime` did, unseen, between v0.1.9 and v0.2.0."""
    from typer.testing import CliRunner

    from openfactory.cli import app

    e2e = (ROOT / "scripts" / "e2e-in-container.sh").read_text()
    supplied = e2e.split("set -- \"$@\" --", 1)[1].split("\n\n")[0]
    vendor = [w for w in supplied.replace("\\\n", " ").split() if w]

    flags = [f for f in _init_flags_the_installer_builds(install_run) if not f.startswith("/out")]
    flags = [f for f in flags if f not in ("--out",)]
    dest = tmp_path / ".env.compose"

    result = CliRunner().invoke(app, ["init", "--out", str(dest), *flags, *vendor])

    assert result.exit_code == 0, (
        f"the installer's own interview REFUSES where there is no terminal, which is what CI and "
        f"every scripted install have:\n{result.output}")
    assert dest.exists(), f"init reported success and wrote no file: {result.output}"


@needs_a_posix_shell
def test_that_guard_would_have_caught_the_v0_2_0_defect(install_run, tmp_path):
    """Verify the verifier. Drop `--runtime` from the flags and the same call must refuse — and
    refuse by NAME, so the guard above cannot be passing for some unrelated reason."""
    from typer.testing import CliRunner

    from openfactory.cli import app

    e2e = (ROOT / "scripts" / "e2e-in-container.sh").read_text()
    vendor = [w for w in e2e.split("set -- \"$@\" --", 1)[1].split("\n\n")[0]
              .replace("\\\n", " ").split() if w]
    flags = [f for f in _init_flags_the_installer_builds(install_run)
             if not f.startswith("/out") and f != "--out"]
    without = [f for i, f in enumerate(flags)
               if f != "--runtime" and (i == 0 or flags[i - 1] != "--runtime")]

    result = CliRunner().invoke(app, ["init", "--out", str(tmp_path / "e"), *without, *vendor])

    assert result.exit_code != 0, "init no longer needs a runtime, so the guard above proves nothing"
    # THE CLAIM, NOT THE SENTENCE. This read `"--runtime is required" in result.output` — the exact
    # wording of a one-flag-per-run refusal that #117 replaced with a single list. The refusal still
    # names the flag; only the prose around it moved, so the guard failed on `main` while measuring
    # nothing that had changed. Reading the LIST the refusal prints survives the next rewording too.
    required = [ln.strip() for ln in result.output.splitlines() if ln.startswith("    --")]
    assert any(ln.startswith("--runtime") for ln in required), result.output


@needs_a_posix_shell
def test_a_forced_reinstall_states_the_runtime_too(tmp_path):
    """THE BRANCH A RE-RUN TAKES, and it was unexercised: the module fixture installs once into a
    fresh directory, so `--force` — the path somebody uses after a failed install — never ran. A
    mutation removed the runtime from that line alone and nothing went red."""
    binaries, target = tmp_path / "bin", tmp_path / "target"
    binaries.mkdir()
    target.mkdir()
    (target / ".env.compose").write_text("OPENFACTORY_VERSION=v0.0.1\n")
    log = tmp_path / "argv.log"
    for name, body in (("docker", _DOCKER_STUB), ("curl", _CURL_STUB)):
        stub = binaries / name
        stub.write_text(body)
        stub.chmod(0o755)

    # A REAL SOCKET, for the module fixture's reason: the installer's own `[ -S … ]` check has to
    # pass for the right reason or it refuses long before `init` and this guard measures nothing.
    import socket as socketlib

    socket_home = _socket_dir()
    socket_path = socket_home / "docker.sock"
    try:
        with socketlib.socket(socketlib.AF_UNIX, socketlib.SOCK_STREAM) as sock:
            sock.bind(str(socket_path))
            done = subprocess.run(
                ["sh", str(INSTALLER), "--version", "v9.9.9", "--dir", str(target), "--force"],
                cwd=tmp_path, capture_output=True, text=True, timeout=180,
                env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}",
                     "ARGV_LOG": str(log), "URL_LOG": str(tmp_path / "url.log"),
                     "FAKE_SOCKET": str(socket_path)})
    finally:
        shutil.rmtree(socket_home, ignore_errors=True)
    assert done.returncode == 0, f"the forced install did not finish:\n{done.stdout}{done.stderr}"

    runs = [line.split() for line in log.read_text().splitlines() if line.startswith("run ")]
    init = next((argv for argv in runs if "init" in argv), None)
    assert init is not None, f"a --force install never ran init: {runs}"
    assert "--force" in init, f"the forced path did not pass --force: {init}"
    assert "--runtime" in init and init[init.index("--runtime") + 1] == "compose", (
        f"a forced re-install states no runtime, so it refuses wherever there is no terminal — "
        f"which is the arrangement somebody re-running a failed install is most likely to be in: "
        f"{init}")


def _a_forced_run_over(tmp_path, content: str, *, stubs: tuple = (),
                       declared_work_dir: bool = True
                       ) -> tuple[subprocess.CompletedProcess, pathlib.Path]:
    """The installer re-run with `--force` over a directory whose `.env.compose` holds `content` at
    0600: the upgrade. The stubbed `init` writes nothing, so what the file holds afterwards is what
    the installer itself did to it. `stubs` adds `(name, body)` commands ahead of the real ones;
    `declared_work_dir=False` runs it with no `OPENFACTORY_WORK_DIR` in the environment."""
    binaries, target = tmp_path / "bin", tmp_path / "target"
    binaries.mkdir()
    target.mkdir()
    env_file = target / ".env.compose"
    env_file.write_text(content)
    env_file.chmod(0o600)
    for name, body in (("docker", _DOCKER_STUB), ("curl", _CURL_STUB), *stubs):
        stub = binaries / name
        stub.write_text(body)
        stub.chmod(0o755)

    import socket as socketlib

    socket_home = _socket_dir()
    socket_path = socket_home / "docker.sock"
    try:
        with socketlib.socket(socketlib.AF_UNIX, socketlib.SOCK_STREAM) as sock:
            sock.bind(str(socket_path))
            done = subprocess.run(
                ["sh", str(INSTALLER), "--version", "v9.9.9", "--dir", str(target), "--force"],
                cwd=tmp_path, capture_output=True, text=True, timeout=180,
                env={**{k: v for k, v in os.environ.items()
                        if declared_work_dir or k != "OPENFACTORY_WORK_DIR"},
                     "PATH": f"{binaries}:{os.environ['PATH']}",
                     "ARGV_LOG": str(tmp_path / "argv.log"), "URL_LOG": str(tmp_path / "url.log"),
                     "FAKE_SOCKET": str(socket_path)})
    finally:
        shutil.rmtree(socket_home, ignore_errors=True)
    return done, env_file


@needs_a_posix_shell
def test_an_upgrade_moves_the_pin_to_the_release_it_installs(tmp_path):
    """THE PIN WAS WRITTEN ONLY WHEN ABSENT, and an upgrade is precisely a file that has one. Once
    `init` keeps what the file held, a pin written only when missing would leave every upgraded
    install on the release it was upgrading FROM. Exactly one pin afterwards, naming this release,
    every other row as it was, and the mode still 0600."""
    done, env_file = _a_forced_run_over(
        tmp_path, "OPENFACTORY_BOT_TOKEN=ghp_kept\nOPENFACTORY_VERSION=v0.0.1\nPANEL_PORT=8899\n")
    assert done.returncode == 0, f"the upgrade did not finish:\n{done.stdout}{done.stderr}"

    rows = env_file.read_text().splitlines()
    pins = [row for row in rows if row.startswith("OPENFACTORY_VERSION=")]
    assert pins == ["OPENFACTORY_VERSION=v9.9.9"], f"the upgraded install is pinned to {pins}"
    assert "OPENFACTORY_BOT_TOKEN=ghp_kept" in rows and "PANEL_PORT=8899" in rows, rows
    assert (env_file.stat().st_mode & 0o777) == 0o600, oct(env_file.stat().st_mode)
    left = [p.name for p in env_file.parent.glob(".env.compose.*")
            if p.name != ".env.compose.example"]
    assert not left, f"the pin's temporary copy, which holds the credentials, was left behind: {left}"


@needs_a_posix_shell
def test_a_pin_that_cannot_be_copied_leaves_the_file_as_it_was(tmp_path):
    """`|| true` on the pin's `grep` read a read error (exit 2) or a full disk as "nothing left
    after filtering", wrote the copy back, and left a one-line `.env.compose` with every credential
    gone, then started the stack (review of #366). A failed copy now stops the run, the file as it
    was and no copy left."""
    real_grep = shutil.which("grep")
    failing_grep = ("#!/bin/sh\n"
                    "case \"$*\" in *'^OPENFACTORY_VERSION='*) exit 2 ;; esac\n"
                    f"exec {real_grep} \"$@\"\n")
    before = "OPENFACTORY_BOT_TOKEN=ghp_kept\nOPENFACTORY_VERSION=v0.0.1\nPANEL_PORT=8899\n"

    done, env_file = _a_forced_run_over(tmp_path, before, stubs=(("grep", failing_grep),))

    assert done.returncode != 0, f"the run went on past a copy it could not make:\n{done.stdout}"
    assert env_file.read_text() == before, "the file was changed by a copy that failed"
    assert "left exactly as it was" in done.stderr, done.stderr
    left = [p.name for p in env_file.parent.glob(".env.compose.*")
            if p.name != ".env.compose.example"]
    assert not left, f"the failed copy, which holds the credentials, was left behind: {left}"


@needs_a_posix_shell
def test_an_upgrade_keeps_the_work_directory_its_file_names(tmp_path):
    """`init` keeps the file's work directory, so the installer must make and mount that one, and
    declare it to `init` — or the file names one directory and the installer made another, which
    Docker then creates as root (review of #366)."""
    theirs = tmp_path / "their-work"

    done, _ = _a_forced_run_over(tmp_path, f"OPENFACTORY_WORK_DIR={theirs}\n",
                                 declared_work_dir=False)

    assert done.returncode == 0, f"the upgrade did not finish:\n{done.stdout}{done.stderr}"
    assert theirs.is_dir(), "the installer did not make the work directory the file names"
    runs = [line for line in (tmp_path / "argv.log").read_text().splitlines()
            if line.startswith("run ") and " init " in line]
    assert runs and f"OPENFACTORY_WORK_DIR={theirs}" in runs[0], runs
    assert f"{theirs}:{theirs}" in runs[0], f"the file's work directory is not mounted: {runs}"


@needs_a_posix_shell
@pytest.mark.parametrize("declared", ["~/work", "work/here", "/srv/~/work"])
def test_a_declared_work_directory_compose_cannot_bind_is_refused_before_anything_is_made(
        tmp_path, declared):
    """The declared value went into the file as it came (#367): `OPENFACTORY_WORK_DIR=~/work` made
    compose — which expands no tilde in a bind source — create a directory called `~` and mount
    an empty box. Refused by name before the target is made or a release is downloaded, and
    nothing called `~` or `work` is created anywhere. `/srv/~/work` is the case the tilde rule
    alone catches: absolute, and compose expands no tilde there either."""
    done, _ = _run_installer(tmp_path, "--version", "v9.9.9", "--dir", str(tmp_path / "target"),
                             extra_env={"OPENFACTORY_WORK_DIR": declared})

    assert done.returncode != 0, f"the installer accepted {declared!r}:\n{done.stdout}"
    said = done.stdout + done.stderr
    assert f"OPENFACTORY_WORK_DIR=`{declared}`" in said and "compose" in said, said
    assert not (tmp_path / "target").exists(), "the target was made before the refusal"
    assert not (tmp_path / "~").exists() and not (tmp_path / "work").exists()


@needs_a_posix_shell
def test_a_kept_work_directory_compose_cannot_bind_is_refused_before_the_installer_makes_it(
        tmp_path):
    """`init` refuses a kept `~/work` — after the installer's `mkdir -p` has already made a
    directory called `~` beside wherever it ran. The same rule, whoever said the value, before
    anything is made."""
    done, _ = _a_forced_run_over(tmp_path, "OPENFACTORY_WORK_DIR=~/work\n",
                                 declared_work_dir=False)

    assert done.returncode != 0, f"the installer accepted a kept `~/work`:\n{done.stdout}"
    assert "OPENFACTORY_WORK_DIR=`~/work`" in done.stdout + done.stderr
    assert not (tmp_path / "~").exists(), "a directory called `~` was made before the refusal"


@needs_a_posix_shell
def test_a_value_holding_a_tilde_is_refused_for_the_tilde(tmp_path):
    """`~/work` is relative as well, and it was refused as "not an absolute path" — true, and
    less specific than the sentence written for it (review of #371). Each value its own reason."""
    done, _ = _run_installer(tmp_path, "--version", "v9.9.9", "--dir", str(tmp_path / "target"),
                             extra_env={"OPENFACTORY_WORK_DIR": "~/work"})

    said = done.stdout + done.stderr
    assert done.returncode != 0, said
    assert "holds a `~`" in said and "not an absolute path" not in said, said


@needs_a_posix_shell
def test_an_uninstall_is_not_refused_by_the_work_directory_it_does_not_need(tmp_path):
    """The escape hatch must stay open over the very file it is reached for (review of #371): a
    `.env.compose` holding `~/work`, which an install made before #366 can hold, refused
    `--uninstall` with a sentence about the work directory. Uninstall needs none — it stops the
    stack and removes its volumes — so with no terminal here it reaches its own question and
    refuses for THAT, which is how far a test can take it without deleting anything."""
    target = tmp_path / "target"
    target.mkdir()
    (target / "docker-compose.yml").write_text("services: {}\n")
    (target / ".env.compose").write_text("OPENFACTORY_WORK_DIR=~/work\n")

    done, _ = _run_installer(tmp_path, "--uninstall", "--dir", str(target))

    said = done.stdout + done.stderr
    assert "OPENFACTORY_WORK_DIR" not in said, f"--uninstall was refused by the work dir:\n{said}"
    assert "needs to ask you to confirm" in said, said
    assert not (tmp_path / "~").exists()


@needs_a_posix_shell
def test_a_kept_value_loses_only_its_surrounding_pair_of_quotes(tmp_path):
    """`tr -d '"'` took a double quote out of ANYWHERE in the value, so a path with one inside
    came back as another path (#367). One surrounding pair goes; the rest is the value."""
    theirs = tmp_path / 'their "own" work'

    done, _ = _a_forced_run_over(tmp_path, f'OPENFACTORY_WORK_DIR="{theirs}"\n',
                                 declared_work_dir=False)

    assert done.returncode == 0, f"the upgrade did not finish:\n{done.stdout}{done.stderr}"
    assert theirs.is_dir(), "the value's inner quotes were stripped, or the outer ones kept"
    assert not (tmp_path / "their own work").exists()


@needs_a_posix_shell
def test_the_dry_run_says_which_runtime_it_would_answer(tmp_path):
    """`--dry-run` exists so a stranger can see what the script would do before trusting it. An
    answer given on their behalf is exactly the kind of thing they are reading for, so it has to
    appear — and it did not, which a mutation found."""
    done, _ = _run_installer(tmp_path, "--dry-run", "--version", "v0.1.9",
                             "--dir", str(tmp_path / "target"))

    line = [row for row in done.stdout.splitlines() if "would run: openfactory init" in row]
    assert line, f"a dry run does not say it would run init at all:\n{done.stdout}"
    assert "--runtime compose" in line[0], (
        f"the dry run hides the runtime it answers for you: {line[0]}")


def test_the_accepted_flag_reader_answers_PER_COMMAND():
    """Verify the verifier. `_flags_the_cli_accepts` replaced a hand-kept `("--out",)` tuple, and a
    reader that answered for every subcommand at once would quietly re-admit the original defect:
    `-t` after the image is `openfactory -t`, and it must not become acceptable merely because
    some other subcommand declares a `-t` of its own. Nothing in the installer's current argv has
    a stray flag, so this cut is invisible to every other guard here — which is why it is asserted
    directly rather than left to be caught in passing."""
    init = _flags_the_cli_accepts("init")

    assert "--out" in init and "--runtime" in init, init
    assert "-t" not in init, "`openfactory init` declares -t, so the original defect is legal again"
    assert _flags_the_cli_accepts("preflight") != init, (
        "every command reports the same flags, so this reader is not reading the command it was "
        "asked about")
    assert _flags_the_cli_accepts("no-such-command") == set(), (
        "an unknown command reports flags, so a typo in the argv would be waved through")


# ── a test that drives the installer skips where the installer cannot run ───────────────────────

def _drives_the_installer(fn, _followed: set[str] | None = None) -> bool:
    """Read off the function itself: it takes the module's run, or its compiled code names the
    script, or names a function of this module whose code does. Not a search of the source, so a
    docstring that mentions `INSTALLER` cannot make a test look like a driver.

    THE HELPERS ARE FOLLOWED, NOT LISTED (#334). This read `{"INSTALLER", "_run_installer"}`, and
    `_a_forced_run_over` runs the script too: the five tests that call it were invisible here, 22
    drivers found of 27 on 2026-10-01. They carried the mark anyway; the next one need not."""
    import inspect

    followed = set() if _followed is None else _followed
    followed.add(fn.__name__)
    if "install_run" in inspect.signature(fn).parameters or "INSTALLER" in fn.__code__.co_names:
        return True
    helpers = [globals().get(name) for name in fn.__code__.co_names if name not in followed]
    return any(inspect.isfunction(helper) and helper.__module__ == __name__
               and _drives_the_installer(helper, followed) for helper in helpers)


def _skips_without_the_tools(fn) -> bool:
    return any(mark.name == "skipif" and mark.args == needs_a_posix_shell.mark.args
               for mark in getattr(fn, "pytestmark", []))


def test_every_test_that_drives_the_installer_skips_where_its_tools_are_missing():
    """FIVE OF THEM DID NOT, and the machine that showed it was an ordinary one (2026-09-24, #260):
    with `sha256sum` off PATH, the other tests here that run the installer skipped naming it and
    these five FAILED — four reading `the installer never ran init` off a run that had died at the
    checksum step, one on `sha256sum: command not found`. A contributor reads that as a broken
    repository, which is the one thing CONTRIBUTING's setup section exists to let them tell apart
    from a missing tool."""
    tests = {name: fn for name, fn in globals().items()
             if name.startswith("test_") and callable(fn)}
    drivers = [name for name, fn in tests.items() if _drives_the_installer(fn)]
    assert len(drivers) >= 15, (
        f"only {drivers} drive the installer — the reader of what a test drives has gone blind")

    unguarded = [name for name in drivers if not _skips_without_the_tools(tests[name])]
    assert not unguarded, (
        f"these tests run install.sh and do not skip where {list(_TOOLS)} are missing, so a "
        f"machine without one reports them FAILED instead of naming the tool: {unguarded}. "
        f"Mark them @needs_a_posix_shell")


# ── a driver anywhere in the suite is found by what it does: it starts the script (#334) ────────
#
# THE FIRST READER HERE SAW NONE OF THIS FILE'S OWN DRIVERS. It took a driver to be
# `subprocess.run(...)` with the literal `"install.sh"` among its positional arguments, and this
# repository writes one as `"sh", str(INSTALLER), *args`, through `_run_installer`, through a
# fixture. Measured on the review of #321: the module guard above found 19 drivers in this file and
# that reader 0. On 2026-10-01 it was 22 against 0, and 1 in the whole tree. A guard that sees only
# a spelling nobody uses is the gap it was written to close, one level over — so this reads what
# the code DOES: which values reach the argv of a call that starts a process.

#: The calls that start a process from an argv. The first reader knew `run` alone (#334).
_STARTS_A_PROCESS = frozenset({"run", "call", "check_call", "check_output", "Popen"})

#: The label a value carries when it holds the script. The other labels are `param:<name>`, a
#: parameter of the function being read: a helper handed the script drives it at the call site.
_THE_SCRIPT = "the installer"


def _names_the_script(value) -> bool:
    """A string that is the script's path: `install.sh`, `./install.sh`, the tail of
    `f"{ROOT}/install.sh"`. Not `e2e-install.sh`, which is another script."""
    return isinstance(value, str) and (value == "install.sh" or value.endswith("/install.sh"))


def _atoms(expr) -> tuple[bool, set[str], set[tuple[str, str]]]:
    """What `expr` is built from, read once: whether a string in it names the script, the names it
    reads, and the `module.name` attributes it reads."""
    script, names, attributes = False, set(), set()
    for node in ast.walk(expr):
        if isinstance(node, ast.Constant):
            script = script or _names_the_script(node.value)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            attributes.add((node.value.id, node.attr))
    return script, names, attributes


def _flows(node) -> list[tuple[set[str], ast.AST]]:
    """The names `node` moves a value into, with the value: an assignment, `argv += …`, and
    `argv.append/extend/insert(…)` — the ways an argv is built before it is run."""
    if isinstance(node, ast.Assign):
        pairs = [(target, node.value) for target in node.targets]
    elif isinstance(node, ast.AugAssign):
        pairs = [(node.target, node.value)]
    elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"append", "extend", "insert"}):
        pairs = [(node.func.value, arg) for arg in node.args]
    else:
        return []
    return [({name.id for name in ast.walk(target) if isinstance(name, ast.Name)}, value)
            for target, value in pairs]


def _assigned(body) -> list[tuple[str, ast.AST]]:
    """`(name, value)` for every plain `name = value` among the statements of `body`, in order."""
    return [(target.id, node.value) for node in body if isinstance(node, ast.Assign)
            for target in node.targets if isinstance(target, ast.Name)]


def _is_a_fixture(fn) -> bool:
    return any((getattr(called, "attr", None) or getattr(called, "id", None)) == "fixture"
               for called in (mark.func if isinstance(mark, ast.Call) else mark
                              for mark in fn.decorator_list))


class _InstallerDrivers:
    """The tests under one directory that start `install.sh`, read from their AST, never run.

    A test drives the script when an argv it hands to a call that starts a process — `run`,
    `check_output`, `Popen` and the rest, however `subprocess` was imported — carries the script's
    path: as a string, as a name bound to one in its module or imported from another module under
    the directory, as a local built from either, or through a helper or a fixture that does the
    same. A helper handed the path by its caller counts where it is called."""

    def __init__(self, directory: pathlib.Path):
        self.directory = directory
        self._trees: dict = {}
        self._functions: dict = {}
        self._bindings: dict = {}
        self._paths: dict = {}
        self._summaries: dict = {}

    def tree(self, module: str) -> ast.Module | None:
        if module not in self._trees:
            path = self.directory / f"{module}.py"
            self._trees[module] = ast.parse(path.read_text()) if path.is_file() else None
        return self._trees[module]

    def functions(self, module: str) -> dict[str, ast.AST]:
        if module not in self._functions:
            tree = self.tree(module)
            self._functions[module] = {
                node.name: node for node in (tree.body if tree else [])
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        return self._functions[module]

    def bindings(self, module: str) -> dict[str, tuple[str, str | None]]:
        """What every import in `module` binds, wherever it sits: `(module, None)` for a module,
        `(module, name)` for a name taken from one. A `tests.` prefix is dropped, so both spellings
        this suite uses — `import installer_script`, `from tests.test_x import _run` — land on the
        same file."""
        if module not in self._bindings:
            found: dict[str, tuple[str, str | None]] = {}
            for node in ast.walk(self.tree(module) or ast.Module(body=[], type_ignores=[])):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        found[alias.asname or alias.name.split(".")[0]] = (
                            alias.name.removeprefix("tests.") if alias.asname
                            else alias.name.split(".")[0], None)
                elif isinstance(node, ast.ImportFrom):
                    package = "" if node.module in (None, "tests") else node.module
                    for alias in node.names:
                        found[alias.asname or alias.name] = (
                            (alias.name, None) if not package
                            else (package.removeprefix("tests."), alias.name))
            self._bindings[module] = found
        return self._bindings[module]

    def paths(self, module: str) -> set[str]:
        """The module-level names in `module` that hold the script's path: bound to a string that
        names it, to an expression over such a name, or imported from a module where one is."""
        if module not in self._paths:
            self._paths[module] = found = set()   # filled in place, so a cycle reads what is known
            tree = self.tree(module)
            if tree is not None:
                found.update(name for name, (home, attr) in self.bindings(module).items()
                             if attr is not None and attr in self.paths(home))
                values = [(name, _atoms(value)) for name, value in _assigned(tree.body)]
                before = None
                while before != len(found):
                    before = len(found)
                    found.update(name for name, atoms in values
                                 if _THE_SCRIPT in self.labels(module, atoms, {}))
        return self._paths[module]

    def labels(self, module: str, atoms, local: dict[str, set[str]]) -> set[str]:
        """What an expression carries, read off its atoms: the script, and which parameters of the
        function being read."""
        script, names, attributes = atoms
        found = {_THE_SCRIPT} if script else set()
        paths, bound = self.paths(module), self.bindings(module)
        for name in names:
            found |= local.get(name, set())
            if name in paths:
                found.add(_THE_SCRIPT)
        for base, attr in attributes:
            home, taken = bound.get(base, ("", ""))
            if taken is None and attr in self.paths(home):
                found.add(_THE_SCRIPT)
        return found

    def starts_a_process(self, module: str, call: ast.Call) -> bool:
        func, bound = call.func, self.bindings(module)
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            return bound.get(func.value.id) == ("subprocess", None) and func.attr in _STARTS_A_PROCESS
        if isinstance(func, ast.Name):
            home, attr = bound.get(func.id, ("", None))
            return home == "subprocess" and attr in _STARTS_A_PROCESS
        return False

    def callee(self, module: str, call: ast.Call) -> tuple[str, ast.AST] | None:
        """The function under the directory that `call` calls, and the module it lives in."""
        func, bound = call.func, self.bindings(module)
        if isinstance(func, ast.Name):
            if func.id in self.functions(module):
                return module, self.functions(module)[func.id]
            home, attr = bound.get(func.id, ("", None))
            found = self.functions(home).get(attr) if attr else None
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            home, attr = bound.get(func.value.id, ("", ""))
            found = self.functions(home).get(func.attr) if attr is None else None
        else:
            found = None
        return (home, found) if found is not None else None

    def fixture(self, module: str, name: str) -> tuple[str, ast.AST] | None:
        for home in (module, "conftest"):
            fn = self.functions(home).get(name)
            if fn is not None and _is_a_fixture(fn):
                return home, fn
        return None

    def summary(self, module: str, fn) -> tuple[bool, frozenset[str]]:
        """Whether `fn` starts the script, and which of its parameters reach an argv that starts a
        process — so a caller handing it the path is a driver too."""
        key = (module, fn.name, fn.lineno)
        if key in self._summaries:
            return self._summaries[key]
        self._summaries[key] = (False, frozenset())   # a helper that recurses reads as no driver
        parameters = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs,
                                      fn.args.vararg, fn.args.kwarg) if a is not None]
        nodes = list(ast.walk(fn))
        reached: set[str] = set()
        carried: list[ast.AST] = []   # what reaches an argv, read once the locals are known
        for call in (node for node in nodes if isinstance(node, ast.Call)):
            if self.starts_a_process(module, call):
                carried += call.args[:1] or [kw.value for kw in call.keywords if kw.arg == "args"]
            elif (called := self.callee(module, call)) is not None:
                runs, handed = self.summary(*called)
                reached |= {_THE_SCRIPT} if runs else set()
                positional = [a.arg for a in (*called[1].args.posonlyargs, *called[1].args.args)]
                for at, arg in enumerate(call.args):
                    if isinstance(arg, ast.Starred):
                        break
                    if at < len(positional) and positional[at] in handed:
                        carried.append(arg)
                carried += [kw.value for kw in call.keywords if kw.arg in handed]
        if fn.name.startswith("test_") or _is_a_fixture(fn):
            reached |= {_THE_SCRIPT for name in parameters
                        if (taken := self.fixture(module, name)) is not None
                        and self.summary(*taken)[0]}

        if carried:
            local = {name: {f"param:{name}"} for name in parameters}
            flows = [(names, _atoms(value)) for node in nodes for names, value in _flows(node)]
            grew = True
            while grew:
                grew = False
                for names, atoms in flows:
                    labels = self.labels(module, atoms, local)
                    for name in names:
                        if not labels <= local.setdefault(name, set()):
                            local[name] |= labels
                            grew = True
            for expr in carried:
                reached |= self.labels(module, _atoms(expr), local)

        result = (_THE_SCRIPT in reached,
                  frozenset(label.removeprefix("param:") for label in reached
                            if label.startswith("param:")))
        self._summaries[key] = result
        return result

    def is_a_skip(self, module: str, mark, seen: frozenset = frozenset()) -> bool:
        """`mark` is a `skipif`: written in place, in a list, or a name bound to one here or in the
        module it is imported from. `@needs_a_posix_shell` is the third, and the first reader took
        it for no mark at all — it had no driver of this file to read it on."""
        if isinstance(mark, (ast.List, ast.Tuple)):
            return any(self.is_a_skip(module, item, seen) for item in mark.elts)
        if isinstance(mark, ast.Call):
            return getattr(mark.func, "attr", None) == "skipif"
        where = None
        if isinstance(mark, ast.Name):
            here = dict(_assigned(self.tree(module).body))
            where = (module, mark.id) if mark.id in here else self.bindings(module).get(mark.id)
        elif isinstance(mark, ast.Attribute) and isinstance(mark.value, ast.Name):
            home, attr = self.bindings(module).get(mark.value.id, ("", ""))
            where = (home, mark.attr) if attr is None else None
        if where is None or where[1] is None or where in seen or self.tree(where[0]) is None:
            return False
        value = dict(_assigned(self.tree(where[0]).body)).get(where[1])
        return value is not None and self.is_a_skip(where[0], value, seen | {where})

    def drivers(self) -> dict[str, bool]:
        """`{"file::test": it carries a skip}` for every test under the directory that starts the
        script. A module's `pytestmark` is a mark on each of its tests."""
        found = {}
        for path in sorted(self.directory.glob("test_*.py")):
            tree = self.tree(path.stem)
            module_marks = [value for name, value in _assigned(tree.body) if name == "pytestmark"]
            for fn in tree.body:
                if (isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and fn.name.startswith("test_") and self.summary(path.stem, fn)[0]):
                    found[f"{path.name}::{fn.name}"] = any(
                        self.is_a_skip(path.stem, mark)
                        for mark in (*fn.decorator_list, *module_marks))
        return found


def test_every_direct_installer_driver_in_the_suite_names_missing_tools():
    """The module guard above cannot see a driver in another test module, so this reads them all.

    IT FINDS THEM BY WHAT THEY DO (#334), and the floor is what keeps a reader gone blind from
    passing over an empty room: the first one here found 1 driver in the whole tree and was green,
    while this file alone held 27. Read this way, the tree held 28 on 2026-10-01."""
    drivers = _InstallerDrivers(ROOT / "tests").drivers()
    assert len(drivers) >= 25, (
        f"only {sorted(drivers)} start install.sh — the reader of what a test drives has gone "
        f"blind, and a guard over no drivers passes whatever they do")

    unguarded = sorted(test for test, marked in drivers.items() if not marked)
    assert not unguarded, f"installer drivers without a missing-tools skip: {unguarded}"


def test_both_guards_find_the_same_drivers_in_this_file():
    """THE TWO READERS SAID 19 AND 0 OF THIS FILE (#334). One reads compiled code objects at run
    time, the other the AST of every module, and they were asked the same question: which tests
    start the script. Equal, not overlapping — the module guard missed the five callers of
    `_a_forced_run_over` until it followed helpers instead of listing them, and an inclusion would
    have let that stand."""
    here = pathlib.Path(__file__).name
    by_this_module = {f"{here}::{name}" for name, fn in globals().items()
                      if name.startswith("test_") and callable(fn) and _drives_the_installer(fn)}
    by_the_suite = {test for test in _InstallerDrivers(ROOT / "tests").drivers()
                    if test.startswith(f"{here}::")}

    assert by_the_suite == by_this_module, (
        f"only the suite guard sees {sorted(by_the_suite - by_this_module)}; only this module's "
        f"sees {sorted(by_this_module - by_the_suite)}")
    assert len(by_this_module) >= 25, sorted(by_this_module)


#: Each way this repository writes a driver, planted where only the suite guard can see it. The
#: first reader saw none of them (#334). Every form holds one test, `test_planted`, that runs the
#: script with no skip mark — so each must be reported, and reported unmarked.
_PLANTED_DRIVERS = {
    "an argv built into a variable first": {"test_planted.py": """
        import subprocess

        def test_planted(tmp_path):
            argv = ["sh", "install.sh", "--dry-run"]
            subprocess.run(argv, cwd=tmp_path, check=False)
        """},
    "an argv grown with +=": {"test_planted.py": """
        import subprocess

        def test_planted():
            argv = ["sh"]
            argv += ["install.sh", "--dry-run"]
            subprocess.run(argv)
        """},
    "an argv grown with append": {"test_planted.py": """
        import subprocess

        def test_planted():
            argv = ["sh"]
            argv.append("./install.sh")
            subprocess.run(argv)
        """},
    "check_output instead of run": {"test_planted.py": """
        import subprocess

        def test_planted():
            assert subprocess.check_output(["sh", "install.sh", "--help"])
        """},
    "Popen instead of run": {"test_planted.py": """
        import subprocess

        def test_planted():
            with subprocess.Popen(["sh", "install.sh"]) as started:
                assert started.wait() == 0
        """},
    "a runner imported under a name of its own": {"test_planted.py": """
        from subprocess import run as start

        def test_planted():
            start(["sh", "install.sh"])
        """},
    "a path constant instead of the literal": {"test_planted.py": """
        import pathlib
        import subprocess

        ROOT = pathlib.Path(__file__).resolve().parent.parent
        INSTALLER = ROOT / "install.sh"

        def test_planted(tmp_path):
            subprocess.run(["sh", str(INSTALLER), "--dry-run"], cwd=tmp_path)
        """},
    "the shared module's path, read as an attribute": {
        "installer_script.py": """
            import pathlib

            INSTALLER = pathlib.Path(__file__).resolve().parent.parent / "install.sh"
            """,
        "test_planted.py": """
            import subprocess

            import installer_script

            def test_planted():
                subprocess.run(["sh", str(installer_script.INSTALLER)])
            """},
    "the shared module's path, imported by name": {
        "installer_script.py": """
            import pathlib

            INSTALLER = pathlib.Path(__file__).resolve().parent.parent / "install.sh"
            """,
        "test_planted.py": """
            import subprocess

            from installer_script import INSTALLER

            def test_planted():
                subprocess.run(["sh", str(INSTALLER)])
            """},
    "a helper in the same module": {"test_planted.py": """
        import subprocess

        def _run_installer(tmp_path, *args):
            return subprocess.run(["sh", "install.sh", *args], cwd=tmp_path)

        def test_planted(tmp_path):
            assert _run_installer(tmp_path, "--dry-run").returncode == 0
        """},
    "a helper imported from another test module": {
        "test_elsewhere.py": """
            import subprocess

            def _run_installer(*args):
                return subprocess.run(["sh", "install.sh", *args])
            """,
        "test_planted.py": """
            from tests.test_elsewhere import _run_installer

            def test_planted():
                _run_installer("--dry-run")
            """},
    "a helper handed the script by position": {"test_planted.py": """
        import pathlib
        import subprocess

        def _sh(script, *args):
            return subprocess.run(["sh", str(script), *args])

        def test_planted():
            _sh(pathlib.Path("install.sh"), "--dry-run")
        """},
    "a helper handed the script by name": {"test_planted.py": """
        import pathlib
        import subprocess

        def _sh(*args, script):
            return subprocess.run(["sh", str(script), *args])

        def test_planted():
            _sh("--dry-run", script=pathlib.Path("install.sh"))
        """},
    "a fixture the test takes": {"test_planted.py": """
        import subprocess

        import pytest

        @pytest.fixture(scope="module")
        def install_run():
            return subprocess.run(["sh", "install.sh"])

        def test_planted(install_run):
            assert install_run.returncode == 0
        """},
    "a fixture from conftest": {
        "conftest.py": """
            import subprocess

            import pytest

            @pytest.fixture
            def install_run():
                return subprocess.run(["sh", "install.sh"])
            """,
        "test_planted.py": """
            def test_planted(install_run):
                assert install_run.returncode == 0
            """},
}


def _plant(directory: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    for name, source in files.items():
        (directory / name).write_text(textwrap.dedent(source))
    return directory


@pytest.mark.parametrize("form", sorted(_PLANTED_DRIVERS))
def test_the_suite_guard_sees_a_driver_written_in_each_form_this_repository_uses(tmp_path, form):
    """A driver written the way this repository writes them would have run install.sh with no
    skip and nothing saying so (#334). Each is planted alone, so a form the reader cannot follow
    is named by the form."""
    drivers = _InstallerDrivers(_plant(tmp_path, _PLANTED_DRIVERS[form])).drivers()

    assert drivers == {"test_planted.py::test_planted": False}, (
        f"a driver written as {form!r} reads as {drivers}")


def test_the_suite_guard_takes_nothing_but_a_started_script_for_a_driver(tmp_path):
    """The other side of reading what the code does. Naming the script, reading its text, starting
    a script whose name ends the same, handing the same helper another script, running the suite
    over the installer's tests, describing a driver in a docstring: none starts install.sh, and a
    guard that asked them all for a skip would be argued with until it was switched off."""
    _plant(tmp_path, {"test_planted.py": '''
        import pathlib
        import subprocess
        import sys

        ROOT = pathlib.Path(__file__).resolve().parent.parent
        INSTALLER = ROOT / "install.sh"

        def _sh(script, *args):
            return subprocess.run(["sh", str(script), *args])

        def test_reads_the_script_and_starts_nothing():
            assert "set -eu" in INSTALLER.read_text()

        def test_starts_another_script_whose_name_ends_the_same():
            subprocess.run(["sh", str(ROOT / "scripts" / "e2e-install.sh")])

        def test_hands_the_same_helper_another_script():
            _sh(ROOT / "scripts" / "collect-release-assets.sh")

        def test_runs_the_suite_over_the_installer_tests():
            subprocess.run([sys.executable, "-m", "pytest",
                            str(ROOT / "tests" / "test_the_installer_builds_the_commands.py")])

        def test_only_describes_a_driver():
            """subprocess.run(["sh", "install.sh"]) is what one looks like."""
            subprocess.run(["git", "status"])
        '''})

    assert _InstallerDrivers(tmp_path).drivers() == {}


def test_the_suite_guard_takes_a_skip_mark_in_each_form_it_is_written(tmp_path):
    """`@needs_a_posix_shell` is a NAME bound to a `skipif`, and the first reader read only a
    `skipif` written in place — it had no driver of this file to be wrong about. Once it has, a
    name, an imported name and a module's `pytestmark` are marks; a `parametrize` is not."""
    _plant(tmp_path, {
        "test_planted.py": """
            import shutil
            import subprocess

            import pytest

            needs_sh = pytest.mark.skipif(shutil.which("sh") is None, reason="no sh here")

            @needs_sh
            def test_marked_by_a_name():
                subprocess.run(["sh", "install.sh"])

            @pytest.mark.skipif(shutil.which("sh") is None, reason="no sh here")
            def test_marked_in_place():
                subprocess.run(["sh", "install.sh"])

            @pytest.mark.parametrize("flag", ["--dry-run"])
            def test_marked_with_something_else(flag):
                subprocess.run(["sh", "install.sh", flag])
            """,
        "test_planted_by_import.py": """
            import subprocess

            from tests.test_planted import needs_sh

            @needs_sh
            def test_marked_by_an_imported_name():
                subprocess.run(["sh", "install.sh"])
            """,
        "test_planted_by_module.py": """
            import shutil
            import subprocess

            import pytest

            pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="no sh here")

            def test_marked_by_the_module():
                subprocess.run(["sh", "install.sh"])
            """})

    assert _InstallerDrivers(tmp_path).drivers() == {
        "test_planted.py::test_marked_by_a_name": True,
        "test_planted.py::test_marked_in_place": True,
        "test_planted.py::test_marked_with_something_else": False,
        "test_planted_by_import.py::test_marked_by_an_imported_name": True,
        "test_planted_by_module.py::test_marked_by_the_module": True,
    }
