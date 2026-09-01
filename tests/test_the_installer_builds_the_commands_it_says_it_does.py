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

import os
import pathlib
import shutil
import subprocess

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
  */SHA256SUMS) d=$(dirname "$out"); ( cd "$d" && sha256sum ./* > SHA256SUMS && sed -i 's| \\./| |' SHA256SUMS ) ;;
  *) : > "$out" ;;
esac
exit 0
"""

_TOOLS = ("sh", "sha256sum", "stat", "id")
_MISSING = [tool for tool in _TOOLS if shutil.which(tool) is None]
needs_a_posix_shell = pytest.mark.skipif(
    bool(_MISSING), reason=f"this machine has no {_MISSING} — the installer cannot be driven here")


@pytest.fixture(scope="module")
def install_run(tmp_path_factory) -> dict:
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
    socket_path = home / "docker.sock"
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
    return {
        "returncode": done.returncode,
        "stdout": done.stdout,
        "stderr": done.stderr,
        "argv": lines,
        "runs": [line.split() for line in lines if line.startswith("run ")],
        "urls": fetched,
        "socket": str(socket_path),
        "target": target,
    }


@needs_a_posix_shell
def test_the_installer_runs_to_completion_under_the_stubs(install_run):
    """The premise every other test rests on. THIS is the assertion that would have caught the
    blocker: with `-t` in the entrypoint's arguments the real `openfactory` exits 2, `run_init` had
    no `|| die`, and `set -e` ended the script — so a run that completes is itself the property."""
    assert install_run["returncode"] == 0, (
        f"install.sh did not finish:\n{install_run['stdout'][-2000:]}\n"
        f"{install_run['stderr'][-2000:]}")
    assert install_run["runs"], "the installer issued no `docker run` at all"


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
        stray = [word for word in after_the_image if word.startswith("-")
                 and word not in ("--out",)]
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
    assert ["init", "--out", "/out/.env.compose"] in commands, (
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
