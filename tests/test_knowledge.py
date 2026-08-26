"""Knowledge Layer, Phase 1 — the deterministic module map (docs/knowledge-layer.md §9/§10/§12).

Covers: deterministic generation over a fixture tree (same input → identical YAML), module /
dependency / public-surface extraction (Python AST + JS/TS regex + C#/.csproj regex), purpose
inference from every source it accepts, the declared coverage survey (C-49 — what the generator
did NOT read), the manifest checksums, the staleness + orphan checks, and the injection wiring
(flag off = unchanged; flag on = map present).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from openfactory.knowledge import (
    build_bundle,
    build_module_map,
    canonical_source_files,
    derived_key,
    is_stale,
    is_trustworthy,
    orphan_links,
    read_bundle,
    render_module_map,
    survey_extensions,
    write_bundle,
)
from openfactory.knowledge.bundle import _dump


def _fixture_repo(root: Path) -> Path:
    """A tiny polyglot repo: a python package (core) that another package (app) imports, a
    dir README, and a TS module that relatively-imports a sibling."""
    (root / "core").mkdir(parents=True)
    (root / "core" / "__init__.py").write_text('"""Core domain — the pure rules."""\n')
    (root / "core" / "rules.py").write_text(
        "SECRET = 1\n\n\ndef decide(x):\n    return x\n\n\nclass Engine:\n    pass\n\n\ndef _hidden():\n    pass\n"
    )
    (root / "app").mkdir(parents=True)
    (root / "app" / "README.md").write_text("# App\nHTTP entrypoints for the service.\n")
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "main.py").write_text(
        "from core.rules import decide\nimport os\n\n\ndef handler():\n    return decide(os.getpid())\n"
    )
    (root / "web").mkdir(parents=True)
    (root / "web" / "util.ts").write_text("export const clamp = (n) => n;\n")
    (root / "web" / "view.tsx").write_text(
        "import { clamp } from './util';\nimport React from 'react';\nexport function View() { return clamp(1); }\n"
    )
    return root


def test_module_extraction(tmp_path: Path):
    m = build_module_map(_fixture_repo(tmp_path), commit="abc123")
    by_name = {mod.name: mod for mod in m.modules}

    assert set(by_name) == {"core", "app", "web"}

    core = by_name["core"]
    assert core.path == "core"
    assert core.purpose == "Core domain — the pure rules."  # from the package docstring
    # public surface = top-level non-underscore defs/classes; _hidden and SECRET excluded
    assert core.public_surface == ["Engine", "decide"]
    assert core.dependencies == []  # core imports nothing in-repo
    assert core.source.file == "core/__init__.py" and core.source.commit == "abc123"


def test_dependency_and_readme_purpose(tmp_path: Path):
    m = build_module_map(_fixture_repo(tmp_path), commit="abc123")
    app = next(x for x in m.modules if x.name == "app")
    # README wins over the (empty) __init__ docstring for purpose
    assert app.purpose == "App"
    # app/main.py imports `core.rules` → the map credits the `core` module (not stdlib `os`)
    assert app.dependencies == ["core"]


def test_js_ts_extraction(tmp_path: Path):
    m = build_module_map(_fixture_repo(tmp_path), commit="c")
    web = next(x for x in m.modules if x.name == "web")
    assert "clamp" in web.public_surface and "View" in web.public_surface
    # './util' resolves in-repo (same dir → self, excluded); 'react' is external (excluded)
    assert web.dependencies == []


def test_generation_is_deterministic(tmp_path: Path):
    repo = _fixture_repo(tmp_path)
    a = build_bundle(repo, commit="abc123", generated_at="2026-07-24T00:00:00Z")
    b = build_bundle(repo, commit="abc123", generated_at="2026-07-24T00:00:00Z")
    # byte-identical serialization is the Phase-1 non-negotiable
    assert _dump(a.model_dump(mode="json")) == _dump(b.model_dump(mode="json"))


def test_manifest_checksums_cover_every_source(tmp_path: Path):
    bundle = build_bundle(_fixture_repo(tmp_path), commit="x", generated_at="t")
    files = {c.file for c in bundle.manifest.checksums}
    # every source file is checksummed; the READMEs / yaml are not "sources"
    assert files == {
        "core/__init__.py", "core/rules.py",
        "app/__init__.py", "app/main.py",
        "web/util.ts", "web/view.tsx",
    }
    assert all(len(c.sha256) == 64 for c in bundle.manifest.checksums)


def test_staleness_detects_edits_and_additions(tmp_path: Path):
    repo = _fixture_repo(tmp_path)
    bundle = build_bundle(repo, commit="x", generated_at="t")
    assert is_stale(bundle, repo) is False  # freshly built → fresh

    # editing a tracked source flips it stale (checksum mismatch)
    (repo / "core" / "rules.py").write_text("def decide(x):\n    return x + 1\n")
    assert is_stale(bundle, repo) is True

    # a NEW source (map coverage now incomplete) is also stale
    bundle2 = build_bundle(repo, commit="x", generated_at="t")
    (repo / "core" / "extra.py").write_text("def more():\n    return 1\n")
    assert is_stale(bundle2, repo) is True


def test_freshness_ignores_the_commit_stamp(tmp_path: Path):
    """A bundle generated at commit X is COMMITTED, which makes commit Y — so its stamp is one
    commit behind HEAD by construction, forever. Freshness must therefore come from the sources
    alone: a stale-looking stamp over identical sources is still FRESH, or the map would never
    be served once in the persist-per-commit model (§22)."""
    repo = _fixture_repo(tmp_path)
    bundle = build_bundle(repo, commit="commit-X", generated_at="t")
    # the tree has since moved to commit Y (only the knowledge/ yaml changed — no source did)
    assert bundle.manifest.source_commit == "commit-X"
    assert is_stale(bundle, repo) is False
    assert is_trustworthy(bundle, repo) is True


def test_regeneration_is_a_noop_when_only_the_stamps_moved(tmp_path: Path):
    """The Phase-2 loop killer: regenerating with a new commit/timestamp but the SAME sources
    must write nothing, so the post-merge pipeline has nothing to commit and cannot re-trigger
    itself forever (build@X → commit Y → build@Y → commit Z → …)."""
    repo = _fixture_repo(tmp_path)
    first = build_bundle(repo, commit="X", generated_at="t1")
    assert write_bundle(first, repo) is not None  # first write lands
    before = (repo / "knowledge" / "manifest.yaml").read_text()

    # same sources, different provenance stamps → nothing to write
    again = build_bundle(repo, commit="Y", generated_at="t2")
    assert derived_key(again) == derived_key(first)
    assert write_bundle(again, repo) is None
    assert (repo / "knowledge" / "manifest.yaml").read_text() == before  # bytes untouched

    # a REAL source change does write
    (repo / "core" / "rules.py").write_text("def decide(x):\n    return x + 2\n")
    changed = build_bundle(repo, commit="Z", generated_at="t3")
    assert derived_key(changed) != derived_key(first)
    assert write_bundle(changed, repo) is not None


def test_src_layout_dependencies_resolve(tmp_path: Path):
    """`src/`-layout repos import `mypkg.foo` while the directory is `src/mypkg/foo` — no prefix
    match can find that, so without the suffix fallback every such repo's import graph (most of
    the map's value) came out silently empty."""
    (tmp_path / "src" / "mypkg" / "core").mkdir(parents=True)
    (tmp_path / "src" / "mypkg" / "__init__.py").write_text("")
    (tmp_path / "src" / "mypkg" / "core" / "__init__.py").write_text("")
    (tmp_path / "src" / "mypkg" / "core" / "rules.py").write_text("def decide():\n    return 1\n")
    (tmp_path / "src" / "mypkg" / "api").mkdir(parents=True)
    (tmp_path / "src" / "mypkg" / "api" / "__init__.py").write_text("")
    (tmp_path / "src" / "mypkg" / "api" / "main.py").write_text(
        "from mypkg.core.rules import decide\n\n\ndef go():\n    return decide()\n"
    )
    m = build_module_map(tmp_path, commit="c")
    api = next(x for x in m.modules if x.name.endswith("api"))
    assert api.dependencies == ["src.mypkg.core"]


