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

#: The OKF format version this package writes. Separate from `BUNDLE_VERSION`, which numbers the
#: module map: the two describe different artifacts and will move at different speeds.
OKF_VERSION = "0.2"

#: A concept's lifecycle, and the ONE closed set in this format. Everything else about a concept —
#: above all its `type` — is open, because a taxonomy that ships closed is wrong at the first
#: client whose domain nobody anticipated (the same reason `profile` is a cascade layer and not an
#: enum). `status` is closed because it is about THIS platform's confidence in a fact, not about
#: the client's domain, and three values is the whole vocabulary.
CONCEPT_STATUSES = ("draft", "stable", "deprecated")


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


# ── the OKF: what a module map structurally cannot say ──────────────────────────────────────────
#
# THE MODULE MAP ANSWERS "WHERE", AND A ROLE ASKING "WHY" GETS NOTHING. `Module` carries path,
# purpose, dependencies and public surface — enough for a coding agent to jump to the right file,
# and not enough for anyone to learn what a rule IS. The models below carry the other half: a
# claim about behaviour, with the `file:line` that makes it checkable, and the absences recorded
# as data rather than left as silence.
#
# EVERY FIELD HERE IS EITHER MEASURED OR CITED. Nothing is a model's unanchored opinion:
# `ConceptSource` pins the exact bytes a claim was read from, and `onboarding/context.py`'s
# `_Anchorer` — which already verifies every citation against the working tree and demotes a claim
# that loses all of them into a question — is what fills these in.


class ConceptSource(BaseModel):
    """The bytes a concept was read from, pinned precisely enough for a machine to invalidate it.

    `fingerprint` is what makes staleness MECHANICAL rather than a judgement: when the bytes move,
    the fingerprint moves, and the concept is stale with nobody in the loop. `commit` alone cannot
    do that job — every refresh produces a new commit whether or not this file changed, which is
    exactly why `BundleManifest` already checksums files instead of comparing commits.

    `lines` is a human-readable range (`"1-39"`, or `"12"`), kept as a STRING because it is a
    citation as written, not an interval to compute with. Empty means the whole file.
    """

    model_config = _MODEL

    repo: str = ""  # the source repository this path belongs to; "" in a single-repo bundle
    path: str  # repo-relative, POSIX separators
    commit: str = ""  # the commit the concept was generated from
    fingerprint: str = ""  # sha256 of the file's bytes at generation time
    lines: str = ""


class BusinessRule(BaseModel):
    """One statement about behaviour, and the citations that survived verification.

    A RULE WITH NO SURVIVING CITATION IS NOT A RULE HERE — it is demoted into a question long
    before it reaches this model (`onboarding/context.py::_Anchorer`). So `cites` is never empty
    in a written concept, and a reader can go from any sentence to the code in one hop.
    """

    model_config = _MODEL

    text: str
    cites: list[str] = Field(default_factory=list)  # "path:line" as verified


class Concept(BaseModel):
    """One semantic fact about a system, with provenance — the unit a module map cannot express.

    `type` IS AN OPEN SET, deliberately (`activity`, `contract`, `integration`, `configuration`,
    `deployment`, `ui-surface`, `workflow`, `policy` are what a real bundle produced, not an enum
    this package enforces). Every company's domain names its own kinds, and a closed list is wrong
    at the first client nobody anticipated — the same decision `profile` takes by being a cascade
    layer rather than a label. `status` is the one closed field (`CONCEPT_STATUSES`).
    """

    model_config = _MODEL

    type: str
    title: str
    description: str = ""
    status: str = "draft"
    generated_by: str = ""  # "machine:<pass>" or "human:<id>" — a machine event is not a signature
    generated_at: str = ""  # ISO-8601, passed in; never read the clock in here
    sources: list[ConceptSource] = Field(default_factory=list)

    what_it_does: str = ""
    behaviour: list[str] = Field(default_factory=list)
    business_rules: list[BusinessRule] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    consumed_by: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class Gap(BaseModel):
    """Something the pass could NOT establish, recorded as data instead of as silence.

    THIS IS THE HALF THAT MAKES A BUNDLE HONEST. A map that omits what it could not read is
    indistinguishable from one that found nothing to worry about, and this codebase already has a
    name for that failure — absence read as compliance. `kind` is open for the same reason
    `Concept.type` is; the kinds a first pass can actually produce today are `open-question`
    (nothing in the repository decides it) and `unresolved` (a claim whose citations did not
    survive verification).
    """

    model_config = _MODEL

    kind: str
    detail: str
    path: str = ""  # repo-relative when the gap is about one file; "" when it is about the whole
    #: the scanner's grade where the gap came from a scan — `high`/`low` on a credential risk,
    #: "" elsewhere. The gate blocks a change on a HIGH credential risk and lists a low one.
    severity: str = ""


