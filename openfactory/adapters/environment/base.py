"""EnvironmentObserver — read-only observation of CI, deploys, and health (D-12).

This is how the platform learns whether a change actually shipped. It never holds
deploy/prod secrets; it only reads status and probes public/known health endpoints.
Feeds the lifecycle state machine and the Notifier.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel

Status = Literal["pending", "success", "failure", "unknown"]


class CheckStatus(BaseModel):
    name: str
    status: Status
    url: str | None = None


@runtime_checkable
class EnvironmentObserver(Protocol):
    def ci_status(self, *, repo: str, ref: str) -> list[CheckStatus]:
        """Status of the project's real CI checks on a PR/commit (read-only)."""
        ...

    def deploy_status(self, *, env: str, ref: str) -> Status:
        """Status of the deploy to `env` (e.g. 'staging', 'prod') for a ref."""
        ...

    def health(self, *, url: str, timeout: int = 10) -> bool:
        """Probe a health endpoint; True if healthy."""
        ...
