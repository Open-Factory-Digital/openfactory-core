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
#
#   --                everything after this is passed to `openfactory init`, for an
#                     unattended install:  … | sh -s -- --dir ./of -- --forge github \
#                     --tracker github --github-auth token --harness claude_code \
#                     --claude-auth subscription --channel panel --panel-local

set -eu

ORG="Open-Factory-Digital"
REPO="openfactory-core"
REGISTRY="ghcr.io/open-factory-digital"
RELEASES="https://github.com/${ORG}/${REPO}/releases"

DIR="./openfactory"
VERSION=""
#: Where this machine's Docker daemon actually listens, and which group may talk to it. Both are
#: RESOLVED (`resolve_the_docker_socket`) rather than assumed — see that function for what each
#: assumption cost.
DOCKER_SOCKET=""
DOCKER_SOCKET_GID=""
DOCKER_ENDPOINT=""
#: Where a job's files live while it runs. THIS machine's answer, handed to the container.
WORK_DIR=""
#: Everything after `--`, handed to `openfactory init`. Empty means "ask me".
INIT_ARGS=""
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

# ── how this machine talks to Docker, asked rather than assumed ─────────────────────────────────
#
# `/var/run/docker.sock` WAS HARDCODED, AND IT IS WRONG ON TWO COMMON SETUPS: rootless Docker puts
# the socket at `$XDG_RUNTIME_DIR/docker.sock`, and Docker Desktop on macOS at
# `~/.docker/run/docker.sock`. Both are ordinary on exactly the laptops this one-liner is aimed at.
#
# AND THE FAILURE IS THE QUIET KIND. Docker does not refuse a bind source that is missing — it
# CREATES IT, as a directory. The container then receives a directory where a socket should be, and
# the error surfaces from inside `openfactory preflight` as "the daemon did not answer" rather than
# from the mount that caused it. That is the same defect class `openfactory/adapters/sandbox/
# container.py` records at length — *"Docker mounts an empty directory rather than failing … the
# box saw 0 entries"* — arriving by a new road.
#
# THE GROUP IS THE SECOND HALF, and it is the one a reviewer caught (2026-08-31). `-u uid:gid` sets
# exactly one gid and DROPS supplementary groups, while a stock Linux socket is `srw-rw---- root
# docker` and every ordinary user reaches it through the supplementary `docker` group. Measured
# here by running it rather than reasoning about it:
#
#   docker run -u 1000:1000                    …  groups=1000        SOCKET: DENIED
#   docker run -u 1000:1000 --group-add 1001   …  groups=1000,1001   readable+writable
#
# Without it `preflight` reports "the Docker daemon did not answer" one line after this script has
# just proved on the host that it does — two diagnostics disagreeing on the first screen of a first
# install, which is the disease `openfactory/onboarding/readiness.py` exists to cure.
# WHERE A JOB'S FILES WILL LIVE, RESOLVED ON THE HOST — because only the host can answer it.
#
# `openfactory init` RUNS IN A CONTAINER, and a container's `$HOME` describes nothing about this
# machine. Worse, `-u "$(id -u):$(id -g)"` gives a uid with no `/etc/passwd` entry, and Docker
# answers that with `HOME=/` — so `init` computed `/.local/share/openfactory/work` and died on
# `Permission denied` for a directory nobody asked for. Measured against the published
# openfactory-cli:v0.1.3 (2026-09-02); it happened on every Linux install, and P0.4 existed
# precisely to stop handing people a root-owned path.
#
# The value is passed in as `OPENFACTORY_WORK_DIR`, which is the same variable `preflight`,
# `docker-compose.yml` and the generated `.env.compose` already read — so there is one name for
# this, and the host is the one machine that gets to fill it in.
resolve_the_work_directory() {
    # NO EARLY RETURN, AND THAT IS THE FIX FOR A DEFECT FOUND BY RUNNING THIS (2026-09-04). A
    # declared OPENFACTORY_WORK_DIR used to `return 0` here — skipping the `mkdir` at the bottom —
    # so the ONE case where the caller knows exactly where the workspace goes was the one case
    # nothing created it. Docker then made it when the cli container mounted it, as ROOT, which is
    # the exact failure the comment on that mkdir warns about:
    #
    #   drwxr-xr-x 2 0 0 …/shared/work
    #   FAIL work_dir  … cannot be created or written here: Permission denied
    #
    # Measured against the published v0.1.4 with the end-to-end scripts, which is also how the CI
    # job would have hit it — it passes the variable, so it took this path every time.
    if [ -n "${OPENFACTORY_WORK_DIR:-}" ]; then
        WORK_DIR="$OPENFACTORY_WORK_DIR"
    else
    # `data_home`, NOT `base`. `fetch_assets` already owns `base` for the release download URL, and
    # one name meaning two things in one script is how the next reader mis-edits it — the guard on
    # the asset base spotted the collision immediately (2026-09-03).
    data_home="${XDG_DATA_HOME:-}"
    if [ -z "$data_home" ]; then
        if [ -z "${HOME:-}" ] || [ "${HOME:-}" = "/" ]; then
            die "cannot choose where a job's files will live: \$HOME is \"${HOME:-}\", which is not a directory you can write under." \
                "Set OPENFACTORY_WORK_DIR to an absolute path you own and run this again — e.g. OPENFACTORY_WORK_DIR=/srv/openfactory/work"
        fi
        data_home="${HOME}/.local/share"
    fi
    WORK_DIR="${data_home}/openfactory/work"
    fi

    # CREATED HERE, ON THE HOST, BY THE PERSON WHO OWNS IT. `openfactory init` used to make it —
    # but `init` runs in a container, where `/home/<you>` does not exist and uid 1000 may not
    # create it, so the mkdir failed against the container's filesystem while describing a path on
    # yours. The host is the only machine that can make a host directory.
    mkdir -p "$WORK_DIR" \
        || die "could not create the job workspace \`${WORK_DIR}\`." \
               "Set OPENFACTORY_WORK_DIR to an absolute path you own and run this again."
}

