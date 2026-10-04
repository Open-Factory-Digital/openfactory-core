"""On a renamed board, the queue's readers count the cards where the board keeps them, the role's
sentences name the board's own columns, and an approved card lands where the poller reads (#502).

WHAT #496 LEFT. The product role FILES and QUEUES by key since #496, and each board names the key —
so on a Jira project whose `status_map` says `Pendências` and `A Fazer`, a filed card really lands
in `Pendências`. Then the role read its own board back by the platform's names:

  1. `queue.readiness` compared each card's column with `"TO-DO"`, `"Backlog"` and `"In progress"`.
     Nothing queued and nothing filed was counted, the floor read idle beside a full queue, and
     `propose_queue` proposed from a backlog it could not see.
  2. `triage.triage` did the same with `In progress`, `Needs Action` and `Done`, and
     `board.parked_with_diagnosis` with `Needs Action`.
  3. The replies said "Fica no Backlog" and "Promover para TO-DO" about a board that has neither.
  4. `pickup_status` changed what the poller reads and not where `promote` writes, so a deployment
     that named its queue there had every approved card land in a column nobody pulls from.

WHAT IS DRIVEN HERE:

  · the REAL `JiraTracker` and `JiraProjectBoard`, built by the registry rows from a project's
    tracker options, against a fake at the one place they touch the network
    (`urllib.request.urlopen`): the board is READ through both of them — the tickets by
    `search/jql`, the columns by the board's own search — and a card the role filed or queued is
    looked for where it went;
  · the REAL `GitHubProjectBoard`, built from a registered project whose `columns:` renames the
    stages, against a fake `gh` (`_run_gh`) that records the option each move wrote;
  · the REAL local board, default and renamed, end to end through its own file;
  · and a guard over the neutral code: no column is compared by the platform's literal name.
"""

from __future__ import annotations

import ast
import json
import logging
import re
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_the_product_role_moves_cards_by_key import (
    ANA,
    _Answer,
    _Gh,
    _Issues,
    _module,
    _product,
)

ROOT = Path(__file__).resolve().parents[1]

KEY = "DAR"
#: The site's statuses, in its own words. `Aberto` is where the site creates an issue and nobody
#: maps it; `Pronto para começar` is the queue a deployment names with `pickup_status`.
OPENED, PENDING, TODO, DOING = "Aberto", "Pendências", "A Fazer", "Em andamento"
WAITING, DONE, READY = "Aguardando você", "Concluído", "Pronto para começar"
TO = {PENDING: "21", TODO: "11", DOING: "31", WAITING: "51", READY: "41"}
RENAMED = {"backlog": PENDING, "todo": TODO, "in_progress": DOING, "needs_action": WAITING,
           "done": DONE}
CRITERIA = "O relatório em CSV\n## Acceptance criteria\n- [ ] o arquivo abre numa planilha"
LONG_AGO = "2020-01-01T10:00:00.000+00:00"


