"""A sentence that points somebody at a document points at one that exists.

`openfactory/cli_refusals.py` told a stranger whose forge refused the CLI to read
`docs/setup/github-app.md`. That file was renamed to `docs/setup/github.md` in a commit that
touched only `docs/` — the package site was missed, and no guard saw it: the docs-drift guards
glob `docs/**`, the refusal guard checks the sentence's shape, and neither asks whether the path
inside a package string is a file. Measured 2026-08-24: the remedy printed on the first-hour
failure path named a document that did not exist.

TWO HALVES. The scan walks every non-docstring string constant in the package for a `docs/….md`
path and asserts each one is a file in this tree — with the one module that deliberately names
a CLIENT's document layout exempted as a MODULE (the literals sit at five places in it, not in
one range). And the public seam: the refusal a failed forge auth produces names a path, and that
path is a file — so the guard is reached the way the CLI reaches it, not only by the scan.
"""

from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: A repository-relative document path, as package sentences spell them — WITH OR WITHOUT the
#: extension. Requiring `.md` was a blind spot measured on 2026-08-26: a sentence pointing at
#: `docs/core/04` slipped past this scan entirely, including one inside a RUNTIME ERROR STRING an
#: operator reads on a real failure (`openfactory/registry.py`). The bare form is how people cite
#: a numbered document ("docs/core/04 §5"), and it rots exactly like the spelled-out one.
DOC_PATH = re.compile(r"docs/[\w./-]*[\w-]")


def resolves(doc: str) -> bool:
    """True when `doc` points at something in this tree. A path with an extension must be that
    file; a bare citation (`docs/core/04`, `docs/adr/0022`) resolves the way a reader does — the
    directory exists and one entry in it begins with that name."""
    target = ROOT / doc
    if target.is_file() or target.is_dir():
        return True
    parent, _, stem = doc.rpartition("/")
    directory = ROOT / parent
    return bool(stem) and directory.is_dir() and any(directory.glob(f"{stem}*"))

#: Modules whose `docs/…md` literals are a CLIENT's repository layout, not ours. `context.py`
#: proposes the context repository's documents (`docs/glossary.md`, `docs/invariants.md`, and
#: their pt-BR spellings) — in the client's tree, where this guard cannot look. A module, not a
#: line range: the literals sit in five places there, and a range exempts whichever three
#: happened to be counted. Note the wrong-reason trap the exemption avoids: `docs/glossary.md`
#: happens to exist in OUR tree too, and a naive check would pass it for the wrong reason.
CLIENT_LAYOUT = {
    "openfactory/onboarding/context.py": "proposes the CLIENT's context-repository documents",
}


def _docstring_ids(tree: ast.AST) -> set[int]:
    ds: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                ds.add(id(node.body[0].value))
    return ds


def _document_paths(source: str) -> list[tuple[int, str]]:
    """Every `docs/….md` path inside a non-docstring string constant, with its line."""
    tree = ast.parse(source)
    prose = _docstring_ids(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in prose):
            found.extend((node.lineno, m) for m in DOC_PATH.findall(node.value))
    return found


def test_the_scan_can_SEE_a_document_path_and_leaves_prose_alone():
    """The positive twin: a scanner that matched nothing would report every path as existing."""
    planted = (
        '"""the module docstring cites docs/setup/nowhere.md and that is prose"""\n'
        'REMEDY = "set the token (docs/setup/somewhere.md) and re-run"\n'
        'TWO = f"see docs/a.md and docs/sub/b-c.md for {x}"\n'
        'BARE = "one deployment per organisation (docs/core/04), or remove the rest."\n'
        'SECTION = "the axes are published in docs/core/07 §2, and nowhere else"\n'
    )
    # A SET, NOT A LIST: `ast.walk` is breadth-first, so an f-string's paths arrive after a plain
    # constant's whatever their order in the file. The property is WHICH paths the scan sees —
    # the two bare citations included, and never the one in the docstring.
    found = {path for _, path in _document_paths(planted)}
    assert found == {"docs/setup/somewhere.md", "docs/a.md", "docs/sub/b-c.md",
                     "docs/core/04", "docs/core/07"}, sorted(found)