def test_skipped_dirs_are_pruned_not_mapped(tmp_path: Path):
    """node_modules & friends must never reach the map — and are pruned during the walk, so a
    huge vendored tree costs nothing on the per-job freshness check."""
    repo = _fixture_repo(tmp_path)
    (repo / "node_modules" / "left-pad").mkdir(parents=True)
    (repo / "node_modules" / "left-pad" / "index.js").write_text("module.exports = 1;\n")
    m = build_module_map(repo, commit="c")
    assert not any("node_modules" in mod.path for mod in m.modules)
    bundle = build_bundle(repo, commit="c", generated_at="t")
    assert not any("node_modules" in c.file for c in bundle.manifest.checksums)


def test_key_files_cap_is_disclosed(tmp_path: Path):
    """A capped key-file list must say so — an under-reported module reads as a complete one,
    and the agent concludes files it needs don't exist."""
    (tmp_path / "big").mkdir()
    for i in range(50):
        (tmp_path / "big" / f"m{i:02d}.py").write_text("def f():\n    return 1\n")
    bundle = build_bundle(tmp_path, commit="c", generated_at="t")
    big = next(x for x in bundle.module_map.modules if x.name == "big")
    assert len(big.key_files) == 40 and big.file_count == 50
    assert "+10 more not listed" in render_module_map(bundle)


