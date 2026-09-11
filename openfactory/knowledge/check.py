"""The checker: re-derives what a published concept claims about its sources, and says which of
those claims no longer hold.

WHY THIS EXISTS — measured 2026-09-04 and recorded in ADR-0045. `ConceptSource.fingerprint` had two
writers (`onboarding/concepts.py`) and ZERO readers, while `okf.py::render_concept`'s own docstring
already named *"the checker that invalidates it reads the fingerprints"*. The promise at the centre
of the OKF — the bytes move, the fingerprint moves, the concept is stale with nobody in the loop —
was design intent with no mechanism behind it. Nothing re-verified a published bundle, so a concept
whose source was rewritten last month read as current to every role that opened it.

WHAT IT CHECKS, AND WHAT IT DELIBERATELY DOES NOT. A concept's `sources` are EARNED, not declared:
`_verified_rules` builds them from the citations that survived `_Anchorer` at authoring time, so
they name exactly the files the concept's claims were read from. Each is re-derived against a
checkout with the one test that is exact: the file is there or it is not, and its bytes hash to the
recorded fingerprint or they do not. The hash is `bundle.py`'s own — the same function that wrote
the fingerprint — so the two cannot drift. It does NOT re-parse the prose for `path:line`
citations: `parse_concept` reads only the frontmatter on purpose (the body is the human half), and
every file a citation was read from is already in `sources`.

A VERDICT PER SOURCE, THE WORST ONE PER CONCEPT, AND NEVER AN EXCEPTION. A concept with one fresh
source and one stale one is stale — a claim is as good as its weakest support. A bundle written
before fingerprints existed is `unverifiable`, which is reported and is NOT `fresh`: the absence of
a measurement is not a measurement. And like everything under `knowledge/`, this answers at the
caller and never raises: a checker that takes the tech-lead's answer down with it has not checked
anything.

WHAT A READER DOES WITH THE VERDICT IS THE READER'S, and the two readers differ on purpose. The
module map is dropped whole when stale (`staleness.is_trustworthy`), because it is regenerated in
0.24s. A concept cost a model call under a budget the project declared, and a stale one is still
history worth opening — so the tech-lead keeps the bundle in its pack and NAMES the stale concepts
as a gap, rather than losing forty concepts to one moved file.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import NamedTuple

from openfactory.knowledge.bundle import _sha256
from openfactory.knowledge.okf import read_concepts

_log = logging.getLogger("openfactory.knowledge.check")

#: The verdicts, in order of SEVERITY — a concept's verdict is the worst of its sources'. `fresh`
#: is the only one that means "verified and holds"; `unverifiable` and `unsourced` mean the check
#: could not be made, which is a different fact from either outcome.
FRESH = "fresh"
UNSOURCED = "unsourced"        # the concept names no source at all — nothing to check
UNVERIFIABLE = "unverifiable"  # a source with no fingerprint recorded — an older bundle
STALE = "stale"                # the file is there and its bytes are not what the concept read
MISSING = "missing"            # the file is gone from this checkout

_SEVERITY = {FRESH: 0, UNSOURCED: 1, UNVERIFIABLE: 2, STALE: 3, MISSING: 4}


class SourceCheck(NamedTuple):
    """One source of one concept, re-derived."""

    path: str
    verdict: str
    detail: str = ""


class ConceptCheck(NamedTuple):
    """One concept, with the worst of its sources as its own verdict."""

    title: str
    type: str
    verdict: str
    sources: tuple[SourceCheck, ...]

    @property
    def broken(self) -> bool:
        """Stale or missing — the claims this concept makes are no longer supported by this tree."""
        return self.verdict in (STALE, MISSING)


class CheckReport(NamedTuple):
    """Every concept in a bundle, checked against one checkout."""

    concepts: tuple[ConceptCheck, ...]

    def count(self, verdict: str) -> int:
        return sum(1 for c in self.concepts if c.verdict == verdict)

    @property
    def broken(self) -> tuple[ConceptCheck, ...]:
        return tuple(c for c in self.concepts if c.broken)

    @property
    def holds(self) -> bool:
        """No concept is stale or missing. An `unverifiable` concept does not fail the bundle —
        it is reported, and it is never counted as fresh. An EMPTY bundle holds vacuously and says
        so in `summary()`; a caller that needs "verified" rather than "not contradicted" reads
        `count(FRESH)`."""
        return not self.broken

    def summary(self) -> str:
        """One line a person can read, and a log line can carry."""
        n = len(self.concepts)
        if n == 0:
            return "0 concepts checked"
        parts = [f"{self.count(v)} {v}" for v in (FRESH, STALE, MISSING, UNVERIFIABLE, UNSOURCED)
                 if self.count(v)]
        return f"{n} concepts checked: " + ", ".join(parts)


def check_concepts(bundle_dir: Path, repo: Path) -> CheckReport:
    """Re-derive every concept in `bundle_dir` against the checkout at `repo`.

    `bundle_dir` is the directory holding `concepts/` — the one `fetch_bundle` returns and
    `write_okf` writes into. Unreadable concept files are skipped by `read_concepts`, for the
    reason it gives; an unreadable SOURCE here is `missing`, because to this checkout it is.
    """
    root = Path(repo).expanduser().resolve()
    out: list[ConceptCheck] = []
    try:
        concepts = read_concepts(Path(bundle_dir))
    except Exception as exc:  # noqa: BLE001 — the bundle cost the bundle, never the caller
        _log.warning("knowledge: could not read the bundle at %s for checking (%s)",
                     bundle_dir, exc)
        return CheckReport(())
    for concept in concepts:
        checks = tuple(_check_source(root, s.path, s.fingerprint) for s in concept.sources)
        verdict = max((c.verdict for c in checks), key=_SEVERITY.__getitem__, default=UNSOURCED)
        out.append(ConceptCheck(title=concept.title, type=concept.type, verdict=verdict,
                                sources=checks))
    return CheckReport(tuple(out))


def _check_source(root: Path, rel: str, fingerprint: str) -> SourceCheck:
    """One file against one recorded fingerprint. Exact, and never raises."""
    path = root / rel
    if path.is_dir():
        # A MODULE'S DIRECTORY, NOT A FILE. `propose_concepts` falls back to the module path when
        # no citation survived, so this concept carries no verified line to hash. That is a fact
        # about the authoring, not about the tree — reported as unverifiable, never as missing:
        # called missing it would be "broken" on every refresh and re-authored, paid for, forever
        # (found by the renewal's own guard, 2026-09-04).
        return SourceCheck(rel, UNVERIFIABLE, "a directory — no verified citation to hash")
    try:
        data = path.read_bytes()
    except OSError:
        return SourceCheck(rel, MISSING, "not in this checkout")
    if not fingerprint:
        return SourceCheck(rel, UNVERIFIABLE, "no fingerprint was recorded when this was written")
    actual = _sha256(data)
    if actual != fingerprint:
        return SourceCheck(rel, STALE,
                           f"bytes moved: recorded {fingerprint[:12]}…, now {actual[:12]}…")
    return SourceCheck(rel, FRESH)


def stale_bundle_gap(report: CheckReport) -> str:
    """The sentence a pack's gaps section carries when the bundle no longer matches the checkout.

    NAMES THE CONCEPTS, because "some concepts are stale" sends a reader to open all forty to find
    the three. Capped, because a bundle where every concept moved is one sentence, not a list."""
    broken = report.broken
    if not broken:
        return ""
    titles = ", ".join(f"'{c.title}'" for c in broken[:6])
    more = f" and {len(broken) - 6} more" if len(broken) > 6 else ""
    return (f"{len(broken)} of {len(report.concepts)} concepts in the knowledge bundle no longer "
            f"match this checkout ({report.count(STALE)} stale, {report.count(MISSING)} missing): "
            f"{titles}{more} — read those as history, not as what the code does today")
