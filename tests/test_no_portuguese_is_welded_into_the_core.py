"""No Portuguese string is welded into the core outside a place that says which language it is (#429).

Found live: an English conversation got a Portuguese card and a Portuguese line under its English
proposal. The card layouts shipped in one language, and ten admin notes in `product/engine.py`
lived outside every catalogue. Measured across `openfactory/`: about four hundred Portuguese
string constants outside any `pt-BR` catalogue.

Every Portuguese literal in the core is one of three kinds, each with its own rule:

- WRITTEN TO A PERSON (a frame, a heading, a note): it lives in a catalogue — a dict whose keys
  are languages — beside its English. Its `pt-BR` value is allowed here, its `en` value is checked;
- RECOGNISING WHAT A PERSON WROTE (assent, intents, heading aliases): it stays, in a table declared
  in `RECOGNISERS`, which must carry English too — a recogniser that knows one language is the
  same defect on the way in;
- EVERYTHING ELSE that is still Portuguese is named in `EXEMPT`, literal by literal.

`EXEMPT` ONLY SHRINKS. It is the sweep's remaining work, not a place to put new literals: a new
Portuguese literal fails here, and so does an entry that no longer matches anything — a dead entry
is room for a new literal to hide behind an old one. Move a literal into a catalogue, and delete
its entry in the same commit.
"""

from __future__ import annotations

import ast
import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "openfactory"
EXEMPT_FILE = Path(__file__).with_name("portuguese_literals_not_yet_in_a_catalogue.json")

#: The letters Portuguese writes and English does not.
_PT_LETTERS = re.compile(r"[ãõçáéíóúâêôàÃÕÇÁÉÍÓÚÂÊÔÀ]")
#: Words of Portuguese no English sentence uses, for text written without accents.
_PT_WORDS = re.compile(
    r"(?i)\b(nao|voce|isso|este|esta|cartao|pedido|requisito|quando|porque|ainda|nada|foi|ja"
    r"|tambem|precisa|confirma|registro|preciso|aqui|agora|sobre|pelo|pela|seu|sua|uma|um|para"
    r"|com|que|mais|dos|das|nos|nas|ao|aos|pode|deve|isto|ele|ela|eles|quem|onde|como)\b")
_EN_WORDS = re.compile(r"(?i)\b(the|and|is|to|of|with|when|this|that|you|it|for|are)\b")

#: The keys of a catalogue: a dict with an `en` key and one of these is one.
_PT_KEYS = {"pt-BR", "pt-PT", "pt"}

#: TABLES THAT READ WHAT A PERSON WROTE, as `(path, name)`: every literal inside the assignment of
#: that name is allowed, and the table must carry English as well (checked below).
RECOGNISERS = {
    ("openfactory/adapters/tracker/parse.py", "_ALIASES"),
    ("openfactory/adapters/tracker/parse.py", "_GIVEN"),
    ("openfactory/adapters/tracker/parse.py", "_STEP"),
    ("openfactory/adapters/tracker/parse.py", "_EXAMPLES"),
    ("openfactory/adapters/tracker/parse.py", "_REQUESTER_LABELS"),
    ("openfactory/product/module.py", "_ALSO_CALLED"),
    ("openfactory/language/written.py", "FUNCTION_WORDS"),
}


def is_portuguese(text: str) -> bool:
    if _PT_LETTERS.search(text):
        return True
    hits = _PT_WORDS.findall(text)
    return len(hits) >= 2 and len(hits) > len(_EN_WORDS.findall(text))


def _docstrings(tree: ast.AST) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                out.add(id(first.value))
    return out


def _subtree(node: ast.AST) -> set[int]:
    return {id(n) for n in ast.walk(node)}


def _in_a_catalogue(tree: ast.AST) -> set[int]:
    allowed = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
        if "en" not in keys or not keys & _PT_KEYS:
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value in _PT_KEYS:
                allowed |= _subtree(value)
    return allowed


def _recognisers(tree: ast.AST, rel: str) -> dict[str, ast.AST]:
    names = {name for path, name in RECOGNISERS if path == rel}
    found = {}
    for node in ast.walk(tree):
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, ast.AnnAssign) and node.value else [])
        for target in targets:
            if isinstance(target, ast.Name) and target.id in names:
                found[target.id] = node.value
    return found