def test_orphan_link_detection(tmp_path: Path):
    repo = _fixture_repo(tmp_path)
    bundle = build_bundle(repo, commit="x", generated_at="t")
    assert orphan_links(bundle, repo) == []  # every source link resolves

    # delete a module's anchor + files → its links become orphans
    (repo / "core" / "__init__.py").unlink()
    (repo / "core" / "rules.py").unlink()
    orphans = orphan_links(bundle, repo)
    assert "core/__init__.py" in orphans and "core/rules.py" in orphans


def test_symbol_scoped_orphan(tmp_path: Path):
    """A symbol-scoped source link is an orphan once the symbol leaves the file."""
    from openfactory.knowledge.contracts import (
        BundleManifest,
        KnowledgeBundle,
        Module,
        ModuleMap,
        SourceLink,
    )

    (tmp_path / "m.py").write_text("def present():\n    pass\n")
    bundle = KnowledgeBundle(
        manifest=BundleManifest(),
        module_map=ModuleMap(modules=[
            Module(name="m", path=".", purpose="p", key_files=["m.py"],
                   source=SourceLink(file="m.py", symbol="present", commit="x")),
            Module(name="g", path=".", purpose="p", key_files=["m.py"],
                   source=SourceLink(file="m.py", symbol="gone", commit="x")),
        ]),
    )
    orphans = orphan_links(bundle, tmp_path)
    assert "m.py::gone" in orphans and "m.py::present" not in orphans


def test_roundtrip_write_read(tmp_path: Path):
    repo = _fixture_repo(tmp_path)
    bundle = build_bundle(repo, commit="x", generated_at="t")
    dest = write_bundle(bundle, repo)
    assert (dest / "modules.yaml").is_file() and (dest / "manifest.yaml").is_file()

    loaded = read_bundle(repo)
    assert loaded is not None
    assert [m.name for m in loaded.module_map.modules] == [m.name for m in bundle.module_map.modules]
    assert is_trustworthy(loaded, repo) is True


def test_read_missing_or_corrupt_bundle_degrades(tmp_path: Path):
    assert read_bundle(tmp_path) is None  # no bundle at all
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "modules.yaml").write_text("{ this: is: not: valid")
    (tmp_path / "knowledge" / "manifest.yaml").write_text("also broken: [")
    assert read_bundle(tmp_path) is None  # corrupt → None, not a crash


def test_render_states_ground_truth(tmp_path: Path):
    bundle = build_bundle(_fixture_repo(tmp_path), commit="abc123def456", generated_at="t")
    text = render_module_map(bundle)
    assert "ground truth" in text.lower() and "verify" in text.lower()
    assert "abc123def456" in text  # the commit is surfaced for traceability
    assert "### core" in text and "purpose:" in text


def test_generator_never_crashes_on_bad_source(tmp_path: Path):
    """A syntactically broken file is skipped, not fatal — the rest of the map still builds."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text('"""Pkg."""\n')
    (tmp_path / "pkg" / "broken.py").write_text("def (:::\n")  # invalid python
    (tmp_path / "pkg" / "ok.py").write_text("def works():\n    pass\n")
    m = build_module_map(tmp_path, commit="x")
    pkg = next(x for x in m.modules if x.name == "pkg")
    assert "works" in pkg.public_surface  # the good file was still parsed


# --- the stacks in the product corpus (C-49) --------------------------------------------
#
# Before this, `sdlc knowledge build` measured: platform 35 modules, fx-ado 2, fx-dsk-ui 2 with
# purpose = the FOLDER NAME, and fx-dsk-flows / fx-dotnet / dotnet-func ZERO modules over 137
# files. Client 2 is .NET 8 + SPFx, so the whole "the map saves you tokens" claim was worth
# nothing there — and an empty map looked exactly like an empty repo.


def test_jsdoc_above_an_export_is_the_purpose(tmp_path: Path):
    """A TS/React front has no per-folder README and no `__init__.py`, so every module used to
    describe itself by its directory name ("src", "test") — a purpose line carrying zero
    information. The `/** … */` above the export is where a TS codebase states its purpose."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "PainelAdmissao.tsx").write_text(
        "import * as React from 'react';\n\n"
        "/**\n * Painel de admissão do colaborador (ACM.CA.Deskline.UI).\n * @param props nada\n */\n"
        "export const PainelAdmissao = () => null;\n"
    )
    m = build_module_map(tmp_path, commit="c")
    src = next(x for x in m.modules if x.name == "src")
    assert src.purpose == "Painel de admissão do colaborador (ACM.CA.Deskline.UI)."
    assert "PainelAdmissao" in src.public_surface


