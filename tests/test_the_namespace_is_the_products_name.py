"""The directory this platform claims in a client's repository carries the product's name — #106.

The product is OpenFactory; the folder it writes into a client's source tree is `.openfactory/`
(the product owner, 2026-08-07: everything lives under `.openfactory`).

For a while this file guarded a MIGRATION — readers answered to both names, writers emitted only
the new one. That code left on 2026-08-25 (the public repository has no old installation; the one
deployment that ran under the former name renamed its own files), and what this file guards now is
the ABSENCE, in three halves:

    NO CONSTANT. The module names the retired directory once, to refuse it, and nothing else in
    the package spells the old name as a code constant — not a path, not a branch, not a label,
    not an environment variable. Scanned as AST over every non-docstring string, so a comment
    explaining the rename cannot fail the guard that enforces it.

    NO READER. Nothing resolves to, copies from, or migrates the retired path — the operator's
    own directory included.

    THE REFUSAL NAMES IT. A repository still on `.sdlc/` is refused with a sentence saying what
    to rename, through the real loader and the real product-module reader. The alternative — a
    reader that simply does not look there — reports "no manifest" to somebody looking at one,
    which is the absence-read-as-compliance class this codebase pays for most.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from openfactory import namespace

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_platform_claims_its_own_name():
    assert namespace.DIR == ".openfactory"
    assert namespace.MANIFEST == ".openfactory/project.yaml"
    assert namespace.PRODUCT_MANIFEST == ".openfactory/product.yaml"


def test_a_project_that_says_nothing_gets_the_NEW_path():
    """The default is the product, and a default is the only thing most clients will ever have."""
    from openfactory.contracts.project import Project

    assert Project.model_fields["manifest_path"].default == namespace.MANIFEST


# ── no constant: the module answers to one name ─────────────────────────────────────────────────

def test_the_namespace_carries_no_second_name():
    """The migration's constants and helpers are GONE, not renamed: a `LEGACY_*` that survived
    under another name would be the same second reader with a new label."""
    survivors = [n for n in dir(namespace) if "LEGACY" in n.upper() or "legacy" in n]
    assert not survivors, f"the namespace still carries a second name: {survivors}"
    # the positive twin — the module still says what the ONE name is
    assert namespace.DIR and namespace.BRANCH_PREFIX and namespace.job_branch("#7") == "openfactory/7"


def test_the_retired_name_is_spelled_for_the_refusal_and_nothing_else():
    """`RETIRED_DIR` exists so the refusal can say what to rename. It is not a path anything
    resolves — the twin helper answers with it only for OUR default location."""
    assert namespace.RETIRED_DIR == ".sdlc"
    assert namespace._retired_twin(namespace.MANIFEST) == ".sdlc/project.yaml"
    assert namespace._retired_twin("./.openfactory/product.yaml") == ".sdlc/product.yaml"
    assert namespace._retired_twin("docs/build/project.yaml") == ""


# ── the refusal names it ────────────────────────────────────────────────────────────────────────

def test_a_repository_still_on_the_old_name_is_REFUSED_by_name(tmp_path):
    """Not read, not ignored: refused, with the rename in the sentence."""
    (tmp_path / ".sdlc").mkdir()
    (tmp_path / ".sdlc/project.yaml").write_text("version: 1\n")

    with pytest.raises(namespace.RetiredNamespace) as refused:
        namespace.resolve(tmp_path, namespace.MANIFEST, project="acme")

    said = str(refused.value)
    assert "acme" in said, said
    assert ".sdlc/project.yaml" in said and ".openfactory/" in said, (
        f"the refusal must name the file it found AND the directory to rename it to: {said}")
    assert "rename" in said.lower(), said


def test_the_refusal_is_a_missing_manifest_to_every_existing_handler():
    """Every caller that already handles a missing manifest handles this one — the doctor's
    finding, the CLI's refusal, the job's park reason — without learning a new type."""
    assert issubclass(namespace.RetiredNamespace, FileNotFoundError)


def test_the_NEW_path_wins_when_both_exist(tmp_path):
    """A repository that renamed and left the old directory behind as a backup is a renamed
    repository. Refusing it would punish exactly the people who did what the refusal asks."""
    for d, body in ((".sdlc", "version: 1\n"), (".openfactory", "version: 2\n")):
        (tmp_path / d).mkdir()
        (tmp_path / d / "project.yaml").write_text(body)

    assert namespace.resolve(tmp_path, namespace.MANIFEST).read_text() == "version: 2\n"


def test_a_missing_manifest_is_reported_in_the_NEW_name(tmp_path):
    """What a client reads when there is nothing there has to say what to CREATE."""
    assert namespace.resolve(tmp_path, namespace.MANIFEST) == tmp_path / namespace.MANIFEST


def test_a_path_that_is_not_OURS_is_left_exactly_alone(tmp_path):
    """`manifest_path` exists so a client can put the file where their conventions say. A fallback
    that second-guessed an explicit value would be the platform overriding the configuration it
    was handed — and a `.sdlc/` beside an explicit path is not ours to refuse either."""
    (tmp_path / ".sdlc").mkdir()
    (tmp_path / ".sdlc/project.yaml").write_text("version: 1\n")

    assert namespace.resolve(tmp_path, "docs/mine.yaml") == tmp_path / "docs/mine.yaml"


def test_the_refusal_reaches_the_manifest_loader(tmp_path):
    """Through the real door, not the helper: `load_manifest` is what every job, the doctor and
    the CLI read a project through, and the sentence has to come out of IT."""
    from openfactory.contracts.project import Project
    from openfactory.loader import load_manifest

    (tmp_path / ".sdlc").mkdir()
    (tmp_path / ".sdlc/project.yaml").write_text("version: 1\nvalidate:\n  test: pytest -q\n")
    project = Project(name="legacy-acme", repo_path=str(tmp_path))

    with pytest.raises(FileNotFoundError) as refused:
        load_manifest(project, repo_root=tmp_path)

    said = str(refused.value)
    assert "legacy-acme" in said and ".sdlc/project.yaml" in said and ".openfactory/" in said, said
    assert "no manifest at" in said, (
        "the tech-lead classifier files a project-configuration problem by this phrase "
        f"(techlead/classify.py); without it the refusal would park as an unknown cause: {said}")


def test_the_refusal_reaches_the_product_module_as_its_OFF_reason(tmp_path):
    """The other reader. A documentation repository still on the old name turns the product
    module OFF with the rename in the reason — never a bare "missing" beside a file that exists."""
    from openfactory.product.loader import _read_docs_manifest

    (tmp_path / ".sdlc").mkdir()
    (tmp_path / ".sdlc/product.yaml").write_text("product: acme\nsources: []\n")

    docs, reason = _read_docs_manifest(tmp_path)

    assert docs is None
    assert ".sdlc/product.yaml" in reason and ".openfactory/" in reason, reason
    assert "missing" not in reason, (
        f"a file that exists under the old name was reported as missing: {reason}")


def test_a_documentation_repository_with_nothing_at_all_is_still_MISSING(tmp_path):
    """The positive twin of the OFF reason: absence and the retired name are different facts and
    get different sentences."""
    from openfactory.product.loader import _read_docs_manifest

    docs, reason = _read_docs_manifest(tmp_path)

    assert docs is None and "missing" in reason, reason


def test_a_product_warning_names_the_file_the_loader_actually_read():
    """The remedy sentences said `.sdlc/project.yaml` after the loader stopped reading it — a
    person following them created a file the platform never opened (measured 2026-08-24, the
    conflict remedy). They name the project's OWN manifest path now: the default when the project
    left it alone, the declared one when it did not."""
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project
    from openfactory.product.config import resolve_product_link

    def conflict_remedy(project) -> str:
        # the source repo claims a documentation repository the registry does not authorise —
        # the remedy tells the person which FILE to fix, and that file must be the one read
        link = resolve_product_link(project=project, manifest_docs_repo="other/docs",
                                    docs=None, docs_error="x")
        assert link.kind == "conflict", link
        return link.reason

    plain = Project(name="p", repo_path="/r", product=ProductConfig(docs_repo="o/docs"))
    assert namespace.MANIFEST in conflict_remedy(plain), conflict_remedy(plain)

    custom = Project(name="p", repo_path="/r", manifest_path="conf/factory.yaml",
                     product=ProductConfig(docs_repo="o/docs"))
    said = conflict_remedy(custom)
    assert "conf/factory.yaml" in said and namespace.MANIFEST not in said, said


# ── no reader: nothing in the package spells the old name as code ──────────────────────────────

#: The retired name as a TOKEN, any case: `.sdlc`, `sdlc/7`, `sdlc-working`, `sdlc_confirm`,
#: `SDLC_TOKEN`, `sdlc:` — and not `sdlcfoo`. One pattern for every shape the name took, because
#: the migration code came back in six shapes (a path, a branch, a label, a button id, a stream
#: prefix, an environment prefix) and a guard per shape is a guard the seventh shape walks past.
OLD_NAME = re.compile(r"(?<![A-Za-z0-9])sdlc(?![A-Za-z0-9])", re.IGNORECASE)


def _docstring_ids(tree: ast.AST) -> set[int]:
    """The constants that are somebody's docstring — prose, not code."""
    ds: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                ds.add(id(node.body[0].value))
    return ds


