"""Every writer that creates a card asks whether it would be born in the queue — and the Jira row,
which had #536's defect, answers the question (#543).

SEVEN CALLS CREATE A CARD, AND #536 GUARDED THREE. `create_ticket` is called in `openfactory/` by
the product role's three filing writers, which ask `board.base.intake` before they write since
#536, and by four that did not ask: the board's own `card_create` (`actions/catalog.py`), a split's
children (`runtime/temporal/activities.py::_do_split`), the factory's impediment card
(`ops/impediment.py`) and the card `openfactory preview propose --as-card` files
(`onboarding/preview_propose.py`). On a board where a new card is born in the pickup column, each
of the four put one where the poller takes it with nobody queueing it — "nothing starts spending
on its own" (ADR-0019 §5). The census below holds the list: a new caller fails it until it asks.

WHAT EACH OF THE FOUR DOES NOW, driven against the REAL Azure rows over #536's fake Azure DevOps
(`test_a_filed_card_never_lands_in_the_pickup_column.py`, its `azure` fixture), on the board the
setup guide used to build (a new item is born in `To Do`, the queue) and on the one it builds now:

  * `card_create` opens nothing, saying why in the project's language — and opens the card a
    person names IN the queue, which is the one gesture that spends and theirs to make;
  * a split whose children wait in the backlog (`split_to_todo: false`) creates none and fails, so
    the job parks with the proposal for a person; a split that sends them straight to the queue
    is not asked — they are born where the policy sends them;
  * the impediment is not filed on the product's own board, and the line says so; on a board of
    its own (ADR-0027), which nothing polls, it is filed as before;
  * `--as-card` files nothing, and its line names the doctor.

THE JIRA ROW HAD THE DEFECT. MEASURED on cc809b8 (#536), with `test_a_jira_key_is_a_card_ref.py`'s
site as it then was — its workflow creates an issue in `A Fazer`, the status the project maps as
its queue, the shape `docs/reference/configuration.md` shows a Jira deployment declaring — and the
board's own pickup read answered: `file_ticket` answered ok with `DAR-1`, and right after the
create `items_in_status("A Fazer")` held `DAR-1`, until the door's `filed` moved it to `Backlog`; on
a workflow that offers no `Backlog`, `DAR-2` stayed in the queue for good while the role answered,
in the project's Portuguese, that it had opened the card and not yet placed it on the board.
Jira's create takes no status (`JiraTracker.intake_state`), so the row cannot create in a backlog
as Azure's does; it answers where a new issue IS born — its workflow's initial status, read off the
project's statuses (`JiraProjectBoard.intake_column`) — and the role, the four writers and the
doctor ask it as they ask Azure's. Driven here against the real `JiraTracker` and
`JiraProjectBoard`, built by the registry rows, over that same site at `urllib.request.urlopen`,
now answering the read of its workflow's statuses. The order a LIVE site lists those statuses in
is not proven here: no live site was read (see `intake_column`).
"""

from __future__ import annotations

import ast
import io
import json
import re
import urllib.error
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_a_filed_card_never_lands_in_the_pickup_column import (  # noqa: F401 — a fixture
    ANA,
    BASIC,
    GUIDE,
    UNREAD,
    VERBS,
    WITH_READY,
    _filed,
    _intake_line,
    azure,
)
from tests.test_a_jira_key_is_a_card_ref import (
    BACKLOG,
    DOING,
    DONE,
    KEY,
    TODO,
    _Answer,
    _Site,
)

ROOT = Path(__file__).resolve().parent.parent

@pytest.fixture
def ado(azure):  # noqa: F811 — #536's fixture, imported above to be requested here
    """`open(states, options, language) -> (project, tracker, board, site)`: #536's registered
    Azure DevOps project, its rows built by the registry over the fake site (`azure` there)."""
    return azure


# ── the census ──────────────────────────────────────────────────────────────────────────────────