resolve_the_docker_socket() {
    # THE DAEMON'S OWN ANSWER, and the script has already earned the right to ask: `the_daemon_
    # answers` ran two lines ago. A `unix://` endpoint is a path to bind-mount; anything else —
    # `tcp://`, `ssh://` — is a daemon somewhere else, which must NOT be bind-mounted and is
    # forwarded as DOCKER_HOST instead.
    endpoint=$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)
    [ -n "$endpoint" ] || endpoint="unix:///var/run/docker.sock"
    DOCKER_ENDPOINT="$endpoint"

    case "$endpoint" in
        unix://*) DOCKER_SOCKET="${endpoint#unix://}" ;;
        *) DOCKER_SOCKET=""; return 0 ;;
    esac

    [ -S "$DOCKER_SOCKET" ] \
        || die "Docker says its socket is at \`${DOCKER_SOCKET}\`, and there is no socket there." \
               "Check \`docker context inspect\`. Mounting that path anyway would make Docker create a DIRECTORY there, and the failure would surface later as \`the daemon did not answer\`."

    # GNU FIRST, THEN BSD, because the two spell it differently and mean different things by the
    # other spelling: on GNU coreutils `stat -f` asks about the FILESYSTEM and fails here, so the
    # order matters rather than being a preference. An unreadable gid is left empty and no
    # `--group-add` is passed — a wrong group is worse than none.
    DOCKER_SOCKET_GID=$(stat -c '%g' "$DOCKER_SOCKET" 2>/dev/null \
        || stat -f '%g' "$DOCKER_SOCKET" 2>/dev/null || true)
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
            # EVERYTHING AFTER `--` BELONGS TO `openfactory init`, which is how an unattended
            # install answers the questions. Without it the interview refuses — correctly, by the
            # house rule against blocking on a prompt nobody can answer — and there is no way to
            # supply the answers, so the one-liner could only ever complete at a terminal. That is
            # what the first `verify_the_install` run reported:
            #     ✗ --forge is required when this does not run in a terminal
            --) shift; INIT_ARGS="$*"; break ;;
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
    # THE OTHER PLACE `set -e` COULD END THIS SCRIPT MID-SENTENCE, found by auditing every command
    # for the missing `|| die` that made the `init` failure unreadable. An unwritable parent is an
    # ordinary mistake — a typo'd `--dir`, a path under someone else's home — and it deserves the
    # same one sentence with a cause and a remedy as everything else here.
    run mkdir -p "$DIR" \
        || die "could not create \`$DIR\`." \
               "Pass --dir <path> pointing somewhere you can write, and run this again."
    # `.env.compose` IS THE ONE FILE THAT MUST NEVER REACH A COMMIT. The target directory is very
    # often inside somebody's own repository, and this costs one line.
    #
    # IT USED TO DO NOTHING IN EXACTLY THE CASE THE SENTENCE ABOVE NAMES (review, 2026-08-31). The
    # test was `[ ! -f "$DIR/.gitignore" ]` — write the file only when there is not one — and a
    # directory inside somebody's repository is PRECISELY the directory that already has a
    # `.gitignore`. So the protection was present, read correctly, and absent on the only path it
    # was argued for, while the file it protects holds a forge token with write access to their
    # repositories and a harness token that bills them.
    #
    # APPENDING IS THE WHOLE FIX, and the trailing newline is the trap in it: a `.gitignore` whose
    # last line has no newline would otherwise gain `somethingelse.env.compose` — a pattern that
    # matches nothing and hides the failure. So a newline is written first when the file does not
    # end in one.
    if [ "$DRY_RUN" -eq 0 ] && ! grep -qxF '.env.compose' "$DIR/.gitignore" 2>/dev/null; then
        if [ -s "$DIR/.gitignore" ] && [ -n "$(tail -c 1 "$DIR/.gitignore")" ]; then
            printf '\n' >> "$DIR/.gitignore"
        fi
        printf '.env.compose\n' >> "$DIR/.gitignore"
    fi
}

