"""Every document that ships serves somebody who will use or contribute to the core.

THE DECISION (owner, 2026-08-26): a document ships only if a stranger can act on it. Eight
documents failed that on 2026-08-26 — a spin-off plan, a commercial-line record, a dated audit of
this tree, a gap analysis with a sales frame, an answered-questions page, the dossier's index, a
website copy source and one cloud deployment's incident page. They are not deleted; they are rows
in `docs/STATUS.md`'s excluded-paths table, and the incident page moved beside the package whose
deployment it describes.

WHAT THAT CUT CAN BREAK, AND WHAT EACH GUARD HERE HOLDS.

  · **A passage can leave with its document.** Four passages in the excluded set survived nowhere
    else public, so each was moved into a page that stays BEFORE the row landed. The rule that
    makes it checkable is structural rather than a search for the words: every excluded document's
    row names, in its own cell, at least one path that a reader of the export can open.

  · **A directory can lose its index.** `docs/core/` goes from nine files to three. The index that
    stays must ship (it is the only thing that stops 00/02/07 reading as an amputation), and every
    document it names must ship with it — a design document nobody links is the signature defect
    of this codebase one level up.

  · **A pointer with no markdown link and no `.md` is invisible to both existing scanners.** The
    link walk in `test_the_public_cut_is_written_down.py` reads `[…](…)` only; the package scan in
    `test_a_remedy_names_a_document_that_exists.py` reads `openfactory/**/*.py` only. Between them
    sit the surfaces that travel with every fork and that neither reads — `NOTICE` (Apache §4(d)
    carries it into every fork), the add-ons' `NOTICE`s, `pyproject.toml`, `.gitignore`'s comments
    and `docs/STATUS.md`'s prose. Five of them pointed at `docs/core/03` or `docs/core/04` on
    2026-08-26.

  · **A guard can read a path the export does not have.** Two did: the front-door list named
    `docs/site-guide.md` and a framing check `read_text()`-ed it. In the export that is a
    `FileNotFoundError` from a guard, which is the worst possible way to learn about the cut. The
    standing rule is that a guard reaches such a path through `add_ons.source()`, which skips at
    RUN time naming the package, or not at all.

  · **A git ref can name a history the reader does not have.** `docs/STATUS.md` said "main at
    `b10271e`" with no attribution. In this tree that resolves, so the guard that checks the sha is
    real passed and the attribution — the entire fix for a reader of the export — was never
    required anywhere it runs. Here it is required unconditionally, of tags as well as shas.
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import tomllib

import add_ons
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATUS = ROOT / "docs" / "STATUS.md"
CORE_INDEX = "docs/core/README.md"

#: The surfaces neither existing scanner reads. Each one ships, each one is read by a person
#: rather than a tool, and none of them is Python or a markdown link.
FORK_SURFACES = ("NOTICE", "pyproject.toml", ".gitignore", "docs/STATUS.md",
                 "addons/openfactory-aws/NOTICE", "addons/openfactory-slack/NOTICE")

#: A repository-relative document citation, spelled with or without its extension — `docs/core/04`
#: rots exactly like `docs/core/04-business-and-licensing.md`, and it was the extension-less form
#: that reached a runtime error string.
#: A citation of a document, and NOT the tail of a longer path: without the lookbehind,
#: `addons/openfactory-aws/docs/runbook.md` yields `docs/runbook.md` — a pointer nobody
#: wrote, at a path that does not exist, reported as a dead end while the sentence beside
#: it was correct (measured 2026-08-26, on the very sentence that says where the page went).
DOC_PATH = re.compile(r"(?<![\w/.-])(?:addons/[\w.-]+/)?docs/[\w./-]*[\w-]")

#: A git ref as this repository's documents spell one: a short or full sha, or a version tag.
GIT_REF = re.compile(r"`(?P<ref>[0-9a-f]{7,40}|v\d+(?:\.\d+)+)`")

#: The binding a ref must carry: `of` and a backticked name. The NAME is checked against what the
#: tree publishes below, so renaming the binding to something invented does not satisfy this.
REF_HOME = re.compile(r"\bof\s+`(?P<home>[\w.\-]+)`")


# ── the table, read once ────────────────────────────────────────────────────────────────────────

def _excluded() -> dict[str, str]:
    return add_ons.excluded_paths()


def _cells() -> dict[str, str]:
    """path → the raw `where it lives instead` cell, which `add_ons` reduces to a package name."""
    text = STATUS.read_text()
    heading = "## What the public repository contains"
    body = text[text.index(heading) + len(heading):]
    nxt = body.find("\n## ")
    body = body if nxt < 0 else body[:nxt]
    return dict(re.findall(r"^\| `([^`]+)` \| (.+?) \|$", body, re.M))


def _is_excluded(rel: str, excluded: dict[str, str]) -> bool:
    return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in excluded)


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True,
                         timeout=120)
    assert out.returncode == 0, out.stderr[:200]
    return [p for p in out.stdout.split("\0") if p]


# ── rescue before you exclude ───────────────────────────────────────────────────────────────────

def homeless(cells: dict[str, str], exists) -> list[str]:
    """The excluded DOCUMENTS whose cell sends a reader nowhere they can go.

    A cell earns its row by naming at least one path that exists AND stays. `exists` is a
    parameter so the judgement can be fed a tree it does not have to build on disk — inline, it
    could not be, and a cut that deleted the whole check would survive on a table that happens to
    be correct."""
    out = []
    for path, cell in sorted(cells.items()):
        if not path.endswith(".md"):
            continue
        named = re.findall(r"`([^`]+)`", cell)
        reachable = [p for p in named if exists(p) and not _is_excluded(p, cells)]
        if not reachable:
            out.append(f"{path} → {cell}")
    return out


def test_the_home_check_REPORTS_a_row_that_sends_a_reader_nowhere():
    """Verify the verifier on the four shapes: a live home, a home that leaves too, a home that is
    not in the tree at all, and a cell with no path in it whatsoever."""
    planted = {
        "docs/gone-a.md": "`docs/STAYS.md` carries the rule a user needs",
        "docs/gone-b.md": "`docs/gone-c.md` says the same thing",
        "docs/gone-c.md": "`docs/never-existed.md` carries it",
        "docs/gone-d.md": "website copy source; this page is the public claim",
        "openfactory/vendor.py": "`openfactory-x` — not a document, not judged here",
    }
    assert homeless(planted, {"docs/STAYS.md", "docs/gone-c.md"}.__contains__) == [
        "docs/gone-b.md → `docs/gone-c.md` says the same thing",
        "docs/gone-c.md → `docs/never-existed.md` carries it",
        "docs/gone-d.md → website copy source; this page is the public claim",
    ]


def test_every_excluded_document_names_a_home_a_reader_of_the_export_can_open():
    cells = _cells()
    documents = [p for p in cells if p.endswith(".md")]
    assert len(documents) >= 6, (
        f"the table excludes {len(documents)} documents — the cut this guard was written for "
        f"removed six, so it is measuring the wrong table")
    stranded = homeless(cells, lambda p: (ROOT / p).exists())
    assert not stranded, (
        "these documents leave the public tree and their row names nothing a reader of the export "
        "can open — whatever they owed a reader has to be moved into a page that stays BEFORE the "
        "row lands:\n  " + "\n  ".join(stranded))


# ── the design directory keeps an index, and the index keeps its documents ──────────────────────

def _core_documents() -> list[str]:
    return [rel for rel in _tracked()
            if rel.startswith("docs/core/") and rel.endswith(".md")]


def test_the_design_directory_is_cut_file_by_file_and_never_as_a_directory():
    """Both halves, because either alone reads as compliance. A `docs/core/` row would take the
    extensibility document with it — the one a third party has for "how do I add a provider" — and
    that is why the cut is six file rows. And a directory NONE of whose files leave would satisfy
    a "no directory row" check while proving the cut never happened."""
    excluded = _excluded()
    assert "docs/core/" not in excluded, (
        "docs/STATUS.md excludes `docs/core/` as a directory, which takes the extensibility "
        "document with it — the cut is file rows, one per document that leaves")
    # LEAVING COMES FROM THE TABLE, STAYING FROM THE TREE. Reading both off the disk made this
    # guard measure nothing in the export, where the documents that leave are exactly the ones
    # that are gone — a cut proving itself by the absence it created.
    leaving = [rel for rel in excluded if rel.startswith("docs/core/")]
    staying = [rel for rel in _core_documents() if not _is_excluded(rel, excluded)]
    assert leaving, "docs/STATUS.md's table excludes no document under docs/core/ — the cut is not written down"
    assert staying, "every document under docs/core/ leaves — the directory ships empty"


def test_the_design_index_SHIPS_and_every_document_it_names_ships_with_it():
    """The index is the answer to a numbering with gaps in it: 00, 02 and 07 read as an amputation
    without a page naming the three by title. An index the export excludes answers nothing, and an
    index naming a document the export drops is worse than no index at all."""
    excluded = _excluded()
    assert not _is_excluded(CORE_INDEX, excluded), (
        f"{CORE_INDEX} is excluded from the public tree — the design directory then ships three "
        f"numbered files and no front page, which is the gap the index exists to close")
    text = (ROOT / CORE_INDEX).read_text()
    targets = [t.split("#", 1)[0].strip() for t in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text)]
    named = [t for t in targets if t and "://" not in t]
    assert named, f"{CORE_INDEX} links to nothing — it is an index of an empty set"
    broken = []
    for target in named:
        rel = (pathlib.PurePosixPath(CORE_INDEX).parent / target).as_posix()
        rel = str(pathlib.PurePosixPath(rel))
        while "/../" in rel:
            rel = re.sub(r"[^/]+/\.\./", "", rel, count=1)
        if not (ROOT / rel).exists():
            broken.append(f"{target} → {rel} is not in the tree")
        elif _is_excluded(rel, excluded):
            broken.append(f"{target} → {rel} leaves the public tree")
    assert not broken, (
        f"{CORE_INDEX} names documents a reader of the export cannot open:\n  "
        + "\n  ".join(broken))


def test_every_design_document_that_STAYS_is_reached_from_the_index():
    """The reachability half, and it is the one this codebase gets wrong: a design document that
    ships and is linked from nowhere is built, tested, reached by nothing, one level up. Every
    `.md` under docs/core/ that stays is named by the index, the index included."""
    excluded = _excluded()
    text = (ROOT / CORE_INDEX).read_text()
    linked = {(pathlib.PurePosixPath(CORE_INDEX).parent / t.split("#", 1)[0].strip()).as_posix()
              for t in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text) if t and "://" not in t}
    orphans = [rel for rel in _core_documents()
               if not _is_excluded(rel, excluded) and rel != CORE_INDEX and rel not in linked]
    assert not orphans, (
        f"these design documents ship and the index does not name them, so nothing in the public "
        f"tree reaches them: {orphans}")


# ── the pointers no scanner reads ───────────────────────────────────────────────────────────────

def _ignore_rules(text: str) -> set[str]:
    """The patterns git reads, from the file's own non-comment lines — so the exemption below is
    derived from the file rather than a name typed into this guard."""
    return {line.strip().rstrip("/") for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")}


def _pointer_text(rel: str, text: str) -> str:
    """What counts as PROSE on this surface.

    `.gitignore` is two languages in one file: comments a person reads, and patterns git reads. A
    pattern is not a pointer — `docs/temp/` names a directory that must NOT exist — so only the
    comments are scanned. `docs/STATUS.md`'s excluded-paths table is the other special case: it is
    the one place an excluded path is written down, so its own rows cannot be read as pointers
    into it."""
    if rel == ".gitignore":
        return "\n".join(line if line.lstrip().startswith("#") else "" for line in text.splitlines())
    if rel == "docs/STATUS.md":
        rows = re.compile(r"^\| `[^`]+` \| .+? \|$", re.M)
        return rows.sub("", text)
    return text


def unreachable(surfaces: dict[str, str], resolve, excluded: dict[str, str]) -> list[str]:
    """`surface:line pointer` for every citation a reader of the export cannot follow.

    Two failures, one judgement: a pointer at nothing, and a pointer at a path the export
    excludes. Two things are not failures. A pointer that resolves inside an add-on package is
    fine — that is where the document moved to, and the sentence around it names the package. And
    a `.gitignore` comment that names the very pattern it explains is describing a RULE, not
    citing a document: `docs/temp/` MUST resolve to nothing, and reading it as a broken pointer
    would make this permanently red on a correct file. That exemption is read off the file's own
    rules, so it covers the next ignored path without being told about it.

    THE EXCLUSION IS TESTED ON THE RESOLVED PATH, NOT ON THE CITATION. `docs/core/04` is how a
    person cites a numbered document; the table's row is `docs/core/04-business-and-licensing.md`.
    Comparing the citation to the table directly is how all four extension-less pointers survived
    a first version of this guard (measured 2026-08-26) — the citation resolved like a reader's
    and matched no row, so it passed twice for the wrong reason. `resolve` returns the path the
    citation names, and that is what the table is asked about."""
    out = []
    for rel, text in sorted(surfaces.items()):
        prose = _pointer_text(rel, text)
        rules = _ignore_rules(text) if rel.endswith(".gitignore") else set()
        for m in DOC_PATH.finditer(prose):
            doc, line = m.group(0), prose.count("\n", 0, m.start()) + 1
            if doc in rules:
                continue
            target = resolve(doc)
            if target and not (_is_excluded(target, excluded) or _is_excluded(target + "/", excluded)):
                continue
            # A CITATION UNDER THE SIGNAL PATH IS A PACKAGE'S OWN DOCUMENT, BY CONSTRUCTION.
            # This used to try each package directory found ON DISK, which is empty in the very
            # tree the guard is about: in the export every pointer into a package was reported as
            # a dead end (measured 2026-08-26). The rule now reads the citation, which ships, and
            # the price is that a document in a package must be cited by its full path — which is
            # the only form a reader of the export can act on anyway.
            if doc.startswith(add_ons.public_tree_signal()):
                continue
            out.append(f"{rel}:{line} {doc}")
    return out


def _package_prefixes() -> list[str]:
    """Where an add-on package's own documents live, derived from the signal path rather than
    typed: `addons/openfactory-aws/`, `addons/openfactory-slack/`."""
    signal = ROOT / add_ons.public_tree_signal()
    if not signal.is_dir():
        return []
    return [f"{add_ons.public_tree_signal()}{d.name}/" for d in sorted(signal.iterdir()) if d.is_dir()]


def _resolve(doc: str) -> str | None:
    """The repo-relative path a citation NAMES, resolved the way a reader resolves it — an
    extension names that file, a bare citation (`docs/core/04`) names the entry of its directory
    that begins with it. `None` when nothing answers.

    Returning the path rather than a yes/no is what lets the exclusion be tested on the document
    instead of on the spelling."""
    if (ROOT / doc).exists():
        return doc
    parent, _, stem = doc.rpartition("/")
    directory = ROOT / parent
    if not stem or not directory.is_dir():
        return None
    hits = sorted(p.name for p in directory.glob(f"{stem}*"))
    return f"{parent}/{hits[0]}" if hits else None


def test_a_bare_citation_resolves_to_the_DOCUMENT_it_names():
    """The half that made four pointers survive: `docs/core/04` has to become the file, or the
    table is asked about a spelling no row uses and answers no every time."""
    assert _resolve("docs/core/07") == "docs/core/07-extensibility.md"
    assert _resolve("docs/core/07-extensibility.md") == "docs/core/07-extensibility.md"
    assert _resolve("docs/adr") == "docs/adr"
    assert _resolve("docs/core/99") is None
    assert _resolve("docs/nowhere/at-all.md") is None


def test_the_pointer_judgement_REPORTS_only_the_dead_and_the_excluded():
    """Verify the verifier before trusting the sweep: fed a live pointer, an excluded one, a dead
    one and one that resolves only inside an add-on package, it returns the middle two."""
    excluded = {"docs/gone.md": "`openfactory-x`"}
    surfaces = {"NOTICE": ("see docs/STAYS.md\n"
                           "and docs/gone.md\n"
                           "and docs/never.md\n"
                           "and that package's addons/openfactory-aws/docs/moved.md\n"
                           "and the numbered docs/gone, cited without its extension\n")}
    here = {"docs/STAYS.md": "docs/STAYS.md",
            "docs/gone.md": "docs/gone.md",
            "docs/gone": "docs/gone.md",
            "addons/openfactory-aws/docs/moved.md": "addons/openfactory-aws/docs/moved.md"}
    assert unreachable(surfaces, here.get, excluded) == [
        "NOTICE:2 docs/gone.md", "NOTICE:3 docs/never.md", "NOTICE:5 docs/gone"], (
        "a citation of a package's own document, written in full, is not a dead end — and the "
        "tail of that path is not a second citation")


def test_the_pointer_scan_reads_a_gitignore_COMMENT_and_never_a_pattern():
    """The one surface where the same shape means two things. `docs/temp/` on its own line is an
    ignore RULE — a directory that must not exist — and reading it as a broken pointer would make
    this guard permanently red on a correct file. The citation in the comment above it is a
    pointer, and that is the one that rotted."""
    planted = ("# `docs/temp/` is where a client's architecture lands, and it is never committed\n"
               "# the plan is written in docs/core/03, Phase 3\n"
               "# and the shape is docs/never-written.md\n"
               "docs/temp/\n")
    seen = {m.group(0) for m in DOC_PATH.finditer(_pointer_text(".gitignore", planted))}
    assert seen == {"docs/temp", "docs/core/03", "docs/never-written.md"}, seen
    assert DOC_PATH.search(_pointer_text("NOTICE", planted)), (
        "the pattern filter is applied to every surface — a real citation on any other file would "
        "be dropped with it")

    # …and the JUDGEMENT keeps the rule and reports the dead pointer beside it
    assert unreachable({".gitignore": planted}, {"docs/core/03": "docs/core/03.md"}.get, {}) == [
        ".gitignore:3 docs/never-written.md"]


def test_the_status_tables_own_rows_are_not_read_as_pointers_into_themselves():
    """The other special case, and the trap in it: the excluded-paths table names every excluded
    path BY DEFINITION, so reading its rows as pointers would report the list as six broken links.
    The prose around the table is still scanned — that is where `docs/core/04` was cited."""
    planted = ("| `docs/core/04-business-and-licensing.md` | `NOTICE` carries the rule |\n"
               "This is the model docs/core/04 sells.\n")
    seen = {m.group(0) for m in DOC_PATH.finditer(_pointer_text("docs/STATUS.md", planted))}
    assert seen == {"docs/core/04"}, seen


def test_the_pointer_scan_has_a_subject():
    """A scan that found nothing would report every surface clean for the wrong reason."""
    surfaces = {rel: (ROOT / rel).read_text() for rel in FORK_SURFACES if (ROOT / rel).is_file()}
    total = sum(len(DOC_PATH.findall(_pointer_text(rel, text))) for rel, text in surfaces.items())
    assert total >= 5, f"the scan found {total} citations across {sorted(surfaces)} — it has lost its subject"


def test_no_pointer_on_a_surface_that_travels_with_every_fork_is_a_dead_end():
    surfaces = {rel: (ROOT / rel).read_text() for rel in FORK_SURFACES if (ROOT / rel).is_file()}
    assert surfaces, "none of the fork surfaces is in the tree"
    dead = unreachable(surfaces, _resolve, _excluded())
    assert not dead, (
        "these sentences point at a document a reader of the public tree cannot open — none of "
        "them is a markdown link and none is in the package, so no other guard sees them:\n  "
        + "\n  ".join(dead))


# ── a guard never reads a path the export does not have ─────────────────────────────────────────

def _paths_bound_by_a_loop(tree: ast.AST) -> dict[str, list[tuple[int, str]]]:
    """name → the path literals a `for` (or a comprehension) binds it to.

    THE INDIRECTION IS THE WHOLE SHAPE. The two guards that broke this rule on 2026-08-26 did not
    write `read_text("docs/site-guide.md")`; they wrote the path into a tuple and read it through
    the loop variable. A scan that only looks at the receiver's own literals walks straight past
    that, which is how the second of those two survived a first version of this guard."""
    bound: dict[str, list[tuple[int, str]]] = {}
    for node in ast.walk(tree):
        pairs = []
        if isinstance(node, (ast.For, ast.AsyncFor)):
            pairs = [(node.target, node.iter)]
        elif isinstance(node, ast.comprehension):
            pairs = [(node.target, node.iter)]
        for target, iterable in pairs:
            literals = [(c.lineno, c.value) for c in ast.walk(iterable)
                        if isinstance(c, ast.Constant) and isinstance(c.value, str)
                        and "/" in c.value]
            if not literals:
                continue
            for name in (n.id for n in ast.walk(target) if isinstance(n, ast.Name)):
                bound.setdefault(name, []).extend(literals)
    return bound


def _read_text_paths(source: str) -> list[tuple[int, str]]:
    """`(line, literal)` for every path literal that reaches a `.read_text()` receiver — written
    into it directly, or bound to a name by a loop the receiver then uses — unless the chain
    routes through `add_ons`, which is what makes the read skip at run time by name."""
    tree = ast.parse(source)
    bound = _paths_bound_by_a_loop(tree)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("read_text", "read_bytes")):
            continue
        receiver = node.func.value
        routed = any(isinstance(n, ast.Name) and n.id == "add_ons"
                     or isinstance(n, ast.Attribute) and n.attr == "source"
                     for n in ast.walk(receiver))
        if routed:
            continue
        for n in ast.walk(receiver):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and "/" in n.value:
                out.append((n.lineno, n.value))
            elif isinstance(n, ast.Name):
                out.extend(bound.get(n.id, ()))
    return sorted(set(out))


def test_the_read_scan_can_SEE_the_shapes_it_is_named_for():
    """Verify the verifier on the three shapes that matter: a direct read of a path, the same read
    routed through `add_ons.source`, and a read of something that is not a path at all."""
    planted = (
        "bad = (ROOT / 'docs/site-guide.md').read_text()\n"
        "ok = add_ons.source('openfactory/runtime/slack/bot.py').read_text()\n"
        "also_ok = (ROOT / 'docs/STATUS.md').read_text()\n"
        "not_a_path = something('add-on').read_text()\n"
    )
    assert _read_text_paths(planted) == [(1, "docs/site-guide.md"), (3, "docs/STATUS.md")]

    # THE INDIRECT SHAPE, which is the one that was actually written: the path goes into a tuple
    # and the read happens through the loop variable.
    through_a_loop = (
        "for rel, must_say in (('docs/ONBOARDING.md', ('add-on',)),\n"
        "                      ('docs/site-guide.md', ('add-on',))):\n"
        "    text = (ROOT / rel).read_text()\n"
    )
    assert _read_text_paths(through_a_loop) == [(1, "docs/ONBOARDING.md"),
                                                (2, "docs/site-guide.md")]

    # …and a loop that binds no literal contributes nothing, or every scan over a computed list
    # would be reported for whatever it happens to read
    computed = "for rel in _tracked():\n    text = (ROOT / rel).read_text()\n"
    assert _read_text_paths(computed) == []


def test_no_guard_reads_a_path_the_public_cut_EXCLUDES():
    """The standing rule this cut leaves behind. A guard that `read_text()`s an excluded path is
    green here and raises `FileNotFoundError` in the export, where the reason it exists is the
    reason it fails. Two did on 2026-08-26, both naming `docs/site-guide.md`."""
    excluded = _excluded()
    offenders = []
    for path in sorted(ROOT.joinpath("tests").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        for line, literal in _read_text_paths(path.read_text()):
            if _is_excluded(literal, excluded) or _is_excluded(literal + "/", excluded):
                offenders.append(f"{rel}:{line} {literal}")
    assert not offenders, (
        "these guards read a path the public tree does not have — route the read through "
        "`add_ons.source()`, which skips at RUN time naming the package, or stop reading it:\n  "
        + "\n  ".join(offenders))


# ── a git ref names the history it belongs to ───────────────────────────────────────────────────

def _published_names() -> set[str]:
    """The repository names this TREE can vouch for, derived rather than typed: the distribution's
    own name, the add-on packages `docs/STATUS.md` lists, and the public export's name, which is
    the distribution's with the suffix the export carries."""
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())
    name = meta["project"]["name"]
    names = {name, f"{name}-core"}
    for cell in _cells().values():
        names |= set(re.findall(r"openfactory-[a-z]+", cell))
    return names