def _old_name_constants(source: str) -> list[tuple[int, str]]:
    """Every non-docstring string constant carrying the retired name — f-string pieces included.

    CONTAINS, NOT STARTSWITH. The first version of this guard matched only constants that BEGAN
    with the old path, and five live sentences (a doctor remedy, three product warnings, an action
    summary) named `.sdlc/project.yaml` mid-string while the guard reported zero offenders — the
    absence-read-as-compliance class, measured 2026-08-24. An f-string's literal pieces are
    `Constant` nodes too, so `ast.walk` reaches them without a second arm."""
    tree = ast.parse(source)
    prose = _docstring_ids(tree)
    return [(node.lineno, node.value[:80]) for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in prose and OLD_NAME.search(node.value)]


def test_the_scan_can_SEE_the_old_name_in_every_shape():
    """The positive twin. `assert not offenders` passes just as happily over a scan that reads
    nothing — plant every shape the name took plus a docstring and a comment, and require exactly
    the code constants back."""
    planted = (
        '"""a module docstring that says .sdlc/ freely"""\n'
        'PATH = ".sdlc/project.yaml"\n'
        'MID = f"fix `docs_repo` in the repo\'s .sdlc/project.yaml, or the registry"\n'
        'BRANCH = f"sdlc/{ticket_id}"\n'
        'LABEL = "sdlc-working"\n'
        'BUTTON = "sdlc_confirm_approve"\n'
        'ENV = "SDLC_FORGE_TOKEN"\n'
        'STATE = "sdlc:"\n'
        'NOT_IT = "sdlcfoo"\n'
        '# a comment that says .sdlc is not a constant at all\n'
        'def f():\n'
        '    """a function docstring naming sdlc/7"""\n'
        '    return "openfactory"\n'
    )
    found = [value for _, value in _old_name_constants(planted)]
    assert sorted(found) == sorted([
        ".sdlc/project.yaml",
        "fix `docs_repo` in the repo's .sdlc/project.yaml, or the registry",
        "sdlc/", "sdlc-working", "sdlc_confirm_approve", "SDLC_FORGE_TOKEN", "sdlc:",
    ]), found


