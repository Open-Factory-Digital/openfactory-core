"""The module map declares its own blindness to the agent that reads it.

THE DEFECT THESE CLOSE. The bundle has surveyed its own coverage since coverage was added:
`files_read`, `files_unread`, `unread_extensions` and `unreadable_paths`, with a deliberate
three-way distinction between never-measured, measured-and-clean, and blind. They are checksummed
into the bundle's derived key and published to the knowledge branch — and `render_module_map`
emitted the header and the module entries and NOTHING ELSE. No agent, on any ticket, was ever told
what the map does not cover.

Measured on this repository on 2026-08-29: 688 source files read, 111 walked and not read, and not
one word about the 111 in 6,164 characters of injected map. `render_module_map`'s own docstring
argues that an omission must be visible rather than assumed away.

WHAT THESE GUARD:

  * the counts and the unreadable kinds REACH the rendering;
  * a bundle that never measured its coverage says UNKNOWN — silence there is how an old bundle
    starts claiming completeness it never had;
  * a bundle that measured and found nothing says THAT, so the warning is information and not
    decoration on every map;
  * the sentence survives BOTH degradation paths. It rides in the header on purpose: the thinner
    the map gets, the more it needs saying, and a coverage note that vanishes exactly when modules
    start being dropped is worse than none.
"""

from __future__ import annotations

from pathlib import Path

from openfactory.knowledge.contracts import (
    BundleManifest,
    KnowledgeBundle,
    Module,
    ModuleMap,
    SourceLink,
    UnreadExtension,
)
from openfactory.knowledge.render import _MAX_CHARS, render_module_map


def _bundle(manifest: BundleManifest, *, modules: int = 1) -> KnowledgeBundle:
    return KnowledgeBundle(
        manifest=manifest,
        module_map=ModuleMap(source_commit="c0ffee123456", modules=[
            Module(name=f"m{i}", path=f"pkg/m{i}", purpose="does a thing",
                   key_files=[f"pkg/m{i}/a.py"], file_count=1,
                   source=SourceLink(file=f"pkg/m{i}/a.py", commit="c0ffee123456"))
            for i in range(modules)
        ]),
    )


# ── the defect ───────────────────────────────────────────────────────────────────────────────────

def test_the_files_the_map_never_read_are_named_to_the_agent() -> None:
    """The whole point. 111 unread files must not travel as silence."""
    rendered = render_module_map(_bundle(BundleManifest(
        files_read=688, files_unread=111,
        unread_extensions=[UnreadExtension(suffix=".java", files=90),
                           UnreadExtension(suffix=".sql", files=21)],
        unreadable_paths=[])))

    assert "688" in rendered and "111" in rendered
    assert ".java" in rendered and "90" in rendered
    assert ".sql" in rendered


def test_a_stack_the_map_cannot_read_is_stated_as_existing_code() -> None:
    """`.java ×90` on its own reads as a footnote. The sentence has to say that the code EXISTS
    and is not below, because the failure being prevented is an agent concluding a subsystem is
    absent from the repository."""
    rendered = render_module_map(_bundle(BundleManifest(
        files_read=10, files_unread=90,
        unread_extensions=[UnreadExtension(suffix=".java", files=90)],
        unreadable_paths=[])))

    assert "EXISTS" in rendered


def test_a_directory_that_could_not_be_opened_is_named() -> None:
    """The blindness the counts cannot express: such a directory contributes to neither
    `files_read` nor `files_unread`, so without this it surveys identically to one read whole."""
    rendered = render_module_map(_bundle(BundleManifest(
        files_read=10, files_unread=0, unread_extensions=[],
        unreadable_paths=["vendor/legacy", "ops/secrets"])))

    assert "vendor/legacy" in rendered and "ops/secrets" in rendered


# ── the three states stay three ──────────────────────────────────────────────────────────────────

def test_a_bundle_that_never_measured_coverage_says_unknown_not_nothing() -> None:
    """`None` is an older bundle, written before the survey existed. Rendering nothing for it is
    exactly how it comes to claim a completeness it never measured."""
    rendered = render_module_map(_bundle(BundleManifest()))

    assert "UNKNOWN" in rendered
    assert "not evidence that the area does not exist" in rendered


