#!/bin/sh
# The end-to-end install, as it runs INSIDE the throwaway container.
#
#   docker run … debian:12-slim sh /e2e.sh
#
# WHY THIS IS A FILE AND NOT A `sh -c '…'` BLOCK IN THE WORKFLOW. It was one, and the v0.1.4
# release run died before `install.sh` executed a single line:
#
#   /home/runner/work/_temp/….sh: line 71: unexpected EOF while looking for matching `"'
#   ##[error]Process completed with exit code 2
#
# THE CAUSE WAS AN APOSTROPHE IN A COMMENT. The block was opened with `sh -c '`, and three of its
# comments contained a backslash followed by an apostrophe — written as an escape, around words
# like "compose" and in two possessives. THAT SEQUENCE ESCAPES NOTHING INSIDE SINGLE QUOTES: the
# apostrophe closes the string and everything after it is reinterpreted. Reproduced on a laptop
# with the identical message. A comment broke the shell, and no reviewer reading fourteen quote
# characters across two nesting levels was going to catch it — I wrote it and did not.
#
# The sequence is deliberately described here rather than shown: a guard
# (`test_no_body_hides_an_apostrophe_escape_that_would_close_a_quoted_block`) keeps it out of these
# files, and it caught this very comment quoting it.
#
# THIS IS THE THIRD SHELL DEFECT IN A WORKFLOW STEP THAT ONLY A TAG COULD EXECUTE: the glob that
# reported its own pattern (v0.1.2), the leading dot GitHub renames (v0.1.1), and now nested
# quoting (v0.1.4). Each cost a version number. `scripts/collect-release-assets.sh` ended that
# class for the release assembly by moving it out of YAML into a file `make lint` shellchecks and
# the suite runs; this is the same move for the job that installs.
#
# EVERYTHING ARRIVES AS AN ENVIRONMENT VARIABLE, so the caller has nothing to quote and this file
# has no interpolation holes of its own.
#
#   SOCKET_GID   the gid that owns the host's docker socket
#   SHARED       a directory the runner and this container both see at the SAME path
#   INSTALLER    where install.sh is mounted
#   VERSION      release tag to install, or empty for the newest
#   COMPOSE_PLUGIN_VERSION  pinned compose v2 to fetch

set -eu

: "${SOCKET_GID:?SOCKET_GID is required}"
: "${SHARED:?SHARED is required}"
INSTALLER="${INSTALLER:-/install.sh}"
VERSION="${VERSION:-}"
COMPOSE_PLUGIN_VERSION="${COMPOSE_PLUGIN_VERSION:-v2.32.4}"

apt-get update -qq
apt-get install -y -qq --no-install-recommends curl ca-certificates docker.io sudo >/dev/null

# NO PYTHON, AND THAT IS THE CLAIM UNDER TEST. `debian:12-slim` has none and nothing above adds
# one, so if any step of the install needed a host interpreter it would fail here, loudly. Checked
# rather than assumed, because `docker.io` has pulled in surprising things before.
if command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
    echo "this container HAS a Python — the whole point of this job is that it does not" >&2
    exit 1
fi

# THE COMPOSE PLUGIN IS NOT IN `docker.io`. Debian ships the v1 python script and no v2 plugin, so
# `docker compose up -d` — the last thing install.sh does — would fail with a message about
# compose not being a docker command, after everything else had worked.
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL -o /usr/local/lib/docker/cli-plugins/docker-compose \
    "https://github.com/docker/compose/releases/download/${COMPOSE_PLUGIN_VERSION}/docker-compose-linux-$(uname -m)"
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
docker compose version

# AN UNPRIVILEGED USER WHOSE PRIMARY GROUP IS ITS OWN, reaching docker through a SUPPLEMENTARY one.
# That is what a stock Linux workstation looks like and it is the arrangement `-u uid:gid` silently
# discards — as root, `id -u` is 0, any socket is readable, and the defect a reviewer found in
# install.sh could not appear here at all. A test whose environment excludes the failure is not
# covering it.
groupadd -g "$SOCKET_GID" hostdocker 2>/dev/null || true
useradd -m -u 1000 -U installer
usermod -aG "$SOCKET_GID" installer
mkdir -p "$SHARED"
chown installer:installer "$SHARED"

# THE WORK DIRECTORY LIVES UNDER THE SHARED PATH, so the bind `docker-compose.yml` makes resolves
# identically on the runner — compose talks to the RUNNER's daemon, and every bind source is
# resolved there. Left to its default it would sit under this container user's home, which the
# runner cannot see, and Docker would answer the missing source by creating it.
if [ -n "$VERSION" ]; then
    sudo -u installer -H env OPENFACTORY_WORK_DIR="$SHARED/work" \
        sh "$INSTALLER" --dir "$SHARED/openfactory" --version "$VERSION" \
        -- --forge github --tracker github --github-auth token \
           --harness claude_code --claude-auth subscription \
           --channel panel --panel-local
else
    sudo -u installer -H env OPENFACTORY_WORK_DIR="$SHARED/work" \
        sh "$INSTALLER" --dir "$SHARED/openfactory" \
        -- --forge github --tracker github --github-auth token \
           --harness claude_code --claude-auth subscription \
           --channel panel --panel-local
fi
