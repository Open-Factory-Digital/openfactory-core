"""An Azure Boards project can read and claim only the cards under ONE Epic (#1078).

WHAT WAS FOUND. The pickup queue of an Azure Boards project is the cards of its TEAM's area paths
(`AzureBoardsBoard._team_area_clause`), and nothing narrower. A repository whose work lives under
one Epic of a team that keeps several has no way to say so, and the column the factory reads as its
queue is one the team uses itself (`Approved` on the stock Scrum flow): any card another person
approves in the team's area is a card the poller may claim and pay an agent for. Jira met the same
shape (#752) and answered it with `scope_jql`; this is the Azure Boards counterpart, `scope_epic`.

THE SHAPE, MEASURED against a live project on 2026-10-23 rather than assumed:

  * flat WIQL has no "descendant of" operator, and `[System.Parent]` reaches one level, while the
    depth is the process's (Epic → Feature → Product Backlog Item here);
  * a recursive link query (`FROM WorkItemLinks … MODE (Recursive)`) returns the whole subtree in
    one request — 26 relations for an Epic with 25 descendants, the Epic itself the root;
  * a filter on the TARGET (type, state, column) cannot ride along: in a tree query it applies to
    every node on the path, the Features in between are filtered out, and only the root comes back;
  * an id that does not exist answers 200 with NO relations and no root, while an item without
    children answers 200 with the root alone — so "not there" and "nothing under it" are told apart.

So the board reads the subtree's ids once, then asks the flat query it always asked with
`[System.Id] IN (…)` added. This file drives the REAL `AzureBoardsBoard`, built by the registry row
from a project's tracker options, over a fake Azure DevOps at the one seam the board talks through
(`_client`). The fake keeps a hierarchy and answers both shapes of query the way the measurements
above say Azure does.
"""

from __future__ import annotations

import json
import logging
import re

import pytest

KIND = "Product Backlog Item"
COLUMNS = ("New", "Approved", "Done")
#: the deployment's own mapping — the queue is `Approved`, as the doctor's remedy asks on this flow
MAPPED = {"backlog": "New", "todo": "Approved", "done": "Done"}


