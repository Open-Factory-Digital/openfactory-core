#!/bin/sh
# OpenFactory — the one-line install.
#
#     curl -fsSL https://openfactory.digital/install.sh | sh
#
# WHAT THIS SCRIPT IS ALLOWED TO KNOW, AND IT IS EXACTLY TWO THINGS: that `docker` is on PATH, and
# that the daemon answers. Everything else about your machine — the compose version, the ports, the
# disk, the work directory, the box image, the credentials — belongs to `openfactory preflight`,
# which runs in a container a few lines below and reports it all with a remedy each.
#
# That split is the whole design and it is not tidiness. There is one honest exception to "the
# package knows about the machine": the shell cannot ask the package anything before Docker works.
# So the shell knows those two facts and no more, and a guard
# (`tests/test_the_installer_knows_exactly_two_facts_the_package_does_not.py`) holds that list at
# two — because a list of exceptions that can grow is a second diagnostic tool, and this project
# already paid for having three disagreeing ones.
#
# THIS SCRIPT SENDS NOTHING ANYWHERE. There is no telemetry in this project. It talks to exactly
# two hosts: github.com, for the release assets, and ghcr.io, for the images. Nothing is reported
# about your machine to anyone, including us.
#
# IT NEVER NEEDS `sudo`. If it ever asks you for a password, something is wrong — stop and report
# it. Everything it writes goes inside the target directory, which you own.
#
# Options:
#   --dir <path>      where to install                     (default: ./openfactory)
#   --version <tag>   which release to install             (default: the latest one)
#   --force           write into a directory that already has an .env.compose
#   --dry-run         print what would happen; touch nothing
#   --no-run          set everything up, do not start the stack
#   --uninstall       stop the stack and remove its volumes, after asking
#   --help            this text

set -eu

ORG="Open-Factory-Digital"
REPO="openfactory-core"
REGISTRY="ghcr.io/open-factory-digital"
RELEASES="https://github.com/${ORG}/${REPO}/releases"

DIR="./openfactory"
VERSION=""
FORCE=0
DRY_RUN=0
NO_RUN=0
UNINSTALL=0

# ── talking to the person ───────────────────────────────────────────────────────────────────────
# EVERY REFUSAL NAMES THE CAUSE AND THE REMEDY, in one sentence, and exits non-zero. That is this
# project's house rule and it applies hardest here: this is the first thing a stranger runs, and a
# bare `set -e` abort tells them a line number and nothing they can act on.

say() { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }

die() {
    printf '\nopenfactory install: %s\n' "$1" >&2
    if [ $# -gt 1 ]; then printf '  → %s\n' "$2" >&2; fi
    exit 1
}

run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '  would run: %s\n' "$*"
        return 0
    fi
    "$@"
}

# ── the two facts, and there are exactly two ────────────────────────────────────────────────────
# openfactory:facts:begin
docker_is_on_path() {
    command -v docker >/dev/null 2>&1 \
        || die "\`docker\` is not on your PATH, and it is the only thing this needs." \
               "Install Docker — https://docs.docker.com/get-started/get-docker/ — then run this again."
}

the_daemon_answers() {
    docker version --format '{{.Server.Version}}' >/dev/null 2>&1 \
        || die "Docker is installed but its daemon is not answering." \
               "Start Docker Desktop, or \`sudo systemctl start docker\`, then run this again."
}
# openfactory:facts:end
#
# NOTHING ELSE GOES BETWEEN THOSE TWO MARKERS. The next check you are tempted to add here almost
# certainly belongs in `openfactory preflight`, where it is a Finding with a remedy, is covered by
# the suite, and is readable by the agent lane. The markers are what the guard counts.

# THE HEADER IS THE HELP, and the range is derived rather than typed. `sed -n '2,30p'` was the
# first version and it stopped four lines short of the options — the part a person actually came
# for — because the header grew after the number was written. This prints from line 2 until the
# first line that is not a comment, so the two cannot drift.
usage() {
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
}

parse_arguments() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --dir) [ $# -ge 2 ] || die "--dir needs a path." "e.g. --dir ~/openfactory"; DIR="$2"; shift 2 ;;
            --version) [ $# -ge 2 ] || die "--version needs a release tag." "e.g. --version v0.1.0"; VERSION="$2"; shift 2 ;;
            --force) FORCE=1; shift ;;
            --dry-run) DRY_RUN=1; shift ;;
            --no-run) NO_RUN=1; shift ;;
            --uninstall) UNINSTALL=1; shift ;;
            -h|--help) usage; exit 0 ;;
            *) die "unknown option \`$1\`." "Run with --help to see the options this accepts." ;;
        esac
    done
}