def test_index_ts_states_the_module_purpose_before_any_other_file(tmp_path: Path):
    """`index.ts` is a JS package's entry point — the `__init__.py` of that world, and the file
    whose doc describes the MODULE. Alphabetical order would hand the purpose to whichever
    component sorts first, so a folder of ten components would be described by component #1."""
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "Alpha.tsx").write_text(
        "/** One card in the grid. */\nexport const Alpha = () => null;\n"
    )
    (tmp_path / "ui" / "index.ts").write_text(
        "/** Componentes do painel de admissão (ACM.CA.Deskline.UI). */\n"
        "export { Alpha } from './Alpha';\n"
    )
    m = build_module_map(tmp_path, commit="c")
    ui = next(x for x in m.modules if x.name == "ui")
    assert ui.purpose == "Componentes do painel de admissão (ACM.CA.Deskline.UI)."


def test_a_block_comment_that_is_not_above_an_export_is_not_a_purpose(tmp_path: Path):
    """The negative twin: accepting ANY `/** */` would make a licence header or a note about a
    private helper the module's stated purpose — invention by accident, in an artefact whose
    whole contract is that it never invents. No qualifying doc → fall back to the dir name."""
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "app.ts").write_text(
        "/**\n * Copyright (c) 2026 Acme Corp. All rights reserved.\n */\n"
        "import { x } from './x';\n\n"
        "/** internal only */\nfunction helper() { return x; }\n\n"
        "export const run = () => helper();\n"
    )
    m = build_module_map(tmp_path, commit="c")
    web = next(x for x in m.modules if x.name == "web")
    assert web.purpose == "web"  # the honest low-signal fallback, not the copyright line


def _dotnet_repo(root: Path) -> Path:
    """A .NET 8 solution shaped like the client's: a project whose sources live in nested
    folders, an xunit project referencing it with WINDOWS separators, and MSBuild's `obj/`
    output sitting next to both."""
    src = root / "src" / "Flows"
    (src / "Domain").mkdir(parents=True)
    (src / "Flows.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n'
        "    <TargetFramework>net8.0</TargetFramework>\n  </PropertyGroup>\n</Project>\n"
    )
    (src / "Admissao.cs").write_text(
        "namespace Flows;\n\n"
        "/// <summary>Regras da orquestração durável de admissão "
        "(ACM.CA.Deskline.Flows).</summary>\n"
        "public static class Admissao\n{\n"
        "    /// <summary>Quais etapas faltam.</summary>\n"
        "    public static IReadOnlyList<string> EtapasPendentes(IEnumerable<string> feitas)\n"
        "    {\n        return new List<string>();\n    }\n\n"
        "    private static int Hidden() => 1;\n}\n"
    )
    (src / "Domain" / "Etapa.cs").write_text(
        "namespace Flows.Domain;\n\npublic sealed record Etapa(string Nome)\n{\n"
        "    public const int Max = 4;\n    public string Rotulo { get; init; } = Nome;\n"
        "    internal string Secret => Nome;\n}\n"
    )
    # MSBuild output: generated `.cs` that must never reach the map
    (src / "obj" / "Debug" / "net8.0").mkdir(parents=True)
    (src / "obj" / "Debug" / "net8.0" / "Flows.AssemblyInfo.cs").write_text(
        '[assembly: System.Reflection.AssemblyTitleAttribute("Flows")]\n'
    )
    (src / "bin" / "Debug").mkdir(parents=True)
    (src / "bin" / "Debug" / "Flows.GlobalUsings.g.cs").write_text("global using global::System;\n")

    tests = root / "tests" / "Flows.Tests"
    tests.mkdir(parents=True)
    (tests / "Flows.Tests.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk">\n  <ItemGroup>\n'
        '    <ProjectReference Include="..\\..\\src\\Flows\\Flows.csproj" />\n'
        "  </ItemGroup>\n</Project>\n"
    )
    (tests / "AdmissaoTests.cs").write_text(
        "using Flows;\n\npublic class AdmissaoTests\n{\n"
        "    public void SemNadaConcluidoTodasPendentes() { }\n}\n"
    )
    return root