class _Azure:
    """One team's board on a process whose backlog level is `Product Backlog Item`, over a work
    item hierarchy. Answers the routes the board really calls; anything else is a failure, because
    a route Azure DevOps never had is a board that only works against its own fake."""

    def __init__(self) -> None:
        #: id → {"type", "column", "parent"}. A column IS a state on this flow.
        self.items: dict[int, dict] = {}
        #: every WIQL the board sent, in order — the tests read WHAT was asked, not just the answer
        self.queries: list[str] = []
        #: every state write, `(id, state)` — the tests that say "nothing was moved" read this
        self.patched: list[tuple[int, str]] = []

    def add(self, number: int, kind: str, *, column: str = "", parent: int | None = None,
            title: str = "") -> None:
        self.items[number] = {"type": kind, "column": column, "parent": parent,
                              "title": title or f"{kind} {number}"}

    def _children(self, number: int) -> list[int]:
        return sorted(n for n, item in self.items.items() if item["parent"] == number)

    def values(self, path: str, params=None, **_kw) -> list:
        if path == "wit/workitems":     # the tracker's batched field read
            return [{"id": n, "fields": {
                        "System.Id": n, "System.Title": self.items[n]["title"],
                        "System.State": self.items[n]["column"],
                        "System.WorkItemType": self.items[n]["type"]}}
                    for n in (int(i) for i in params["ids"].split(","))]
        if re.fullmatch(r"wit/workitemtypes/[^/]+/states", path):
            return [{"name": "New", "category": "Proposed"},
                    {"name": "Approved", "category": "Proposed"},
                    {"name": "Doing", "category": "InProgress"},
                    {"name": "Done", "category": "Completed"}]
        if path == "work/boards":
            return [{"name": "Backlog items"}]
        if re.fullmatch(r"work/boards/[^/]+/columns", path):
            return [{"name": name, "stateMappings": {KIND: name},
                     "columnType": {"New": "incoming", "Done": "outgoing"}.get(name, "inProgress")}
                    for name in COLUMNS]
        raise AssertionError(f"the board listed {path}, a route Azure DevOps never had")

    def call(self, method: str, path: str, *, body=None, **_kw) -> dict:
        if method == "GET" and path.startswith("projects/"):
            return {"defaultTeam": {"name": "factory Team"}}
        if (method, path) == ("GET", "work/teamsettings/teamfieldvalues"):
            return {"field": {"referenceName": "System.AreaPath"}, "values": []}
        if (method, path) == ("POST", "wit/wiql"):
            query = body["query"]
            self.queries.append(query)
            if "FROM WorkItemLinks" in query:
                return self._subtree(query)
            return self._flat(query)
        if path.startswith("wit/workitems/"):       # the move: read the type, write the state
            number = int(path.rsplit("/", 1)[1])
            if method == "GET":
                return {"fields": {"System.WorkItemType": self.items[number]["type"],
                                   "System.State": self.items[number]["column"]}}
            if method == "PATCH":
                self.patched.append((number, body[0]["value"]))
                self.items[number]["column"] = body[0]["value"]
                return {}
        raise AssertionError(f"the board called {method} {path}, a route Azure DevOps never had")

    def _subtree(self, query: str) -> dict:
        root = int(re.search(r"\[Source\]\.\[System\.Id\] = (\d+)", query).group(1))
        if root not in self.items:
            return {"queryType": "tree", "workItemRelations": []}   # measured: 200, no root
        relations = [{"rel": None, "source": None, "target": {"id": root}}]
        pending = [root]
        while pending:
            parent = pending.pop(0)
            for child in self._children(parent):
                relations.append({"rel": "System.LinkTypes.Hierarchy-Forward",
                                  "source": {"id": parent}, "target": {"id": child}})
                pending.append(child)
        return {"queryType": "tree", "workItemRelations": relations}

    def _flat(self, query: str) -> dict:
        """The clauses the board and the tracker really send, each applied only when it is there —
        a fake that filtered by type when the query did not ask would hide the very difference
        between the board's read (typed) and the tracker's (every type)."""
        column = re.search(r"\[System\.BoardColumn\] = '([^']*)'", query)
        title = re.search(r"\[System\.Title\] = '((?:[^']|'')*)'", query)
        types = re.search(r"\[System\.WorkItemType\] IN \(([^)]*)\)", query)
        inside = re.search(r"\[System\.Id\] IN \(([\d, ]+)\)", query)
        wanted = set(re.findall(r"'([^']*)'", types.group(1))) if types else None
        allowed = {int(n) for n in inside.group(1).split(",")} if inside else None
        found = [n for n, item in sorted(self.items.items())
                 if (wanted is None or item["type"] in wanted)
                 and (column is None or item["column"] == column.group(1))
                 and (title is None or item["title"] == title.group(1).replace("''", "'"))
                 and (allowed is None or n in allowed)]
        if "[System.Id] DESC" in query:     # find_ticket asks for the newest first
            found.reverse()
        return {"queryType": "flat", "workItems": [{"id": n} for n in found]}

    @property
    def link_queries(self) -> int:
        return sum("FROM WorkItemLinks" in q for q in self.queries)


