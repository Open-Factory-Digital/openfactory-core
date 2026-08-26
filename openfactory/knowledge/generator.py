"""The deterministic module-map generator (Knowledge Layer, Phase 1 · §10).

DETERMINISTIC-FIRST is the whole point: this parses a repo with NOTHING but directory
structure + Python `ast` (imports/defs) + regex over TS/JS import/export statements + regex
over C#/.NET declarations and `.csproj` project references. There are ZERO LLM calls — the
map is cheap, exact, and safe to run on every merge (§10/§11), and the same repo state always
produces byte-identical YAML (see `bundle.write_bundle`).

What it emits, per source directory ("module"):
- `path`            — the directory, repo-relative.
- `purpose`         — one line, inferred from a dir README / package docstring / a JSDoc
                      block above an export / a C# `/// <summary>` / a `.csproj`
                      `<Description>` / the dir name. Inferred, never invented (§10 — the
                      fuzzy LLM slice is Phase 3).
- `key_files`       — the source files in the directory.
- `dependencies`    — other in-repo modules it imports (resolved from the import graph;
                      for .NET, from `<ProjectReference>`).
- `public_surface`  — exported top-level symbols (Python defs/classes/`__all__`; JS exports;
                      C# public types and members).
- `source`          — the anchor file + the commit it was generated from (the §7 link).

And — `survey_extensions` — what it did NOT read, per extension, with counts, PLUS every
directory it could not open at all. A map that covers 2 of 139 files and says nothing about
the other 137 reads as a COMPLETE map, and the next stack we have not taught it is discovered
by accident (C-49). The bundle declares its own blindness so the gap is visible before someone
relies on the map.

Best-effort throughout (ADR-house style): a file that will not parse is skipped with a
note, never a crash — a generation hiccup must degrade the map, not fail the caller.
"""

from __future__ import annotations

import ast
import logging
import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NamedTuple

from openfactory.knowledge.contracts import (
    Module,
    ModuleMap,
    SourceLink,
)

_log = logging.getLogger("openfactory.knowledge.generator")

# Source files we understand. Python is parsed with `ast` (robust); TS/JS and C# with regex
# (best-effort — a real TS/Roslyn parser is not worth a Phase-1 dependency).
_PY_SUFFIXES = {".py"}
_JS_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
_CS_SUFFIXES = {".cs"}
# .NET project files. They are SOURCES here, not just markers: they delimit the module (a
# `.csproj` globs `**/*.cs` beneath it, so the project — not the folder — is the real .NET
# module boundary) and they carry the in-repo dependency graph (`<ProjectReference>`). Being
# canonical sources also means an edit to one flips the bundle stale, which is right: adding
# a ProjectReference changes the map.
_PROJECT_SUFFIXES = {".csproj", ".fsproj", ".vbproj"}
_SOURCE_SUFFIXES = _PY_SUFFIXES | _JS_SUFFIXES | _CS_SUFFIXES | _PROJECT_SUFFIXES

# MSBuild's build output. `obj/` alone holds generated `.cs` (AssemblyInfo.cs,
# GlobalUsings.g.cs, .NETCoreApp,Version=v8.0.AssemblyAttributes.cs) — mapping those would
# fill a .NET repo's map with machine-written files and make every `dotnet build` look like
# a source change. Pruned ONLY next to a project file, because `bin/` is an ordinary source
# directory in plenty of non-.NET repos.
_DOTNET_OUTPUT_DIRS = {"obj", "bin"}

# The generator's own artefact. The extension survey must not count the YAML it is about to
# write, or the first build in any repo would report a `.yaml` delta against itself and cost
# a second no-op commit in the post-merge pipeline (§22). `bundle.py` aliases these names so
# the two cannot drift apart.
BUNDLE_MODULES_FILE = "modules.yaml"
BUNDLE_MANIFEST_FILE = "manifest.yaml"

# Directories that are never product code — skipped wholesale so the map stays about the
# codebase, not its tooling. Matched by exact directory NAME at any depth.
_SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "node_modules", ".venv", "venv", "env", ".env", "dist", "build", ".next", "coverage",
    ".tox", ".idea", ".vscode", "site-packages", ".claude",
    # NB: the generated bundle dir (`knowledge/`) is not listed — it holds only YAML, so it
    # never yields a module anyway, and listing it would wrongly skip a real source package
    # that happens to be named `knowledge/` (e.g. this framework's own openfactory/knowledge/).
    ".egg-info",  # matched as a substring too (see _is_skipped)
}

