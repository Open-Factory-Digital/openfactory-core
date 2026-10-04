"""On a board whose columns are renamed, the product role queues and files a card by the board's own
name for the column (#496).

WHAT IT DID. `ProductModule.QUEUE_COLUMN` was `CANONICAL_COLUMNS["todo"]` and `FILING_COLUMN` was
`CANONICAL_COLUMNS["backlog"]` — the platform's own words, `TO-DO` and `Backlog` — and `promote`,
`file_ticket`, `file_defect`, `_file_one` and `reorder` handed them to the board BY NAME. Only a
board this platform created says those. Measured while fixing #491, with Jira's REST transport
faked and `status_map: {todo: "A Fazer"}`: every promotion answered *"o quadro recusou a
movimentação"*, because the site's workflow offers `A Fazer` and the Jira row matches a transition
by name. The poller had asked the row all along (`pickup_column`); the product role was the caller
that still spelled one.

WHAT IT DOES NOW. The two constants hold the platform's KEYS (`todo`, `backlog`) — the choice of key
is the money gate, and it stays closed — and each board names the key from the deployment's own map
(`board.base.stage_column`, the inverse of `stage_key`). What is driven here:

  · the REAL `JiraTracker` and `JiraProjectBoard`, built by the registry rows from a project's
    tracker options, against a fake at the one place the adapter touches the network
    (`urllib.request.urlopen`), as `test_a_jira_key_is_a_card_ref.py` does. The site's statuses are
    its own words and the platform's six appear nowhere on it;
  · the REAL `GitHubProjectBoard`, built from a registered project whose `columns:` renames both,
    against a fake `gh` (the module's `_run_gh`) that answers the board's own reads and records the
    option each move wrote;
  · the REAL `AzureBoardsBoard` with nothing renamed, whose own default says `To Do`;
  · the REAL local board, default and renamed, which must keep landing where it did;
  · the gate itself: the product role names a column only through its two keys, and only
    `promote` names the queue;
  · and the seam, which is the ONE inverse of `stage_key`: the row's map, then a real column of the
    board, then the platform's word (review of #505/#506).
"""

from __future__ import annotations

import ast
import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "openfactory" / "product" / "module.py"

KEY = "DAR"
#: The site's statuses, in its own words. `Aberto` is where the site creates an issue and nobody
#: maps it — so a card that was not placed is visibly NOT in the backlog.
OPENED, PENDING, TODO, DOING, DONE = "Aberto", "Pendências", "A Fazer", "Em andamento", "Concluído"
TO = {PENDING: "21", TODO: "11", DOING: "31"}
ANA = "ana-requester-77"


class _Answer:
    def __init__(self, payload) -> None:
        self._body = json.dumps(payload).encode() if payload is not None else b""

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class _Site:
    """A Jira site whose workflow offers its own statuses from wherever an issue is."""

    def __init__(self) -> None:
        self.status: dict[str, str] = {}
        self.requests: list[tuple[str, str, dict | None]] = []
        #: statuses the workflow does NOT offer — a refusal, said by the board
        self.refuses: set[str] = set()

    def moves(self) -> list[tuple[str, str]]:
        return [(path.split("/")[1], (body or {})["transition"]["id"])
                for method, path, body in self.requests
                if method == "POST" and path.endswith("/transitions")]

    def urlopen(self, req, timeout=0):  # noqa: ARG002 — urllib's own signature
        method = req.get_method()
        path = req.full_url.split("/rest/api/3/", 1)[1]
        body = json.loads(req.data) if req.data else None
        self.requests.append((method, path, body))
        if (method, path) == ("POST", "search/jql"):        # `find_ticket`: nothing filed before
            return _Answer({"isLast": True, "issues": []})
        if (method, path) == ("POST", "issue"):
            key = f"{KEY}-{len(self.status) + 1}"
            self.status[key] = OPENED
            return _Answer({"id": str(10000 + len(self.status)), "key": key})
        moved = re.fullmatch(rf"issue/({KEY}-\d+)/transitions", path)
        if moved and method == "GET":
            return _Answer({"transitions": [
                {"id": tid, "name": f"Mover para {to}", "to": {"name": to}}
                for to, tid in TO.items()
                if to != self.status[moved.group(1)] and to not in self.refuses]})
        if moved and method == "POST":
            self.status[moved.group(1)] = {v: k for k, v in TO.items()}[body["transition"]["id"]]
            return _Answer(None)
        raise AssertionError(f"the adapter called {method} {path}, a route this site never had")


