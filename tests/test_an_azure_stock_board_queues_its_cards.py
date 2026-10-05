"""On an Azure DevOps board with a stock process, a card in `New` is queued once the deployment maps
the column — and until it does, every sentence that refuses the card names the line that maps it
(#521).

WHAT WAS FOUND. A board can run Azure's stock process rather than the platform's own `OpenFactory
Basic`, and Azure files every new work item in that process's first column — `New` on Scrum and
Agile. No stage is `New` by default (`AzureBoardsBoard.stage_key("New")` is `""`), and the card's
door reads a card's state from its column, so the first queueing of the first card was refused
with *"not a column this platform maps … Map it in the project's tracker options"*: in English to
every conversation, naming neither the option nor the stage. Before the door, `promote` moved it.
And because the board has no backlog either, the product role's filing placed its card nowhere.

THE CHOICE, AND WHY THE TABLE STAYS AS IT IS. Reading an unmapped column as the backlog would have
let the queueing through — and every other event the backlog allows with it, an edit, a
withdrawal, a removal, for a card in ANY column nobody maps, including one a person dragged out
from under its job. A column that is no stage has no state to allow anything. So the refusal
stands, and what changed is what it says — the option THIS board reads and the one line that
makes the column the backlog, in the project's language — and `openfactory doctor` says the same
before the first card. The line it names is the whole repair: with `columns: '{"backlog": "New"}'`
the stock card is queued, and a filed card lands in `New`. QUOTED, a string of JSON — the registry's
options are strings, and the line the sentences first printed unquoted was a mapping the registry
refuses (review of #521) — so the line the sentence prints is pasted into a registry file, read by
the real loader, and the column it names is asked of the board it builds.

Driven here, against the REAL `AzureBoardsBoard` built by the registry row from a project's
tracker options, over a fake Azure DevOps at the one seam the board talks through (`_client`),
which keeps the work items' states and answers the routes this board really calls:

  * the product role's `promote` — refused, by the line that maps the column, in both languages;
    queued into the deployment's own queue column once the line is there;
  * the panel's `card_move` — the same sentence, since its gate refuses before the door does;
  * the product role's filing — placed nowhere on a board with no backlog, placed in `New` once
    it is the backlog;
  * the card's door itself — a card in an unmapped column has no state, whatever the event;
  * the doctor — the real probe over the same board, and the line the command prints.
"""

from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace

import pytest

#: Azure's stock Scrum process, as its board reports it: the incoming column first, each column a
#: state of the one work item type the board carries.
KIND = "Product Backlog Item"
STOCK = ("New", "Approved", "Committed", "Done")
#: What a deployment on that process maps today — the queue and the work, as the doctor's
#: `board_columns` remedy asks — and nothing for where Azure files a new card.
MAPPED = {"todo": "Approved", "in_progress": "Committed"}
#: …and the one line the refusal names.
REPAIRED = {**MAPPED, "backlog": "New"}
ANA = "ana-requester-77"


class _Azure:
    """Azure DevOps for one team's board on the stock Scrum process — every route this board calls,
    the work items' states kept here. A column IS a state, so a PATCH of the state is the move."""

    def __init__(self, **cards: str) -> None:
        self.state = {number.lstrip("n"): state for number, state in cards.items()}
        self.patched: list[tuple[int, str]] = []
        #: the board's columns cannot be read — a wrong team answers exactly like this
        self.blind = False

    def values(self, path: str, **_kw) -> list:
        if path == "work/boards":
            return [{"name": "Backlog items"}]
        if re.fullmatch(r"work/boards/[^/]+/columns", path):
            if self.blind:
                raise RuntimeError("404 TF401501: The board does not exist")
            return [{"name": name, "stateMappings": {KIND: name},
                     "columnType": {"New": "incoming", "Done": "outgoing"}.get(name, "inProgress")}
                    for name in STOCK]
        raise AssertionError(f"the board listed {path}, a route Azure DevOps never had")

    def call(self, method: str, path: str, *, body=None, **_kw) -> dict:
        if method == "GET" and path.startswith("projects/"):
            return {"defaultTeam": {"name": "factory Team"}}
        if (method, path) == ("GET", "work/teamsettings/teamfieldvalues"):
            return {"field": {"referenceName": "System.AreaPath"}, "values": []}
        if (method, path) == ("POST", "wit/wiql"):
            column = re.search(r"\[System\.BoardColumn\] = '([^']*)'", body["query"]).group(1)
            return {"workItems": [{"id": int(n)} for n, s in self.state.items() if s == column]}
        number = path.rsplit("/", 1)[1]
        if method == "GET":
            return {"fields": {"System.WorkItemType": KIND, "System.State": self.state[number]}}
        if method == "PATCH":
            self.state[number] = body[0]["value"]
            self.patched.append((int(number), body[0]["value"]))
            return {}
        raise AssertionError(f"the board called {method} {path}, a route Azure DevOps never had")