_PURPOSE_MAX = 200  # a purpose line is a signpost, not prose
_MAX_KEY_FILES = 40  # a module with hundreds of files: list the first N (sorted), note the rest


def _is_skipped_name(name: str) -> bool:
    """A single directory NAME that is never product code (exact skip-dir, or the `.egg-info`
    build-artifact suffix). Used to prune the walk at the shallowest point."""
    return name in _SKIP_DIRS or name.endswith(".egg-info")


def _is_skipped(rel_dir: Path) -> bool:
    """A directory is skipped if any of its path parts is a skip-dir (exact name, or the
    `.egg-info` build-artifact suffix)."""
    return any(_is_skipped_name(part) for part in rel_dir.parts)


def _posix(rel: Path) -> str:
    """Repo-relative path as POSIX text — stable regardless of the host OS separator."""
    return rel.as_posix()


def _module_name(rel_dir: Path) -> str:
    """A stable dotted id for a directory. The repo root ('.') is the sentinel '<root>'."""
    return "<root>" if rel_dir == Path(".") else ".".join(rel_dir.parts)


# --- purpose inference (deterministic) --------------------------------------------------

_README_NAMES = ("README.md", "README.rst", "README.txt", "README")


def _first_meaningful_line(text: str) -> str:
    """The first non-empty, non-heading-marker line of a doc — a human-written one-liner."""
    for raw in text.splitlines():
        line = raw.strip().lstrip("#").strip()
        if line and not line.startswith(("---", "===", "```")):
            return line
    return ""


def _first_docstring_line(py_source: str) -> str:
    """The first line of a Python module docstring (the module's own stated purpose)."""
    try:
        mod = ast.parse(py_source)
    except (SyntaxError, ValueError):
        return ""
    doc = ast.get_docstring(mod)
    if not doc:
        return ""
    return _first_meaningful_line(doc)


_JSDOC_BLOCK = re.compile(r"/\*\*(.*?)\*/", re.DOTALL)
# What must follow a JSDoc block for it to be a statement about the MODULE's surface. We do
# not accept just any `/** */` in the file: a licence header or an inline note about a private
# helper would then become the module's stated purpose, which is invention by accident.
_JS_AFTER_DOC = re.compile(r"\s*(?:export\b|module\.exports\b|declare\b)")


def _js_doc_purpose(text: str) -> str:
    """The first line of the JSDoc block that sits directly above an export.

    On a TS/React front — an SPFx web part, a component tree — there is normally no README per
    folder and no `__init__.py`, so before this every such module described itself by its own
    directory name ("src", "test"): a purpose line carrying zero information. The `/** … */`
    above the export is where a TS codebase actually writes its purpose, and it is a real
    string in a real file, so reading it keeps the deterministic rule intact."""
    for m in _JSDOC_BLOCK.finditer(text):
        if not _JS_AFTER_DOC.match(text, m.end()):
            continue
        for raw in m.group(1).splitlines():
            line = raw.strip().lstrip("*").strip()
            if line and not line.startswith("@"):  # @param/@returns are not a purpose
                return line
    return ""


_CS_XMLDOC = re.compile(r"^\s*///(.*)$")
_CS_SUMMARY = re.compile(r"<summary>(.*?)</summary>", re.DOTALL | re.IGNORECASE)
_XML_TAG = re.compile(r"<[^>]*>")
_WHITESPACE = re.compile(r"\s+")
# `<see cref="X"/>` and friends carry their subject in an ATTRIBUTE, not as element text, so
# blanket tag-stripping turns "Ver <see cref="AdmissaoService"/> para as regras" into "Ver para
# as regras" — a sentence with its noun deleted. cref links are pervasive in enterprise C#.
_XML_REF = re.compile(
    r"""<(?:see|seealso|paramref|typeparamref)\s[^>]*?(?:cref|name)\s*=\s*["']([^"']+)["'][^>]*>""",
    re.IGNORECASE,
)
# A cref is often prefixed with its member kind — `T:Flows.Admissao`, `M:Foo.Bar(System.Int32)`
_XML_REF_PREFIX = re.compile(r"^[A-Z]:")