@pytest.fixture
def site(monkeypatch) -> _Site:
    jira = _Site()
    monkeypatch.setattr("urllib.request.urlopen", jira.urlopen)
    return jira


def _ctx(tmp_path):
    from openfactory.product.config import ProductLink
    from openfactory.product.loader import ProductContext
    from tests.test_card_maintenance import COMMIT, REQUIREMENTS_DIR, _corpus

    return ProductContext(link=ProductLink(active=True, docs_repo="acme/acme-docs", kind="ok",
                                           reason="fine"),
                          corpus=_corpus(), docs_path=str(tmp_path), docs_commit=COMMIT,
                          requirements_dir=REQUIREMENTS_DIR)


def _module(project, tmp_path, tracker):
    from openfactory.product.module import ProductModule
    from tests.test_card_maintenance import _Harness

    return ProductModule(project, context=_ctx(tmp_path), agent=_Harness("{}"), tracker=tracker)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """The deployment's ledger, on SQLite in this test's own directory — a defect opens a loop."""
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))


def _product():
    from openfactory.contracts.product import ProductConfig

    return ProductConfig(docs_repo="acme/acme-docs", admins=[ANA], agent_name="Nina")


@pytest.fixture
def jira(site, tmp_path, monkeypatch):
    """The product role, the Jira row's tracker and its board — built by the registry rows from a
    project whose `status_map` renames the backlog AND the queue."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.project import Project, ProviderRef

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    options = {"site": "https://acme-team.atlassian.net", "email": "alice@acme.ai",
               "status_map": json.dumps({"backlog": PENDING, "todo": TODO,
                                         "in_progress": DOING, "done": DONE})}
    project = Project(name="acme", repo_path=str(tmp_path), language="pt-BR",
                      tracker=ProviderRef(kind="jira", repo=KEY, options=options),
                      product=_product())
    tracker, board = build_tracker(project, token="t"), build_board(project, token="t")
    assert type(board).__name__ == "JiraProjectBoard"
    return _module(project, tmp_path, tracker), tracker, board


def _filed(verb: str, module, tracker, board):
    from openfactory.product.role import IssueDraft
    from tests.test_card_maintenance import _corpus

    if verb == "ticket":
        return module.file_ticket(title="Exportar o relatório em CSV", described="o relatório",
                                  reported_by=ANA, tracker=tracker, board=board)
    if verb == "defect":
        return module.file_defect(restated="o extrato duplica o último lançamento",
                                  reported_by=ANA, violates=None, tracker=tracker, board=board)
    return module._file_one(IssueDraft(title="Gerar o pacote de fecho", objective="o pacote",
                                       acceptance_criteria=["o pacote sai completo"]),
                            _corpus().requirements[0], tracker, board)


# ── Jira: the row the defect was measured on ────────────────────────────────────────────────────

@pytest.mark.parametrize("verb", ["ticket", "defect", "requirement"])
def test_a_card_filed_on_jira_lands_in_the_status_the_deployment_calls_its_backlog(site, jira,
                                                                                  verb):
    module, tracker, board = jira

    result = _filed(verb, module, tracker, board)

    assert (result.ok, result.ref, result.detail) == (True, "DAR-1", "")
    assert site.moves() == [("DAR-1", TO[PENDING])]
    assert site.status["DAR-1"] == PENDING


def test_a_card_queued_on_jira_lands_in_the_status_the_deployment_calls_its_queue(site, jira):
    """THE MEASURED DEFECT: `promote` asked the site for `TO-DO`, which its workflow does not
    offer, and every approved card stayed where it was."""
    module, _tracker, board = jira
    site.status["DAR-7"] = PENDING

    [only] = module.promote(["DAR-7"], actor=ANA, board=board)

    assert (only.ok, only.detail) == (True, ""), only.detail
    assert site.moves() == [("DAR-7", TO[TODO])] and site.status["DAR-7"] == TODO


def test_a_refused_placement_names_the_column_as_the_board_calls_it(site, jira, caplog):
    """The person reading the log looks for that column on their own board — the platform's word,
    or the key, sends them looking for a column their board does not have."""
    module, tracker, board = jira
    site.refuses = {PENDING}

    with caplog.at_level(logging.WARNING):
        result = module.file_ticket(title="Exportar CSV", described="x", reported_by=ANA,
                                    tracker=tracker, board=board)

    assert result.ok and result.detail, "a card left unplaced was reported as placed"
    assert f"OPENFACTORY_PRODUCT_TICKET_NOT_PLACED ref=DAR-1 column={PENDING}" in caplog.text


# ── GitHub Projects: `columns:` renames both ────────────────────────────────────────────────────

class _Ran:
    def __init__(self, stdout: str = "") -> None:
        self.returncode, self.stdout, self.stderr = 0, stdout, ""


class _Gh:
    """`gh` for one Projects v2 board whose Status options are the client's own words. Answers the
    board's own reads and records which OPTION each move wrote, by name."""

    def __init__(self, options: list[str]) -> None:
        self.options = {name: f"OPT_{i}" for i, name in enumerate(options)}
        self.moved: list[tuple[str, str]] = []

    def __call__(self, args, token):  # noqa: ARG002 — `_run_gh`'s own signature
        if args[:2] == ["project", "view"]:
            return _Ran(json.dumps({"id": "PVT_1"}))
        if args[:2] == ["project", "field-list"]:
            return _Ran(json.dumps({"fields": [{"name": "Status", "id": "FLD_1", "options": [
                {"name": name, "id": oid} for name, oid in self.options.items()]}]}))
        query = next((a for a in args if a.startswith("query=")), "")
        said = dict(a.split("=", 1) for a in args if "=" in a and not a.startswith("query="))
        if "repository(owner" in query:
            return _Ran(json.dumps({"data": {"repository": {"issue": {"id": "I_kw12"}}}}))
        if "addProjectV2ItemById" in query:
            return _Ran()
        if "updateProjectV2ItemFieldValue" in query:
            named = {oid: name for name, oid in self.options.items()}
            self.moved.append((said["item"], named[said["option"]]))
            return _Ran()
        raise AssertionError(f"gh {args[:3]} — a call this board never makes")


