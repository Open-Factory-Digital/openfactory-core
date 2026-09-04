"""The product owner writes the backlog order — #33's second verb at the frontier.

`propose_queue` said what should start next and wrote nothing; a reprioritisation lived in a
chat message until somebody dragged cards. No board adapter had a write for order: the port has
`set_state`, `set_column`, labels, `create_ticket` — and nothing for rank. So this is a capability
first and a verb second: `Rankable.place_after` on the three boards shipped here, and
`ProductModule.reorder` chaining it top-first.

THE PROVIDERS ARE EXERCISED AT THEIR OWN SEAMS, the way their existing guards do it: the Azure
Boards client faked at `_client`, `gh` faked at `_run_gh`, the Jira tracker faked at `_call`. What
is asserted is what each provider was asked to write — the rank value, the mutation, the payload —
never a reply the test invented.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory.actions import catalog
from openfactory.actions.base import PRODUCT, Actor
from openfactory.adapters.board.azure_devops import AzureBoardsBoard
from openfactory.adapters.board.base import BoardAdapter, Rankable
from openfactory.adapters.board.jira import JiraProjectBoard
from openfactory.adapters.tracker import github_project as gp
from openfactory.adapters.tracker.jira import JiraTracker
from tests.test_product_module import ADMIN, OUTSIDER
from tests.test_product_module import _module as _product_module

ROOT = Path(__file__).resolve().parents[1]


# ── the capability ──────────────────────────────────────────────────────────────────────────────

class _Plain:
    """A board that reads and moves and does not rank — a client's own adapter, or a double."""

    def url(self): return ""
    def columns(self): return {}
    def column_names(self): return []
    def pickup_column(self): return "TO-DO"
    def items_in_status(self, status): return []
    def add_item(self, *, issue_url): return None
    def set_column(self, *, issue, issue_url, name): return True
    def set_status(self, *, issue, issue_url, state, needs_person=None): return True


def test_rank_is_a_capability_beside_the_port_not_a_promise_every_board_makes():
    """A method on `BoardAdapter` would make every double and every client adapter claim it or
    fail `isinstance`; a second protocol lets a board that cannot rank still BE a board."""
    assert isinstance(_Plain(), BoardAdapter)
    assert not isinstance(_Plain(), Rankable)
    assert isinstance(AzureBoardsBoard(organization="o", project="p", token="t"), Rankable)
    assert isinstance(GitHub(), Rankable)
    assert isinstance(JiraProjectBoard(tracker=_Jira()), Rankable)


# ── Azure Boards: a midpoint in the field the process uses ──────────────────────────────────────

class _AdoClient:
    """Records what the board asked of Azure DevOps; answers ranks per work item."""

    def __init__(self, ranks: dict[int, dict[str, float]], *, breaks: bool = False):
        self.ranks, self.breaks = ranks, breaks
        self.calls: list[tuple] = []

    def call(self, method, path, **kw):
        self.calls.append((method, path, kw))
        if self.breaks:
            raise RuntimeError("503")
        if method == "GET":
            number = int(path.rsplit("/", 1)[1])
            return {"fields": {k: v for k, v in self.ranks.get(number, {}).items()}}
        return {}


def _ado(monkeypatch, *, column: list[str], ranks: dict[int, dict[str, float]],
         breaks: bool = False) -> tuple[AzureBoardsBoard, _AdoClient]:
    board = AzureBoardsBoard(organization="acme", project="factory", token="t")
    client = _AdoClient(ranks, breaks=breaks)
    monkeypatch.setattr(board, "_client", lambda **kw: client)
    monkeypatch.setattr(board, "items_in_status", lambda status: list(column))
    return board, client


def _patched(client: _AdoClient) -> list[tuple[int, str, float]]:
    return [(int(p.rsplit("/", 1)[1]), kw["body"][0]["path"], kw["body"][0]["value"])
            for m, p, kw in client.calls if m == "PATCH"]


def test_the_top_is_half_the_first_cards_rank(monkeypatch):
    board, client = _ado(monkeypatch, column=["7", "3", "9"],
                         ranks={7: {"Microsoft.VSTS.Common.StackRank": 2000.0}})

    assert board.place_after(issue="9", issue_url="u", after=None, column="Backlog")

    assert _patched(client) == [(9, "/fields/Microsoft.VSTS.Common.StackRank", 1000.0)]
    assert client.calls[-1][2]["content_type"] == "application/json-patch+json"