def _strings(node: ast.AST) -> list[ast.Constant]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def welded() -> dict[str, list[str]]:
    """Every Portuguese string constant of the package that no rule above allows, by file."""
    out: dict[str, list[str]] = collections.defaultdict(list)
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        allowed = _docstrings(tree) | _in_a_catalogue(tree)
        for table in _recognisers(tree, rel).values():
            allowed |= _subtree(table)
        for node in _strings(tree):
            if id(node) not in allowed and is_portuguese(node.value):
                out[rel].append(node.value)
    return {rel: sorted(found) for rel, found in out.items()}


def _exempt() -> dict[str, list[str]]:
    return json.loads(EXEMPT_FILE.read_text(encoding="utf-8"))


def compare(found: dict[str, list[str]],
            exempt: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """`(new, dead)`: literals no entry covers, and entries no literal matches — counted, so two
    copies of one literal need two entries."""
    new, dead = [], []
    for rel in sorted(set(found) | set(exempt)):
        have = collections.Counter(found.get(rel, []))
        listed = collections.Counter(exempt.get(rel, []))
        new += [f"{rel}: {text!r}" for text in (have - listed).elements()]
        dead += [f"{rel}: {text!r}" for text in (listed - have).elements()]
    return new, dead


def test_no_new_portuguese_literal_and_no_dead_exemption():
    new, dead = compare(welded(), _exempt())
    assert not new, (
        "a Portuguese literal outside any catalogue — put it in a voice catalogue beside its "
        "English (or in a declared recogniser, with English beside it):\n" + "\n".join(new[:20]))
    assert not dead, (
        f"entries of {EXEMPT_FILE.name} that match nothing any more — delete them, the list only "
        "shrinks:\n" + "\n".join(dead[:20]))


def test_every_recogniser_is_declared_where_it_lives_and_carries_english():
    for rel, name in sorted(RECOGNISERS):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        table = _recognisers(tree, rel).get(name)
        assert table is not None, f"{rel} declares no {name} — the recogniser moved or was renamed"
        english = [n.value for n in _strings(table)
                   if n.value.strip() and not is_portuguese(n.value) and n.value.isascii()]
        assert english, f"{rel}::{name} recognises Portuguese only — add the English beside it"


def test_a_catalogues_english_is_english():
    """The half a catalogue is FOR: a Portuguese sentence filed under `en` is the defect itself."""
    wrong = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            pairs = {k.value: v for k, v in zip(node.keys, node.values, strict=True)
                     if isinstance(k, ast.Constant)}
            if "en" in pairs and set(pairs) & _PT_KEYS:
                wrong += [f"{path.relative_to(ROOT)}: {n.value!r}"
                          for n in _strings(pairs["en"]) if _PT_LETTERS.search(n.value)]
    assert not wrong, "\n".join(wrong[:20])


def test_the_detector_sees_what_it_guards():
    """The self-test calls the rule, so a detector gone blind fails here and not in silence."""
    assert is_portuguese("({admins}: o registro precisa da sua confirmação.)")
    assert is_portuguese("preciso de um titulo para abrir o cartao")
    assert is_portuguese("confirmação")
    assert not is_portuguese("({admins}: registering this needs your confirmation.)")
    assert not is_portuguese("a card for the Studio")
    tree = ast.parse('X = {"pt-BR": "não", "en": "no"}\nY = "não"\nZ = {"pt-BR": "sim"}\n')
    allowed = _in_a_catalogue(tree)
    [in_x, bare, lone] = sorted((n for n in _strings(tree) if n.value in ("não", "sim")),
                                key=lambda n: (n.lineno, n.col_offset))
    assert id(in_x) in allowed, "a catalogue's Portuguese is allowed"
    assert id(bare) not in allowed, "a bare literal is not"
    assert id(lone) not in allowed, "nor is a 'catalogue' with no English beside it"
    # AND THE LIST ONLY SHRINKS: an entry that matches nothing is reported, and so is a literal
    # with no entry — counted, so a second copy of an exempt literal is new
    assert compare({"a.py": ["x", "x"]}, {"a.py": ["x"]}) == (["a.py: 'x'"], [])
    assert compare({"a.py": ["x"]}, {"a.py": ["x", "y"]}) == ([], ["a.py: 'y'"])
