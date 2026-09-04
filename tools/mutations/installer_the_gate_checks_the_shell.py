"""P1.4 — the shell script a stranger runs first is checked by the command the gate runs.

Run:  .venv/bin/python tools/mutate.py tools/mutations/installer_the_gate_checks_the_shell.py

THE CUT THAT MATTERS MOST IS THE QUIET ONE. `make lint` passing while checking nothing is the
failure this arrangement exists to prevent, and it is the shape a helpful person actually
produces: shellcheck is a Haskell binary that `make install` cannot supply, so "skip it if it is
not there" is the obvious kindness. It is also how the add-on packages went unlinted for as long
as they did — absence read as compliance.

The rest are the ways the arrangement gets undone while still looking checked: shellcheck moved
into a CI-only step (green on every laptop, run on one machine), the dialect widened to bash so a
bashism passes here and fails on the Debian-family machines this is most likely to be piped into,
CI inlining ruff again so nothing the Makefile adds ever reaches the gate, and the end-to-end job
wired onto `pull_request`, where it would be red for reasons no PR caused.
"""

TEST = "tests/test_the_gate_checks_the_shell_script_a_stranger_runs_first.py"

MAKEFILE = "Makefile"
CI = ".github/workflows/ci.yml"
E2E = ".github/workflows/install-e2e.yml"
WORKFLOW = ".github/workflows/release.yml"

MUTATIONS = [
    ("`make lint` stops checking the installer at all",
     MAKEFILE,
     "\t@$(call shellcheck-or-refuse,$(SHELL_SCRIPTS))",
     "\t@true"),

    ("a machine with neither shellcheck nor Docker SKIPS quietly — lint passes, nothing is checked",
     MAKEFILE,
     '\t  echo "    start Docker         (this then runs $(SHELLCHECK_IMAGE))" >&2; \\\n'
     "\t  exit 1; \\",
     '\t  echo "    start Docker         (this then runs $(SHELLCHECK_IMAGE))" >&2; \\\n'
     "\t  exit 0; \\"),

    ("the scripts are judged as bash, so a bashism passes here and fails on Debian's /bin/sh",
     MAKEFILE,
     "\t  shellcheck -s sh $(1); \\",
     "\t  shellcheck -s bash $(1); \\"),

    ("only install.sh is checked, and the script that decides the public build is not",
     MAKEFILE,
     "SHELL_SCRIPTS := install.sh docker/install-addons.sh",
     "SHELL_SCRIPTS := install.sh"),

    ("the container is tried before a local shellcheck, so everyone waits for a pull",
     MAKEFILE,
     "\tif command -v shellcheck >/dev/null 2>&1; then \\\n"
     "\t  shellcheck -s sh $(1); \\\n"
     "\telif docker info >/dev/null 2>&1; then \\",
     "\tif docker info >/dev/null 2>&1; then \\\n"
     "\t  docker run --rm -v \"$(CURDIR):/mnt\" $(SHELLCHECK_IMAGE) -s sh "
     "$(addprefix /mnt/,$(1)); \\\n"
     "\telif command -v shellcheck >/dev/null 2>&1; then \\"),

    ("CI inlines ruff again, so nothing the Makefile adds to the gate ever reaches CI",
     CI,
     "      - run: make lint",
     "      - run: ruff check openfactory/ tests/"),

    # ── the end-to-end job ──────────────────────────────────────────────────────────────────────
    ("the end-to-end job stops checking that the panel answers",
     "scripts/e2e-verify.sh",
     '[ "$panel" = up ] || { echo "the panel never answered on :${PORT}" >&2; exit 1; }',
     "true"),

    # RE-AIMED 2026-09-04: the verification body moved into `scripts/e2e-verify.sh` after an
    # apostrophe in a comment closed the `sh -c` block it lived in and stopped v0.1.4.
    ("the end-to-end job accepts a refusal with no remedy",
     "scripts/e2e-verify.sh",
     '        assert finding["remedy"].strip(), f"{finding[\'check\']} refuses with no remedy"',
     "        pass"),

    # ── the circular gate ───────────────────────────────────────────────────────────────────────
    #
    # `release: published` runs from the DEFAULT BRANCH ONLY. With this workflow living on a
    # feature branch it could never fire, so it never ran for v0.1.0 or v0.1.1 and the asset-name
    # defect that broke every v0.1.1 install was found by a person from the outside. The first cut
    # restores exactly that.
    ("the end-to-end install goes back to `release: published`, which a branch can never fire",
     E2E,
     "on:\n  workflow_call:",
     "on:\n  release:\n    types: [published]\n  workflow_call:"),

    ("the end-to-end install is wired onto every pull request, where it cannot pass",
     E2E,
     "on:\n  workflow_call:",
     "on:\n  pull_request:\n  workflow_call:"),

    ("nothing calls the end-to-end install, so it exists and never runs",
     WORKFLOW,
     "    uses: ./.github/workflows/install-e2e.yml",
     "    uses: ./.github/workflows/ci.yml"),

    ("the install is verified before the release exists, so there is nothing to install",
     WORKFLOW,
     "  verify_the_install:\n    if: startsWith(github.ref, 'refs/tags/v')\n    needs: release",
     "  verify_the_install:\n    if: startsWith(github.ref, 'refs/tags/v')\n    needs: images"),
]
