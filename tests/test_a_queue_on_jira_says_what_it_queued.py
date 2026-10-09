"""On Jira, a queue confirmed says which cards it queued (#491).

THE CARDS WENT INTO THE QUEUE AND THE PERSON WAS TOLD NONE HAD. `confirm._confirm_queue` kept the
refs that landed with `contracts.refs.ref_numbers`, and `promote` answers each card as the tracker
spells it, decorated: `#DAR-1` on Jira, which carries no number. So nothing "landed", and the reply
to the one yes on this surface that spends money was "não consegui colocar na fila." — while every
card sat in the queue and the factory was about to start on it. Measured on the branch this is cut
from (ba1c3bf) with this file: both Jira cases fail and the local row's passes. Both cards moved
and the reply was that sentence; with one card refused, the one that moved was not named and the
whole reply was the other's refusal, "o quadro recusou a movimentação".

NOW THE REFS THAT LANDED ARE KEPT AS THE TRACKER SPELLS THEM (`refs.canonical_refs`, #485), and the
sentence names them as a person there reads them (`refs.ref_label`): `DAR-1` on Jira, never
`#DAR-1`, and `#1` on a numbered board, as it always read.

WHAT IS DRIVEN HERE. The yes itself, through `confirm.confirm` — the executor every transport
reaches — over a staged queue, with the product role's real pen holding each row's real tracker and
board: Jira's built by the registry against a fake at the one place the adapter touches the network
(`urllib.request.urlopen`), as `test_a_jira_key_is_a_card_ref.py` does, and the local row's on its
own SQLite board.

WHY THE SITE'S QUEUE IS A STATUS CALLED `TO-DO`. `promote` asks the board for the platform's own
name of the queue column (`ProductModule.QUEUE_COLUMN`). Measured while writing this file: on a
site whose queue status is `A Fazer` — `test_a_jira_key_is_a_card_ref.py`'s, with `status_map`
saying so — every move is refused ("o quadro recusou a movimentação") and nothing is queued. That
is a defect of its own (#496), not this one; here the cards must move for the reply to be about
what moved.
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlsplit

import pytest

from openfactory.product import staging
from openfactory.product.confirm import confirm
from tests.test_a_jira_key_is_a_card_ref import _Answer

KEY = "DAR"
BACKLOG, QUEUE, DOING, DONE = "Backlog", "TO-DO", "Em andamento", "Concluído"
TO_BACKLOG, TO_QUEUE, TO_DOING = "21", "11", "31"
ANA = "ana-requester-77"
LANG, AGENT, ROOM = "pt-BR", "Nina", "acme"


class _Site:
    """A Jira site whose cards wait in `Backlog`, each offered the move into the queue — unless its
    workflow is one that does not offer it (`refuses`).

    AND RANKED AS A JIRA SITE RANKS (#512): one order over the whole project, which a status change
    does not touch, written only through the Agile API's rank endpoint — and a search reads a
    status's cards in it (`ORDER BY Rank`). The cards start ranked in the order they are named."""

    def __init__(self, *cards: str) -> None:
        self.status = dict.fromkeys(cards, BACKLOG)
        self.rank = list(cards)
        self.refuses: set[str] = set()

    def urlopen(self, req, timeout=0):  # noqa: ARG002 — urllib's own signature
        method = req.get_method()
        if "/rest/agile/1.0/" in req.full_url:
            return self._ranked(method, req.full_url.split("/rest/agile/1.0/", 1)[1],
                                json.loads(req.data))
        path = req.full_url.split("/rest/api/3/", 1)[1]
        # THE CARD'S DOOR READS THE BOARD, THEN EACH CARD, BEFORE IT QUEUES ONE (ADR-0055, #414)
        if method == "GET" and path.startswith("search/jql?"):
            jql = parse_qs(urlsplit(path).query)["jql"][0]
            status = re.search(r'status = "([^"]+)"', jql)
            return _Answer({"isLast": True, "issues": [
                {"key": card, "fields": {"status": {"name": self.status[card]}}}
                for card in self.rank
                if status is None or self.status[card] == status.group(1)]})
        read = re.fullmatch(rf"issue/({KEY}-\d+)", path)
        if read and method == "GET":
            return _Answer({"key": read.group(1), "fields": {
                "summary": "Exportar CSV", "description": None, "reporter": None,
                "status": {"name": self.status[read.group(1)], "statusCategory": {"key": "new"}}}})
        moved = re.fullmatch(rf"issue/({KEY}-\d+)/transitions", path)
        names = {TO_BACKLOG: BACKLOG, TO_QUEUE: QUEUE, TO_DOING: DOING}
        if moved and method == "GET":
            card = moved.group(1)
            return _Answer({"transitions": [
                {"id": tid, "name": f"Mover para {to}", "to": {"name": to}}
                for tid, to in names.items() if to != self.status[card]
                and (to != QUEUE or card not in self.refuses)]})
        if moved and method == "POST":
            self.status[moved.group(1)] = names[json.loads(req.data)["transition"]["id"]]
            return _Answer(None)
        raise AssertionError(f"the adapter called {method} {path}, a route this site never had")

    def _ranked(self, method: str, path: str, payload: dict):
        """`PUT /rest/agile/1.0/issue/rank` — the card put right after, or right before, its
        neighbour in the project's one order."""
        assert (method, path) == ("PUT", "issue/rank"), f"{method} {path} on the agile API"
        (card,) = payload["issues"]
        self.rank.remove(card)
        if "rankAfterIssue" in payload:
            self.rank.insert(self.rank.index(payload["rankAfterIssue"]) + 1, card)
        else:
            self.rank.insert(self.rank.index(payload["rankBeforeIssue"]), card)
        return _Answer(None)


@pytest.fixture(autouse=True)
def _clean():
    staging._PENDING.clear()
    yield
    staging._PENDING.clear()


def _memory(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))


