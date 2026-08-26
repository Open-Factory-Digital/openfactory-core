"""Render the module map into agent-context text (the injection payload).

This plays the exact role the hand-written index played in the proof of concept:
a compact "where things live" map the coding agent reads to jump to the right code instead of
hunting for it. The rendered header states the GROUND-TRUTH rule (§7) explicitly — use the map
to locate, then open and verify the real files — so the map accelerates navigation without ever
substituting for reading the code.

Deterministic and size-capped: the same bundle renders identical text, bounded so a large repo's
map cannot blow the prompt budget.
"""

from __future__ import annotations

from openfactory.knowledge.contracts import KnowledgeBundle

_MAX_CHARS = 8000  # mirror context.py's per-doc cap — a signpost, not the whole repo

_HEADER = (
    "This is a GENERATED module map of the repository — a navigation aid, not the source of "
    "truth. Use it to locate the right code FAST, then OPEN and VERIFY the real files before "
    "you rely on or change anything (the code is ground truth; this map can lag it). Each entry "
    "links to the source file it was generated from.\n"
    "Generated from commit {commit}.\n"
)


def _entry(m, *, detail: int) -> list[str]:
    """One module's lines at a given detail level. Level 3 is everything; each step down drops
    the widest field first, so what degrades is DEPTH, never coverage."""
    out = [f"### {m.path or m.name}"]
    if m.purpose:
        out.append(f"purpose: {m.purpose}")
    if detail >= 2 and m.key_files:
        # say so when the list is capped — an under-reported module must not read as a
        # complete one (the agent would conclude files it needs don't exist).
        more = m.file_count - len(m.key_files)
        extra = f" (+{more} more not listed)" if more > 0 else ""
        out.append("key files: " + ", ".join(m.key_files) + extra)
    if detail >= 3 and m.public_surface:
        out.append("public: " + ", ".join(m.public_surface))
    if detail >= 1 and m.dependencies:
        out.append("depends on: " + ", ".join(m.dependencies))
    out.append(f"source: {m.source.file}")
    out.append("")
    return out


def render_module_map(bundle: KnowledgeBundle) -> str:
    """A compact, deterministic text rendering of the module map for prompt injection.
    Empty string if the map has no modules (nothing useful to inject).

    Fitting the budget DEGRADES DETAIL, never coverage. Truncating the concatenated text (the
    obvious approach) drops whole modules from the alphabetical tail — on a repo of any size the
    agent silently gets a map that omits a third of the codebase, always the same third, and
    concludes those areas don't exist. That is worse than no map (§12), and it would quietly
    bias the very cost measurement Phase 1 exists to produce. So we shed the widest fields
    first (public surface → key files → dependencies) and keep every module's path, purpose and
    source link. Only if the barest form still overflows do we drop modules — and then we say
    exactly how many, so the omission is visible rather than assumed away."""
    modules = bundle.module_map.modules
    if not modules:
        return ""
    commit = (bundle.module_map.source_commit or "unknown")[:12]
    header = _HEADER.format(commit=commit)

    for detail in (3, 2, 1, 0):
        lines = [header]
        for m in modules:
            lines += _entry(m, detail=detail)
        text = "\n".join(lines).rstrip() + "\n"
        if len(text) <= _MAX_CHARS:
            return text

    # Even the barest entries overflow: keep as many WHOLE modules as fit and declare the rest.
    kept: list[str] = [header]
    shown = 0
    for m in modules:
        entry = _entry(m, detail=0)
        if len("\n".join(kept + entry)) + 80 > _MAX_CHARS:  # 80 = room for the omission note
            break
        kept += entry
        shown += 1
    omitted = len(modules) - shown
    kept.append(f"… ({omitted} more module(s) omitted for size — search the code for those)")
    return "\n".join(kept).rstrip() + "\n"
