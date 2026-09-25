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
