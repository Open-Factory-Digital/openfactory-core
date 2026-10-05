"""A backlog order confirmed in the conversation reaches the board through the watched writes
(#511).

EVERY CONFIRMED REORDER WAS REFUSED, ON THE BOARDS THAT RANK. `ProductModule.reorder` asks
`isinstance(board, Rankable)` before it writes an order, and the board it asks is its own,
`self._board()` — the adapter wrapped in `_WatchedWrites`, which forwards through `__getattr__` and
reports a machine failure of any write to the factory's board. Since Python 3.12 `isinstance`
against a `runtime_checkable` protocol looks the members up STATICALLY (`inspect.getattr_static`),
and a forwarded member is not there to be found. Measured on `main` (755e489): the bare GitHub,
Jira and Azure boards are `Rankable`, the same boards watched are not, though `hasattr` says
`place_after` is there. So "coloca nessa ordem: 7, 3, 9", confirmed with a yes, was answered "este
quadro ainda não aceita reordenação" on every board this platform ships that ranks.

The existing guards never saw it because every one of them handed `reorder` a bare stand-in
(`board=_RankingBoard()`), which is exactly what production never does.

WHAT IS DRIVEN HERE IS THE CONFIRMATION, `confirm.confirm`, with a real `ProductModule` building its
OWN board through the registry, so the order goes through the wrapper or nowhere:

  · on the GitHub Projects row, with `gh` faked at the adapter's one door (`_run_gh`), the order is
    written as a chain of position mutations and the reply reads it back;
  · a rank the board refused, and one whose call raised, is still REPORTED by the wrapper — which
    is why the fix keeps the wrapper rather than unwrapping it at the check;
  · on a board that does not rank — a client's own, since the local row ranks too (#512) — the
    person is still told so in one sentence, and on the local row the order is written;
  · and a guard: for every `runtime_checkable` protocol the product module checks, and the board
    and tracker capabilities beside them, an adapter that satisfies it satisfies it wrapped, and
    one that does not, does not.

The order marker reads digits only (`role._ORDER_RE`), so a Jira key cannot reach this verb from
the conversation at all; the hosted row driven here is therefore the one whose refs a person can
actually say in chat.
"""

from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

import pytest

from openfactory.adapters.board.base import BoardAdapter, Rankable, Staged, Watchable
from openfactory.adapters.tracker import github_project as gp
from openfactory.adapters.tracker.base import TrackerAdapter
from openfactory.product import confirm as confirm_module
from openfactory.product import module as product_module
from openfactory.product import staging
from openfactory.product.module import _IMP_WRITE, ProductModule, _WatchedWrites
from openfactory.product.voice import reordered

ROOT = Path(__file__).resolve().parents[1]
ADMIN = "U1"
KEY = f"person:{ADMIN}"
LANG = "pt-BR"


def _project(tracker):
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project

    return Project(name="acme", repo_path="/t", language=LANG, tracker=tracker,
                   product=ProductConfig(docs_repo="acme/acme-docs", admins=[ADMIN],
                                         agent_name="Nina"))


@pytest.fixture
def told(monkeypatch) -> list[tuple[str, bool]]:
    """What the wrapper reported to the factory's board about the product role's writes."""
    seen: list[tuple[str, bool]] = []
    monkeypatch.setattr(product_module, "_tell_the_factory",
                        lambda project, cause, detail, *, ok: seen.append((detail, ok))
                        if cause == _IMP_WRITE else None)
    return seen


def _confirmed(project, module, numbers: list[str]) -> str:
    """A person staged an order and says yes — the confirmation, as the conversation runs it."""
    staging.forget(KEY)
    staging.remember(KEY, {"kind": "reorder", "numbers": numbers}, project=project, person=ADMIN)
    return confirm_module.confirm(project, key=KEY, entry=staging.pending_for(KEY), module=module,
                                  user=ADMIN, lang=LANG)


# ── a board that ranks: GitHub Projects, with `gh` faked at its one door ───────────────────────