# ── the assets, verified ────────────────────────────────────────────────────────────────────────

# THE ASSETS THIS SCRIPT DOWNLOADS, spelled exactly as the release attaches them.
#
# `env.compose.example` HAS NO LEADING DOT AND THAT IS LOAD-BEARING. GitHub does not permit a
# release asset name to begin with one — it silently renames it, replacing the `.` with `default.`.
# Measured against the real v0.1.1 release (2026-08-31): `.env.compose.example` 404,
# `default.env.compose.example` 200. This loop asked for the dotted name, died on the second file
# it fetches, and every v0.1.1 install stopped there — before the CLI image was even pulled.
#
# The file is saved back under its dotted name below, because that is what `docker-compose.yml`'s
# header and the README both tell a person to copy.
ASSETS="docker-compose.yml env.compose.example SHA256SUMS"

fetch_assets() {
    base="${RELEASES}/download/${VERSION}"
    for asset in ${ASSETS}; do
        run curl -fsSL "${base}/${asset}" -o "${DIR}/${asset}" \
            || die "could not download \`${asset}\` from release ${VERSION}." \
                   "Check that ${RELEASES}/tag/${VERSION} exists, or pass --version <tag>."
    done
    [ "$DRY_RUN" -eq 1 ] && return 0

    verify_the_downloads
    # THE NAME A PERSON IS TOLD TO COPY. It travels without its dot and lands with one.
    mv "${DIR}/env.compose.example" "${DIR}/.env.compose.example"
}