class _Issues:
    """A tracker whose refs are `#N` — consulted for the card's URL, and for a filing."""

    def find_ticket(self, *, title):
        return None

    def create_ticket(self, *, title, body, **_):
        return "#12"

    def ticket_url(self, ref):
        return f"https://github.com/acme/app/issues/{str(ref).lstrip('#')}"


@pytest.fixture
def github(tmp_path, monkeypatch):
    from openfactory.adapters.board import build_board
    from openfactory.adapters.tracker import github_project as gp
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "ghs_x")
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    registry = ProjectRegistry()
    registry.add(Project(name="acme", repo_path=str(tmp_path), language="pt-BR",
                         tracker=ProviderRef(kind="github", repo="acme/app", options={
                             "board_owner": "acme", "board_number": "4",
                             "columns": json.dumps({"backlog": PENDING, "todo": TODO})}),
                         product=_product()))
    project = registry.get("acme")
    gh = _Gh([PENDING, TODO, "In progress", "In review", "Needs Action", "Done"])
    monkeypatch.setattr(gp, "_run_gh", gh)
    board = build_board(project)
    assert isinstance(board, gp.GitHubProjectBoard)
    # the item lookup scans the whole board; the card is on it, under its item id
    monkeypatch.setattr(board, "_item_id", lambda number, url, repo="": f"PVTI_{number}")
    tracker = _Issues()
    return _module(project, tmp_path, tracker), tracker, board, gh


def test_a_card_queued_on_a_renamed_github_board_lands_in_the_option_the_client_named(github):
    module, _tracker, board, gh = github

    [only] = module.promote(["12"], actor=ANA, board=board)

    assert (only.ok, only.detail) == (True, ""), only.detail
    assert gh.moved == [("PVTI_12", TODO)]


@pytest.mark.parametrize("verb", ["ticket", "defect", "requirement"])
def test_a_card_filed_on_a_renamed_github_board_lands_in_the_clients_backlog(github, verb):
    module, tracker, board, gh = github

    result = _filed(verb, module, tracker, board)

    assert result.ok and result.detail == "", result.detail
    assert gh.moved == [("PVTI_12", PENDING)]


# ── Azure Boards: nothing renamed, and the platform's word was still the wrong one ──────────────

class _Ado:
    def __init__(self) -> None:
        self.patched: list[tuple[int, str]] = []

    def call(self, method, path, **kw):
        number = int(path.rsplit("/", 1)[1])
        if method == "GET":
            return {"fields": {"System.WorkItemType": "Issue", "System.State": "New"}}
        self.patched.append((number, kw["body"][0]["value"]))
        return {}