# ── which release ───────────────────────────────────────────────────────────────────────────────

resolve_version() {
    if [ -n "$VERSION" ]; then return 0; fi
    # NO HARD-CODED DEFAULT TAG, and no floating one either. A tag written into this file would
    # have to be bumped by hand on every release — the second home for a version number, and the
    # one nobody remembers. `releases/latest` REDIRECTS to the newest release's page, so following
    # the redirect and reading the effective URL resolves a CONCRETE tag here, once, and every step
    # below uses that. What lands in `.env.compose` is `vX.Y.Z`, never `latest` and never `main`:
    # a floating tag is an upgrade nobody chose, arriving between two `up -d`s.
    resolved=$(curl -fsSLI -o /dev/null -w '%{url_effective}' "${RELEASES}/latest" 2>/dev/null) \
        || die "could not reach github.com to find the latest release." \
               "Check your network, or pass --version <tag> to install a specific one."
    VERSION="${resolved##*/tag/}"
    case "$VERSION" in
        v*) : ;;
        *) die "github.com did not answer with a release tag (got \`${resolved}\`)." \
               "Pass --version <tag> to install a specific release instead." ;;
    esac
}

# ── the target directory ────────────────────────────────────────────────────────────────────────

prepare_directory() {
    if [ -e "$DIR" ] && [ ! -d "$DIR" ]; then
        die "\`$DIR\` exists and is not a directory." "Pass --dir <path> to install somewhere else."
    fi
    # THE `init` RULE, FOR THE SAME REASON. That file holds credentials somebody pasted by hand —
    # a forge token with write access to their repositories, a harness token that bills them — and
    # overwriting it silently is how an install becomes an incident.
    if [ -f "$DIR/.env.compose" ] && [ "$FORCE" -eq 0 ]; then
        die "\`$DIR/.env.compose\` already exists, and it holds credentials." \
            "Re-run with --force to overwrite it, or --dir <path> to install beside it. To UPGRADE an existing install, run this from that directory with --force: it keeps your answers."
    fi
    run mkdir -p "$DIR"
    # `.env.compose` IS THE ONE FILE THAT MUST NEVER REACH A COMMIT. The target directory is very
    # often inside somebody's own repository, and this costs one line.
    if [ "$DRY_RUN" -eq 0 ] && [ ! -f "$DIR/.gitignore" ]; then
        printf '.env.compose\n' > "$DIR/.gitignore"
    fi
}

# ── the assets, verified ────────────────────────────────────────────────────────────────────────

fetch_assets() {
    base="${RELEASES}/download/${VERSION}"
    for asset in docker-compose.yml .env.compose.example SHA256SUMS; do
        run curl -fsSL "${base}/${asset}" -o "${DIR}/${asset}" \
            || die "could not download \`${asset}\` from release ${VERSION}." \
                   "Check that ${RELEASES}/tag/${VERSION} exists, or pass --version <tag>."
    done
    [ "$DRY_RUN" -eq 1 ] && return 0
    # VERIFIED AGAINST THE RELEASE'S OWN SUMS, and this is why the assets come from the release
    # rather than from openfactory.digital: a static host serves a file and can checksum nothing.
    # `--ignore-missing` because SHA256SUMS covers assets this script does not download.
    ( cd "$DIR" && sha256sum -c SHA256SUMS --ignore-missing >/dev/null 2>&1 ) \
        || ( cd "$DIR" && shasum -a 256 -c SHA256SUMS --ignore-missing >/dev/null 2>&1 ) \
        || die "the downloaded files do not match the release's SHA256SUMS." \
               "Delete \`$DIR\` and run this again; if it happens twice, please report it."
}

# ── the images ──────────────────────────────────────────────────────────────────────────────────