def _world() -> _Azure:
    """Two Epics on one team, and a card that hangs under neither.

        100 Epic "the Epic this project is for"
          └─ 101 Feature
               ├─ 102 PBI  Approved      ← the queue, inside
               ├─ 103 PBI  Approved      ← the queue, inside
               └─ 104 PBI  New           ← the backlog, inside
        200 Epic "another piece of the team's work"
          └─ 201 Feature
               └─ 202 PBI  Approved      ← the queue, OUTSIDE (another person approved it)
        300 PBI  Approved                ← the queue, under no Epic at all
    """
    site = _Azure()
    site.add(100, "Epic", column="Doing")
    site.add(101, "Feature", column="Doing", parent=100)
    site.add(102, KIND, column="Approved", parent=101, title="Export the report")
    site.add(103, KIND, column="Approved", parent=101, title="Only inside")
    site.add(104, KIND, column="New", parent=101, title="Backlog inside")
    site.add(200, "Epic", column="Doing")
    site.add(201, "Feature", column="Doing", parent=200)
    # the SAME title as 102, and the newer card: the one an unscoped "already filed?" finds first
    site.add(202, KIND, column="Approved", parent=201, title="Export the report")
    site.add(300, KIND, column="Approved", title="Only outside")
    return site


@pytest.fixture
def azure(tmp_path, monkeypatch):
    """`open(**options) -> (board, site)`: the real board the registry row builds from the tracker
    options a deployment writes, over the fake site."""
    from openfactory.adapters.board.azure_devops import AzureBoardsBoard

    site = _world()
    monkeypatch.setattr(AzureBoardsBoard, "_client", lambda self, **_kw: site)

    def _open(**options: str):
        from openfactory.adapters.board import build_board
        from openfactory.contracts.project import Project, ProviderRef

        project = Project(
            name="acme", repo_path=str(tmp_path),
            tracker=ProviderRef(kind="azure_devops", repo="factory",
                                options={"organization": "acme", "columns": json.dumps(MAPPED),
                                         **options}))
        board = build_board(project, token="t")
        assert type(board).__name__ == "AzureBoardsBoard"
        return board, site
    return _open


# ── the pickup queue ────────────────────────────────────────────────────────────────────────────

def test_a_scoped_board_queues_only_the_cards_under_its_epic(azure):
    """THE BREAK THIS CATCHES: the option is read and nothing uses it, so the queue is the whole
    team's. Three PBIs wait in `Approved` — 102 and 103 under the Epic, 202 under another Epic and
    300 under none — and the poller may claim only the first two."""
    board, _site = azure(scope_epic="100")

    assert board.items_in_status("Approved") == ["102", "103"]


def test_the_backlog_is_scoped_too_so_the_panel_shows_one_epics_board(azure):
    """`columns()` is the panel's board and the gate's reading of "where is this card". Scoping the
    queue alone would leave the Board page showing another Epic's cards in the project's name."""
    board, _site = azure(scope_epic="100")

    assert board.columns() == {"104": "New", "102": "Approved", "103": "Approved"}


def test_an_unscoped_board_reads_what_it_always_read_and_asks_for_no_subtree(azure):
    """A project that declares no `scope_epic` pays nothing and sees everything, exactly as before.
    THE BREAK: the scope read leaking onto the unscoped path — one wasted request per read for
    every Azure Boards project that never asked for a scope."""
    board, site = azure()

    assert board.items_in_status("Approved") == ["102", "103", "202", "300"]
    assert site.link_queries == 0


def test_a_blank_scope_epic_is_no_scope_not_an_empty_one(azure):
    """A YAML key left blank must not become `IN ()`, which Azure refuses, nor a scope that matches
    nothing — it is the absence of a scope, the way a blank `scope_jql` is."""
    board, site = azure(scope_epic="   ")

    assert board.items_in_status("Approved") == ["102", "103", "202", "300"]
    assert site.link_queries == 0


# ── fails closed ────────────────────────────────────────────────────────────────────────────────

def test_an_epic_that_does_not_exist_queues_nothing_it_never_falls_back_to_the_team(azure, caplog):
    """THE BREAK THAT MATTERS MOST. A scope that disappears when it cannot be resolved widens the
    read to the whole team — the accident the option exists to prevent. Azure answers an id that is
    not there with 200 and no relations, which is NOT the same as an Epic with no children."""
    board, _site = azure(scope_epic="999")

    with caplog.at_level(logging.WARNING):
        assert board.items_in_status("Approved") == []
        assert board.columns() is None
    assert "scope_epic" in caplog.text and "999" in caplog.text, caplog.text