def test_a_card_queued_on_an_azure_board_nobody_renamed_lands_in_its_own_to_do(tmp_path, store,
                                                                              monkeypatch):
    """`To Do` is this row's DEFAULT, and the case-folding match does not equate it with `TO-DO` —
    so a deployment that configured nothing wrong could not queue anything."""
    from openfactory.adapters.board.azure_devops import AzureBoardsBoard
    from openfactory.contracts.project import Project

    board = AzureBoardsBoard(organization="acme", project="factory", token="t")
    client = _Ado()
    monkeypatch.setattr(board, "_client", lambda **kw: client)
    monkeypatch.setattr(board, "_board_columns", lambda: [
        {"name": "New", "stateMappings": {"Issue": "New"}},
        {"name": "To Do", "stateMappings": {"Issue": "To Do"}},
        {"name": "Done", "stateMappings": {"Issue": "Done"}}])
    project = Project(name="acme", repo_path=str(tmp_path), language="pt-BR", product=_product())
    tracker = SimpleNamespace(ticket_url=lambda ref: f"https://dev.azure.com/acme/_workitems/{ref}")

    [only] = _module(project, tmp_path, tracker).promote(["412"], actor=ANA, board=board)

    assert (only.ok, only.detail) == (True, ""), only.detail
    assert client.patched == [(412, "To Do")]


# ── the local board: where it landed, it still lands — and a renamed one is followed ────────────

@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))

    def _open(columns: dict | None = None):
        from openfactory.adapters.board import build_board
        from openfactory.adapters.board_setup.local import LocalBoardSetup
        from openfactory.adapters.tracker.registry import build_tracker
        from openfactory.contracts.project import Project, ProviderRef
        from openfactory.registry import ProjectRegistry

        options = {"columns": json.dumps(columns)} if columns else {}
        registry = ProjectRegistry()
        registry.add(Project(name="acme", repo_path=str(tmp_path), language="pt-BR",
                             tracker=ProviderRef(kind="local", repo="acme", options=options),
                             product=_product()))
        project = registry.get("acme")
        LocalBoardSetup().create(project=project, owner="", title="acme", token=None)
        tracker, board = build_tracker(project), build_board(project)
        return _module(project, tmp_path, tracker), tracker, board
    return _open


@pytest.mark.parametrize("renamed, backlog, queue", [
    (None, "Backlog", "TO-DO"),
    ({"backlog": PENDING, "todo": TODO}, PENDING, TODO),
])
def test_the_local_board_files_and_queues_where_its_own_columns_say(local, renamed, backlog,
                                                                    queue):
    module, tracker, board = local(renamed)

    filed = module.file_ticket(title="Exportar CSV", described="o relatório", reported_by=ANA,
                               tracker=tracker, board=board)
    assert filed.ok and filed.detail == "", filed.detail
    ref = filed.ref.lstrip("#")
    assert board.columns()[ref] == backlog

    [only] = module.promote([ref], actor=ANA, board=board)

    assert (only.ok, only.detail) == (True, ""), only.detail
    assert board.columns()[ref] == queue


# ── the seam ────────────────────────────────────────────────────────────────────────────────────

def test_every_shipped_board_row_names_its_own_stages():
    """A row that forgot the verb degrades SILENTLY to the platform's six — which is the defect."""
    from openfactory.adapters.board.azure_devops import AzureBoardsBoard
    from openfactory.adapters.board.jira import JiraProjectBoard
    from openfactory.adapters.board.local import LocalBoard
    from openfactory.adapters.tracker.github_project import GitHubProjectBoard

    for row in (LocalBoard, JiraProjectBoard, GitHubProjectBoard, AzureBoardsBoard):
        assert callable(getattr(row, "stage_column", None)), row.__name__


def test_each_row_names_a_stage_as_its_pickup_column_names_the_queue():
    """The two questions are one for `todo`, and the rows must not come to answer them apart."""
    from openfactory.adapters.board.azure_devops import AzureBoardsBoard
    from openfactory.adapters.board.base import stage_column
    from openfactory.adapters.board.jira import JiraProjectBoard
    from openfactory.adapters.tracker.github_project import GitHubProjectBoard

    jira = JiraProjectBoard(SimpleNamespace(status_map={"todo": TODO, "backlog": PENDING}))
    github = GitHubProjectBoard("acme", "4", token="t", columns={"todo": TODO})
    azure = AzureBoardsBoard(organization="acme", project="factory", token="t")

    assert stage_column(jira, "todo") == jira.pickup_column() == TODO
    assert stage_column(jira, "backlog") == PENDING
    assert stage_column(github, "todo") == github.pickup_column() == TODO
    assert stage_column(github, "backlog") == "Backlog", "the platform's word under the map"
    assert stage_column(azure, "todo") == azure.pickup_column() == "To Do"


