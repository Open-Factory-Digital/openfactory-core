#!/bin/sh
# Assemble the files a pinned install downloads, and their checksums.
#
#   sh scripts/collect-release-assets.sh [<destination>]      (default: dist)
#
# WHY THIS IS A SCRIPT AND NOT A `run:` BLOCK. It used to be eleven lines inside
# `.github/workflows/release.yml`, and nothing outside a real tag could execute them — so a shell
# bug in it cost a version number to discover. Two of them did:
#
#   v0.1.1  the template was attached as `.env.compose.example`; GitHub renames a leading-dot asset
#           to `default.…`, so `install.sh` fetched a 404 and every install died at the interview.
#           The same dot hid it from `sha256sum ./*`, which does not match dotfiles, so it was also
#           never checksummed. One character, two failures, opposite halves of the release.
#   v0.1.2  the guard added for that (a loop over `dist/.*`) reported ITS OWN unexpanded pattern
#           and exited 1 — the release job failed, no Release was created, and `verify_the_install`
#           was skipped for the third tag running.
#
# THE FOURTH TIME A CHECK HAS BEEN PRESENT, READ CORRECTLY, AND BEEN UNABLE TO DO ITS JOB — and the
# first where the check WAS the failure rather than what it watched. The three before it were a
# guard reading a comment that quoted the line it was watching, two end-to-end assertions satisfied
# by the words `8787` and `remedy` in prose, and an asset guard satisfied by a comment describing
# the very defect. The pattern is the same each time: something that looks like a check, and cannot
# fail for the reason it exists.
#
# So this file is executable by the suite (`tests/test_the_release_assembles_what_the_installer_
# downloads.py` runs it, both directions), shellcheck'd by `make lint`, and called by the workflow.
# A workflow whose logic can only be run by tagging is the same circularity that was just removed
# from the end-to-end job, one layer down.

set -eu

dist="${1:-dist}"
mkdir -p "$dist"

cp docker-compose.yml "$dist/"

# THE TEMPLATE IS ATTACHED WITHOUT ITS LEADING DOT. GitHub does not permit a release asset name to
# begin with one and silently rewrites it to `default.…`; `install.sh` renames it back on arrival,
# because `.env.compose.example` is the name docker-compose.yml's header and the README tell a
# person to copy. Measured against the real v0.1.1 release: `.env.compose.example` 404,
# `default.env.compose.example` 200.
cp .env.compose.example "$dist/env.compose.example"

# `install.md` joins from Phase 2; copied only when present so this is runnable before that lands.
for optional in install.sh install.md; do
    if [ -f "$optional" ]; then cp "$optional" "$dist/"; fi
done

# NOTHING IN THE DESTINATION MAY START WITH A DOT, because such a file is renamed by GitHub on
# upload AND skipped by the checksum glob below — both silently, both at the moment the mistake is
# made rather than when it is felt.
#
# `find … -name '.?*'` RATHER THAN A GLOB, and that is the v0.1.2 defect not being repeated. The
# first version was `for f in dist/.*`, and an unmatched glob is left LITERAL by the shell — so with
# no dotfiles present the loop ran once, over the string `dist/.*`, and reported it. Bash 5.2's
# `globskipdots` is what makes that reachable: it stops `.*` matching `.` and `..`, so the two
# entries the loop's `case` was written to skip never appear and the pattern matches nothing at all.
# Verified here — with `globskipdots` on the loop reports `dist/.*`; with it off, or under dash, it
# is silent. `ubuntu-latest` runs bash 5.2+, so CI is exactly where it fires.
#
# `-name '.?*'` needs at least one character after the dot, so `.` and `..` cannot match and there
# is no pattern left to leak. `docker/install-addons.sh` has carried the guarded form of this since
# it was written — *"a glob that matched nothing leaves the pattern itself"* — one directory away
# from the file that got it wrong.
# `-mindepth 1` KEEPS THE STARTING POINT OUT OF ITS OWN SEARCH. `find` reports the directory it
# was given at depth 0, so a destination whose own name begins with a dot — `.dist`, or any temp
# directory a test hands it — matched the pattern and the script refused to assemble anything.
# Found by running it (2026-09-01), which is the entire argument for this being a script.
dotted=$(find "$dist" -mindepth 1 -maxdepth 1 -name '.?*')
if [ -n "$dotted" ]; then
    echo "$dist holds files whose names start with a dot:" >&2
    echo "$dotted" >&2
    echo "GitHub renames those to \`default.…\` on upload and the checksum glob below skips" >&2
    echo "them, both silently. Attach them without the leading dot." >&2
    exit 1
fi

# SHA256SUMS IS WHY THE ASSETS LIVE ON THE RELEASE AND NOT ON THE DOMAIN. GitHub Pages serves
# static files and can checksum nothing; a release can, and `install.sh` verifies what it
# downloaded against this file before running any of it — and refuses an asset this file does not
# cover, because `sha256sum -c --ignore-missing` succeeds when it matches nothing at all.
#
# Written from INSIDE the destination so the names in it are bare: `sha256sum -c` resolves them
# relative to the working directory, and a path prefix would make verification fail in the one
# directory a user actually runs it from.
( cd "$dist" && sha256sum ./* > SHA256SUMS && sed -i 's| \./| |' SHA256SUMS )
cat "$dist/SHA256SUMS"
