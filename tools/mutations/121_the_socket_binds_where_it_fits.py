"""#121: the installer's fake Docker socket binds where `sun_path` will take it, and says so.

Two binds under pytest's `tmp_path` were 105 and 128 bytes on macOS, where `sun_path` caps a Unix
socket path at 104 — `bind()` raised `OSError: AF_UNIX path too long`, and the module-scoped
fixture holding the first one took 15 tests with it. Green on `ubuntu-latest`, unrunnable on a
maintainer's machine.

THE TEST IS THE NEW GUARD, NOT THE FILE BEING FIXED. `tests/test_the_installer_builds_the_commands
_it_says_it_does.py` cannot be the target: four of its tests fail on any machine with no Docker
daemon (this container included) and one more is #123's, so every row would report RED for reasons
that have nothing to do with its cut — a proof that never saw its own wound.

The rows restore the defect from both ends. Two put the binds back under `tmp_path`, one at each
site. Two attack the helper itself: the explicit short base, which is the whole fix (`$TMPDIR` on
macOS IS the long path), and the refusal that turns the failure into a sentence. The last one
protects the property the move could most easily have dropped in passing — the socket's
supplementary group, which a mutation already had to prove once on 2026-08-31.
"""

TEST = "tests/test_the_socket_binds_where_it_fits.py"
INSTALLER_TESTS = "tests/test_the_installer_builds_the_commands_it_says_it_does.py"

MUTATIONS = [
    # ── the helper's own two claims ─────────────────────────────────────────────────────────────
    ("the short base goes away, so the socket lands in $TMPDIR — the long path on macOS",
     INSTALLER_TESTS,
     '    home = tempfile.mkdtemp(prefix="of-sock-", dir=_SHORT_TMP)',
     '    home = tempfile.mkdtemp(prefix="of-sock-")'),

    ("a path past the cap reaches bind() again, so the failure is a bare OSError naming no remedy",
     INSTALLER_TESTS,
     "        if len(str(path).encode()) >= _SUN_PATH_MAX:\n"
     "            raise AssertionError(\n"
     '                f"{path} is {len(str(path).encode())} bytes and `sun_path` caps a Unix '
     'socket "\n'
     '                f"path at {_SUN_PATH_MAX} on macOS — bind under a shorter directory, not '
     'pytest\'s "\n'
     '                f"tmp_path")',
     "        pass"),

    # ── the two sites, put back the way they shipped ────────────────────────────────────────────
    ("the module fixture binds under tmp_path again — the bind that cost 15 tests",
     INSTALLER_TESTS,
     "    with _a_bound_docker_socket() as (sock, socket_path):\n"
     '        log = home / "argv.log"',
     '    socket_path = home / "docker.sock"\n'
     "    with socketlib.socket(socketlib.AF_UNIX, socketlib.SOCK_STREAM) as sock:\n"
     "        sock.bind(str(socket_path))\n"
     '        log = home / "argv.log"'),

    ("the forced reinstall binds under tmp_path again — the second site, added by #120",
     INSTALLER_TESTS,
     "    with _a_bound_docker_socket() as (sock, socket_path):\n"
     "        done = subprocess.run(",
     '    socket_path = tmp_path / "docker.sock"\n'
     "    with socketlib.socket(socketlib.AF_UNIX, socketlib.SOCK_STREAM) as sock:\n"
     "        sock.bind(str(socket_path))\n"
     "        done = subprocess.run("),

    # ── the property the move could have dropped in passing (2026-08-31) ────────────────────────
    ("the socket keeps this process's own group, so --group-add proves nothing again",
     INSTALLER_TESTS,
     "            supplementary = [g for g in os.getgroups() if g != os.getgid()]\n"
     "            if supplementary:\n"
     "                os.chown(path, -1, supplementary[0])",
     "            pass"),
]