verify_the_downloads() {
    # EVERY FILE THIS SCRIPT DOWNLOADED IS NAMED IN SHA256SUMS, CHECKED BEFORE THE CHECKING.
    #
    # `sha256sum -c --ignore-missing` SUCCEEDS WHEN IT MATCHES NOTHING AT ALL, which is the failure
    # mode that hid here: the template was fetched and never verified, because `sha256sum ./*` on
    # the release side does not match dotfiles and it was called `.env.compose.example` there
    # (measured 2026-08-31 against v0.1.1 — SHA256SUMS was 162 bytes and held two entries, for
    # `docker-compose.yml` and `install.sh`). The flag's comment said the opposite of the truth:
    # it read "SHA256SUMS covers assets this script does not download", while the script was
    # downloading an asset SHA256SUMS did not cover.
    #
    # BOTH HALVES ARE TRUE NOW AND BOTH ARE ASSERTED. `--ignore-missing` is still needed, because
    # the release also attaches `install.sh` (and `install.md`) which this script does not fetch —
    # that is the reason the old comment gave, and it is a real one. What it could not do is notice
    # the reverse, so the loop below does: an asset with no entry is refused by name rather than
    # skipped in silence.
    for asset in ${ASSETS}; do
        [ "$asset" = SHA256SUMS ] && continue
        grep -q "[ *]${asset}\$" "${DIR}/SHA256SUMS" \
            || die "the release's SHA256SUMS does not cover \`${asset}\`, so it cannot be verified." \
                   "This is a defect in release ${VERSION} rather than on your machine — please report it, and do not use these files meanwhile."
    done

    # VERIFIED AGAINST THE RELEASE'S OWN SUMS, and this is why the assets come from the release
    # rather than from openfactory.digital: a static host serves a file and can checksum nothing.
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
    # `&&`, NOT TWO STATEMENTS. A subshell reports the status of its LAST command, so with these
    # on separate lines a failed WORKER pull exited 0 and `wait "$PULL_PID"` below saw success —
    # the multi-gigabyte image, silently absent, discovered at `docker compose up -d`. Measured
    # 2026-09-04: `( false; true ) & wait $!` exits 0.
    (
        docker pull --quiet "${REGISTRY}/openfactory-worker:${VERSION}" >/dev/null 2>&1 \
            && docker pull --quiet "${REGISTRY}/openfactory-sandbox:${VERSION}" >/dev/null 2>&1
    ) &
    PULL_PID=$!
}

# THE CHECK THAT MAKES THE PULL A GUARANTEE RATHER THAN AN ATTEMPT.
#
# P0.3 EXISTS FOR EXACTLY THIS FAILURE: the worker `docker run`s the box image against the HOST's
# daemon, `docker compose up -d` neither builds nor fetches it, and nothing else will. Absent, the
# install looks perfect and the FIRST TICKET dies on `image not found` — hours later, one layer
# from its cause. `preflight` names it, but preflight runs while the pull is still in flight, so
# its answer is about a moment that has passed by the time this finishes.
#
# Measured on the v0.1.5 end-to-end run: `FAIL box_image … is not on this daemon` at preflight, and
# the install then declared success. The image had in fact arrived; nothing checked, and a person
# reading that transcript could not tell the difference between "arrived" and "still missing".
confirm_the_box_image() {
    [ "$DRY_RUN" -eq 1 ] && return 0
    image="${REGISTRY}/openfactory-sandbox:${VERSION}"
    docker image inspect "$image" >/dev/null 2>&1 \
        || die "the box image \`${image}\` is not on this machine, and nothing else fetches it." \
               "Run \`docker pull ${image}\` and then \`cd ${DIR} && docker compose --env-file .env.compose up -d\`. Without it the stack starts and the first ticket fails on a missing image."
}

wait_for_images() {
    [ "$DRY_RUN" -eq 1 ] && return 0
    [ -n "${PULL_PID:-}" ] || return 0
    step "Waiting for the factory image to finish downloading"
    wait "$PULL_PID" || die "the worker or box image failed to download." \
        "Run \`docker pull ${REGISTRY}/openfactory-worker:${VERSION}\` by hand to see why."
}

# ── the package speaks for itself from here on ──────────────────────────────────────────────────