#: `1_0` and `+5` are in the list because Python's `int()` ACCEPTS them (10 and 5): they are the
#: values that tell the pattern in `epic_subtree` from a bare `int(epic)`, which would let them
#: through and ask Azure about an id nobody wrote.
@pytest.mark.parametrize("declared", ["Knowledge Base", "1o0", "100,200", "-5", "#100", "1_0", "+5"])
def test_a_scope_epic_that_is_not_an_id_is_unreadable_and_names_the_option(azure, caplog, declared):
    """The option is an id, because a title is not unique. A value that is not one is a typo that
    must not become "no scope" — and the sentence must name the OPTION, because the board's own
    remedy for an unreadable board points at the credential."""
    board, site = azure(scope_epic=declared)

    with caplog.at_level(logging.WARNING):
        assert board.items_in_status("Approved") == []
        assert board.columns() is None
    assert "scope_epic" in caplog.text, caplog.text
    assert site.queries == [], "a value that is not an id must not reach Azure DevOps at all"


def test_a_readable_leaf_scope_is_an_empty_queue_not_an_unreadable_board(azure):
    """Scope resolves a hierarchy root without checking its type. A readable leaf therefore gives
    an empty board (`{}`), where a missing or unreadable root says `None`."""
    board, site = azure(scope_epic="300")       # a card with no children: the root alone

    assert board.items_in_status("Approved") == []
    assert board.columns() == {}
    assert not any("IN (" in q for q in site.queries if "FROM WorkItems " in q), (
        "an empty subtree must not become an empty `IN ()`, which Azure refuses")


# ── cost ────────────────────────────────────────────────────────────────────────────────────────

def test_the_subtree_is_read_once_per_board_not_once_per_column(azure):
    """`columns()` asks every column "who is in you?" — three flat queries here. The subtree must
    not be re-read for each, or one board read costs N+1 requests. THE BREAK: the cache removed."""
    board, site = azure(scope_epic="100")

    board.columns()

    assert site.link_queries == 1
    assert sum("FROM WorkItems " in q for q in site.queries) == len(COLUMNS)


# ── the gate: a card outside the slice ──────────────────────────────────────────────────────────

def test_the_board_says_whether_it_holds_a_card_and_names_its_scope(azure):
    """`catalog._stage` reads `holds(ref)` and `scope_named()` through `getattr` for a card the
    board did not return, so an edit, a close or a removal of ANOTHER Epic's card is refused by
    name. Unscoped, every card is the project's and the answer costs no request."""
    board, site = azure(scope_epic="100")

    assert board.holds("102") is True
    assert board.holds("202") is False
    assert board.holds("300") is False
    assert board.scope_named() == "within scope_epic '100'"

    asked = len(site.queries)       # the fixture hands every board the SAME site
    unscoped, _ = azure()
    assert unscoped.holds("202") is True
    assert unscoped.scope_named() == ""
    assert len(site.queries) == asked, "an unscoped board answered `holds` with a request"


def test_a_board_that_cannot_tell_whether_it_holds_a_card_says_none_not_false(azure):
    """"Could not see" and "it is not ours" are different refusals (#752's rule): the first is
    retried, the second is final. An unresolvable scope is the first."""
    board, _site = azure(scope_epic="999")

    assert board.holds("102") is None


# ── the tracker: the panel, the product role and the "already filed?" check ─────────────────────
#
# The board is the poller's door. The TRACKER is everything else that reads the project's cards —
# `list_tickets` for the panel, the product role and `forget`, `find_ticket` for the splitter's and
# the product role's "was this already filed?". Both read `@project` and nothing narrower, so a
# board scoped to one Epic whose tracker is not would show, and reuse, another Epic's cards.