def test_a_bare_citation_resolves_the_way_a_READER_resolves_it():
    """`docs/core/04` is how people cite a numbered document, and it is a live pointer: it
    resolves when the directory holds a file beginning with that name, and stops resolving the
    moment that file leaves — which is the whole point of widening the scan."""
    assert resolves("docs/core/07")
    assert resolves("docs/core/07-extensibility.md")
    assert resolves("docs/adr")
    assert not resolves("docs/core/99")
    assert not resolves("docs/nowhere/at-all.md")


def _package_document_paths() -> dict[str, list[tuple[int, str]]]:
    out: dict[str, list[tuple[int, str]]] = {}
    for path in sorted(ROOT.joinpath("openfactory").rglob("*.py")):
        rel = str(path.relative_to(ROOT))
        if rel in CLIENT_LAYOUT:
            continue
        hits = _document_paths(path.read_text())
        if hits:
            out[rel] = hits
    return out


def dangling(found: dict[str, list[tuple[int, str]]]) -> dict[str, list[tuple[int, str]]]:
    """The pointers in `found` that resolve to nothing — the JUDGEMENT, kept apart from the walk
    so it can be fed a case that must fail. Inline, it could not be: no package sentence dangles
    today, so a cut that removed the check entirely survived the assertion below (2026-08-26)."""
    out = {rel: [(line, doc) for line, doc in hits if not resolves(doc)]
           for rel, hits in found.items()}
    return {rel: gone for rel, gone in out.items() if gone}


def test_the_judgement_REPORTS_a_pointer_that_resolves_to_nothing():
    """Verify the verifier, before trusting the sweep below: fed one live pointer and one dead
    one, the judgement returns the dead one and only the dead one."""
    planted = {"openfactory/live.py": [(7, "docs/core/07")],
               "openfactory/rotted.py": [(9, "docs/core/07"), (11, "docs/core/99-gone.md")]}
    assert dangling(planted) == {"openfactory/rotted.py": [(11, "docs/core/99-gone.md")]}


def test_every_document_a_package_sentence_points_at_EXISTS():
    missing = dangling(_package_document_paths())
    assert not missing, (
        f"these sentences send somebody to a document that is not in the tree: {missing}. Rename "
        f"the reference with the document — a first-hour remedy naming a missing page is a dead "
        f"end wearing a remedy's clothes")


def test_the_scan_has_a_subject():
    """The other twin: the package DOES name documents in its sentences — ten sites when this
    was written (cli.py, cli_refusals.py, doctor.py, deployment.py, github.py, bundle.py). A
    scan that found none would be reporting a clean package for the wrong reason."""
    total = sum(len(hits) for hits in _package_document_paths().values())
    assert total >= 20, f"the scan found only {total} document references — it has lost its subject"


def test_every_exemption_is_still_EARNED():
    """Staleness, the house pattern: an exempted module that no longer names any document is an
    exemption that reads as documentation and is a lie."""
    for rel in CLIENT_LAYOUT:
        assert _document_paths((ROOT / rel).read_text()), (
            f"{rel} is exempted and names no document at all — delete its entry")


# ── the public seam: the refusal a person actually reads ────────────────────────────────────────

def test_the_forge_auth_refusal_names_a_document_that_is_a_file():
    """Through `name_the_cause`, the way the CLI reaches it, not only through the scan: the remedy
    for an unauthenticated forge points at the setup page, and the page is in the tree."""
    from openfactory.cli_refusals import name_the_cause

    cause = name_the_cause(RuntimeError("gh pr create failed: gh auth login"))
    assert cause is not None, "an unauthenticated `gh` is no longer recognised as a cause"
    _, remedy = cause
    named = DOC_PATH.findall(remedy)
    assert named, f"the remedy no longer points at a setup document: {remedy!r}"
    for doc in named:
        assert resolves(doc), f"the remedy points at {doc}, which is not in the tree"