class _Site:
    """A Jira site whose workflow offers its own statuses — read by search, moved by transition."""

    def __init__(self) -> None:
        self.issues: dict[str, dict] = {}
        self.requests: list[tuple[str, str, dict | None]] = []

    def put(self, key: str, status: str, *, summary: str = "", body: str = "",
            updated: str = "2026-10-01T10:00:00.000+00:00") -> None:
        self.issues[key] = {"summary": summary or f"card {key}", "status": status, "body": body,
                            "updated": updated}

    def moves(self) -> list[tuple[str, str]]:
        return [(path.split("/")[1], (body or {})["transition"]["id"])
                for method, path, body in self.requests
                if method == "POST" and path.endswith("/transitions")]

    def _row(self, key: str) -> dict:
        from openfactory.adapters.tracker.jira import JiraTracker

        issue = self.issues[key]
        category = "done" if issue["status"] == DONE else "indeterminate"
        return {"key": key, "fields": {
            "summary": issue["summary"], "description": JiraTracker._adf(issue["body"]),
            "status": {"name": issue["status"], "statusCategory": {"key": category}},
            "labels": [], "assignee": None, "updated": issue["updated"]}}

    def urlopen(self, req, timeout=0):  # noqa: ARG002 — urllib's own signature
        method = req.get_method()
        path = req.full_url.split("/rest/api/3/", 1)[1]
        body = json.loads(req.data) if req.data else None
        self.requests.append((method, path, body))
        route, _, query = path.partition("?")
        if (method, route) == ("POST", "search/jql"):      # the tickets, and `find_ticket`
            return _Answer({"isLast": True, "issues": [self._row(k) for k in self.issues]})
        if (method, route) == ("GET", "search/jql"):       # the board's columns and its queue
            jql = urllib.parse.parse_qs(query)["jql"][0]
            wanted = re.search(r'status = "([^"]+)"', jql)
            return _Answer({"isLast": True, "issues": [
                {"key": k, "fields": {"status": {"name": i["status"]}}}
                for k, i in self.issues.items() if not wanted or i["status"] == wanted.group(1)]})
        if (method, route) == ("POST", "issue"):
            key = f"{KEY}-{len(self.issues) + 1}"
            self.put(key, OPENED, summary=body["fields"]["summary"])
            return _Answer({"id": str(10000 + len(self.issues)), "key": key})
        if method == "GET" and re.fullmatch(rf"issue/{KEY}-\d+/comment", route):
            return _Answer({"comments": [], "total": 0, "startAt": 0, "maxResults": 50})
        if method == "GET" and re.fullmatch(rf"issue/{KEY}-\d+", route):   # the door's look
            return _Answer(self._row(route.split("/")[1]))
        moved = re.fullmatch(rf"issue/({KEY}-\d+)/transitions", route)
        if moved and method == "GET":
            here = self.issues[moved.group(1)]["status"]
            return _Answer({"transitions": [
                {"id": tid, "name": f"Mover para {to}", "to": {"name": to}}
                for to, tid in TO.items() if to != here]})
        if moved and method == "POST":
            self.issues[moved.group(1)]["status"] = {v: k for k, v in TO.items()}[
                body["transition"]["id"]]
            return _Answer(None)
        raise AssertionError(f"the adapter called {method} {path}, a route this site never had")


@pytest.fixture
def site(monkeypatch) -> _Site:
    from openfactory.product.board import forget_board

    forget_board()
    jira = _Site()
    monkeypatch.setattr("urllib.request.urlopen", jira.urlopen)
    yield jira
    forget_board()


@pytest.fixture
def jira(site, tmp_path, monkeypatch):
    """`(project, open)` — `open(**options)` is the product role on the Jira row's tracker and
    board, built by the registry rows from the project's tracker options."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.project import Project, ProviderRef

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))

    def _open(status_map: dict | None = None, **more):
        options = {"site": "https://acme-team.atlassian.net", "email": "alice@acme.ai",
                   "status_map": json.dumps(RENAMED if status_map is None else status_map),
                   **more}
        project = Project(name="acme", repo_path=str(tmp_path), language="pt-BR",
                          tracker=ProviderRef(kind="jira", repo=KEY, options=options),
                          product=_product())
        tracker, board = build_tracker(project, token="t"), build_board(project, token="t")
        assert type(board).__name__ == "JiraProjectBoard"
        return project, _module(project, tmp_path, tracker), tracker, board
    return _open


# ── 1. readiness reads by key, through the board's own map ──────────────────────────────────────

def test_a_renamed_jira_board_counts_its_queue_its_backlog_and_its_floor(site, jira):
    """THE MEASURED DEFECT: read through the real Jira row, every card sat in a status the
    platform's names do not say — so `todo`, `ready` and `in_progress` all came back empty."""
    site.put("DAR-1", PENDING, body=CRITERIA)
    site.put("DAR-2", PENDING)
    site.put("DAR-3", TODO)
    site.put("DAR-4", DOING)
    _project, module, _tracker, _board = jira()

    state, _proposal, error = module.propose_queue()

    assert error == ""
    assert (state.todo, state.ready, state.needs_refinement, state.in_progress) == (
        ["DAR-3"], ["DAR-1"], ["DAR-2"], 1)


