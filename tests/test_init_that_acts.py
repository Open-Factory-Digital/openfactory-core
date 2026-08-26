"""`init` acts: from nothing to a project that can move a ticket, two manual steps left (C-16).

The rule: anything the tool can do through an API, the tool does — a walkthrough step a human
performs by hand is a step that can be skipped, mistyped, or done in the wrong order. Projects v2
has an API and the platform already speaks it — so `init` creates the board, registers the
project into runtime state, attaches the board, and scaffolds the manifest. What stays manual is
irreducible: the OAuth grant and the harness login.

CONVERGES, NEVER SCRIPTS. Each step runs only when its result is missing, so a failed board
creation is retried by running init again — the alternative is a human hand-assembling the
remaining half, which is the walkthrough this wave exists to delete.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from openfactory import namespace
from openfactory.cli import _infer_repo, app


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


class _FakeGh:
    """The four GraphQL round trips, answered by QUERY SHAPE — a stub that replays a script by
    call order would keep passing after the order changed underneath it."""

    def __init__(self, *, org_exists=True, fail_options=False):
        self.org_exists = org_exists
        self.fail_options = fail_options
        self.mutations: list[str] = []

    def __call__(self, cmd, **kw):
        query = next(a.split("=", 1)[1] for a in cmd if a.startswith("query="))

        class _P:
            returncode = 0
            stderr = ""

        if "organization(login" in query:
            _P.stdout = json.dumps({"data": {"organization":
                                             {"id": "ORG1"} if self.org_exists else None}})
        elif "user(login" in query:
            _P.stdout = json.dumps({"data": {"user": {"id": "USR1"}}})
        elif "createProjectV2" in query:
            self.mutations.append("create")
            _P.stdout = json.dumps({"data": {"createProjectV2": {"projectV2": {
                "id": "PROJ1", "number": 7, "url": "https://github.com/orgs/o/projects/7"}}}})
        elif 'field(name' in query:
            _P.stdout = json.dumps({"data": {"node": {"field": {"id": "FIELD1"}}}})
        elif "updateProjectV2Field" in query:
            self.mutations.append("options")
            if self.fail_options:
                _P.returncode = 1
                _P.stderr = "GraphQL: boom"
                _P.stdout = ""
            else:
                _P.stdout = json.dumps({"data": {"updateProjectV2Field":
                                                 {"projectV2Field": {"id": "FIELD1"}}}})
        else:  # pragma: no cover - an unmatched query IS the failure
            raise AssertionError(f"unexpected GraphQL query: {query[:120]}")
        return _P


def _wire(monkeypatch, fake):
    import openfactory.adapters.tracker.github_board_setup as setup

    monkeypatch.setattr(setup.subprocess, "run", fake)
    monkeypatch.setattr("openfactory.credentials.tracker_token", lambda: "tok")


def test_init_takes_a_fresh_product_to_a_moving_ticket_shape(env, monkeypatch):
    """The card's done-when, minus the two irreducible steps — which the output must NAME."""
    fake = _FakeGh()
    _wire(monkeypatch, fake)

    result = CliRunner().invoke(app, ["project", "init", "acme", str(env),
                                      "--repo", "org/acme"])

    assert result.exit_code == 0, result.output
    assert fake.mutations == ["create", "options"], "the board was not created with its columns"
    from openfactory.registry import ProjectRegistry

    project = ProjectRegistry().get("acme")
    assert project.tracker.options["board_number"] == "7"
    assert (env / namespace.DIR / "project.yaml").exists(), "the manifest was not scaffolded"
    # THE PROPERTY, NOT THE WORDING. This pinned the literal "OAuth"/"harness" of the old
    # closing lines, which said "what remains is the irreducible pair" — a claim about state
    # the command never measured, and one that told the pilot both steps were pending after he
    # had done both (2026-08-12). What must hold is that the two things init CANNOT do are
    # named, and that the reader is handed the command that CAN measure them.
    assert "repository" in result.output and "coding agent" in result.output, (
        "the two things no command can do for you were not named")
    assert "doctor acme" in result.output, "the verb that measures them is not offered"


def test_init_converges_instead_of_failing_on_rerun(env, monkeypatch):
    """Run twice: the second run performs NOTHING and says what already exists — convergence is
    what makes init the retry for its own failures."""
    fake = _FakeGh()
    _wire(monkeypatch, fake)
    runner = CliRunner()
    assert runner.invoke(app, ["project", "init", "acme", str(env),
                               "--repo", "org/acme"]).exit_code == 0

    second = runner.invoke(app, ["project", "init", "acme"])

    assert second.exit_code == 0, second.output
    assert fake.mutations == ["create", "options"], "the second run re-created the board"
    assert "already" in second.output


def test_a_failed_board_leaves_a_registered_ticketsonly_project_and_says_the_retry(env, monkeypatch):
    """Tickets-only is a legitimate state, not debris — and the message must say the retry is
    `init` again, or the human hand-assembles the half that failed."""
    fake = _FakeGh(fail_options=True)
    _wire(monkeypatch, fake)

    result = CliRunner().invoke(app, ["project", "init", "acme", str(env),
                                      "--repo", "org/acme"])

    assert result.exit_code == 1
    from openfactory.registry import ProjectRegistry

    assert ProjectRegistry().get("acme").tracker.options.get("board_number") is None
    assert "re-run" in result.output or "init" in result.output
    # CONVERGES is the docstring's own word: the board failing must not make the manifest
    # scaffold unreachable — a boardless project could never COMPLETE init otherwise
    # (pre-pilot review, 2026-08-09). Exit stays 1: a script must notice the board step failed.
    from openfactory import namespace as ns

    assert (env / ns.MANIFEST).exists(), "the scaffold must still be written after a board failure"


def test_a_user_owner_falls_back_from_the_org_query(env, monkeypatch):
    """GitHub answers orgs and users from different roots, and init cannot know which it was
    handed."""
    fake = _FakeGh(org_exists=False)
    _wire(monkeypatch, fake)

    result = CliRunner().invoke(app, ["project", "init", "acme", str(env),
                                      "--repo", "someuser/acme"])

    assert result.exit_code == 0, result.output
    assert fake.mutations == ["create", "options"]


def test_the_repo_is_inferred_from_the_clone_url():
    assert _infer_repo("https://github.com/org/name.git") == "org/name"
    assert _infer_repo("git@github.com:org/name.git") == "org/name"
    assert _infer_repo("/some/local/path") == ""
