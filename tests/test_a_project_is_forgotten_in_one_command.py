"""A project is forgotten in one command — #453.

WHAT IT CLOSES. Forgetting what the product role remembers about a project took seven layers, and
the core offered one command for one of them (`project forget-conversations`). On 2026-09-30 a
deployment's add-on carried a 120-line shell command to reach the rest. `openfactory project
forget <name>` reaches every layer through the API its store already deletes with, refuses by name
what this deployment cannot forget, asks first, backs up first, refuses while something runs, and
says per layer what went.

RUN AGAINST REAL PARTS: the SQLite metrics store the open distribution ships, the local board in
`board.db`, the project's real memory directory and the product's state directory, all in files of
the test's own; the context repository is a real bare git repository. The one double is the
durable engine, which the suite may not reach (`conftest._no_live_durable_engine`).

AND NOTHING THAT IS NOT THE PROJECT'S: every test that deletes runs with a second product's rows,
board, memory and files present, and the deployment's people registered — and asserts they are
all still there.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.memory import transcript
from openfactory.product import forget
from openfactory.product.key import product_key

BOOKS_DOCS, SHOP_DOCS = "acme/books-docs", "acme/shop-docs"


def _project(name: str, docs: str = BOOKS_DOCS) -> Project:
    return Project(name=name, repo_path=f"/work/{name}", language="en",
                   tracker=ProviderRef(kind="local", repo=name, options={}),
                   product=ProductConfig(docs_repo=docs, admins=["U0ADMIN"], agent_name="Nina"))


@pytest.fixture
def deployment(monkeypatch, tmp_path) -> dict[str, Project]:
    """Two registry projects of ONE product (books, books-api) and one of another (shop), on the
    open distribution's store, a local board and memory directories of this test's own."""
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "state" / "metrics.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "state" / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "state" / "board.db"))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    registry = ProjectRegistry()
    projects = {p.name: p for p in (_project("books"), _project("books-api"),
                                    _project("shop", SHOP_DOCS))}
    for p in projects.values():
        registry.add(p)
    return {name: registry.get(name) for name in projects}


def _remember_everything(project: Project, *, thread: str = "sala") -> None:
    """One of every layer the role remembers, written through each store's own writer."""
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.memory import messages
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import DELIVERY, open_loop
    from openfactory.observability.metrics import MetricRecord
    from openfactory.observability.registry import deployment_metrics_sink
    from openfactory.paths import project_memory_dir
    from openfactory.product import attachments, case, sessions

    now = datetime.now(UTC).isoformat()
    transcript.record(project, thread=thread, role="person", text=f"{project.name}: o saldo",
                      actor="ana")
    loop_store.write(project.name, [open_loop(DELIVERY, "7", owner="product", ts=now)])
    sink = deployment_metrics_sink()
    for kind in ("card_verdict", "preview"):
        assert sink.record(MetricRecord(project=project.name, ticket="7", ts=now, kind=kind,
                                        role=kind))
    assert messages.say(project.name, "staged: a monthly report", channel=project.name)
    case.note_turn(project, thread, "ana", "o saldo vem errado", SimpleNamespace(text="Qual tela?"))
    told = Path(project_memory_dir(project)) / "events.json"
    told.write_text(json.dumps({"told": {"delivered-x": 1.0}, "seen": {"pr-1": 2.0}}))
    key = product_key(project)
    attachments.store(key, conversation=thread, name="saldo.txt",
                      data=f"{project.name} statement".encode())
    sessions.rename(key, "ana", "", "o saldo")
    tracker = build_tracker(project)
    closed = tracker.create_ticket(title=f"{project.name}: done long ago", body="b")
    tracker.close_ticket(closed, "shipped")
    tracker.create_ticket(title=f"{project.name}: still open", body="b")


