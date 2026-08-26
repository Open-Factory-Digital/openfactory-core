"""A board this platform CREATED must be readable by the same platform, on a personal account.

The pilot, one command after the board was created successfully (2026-08-13):

    could not read the columns of solo-dev/1 (gh project view 1 --owner solo-dev
    --format json failed: unknown owner type)

The asymmetry is the finding. Board CREATION asks our own GraphQL and falls through
`organization(login:)` → `user(login:)`, which is why it worked. Board READING goes through
`gh project …`, and gh resolves `--owner` by typing the login itself — a token without
`read:org` (which a PERSONAL account has no reason to carry) fails the organisation half and
takes the whole answer with it. So the platform created a board it then reported as unreadable,
and the doctor blamed the credential, which was correct and perfectly configured.

`@me` is gh's own spelling for the authenticated user and needs no organisation scope. It is
tried ONCE, on that one error string, so a genuine permission failure still surfaces as itself.

AND IT WAS NOT ENOUGH — the same board was still unreadable a day later (2026-08-14). The
double below decides the outcome: it answers `@me` with SUCCESS, so what these tests prove is
that the retry is attempted and used, never that it works in the field. When `@me` fails too,
`_run_gh` returns the FIRST result and the retry's own error is swallowed. The read path now
resolves the owner through GraphQL exactly as creation does, and every attempt's error travels
into the message —see `test_a_personal_accounts_board_is_readable.py`, which starts from the
case this file's double cannot express.
"""

from __future__ import annotations

import json

import pytest

from openfactory.adapters.tracker import github_project as gp


class _Calls:
    def __init__(self, *, fail_owner: str = "", stdout: str = "{}"):
        self.seen: list[list[str]] = []
        self.fail_owner = fail_owner
        self.stdout = stdout

    def __call__(self, cmd, **kw):
        self.seen.append(list(cmd))
        owner = cmd[cmd.index("--owner") + 1] if "--owner" in cmd else ""

        class _P:
            returncode = 1 if owner == self.fail_owner else 0
            stdout = "" if owner == self.fail_owner else self.stdout
            stderr = ("gh: unknown owner type\n" if owner == self.fail_owner else "")
        return _P()


def test_a_command_gh_cannot_type_is_retried_as_me(monkeypatch):
    calls = _Calls(fail_owner="solo-dev", stdout='{"fields": []}')
    monkeypatch.setattr(gp.subprocess, "run", calls)

    answer = gp._gh_json(["project", "view", "1", "--owner", "solo-dev", "--format", "json"],
                         "ghp_token")

    assert answer == {"fields": []}
    owners = [c[c.index("--owner") + 1] for c in calls.seen if "--owner" in c]
    assert owners == ["solo-dev", "@me"], (
        f"the personal-account retry did not happen: {owners}")


def test_a_REAL_failure_is_not_retried_into_a_confusing_second_message(monkeypatch):
    """Only that one error string earns the retry — a bad token must still say so."""
    class _Denied:
        def __init__(self):
            self.seen = []

        def __call__(self, cmd, **kw):
            self.seen.append(list(cmd))

            class _P:
                returncode = 1
                stdout = ""
                stderr = "gh: Bad credentials (HTTP 401)"
            return _P()

    denied = _Denied()
    monkeypatch.setattr(gp.subprocess, "run", denied)

    with pytest.raises(RuntimeError, match=r"Bad credentials"):
        gp._gh_json(["project", "view", "1", "--owner", "acme", "--format", "json"], "tok")

    assert len(denied.seen) == 1, "a permission failure was retried"


def test_a_command_with_no_owner_is_never_rewritten(monkeypatch):
    """The rewrite has an owner to rewrite or it does nothing — a call with no `--owner` that
    somehow hits the same error must be reported, not retried into an identical failure."""
    seen: list[list[str]] = []

    def _always_unknown(cmd, **kw):
        seen.append(list(cmd))

        class _P:
            returncode = 1
            stdout = ""
            stderr = "gh: unknown owner type"
        return _P()

    monkeypatch.setattr(gp.subprocess, "run", _always_unknown)

    with pytest.raises(RuntimeError, match=r"unknown owner type"):
        gp._gh_json(["api", "rate_limit"], "tok")

    assert len(seen) == 1, "a command with no --owner was retried"


def test_the_WRITES_never_ask_gh_to_type_the_owner_at_all(monkeypatch):
    """THE FIFTH SIGHTING OF THE SAME ASYMMETRY, and the first that reached the pilot's board
    while a job ran (2026-08-15). Reads had already moved to our own GraphQL; the writes were
    still `gh project item-add` / `item-edit`, which type the `--owner` login and fail a personal
    account's token with *"unknown owner type"* / *"missing required scopes [read:org]"*. Every
    card add and every column move failed for eleven minutes while `#87` went from TO-DO to an
    open PR, and the board never moved.

    The retry-as-`@me` is not the fix here — not asking the question is. A mutation takes ids
    (`projectId`, `itemId`), and ids have no owner type, so the failure mode cannot recur.
    """
    calls = _Calls(fail_owner="solo-dev", stdout=json.dumps({
        "data": {"repository": {"issue": {"id": "I_1"}},
                 "addProjectV2ItemById": {"item": {"id": "ITEM1"}}},
        "id": "PID", "fields": [{"name": "Status", "id": "FID", "options": []}]}))
    monkeypatch.setattr(gp.subprocess, "run", calls)
    board = gp.GitHubProjectBoard(owner="solo-dev", number="1", token="tok")
    board._project_id = "PID"          # meta already resolved (its own retry is tested above)
    board._status_field_id = "FID"

    board.add_item(issue_url="https://github.com/solo-dev/podbeam/issues/1")

    writes = [c for c in calls.seen if "addProjectV2ItemById" in " ".join(c)]
    assert writes, f"no card add was attempted; calls: {[c[:3] for c in calls.seen]}"
    assert not any("--owner" in c for c in writes), (
        "the write still asks gh to type the owner — the one thing a personal account's token "
        "cannot answer")