def unattributed(text: str, known: set[str]) -> list[str]:
    """Every git ref in `text` that does not say whose history it belongs to.

    A ref is attributed when the sentence carrying it binds it to a name the tree publishes.
    Requiring only the binding would accept an invented repository; requiring only a known name
    somewhere on the page would accept a ref beside it by accident. Both, together."""
    out = []
    for m in GIT_REF.finditer(text):
        start = max(text.rfind(".", 0, m.start()), text.rfind("\n\n", 0, m.start())) + 1
        end = text.find(".", m.end())
        sentence = text[start:end if end > 0 else len(text)]
        home = REF_HOME.search(sentence)
        if not home or home.group("home") not in known:
            out.append(f"{m.group('ref')} — {' '.join(sentence.split())[:90]}")
    return out


def test_the_attribution_check_REPORTS_both_ways_it_fails():
    """Verify the verifier: a bound ref passes, a bare one fails, one bound to a name the tree
    does not publish fails, and a version tag is judged exactly like a sha."""
    known = {"openfactory", "openfactory-core"}
    assert unattributed("main at `b10271e` of `openfactory`, the source tree.", known) == []
    assert unattributed("cut from `deadbee` of `openfactory-core`.", known) == []
    assert len(unattributed("Status as of 2026-08-26, main at `b10271e` — green.", known)) == 1
    assert len(unattributed("main at `b10271e` of `somewhere-else`.", known)) == 1
    assert len(unattributed("19 tickets are in the `v1.1.0` tag.", known)) == 1
    assert unattributed("19 tickets are in the `v1.1.0` tag of `openfactory`.", known) == []
    # …and the binding has to be in the ref's OWN sentence. A page that names the repository
    # somewhere else has not attributed anything — that is how "a known name is on the page"
    # would pass a page where every ref is bare.
    assert len(unattributed("main at `b10271e`. The tree is a clone of `openfactory`.", known)) == 1