def _what_is_remembered(project: Project, *, thread: str = "sala") -> dict:
    """Each layer as its own reader sees it — the readers the role reads through."""
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.memory import messages
    from openfactory.memory import store as loop_store
    from openfactory.observability.query import records_of_kind
    from openfactory.paths import project_memory_dir
    from openfactory.product import attachments, case, sessions

    key = product_key(project)
    tracker = build_tracker(project)
    return {
        "said": [t.text for t in transcript.recent(project, thread=thread)],
        "loops": len(loop_store.read(project.name)),
        "verdicts": len(records_of_kind(project.name, "card_verdict")),
        "previews": len(records_of_kind(project.name, "preview")),
        "messages": len(messages.read(project.name)),
        "cases": len(case.open_cases(project, thread)),
        "told": (Path(project_memory_dir(project)) / "events.json").is_file(),
        "files": len(attachments.listed_in(key, thread)),
        "names": sessions.titles(key, "ana"),
        "closed": [t.title for t in tracker.list_tickets(state="closed")],
        "open": [t.title for t in tracker.list_tickets(state="open")],
    }


def _bytes_kept(project: Project) -> list[Path]:
    from openfactory.paths import product_state_dir

    return list((product_state_dir(product_key(project)) / "attachments" / "blobs").glob("*"))


def _people() -> list[str]:
    from openfactory.identity.people import PeopleStore

    return [i.id for i in PeopleStore().pending()]


@pytest.fixture
def remembered(deployment):
    """Everything remembered about books — and about shop, and a person registered."""
    from openfactory.identity.people import PeopleStore
    from openfactory.product import case

    _remember_everything(deployment["books"])
    _remember_everything(deployment["shop"])
    assert not isinstance(PeopleStore().invite("ana@acme.example", display="Ana", by="root"),
                          str), "the invitation did not land"
    case._reset_for_tests()   # a fresh process reads the stores, not this one's copies
    return deployment


def _forget(*args: str, input: str | None = None):
    from openfactory.cli import app

    return CliRunner().invoke(app, ["project", "forget", *args], input=input)


# ── the command ─────────────────────────────────────────────────────────────────────────────────

def test_every_layer_the_role_remembers_goes_and_nothing_of_another_project_does(remembered):
    shop_before = _what_is_remembered(remembered["shop"])
    people_before = _people()

    done = _forget("books", "--yes", "--no-backup")

    assert done.exit_code == 0, done.output
    books = _what_is_remembered(remembered["books"])
    assert books == {"said": [], "loops": 0, "verdicts": 0, "previews": 0, "messages": 0,
                     "cases": 0, "told": False, "files": 0, "names": {}, "closed": [],
                     "open": ["books: still open"]}, books
    assert not _bytes_kept(remembered["books"]), "a file's bytes outlived its claims"
    assert _what_is_remembered(remembered["shop"]) == shop_before, "another product's went"
    assert _bytes_kept(remembered["shop"]), "another product's files went"
    assert shop_before["said"] and shop_before["closed"] and shop_before["files"], shop_before
    assert _people() == people_before == ["ana@acme.example"], "the deployment's people went"


def test_each_layer_says_what_went_with_its_count(remembered):
    done = _forget("books", "--yes", "--no-backup")

    lines = {line.split(":")[0][2:]: line for line in done.output.splitlines()
             if line[:2] in ("✓ ", "· ", "✗ ", "! ")}
    assert list(lines) == list(forget.LAYERS), done.output
    assert "1 conversation rows" in lines["conversations"], lines
    assert "1 files sent in them" in lines["conversations"], lines
    assert "1 ledger rows" in lines["loops"], lines
    assert "1 card verdicts, 1 preview records, 1 panel messages" in lines["records"], lines
    assert "1 intake cases, 2 events told" in lines["intake"], lines
    assert "1 closed cards" in lines["closed cards"], lines
    assert lines["context"].startswith("· context: kept"), lines
    assert lines["processes"].startswith("! processes: restart"), lines
    assert "docker compose restart worker panel" in lines["processes"], lines