#: Where the old name may still appear as a CODE constant, and why. ONE entry: the module that
#: refuses it has to be able to spell it. Every other entry the table ever had was paid down —
#: `approvals`/`registry` when the operator directory got its home, `testing/local_flow.py` when
#: the migration read it exercised left — and the staleness check below retires an entry the day
#: its reason stops being true.
ALLOWED = {
    "openfactory/namespace.py": "names the retired directory once, in order to refuse it by name",
}


def test_nothing_in_the_package_spells_the_old_name_as_code():
    """Derived by walking `openfactory/` rather than by listing suspects, so a new reader — a path,
    a branch, a label, a button id, a stream prefix, an environment variable, a remedy sentence —
    is caught the day it is written, whatever shape it takes."""
    offenders = {}
    for path in sorted(ROOT.joinpath("openfactory").rglob("*.py")):
        rel = str(path.relative_to(ROOT))
        if rel in ALLOWED:
            continue
        hits = _old_name_constants(path.read_text())
        if hits:
            offenders[rel] = hits

    assert not offenders, (
        f"these spell the platform's former name as a code constant: {offenders}. The name left "
        f"on 2026-08-25 — use `namespace.DIR`/`namespace.MANIFEST`/`namespace.job_branch`, and "
        f"a sentence that tells somebody what to edit must name a file the platform reads")


@pytest.mark.parametrize("rel", sorted(ALLOWED))
def test_every_exemption_is_still_EARNED(rel):
    """Staleness, the house pattern. An exemption for a file that no longer contains the old name
    is a note that reads as documentation and is a lie — so it fails, and the fix is to delete
    the entry."""
    assert _old_name_constants((ROOT / rel).read_text()), (
        f"{rel} is exempted from the namespace guard and no longer spells the old name at all. "
        f"Delete its entry from ALLOWED — the exemption was paid down.")


def test_the_only_exemption_spells_it_exactly_once():
    """The refusal needs the word once. A second occurrence in the exempted module is the
    migration growing back inside the one file the guard cannot see."""
    hits = _old_name_constants((ROOT / "openfactory/namespace.py").read_text())
    assert [value for _, value in hits] == [".sdlc"], hits


# ── no constant, in the shipped files that are not Python either ───────────────────────────────

