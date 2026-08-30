# The `openfactory` command, and nothing else — the image the INSTALLER runs (ADR-0043).
#
#   docker build -f docker/cli.Dockerfile -t ghcr.io/open-factory-digital/openfactory-cli:main .
#   docker run --rm -it -v "$PWD:/out" -u "$(id -u):$(id -g)" \
#       ghcr.io/open-factory-digital/openfactory-cli:main init --out /out/.env.compose
#
# WHY A THIRD IMAGE EXISTS AT ALL, WHICH IS THE ONLY INTERESTING QUESTION HERE. The installer has
# to run two commands before the stack can start — `openfactory preflight`, which says what is
# still wrong with this machine, and `openfactory init`, which writes `.env.compose` — and until
# 2026-08-30 the only way to run either was to build a virtualenv on the host with a 3.12+
# interpreter. `docs/ONBOARDING.md` §0 spent a full page on the interpreter alone, because stock
# Debian/Ubuntu and Homebrew macOS ship `python3` older than 3.12 and the venv builds happily and
# dies four commands later at `pip install`. Running those two commands in a container deletes
# that page from the FIRST-RUN path and leaves it where it belongs, on the contributor's.
#
# `openfactory-worker` COULD RUN THEM AND MUST NOT BE ASKED TO. That image carries a Node runtime
# and four agent CLIs — it is multi-GB, and it is the single largest download in the install. The
# whole wall-clock trick of the installer is that the worker's pull runs in the BACKGROUND while
# the interview happens in front of the user; an interview that waits for the worker to arrive
# gives that back. This image is the wheel on `python:3.12-slim` and nothing else, so it is there
# in seconds.
#
# NO NODE, NO agent CLI, NO TOOLBOX, and that is the point rather than an economy: nothing this
# image runs writes code. `preflight` reads the machine and `init` writes a text file. A harness
# here would be several hundred megabytes bought for a capability neither command has.

FROM python:3.12-slim

# ── A ROOT CA THIS DEPLOYMENT'S NETWORK REQUIRES — empty in this repository ──────────────────
# The same no-op block the other images carry, and it earns its place here for one instruction:
# the `pip install` below. An organisation that terminates outbound HTTPS (Zscaler, Netskope, a
# corporate proxy) presents a certificate signed by a root no public image ships, and pip fails
# with `SSLError(CERTIFICATE_VERIFY_FAILED)` — which reads as a broken package rather than a
# broken trust store.
#
# NO `apt` AND THEREFORE NO `DEBIAN_MIRROR` ARG, unlike `base-python` and `worker`. This image
# installs nothing from Debian's archive, so the throttled-port-80 failure those two carry a
# mirror argument for cannot happen here; an ARG for it would be a setting that looks configured
# and changes nothing.
#
# `/etc/pip.conf` rather than `PIP_CERT`: a file can be written before the tool that reads it
# runs, and a file that was never written is a stronger no-op than an environment variable always
# set to something. It IS pip's global config on Linux, wherever pip came from.
COPY docker/extra-ca/ /tmp/extra-ca/
RUN set -eu; \
    mkdir -p /usr/local/share/openfactory; \
    : > /usr/local/share/openfactory/extra-ca.crt; \
    for crt in /tmp/extra-ca/*.crt; do \
      [ -e "$crt" ] || continue; \
      cat "$crt" >> /usr/local/share/openfactory/extra-ca.crt; \
    done; \
    if [ -s /usr/local/share/openfactory/extra-ca.crt ]; then \
      cat /usr/local/share/openfactory/extra-ca.crt >> \
        "$(python -c 'import certifi; print(certifi.where())')"; \
      printf '[global]\ncert = %s\n' \
        "$(python -c 'import certifi; print(certifi.where())')" > /etc/pip.conf; \
    fi; \
    rm -rf /tmp/extra-ca

WORKDIR /opt/openfactory
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY openfactory ./openfactory
# THE SAME INSTALL STEP THE OTHER TWO IMAGES RUN, as the same script — see
# `docker/install-addons.sh` for why it is a script a guard can EXECUTE rather than a shell line a
# guard can only read (a reviewer once replaced its existence test with one that is always true and
# 23 green guards shipped a public build that aborted on its own first command, 2026-08-26).
#
# `COPY addon[s]` IS THE OPTIONAL GLOB AND IS NOT OPTIONAL HERE. `addons/` is a row of
# docs/STATUS.md's excluded-paths table, so the public repository does not have that directory, and
# a bare `COPY addons ./addons` does not degrade there — it ABORTS with `failed to compute cache
# key: "/addons": not found`.
#
# THE CORE ALONE, NOT `.[runtime]`: this image runs `preflight` and `init`, neither of which starts
# a durable workflow, so the runtime extra would pull `temporalio` and its protobuf stack for code
# nothing in this image reaches. An add-on the tree carries is still installed, because a
# deployment that HAS one expects `init` to ask its questions and name its variables.
COPY docker/install-addons.sh ./docker/install-addons.sh
COPY addon[s] ./addons
RUN sh docker/install-addons.sh '.'

# WHICH CODE IS ACTUALLY RUNNING IN THIS IMAGE — the question nobody could answer (2026-08-14), and
# it matters more here than anywhere: this is the image that tells a stranger what is wrong with
# their machine, so "which build said that" has to have an answer. Computed AFTER the COPY above,
# so Docker's layer cache refreshes it exactly when the code changes and keeps it when nothing did.
RUN python -c "\
import hashlib, json, pathlib, datetime;\
h = hashlib.sha256();\
[h.update(p.read_bytes()) for p in sorted(pathlib.Path('openfactory').rglob('*.py'))];\
pathlib.Path('/etc/openfactory').mkdir(parents=True, exist_ok=True);\
pathlib.Path('/etc/openfactory/build.json').write_text(json.dumps({\
  'code_sha256': h.hexdigest()[:12],\
  'built_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),\
}))"

# WORKDIR `/out`, AND IT IS THE WHOLE CONTRACT WITH `install.sh`. The installer mounts the target
# directory there and runs as the invoking uid/gid (`-u "$(id -u):$(id -g)"`), so the 0600
# `.env.compose` this writes belongs to the person who ran the installer and not to root. A file
# the user cannot edit without `sudo` would put back, at the last step, exactly the thing P0.4
# removed from the first.
WORKDIR /out

# ENTRYPOINT AND NOT CMD, so `docker run … openfactory-cli preflight` reads as the command it is.
# With CMD the user would have to type the console script's name inside the image as well, which
# is the kind of detail that ends up wrong in one of the four places the README prints it.
ENTRYPOINT ["openfactory"]
CMD ["--help"]