pull_images() {
    # THE CLI IMAGE FIRST AND ON ITS OWN, because everything a human does next happens in it. It is
    # ~150 MB against the worker's several gigabytes.
    step "Pulling the tools (this is the small one)"
    run docker pull --quiet "${REGISTRY}/openfactory-cli:${VERSION}" \
        || die "could not pull \`${REGISTRY}/openfactory-cli:${VERSION}\`." \
               "Check your network. If ${RELEASES}/tag/${VERSION} exists but the image does not, please report it."

    # AND THE BIG ONES IN THE BACKGROUND, THROUGH THE INTERVIEW. This is the single largest
    # wall-clock win in the whole install and it costs about ten lines: the worker image downloads
    # while the person answers `openfactory init`'s questions, instead of after.
    #
    # THE BOX IMAGE IS PULLED EXPLICITLY, and that is not redundant. `sandbox-image` sits behind
    # compose's `build` profile, so `docker compose up -d` neither builds nor pulls it — and the
    # worker `docker run`s it against the HOST daemon at the first ticket. Without this line the
    # install looks perfect and the first job dies on an image nobody fetched.
    step "Pulling the factory in the background while you answer a few questions"
    if [ "$DRY_RUN" -eq 1 ]; then
        say "  would pull: ${REGISTRY}/openfactory-worker:${VERSION}"
        say "  would pull: ${REGISTRY}/openfactory-sandbox:${VERSION}"
        return 0
    fi
    (
        docker pull --quiet "${REGISTRY}/openfactory-worker:${VERSION}" >/dev/null 2>&1
        docker pull --quiet "${REGISTRY}/openfactory-sandbox:${VERSION}" >/dev/null 2>&1
    ) &
    PULL_PID=$!
}

wait_for_images() {
    [ "$DRY_RUN" -eq 1 ] && return 0
    [ -n "${PULL_PID:-}" ] || return 0
    step "Waiting for the factory image to finish downloading"
    wait "$PULL_PID" || die "the worker or box image failed to download." \
        "Run \`docker pull ${REGISTRY}/openfactory-worker:${VERSION}\` by hand to see why."
}

# ── the package speaks for itself from here on ──────────────────────────────────────────────────

in_the_cli() {
    # `-u` SO WHAT IT WRITES IS YOURS. `openfactory init` writes `.env.compose` at 0600; created by
    # root inside a container it would be a file the person cannot edit without `sudo`, which would
    # put back at the last step exactly the thing this install removed from the first.
    docker run --rm -i \
        -u "$(id -u):$(id -g)" \
        -v "$(cd "$DIR" && pwd):/out" \
        -v /var/run/docker.sock:/var/run/docker.sock \
        -e OPENFACTORY_VERSION="${VERSION}" \
        "${REGISTRY}/openfactory-cli:${VERSION}" "$@"
}

run_preflight() {
    step "Checking this machine"
    if [ "$DRY_RUN" -eq 1 ]; then say "  would run: openfactory preflight"; return 0; fi
    # NON-ZERO IS NOT FATAL HERE, deliberately. Most of what preflight names at this point is
    # supposed to be missing — there is no `.env.compose` yet and no credential — so refusing on it
    # would refuse every first install. The findings are PRINTED, with their remedies, and the same
    # command is offered at the end for after the answers are in.
    in_the_cli preflight || true
}

run_init() {
    step "Writing this deployment's environment"
    if [ "$DRY_RUN" -eq 1 ]; then say "  would run: openfactory init --out /out/.env.compose"; return 0; fi
    if [ -f "$DIR/.env.compose" ] && [ "$FORCE" -eq 1 ]; then
        in_the_cli -t init --out /out/.env.compose --force
    else
        in_the_cli -t init --out /out/.env.compose
    fi
    # THE VERSION IS PINNED INTO THE FILE, and this is the line that keeps every user off a
    # floating tag. `docker-compose.yml` defaults to `main` so a CONTRIBUTOR gets the branch they
    # are working on; an install must never be moved by somebody else's push.
    if ! grep -q '^OPENFACTORY_VERSION=' "$DIR/.env.compose" 2>/dev/null; then
        printf 'OPENFACTORY_VERSION=%s\n' "$VERSION" >> "$DIR/.env.compose"
    fi
}

start_the_stack() {
    step "Starting the factory"
    # THE `cd` IS OUTSIDE `run`, so a dry run must not attempt it. It did, and the dry run ended
    # with `cd: can't cd to /tmp/of-probe` followed by our own "the stack did not start" — a
    # refusal about a directory the dry run had correctly declined to create (measured while
    # writing this, 2026-08-31). A --dry-run that reports a failure it invented is worse than one
    # that reports nothing.
    if [ "$DRY_RUN" -eq 1 ]; then
        say "  would run: (cd $DIR && docker compose --env-file .env.compose up -d)"
        return 0
    fi
    ( cd "$DIR" && docker compose --env-file .env.compose up -d ) \
        || die "the stack did not start." \
               "Run \`cd $DIR && docker compose --env-file .env.compose logs\` to see why."
}

