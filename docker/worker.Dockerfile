# The Temporal worker image (ADR-0001 D-16). Unlike the sandbox image, the worker only
# ORCHESTRATES — it never runs the project's build/test — so it needs just Python + the
# platform's runtime extra (temporalio + boto3), not the heavy toolchain. Small + fast.
#
#   docker build -f docker/worker.Dockerfile -t openfactory-worker .
#
# In prod this runs as an ECS service that ASSUMES the openfactory-worker IAM role (see
# infra/terraform/worker.tf), so its AWS creds auto-refresh — never static/expiring.
# Temporal connection (TEMPORAL_ADDRESS / TEMPORAL_NAMESPACE + TLS for Temporal Cloud)
# and the OPENFACTORY_FARGATE_* config are injected as env at deploy time.
# Default ARM64 (Graviton — cheaper) for the worker/panel on Fargate. Override to
# linux/amd64 for App Runner, which doesn't support ARM:
#   docker build --platform linux/amd64 ...
# Platform: NOT pinned. `infra/deploy.sh` passes `--platform` explicitly for the cloud
# (arm64 for Fargate, amd64 for the panel), so a hard-coded FROM platform bought that build
# nothing and cost everyone else the ability to build at all — both prospect stacks run x86
# Linux. Left unpinned, Docker builds natively for whatever machine runs it, and an explicit
# --platform still wins. (C-13)
# ── the harness toolbox (ADR-0037 D2) ───────────────────────────────────────────────────────────
#
# A separate stage so ~800 MB of npm scratch never lands in the shipped layer: only the assembled
# toolbox is copied forward.
#
# WHY THIS EXISTS. Under D1 the box is built from the CLIENT's image, so the harness cannot live in
# it — we do not control that image and will not ask a client to rebuild theirs when we pin a new
# agent CLI. The harness ships here instead, and is mounted read-only into every box.
#
# WHY ALL OF THEM. The product owner, asked whether to carry one or all: *"all of them, for
# certain — 800MB or 10GB is a cheap price for the benefit."* Carrying them all is what makes `harness: {executor: codex,
# reviewer: claude_code}` pure configuration — rotating between harnesses, or mixing them per role,
# never touches an image. Carrying one would put a rebuild between a client and a decision they are
# entitled to change on a Tuesday. `opencode` joined as the fourth for the axis's other half: it is
# the one that reaches Bedrock, Azure/Foundry, Vertex or any OpenAI-compatible endpoint by changing
# `model:` alone, so "which provider serves this client" stops needing a different harness.
#
# WHY NODE COMES TOO, and this is a correction to the first draft of the ADR: only `claude` is a
# self-contained native. `codex`'s npm entry is a `#!/usr/bin/env node` shim over a vendored binary,
# and `kimi` is an ESM bundle with no native at all. Measured, not assumed. Choosing per harness
# would give a toolbox that works for two and silently not the third, so all three go through the
# runtime that ships beside them — at ~50 MB it is noise next to the harnesses.
FROM node:20-slim AS toolbox

ARG HARNESS_CLAUDE=@anthropic-ai/claude-code@2.1.219
ARG HARNESS_CODEX=@openai/codex@0.146.0
ARG HARNESS_KIMI=@moonshot-ai/kimi-code@0.31.1
ARG HARNESS_OPENCODE=1.18.13