def test_it_names_what_it_keeps_and_who_shares_the_memory_BEFORE_it_asks(remembered):
    asked = _forget("books", "--no-backup", input="n\n")

    assert asked.exit_code != 0, asked.output
    before = asked.output[:asked.output.index("Proceed?")]
    assert "books-api" in before, "the registry project sharing the conversations is not named"
    for kept in forget.KEPT:
        assert kept in before, f"not said before asking: {kept}"
    assert _what_is_remembered(remembered["books"])["said"], "it deleted on a no"


def test_a_name_this_deployment_does_not_drive_is_refused_by_name(remembered):
    done = _forget("nobody", "--yes")

    assert done.exit_code == 2, done.output
    assert "no project named 'nobody'" in done.output
    assert "forget-conversations nobody" in done.output, "the remedy for an old name"


# ── refused while something runs ────────────────────────────────────────────────────────────────

def test_a_running_job_refuses_it_and_nothing_is_deleted(remembered, monkeypatch):
    async def _running(_t, **_k):
        return forget.Flight(jobs=("books #12",))

    monkeypatch.setattr(forget, "in_flight", _running)

    done = _forget("books", "--yes", "--no-backup")

    assert done.exit_code == 1, done.output
    assert "job books #12" in done.output and "Nothing was deleted" in done.output
    assert _what_is_remembered(remembered["books"])["said"], "it deleted under a running job"


def test_an_engine_that_cannot_say_what_runs_refuses_it(remembered, monkeypatch):
    async def _unread(_t, **_k):
        return forget.Flight(unread="the durable engine did not answer (connection refused)")

    monkeypatch.setattr(forget, "in_flight", _unread)

    done = _forget("books", "--yes", "--no-backup")

    assert done.exit_code == 1, done.output
    assert "cannot tell whether a job or a turn runs" in done.output
    assert _what_is_remembered(remembered["books"])["loops"] == 1


class _Engine:
    """The durable engine as `in_flight` asks it: the running workflows by type, and each
    conversation's presence. A double, because the suite may not reach a real one."""

    def __init__(self, *, jobs=(), conversations=(), presence=None, fails=False):
        self.jobs, self.conversations = list(jobs), list(conversations)
        self.presence, self.fails = dict(presence or {}), fails

    def list_workflows(self, query: str):
        if self.fails:
            raise RuntimeError("visibility store unavailable")
        ids = self.jobs if "JobWorkflow" in query else self.conversations

        async def _rows():
            for wid in ids:
                yield SimpleNamespace(id=wid)
        return _rows()

    def get_workflow_handle(self, wid: str):
        engine = self

        class _Handle:
            async def query(self, _name, _cursor, **_kw):
                return {"seq": 0, "entries": [], "presence": engine.presence.get(wid, {})}
        return _Handle()


def test_what_runs_is_read_for_the_project_and_its_product_and_no_other(deployment):
    import asyncio

    from openfactory.product.door import workflow_id

    books, shop = deployment["books"], deployment["shop"]
    room, quiet = workflow_id(product_key(books), "sala"), workflow_id(product_key(books), "x")
    elsewhere = workflow_id(product_key(shop), "sala")
    engine = _Engine(jobs=["openfactory-books-12", "openfactory-books-api-3", "openfactory-shop-4"],
                     conversations=[room, quiet, elsewhere],
                     presence={room: {"running": True}, quiet: {"running": False},
                               elsewhere: {"running": True}})

    flight = asyncio.run(forget.in_flight(forget.target("books"), client=engine))

    assert flight.jobs == ("books #12", "books-api #3"), flight
    assert flight.turns == (room,), flight
    assert flight.refusal(), "something runs and nothing refused it"
    idle = asyncio.run(forget.in_flight(forget.target("books"), client=_Engine()))
    assert idle == forget.Flight() and not idle.refusal()
    broken = asyncio.run(forget.in_flight(forget.target("books"), client=_Engine(fails=True)))
    assert "visibility store unavailable" in broken.unread and broken.refusal()