@pytest.fixture
def tracker(tmp_path, monkeypatch):
    """`open(**options) -> (tracker, site)`: the tracker the REGISTRY ROW builds from the options a
    deployment writes — the option's only road to the tracker — over the same fake site."""
    site = _world()
    monkeypatch.setattr("openfactory.adapters.tracker.azure_devops.AzureDevOpsClient",
                        lambda **_kw: site)

    def _open(**options: str):
        from openfactory.adapters.tracker.registry import build_tracker
        from openfactory.contracts.project import Project, ProviderRef

        project = Project(
            name="acme", repo_path=str(tmp_path),
            tracker=ProviderRef(kind="azure_devops", repo="factory",
                                options={"organization": "acme", "work_item_type": KIND,
                                         **options}))
        built = build_tracker(project, token="t")
        assert type(built).__name__ == "AzureBoardsTracker"
        return built, site
    return _open


def _refs(summaries) -> list[str]:
    return sorted(s.ref for s in summaries)


def test_a_scoped_tracker_lists_only_the_work_items_under_its_epic(tracker):
    """THE BREAK: the panel and the product role read the project's cards, and a tracker that
    ignores the scope shows another Epic's work in this project's name. The Feature is under the
    Epic and is listed with its cards; the other Epic, its Feature and the loose card are not."""
    scoped, _site = tracker(scope_epic="100")

    assert _refs(scoped.list_tickets()) == ["101", "102", "103", "104"]


def test_an_unscoped_tracker_lists_every_work_item_and_asks_for_no_subtree(tracker):
    scoped, site = tracker()

    assert _refs(scoped.list_tickets()) == [
        "100", "101", "102", "103", "104", "200", "201", "202", "300"]
    assert site.link_queries == 0


def test_find_ticket_answers_only_within_the_epic(tracker):
    """The "already filed?" check of the splitter and the product role. Unscoped, it finds the
    NEWEST card of that title, which is 202 — another Epic's — and reuses it instead of filing."""
    scoped, _site = tracker(scope_epic="100")

    assert scoped.find_ticket(title="Export the report") == "102"
    assert scoped.find_ticket(title="Only outside") is None, (
        "a card outside the Epic was reused as if it were this project's")


def test_find_ticket_unscoped_still_finds_the_newest_card_of_the_title(tracker):
    """The control for the test above: without it, `== "102"` could pass for the wrong reason."""
    unscoped, _site = tracker()

    assert unscoped.find_ticket(title="Export the report") == "202"


def test_a_tracker_whose_epic_cannot_be_told_lists_unreadable_and_refuses_to_search(tracker):
    """`list_tickets` has a word for "I could not read" (`None`) and uses it. `find_ticket` does
    not — its `None` means "nothing of that title" — so an unreadable scope there must RAISE, or
    the splitter files a duplicate of a card it could not look for."""
    from openfactory.adapters.azure_devops import AzureDevOpsError

    scoped, _site = tracker(scope_epic="999")

    assert scoped.list_tickets() is None
    with pytest.raises(AzureDevOpsError, match="scope_epic"):
        scoped.find_ticket(title="Export the report")


def test_a_tracker_scope_that_is_not_an_id_never_reaches_azure(tracker):
    from openfactory.adapters.azure_devops import AzureDevOpsError

    scoped, site = tracker(scope_epic="Knowledge Base")

    assert scoped.list_tickets() is None
    with pytest.raises(AzureDevOpsError, match="scope_epic"):
        scoped.find_ticket(title="Export the report")
    assert site.queries == []


def test_the_tracker_reads_the_subtree_once_however_many_questions_it_is_asked(tracker):
    scoped, site = tracker(scope_epic="100")

    scoped.list_tickets()
    scoped.list_tickets()
    scoped.find_ticket(title="Export the report")

    assert site.link_queries == 1


# ── the gate and the doctor, through the code that really reads them ────────────────────────────

