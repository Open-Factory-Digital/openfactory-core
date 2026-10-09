"""On Jira, a card the product role files is placed in Backlog, and a reported defect is followed
(#479).

THE PRODUCT ROLE READ THE CARD IT HAD JUST OPENED AS A NUMBER. `_as_ticket_number(ref)` is
`ref_number(ref) or 0`, and a Jira key carries none, so both callers skipped their second half:
`file_ticket` and `file_defect` never placed the card in the filing column (and the warning that
says so sat inside the skipped block), and `file_defect` never opened the defect's delivery loop.
The breakdown's filer, `_file_one`, refused the placement out loud instead ("reason=non-numeric —
the board port takes an integer issue id"), though the port takes the provider's ref since C-05
(`tests/test_the_board_port_takes_any_providers_ref.py`).

MEASURED ON `main` (7fa72bc) WITH THIS FILE: its four Jira cases fail and its three numbered ones
pass. A card and a defect filed on the Jira row are created as `DAR-1` and `DAR-2` and stay in
`A Fazer` — the status this project maps to the factory's TO-DO, the queue nobody promoted them to
— with no transition asked of the site and nothing logged; the ledger holds no delivery loop for
the defect; and a requirement's card is created and answered, in the project's Portuguese,
"created, but the board did not accept the placement".

WHAT IS DRIVEN HERE IS THE REAL `JiraTracker` AND THE REAL `JiraProjectBoard`, built by the
registry rows from a project's tracker options, against a fake at the one place the adapter
touches the network (`urllib.request.urlopen`) — as `test_a_withdrawn_card_lands_in_the_sites_own_
status_on_jira.py` does. The site creates an issue in `Aberto`, a status the project maps to
nothing, and its workflow offers `Backlog`.

SINCE #543 THE SITE IS NOT THE ONE MEASURED ABOVE. A workflow that creates an issue IN the queue
(`A Fazer`, here) is where the product role files nothing at all — the card would be built with
nobody queueing it (`test_every_card_writer_asks_whether_it_is_born_in_the_queue.py`) — so the
workflow here creates it one status before, which is what this file is about: where the card is
PLACED once it exists, and under which key its delivery is followed.
The ledger is the deployment's SQLite store. A GitHub-shaped ref (`#12`) is keyed exactly as
before: the board is asked for `12`, and the defect is followed as `defeito-12`.
"""

from __future__ import annotations

import json
import re

import pytest

from openfactory.memory import store as loop_store
from openfactory.memory.ledger import DELIVERY, waiting
from openfactory.product import events

KEY = "DAR"
BACKLOG, TODO, DOING, DONE = "Backlog", "A Fazer", "Em andamento", "Concluído"
#: where the workflow creates an issue — out of the queue, and mapped to nothing (#543)
OPENED = "Aberto"
TO_BACKLOG, TO_TODO, TO_DOING = "21", "11", "31"
ANA = "ana-requester-77"
ANAS = f"person:{ANA}"


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
    """A Jira site whose workflow creates an issue in `Aberto` and offers `Backlog` from it."""

    def __init__(self) -> None:
        self.status: dict[str, str] = {}
        self.requests: list[tuple[str, str, dict | None]] = []
        #: False: the workflow offers no way into Backlog, and the board answers that it could not
        self.offers_backlog = True

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
        if (method, path) == ("GET", f"project/{KEY}/statuses"):
            # WHERE A NEW ISSUE IS BORN, asked before one is filed (#543): the workflow's first
            return _Answer([{"name": "Task", "statuses": [
                {"name": n, "statusCategory": {"key": c}} for n, c in (
                    (OPENED, "new"), (BACKLOG, "new"), (TODO, "new"), (DOING, "indeterminate"),
                    (DONE, "done"))]}])
        if (method, path) == ("POST", "issue"):
            key = f"{KEY}-{len(self.status) + 1}"
            self.status[key] = OPENED
            return _Answer({"id": str(10000 + len(self.status)), "key": key})
        read = re.fullmatch(rf"issue/({KEY}-\d+)", path)
        if read and method == "GET":
            # the card just written, as its door reads it before it files it (ADR-0055, #414)
            key = read.group(1)
            return _Answer({"key": key, "fields": {
                "summary": "Exportar CSV", "description": None, "reporter": None,
                "status": {"name": self.status[key], "statusCategory": {"key": "new"}}}})
        moved = re.fullmatch(rf"issue/({KEY}-\d+)/transitions", path)
        if moved and method == "GET":
            offers = {TO_BACKLOG: BACKLOG, TO_TODO: TODO, TO_DOING: DOING}
            return _Answer({"transitions": [
                {"id": tid, "name": f"Mover para {to}", "to": {"name": to}}
                for tid, to in offers.items() if to != self.status[moved.group(1)]
                and (self.offers_backlog or to != BACKLOG)]})
        if moved and method == "POST":
            to = {TO_BACKLOG: BACKLOG, TO_TODO: TODO, TO_DOING: DOING}[body["transition"]["id"]]
            self.status[moved.group(1)] = to
            return _Answer(None)
        raise AssertionError(f"the adapter called {method} {path}, a route this site never had")


