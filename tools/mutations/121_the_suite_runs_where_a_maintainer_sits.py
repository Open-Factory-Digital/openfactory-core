"""#121: the installer's guards can be run on the machine a maintainer is sitting at.

Two independent portability defects lived in one file and the first hid the second. The rows below
restore each, and the reverses check that the guards measure BEHAVIOUR rather than the spelling
that happens to fix it today.
"""

TEST = "tests/test_the_suite_runs_where_a_maintainer_sits.py"
SRC = "tests/test_the_installer_builds_the_commands_it_says_it_does.py"

MUTATIONS = [
    # RETIRED 2026-09-14: THE CUT WAS AIMED WRONG, the second of the three meanings a survivor
    # can have. Plain `tempfile.mkdtemp()` measures 72 bytes on macOS and BINDS FINE — the
    # problem was never TMPDIR, it was the `pytest-of-<user>/pytest-<N>/<test name>/` segments
    # pytest appends on top of it. So that cut is a legitimate alternative fix rather than a
    # regression, and a guard going red on it would be enforcing a spelling. `dir="/tmp"` is
    # kept because it is short by definition, where TMPDIR is only short by habit.

    ("…and the reverse: a long directory is accepted as long as it is not pytest's", SRC,
     '    return pathlib.Path(tempfile.mkdtemp(prefix="ofsock", dir="/tmp"))',
     '    return pathlib.Path(tempfile.mkdtemp(prefix="a" * 90, dir="/tmp"))'),

    ("the module fixture binds under tmp_path again", SRC,
     '    socket_home = _socket_dir()\n    socket_path = socket_home / "docker.sock"'
     '\n    import socket as socketlib',
     '    socket_home = _socket_dir()\n    socket_path = home / "docker.sock"'
     '\n    import socket as socketlib'),

    ("the fixture stops releasing its directory, as it never did until #128's review", SRC,
     "\n    shutil.rmtree(socket_home, ignore_errors=True)\n",
     "\n"),

    ("the curl stub rewrites the checksums with GNU's spelling of sed", SRC,
     "    && sed 's| \\\\./| |' SHA256SUMS > SHA256SUMS.rewritten && mv SHA256SUMS.rewritten SHA256SUMS ) ;;",
     "    && sed -i 's| \\\\./| |' SHA256SUMS ) ;;"),

    ("…and the reverse: the rewrite stops happening at all, so the names keep their `./`", SRC,
     "    && sed 's| \\\\./| |' SHA256SUMS > SHA256SUMS.rewritten && mv SHA256SUMS.rewritten SHA256SUMS ) ;;",
     "    ) ;;"),
]