def _xml_doc_text(raw: str) -> str:
    """Inner XML-doc text as one clean line: cross-references replaced by the identifier they
    name, remaining tags (`<c>`, `<para>`) stripped, whitespace collapsed. Every character of
    the result was read out of the file — nothing is rephrased. "" when nothing readable is
    left."""
    resolved = _XML_REF.sub(lambda m: _XML_REF_PREFIX.sub("", m.group(1)), raw)
    return _WHITESPACE.sub(" ", _XML_TAG.sub("", resolved)).strip()


def _cs_doc_summary(text: str) -> str:
    """The first `/// <summary>` in a C# file — C#'s docstring, and the .NET equivalent of the
    Python module docstring this generator has always read.

    Scanned per CONSECUTIVE `///` run rather than over the whole file, so an unterminated
    `<summary>` in one doc comment cannot splice itself onto a `</summary>` twenty lines
    below and manufacture a sentence nobody wrote."""
    block: list[str] = []
    for raw in text.splitlines():
        m = _CS_XMLDOC.match(raw)
        if m:
            block.append(m.group(1))
            continue
        if block:
            found = _CS_SUMMARY.search(" ".join(block))
            if found and _xml_doc_text(found.group(1)):
                return _xml_doc_text(found.group(1))
            block = []
    if block:
        found = _CS_SUMMARY.search(" ".join(block))
        if found:
            return _xml_doc_text(found.group(1))
    return ""


_CSPROJ_DESCRIPTION = re.compile(r"<Description>(.*?)</Description>", re.DOTALL | re.IGNORECASE)


def _csproj_description(text: str) -> str:
    """MSBuild's `<Description>` — the .NET project's own one-line statement of what it is
    (it ships as the NuGet package description). Describes the whole module, so it outranks
    any single type's `<summary>`."""
    m = _CSPROJ_DESCRIPTION.search(text)
    return _xml_doc_text(m.group(1)) if m else ""


def _humanize(name: str) -> str:
    """Last-resort purpose from the directory name — deterministic, low-signal but honest."""
    if name == "<root>":
        return "repository root"
    leaf = name.split(".")[-1].replace("_", " ").replace("-", " ").strip()
    return leaf or name