@pytest.fixture
def site(monkeypatch) -> _Site:
    jira = _Site()
    monkeypatch.setattr("urllib.request.urlopen", jira.urlopen)
    return jira


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A Jira project as the registry holds one, its memory on SQLite."""
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    # `intake_status`: the workflow below lists three statuses of the To Do category, and where a
    # new issue starts is declared, never taken from the order they are listed in (#552's review)
    options = {"site": "https://acme-team.atlassian.net", "email": "alice@acme.ai",
               "status_map": json.dumps({"todo": TODO, "in_progress": DOING, "done": DONE}),
               "intake_status": OPENED}
    return Project(name="acme", repo_path=str(tmp_path), language="pt-BR",
                   tracker=ProviderRef(kind="jira", repo=KEY, options=options),
                   product=ProductConfig(docs_repo="acme/acme-docs", admins=[ANA],
                                         agent_name="Nina"))


@pytest.fixture
def pen(project, tmp_path):
    """The product role's real pen, and the Jira row's tracker and board, built by the registry."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.product.config import ProductLink
    from openfactory.product.loader import ProductContext
    from openfactory.product.module import ProductModule
    from tests.test_card_maintenance import COMMIT, REQUIREMENTS_DIR, _corpus, _Harness

    ctx = ProductContext(link=ProductLink(active=True, docs_repo="acme/acme-docs", kind="ok",
                                          reason="fine"),
                         corpus=_corpus(), docs_path=str(tmp_path), docs_commit=COMMIT,
                         requirements_dir=REQUIREMENTS_DIR)
    module = ProductModule(project, context=ctx, agent=_Harness("{}"))
    tracker, board = build_tracker(project, token="t"), build_board(project, token="t")
    assert type(tracker).__name__ == "JiraTracker" and type(board).__name__ == "JiraProjectBoard"
    return module, tracker, board


def _deliveries(project) -> list:
    return [x for x in waiting(loop_store.read(project.name)) if x.kind == DELIVERY]


# ── the card a person asked for ─────────────────────────────────────────────────────────────────

def test_a_card_filed_on_jira_is_placed_in_the_filing_column(site, pen):
    module, tracker, board = pen

    result = module.file_ticket(title="Exportar o relatório em CSV", described="o relatório",
                                reported_by=ANA, tracker=tracker, board=board)

    assert (result.ok, result.ref, result.detail) == (True, "DAR-1", "")
    assert result.url == "https://acme-team.atlassian.net/browse/DAR-1"
    assert site.moves() == [("DAR-1", TO_BACKLOG)]
    assert site.status["DAR-1"] == BACKLOG


# ── the defect a person reported ────────────────────────────────────────────────────────────────

