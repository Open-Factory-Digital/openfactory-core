"""The reading of an intake, bounded by what can be checked (#33 slice 7, holes 5 and 6).

TELLING A BUG FROM "WORKING AS DESIGNED" REQUIRES KNOWING WHAT THE CODE DOES — the knowledge bundle
— and telling a wish from a promise requires the requirements. The model reads the message and
says which it saw, and names what it relied on (`[[EVIDENCIA]]`, `[[USO]]`). This module is the
half a model cannot do: it CHECKS that evidence — is the cited concept in the bundle, is it still
fresh (the renewal records a `stale` gap when its bytes moved), does the cited requirement exist —
and bounds the confidence a person is shown by the answer. A reading that relied on nothing, or on
a bundle that does not exist, is `baixa` however sure the model sounded; one that relied on a
stale concept is `média`; only one whose evidence stands is `alta`.

WHY THE BOUND IS MECHANICAL. The confidence is what a person decides on — whether to argue with
the role, file the defect anyway, or accept "it works like this". A confidence the model assigned
itself would be the same guess dressed as a measurement.
"""

from __future__ import annotations

import logging
from pathlib import Path

from openfactory.product.role import Reading

log = logging.getLogger("openfactory.product.reading")

ALTA = "alta"
MEDIA = "média"
BAIXA = "baixa"
STALE_GAP = "stale"


def _concepts_in(bundle_dir: Path) -> tuple[list, list]:
    from openfactory.knowledge.okf import read_concepts, read_manifest
    concepts = read_concepts(bundle_dir)
    manifest = read_manifest(bundle_dir)
    stale = [g for g in (manifest.gaps if manifest else []) if g.kind == STALE_GAP]
    return concepts, stale


def _find(cited: str, concepts: list) -> object | None:
    """A cited concept by file (any suffix of the path the writer gives it) or by title."""
    from openfactory.knowledge.okf import concept_path
    wanted = cited.strip().strip("`").lower()
    for concept in concepts:
        path = concept_path(concept).as_posix().lower()
        if wanted == path or path.endswith("/" + wanted) or wanted.endswith(path):
            return concept
    for concept in concepts:
        if concept.title.strip().lower() == wanted:
            return concept
    return None


def _is_stale(concept, stale_gaps: list) -> bool:
    title = f"'{concept.title}'"
    paths = {s.path for s in concept.sources}
    return any(title in g.detail or (g.path and g.path in paths) for g in stale_gaps)


def bound(reading: Reading, *, bundle_dir: Path | None, corpus) -> Reading:
    """The reading with its confidence set by what its evidence checks out against."""
    verified: dict = {"concepts": {}, "requirements": {}}
    reasons: list[str] = []
    level = ALTA
    if bundle_dir is None:
        level = BAIXA
        reasons.append("no knowledge bundle is published for this project — nothing the reading "
                       "says about what the code does can be checked")
    elif not reading.concepts:
        level = BAIXA
        reasons.append("the reading cites no concept — nothing about what the code does was "
                       "checked")
    else:
        try:
            concepts, stale = _concepts_in(bundle_dir)
        except Exception as exc:  # noqa: BLE001 — an unreadable bundle bounds the reading, never the reply
            log.info("could not read the bundle at %s (%s)", bundle_dir, exc)
            concepts, stale = [], []
            reasons.append("the knowledge bundle could not be read")
            level = BAIXA
        for cited in reading.concepts:
            found = _find(cited, concepts)
            if found is None:
                verified["concepts"][cited] = "missing"
                level = BAIXA
                reasons.append(f"`{cited}` is not in the bundle")
            elif _is_stale(found, stale):
                verified["concepts"][cited] = "stale"
                if level == ALTA:
                    level = MEDIA
                reasons.append(f"`{cited}` describes bytes that have since moved")
            else:
                verified["concepts"][cited] = "fresh"
    for number in reading.requirements:
        exists = False
        try:
            exists = corpus is not None and corpus.by_number(number) is not None
        except Exception:  # noqa: BLE001 — an unreadable corpus is an absent requirement, said below
            log.info("could not look up REQ-%s", number, exc_info=True)
        verified["requirements"][number] = exists
        if not exists:
            if level == ALTA:
                level = MEDIA
            reasons.append(f"REQ-{number} is not in the requirements")
    return reading.model_copy(update={"confidence": level, "bounded_by": "; ".join(reasons),
                                      "verified": verified})


def render_reading(reading: Reading, *, language: str | None = None) -> str:
    """One line for a case, a row, a log: the kind, the confidence, what it stood on."""
    kinds = {"defect": ("problema", "defect"), "request": ("pedido", "request"),
             "misuse": ("funciona assim", "working as designed"),
             "question": ("pergunta", "question")}
    pt = (language or "pt-BR").lower().startswith("pt")
    kind = kinds.get(reading.kind, (reading.kind, reading.kind))[0 if pt else 1]
    parts = [f"{'leitura' if pt else 'reading'}: {kind}"]
    if reading.confidence:
        parts.append(f"{'confiança' if pt else 'confidence'} {reading.confidence}")
    stood = [f"{c} ({reading.verified.get('concepts', {}).get(c, '?')})" for c in reading.concepts]
    stood += [f"REQ-{n}" + ("" if reading.verified.get("requirements", {}).get(n) else " (?)")
              for n in reading.requirements]
    if stood:
        parts.append(", ".join(stood))
    line = " · ".join(parts)
    if reading.bounded_by:
        line += f" — {reading.bounded_by}"
    return line


__all__ = ["ALTA", "BAIXA", "MEDIA", "bound", "render_reading"]