def test_arriving_on_a_renamed_jira_board_says_the_floor_is_busy(site, jira):
    """`introduce` opens with where things stand — read by the platform's names, a board with a
    card queued and one in flight was announced as a quiet floor."""
    site.put("DAR-1", TODO)
    site.put("DAR-2", DOING)
    _project, module, _tracker, _board = jira()

    said = module.introduce()

    assert "**1** em andamento, **1** na fila" in said, said


def test_what_the_role_filed_and_queued_on_jira_it_finds_again(site, jira):
    """The round trip #496 opened: the role files into `Pendências` and queues into `A Fazer` by
    the board's names, and its own next read has to find them there."""
    site.put("DAR-1", PENDING, body=CRITERIA)
    _project, module, tracker, board = jira()

    [queued] = module.promote(["DAR-1"], actor=ANA, board=board)
    filed = module.file_ticket(title="Exportar o relatório em CSV", described="o relatório",
                               reported_by=ANA, tracker=tracker, board=board)
    assert queued.ok and filed.ok and filed.ref == "DAR-2", (queued.detail, filed.detail)

    state, _proposal, _error = module.propose_queue()

    assert state.todo == ["DAR-1"], "the card the role queued is invisible to its own queue"
    assert "DAR-2" in state.ready + state.needs_refinement, "the card the role filed vanished"


def test_the_tech_leads_queued_cards_are_read_by_key(site, jira, monkeypatch):
    """The other reader of `readiness`: the tech-lead's idle-floor finding asks what is queued."""
    from openfactory.runtime.temporal import activities

    site.put("DAR-1", TODO)
    site.put("DAR-2", PENDING)
    monkeypatch.setenv("JIRA_API_TOKEN", "t")
    project, _module_, _tracker, _board = jira()

    assert activities._queued_tickets(project) == ["DAR-1"]


def test_a_renamed_github_board_counts_its_queue_and_its_backlog(github):
    """The GitHub row names the stages from `columns:`; the read is the judgement's, not gh's."""
    from openfactory.product.triage import Ticket

    module, _tracker, _board, _gh = github
    module._read_board = lambda **_: ([        # noqa: SLF001 — the read is not what is under test
        Ticket(number="1", column=PENDING, body=CRITERIA), Ticket(number="2", column=TODO),
        Ticket(number="3", column="Fazendo")], "")

    state, _proposal, _error = module.propose_queue()

    assert (state.todo, state.ready, state.in_progress) == (["2"], ["1"], 1)


@pytest.mark.parametrize("renamed, backlog, queue", [
    (None, "Backlog", "TO-DO"),
    ({"backlog": PENDING, "todo": TODO}, PENDING, TODO),
])
def test_the_local_board_counts_what_the_role_filed_and_queued(local, renamed, backlog, queue):
    """Local, end to end through its own file — the default reads exactly as it did."""
    module, tracker, board = local(renamed)
    first = module.file_ticket(title="Exportar CSV", described="o relatório", reported_by=ANA,
                               tracker=tracker, board=board)
    second = module.file_ticket(title="Importar OFX", described="o extrato", reported_by=ANA,
                                tracker=tracker, board=board)
    queued = second.ref.lstrip("#")
    module.promote([queued], actor=ANA, board=board)
    assert board.columns() == {first.ref.lstrip("#"): backlog, queued: queue}

    state, _proposal, _error = module.propose_queue()

    assert state.todo == [queued]
    assert first.ref.lstrip("#") in state.ready + state.needs_refinement


