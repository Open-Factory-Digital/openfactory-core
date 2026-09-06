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

from openfactory.knowledge.check import FRESH, CheckReport, ConceptCheck, check_concepts
from openfactory.knowledge.contracts import Concept, CoverageRow, Gap, Inventory, OkfManifest
from openfactory.knowledge.inventory import (
    INVENTORY_GAP_KINDS,
    coverage_by_kind,
    inventory_gaps,
    read_inventory,
    take_inventory,
    write_inventory,
)
from openfactory.knowledge.okf import (
    OKF_INDEX_FILE,
    SCOPE_LIMIT,
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
    #: the inventory was re-taken and had CHANGED — files, kinds, fingerprints or risks — so the
    #: bundle on disk changed even when every concept was fresh (#48 joins the renewal path)
    inventoried: bool = False

    @property
    def wrote(self) -> bool:
        """Whether the bundle on disk changed — the manifest is rewritten whenever anything was
        broken, so a round that rewrote nothing but recorded gaps still has to publish."""
        return (self.broken > 0 or self.inventoried) and self.mode != "failed"

    def summary(self) -> str:
        tail = " — inventory refreshed" if self.inventoried else ""
        if self.checked == 0:
            return "no concepts published" + tail
        if self.broken == 0:
            return f"{self.checked} concepts, all fresh{tail}"
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
    if not existing and read_inventory(bundle_dir) is None:
        return Renewal(0, 0, 0, 0, "nothing-published")
    # THE INVENTORY FIRST, EVERY ROUND (#48 joins the renewal path). The backfill took it once; a
    # bundle whose concepts were all fresh kept an inventory of a tree that no longer existed —
    # the coverage table divided by yesterday's files, a credential risk that was fixed still a
    # gap, a file added since read as `new-file` by the gate for ever. Re-taken and compared by
    # SHAPE (paths, kinds, fingerprints, risks), so an unchanged tree writes nothing.
    inventory, inventoried = _refresh_inventory(bundle_dir, source, commit=commit,
                                                generated_at=generated_at)
    report = check_concepts(bundle_dir, source) if existing else CheckReport(())
    broken = list(report.broken)
    if not broken:
        if inventoried:
            manifest = _manifest_for(bundle_dir, inventory, existing, commit=commit,
                                     generated_at=generated_at)
            write_okf(bundle_dir, manifest=manifest, concepts=[])
            (bundle_dir / OKF_INDEX_FILE).write_text(render_index(manifest, existing),
                                                     encoding="utf-8")
        return Renewal(len(existing), 0, 0, 0, "fresh", inventoried)

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
    # A BUNDLE WITH CONCEPTS AND NO MANIFEST — never published by this code, and reachable by a
    # hand-deleted file or a `manifest.yaml` the module map overwrote before `okf.yaml` existed —
    # is renewed from a manifest that still carries the scope statement. Without it the index
    # would say nothing about what the bundle is NOT, which is the sentence it exists to say.
    stale_gaps = [
        Gap(kind=STALE_GAP, path=_first_broken_path(b),
            detail=f"'{b.title}' no longer matches the source and was not re-authored — {why}")
        for b in left
    ]
    # WHAT IS ON DISK AFTER THIS WRITE: `write_okf` never deletes and a rewritten concept lands on
    # its predecessor's path, so the coverage table counts the untouched plus the rewritten.
    now = {(c.type, c.title): c for c in existing}
    now.update({(c.type, c.title): c for c in rewritten})
    manifest = _manifest_for(bundle_dir, inventory, list(now.values()), commit=commit,
                             generated_at=generated_at, new_gaps=new_gaps, stale_gaps=stale_gaps)
    write_okf(bundle_dir, manifest=manifest, concepts=rewritten)
    # THE INDEX LISTS WHAT IS THERE NOW — the untouched, the rewritten and the gaps — not only what
    # this round wrote. Re-derived from the directory for the reason `_front_door` gives.
    (bundle_dir / OKF_INDEX_FILE).write_text(
        render_index(manifest, read_concepts(bundle_dir)), encoding="utf-8")
    return Renewal(len(existing), len(broken), len(rewritten), len(left), mode, inventoried)


def _shape(inventory: Inventory) -> tuple:
    """What makes two inventories the same inventory: the files, their kinds and bytes, the
    remainders and the risks — never the commit stamp or the clock."""
    return (tuple((f.path, f.kind, f.fingerprint) for f in inventory.files),
            tuple(inventory.unclassified), tuple(inventory.ignored), tuple(inventory.unreadable),
            tuple(inventory.errors), inventory.truncated,
            tuple((r.path, r.key, r.line, r.severity) for r in inventory.secret_risks))


def _refresh_inventory(bundle_dir: Path, source: Path, *, commit: str,
                       generated_at: str) -> tuple[Inventory, bool]:
    """The inventory of `source` now — written into the bundle only when its shape changed, and
    the one already there otherwise, so an unchanged tree leaves the bundle byte-identical."""
    # THE BUNDLE IS NOT THE REPOSITORY: the refresh stages it INSIDE the checkout it renews.
    fresh = take_inventory(source, commit=commit, generated_at=generated_at, exclude=bundle_dir)
    old = read_inventory(bundle_dir)
    if old is not None and _shape(old) == _shape(fresh):
        return old, False
    write_inventory(bundle_dir, fresh)
    return fresh, True


def _coverage_rows(previous: list[CoverageRow], concepts: list[Concept],
                   inventory: Inventory) -> list[CoverageRow]:
    """The coverage table re-derived from what is on disk now. The module row stays as the
    backfill wrote it (it needs the survey the backfill had); the type rows and the per-kind rows
    are recomputed, so a rewritten concept and a changed tree both move the numbers."""
    rows = [r for r in previous if r.kind == "module"]
    by_type: dict[str, int] = {}
    for concept in concepts:
        by_type[concept.type] = by_type.get(concept.type, 0) + 1
    rows += [CoverageRow(kind=kind, inventoried=count, concepts=count)
             for kind, count in sorted(by_type.items())]
    rows += coverage_by_kind(inventory, concepts)
    return rows


def _manifest_for(bundle_dir: Path, inventory: Inventory, concepts: list[Concept], *,
                  commit: str, generated_at: str, new_gaps: list[Gap] | None = None,
                  stale_gaps: list[Gap] | None = None) -> OkfManifest:
    """The manifest this round publishes: the previous one's gaps minus what is re-derived here
    (`stale`, and every inventory gap — a risk that was fixed leaves rather than accumulating
    beside its successor), plus this round's; the coverage table from the tree and the concepts
    as they are now."""
    manifest = read_manifest(bundle_dir) or OkfManifest(bundle_kind="source-repo",
                                                        scope_limit=SCOPE_LIMIT)
    kept = [g for g in manifest.gaps if g.kind != STALE_GAP and g.kind not in INVENTORY_GAP_KINDS]
    gaps = kept + list(new_gaps or []) + list(stale_gaps or []) + inventory_gaps(inventory)
    return manifest.model_copy(update={
        "source_commit": commit, "generated_at": generated_at, "gaps": gaps,
        "coverage": _coverage_rows(manifest.coverage, concepts, inventory)})


def _broken_paths(broken: list[ConceptCheck]) -> list[str]:
    out: list[str] = []
    for concept in broken:
        for src in concept.sources:
            if src.verdict != FRESH and src.path not in out:
                out.append(src.path)
    return out


def _first_broken_path(concept: ConceptCheck) -> str:
    return next((s.path for s in concept.sources if s.verdict != FRESH), "")
