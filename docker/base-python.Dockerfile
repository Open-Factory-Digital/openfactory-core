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

WORKDIR /workspace

# The workspace is a host-owned bind mount; allow git to operate on it as root.
RUN git config --global --add safe.directory /workspace

# Auth (CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY) is injected as env at run
# time by ContainerSandbox — never baked into the image.
