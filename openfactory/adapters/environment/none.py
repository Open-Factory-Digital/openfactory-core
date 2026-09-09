"""`ci: none` — an observer for a project whose code is watched by nothing (ADR-0049 D1).

AN HONEST ROW, NOT A DEGRADED ONE. Every other row on this axis reaches a CI system and reports
what it found; this one reports that there is nothing to find, which is a different and equally
true answer. It exists because `build_observer` REFUSES an unknown kind, on the reasoning that an
observer pointed at the wrong system never confirms a deployment and the symptom is a release that
hangs in *verifying* for ever. That reasoning is right, and it left a deployment with no CI at all
with nowhere to go: the registry knew four names, all of them somebody's pipelines.

`none` IS THE NAME A DEPLOYMENT WRITES, and any forge may name it through `forge.options.ci` — a
GitHub project whose repository has no workflows is entitled to say so rather than being told its
checks are pending for ever. `local` maps here too, so the rule that turns `azure_devops` into
`azure_pipelines` turns the platform's own forge into *nothing is watched*, without the caller
having to know which.

WHY THE ANSWERS ARE THE SHAPES THEY ARE. `[]` from `ci_status` is *there are no checks*, which is
what the merge loop reads as "nothing to wait for"; `"none"` from `deploy_status` is the Status
vocabulary's own word for *no run found*; and `health` answers False, because a probe that was
never made must not report a healthy service. None of the three is `None`: this row is not failing
to look, it is looking at a system that does not exist.
"""

from __future__ import annotations

from openfactory.adapters.environment.base import CheckStatus


class NoObserver:
    """Nothing watches this project's code, and every answer says so."""

    def __init__(self, project=None, *, token: str | None = None) -> None:
        #: Accepted and ignored, as on every other row: the composition root hands this axis a
        #: credential unconditionally, and a row that refused the argument would fail on a
        #: deployment that has one.
        self.token = token

    def ci_status(self, *, repo: str, ref: str) -> list[CheckStatus]:
        """`[]` — asked, and this project has no checks.

        NOT `None`, AND THE DIFFERENCE MATTERS HERE AS EVERYWHERE ELSE ON THIS PLATFORM: `None`
        would say the checks could not be read, which sends a caller to look for a credential that
        does not exist. `[]` is a fact — there is nothing watching — and the merge loop reads it as
        nothing to wait for."""
        return []

    def deploy_status(self, *, env: str, ref: str) -> str:
        """`"none"` — the Status vocabulary's own word for *no run found for this ref*."""
        return "none"

    def health(self, *, url: str, timeout: int = 10) -> bool:
        """`False`. A probe nobody made must not report a healthy service — the caller then says
        it could not confirm, which is true, rather than confirming something it never saw."""
        return False
