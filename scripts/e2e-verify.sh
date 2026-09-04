#!/bin/sh
# What the end-to-end claim is actually about: a panel that answers, and a preflight that speaks.
#
#   sh scripts/e2e-verify.sh
#
# A STACK THAT STARTS AND SERVES NOTHING IS NOT AN INSTALL, and a preflight that names nothing is
# not a diagnosis. Both halves are asserted here rather than in the workflow, for the reason
# `scripts/collect-release-assets.sh` and `scripts/e2e-in-container.sh` exist: shell inside YAML is
# shell nothing can run until a tag, and this repository has spent three version numbers learning
# it (a glob that matched its own pattern, a leading dot, an apostrophe in a comment).
#
#   OPENFACTORY_E2E_SHARED   where the install landed
#   OPENFACTORY_E2E_PORT     the panel's published port

set -eu

die() {
    printf '\ne2e-verify: %s\n' "$1" >&2
    if [ $# -gt 1 ]; then printf '  → %s\n' "$2" >&2; fi
    exit 1
}

SHARED="${OPENFACTORY_E2E_SHARED:-/opt/openfactory-e2e}"
PORT="${OPENFACTORY_E2E_PORT:-8787}"
INSTALL="${SHARED}/openfactory"
ENV_FILE="${INSTALL}/.env.compose"

[ -f "$ENV_FILE" ] || { echo "no install at ${INSTALL} — nothing to verify" >&2; exit 1; }

panel=""
n=0
while [ "$n" -lt 60 ]; do
    if curl -fsS "http://localhost:${PORT}/" >/dev/null 2>&1; then panel=up; break; fi
    sleep 5
    n=$((n + 1))
done
[ "$panel" = up ] || { echo "the panel never answered on :${PORT}" >&2; exit 1; }
echo "panel: up on :${PORT}"

# IT DOES NOT GO THROUGH COMPOSE AT ALL, AND `--env-file` WAS NEVER THE WHOLE PATH TO THE FILE.
#
# Three attempts died here. v0.1.5 ran `docker compose --env-file …` as the runner and could not
# read the 0600 file. v0.1.6 borrowed the owner's uid and that process could not reach the socket.
# v0.1.7's fix dropped `--env-file` — and v0.1.8 failed with the v0.1.5 message again, because
# `docker-compose.yml` DECLARES the file itself:
#
#     env_file:
#       - path: .env.compose
#         required: false
#
# Compose reads it because the PROJECT asks for it, not because the command line did, and
# `required: false` covers ABSENT, not present-and-unreadable. Reproduced locally on a two-service
# project with no `--env-file` anywhere: `open …/.env.compose: permission denied`, exit 1. So no
# change to the command line could ever have fixed this — which is why the same class returned in
# three different sentences.
#
# `docker exec` NEEDS NONE OF IT. Compose's own labels say which container is which, so the service
# is found without a compose file, without an env_file and without any credential. Measured in the
# same probe: exit 0. There is no capability compose was providing here that the labels do not —
# we were asking for the project because we had asked for the project.
worker=$(docker ps -q \
    --filter "label=com.docker.compose.project.working_dir=${INSTALL}" \
    --filter "label=com.docker.compose.service=worker" | head -n 1)
[ -n "$worker" ] || die "no running worker container for the install at ${INSTALL}." \
    "The stack started and the panel answered, so it should be there — \`docker ps -a\` will say what happened to it."

# PREFLIGHT EXITS NON-ZERO HERE AND THAT IS CORRECT: a CI machine has no agent credential, so the
# honest report is a red line with a remedy. What is asserted is that it produced a document at
# all, in the shape the agent lane reads — and that every refusal in it carries a remedy, which is
# the house rule this project holds every Finding to.
docker exec "$worker" openfactory preflight --json \
    > "${SHARED}/preflight.json" 2> "${SHARED}/preflight.err" || true

if [ ! -s "${SHARED}/preflight.json" ]; then
    # WHO WE ARE, WHEN IT FAILS. Reasoning from a log produced a wrong answer twice here, so the
    # log carries the evidence now. Printed only on failure.
    echo "" >&2
    echo "  who this step is: $(id 2>&1)" >&2
    echo "  the socket:       $(ls -ln /var/run/docker.sock 2>&1)" >&2
    echo "  the worker:       ${worker}" >&2
    die "\`openfactory preflight --json\` produced nothing, so there is no document to check." \
        "It said: $(tr '\n' ' ' < "${SHARED}/preflight.err" | cut -c1-300)"
fi

python3 - "${SHARED}/preflight.json" <<'PY'
import json
import sys

try:
    with open(sys.argv[1]) as handle:
        doc = json.load(handle)
except (OSError, ValueError) as exc:
    # THE SAME RULE ONE LAYER IN. `json.load` on a truncated or unreadable file raises, and a
    # traceback tells a reader about our parser rather than about their install.
    sys.exit(f"the preflight document at {sys.argv[1]} could not be read: {exc}")

assert doc["schema"].startswith("openfactory.preflight/"), doc.get("schema")
assert doc["findings"], "preflight named nothing at all"
for finding in doc["findings"]:
    if finding["answered"] and not finding["ok"]:
        assert finding["remedy"].strip(), f"{finding['check']} refuses with no remedy"
print(f"preflight: {doc['verdict']} over {len(doc['findings'])} checks")
PY
