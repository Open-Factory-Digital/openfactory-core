"""#131: the backstop that catches the GNU-only `sed -i` before it ships.

ROW 1 IS THE REASON THIS FILE EXISTS. The behavioural guard — the release suite running the real
script — cannot pin this regression on Linux, because GNU sed accepts the line and the script
works. Reading the spelling does pin it, on every platform. That is the trade this backstop makes,
and the row proves it is worth making.
"""

TEST = "tests/test_the_shell_we_ship_runs_on_both_seds.py"
SCRIPT = "scripts/collect-release-assets.sh"
SRC = TEST

MUTATIONS = [
    ("the shipped defect returns to the release script — and unlike the behavioural row in "
     "`installer_the_release_assembles.py`, THIS one is red on Linux too", SCRIPT,
     "  && sed 's| \\./| |' SHA256SUMS > SHA256SUMS.bare && mv SHA256SUMS.bare SHA256SUMS )",
     "  && sed -i 's| \\./| |' SHA256SUMS )"),

    ("the sweep matches nothing, so the guard passes forever over an empty set", SRC,
     '_SHIPPED = ("scripts/*.sh", "install.sh", ".github/workflows/*.yml")',
     '_SHIPPED = ("scripts/*.nothing",)'),

    ("the pattern stops recognising the GNU-only form it exists to find", SRC,
     '_GNU_ONLY = re.compile(r"sed\\s+(?:-[a-zA-Z]+\\s+)*-i\\s+(?![\'\\"]{2})")',
     '_GNU_ONLY = re.compile(r"sed\\s+--in-place-and-never-written\\s+")'),

    ("…and the reverse: the portable BSD form is called a defect, which would send somebody to "
     "'fix' the one spelling that works everywhere", SRC,
     '_GNU_ONLY = re.compile(r"sed\\s+(?:-[a-zA-Z]+\\s+)*-i\\s+(?![\'\\"]{2})")',
     '_GNU_ONLY = re.compile(r"sed\\s+(?:-[a-zA-Z]+\\s+)*-i\\s+")'),
]
