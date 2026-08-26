"""C-18 (#50): the product owns the board; the repository moves to the ticket.

One Projects v2 board routes cards to SEVERAL source repositories — the common enterprise shape
(F-04's fixture, client 2's real Deskline shape). The wire form is the ref itself: a bare
`'12'` means the project's default repo (byte-for-byte today's behaviour, so nothing persisted
changes identity), and `owner/name#12` carries the card's own repo to every consumer — the
clone, the tracker call, the board move, the issue URL, the box.

Every test here is a seam the repo used to be ASSUMED at, now proven to FOLLOW the ref.
"""

from __future__ import annotations

import pytest

from openfactory.contracts.refs import qualify_ref, split_repo_ref

API = "AcmeFixtures/fx-multirepo-api"
WEB = "AcmeFixtures/fx-multirepo-web"


# ── the grammar ─────────────────────────────────────────────────────────────────────────────────

def test_a_bare_ref_means_the_default_repo():
    assert split_repo_ref("12", API) == (API, "12")
    assert split_repo_ref("#12", API) == (API, "12")
    assert split_repo_ref("  #12  ", API) == (API, "12")


def test_a_qualified_ref_carries_its_own_repo():
    assert split_repo_ref(f"{WEB}#3", API) == (WEB, "3")


def test_a_human_typed_hash_on_a_qualified_ref_does_not_corrupt_the_repo():
    """`#owner/name#3` — the decoration comes off before the split, or the repo would keep it."""
    assert split_repo_ref(f"#{WEB}#3", API) == (WEB, "3")


def test_a_jira_ref_with_a_dash_stays_bare():
    """`CONT-412` has no `#`, and `PROJ#12` has no `/` — neither is a repo-qualified ref."""
    assert split_repo_ref("CONT-412", "PROJ") == ("PROJ", "CONT-412")
    assert split_repo_ref("PROJ#12", "X") == ("X", "PROJ#12")


def test_qualify_is_the_inverse_of_split():
    for ref in ("12", f"{WEB}#3"):
        repo, bare = split_repo_ref(ref, API)
        assert qualify_ref(repo, bare, API) == ref.strip()


def test_the_default_repo_never_qualifies():
    """The bare spelling is what every persisted key and workflow id already uses — qualifying
    the common case would split one ticket into two identities."""
    assert qualify_ref(API, "12", API) == "12"
    assert qualify_ref("", "12", API) == "12"
    assert qualify_ref(WEB, "3", API) == f"{WEB}#3"


# ── the board qualifies on the way out and matches (number, repo) on the way in ─────────────────

def _board(monkeypatch, items):
    from openfactory.adapters.tracker.github_project import GitHubProjectBoard

    b = GitHubProjectBoard("acme", "7", default_repo=API)
    monkeypatch.setattr(b, "_board_items", lambda: items)
    return b


def test_the_pickup_queue_qualifies_foreign_cards_and_only_those(monkeypatch):
    b = _board(monkeypatch, [
        {"id": "A", "number": 3, "repo": API, "status": "TO-DO"},
        {"id": "B", "number": 3, "repo": WEB, "status": "TO-DO"},
    ])

    assert b.items_in_status("TO-DO") == ["3", f"{WEB}#3"]


def test_columns_never_collapse_two_same_numbered_cards_into_one_key(monkeypatch):
    """A board that thinks two tickets are one moves the wrong card, silently."""
    b = _board(monkeypatch, [
        {"id": "A", "number": 3, "repo": API, "status": "TO-DO"},
        {"id": "B", "number": 3, "repo": WEB, "status": "Done"},
    ])

    cols = b.columns()

    assert cols == {"3": "TO-DO", f"{WEB}#3": "Done"}