def test_between_two_cards_is_the_midpoint_of_their_ranks(monkeypatch):
    """THE NEIGHBOURS ARE 1000 AND 5000, NOT 1000 AND 3000. With 3000 the midpoint is 2000 — and so
    is "the predecessor plus a fixed step", the wrong rule this guard exists to catch; the mutation
    plan showed the first version green under it. A fixture whose numbers make the wrong formula
    agree with the right one measures nothing."""
    board, client = _ado(monkeypatch, column=["7", "3", "9"],
                         ranks={7: {"Microsoft.VSTS.Common.StackRank": 1000.0},
                                3: {"Microsoft.VSTS.Common.StackRank": 5000.0}})

    assert board.place_after(issue="9", issue_url="u", after="7", column="Backlog")

    assert _patched(client) == [(9, "/fields/Microsoft.VSTS.Common.StackRank", 3000.0)]


def test_after_the_last_card_is_a_fixed_step_past_it(monkeypatch):
    board, client = _ado(monkeypatch, column=["7", "3"],
                         ranks={3: {"Microsoft.VSTS.Common.StackRank": 5000.0}})

    assert board.place_after(issue="7", issue_url="u", after="3", column="Backlog")

    assert _patched(client) == [(7, "/fields/Microsoft.VSTS.Common.StackRank", 6000.0)]


def test_a_scrum_process_is_ranked_in_the_field_it_actually_uses(monkeypatch):
    """`StackRank` is null on every Scrum card and `BacklogPriority` carries the order. Writing
    the field the process ignores would reorder nothing while reporting success."""
    board, client = _ado(monkeypatch, column=["7", "3"],
                         ranks={7: {"Microsoft.VSTS.Common.StackRank": None,
                                    "Microsoft.VSTS.Common.BacklogPriority": 400.0}})

    assert board.place_after(issue="3", issue_url="u", after=None, column="Backlog")

    assert _patched(client) == [(3, "/fields/Microsoft.VSTS.Common.BacklogPriority", 200.0)]


def test_no_neighbours_at_all_writes_a_rank_rather_than_nothing(monkeypatch):
    board, client = _ado(monkeypatch, column=["3"], ranks={})

    assert board.place_after(issue="3", issue_url="u", after=None, column="Backlog")

    assert _patched(client) == [(3, "/fields/Microsoft.VSTS.Common.StackRank", 1000.0)]


def test_an_anchor_that_is_not_in_the_column_is_refused_loudly(monkeypatch, caplog):
    board, client = _ado(monkeypatch, column=["7", "3"], ranks={})

    with caplog.at_level("ERROR"):
        assert not board.place_after(issue="7", issue_url="u", after="42", column="Backlog")

    assert _patched(client) == []
    assert "OPENFACTORY_BOARD_RANK_FAILED" in caplog.text and "42" in caplog.text


def test_a_provider_that_is_down_costs_the_placement_and_leaves_a_why(monkeypatch, caplog):
    board, _ = _ado(monkeypatch, column=["7", "3"], ranks={}, breaks=True)

    with caplog.at_level("ERROR"):
        assert not board.place_after(issue="7", issue_url="u", after=None, column="Backlog")

    assert "503" in caplog.text


# ── GitHub Projects v2: the item position mutation ─────────────────────────────────────────────

class _Run:
    def __init__(self, returncode=0, stderr=""):
        self.returncode, self.stderr, self.stdout = returncode, stderr, ""


def GitHub() -> gp.GitHubProjectBoard:
    return gp.GitHubProjectBoard(owner="acme", number="1", token="t")


def _gh(monkeypatch, *, rc: int = 0) -> tuple[gp.GitHubProjectBoard, list[list[str]]]:
    board = GitHub()
    calls: list[list[str]] = []
    monkeypatch.setattr(board, "_ensure_meta", lambda: None)
    board._project_id = "P1"
    monkeypatch.setattr(board, "_item_id", lambda n, url, repo="": f"I{n}")
    monkeypatch.setattr(board, "_existing_item_id",
                        lambda n, repo="": f"I{n}" if n in (3, 7) else None)
    monkeypatch.setattr(gp, "_run_gh", lambda args, token: calls.append(list(args)) or _Run(rc))
    return board, calls


