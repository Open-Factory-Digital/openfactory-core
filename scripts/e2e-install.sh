#!/bin/sh
# Drive the end-to-end install: prepare the shared directory, then run the installer inside a
# container that has Docker and no Python.
#
#   sh scripts/e2e-install.sh
#
# THE WORKFLOW'S `run:` IS THIS ONE LINE, and that is the point. The step used to be a `docker run
# … sh -c '…'` block with fourteen quote characters across two nesting levels, and the v0.1.4
# release died in it before `install.sh` ran at all — an apostrophe inside a COMMENT closed the
# single-quoted string. Nothing here is nested: this file invokes `docker run` with a mounted
# script and environment variables, so there is nothing to quote and nothing to escape.
#
#   OPENFACTORY_E2E_VERSION  release tag to install, or empty for the newest
#   OPENFACTORY_E2E_SHARED   the directory the runner and the container share, at the same path

set -eu

SHARED="${OPENFACTORY_E2E_SHARED:-/opt/openfactory-e2e}"
VERSION="${OPENFACTORY_E2E_VERSION:-}"
HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH='' cd -- "$HERE/.." && pwd)
SOCKET="${OPENFACTORY_E2E_SOCKET:-/var/run/docker.sock}"

[ -S "$SOCKET" ] || { echo "no docker socket at $SOCKET" >&2; exit 1; }
socket_gid=$(stat -c '%g' "$SOCKET" 2>/dev/null || stat -f '%g' "$SOCKET")

# A DIRECTORY THE RUNNER AND THE CONTAINER BOTH SEE AT THE SAME PATH. `install.sh` ends with
# `docker compose up -d`, whose API calls go to the HOST's daemon — so every bind source in
# docker-compose.yml is resolved there, not inside the container. An install that happened only
# inside would name paths the daemon cannot find, and Docker answers a missing bind source by
# CREATING it, so the stack would come up healthy over empty directories. It is also what lets the
# verification step, which runs outside, see what was installed.
if [ ! -d "$SHARED" ]; then
    mkdir -p "$SHARED" 2>/dev/null || sudo mkdir -p "$SHARED"
fi
chown 1000:1000 "$SHARED" 2>/dev/null || sudo chown 1000:1000 "$SHARED"

# `--network host` SO `localhost` MEANS THE SAME THING ON BOTH SIDES. The stack publishes its ports
# on the host; inside a bridged container `localhost:8787` is the container itself, so the
# installer's own wait-for-the-panel would burn three minutes and then report a panel that is up.
docker run --rm \
    --network host \
    -v "$SOCKET:/var/run/docker.sock" \
    -v "$ROOT/install.sh:/install.sh:ro" \
    -v "$HERE/e2e-in-container.sh:/e2e.sh:ro" \
    -v "$SHARED:$SHARED" \
    -w "$SHARED" \
    -e SOCKET_GID="$socket_gid" \
    -e SHARED="$SHARED" \
    -e INSTALLER=/install.sh \
    -e VERSION="$VERSION" \
    debian:12-slim sh /e2e.sh