# EVERY ARGUMENT A CALLER PASSES IS THE COMMAND'S, AND NONE OF THEM CAN BECOME A DOCKER FLAG.
# That sentence is the fix for the defect this shipped with (found in review, 2026-08-31, and
# reproduced here): the call site read `in_the_cli -t init --out /out/.env.compose`, `"$@"` was
# placed AFTER the image name, and `docker/cli.Dockerfile` sets `ENTRYPOINT ["openfactory"]` — so
# `-t` was never seen by `docker run` at all. It was the first argument to `openfactory`:
#
#     $ openfactory -t init --out …
#     Error: No such option: -t
#     $ echo $?
#     2
#
# `run_init` had no `|| die`, so `set -e` took the script out at that line: assets downloaded, the
# cli image pulled, the worker pull still running in the background, no `.env.compose`, a Typer
# usage box, and a re-run that now needs `--force` — through a message nobody was ever shown.
#
# THE SHAPE OF THE BUG IS THE ARGUMENT ORDER, so the shape of the fix is too. `docker run` takes
# `<flags> <image> <command>`, and the only reliable way to keep those three apart in POSIX sh is
# to build them in that order. The command goes in first and everything else is PREPENDED, so a
# caller physically cannot reach the flag position. Asking for a terminal is a named function
# rather than a flag smuggled through `"$@"`, which is what went wrong.
_cli() {
    want_tty=$1
    shift
    #  …<command>
    set -- "${REGISTRY}/openfactory-cli:${VERSION}" "$@"
    #  <image> <command>
    set -- -e "OPENFACTORY_VERSION=${VERSION}" "$@"
    set -- -e "OPENFACTORY_WORK_DIR=${WORK_DIR}" "$@"
    # BOUND AT THE SAME PATH ON BOTH SIDES, for the reason `docker-compose.yml` binds it that way:
    # a path this container invents means nothing to the machine that has to honour it. Without the
    # mount, `preflight` checked whether `/home/<you>/.local/share/openfactory/work` was writable
    # INSIDE THE CONTAINER — where `/home` is root-owned and the answer is always no — and reported
    # `Permission denied` about a directory that is fine on the host (measured 2026-09-02).
    set -- -v "${WORK_DIR}:${WORK_DIR}" "$@"
    # THE SOCKET, WHERE THIS MACHINE ACTUALLY KEEPS IT, and the group that may talk to it. A daemon
    # that is not on a unix socket is reached by DOCKER_HOST instead — bind-mounting a `tcp://`
    # endpoint is not a thing, and Docker would helpfully create a directory named after it.
    if [ -n "$DOCKER_SOCKET" ]; then
        if [ -n "$DOCKER_SOCKET_GID" ]; then
            set -- --group-add "$DOCKER_SOCKET_GID" "$@"
        fi
        set -- -v "${DOCKER_SOCKET}:/var/run/docker.sock" "$@"
    else
        set -- -e "DOCKER_HOST=${DOCKER_ENDPOINT}" "$@"
    fi
    # `-u` SO WHAT IT WRITES IS YOURS. `openfactory init` writes `.env.compose` at 0600; created by
    # root inside a container it would be a file the person cannot edit without `sudo`, which would
    # put back at the last step exactly the thing this install removed from the first.
    set -- -u "$(id -u):$(id -g)" "$@"
    set -- -v "$(cd "$DIR" && pwd):/out" "$@"
    set -- --rm -i "$@"
    #  <flags> <image> <command>

    # A TTY ONLY WHERE THERE IS ONE TO GIVE. `docker run -t` against a pipe fails with `the input
    # device is not a TTY`, and the headline command IS a pipe — `curl … | sh` leaves this script's
    # stdin attached to curl. `/dev/tty` is the terminal itself, still there behind the pipe, which
    # is what lets the interview ask its questions from a piped installer at all. Where there is
    # genuinely no terminal (CI, a scripted install), no `-t` is passed and `openfactory init`
    # refuses by name asking for the flags instead of hanging on a question nobody can answer.
    # THE TEST IS AN OPEN, NOT AN `-r`. `[ -r /dev/tty ]` answers TRUE on a machine with no
    # controlling terminal — the device node exists and its permissions are fine — and the redirect
    # then dies with `cannot open /dev/tty: No such device or address`. Measured 2026-08-31 in a
    # detached shell, where the first version of this line did exactly that. Opening it is the only
    # question worth asking, so that is the question.
    # THE OPEN HAPPENS IN A SUBSHELL, AND THAT IS NOT STYLE. POSIX says a redirection error on a
    # SPECIAL built-in shall exit the shell, and `:` is a special built-in — so `{ : < /dev/tty; }`
    # does not evaluate to false where there is no terminal, it terminates the installer. Measured
    # 2026-08-31 under dash (Debian's /bin/sh): the script died at this line with exit 2, no
    # message, immediately after printing "Writing this deployment's environment". A subshell
    # confines the failure to itself and lets the test be a test.
    if [ "$want_tty" = tty ] && (exec < /dev/tty) 2>/dev/null; then
        docker run -t "$@" < /dev/tty
    else
        docker run "$@"
    fi
}