@pytest.fixture
def azure(tmp_path, monkeypatch):
    """`(project, board, site)` for a registered Azure DevOps project whose tracker options map
    `columns` — the real row, built by `build_board` from the registry; the site behind it fake."""
    from openfactory.adapters.board.azure_devops import AzureBoardsBoard

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    site = _Azure(n412="New")
    monkeypatch.setattr(AzureBoardsBoard, "_client", lambda self, **_kw: site)

    def _open(columns: dict[str, str], *, language: str = "en"):
        from openfactory.adapters.board import build_board
        from openfactory.contracts.project import Project, ProviderRef
        from openfactory.registry import ProjectRegistry
        from tests.test_the_product_role_moves_cards_by_key import _product

        registry = ProjectRegistry()
        if any(p.name == "acme" for p in registry.list()):
            registry.remove("acme")      # the same project, its `columns` line written in
        registry.add(Project(
            name="acme", repo_path=str(tmp_path), language=language, product=_product(),
            tracker=ProviderRef(kind="azure_devops", repo="factory",
                                options={"organization": "acme",
                                         "columns": json.dumps(columns)})))
        project = registry.get("acme")
        board = build_board(project, token="t")
        assert type(board).__name__ == "AzureBoardsBoard"
        return project, board, site
    return _open


def _tracker():
    """The card as its tracker holds it — open, written on the board; the door asks it first."""
    return SimpleNamespace(
        ticket_url=lambda ref: f"https://dev.azure.com/acme/factory/_workitems/edit/{ref}",
        get_ticket=lambda ref: SimpleNamespace(state="open", title="Exportar CSV", raw=""))


def _promote(project, board, number: str = "412"):
    from tests.test_the_product_role_moves_cards_by_key import _module

    [only] = _module(project, _tmp(project), _tracker()).promote([number], actor=ANA,
                                                                 board=board)
    return only


def _tmp(project):
    from pathlib import Path

    return Path(project.repo_path)


# ── the product role's queueing ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("language, said", [
    ("en", "#412 is in 'New', which is not a column this platform maps, so it cannot tell where "
           "the card is in its life. Nothing was changed. Map it with the project's tracker "
           "option `columns` — if cards wait there to be queued, `columns: '{\"backlog\": "
           "\"New\"}'` makes it the backlog — and try again."),
    ("pt-BR", "O #412 está em 'New', que não é uma coluna que esta plataforma mapeia, então não "
              "há como saber em que ponto da vida o cartão está. Nada foi alterado. Mapeie a "
              "coluna com a opção `columns` do tracker do projeto — se é nela que um cartão "
              "espera para entrar na fila, `columns: '{\"backlog\": \"New\"}'` faz dela o backlog "
              "— e tente de novo."),
])
def test_a_card_in_the_stock_new_column_is_refused_with_the_line_that_maps_it(azure, language,
                                                                              said):
    """THE DEFECT'S SENTENCE, REPAIRED: the person who queued reads which option, which line, and
    in the conversation's language — and nothing moved."""
    project, board, site = azure(MAPPED, language=language)

    refused = _promote(project, board)

    assert not refused.ok
    assert refused.detail == said, refused.detail
    assert site.patched == [], "a card in a column no stage is was moved anyway"