def test_the_top_is_the_mutation_with_no_after(monkeypatch):
    board, calls = _gh(monkeypatch)

    assert board.place_after(issue="9", issue_url="u", after=None, column="Backlog")

    [args] = calls
    query = args[args.index("-f") + 1]
    assert "updateProjectV2ItemPosition" in query and "afterId:$after" in query
    assert "item=I9" in args and "project=P1" in args
    assert not any(a.startswith("after=") for a in args), "top means no afterId"


def test_after_a_card_names_that_cards_item(monkeypatch):
    board, calls = _gh(monkeypatch)

    assert board.place_after(issue="9", issue_url="u", after="3", column="Backlog")

    [args] = calls
    assert "after=I3" in args


def test_the_anchor_is_looked_up_never_added(monkeypatch, caplog):
    """`_item_id` adds before it scans — right for the card being placed, wrong for a neighbour a
    typo named: adding it would put a stranger's issue on the client's board."""
    board, calls = _gh(monkeypatch)

    with caplog.at_level("ERROR"):
        assert not board.place_after(issue="9", issue_url="u", after="42", column="Backlog")

    assert calls == []
    assert "'42'" in caplog.text


def test_a_failed_mutation_is_false_with_gh_s_own_words(monkeypatch, caplog):
    board, _ = _gh(monkeypatch, rc=1)

    with caplog.at_level("ERROR"):
        assert not board.place_after(issue="9", issue_url="u", after=None, column="Backlog")

    assert "OPENFACTORY_BOARD_RANK_FAILED" in caplog.text


# ── Jira: the Agile rank endpoint, through the tracker's one HTTP door ─────────────────────────

class _Jira:
    project_key = "DAR"

    def __init__(self, *, column=("DAR-1", "DAR-2"), breaks=False):
        self.column, self.breaks = list(column), breaks
        self.calls: list[tuple] = []

    def _call(self, method, path, payload=None, **kw):
        self.calls.append((method, path, payload, kw.get("api")))
        if self.breaks:
            raise RuntimeError("jira PUT issue/rank failed: 400")
        return {}


def _jira(monkeypatch, **kw) -> tuple[JiraProjectBoard, _Jira]:
    tracker = _Jira(**kw)
    board = JiraProjectBoard(tracker=tracker)
    monkeypatch.setattr(board, "items_in_status", lambda status: list(tracker.column))
    return board, tracker


def test_the_top_ranks_before_the_first_card_of_the_column(monkeypatch):
    board, tracker = _jira(monkeypatch)

    assert board.place_after(issue="DAR-9", issue_url="u", after=None, column="Backlog")

    assert tracker.calls == [("PUT", "issue/rank",
                              {"issues": ["DAR-9"], "rankBeforeIssue": "DAR-1"}, "agile/1.0")]


def test_after_a_card_ranks_after_it(monkeypatch):
    board, tracker = _jira(monkeypatch)

    assert board.place_after(issue="DAR-9", issue_url="u", after="DAR-2", column="Backlog")

    assert tracker.calls[0][2] == {"issues": ["DAR-9"], "rankAfterIssue": "DAR-2"}


def test_alone_in_the_column_is_already_first(monkeypatch):
    board, tracker = _jira(monkeypatch, column=("DAR-9",))

    assert board.place_after(issue="DAR-9", issue_url="u", after=None, column="Backlog")

    assert tracker.calls == []


def test_a_refused_rank_is_false_and_says_why(monkeypatch, caplog):
    board, _ = _jira(monkeypatch, breaks=True)

    with caplog.at_level("ERROR"):
        assert not board.place_after(issue="DAR-9", issue_url="u", after=None, column="Backlog")

    assert "400" in caplog.text


def test_the_tracker_reaches_the_agile_family_through_the_same_door(monkeypatch):
    """`_call` had one base, `/rest/api/3/`; the rank endpoint lives under `/rest/agile/1.0/`
    and nowhere else. The family is a parameter, the door is the same one."""
    import urllib.request

    seen: list[str] = []

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"{}"

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=45: seen.append(req.full_url) or _Resp())
    tracker = JiraTracker.__new__(JiraTracker)
    tracker.site = "https://acme.atlassian.net"
    tracker._headers = lambda: {}

    tracker._call("PUT", "issue/rank", {"issues": ["DAR-9"]}, api="agile/1.0")
    tracker._call("GET", "issue/DAR-9")

    assert seen == ["https://acme.atlassian.net/rest/agile/1.0/issue/rank",
                    "https://acme.atlassian.net/rest/api/3/issue/DAR-9"]