def test_a_board_that_cannot_be_built_is_read_by_the_platforms_own_names(tmp_path,
                                                                        monkeypatch):
    """A reader degrades, it does not raise: a board nobody can build is asked nothing, and the
    columns are read by the platform's six — the role's read and the tech-lead's alike."""
    from openfactory.adapters import board as boards
    from openfactory.contracts.project import Project
    from openfactory.product.board import stages_for
    from openfactory.product.triage import Ticket

    def _unbuildable(*_args, **_kwargs):
        raise RuntimeError("the board's site is down")

    monkeypatch.setattr(boards, "build_board", _unbuildable)
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    project = Project(name="acme", repo_path=str(tmp_path), language="pt-BR", product=_product())
    tickets = [Ticket(number="1", column="TO-DO")]
    module = _module(project, tmp_path, _Issues())
    module._read_board = lambda **_: (tickets, "")   # noqa: SLF001 — the read is not under test

    assert stages_for(project, tickets) == {"TO-DO": "todo"}
    state, _proposal, error = module.propose_queue()
    assert error == "" and state.todo == ["1"]


def test_no_board_to_ask_is_read_by_the_platforms_own_names():
    from openfactory.product.queue import readiness
    from openfactory.product.triage import Ticket

    tickets = [Ticket(number="1", column="TO-DO"), Ticket(number="2", column=TODO)]

    assert readiness(tickets).todo == ["1"]
    assert readiness(tickets, stages={"TO-DO": "", TODO: "todo"}).todo == ["2"]


# ── 2. triage, and what is parked, read by key ──────────────────────────────────────────────────

def test_a_renamed_jira_board_is_triaged_where_its_cards_are(site, jira):
    site.put("DAR-1", DOING, body=CRITERIA, updated=LONG_AGO)
    site.put("DAR-2", WAITING, body=CRITERIA, updated=LONG_AGO)
    _project, module, _tracker, _board = jira()

    report, error = module.triage_board()

    assert error == ""
    assert {o.ticket: o.kind for o in report.observations} == {
        "DAR-1": "stalled", "DAR-2": "waiting-too-long"}


def test_a_renamed_github_board_is_triaged_where_its_cards_are(github):
    from openfactory.product.triage import Ticket

    module, _tracker, _board, _gh = github
    module._read_board = lambda **_: ([        # noqa: SLF001 — the read is not what is under test
        Ticket(number="1", column="Fazendo", body=CRITERIA, updated_days_ago=40),
        Ticket(number="2", column="Precisa de você", body=CRITERIA, updated_days_ago=40),
        Ticket(number="3", column="Entregue", body=CRITERIA),
        Ticket(number="4", column="Entregue", state="closed")], "")

    report, _error = module.triage_board()

    assert {o.ticket: o.kind for o in report.observations} == {
        "1": "stalled", "2": "waiting-too-long", "3": "done-but-open"}


def test_what_is_parked_on_a_renamed_jira_board_is_found(site, jira):
    from openfactory.product.board import parked_with_diagnosis

    site.put("DAR-1", WAITING)
    site.put("DAR-2", DOING)
    project, _module_, tracker, _board = jira()

    items, error = parked_with_diagnosis(project, token="t", tracker=tracker)

    assert error == "" and [i.number for i in items] == ["DAR-1"]


# ── 3. the sentences name the board's own columns ───────────────────────────────────────────────

def test_a_card_filed_on_jira_is_said_to_be_in_the_boards_own_backlog(site, jira):
    from openfactory.product.confirm import _confirm_ticket

    project, module, _tracker, _board = jira()

    said = _confirm_ticket(project, {"title": "Exportar CSV", "described": "o relatório",
                                     "reported_by": ANA}, module=module, user=ANA, lang="pt-BR")

    assert f"Fica na coluna {PENDING} até o time" in said and "Backlog" not in said, said
    assert site.issues["DAR-1"]["status"] == PENDING