def test_a_move_with_a_qualified_ref_finds_the_cards_own_item(monkeypatch):
    """The consequence that matters: `…-web#3` must edit item B, never item A."""
    import subprocess as sp


    b = _board(monkeypatch, [
        {"id": "A", "number": 3, "repo": API, "status": "TO-DO"},
        {"id": "B", "number": 3, "repo": WEB, "status": "TO-DO"},
    ])
    b._project_id, b._status_field_id = "P", "F"
    b._option_ids = {"In progress": "OPT"}
    edited: list[list[str]] = []

    def _fake_run(args, **kw):
        edited.append(list(args))

        class _P:
            returncode = 0
            stderr = ""

        return _P()

    monkeypatch.setattr(sp, "run", _fake_run)
    monkeypatch.setattr(b, "add_item", lambda **kw: None)

    ok = b.set_column(issue=f"{WEB}#3", issue_url=f"https://github.com/{WEB}/issues/3",
                      name="In progress")

    assert ok, "the move failed outright"
    # the item id travels as `-f item=<id>` since the writes became GraphQL mutations (a
    # personal-account board cannot use `gh project item-edit` at all) — the property is the
    # same: the card that gets moved is the one belonging to THIS repository
    ids = [x[len("item="):] for a in edited for x in a if x.startswith("item=")]
    assert ids == ["B"], f"the wrong card was moved: {ids}"


def test_a_bare_ref_still_matches_the_default_repos_card(monkeypatch):
    import subprocess as sp

    b = _board(monkeypatch, [
        {"id": "B", "number": 3, "repo": WEB, "status": "TO-DO"},
        {"id": "A", "number": 3, "repo": API, "status": "TO-DO"},
    ])
    b._project_id, b._status_field_id = "P", "F"
    b._option_ids = {"Done": "OPT"}
    edited: list[list[str]] = []

    def _fake_run(args, **kw):
        edited.append(list(args))

        class _P:
            returncode = 0
            stderr = ""

        return _P()

    monkeypatch.setattr(sp, "run", _fake_run)
    monkeypatch.setattr(b, "add_item", lambda **kw: None)

    assert b.set_column(issue="3", issue_url=f"https://github.com/{API}/issues/3", name="Done")
    # the item id travels as `-f item=<id>` since the writes became GraphQL mutations (a
    # personal-account board cannot use `gh project item-edit` at all) — the property is the
    # same: the card that gets moved is the one belonging to THIS repository
    ids = [x[len("item="):] for a in edited for x in a if x.startswith("item=")]
    assert ids == ["A"], "a bare ref matched a foreign card because it came first in the scan"


def test_an_item_without_a_repo_still_matches_by_number(monkeypatch):
    """A provider whose items carry no repo (or a pre-C-18 fake) keeps today's behaviour."""
    import subprocess as sp

    b = _board(monkeypatch, [{"id": "A", "number": 5, "repo": "", "status": "TO-DO"}])
    b._project_id, b._status_field_id = "P", "F"
    b._option_ids = {"Done": "OPT"}
    monkeypatch.setattr(sp, "run", lambda *a, **k: type("P", (), {"returncode": 0, "stderr": ""})())
    monkeypatch.setattr(b, "add_item", lambda **kw: None)

    assert b.set_column(issue="5", issue_url="u", name="Done")


# ── the tracker locates every per-ticket op at the ref's repo ───────────────────────────────────

def _tracker(monkeypatch, calls):
    from openfactory.adapters.tracker.github import GitHubIssuesTracker

    t = GitHubIssuesTracker(API)

    def _fake_gh(args, timeout=60):
        calls.append(list(args))

        class _P:
            returncode = 0
            stdout = ('{"number": 3, "title": "t", "body": "", "labels": [], '
                      '"author": {"login": "x"}, "assignees": []}')
            stderr = ""

        return _P()

    monkeypatch.setattr(t, "_gh", _fake_gh)
    return t


def test_get_ticket_reads_from_the_refs_repo(monkeypatch):
    calls: list[list[str]] = []
    t = _tracker(monkeypatch, calls)

    ticket = t.get_ticket(f"{WEB}#3")

    assert ["issue", "view", "3", "--repo", WEB] == calls[0][:5]
    assert ticket.repo == WEB, "the Ticket must say where it actually lives"