def test_no_engine_declared_runs_nothing_and_a_declared_one_that_will_not_answer_refuses(
        deployment, monkeypatch):
    """Nobody declared an engine: nothing can be running in one, and the command says so. One
    declared and silent is NOT a drained floor — an unread list refuses like a running job."""
    import asyncio

    from openfactory.runtime.temporal import view

    books = forget.target("books")
    nothing = asyncio.run(forget.in_flight(books))
    assert nothing == forget.Flight(engine=False) and not nothing.refusal()

    async def _down():
        raise ConnectionError("connection refused")

    monkeypatch.setenv("TEMPORAL_ADDRESS", "engine.invalid:7233")
    monkeypatch.setattr(view, "connect", _down)
    silent = asyncio.run(forget.in_flight(books))
    assert "connection refused" in silent.unread and silent.refusal(), silent


# ── what this deployment cannot forget is refused by name ───────────────────────────────────────

class _KeepsEverything:
    """A store that records and reads and cannot delete — a third-party sink's honest shape."""

    def __init__(self, inner):
        self.inner = inner

    def record(self, rec):
        return self.inner.record(rec)

    def scan(self):
        return self.inner.scan()

    def records_of_kind(self, project, kind, *, limit=500):
        return self.inner.records_of_kind(project, kind, limit=limit)


def test_a_store_that_cannot_delete_is_refused_by_name_and_never_reported_done(remembered,
                                                                              monkeypatch):
    from openfactory.observability import registry

    real = registry.deployment_metrics_sink()
    monkeypatch.setattr(registry, "deployment_metrics_sink", lambda: _KeepsEverything(real))

    done = _forget("books", "--yes", "--no-backup")

    assert done.exit_code == 1, done.output
    for layer in ("conversations", "loops", "records"):
        line = next(x for x in done.output.splitlines() if x.startswith(f"✗ {layer}:"))
        assert "refused" in line and "does not implement deletion" in line, line
    assert _what_is_remembered(remembered["books"])["loops"] == 1, "reported refused, deleted"
    assert "✓ intake: forgotten" in done.output, "one refusal cost the independent layers"


def test_a_store_that_fails_is_reported_FAILED_never_forgotten(remembered, monkeypatch):
    import sqlite3

    from openfactory.observability.sqlite_metrics import SqliteMetricsSink

    def _broken(self, project, *, kind):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(SqliteMetricsSink, "forget", _broken)

    done = _forget("books", "--yes", "--no-backup")

    assert done.exit_code == 1, done.output
    line = next(x for x in done.output.splitlines() if x.startswith("✗ loops:"))
    assert "failed" in line and "disk I/O error" in line and "nothing of it is reported" in line
    assert "not everything was forgotten" in done.output


def test_a_board_with_no_removal_of_its_own_refuses_the_closed_cards_by_name(remembered,
                                                                            monkeypatch):
    from openfactory.adapters.tracker import registry as trackers
    from openfactory.adapters.tracker.local import LocalTracker

    class _ClosesOnly(LocalTracker):
        remove_ticket = None   # the hosted rows' shape: no removal of their own

    monkeypatch.setitem(trackers.TRACKERS, "local", lambda project, **_kw: _ClosesOnly(
        project.name))

    done = _forget("books", "--yes", "--no-backup")

    line = next(x for x in done.output.splitlines() if x.startswith("✗ closed cards:"))
    assert "refused" in line and "no removal of its own" in line, line
    assert done.exit_code == 1
    assert _what_is_remembered(remembered["books"])["closed"] == ["books: done long ago"]


def test_keep_closed_cards_keeps_them_and_says_so(remembered):
    done = _forget("books", "--yes", "--no-backup", "--keep-closed-cards")

    assert done.exit_code == 0, done.output
    assert "· closed cards: kept" in done.output
    assert _what_is_remembered(remembered["books"])["closed"] == ["books: done long ago"]


# ── the backup comes first ──────────────────────────────────────────────────────────────────────

