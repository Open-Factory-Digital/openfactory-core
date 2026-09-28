"""A declared `OPENFACTORY_WORK_DIR` gets the check a kept one gets, in `init` and in the installer
alike, and the installer strips one pair of quotes from a value it reads (#367).

Run:  .venv/bin/python tools/mutate.py tools/mutations/367_a_declared_work_directory_is_checked_like_a_kept_one.py

The first row is the defect as it shipped in 0.4.0: `OPENFACTORY_WORK_DIR=~/work openfactory init`
wrote `~/work` into `.env.compose`, compose expanded no tilde, made a directory called `~` and
mounted an empty box — the "box saw 0 entries" defect reached by the road #366 left open when it
guarded the kept value. Rows 2-3 are each half of the rule in `default_work_dir`; rows 4-5 the same
rule in `install.sh`, which resolves the directory before anything is downloaded or made; row 6 the
installer's `tr -d '"'`, which took a double quote out of anywhere in a value.
"""

TEST = "tests/test_a_re_run_keeps_every_value_the_file_holds.py"

DEPLOYMENT = "openfactory/onboarding/deployment.py"
INSTALLER = "install.sh"
INSTALLER_TEST = "tests/test_the_installer_builds_the_commands_it_says_it_does.py"

_TILDE_CASE = (
    r'        *~*) die "OPENFACTORY_WORK_DIR=\`${WORK_DIR}\` holds a \`~\`, which compose does '
    r'not expand in a bind source: it would create a directory called \`~\` and mount an empty '
    r'box."' + " \\\n"
    r'                 "Write the whole path — e.g. OPENFACTORY_WORK_DIR=\$HOME/.local/share/'
    r'openfactory/work — and run this again." ;;')

_RELATIVE_CASE = (
    r'        *) die "OPENFACTORY_WORK_DIR=\`${WORK_DIR}\` is not an absolute path, and compose '
    r'resolves a relative bind source against wherever \`up\` runs."' + " \\\n"
    r'               "Write the whole path — e.g. OPENFACTORY_WORK_DIR=/srv/openfactory/work — '
    r'and run this again." ;;')

MUTATIONS = [
    ("TODAY'S DEFECT: a declared work directory is written as it came, `~` and all", DEPLOYMENT,
     '        if not declared.startswith("/") or "~" in declared:',
     "        if False:"),

    ("a relative declared path is accepted", DEPLOYMENT,
     '        if not declared.startswith("/") or "~" in declared:',
     '        if "~" in declared:'),

    ("a declared path holding a `~` is accepted", DEPLOYMENT,
     '        if not declared.startswith("/") or "~" in declared:',
     '        if not declared.startswith("/"):'),

    ("the installer accepts a path holding a `~`, declared or kept", INSTALLER,
     _TILDE_CASE,
     "        *~*) ;;",
     INSTALLER_TEST),

    ("the installer accepts a relative path, declared or kept", INSTALLER,
     _RELATIVE_CASE,
     "        *) ;;",
     INSTALLER_TEST),

    ("the installer takes a double quote out of anywhere in a value it reads", INSTALLER,
     "    sed -e 's/^\"\\(.*\\)\"$/\\1/'",
     "    tr -d '\"'",
     INSTALLER_TEST),
]