#: Every function in `openfactory/` that calls `create_ticket`, and the function of the same file
#: that asks where the card would be born before it is written. `_file_one` is asked for by its
#: one caller, for the whole breakdown at once (#536).
WRITERS = {
    ("openfactory/product/module.py", "file_ticket"): "file_ticket",
    ("openfactory/product/module.py", "file_defect"): "file_defect",
    ("openfactory/product/module.py", "_file_one"): "file_issues",
    ("openfactory/actions/catalog.py", "_card_create"): "_card_create",
    ("openfactory/runtime/temporal/activities.py", "_do_split"): "_do_split",
    ("openfactory/ops/impediment.py", "report"): "report",
    ("openfactory/onboarding/preview_propose.py", "_as_card"): "_as_card",
}
#: Where a `create_ticket` is not a writer but the port: a row implementing it, and the in-memory
#: harness a contributor's adapter is run against.
ROWS = ("openfactory/adapters/", "openfactory/testing/")
#: The names that ask: the one decision, and the wrappers that say it on their own surface.
ASKS = frozenset({"intake_held", "_born_in_the_queue"})


def _functions(body):
    """The functions a module or class defines — methods included, nested functions not: a
    `create_ticket` inside a function's own helper belongs to the function."""
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node
        elif isinstance(node, ast.ClassDef):
            yield from _functions(node.body)


def _named(node: ast.AST) -> set[str]:
    return ({x.id for x in ast.walk(node) if isinstance(x, ast.Name)}
            | {x.attr for x in ast.walk(node) if isinstance(x, ast.Attribute)})


def _calls(fn: ast.AST, name: str) -> bool:
    return any(isinstance(x, ast.Call) and isinstance(x.func, (ast.Name, ast.Attribute))
               and (getattr(x.func, "id", "") or getattr(x.func, "attr", "")) == name
               for x in ast.walk(fn))


def _every_function() -> dict[tuple[str, str], ast.AST]:
    found: dict[tuple[str, str], ast.AST] = {}
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        for fn in _functions(ast.parse(path.read_text()).body):
            found[(rel, fn.name)] = fn
    return found


def test_every_writer_of_a_new_card_is_named_and_asks_before_it_writes():
    functions = _every_function()
    writers = {key for key, fn in functions.items()
               if not key[0].startswith(ROWS) and _calls(fn, "create_ticket")}

    assert writers == set(WRITERS), (
        f"a new writer of a card must ask `board.base.intake_held` before it creates one (#543): "
        f"{sorted(writers - set(WRITERS))}; gone: {sorted(set(WRITERS) - writers)}")
    for (rel, _writer), asker in WRITERS.items():
        assert _named(functions[(rel, asker)]) & ASKS, f"{rel}::{asker} does not ask"
    wrappers = {key: fn for key, fn in functions.items() if key[1] == "_born_in_the_queue"}
    assert len(wrappers) == 3 and all("intake_held" in _named(fn) for fn in wrappers.values())
    callers = {key for key, fn in functions.items() if _calls(fn, "_file_one")}
    assert callers == {("openfactory/product/module.py", "file_issues")}, callers


def test_a_question_that_could_not_be_answered_holds_the_card():
    """UNSURE IS NOT "SAFE TO SPEND" (`board.base.intake_held`): a tracker or a board that raised
    while asked holds the card as an unread board does — and one born out of the queue, or on no
    column, files."""
    from openfactory.adapters.board.base import Intake, intake_held

    def _raises():
        raise RuntimeError("the vendor said no")

    board = SimpleNamespace(intake_column=lambda state: "Backlog", pickup_column=lambda: "To Do")
    assert intake_held(SimpleNamespace(intake_state=_raises), board) == Intake(
        column=None, queue="", queued=False)
    assert intake_held(SimpleNamespace(), board) is None
    assert intake_held(SimpleNamespace(), SimpleNamespace(intake_column=lambda state: "",
                                                          pickup_column=lambda: "To Do")) is None
    born = intake_held(SimpleNamespace(), SimpleNamespace(intake_column=lambda state: "to do",
                                                          pickup_column=lambda: "To Do"))
    assert (born.column, born.queued) == ("to do", True)