def test_the_backup_is_taken_first_and_holds_what_was_forgotten(remembered, tmp_path):
    from openfactory.adapters.tracker.local import LocalTracker
    from openfactory.observability.sqlite_metrics import SqliteMetricsSink

    done = _forget("books", "--yes")

    assert done.exit_code == 0, done.output
    folder = next((tmp_path / "state" / "backups").glob("forget-books-*"))
    assert str(folder) in done.output
    assert "not answered while it exists" in done.output, "the backup's own risk is not said"
    kept = SqliteMetricsSink(folder / "metrics.db")
    assert [r["extra"]["text"] for r in kept.records_of_kind(product_key(remembered["books"]),
                                                             transcript.TRANSCRIPT_KIND)] == [
        "books: o saldo"]
    assert kept.records_of_kind("books", "agent_loop"), "the ledger is not in the backup"
    old_board = LocalTracker("books", db_path=folder / "board.db")
    assert [t.title for t in old_board.list_tickets(state="closed")] == ["books: done long ago"]
    assert json.loads((folder / "memory" / "books" / "cases.json").read_text())["cases"]
    assert list((folder / "attachments").glob("*.json")), "the files sent are not in the backup"


def test_a_store_with_no_backup_refuses_before_anything_is_deleted(remembered, monkeypatch):
    from openfactory.observability import registry

    real = registry.deployment_metrics_sink()
    monkeypatch.setattr(registry, "deployment_metrics_sink", lambda: _KeepsEverything(real))

    done = _forget("books", "--yes")

    assert done.exit_code == 1, done.output
    assert "offers no backup" in done.output and "--no-backup" in done.output
    assert _what_is_remembered(remembered["books"])["cases"] == 1, "deleted with no backup"


# ── what the narrow deletions beside each store hold ────────────────────────────────────────────

def test_every_kind_it_forgets_is_one_the_store_knows_and_never_the_people():
    from typing import get_args

    from openfactory.identity.people import KIND as PEOPLE
    from openfactory.memory.store import LEDGER_KIND
    from openfactory.observability.metrics import MetricKind

    known = set(get_args(MetricKind))
    assert set(forget.RECORD_KINDS) | {LEDGER_KIND} <= known
    assert PEOPLE not in forget.RECORD_KINDS and PEOPLE != LEDGER_KIND
    assert not {"agent_run", "job", "techlead_watch", "product_sweep"} & set(forget.RECORD_KINDS)


def test_a_process_that_was_not_restarted_cannot_write_forgotten_cases_back(deployment):
    """The worker that loaded the cases before the forgetting still holds them, and its next save
    merges its bucket into the file — which put every forgotten case back. The store's stamp is
    how that process is told."""
    from openfactory.product import case

    books = deployment["books"]
    case.note_turn(books, "sala", "ana", "o saldo vem errado", SimpleNamespace(text="Qual tela?"))
    stale = dict(case._CASES["books"])          # the worker's copy, as it was

    assert case.forget_project(books) == 1
    case._CASES["books"] = stale                # ... and that worker was never restarted
    case._LOADED["books"] = True
    case.note_turn(books, "outra", "bia", "uma pergunta nova", SimpleNamespace(text="ok"))

    path = Path(case._path(books))
    on_disk = [c["thread"] for c in json.loads(path.read_text())["cases"]]
    assert on_disk == ["outra"], f"a forgotten case was written back: {on_disk}"


def test_forget_conversations_is_the_same_conversations_layer(remembered):
    """The older command deletes through the same function, so it erases the files sent in the
    conversations and the names given to them too — the four places one conversation's deletion
    already reached (#335)."""
    from openfactory.cli import app

    done = CliRunner().invoke(app, ["project", "forget-conversations", "books", "--yes"])

    assert done.exit_code == 0, done.output
    assert "erased 1 file(s) sent in them, and the names 1 person(s) gave them" in done.output
    books = _what_is_remembered(remembered["books"])
    assert (books["said"], books["files"], books["names"]) == ([], 0, {})
    assert books["loops"] == 1, "the conversations command reached the operational memory"
    assert _what_is_remembered(remembered["shop"])["files"] == 1


