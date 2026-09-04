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

# PREFLIGHT EXITS NON-ZERO HERE AND THAT IS CORRECT: a CI machine has no agent credential, so the
# honest report is a red line with a remedy. What is asserted is that it produced a document at
# all, in the shape the agent lane reads — and that every refusal in it carries a remedy, which is
# the house rule this project holds every Finding to.
docker compose --env-file "$ENV_FILE" --project-directory "$INSTALL" \
    exec -T worker openfactory preflight --json > "${SHARED}/preflight.json" || true

python3 - "${SHARED}/preflight.json" <<'PY'
import json
import sys

with open(sys.argv[1]) as handle:
    doc = json.load(handle)

assert doc["schema"].startswith("openfactory.preflight/"), doc.get("schema")
assert doc["findings"], "preflight named nothing at all"
for finding in doc["findings"]:
    if finding["answered"] and not finding["ok"]:
        assert finding["remedy"].strip(), f"{finding['check']} refuses with no remedy"
print(f"preflight: {doc['verdict']} over {len(doc['findings'])} checks")
PY
