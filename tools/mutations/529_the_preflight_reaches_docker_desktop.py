"""On Docker Desktop the installer's preflight reaches the daemon, and a refused socket is named
as one rather than as a stopped Docker (#529).

Run:  .venv/bin/python tools/mutate.py tools/mutations/529_the_preflight_reaches_docker_desktop.py

Measured on macOS with Docker Desktop (2026-10-05): the context's socket is `501:20 0755` on the
host and `0:0 0660` inside a container, so the host gid the installer passed to `--group-add`
granted nothing, and preflight printed "the Docker daemon did not answer: docker gave no answer —
start Docker" while that daemon was serving the install's pulls. The claims:

  1. the installer asks a container which group the socket has there, and EVERY cli run gets that
     group — asked before preflight, which is the first run that needs it (rows 1-2);
  2. an answer that is not a number keeps the host's gid (row 3);
  3. the question is asked as the invoking user, of the socket `docker context inspect` named
     (rows 4-5);
  4. --dry-run asks no container anything, since `docker run` would pull the image (row 6);
  5. preflight lets the refusal docker printed on stderr through a blank stdout (row 7), names
     the socket's owner and the asker's groups (row 8), and does not answer a refused socket with
     "start Docker" (row 9).
"""

TEST = "tests/test_the_installer_builds_the_commands_it_says_it_does.py"

SH = "install.sh"
PREFLIGHT = "openfactory/preflight.py"
REMEDY_TEST = "tests/test_preflight_names_a_remedy_for_every_thing_it_refuses.py"

_ASKED_THEN_PREFLIGHT = "    resolve_the_socket_group_a_container_sees\n    run_preflight\n"

MUTATIONS = [
    ("TODAY'S DEFECT: nobody asks a container, so Docker Desktop gets the host file's gid",
     SH,
     _ASKED_THEN_PREFLIGHT,
     "    run_preflight\n"),

    ("the group is asked after preflight, which then runs with the host file's gid",
     SH,
     _ASKED_THEN_PREFLIGHT,
     "    run_preflight\n    resolve_the_socket_group_a_container_sees\n"),

    ("any answer is taken as the group, a sentence on stdout included",
     SH,
     "        ''|*[!0-9]*) ;;\n",
     "        '') ;;\n"),

    ("the socket question runs as the image's user, which is root",
     SH,
     '    seen=$(docker run --rm -u "$(id -u):$(id -g)" --entrypoint stat \\\n',
     "    seen=$(docker run --rm --entrypoint stat \\\n"),

    ("the socket question asks about a hardcoded path, not the one the context named",
     SH,
     '               -v "${DOCKER_SOCKET}:/var/run/docker.sock" \\\n'
     '               "${REGISTRY}/openfactory-cli:${VERSION}" -c',
     '               -v /var/run/docker.sock:/var/run/docker.sock \\\n'
     '               "${REGISTRY}/openfactory-cli:${VERSION}" -c'),

    ("--dry-run asks a container, and `docker run` pulls the image it promised not to",
     SH,
     "resolve_the_socket_group_a_container_sees() {\n    [ \"$DRY_RUN\" -eq 1 ] && return 0\n",
     "resolve_the_socket_group_a_container_sees() {\n"),

    ("a blank line on stdout hides the refusal on stderr again: `docker gave no answer`",
     PREFLIGHT,
     "    return done.returncode, (done.stdout.strip() or done.stderr.strip())",
     "    return done.returncode, (done.stdout or done.stderr).strip()",
     REMEDY_TEST),

    ("the refusal no longer says who owns the socket here and who asked",
     PREFLIGHT,
     '        out = f"{out} ({_the_socket_as_this_process_sees_it()})"\n',
     "        pass\n",
     REMEDY_TEST),

    ("a refused socket is answered with `start Docker` again",
     PREFLIGHT,
     '    if "permission denied" in detail.lower():\n        return _fail(',
     '    if False:\n        return _fail(',
     REMEDY_TEST),
]