def _read(path: Path) -> str:
    """File text, or "" if it cannot be read. Purpose inference is best-effort by design: an
    unreadable candidate must fall through to the next source, never abort the module."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _entry_first(files: list[Path], names: tuple[str, ...]) -> list[Path]:
    """`files` reordered so a conventional entry point comes first (`index.ts` for JS, the way
    `__init__.py` already leads for Python) — the file whose doc comment describes the module
    rather than one arbitrary member of it."""
    lead = [f for f in files if f.name in names]
    return lead + [f for f in files if f.name not in names]


_JS_INDEX_NAMES = tuple(f"index{s}" for s in sorted(_JS_SUFFIXES))


def _infer_purpose(abs_dir: Path, rel_dir: Path, files: list[Path]) -> str:
    """Deterministic purpose, in priority order: a directory README, then the package
    `__init__.py` docstring, then the docstring of the (alphabetically) first Python module,
    then the JSDoc above an export, then the `.csproj` `<Description>`, then the first C#
    `/// <summary>`, then the humanized directory name.

    Never an LLM, never invented: every branch returns a real string read out of a real file,
    or falls through. That is what makes this artefact safe to refresh on every merge."""
    for name in _README_NAMES:
        readme = abs_dir / name
        if readme.is_file():
            line = _first_meaningful_line(_read(readme))
            if line:
                return line[:_PURPOSE_MAX]

    py_files = sorted(f for f in files if f.suffix in _PY_SUFFIXES)
    init = abs_dir / "__init__.py"
    ordered = ([init] if init.is_file() else []) + [f for f in py_files if f.name != "__init__.py"]
    for f in ordered:
        line = _first_docstring_line(_read(f))
        if line:
            return line[:_PURPOSE_MAX]

    for f in _entry_first(sorted(f for f in files if f.suffix in _JS_SUFFIXES), _JS_INDEX_NAMES):
        line = _js_doc_purpose(_read(f))
        if line:
            return line[:_PURPOSE_MAX]

    for f in sorted(f for f in files if f.suffix in _PROJECT_SUFFIXES):
        line = _csproj_description(_read(f))
        if line:
            return line[:_PURPOSE_MAX]

    for f in sorted(f for f in files if f.suffix in _CS_SUFFIXES):
        line = _cs_doc_summary(_read(f))
        if line:
            return line[:_PURPOSE_MAX]

    return _humanize(_module_name(rel_dir))[:_PURPOSE_MAX]


# --- Python AST extraction --------------------------------------------------------------


def _py_public_symbols(tree: ast.Module) -> list[str]:
    """Top-level defs/classes not prefixed '_', plus everything named in `__all__` if the
    module declares one (the module's own statement of its public surface)."""
    explicit: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "__all__" in targets and isinstance(node.value, (ast.List, ast.Tuple)):
                explicit = [
                    el.value for el in node.value.elts
                    if isinstance(el, ast.Constant) and isinstance(el.value, str)
                ]
    if explicit:
        return explicit
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                out.append(node.name)
    return out


def _py_imports(tree: ast.Module) -> list[tuple[str, int]]:
    """Every import as (dotted_module, relative_level). `import a.b` → ('a.b', 0);
    `from .x import y` → ('.x' collapsed to module 'x' with level 1); `from . import y`
    → ('', 1). The level drives relative-import resolution against the file's package."""
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((alias.name, 0))
        elif isinstance(node, ast.ImportFrom):
            out.append((node.module or "", node.level or 0))
    return out


def _resolve_python_import(
    dotted: str, level: int, file_rel: Path, py_modules: dict[str, Path]
) -> str | None:
    """Resolve an import to the in-repo MODULE (directory) that owns it, or None if it is a
    third-party/stdlib import. `py_modules` maps a dotted package path → its directory.

    Absolute: 'openfactory.adapters.agent.base' → longest package prefix present in `py_modules`.
    Relative (level>0): walk up `level-1` dirs from the file's package, then descend the
    dotted tail, and map the resulting directory back to a module."""
    if level and level > 0:
        base = file_rel.parent
        for _ in range(level - 1):
            base = base.parent
        if dotted:
            base = base / Path(*dotted.split("."))
        target = _posix(base)
        # the import may name a module file inside the package dir; either way credit its dir
        if target in py_modules:
            return target
        # a relative import of a sibling module file → its directory is the package itself
        parent = _posix(base.parent) if base != Path(".") else "."
        return parent if parent in py_modules else None

    if not dotted:
        return None
    parts = dotted.split(".")
    # longest matching package prefix wins (openfactory.adapters.agent before openfactory.adapters)
    for i in range(len(parts), 0, -1):
        cand = "/".join(parts[:i])
        if cand in py_modules:
            return cand
    # SRC-LAYOUT fallback. In `src/`-layout repos (very common) the import `mypkg.foo` maps to
    # the directory `src/mypkg/foo`, which no prefix match can ever find — so without this every
    # such repo's `dependencies` come out silently EMPTY, and the map loses the import graph
    # that is most of its value. Match the dotted path as a path SUFFIX instead, and only accept
    # an UNAMBIGUOUS hit (exactly one candidate directory): a guess would invent a dependency,
    # and an invented fact is worse than a missing one (§7).
    for i in range(len(parts), 0, -1):
        tail = "/".join(parts[:i])
        hits = [d for d in py_modules if d == tail or d.endswith("/" + tail)]
        if len(hits) == 1:
            return hits[0]
        if hits:  # ambiguous at this depth — a shorter tail can only be more ambiguous
            return None
    return None


# --- JS/TS extraction (best-effort regex) -----------------------------------------------

_JS_EXPORT = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:async\s+)?"
    r"(?:function\*?|class|const|let|var|enum|interface|type)\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)
_JS_EXPORT_LIST = re.compile(r"export\s*\{([^}]*)\}")
_JS_IMPORT_FROM = re.compile(r"""(?:import|export)[^;\n]*?from\s*['"]([^'"]+)['"]""")
_JS_REQUIRE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")


def _js_public_symbols(text: str) -> list[str]:
    """Exported symbols from `export const/function/class/...` and `export { a, b as c }`."""
    out = list(_JS_EXPORT.findall(text))
    for block in _JS_EXPORT_LIST.findall(text):
        for item in block.split(","):
            name = item.strip().split(" as ")[-1].strip()
            if re.fullmatch(r"[A-Za-z_$][\w$]*", name or ""):
                out.append(name)
    return out