# ── the board's own `card_create` ───────────────────────────────────────────────────────────────

OPEN_HELD = {
    "en": ("Nothing was opened: on this board a new card starts in 'To Do', the column the factory "
           "picks work up from, so it would start being built — and paid for — without anybody "
           "queueing it. To start it now, open it in 'To Do'; for it to wait, whoever runs this "
           "factory sets where new cards wait — `openfactory doctor` names the line."),
    "pt-BR": ("Nada foi aberto: neste quadro um cartão novo nasce em 'To Do', a coluna de onde a "
              "fábrica pega trabalho, então ele começaria a ser construído — e a custar — sem "
              "ninguém colocá-lo na fila. Para começar agora, abra-o em 'To Do'; para que espere, "
              "quem opera esta fábrica define onde os cartões novos esperam — o `openfactory "
              "doctor` diz a linha."),
}
OPEN_UNREAD = ("Nothing was opened: the board could not be read to see where a new card starts, "
               "and one that starts in the column the factory picks work up from is built without "
               "anybody queueing it. Try again in a moment.")


def _open_card(**params):
    """`card_create` on the registered project, driven the way every front end drives it."""
    import asyncio

    from openfactory import actions

    who = actions.Actor(id=ANA, display="Ana", via="panel", admin=True)
    return asyncio.run(actions.perform("card_create", by=who, project="acme", **params))


@pytest.mark.parametrize("language", ["en", "pt-BR"])
def test_the_board_opens_no_card_that_would_be_born_in_the_queue(ado, language):
    _project, _tracker, _board, site = ado(BASIC, {}, language=language)

    out = _open_card(title="Exportar o relatório em CSV")

    assert (out.ok, out.code, out.message) == (False, "conflict", OPEN_HELD[language]), out.message
    assert site.items == {}, "a card was opened where it is born in the queue"


def test_a_card_the_person_opens_in_the_queue_is_theirs_to_start(ado):
    """THE ONE GESTURE THAT SPENDS IS NOT ASKED: a card opened IN the queue is born where it was
    sent, by the person who sent it."""
    _project, _tracker, _board, site = ado(BASIC, {})

    out = _open_card(title="Exportar o relatório em CSV", column="To Do")

    assert out.ok, out.message
    assert [site.state_of(n) for n in site.items] == ["To Do"]


def test_an_unread_board_opens_nothing_either(ado):
    _project, _tracker, _board, site = ado(WITH_READY, GUIDE)
    site.blind = True

    out = _open_card(title="Exportar o relatório em CSV")

    assert (out.ok, out.code, out.message) == (False, "unavailable", OPEN_UNREAD), out.message
    assert site.items == {}


def test_on_the_guides_board_the_card_is_opened_in_the_backlog(ado):
    _project, _tracker, board, site = ado(WITH_READY, GUIDE)

    out = _open_card(title="Exportar o relatório em CSV")

    assert out.ok, out.message
    assert site.created_in() == ["To Do"] and board.items_in_status("Ready") == []


# ── a split's children ──────────────────────────────────────────────────────────────────────────

CHILDREN = [{"title": "harden the guest surface", "objective": "o", "criteria": ["c1"]},
            {"title": "rate limits", "objective": "o2", "criteria": ["c2"]}]


@pytest.fixture
def split(ado, monkeypatch):
    """`open(states, options, to_todo) -> (parent, site, run)`: a parent card on the registered
    Azure project, and the REAL `_do_split` of it with the deployment's split policy."""
    import openfactory.loader
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.io import SplitInput

    def _open(states, options, *, to_todo: bool):
        _project, tracker, _board, site = ado(states, options)
        monkeypatch.setattr(acts, "_tracker_for", lambda project: tracker)
        monkeypatch.setattr(openfactory.loader, "load_manifest",
                            lambda project: SimpleNamespace(split_to_todo=to_todo))
        parent = tracker.create_ticket(title="Plan 92 — Guest hardening",
                                       body="## Objective\no\n\n## Acceptance criteria\n- c")
        site.created.clear()
        return parent, site, lambda: acts._do_split(SplitInput(
            project="acme", issue=str(parent), reasons="two features in one card",
            children=CHILDREN))
    return _open