def _project(tmp_path, **options: str):
    from openfactory.contracts.project import Project, ProviderRef

    return Project(name="acme", repo_path=str(tmp_path),
                   tracker=ProviderRef(kind="azure_devops", repo="factory",
                                       options={"organization": "acme",
                                                "columns": json.dumps(MAPPED), **options}))


def _gate(project, board, ref: str) -> dict[str, str]:
    """What the edit/close/remove gate answers for `ref`, per act — the real `_stage_refusal`."""
    from openfactory.actions.catalog import _stage_refusal

    return {act: _stage_refusal(project, board, ref, act=act)
            for act in ("edit", "close", "remove")}


def test_a_card_under_another_epic_is_refused_by_name_naming_the_scope(azure, tmp_path):
    """THE BREAK (#752's review, for Azure): an edit, a close or a removal reaches a card by key, so
    another Epic's card is absent from `columns()` and the gate read it as "nobody has moved it".
    The refusal says whose slice it is, which scope, and where to act instead."""
    board, _site = azure(scope_epic="100")

    said = _gate(_project(tmp_path, scope_epic="100"), board, "202")

    for act, sentence in said.items():
        assert "acme's slice" in sentence, (act, sentence)
        assert "(within scope_epic '100')" in sentence, (act, sentence)


def test_a_scope_that_cannot_be_asked_about_a_card_refuses_as_an_unreadable_board(azure, tmp_path):
    """"Could not see" is not "nobody moved it": an epic that cannot be resolved makes the gate say
    the board could not be read, in the words it already uses for that."""
    board, _site = azure(scope_epic="999")

    for act, sentence in _gate(_project(tmp_path, scope_epic="999"), board, "202").items():
        assert "acme's board could not be read" in sentence, (act, sentence)


def test_an_unscoped_azure_boards_gate_asks_nothing_more(azure, tmp_path):
    """A project that declares no scope owns every card of its team: the gate pays no subtree read
    and no extra query for a card the board did not return."""
    board, site = azure()

    _gate(_project(tmp_path), board, "202")

    assert site.link_queries == 0


def test_the_remedy_for_an_unreadable_board_names_the_scope_when_there_is_one(tmp_path):
    """The board's own remedy points at the credential, because that is nearly always the cause
    ("Azure DevOps answers a wrong credential with HTTP 200 and a sign-in page"). With a
    `scope_epic` declared, an Epic that names nothing makes the board exactly as unreadable, and a
    person who is only told to check the PAT looks in the wrong place."""
    from openfactory.adapters.board.factory import _azure_devops

    scoped = _azure_devops.when_unreadable(_project(tmp_path, scope_epic="100"))
    plain = _azure_devops.when_unreadable(_project(tmp_path))

    assert "scope_epic" in scoped and "100" in scoped, scoped
    assert "AZURE_DEVOPS_PAT" in scoped, "the credential is still the first suspect"
    assert "scope_epic" not in plain, plain


# ── the product role: queueing and ordering ─────────────────────────────────────────────────────
#
# `promote` and `reorder` reach a card BY KEY, and ask the board's `holds` about one its batch read
# did not return (#752's review, rounds 2 and 3 and PR #884's point 3). Without `holds` on this
# board they would queue, and rank, another Epic's card from this project.

ANA = "ana-requester-77"


def _product_role(tmp_path, monkeypatch, **options: str):
    """The real `ProductModule` for a project that declares `options`, over a tracker that knows
    just the two things the queueing asks of it."""
    from types import SimpleNamespace

    from openfactory.contracts.project import Project, ProviderRef
    from tests.test_the_product_role_moves_cards_by_key import _module, _product

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    project = Project(
        name="acme", repo_path=str(tmp_path), language="en", product=_product(),
        tracker=ProviderRef(kind="azure_devops", repo="factory",
                            options={"organization": "acme", "columns": json.dumps(MAPPED),
                                     **options}))
    tracker = SimpleNamespace(
        ticket_url=lambda ref: f"https://dev.azure.com/acme/factory/_workitems/edit/{ref}",
        get_ticket=lambda ref: SimpleNamespace(state="open", title="a card", raw=""))
    return _module(project, tmp_path, tracker)