def _js_import_specifiers(text: str) -> list[str]:
    """Every module specifier this file imports/requires (relative and bare)."""
    return list(_JS_IMPORT_FROM.findall(text)) + list(_JS_REQUIRE.findall(text))


def _resolve_js_import(spec: str, file_rel: Path, source_dirs: set[str]) -> str | None:
    """Resolve a RELATIVE js/ts specifier ('./x', '../y') to the in-repo directory that
    owns it. Bare specifiers ('react', '@scope/pkg') are external → None. Extension and
    '/index' suffixes are stripped; we credit the containing directory of the target."""
    if not spec.startswith("."):
        return None
    target = (file_rel.parent / spec).as_posix()
    # normalize '..' segments
    try:
        norm = Path(target)
        norm = Path(*_normalize_parts(norm.parts))
    except (ValueError, IndexError):
        return None
    cand = norm.as_posix()
    # './comp' may point at a file (comp.ts) or a dir (comp/index.ts); the owning module is
    # the directory: if the resolved path itself is a known source dir, use it, else its parent.
    if cand in source_dirs:
        return cand
    parent = norm.parent.as_posix()
    return parent if parent in source_dirs else None


# --- C# / .NET extraction (best-effort regex) -------------------------------------------

_CS_NAMESPACE = re.compile(r"^\s*namespace\s+([A-Za-z_][\w.]*)")
_CS_TYPE = re.compile(
    r"^[ \t]*public\s+(?:(?:static|sealed|abstract|partial|unsafe|readonly|ref)\s+)*"
    r"(?:record\s+(?:class|struct)|class|record|struct|interface|enum)\s+"
    r"([A-Za-z_]\w*)"
)
# A public member: `public <modifiers> <return type> Name(` / `{` (property) / `=` (const or
# expression body) / `;` / end of line (property with the brace on the next line). The middle
# is lazy and forbids `=;(){}` so it cannot swallow a body, and this is only ever tried on
# lines that did NOT declare a type — otherwise `public static class Admissao` would report
# `Admissao` a second time as a member.
_CS_MEMBER = re.compile(
    r"^[ \t]*public\s+[^=;(){}\r\n]*?\b([A-Za-z_]\w*)\s*(?:<[^<>()]*>\s*)?(?:\(|\{|=>|=|;|$)"
)


def _cs_public_symbols(text: str) -> list[str]:
    """Public C# surface: types as `Namespace.Type`, members as bare names.

    Types carry their namespace because that is what a caller needs to `using` them; members
    stay bare because attributing a member to its enclosing type would require brace counting,
    and brace counting over raw C# is a lie waiting to happen — an interpolated string
    (`$"{a}R$ {b:D2}"`) or a `'{'` char literal desynchronises it, and a wrong qualifier is a
    fact this map invented. A bare name is the search key an agent actually needs.

    Constructors are dropped (a member whose name is a type declared in the same file): they
    are noise here, and the type is already listed."""
    namespace = ""
    types: list[str] = []
    type_names: set[str] = set()
    members: list[str] = []
    for line in text.splitlines():
        ns = _CS_NAMESPACE.match(line)
        if ns:
            namespace = ns.group(1)
            continue
        t = _CS_TYPE.match(line)
        if t:
            type_names.add(t.group(1))
            types.append(f"{namespace}.{t.group(1)}" if namespace else t.group(1))
            continue
        m = _CS_MEMBER.match(line)
        if m:
            members.append(m.group(1))
    return types + [m for m in members if m not in type_names]


_CSPROJ_REFERENCE = re.compile(
    r"""<ProjectReference\s[^>]*?Include\s*=\s*["']([^"']+)["']""", re.IGNORECASE
)


def _csproj_project_references(text: str) -> list[str]:
    """The `Include=` paths of every `<ProjectReference>` — .NET's in-repo import graph.

    This is the exact analogue of a relative JS import, and it is the RIGHT signal at this
    map's granularity: since a `.csproj` owns every `.cs` beneath it, `using` statements
    between those files are intra-module and would resolve to the module itself anyway. What
    crosses a module boundary in .NET is a project reference."""
    return list(_CSPROJ_REFERENCE.findall(text))