def test_a_dotnet_project_is_one_module_not_one_per_folder(tmp_path: Path):
    """`.csproj` is the .NET module boundary: it globs `**/*.cs`, so `src/Flows` and
    `src/Flows/Domain` are two folders of ONE compiled unit. Grouping by folder would split a
    real client project into a dozen "modules" that no `using` statement can tell apart."""
    m = build_module_map(_dotnet_repo(tmp_path), commit="c")
    names = {mod.name for mod in m.modules}
    assert names == {"src.Flows", "tests.Flows.Tests"}
    flows = next(x for x in m.modules if x.name == "src.Flows")
    assert flows.key_files == [
        "src/Flows/Admissao.cs", "src/Flows/Domain/Etapa.cs", "src/Flows/Flows.csproj",
    ]
    assert flows.file_count == 3


def test_cs_summary_is_the_purpose_and_public_surface_is_read(tmp_path: Path):
    """`/// <summary>` is C#'s docstring — the .NET twin of the Python module docstring this
    generator has always read. Ignoring it left a 137-file repo describing itself as "src"."""
    m = build_module_map(_dotnet_repo(tmp_path), commit="c")
    flows = next(x for x in m.modules if x.name == "src.Flows")
    assert flows.purpose == (
        "Regras da orquestração durável de admissão (ACM.CA.Deskline.Flows)."
    )
    # types carry their namespace (that is what a caller has to `using`); members stay bare
    assert "Flows.Admissao" in flows.public_surface
    assert "Flows.Domain.Etapa" in flows.public_surface
    assert "EtapasPendentes" in flows.public_surface  # public method
    assert "Max" in flows.public_surface and "Rotulo" in flows.public_surface  # const, property
    assert "Hidden" not in flows.public_surface  # private
    assert "Secret" not in flows.public_surface  # internal


def test_multiline_cs_summary_is_joined_into_one_line(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "OrderQueue.cs").write_text(
        "namespace Functions;\n\n"
        "/// <summary>What an Azure Function does before it does anything interesting:\n"
        "/// pull the records out of an envelope without trusting its <c>shape</c>.</summary>\n"
        "public static class OrderQueue\n{\n}\n"
    )
    m = build_module_map(tmp_path, commit="c")
    src = next(x for x in m.modules if x.name == "src")
    assert src.purpose == (
        "What an Azure Function does before it does anything interesting: pull the records "
        "out of an envelope without trusting its shape."
    )


