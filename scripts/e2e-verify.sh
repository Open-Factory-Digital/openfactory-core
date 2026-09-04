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

# IT NEVER READS `.env.compose` AT ALL, WHICH IS BETTER THAN BEING ALLOWED TO.
#
# Two releases were spent on this one line. v0.1.5: the step ran `docker compose --env-file …` as
# the runner's user, and the file is 0600 because `openfactory init` is right to write it that way,
# so it could not be read. v0.1.6: the step borrowed the owner's uid with `sudo -n -u #1000`, and
# THAT process could not reach the docker socket.
#
# MEASURED 2026-09-04, because the two candidate causes have different fixes and the transcript
# cannot tell them apart:
#
#   sudo -n -u "#<uid that exists>"  ->  groups preserved, docker group included
#   sudo -n -u "#4242"               ->  sudo: user '#4242' not found
#
# So `sudo -u` does NOT drop supplementary groups. The uid is the problem: the file is owned by uid
# 1000 as created INSIDE the container, and on a GitHub runner uid 1000 is `ubuntu` while the
# runner is `runner` at 1001 — a different account, never in the docker group. Borrowing a uid
# across a container boundary borrows a number, not an identity.
#
# `docker compose exec` NEEDS THE PROJECT, NOT THE CREDENTIALS. `--project-directory` finds
# `docker-compose.yml`, whose `name: openfactory` fixes the project, and that is enough to locate a
# running service. Measured against a live stack: `docker compose --project-directory … exec -T
# worker true` exits 0 with no `--env-file` anywhere. Unset variables fall back to their `:-`
# defaults, which `exec` never looks at.
#
# So there is no identity to borrow and no credential to read — and the 0600 the product was right
# to write stays exactly as it is. A guard refuses any `chmod` that would loosen it.
# PREFLIGHT EXITS NON-ZERO HERE AND THAT IS CORRECT: a CI machine has no agent credential, so the
# honest report is a red line with a remedy. What is asserted is that it produced a document at
# all, in the shape the agent lane reads — and that every refusal in it carries a remedy, which is
# the house rule this project holds every Finding to.
docker compose --project-directory "$INSTALL" \
    exec -T worker openfactory preflight --json > "${SHARED}/preflight.json" 2> "${SHARED}/preflight.err" || true

# A TRACEBACK IS NOT A DIAGNOSIS, and this script broke that rule about a file it could not read.
# The parser below is only reached once there is something to parse; before that, whatever went
# wrong is quoted in one sentence naming the command and the reason.
if [ ! -s "${SHARED}/preflight.json" ]; then
    # WHO WE ARE, WHEN IT FAILS. The v0.1.6 and v0.1.7 runs both died here on `permission denied …
    # docker.sock`, and the first was diagnosed as a borrowed-uid problem — a diagnosis this step no
    # longer permits, since it borrows nothing. The same message arriving without any uid borrowing
    # means the earlier conclusion was incomplete, and neither transcript carried the one fact that
    # would settle it: which identity was refused, and by what.
    #
    # Reasoning from a log twice produced a wrong answer, so the log now carries the evidence.
    # Printed only on failure, because a passing run does not need it.
    echo "" >&2
    echo "  who this step is: $(id 2>&1)" >&2
    echo "  the socket:       $(ls -ln /var/run/docker.sock 2>&1)" >&2
    echo "  docker context:   $(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>&1)" >&2
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