def _pen(project, tmp_path, *, tracker=None, board=None):
    """The product role's real pen over `project`, holding the row's tracker and board."""
    from openfactory.product.config import ProductLink
    from openfactory.product.loader import ProductContext
    from openfactory.product.module import ProductModule
    from tests.test_card_maintenance import COMMIT, REQUIREMENTS_DIR, _corpus, _Harness

    ctx = ProductContext(link=ProductLink(active=True, docs_repo="acme/acme-docs", kind="ok",
                                          reason="fine"),
                         corpus=_corpus(), docs_path=str(tmp_path), docs_commit=COMMIT,
                         requirements_dir=REQUIREMENTS_DIR)
    return ProductModule(project, context=ctx, agent=_Harness("{}"), tracker=tracker,
                         board=board)


def _yes(project, module, numbers: list[str]) -> str:
    """The queue `numbers` is staged for Ana, as the proposal stages it, and Ana says yes."""
    staging.remember(ROOM, {"kind": "queue", "channel": ROOM, "numbers": list(numbers)},
                     lang=LANG, project=project, person=ANA)
    key, waiting = staging.find_waiting(ROOM, ROOM, project=project, person=ANA)
    assert waiting is not None and waiting["kind"] == "queue", "nothing is staged"
    return confirm(project, key=key, entry=waiting, module=module, user=ANA, lang=LANG)


# ── the Jira row ─────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def jira(monkeypatch, tmp_path):
    """A Jira project as the registry holds one, two approved cards waiting in its Backlog, and the
    pen holding the row's real tracker and board."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef

    _memory(monkeypatch, tmp_path)
    site = _Site("DAR-9", "DAR-10")
    monkeypatch.setattr("urllib.request.urlopen", site.urlopen)
    options = {"site": "https://acme-team.atlassian.net", "email": "alice@acme.ai",
               "status_map": json.dumps({"todo": QUEUE, "in_progress": DOING, "done": DONE})}
    project = Project(name=ROOM, repo_path=str(tmp_path), language=LANG,
                      tracker=ProviderRef(kind="jira", repo=KEY, options=options),
                      product=ProductConfig(docs_repo="acme/acme-docs", admins=[ANA],
                                            agent_name=AGENT))
    tracker, board = build_tracker(project, token="t"), build_board(project, token="t")
    assert type(tracker).__name__ == "JiraTracker" and type(board).__name__ == "JiraProjectBoard"
    return project, site, _pen(project, tmp_path, tracker=tracker, board=board)


def test_a_queue_confirmed_on_jira_answers_with_the_cards_it_queued(jira):
    project, site, module = jira

    said = _yes(project, module, ["DAR-9", "DAR-10"])

    assert site.status == {"DAR-9": QUEUE, "DAR-10": QUEUE}
    assert said == ("Nina: Coloquei na fila, nesta ordem: DAR-9, DAR-10. "
                    "A fábrica começa pelo primeiro."), said


def test_a_queue_half_refused_on_jira_names_the_card_that_went_in(jira):
    """One card's workflow offers no way into the queue: the reply names the one that went in, as
    Jira spells it, and says the other did not — it does not answer that nothing was queued."""
    project, site, module = jira
    site.refuses = {"DAR-10"}

    said = _yes(project, module, ["DAR-9", "DAR-10"])

    assert site.status == {"DAR-9": QUEUE, "DAR-10": BACKLOG}
    # the refusal is a failed placement of a RECORDED promotion, which the hourly round applies
    # again (ADR-0055, #414) — and the card it names is spelled as Jira spells it
    assert said == ("Nina: Coloquei na fila, nesta ordem: DAR-9. A fábrica começa pelo primeiro."
                    "\n\n1 não entraram: não consegui colocar o DAR-10 na fila agora — ficou "
                    "anotado, e eu tento de novo dentro de uma hora."), said


# ── the local row: a numbered board reads as it always read ──────────────────────────────────────

@pytest.fixture
def local(monkeypatch, tmp_path):
    """A registered project on the local row, its board created, two cards in its Backlog."""
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    _memory(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    registry = ProjectRegistry()
    registry.add(Project(name=ROOM, repo_path=str(tmp_path), language=LANG,
                         tracker=ProviderRef(kind="local", repo=ROOM, options={}),
                         product=ProductConfig(docs_repo="acme/acme-docs", admins=[ANA],
                                               agent_name=AGENT)))
    project = registry.get(ROOM)
    LocalBoardSetup().create(project=project, owner="", title=ROOM, token=None)
    tracker = build_tracker(project)
    cards = [tracker.create_ticket(title=t, body="x") for t in ("Exportar CSV", "Importar OFX")]
    assert cards == ["#1", "#2"]
    return project, _pen(project, tmp_path)


def test_a_queue_confirmed_on_a_numbered_board_answers_as_before(local):
    from openfactory.adapters.board import build_board

    project, module = local

    said = _yes(project, module, ["1", "2"])

    assert build_board(project).items_in_status(QUEUE) == ["1", "2"]
    assert said == ("Nina: Coloquei na fila, nesta ordem: #1, #2. "
                    "A fábrica começa pelo primeiro."), said