def _resolve_project_reference(include: str, file_rel: Path, source_dirs: set[str]) -> str | None:
    """Resolve a `<ProjectReference Include="…">` to the in-repo module that owns the
    referenced project, or None if it points outside the repo's mapped source dirs.

    MSBuild writes these with WINDOWS separators (`..\\..\\src\\Foo\\Foo.csproj`) even in
    repos that only ever build on Linux, so the separator is normalised before resolving —
    without that, every .NET dependency edge on this platform silently resolved to nothing."""
    spec = include.strip().replace("\\", "/")
    if not spec:
        return None
    parts = _normalize_parts((file_rel.parent / spec).parts)
    if not parts:
        return None
    owner = Path(*parts).parent.as_posix()
    return owner if owner in source_dirs else None


def _normalize_parts(parts: tuple[str, ...]) -> list[str]:
    """Collapse '.' and '..' in a path's parts (pure-lexical, no filesystem access)."""
    stack: list[str] = []
    for p in parts:
        if p == "." or p == "":
            continue
        if p == "..":
            if stack:
                stack.pop()
        else:
            stack.append(p)
    return stack


# --- the generator ----------------------------------------------------------------------


def _walk_files(
    repo: Path, *, on_error: Callable[[OSError], None] | None = None
) -> Iterator[tuple[Path, list[str]]]:
    """(repo-relative dir, filenames) for every directory that is not pruned. THE single
    pruning implementation — the module map and the extension survey must agree on what the
    repository contains, or the survey's "files read / files not read" numbers describe two
    different repositories.

    PRUNES during the walk rather than filtering after it. That is the difference between
    touching a real client repo's `node_modules`/`.git` (tens of thousands of entries, on the
    per-job critical path — this runs on every freshness check) and never descending into
    them at all. Same result, bounded cost.

    `on_error` is handed straight to `os.walk`. Passing it MATTERS: `os.walk`'s default is to
    SWALLOW every `OSError` — a directory it cannot open, a `repo` that is not a directory, a
    `repo` that does not exist at all — and simply yield fewer entries. So a repository the
    process cannot read is indistinguishable from an empty one, which is exactly the collapse
    this module's survey exists to prevent. The survey passes a recorder; the map path leaves
    it None deliberately (its answer is the module list, and a partial map is still useful) —
    the survey is where the blindness is DECLARED."""
    for dirpath, dirnames, filenames in os.walk(repo, followlinks=False, onerror=on_error):
        rel_dir = Path(dirpath).relative_to(repo)
        # prune in place: os.walk will not descend into what we remove from `dirnames`
        dirnames[:] = [d for d in dirnames if not _is_skipped_name(d)]
        if any(Path(f).suffix in _PROJECT_SUFFIXES for f in filenames):
            dirnames[:] = [d for d in dirnames if d not in _DOTNET_OUTPUT_DIRS]
        yield rel_dir, filenames


def _nearest_project_root(rel_dir: Path, roots: set[Path]) -> Path | None:
    """The nearest ancestor-or-self directory holding a `.csproj`, or None."""
    cur = rel_dir
    while True:
        if cur in roots:
            return cur
        if cur == Path("."):
            return None
        cur = cur.parent


def _iter_source_dirs(repo: Path) -> dict[Path, list[Path]]:
    """Map each non-skipped directory that CONTAINS source files → its source files (as
    repo-relative paths). Sorted deterministically by the caller.

    .NET is grouped by PROJECT, not by folder: every `.cs` under a `.csproj` is folded into
    that project's directory, because that is what the project file means — the default glob
    is `**/*.cs`, so `src/Api/Models` and `src/Api/Services` are two folders of ONE compiled
    unit, not two modules. Folding only moves `.cs` files, so a `web/` of TypeScript nested
    inside a .NET project stays its own module."""
    dirs: dict[Path, list[Path]] = {}
    project_roots: set[Path] = set()
    cs_by_dir: dict[Path, list[Path]] = {}
    for rel_dir, filenames in _walk_files(repo):
        for name in filenames:
            suffix = Path(name).suffix
            if suffix not in _SOURCE_SUFFIXES:
                continue
            rel = rel_dir / name if rel_dir != Path(".") else Path(name)
            if suffix in _PROJECT_SUFFIXES:
                project_roots.add(rel_dir)
                dirs.setdefault(rel_dir, []).append(rel)
            elif suffix in _CS_SUFFIXES:
                cs_by_dir.setdefault(rel_dir, []).append(rel)
            else:
                dirs.setdefault(rel_dir, []).append(rel)
    for rel_dir, files in cs_by_dir.items():
        owner = _nearest_project_root(rel_dir, project_roots) or rel_dir
        dirs.setdefault(owner, []).extend(files)
    return dirs


