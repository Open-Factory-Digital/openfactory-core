"""The OKF on disk: concepts as files a role can open, and a manifest that admits what is missing.

WHY FILES AND NOT ONE INJECTED BLOB, which is the decision this module turns on. `render.py` caps
the module map at 8,000 characters and sheds detail to fit — measured on this repository, only the
barest level survives, so the agent receives `path`, `purpose` and an anchor and never learns a
dependency. That is the right answer for a NAVIGATION AID and the wrong one for knowledge: a
concept truncated in the middle is worse than a concept nobody opened, because the model cannot
tell which happened.

`techlead/pack.py` already solved this exact problem for the tech-lead's facts, and its reasoning
transfers whole: *"The caps are logged when they bite and INVISIBLE to the model, so it answered
thin and confident about a floor it had been shown a truncation of."* Its answer — write the facts
as FILES, hand over an index, and let the role open what its question needs — works on all four
harnesses today with no new flag, because every one of them ships a read-only file tool. So the
OKF is written the same way: `concepts/<type>/<slug>.md`, one fact per file, plus a manifest that
names what is NOT there.

WHAT THIS MODULE WILL NOT DO. It never invents a fact and never edits one: it renders what
`onboarding/context.py` produced and verified, and reads it back. The verification lives there
(`_Anchorer`, which checks every `file:line` against the working tree and demotes a claim that
loses all of its citations into a question) precisely so that a claim reaching this module is
already anchored. A renderer that could also author would be a second place for an unverified
sentence to enter the bundle.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from openfactory.knowledge.contracts import (
    BusinessRule,
    Concept,
    ConceptSource,
    CoverageRow,
    Gap,
    OkfManifest,
)

#: The bundle's own directory name, and the manifest inside it. `.okf/` rather than `knowledge/`
#: so the name cannot collide with a client directory called `knowledge` — which
#: `onboarding/onboard.py` already has to detect and step around.
OKF_DIRNAME = ".okf"
CONCEPTS_DIRNAME = "concepts"
OKF_MANIFEST_FILE = "manifest.yaml"
OKF_INDEX_FILE = "index.md"

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


def _dump(data: object) -> str:
    """Deterministic YAML — the same contract `bundle.py::_dump` states: keys sorted, block style,
    no aliases, unicode preserved, so one repository state serializes to identical bytes."""
    return yaml.safe_dump(data, sort_keys=True, default_flow_style=False, allow_unicode=True)


def slug(title: str) -> str:
    """A filename from a title, stable and collision-visible.

    Lowercase, non-alphanumerics collapsed to single hyphens, trimmed. `""` becomes `"untitled"`
    rather than an empty filename — a concept with no title is a defect upstream, and writing
    `.md` with nothing before the dot would hide it as a filesystem oddity instead.
    """
    out = re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-")
    return out or "untitled"


def concept_path(concept: Concept) -> Path:
    """`concepts/<type>/<slug>.md`. The TYPE is a directory, which is what makes an open taxonomy
    survive contact with a filesystem: a client's own kind needs no registration anywhere, it just
    becomes a folder.

    NOT UNIQUE ON ITS OWN — see `assign_paths`, which is what the writer uses. Two modules can
    honestly produce the same title (`Configuration`, `API routes`), and a filename derived from
    the title alone would let the second silently overwrite the first: a concept would vanish and
    the bundle would still read as complete. Measured on the first end-to-end run of this module.
    """
    return Path(CONCEPTS_DIRNAME) / slug(concept.type) / f"{slug(concept.title)}.md"


def assign_paths(concepts: list[Concept]) -> list[tuple[Concept, Path]]:
    """Every concept with the path it will actually occupy — unique, deterministic, and never
    silently merged.

    A COLLISION IS DISAMBIGUATED, NEVER DROPPED. Two concepts of one type sharing a title keep
    both files: the second becomes `<slug>-2.md`. Ordered by (type, title) first so the same
    bundle always assigns the same names — a suffix that moved between runs would make every diff
    unreadable and would silently relabel a human's earlier file.
    """
    out: list[tuple[Concept, Path]] = []
    taken: set[str] = set()
    for concept in sorted(concepts, key=lambda c: (c.type, c.title)):
        base = concept_path(concept)
        candidate, n = base, 1
        while candidate.as_posix() in taken:
            n += 1
            candidate = base.with_name(f"{base.stem}-{n}{base.suffix}")
        taken.add(candidate.as_posix())
        out.append((concept, candidate))
    return out


def render_concept(concept: Concept) -> str:
    """One concept as YAML frontmatter plus prose.

    THE FRONTMATTER IS FOR MACHINES AND THE BODY IS FOR PEOPLE, and both are in one file on
    purpose: a role that opens this reads the prose, and the checker that invalidates it reads the
    fingerprints, and neither can drift from the other because there is only one artifact.
    """
    head: dict[str, object] = {
        "type": concept.type,
        "title": concept.title,
        "status": concept.status,
    }
    if concept.description:
        head["description"] = concept.description
    generated = {k: v for k, v in (("by", concept.generated_by), ("at", concept.generated_at)) if v}
    if generated:
        head["generated"] = generated
    if concept.sources:
        head["sources"] = [
            {k: v for k, v in s.model_dump().items() if v} for s in concept.sources
        ]

    lines = ["---", _dump(head).rstrip(), "---", "", f"# {concept.title}", ""]
    if concept.what_it_does:
        lines += ["## What it does", "", concept.what_it_does, ""]
    if concept.behaviour:
        lines += ["## Behaviour", "", *[f"- {b}" for b in concept.behaviour], ""]
    if concept.business_rules:
        lines += ["## Business rules", ""]
        for rule in concept.business_rules:
            cites = f" ({', '.join(f'`{c}`' for c in rule.cites)})" if rule.cites else ""
            lines.append(f"- {rule.text}{cites}")
        lines.append("")
    for heading, items in (("Depends on", concept.depends_on),
                           ("Consumed by", concept.consumed_by),
                           ("Gaps and caveats", concept.caveats)):
        if items:
            lines += [f"## {heading}", "", *[f"- {i}" for i in items], ""]
    return "\n".join(lines).rstrip() + "\n"


def parse_concept(text: str) -> Concept | None:
    """Read a concept file back. `None` when the file carries no frontmatter at all.

    READING BACK IS NOT A CONVENIENCE — it is what lets a later pass know which concepts already
    exist, so a refresh can leave a human's edits alone instead of overwriting the file every
    time. Only the frontmatter is parsed: the body is the human half, and a renderer that tried to
    round-trip prose would start owning wording it did not write.
    """
    match = _FRONTMATTER.match(text)
    if match is None:
        return None
    try:
        head = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(head, dict):
        return None
    generated = head.get("generated") or {}
    return Concept(
        type=str(head.get("type") or ""),
        title=str(head.get("title") or ""),
        description=str(head.get("description") or ""),
        status=str(head.get("status") or "draft"),
        generated_by=str(generated.get("by") or "") if isinstance(generated, dict) else "",
        generated_at=str(generated.get("at") or "") if isinstance(generated, dict) else "",
        sources=[ConceptSource(**s) for s in (head.get("sources") or [])
                 if isinstance(s, dict) and s.get("path")],
    )


def render_manifest(manifest: OkfManifest) -> str:
    """The bundle's account of itself, as YAML.

    COVERAGE AND GAPS ARE WRITTEN EVEN WHEN EMPTY, and that is deliberate. An absent `gaps:` key
    reads as "nothing was missing"; an empty list reads as "this pass looked and found none". The
    three-state discipline `BundleManifest` already keeps for its own blindness counters
    (never-surveyed / surveyed-clean / blind) is the same distinction, one artifact along.
    """
    data: dict[str, object] = {
        "okf_version": manifest.okf_version,
        "bundle_kind": manifest.bundle_kind,
        "coverage": [row.model_dump() for row in manifest.coverage],
        "gaps": [gap.model_dump(exclude_defaults=False) for gap in manifest.gaps],
    }
    for key, value in (("generated_at", manifest.generated_at),
                       ("source_commit", manifest.source_commit),
                       ("scope_limit", manifest.scope_limit)):
        if value:
            data[key] = value
    return _dump(data)


def write_okf(root: Path, *, manifest: OkfManifest, concepts: list[Concept]) -> list[Path]:
    """Write the bundle under `root/.okf/`. Returns every path written, sorted.

    NEVER DELETES. A concept this pass did not produce is left exactly where it is — it may be a
    human's, or an earlier pass's about code this run could not reach, and a refresh that prunes
    what it cannot currently see would turn one bad run into data loss. Removing a concept is a
    decision, and a decision belongs in a diff somebody reads.
    """
    okf = Path(root) / OKF_DIRNAME
    okf.mkdir(parents=True, exist_ok=True)
    written = [okf / OKF_MANIFEST_FILE]
    (okf / OKF_MANIFEST_FILE).write_text(render_manifest(manifest), encoding="utf-8")
    for concept, relative in assign_paths(concepts):
        path = okf / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_concept(concept), encoding="utf-8")
        written.append(path)
    return sorted(written)


def read_concepts(root: Path) -> list[Concept]:
    """Every concept already in the bundle, sorted by type then title. Unreadable files are
    SKIPPED rather than raising: one hand-edited file with broken frontmatter must not make the
    whole bundle unreadable to the role that needs the other forty."""
    okf = Path(root) / OKF_DIRNAME / CONCEPTS_DIRNAME
    out: list[Concept] = []
    if not okf.is_dir():
        return out
    for path in sorted(okf.rglob("*.md")):
        try:
            parsed = parse_concept(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if parsed is not None:
            out.append(parsed)
    return sorted(out, key=lambda c: (c.type, c.title))


def render_index(manifest: OkfManifest, concepts: list[Concept]) -> str:
    """The front door: what is here, and — first — what is NOT.

    THE GAPS COME BEFORE THE CONTENTS, and the order is the argument. A reader who scrolls a list
    of forty concepts and never reaches a "what we could not establish" section at the bottom has
    been told, by the layout, that the bundle is complete. `techlead/pack.py`'s manifest makes the
    same choice for the same reason — it names every fact it could not gather, with the reason,
    beside the ones it could.
    """
    lines = ["# Knowledge bundle", ""]
    if manifest.scope_limit:
        lines += ["> " + manifest.scope_limit.strip().replace("\n", "\n> "), ""]
    lines += ["## What this bundle could not establish", ""]
    if manifest.gaps:
        for gap in manifest.gaps:
            where = f"`{gap.path}` — " if gap.path else ""
            lines.append(f"- **{gap.kind}** — {where}{gap.detail}")
    else:
        lines.append("- Nothing was recorded as missing by the pass that wrote this.")
    lines.append("")

    lines += ["## Concepts", ""]
    if not concepts:
        lines += ["- None yet.", ""]
    else:
        # THE SAME ASSIGNMENT THE WRITER USES, not a second derivation of it. Rendering the index
        # from `concept_path` alone produced two entries pointing at one file the moment two
        # concepts shared a title — a link that lies about which fact it opens.
        placed = assign_paths(concepts)
        for kind in sorted({c.type for c in concepts}):
            lines += [f"### {kind}", ""]
            for concept, where in [(c, p) for c, p in placed if c.type == kind]:
                summary = f" — {concept.description}" if concept.description else ""
                lines.append(f"- [{concept.title}]({where.as_posix()}){summary}")
            lines.append("")

    if manifest.coverage:
        lines += ["## Coverage", "",
                  "| kind | inventoried | concepts | why not |", "|---|---:|---:|---|"]
        for row in manifest.coverage:
            lines.append(f"| {row.kind} | {row.inventoried} | {row.concepts} | {row.reason} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "CONCEPTS_DIRNAME",
    "OKF_DIRNAME",
    "OKF_INDEX_FILE",
    "OKF_MANIFEST_FILE",
    "BusinessRule",
    "CoverageRow",
    "Gap",
    "assign_paths",
    "concept_path",
    "parse_concept",
    "read_concepts",
    "render_concept",
    "render_index",
    "render_manifest",
    "slug",
    "write_okf",
]
