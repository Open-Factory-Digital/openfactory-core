"""The extensibility document tells a stranger the group that EXISTS, and nothing else does.

`docs/core/07-extensibility.md` is the only document a third party has for "how do I add a
provider without editing your files". On 2026-08-24 it told them two things that were false at
once: that an add-on has *nowhere to register itself* (§2), and that the group to register under
is `openfactory.forge` (§3). Measured with real dist-info metadata: an add-on written to the
document's spelling was loaded as `{}` with no warning, and `build_forge` raised `unknown forge
'gitea'` naming only the built-ins. The group that exists is `openfactory.adapters`
(`openfactory/plugins.py`), with the axis in the entry-point NAME (`forge.gitea`), and it was
stated only in a pyproject comment and a module docstring — nowhere a stranger reads.

WHY A GUARD AND NOT AN EDIT. The document said the truth on the day it was written; the platform
moved (#106) and the sentence did not. The group name, the "nowhere to register" sentence and
the list of axes that consult the loader are all facts the tree can be asked for, so each is
derived here rather than trusted.

WHAT IS NOT CHECKED, and why. ADRs are history — ADR-0034 §5 and ADR-0038 still say the platform
has nowhere to plug in, which was true when they were accepted and is the record an ADR exists to
keep. `plugins.py`, `pyproject.toml` and the extensibility guard quote the sentence deliberately
for the same reason. Only doctrine under `docs/` is held to today's truth.
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess

from openfactory import plugins

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "core" / "07-extensibility.md"
HISTORY = ("docs/adr/",)

#: Any entry-point group spelled the way a pyproject spells it. The capture is the whole group
#: name, so a group that is not ours is reported by name.
GROUP_IN_A_DOC = re.compile(r'entry-points\.\"([A-Za-z0-9_.-]+)\"')
NOWHERE = "nowhere to register"


def _doctrine() -> list[str]:
    """Every tracked document under docs/ that states how things ARE, as opposed to how they
    were decided: the ADR directory is excluded by prefix."""
    out = subprocess.run(["git", "ls-files", "-z", "docs/*.md"], cwd=ROOT,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[:200]
    return [p for p in out.stdout.split("\0") if p and not p.startswith(HISTORY)]


def test_the_doctrine_set_holds_the_document_this_guard_was_written_for():
    """The twin of the exclusion. `HISTORY` is a prefix list, and a prefix list can grow to
    swallow the very document these guards exist for — `('docs/adr/', 'docs/core/')` left every
    test below green while `len(docs) > 5` still held (reviewer's cut, 2026-08-26). So the set
    is held to contain §3's own file, by name."""
    docs = _doctrine()
    assert DOC.relative_to(ROOT).as_posix() in docs, (
        f"{DOC.name} is not in the doctrine set the guards scan — the exclusion {HISTORY} "
        f"swallowed the document this guard was written for; scanned: {docs}")


def test_the_doc_names_the_group_the_loader_actually_reads():
    """The positive statement: a stranger reading §3 sees the group `plugins._load` asks for,
    spelled as they will have to spell it in their own pyproject."""
    text = DOC.read_text()
    assert f'[project.entry-points."{plugins.GROUP}"]' in text, (
        f"{DOC.name} does not show `[project.entry-points.\"{plugins.GROUP}\"]` — the one group "
        f"the loader reads is documented nowhere a stranger looks")


def test_no_doctrine_document_names_a_group_that_does_not_exist():
    """The twin of the statement above, over every document at once. `openfactory.forge` was
    in §3 as an example of the shape — and an example is what a stranger copies."""
    docs = _doctrine()
    assert len(docs) > 5, f"only {len(docs)} documents — this measures nothing"
    offenders = []
    for rel in docs:
        text = (ROOT / rel).read_text()
        for m in GROUP_IN_A_DOC.finditer(text):
            if m.group(1) != plugins.GROUP:
                line = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{rel}:{line}  {m.group(1)}")
    assert not offenders, (
        f"a document names an entry-point group the loader never reads (it reads only "
        f"`{plugins.GROUP}`); an add-on declared under it is silently ignored:\n  "
        + "\n  ".join(offenders))


def test_the_group_pattern_can_SEE_the_spelling_that_was_wrong():
    """Verify the verifier: the exact line §3 carried on 2026-08-24 must be caught, and the
    correct one must not be reported."""
    assert GROUP_IN_A_DOC.findall('[project.entry-points."openfactory.forge"]') == ["openfactory.forge"]
    assert GROUP_IN_A_DOC.findall(f'[project.entry-points."{plugins.GROUP}"]') == [plugins.GROUP]


def test_no_doctrine_document_says_an_add_on_has_nowhere_to_register():
    """The sentence that told a stranger not to try at all."""
    offenders = [rel for rel in _doctrine() if NOWHERE in (ROOT / rel).read_text()]
    assert not offenders, (
        f"a document still says an add-on has {NOWHERE!r} — the group exists "
        f"(`{plugins.GROUP}`), and a reader who believes the sentence never looks for it: "
        f"{offenders}")


def test_the_sentence_is_still_QUOTED_where_history_belongs():
    """The positive twin: the phrase is real and the check is not vacuous. `plugins.py` quotes it
    on purpose — it is the admission that module exists to answer."""
    assert NOWHERE in (ROOT / "openfactory" / "plugins.py").read_text()


# ── which axes consult the loader is read off the registries, not maintained by hand ────────────

def _axes_that_consult_the_loader(root: pathlib.Path = ROOT) -> set[str]:
    """Every axis name passed to `plugins.builder(...)` in a registry module — as a literal, or
    as a module-level string constant the registry spells once (`AXIS = "box"`) and reuses in
    its refusal. Registries are `**/registry.py`, plus the board axis's, which is called
    `factory.py`.

    THE CONSTANT FORM WAS INVISIBLE until 2026-08-26: five registries spell their axis once,
    the walker collected only literals, and the sentence in §2 said "five registries" while
    nine consulted the loader — a guard that could not see what it was measuring. And two
    registries are not called `registry.py` at all (`session_store.py`, `token_pool.py`), so
    every module under the package is read: a registry is whatever asks the loader."""
    files = list(root.joinpath("openfactory").rglob("*.py"))
    axes: set[str] = set()
    for path in files:
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text())
        constants = {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign)
                     and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
                     for t in n.targets if isinstance(t, ast.Name)}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "builder"
                    and getattr(node.func.value, "id", "") == "plugins"):
                axes |= {a.value if isinstance(a, ast.Constant)
                         else constants.get(getattr(a, "id", ""))
                         for a in node.args[:1]} - {None}
    return axes


