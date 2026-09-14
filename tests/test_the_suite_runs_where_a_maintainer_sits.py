"""#121: the installer's guards must be runnable on the machine a maintainer is sitting at.

`tests/test_the_installer_builds_the_commands_it_says_it_does.py` was green in CI and could not run
on macOS at all, for two independent reasons in the same file:

1. it bound an `AF_UNIX` socket under pytest's `tmp_path`, and `sun_path` caps at **104 bytes** on
   macOS (108 on Linux) while pytest's base temp there is already ~90 before the test's own
   directory is appended. Every bind raised `OSError: AF_UNIX path too long`, and because the
   fixture is module-scoped one failed bind took the whole file down: **14 errors**;
2. its `curl` stub rewrote `SHA256SUMS` with `sed -i 's|…|…|' FILE`. GNU `sed` accepts `-i` with no
   argument; **BSD `sed` reads the next word as the backup suffix**, so on macOS the script became
   the filename and the installer aborted on an unverifiable checksum list.

The second was invisible until the first was fixed. That is the cost being paid here: the file's
own unrunnability hid a second defect in itself, and `test_ci_runs_what_we_run.py` exists because
green-in-CI is not the same claim as correct.

It cost three separate confusions on 2026-09-13, one of them a CI failure that could not be
reproduced locally by either person looking at it.

THESE GUARDS LIVE IN THEIR OWN FILE ON PURPOSE. Guards protecting a file's runnability are worth
nothing inside it: the fixture that cannot bind takes them down with everything else, and the
suite reports an error where it should report a claim.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTALLER_TESTS = ROOT / "tests" / "test_the_installer_builds_the_commands_it_says_it_does.py"

#: The smaller of the two platform limits, minus the `\0`. Linux allows 108; macOS is the binding
#: constraint and the one a guard should hold, because a path that fits there fits everywhere.
SUN_PATH_MAX = 104


#: Where `_socket_dir` puts things, so a guard can count what a run left behind.
SOCKET_ROOT, SOCKET_PREFIX = pathlib.Path("/tmp"), "ofsock"


@pytest.fixture
def self_cleanup():
    """These guards call `_socket_dir()` for real, so without this THEY would be the leak the
    guard below refuses — a test file that measures a mess while making one."""
    made: list[pathlib.Path] = []
    yield made
    for path in made:
        shutil.rmtree(path, ignore_errors=True)


def test_the_socket_directory_leaves_room_for_a_socket_name(self_cleanup):
    """Executed, not read: the helper is called and its answer measured against the real cap."""
    from tests.test_the_installer_builds_the_commands_it_says_it_does import _socket_dir

    home = _socket_dir()
    self_cleanup.append(home)
    path = home / "docker.sock"

    assert len(str(path).encode()) < SUN_PATH_MAX, (
        f"{path} is {len(str(path).encode())} bytes; sun_path caps at {SUN_PATH_MAX} on macOS, so "
        f"every bind in that file raises OSError and its module-scoped fixture takes the file down"
    )


def test_a_socket_can_actually_be_bound_there(self_cleanup):
    """The claim the byte count is a proxy for. A limit read from a constant is a limit nobody has
    checked — this binds a real socket, which is what the file under repair does."""
    from tests.test_the_installer_builds_the_commands_it_says_it_does import _socket_dir

    home = _socket_dir()
    self_cleanup.append(home)
    path = home / "docker.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.bind(str(path))          # raises OSError: AF_UNIX path too long if this regresses

    assert path.is_socket()


def test_pytests_own_tmp_path_is_not_used_for_the_socket(tmp_path, self_cleanup):
    """The reverse, and the one that would quietly come back: `tmp_path` is the obvious place to
    put a file and the one place this cannot go. Stated as a measurement of THIS machine rather
    than as a rule, so on Linux — where it fits — the guard says so instead of failing."""
    candidate = tmp_path / "docker.sock"

    if sys.platform == "darwin":
        assert len(str(candidate).encode()) >= SUN_PATH_MAX, (
            "pytest's tmp_path now fits in sun_path on this machine, so this guard no longer "
            "proves anything — check whether the helper is still needed before deleting it"
        )
    from tests.test_the_installer_builds_the_commands_it_says_it_does import _socket_dir

    home = _socket_dir()
    self_cleanup.append(home)
    assert str(home) != str(tmp_path), "the socket went back under pytest's temp root"


def test_no_stub_in_that_file_uses_a_gnu_only_sed():
    """`sed -i` with no argument is GNU's spelling and BSD reads the next word as a backup suffix.
    The stubs are shell this suite EXECUTES, so a GNU-ism there is a test that cannot run rather
    than a product defect — which is the harder kind to see.

    Read from the stub bodies rather than the whole file, so prose about the defect cannot satisfy
    it: the constants are assigned source, and that is what is scanned."""
    from tests import test_the_installer_builds_the_commands_it_says_it_does as mod

    stubs = {name: getattr(mod, name) for name in dir(mod)
             if name.endswith("_STUB") and isinstance(getattr(mod, name), str)}

    assert stubs, "no *_STUB constants found — this guard has no subject"
    for name, body in stubs.items():
        offending = re.search(r"sed\s+-i\s+(?!['\"]{2})", body)
        assert not offending, (
            f"{name} uses `sed -i` without a backup suffix, which BSD sed refuses: "
            f"{body[max(0, offending.start() - 40):offending.end() + 40]!r}"
        )


def test_that_stub_rewrites_the_checksums_the_same_way_under_this_shell():
    """The behaviour the spelling is a proxy for, executed under whatever `sh` this machine has.

    `sha256sum ./*` writes `<hash>  ./name`, and the installer's `sha256sum -c` needs bare names.
    The rewrite is what makes the fixture's release verifiable at all; when it silently failed, the
    installer refused its own assets and every downstream assertion read as a product defect."""
    from tests.test_the_installer_builds_the_commands_it_says_it_does import _CURL_STUB

    rewrite = [ln for ln in _CURL_STUB.splitlines() if "SHA256SUMS" in ln and "sed" in ln]
    assert rewrite, "the SHA256SUMS branch no longer rewrites anything — re-aim this guard"

    # `tempfile.mkdtemp`, NOT `mktemp -d -t ofsums`. THIS GUARD SHIPPED WITH THE DEFECT IT
    # GUARDS AGAINST: BSD `mktemp` reads `-t` as a prefix, GNU coreutils reads it as a flag that
    # still wants a TEMPLATE — so the line that proved a GNU-ism on macOS was itself a BSD-ism,
    # and CI died on `returned non-zero exit status 1` where this machine was green. The reverse
    # direction of #121, found by the CI run of #121.
    work = pathlib.Path(tempfile.mkdtemp(prefix="ofsums"))
    (work / "SHA256SUMS").write_text("abc123  ./docker-compose.yml\ndef456  ./install.sh\n")
    script = "\n".join(rewrite).split(")", 1)[1].rsplit(";;", 1)[0].replace('$(dirname "$out")',
                                                                           f'"{work}"')
    done = subprocess.run(["sh", "-c", script.replace("cd \"$d\"", f'cd "{work}"')
                           .replace("sha256sum ./* > SHA256SUMS", ":")],
                          capture_output=True, text=True)

    assert done.returncode == 0, f"the rewrite failed under this shell: {done.stderr[:300]}"
    assert "./" not in (work / "SHA256SUMS").read_text(), (
        "the `./` prefixes survived, so `sha256sum -c` will not match the downloaded names and "
        "the installer refuses its own release"
    )


def test_the_installer_file_can_be_collected_at_all():
    """The whole point, stated once: pytest must be able to COLLECT and run that file here. A
    module-scoped fixture that raises turns every test in it into an error, and an error is not a
    finding — it is the suite failing to ask the question."""
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "--collect-only",
                           str(INSTALLER_TESTS)], capture_output=True, text=True, cwd=ROOT)

    assert done.returncode == 0, done.stdout[-800:] + done.stderr[-400:]
    assert "error" not in done.stdout.lower(), done.stdout[-800:]


def test_the_fixture_actually_uses_the_short_directory():
    """THE GUARD ABOVE MEASURED THE HELPER AND NOT ITS CALLER, and a mutation row survived saying
    so: putting the bind back under `tmp_path` left every guard here green, because none of them
    ran the fixture. `--collect-only` does not execute fixtures either, so the collection guard
    could not see it.

    This RUNS the file. Failures are none of this guard's business — the point is that no test in
    it ERRORS, because an error is the module-scoped fixture dying and taking the file with it."""
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:randomly",
                           str(INSTALLER_TESTS)], capture_output=True, text=True, cwd=ROOT)
    tail = done.stdout.strip().splitlines()[-1] if done.stdout.strip() else ""

    assert " error" not in tail, (
        f"the installer tests error rather than run on this machine — the fixture is not using a "
        f"bindable socket path: {tail}"
    )


def test_the_run_leaves_no_directory_behind():
    """THE CLAIM THE DOCSTRING USED TO MAKE AND NOBODY KEPT. It read `the caller owns the cleanup`
    while neither caller cleaned up, so every run of that file left two directories under `/tmp`
    for good — on the machine of the maintainer this whole change exists for.

    Counted around a real run rather than asserted from the source, because `shutil.rmtree` being
    written somewhere is not the same claim as the directory being gone: a `finally` on the wrong
    block, an early return, or a second call site added later all read identically in a diff."""
    before = {p for p in SOCKET_ROOT.glob(f"{SOCKET_PREFIX}*")}

    subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:randomly",
                    str(INSTALLER_TESTS)], capture_output=True, text=True, cwd=ROOT)

    leaked = {p for p in SOCKET_ROOT.glob(f"{SOCKET_PREFIX}*")} - before
    assert not leaked, (
        f"{len(leaked)} directory(ies) survived one run of that file and nothing will ever remove "
        f"them: {sorted(str(p) for p in leaked)}"
    )