class _Gh:
    """`gh` for one Projects v2 board — project P1 with a Status field, the cards 7, 3 and 9 of
    acme/web on it — recording every position mutation it is asked for."""

    def __init__(self, *, refuses: frozenset[str] = frozenset(), down: bool = False) -> None:
        self.refuses, self.down = refuses, down
        self.positions: list[tuple[str, str | None]] = []

    def __call__(self, args: list[str], token):  # noqa: ARG002 — `_run_gh`'s own signature
        query = next((a[len("query="):] for a in args if a.startswith("query=")), "")
        fields = dict(a.split("=", 1) for a in args if "=" in a and not a.startswith("query="))
        if args[:2] == ["project", "view"]:
            return self._answer({"id": "P1"}, fails=self.down)
        if args[:2] == ["project", "field-list"]:
            return self._answer({"fields": [{"name": "Status", "id": "F1",
                                             "options": [{"name": "Backlog", "id": "o1"}]}]})
        if "updateProjectV2ItemPosition" in query:
            self.positions.append((fields["item"], fields.get("after")))
            return self._answer({}, fails=fields["item"] in self.refuses)
        if "addProjectV2ItemById" in query:
            return self._answer({})
        if "issue(number:$number)" in query:
            return self._answer({"data": {"repository": {"issue": {"id": f"N{fields['number']}"}}}})
        if "organization(login:$owner)" in query:
            nodes = [{"id": f"I{n}", "content": {"number": n,
                                                 "repository": {"nameWithOwner": "acme/web"}},
                      "fieldValueByName": {"name": "Backlog"}} for n in (7, 3, 9)]
            return self._answer({"data": {"organization": {"projectV2": {"items": {
                "pageInfo": {"hasNextPage": False}, "nodes": nodes}}}}})
        raise AssertionError(f"the board asked gh for something this fake never had: {args}")

    @staticmethod
    def _answer(payload, *, fails: bool = False):
        from types import SimpleNamespace

        return SimpleNamespace(returncode=1 if fails else 0, stdout=json.dumps(payload),
                               stderr="HTTP 503: Service Unavailable" if fails else "")


@pytest.fixture
def github(monkeypatch):
    from openfactory.contracts.project import ProviderRef

    for name in ("GH_HOST", "GITHUB_HOST"):
        monkeypatch.delenv(name, raising=False)
    project = _project(ProviderRef(kind="github", repo="acme/web",
                                   options={"board_owner": "acme", "board_number": "1"}))

    def board(**kw) -> tuple[ProductModule, _Gh]:
        gh = _Gh(**kw)
        monkeypatch.setattr(gp, "_run_gh", gh)
        return ProductModule(project, token="t"), gh

    return project, board


def test_a_confirmed_order_is_written_through_the_modules_own_watched_board(github, told):
    project, board = github
    module, gh = board()
    assert isinstance(module._board(), _WatchedWrites), "the board under test is not the watched"

    said = _confirmed(project, module, ["7", "3", "9"])

    assert gh.positions == [("I7", None), ("I3", "I7"), ("I9", "I3")], gh.positions
    assert said == reordered(["7", "3", "9"], language=LANG, agent_name="Nina"), said
    assert told == [("place_after", True)] * 3, "the rank went around the watch"


def test_a_rank_the_board_refused_is_reported_by_the_wrapper_and_the_rest_stand(github, told):
    project, board = github
    module, gh = board(refuses=frozenset({"I3"}))

    said = _confirmed(project, module, ["7", "3", "9"])

    assert gh.positions == [("I7", None), ("I3", "I7"), ("I9", "I7")], gh.positions
    assert "#7, #9" in said and "1 não entraram na ordem" in said, said
    assert told == [("place_after", True), ("place_after recusou a escrita", False),
                    ("place_after", True)], told


def test_a_rank_whose_call_raised_is_reported_by_the_wrapper(github, told):
    project, board = github
    module, gh = board(down=True)

    said = _confirmed(project, module, ["7", "3"])

    assert gh.positions == []
    assert "não consegui reposicionar o #7" in said and "Ordem gravada" not in said, said
    assert [ok for _, ok in told] == [False, False], told
    assert all(detail.startswith("place_after: ") and "503" in detail for detail, _ in told), told


# ── a board that does not rank, and the local row, which does since #512 ───────────────────────

class _ItsOwnBoard:
    """A client's own board: it reads and moves cards, and keeps no order this platform can write
    — it has no `place_after`, and so does not claim `Rankable`."""

    def url(self) -> str:
        return ""

    def columns(self) -> dict[str, str]:
        return {}

    def column_names(self) -> list[str]:
        return ["Backlog", "TO-DO"]

    def items_in_status(self, status: str) -> list[str]:
        return []

    def add_item(self, *, issue_url: str) -> None:
        return None

    def set_column(self, *, issue: str, issue_url: str, name: str) -> bool:
        return True

    def set_status(self, *, issue: str, issue_url: str, state, needs_person=None) -> bool:
        return True


@pytest.fixture
def local(tmp_path, monkeypatch):
    """A project on the local row, its board created and three cards filed in its Backlog."""
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.project import ProviderRef

    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    project = _project(ProviderRef(kind="local", repo="acme", options={}))
    LocalBoardSetup().create(project=project, owner="", title="acme", token=None)
    tracker = build_tracker(project)
    assert [tracker.create_ticket(title=t, body="x") for t in ("um", "dois", "três")] == [
        "#1", "#2", "#3"]
    return project


def test_a_board_that_does_not_rank_still_says_so_in_one_sentence(local, told):
    """A board that keeps no rank says so by not claiming `Rankable`. Wrapped, it must not start
    claiming it: a wrapper that answered yes for every board would turn this sentence into an
    `AttributeError` caught one level down — "não consegui reposicionar" about a board that was
    never able to. The local row was this board until #512; a client's own adapter is now."""
    module = ProductModule(local, token="t", board=_ItsOwnBoard())
    assert type(module._board()._inner) is _ItsOwnBoard

    said = _confirmed(local, module, ["1", "2"])

    assert said.startswith("este quadro ainda não aceita reordenação por aqui"), said
    assert "não consegui" not in said and told == [], (said, told)


