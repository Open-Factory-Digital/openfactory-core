"""The factory authors what it does not know before it changes it (ADR-0046, decided 2026-09-06).

THE GATE'S LAST PIECE. Under `okf_gate: enforce`, a change touching a file nothing describes was
refused with the question asked — author the knowledge, or merge by hand — and on a legacy
repository after a five-concept backfill that is most changes: a factory that stops to ask on
nearly every pull request is the opposite of the product. So before it asks, it answers: the
same authoring the backfill and the renewal use (`concepts.author_for_paths`), aimed at the
modules the dark files belong to, under the budget the project already declares, written into
the fetched bundle and published; the gate judges again, and parks only if it is still dark.

THE COST IS THE BUDGET, NOT THE REPOSITORY. `okf_concept_budget` bounds every authoring the same
way; a dark change costs at most one backfill's worth of model calls, and nothing that scales
with the size of the client's tree. What it writes is checkable the way every concept is — each
rule cites `path:line` against the bytes on disk, with a fingerprint — and unreviewed the way the
backfill's are: autonomy is the product (the port's first decision), and the concept is born
exactly when somebody is about to change what it describes, which is when it is worth most.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import NamedTuple

from openfactory.knowledge.contracts import OkfManifest
from openfactory.knowledge.gaps import answered_gaps, merge_gaps
from openfactory.knowledge.okf import (
    OKF_INDEX_FILE,
    SCOPE_LIMIT,
    read_concepts,
    read_manifest,
    render_index,
    write_okf,
)
from openfactory.onboarding.concepts import author_for_paths

log = logging.getLogger("openfactory.onboarding.cover")


class Covered(NamedTuple):
    """What one covering did: how many concepts it wrote, which of the asked paths they cite,
    which are still described by nothing, and the harness mode (or why none ran)."""

    authored: int
    covered: tuple[str, ...]
    left: tuple[str, ...]
    mode: str

    def summary(self) -> str:
        if not self.authored:
            return f"nothing authored for {len(self.left)} undescribed file(s) — {self.mode}"
        return (f"authored {self.authored} concept(s) covering {len(self.covered)} of "
                f"{len(self.covered) + len(self.left)} undescribed file(s)")


def cover_paths(project, bundle_dir: Path, source: Path, paths: list[str], *, commit: str,
                generated_at: str) -> Covered:
    """Author concepts for `paths` into the bundle at `bundle_dir` and say what is still uncovered.

    NEVER RAISES: the covering is the factory's own diligence before a change, and a diligence
    that crashed the job it was protecting would be the argument for switching it off. Writes
    nothing when nothing was authored, so a bundle a harness could not serve is left exactly as
    it was fetched."""
    wanted = [p for p in dict.fromkeys(str(p).strip() for p in paths) if p]
    if not wanted:
        return Covered(0, (), (), "nothing to cover")
    bundle = Path(bundle_dir)
    previous = read_manifest(bundle)
    try:
        # WHAT WAS ALREADY ANSWERED RIDES INTO THE PROMPT, so the author does not mint the same
        # question in new words — the way a gather that asked once would ask for ever.
        authored = author_for_paths(project, Path(source), wanted, commit=commit,
                                    generated_at=generated_at, answered=answered_gaps(previous))
    except Exception as exc:  # noqa: BLE001 — the change is judged as it is; nothing is lost
        log.warning("OPENFACTORY_KNOWLEDGE_COVER_FAILED project=%s (%s)",
                    getattr(project, "name", "?"), str(exc)[:160])
        return Covered(0, (), tuple(wanted), f"the authoring failed: {str(exc)[:120]}")
    if not authored.concepts:
        return Covered(0, (), tuple(wanted), authored.mode)
    manifest = previous or OkfManifest(bundle_kind="source-repo", scope_limit=SCOPE_LIMIT)
    manifest = manifest.model_copy(update={
        "source_commit": commit or manifest.source_commit, "generated_at": generated_at,
        # a manifest published without its scope statement gets it here — the sentence that
        # stops a reader treating a machine reading as a specification (the renewal's lesson)
        "scope_limit": manifest.scope_limit or SCOPE_LIMIT,
        # THE RECORD FIRST, BY KEY: an answered question is not shadowed by its re-derivation
        "gaps": merge_gaps(manifest.gaps, authored.gaps)})
    write_okf(bundle, manifest=manifest, concepts=authored.concepts)
    (bundle / OKF_INDEX_FILE).write_text(render_index(manifest, read_concepts(bundle)),
                                         encoding="utf-8")
    cited = {s.path for c in authored.concepts for s in c.sources}
    covered = tuple(p for p in wanted if p in cited)
    return Covered(len(authored.concepts), covered, tuple(p for p in wanted if p not in cited),
                   authored.mode)


__all__ = ["Covered", "cover_paths"]
