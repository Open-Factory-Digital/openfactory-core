"""Task O — the release's asset assembly is executable, and both directions are proven.

Run:  .venv/bin/python tools/mutate.py tools/mutations/installer_the_release_assembles.py

THE FIRST CUT IS TODAY'S DEFECT, RESTORED VERBATIM: the `for f in dist/.*` loop that failed the
v0.1.2 release. An unmatched glob is left LITERAL by the shell, so with no dotfiles present the
loop ran once over the string `dist/.*` and reported it — the release job exited 1, no Release was
created, and the end-to-end install was skipped for the third tag running. Bash 5.2's
`globskipdots` is what makes it reachable: it stops `.*` matching `.` and `..`, so the two entries
the loop's `case` was written to skip never appear at all. `ubuntu-latest` has it on by default.

THE SECOND CUT IS THE v0.1.1 DEFECT, for the same reason: these two cost a version number each,
and the point of extracting the assembly into a script the suite runs is that neither can cost a
third.

The rest are the ways the assembly stops being trustworthy while still reading correctly — a guard
that cannot fire, a checksum file that covers nothing, names that break verification in the
directory a person actually runs it from.
"""

TEST = "tests/test_the_release_assembles_what_the_installer_downloads.py"

SCRIPT = "scripts/collect-release-assets.sh"
WORKFLOW = ".github/workflows/release.yml"

MUTATIONS = [
    # ── the two defects that cost a version number each ─────────────────────────────────────────
    ("THE v0.1.2 FAILURE: the dotfile guard is a bare glob and reports its own pattern",
     SCRIPT,
     "dotted=$(find \"$dist\" -mindepth 1 -maxdepth 1 -name '.?*')\n"
     "if [ -n \"$dotted\" ]; then\n"
     "    echo \"$dist holds files whose names start with a dot:\" >&2\n"
     "    echo \"$dotted\" >&2",
     "for f in \"$dist\"/.*; do\n"
     "    case \"$f\" in \"$dist\"/.|\"$dist\"/..) continue ;; esac\n"
     "    dotted=$f\n"
     "if [ -n \"$dotted\" ]; then\n"
     "    echo \"$dist holds files whose names start with a dot:\" >&2\n"
     "    echo \"$dotted\" >&2"),

    ("THE v0.1.1 FAILURE: the template is attached with its leading dot, which GitHub renames",
     SCRIPT,
     'cp .env.compose.example "$dist/env.compose.example"',
     'cp .env.compose.example "$dist/"'),

    # ── the guard stops being able to fire ──────────────────────────────────────────────────────
    ("the dotfile guard is removed, so a renamed asset ships silently",
     SCRIPT,
     'dotted=$(find "$dist" -mindepth 1 -maxdepth 1 -name \'.?*\')',
     'dotted=""'),

    ("the refusal stops naming the file, so a person is told something is wrong and not what",
     SCRIPT,
     '    echo "$dotted" >&2\n',
     ""),

    ("`find` reports its own starting point again, so a dotted destination assembles nothing",
     SCRIPT,
     'find "$dist" -mindepth 1 -maxdepth 1',
     'find "$dist" -maxdepth 1'),

    # ── the checksums ───────────────────────────────────────────────────────────────────────────
    ("the checksums are written over nothing, so --ignore-missing verifies nothing",
     SCRIPT,
     '( cd "$dist" && sha256sum ./* > SHA256SUMS && sed -i \'s| \\./| |\' SHA256SUMS )',
     '( cd "$dist" && sha256sum docker-compose.yml > SHA256SUMS && sed -i \'s| \\./| |\' SHA256SUMS )'),

    ("the checksum names keep their `./`, so verification fails where a user runs it",
     SCRIPT,
     " && sed -i 's| \\./| |' SHA256SUMS )",
     " )"),

    # ── the assembly stops being what the release runs ──────────────────────────────────────────
    ("the workflow stops calling the script, so what the suite proves is not what a tag does",
     WORKFLOW,
     "        run: sh scripts/collect-release-assets.sh dist",
     "        run: mkdir -p dist && cp docker-compose.yml dist/"),

    ("the release stops attaching an asset the installer downloads",
     SCRIPT,
     'cp docker-compose.yml "$dist/"',
     "true"),
]
