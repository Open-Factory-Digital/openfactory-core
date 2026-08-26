"""A board this platform CREATED must be readable by this platform (pilot, 2026-08-13/14).

Twice now the same board — `solo-dev/1`, created by `openfactory project init` and confirmed
by the operator — answered `unknown owner type` on every read, so `doctor` reported it
unreadable and the poller would never have picked anything up.

WHY IT SURVIVED THE FIRST FIX. `gh project view --owner <login>` asks gh to TYPE the login, and
gh resolves organisation and user in one document: a token without `read:org` — which a
personal account has no reason to carry, and which this platform's own guide does not ask for —
fails the organisation half and takes the whole answer down. The first fix retried the same
command as `@me`; when that retry ALSO failed, `_run_gh` returned the first result and the
retry's own error was swallowed, so the field could not tell "the fix did not run" from "the
fix ran and did not help".

Board CREATION never had this problem: it asks our own GraphQL, organisation first and user
second, treating a failed org probe as "not an org". The read path now does the same.

  1. a personal-account board resolves through the user root, columns and all;
  2. an organisation board still resolves through the organisation root;
  3. when NEITHER answers, every attempt's own error is in the message — a swallowed retry is a
     fix nobody can confirm;
  4. a failure that is NOT the owner-typing one is never retried into a confusing second story.
"""

from __future__ import annotations

import json

import pytest

from openfactory.adapters.tracker import github_project as gp


class _Run:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def _board(monkeypatch, *, gh_project: _Run, graphql):
    """A board whose `gh project ...` answers `gh_project` and whose GraphQL answers `graphql`
    (a callable of the query string, returning data or raising BoardSetupError)."""
    calls: list[list[str]] = []

    def fake_run(args, capture_output=True, text=True, timeout=60, env=None, check=False):
        calls.append(list(args))
        return _Run(returncode=1, stderr="unknown owner type")

    monkeypatch.setattr(gp.subprocess, "run", fake_run)

    def fake_graphql(query, token, **variables):
        calls.append(["graphql", query])
        return graphql(query)

    monkeypatch.setattr(
        "openfactory.adapters.tracker.github_board_setup._gh_graphql", fake_graphql)
    board = gp.GitHubProjectBoard(owner="solo-dev", number="1", token="ghp_pat")
    return board, calls


def _project_payload(root: str) -> dict:
    return {root: {"projectV2": {
        "id": "PVT_kw", "field": {"id": "PVTSSF_x", "options": [
            {"id": "o1", "name": "Backlog"}, {"id": "o2", "name": "TO-DO"},
            {"id": "o3", "name": "Done"}]}}}}


def test_a_personal_accounts_board_resolves_through_the_user_root(monkeypatch):
    from openfactory.adapters.tracker.github_board_setup import BoardSetupError

    def graphql(query):
        if "organization(login:" in query:
            raise BoardSetupError("the tracker token is missing `read:org`")
        return _project_payload("user")

    board, _ = _board(monkeypatch, gh_project=_Run(returncode=1, stderr="unknown owner type"),
                      graphql=graphql)

    assert board.column_names() == ["Backlog", "TO-DO", "Done"], (
        "the board this platform created is still unreadable by it")


def test_an_organisation_board_still_resolves_through_the_organisation_root(monkeypatch):
    def graphql(query):
        assert "organization(login:" in query, "the org root was not tried first"
        return _project_payload("organization")

    board, _ = _board(monkeypatch, gh_project=_Run(returncode=1, stderr="unknown owner type"),
                      graphql=graphql)

    assert board.column_names() == ["Backlog", "TO-DO", "Done"]


def test_when_nothing_answers_every_attempt_is_in_the_message(monkeypatch):
    from openfactory.adapters.tracker.github_board_setup import BoardSetupError

    def graphql(query):
        root = "organization" if "organization(login:" in query else "user"
        raise BoardSetupError(f"HTTP 403 refusing the {root} query")

    board, _ = _board(monkeypatch, gh_project=_Run(returncode=1, stderr="unknown owner type"),
                      graphql=graphql)

    with pytest.raises(RuntimeError) as err:
        board._ensure_meta()

    text = str(err.value)
    assert "--owner solo-dev" in text, "gh's own failure is missing"
    assert "as a organization" in text and "as a user" in text, (
        f"a swallowed attempt is a fix nobody can confirm: {text}")


def test_a_failure_that_is_not_owner_typing_is_never_retried_into_another_story(monkeypatch):
    """A real permission failure must surface as itself."""
    def fake_run(args, capture_output=True, text=True, timeout=60, env=None, check=False):
        return _Run(returncode=1, stderr="HTTP 401: Bad credentials")

    monkeypatch.setattr(gp.subprocess, "run", fake_run)

    def _boom(*a, **kw):
        raise AssertionError("the GraphQL fallback ran for a credential failure")

    monkeypatch.setattr(
        "openfactory.adapters.tracker.github_board_setup._gh_graphql", _boom)
    board = gp.GitHubProjectBoard(owner="acme", number="1", token="ghp_pat")

    with pytest.raises(RuntimeError, match="Bad credentials"):
        board._ensure_meta()


def test_the_columns_a_working_gh_returns_are_untouched(monkeypatch):
    """The path every healthy deployment takes must not have moved."""
    def fake_run(args, capture_output=True, text=True, timeout=60, env=None, check=False):
        if "field-list" in args:
            return _Run(stdout=json.dumps({"fields": [
                {"name": "Status", "id": "F1",
                 "options": [{"id": "o1", "name": "Backlog"}, {"id": "o2", "name": "TO-DO"}]}]}))
        return _Run(stdout=json.dumps({"id": "PVT_kw"}))

    monkeypatch.setattr(gp.subprocess, "run", fake_run)

    def _boom(*a, **kw):
        raise AssertionError("the fallback ran when gh answered perfectly well")

    monkeypatch.setattr(
        "openfactory.adapters.tracker.github_board_setup._gh_graphql", _boom)
    board = gp.GitHubProjectBoard(owner="acme", number="1", token="t")

    assert board.column_names() == ["Backlog", "TO-DO"]


# ── the property is the PRODUCT's, not GitHub's ────────────────────────────────────────────────

def test_the_board_contract_makes_every_vendor_answer_the_same_question():
    """Twice in four days the same defect surfaced on GitHub, and twice the fix landed in the
    GitHub adapter while nothing asked Azure DevOps or Jira the same question. The three-state
    answer (`[names]` / `None` / never a raise) is now part of the contract `openfactory
    conformance-adapter` holds EVERY board to."""
    from openfactory.adapters.board.base import BoardAdapter
    from openfactory.conformance.adapters import check_board

    class _Board(BoardAdapter):
        def __init__(self, columns):
            self._columns = columns

        def column_names(self):
            if isinstance(self._columns, Exception):
                raise self._columns
            return self._columns

        def items_in_status(self, status):
            return []

        def set_column(self, *, issue, issue_url, name):
            return False

        def pickup_column(self):
            return "TO-DO"

    rules = lambda board: {f.rule for f in check_board(board)}  # noqa: E731

    assert not rules(_Board(["Backlog", "TO-DO"])), "a healthy board was faulted"
    assert not rules(_Board(None)), "None is the legitimate 'could not read' answer"
    assert "board.columns-unreadable-is-None" in rules(_Board([])), (
        "an empty list still passes as a board with no columns — the shape that let doctor "
        "report a permissions failure as a healthy setup")
    assert "board.columns-unreadable-is-None" in rules(_Board(RuntimeError("401"))), (
        "a raise still escapes into doctor as a traceback instead of a finding")