# ── A ROOT CA THIS DEPLOYMENT'S NETWORK REQUIRES — empty in this repository ──────────────────
# An organisation that terminates outbound HTTPS (Zscaler, Netskope, a corporate proxy) presents a
# certificate signed by a root no public image ships. `apt` survives it — Debian's mirrors are
# plain HTTP — so the build dies on the SECOND network instruction and reads like a broken package
# rather than a broken trust store:
#
#     pip install uv → SSLError(CERTIFICATE_VERIFY_FAILED): unable to get local issuer certificate
#
# WITH NO `.crt` IN `docker/extra-ca/` THIS IS A NO-OP, which is the property that matters: the
# public build stays what it was and nobody opts out of anything. That directory is COMMITTED
# (with its README) rather than made optional, because `COPY docker/extra-c[a]` — the trick
# `COPY addon[s]` uses one level up — does NOT tolerate a missing NESTED directory: BuildKit
# answers `lstat /docker: no such file or directory`. Measured 2026-08-27, both forms.
#
# `/etc/npmrc` and `/etc/pip.conf` rather than `npm config set` and `PIP_CERT`: a file can be
# written before either tool is installed — which is the whole point, since this block has to run
# BEFORE the installs it exists to make possible — and a file that was never written is a
# stronger no-op than an environment variable that is always set to something.#
# THREE npmrc PATHS AND NOT ONE, because npm's global config is `$PREFIX/etc/npmrc` and the prefix
# depends on where npm came from. Measured, after this block was written with `/etc/npmrc` alone
# and the worker's toolbox stage then died on `UNABLE_TO_GET_ISSUER_CERT_LOCALLY`:
#
#     python:3.12-slim (npm from Debian's apt) → globalconfig /etc/npmrc
#     node:20-slim     (the official image)    → globalconfig /usr/local/etc/npmrc
#
# The base image passed on a coincidence of layout rather than on the block being right, which is
# the worst way for a fix to look correct. `pip` needs no such care: `/etc/pip.conf` IS its global
# file on Linux, wherever pip came from.
COPY docker/extra-ca/ /tmp/extra-ca/
RUN set -eu; \
    mkdir -p /usr/local/share/openfactory; \
    : > /usr/local/share/openfactory/extra-ca.crt; \
    if ls /tmp/extra-ca/*.crt >/dev/null 2>&1; then \
      command -v update-ca-certificates >/dev/null 2>&1 || { \
        apt-get update && apt-get install -y --no-install-recommends ca-certificates \
        && rm -rf /var/lib/apt/lists/* ; }; \
      cp /tmp/extra-ca/*.crt /usr/local/share/ca-certificates/; \
      update-ca-certificates; \
      cat /tmp/extra-ca/*.crt > /usr/local/share/openfactory/extra-ca.crt; \
      printf '[global]\ncert = /etc/ssl/certs/ca-certificates.crt\n' > /etc/pip.conf; \
      echo "extra CA trusted: $(ls /tmp/extra-ca/*.crt)"; \
    else \
      echo "no extra CA supplied (docker/extra-ca holds no .crt) — the default trust store stands"; \
    fi; \
    rm -rf /tmp/extra-ca

# NODE, AND THE ONE MECHANISM `--prefix` CANNOT MOVE. This file is ALWAYS created — empty when the
# deployment supplied nothing — and the variable is therefore always valid, which is what keeps the
# public build silent: node warns on a MISSING extra-certs file on every invocation and says
# nothing about an empty one (measured, both).
#
# IT REPLACED AN npmrc, AND THE REASON IS THE WHOLE TRAP. npm's global config is `$PREFIX/etc/npmrc`
# and `--prefix` REDEFINES that prefix, so `npm install -g --prefix /toolbox/pkg` — the worker's own
# toolbox line — reads `/toolbox/pkg/etc/npmrc` and no file this block could have written. The first
# fix wrote `/etc/npmrc`, which is where Debian's npm looks, so the base image built green while the
# toolbox stage died on UNABLE_TO_GET_ISSUER_CERT_LOCALLY; the second wrote three prefixes and died
# the same way, because the one that mattered is chosen by the caller. `NODE_EXTRA_CA_CERTS` is read
# by node itself, so npm inherits it whatever prefix it is handed — and it EXTENDS node's roots
# rather than replacing them, which is why it can be set unconditionally.
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/openfactory/extra-ca.crt

# ── WHERE `apt` FETCHES FROM — Debian's own mirror unless a deployment says otherwise ────────
# `DEBIAN_MIRROR` is empty here and the sed is then a no-op: the public build fetches exactly
# where it always did.
#
# IT EXISTS BECAUSE PORT 80 IS NOT UNIVERSALLY REACHABLE, and the way it fails is expensive.
# Debian's sources are plain HTTP by design (apt verifies signatures, so the transport need not be
# private), and a corporate network that inspects 443 while throttling 80 lets `apt-get update`
# succeed, streams most of the archive, and then drops the connection part way through the
# install:
#
#     E: Failed to fetch http://deb.debian.org/…/npm_9.2.0~ds1-3_all.deb
#        Unable to connect to deb.debian.org:http [IP: 146.75.90.132 80]
#
# Measured twice at the same point, ~136 MB in (Debian trixie packages `npm` with several hundred
# node-* dependencies), then measured again with `https://deb.debian.org` — the identical install
# completed in 156 seconds. A mirror of your own works the same way.
#
# ORDER: THIS FOLLOWS THE CA BLOCK AND MUST. An https mirror cannot be verified by an image that
# does not yet trust the root its proxy presents, and the failure is not "TLS refused" — apt
# reports no package lists at all and every install then says `E: Unable to locate package git`,
# which reads like a broken mirror rather than a missing certificate. Measured, in that order,
# 2026-08-27. A guard asserts the ordering so it cannot be reversed by a tidy-up.
ARG DEBIAN_MIRROR=""
RUN set -eu; \
    if [ -n "${DEBIAN_MIRROR}" ]; then \
      sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list 2>/dev/null || true; \
      echo "apt fetches from ${DEBIAN_MIRROR}"; \
    else \
      echo "apt fetches from Debian's own mirror over http (set DEBIAN_MIRROR to change it)"; \
    fi

RUN npm install -g --prefix /toolbox/pkg "$HARNESS_CLAUDE" "$HARNESS_CODEX" "$HARNESS_KIMI"

# The Node runtime the wrappers below invoke by absolute path, and `rg`, which is opencode's one
# runtime dependency. It lives here rather than being expected of the CLIENT's image for the same
# reason the harnesses do — we do not control that image (ADR-0037 D1).
RUN apt-get update && apt-get install -y --no-install-recommends ripgrep && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /toolbox/runtime/bin \
 && cp "$(command -v node)" /toolbox/runtime/bin/node \
 && cp "$(command -v rg)" /toolbox/runtime/bin/rg

# OPENCODE IS INSTALLED BY ITS PLATFORM PACKAGE, NOT BY THE META-PACKAGE, and that is deliberate.
# `opencode-ai`'s `bin/opencode.exe` ships as a SHELL STUB that only prints "postinstall was not
# run"; a real binary appears solely as a side effect of `postinstall.mjs`. So the usual hardening
# reflex — `npm ci --ignore-scripts` — would produce a toolbox that builds green, stamps `opencode`
# as present, passes a `--version` smoke test with an error message, and fails every real run.
#
# Worse, that postinstall chooses the artefact from the BUILD MACHINE: it reads `/proc/cpuinfo` for
# AVX2 and `ldd --version` for musl. The libc half matches how this toolbox is already built (one
# image per variant), but AVX2 is invisible to the variant stamp — a toolbox built on a modern
# builder would take the AVX2 binary and SIGILL on an older host, which the OSS `docker compose`
# distribution makes a real target rather than a hypothetical one. Pinning `-baseline` on x64 costs
# nothing measurable for a CLI that spends its life waiting on a model, and removes the coupling.
ARG TARGETARCH
RUN set -eu; \
    arch="${TARGETARCH:-$(uname -m)}"; \
    case "$arch" in \
      amd64|x86_64) pkg=opencode-linux-x64-baseline ;; \
      arm64|aarch64) pkg=opencode-linux-arm64 ;; \
      *) echo "no opencode build for arch '$arch'" >&2; exit 1 ;; \
    esac; \
    npm install -g --prefix /toolbox/pkg "$pkg@$HARNESS_OPENCODE"; \
    printf '#!/bin/sh\nPATH=/opt/openfactory-toolbox/runtime/bin:$PATH\nexport PATH\nexec /opt/openfactory-toolbox/pkg/lib/node_modules/%s/bin/opencode "$@"\n' \
      "$pkg" > /toolbox/opencode; \
    chmod 0755 /toolbox/opencode

# One entry per harness at the TOP of the toolbox, which is what `harness_path()` names. `claude`
# is the native ELF, linked straight through. The other two are wrappers that give BOTH halves
# absolutely — the runtime and the script — because the whole point of D2a is that nothing is found
# via PATH inside an image whose /etc/profile we did not write.
RUN set -eu; \
    ln -s /opt/openfactory-toolbox/pkg/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe \
          /toolbox/claude; \
    for h in codex:@openai/codex/bin/codex.js kimi:@moonshot-ai/kimi-code/dist/main.mjs; do \
      name="${h%%:*}"; script="${h#*:}"; \
      printf '#!/bin/sh\nexec /opt/openfactory-toolbox/runtime/bin/node /opt/openfactory-toolbox/pkg/lib/node_modules/%s "$@"\n' \
        "$script" > "/toolbox/$name"; \
      chmod 0755 "/toolbox/$name"; \
    done


FROM python:3.12-slim

# The assembled toolbox, baked where `openfactory.runtime.toolbox.populate()` looks for it. It is copied
# from here into a docker VOLUME on the worker's first boot — never mounted from this path, because
# a `-v` issued by a containerised worker is resolved by the HOST daemon, where this path does not
# exist, and Docker would create an empty directory rather than fail.
COPY --from=toolbox /toolbox /opt/openfactory-toolbox-src

# ── A ROOT CA THIS DEPLOYMENT'S NETWORK REQUIRES — empty in this repository ──────────────────
# An organisation that terminates outbound HTTPS (Zscaler, Netskope, a corporate proxy) presents a
# certificate signed by a root no public image ships. `apt` survives it — Debian's mirrors are
# plain HTTP — so the build dies on the SECOND network instruction and reads like a broken package
# rather than a broken trust store:
#
#     pip install uv → SSLError(CERTIFICATE_VERIFY_FAILED): unable to get local issuer certificate
#
# WITH NO `.crt` IN `docker/extra-ca/` THIS IS A NO-OP, which is the property that matters: the
# public build stays what it was and nobody opts out of anything. That directory is COMMITTED
# (with its README) rather than made optional, because `COPY docker/extra-c[a]` — the trick
# `COPY addon[s]` uses one level up — does NOT tolerate a missing NESTED directory: BuildKit
# answers `lstat /docker: no such file or directory`. Measured 2026-08-27, both forms.
#
# `/etc/npmrc` and `/etc/pip.conf` rather than `npm config set` and `PIP_CERT`: a file can be
# written before either tool is installed — which is the whole point, since this block has to run
# BEFORE the installs it exists to make possible — and a file that was never written is a
# stronger no-op than an environment variable that is always set to something.#
# THREE npmrc PATHS AND NOT ONE, because npm's global config is `$PREFIX/etc/npmrc` and the prefix
# depends on where npm came from. Measured, after this block was written with `/etc/npmrc` alone
# and the worker's toolbox stage then died on `UNABLE_TO_GET_ISSUER_CERT_LOCALLY`:
#
#     python:3.12-slim (npm from Debian's apt) → globalconfig /etc/npmrc
#     node:20-slim     (the official image)    → globalconfig /usr/local/etc/npmrc
#
# The base image passed on a coincidence of layout rather than on the block being right, which is
# the worst way for a fix to look correct. `pip` needs no such care: `/etc/pip.conf` IS its global
# file on Linux, wherever pip came from.
COPY docker/extra-ca/ /tmp/extra-ca/
RUN set -eu; \
    mkdir -p /usr/local/share/openfactory; \
    : > /usr/local/share/openfactory/extra-ca.crt; \
    if ls /tmp/extra-ca/*.crt >/dev/null 2>&1; then \
      command -v update-ca-certificates >/dev/null 2>&1 || { \
        apt-get update && apt-get install -y --no-install-recommends ca-certificates \
        && rm -rf /var/lib/apt/lists/* ; }; \
      cp /tmp/extra-ca/*.crt /usr/local/share/ca-certificates/; \
      update-ca-certificates; \
      cat /tmp/extra-ca/*.crt > /usr/local/share/openfactory/extra-ca.crt; \
      printf '[global]\ncert = /etc/ssl/certs/ca-certificates.crt\n' > /etc/pip.conf; \
      echo "extra CA trusted: $(ls /tmp/extra-ca/*.crt)"; \
    else \
      echo "no extra CA supplied (docker/extra-ca holds no .crt) — the default trust store stands"; \
    fi; \
    rm -rf /tmp/extra-ca

# NODE, AND THE ONE MECHANISM `--prefix` CANNOT MOVE. This file is ALWAYS created — empty when the
# deployment supplied nothing — and the variable is therefore always valid, which is what keeps the
# public build silent: node warns on a MISSING extra-certs file on every invocation and says
# nothing about an empty one (measured, both).
#
# IT REPLACED AN npmrc, AND THE REASON IS THE WHOLE TRAP. npm's global config is `$PREFIX/etc/npmrc`
# and `--prefix` REDEFINES that prefix, so `npm install -g --prefix /toolbox/pkg` — the worker's own
# toolbox line — reads `/toolbox/pkg/etc/npmrc` and no file this block could have written. The first
# fix wrote `/etc/npmrc`, which is where Debian's npm looks, so the base image built green while the
# toolbox stage died on UNABLE_TO_GET_ISSUER_CERT_LOCALLY; the second wrote three prefixes and died
# the same way, because the one that mattered is chosen by the caller. `NODE_EXTRA_CA_CERTS` is read
# by node itself, so npm inherits it whatever prefix it is handed — and it EXTENDS node's roots
# rather than replacing them, which is why it can be set unconditionally.
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/openfactory/extra-ca.crt

# ── WHERE `apt` FETCHES FROM — Debian's own mirror unless a deployment says otherwise ────────
# `DEBIAN_MIRROR` is empty here and the sed is then a no-op: the public build fetches exactly
# where it always did.
#
# IT EXISTS BECAUSE PORT 80 IS NOT UNIVERSALLY REACHABLE, and the way it fails is expensive.
# Debian's sources are plain HTTP by design (apt verifies signatures, so the transport need not be
# private), and a corporate network that inspects 443 while throttling 80 lets `apt-get update`
# succeed, streams most of the archive, and then drops the connection part way through the
# install:
#
#     E: Failed to fetch http://deb.debian.org/…/npm_9.2.0~ds1-3_all.deb
#        Unable to connect to deb.debian.org:http [IP: 146.75.90.132 80]
#
# Measured twice at the same point, ~136 MB in (Debian trixie packages `npm` with several hundred
# node-* dependencies), then measured again with `https://deb.debian.org` — the identical install
# completed in 156 seconds. A mirror of your own works the same way.
#
# ORDER: THIS FOLLOWS THE CA BLOCK AND MUST. An https mirror cannot be verified by an image that
# does not yet trust the root its proxy presents, and the failure is not "TLS refused" — apt
# reports no package lists at all and every install then says `E: Unable to locate package git`,
# which reads like a broken mirror rather than a missing certificate. Measured, in that order,
# 2026-08-27. A guard asserts the ordering so it cannot be reversed by a tidy-up.
ARG DEBIAN_MIRROR=""
RUN set -eu; \
    if [ -n "${DEBIAN_MIRROR}" ]; then \
      sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list 2>/dev/null || true; \
      echo "apt fetches from ${DEBIAN_MIRROR}"; \
    else \
      echo "apt fetches from Debian's own mirror over http (set DEBIAN_MIRROR to change it)"; \
    fi

RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates \
    && mkdir -p -m 755 /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
       -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
       > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# THE DOCKER CLIENT, and only the client. `ContainerSandbox` shells out to `docker` to start the
# box as a SIBLING container on the host's daemon, through the mounted socket — so the worker needs
# the binary that talks to that socket, and needs no daemon of its own.
#
# It was missing, and the shape of the failure is the point: `docker compose up` came up green,
# every service healthy, and every job would have died on "docker: not found" at the first ticket.
# `openfactory doctor` did catch it and then gave the WRONG remedy — its probe runs `docker info`, which
# fails identically whether the daemon is down or the client is absent, so it said "start Docker
# Desktop" to somebody whose Docker was running perfectly. A check that cannot tell those apart
# sends people to fix the wrong thing, which is worse than not checking.
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
       > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# The pre-flight sizer (ADR-0013 D2) runs a READ-ONLY agent pass on the worker, over its
# cached checkout — so the worker now carries the agent CLI. SAME pinned version as the
# sandbox base image (docker/base-python.Dockerfile) — drift between the two would create
# "works in preflight, breaks in execute" bugs.
RUN npm install -g @anthropic-ai/claude-code@2.1.219

WORKDIR /opt/openfactory
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY openfactory ./openfactory
# THE ADD-ON PACKAGES, BUILT HERE FROM THE SAME TREE — WHERE THE TREE HAS THEM. The cloud rows (the
# remote box, the metrics table, the session store, the token pool) and the chat rows (the channel,
# its notifier, the Telegram fallback) are `addons/openfactory-aws` and `addons/openfactory-slack`
# since 2026-08-26 — not extras of the core, and not rows in its tables. Their wheels carry the
# modules at their original paths, copied from `./openfactory` at build time
# (`addons/overlay_build.py`), so this COPY has to come after the one above. A worker built WITH
# them serves `channel: slack` and `OPENFACTORY_SANDBOX=fargate`; a worker built without them
# refuses both BY NAME, with the package to install — which is the public distribution's answer,
# not a broken one.
#
# BOTH HALVES ARE OPTIONAL, AND THAT IS THE WHOLE POINT OF THE SHAPE. `addons/` is a row of
# docs/STATUS.md's excluded-paths table, so the public repository does not have that directory —
# and a bare `COPY addons ./addons` there does not degrade, it ABORTS: `failed to compute cache
# key: "/addons": not found`. The command it aborts is the first one README.md gives a stranger
# (`docker compose --env-file .env.compose up -d --build`), so the published tree could not run its
# own first command (found 2026-08-26). `addon[s]` is the same optional glob the registry line
# below uses for `registry.yam[l]`: it copies the directory's contents when it is there and matches
# NOTHING, without erroring, when it is not.
#
# THE INSTALL IS A SCRIPT, NOT A SHELL LINE, so that a guard can RUN it instead of reading its
# shape. The loop that lived here was judged by "a glob is copied and an existence test stands
# somewhere in the instruction"; a reviewer swapped `[ -d "$p" ]` for `[ -f README.md ]` — always
# true, README.md is COPYied into this very WORKDIR — and 23 green guards shipped a public build
# that aborts (2026-08-26). `docker/install-addons.sh` states the behaviour instead, and
# `tests/test_the_public_cut_is_written_down.py` runs THIS instruction's own argument list in a
# planted tree with `addons/` and one without.
COPY docker/install-addons.sh ./docker/install-addons.sh
COPY addon[s] ./addons
RUN sh docker/install-addons.sh '.[runtime]'

# WHICH CODE IS ACTUALLY RUNNING IN THIS IMAGE — the question nobody could answer (2026-08-14).
# The package is BAKED here, not mounted, so `git pull && docker compose up -d` restarts the OLD
# build in silence: the operator ran the diagnostic three times against fixes that were on their
# disk and not in their worker, and neither of us could tell from the output. The stamp is
# computed AFTER the COPY above, so Docker's layer cache refreshes it exactly when the code
# changes and keeps it when nothing did — which is the honest answer either way.
RUN python -c "\
import hashlib, json, pathlib, datetime;\
h = hashlib.sha256();\
[h.update(p.read_bytes()) for p in sorted(pathlib.Path('openfactory').rglob('*.py'))];\
pathlib.Path('/etc/openfactory').mkdir(parents=True, exist_ok=True);\
pathlib.Path('/etc/openfactory/build.json').write_text(json.dumps({\
'code': h.hexdigest()[:12],\
'built_at': datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}))"

# The project registry, in two halves (C-12).
#
# The image carries a SEED: immutable, and what this build was shipped knowing. The worker reads a
# WRITABLE path that outlives the image, and copies the seed in on first boot when — and only when
# — it holds no projects yet.
#
# Baking the registry at the path the worker READ meant onboarding a repository cost a rebuild and
# a redeploy, which is disqualifying for a downloadable product; it also meant a rebuild without
# the gitignored deploy/registry.yaml shipped a project-less worker. The seed keeps first boot
# deterministic without the rebuild.
#
# Mount /var/lib/openfactory to make projects added at runtime survive the next deploy. Without a mount
# the worker still runs — it is simply re-seeded each time, which is exactly today's behaviour.
# TWO COPIES, AND THE ORDER IS THE POINT. `deploy/registry.yaml` is gitignored — it is one
# deployment's real project list — so a COPY of it is a build that only its author can run:
# anybody cloning this repository has no such file, and `docker build` aborts on a missing COPY
# source. The distribution could not be built by the people it is FOR, which is a strange thing
# for a distribution to be.
#
# The DISTRIBUTION seed lands first, and it is EMPTY — `projects: {}` — never the annotated
# example: seeding the documentation's `myapp` entry meant every fresh install booted with a
# phantom project already registered and HELD, which is the first thing the pilot operator saw
# and questioned (2026-08-10). `registry.yam[l]` is a glob that matches the real file when it
# exists and matches NOTHING — without erroring — when it does not, so a deployment build still
# overwrites the seed with its own. One line each, no entrypoint logic.
COPY deploy/registry.seed.yaml /etc/openfactory/registry.seed.yaml
COPY deploy/registry.yam[l] /etc/openfactory/registry.seed.yaml
ENV OPENFACTORY_REGISTRY=/var/lib/openfactory/registry.yaml
ENV OPENFACTORY_REGISTRY_SEED=/etc/openfactory/registry.seed.yaml
VOLUME ["/var/lib/openfactory"]

CMD ["python", "-m", "openfactory.runtime.temporal.worker"]
