"""The merge re-authors the concepts its change invalidated — one function, for every trigger.

THE CODE IS THE GROUND TRUTH, SO A CHANGE TO IT MOVES THE OKF. Until this module, the concepts
were written ONCE, at the backfill, and never again: `propose_concepts` had exactly one caller
(`onboard.py::_backfill`), while the refresh that runs after every merge and every six hours
(`_do_refresh_knowledge`) regenerated the module map alone. A file rewritten on day 30 left its
concept describing day 1 forever, and the checker (`knowledge/check.py`) could only tell a reader
so at the moment of reading. The product owner's expectation, 2026-09-04: *"o OKF atualiza depois
da mudança do código"* — the trigger is the change, not a question and not a clock.

ONE PATH, THREE TRIGGERS. This is the only place concepts are renewed. The merge-time refresh and
the scheduled refresh are already one activity, and it calls this; nothing else re-implements the
decision. Three call sites of one function cannot drift the way three copies would.

THE FINGERPRINT IS THE SIGNAL, NOT THE DIFF. A merge knows which files it touched, and it is
tempting to intersect that with the concepts' sources — but the fingerprint already compares the
bytes a concept READ with the bytes that are there now, exactly, per concept, and needs no git
history to do it (the worker's checkout may be shallow). The diff would be a second, weaker
answer to a question the bundle already answers precisely.

WHAT A BROKEN CONCEPT COSTS, AND WHO PAYS. A concept is re-authored per MODULE (the unit the prompt
describes), under the project's own budget, with the same harness the backfill used. A broken
concept the budget did not reach this round — or that no harness on this machine could rewrite —
is written into the manifest as a `stale` gap naming it, so the index shows it until a round
reaches it. That is the platform's rule for anything it could not establish: data, not silence.

NEVER DELETES, NEVER RAISES. `write_okf`'s promise holds: a concept this pass did not rewrite is
left exactly where it is. A re-authored concept replaces its file only when it comes back with the
same type and title; a retitled one lands beside the old, which the checker keeps flagging until
somebody decides. And a failure anywhere here costs the renewal, never the merge that triggered it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import NamedTuple

from openfactory.knowledge.check import FRESH, ConceptCheck, check_concepts
from openfactory.knowledge.contracts import Concept, Gap, OkfManifest
from openfactory.knowledge.okf import (
    OKF_INDEX_FILE,
    read_concepts,
    read_manifest,
    render_index,
    write_okf,
)

log = logging.getLogger("openfactory.onboarding.renew")

#: The gap kind a broken concept becomes when this round could not re-author it. Open, like every
#: other kind (`Gap.kind` is deliberately not an enum); named here so the reader and the writer
#: agree on the string.
STALE_GAP = "stale"


class Renewal(NamedTuple):
    """What one renewal did, for the log line and the outcome word."""

    checked: int      # concepts in the published bundle
    broken: int       # of those, stale or missing against this checkout
    rewritten: int    # re-authored this round
    left: int         # broken and NOT re-authored — recorded as `stale` gaps
    mode: str         # "nothing-published" / "fresh" / the harness mode / "failed"

    @property
    def wrote(self) -> bool:
        """Whether the bundle on disk changed — the manifest is rewritten whenever anything was
        broken, so a round that rewrote nothing but recorded gaps still has to publish."""
        return self.broken > 0 and self.mode != "failed"

    def summary(self) -> str:
        if self.checked == 0:
            return "no concepts published"
        if self.broken == 0:
            return f"{self.checked} concepts, all fresh"
        return (f"{self.checked} concepts, {self.broken} broken: {self.rewritten} re-authored, "
                f"{self.left} left as gaps ({self.mode})")


def renew_concepts(project, bundle_dir: Path, source: Path, *, commit: str,
                   generated_at: str) -> Renewal:
    """Re-author the concepts in `bundle_dir` that no longer match the checkout at `source`.

    `bundle_dir` is the published `.okf/repos/<source>/` as the refresh has it on disk — with the
    module map beside the concepts, which is why the manifest is `okf.yaml` and not `manifest.yaml`.
    """
    try:
        return _renew(project, Path(bundle_dir), Path(source), commit=commit,
                      generated_at=generated_at)
    except Exception as exc:  # noqa: BLE001 — the merge already happened; the renewal is best-effort
        log.warning("concept renewal failed for %s (%s)", getattr(project, "name", "?"),
                    str(exc)[:200])
        return Renewal(0, 0, 0, 0, "failed")


def _renew(project, bundle_dir: Path, source: Path, *, commit: str, generated_at: str) -> Renewal:
    existing = read_concepts(bundle_dir)
    if not existing:
        return Renewal(0, 0, 0, 0, "nothing-published")
    report = check_concepts(bundle_dir, source)
    broken = list(report.broken)
    if not broken:
        return Renewal(len(existing), 0, 0, 0, "fresh")

    # THE SAME HARNESS, BUDGET AND SURVEY THE BACKFILL USES — imported here, not copied, so the
    # refresh cannot come to a different answer than onboarding about what this machine can run.
    from openfactory.knowledge.bundle import compute_checksums
    from openfactory.onboarding import context as ctx
    from openfactory.onboarding.concepts import modules_for_sources, propose_concepts
    from openfactory.onboarding.history import read_history
    from openfactory.onboarding.onboard import _concept_budget, semantic_pass_for

    ask_fn, mode = semantic_pass_for(project, source)
    rewritten: list[Concept] = []
    new_gaps: list[Gap] = []
    if ask_fn is not None:
        survey = ctx.survey(str(source), history=read_history(source))
        wanted = modules_for_sources(survey, _broken_paths(broken))
        budget = _concept_budget(project, source)
        fingerprints = {c.file: c.sha256 for c in compute_checksums(source)}
        rewritten, new_gaps = propose_concepts(
            survey, ask=ask_fn, budget=budget, modules=wanted, commit=commit,
            generated_at=generated_at, language=getattr(project, "language", None),
            fingerprints=fingerprints)

    covered = {(c.type, c.title) for c in rewritten}
    left = [b for b in broken if (b.type, b.title) not in covered]
    why = ("no harness could write one on this machine" if ask_fn is None
           else "over budget this round")
    manifest = read_manifest(bundle_dir) or OkfManifest(bundle_kind="source-repo")
    gaps = [g for g in manifest.gaps if g.kind != STALE_GAP] + new_gaps + [
        Gap(kind=STALE_GAP, path=_first_broken_path(b),
            detail=f"'{b.title}' no longer matches the source and was not re-authored — {why}")
        for b in left
    ]
    manifest = manifest.model_copy(update={
        "source_commit": commit, "generated_at": generated_at, "gaps": gaps})
    write_okf(bundle_dir, manifest=manifest, concepts=rewritten)
    # THE INDEX LISTS WHAT IS THERE NOW — the untouched, the rewritten and the gaps — not only what
    # this round wrote. Re-derived from the directory for the reason `_front_door` gives.
    (bundle_dir / OKF_INDEX_FILE).write_text(
        render_index(manifest, read_concepts(bundle_dir)), encoding="utf-8")
    return Renewal(len(existing), len(broken), len(rewritten), len(left), mode)


def _broken_paths(broken: list[ConceptCheck]) -> list[str]:
    out: list[str] = []
    for concept in broken:
        for src in concept.sources:
            if src.verdict != FRESH and src.path not in out:
                out.append(src.path)
    return out


def _first_broken_path(concept: ConceptCheck) -> str:
    return next((s.path for s in concept.sources if s.verdict != FRESH), "")