# ── the context repository ──────────────────────────────────────────────────────────────────────

def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout


@pytest.fixture
def context_repo(tmp_path) -> Path:
    """A context repository as the factory leaves it: a baseline requirement, one the role wrote
    from a conversation, a conversation's distillate — and a person's notes under the same folder,
    at a path no distillate has."""
    bare = tmp_path / "docs.git"
    _git("init", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    work = tmp_path / "work"
    _git("clone", str(bare), str(work), cwd=tmp_path)
    (work / "requirements").mkdir()
    (work / "requirements" / "0001-baseline.md").write_text("# REQ-0001\n")
    _git("add", "-A", cwd=work)
    _git("commit", "-m", "baseline: the product as it is", cwd=work)
    (work / "requirements" / "0002-monthly-report.md").write_text("# REQ-0002\n")
    _git("add", "-A", cwd=work)
    _git("commit", "-m", "REQ-0002: A monthly report\n\nProposed from a product conversation "
                         "with ana.\n", cwd=work)
    (work / "requirements" / "0003-by-hand.md").write_text("# REQ-0003\n")
    _git("add", "-A", cwd=work)
    _git("commit", "-m", "REQ-0003: Written by a person, in an editor", cwd=work)
    distillate = work / "conversations" / "room" / ("ab" * 8) / "2026-09-30.md"
    distillate.parent.mkdir(parents=True)
    distillate.write_text("---\nuntil: 2026-09-30\n---\nthey agreed on monthly\n")
    (work / "conversations" / "notes.md").write_text("a person's own notes\n")
    _git("add", "-A", cwd=work)
    _git("commit", "-m", "a conversation, distilled", cwd=work)
    _git("push", "origin", "HEAD:main", cwd=work)
    return bare


def _tree(bare: Path, tmp_path: Path) -> list[str]:
    look = tmp_path / f"look-{len(list(tmp_path.glob('look-*')))}"
    _git("clone", str(bare), str(look), cwd=tmp_path)
    return sorted(_git("ls-files", cwd=look).split())


def test_the_distillates_go_and_the_role_s_requirements_are_named_and_kept(context_repo, tmp_path):
    from openfactory.product.authoring import forget_distillates

    got = forget_distillates(docs_repo="acme/books-docs", clone_url=str(context_repo))

    assert got.ok, got.detail
    assert got.distillates == (f"conversations/room/{'ab' * 8}/2026-09-30.md",)
    assert got.requirements == ("REQ-0002 requirements/0002-monthly-report.md",)
    assert _tree(context_repo, tmp_path) == [
        "conversations/notes.md", "requirements/0001-baseline.md",
        "requirements/0002-monthly-report.md", "requirements/0003-by-hand.md"]


def test_with_context_the_command_removes_the_distillates_through_the_project_s_clone_url(
        deployment, context_repo, tmp_path):
    from openfactory.registry import ProjectRegistry

    registry = ProjectRegistry()
    books = registry.get("books").model_copy(update={
        "forge": ProviderRef(kind="local", repo="books"),
        "product": registry.get("books").product.model_copy(
            update={"docs_repo": f"file://{context_repo}"})})
    registry.remove("books")
    registry.add(books)

    done = _forget("books", "--yes", "--no-backup", "--with-context")

    line = next(x for x in done.output.splitlines() if x.startswith(("✓ context", "✗ context")))
    assert line.startswith("✓ context: forgotten — 1 distillates"), line
    assert "REQ-0002 requirements/0002-monthly-report.md" in line and "product_drop" in line
    assert "conversations/notes.md" in _tree(context_repo, tmp_path)
    assert not [p for p in _tree(context_repo, tmp_path) if p.startswith("conversations/room")]
