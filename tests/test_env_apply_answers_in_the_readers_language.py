"""`env apply` takes what a person can actually type, and refuses what it cannot (#110).

Measured in the pre-pilot review (2026-08-09), verified adversarially, deferred out of that batch
because it touches the action layer. Three defects, each a different way of being unhelpful:

1. **`--set setup=…` could never work.** `setup` is `list[str]` on the manifest and the transport
   coerces only booleans — so the remedy the CLI itself prints for a missing `setup`, verbatim
   `--set setup=<the answer>`, ended in a Pydantic error. The platform documenting a command that
   cannot succeed is the `conformance`-recommends-`stack: security-oss` shape again.

2. **An unknown name in `--accept` was ignored in silence.** It matched no row, accepted nothing,
   and the refusal two screens down then blamed the reader for not having accepted anything — a
   typo answered with an accusation. Every adapter registry in this codebase gives an unknown
   kind the courtesy of a list; this verb gave none.

3. **The 'nothing to write' hint taught PYTHON API syntax** — `accept=[…]`, `answers={'…': '…'}` —
   to somebody who had just typed `openfactory env apply`. And the schema-error branch beside it
   had the same bug pointing the other way: hardcoded `--set`/`--accept` flags, printed to a panel
   with no command line.

The action layer speaks no transport, which is why the spelling is keyed off `Actor.via` — the one
thing here that knows which door the request came through. Same lesson as `_parse_params`' `flag`.
"""

from __future__ import annotations

import pytest

from openfactory.actions.base import Actor
from openfactory.actions.catalog import (
    _as_the_schema_wants,
    _how_to_say_it,
    _how_to_say_this_field,
    _wants_a_list,
)

CLI = Actor(id="rob", via="cli", admin=True)
PANEL = Actor(id="rob", via="panel", admin=True)
NOBODY = Actor(id="script", admin=True)


# ── 1. a scalar for a list field ────────────────────────────────────────────────────────────────

def test_the_field_the_CLI_tells_people_to_set_is_a_LIST():
    """The premise. If `setup` ever stops being a list this whole coercion is dead weight, and a
    guard that cannot see that is a guard that outlives its reason."""
    assert _wants_a_list("setup"), "setup is no longer a list — re-read why this exists"
    assert not _wants_a_list("base_branch")
    assert not _wants_a_list("validate.test"), (
        "a mapping's leaf is not a list; wrapping it would produce YAML the schema refuses")


def test_one_command_becomes_one_element():
    assert _as_the_schema_wants("setup", "uv sync") == ["uv sync"]


def test_two_commands_joined_the_way_a_HUMAN_writes_them_split():
    """`&&` is how somebody puts two commands on one line, and one line is all `--set` can carry."""
    assert _as_the_schema_wants("setup", "uv sync && uv run pre-commit install") == [
        "uv sync", "uv run pre-commit install"]


def test_a_scalar_field_is_left_alone():
    assert _as_the_schema_wants("base_branch", "main") == "main"


def test_a_value_that_is_ALREADY_a_list_passes_through():
    assert _as_the_schema_wants("setup", ["a", "b"]) == ["a", "b"]


def test_an_unknown_field_name_is_never_reshaped():
    """Only the schema decides. Guessing here would turn a typo into a differently-wrong value
    instead of the named refusal it now gets."""
    assert _as_the_schema_wants("no_such_field", "x") == "x"


@pytest.mark.parametrize("given", ["", "   ", "&&", " && "])
def test_an_EMPTY_answer_is_left_for_the_SCHEMA_to_refuse(given):
    """I got this backwards first, and an existing guard caught it.

    `--set setup=` is somebody saying "nothing". Widening it produced `[""]` — a list the schema
    happily accepts, written into their repository as an install step that runs the empty string.
    This action's rule is that a person's answer is never silently discarded AND never silently
    improved: it goes to `Manifest` as typed, is refused in a sentence naming the field, and
    nothing is written. `test_an_empty_answer_a_human_typed_is_not_silently_dropped` is the guard
    that said so, and it was right."""
    got = _as_the_schema_wants("setup", given)
    assert got == given, f"an empty answer was invented into {got!r}"
    assert not isinstance(got, list), "the schema can no longer refuse it"