class CoverageRow(BaseModel):
    """How many units of one kind were inventoried, how many got a concept — and, when that is
    zero, WHY.

    `reason` IS THE POINT OF THIS TABLE. "inventoried 15, concepts 0" alone is a number a reader
    must interpret; with *"data shapes are fully recorded in the inventory"* beside it, it is a
    decision somebody can disagree with. The difference between "we did not" and "we chose not to,
    and here is why" is the whole difference between an omission and a scope.

    `excused` IS THE HALF A REASON CANNOT CARRY. A reason says why the count is zero; it does not
    say whether that is fine. "Generated code is represented by the inventory alone" excuses a
    kind wholesale; "the budget did not reach these" explains and excuses NOTHING — every file
    behind that row is still owed a concept, an exclusion or a gap. The reference checker found
    the trap when a bundle with four concepts over eighty-two files exited clean because every kind
    had a reason: a gate that reads only the reason cannot tell the two apart, so the row says.
    """

    model_config = _MODEL

    kind: str
    inventoried: int = 0
    concepts: int = 0
    reason: str = ""
    excused: bool = False


class FileRow(BaseModel):
    """One file of the repository: what it is, and WHY the inventory says so.

    `kind_reason` is the inventory's failure mode made visible (OKF §6.1): a wrong kind is a
    mistake a reader can find, because the rule that produced it is written beside it."""

    model_config = _MODEL

    path: str
    kind: str
    kind_reason: str
    lines: int = 0
    #: sha256 of the bytes — the same digest a concept's `ConceptSource.fingerprint` carries and
    #: the checker re-derives, so the inventory is what a citation's freshness is measured against
    fingerprint: str = ""


class SecretRisk(BaseModel):
    """A credential-shaped assignment: the path, the key's NAME, the line — never the value.

    `severity` is the scanner's: `high` for a literal that does not look like a placeholder or a
    lookup, `low` for one that does. `kind` is the file's, so a reader can weigh a fixture's
    password against a config file's without opening either."""

    model_config = _MODEL

    path: str
    key: str
    line: int
    severity: str = "high"
    kind: str = ""


class Inventory(BaseModel):
    """The structural inventory of one source repository at one commit (OKF §6.1).

    EXHAUSTIVE BY CONSTRUCTION: every file the walk reached is a row, a file no rule places is
    `unclassified` and COUNTED, a directory the walk could not open is named, and a walk that hit
    its ceiling says so. Each of those is a sentence a reader can act on; none of them is silence.
    """

    model_config = _MODEL

    schema_version: str = "1"
    commit: str = ""
    generated_at: str = ""
    files: list[FileRow] = Field(default_factory=list)
    by_kind: dict[str, int] = Field(default_factory=dict)
    unclassified: list[str] = Field(default_factory=list)
    #: directories the walk could not open — read as UNREAD, never as empty
    unreadable: list[str] = Field(default_factory=list)
    #: files the walk found and could not read
    errors: list[str] = Field(default_factory=list)
    truncated: bool = False
    secret_risks: list[SecretRisk] = Field(default_factory=list)

    def kind_of(self, path: str) -> str:
        """The kind of one path, or "" when the inventory never saw it."""
        for row in self.files:
            if row.path == path:
                return row.kind
        return ""


class OkfManifest(BaseModel):
    """The bundle's own account of itself: what it covers, what it does not, and what it refuses
    to authorise.

    `scope_limit` is prose ON PURPOSE and it is not decoration: it is the sentence that stops a
    reader treating a machine-generated reading of a legacy system as a specification of it. The
    core's own doctrine already says the code is ground truth and the map only says where to look;
    this is where that is said to whoever opens the bundle.
    """

    model_config = _MODEL

    okf_version: str = OKF_VERSION
    bundle_kind: str = "source-repo"  # or "project-context" for the cross-repo bundle
    generated_at: str = ""
    source_commit: str = ""
    coverage: list[CoverageRow] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    scope_limit: str = ""