def test_a_bare_ref_keeps_reading_from_the_default_repo(monkeypatch):
    calls: list[list[str]] = []
    t = _tracker(monkeypatch, calls)

    t.get_ticket("#3")

    assert ["issue", "view", "3", "--repo", API] == calls[0][:5]


def test_comment_and_close_land_on_the_refs_repo(monkeypatch):
    calls: list[list[str]] = []
    t = _tracker(monkeypatch, calls)

    t.comment(f"{WEB}#3", "hello")
    t.close_ticket(f"{WEB}#3", "done", delivered=True)

    for args in calls:
        assert "--repo" in args and args[args.index("--repo") + 1] == WEB, args


# ── the worker routes the box, the clone and the URL through the ref ────────────────────────────

def _project():
    from openfactory.contracts.project import Project, ProviderRef

    return Project(name="fx-multirepo", repo_path="unused",
                   tracker=ProviderRef(kind="github", repo=API))


def test_the_box_gets_the_cards_repo_and_a_bare_issue(monkeypatch):
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal.activities import _box_for
    from openfactory.runtime.temporal.io import RunJobInput

    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: _project())

    box = _box_for(RunJobInput(project="fx-multirepo", issue=f"{WEB}#3"))

    assert box.repo == WEB
    assert box.issue == "3", "inside the box the ref is bare — branches and gh calls need it so"


def test_a_bare_issue_boxes_exactly_as_before(monkeypatch):
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal.activities import _box_for
    from openfactory.runtime.temporal.io import RunJobInput

    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: _project())

    box = _box_for(RunJobInput(project="fx-multirepo", issue="3"))

    assert (box.repo, box.issue) == (API, "3")


def test_two_repos_never_share_one_checkout():
    from openfactory.runtime.temporal.activities import _checkout_key, _ref_repo

    p = _project()
    assert _checkout_key(p, _ref_repo(p, "3")[0]) == "fx-multirepo"
    foreign = _checkout_key(p, _ref_repo(p, f"{WEB}#3")[0])
    assert foreign != "fx-multirepo", (
        "a preflight against …-api would read …-web's manifest and size the wrong world")
    assert "/" not in foreign, "the cache key becomes a directory name"


# ── the forge's one REST-composed op follows the PR's own URL ───────────────────────────────────

def test_update_branch_updates_the_prs_own_repo(monkeypatch):
    from openfactory.adapters.forge.github import GitHubForge

    f = GitHubForge(API)
    calls: list[list[str]] = []

    def _fake_gh(args, timeout=60):
        calls.append(list(args))

        class _P:
            returncode = 0
            stdout = ""
            stderr = ""

        return _P()

    monkeypatch.setattr(f, "_gh", _fake_gh)

    f.update_branch(pr=f"https://github.com/{WEB}/pull/9")

    assert any(f"repos/{WEB}/pulls/9/update-branch" in " ".join(a) for a in calls), calls
    assert not any(f"repos/{API}/" in " ".join(a) for a in calls), (
        "the default repo's same-numbered PR would have been updated instead")


def test_update_branch_on_a_bare_number_keeps_the_default_repo(monkeypatch):
    from openfactory.adapters.forge.github import GitHubForge

    f = GitHubForge(API)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        f, "_gh",
        lambda args, timeout=60: (calls.append(list(args)),
                                  type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})())[1])

    f.update_branch(pr="9")

    assert any(f"repos/{API}/pulls/9/update-branch" in " ".join(a) for a in calls), calls


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── the LOCAL runner, which C-18's first pass left reading the project default ──────────────────
#
# FOUND LIVE (fx-multirepo web#1, 2026-08-04). The board, the tracker, the Fargate box and the
# preflight clone all followed the ref; `build_runner` did not. A qualified card cloned the
# project's DEFAULT repository, the agent edited another product's files, and `gh pr create`
# refused with "No commits between main and sdlc/1" — and the only reason nothing worse happened
# is that the default repo had just merged a branch of that name.

