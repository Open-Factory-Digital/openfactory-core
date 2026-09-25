"""`OPENFACTORY_PREVIEW_RUNTIME=none` — a deployment that runs no preview, and says so by name
(ADR-0050 D11; the design on #265, §5.1).

AN HONEST ROW, NOT A DEGRADED ONE — the CI axis's `none` precedent. A cloud worker has no Docker
daemon, and the one-machine kind has none until its person opts in; on both, "no preview can run
here" is a true answer, and every surface that asks gets it in the same sentence. What this row
must never do is answer `[]` from `prerequisites()`: a deployment reported ready for previews that
then runs nothing is the silence this platform exists to end.
"""

from __future__ import annotations

from openfactory.preview.plan import PreviewPlan, PreviewUp, RunningPreview

#: The sentence. One place, because the card, `doctor` and `preview prove` all say it.
REFUSAL = ("this deployment names no preview runtime (OPENFACTORY_PREVIEW_RUNTIME=none) — set it "
           "to `compose` where the worker holds a Docker daemon, or install an add-on that "
           "declares `preview.<kind>`")

#: The same answer on ONE MACHINE (ADR-0049's local kind; the design on #265, §7.2), where "no
#: Docker" is the promise and a preview is opted into, not installed: the card names the four
#: lines `openfactory init` wrote commented, so the way in is on the card that has no preview.
ONE_MACHINE = ("No preview on this deployment — the one-machine runtime names no preview "
               "runtime; with Docker installed, set OPENFACTORY_PREVIEW_RUNTIME=compose, "
               "OPENFACTORY_PREVIEW_REACH=loopback, OPENFACTORY_PREVIEW_PORTS=42000-42999 and "
               "OPENFACTORY_PREVIEW_DOMAIN=preview.localhost")


def said() -> str:
    """Which of the two sentences this deployment says: the one-machine one where the deployment
    has declared the worker is its person's own machine (`OPENFACTORY_OWN_WORK`, the declaration
    `init` writes for the local kind and never for a server), the general one everywhere else."""
    from openfactory import own_work

    return ONE_MACHINE if own_work.declared() else REFUSAL


class NoRuntime:
    """Runs nothing; every answer says why, and nothing it answers can be mistaken for a preview."""

    def prerequisites(self) -> list[str]:
        return [REFUSAL]

    def up(self, plan: PreviewPlan) -> PreviewUp:
        return PreviewUp(ok=False, why=REFUSAL)

    def watch(self, compose_project: str) -> RunningPreview | None:
        return None

    def logs(self, compose_project: str, log_dir: str) -> list[str]:
        return []

    def down(self, compose_project: str, workdir: str) -> list[str]:
        return []

    def running(self) -> list[RunningPreview]:
        return []

    def prove(self, plan: PreviewPlan) -> PreviewUp:
        return PreviewUp(ok=False, why=REFUSAL)
