"""On an Azure DevOps board, a card the product role files is never born in the pickup column —
it is created in the backlog the deployment declared, or it is not filed and the conversation is
told why; and `openfactory doctor` FAILS a board where it would be (#536).

WHAT WAS FOUND, READ IN v0.5.0-rc.1. On the process `docs/setup/azure-devops.md` built (`OpenFactory
Basic`), `AzureBoardsTracker.create_ticket` sent no `System.State`, so the item got its type's
first state — `To Do`, the row's pickup column. The door's `filed` then placed it in `Backlog`, a
column that board does not have; the placement failed and the card stayed in `To Do`, where
`openfactory poll` and the unattended scan took it. Work started, and was paid for, with nobody
queueing it — ADR-0019 §5, "nothing starts spending on its own", broken by the role whose constant
`FILING_KEY` exists to keep it.

THE FIX, IN THE ORDER A CARD MEETS IT:

  * the TRACKER creates the item in the state the deployment declared as its backlog
    (`state_map: '{"backlog": …}'`) — on the create itself, so no moment exists in which the card
    sits in the queue;
  * the product role asks, BEFORE anything is written, where a card filed now is born
    (`board.base.intake`: the tracker's state, the board's column for it) — and on a board where
    that is the pickup column, or a board it could not read, it files nothing and says why, in the
    conversation's language;
  * `openfactory doctor` asks the same question and FAILS, handing the line that repairs it — a
    line the registry takes, proved by pasting it into one;
  * the setup guide builds a queue of its own (`Ready`), so `To Do` is the backlog.

Driven against the REAL rows — `AzureBoardsTracker` and `AzureBoardsBoard`, built by the registry
from the tracker options a person writes — over a fake Azure DevOps at the one transport every
Azure axis talks through (`AzureDevOpsClient.call`), which keeps the work items, a process's
states and its team's board. The real product role files; the real `openfactory poll` reads the
queue, with the one call that would start (and spend) replaced by a recorder.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest

KIND = "Issue"
ANA = "ana-requester-77"

#: OpenFactory Basic as the guide used to build it, in workflow order — the type's first state is
#: where Azure files an item created without one.
BASIC = (("To Do", "Proposed"), ("Doing", "InProgress"), ("Needs Action", "InProgress"),
         ("In review", "Resolved"), ("Done", "Completed"))
#: …and as it builds it now: a queue of its own, `Ready`, after `To Do` in the Proposed category.
WITH_READY = (("To Do", "Proposed"), ("Ready", "Proposed"), ("Doing", "InProgress"),
              ("Needs Action", "InProgress"), ("In review", "Resolved"), ("Done", "Completed"))
#: The guide's other shape: a backlog state of its own, which is NOT the type's first state.
WITH_BACKLOG = (("To Do", "Proposed"), ("Backlog", "Proposed"), ("Doing", "InProgress"),
                ("Needs Action", "InProgress"), ("In review", "Resolved"), ("Done", "Completed"))

#: The two lines `docs/setup/azure-devops.md` §3 declares.
GUIDE = {"columns": json.dumps({"backlog": "To Do", "todo": "Ready"}),
         "state_map": json.dumps({"backlog": "To Do", "todo": "Ready"})}
OWN_BACKLOG = {"columns": json.dumps({"backlog": "Backlog"}),
               "state_map": json.dumps({"backlog": "Backlog"})}

HELD = {
    "en": ("I filed nothing: on this board a new card starts in 'To Do', the column the factory "
           "picks work up from, so it would start being built — and paid for — without anybody "
           "queueing it. Whoever runs this factory sets where new cards wait; `openfactory "
           "doctor` names the line."),
    "pt-BR": ("Não registrei nada: neste quadro um cartão novo nasce em 'To Do', a coluna de onde "
              "a fábrica pega trabalho, então ele começaria a ser construído — e a custar — sem "
              "ninguém colocá-lo na fila. Quem opera esta fábrica define onde os cartões novos "
              "esperam; o `openfactory doctor` diz a linha."),
}
UNREAD = ("I filed nothing: I could not read the board to see where a new card starts, and one "
          "that starts in the column the factory picks work up from is built without anybody "
          "queueing it. Try again in a moment.")


class _Azure:
    """Azure DevOps for one project: work items, one type's states in workflow order, and its
    team's board — one column per state, each mapping it (a column IS a state), the first one
    INCOMING as the live board reports it. Every state an item is ever in is kept, in order."""

    def __init__(self, states) -> None:
        self.states = tuple(states)
        self.items: dict[int, dict] = {}
        self.lived: dict[int, list[str]] = {}
        self.created: list[tuple[int, list[dict]]] = []
        self.next_id = 100
        #: the board's columns cannot be read — a wrong team answers exactly like this
        self.blind = False
        #: the board's columns say which is the incoming one, as the live board does
        self.typed = True
        #: states of the type the board shows on no column — a state is not a column by existing
        self.unshown: set[str] = set()

    def state_of(self, n) -> str:
        return self.items[int(n)]["System.State"]

    def _row(self, n: int) -> dict:
        return {"id": n, "fields": dict(self.items[n]), "url": f"https://x/_apis/wit/{n}",
                "multilineFieldsFormat": {"System.Description": "markdown"}}

    def _apply(self, n: int, ops: list[dict]) -> None:
        from openfactory.adapters.azure_devops import AzureDevOpsError

        for op in ops:
            if not op["path"].startswith("/fields/"):
                continue
            name, value = op["path"].split("/fields/", 1)[1], op.get("value")
            if name == "System.State":
                if value not in [s for s, _ in self.states]:
                    raise AzureDevOpsError(f"PATCH wit/workitems/{n} → 400: TF401320: the field "
                                           f"'State' contains the value '{value}' that is not in "
                                           f"the list of supported values")
                self.lived[n].append(value)
            self.items[n][name] = value

    def call(self, method: str, path: str, body=None, params=None) -> dict:
        from openfactory.adapters.azure_devops import AzureDevOpsError

        params = dict(params or {})
        if method == "GET" and path.startswith("projects/"):
            return {"defaultTeam": {"name": "factory Team"}}
        if (method, path) == ("GET", "work/boards"):
            return {"value": [{"name": "Issues"}]}
        if method == "GET" and re.fullmatch(r"work/boards/[^/]+/columns", path):
            if self.blind:
                raise AzureDevOpsError("GET work/boards/Issues/columns → 404 TF401501")
            shown = [s for s, _c in self.states if s not in self.unshown]
            last = len(shown) - 1
            return {"value": [{"name": s, "stateMappings": {KIND: s},
                               **({"columnType": ("incoming" if i == 0 else
                                                  "outgoing" if i == last else "inProgress")}
                                  if self.typed else {})}
                              for i, s in enumerate(shown)]}
        if (method, path) == ("GET", "work/teamsettings/teamfieldvalues"):
            return {"field": {"referenceName": "System.AreaPath"}, "values": []}
        if (method, path) == ("GET", f"wit/workitemtypes/{KIND}/states"):
            return {"value": [{"name": s, "category": c} for s, c in self.states]}
        if (method, path) == ("POST", "wit/wiql"):
            query = body["query"]
            column = re.search(r"\[System\.BoardColumn\] = '((?:[^']|'')*)'", query)
            title = re.search(r"\[System\.Title\] = '((?:[^']|'')*)'", query)
            if column:
                want = column.group(1).replace("''", "'")
                ids = [n for n, f in sorted(self.items.items()) if f["System.State"] == want]
            elif title:
                want = title.group(1).replace("''", "'").casefold()
                ids = [n for n, f in self.items.items() if f["System.Title"].casefold() == want]
            else:
                ids = sorted(self.items, reverse=True)
            return {"workItems": [{"id": n} for n in ids]}
        if (method, path) == ("POST", f"wit/workitems/${KIND}"):
            n, self.next_id = self.next_id, self.next_id + 1
            # NO STATE ON THE CREATE IS THE TYPE'S FIRST ONE — Azure's rule, and the defect's root
            self.items[n] = {"System.Id": n, "System.WorkItemType": KIND, "System.Title": "",
                             "System.Description": "", "System.State": self.states[0][0]}
            self.lived[n] = []
            self._apply(n, body)
            self.lived[n] = self.lived[n] or [self.states[0][0]]
            self.created.append((n, body))
            return {"id": n, "fields": dict(self.items[n])}
        if (method, path) == ("GET", "wit/workitems"):
            ids = [int(i) for i in str(params.get("ids") or "").split(",") if i]
            return {"value": [self._row(n) for n in ids if n in self.items]}
        if re.fullmatch(r"wit/workItems/\d+/comments", path):
            return {"id": 1} if method == "POST" else {"comments": [], "totalCount": 0}
        found = re.fullmatch(r"wit/workitems/(\d+)", path)
        if found and int(found.group(1)) in self.items:
            n = int(found.group(1))
            if method == "PATCH":
                self._apply(n, body)
            return self._row(n)
        raise AssertionError(f"{method} {path} is a route this Azure DevOps does not answer")

    def created_in(self) -> list[str | None]:
        """The `System.State` each create SENT — None for a create that sent none."""
        return [next((op["value"] for op in body if op["path"] == "/fields/System.State"), None)
                for _n, body in self.created]


@pytest.fixture
def azure(tmp_path, monkeypatch):
    """`open(states, options, language) -> (project, tracker, board, site)`: a registered Azure
    DevOps project, its tracker and board built by the registry rows, the site behind them fake."""
    from openfactory.adapters.azure_devops import AzureDevOpsClient
    from openfactory.product import events

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(events, "_tell", lambda project, **kw: True)
    holder = SimpleNamespace(site=None)

    def _call(self, method, path, *, body=None, params=None, **_kw):
        return holder.site.call(method, path, body, params)

    monkeypatch.setattr(AzureDevOpsClient, "call", _call)

    def _open(states, options: dict[str, str], *, language: str = "en"):
        from openfactory.adapters.board import build_board
        from openfactory.adapters.tracker.registry import build_tracker
        from openfactory.contracts.project import Project, ProviderRef
        from openfactory.registry import ProjectRegistry
        from tests.test_the_product_role_moves_cards_by_key import _product

        holder.site = _Azure(states)
        registry = ProjectRegistry()
        if any(p.name == "acme" for p in registry.list()):
            registry.remove("acme")
        registry.add(Project(
            name="acme", repo_path=str(tmp_path), language=language, product=_product(),
            tracker=ProviderRef(kind="azure_devops", repo="factory",
                                options={"organization": "acme", **options})))
        project = registry.get("acme")
        tracker, board = build_tracker(project, token="t"), build_board(project, token="t")
        assert (type(tracker).__name__, type(board).__name__) == ("AzureBoardsTracker",
                                                                  "AzureBoardsBoard")
        return project, tracker, board, holder.site
    return _open


def _filed(verb: str, project, tracker, board) -> list:
    """What the product role answers for each of its three filing writers — a card asked for, a
    defect reported, and a requirement broken into work."""
    from pathlib import Path

    from tests.test_a_requirements_delivery_keys_on_the_trackers_refs import REQ, _front, _pen
    from tests.test_the_product_role_moves_cards_by_key import _module

    if verb == "requirement":
        pen = _pen(project, Path(project.repo_path), [_front("Gerar o pacote de fecho")])
        return pen.file_issues(REQ, actor=ANA, tracker=tracker, board=board)
    module = _module(project, Path(project.repo_path), tracker)
    if verb == "ticket":
        return [module.file_ticket(title="Exportar o relatório em CSV", described="o relatório",
                                   reported_by=ANA, tracker=tracker, board=board)]
    return [module.file_defect(restated="o extrato duplica o último lançamento",
                               reported_by=ANA, violates=None, tracker=tracker, board=board)]


def _poll(monkeypatch) -> list[str]:
    """The REAL `openfactory poll acme` — what it would have started, in order. The one call that
    starts a job (and spends) is a recorder; the gates it asks first are open."""
    from typer.testing import CliRunner

    from openfactory import cli
    from openfactory.contracts import JobState

    started: list[str] = []
    monkeypatch.setattr(cli, "resolve_box_image", lambda *a, **k: "img")
    monkeypatch.setattr("openfactory.box_prove.gate_reason", lambda *a, **k: None)
    monkeypatch.setattr("openfactory.scheduler.ready_to_resume", lambda *a, **k: [])
    monkeypatch.setattr(cli, "_drive_one", lambda project, num, **_kw: started.append(str(num))
                        or SimpleNamespace(state=JobState.PR_OPEN, note=""))
    out = CliRunner().invoke(cli.app, ["poll", "acme", "--sandbox", "worktree"])
    assert out.exit_code == 0, out.output
    return started


VERBS = ("ticket", "defect", "requirement")


# ── the board the guide used to build: nothing is filed, and the conversation hears why ─────────

@pytest.mark.parametrize("language", ["en", "pt-BR"])
@pytest.mark.parametrize("verb", VERBS)
def test_where_a_new_card_is_born_in_the_queue_nothing_is_filed_and_the_reason_is_said(
        azure, monkeypatch, verb, language):
    """THE DEFECT, CLOSED AT ITS CAUSE: the role asks before it writes, so no work item exists —
    and the poller has nothing to start."""
    project, tracker, board, site = azure(BASIC, {}, language=language)

    [held] = _filed(verb, project, tracker, board)

    assert (held.ok, held.detail) == (False, HELD[language]), held.detail
    assert site.items == {}, "a card was created where it is born in the queue"
    assert _poll(monkeypatch) == []


def test_a_backlog_declared_as_the_queues_own_state_is_still_the_queue(azure):
    """A DECLARATION IS NOT A REPAIR: the backlog `state_map` names is where the card is born, and
    when that is the column the poller reads, it is refused the same way."""
    project, tracker, board, site = azure(BASIC, {"state_map": json.dumps({"backlog": "To Do"})})

    [held] = _filed("ticket", project, tracker, board)

    assert (held.ok, held.detail) == (False, HELD["en"])
    assert site.items == {}


def test_a_board_whose_columns_report_no_type_is_read_by_its_first_column(azure):
    """Azure DevOps puts the INCOMING column first; a board that does not say which is which is
    read that way, and the card a new item would be is still refused there."""
    project, tracker, board, site = azure(BASIC, {})
    site.typed = False

    [held] = _filed("ticket", project, tracker, board)

    assert (held.ok, held.detail) == (False, HELD["en"])
    assert site.items == {}


def test_a_board_that_could_not_be_read_files_nothing_either(azure):
    """UNREAD IS NOT "SAFE TO SPEND": whether a card filed now starts in the queue is unknown, and
    the filing is asked for again in a moment."""
    project, tracker, board, site = azure(WITH_READY, GUIDE)
    site.blind = True

    [held] = _filed("ticket", project, tracker, board)

    assert (held.ok, held.detail) == (False, UNREAD), held.detail
    assert site.items == {}


# ── the board the guide builds now: filed in the backlog, queued by a person ────────────────────

@pytest.mark.parametrize("verb", VERBS)
def test_on_the_guides_board_a_filed_card_is_created_in_the_backlog_out_of_the_queue(
        azure, monkeypatch, verb):
    project, tracker, board, site = azure(WITH_READY, GUIDE)

    [filed] = _filed(verb, project, tracker, board)

    assert filed.ok, filed.detail
    n = int(filed.ref.lstrip("#"))
    assert site.created_in() == ["To Do"], "the create did not carry the declared backlog"
    assert site.lived[n] == ["To Do"], "the card was in another column on its way"
    assert board.pickup_column() == "Ready" and board.items_in_status("Ready") == []
    assert _poll(monkeypatch) == []


def test_and_a_person_queues_it_and_only_then_the_poller_takes_it(azure, monkeypatch):
    """THE ONE GESTURE THAT SPENDS STILL WORKS: `promote` moves it to the deployment's queue."""
    from pathlib import Path

    from tests.test_the_product_role_moves_cards_by_key import _module

    project, tracker, board, site = azure(WITH_READY, GUIDE)
    [first] = _filed("ticket", project, tracker, board)
    [second] = _filed("defect", project, tracker, board)
    assert _poll(monkeypatch) == []

    [queued] = _module(project, Path(project.repo_path), tracker).promote(
        [first.ref], actor=ANA, board=board)

    assert (queued.ok, queued.detail) == (True, ""), queued.detail
    assert (site.state_of(first.ref), site.state_of(second.ref)) == ("Ready", "To Do")
    assert _poll(monkeypatch) == [first.ref]


