"""What can be done to a recorded gap after it was recorded: merged with the next round's, and
answered.

WHY THIS FILE EXISTS. The slice-2 design critique (2026-09-06) traced what would happen to an
`open-question` a person had answered on a card: nothing. `Gap` had no identity and no state;
`renew._manifest_for` kept every gap that was not stale; `cover_paths` appended the new round's
gaps to the old ones without looking; the concept pass minted one question per caveat, in fresh
wording each time. So a pass that asked, got its answer and wrote it into the product's context
would, on its next run, re-judge the same file, re-author the same module, and ask the same
question again — the gather could never terminate, and the person would learn to ignore it.

The two operations here are the MECHANICAL half of the remedy, and this docstring used to claim
the whole of it (the review of #73). `merge_gaps` keeps the record and adds only what is NEW
by key, so the answered question is never shadowed by its own re-derivation; `retire` marks a
question answered and keeps it, because a record that deleted what it finished could not tell
the next reader "nobody asked" from "somebody answered" — the same rule every ledger in this
codebase keeps ("anonymise, never delete").

WHAT THE KEY CATCHES IS THE SAME QUESTION IN THE SAME WORDS — case, spacing and trailing
punctuation folded (`contracts.gap_key`), and nothing more: "Was the 5 percent cap deliberate?"
is a new key beside "Is the 5% cap intentional?". The paraphrase — the case the paragraph above
actually describes, a model re-raising the same caveat in fresh wording — is ASKED away, not
enforced: the concept pass is handed the answered questions ("ALREADY ANSWERED",
`concepts._already_answered`) and told not to raise them again in other words. That is a prompt,
and a prompt is the only instrument there is for a paraphrase; the termination this file promises
rests on the model obeying it. Written down so the next reader does not credit the key with work
it does not do.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from openfactory.knowledge.contracts import ANSWERED, Gap, OkfManifest

log = logging.getLogger("openfactory.knowledge.gaps")


def merge_gaps(existing: Iterable[Gap], new: Iterable[Gap]) -> list[Gap]:
    """The record first, then only what the new round found that the record does not hold.

    BY KEY, NOT BY TEXT: a gap's key folds case and spacing, so the same caveat re-typed is the
    same gap and lands once. An answered question in `existing` therefore survives its own
    re-derivation in `new`, still answered — which is what lets the gate stop naming it for good
    rather than until the next backfill."""
    out: list[Gap] = []
    seen: set[str] = set()
    for gap in list(existing) + list(new):
        if gap.key in seen:
            continue
        seen.add(gap.key)
        out.append(gap)
    return out


def answered_gaps(manifest: OkfManifest | None) -> list[Gap]:
    """The questions somebody already answered — what the next authoring must be told."""
    return [g for g in (manifest.gaps if manifest else []) if g.status == ANSWERED]


def about(gaps: Iterable[Gap], path: str) -> list[Gap]:
    """The gaps recorded on `path`, on a directory above it, or on a file beneath it — the
    module's questions when `path` is a module, the module's when `path` is one of its files.
    The gate's prefix rule (`gate._gaps_about`), read in both directions."""
    where = str(path).strip().strip("/")
    out: list[Gap] = []
    for gap in gaps:
        there = (gap.path or "").strip().strip("/")
        if not where or not there:
            continue
        if there == where or where.startswith(there + "/") or there.startswith(where + "/"):
            out.append(gap)
    return out


def retire(manifest: OkfManifest, key: str, *, answer: str, by: str, at: str) -> OkfManifest:
    """The manifest with the gap `key` marked answered — kept, with the answer beside the
    question. A key nothing holds returns the manifest unchanged: the caller reads `answered`
    back to know whether anything happened, and a retirement that raised on a stale key would
    make a person's answer cost the sweep that carried it."""
    wanted = (key or "").strip()
    if not wanted:
        return manifest
    gaps = [
        gap.model_copy(update={"status": ANSWERED, "answer": (answer or "").strip(),
                               "answered_by": (by or "").strip(), "answered_at": at or ""})
        if gap.key == wanted else gap
        for gap in manifest.gaps
    ]
    return manifest.model_copy(update={"gaps": gaps})


def retire_in_bundle(bundle_dir: Path, key: str, *, answer: str, by: str, at: str) -> bool:
    """Retire `key` in the published bundle at `bundle_dir` — the manifest rewritten, the front
    door re-rendered — and say whether the key was there. Writes nothing when it was not."""
    from openfactory.knowledge.okf import (
        OKF_INDEX_FILE,
        read_concepts,
        read_manifest,
        render_index,
        write_okf,
    )

    bundle = Path(bundle_dir)
    manifest = read_manifest(bundle)
    if manifest is None or not any(g.key == key for g in manifest.gaps):
        log.info("OPENFACTORY_GAP_NOT_FOUND key=%s bundle=%s", key, bundle)
        return False
    retired = retire(manifest, key, answer=answer, by=by, at=at)
    write_okf(bundle, manifest=retired, concepts=[])
    (bundle / OKF_INDEX_FILE).write_text(render_index(retired, read_concepts(bundle)),
                                         encoding="utf-8")
    return True


__all__ = ["about", "answered_gaps", "merge_gaps", "retire", "retire_in_bundle"]
