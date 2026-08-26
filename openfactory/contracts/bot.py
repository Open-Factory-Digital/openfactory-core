"""Bot identity & per-axis credentials — the agent acts as a distinct actor (D-12).

Two separate things, kept separate on purpose so nothing is provider-locked:

- **The actor** (`name`, `email`) — one logical identity, used as the git commit
  author. Provider-agnostic.
- **The credentials** — one **per axis**, because the axes are independent. A
  Jira-tracker + GitLab-forge project needs a Jira API token *and* a GitLab access
  token; a single-vendor GitHub project can reuse one token for both. Each token is
  **opaque to the framework** — how it's obtained is a per-provider concern (a
  GitHub App installation token, a GitLab Project/Group Access Token, a Jira API
  token, a bot PAT…). Each adapter authenticates with its token its own way.

Tokens come from the environment, never the registry (no plaintext secrets):
`OPENFACTORY_BOT_TOKEN` is the default; `OPENFACTORY_TRACKER_TOKEN` / `OPENFACTORY_FORGE_TOKEN`
override
per axis when the providers differ. `None` falls back to ambient CLI auth (dev).
Least privilege on these tokens is the executable control behind the floor.
(Auto-minting short-lived tokens — needed for GitHub Apps, unnecessary for
long-lived GitLab/Jira tokens — is a future per-adapter `TokenProvider` seam.)
"""

from __future__ import annotations

from pydantic import BaseModel


class BotIdentity(BaseModel):
    """WHO the factory commits, comments and pushes as.

    A value, and only a value. It used to build itself from `os.environ` — a domain model reaching
    into process state, which a vendor-NAME guard would never catch and which makes the kernel
    untestable without a environment to arrange. Reading the environment is the composition root's
    job and now lives in `openfactory/credentials.py`.

    Neutral defaults: every deployment sets its own brand (the worker task injects them from
    terraform). The defaults only apply to a bare local run.
    """

    name: str = "OpenFactory Bot"
    email: str = "openfactory-bot@localhost"
    login: str | None = None  # the bot's username on the tracker (for claim/lock)
