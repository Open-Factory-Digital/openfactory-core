"""Typed contracts for the OKF knowledge bundle (Knowledge Layer, Phase 1).

The bundle is the *generated, source-linked, verifiable* map described in
`docs/knowledge-layer.md` §9. Phase 1 ships two of the §9 artifacts:

- `modules.yaml`  — the deterministic module map (this file's `Module` / `ModuleMap`).
- `manifest.yaml` — the staleness detector (§12): the source commit + a checksum per
  canonical source file, so drift is *detectable* rather than silently served.

Ground truth (§7): every entry carries a `source` link (file + optional symbol + the
commit it was generated from). The map says *where* things live; an agent still reads
and verifies the real code before acting. Nothing here is authoritative over the repo.

These are plain pydantic models so the bundle round-trips through YAML for free and any
consumer (Claude / Codex / Gemini) reads the same provider-neutral shape (§16).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# The bundle is generated, never hand-edited — but unlike the project manifest we do NOT
# forbid extra keys: a NEWER generator may add fields (Phase 2 adds api/schema/adr bundles),
# and an older reader must degrade gracefully rather than crash on an unknown key (§12
# fail-safe posture). Forward-compatible by design.
_MODEL = ConfigDict(extra="ignore")

BUNDLE_VERSION = "1"


class SourceLink(BaseModel):
    """A verifiable back-reference to the ground truth (§7): file + optional symbol +
    the commit the fact was generated from. A consumer follows this to confirm the map
    against the real code; the orphan check (§12) verifies it still resolves."""

    model_config = _MODEL

    file: str  # repo-relative path (POSIX separators, stable across machines)
    symbol: str | None = None  # a top-level def/class when the fact is symbol-scoped
    commit: str  # the source commit the map was generated from ("" if not a git repo)


class Module(BaseModel):
    """One navigable unit of the codebase — a source directory. Derived DETERMINISTICALLY
    from structure + the import/AST graph (§10); no LLM. The `purpose` is inferred from a
    dir README or the package docstring or the dir name — never invented."""

    model_config = _MODEL

    name: str  # stable id, e.g. "openfactory.adapters.agent" (dir path with os-sep → ".")
    path: str  # repo-relative directory (POSIX separators)
    purpose: str  # one line, inferred from README/docstring/name — deterministic
    key_files: list[str] = Field(default_factory=list)  # repo-relative source files, sorted
    # How many source files the module ACTUALLY has. `key_files` is capped (a module with
    # hundreds of files would swamp the map), so without this the map silently under-reports a
    # big module as a small one — a map that misleads is worse than no map (§12). 0 = unset
    # (a bundle written by an older generator).
    file_count: int = 0
    dependencies: list[str] = Field(default_factory=list)  # other module names, in-repo, sorted
    public_surface: list[str] = Field(default_factory=list)  # exported symbols, sorted
    source: SourceLink  # the module's anchor file + commit (the ground-truth link)


class ModuleMap(BaseModel):
    """`modules.yaml` — the module map. Ordered (modules sorted by name) so the same repo
    state always serializes to byte-identical YAML (determinism is Phase 1's whole point)."""

    model_config = _MODEL

    version: str = BUNDLE_VERSION
    source_commit: str = ""
    modules: list[Module] = Field(default_factory=list)


class SourceChecksum(BaseModel):
    """A canonical source file + the sha256 of its bytes at generation time. The set of
    these IS the staleness detector: recompute them against the working tree and any
    mismatch/missing means the map no longer describes reality (§12)."""

    model_config = _MODEL

    file: str  # repo-relative path
    sha256: str


class UnreadExtension(BaseModel):
    """One file extension the generator does NOT understand, and how many such files the
    repository holds. The bundle declaring its own blind spots is what keeps a map of 2 files
    out of 139 from reading like a complete map of a small repo."""

    model_config = _MODEL

    suffix: str  # ".cs", ".java", or "" for files with no extension (Makefile, LICENSE)
    files: int


class BundleManifest(BaseModel):
    """`manifest.yaml` — bundle version, when it was generated, the source commit, a
    checksum per canonical source, and the generator's declared COVERAGE. This is what makes
    the layer SAFE for an autonomous factory that mutates the repo constantly: drift is
    detectable, never silently served — and neither is a stack the generator cannot read."""

    model_config = _MODEL

    bundle_version: str = BUNDLE_VERSION
    generated_at: str = ""  # ISO-8601, passed in by the caller (never read the clock here)
    source_commit: str = ""
    checksums: list[SourceChecksum] = Field(default_factory=list)

    # Coverage. `None` means NOT DECLARED — a bundle written by a generator that predates the
    # survey, so the reader knows it cannot tell. An empty `unread_extensions` list means the
    # opposite and is a real answer: surveyed, and every file was understood. Collapsing those
    # two would make an old bundle claim full coverage it never measured.
    files_read: int | None = None
    files_unread: int | None = None
    unread_extensions: list[UnreadExtension] | None = None

    # The blindness the counts above CANNOT express: directories the generator could not open
    # (a permission-denied vendored subtree, or a `repo_path` that does not exist / is not a
    # directory). Such a directory contributes to neither `files_read` nor `files_unread`, so
    # without this a repository the process cannot read surveys identically to one it read
    # completely. Same three-way rule as the fields above: `None` = never walked (an older
    # bundle — cannot tell), `[]` = walked and every directory opened, non-empty = these are
    # the parts of the repository this map is silent about.
    unreadable_paths: list[str] | None = None


class KnowledgeBundle(BaseModel):
    """The in-memory whole: the manifest (staleness) + the module map. Written to disk as
    two YAML files under a project's `knowledge/` directory."""

    model_config = _MODEL

    manifest: BundleManifest
    module_map: ModuleMap