def test_a_split_that_keeps_its_children_in_the_backlog_creates_none_born_in_the_queue(split,
                                                                                      caplog):
    """THE JOB PARKS WITH THE PROPOSAL (`workflow._preflight`): a person splits it by hand, and no
    child is taken by the poller before anybody queued it."""
    parent, site, run = split(BASIC, {}, to_todo=False)

    with caplog.at_level("ERROR"), pytest.raises(RuntimeError, match="was not split"):
        run()

    assert site.created == [], "a child was created where it is born in the queue"
    assert site.state_of(parent) == "To Do", "the parent was closed for a split that never was"
    assert "OPENFACTORY_SPLIT_HELD" in caplog.text and "'To Do', the pickup column" in caplog.text


def test_and_on_an_unread_board_it_creates_none_either(split):
    _parent, site, run = split(WITH_READY, GUIDE, to_todo=False)
    site.blind = True

    with pytest.raises(RuntimeError, match="could not say"):
        run()

    assert site.created == []


def test_on_the_guides_board_the_children_are_created_in_the_backlog(split):
    parent, site, run = split(WITH_READY, GUIDE, to_todo=False)

    said = run()

    assert said.startswith("split into"), said
    assert site.created_in() == ["To Do", "To Do"] and site.state_of(parent) == "Done"


def test_children_sent_straight_to_the_queue_are_born_where_the_policy_sends_them(split):
    """NOT ASKED (ADR-0013 D3): on the board where a new card is born in the queue, the children of
    a deployment that queues them are created — and are in the queue, as they were going to be."""
    _parent, site, run = split(BASIC, {}, to_todo=True)

    said = run()

    assert said.startswith("split into"), said
    children = [n for n, _body in site.created]
    assert len(children) == 2 and {site.state_of(n) for n in children} == {"To Do"}


# ── the factory's own impediment card ───────────────────────────────────────────────────────────

@pytest.fixture
def impediments():
    from openfactory.ops import impediment

    impediment._LAST.clear()
    yield impediment
    impediment._LAST.clear()


def _declared(project, *, own: bool = False):
    """`project` with a factory board declared: the product's own tracker, or one of its own."""
    from openfactory.contracts.project import FactoryBoard, ProviderRef

    tracker = (ProviderRef(kind="azure_devops", repo="factory-ops",
                           options={"organization": "acme"}) if own else project.tracker)
    return project.model_copy(update={"factory_board": FactoryBoard(tracker=tracker)})


def test_an_impediment_on_the_products_own_board_is_not_born_in_its_queue(ado, impediments,
                                                                         caplog):
    """The factory's card would be BUILT: an agent sent into the client's repository to fix the
    factory's own trouble, with nobody queueing it."""
    project, _tracker, _board, site = ado(BASIC, {})

    with caplog.at_level("ERROR"):
        ref = impediments.report(_declared(project), impediments.PRODUCT_MOUNT_EMPTY, "entries=0")

    assert ref == "" and site.items == {}
    assert "OPENFACTORY_OPS_IMPEDIMENT_HELD project=acme" in caplog.text
    assert "'To Do', the pickup column" in caplog.text


def test_on_the_guides_board_the_impediment_is_filed_in_the_backlog(ado, impediments):
    project, _tracker, _board, site = ado(WITH_READY, GUIDE)

    ref = impediments.report(_declared(project), impediments.PRODUCT_MOUNT_EMPTY, "entries=0")

    assert ref and site.created_in() == ["To Do"]