in_the_cli() { _cli no-tty "$@"; }

in_the_cli_asking_questions() { _cli tty "$@"; }

run_preflight() {
    step "Checking this machine"
    if [ "$DRY_RUN" -eq 1 ]; then say "  would run: openfactory preflight"; return 0; fi
    # NON-ZERO IS NOT FATAL HERE, deliberately. Most of what preflight names at this point is
    # supposed to be missing — there is no `.env.compose` yet and no credential — so refusing on it
    # would refuse every first install. The findings are PRINTED, with their remedies, and the same
    # command is offered at the end for after the answers are in.
    in_the_cli preflight || true
    # WHY `box_image` MAY BE RED HERE AND IS NOT WORK FOR YOU. This runs WHILE the worker and box
    # images are still downloading — that overlap is the single largest wall-clock win in the
    # install — so preflight is telling the truth about this moment and the moment is about to
    # change. `confirm_the_box_image` re-asks once the pull has finished, and THAT one is a
    # refusal. Said out loud because a FAIL nobody explains is a FAIL somebody acts on.
    say ""
    say "  (the box image is still downloading — it is checked again before this finishes)"
}

run_init() {
    step "Writing this deployment's environment"
    if [ "$DRY_RUN" -eq 1 ]; then say "  would run: openfactory init --out /out/.env.compose"; return 0; fi
    # `|| die` ON BOTH, and its absence is half of why the defect above was so expensive. Without
    # it `set -e` ends the script at this line with no sentence at all — and this is the step most
    # likely to fail for an ordinary reason (a question nobody can answer without a terminal, a
    # directory that turned out not to be writable). The remedy names `--force`, because by the
    # time anybody re-runs, the target directory exists and the plain command will refuse.
    # THE REMEDY USED TO BE WRONG, AND WRONG IN THE DIRECTION THAT COSTS TIME. It said to re-run
    # with `--force` "because the target directory exists now" — but `prepare_directory` refuses
    # only when `.env.compose` EXISTS, and a failed `init` is precisely the case where it does not.
    # So it sent people to add a flag they did not need, to work around a refusal that would not
    # have happened. A plain re-run is the right advice.
    #
    # `$INIT_ARGS` IS DELIBERATELY UNQUOTED: it is a list of separate flags, not one argument.
    # shellcheck disable=SC2086
    if [ -f "$DIR/.env.compose" ] && [ "$FORCE" -eq 1 ]; then
        in_the_cli_asking_questions init --out /out/.env.compose --force $INIT_ARGS \
            || die "\`openfactory init\` did not finish, so ${DIR}/.env.compose was not written." \
                   "Fix what it reported above and run this installer again with --force."
    else
        # shellcheck disable=SC2086
        in_the_cli_asking_questions init --out /out/.env.compose $INIT_ARGS \
            || die "\`openfactory init\` did not finish, so ${DIR}/.env.compose was not written." \
                   "Fix what it reported above and run this installer again — nothing was left behind that needs --force."
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
    # NOT A THIRD FACT ABOUT THE MACHINE — it is how to reach the daemon the two facts above just
    # established, which the script is already permitted to know. It asks Docker rather than
    # checking anything, and it names no prerequisite: `preflight` still owns every question that
    # has a remedy.
    resolve_the_docker_socket
    resolve_the_work_directory

    if [ "$UNINSTALL" -eq 1 ]; then uninstall; return 0; fi

    resolve_version
    step "Installing OpenFactory ${VERSION} into ${DIR}"
    prepare_directory
    fetch_assets
    pull_images
    run_preflight
    run_init
    wait_for_images
    confirm_the_box_image

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