@pytest.mark.parametrize("lang, sentence", [
    ("pt-BR", f"Está na coluna {PENDING} — começar a trabalhar nela"),
    ("en", f"It is in the {PENDING} — starting work on it"),
])
def test_a_breakdown_says_the_boards_own_backlog_in_either_door(site, jira, lang, sentence):
    """The automatic second act of an acceptance, and an admin asking for it by name."""
    from openfactory.product import engine
    from openfactory.product.authoring import WriteResult
    from openfactory.product.confirm import _also_broke_it_down

    project, module, _tracker, _board = jira()
    filed = SimpleNamespace(board_words=module.board_words,
                            break_down=lambda number, **_: [WriteResult(ok=True, ref="DAR-1")])

    accepted = _also_broke_it_down(filed, 7, ANA, "Aceito.", lang, project)
    asked = engine._run_intent(project, "breakdown", {"number": "7"}, module=filed, lang=lang,
                               user=ANA)

    for said in (accepted, asked):
        assert sentence in str(said) and "Backlog" not in str(said), said


def test_the_cards_opened_for_a_requirement_are_said_to_be_in_the_boards_backlog(site, jira):
    from openfactory.product.authoring import WriteResult
    from openfactory.product.confirm import _the_official_cards

    project, module, _tracker, _board = jira()
    opened = SimpleNamespace(board_words=module.board_words,
                             open_cards_for=lambda number, **_: [WriteResult(ok=True,
                                                                             ref="DAR-1")])

    said, cards = _the_official_cards(opened, 7, ANA, project, "pt-BR", "Escrito.")

    assert cards == ["DAR-1"] and f"na coluna {PENDING}, ainda **sem aceite**" in said, said


def test_a_handback_comment_names_the_boards_backlog_and_queue(site, jira):
    """The review's comment on a parked card, through the real Jira row's names."""
    from openfactory.product.needs_action import Verdict, review

    _project, module, _tracker, _board = jira()
    verdict = Verdict(ticket="DAR-1", cause="requirement", confidence="high", fix="o critério")

    [decision] = review([verdict], may_act=True, language="pt-BR",
                        columns=module.board_words()).decisions

    assert f"Devolvi para a coluna {PENDING}. Promover para a coluna {TODO}" in decision.comment


def test_the_role_reviews_what_is_parked_in_the_boards_own_words(site, jira):
    """`review_needs_action` hands the board's names to the comments it writes."""
    site.put("DAR-1", WAITING)
    _project, module, _tracker, _board = jira()
    module._role = lambda: SimpleNamespace(   # noqa: SLF001 — the model is not what is under test
        ask_json=lambda **_: {"cause": "requirement", "confidence": "high", "fix": "x"})
    module._workspace = lambda: (None, None)  # noqa: SLF001

    found, error = module.review_needs_action()

    assert error == "" and found.decisions, error
    assert f"Promover para a coluna {TODO}" in found.decisions[0].comment


def test_a_refusal_names_the_queue_as_the_board_calls_it(site, jira, tmp_path):
    """The door's refusal: a card waiting in `A Fazer` is said to be in `A Fazer`."""
    from openfactory.lifecycle.card import transition

    site.put("DAR-1", TODO)
    project, _module_, tracker, board = jira()

    done = transition(project, "DAR-1", "discarded", by=ANA, tracker=tracker, board=board)

    assert done.refused and f"na coluna {TODO}, esperando a fábrica" in done.refused, done.refused


def test_a_sentence_with_no_board_to_ask_says_the_platforms_words():
    from openfactory.product import voice

    assert "Fica na coluna Backlog até" in voice.ticket_filed(ref="1", language="pt-BR")
    assert "na coluna TO-DO, esperando" in voice.card_refused("discarded", state="todo", ref="1",
                                                       language="pt-BR")


# ── 4. `promote` writes where the poller reads ──────────────────────────────────────────────────

