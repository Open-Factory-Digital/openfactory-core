"""Task AG — the installer's interview finishes where there is no terminal at all.

Run:  .venv/bin/python tools/mutate.py tools/mutations/installer_states_its_runtime.py

v0.2.0 shipped and `verify_the_install` died at:

    ✗ --runtime is required when this does not run in a terminal (one of: local, compose, fargate)

`--runtime` became required off a terminal when the `local` door shipped (ADR-0049). Nothing in
the suite drove an install with no terminal, so the flag became required and the installer never
learned to pass it.

MEASURED 2026-09-11, including the part that is easy to get backwards:

  * `_cli tty` passes `-t` ONLY when `(exec < /dev/tty)` succeeds. With no controlling terminal
    that open fails, so `docker run` gets `-i` and no `-t`, and `sys.stdin.isatty()` is false.
  * `-t` WITHOUT `-i` DOES give the container a tty on stdin. The missing `-t` was the cause; the
    missing `-i` was not.
  * `curl … | sh` AT A TERMINAL was never broken — `/dev/tty` is reachable around the pipe. What
    broke is every arrangement with no controlling terminal: CI, cron, `ssh host sh -s`, a
    Dockerfile RUN, a systemd unit.

The first cut is the defect exactly as it shipped. The rest attack the guards, and two of them
matter more than the fix: the guard drives the REAL `init` through `CliRunner` (whose stdin is not
a tty) using flags taken off the installer's own argv and out of `e2e-in-container.sh` — so a
future required flag breaks a test rather than a release, which is the thing that did not happen
this time.
"""

TEST = "tests/test_the_installer_builds_the_commands_it_says_it_does.py"

INSTALLER = "install.sh"

MUTATIONS = [
    # ── the defect as it shipped in v0.2.0 ──────────────────────────────────────────────────────
    ("TODAY'S DEFECT: the installer stops stating a runtime, so `init` refuses wherever there is "
     "no controlling terminal",
     INSTALLER,
     "        in_the_cli_asking_questions init --out /out/.env.compose --runtime compose $INIT_ARGS \\",
     "        in_the_cli_asking_questions init --out /out/.env.compose $INIT_ARGS \\"),

    ("the --force path stops stating it, so a re-run of a half-finished install refuses",
     INSTALLER,
     "init --out /out/.env.compose --force --runtime compose $INIT_ARGS",
     "init --out /out/.env.compose --force $INIT_ARGS"),

    ("the stated runtime moves AFTER the user's flags, where a later --runtime can no longer "
     "override it — stating becomes forcing",
     INSTALLER,
     "        in_the_cli_asking_questions init --out /out/.env.compose --runtime compose $INIT_ARGS \\",
     "        in_the_cli_asking_questions init --out /out/.env.compose $INIT_ARGS --runtime compose \\"),

    ("the installer answers `local` — a door with no Docker, no compose file and no images, after "
     "this script has already fetched and checksummed all three",
     INSTALLER,
     "init --out /out/.env.compose --runtime compose $INIT_ARGS",
     "init --out /out/.env.compose --runtime local $INIT_ARGS"),

    ("the dry run no longer shows the runtime it would state, so the reader cannot tell what a "
     "real run answers on their behalf",
     INSTALLER,
     'say "  would run: openfactory init --out /out/.env.compose --runtime compose"',
     'say "  would run: openfactory init --out /out/.env.compose"'),

    # ── the guards ──────────────────────────────────────────────────────────────────────────────
    ("the interview is no longer RUN against the real CLI — the assertion becomes a description, "
     "which is exactly what let this ship",
     TEST,
     '    result = CliRunner().invoke(app, ["init", "--out", str(dest), *flags, *vendor])',
     '    result = CliRunner().invoke(app, ["init", "--help"])'),

    ("the vendor flags stop coming from e2e-in-container.sh and are hard-coded here, so the guard "
     "and the job it speaks for can drift apart",
     TEST,
     '    supplied = e2e.split("set -- \\"$@\\" --", 1)[1].split("\\n\\n")[0]',
     '    supplied = "--forge github --tracker github --github-auth token"'),

    # ── two cuts that first attacked the guards and SURVIVED, re-aimed at the code ───────────────
    #
    # Each removed the only assertion making a claim, so nothing else could go red — a cut the
    # suite cannot be asked to catch. Aimed at the code they are regressions, and each is red only
    # because of the assertion the surviving cut had removed.

    ("the refusal stops naming the FLAG a person has to pass, so a scripted install is told only "
     "that something is required",
     "openfactory/cli.py",
     'typer.echo(f"✗ --{flag} is required when this does not run in a terminal "\n'
     '                       f"(one of: {\', \'.join(entry.options)})")',
     'typer.echo("✗ a required answer is missing")'),

    ("the accepted-flag reader answers for EVERY command at once, so a stray docker flag after "
     "the image passes as long as some other subcommand happens to declare it",
     TEST,
     "    found = group.commands.get(command)\n"
     "    if found is None:\n"
     "        return set()\n"
     "    return {opt for param in found.params for opt in getattr(param, \"opts\", [])}",
     "    return {opt for cmd in group.commands.values() for param in cmd.params\n"
     "            for opt in getattr(param, \"opts\", [])}"),
]