class ExtensionSurvey(NamedTuple):
    """What the generator read and what it did not, by extension. `unread` is sorted by
    descending count then extension, so the biggest blind spot is first and the serialization
    stays byte-stable.

    `unreadable` is the OTHER kind of blindness, and the counts above cannot express it: the
    repo-relative directories the walk could not open. Empty list = the walk completed, every
    directory was entered — a measured answer, not an assumed one."""

    files_read: int
    files_unread: int
    unread: list[tuple[str, int]]
    unreadable: list[str]


def _is_generated_bundle_file(name: str, filenames: list[str]) -> bool:
    """True for `modules.yaml`/`manifest.yaml` sitting together — i.e. this generator's own
    output, which it must not count as an unread file of the repository."""
    return name in (BUNDLE_MODULES_FILE, BUNDLE_MANIFEST_FILE) and (
        BUNDLE_MODULES_FILE in filenames and BUNDLE_MANIFEST_FILE in filenames
    )


def survey_extensions(repo_path: Path) -> ExtensionSurvey:
    """Count every file in the repo and split it into "the map read this" vs "the map did not
    understand this extension".

    THIS IS THE PART THAT STOPS THE GAP RECURRING (C-49). Before it, a repo whose stack the
    generator had never been taught produced an EMPTY module map that looked exactly like a
    repo with no code — an unread stack read as an absent one, which is the house's most
    expensive defect class. Declaring the extensions and their counts turns silence into a
    statement a human can act on.

    Deliberately NOT filtered to a curated list of "code" extensions: the whole point is the
    stack nobody has taught it yet, and a curated filter would drop exactly that file. `.md`
    and `.png` show up too; that is the honest report, and the reader can judge.

    AND it declares the directories it could not OPEN. The extension counts alone cannot say
    that: a directory `os.walk` fails on contributes nothing to either side of the split, so a
    repo with an unreadable vendored subtree — or a `repo_path` that does not exist at all, or
    points at a file — surveyed to `files_unread=0, unread=[]`, i.e. "I read this repository
    and understood every file in it". That is the house's most expensive defect verbatim
    (could-not-read reading as read-and-empty), living inside the function written to stop it.
    A caller can now tell the two apart, because `unreadable` is non-empty in every one of
    those cases and empty only when the walk really did complete."""
    repo = Path(repo_path).expanduser().resolve()
    read = 0
    unread: dict[str, int] = {}
    unreadable: set[str] = set()

    def _record(exc: OSError) -> None:
        """`os.walk` reports a directory it could not enter here and then carries on. The
        failing path is on the exception; when the ROOT is what failed it equals `repo`, which
        `relative_to` renders as '.' — the honest way to say "I could not open the repository
        itself"."""
        raw = getattr(exc, "filename", None)
        _log.warning(
            "knowledge: could not read %s (%s) — declaring it unreadable, NOT empty",
            raw or repo, exc,
        )
        if not raw:  # no path on the error: the root is the only thing it can have been
            unreadable.add(".")
            return
        try:
            unreadable.add(Path(raw).relative_to(repo).as_posix())
        except ValueError:  # outside the repo (should not happen) — name it verbatim
            unreadable.add(str(raw))

    for _rel_dir, filenames in _walk_files(repo, on_error=_record):
        for name in filenames:
            if _is_generated_bundle_file(name, filenames):
                continue
            suffix = Path(name).suffix
            if suffix in _SOURCE_SUFFIXES:
                read += 1
            else:
                # "" is a real answer here — Makefile, Dockerfile, LICENSE have no extension
                unread[suffix] = unread.get(suffix, 0) + 1
    ordered = sorted(unread.items(), key=lambda kv: (-kv[1], kv[0]))
    return ExtensionSurvey(
        files_read=read,
        files_unread=sum(unread.values()),
        unread=ordered,
        unreadable=sorted(unreadable),
    )