#: The package ships files the AST scan cannot walk — the panel, the deployment's default floor,
#: the presets, the role prompts. A `sdlc_token` in the panel's script or a `.sdlc/` in a shipped
#: YAML is the same second reader in a shape that scan is blind to (review, 2026-08-25: the
#: panel's token adoption was removed with nothing guarding its return).
SHIPPED_NOT_PYTHON = (".html", ".yaml", ".yml", ".md", ".json")


def _without_comments(text: str, suffix: str) -> str:
    """The lines a machine reads: YAML minus its `#` comments; HTML minus `<!-- -->`, `/* */` and
    comment-only `//` lines. Markdown is left whole on purpose — a role prompt is prose read by a
    MODEL, so the old directory named there is an instruction, not a remark."""
    if suffix in (".yaml", ".yml"):
        return "\n".join(line.split(" #", 1)[0] for line in text.splitlines()
                         if not line.lstrip().startswith("#"))
    if suffix == ".html":
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        return "\n".join(line for line in text.splitlines()
                         if not line.lstrip().startswith("//"))
    return text


def _old_name_in_shipped_file(text: str, suffix: str) -> list[str]:
    return [line.strip()[:80] for line in _without_comments(text, suffix).splitlines()
            if OLD_NAME.search(line)]


def test_the_shipped_file_scan_can_SEE_the_old_name_and_leaves_comments_alone():
    """The positive twin, one planted offender per file kind beside a comment of the same shape."""
    yaml = ("# the old `.sdlc/project.yaml`, in a comment\n"
            "image: sdlc-python:sandbox  # trailing remark\n"
            "name: fine\n")
    html = ("<!-- .sdlc in a comment -->\n<script>\n/* sdlc_token in a block */\n"
            "// sdlc_token on a comment-only line\nconst k = 'sdlc_token';\n</script>\n")
    md = "Write the manifest to `.sdlc/project.yaml`.\n"

    assert _old_name_in_shipped_file(yaml, ".yaml") == ["image: sdlc-python:sandbox"]
    assert _old_name_in_shipped_file(html, ".html") == ["const k = 'sdlc_token';"]
    assert _old_name_in_shipped_file(md, ".md") == ["Write the manifest to `.sdlc/project.yaml`."]


#: The two shipped files the review named — the panel (the ONLY `.html` the package ships) and
#: the deployment's default floor. A COUNT floor could not see either leave: eleven of the sixteen
#: shipped files are Markdown, so a tuple without `.html` or without `.yaml` still clears ten
#: (review, 2026-08-26: both cuts survived the count). These are asserted by name.
NAMED_SHIPPED_FILES = ("openfactory/api/panel.html", "openfactory/org_defaults/floor.yaml")


def test_no_shipped_file_outside_python_spells_the_old_name():
    """Derived by walking `openfactory/` for every shipped file the AST scan does not read."""
    offenders = {}
    scanned: list[str] = []
    for path in sorted(ROOT.joinpath("openfactory").rglob("*")):
        if not path.is_file() or path.suffix not in SHIPPED_NOT_PYTHON:
            continue
        scanned.append(str(path.relative_to(ROOT)))
        hits = _old_name_in_shipped_file(path.read_text(encoding="utf-8"), path.suffix)
        if hits:
            offenders[str(path.relative_to(ROOT))] = hits

    assert len(scanned) >= 10, f"the scan has no subject — {len(scanned)} shipped file(s) found"
    for named in NAMED_SHIPPED_FILES:
        assert named in scanned, (
            f"{named} is not in the scanned set — the scan lost the file kind it was written for, "
            f"and a count of {len(scanned)} could not tell")
    assert not offenders, (
        f"these shipped files spell the platform's former name outside a comment: {offenders}")


# ── the operator's directory: one home, no migration ───────────────────────────────────────────

def test_the_operator_file_lives_under_the_products_name(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: tmp_path))

    got = namespace.operator_path("registry.yaml")

    assert got == tmp_path / ".openfactory" / "registry.yaml"
    assert not got.exists()  # resolving must not invent a file


def test_an_old_operator_file_is_neither_read_nor_copied(tmp_path, monkeypatch):
    """The migration used to copy `~/.sdlc/<file>` to the new home on first touch. It is gone:
    the path is answered, nothing is created, nothing is read from the old home, and the old file
    is left exactly where it was."""
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: tmp_path))
    (tmp_path / ".sdlc").mkdir()
    (tmp_path / ".sdlc" / "registry.yaml").write_text("projects: {}\n")

    got = namespace.operator_path("registry.yaml")

    assert got == tmp_path / ".openfactory" / "registry.yaml"
    assert not got.exists(), "the retired home was copied into the new one"
    assert not (tmp_path / ".openfactory").exists(), "resolving created a directory"
    assert (tmp_path / ".sdlc" / "registry.yaml").read_text() == "projects: {}\n"