def test_an_impediment_on_a_board_of_its_own_is_not_asked(ado, impediments):
    """ADR-0027's board, on another tracker, is no project's queue: nothing polls it, and holding
    the impediment there would leave the trouble in a log line."""
    project, _tracker, _board, site = ado(BASIC, {})

    ref = impediments.report(_declared(project, own=True), impediments.PRODUCT_MOUNT_EMPTY,
                             "entries=0")

    assert ref and len(site.items) == 1


# ── the card onboarding proposes ────────────────────────────────────────────────────────────────

def _proposal():
    return SimpleNamespace(case="inferred", questions=["how does it start?"], read=["Dockerfile"])


def test_a_preview_card_is_not_filed_where_it_would_be_born_in_the_queue(ado):
    from openfactory.onboarding.preview_propose import _as_card

    project, _tracker, _board, site = ado(BASIC, {})

    out = _as_card(project, "acme/api", _proposal())

    assert not out.ok and site.items == {}
    assert out.detail == ("the card was not filed: a new card on this board is born in 'To Do', the "
                          "column the factory picks work up from, so it would be built with nobody "
                          "queueing it. `openfactory doctor acme` names the board's line.")


def test_on_the_guides_board_the_preview_card_waits_in_the_backlog(ado):
    from openfactory.onboarding.preview_propose import _as_card

    project, _tracker, _board, site = ado(WITH_READY, GUIDE)

    out = _as_card(project, "acme/api", _proposal())

    assert out.ok, out.detail
    assert site.created_in() == ["To Do"]


# ── the Jira row ────────────────────────────────────────────────────────────────────────────────

READY = "Ready"
#: The workflow a Jira project starts from: one status of the To Do category, which the
#: deployment maps as its queue — and a `Backlog` the door's `filed` can move a card to.
IN_THE_QUEUE = ((TODO, "new"), (BACKLOG, "new"), (DOING, "indeterminate"), (DONE, "done"))
#: …and one whose first status is a backlog of its own.
BACKLOG_FIRST = ((BACKLOG, "new"), (TODO, "new"), (DOING, "indeterminate"), (DONE, "done"))
#: …and the queue of its own the doctor's line asks for, after the status Jira files in.
WITH_ITS_QUEUE = ((TODO, "new"), (READY, "new"), (DOING, "indeterminate"), (DONE, "done"))
STATUS_MAP = {"todo": TODO, "in_progress": DOING, "done": DONE}


class _Workflow(_Site):
    """`test_a_jira_key_is_a_card_ref.py`'s site, holding its WORKFLOW: the statuses each issue type
    lists, in the site's order; the one a new issue is born in; and the board's own search for a
    status, which is the poller's queue."""

    def __init__(self, statuses=IN_THE_QUEUE, *, initial: str = TODO, types=None) -> None:
        super().__init__()
        self.types = types or {"Task": statuses}
        self.initial = initial
        #: the project's statuses cannot be read
        self.blind = False

    def urlopen(self, req, timeout=0):  # noqa: ARG002 — urllib's own signature
        method, path = req.get_method(), req.full_url.split("/rest/api/3/", 1)[1]
        if (method, path) == ("GET", f"project/{KEY}/statuses"):
            if self.blind:
                raise urllib.error.HTTPError(req.full_url, 403, "forbidden", hdrs=None,
                                             fp=io.BytesIO(b"{}"))
            return _Answer([{"name": kind, "statuses": [
                {"name": n, **({"statusCategory": {"key": c}} if c else {})} for n, c in listed]}
                for kind, listed in self.types.items()])
        if method == "GET" and path.startswith("search/jql?"):
            wanted = re.search(r'status = "([^"]+)"',
                               urllib.parse.parse_qs(path.split("?", 1)[1])["jql"][0])
            return _Answer({"isLast": True, "issues": [
                {"key": k, "fields": {"status": {"name": s}}} for k, s in self.status.items()
                if not wanted or s == wanted.group(1)]})
        answer = super().urlopen(req, timeout)
        if (method, path) == ("POST", "issue"):
            self.status[f"{KEY}-{len(self.status)}"] = self.initial   # the workflow's own
        return answer


