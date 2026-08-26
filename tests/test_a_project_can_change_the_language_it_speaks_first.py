"""The language a project speaks FIRST is a setting somebody can change (#124, 2026-08-16).

`language` has existed since the product role and had exactly one way in: `--language`, offered by
`project add` and `project init`, at registration, once. After that the only route was editing the
registry YAML **inside the worker image** and rebuilding — the same "edit a file by hand" that
`set_model` and `set_docs_repo` were built to remove. An operator who onboarded a project in
Portuguese and later wanted English had no command at all.

THE RULE THIS SETTING IS HALF OF, decided by the product owner today:

    a PROACTIVE message from the project — a park alert, a scheduled round, a comment it writes on
    a ticket nobody asked for — is written in the configured language;

    a REPLY follows the language of the QUESTION. Someone who writes in English gets English,
    whatever the project is configured for.

The second half already exists for the agents (`adapters/agent/roles.py::language_directive`, whose
docstring states exactly this and is prepended to every harness prompt). This file guards the first
half's plumbing, and guards that the command does not accidentally promise to govern the second.
"""

from __future__ import annotations

import inspect
import pathlib
import tempfile

import pytest

from openfactory.registry import ProjectRegistry

_ROW = ("projects:\n"
        "  acme:\n"
        "    name: acme\n"
        "    repo_path: https://github.com/o/r.git\n"
        "    language: pt-BR\n")


@pytest.fixture
def registry() -> pathlib.Path:
    path = pathlib.Path(tempfile.mkdtemp()) / "registry.yaml"
    path.write_text(_ROW)
    return path


def test_the_language_survives_a_write_and_a_read(registry):
    assert ProjectRegistry(registry).get("acme").language == "pt-BR"
    ProjectRegistry(registry).set_language("acme", "en")
    assert ProjectRegistry(registry).get("acme").language == "en", (
        "the only way to change this is still editing YAML inside the worker image")


def test_nothing_else_in_the_row_is_disturbed(registry):
    """`set_docs_repo` rebuilds a nested block and `set_model` rewrites a field; both leave the
    rest alone, and a setter that quietly dropped `repo_path` would unregister the project."""
    ProjectRegistry(registry).set_language("acme", "en")
    p = ProjectRegistry(registry).get("acme")
    assert p.repo_path == "https://github.com/o/r.git" and p.name == "acme"


def test_a_language_with_no_name_in_it_is_refused(registry):
    with pytest.raises(ValueError):
        ProjectRegistry(registry).set_language("acme", "   ")
    assert ProjectRegistry(registry).get("acme").language == "pt-BR", "it wrote the blank anyway"


def test_an_unknown_project_is_refused_by_NAME(registry):
    with pytest.raises(KeyError):
        ProjectRegistry(registry).set_language("nope", "en")


def test_a_language_nobody_translated_is_still_accepted(registry):
    """The same argument `set_model` makes about model strings. The phrasebooks carry `en` and
    `pt-BR` and fall back to English for anything else (`voice.py::_pick`), while the AGENTS take
    the value verbatim as an instruction — so `de` produces sensible agent output today and
    understandable canned text. Refusing it here would block the half that already works."""
    ProjectRegistry(registry).set_language("acme", "de")
    assert ProjectRegistry(registry).get("acme").language == "de"


# ── the command, and what it must NOT claim ─────────────────────────────────────────────────────

def test_the_cli_exposes_it_next_to_the_other_registry_setters():
    from openfactory.cli import project_set_language

    assert callable(project_set_language)
    # A CALL, NOT A SUBSTRING. `assert "set_language" in src` was a TAUTOLOGY (guard audit,
    # 2026-08-17): the source includes `def project_set_language`, whose own name contains the
    # anchor — so the real `reg.set_language(...)` call could be deleted with the guard green.
    import ast

    tree = ast.parse(inspect.getsource(project_set_language))
    calls = {getattr(n.func, "attr", "") for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "set_language" in calls, "the command does not reach the setter"
    handled = {getattr(h.type, "id", "") for n in ast.walk(tree)
               if isinstance(n, ast.Try) for h in n.handlers}
    for refusal in ("KeyError", "ValueError"):
        assert refusal in handled, (
            f"an operator triggering a {refusal} gets a traceback instead of a sentence")


def test_the_command_says_a_REPLY_is_not_governed_by_it():
    """The rule has two halves and this setting is one. A command that said only "this project now
    speaks English" would leave an operator expecting their Portuguese question to be answered in
    English — and it will not be, by design."""
    from openfactory.cli import project_set_language

    said = inspect.getsource(project_set_language).lower()
    assert "repl" in said, "the command never mentions that replies follow the asker"
    assert "question" in said or "asked" in said


def test_the_two_halves_of_the_rule_agree_with_the_HARNESS_that_implements_one():
    """Derived from the code that already carries the rule for agents, so the CLI cannot drift
    from it: `language_directive` chooses a default for unprompted speech and defers to the
    incoming language on a reply."""
    from openfactory.adapters.agent.roles import language_directive

    directive = language_directive("pt-BR")
    assert "pt-BR" in directive, "the configured language stopped reaching the agent at all"
    lowered = directive.lower()
    assert "repl" in lowered or "answer" in lowered, (
        "the harness instruction no longer distinguishes speaking first from replying — the CLI's "
        "promise about replies would then be the only place that rule exists")
