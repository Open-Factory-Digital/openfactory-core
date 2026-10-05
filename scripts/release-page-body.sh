#!/bin/sh
# The top of a release's GitHub page: how to install THIS release, and which images it published.
#
#   sh scripts/release-page-body.sh <tag>      (writes it to stdout)
#
# THE INSTALL LINE DEPENDS ON WHAT THE TAG IS (#531). A final release (`v0.5.0`) is installed by the
# one-line install, `curl -fsSL https://openfactory.digital/install.sh | sh`, because that resolves
# the latest final release. A candidate (a tag with a hyphen, `v0.5.0-rc.1`) is a pre-release, and
# nothing that resolves "the latest" ever reaches it, by design (docs/RELEASING.md): it is
# installed only by naming it. The page used to print the one-line install for every tag, so
# v0.5.0-rc.1's page told its testers to install v0.4.2, until the release manager corrected it by
# hand.
#
# A SCRIPT THE SUITE RUNS, for the reason `scripts/collect-release-assets.sh` gives: a `run:` or
# `body:` block in the workflow can only be executed by tagging.
# `tests/test_a_release_page_tells_how_to_install_what_it_is.py` runs it for both kinds of tag.

# THE PROSE IS NOT WRAPPED: a release page renders a newline inside a paragraph as a line break.

set -eu

tag=${1:?usage: sh scripts/release-page-body.sh <tag>}
repo="https://github.com/Open-Factory-Digital/openfactory-core"
# shellcheck disable=SC2016  # the backticks are Markdown, not a command substitution
fence='```'

case "$tag" in
    v[0-9]*) ;;
    *) echo "release-page-body.sh: '$tag' is not a version tag (v<x.y.z>…)" >&2; exit 2 ;;
esac

case "$tag" in
    *-*)
        cat <<EOF
### Install this release candidate

**This is a pre-release, for testing.** The one-line install keeps installing the latest final release. To install this candidate, name it:

${fence}bash
curl -fsSL ${repo}/releases/download/${tag}/install.sh -o install.sh
sh install.sh --version ${tag}
${fence}

To upgrade an existing installation to it (every value in \`.env.compose\` is kept; only the pinned version moves):

${fence}bash
sh install.sh --version ${tag} --dir <the installation's directory> --force
${fence}

Going back to the last final release is the same command with its tag, and it is not rehearsed: take a backup of the installation first.
EOF
        # PyPI's spelling of a candidate: `v0.5.0-rc.1` is published as `0.5.0rc1`
        wheel=$(printf '%s\n' "${tag#v}" | sed -n 's/^\([0-9][0-9.]*\)-rc\.\([0-9][0-9]*\)$/\1rc\2/p')
        if [ -n "$wheel" ]; then
            # shellcheck disable=SC2016  # Markdown backticks, printed as they are
            printf '\nThe wheel: `pip install openfactory==%s`.\n' "$wheel"
        fi
        ;;
    *)
        cat <<EOF
### Install

${fence}bash
curl -fsSL https://openfactory.digital/install.sh | sh
${fence}

Re-running the installer with \`--force\` is the upgrade path: every value in \`.env.compose\` is kept, credentials included, and only the pinned version moves.
EOF
        ;;
esac

cat <<EOF

Images published for this tag (\`linux/amd64\`, \`linux/arm64\`):

- \`ghcr.io/open-factory-digital/openfactory-worker:${tag}\`
- \`ghcr.io/open-factory-digital/openfactory-sandbox:${tag}\`
- \`ghcr.io/open-factory-digital/openfactory-cli:${tag}\`

Verify the assets below with \`sha256sum -c SHA256SUMS --ignore-missing\`.
EOF
