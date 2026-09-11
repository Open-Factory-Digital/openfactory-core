"""Task AC — the two modes that promise not to write are the two the suite now RUNS.

Run:  .venv/bin/python tools/mutate.py tools/mutations/installer_promise_keeping_modes_write_nothing.py

`git grep -l 'dry.run' -- tests/` was empty before this change. `--dry-run` ("print what would
happen; touch nothing") and a refused `--uninstall` were the two run modes carrying the strongest
promises in the file and the two nothing executed — so a write outside `$DIR` lived in both for
four releases without a single red test.

The first cut is today's defect, restored exactly: `mkdir -p "$WORK_DIR"` back at the bottom of
`resolve_the_work_directory`, which `main()` calls before the `--uninstall` branch and before the
`run` wrapper that turns a dry run into a printed line. It is invisible on any machine that has
installed once — `mkdir -p` is idempotent — and appears on the machine of the stranger who runs
`--dry-run` first to decide whether to trust the script. That is the reader these two modes exist
for, and the only reader who ever saw it.

The later cuts attack the guards rather than the script: a guard that reads the file as text
instead of as code passes on a comment SAYING the mkdir moved (I wrote that bug and it failed,
which is why the cut is here), and a `--dry-run` guard that never checks a real run would create
the directory can be satisfied by deleting the creation altogether.
"""

TEST = "tests/test_the_installer_builds_the_commands_it_says_it_does.py"

INSTALLER = "install.sh"

_MADE_IN_MAIN = '''    run mkdir -p "$WORK_DIR" \\
        || die "could not create the job workspace \\`${WORK_DIR}\\`." \\
               "Set OPENFACTORY_WORK_DIR to an absolute path you own and run this again."
'''
_RESOLVES_ONLY = "    # The creation now lives in `main()`, after the `--uninstall` branch"

MUTATIONS = [
    # ── the defect, exactly as it shipped in v0.1.6 through v0.1.9 ───────────────────────────────
    ("TODAY'S DEFECT: the creation moves back into resolve_the_work_directory, so --dry-run and a "
     "refused --uninstall each write a directory outside the target",
     INSTALLER,
     _RESOLVES_ONLY,
     '    mkdir -p "$WORK_DIR"\n' + _RESOLVES_ONLY),

    ("the creation is made unconditionally rather than through `run`, so --dry-run performs the "
     "one write it promises not to",
     INSTALLER,
     '    run mkdir -p "$WORK_DIR" \\',
     '    mkdir -p "$WORK_DIR" \\'),

    ("the creation moves above the --uninstall branch, so a refusal writes on its way out",
     INSTALLER,
     "    if [ \"$UNINSTALL\" -eq 1 ]; then uninstall; return 0; fi\n",
     _MADE_IN_MAIN + "\n    if [ \"$UNINSTALL\" -eq 1 ]; then uninstall; return 0; fi\n"),

    ("the creation moves below run_preflight, which is the first step to bind-mount it",
     INSTALLER,
     _MADE_IN_MAIN,
     ""),

    # ── the guards themselves ───────────────────────────────────────────────────────────────────
    ("the control-flow guard reads the file as text, so the COMMENT saying the mkdir moved out "
     "satisfies it — the defect class CONTRIBUTING names by name",
     TEST,
     '    code = "\\n".join(installer_script.code_lines())\n    main = code[code.index("main() {"):]',
     '    code = INSTALLER.read_text()\n    main = code[code.index("main() {"):]'),

    ("the environment is inherited instead of built, so a work directory left by any earlier run "
     "on this machine hides the write being measured",
     TEST,
     '        ["env", "-i", f"PATH={binaries}:/usr/bin:/bin", f"HOME={house}",',
     '        ["env", f"PATH={binaries}:/usr/bin:/bin", f"HOME={house}",'),

    # ── three cuts that first attacked the guards and SURVIVED, re-aimed at the script ───────────
    #
    # Each removed one assertion while a sibling test asserted the same property — duplicate
    # coverage, not a weak guard, and a cut the suite cannot be expected to catch. Aimed at
    # `install.sh` instead they are real regressions, and each is red only because of the
    # assertion the surviving cut had removed. Written this way they measure something.

    ("the promise is kept by SILENCE rather than by `run` — a dry run creates nothing and also "
     "never tells the reader it would, which is the whole point of the mode",
     INSTALLER,
     '    run mkdir -p "$WORK_DIR" \\',
     '    [ "$DRY_RUN" -eq 1 ] || mkdir -p "$WORK_DIR" \\'),

    ("--uninstall checks for a terminal BEFORE checking there is anything to uninstall, so the "
     "refusal a stranger gets names the wrong problem",
     INSTALLER,
     '    [ -f "$DIR/docker-compose.yml" ] \\',
     '    [ -t 0 ] || die "--uninstall needs a terminal." "Run it from a shell."\n'
     '    [ -f "$DIR/docker-compose.yml" ] \\'),

    ("the work directory moves to a different path outside the target — still exactly one write, "
     "so a guard that only COUNTS them cannot see it",
     INSTALLER,
     '    WORK_DIR="${data_home}/openfactory/work"',
     '    WORK_DIR="${data_home}/openfactory-jobs"'),
]