# ── 2. an unknown name is refused, naming what exists ───────────────────────────────────────────

class _Row(dict):
    pass


def _apply(**kw):
    """Run the verb against a repository that proposes exactly one INFERRED field."""
    import asyncio

    from openfactory.actions import catalog

    return asyncio.run(catalog._env_apply(**kw))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A registered local checkout whose inference proposes one accept-able field."""
    from openfactory.actions import catalog

    checkout = tmp_path / "app"
    checkout.mkdir()

    class Project:
        name = "app"
        repo_path = str(checkout)
        manifest_path = ".openfactory/project.yaml"

    monkeypatch.setattr(catalog, "_project", lambda name: (Project(), None))
    monkeypatch.setattr(
        catalog, "_proposed_rows",
        lambda proposal: ([{"name": "validate.test", "value": "pytest -q",
                            "confidence": catalog.INFERRED, "source": "Makefile:4", "note": ""}],
                          0))
    monkeypatch.setattr(catalog, "_entry_point", lambda mod, *names: (lambda path: object(), []))
    return checkout


def test_an_unknown_accept_is_REFUSED_and_names_the_wrong_word(repo):
    outcome = _apply(project="app", by=CLI, yes=True, accept=["validate.tests"])

    assert not outcome.ok and outcome.code == "invalid"
    assert "validate.tests" in outcome.message, "it does not say which name was wrong"
    assert outcome.data.get("proposed") == ["validate.test"]
    assert not (repo / ".openfactory" / "project.yaml").exists(), "it wrote anyway"


def test_the_refusal_names_the_fields_that_DO_exist(repo):
    """A SEPARATE STRAY, and not a near-miss of the real name. The first version of this asserted
    `"validate.test" in message` about a run whose typo was `validate.tests` — which CONTAINS it,
    so deleting the "It proposed: …" clause entirely left the assertion green. A substring is not
    a sentence."""
    outcome = _apply(project="app", by=CLI, yes=True, accept=["setup"])

    assert not outcome.ok
    assert "It proposed" in outcome.message, outcome.message
    assert "validate.test" in outcome.message.split("It proposed")[1], (
        "the reader is told their word is wrong and never told which words are right")


def test_the_refusal_does_not_blame_the_reader(repo):
    outcome = _apply(project="app", by=CLI, yes=True, accept=["nope"])
    assert "none carries a value" not in outcome.message, (
        "a typo is still being answered with 'you accepted nothing'")


def test_ACCEPT_ALL_is_not_an_unknown_field(repo):
    outcome = _apply(project="app", by=CLI, yes=True, accept=["all"])
    assert outcome.ok or "not a field" not in outcome.message


def test_a_KNOWN_accept_still_works(repo):
    """The positive twin — a refusal that also refuses the correct spelling is worse than the
    silence it replaced."""
    outcome = _apply(project="app", by=CLI, yes=True, accept=["validate.test"])
    assert outcome.ok, outcome.message


def test_an_ANSWER_for_a_field_nobody_proposed_is_still_honoured(repo):
    """Deliberately NOT symmetric with `accept`. Writing a field the inference never proposed is
    this verb's design — a person in the room outranks a reading — and a name the SCHEMA refuses
    is caught downstream with the field named."""
    outcome = _apply(project="app", by=CLI, yes=True, answers={"base_branch": "develop"})
    assert outcome.ok, outcome.message
    assert "develop" in (repo / ".openfactory" / "project.yaml").read_text()


def test_answering_a_field_the_read_DID_propose_is_reshaped_too(repo, monkeypatch):
    """TWO BRANCHES WRITE AN ANSWER — the row loop, for a field the read proposed, and the tail,
    for one it did not. The first version of this file only ever exercised the tail, so a mutation
    removing the coercion from the row loop sat green: the pilot's own `--set setup=…` on a
    repository whose read DOES propose `setup` would still have died in Pydantic."""
    from openfactory.actions import catalog

    monkeypatch.setattr(
        catalog, "_proposed_rows",
        lambda proposal: ([{"name": "setup", "value": None, "confidence": catalog.UNKNOWN,
                            "source": "", "note": "nothing declared an install"}], 0))

    outcome = _apply(project="app", by=CLI, yes=True, answers={"setup": "uv sync"})

    assert outcome.ok, outcome.message
    import yaml as yaml_mod

    from openfactory.contracts.manifest import Manifest
    body = (repo / ".openfactory" / "project.yaml").read_text()
    assert Manifest.model_validate(yaml_mod.safe_load(body)).setup == ["uv sync"]


def test_the_pilots_own_command_now_writes_a_valid_manifest(repo):
    """The whole card in one call: the remedy the CLI prints, run verbatim."""
    outcome = _apply(project="app", by=CLI, yes=True, answers={"setup": "uv sync"})

    assert outcome.ok, outcome.message
    body = (repo / ".openfactory" / "project.yaml").read_text()
    assert "setup:" in body and "uv sync" in body
    import yaml as yaml_mod

    from openfactory.contracts.manifest import Manifest
    Manifest.model_validate(yaml_mod.safe_load(body))  # raises if the shape is wrong


# ── 3. the reader's own vocabulary ──────────────────────────────────────────────────────────────

def test_the_CLI_is_told_about_FLAGS():
    accept, answer = _how_to_say_it(CLI)
    assert "--accept" in accept and "--set" in answer
    assert "accept=[" not in accept, "a command-line reader is being taught Python"


def test_the_PANEL_is_not_told_about_flags():
    accept, answer = _how_to_say_it(PANEL)
    assert "--" not in accept + answer, (
        "a surface with no command line is being handed command-line flags")


def test_an_UNKNOWN_caller_gets_the_neutral_shape():
    accept, answer = _how_to_say_it(NOBODY)
    assert "accept" in accept and "answers" in answer


def test_the_schema_error_names_the_field_in_the_readers_language():
    """This branch had the bug pointing the OTHER way — hardcoded `--set`/`--accept`, printed to
    a panel that has neither."""
    assert _how_to_say_this_field(CLI, "components", answer=False) == "`--accept components`"
    assert _how_to_say_this_field(CLI, "validate.test", answer=True) == "`--set validate.test=…`"
    panel = _how_to_say_this_field(PANEL, "components", answer=False)
    assert "--" not in panel and "components" in panel


def test_the_refusal_uses_it(repo, monkeypatch):
    """Reachability: the strings above must be what an operator actually receives."""
    from openfactory.actions import catalog

    monkeypatch.setattr(
        catalog, "_proposed_rows",
        lambda proposal: ([{"name": "setup", "value": [], "confidence": catalog.OBSERVED,
                            "source": "read", "note": ""}], 0))
    cli = _apply(project="app", by=CLI, yes=True)
    panel = _apply(project="app", by=PANEL, yes=True)

    assert "--accept" in cli.message and "--set" in cli.message, cli.message
    assert "--accept" not in panel.message and "--set" not in panel.message, panel.message
    assert "accept" in panel.message, panel.message


def test_every_spelling_carries_all_four_forms():
    """A table entry short one form would raise IndexError inside a refusal — the one code path
    that must never fail, since it is what the reader gets instead of a traceback."""
    from openfactory.actions.catalog import _SPELLING, _SPELLING_DEFAULT

    for name, entry in list(_SPELLING.items()) + [("default", _SPELLING_DEFAULT)]:
        assert len(entry) == 4, f"{name} has {len(entry)} forms"
        assert all(isinstance(s, str) and s for s in entry), name
    # the per-field forms are format strings and must accept `name` without blowing up
    for via in (*_SPELLING, "something-else"):
        who = Actor(id="x", via=via)
        assert "f.x" in _how_to_say_this_field(who, "f.x", answer=True)
        assert "f.x" in _how_to_say_this_field(who, "f.x", answer=False)
