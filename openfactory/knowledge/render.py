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

#: Bounds on the coverage sentence. It travels in the header, so it is paid for on every injection
#: and before any module — small on purpose. The counts are never capped; only the lists are.
_MAX_UNREAD_SUFFIXES = 8
_MAX_UNREADABLE_PATHS = 5


def _coverage(manifest) -> str:
    """What this map does NOT cover, in one paragraph — or the fact that nobody measured it.

    WHY THIS IS IN THE HEADER AND NOT A SECTION. Every other line of the rendering can be shed:
    detail levels drop fields, and the last resort drops whole modules. This one must survive all
    of that, because it is the line that stops the rest being read as complete. A coverage note
    that disappears exactly when the map gets thin is worse than none — that is when it matters.

    THE BUNDLE HAS COMPUTED THIS SINCE IT WAS FIRST WRITTEN AND NEVER SAID IT. `files_unread`,
    `unread_extensions` and `unreadable_paths` are surveyed, checksummed into the bundle's derived
    key, and published to the knowledge branch, and no reader ever saw them: `render_module_map`
    emitted the header and the module entries and nothing else. So an agent handed a map of 688
    files out of 799 had no way to learn that 111 existed — while the same function's docstring
    argues that an omission must be visible rather than assumed away. Measured on this repository:
    38 modules, 688 read, 111 unread, and not one word about the 111 (2026-08-29).

    The three states are the manifest's own, and they are kept apart here: `None` = never
    surveyed (an older bundle, and the reader is told it cannot tell), `[]` = surveyed and clean,
    non-empty = the parts this map is silent about."""
    unread = manifest.unread_extensions
    unreadable = manifest.unreadable_paths
    if unread is None and unreadable is None and manifest.files_unread is None:
        # NOT "this map is complete". An older bundle never measured its coverage, and saying
        # nothing here is exactly how that becomes a claim of completeness.
        return ("COVERAGE: this bundle predates coverage measurement, so how much of the "
                "repository the map below describes is UNKNOWN. An area missing from it is not "
                "evidence that the area does not exist.\n")

    out: list[str] = []
    read, missed = manifest.files_read, manifest.files_unread
    if read is not None and missed is not None:
        out.append(f"COVERAGE: built from {read} source file(s); {missed} more were walked and "
                   f"NOT read.")
    else:
        out.append("COVERAGE:")

    if unread:
        shown = unread[:_MAX_UNREAD_SUFFIXES]
        names = ", ".join(f"{u.suffix or '(no extension)'} ×{u.files}" for u in shown)
        rest = len(unread) - len(shown)
        out.append(f"This map cannot read {names}{f' and {rest} more kind(s)' if rest else ''} — "
                   f"code in those files EXISTS and is not described below.")
    if unreadable:
        shown_paths = unreadable[:_MAX_UNREADABLE_PATHS]
        rest = len(unreadable) - len(shown_paths)
        out.append("Directories it could not open: " + ", ".join(shown_paths)
                   + (f" and {rest} more" if rest else "") + ".")
    if not unread and not unreadable and unread is not None and unreadable is not None:
        out.append("Every file walked was read and every directory opened.")
    return " ".join(out) + "\n"


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
    exactly how many, so the omission is visible rather than assumed away.

    THE HEADER ALSO CARRIES WHAT THE MAP DOES NOT COVER (`_coverage`), before any module and after
    every degradation, because the thinner this rendering gets the more it needs saying."""
    modules = bundle.module_map.modules
    if not modules:
        return ""
    commit = (bundle.module_map.source_commit or "unknown")[:12]
    header = _HEADER.format(commit=commit) + _coverage(bundle.manifest)

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