def test_the_runner_works_the_CARDS_repository_not_the_projects_default():
    from openfactory.runtime.temporal.activities import _runner_view

    view, key = _runner_view(_project(), f"{WEB}#1")

    # THE TRACKER STAYS PUT, and this assertion used to say the opposite.
    #
    # C-18's own sentence is "the board belongs to the PRODUCT; only the checkout and the container
    # need to tell two repositories apart" — and the code moved the tracker anyway. GitHub hid it
    # for free: there a card's repository IS the repository its issue lives in, so rewriting
    # `tracker.repo` was merely redundant. Every method already resolves the card's repo per
    # operation through `_locate` → `split_repo_ref`, asserted just below.
    #
    # On Azure DevOps the two are different LEVELS: `tracker.repo` names the ADO PROJECT holding
    # the work items, and the card's repository is one of the N git repos inside it. Rewriting the
    # first with the second produced `/Deskline/fx-dsk-ui/_apis/wit/workitems/15` and a 404
    # about a missing CONTROLLER — an error that reads like a platform routing bug rather than a
    # coordinate mistake. Found on the first real multi-repo card, on the first provider where the
    # two levels differ.
    assert view.tracker.repo == API, (
        "the board belongs to the product; moving the tracker breaks any provider whose tracker "
        "coordinate is not a git repository"
    )
    assert view.forge.repo == WEB, "the PR would be opened against the wrong repository"
    assert view.ci.repo == WEB
    assert view.repo_path.endswith(f"{WEB}.git"), "the clone would fetch the wrong code"
    assert key != "fx-multirepo", "two repositories would share one checkout"


def test_a_bare_card_gets_the_project_UNTOUCHED():
    """The regression path: a single-repo project must reach byte-for-byte the object, key and
    checkout it always had — the view is only for a card that names another repository."""
    from openfactory.runtime.temporal.activities import _runner_view

    project = _project()
    view, key = _runner_view(project, "1")

    assert view is project, "a bare card must not travel through a copy at all"
    assert key == "fx-multirepo"


def test_the_view_never_mutates_the_registry_entry():
    """The registry object is shared across jobs in a long-lived worker: rewriting it would leak
    this card's repository into every later ticket."""
    from openfactory.runtime.temporal.activities import _runner_view

    project = _project()
    before = project.repo_path
    _runner_view(project, f"{WEB}#1")

    assert project.tracker.repo == API
    assert project.forge.repo == API
    assert project.repo_path == before


def test_the_view_keeps_the_deployments_own_host():
    """A GitHub Enterprise install registers `https://ghe.acme.com/...` — swapping the slug keeps
    that host, while composing a github.com URL would send the clone to the public internet."""
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.runtime.temporal.activities import _runner_view

    project = Project(name="p", repo_path=f"https://ghe.acme.com/{API}.git",
                      tracker=ProviderRef(kind="github", repo=API))

    view, _ = _runner_view(project, f"{WEB}#1")

    assert view.repo_path == f"https://ghe.acme.com/{WEB}.git"


def test_the_PRODUCTS_identity_does_not_move_with_the_repository():
    """`name` is the product: the journal, the log dir, the channel and the board all key off it,
    and the panel reads a path computed from the REAL project. Only the checkout and the container
    need to tell two repositories apart."""
    from openfactory.runtime.temporal.activities import _runner_view

    view, _ = _runner_view(_project(), f"{WEB}#1")

    assert view.name == "fx-multirepo"


# ── the action layer: every surface a human acts through ────────────────────────────────────────

def test_a_qualified_ref_is_accepted_by_the_one_validator_every_surface_uses():
    """FOUND LIVE: `resume` on a multi-repo card was refused as "not a ticket reference" — so the
    panel, Slack and the CLI could all SEE the card and none could act on it."""
    from openfactory.actions import _clean_ref

    ref, problem = _clean_ref(f"{WEB}#1")

    assert problem == "", problem
    assert ref == f"{WEB}#1"


def test_the_human_hash_still_comes_off_a_qualified_ref():
    from openfactory.actions import _clean_ref

    assert _clean_ref(f"#{WEB}#1")[0] == f"{WEB}#1", "'#owner/name#1' and 'owner/name#1' are one"