def test_a_backlog_that_is_not_the_types_first_state_is_where_the_card_is_born(azure, monkeypatch):
    """THE CREATE CARRIES THE STATE — a move after it would leave the card in `To Do`, the queue
    here, between the two, and for an hour whenever the move failed. Never in `To Do` at all."""
    project, tracker, board, site = azure(WITH_BACKLOG, OWN_BACKLOG)

    [filed] = _filed("ticket", project, tracker, board)

    assert filed.ok, filed.detail
    assert site.created_in() == ["Backlog"]
    assert site.lived[int(filed.ref)] == ["Backlog"], site.lived
    assert board.pickup_column() == "To Do" and _poll(monkeypatch) == []


def test_where_the_types_first_state_is_the_backlog_nothing_needs_declaring_on_the_create(azure):
    """A BOARD WHOSE QUEUE IS NOT WHERE AZURE FILES — only `columns` naming them apart — files as it
    always did: no state on the create, the card born in the first state, which is the backlog."""
    project, tracker, board, site = azure(WITH_READY, {"columns": GUIDE["columns"]})

    [filed] = _filed("ticket", project, tracker, board)

    assert filed.ok, filed.detail
    assert site.created_in() == [None]
    assert site.state_of(filed.ref) == "To Do" and board.items_in_status("Ready") == []


