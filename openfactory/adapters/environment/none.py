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
vocabulary's own word for *no run found*; and `health` PROBES, like every other row's. None of the
answers is `None`: this row is not failing to look, it is looking at a system that does not exist.

`health` USED TO ANSWER False WITHOUT LOOKING (#518). Its reasoning was right — a probe that was
never made must not report a healthy service — and the conclusion was not: the URL is the client's
own page, not a CI's, and every other row probes it the same way ("provider-independent by
nature", the Azure row says). Once `"none"` stopped counting as a reached stage, a `health_url` is
the ONE observation a project without a CI has, and a `False` that never looked held every such
stage red with "deploy/health failed" — a failure nobody saw. A probe that IS made reports what it
got: healthy only when the page answered, False when it did not or could not be reached.
"""

from __future__ import annotations

import logging

from openfactory.adapters.environment.base import CheckStatus

log = logging.getLogger("openfactory.environment.none")


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
        """The client's own page, probed: healthy only when it answered with a success status.

        THE ONE OBSERVATION THIS PROJECT HAS (#518). There is no CI to read a deploy from, so a
        stage of its chain is reached on its `health_url` or not at all — which is why the
        manifest is refused when a stage declares none. Never raises: an unreachable page, or a
        `health_url` that is not a URL, is False, the same answer and the same reason as the
        other rows."""
        import httpx

        try:
            return httpx.get(url, timeout=timeout).is_success
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            log.warning("health probe %s failed: %s", url, exc)
            return False
