# The Fargate sandbox image (ADR-0001 D-17): the toolchain base + the platform baked
# in, so the task runs a whole job self-contained. Built on top of the per-stack base
# (git + node + make + the `claude` CLI). Command = the in-task entrypoint.
#
#   docker build -f docker/sandbox.Dockerfile -t openfactory-python:sandbox .
# Platform: NOT pinned. `infra/deploy.sh` passes `--platform` explicitly for the cloud
# (arm64 for Fargate, amd64 for the panel), so a hard-coded FROM platform bought that build
# nothing and cost everyone else the ability to build at all — both prospect stacks run x86
# Linux. Left unpinned, Docker builds natively for whatever machine runs it, and an explicit
# --platform still wins. (C-13)
FROM openfactory-python:latest

# The GitHub CLI: in the whole-job-in-task model the tracker/forge run INSIDE the task
# (in the local model they ran on the host), so the task needs `gh`. Auth is the bot
# token via GH_TOKEN, set by the adapters at call time.
RUN mkdir -p -m 755 /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
       -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
       > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Bake the platform so `python -m openfactory.runtime.boxed_job` works. The task needs the
# core plus the two add-on packages (2026-08-26; the `sandbox` extra they replace is gone):
# `openfactory-aws` for the S3 session snapshot/restore that runs INSIDE the task
# (`session_store.s3`, with boto3 as that package's dependency), `openfactory-slack` for the
# deployment-wide Telegram fallback the in-task notifier reaches when
# `OPENFACTORY_NOTIFIER_FALLBACK=telegram` declares it. No temporalio: that stays a host-runtime
# concern, which is why the slack package does not depend on the core's `runtime` extra. The
# wheels are built from `./openfactory` at install time, so the COPY of `addons` comes after it
# (`addons/overlay_build.py`).
#
# WHERE THE TREE HAS THEM — the same optional install as docker/worker.Dockerfile, through the
# same script, for the same measured reason. `addons/` is a row of docs/STATUS.md's excluded-paths
# table, so the public repository does not have that directory, and a bare `COPY addons ./addons`
# there ABORTS the build (`failed to compute cache key: "/addons": not found`) — this image is
# built by the very first command README.md gives a stranger. `addon[s]` matches the directory when
# it is there and matches nothing, without erroring, when it is not. Without the packages the task
# keeps the core: `session_store.s3` and `notifier.telegram` are then refused BY NAME, with the
# package to install. `docker/install-addons.sh` carries the rest, and is RUN by its guard in both
# shapes rather than read for the shape it happens to have.
WORKDIR /opt/openfactory
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY openfactory ./openfactory
COPY docker/install-addons.sh ./docker/install-addons.sh
COPY addon[s] ./addons
RUN sh docker/install-addons.sh .

# git operates on a clone the task makes under /tmp (consistent ownership, no mount);
# allow any dir to avoid dubious-ownership refusals.
RUN git config --global --add safe.directory '*'

WORKDIR /work
ENTRYPOINT []
CMD ["python", "-m", "openfactory.runtime.boxed_job"]

# WHAT THIS BOX OFFERS THE CLIENT'S COMMANDS, written down so a REBUILD is not mistaken for a
# CHANGE. A compose deployment builds this image locally, so it has no registry digest and the
# proof pins its content id — which moves on every `--build`, including the ones that only carry
# a new version of our own package. The pilot's tech-lead channel filled with "the image changed
# — run box prove" after each update, and the factory held his tickets each time (2026-08-15).
#
# The client's `setup:` and `validate:` depend on the TOOLCHAIN, not on `openfactory`'s bytes. So
# the box records the toolchain, the proof records what it saw, and `gate_reason` re-proves only
# when THIS line changes. Kept deliberately cheap and readable: an operator can run
# `docker run --rm <image> cat /etc/openfactory-toolchain` and see exactly what a proof is
# pinned to.
RUN { \
      echo "os=$(. /etc/os-release 2>/dev/null && echo \"$ID $VERSION_ID\")"; \
      echo "python=$(python3 -V 2>&1)"; \
      echo "node=$(node -v 2>/dev/null || echo none)"; \
      echo "git=$(git --version 2>&1)"; \
      echo "gh=$(gh --version 2>/dev/null | head -1 || echo none)"; \
      echo "uv=$(uv --version 2>/dev/null || echo none)"; \
    } > /etc/openfactory-toolchain && cat /etc/openfactory-toolchain