@pytest.mark.parametrize("status_map", [
    {"backlog": PENDING},
    {"backlog": PENDING, "todo": TODO},
], ids=["only-pickup_status", "both-declared"])
def test_on_jira_an_approved_card_lands_in_the_column_the_poller_reads(site, jira, status_map,
                                                                       caplog):
    """`pickup_status` named the queue for the poller only. Folded into the row's map, it is the
    queue for every reader — and the card the role queues is the one the poller's read finds."""
    site.put("DAR-7", PENDING)
    project, module, _tracker, board = jira(status_map, pickup_status=READY)
    pickup = project.tracker.options.get("pickup_status") or board.pickup_column()   # the poller

    with caplog.at_level(logging.WARNING):
        [only] = module.promote(["DAR-7"], actor=ANA, board=board)

    assert (only.ok, only.detail) == (True, ""), only.detail
    assert site.moves() == [("DAR-7", TO[READY])]
    assert board.items_in_status(pickup) == ["DAR-7"], "the poller never sees the approved card"
    assert board.pickup_column() == READY
    if "todo" in status_map:
        assert "OPENFACTORY_BOARD_QUEUE_NAMED_TWICE" in caplog.text
        assert READY in caplog.text and TODO in caplog.text, "the warning names both"


def test_a_card_in_the_named_queue_is_read_as_queued(site, jira):
    """…and the readers agree: what sits in the column the deployment named is `todo`."""
    site.put("DAR-1", READY)
    _project, module, _tracker, _board = jira({"backlog": PENDING}, pickup_status=READY)

    state, _proposal, _error = module.propose_queue()

    assert state.todo == ["DAR-1"]


def test_the_pollers_own_answer_is_the_named_queue(site, jira):
    from openfactory.runtime.temporal import activities

    project, _module_, _tracker, _board = jira({"backlog": PENDING}, pickup_status=READY)

    assert activities._pickup_column(project) == READY


def test_on_a_renamed_github_board_an_approved_card_lands_in_the_named_queue(tmp_path,
                                                                            monkeypatch):
    board, module, gh = _github_board(tmp_path, monkeypatch, columns={"todo": TODO},
                                      pickup_status=READY)

    [only] = module.promote(["12"], actor=ANA, board=board)

    assert (only.ok, only.detail) == (True, ""), only.detail
    assert gh.moved == [("PVTI_12", READY)]
    assert board.pickup_column() == READY


def test_the_local_board_queues_into_the_column_its_deployment_named(local):
    """`project init` writes the named queue as the board's own `todo` row, and the role and the
    poller both use it."""
    module, tracker, board = local(None, pickup_status=READY)
    filed = module.file_ticket(title="Exportar CSV", described="o relatório", reported_by=ANA,
                               tracker=tracker, board=board)
    ref = filed.ref.lstrip("#")

    [only] = module.promote([ref], actor=ANA, board=board)

    assert (only.ok, only.detail) == (True, ""), only.detail
    assert board.columns()[ref] == READY and board.items_in_status(READY) == [ref]


def test_a_local_queue_named_after_the_board_was_made_is_refused_rather_than_lost(local):
    """Named after `project init`, the queue is not on the board: the promotion is REFUSED, said
    to the person, rather than landing in `TO-DO` where nobody pulls."""
    local(None)                                    # `project init`, before the queue was named
    module, tracker, board = local(None, pickup_status=READY, init=False)
    filed = module.file_ticket(title="Exportar CSV", described="o relatório", reported_by=ANA,
                               tracker=tracker, board=board)

    [only] = module.promote([filed.ref.lstrip("#")], actor=ANA, board=board)

    assert not only.ok and only.detail, "a promotion landed in a column the poller never reads"
    assert board.pickup_column() == READY, "the poller and the role read two different queues"


# ── the guard: no column is compared by the platform's literal name ─────────────────────────────

#: Neutral code — where a column's NAME is the board's business and only its KEY is the platform's.
# `openfactory/techlead` since the review of #507: its catalogue speaks to the people who
# queued the work, and its split rows named the platform's columns beside a note that did not
NEUTRAL = ("openfactory/product", "openfactory/runtime", "openfactory/lifecycle",
           "openfactory/techlead")

#: `(file, literal)` → why it may stay. Short on purpose: each one is a place a person decided.
ALLOWED = {
    ("openfactory/runtime/temporal/io.py", "TO-DO"):
        "`ScanInput.pickup_status`'s default — a Temporal payload's field, always set by its one "
        "producer (`scan_projects`) from the board's own answer; the module is imported inside the "
        "workflow sandbox, which a table import here has no business widening",
}