def test_what_was_refused_before_is_still_refused():
    """Widening a validator is where a hole gets opened. `/` and `#` reach a workflow id and a
    filename, so exactly two path segments and one hash — never a third, never a traversal."""
    from openfactory.actions import _clean_ref

    for bad in ("owner/name#", "/name#1", "owner/#1", "a/b/c#1", "../../etc#1", "owner/name",
                "owner name#1", "owner/name#1;rm -rf /", ""):
        assert _clean_ref(bad)[1], f"{bad!r} was accepted"


def test_a_bare_ref_is_refused_exactly_as_before():
    from openfactory.actions import _clean_ref

    assert _clean_ref("189")[0] == "189"
    assert _clean_ref("CONT-412")[0] == "CONT-412"
    assert _clean_ref("12a b")[1]


def test_a_qualified_ref_makes_a_SAFE_and_DISTINCT_journal_name():
    """The ref becomes a filename. Two same-numbered cards from different repos must land on two
    journals, and neither may escape the log directory."""
    from openfactory.paths import journal_stem

    web = journal_stem(f"{WEB}#1")
    api = journal_stem("1")

    assert web != api
    assert "/" not in web and ".." not in web and not web.startswith(".")


def test_each_shape_keeps_its_OWN_length_bound():
    """The bare bound is what stops a ref becoming an unreasonable workflow id or filename.
    Making room for `owner/name#` must not quietly make room for a 160-character bare ref."""
    from openfactory.actions import _ISSUE_MAX, _QUALIFIED_MAX, _clean_ref

    assert _clean_ref("a" * _ISSUE_MAX)[1] == ""
    assert _clean_ref("a" * (_ISSUE_MAX + 1))[1], "the bare bound was widened by the qualified one"
    assert _clean_ref(f"{WEB}#1")[1] == ""
    assert _clean_ref("o/" + "n" * _QUALIFIED_MAX + "#1")[1]


def test_the_github_tracker_still_reaches_the_CARDS_repo_without_the_view_moving_it():
    """The positive twin for the assertion above, and the reason it is safe.

    Leaving `tracker.repo` alone would be a regression if anything depended on the view rewriting
    it. Nothing does: the GitHub tracker resolves the card's repository on EVERY operation from the
    ref itself, and the project's own repo is only the fallback for a bare one."""
    from openfactory.adapters.tracker.github import GitHubIssuesTracker
    from openfactory.runtime.temporal.activities import _runner_view

    view, _ = _runner_view(_project(), f"{WEB}#1")
    tracker = GitHubIssuesTracker(view.tracker.repo, token="x")

    assert tracker._locate(f"{WEB}#1") == (WEB, "1"), "a qualified ref must reach the card's repo"
    assert tracker._locate("42") == (API, "42"), "a bare ref must still mean the project's own"


def test_an_azure_card_keeps_the_BOARDS_coordinate_and_moves_only_the_code():
    """The case that exposed it: two coordinates at different levels.

    `tracker.repo` is the ADO PROJECT (where work items live); the card's repository is a git repo
    inside it. Both must end up right, and before this they could not.
    """
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.runtime.temporal.activities import _runner_view

    opts = {"organization": "acme-ai"}
    project = Project(
        name="fx-dsk", repo_path="https://dev.azure.com/acme-ai/Deskline/_git/fx-dsk-flows",
        tracker=ProviderRef(kind="azure_devops", repo="Deskline", options=opts),
        forge=ProviderRef(kind="azure_devops", repo="fx-dsk-flows", options=opts),
        ci=ProviderRef(kind="azure_devops", repo="fx-dsk-flows", options=opts),
    )

    view, key = _runner_view(project, "Deskline/fx-dsk-ui#15")

    assert view.tracker.repo == "Deskline", "the work items live in the PROJECT, not the repo"
    assert view.forge.repo == "Deskline/fx-dsk-ui"
    assert view.repo_path == "https://dev.azure.com/acme-ai/Deskline/_git/fx-dsk-ui"
    assert key != "fx-dsk", "two repositories of one product would share a checkout"
