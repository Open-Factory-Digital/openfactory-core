"""Creating a Projects v2 board with the platform's columns — the act `init` performs (C-16).

SEPARATE FROM `github_project.py` ON PURPOSE. That module is the RUNTIME board adapter — it moves
cards on every job and is built through the registry. This is a ONE-SHOT onboarding act performed
by a human at a terminal, before the project exists; folding it into the adapter would give the
money-gated runtime surface a method that creates infrastructure.

THE OPTION REWRITE IS SAFE HERE AND ONLY HERE. `updateProjectV2Field` re-mints every option id
and drops every assignment (the board-wipe memory, learned the hard way on a LIVE board). On the
board this module just created there are no assignments to drop — which is exactly why creation
and mutation live together in one act instead of the mutation being offered à la carte.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess

#: The neutral error every board-setup act raises, re-exported under the name this module's
#: callers have always imported it by. One type, so `init` catches it whichever vendor acted.
from openfactory.adapters.board_setup.base import BoardSetupError

log = logging.getLogger("openfactory.tracker.github_project")

_TIMEOUT = 60

#: The canonical column set, in board order — DEFAULT_COLUMNS' values plus the queue's own
#: ordering. A client who wants their own names renames AFTER creation and maps them with
#: `columns:` in the registry (C-14); init creates the platform's vocabulary so the mapping
#: starts as the identity.
CANONICAL_COLUMNS = ("Backlog", "TO-DO", "In progress", "In review", "Needs Action", "Done")




#: The REQUIRED half of GitHub's scope refusal — "requires one of the following scopes:
#: ['read:org']". The GRANTED half is a second, identically-shaped list in the same sentence,
#: which is exactly how the first version of this read `project` off a token that had it.
_REQUIRED_SCOPES = re.compile(
    r"requires? one of the following scopes:\s*\[([^\]]*)\]", re.IGNORECASE)


def _missing_scopes(stderr: str) -> list[str]:
    """The scopes GitHub says the query NEEDS, minus the ones it says the token HAS."""
    required = _REQUIRED_SCOPES.search(stderr)
    if not required:
        return []
    granted = re.search(r"granted the:?\s*\[([^\]]*)\]", stderr, re.IGNORECASE)

    def _names(raw: str) -> list[str]:
        return [s.strip().strip("'\"") for s in raw.split(",") if s.strip()]

    have = set(_names(granted.group(1)) if granted else [])
    return [s for s in _names(required.group(1)) if s not in have]


def _gh_graphql(query: str, token: str | None, **variables: str) -> dict:
    env = {**os.environ, "GH_TOKEN": token} if token else None
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        cmd += ["-f", f"{key}={value}"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT,
                           check=False, env=env)
    except FileNotFoundError:
        raise BoardSetupError(
            "the `gh` CLI is not installed — board creation speaks through it. Install it "
            "(https://cli.github.com) and run `gh auth login`.") from None
    if p.returncode != 0:
        stderr = p.stderr.strip()
        low = stderr.lower()
        missing = _missing_scopes(stderr)
        if missing:
            # READ THE REQUIRED LIST, NEVER THE GRANTED ONE. The first version of this matched
            # "scope" plus the word "project" anywhere in the message — and GitHub prints BOTH
            # lists, so a token that already HAD `project` was told to add `project`, while the
            # scope actually required (`read:org`) went unnamed. Found live in the pilot's
            # first board attempt (2026-08-12) and fixed against that verbatim message.
            raise BoardSetupError(
                f"the tracker token is missing {', '.join('`' + s + '`' for s in missing)} — "
                f"GitHub refused the query that needs it. Regenerate it at "
                f"github.com/settings/tokens (classic) with `repo` + `project`, adding what is "
                f"named here, never `workflow`; put it in OPENFACTORY_TRACKER_TOKEN, recreate "
                f"the stack with --env-file, and re-run — the board step is idempotent. "
                f"GitHub said: {stderr[:200]}")
        if "bad credentials" in low or "401" in low:
            raise BoardSetupError(
                "GitHub refused the tracker token — it is wrong, revoked, or EXPIRED (a "
                "classic token defaults to 30 days). Generate a new one at "
                "github.com/settings/tokens with scopes `repo` + `project`, put it in "
                "OPENFACTORY_TRACKER_TOKEN, recreate the stack with --env-file, and re-run. "
                f"GitHub said: {stderr[:200]}")
        raise BoardSetupError(f"gh api graphql failed: {stderr[:300]}")
    try:
        return json.loads(p.stdout)["data"]
    except (ValueError, KeyError) as exc:
        raise BoardSetupError(f"unreadable GraphQL answer: {p.stdout[:200]}") from exc


def _owner_id(owner: str, token: str | None) -> str:
    """The node id behind an org OR a user login — tried in that order, because init cannot know
    which kind of owner it was handed and GitHub answers them with different roots.

    THE ORG PROBE MAY NOT DECIDE THE OUTCOME. `organization(login:)` needs `read:org`, which is
    an ORGANISATION scope — meaningless on a personal account — and GitHub answers a token
    without it by FAILING the query rather than returning null. So a personal-account board,
    with the exact `repo` + `project` token this platform's own guide prescribes, died on a
    scope it must never have needed: the fallback that exists for precisely this case was never
    reached (measured live in the pilot, 2026-08-12). A failed org probe is now "not an org",
    which is the only thing it can honestly mean here; the USER probe's failure is the one that
    speaks."""
    try:
        data = _gh_graphql(
            "query($login: String!) { organization(login: $login) { id } }", token, login=owner)
        org = (data.get("organization") or {}).get("id")
        if org:
            return org
    except BoardSetupError as exc:
        log.info("the organization probe for %r failed (%s) — treating %r as a personal "
                 "account and asking for the user instead", owner, str(exc)[:120], owner)
    data = _gh_graphql(
        "query($login: String!) { user(login: $login) { id } }", token, login=owner)
    user = (data.get("user") or {}).get("id")
    if user:
        return user
    raise BoardSetupError(f"no organization or user called {owner!r} is visible to this token")


def create_board(*, owner: str, title: str, token: str | None = None) -> tuple[str, str]:
    """Create a Projects v2 board named `title` under `owner`, with the canonical columns.

    Returns `(board number, url)` — the number is what the registry's `board_number` wants.
    Raises `BoardSetupError` with an actionable sentence; never leaves a half-described state
    unreported (a created board whose columns failed is SAID, because the board exists either
    way and silence would hide where the retry must start)."""
    if not token and not os.environ.get("GH_TOKEN"):
        # REFUSE IN OUR VOCABULARY, BEFORE the subprocess. With no token, `gh` answers "run
        # `gh auth login` … or populate GH_TOKEN" — the vendor tool's remedy, in a container
        # where neither is a thing the operator should do. The first pilot funnel run hit
        # exactly this (2026-08-10) and the operator was handed gh's words instead of ours.
        raise BoardSetupError(
            "no tracker credential is configured — creating the board needs one. Set "
            "OPENFACTORY_TRACKER_TOKEN in .env.compose (a classic PAT with scopes repo + "
            "project — a PERSONAL account's board cannot use the App token, "
            "docs/setup/github.md §6), recreate the stack with --env-file, and re-run "
            "`openfactory project init` — the board step is idempotent")
    owner_id = _owner_id(owner, token)
    data = _gh_graphql(
        "mutation($ownerId: ID!, $title: String!) {"
        " createProjectV2(input: {ownerId: $ownerId, title: $title})"
        " { projectV2 { id number url } } }",
        token, ownerId=owner_id, title=title)
    project = (data.get("createProjectV2") or {}).get("projectV2") or {}
    project_id, number, url = project.get("id"), project.get("number"), project.get("url", "")
    if not (project_id and number is not None):
        raise BoardSetupError("the board was not created — GraphQL answered without a project")

    data = _gh_graphql(
        "query($id: ID!) { node(id: $id) { ... on ProjectV2 {"
        " field(name: \"Status\") { ... on ProjectV2SingleSelectField { id } } } } }",
        token, id=project_id)
    field_id = (((data.get("node") or {}).get("field")) or {}).get("id")
    if not field_id:
        raise BoardSetupError(
            f"board #{number} was created ({url}) but its Status field could not be read — "
            f"add the columns by hand or re-run init after deleting it")

    options = ", ".join(
        f'{{name: "{name}", color: GRAY, description: ""}}' for name in CANONICAL_COLUMNS)
    try:
        _gh_graphql(
            "mutation($fieldId: ID!) {"
            " updateProjectV2Field(input: {fieldId: $fieldId, singleSelectOptions: ["
            + options +
            "]}) { projectV2Field { ... on ProjectV2SingleSelectField { id } } } }",
            token, fieldId=field_id)
    except BoardSetupError as exc:
        raise BoardSetupError(
            f"board #{number} was created ({url}) but setting its columns failed: {exc}. "
            f"The safe retry is deleting the empty board and running init again.") from exc
    return str(number), url
