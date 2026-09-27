"""An upgrade through the installer keeps every value in `.env.compose` (#363).

Run:  .venv/bin/python tools/mutate.py tools/mutations/363_an_upgrade_keeps_every_value_the_file_holds.py

The first row is the defect as it shipped: `init --force` wrote the answers' file over the one
that held the credentials. Measured on 2026-09-27 through `install.sh`, v0.2.1 → v0.3.0: three
credentials, a moved port and an added row were gone. Rows 2-8 attack `carry_over` and what
`init` says about it. Rows 9-11 are the installer's pin: the one written only when missing, a
failed copy swallowed, and the copy left behind.

ROWS 12-19 ARE THE REVIEW OF #366:
- a failed copy of the pin turned into a one-line file (row 10);
- a kept work directory that nothing made or checked, a declared one that lost to it, and the
  installer resolving another;
- the to-do filter's substring search, and the "was taken from your login" notice left behind;
- a value's trailing spaces, and compose's `export NAME=`.

Row 8's refusal is also proven through a file that is not text, so it stays red where the suite
runs as root, which reads a 0000 file.
"""

TEST = "tests/test_a_re_run_keeps_every_value_the_file_holds.py"

CLI = "openfactory/cli.py"
DEPLOYMENT = "openfactory/onboarding/deployment.py"
INSTALLER = "install.sh"
INSTALLER_TEST = "tests/test_the_installer_builds_the_commands_it_says_it_does.py"

MUTATIONS = [
    ("TODAY'S DEFECT: a re-run writes the answers' file over the one that held the values", CLI,
     "    text, kept = ((rendered.text, []) if previous is None\n"
     "                  else carry_over(previous, rendered.text, ours=ours))",
     "    text, kept = rendered.text, []"),

    ("a row the person filled takes this run's value instead", DEPLOYMENT,
     "            if held.get(name, \"\").strip() and held[name] != value:",
     "            if False:"),

    ("a row only the old file had is dropped", DEPLOYMENT,
     "    if extra:\n        if lines and not lines[-1].endswith(\"\\n\"):",
     "    if False:\n        if lines and not lines[-1].endswith(\"\\n\"):"),

    ("the old pin is carried over, holding the upgrade on the release it left", DEPLOYMENT,
     "_NEVER_CARRIED = frozenset({\"OPENFACTORY_VERSION\"})",
     "_NEVER_CARRIED = frozenset()"),

    ("a row the person emptied stays empty instead of taking what this run generates", DEPLOYMENT,
     "            if held.get(name, \"\").strip() and held[name] != value:",
     "            if name in held and held[name] != value:"),

    ("what was kept is not named", CLI,
     "    if kept:\n        # NAMES, NEVER VALUES, for the reason below.",
     "    if False:\n        # NAMES, NEVER VALUES, for the reason below."),

    ("a credential the file already holds stays on the to-do list", CLI,
     "    remaining = still_to_do(rendered.remaining, kept)",
     "    remaining = list(rendered.remaining)"),

    ("a file that exists and cannot be read is written over", CLI,
     "        except (OSError, UnicodeDecodeError) as exc:\n",
     "        except (OSError, UnicodeDecodeError) as exc:\n            previous = None\n        if False:\n"),

    ("the installer keeps the old pin beside the new one", INSTALLER,
     "        grep -v '^OPENFACTORY_VERSION=' \"$DIR/.env.compose\" > \"$pinned\" || rc=$?",
     "        cat \"$DIR/.env.compose\" > \"$pinned\" || rc=$?",
     INSTALLER_TEST),

    ("a copy of the pin that failed is written back, leaving a one-line file", INSTALLER,
     "    if [ \"$rc\" -gt 1 ] || ! printf",
     "    if false || ! printf",
     INSTALLER_TEST),

    ("the pin's failed copy, which holds the credentials, is left behind", INSTALLER,
     "        rm -f \"$pinned\"\n        die \"could not copy",
     "        die \"could not copy",
     INSTALLER_TEST),

    ("the installer resolves a work directory other than the one its file names", INSTALLER,
     "    elif [ -n \"$kept_work_dir\" ]; then\n        WORK_DIR=\"$kept_work_dir\"\n",
     "",
     INSTALLER_TEST),

    ("a declared work directory loses to the one the old file named", CLI,
     "    ours = frozenset({\"OPENFACTORY_WORK_DIR\"}) if declared else frozenset()",
     "    ours = frozenset()"),

    ("a kept work directory is written but never made", CLI,
     "        work_dir = written\n",
     "        pass\n"),

    ("a kept work directory compose cannot bind is written anyway", CLI,
     "        if not written.startswith(\"/\") or \"~\" in written:",
     "        if False:"),

    ("the to-do filter searches the English for the kept names again", DEPLOYMENT,
     "            if not (names := named(line)) or not all(name in done for name in names)]",
     "            if not any(name in line for name in done)]"),

    ("the notice that a login filled a row stays after the row was kept", DEPLOYMENT,
     "        if match := _TAKEN.match(line):\n            return [match.group(1)]\n",
     ""),

    ("a carried value loses its trailing spaces", DEPLOYMENT,
     "        row = _ROW.match(line.lstrip())\n        if row and row.group(1) not in never:",
     "        row = _ROW.match(line.strip())\n        if row and row.group(1) not in never:"),

    ("a row written `export NAME=` is neither carried nor reported", DEPLOYMENT,
     "_ROW = re.compile(r\"^(?:export\\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$\")",
     "_ROW = re.compile(r\"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$\")"),
]