def test_the_product_role_does_not_queue_a_card_under_another_epic(azure, tmp_path, monkeypatch):
    """THE BREAK: the queueing moves a card by key. 202 is in `Approved` under ANOTHER Epic, so the
    scoped batch read leaves it out and, without `holds`, the role would treat "not in the read" as
    "nobody has moved it" and queue it from this project."""
    board, site = azure(scope_epic="100")
    role = _product_role(tmp_path, monkeypatch, scope_epic="100")

    [outside] = role.promote(["202"], actor=ANA, board=board)

    assert not outside.ok
    assert "acme's slice of its board" in outside.detail, outside.detail
    assert site.patched == [], "another Epic's card was moved from this project"


def test_the_product_role_still_queues_a_card_under_its_own_epic(azure, tmp_path, monkeypatch):
    """The control for the test above: the scope must narrow the queueing, not stop it. 104 waits in
    the backlog under the Epic, and is queued."""
    board, site = azure(scope_epic="100")
    role = _product_role(tmp_path, monkeypatch, scope_epic="100")

    [inside] = role.promote(["104"], actor=ANA, board=board)

    assert inside.ok, inside.detail
    assert (104, "Approved") in site.patched
    # the placement writes the card's rank too; what must not happen is a write to ANY other card
    assert {number for number, _ in site.patched} == {104}, site.patched


def test_the_product_role_does_not_queue_when_the_scope_cannot_be_told(azure, tmp_path,
                                                                      monkeypatch):
    """"Could not see" is not "nobody moved it": the batch read is refused (`None`), `holds` cannot
    tell either, and the card is refused as an unreachable board — not sent to the door."""
    board, site = azure(scope_epic="999")
    role = _product_role(tmp_path, monkeypatch, scope_epic="999")

    [only] = role.promote(["104"], actor=ANA, board=board)

    assert not only.ok
    assert site.patched == []


def test_the_product_role_does_not_rank_a_card_under_another_epic(azure, tmp_path, monkeypatch):
    """`place_after` ranks by key, so under a scope `reorder(["202"])` would rank another Epic's
    running card from this project (PR #884's point 3, for Azure)."""
    board, site = azure(scope_epic="100")
    role = _product_role(tmp_path, monkeypatch, scope_epic="100")

    [outside] = role.reorder(["202"], actor=ANA, board=board)

    assert not outside.ok
    assert "acme's slice of its board" in outside.detail, outside.detail
    assert site.patched == []


# ── the ceiling ─────────────────────────────────────────────────────────────────────────────────

def test_a_subtree_too_large_for_one_query_is_refused_by_name_never_cut(azure, caplog, monkeypatch):
    """The subtree goes back into WIQL as `[System.Id] IN (…)`, and a query has a length limit. A
    list cut to fit is a queue missing cards that look as if they were never there, so past the
    ceiling the board is UNREADABLE and says which option and how many. Epic 100 has four
    descendants (101, 102, 103, 104)."""
    monkeypatch.setattr("openfactory.adapters.azure_devops.SCOPE_CEILING", 3)
    board, _site = azure(scope_epic="100")

    with caplog.at_level(logging.WARNING):
        assert board.columns() is None
    assert "scope_epic" in caplog.text and "4 work items" in caplog.text, caplog.text


def test_a_subtree_exactly_at_the_ceiling_is_still_read(azure, monkeypatch):
    """The other side of the boundary: the ceiling is the most a scope MAY name, not one less."""
    monkeypatch.setattr("openfactory.adapters.azure_devops.SCOPE_CEILING", 4)
    board, _site = azure(scope_epic="100")

    assert board.items_in_status("Approved") == ["102", "103"]
