"""Task G — the installer's argv is EXECUTED and read, not matched against text.

Run:  .venv/bin/python tools/mutate.py tools/mutations/installer_argv_is_built_not_described.py

THE FIRST CUT IS THE DEFECT THAT SHIPPED, restored exactly: `in_the_cli -t init …` with `"$@"`
after the image name, which made `-t` the first argument to `openfactory` rather than a flag to
`docker run` — `No such option: -t`, exit 2, `set -e`, and a person left with a half-populated
directory and no `.env.compose`. It reached a review, a tag and a public release run while three
mechanisms watched: two guards reading the script's text, shellcheck (which cannot tell a docker
flag from an entrypoint argument), and an end-to-end job that fires on `release: published`. This
plan exists to make that cut cost a red suite on a laptop.

Every cut here is a defect that reads perfectly. That is the point the reviewer made about all four
of their findings, and it is why these guards RUN the script instead of describing it.
"""

TEST = "tests/test_the_installer_builds_the_commands_it_says_it_does.py"

SH = "install.sh"
E2E = ".github/workflows/install-e2e.yml"
GATE_TEST = "tests/test_the_gate_checks_the_shell_script_a_stranger_runs_first.py"

MUTATIONS = [
    # ── the defect that shipped ─────────────────────────────────────────────────────────────────
    ("THE SHIPPED BUG: a caller's flag lands after the image and becomes an entrypoint argument",
     SH,
     "        in_the_cli_asking_questions init --out /out/.env.compose $INIT_ARGS \\",
     "        in_the_cli -t init --out /out/.env.compose $INIT_ARGS \\"),

    ("the command is appended after the flags instead of the flags being prepended",
     SH,
     '    set -- "${REGISTRY}/openfactory-cli:${VERSION}" "$@"',
     '    set -- "$@" "${REGISTRY}/openfactory-cli:${VERSION}"'),

    # ── the refusal that made the bug unreadable ────────────────────────────────────────────────
    ("`init` failing takes the script out silently again, with no cause and no remedy",
     SH,
     "        in_the_cli_asking_questions init --out /out/.env.compose $INIT_ARGS \\\n"
     "            || die",
     "        in_the_cli_asking_questions init --out /out/.env.compose $INIT_ARGS || true \\\n"
     "            && die"),

    # ── the socket, both halves ─────────────────────────────────────────────────────────────────
    ("--group-add is dropped, so the container cannot read the socket it was handed",
     SH,
     "        if [ -n \"$DOCKER_SOCKET_GID\" ]; then\n"
     "            set -- --group-add \"$DOCKER_SOCKET_GID\" \"$@\"\n"
     "        fi\n",
     ""),

    ("--group-add carries the invoking user's gid rather than the socket's",
     SH,
     '            set -- --group-add "$DOCKER_SOCKET_GID" "$@"',
     '            set -- --group-add "$(id -g)" "$@"'),

    ("the socket path goes back to being hardcoded, so rootless and Desktop mount a directory",
     SH,
     '        set -- -v "${DOCKER_SOCKET}:/var/run/docker.sock" "$@"',
     '        set -- -v /var/run/docker.sock:/var/run/docker.sock "$@"'),

    # ── the terminal ────────────────────────────────────────────────────────────────────────────
    ("`-t` is passed unconditionally, which docker refuses against a pipe",
     SH,
     '    if [ "$want_tty" = tty ] && (exec < /dev/tty) 2>/dev/null; then',
     '    if [ "$want_tty" = tty ]; then'),

    # ── the credentials file becomes committable again ──────────────────────────────────────────
    ("the .gitignore line is only written when there is no .gitignore — the shipped defect",
     SH,
     "    if [ \"$DRY_RUN\" -eq 0 ] && ! grep -qxF '.env.compose' \"$DIR/.gitignore\" 2>/dev/null; then",
     "    if [ \"$DRY_RUN\" -eq 0 ] && [ ! -f \"$DIR/.gitignore\" ]; then"),

    # ── the defects the first `verify_the_install` run found ────────────────────────────────────
    ("the cli image loses its docker client, so preflight cannot ask the daemon it was handed",
     "docker/cli.Dockerfile",
     "COPY --from=docker-client /usr/local/bin/docker /usr/local/bin/docker",
     "# no docker client"),

    ("the cli image loses the compose plugin, so `docker compose version` cannot answer",
     "docker/cli.Dockerfile",
     "COPY --from=compose-plugin /docker-compose /usr/local/lib/docker/cli-plugins/docker-compose",
     "# no compose plugin"),

    ("the work directory is left to the container's own $HOME, which Docker sets to `/`",
     SH,
     '    set -- -e "OPENFACTORY_WORK_DIR=${WORK_DIR}" "$@"\n',
     "",
     "tests/test_the_generated_environment_names_a_work_directory_that_needs_no_root.py"),

    ("the work directory is not bound, so preflight judges a host path inside the container",
     SH,
     '    set -- -v "${WORK_DIR}:${WORK_DIR}" "$@"\n',
     "",
     "tests/test_the_generated_environment_names_a_work_directory_that_needs_no_root.py"),

    ("a $HOME of `/` is rooted at the filesystem root again instead of refused",
     "openfactory/onboarding/deployment.py",
     '        if home in ("", "/"):',
     '        if home in ("",):',
     "tests/test_the_generated_environment_names_a_work_directory_that_needs_no_root.py"),

    ("the installer stops answering init's questions, so an unattended install cannot complete",
     SH,
     "            --) shift; INIT_ARGS=\"$*\"; break ;;\n",
     ""),

    # ── the end-to-end job stops being able to contain the bug class ────────────────────────────
    ("the end-to-end job runs the installer as root again, where the socket defect cannot appear",
     E2E,
     "              sudo -u installer -H \\",
     "              env -u NOTHING \\",
     GATE_TEST),

    ("the end-to-end user gets the socket group as its PRIMARY group, which -u would not drop",
     E2E,
     '              usermod -aG "$SOCKET_GID" installer',
     '              true',
     GATE_TEST),
]