def test_with_the_line_it_names_the_stock_card_is_queued_into_the_deployments_own_queue(azure):
    """THE REPAIR IS THE WHOLE REPAIR: `New` is the backlog, the backlog may be queued, and the
    card lands in the column this deployment calls its queue."""
    project, board, site = azure(REPAIRED)

    queued = _promote(project, board)

    assert (queued.ok, queued.detail) == (True, ""), queued.detail
    assert site.patched == [(412, "Approved")] and site.state["412"] == "Approved"


# ── the panel's move ────────────────────────────────────────────────────────────────────────────

def _card_move(column: str, issue: str = "412"):
    from openfactory import actions

    who = actions.Actor(id="me", display="Me", via="panel", admin=True)
    return asyncio.run(actions.perform("card_move", by=who, project="acme", issue=issue,
                                       column=column))


def test_the_panels_move_refuses_with_the_same_sentence(azure, monkeypatch):
    """`card_move`'s own gate reads the card before the door does, and it said the same refusal
    in other words — one sentence now, wherever the person meets it."""
    from openfactory.product.voice import card_unmapped

    _project, _board, site = azure(MAPPED)
    monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker",
                        lambda *a, **k: _tracker())

    out = _card_move("Approved")

    assert not out.ok
    assert out.message == card_unmapped(ref="412", column="New", option="columns"), out.message
    assert site.patched == []


def test_card_moves_own_gate_refuses_an_unmapped_column_before_the_door_is_asked(azure):
    """The review of #539: since #521 the door says the same sentence, so a test through
    `card_move` passes whether `_stage`'s gate refuses or the door does. Asked directly, the gate
    must answer the refusal itself, with no key, before any transition is attempted."""
    from openfactory.actions.catalog import _stage
    from openfactory.product.voice import card_unmapped

    project, board, _site = azure(MAPPED)

    stage = _stage(project, board, "412")

    assert stage.key == "" and stage.column == "New", stage
    assert stage.cannot_tell == card_unmapped(ref="412", column="New", option="columns",
                                              language=project.language), stage


def test_and_with_the_line_the_panel_queues_it_too(azure, monkeypatch):
    _project, _board, site = azure(REPAIRED)
    monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker",
                        lambda *a, **k: _tracker())

    out = _card_move("Approved")

    assert out.ok, out.message
    assert site.patched == [(412, "Approved")]


# ── the product role's filing ───────────────────────────────────────────────────────────────────

def test_a_card_filed_on_a_board_with_no_backlog_is_placed_nowhere_until_new_is_the_backlog(
        azure):
    """THE RELATED HALF: a filed card is placed in the backlog by the board's own name for it, and
    a stock board has none — the platform's `Backlog` names no column there. The same line puts it
    where Azure filed it."""
    from tests.test_the_product_role_moves_cards_by_key import _module

    project, board, site = azure(MAPPED)
    site.state["413"] = "New"
    module = _module(project, _tmp(project), _tracker())

    assert module._filed_through_the_door("413", by=ANA, tracker=_tracker(),
                                          board=board) == (False, "Backlog")

    project, board, _site = azure(REPAIRED)
    module = _module(project, _tmp(project), _tracker())

    assert module._filed_through_the_door("413", by=ANA, tracker=_tracker(),
                                          board=board) == (True, "New")


# ── the line the person is handed, pasted where they would paste it ─────────────────────────────

#: A registry file as a person keeps it, with the line the sentence printed pasted, as printed,
#: under the tracker's `options` — the place `docs/setup/azure-devops.md` says to put it.
PASTED = """\
projects:
  stock:
    name: stock
    repo_path: {path}
    tracker:
      kind: azure_devops
      repo: factory
      options:
        organization: acme
        {line}
"""