def test_a_board_that_says_nothing_is_asked_by_the_platforms_own_names(caplog):
    """No board, a silent row, a row that raises, and a mock's answer: the platform's word each
    time — what every one of them was asked for before — and only the last two are logged."""
    from unittest.mock import MagicMock

    from openfactory.adapters.board.base import stage_column

    class _Silent:
        pass

    class _Broken:
        def stage_column(self, key):
            raise RuntimeError("down")

    assert stage_column(None, "todo") == "TO-DO" and stage_column(_Silent(), "backlog") == "Backlog"
    assert stage_column(_Silent(), "") == "" and stage_column(_Silent(), "sprint") == ""
    with caplog.at_level(logging.WARNING):
        assert stage_column(_Broken(), "todo") == "TO-DO"
        assert stage_column(MagicMock(), "backlog") == "Backlog"
    assert caplog.text.count("OPENFACTORY_BOARD_STAGE_UNANSWERED") == 2, caplog.text


class _Columns:
    """A board with no map of its own that still knows which stage each of its columns is."""

    def __init__(self) -> None:
        self.listed = 0

    def column_names(self):
        self.listed += 1
        return [PENDING, TODO, DOING]

    def stage_key(self, column):
        return {PENDING: "backlog", TODO: "todo", DOING: "in_progress"}.get(column, "")


def test_a_board_whose_map_is_silent_is_named_by_its_own_columns():
    """THE MIDDLE LAYER (review of #505/#506): a row that declares no map — or answers `""` — still
    knows which stage each of its own columns is, and the column it reads as `todo` is the one
    asked for, before the platform's `TO-DO`, which this board does not have. The literal answers
    only a key no column of the board is."""
    from openfactory.adapters.board.base import stage_column

    class _Unmapped(_Columns):
        def stage_column(self, key):
            return ""

    for board in (_Columns(), _Unmapped()):
        assert stage_column(board, "todo") == TODO, type(board).__name__
        assert stage_column(board, "backlog") == PENDING, type(board).__name__
        assert stage_column(board, "done") == "Done", type(board).__name__


def test_a_caller_that_draws_is_named_only_a_column_the_board_has():
    """`existing=True` is `/api/board`'s: the map's name when the board HAS that column, else the
    first real column that is the stage, else nothing — never the literal. A move believes the map
    without asking (`set_column` says the rest), and `names` handed in is not asked again."""
    from openfactory.adapters.board.base import stage_column

    class _Declared(_Columns):
        def stage_column(self, key):
            return {"todo": "Fila", "backlog": PENDING}.get(key, "")

    board = _Declared()
    assert stage_column(board, "todo") == "Fila" and board.listed == 0
    assert stage_column(board, "todo", existing=True) == TODO, "a map name that is no column"
    assert stage_column(board, "backlog", existing=True) == PENDING
    assert stage_column(board, "done", existing=True) == "", "no column is `done`: none invented"
    assert stage_column(None, "done", existing=True) == ""
    asked = board.listed
    assert stage_column(board, "todo", existing=True, names=[PENDING, "Fila"]) == "Fila"
    assert board.listed == asked, "the caller's names were read again"


def test_there_is_one_inverse_of_stage_key():
    """TWO ANSWERS TO ONE QUESTION IN ONE FILE (review of #505/#506). #500 grew `column_for` beside
    this seam, walking the board's columns while this one read the row's map — free to come apart
    on the first board that disagreed with itself. They are one function, and both callers ask it:
    nothing else public in `board/base.py` takes a board and a key, and the panel's Done asks it
    for a column that exists."""
    import openfactory.adapters.board.base as base

    tree = ast.parse(Path(base.__file__).read_text(encoding="utf-8"))
    inverses = [fn.name for fn in tree.body if isinstance(fn, ast.FunctionDef)
                and not fn.name.startswith("_")
                and [a.arg for a in fn.args.args[:2]] == ["board", "key"]]
    assert inverses == ["stage_column"], inverses
    assert not hasattr(base, "column_for")

    app = ast.parse((ROOT / "openfactory" / "api" / "app.py").read_text(encoding="utf-8"))
    asked = [c for c in ast.walk(app) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
             and c.func.id in ("stage_column", "column_for")]
    assert asked, "the panel's Done no longer asks the board what it calls the stage"
    for call in asked:
        assert call.func.id == "stage_column"
        assert any(k.arg == "existing" and isinstance(k.value, ast.Constant) and k.value.value is True
                   for k in call.keywords), "the panel draws, so it asks for a column that exists"


