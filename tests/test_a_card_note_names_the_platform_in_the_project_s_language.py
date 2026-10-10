"""A card's note names the platform in the project's language, and a person by their name (#546).

The card's door writes notes such as `_Fechado por {who}._`, and `{who}` was the transition's
`by=`: a person's name when a person made the change, and an internal English actor name when the
platform did — so a Portuguese project's card read "_Fechado por the workflow._".

Every platform actor the code passes now has two forms in each language: the subject ("a fábrica")
and the agent with its preposition ("pela fábrica"), because Portuguese contracts it and a
template cannot contract a word it does not know. A GUARD reads the code for every literal it
passes to the door, and fails on one with no entry.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from openfactory.product import voice

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: The calls whose `by=` reaches a card's note, and the note writers' own `who=`.
DOOR = {"transition", "_ready_to_try"}
NOTES = {"card_note", "card_close_note", "card_reopen_note", "card_edit_note"}


def _module_strings(path: pathlib.Path) -> dict[str, str]:
    """`NAME = "text"` at a module's top level."""
    out: dict[str, str] = {}
    for node in ast.parse(path.read_text()).body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def _resolved(name: str, path: pathlib.Path, tree: ast.Module) -> str | None:
    """A name's string value: the module's own constant, or one imported from another module."""
    own = _module_strings(path)
    if name in own:
        return own[name]
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(
                "openfactory"):
            for alias in node.names:
                if (alias.asname or alias.name) == name:
                    source = ROOT / (node.module.replace(".", "/") + ".py")
                    if source.is_file():
                        return _module_strings(source).get(alias.name)
    return None


def _actors_the_code_passes() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
            wanted = "by" if name in DOOR else "who" if name in NOTES else None
            if wanted is None:
                continue
            for kw in call.keywords:
                if kw.arg != wanted:
                    continue
                for node in ast.walk(kw.value):
                    value = None
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        value = node.value
                    elif isinstance(node, ast.Name):
                        value = _resolved(node.id, path, tree)
                    if value:
                        where = f"{path.relative_to(ROOT)}:{call.lineno}"
                        found.setdefault(value, []).append(where)
    return found


def test_every_platform_actor_the_code_passes_to_the_door_has_a_voice_entry():
    found = _actors_the_code_passes()
    assert {"the workflow", "observed", "the job"} <= set(found), (
        f"the guard no longer sees the door's actors — it is reading nothing: {sorted(found)}")
    missing = {who: where for who, where in found.items() if who not in voice._PLATFORM_ACTORS}
    assert not missing, (
        f"these reach a card's note as the code's own name — add each to "
        f"voice._PLATFORM_ACTORS, in pt-BR and en: {missing}")


@pytest.mark.parametrize("who", sorted(voice._PLATFORM_ACTORS))
@pytest.mark.parametrize("event", sorted(voice._CARD_NOTE["en"]) + ["closed", "reopened"])
def test_no_note_in_portuguese_carries_the_code_s_english_name(who, event):
    note = voice.card_note(event, who=who, why="", language="pt-BR")
    assert who not in note, note
    assert " por a " not in note and " por o " not in note, f"uncontracted: {note}"


def test_the_platform_is_named_with_its_preposition_contracted():
    assert voice.card_close_note(who="the workflow", reason="pedido duplicado",
                                 language="pt-BR") == "_Fechado pela fábrica._ pedido duplicado"
    assert voice.card_close_note(who="the workflow", reason="duplicate",
                                 language="en") == "_Closed by the factory._ duplicate"
    assert voice.card_reopen_note(who="observed", language="pt-BR") == (
        "_Reaberto por alguém no próprio quadro._")
    assert voice.card_note("promoted", who="the product role", language="pt-BR") == (
        "_Colocado na fila pelo papel de produto._")


def test_where_the_platform_is_the_subject_it_is_named_as_one():
    assert "disse a fábrica" in voice.card_note("stage_rejected", who="the workflow",
                                                language="pt-BR")
    assert voice.card_edit_note(who="the product role", parts=["title"],
                                language="pt-BR").startswith("_O papel de produto corrigiu")


def test_a_person_is_named_as_they_are():
    assert voice.card_close_note(who="ana-requester-77", reason="x", language="pt-BR") == (
        "_Fechado por ana-requester-77._ x")
    assert voice.card_close_note(who="ana-requester-77", reason="x", language="en") == (
        "_Closed by ana-requester-77._ x")
    assert voice.card_edit_note(who="ana-requester-77", parts=["title"],
                                language="pt-BR").startswith("_ana-requester-77 corrigiu")