@pytest.fixture
def jira(tmp_path, monkeypatch):
    """`open(statuses, initial, language) -> (project, tracker, board, site)`: a Jira project as the
    registry holds one, its row's tracker and board built by the registry rows."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.project import Project, ProviderRef
    from tests.test_the_product_role_moves_cards_by_key import _product

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))

    def _open(statuses=IN_THE_QUEUE, *, initial: str = TODO, language: str = "pt-BR",
              status_map: dict | None = None, types=None):
        site = _Workflow(statuses, initial=initial, types=types)
        monkeypatch.setattr("urllib.request.urlopen", site.urlopen)
        options = {"site": "https://acme-team.atlassian.net", "email": "alice@acme.ai",
                   "status_map": json.dumps(status_map or STATUS_MAP, ensure_ascii=False)}
        project = Project(name="acme", repo_path=str(tmp_path), language=language,
                          product=_product(),
                          tracker=ProviderRef(kind="jira", repo=KEY, options=options))
        tracker, board = build_tracker(project, token="t"), build_board(project, token="t")
        assert (type(tracker).__name__, type(board).__name__) == ("JiraTracker",
                                                                  "JiraProjectBoard")
        return project, tracker, board, site
    return _open


@pytest.mark.parametrize("language", ["en", "pt-BR"])
@pytest.mark.parametrize("verb", VERBS)
def test_on_jira_where_the_workflow_creates_an_issue_in_the_queue_nothing_is_filed(jira, verb,
                                                                                  language):
    from openfactory.product.voice import filing_held

    project, tracker, board, site = jira(language=language)

    [held] = _filed(verb, project, tracker, board)

    assert (held.ok, held.detail) == (False, filing_held("queue", column=TODO, language=language))
    assert site.status == {}, "an issue was created in the status the poller reads"
    assert board.items_in_status(board.pickup_column()) == []


def test_on_jira_a_workflow_that_creates_an_issue_in_a_backlog_of_its_own_files_it_there(jira):
    """AND IT IS PLACED WHERE IT ALREADY IS: the workflow offers no move into the status an issue
    is in, and a placement refused for that was said to the person and retried by the hourly
    round for ever."""
    project, tracker, board, site = jira(BACKLOG_FIRST, initial=BACKLOG)

    [filed] = _filed("ticket", project, tracker, board)

    assert (filed.ok, filed.ref, filed.detail) == (True, "DAR-1", "")
    assert site.status == {"DAR-1": BACKLOG} and site.moves() == []
    assert board.items_in_status(board.pickup_column()) == []


def test_on_jira_a_backlog_declared_is_not_where_an_issue_is_born(jira):
    """A DECLARATION IS NOT A CREATE: `status_map` naming a backlog moves nothing Jira creates —
    the issue is born in the workflow's first status, the queue here — so it is refused the
    same way (`JiraTracker.intake_state`)."""
    project, tracker, board, site = jira(status_map={**STATUS_MAP, "backlog": BACKLOG})

    [held] = _filed("ticket", project, tracker, board)

    assert not held.ok and "'A Fazer'" in held.detail and site.status == {}


def test_an_unread_jira_project_files_nothing(jira):
    project, tracker, board, site = jira(language="en")
    site.blind = True

    [held] = _filed("ticket", project, tracker, board)

    assert (held.ok, held.detail) == (False, UNREAD) and site.status == {}
    assert _intake_line(project)[0] is None, "an unread board is said by board_columns, once"


def test_the_jira_row_reads_where_a_new_issue_is_born(jira):
    """The first status of the To Do category for the type the tracker creates, the first listed
    when the site names no category; a declared status by its name; and the tracker's half is
    always the workflow's own — Jira's create takes no status."""
    _p, tracker, board, site = jira(((DONE, "done"), (TODO, "new"), (BACKLOG, "new")))
    assert tracker.intake_state() == ""
    assert board.intake_column() == TODO
    assert (board.intake_column("backlog"), board.intake_column("Pronto")) == (BACKLOG, "")

    site.types = {"Task": ((BACKLOG, ""), (TODO, ""))}
    assert board.intake_column() == BACKLOG

    site.types = {"Bug": ((BACKLOG, "new"),), "Task": ((TODO, "new"), (BACKLOG, "new"))}
    assert board.intake_column() == TODO

    site.types = {"Task": ()}
    assert board.intake_column() is None, "a type that lists no status has not said"


# ── the doctor, on Jira ─────────────────────────────────────────────────────────────────────────

def test_the_doctor_fails_a_jira_board_whose_workflow_creates_an_issue_in_the_queue(jira):
    project, _tracker, _board, _site = jira()

    line, report = _intake_line(project)

    assert not line.ok and not report.ok, "a board that spends on its own passed the doctor"
    assert "created in 'A Fazer', the column the poller picks work up from" in line.message
    assert ("`status_map: '{\"todo\": \"Ready\", \"in_progress\": \"Em andamento\", \"done\": "
            "\"Concluído\", \"backlog\": \"A Fazer\"}'`") in line.remedy, line.remedy
    assert "with a transition into it from `A Fazer`" in line.remedy


def test_the_jira_line_the_doctor_hands_over_is_a_repair_the_registry_takes(jira, tmp_path):
    """PASTED UNDER THE TRACKER'S OPTIONS, read by the real loader, on the workflow the line asks
    for — a `Ready` after the status Jira files in — and a card filed then waits there, placed
    where it was born, with every other stage still mapped."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.board.base import intake
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.registry import ProjectRegistry

    project, _tracker, _board, _site = jira()
    line, _report = _intake_line(project)
    [pasted] = re.findall(r"`(status_map: [^`]+)`", line.remedy)
    registry = tmp_path / "pasted.yaml"
    registry.write_text(f"projects:\n  acme:\n    name: acme\n    repo_path: {tmp_path}\n"
                        f"    tracker:\n      kind: jira\n      repo: {KEY}\n      options:\n"
                        f"        site: https://acme-team.atlassian.net\n"
                        f"        email: alice@acme.ai\n        {pasted}\n")
    _p, _t, _b, site = jira(WITH_ITS_QUEUE)
    fixed = ProjectRegistry(registry).get("acme")
    tracker, board = build_tracker(fixed, token="t"), build_board(fixed, token="t")

    born = intake(tracker, board)

    assert (born.column, born.queue, born.queued) == (TODO, READY, False), born
    assert board.stage_column("done") == DONE and board.stage_column("in_progress") == DOING
    [filed] = _filed("ticket", fixed, tracker, board)
    assert (filed.ok, filed.detail) == (True, ""), filed.detail
    assert site.status == {"DAR-1": TODO} and site.moves() == []


def test_the_jira_line_quotes_a_status_the_way_the_registry_reads_it(jira):
    """A status named with an apostrophe — `Won't Do` — is a line YAML still reads as the map."""
    import yaml

    _p, _tracker, board, _site = jira(status_map={**STATUS_MAP, "done": "Won't Do"})

    [pasted] = re.findall(r"`(status_map: [^`]+)`", board.intake_remedy(TODO))

    assert json.loads(yaml.safe_load(pasted)["status_map"]) == {
        "todo": READY, "in_progress": DOING, "done": "Won't Do", "backlog": TODO}


def test_on_a_jira_board_with_a_backlog_first_the_doctor_says_where_a_filed_card_starts(jira):
    project, _tracker, _board, _site = jira(BACKLOG_FIRST, initial=BACKLOG)

    line, report = _intake_line(project)

    assert line.ok and report.ok
    assert line.message == ("a card the product role files starts in 'Backlog', out of 'A Fazer', "
                            "the column the poller reads")