def test_the_name_for_a_key_takes_the_deployments_map_as_its_inverse_does():
    from openfactory.adapters.board.columns import key_for, name_for

    renamed = {"todo": TODO}
    assert name_for("todo", renamed=renamed) == TODO and key_for(TODO, renamed=renamed) == "todo"
    assert name_for("backlog", renamed=renamed) == "Backlog"
    assert name_for("todo", renamed={"todo": ""}) == "TO-DO", "an empty name is not a rename"


# ── the money gate: two keys, and only `promote` names the queue ────────────────────────────────

class _Naming:
    """A board that names each stage its own way and records which key it was asked to name."""

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.placed: list[tuple[str, str]] = []
        self.ranked: list[str] = []

    def stage_column(self, key):
        self.asked.append(key)
        return f"<{key}>"

    def add_item(self, *, issue_url):
        return None

    def set_column(self, *, issue, issue_url, name):
        self.placed.append((issue, name))
        return True

    def place_after(self, *, issue, issue_url, after, column):
        self.ranked.append(column)
        return True


@pytest.mark.parametrize("verb, key", [("ticket", "backlog"), ("defect", "backlog"),
                                       ("requirement", "backlog"), ("promote", "todo"),
                                       ("reorder", "backlog")])
def test_each_caller_asks_the_board_for_one_key_and_moves_by_the_boards_answer(tmp_path, store,
                                                                              verb, key):
    from openfactory.contracts.project import Project

    project = Project(name="acme", repo_path=str(tmp_path), language="pt-BR", product=_product())
    board, tracker = _Naming(), _Issues()
    module = _module(project, tmp_path, tracker)
    if verb == "promote":
        module.promote(["12"], actor=ANA, board=board)
    elif verb == "reorder":
        module.reorder(["12"], actor=ANA, board=board)
    else:
        _filed(verb, module, tracker, board)

    assert board.asked == [key]
    moved = board.ranked if verb == "reorder" else [name for _, name in board.placed]
    assert moved == [f"<{key}>"], "the board was handed something other than its own name"


def _assigned(fn: ast.AST) -> dict[str, ast.AST]:
    return {t.id: node.value for node in ast.walk(fn) if isinstance(node, ast.Assign)
            for t in node.targets if isinstance(t, ast.Name)}


def _gate(call: ast.AST) -> str:
    """The constant a `stage_column(board, self.<X>)` call names, or `""` for anything else."""
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id == "stage_column" and len(call.args) == 2):
        return ""
    key = call.args[1]
    if (isinstance(key, ast.Attribute) and isinstance(key.value, ast.Name)
            and key.value.id == "self" and key.attr in ("FILING_KEY", "QUEUE_KEY")):
        return key.attr
    return ""


def test_the_product_role_names_a_column_only_through_its_two_keys():
    """THE MONEY GATE THE CONSTANT EXISTS FOR (ADR-0019 §5). A caller able to name the column is a
    gate one argument wide; so every move in the product role names its column through
    `stage_column(board, self.FILING_KEY | self.QUEUE_KEY)`, and the queue is named in `promote`
    alone — filing, of any kind, cannot reach the column the poller pulls from."""
    from openfactory.product.module import ProductModule

    assert (ProductModule.FILING_KEY, ProductModule.QUEUE_KEY) == ("backlog", "todo")
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    named: dict[str, set[str]] = {}
    for fn in functions:
        bound = _assigned(fn)
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr in ("set_column", "place_after")):
                continue
            word = "name" if call.func.attr == "set_column" else "column"
            [arg] = [k.value for k in call.keywords if k.arg == word]
            gate = _gate(bound.get(arg.id, arg)) if isinstance(arg, ast.Name) else _gate(arg)
            assert gate, (f"{fn.name}: `{call.func.attr}({word}=…)` names a column that is not "
                          f"the board's answer for one of the product role's two keys")
            named.setdefault(gate, set()).add(fn.name)
        for call in ast.walk(fn):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) \
                    and call.func.id == "stage_column":
                assert _gate(call), f"{fn.name}: `stage_column` asked for a key that is not a gate"

    assert named["QUEUE_KEY"] == {"promote"}, named
    assert named["FILING_KEY"] == {"file_ticket", "file_defect", "_file_one", "reorder"}, named