def _docstrings(tree: ast.AST) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def test_no_neutral_code_names_a_column_by_the_platforms_literal():
    """THE CLASS #502 IS ONE OF. A literal `"TO-DO"` in neutral code is a column compared, moved or
    defaulted by a name only a board this platform created carries — every one of them read
    somebody's renamed board wrong. The KEY is the platform's; the name is asked of the board
    (`stage_key`, `stage_column`, `pickup_column`). Docstrings and comments may say the words —
    read by the AST, they are not code — and a sentence that mentions one inside more text is
    the sentences' own test above."""
    from openfactory.adapters.board.columns import CANONICAL_COLUMNS

    names = set(CANONICAL_COLUMNS.values())
    found = set()
    for folder in NEUTRAL:
        for path in sorted((ROOT / folder).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            prose = _docstrings(tree)
            rel = path.relative_to(ROOT).as_posix()
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and id(node) not in prose and node.value.strip() in names):
                    found.add((rel, node.value.strip()))

    assert found - set(ALLOWED) == set(), (
        "neutral code names a column by the platform's word — ask the board for the key's name "
        f"(`stage_column`) or read the column by key (`stage_key`): {sorted(found - set(ALLOWED))}")
    assert set(ALLOWED) <= found, (
        f"an allowance no longer used — take it out: {sorted(set(ALLOWED) - found)}")


# ── the boards ──────────────────────────────────────────────────────────────────────────────────

def _github_board(tmp_path, monkeypatch, *, columns: dict, pickup_status: str = ""):
    from openfactory.adapters.board import build_board
    from openfactory.adapters.tracker import github_project as gp
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "ghs_x")
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    options = {"board_owner": "acme", "board_number": "4", "columns": json.dumps(columns)}
    if pickup_status:
        options["pickup_status"] = pickup_status
    registry = ProjectRegistry()
    registry.add(Project(name="acme", repo_path=str(tmp_path), language="pt-BR",
                         tracker=ProviderRef(kind="github", repo="acme/app", options=options),
                         product=_product()))
    project = registry.get("acme")
    gh = _Gh([*columns.values(), READY, "Backlog", "TO-DO", "In progress", "Done"])
    monkeypatch.setattr(gp, "_run_gh", gh)
    board = build_board(project)
    assert isinstance(board, gp.GitHubProjectBoard)
    monkeypatch.setattr(board, "_item_id", lambda number, url, repo="": f"PVTI_{number}")
    return board, _module(project, tmp_path, _Issues()), gh


@pytest.fixture
def github(tmp_path, monkeypatch):
    """The product role on a GitHub board whose `columns:` renames every stage it reads."""
    board, module, gh = _github_board(tmp_path, monkeypatch, columns={
        "backlog": PENDING, "todo": TODO, "in_progress": "Fazendo",
        "needs_action": "Precisa de você", "done": "Entregue"})
    return module, _Issues(), board, gh


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    from openfactory.product.board import forget_board

    forget_board()

    def _open(columns: dict | None = None, *, pickup_status: str = "", init: bool = True):
        from openfactory.adapters.board import build_board
        from openfactory.adapters.board_setup.local import LocalBoardSetup
        from openfactory.adapters.tracker.registry import build_tracker
        from openfactory.contracts.project import Project, ProviderRef
        from openfactory.registry import ProjectRegistry

        options = {"columns": json.dumps(columns)} if columns else {}
        if pickup_status:
            options["pickup_status"] = pickup_status
        registry = ProjectRegistry()
        project = Project(name="acme", repo_path=str(tmp_path), language="pt-BR",
                          tracker=ProviderRef(kind="local", repo="acme", options=options),
                          product=_product())
        if init:
            registry.add(project)
            project = registry.get("acme")
            LocalBoardSetup().create(project=project, owner="", title="acme", token=None)
        tracker, board = build_tracker(project), build_board(project)
        return _module(project, tmp_path, tracker), tracker, board
    yield _open
    forget_board()