def _said(where: str, azure) -> str:
    """The sentence a person reads, from where they read it."""
    from openfactory import doctor
    from tests.pinned_probes import a_fully_pinned_probe_set

    project, board, _site = azure(MAPPED, language=where.split(":")[-1])
    if where.startswith("refusal"):
        return _promote(project, board).detail
    if where.startswith("pickup"):
        # the board's own pickup remedy, on a board whose queue nobody named: the same kind of line
        report = doctor.diagnose(a_fully_pinned_probe_set(board_columns=lambda: list(STOCK),
                                                          pickup_column=lambda: "To Do"))
        [line] = [f for f in report.findings if f.check == "board_columns"]
        return line.remedy.replace("<your column>", "Approved")
    return _stages_line(project)[0].message


@pytest.mark.parametrize("where, column, stage", [
    ("refusal:en", "New", "backlog"), ("refusal:pt-BR", "New", "backlog"),
    ("doctor:en", "New", "backlog"), ("pickup:en", "Approved", "todo"),
])
def test_the_line_the_sentence_prints_is_a_line_the_registry_takes(azure, tmp_path, where,
                                                                   column, stage):
    """THE REPAIR, TRIED THE WAY A PERSON TRIES IT. The line is taken out of the sentence exactly
    as printed, pasted into a registry file, read back by the real loader, and the board built from
    that entry is asked about the column. Unquoted, the line is a mapping where
    `ProviderRef.options` holds strings, and the registry refuses the project — the repair a person
    was handed broke the project it was meant to fix. The doctor's pickup remedy printed the same
    kind of line, the same way."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.board.base import stage_key
    from openfactory.registry import ProjectRegistry

    line = re.search(r"`(columns: [^`]+)`", _said(where, azure)).group(1)
    pasted = tmp_path / "pasted.yaml"
    pasted.write_text(PASTED.format(path=tmp_path, line=line))

    project = ProjectRegistry(pasted).get("stock")
    board = build_board(project, token="t")

    assert stage_key(board, column) == stage, line


# ── the door: a column that is no stage has no state ────────────────────────────────────────────

@pytest.mark.parametrize("columns", [MAPPED, {"backlog": "Approved", "todo": "Committed"}])
def test_the_door_reads_no_state_for_a_column_no_stage_is_whatever_else_is_mapped(azure,
                                                                                    columns):
    """NOT READ AS THE BACKLOG — even on a board that HAS no backlog to stand in for, and even on
    one that has. The table judges a state; a card in `New` here has none, so every event the
    door is asked about it is refused for the same reason, by the same sentence."""
    from openfactory.lifecycle import CardEvent, transition
    from openfactory.lifecycle.ports import Ports

    project, board, site = azure(columns)
    seen = Ports(project, tracker=_tracker(), board=board).seen("412")

    assert seen.state is None and "`columns`" in seen.cannot_tell, seen
    for event in (CardEvent.PROMOTED, CardEvent.EDITED, CardEvent.WITHDRAWN, CardEvent.REMOVED):
        moved = transition(project, "412", event, by=ANA, tracker=_tracker(), board=board)
        assert moved.refused == seen.cannot_tell, (event, moved)
    assert site.patched == []


def test_the_door_names_the_option_THIS_row_reads():
    """On Jira the map is `status_map`, and a sentence naming `columns` there sends a person to
    edit an option that changes nothing (#231) — the door asks the row, as the edit gate does."""
    from openfactory.adapters.board.jira import JiraProjectBoard
    from openfactory.lifecycle.ports import Ports

    board = JiraProjectBoard(SimpleNamespace(status_map={"todo": "A Fazer"}))
    seen = Ports(SimpleNamespace(name="acme", language="en"), tracker=_tracker(), board=board,
                 columns={"DAR-9": "Arquivado"}).seen("DAR-9")

    assert seen.state is None
    assert "`status_map: '{\"backlog\": \"Arquivado\"}'`" in seen.cannot_tell, seen.cannot_tell
    assert "`columns`" not in seen.cannot_tell, seen.cannot_tell


# ── the doctor, before the first card ───────────────────────────────────────────────────────────

def _stages_line(project):
    """The `board_stages` finding over the REAL probe, every other probe pinned green."""
    from openfactory import doctor
    from tests.pinned_probes import a_fully_pinned_probe_set

    live = doctor.probes_for(project)
    report = doctor.diagnose(a_fully_pinned_probe_set(board_stages=live.board_stages))
    [line] = [f for f in report.findings if f.check == "board_stages"]
    return line, report


def test_the_doctor_names_the_stock_column_no_stage_is_and_the_line_that_maps_it(azure):
    project, _board, _site = azure(MAPPED)

    line, report = _stages_line(project)

    assert line.ok and report.ok, "a column a client's board legitimately has failed the doctor"
    assert "'New' is no stage this platform maps" in line.message, line.message
    assert "no column is the backlog" in line.message, line.message
    assert "`columns: '{\"backlog\": \"New\"}'` makes it the backlog" in line.message, line.message
    assert line.note == line.message, "the verdict does not repeat the line, consequence and all"


def test_and_once_the_line_is_there_it_says_the_board_is_whole(azure):
    project, _board, _site = azure(REPAIRED)

    line, _report = _stages_line(project)

    assert line.ok and not line.note
    assert line.message == ("every column of the board is a stage this platform maps, and 'New' "
                            "is the backlog"), line.message


def test_the_command_prints_it(azure, monkeypatch):
    """THE SENTENCE THE OPERATOR READS: the doctor's own output, not the report object."""
    from typer.testing import CliRunner

    from openfactory import doctor
    from openfactory.cli import app
    from tests.pinned_probes import a_fully_pinned_probe_set

    project, _board, _site = azure(MAPPED)
    live = doctor.probes_for(project)
    monkeypatch.setattr(doctor, "probes_for",
                        lambda _p: a_fully_pinned_probe_set(board_stages=live.board_stages))

    out = CliRunner().invoke(app, ["doctor", "acme"]).output

    assert "board_stages" in out and "'New' is no stage this platform maps" in out, out
    assert "columns: '{\"backlog\": \"New\"}'" in out, out


def test_a_board_whose_row_declares_no_option_is_not_handed_one():
    """`columns` named to a row that reads no such option is a remedy that changes nothing
    (#231), so the doctor names none — the same rule the refusal keeps."""
    from openfactory import doctor
    from tests.pinned_probes import a_fully_pinned_probe_set

    report = doctor.diagnose(a_fully_pinned_probe_set(
        board_stages=lambda: ({"Backlog": "backlog", "Parking": ""}, "")))
    [line] = [f for f in report.findings if f.check == "board_stages"]

    assert "'Parking'" in line.message and "`" not in line.message, line.message


def test_a_board_that_could_not_be_read_is_not_reported_as_one_with_no_backlog(azure):
    """UNREADABLE IS NOT EMPTY — the port's hardest rule. A board whose columns could not be read
    has no column that is the backlog only in the sense that nobody saw any; `board_columns` says
    it could not read the board, once, and this line says nothing rather than something false."""
    from openfactory import doctor
    from openfactory.doctor import BoardUnreadable
    from tests.pinned_probes import a_fully_pinned_probe_set

    project, _board, site = azure(MAPPED)
    site.blind = True
    live = doctor.probes_for(project)

    with pytest.raises(BoardUnreadable):
        live.board_stages()
    report = doctor.diagnose(a_fully_pinned_probe_set(board_stages=live.board_stages))
    assert "board_stages" not in [f.check for f in report.findings]


def test_a_board_with_no_backlog_whose_first_column_is_the_queue_is_not_read_as_harmless():
    """#536, SAID AND NOT REPAIRED HERE: on an Azure board with the Basic process every column is
    mapped, none is the backlog, and the board creates a card in its first column — the pickup
    column. The line must not read as a board that is merely missing a nicety."""
    from openfactory import doctor
    from tests.pinned_probes import a_fully_pinned_probe_set

    basic = {"To Do": "todo", "Doing": "in_progress", "In review": "in_review",
             "Needs Action": "needs_action", "Done": "done"}
    report = doctor.diagnose(a_fully_pinned_probe_set(board_stages=lambda: (basic, "columns")))
    [line] = [f for f in report.findings if f.check == "board_stages"]

    assert "no column is the backlog" in line.message, line.message
    assert "the board's first column, 'To Do', which is the pickup column (#536)" in line.message
    assert line.note == line.message, "the verdict drops what the repair is for"