panel_port() {
    port=$(grep '^PANEL_PORT=' "$DIR/.env.compose" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
    [ -n "${port:-}" ] && printf '%s' "$port" || printf '8787'
}

wait_for_the_panel() {
    [ "$DRY_RUN" -eq 1 ] && return 0
    port=$(panel_port)
    step "Waiting for the panel on :${port}"
    waited=0
    while [ "$waited" -lt 180 ]; do
        if curl -fsS "http://localhost:${port}/" >/dev/null 2>&1; then return 0; fi
        sleep 3
        waited=$((waited + 3))
    done
    # NOT A FAILURE, AND NOT A SILENT PASS EITHER. The stack is up; something is slow or wrong, and
    # the person needs the one command that tells them which.
    say ""
    say "The panel has not answered on :${port} after 3 minutes. The stack is running —"
    say "  cd $DIR && docker compose --env-file .env.compose logs panel"
}

finish() {
    port=$(panel_port)
    say ""
    if [ "$DRY_RUN" -eq 1 ]; then
        # A DRY RUN THAT ENDS "OpenFactory v0.1.0 is installed in ./openfactory" IS A LIE, and it
        # is the one sentence a person scrolls to. Caught by running it (2026-08-31).
        say "That is everything --dry-run would do. Nothing was written and nothing was pulled."
        say "Run it again without --dry-run to install into ${DIR}."
        return 0
    fi
    say "OpenFactory ${VERSION} is installed in ${DIR}."
    say ""
    say "  the panel        http://localhost:${port}"
    say "  what is left     cd ${DIR} && docker compose --env-file .env.compose exec worker openfactory preflight"
    say ""
    say "Next, register your first project:"
    say ""
    say "  cd ${DIR} && docker compose --env-file .env.compose exec worker \\"
    say "    openfactory project init myapp https://github.com/<owner>/myapp.git"
    say ""
    say "To upgrade later, run this installer again from ${DIR} with --force."
}

# ── uninstall ───────────────────────────────────────────────────────────────────────────────────

uninstall() {
    [ -f "$DIR/docker-compose.yml" ] \
        || die "there is no OpenFactory install in \`$DIR\`." \
               "Pass --dir <path> to point at the one you mean."
    say "This will stop the stack in ${DIR} and REMOVE its volumes:"
    say ""
    say "  · the project registry and the telemetry database"
    say "  · the harness toolbox"
    say "  · every job's event journal"
    say ""
    say "It will NOT remove ${DIR} itself, your .env.compose, or anything in your own repositories."
    say ""
    # IT ASKS, AND WITH NO TERMINAL IT REFUSES RATHER THAN ASSUMING. An unattended `--uninstall`
    # that deleted a deployment's registry because nobody could answer would be the worst possible
    # reading of silence. Same rule `openfactory init` already follows for its own questions.
    if [ ! -t 0 ]; then
        die "--uninstall needs to ask you to confirm, and there is no terminal here." \
            "Run it from a terminal, or do it by hand: cd $DIR && docker compose --env-file .env.compose down -v"
    fi
    printf 'Type "yes" to continue: '
    read -r answer
    [ "$answer" = "yes" ] || die "nothing was removed." "Run this again and answer \`yes\` if you meant to."
    if [ "$DRY_RUN" -eq 1 ]; then
        say "  would run: (cd $DIR && docker compose --env-file .env.compose down -v)"
        return 0
    fi
    ( cd "$DIR" && docker compose --env-file .env.compose down -v )
    say ""
    say "Stopped, and the volumes are gone. ${DIR} is still there — delete it yourself when you are ready."
}

main() {
    parse_arguments "$@"
    docker_is_on_path
    the_daemon_answers

    if [ "$UNINSTALL" -eq 1 ]; then uninstall; return 0; fi

    resolve_version
    step "Installing OpenFactory ${VERSION} into ${DIR}"
    prepare_directory
    fetch_assets
    pull_images
    run_preflight
    run_init
    wait_for_images

    if [ "$NO_RUN" -eq 1 ]; then
        say ""
        say "Set up in ${DIR}, and not started (--no-run). When you are ready:"
        say "  cd ${DIR} && docker compose --env-file .env.compose up -d"
        return 0
    fi

    start_the_stack
    wait_for_the_panel
    finish
}

main "$@"