def test_a_cross_reference_keeps_the_identifier_it_names(tmp_path: Path):
    """`<see cref="X"/>` carries its subject in an attribute, so blanket tag-stripping deletes
    the noun: "Ver <see cref="AdmissaoService"/> para as regras" becomes "Ver para as regras".
    The identifier is a literal string in the file, so keeping it invents nothing."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Api.cs").write_text(
        "namespace Api;\n\n"
        '/// <summary>Endpoints de admissão. Ver <see cref="T:Flows.AdmissaoService" /> '
        "para as <c>regras</c>.</summary>\n"
        "public sealed partial class AdmissaoController { }\n"
    )
    m = build_module_map(tmp_path, commit="c")
    assert next(x for x in m.modules if x.name == "src").purpose == (
        "Endpoints de admissão. Ver Flows.AdmissaoService para as regras."
    )


def test_project_reference_is_the_dotnet_dependency_edge(tmp_path: Path):
    """MSBuild writes `Include="..\\..\\src\\Flows\\Flows.csproj"` with Windows separators even
    in repos that only build on Linux — unnormalised, every .NET edge resolves to nothing and
    the import graph (most of the map's value) comes out silently empty."""
    m = build_module_map(_dotnet_repo(tmp_path), commit="c")
    tests = next(x for x in m.modules if x.name == "tests.Flows.Tests")
    assert tests.dependencies == ["src.Flows"]


def test_msbuild_output_is_not_source_but_a_plain_bin_dir_still_is(tmp_path: Path):
    """`obj/`+`bin/` next to a `.csproj` are machine-written: mapping them would fill a .NET
    repo with generated files and make every `dotnet build` flip the bundle stale.

    The positive twin matters as much as the skip — `bin/` is an ordinary source directory in
    plenty of non-.NET repos, so the prune must be conditional on the project file, not global."""
    repo = _dotnet_repo(tmp_path)
    sources = {f.as_posix() for f in canonical_source_files(repo)}
    assert not any("/obj/" in f or "/bin/" in f for f in sources), sources
    assert "src/Flows/Admissao.cs" in sources

    other = tmp_path / "other"
    (other / "bin").mkdir(parents=True)
    (other / "bin" / "tool.py").write_text('"""A real CLI entrypoint, in a repo with no .csproj."""\n')
    assert "bin/tool.py" in {f.as_posix() for f in canonical_source_files(other)}


def test_csproj_description_outranks_a_type_summary(tmp_path: Path):
    """`<Description>` describes the whole project; a `<summary>` describes one type in it."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.csproj").write_text(
        "<Project><PropertyGroup><Description>Durable admission orchestration."
        "</Description></PropertyGroup></Project>\n"
    )
    (tmp_path / "src" / "A.cs").write_text("/// <summary>One type.</summary>\npublic class A { }\n")
    m = build_module_map(tmp_path, commit="c")
    assert next(x for x in m.modules if x.name == "src").purpose == (
        "Durable admission orchestration."
    )


# --- the declared coverage: what the generator did NOT read ------------------------------


def test_unread_extensions_are_declared_with_counts(tmp_path: Path):
    """A map that covers 2 of 139 files and says nothing about the other 137 reads as a
    COMPLETE map of a small repo. The bundle declares its own blindness so the next client on
    a stack we have not taught it does not discover the hole by accident."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text('"""App."""\n')
    (tmp_path / "app" / "Service.java").write_text("class Service {}\n")
    (tmp_path / "app" / "Model.java").write_text("class Model {}\n")
    (tmp_path / "app" / "schema.sql").write_text("select 1;\n")
    (tmp_path / "Makefile").write_text("all:\n\techo hi\n")

    bundle = build_bundle(tmp_path, commit="c", generated_at="t")
    declared = {e.suffix: e.files for e in bundle.manifest.unread_extensions}
    assert declared == {".java": 2, ".sql": 1, "": 1}  # "" = Makefile, a real answer
    # sorted by descending count, so the biggest blind spot is first (and bytes are stable)
    assert [e.suffix for e in bundle.manifest.unread_extensions] == [".java", "", ".sql"]
    assert bundle.manifest.files_read == 1 and bundle.manifest.files_unread == 4
    # the read count is the same set the checksums track — one repo, not two
    assert bundle.manifest.files_read == len(canonical_source_files(tmp_path))


def test_nothing_unread_is_an_empty_list_but_never_declared_is_none(tmp_path: Path):
    """[] and None are different answers. [] = surveyed, everything understood. None = a
    bundle written before the survey existed, which cannot tell you anything — collapsing them
    would make an old bundle claim a coverage it never measured."""
    from openfactory.knowledge.contracts import BundleManifest

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text('"""A."""\n')
    bundle = build_bundle(tmp_path, commit="c", generated_at="t")
    assert bundle.manifest.unread_extensions == []  # read the repo, nothing was unreadable
    assert bundle.manifest.files_unread == 0

    assert BundleManifest().unread_extensions is None  # an older generator's bundle
    assert BundleManifest().files_read is None


def test_an_undeclared_bundle_is_rewritten_to_gain_the_declaration(tmp_path: Path):
    """The upgrade path. Every bundle already on disk was written before the survey existed, so
    its coverage is None — "I could not tell". If the rewrite key treats that as [] ("I looked,
    nothing unread") the two compare equal, nothing is ever written, and no existing project
    gains the declaration until some unrelated source happens to change."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text('"""A."""\n')
    old = build_bundle(tmp_path, commit="X", generated_at="t1")
    old.manifest.files_read = None
    old.manifest.files_unread = None
    old.manifest.unread_extensions = None  # as an older generator left it
    assert write_bundle(old, tmp_path, force=True) is not None

    fresh = build_bundle(tmp_path, commit="X", generated_at="t1")
    assert fresh.manifest.unread_extensions == []  # surveyed: nothing unread here
    assert derived_key(fresh) != derived_key(old)
    assert write_bundle(fresh, tmp_path) is not None
    assert read_bundle(tmp_path).manifest.files_read == 1


def test_a_new_unreadable_stack_forces_the_declaration_to_be_rewritten(tmp_path: Path):
    """A merge that adds three `.java` files changes NO checksum — they are not canonical
    sources. Without coverage in the rewrite key the manifest would keep saying "no .java
    here" forever: the declaration would understate the blindness it exists to expose."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text('"""A."""\n')
    first = build_bundle(tmp_path, commit="X", generated_at="t1")
    assert write_bundle(first, tmp_path) is not None

    for i in range(3):
        (tmp_path / f"Svc{i}.java").write_text("class Svc {}\n")
    after = build_bundle(tmp_path, commit="Y", generated_at="t2")
    assert [c.file for c in after.manifest.checksums] == [c.file for c in first.manifest.checksums]
    assert derived_key(after) != derived_key(first)
    assert write_bundle(after, tmp_path) is not None
    assert {e.suffix: e.files for e in after.manifest.unread_extensions} == {".java": 3}


def test_the_survey_does_not_count_the_bundle_it_just_wrote(tmp_path: Path):
    """The survey walks the repo the bundle is written INTO. Counting `knowledge/*.yaml` would
    make the first build report a delta against its own output, and in the post-merge pipeline
    that is a second commit that re-triggers the pipeline (§22). Must converge in one."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text('"""A."""\n')
    first = build_bundle(tmp_path, commit="X", generated_at="t1")
    assert write_bundle(first, tmp_path) is not None

    again = build_bundle(tmp_path, commit="Y", generated_at="t2")
    assert ".yaml" not in {e.suffix for e in again.manifest.unread_extensions}
    assert write_bundle(again, tmp_path) is None  # converged: nothing to commit


def _force_unreadable(d: Path) -> bool:
    """chmod the directory shut and CONFIRM it is really shut. Returns False when the process
    can still read it (running as root, or a filesystem that ignores the mode) — the test then
    skips rather than passing for the wrong reason: `unreadable == []` would be the CORRECT
    answer there, and asserting the opposite would make the guard fail on real CI."""
    os.chmod(d, 0o000)
    try:
        list(os.scandir(d))
    except OSError:
        return True
    return False


def test_a_directory_the_walk_cannot_read_is_declared_not_swallowed(tmp_path: Path):
    """`os.walk` SWALLOWS every OSError by default and just yields fewer entries, so a vendored
    subtree the process cannot open contributed to neither `files_read` nor `files_unread` — the
    survey reported "0 unread, nothing I did not understand" about 8 files it never saw. That is
    could-not-read reading as read-and-empty, inside the function written to stop exactly that."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text('"""A."""\n')
    vendored = tmp_path / "vendorlib"
    vendored.mkdir()
    (vendored / "core.py").write_text("def important():\n    return 1\n")
    for i in range(7):
        (vendored / f"T{i}.java").write_text("class T {}\n")
    if not _force_unreadable(vendored):
        pytest.skip("this process can read a 0o000 directory (root?) — nothing to declare")
    try:
        survey = survey_extensions(tmp_path)
        assert survey.unreadable == ["vendorlib"]
        bundle = build_bundle(tmp_path, commit="c", generated_at="t")
        assert bundle.manifest.unreadable_paths == ["vendorlib"]
        # the counts still cannot see those 8 files — which is WHY the declaration must exist
        assert bundle.manifest.files_read == 1 and bundle.manifest.files_unread == 0
    finally:
        os.chmod(vendored, 0o755)


def test_a_repository_that_could_not_be_walked_is_not_an_empty_one(tmp_path: Path):
    """The positive twin, and the one that decides whether the declaration means anything: an
    EMPTY repo and a MISSING one both yield zero modules and zero files, so `unreadable` is the
    only field that can separate them. Empty must stay `[]` — a guard that shouted "blind" at
    every repo would be as useless as the silence it replaces."""
    empty = tmp_path / "empty"
    empty.mkdir()
    assert survey_extensions(empty).unreadable == []  # walked it, nothing there. A real answer.

    missing = tmp_path / "no-such-checkout"
    assert survey_extensions(missing).unreadable == ["."]  # could not open the repo at all
    assert build_bundle(missing, commit="c", generated_at="t").manifest.unreadable_paths == ["."]

    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("hello\n")
    assert survey_extensions(not_a_dir).unreadable == ["."]


def test_never_walked_is_none_but_a_clean_walk_is_an_empty_list(tmp_path: Path):
    """Third value, same rule as `unread_extensions`: None = a bundle from a generator that
    never walked for readability, and it cannot tell you anything."""
    from openfactory.knowledge.contracts import BundleManifest

    assert BundleManifest().unreadable_paths is None
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text('"""A."""\n')
    assert build_bundle(tmp_path, commit="c", generated_at="t").manifest.unreadable_paths == []


def test_a_bundle_that_never_checked_readability_is_rewritten_to_gain_the_check(tmp_path: Path):
    """THE upgrade path for this field, and it is not hypothetical: every bundle sitting in a
    deployment right now was written before `unreadable_paths` existed, so it carries the other
    coverage fields but not this one. If the rewrite key collapses None into [] the two compare
    equal, nothing is written, and no existing project ever gains the readability check — the
    same hole `test_an_undeclared_bundle_is_rewritten_to_gain_the_declaration` closes one field
    over."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text('"""A."""\n')
    old = build_bundle(tmp_path, commit="X", generated_at="t1")
    old.manifest.unreadable_paths = None  # as the previous generator left it: never checked
    assert write_bundle(old, tmp_path, force=True) is not None

    fresh = build_bundle(tmp_path, commit="X", generated_at="t1")
    assert fresh.manifest.unreadable_paths == []  # walked it: every directory opened
    assert derived_key(fresh) != derived_key(old)
    assert write_bundle(fresh, tmp_path) is not None
    assert read_bundle(tmp_path).manifest.unreadable_paths == []


def test_a_newly_unreadable_directory_forces_the_declaration_to_be_rewritten(tmp_path: Path):
    """A directory that becomes unreadable changes NO checksum (its files were never canonical
    sources) and NO extension count (it contributes to neither side). Without it in the rewrite
    key the manifest on disk keeps claiming a clean walk forever — understating the blindness
    the declaration exists to expose, which is the same defect as the `.java` case.

    The locked directory is EMPTY on purpose. My first version put a `notes.md` in it, and the
    `derived_key` assertion then passed whether or not readability was in the key at all — the
    file vanishing from the extension counts moved the key by itself. Isolating readability as
    the only variable is what makes this assertion mean what it says."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text('"""A."""\n')
    vendored = tmp_path / "vendorlib"
    vendored.mkdir()
    first = build_bundle(tmp_path, commit="X", generated_at="t1")
    assert write_bundle(first, tmp_path) is not None

    if not _force_unreadable(vendored):
        pytest.skip("this process can read a 0o000 directory (root?) — nothing to declare")
    try:
        after = build_bundle(tmp_path, commit="Y", generated_at="t2")
        assert [c.file for c in after.manifest.checksums] == [
            c.file for c in first.manifest.checksums
        ]
        assert derived_key(after) != derived_key(first)
        assert write_bundle(after, tmp_path) is not None
        assert read_bundle(tmp_path).manifest.unreadable_paths == ["vendorlib"]
    finally:
        os.chmod(vendored, 0o755)


def test_survey_and_map_walk_the_same_repository(tmp_path: Path):
    """One pruning implementation, or the "read / not read" split describes two different
    repositories: a vendored tree counted as unread would swamp the declaration."""
    repo = _fixture_repo(tmp_path)
    (repo / "node_modules" / "left-pad").mkdir(parents=True)
    for i in range(5):
        (repo / "node_modules" / "left-pad" / f"f{i}.md").write_text("x\n")
    survey = survey_extensions(repo)
    assert survey.files_read == len(canonical_source_files(repo))
    assert dict(survey.unread) == {".md": 1}  # app/README.md only — never node_modules


def test_render_sheds_detail_not_coverage(tmp_path: Path):
    """Truncating the concatenated map drops whole modules from the alphabetical tail — the agent
    silently gets a map missing the same slice of the codebase every time and concludes it does
    not exist. Every module must survive the budget; only DEPTH may be shed."""
    from openfactory.knowledge.render import _MAX_CHARS

    for i in range(60):
        d = tmp_path / f"mod{i:02d}"
        d.mkdir()
        (d / "__init__.py").write_text(f'"""Module {i} — a reasonably wordy purpose line."""\n')
        # enough surface to blow the budget at full detail
        (d / "impl.py").write_text(
            "".join(f"def helper_number_{j}():\n    return {j}\n\n\n" for j in range(12))
        )
    bundle = build_bundle(tmp_path, commit="c", generated_at="t")
    text = render_module_map(bundle)

    assert len(text) <= _MAX_CHARS
    assert text.count("### ") == 60  # every module still located
    for i in (0, 30, 59):
        assert f"mod{i:02d}" in text
