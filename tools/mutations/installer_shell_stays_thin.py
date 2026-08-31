"""P1.2 — the installer stays thin, needs no root, pins its version and reports nothing.

Run:  .venv/bin/python tools/mutate.py tools/mutations/installer_shell_stays_thin.py

Four properties, and each of them is the kind that erodes for a good local reason rather than in
one bad commit.

THE TWO FACTS. Every check that migrates into the shell is a diagnosis with no remedy field, no
test and no JSON — invisible to the agent lane, which reads `preflight --json` and nothing else.
The count is the conversation: a third fact moves the number in a commit that says why.

`sudo`. P0.4 removed the one root command from the first-run path by putting the job workspace
under `$HOME`. The cheapest way to undo that is one `sudo mkdir` added to fix something else.

THE PIN. `docker-compose.yml` defaults to `main` because a CONTRIBUTOR wants their branch. The
only thing standing between a user and that floating tag is the line where `install.sh` writes an
explicit version into `.env.compose` — a line that looks redundant beside a default that is
already there.

TELEMETRY. "Sends nothing anywhere" is a sentence on a public page. The cuts add a beacon two ways:
a host nobody vetted, and a POST to a host that is allowed.
"""

TEST = "tests/test_the_installer_knows_exactly_two_facts_the_package_does_not.py"

SH = "install.sh"
SUDO_TEST = "tests/test_the_installer_never_calls_sudo.py"
PIN_TEST = "tests/test_the_installer_pins_a_version_and_never_installs_a_floating_tag.py"

MUTATIONS = [
    # ── the shell gets opinions of its own ──────────────────────────────────────────────────────
    ("a third fact joins the two — a diagnosis with no remedy and no JSON",
     SH,
     "# openfactory:facts:end",
     "there_is_enough_disk() {\n"
     "    [ \"$(df -k . | awk 'NR==2 {print $4}')\" -gt 8000000 ] \\\n"
     "        || die \"not enough disk.\" \"Free some space.\"\n"
     "}\n"
     "# openfactory:facts:end"),

    ("the shell works out the machine's architecture instead of asking preflight",
     SH,
     "    if [ \"$UNINSTALL\" -eq 1 ]; then uninstall; return 0; fi",
     "    arch=$(uname -m)\n"
     "    [ \"$arch\" = x86_64 ] || [ \"$arch\" = aarch64 ] || die \"unsupported arch.\" \"Build from source.\"\n"
     "    if [ \"$UNINSTALL\" -eq 1 ]; then uninstall; return 0; fi"),

    ("the shell stops asking the package anything at all",
     SH,
     "    in_the_cli preflight || true",
     "    say \"  (skipped)\""),

    # ── root creeps back ────────────────────────────────────────────────────────────────────────
    ("one `sudo mkdir` comes back, and P0.4's whole point with it",
     SH,
     "    run mkdir -p \"$DIR\"",
     "    run sudo mkdir -p \"$DIR\"",
     SUDO_TEST),

    ("the installer writes outside the directory the user gave it",
     SH,
     "    run mkdir -p \"$DIR\"",
     "    run mkdir -p /usr/local/share/openfactory\n    run mkdir -p \"$DIR\"",
     SUDO_TEST),

    # ── the pin ─────────────────────────────────────────────────────────────────────────────────
    ("the version is never written into .env.compose, so the install follows `main`",
     SH,
     "    if ! grep -q '^OPENFACTORY_VERSION=' \"$DIR/.env.compose\" 2>/dev/null; then\n"
     "        printf 'OPENFACTORY_VERSION=%s\\n' \"$VERSION\" >> \"$DIR/.env.compose\"\n"
     "    fi",
     "    :",
     PIN_TEST),

    ("the images are pulled at a floating tag",
     SH,
     '    run docker pull --quiet "${REGISTRY}/openfactory-cli:${VERSION}" \\',
     '    run docker pull --quiet "${REGISTRY}/openfactory-cli:latest" \\',
     PIN_TEST),

    ("a release tag is hard-coded here, becoming a second home for the number",
     SH,
     'VERSION=""',
     'VERSION="v0.1.0"',
     PIN_TEST),

    ("the assets are fetched through the moving `latest` path rather than the resolved tag",
     SH,
     '    base="${RELEASES}/download/${VERSION}"',
     '    base="${RELEASES}/latest/download"',
     PIN_TEST),

    ("what github answered is used unchecked, so an intercepted redirect becomes a fetch path",
     SH,
     '    case "$VERSION" in\n        v*) : ;;',
     '    case "$VERSION" in\n        *) : ;;',
     PIN_TEST),

    # ── telemetry ───────────────────────────────────────────────────────────────────────────────
    ("a host nobody vetted appears in the script",
     SH,
     'RELEASES="https://github.com/${ORG}/${REPO}/releases"',
     'RELEASES="https://github.com/${ORG}/${REPO}/releases"\n'
     'STATS="https://telemetry.example.com/install"',
     SUDO_TEST),

    ("a report about the machine is POSTed to a host that IS allowed",
     SH,
     "    start_the_stack\n    wait_for_the_panel",
     "    curl -fsS -X POST \"https://github.com/collect\" --data \"v=${VERSION}\" >/dev/null 2>&1\n"
     "    start_the_stack\n    wait_for_the_panel",
     SUDO_TEST),
]