def test_a_defect_filed_on_jira_is_placed_and_its_delivery_is_followed(site, pen, project):
    module, tracker, board = pen

    result = module.file_defect(restated="o extrato duplica o último lançamento",
                                reported_by=ANA, violates=None, tracker=tracker, board=board,
                                conversation=ANAS, requester=ANA)

    assert (result.ok, result.ref, result.detail) == (True, "DAR-1", "")
    assert site.moves() == [("DAR-1", TO_BACKLOG)] and site.status["DAR-1"] == BACKLOG
    [loop] = _deliveries(project)
    assert (loop.subject, loop.context["issues"], loop.context["defect"]) == (
        "defeito-DAR-1", "DAR-1", "1")
    assert events.requester_conversation(project, "DAR-1") == ANAS


def test_a_board_that_refuses_the_move_on_jira_is_said_out_loud(site, pen, caplog):
    """The warning sat inside the skipped block: on `main` a Jira card was never placed and
    nothing said so. Now a refusal is said, as on every other row."""
    module, tracker, board = pen
    site.offers_backlog = False
    with caplog.at_level("WARNING"):
        ticket = module.file_ticket(title="Exportar CSV", described="x", reported_by=ANA,
                                    tracker=tracker, board=board)
        defect = module.file_defect(restated="o extrato duplica", reported_by=ANA, violates=None,
                                    tracker=tracker, board=board)

    assert ticket.ok and "posicion" in ticket.detail
    assert defect.ok and "quadro" in defect.detail
    assert "OPENFACTORY_PRODUCT_TICKET_NOT_PLACED ref=DAR-1" in caplog.text
    assert "OPENFACTORY_PRODUCT_DEFECT_NOT_PLACED ref=DAR-2" in caplog.text


# ── a requirement's card (the breakdown's filer) ────────────────────────────────────────────────

def test_a_requirements_card_filed_on_jira_is_placed(site, pen):
    from openfactory.product.role import IssueDraft
    from tests.test_card_maintenance import _corpus

    module, tracker, board = pen
    requirement = _corpus().requirements[0]

    result = module._file_one(IssueDraft(title="Gerar o pacote de fecho", objective="o pacote",
                                         acceptance_criteria=["o pacote sai completo"]),
                              requirement, tracker, board)

    assert (result.ok, result.ref, result.detail) == (True, "DAR-1", "")
    assert site.moves() == [("DAR-1", TO_BACKLOG)] and site.status["DAR-1"] == BACKLOG


# ── a GitHub-shaped ref is keyed exactly as before ──────────────────────────────────────────────

class _Numbered:
    """A tracker whose refs are `#N`, and a board recording what it was asked to move."""

    def __init__(self) -> None:
        self.placed: list[tuple[str, str]] = []

    def find_ticket(self, *, title):
        return None

    def get_ticket(self, ref):
        """The card just written, as its door reads it before it files it (ADR-0055, #414)."""
        from types import SimpleNamespace

        return SimpleNamespace(title="Exportar CSV", state="open", raw="")

    def create_ticket(self, *, title, body, **_):
        return "#12"

    def ticket_url(self, ref):
        return f"https://forge.example/acme/acme/issues/{ref.lstrip('#')}"

    def add_item(self, *, issue_url):
        return True

    def set_column(self, *, issue, issue_url, name):
        self.placed.append((issue, name))
        return True


@pytest.mark.parametrize("verb", ["ticket", "defect", "requirement"])
def test_a_numbered_ref_is_placed_and_followed_under_the_same_key_as_before(pen, project, verb):
    from openfactory.product.role import IssueDraft
    from tests.test_card_maintenance import _corpus

    module, _tracker, _board = pen
    both = _Numbered()
    if verb == "ticket":
        module.file_ticket(title="Exportar CSV", described="x", reported_by=ANA, tracker=both,
                           board=both)
    elif verb == "defect":
        module.file_defect(restated="o extrato duplica", reported_by=ANA, violates=None,
                           tracker=both, board=both, conversation=ANAS, requester=ANA)
        [loop] = _deliveries(project)
        assert (loop.subject, loop.context["issues"]) == ("defeito-12", "12")
    else:
        module._file_one(IssueDraft(title="Gerar o pacote", objective="o",
                                    acceptance_criteria=["c"]),
                         _corpus().requirements[0], both, both)

    assert both.placed == [("12", BACKLOG)]