def test_every_git_ref_the_status_page_names_says_WHOSE_history_it_is():
    """Unconditionally, in every tree. The existing sha guard resolves the ref against this
    repository, so in the private tree it passes and in the export it skips — the attribution a
    reader of the export actually needs was therefore required nowhere. This asks for the
    attribution instead of the resolution, so it is the same assertion on both sides of the cut."""
    text = STATUS.read_text()
    refs = GIT_REF.findall(text)
    assert refs, "docs/STATUS.md names no git ref at all — this guard has lost its subject"
    known = _published_names()
    assert len(known) >= 3, f"only {sorted(known)} — the published names are not being derived"
    bare = unattributed(text, known)
    assert not bare, (
        "these git refs on docs/STATUS.md do not say whose history they belong to. The public "
        f"repository is cut from a different history, so a bare ref there resolves to nothing — "
        f"bind each to one of {sorted(known)}:\n  " + "\n  ".join(bare))


def test_the_published_names_include_the_export_and_the_packages():
    """The positive twin of the derivation: a `_published_names` that returned everything would
    make the attribution check accept any word, and one that returned the distribution alone would
    refuse the export's own name — which is the name the public page has to use."""
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())
    known = _published_names()
    assert meta["project"]["name"] in known
    assert f"{meta['project']['name']}-core" in known
    assert {p for p in known if p.startswith("openfactory-") and not p.endswith("-core")}, (
        "the add-on packages docs/STATUS.md lists are not in the published names")
    assert "main" not in known and "tag" not in known, (
        "the derivation is admitting ordinary words — the binding would then accept anything")


# ── the private tree keeps what it excludes ─────────────────────────────────────────────────────

def test_the_excluded_documents_are_STILL_HERE_and_tracked():
    """Excluded is not deleted, and the difference is the whole reason this is a table rather than
    a `git rm`. `test_the_public_cut_is_written_down.py` holds every row to the tree; this states
    the half a reader of THIS page needs — the documents the export drops are still readable by
    whoever owns this repository."""
    if add_ons.is_public_tree():
        pytest.skip("this is the public tree — the excluded documents are gone by construction")
    tracked = set(_tracked())
    documents = [p for p in _excluded() if p.endswith(".md")]
    gone = sorted(p for p in documents if p not in tracked)
    assert not gone, f"these documents are excluded from the export AND deleted here: {gone}"