def _axes_the_doc_claims(text: str) -> set[str]:
    # whitespace-tolerant: the sentence wraps wherever the paragraph wraps
    m = re.search(r"consult\s+the\s+loader\s+today:\s*((?:`[a-z_]+`(?:,\s+|\s+and\s+)?)+)", text)
    assert m, "the document no longer states which registries consult the loader"
    return set(re.findall(r"`([a-z_]+)`", m.group(1)))


def test_the_doc_lists_exactly_the_axes_that_consult_the_loader():
    """The 4-versus-rest split cannot drift: when a fifth registry is wired the sentence has to
    change, and when the sentence claims an axis the registries do not ask for, a stranger writes
    an add-on nothing will ever load."""
    from_tree = _axes_that_consult_the_loader()
    assert len(from_tree) >= 4, f"only {sorted(from_tree)} registries consult the loader — was a call removed?"
    from_doc = _axes_the_doc_claims(DOC.read_text())
    assert from_doc == from_tree, (
        f"{DOC.name} says the loader is consulted by {sorted(from_doc)}; the registries say "
        f"{sorted(from_tree)}")


def test_the_registry_walk_can_SEE_a_planted_call(tmp_path):
    """The twin: a registry that asks the loader for a new axis must be counted, in the exact
    shape the four real ones use."""
    reg = tmp_path / "openfactory" / "adapters" / "board" / "factory.py"
    reg.parent.mkdir(parents=True)
    reg.write_text("from openfactory import plugins\n"
                   "def build(kind):\n"
                   "    return BOARDS.get(kind) or plugins.builder('board', kind, builtin=BOARDS)\n")
    other = tmp_path / "openfactory" / "adapters" / "sandbox" / "registry.py"
    other.parent.mkdir(parents=True)
    other.write_text("SANDBOXES = {}\n")
    assert _axes_that_consult_the_loader(tmp_path) == {"board"}