def test_a_bundle_that_measured_and_found_nothing_says_so() -> None:
    """The positive twin, and it is load-bearing: without it a renderer that warned on EVERY map
    would pass every guard above, and the warning would stop carrying information."""
    rendered = render_module_map(_bundle(BundleManifest(
        files_read=42, files_unread=0, unread_extensions=[], unreadable_paths=[])))

    assert "Every file walked was read and every directory opened." in rendered
    assert "UNKNOWN" not in rendered


# ── it survives both ways the rendering degrades ─────────────────────────────────────────────────

def test_the_coverage_line_survives_the_detail_degradation() -> None:
    """A map big enough to shed its widest fields still says what it does not cover."""
    big = _bundle(BundleManifest(
        files_read=1, files_unread=500,
        unread_extensions=[UnreadExtension(suffix=".java", files=500)],
        unreadable_paths=[]), modules=200)

    rendered = render_module_map(big)

    assert ".java" in rendered
    assert len(rendered) <= _MAX_CHARS


def test_the_coverage_line_survives_modules_being_dropped() -> None:
    """THE CASE IT EXISTS FOR. When even the barest entries overflow, whole modules are dropped —
    and that is precisely when an agent most needs to be told the map is partial. A coverage note
    that disappeared here would vanish exactly when it matters."""
    huge = _bundle(BundleManifest(
        files_read=1, files_unread=9000,
        unread_extensions=[UnreadExtension(suffix=".cbl", files=9000)],
        unreadable_paths=[]), modules=4000)

    rendered = render_module_map(huge)

    assert "module(s) omitted for size" in rendered, "the fixture must reach the last-resort path"
    assert ".cbl" in rendered
    assert "9000" in rendered
    assert len(rendered) <= _MAX_CHARS


# ── bounds, so the header cannot become the payload ──────────────────────────────────────────────

def test_a_long_tail_of_unread_kinds_is_capped_and_says_how_many_more() -> None:
    """The note travels on every injection and before any module, so it is bounded. A cap that did
    not say it was a cap would be the same defect one level down."""
    rendered = render_module_map(_bundle(BundleManifest(
        files_read=1, files_unread=60,
        unread_extensions=[UnreadExtension(suffix=f".x{i}", files=1) for i in range(20)],
        unreadable_paths=[])))

    assert "more kind(s)" in rendered
    assert ".x19" not in rendered          # the tail is not printed …
    assert ".x0" in rendered               # … and the head is


def test_many_unreadable_directories_are_capped_and_say_how_many_more() -> None:
    rendered = render_module_map(_bundle(BundleManifest(
        files_read=1, files_unread=0, unread_extensions=[],
        unreadable_paths=[f"vendor/p{i}" for i in range(12)])))

    assert "and 7 more" in rendered
    assert "vendor/p11" not in rendered


def test_a_file_with_no_extension_is_named_rather_than_rendered_blank() -> None:
    """`suffix` is `""` for `Makefile` and `LICENSE`. Rendered verbatim that is ` ×6`, which a
    reader takes for a bug in the platform rather than a fact about their repository."""
    rendered = render_module_map(_bundle(BundleManifest(
        files_read=1, files_unread=6,
        unread_extensions=[UnreadExtension(suffix="", files=6)], unreadable_paths=[])))

    assert "(no extension) ×6" in rendered


# ── the control ──────────────────────────────────────────────────────────────────────────────────

def test_control_a_real_bundle_of_this_repository_declares_its_own_blindness() -> None:
    """Built from this repository, not a fixture — the measurement the defect was found by. If
    this goes red, read it before anything above."""
    from openfactory.knowledge.bundle import build_bundle

    rendered = render_module_map(
        build_bundle(Path("."), commit="abc123", generated_at="2026-08-29T00:00:00Z"))

    assert "COVERAGE:" in rendered
    assert "were walked and NOT read" in rendered
    assert len(rendered) <= _MAX_CHARS


def test_a_map_with_no_modules_still_renders_nothing() -> None:
    """Unchanged behaviour, guarded because the coverage line is now built before the modules are
    checked in an earlier draft of this change — an empty map must stay an empty string, or every
    caller's `if knowledge_map:` starts injecting a header about nothing."""
    assert render_module_map(_bundle(BundleManifest(files_read=1, files_unread=1,
                                                    unread_extensions=[], unreadable_paths=[]),
                                     modules=0)) == ""
