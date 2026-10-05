"""A release's page tells how to install that release (#531), proven by breaking it.

Run:  .venv/bin/python tools/mutate.py tools/mutations/531_a_release_page_installs_what_it_is.py

v0.5.0-rc.1's page printed the one-line install, which resolves the latest final release, so it
told its testers to install v0.4.2. Each row puts one way back.
"""

TEST = "tests/test_a_release_page_tells_how_to_install_what_it_is.py"
SCRIPT = "scripts/release-page-body.sh"
WORKFLOW = ".github/workflows/release.yml"

MUTATIONS = [
    ("THE DEFECT: a candidate's page prints the one-line install, which installs the last final",
     SCRIPT,
     "    *-*)\n        cat <<EOF\n### Install this release candidate\n",
     "    *-never-*)\n        cat <<EOF\n### Install this release candidate\n"),

    ("a candidate's page installs it without naming it", SCRIPT,
     "sh install.sh --version ${tag}\n${fence}\n",
     "sh install.sh\n${fence}\n"),

    ("the workflow publishes a page of its own beside the script's", WORKFLOW,
     "          body_path: release-page.md\n",
     "          body: |\n            ### Install\n"),

    ("the page is written for a tag the workflow did not push", WORKFLOW,
     "          TAG: ${{ github.ref_name }}\n          # the page names the wheel",
     "          TAG: v0.0.0\n          # the page names the wheel"),

    ("a paragraph on the page is wrapped, and renders as broken lines", SCRIPT,
     "**This is a pre-release, for testing.** The one-line install keeps installing the latest "
     "final release. To install this candidate, name it:",
     "**This is a pre-release, for testing.** The one-line install keeps installing the latest\n"
     "final release. To install this candidate, name it:"),
]
