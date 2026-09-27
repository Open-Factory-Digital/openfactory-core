"""An upgrade through the installer keeps every value in `.env.compose` (#363).

Run:  .venv/bin/python tools/mutate.py tools/mutations/363_an_upgrade_keeps_every_value_the_file_holds.py

The first row is the defect as it shipped: `init --force` wrote the answers' file over the one
that held the credentials. Measured on 2026-09-27 through `install.sh`, v0.2.1 → v0.3.0: three
credentials, a moved port and an added row were gone. Rows 2-8 attack `carry_over` and what
`init` says about it. Rows 9 and 10 are the installer's half: the pin it wrote only when missing,
and the temporary copy it makes to replace it, which holds the credentials.
"""

TEST = "tests/test_a_re_run_keeps_every_value_the_file_holds.py"

CLI = "openfactory/cli.py"
DEPLOYMENT = "openfactory/onboarding/deployment.py"
INSTALLER = "install.sh"
INSTALLER_TEST = "tests/test_the_installer_builds_the_commands_it_says_it_does.py"

MUTATIONS = [
    ("TODAY'S DEFECT: a re-run writes the answers' file over the one that held the values", CLI,
     "    text, kept = (rendered.text, []) if previous is None else carry_over(previous, rendered.text)",
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
     "    remaining = [line for line in rendered.remaining if not any(name in line for name in kept)]",
     "    remaining = list(rendered.remaining)"),

    ("a file that exists and cannot be read is written over", CLI,
     "        except (OSError, UnicodeDecodeError) as exc:\n",
     "        except (OSError, UnicodeDecodeError) as exc:\n            previous = None\n        if False:\n"),

    ("the installer keeps the old pin beside the new one", INSTALLER,
     "    grep -v '^OPENFACTORY_VERSION=' \"$DIR/.env.compose\" > \"$pinned\" || true",
     "    cat \"$DIR/.env.compose\" > \"$pinned\"",
     INSTALLER_TEST),

    ("the pin's temporary copy, which holds the credentials, is left behind", INSTALLER,
     "    rm -f \"$pinned\"",
     "    :",
     INSTALLER_TEST),
]