def test_the_local_board_writes_the_order_confirmed(local, told):
    """The local row ranks by a position in the column (#512): the order confirmed is written
    through the module's own watched board, and the backlog is read in it."""
    from openfactory.adapters.board import build_board

    module = ProductModule(local, token="t")
    assert type(module._board()._inner).__name__ == "LocalBoard"

    said = _confirmed(local, module, ["3", "1"])

    assert build_board(local).items_in_status("Backlog") == ["3", "1", "2"]
    assert said == reordered(["3", "1"], language=LANG, agent_name="Nina"), said
    assert told == [("place_after", True)] * 2, "the rank went around the watch"


# ── the guard: what the module asks of a watched adapter is what the adapter answers ───────────

def _protocols_the_module_checks() -> set[type]:
    """Every `runtime_checkable` protocol `module.py` hands to `isinstance`, resolved through the
    module's own imports — so the next capability the module asks about is in this guard without
    anybody adding it here."""
    tree = ast.parse((ROOT / "openfactory" / "product" / "module.py").read_text(encoding="utf-8"))
    where = {alias.asname or alias.name: node.module
             for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
             for alias in node.names}
    found: set[type] = set()
    for call in ast.walk(tree):
        if (isinstance(call, ast.Call) and getattr(call.func, "id", "") == "isinstance"
                and len(call.args) == 2 and isinstance(call.args[1], ast.Name)
                and call.args[1].id in where):
            kind = getattr(importlib.import_module(where[call.args[1].id]), call.args[1].id, None)
            if getattr(kind, "_is_runtime_protocol", False):
                found.add(kind)
    return found


def test_the_guard_finds_the_question_the_defect_was_in():
    assert Rankable in _protocols_the_module_checks()


#: The board and tracker capabilities — the two axes `_WatchedWrites` wraps — beside whatever the
#: module itself asks today.
GUARDED = sorted(_protocols_the_module_checks() | {BoardAdapter, Rankable, Watchable, Staged,
                                                   TrackerAdapter}, key=lambda p: p.__name__)


def _members(protocol) -> list[str]:
    return sorted(protocol.__protocol_attrs__)


def _row(members: dict, *, on_the_instance: bool = False):
    if on_the_instance:
        row = type("Row", (), {})()
        vars(row).update(members)
        return row
    return type("Row", (), members)()


def _works(*_a, **_k):
    return True


@pytest.mark.parametrize("protocol", GUARDED, ids=lambda p: p.__name__)
@pytest.mark.parametrize("on_the_instance", [False, True], ids=["on-the-class", "on-the-instance"])
def test_a_watched_adapter_answers_every_capability_as_its_adapter_does(protocol,
                                                                        on_the_instance):
    names = _members(protocol)
    whole = _row({n: _works for n in names}, on_the_instance=on_the_instance)
    assert isinstance(whole, protocol), "the fixture does not satisfy the protocol it stands for"
    assert isinstance(_WatchedWrites(whole, lambda *_: None), protocol), (
        f"an adapter that is {protocol.__name__} is not, once watched")

    for gone in names:
        rest = {n: _works for n in names if n != gone}
        lacking = _row(rest, on_the_instance=on_the_instance)
        opted_out = _row({**rest, gone: None}, on_the_instance=on_the_instance)
        for how, row in (("without", lacking), ("that set None for", opted_out)):
            watched = _WatchedWrites(row, lambda *_: None)
            assert isinstance(watched, protocol) == isinstance(row, protocol), (
                f"watched, an adapter {how} {gone!r} answers {protocol.__name__} differently")


def _shipped():
    from openfactory.adapters.board.azure_devops import AzureBoardsBoard
    from openfactory.adapters.board.jira import JiraProjectBoard
    from openfactory.adapters.board.local import LocalBoard
    from openfactory.adapters.tracker.github import GitHubIssuesTracker

    class _Tracker:
        project_key = "DAR"

    return [JiraProjectBoard(tracker=_Tracker()), LocalBoard(_Tracker()),
            gp.GitHubProjectBoard("acme", "1", token="t"),
            AzureBoardsBoard(organization="o", project="p", token="t"),
            GitHubIssuesTracker("acme/web")]


@pytest.mark.parametrize("row", _shipped(), ids=lambda r: type(r).__name__)
def test_every_shipped_row_keeps_its_capabilities_when_watched(row):
    watched = _WatchedWrites(row, lambda *_: None)
    assert {p.__name__: isinstance(watched, p) for p in GUARDED} == {
        p.__name__: isinstance(row, p) for p in GUARDED}