# ── the doctor ──────────────────────────────────────────────────────────────────────────────────

def _intake_line(project):
    """The `board_intake` finding over the REAL probe, every other probe pinned green."""
    from openfactory import doctor
    from tests.pinned_probes import a_fully_pinned_probe_set

    live = doctor.probes_for(project)
    report = doctor.diagnose(a_fully_pinned_probe_set(board_intake=live.board_intake))
    lines = [f for f in report.findings if f.check == "board_intake"]
    return (lines[0] if lines else None), report


def test_the_doctor_fails_a_board_where_a_filed_card_is_born_in_the_queue(azure):
    project, _tracker, _board, _site = azure(BASIC, {})

    line, report = _intake_line(project)

    assert not line.ok and not report.ok, "a board that spends on its own passed the doctor"
    assert "created in 'To Do', the column the poller picks work up from" in line.message
    assert ("`columns: '{\"backlog\": \"To Do\", \"todo\": \"Ready\"}'` and `state_map: "
            "'{\"backlog\": \"To Do\", \"todo\": \"Ready\"}'`") in line.remedy, line.remedy
    assert "docs/setup/azure-devops.md §3" in line.remedy


def test_the_line_the_doctor_hands_over_is_a_repair_the_registry_takes(azure, tmp_path):
    """THE REPAIR, TRIED THE WAY A PERSON TRIES IT: the two lines out of the remedy, pasted under the
    tracker's options in a registry file, read by the real loader — on the board the remedy also
    asks for (a `Ready` state and column) — and a card filed then is born out of the queue."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.board.base import intake
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.registry import ProjectRegistry

    project, _tracker, _board, _site = azure(BASIC, {})
    line, _report = _intake_line(project)
    pasted = "\n".join(f"        {m}" for m in re.findall(r"`((?:columns|state_map): [^`]+)`",
                                                           line.remedy))
    registry = tmp_path / "pasted.yaml"
    registry.write_text(f"projects:\n  acme:\n    name: acme\n    repo_path: {tmp_path}\n"
                        f"    tracker:\n      kind: azure_devops\n      repo: factory\n"
                        f"      options:\n        organization: acme\n{pasted}\n")
    project, _tracker, _board, _site = azure(WITH_READY, {})
    fixed = ProjectRegistry(registry).get("acme")

    born = intake(build_tracker(fixed, token="t"), build_board(fixed, token="t"))

    assert (born.column, born.queue, born.queued) == ("To Do", "Ready", False), born


def test_on_the_guides_board_the_doctor_says_where_a_filed_card_starts(azure):
    project, _tracker, _board, _site = azure(WITH_READY, GUIDE)

    line, report = _intake_line(project)

    assert line.ok and report.ok
    assert line.message == ("a card the product role files starts in 'To Do', out of 'Ready', the "
                            "column the poller reads")


def test_an_unread_board_is_said_once_by_board_columns_and_not_again_here(azure):
    project, _tracker, _board, site = azure(BASIC, {})
    site.blind = True

    line, _report = _intake_line(project)

    assert line is None


def test_a_board_whose_new_card_is_on_no_column_is_not_asked():
    """A GitHub issue is on a board only once it is added, and the local board files into its own
    backlog: neither has a column a card is born in, so neither row has the verb, and the question
    does not arise — for the role or for the doctor."""
    from openfactory.adapters.board.base import intake
    from openfactory.adapters.board.local import LocalBoard
    from openfactory.adapters.tracker.github_project import GitHubProjectBoard

    for row in (GitHubProjectBoard, LocalBoard):
        assert not hasattr(row, "intake_column"), row
    assert intake(SimpleNamespace(intake_state=lambda: "To Do"), SimpleNamespace()) is None
    assert intake(SimpleNamespace(), None) is None


# ── the guide ───────────────────────────────────────────────────────────────────────────────────

def test_the_setup_guide_makes_the_backlog_part_of_the_setup_and_its_lines_hold(azure, tmp_path):
    """THE STATE TABLE LISTS A BACKLOG AS REQUIRED, apart from the queue, and the two lines it
    declares are the lines this file proves: pasted from the guide, the board is safe."""
    from pathlib import Path

    from openfactory.adapters.board import build_board
    from openfactory.adapters.board.base import intake
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.registry import ProjectRegistry

    guide = (Path(__file__).resolve().parent.parent / "docs/setup/azure-devops.md").read_text()
    section = guide.split("## 3 · ", 1)[1].split("\n## ", 1)[0]
    assert "| backlog — where a filed card waits | **To Do** (declared, step 5) | yes — " \
           "**required** |" in section
    assert "| pickup — the queue the factory takes work from | **Ready** (declared, step 5) | " \
           "**no — create it** |" in section
    assert "`Ready` — in the **Proposed** category" in section
    declared = re.search(r"```yaml\ntracker:\n  options:\n((?:    .*\n)+?)```", section).group(1)
    lines = "\n".join("    " + raw.split("#", 1)[0].rstrip() for raw in declared.splitlines())
    registry = tmp_path / "from-the-guide.yaml"
    registry.write_text(f"projects:\n  acme:\n    name: acme\n    repo_path: {tmp_path}\n"
                        f"    tracker:\n      kind: azure_devops\n      repo: factory\n"
                        f"      options:\n        organization: acme\n{lines}\n")
    azure(WITH_READY, {})
    project = ProjectRegistry(registry).get("acme")

    born = intake(build_tracker(project, token="t"), build_board(project, token="t"))

    assert (born.column, born.queue, born.queued) == ("To Do", "Ready", False), born