# ── the module: top first, chained, gated ───────────────────────────────────────────────────────

class _RankingBoard(_Plain):
    def __init__(self, *, refuse: set[str] = frozenset(), boom: set[str] = frozenset()):
        self.refuse, self.boom = set(refuse), set(boom)
        self.placed: list[tuple[str, str | None, str]] = []

    def place_after(self, *, issue, issue_url, after, column):
        if issue in self.boom:
            raise RuntimeError("board down")
        self.placed.append((issue, after, column))
        return issue not in self.refuse


def test_the_order_is_written_top_first_as_a_chain(tmp_path):
    mod, _ = _product_module(tmp_path)
    board = _RankingBoard()

    results = mod.reorder(["7", "3", "9"], actor=ADMIN, board=board)

    assert [r.ok for r in results] == [True, True, True]
    assert board.placed == [("7", None, "Backlog"), ("3", "7", "Backlog"), ("9", "3", "Backlog")]


def test_a_refused_placement_does_not_become_the_next_anchor(tmp_path):
    """The chain follows what LANDED. Anchoring the third card on a second that the board refused
    would put it after a card whose position is unknown."""
    mod, _ = _product_module(tmp_path)
    board = _RankingBoard(refuse={"3"})

    results = mod.reorder(["7", "3", "9"], actor=ADMIN, board=board)

    assert [r.ok for r in results] == [True, False, True]
    assert board.placed[-1] == ("9", "7", "Backlog")
    assert "recusou" in results[1].detail


def test_a_board_that_cannot_rank_says_so_in_one_sentence(tmp_path):
    mod, _ = _product_module(tmp_path)

    [only] = mod.reorder(["7"], actor=ADMIN, board=_Plain())

    assert not only.ok and "ainda não aceita reordenação" in only.detail


def test_only_the_allowlist_may_write_the_order(tmp_path):
    mod, _ = _product_module(tmp_path)
    board = _RankingBoard()

    [only] = mod.reorder(["7"], actor=OUTSIDER, board=board)

    assert not only.ok and board.placed == []


def test_a_board_that_raises_costs_that_card_and_not_the_rest(tmp_path):
    mod, _ = _product_module(tmp_path)
    board = _RankingBoard(boom={"3"})

    results = mod.reorder(["7", "3", "9"], actor=ADMIN, board=board)

    assert [r.ok for r in results] == [True, False, True]
    assert "não consegui reposicionar o #3" in results[1].detail


# ── the row ─────────────────────────────────────────────────────────────────────────────────────

def _actor() -> Actor:
    return Actor(id="ana", display="Ana", via="panel", admin=True, scopes=frozenset({PRODUCT}))


class _Module:
    def __init__(self):
        self.asked: list[list[str]] = []

    def reorder(self, numbers, *, actor):
        self.asked.append(list(numbers))
        return [SimpleNamespace(ok=True, ref=f"#{n}", detail="") for n in numbers]


@pytest.mark.asyncio
async def test_the_row_refuses_without_yes_and_writes_the_order_with_it(monkeypatch):
    mod = _Module()
    monkeypatch.setattr(catalog, "_product_module",
                        lambda project, by: (mod, SimpleNamespace(name=project), None))

    refused = await catalog._product_reorder(project="books", numbers="7, #3, 9", by=_actor())
    assert not refused.ok and "yes" in refused.message and mod.asked == []

    done = await catalog._product_reorder(project="books", numbers="7, #3, 9", by=_actor(),
                                          yes=True)
    assert done.ok and mod.asked == [["7", "3", "9"]]
    assert done.data["placed"] == ["#7", "#3", "#9"]


@pytest.mark.asyncio
async def test_the_row_refuses_an_empty_order(monkeypatch):
    mod = _Module()
    monkeypatch.setattr(catalog, "_product_module",
                        lambda project, by: (mod, SimpleNamespace(name=project), None))

    outcome = await catalog._product_reorder(project="books", numbers="", by=_actor(), yes=True)

    assert not outcome.ok and mod.asked == []


def test_the_row_is_declared_in_the_product_area_with_numbers_required():
    src = (ROOT / "openfactory" / "actions" / "catalog.py").read_text(encoding="utf-8")
    block = src[src.index('name="product_reorder"'):][:400]

    assert "scope=PRODUCT" in block and 'required=("project", "numbers")' in block
