# Per-stack base image for ContainerSandbox (ADR-0001 D-4).
# Project-agnostic: toolchain + git + the `claude` CLI preinstalled so job startup
# is fast and reproducible. The repo is mounted at /workspace at run time, never
# baked in. One image per stack (python here; mirror for node/terraform).
# Platform: NOT pinned. `infra/deploy.sh` passes `--platform` explicitly for the cloud
# (arm64 for Fargate, amd64 for the panel), so a hard-coded FROM platform bought that build
# nothing and cost everyone else the ability to build at all — both prospect stacks run x86
# Linux. Left unpinned, Docker builds natively for whatever machine runs it, and an explicit
# --platform still wins. (C-13)
FROM python:3.12-slim

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
# stronger no-op than an environment variable that is always set to something.
COPY docker/extra-ca/ /tmp/extra-ca/
RUN set -eu; \
    if ls /tmp/extra-ca/*.crt >/dev/null 2>&1; then \
      command -v update-ca-certificates >/dev/null 2>&1 || { \
        apt-get update && apt-get install -y --no-install-recommends ca-certificates \
        && rm -rf /var/lib/apt/lists/* ; }; \
      cp /tmp/extra-ca/*.crt /usr/local/share/ca-certificates/; \
      update-ca-certificates; \
      printf 'cafile=/etc/ssl/certs/ca-certificates.crt\n' > /etc/npmrc; \
      printf '[global]\ncert = /etc/ssl/certs/ca-certificates.crt\n' > /etc/pip.conf; \
      echo "extra CA trusted: $(ls /tmp/extra-ca/*.crt)"; \
    else \
      echo "no extra CA supplied (docker/extra-ca holds no .crt) — the default trust store stands"; \
    fi; \
    rm -rf /tmp/extra-ca

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

RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl ca-certificates nodejs npm make build-essential \
    && rm -rf /var/lib/apt/lists/*

# THE PACKAGE-MANAGER FLOOR (pilot, 2026-08-13). The rule that decides what belongs here: if
# `openfactory env read`/`onboard` can PROPOSE a command, the stock box must be able to RUN it —
# the first pilot proof failed on `uv sync` read from the client's own CI, inside an image that
# never carried uv, a contradiction between our proposer and our own box. pip and npm come from
# the layers above; uv/pnpm/yarn are the other managers the proposer recognises. Versions PINNED
# for the same reason as the CLI below. dotnet/go/maven/cargo are deliberately NOT here — for a
# stack beyond this floor the proof's remedy says so and `box.image` is the client's answer.
RUN pip install --no-cache-dir uv==0.8.6 \
    && npm install -g pnpm@10.14.0 yarn@1.22.22

# The agent executor. We run `claude -p` (CLI), never the Agent SDK. PIN the version: an
# unpinned install drifts silently between builds (a cached layer once shipped an older CLI
# than local), and the read-only enforcement depends on how the CLI honours --tools /
# --disallowedTools. Bump deliberately, after verifying the flags still restrict.
RUN npm install -g @anthropic-ai/claude-code@2.1.219

# ADDITIVE, AND THAT IS WHY IT IS UNCONDITIONAL. `NODE_EXTRA_CA_CERTS` EXTENDS Node's built-in
# roots — it never replaces them — so with no extra CA this points at Debian's own store and
# changes nothing. With one, the CLIENT's `npm ci` trusts it too, and that install runs at RUN
# time inside the box, long after this build: a build-time-only fix would leave every job failing
# on the same certificate this file exists to install.
ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt

WORKDIR /workspace

# The workspace is a host-owned bind mount; allow git to operate on it as root.
RUN git config --global --add safe.directory /workspace

# Auth (CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY) is injected as env at run
# time by ContainerSandbox — never baked into the image.