def canonical_source_files(repo_path: Path) -> list[Path]:
    """Every source file the map is derived from, as repo-relative paths, sorted. This is
    the exact set the staleness manifest checksums (§12) — one source of truth for "which
    files feed the bundle", shared by the generator and the checksum pass."""
    repo = Path(repo_path).expanduser().resolve()
    files = [f for group in _iter_source_dirs(repo).values() for f in group]
    return sorted(files, key=lambda p: p.as_posix())


def build_module_map(repo_path: Path, *, commit: str = "") -> ModuleMap:
    """Parse `repo_path` deterministically and return the module map. `commit` is stamped
    into every source link (pass the repo HEAD; "" when not a git repo). No LLM, no clock,
    no network — same input, identical output."""
    repo = Path(repo_path).expanduser().resolve()
    dirs = _iter_source_dirs(repo)

    # A directory → its dotted-package path, for resolving in-repo Python imports. Both the
    # POSIX dir path ('openfactory/adapters/agent') and its dotted form must be resolvable, so we
    # key the resolver by POSIX path and translate dotted imports to POSIX candidates.
    py_module_dirs = {
        _posix(rel_dir) for rel_dir in dirs
        if any(f.suffix in _PY_SUFFIXES for f in dirs[rel_dir])
    }
    py_modules = {p: Path(p) for p in py_module_dirs}
    source_dir_posix = {_posix(rel_dir) for rel_dir in dirs}

    modules: list[Module] = []
    for rel_dir in dirs:
        files = sorted(dirs[rel_dir], key=lambda p: p.as_posix())
        abs_dir = repo / rel_dir
        deps: set[str] = set()
        public: set[str] = set()

        for rel_file in files:
            abs_file = repo / rel_file
            try:
                text = abs_file.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:  # unreadable file: skip it, keep the module
                _log.warning("knowledge: could not read %s (%s)", rel_file, exc)
                continue

            if rel_file.suffix in _PY_SUFFIXES:
                try:
                    tree = ast.parse(text)
                except (SyntaxError, ValueError) as exc:
                    _log.warning("knowledge: skipping unparseable %s (%s)", rel_file, exc)
                    continue
                public.update(_py_public_symbols(tree))
                for dotted, level in _py_imports(tree):
                    owner = _resolve_python_import(dotted, level, rel_file, py_modules)
                    if owner and owner != _posix(rel_dir):
                        deps.add(_dir_to_name(owner))
            elif rel_file.suffix in _CS_SUFFIXES:
                public.update(_cs_public_symbols(text))
            elif rel_file.suffix in _PROJECT_SUFFIXES:
                for include in _csproj_project_references(text):
                    owner = _resolve_project_reference(include, rel_file, source_dir_posix)
                    if owner and owner != _posix(rel_dir):
                        deps.add(_dir_to_name(owner))
            else:  # js/ts
                public.update(_js_public_symbols(text))
                for spec in _js_import_specifiers(text):
                    owner = _resolve_js_import(spec, rel_file, source_dir_posix)
                    if owner and owner != _posix(rel_dir):
                        deps.add(_dir_to_name(owner))

        key_files = [f.as_posix() for f in files][:_MAX_KEY_FILES]
        anchor = _anchor_file(rel_dir, files)
        modules.append(
            Module(
                name=_module_name(rel_dir),
                path=_posix(rel_dir),
                purpose=_infer_purpose(abs_dir, rel_dir, [repo / f for f in files]),
                key_files=key_files,
                file_count=len(files),
                dependencies=sorted(deps),
                public_surface=sorted(public),
                source=SourceLink(file=anchor, commit=commit),
            )
        )

    modules.sort(key=lambda m: m.name)
    return ModuleMap(version="1", source_commit=commit, modules=modules)


def _dir_to_name(posix_dir: str) -> str:
    """Module name for a resolved POSIX directory (mirrors `_module_name`)."""
    return "<root>" if posix_dir in (".", "") else posix_dir.replace("/", ".")


def _anchor_file(rel_dir: Path, files: list[Path]) -> str:
    """The module's ground-truth anchor: the package `__init__.py` if present, else the
    (alphabetically) first source file. This is what a consumer opens first to verify (§7)."""
    for f in files:
        if f.name == "__init__.py":
            return f.as_posix()
    return files[0].as_posix() if files else _posix(rel_dir)
