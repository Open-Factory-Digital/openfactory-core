"""One semaphore per product on what becomes work — #266 slice 3, ADR-0051 D7–D11.

WHY THIS FILE EXISTS. Conversations with the product role run in parallel, and what they turn
into work did not pass through anything that ordered it. Two proposals at once minted one
requirement number (the second push was refused and landed on a `req/N-…` branch under the same
N); two saves to the context repository collided and the second person was told the save failed;
two conversations that both found nothing both filed the same card. `product/semaphore.py` is the
lock around every act that creates or changes the product's record, keyed by the PRODUCT — the
context repository two registry projects can share — with the duplicate check and the write as one
step, and the model's judgement kept outside it by the write sequence.

REAL CONCURRENCY, NOT A MOCKED LOCK. The races here are run: two threads write to a local bare git
repository as the context repository's base, and every clone waits at a rendezvous for the other
writer's clone — so, without the semaphore, both mint from the same base and the race is
certain; with it, the second never clones until the first has pushed. The timeout is taken
against a semaphore held by another PROCESS, which is also what shows the lock holds across
processes and across two registry projects of one product.

Every rule here has a row in `tools/mutations/266_the_semaphore_on_work.py` that cuts it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.memory import recall
from openfactory.product import authoring, case, engine, semaphore, staging, voice
from openfactory.product import confirm as confirm_module
from openfactory.product.config import ProductLink
from openfactory.product.corpus import Corpus, load_corpus
from openfactory.product.loader import ProductContext
from openfactory.product.module import ProductModule
from openfactory.product.role import ProductAnswer, ProductRole, RequirementDraft
from tests.the_sink_door import SINK_DOOR

DOCS = "acme/books-docs"
ADMIN = "U0ADMIN"
LANG = "pt-BR"


def _project(name: str = "books", docs: str = DOCS) -> Project:
    return Project(name=name, repo_path="/t", language=LANG,
                   product=ProductConfig(docs_repo=docs, admins=[ADMIN]))


def _git(*args, cwd=None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout


def _drafted(title: str) -> ProductAnswer:
    return ProductAnswer(ok=True, draft=RequirementDraft(
        title=title, why="pedido numa conversa", must_be_true=[f"{title} funciona"]))


# ── the harness ─────────────────────────────────────────────────────────────────────────────────

class _Table:
    """The append-only telemetry table, in memory — where the durable staging mirror lands."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._lock = threading.Lock()

    def record(self, rec) -> bool:
        with self._lock:
            self.rows.append({"project": rec.project, "kind": rec.kind, "ticket": rec.ticket,
                              "role": rec.role, "ts": rec.ts, "extra": dict(rec.extra)})
        return True

    def of_kind(self, project, kind, limit=500, **_kw) -> list[dict]:
        with self._lock:
            rows = [r for r in self.rows if r["project"] == project and r["kind"] == kind]
        return sorted(rows, key=lambda r: str(r["ts"]))[-limit:]


@pytest.fixture(autouse=True)
def table(monkeypatch) -> _Table:
    t = _Table()
    monkeypatch.setattr(SINK_DOOR, lambda *a, **k: t)
    monkeypatch.setattr("openfactory.observability.query.records_of_kind", t.of_kind)
    # the factory's own board is not what is under test, and a write reports to it
    monkeypatch.setattr("openfactory.product.module._tell_the_factory", lambda *a, **k: None)
    return t


@pytest.fixture
def docs_base(tmp_path) -> Path:
    """A BARE repository as the context repository's base, seeded with one requirement."""
    bare = tmp_path / "docs.git"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    _git("clone", "-q", str(bare), str(seed))
    (seed / "requirements").mkdir()
    (seed / "requirements" / "0001-conciliar-extratos.md").write_text(
        authoring.render_requirement(RequirementDraft(title="Conciliar extratos",
                                                      must_be_true=["o saldo bate"]), number=1),
        encoding="utf-8")
    _git("add", "-A", cwd=seed)
    _git("commit", "-qm", "seed", cwd=seed)
    _git("push", "-q", "origin", "HEAD:main", cwd=seed)
    return bare


def _corpus(base: Path) -> Corpus:
    """The corpus a turn read BEFORE the semaphore: the base as it was when the turn began."""
    checkout = base.parent / f"read-{time.monotonic_ns()}"
    _git("clone", "-q", str(base), str(checkout))
    return load_corpus(checkout / "requirements")


def _on_main(base: Path, folder: str = "requirements") -> list[str]:
    return [line.rsplit("/", 1)[-1] for line in _git(
        "ls-tree", "-r", "--name-only", "main", folder, cwd=base).splitlines()]


class _Forge:
    """The forge's reads over the context repository: no proposal branch is in flight."""

    def list_branches(self, repo: str = "", *, prefix: str = ""):
        return []

    def pr_for_head(self, head: str, *, repo: str = ""):
        return ""


class _Tracker:
    """A tracker shared by every writer, searched by EXACT title like the real ones — and slow
    to create, so two writers that both searched before either created both create."""

    def __init__(self) -> None:
        self.created: list[str] = []
        self._lock = threading.Lock()

    def find_ticket(self, *, title: str):
        with self._lock:
            return next((f"#{n}" for n, t in enumerate(self.created, 700) if t == title), None)

    def create_ticket(self, *, title: str, body: str) -> str:
        time.sleep(0.3)
        with self._lock:
            self.created.append(title)
            return f"#{699 + len(self.created)}"

    def ticket_url(self, ref: str) -> str:
        return f"https://board.example/{ref.lstrip('#')}"


class _Board:
    def add_item(self, *, issue_url):
        return True

    def set_column(self, *, issue, issue_url, name):
        return True


def _no_model(**_kw) -> str:
    raise AssertionError("no judgement was expected here")


def _module(project: Project, base: Path | None = None, *, corpus: Corpus | None = None,
            tracker=None, judge=_no_model) -> ProductModule:
    ctx = ProductContext(link=ProductLink(active=True, docs_repo=project.product.docs_repo,
                                          kind="ok"),
                         corpus=corpus if corpus is not None else Corpus(),
                         requirements_dir="requirements")
    module = ProductModule(project, token="", context=ctx, tracker=tracker, board=_Board())
    module._clone_url = lambda repo: str(base)
    module._forge = lambda: _Forge()
    module._forge_kind = lambda: "github"
    module._workspace = lambda: (None, None)
    module._role = lambda **_kw: SimpleNamespace(judge_same=judge)
    return module


@pytest.fixture
def rendezvous(monkeypatch) -> None:
    """Every clone waits, up to a second, for the other writer's clone. WITHOUT the semaphore both
    writers clone the same base and mint from it; WITH it the second is still waiting for the
    semaphore, the first gives up waiting, pushes, and only then does the second clone."""
    barrier = threading.Barrier(2)
    real = authoring._git

    def _git_then_meet(args, cwd=None):
        rc, out = real(args, cwd=cwd)
        if args and args[0] == "clone":
            try:
                barrier.wait(timeout=1.0)
            except threading.BrokenBarrierError:
                pass
        return rc, out

    monkeypatch.setattr(authoring, "_git", _git_then_meet)


def _together(*calls):
    """Run the calls on threads of their own, all at once; their results, in order."""
    out: list = [None] * len(calls)
    errors: list[BaseException] = []

    def run(i, fn):
        try:
            out[i] = fn()
        except BaseException as exc:  # noqa: BLE001 — re-raised below, on the test's thread
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert not errors, errors
    return out


# ── numbers: one per requirement, across writers and across registry projects ──────────────────

def test_two_proposals_at_once_never_mint_one_number(docs_base, rendezvous):
    """Both turns read the base with REQ-0001 in it, so both would mint 2. The second mints from
    the base its own clone holds, under the semaphore — and that clone has the first one's 2."""
    project = _project()
    read = _corpus(docs_base)
    first, second = _module(project, docs_base, corpus=read), _module(project, docs_base,
                                                                      corpus=read)

    a, b = _together(lambda: first.propose(_drafted("Exportar extrato em PDF"), actor=ADMIN),
                     lambda: second.propose(_drafted("Login com SSO"), actor=ADMIN))

    assert a.ok and b.ok, (a.detail, b.detail)
    assert sorted([a.number, b.number]) == [2, 3], (a.number, b.number)
    files = _on_main(docs_base)
    assert len({name[:4] for name in files}) == len(files) == 3, files


def test_two_registry_projects_of_one_product_share_one_semaphore(docs_base, rendezvous):
    """ADR-0051 D2: the lock is the PRODUCT's. Two registry projects over one context repository
    under two locks would mint into one corpus twice."""
    web, api = _project("books-web"), _project("books-api")
    assert semaphore.product_of(web) == semaphore.product_of(api)
    read = _corpus(docs_base)

    a, b = _together(
        lambda: _module(web, docs_base, corpus=read).propose(_drafted("Exportar extrato em PDF"),
                                                             actor=ADMIN),
        lambda: _module(api, docs_base, corpus=read).propose(_drafted("Login com SSO"),
                                                             actor=ADMIN))

    assert a.ok and b.ok, (a.detail, b.detail)
    assert a.number != b.number
    files = _on_main(docs_base)
    assert len({name[:4] for name in files}) == len(files), files


def test_a_requirement_asked_twice_at_once_is_written_once_and_the_second_is_told(docs_base,
                                                                                    rendezvous):
    """The same request from two conversations: the first confirmation writes it; the second
    finds it among what was saved after its check, writes nothing, and hears its number — the
    number and what it says, never who asked."""
    project = _project()
    read = _corpus(docs_base)
    seen = semaphore.sequence(project)

    a, b = _together(
        lambda: _module(project, docs_base, corpus=read).propose(
            _drafted("Exportar extrato em PDF"), actor=ADMIN, asked_by="<@U0ANA>", seen=seen),
        lambda: _module(project, docs_base, corpus=read).propose(
            _drafted("Exportar extrato em PDF"), actor=ADMIN, asked_by="<@U0BIA>", seen=seen))

    written, linked = (a, b) if a.ok else (b, a)
    assert written.ok and written.number == 2
    assert not linked.ok and linked.existed and linked.just_asked and linked.number == 2
    assert linked.detail == voice.just_asked_for_a_requirement(
        number=2, title="Exportar extrato em PDF", language=LANG)
    assert "U0ANA" not in linked.detail and "U0BIA" not in linked.detail
    assert [n for n in _on_main(docs_base) if n.startswith("0002")] == [
        "0002-exportar-extrato-em-pdf.md"]
    assert not [n for n in _on_main(docs_base) if n.startswith("0003")]


# ── saves to the context repository: both land ──────────────────────────────────────────────────

def test_two_decisions_saved_at_once_both_land(docs_base, rendezvous):
    """The second of two concurrent saves used to be refused by the push, and its person told the
    save failed. Under the semaphore the second clones after the first pushed."""
    project = _project()
    read = _corpus(docs_base)

    a, b = _together(
        lambda: _module(project, docs_base, corpus=read).record_decision(
            1, decision="o fechamento é mensal", actor=ADMIN),
        lambda: _module(project, docs_base, corpus=read).record_decision(
            1, decision="o extrato sai em PDF", actor=ADMIN))

    assert a.ok and b.ok, (a.detail, b.detail)
    text = _git("show", "main:requirements/0001-conciliar-extratos.md", cwd=docs_base)
    assert "o fechamento é mensal" in text and "o extrato sai em PDF" in text


# ── one card for one request, however many conversations ask ────────────────────────────────────

def _stage_a_card(project: Project, thread: str, title: str, *, who: str, seen: int) -> dict:
    staging.remember(thread, {"kind": "ticket", "title": title, "described": title,
                              "reported_by": f"<@{who}>", "source": "", "channel": thread,
                              "seq": seen}, lang=LANG, project=project)
    return staging.pending_for(thread, project=project)


def test_two_conversations_asking_for_the_same_card_at_once_file_one(table):
    """Both staged before either confirmed; both confirm at once. The titles differ only in
    case and accents, so the tracker's exact search finds nothing for the second — what the
    semaphore's re-check of what was SAVED after the second's check finds is the first."""
    project = _project()
    tracker = _Tracker()
    seen = semaphore.sequence(project)
    ana = _stage_a_card(project, "person:ana", "Exportar relatório mensal em PDF", who="U0ANA",
                        seen=seen)
    bia = _stage_a_card(project, "person:bia", "exportar relatorio mensal em pdf", who="U0BIA",
                        seen=seen)

    said = _together(
        lambda: confirm_module.confirm(project, key="person:ana", entry=ana,
                                       module=_module(project, tracker=tracker), user=ADMIN,
                                       lang=LANG, via="panel"),
        lambda: confirm_module.confirm(project, key="person:bia", entry=bia,
                                       module=_module(project, tracker=tracker), user=ADMIN,
                                       lang=LANG, via="panel"))

    assert len(tracker.created) == 1, tracker.created
    told = [s for s in said if "acabou de ser pedido" in s]
    assert len(told) == 1, said
    assert "https://board.example/700" in told[0], "the second is not linked to the card"
    for sentence in said:
        for somebody in ("U0ANA", "U0BIA", "ana", "bia", "Ana", "Bia"):
            assert somebody not in sentence, f"{somebody!r} crossed conversations: {sentence}"


def test_a_close_card_saved_after_the_check_is_judged_outside_the_lock(table):
    """Not the same words — so the model decides, and it is asked with the semaphore let go."""
    project = _project()
    tracker = _Tracker()
    seen = semaphore.sequence(project)
    first = _module(project, tracker=tracker).file_ticket(
        title="Relatório mensal em PDF", described="x", reported_by="<@U0ANA>")
    asked: list[bool] = []

    def judge(*, sandbox, workspace, request, candidates):
        asked.append(semaphore.held_here())
        assert candidates == ["Relatório mensal em PDF"]
        return "1"

    second = _module(project, tracker=tracker, judge=judge).file_ticket(
        title="Exportar o relatório mensal em PDF", described="y", reported_by="<@U0BIA>",
        seen=seen)

    assert first.ok and second.ok and second.existed and second.just_asked
    assert second.url == first.url
    assert asked == [False], "the model was asked while the semaphore was held"
    assert tracker.created == ["Relatório mensal em PDF"]


def test_what_the_model_says_is_different_is_filed(table):
    project = _project()
    tracker = _Tracker()
    seen = semaphore.sequence(project)
    _module(project, tracker=tracker).file_ticket(title="Relatório mensal em PDF", described="x",
                                                  reported_by="")

    second = _module(project, tracker=tracker, judge=lambda **_kw: "none").file_ticket(
        title="Relatório mensal em PDF por região", described="y", reported_by="", seen=seen)

    assert second.ok and not second.existed
    assert len(tracker.created) == 2


def test_a_write_whose_sequence_never_stops_moving_writes_nothing_unchecked(table):
    """The bound on the rounds: every judgement comes back to find something new saved, so the
    write gives up — said to the person — rather than write unchecked."""
    project = _project()
    tracker = _Tracker()
    seen = semaphore.sequence(project)
    semaphore.note(project, state=semaphore.SAVED, kind="ticket", text="Relatório mensal",
                   ref="#1")

    def busy_elsewhere(*, sandbox, workspace, request, candidates):
        semaphore.note(project, state=semaphore.SAVED, kind="ticket",
                       text=f"Relatório mensal {time.monotonic_ns()}", ref="#2")
        return "none"

    result = _module(project, tracker=tracker, judge=busy_elsewhere).file_ticket(
        title="Relatório mensal em PDF", described="y", reported_by="", seen=seen)

    assert not result.ok and result.detail == voice.too_much_at_once(language=LANG)
    assert tracker.created == []


# ── a staged draft is found from another conversation, anonymously ──────────────────────────────

class _Drafter:
    """A module whose model drafts one fixed title — the engine's `offer_draft` needs no more."""

    def __init__(self, title: str) -> None:
        self.title = title

    def draft(self, request, *, asked_by=""):
        return _drafted(self.title)

    def context(self, **_kw):
        return ProductContext(link=ProductLink(active=True, docs_repo=DOCS, kind="ok"))


def _offered(project, *, thread: str, who: str, title: str, request: str) -> str:
    reply = engine.offer_draft(project, request=request, user=who, thread=thread,
                               module=_Drafter(title), asked_by=f"<@{who}>")
    return reply.text if isinstance(reply, engine.Reply) else str(reply)


def test_a_draft_staged_in_one_conversation_is_found_from_another_without_a_name():
    project = _project()
    _offered(project, thread="person:ana", who="U0ANA", title="Exportar o extrato mensal em PDF",
             request="quero o extrato mensal em PDF")

    text = _offered(project, thread="person:bia", who="U0BIA",
                    title="Extrato mensal exportado em PDF",
                    request="preciso exportar o extrato mensal em pdf")

    assert voice.asked_close_to_this(language=LANG) in text
    for crossing in ("U0ANA", "person:ana", "Exportar o extrato mensal em PDF",
                     "quero o extrato mensal"):
        assert crossing not in text, f"{crossing!r} crossed from the other conversation"
    # and the second is staged anyway: an unconfirmed draft is nobody's yet (D9)
    assert staging.pending_for("person:bia", project=project) is not None


def test_a_staged_draft_that_was_answered_is_no_longer_close_to_anything():
    project = _project()
    _offered(project, thread="person:ana", who="U0ANA", title="Exportar o extrato mensal em PDF",
             request="quero o extrato mensal em PDF")
    ana = staging.pending_for("person:ana", project=project)
    assert staging.consume("person:ana", ana, project=project, by="U0ANA", approved=False)

    text = _offered(project, thread="person:bia", who="U0BIA",
                    title="Extrato mensal exportado em PDF",
                    request="preciso exportar o extrato mensal em pdf")

    assert voice.asked_close_to_this(language=LANG) not in text


def test_a_draft_is_not_close_to_its_own_conversation():
    project = _project()
    _offered(project, thread="person:ana", who="U0ANA", title="Exportar o extrato mensal em PDF",
             request="quero o extrato mensal em PDF")

    text = _offered(project, thread="person:ana", who="U0ANA",
                    title="Extrato mensal exportado em PDF", request="melhor: exportado em pdf")

    assert voice.asked_close_to_this(language=LANG) not in text


def test_the_write_log_keeps_no_person_and_no_conversation_key():
    """What is shared by every registry project of the product carries nobody: no requester
    field exists, and the conversation is kept only as a digest to tell it from the asker's."""
    project = _project()
    _offered(project, thread="person:ana", who="U0ANA", title="Exportar o extrato mensal em PDF",
             request="quero o extrato mensal em PDF")
    from openfactory.paths import product_state_dir

    raw = (product_state_dir(semaphore.product_of(project)) / semaphore.WORK_FILE).read_text()
    assert "Exportar o extrato mensal em PDF" in raw, "the log did not take the staging at all"
    for person in ("U0ANA", "person:ana", "ana"):
        assert person not in raw, f"{person!r} is in the product's write log"


def test_the_already_asked_section_names_nobody(monkeypatch):
    """The prompt a conversation reads never carries who asked — the saved record's requester
    included (ADR-0051 D9)."""
    from openfactory.memory import store as loop_store
    from openfactory.product.corpus import Requirement

    monkeypatch.setattr(loop_store, "read", lambda project: [])
    corpus = Corpus(requirements=[Requirement(number=7, slug="exportar-csv",
                                              title="Exportar CSV dos relatórios",
                                              path="0007-exportar-csv.md",
                                              asked_by="Ana Lima")])
    module = _module(_project(), corpus=corpus)
    module._board_cards = lambda: []

    section = module.already_asked("quero exportar os relatórios em CSV")

    assert "REQ-0007" in section and "Ana Lima" not in section


# ── the write sequence a turn's check saw travels with what it stages ───────────────────────────

class _Turned:
    """The module an Exchange holds, for a stage called on its own."""

    def context(self, **_kw):
        return ProductContext(link=ProductLink(active=True, docs_repo=DOCS, kind="ok"))


def test_what_a_turn_stages_carries_the_sequence_its_check_saw_and_the_yes_rechecks_after_it():
    """Noted before the turn reads anything; a card saved while the model was thinking is after
    it — and the yes finds it, writes nothing, and links it."""
    project = _project()
    ex = engine.Exchange(project, engine.Message(project=project.name, conversation="C1",
                                                 speaker="U0BIA", text="abre um cartão"),
                         module=_Turned())
    semaphore.note(project, state=semaphore.SAVED, kind="ticket", text="Exportar CSV",
                   ref="#9", url="https://board.example/9")

    engine.gestures(ex, ProductAnswer(ok=True, is_ticket=True, ticket_title="Exportar CSV"))
    staged = staging.pending_for("C1", project=project)
    assert staged["seq"] == ex.seen < semaphore.sequence(project)

    tracker = _Tracker()
    said = confirm_module.confirm(project, key="C1", entry=staged,
                                  module=_module(project, tracker=tracker), user=ADMIN,
                                  lang=LANG, via="panel")

    assert tracker.created == [], "a card saved after the check was filed a second time"
    assert said == voice.just_asked_for_a_card(where="https://board.example/9", language=LANG)


# ── the lock itself: released on an exception, and a timeout says so ───────────────────────────

def _holds(project, timeout: float) -> bool:
    try:
        with semaphore.held(project, timeout=timeout):
            return True
    except semaphore.Busy:
        return False


def test_the_semaphore_is_let_go_when_the_write_raises():
    project = _project()

    def boom():
        raise RuntimeError("the push died")

    with pytest.raises(RuntimeError):
        semaphore.check_and_write(project, seen=None, kind="ticket", text="x", write=boom)

    assert not semaphore.held_here()
    [other_thread_got_it] = _together(lambda: _holds(project, 1.0))
    assert other_thread_got_it


def _hold_in_another_process(tmp_path: Path, *, registry_name: str, seconds: float):
    ready = tmp_path / f"held-{registry_name}"
    code = textwrap.dedent(f"""
        import pathlib, time
        from openfactory.contracts.product import ProductConfig
        from openfactory.contracts.project import Project
        from openfactory.product import semaphore
        project = Project(name={registry_name!r}, repo_path="/t",
                          product=ProductConfig(docs_repo={DOCS!r}))
        with semaphore.held(project):
            pathlib.Path({str(ready)!r}).write_text("held")
            time.sleep({seconds})
    """)
    proc = subprocess.Popen([sys.executable, "-c", code], env=dict(os.environ),
                            cwd=str(Path(__file__).resolve().parent.parent))
    deadline = time.monotonic() + 30
    while not ready.exists():
        assert proc.poll() is None, "the holding process died before it held anything"
        assert time.monotonic() < deadline, "the holding process never took the semaphore"
        time.sleep(0.05)
    return proc


def test_a_semaphore_held_by_another_process_times_out_in_words(tmp_path, caplog):
    """Another PROCESS, and another registry project of the same product: the lock is the
    product's and it is the kernel's, so both hold. Waiting past the timeout says so."""
    project = _project("books-web")
    proc = _hold_in_another_process(tmp_path, registry_name="books-api", seconds=3)
    try:
        with caplog.at_level("ERROR", logger="openfactory.product.semaphore"), \
                pytest.raises(semaphore.Busy) as busy:
            with semaphore.held(project, timeout=0.3):
                pass
        assert busy.value.sentence == voice.semaphore_busy(language=LANG)
        assert "OPENFACTORY_PRODUCT_SEMAPHORE_TIMEOUT" in caplog.text
    finally:
        proc.wait(timeout=30)
    assert _holds(project, 5.0), "the semaphore was not let go when its holder ended"


def test_a_write_that_cannot_have_the_semaphore_tells_the_person_and_writes_nothing(
        tmp_path, docs_base, monkeypatch):
    monkeypatch.setattr(semaphore, "TIMEOUT_SECONDS", 0.3)
    project = _project()
    proc = _hold_in_another_process(tmp_path, registry_name="books", seconds=3)
    try:
        result = _module(project, docs_base, corpus=_corpus(docs_base)).propose(
            _drafted("Exportar extrato em PDF"), actor=ADMIN)
    finally:
        proc.wait(timeout=30)

    assert not result.ok and result.detail == voice.semaphore_busy(language=LANG)
    assert _on_main(docs_base) == ["0001-conciliar-extratos.md"]


def test_no_model_is_asked_while_the_semaphore_is_held():
    """D8, held structurally: every product model call passes `ProductRole._ask`, and it refuses
    under the lock — before the agent is reached."""
    asked: list[str] = []
    agent = SimpleNamespace(name="fake", ask=lambda **kw: asked.append(kw["phase"]))
    role = ProductRole(agent)

    with semaphore.held(_project()), pytest.raises(semaphore.ModelUnderSemaphore):
        role.judge_same(sandbox=None, workspace=None, request="x", candidates=["y"])

    assert asked == []


# ── the two JSON stores: replaced whole, and no last writer wins ────────────────────────────────

def _turn(text: str):
    return SimpleNamespace(text="")


def test_the_cases_file_is_replaced_whole_never_rewritten_in_place():
    """A reader holding the file sees the old one whole — never the truncated middle of a
    write, which is what a crash between `write_text`'s truncate and its write left behind."""
    project = _project()
    case.note_turn(project, "C1", "U1", "primeiro", _turn(""))
    path = case._path(project)
    before = path.read_text(encoding="utf-8")

    with open(path, encoding="utf-8") as reader:
        case.note_turn(project, "C1", "U1", "segundo", _turn(""))
        assert reader.read() == before

    assert "segundo" in path.read_text(encoding="utf-8")


def test_a_case_another_process_saved_is_kept_by_this_ones_save():
    project = _project()
    case.note_turn(project, "C1", "U1", "daqui", _turn(""))
    path = case._path(project)
    now = time.time()
    theirs = case.Case(id=f"C2|U2|{now:.3f}", thread="C2", opened_by="U2", facts=["de lá"],
                       opened_ts=now, updated_ts=now)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cases"].append(theirs.model_dump())
    path.write_text(json.dumps(data), encoding="utf-8")   # the other process's save

    case.note_turn(project, "C1", "U1", "daqui de novo", _turn(""))

    ids = {c["id"] for c in json.loads(path.read_text(encoding="utf-8"))["cases"]}
    assert theirs.id in ids, "this process's save overwrote the other's case"


def test_the_recall_index_is_replaced_whole_never_rewritten_in_place(tmp_path):
    path = tmp_path / recall.INDEX_FILE
    index = recall.MemoryIndex(project="books")
    index.add(recall.Said(id="t:C1:1", ts="2026-09-24T10:00:00", store=recall.CONVERSATION,
                          where="C1", role="person", actor="U1", text="relatório mensal"))
    index.save(path)
    before = path.read_text(encoding="utf-8")

    with open(path, encoding="utf-8") as reader:
        index.add(recall.Said(id="t:C1:2", ts="2026-09-24T10:01:00",
                              store=recall.CONVERSATION, where="C1", role="person", actor="U1",
                              text="extrato em PDF"))
        index.save(path)
        assert reader.read() == before

    assert "extrato em PDF" in path.read_text(encoding="utf-8")


def test_a_refresh_reads_the_stores_holding_the_index_lock_of_its_own(tmp_path):
    from openfactory.util.filelock import lock_beside

    held: list[bool] = []

    def rows(_fetch):
        held.append(lock_beside(tmp_path / recall.INDEX_FILE).held_here())
        return []

    recall.refresh("books", tmp_path, transcript_rows=rows, messages_scan=lambda: [])

    assert held == [True]
    assert not semaphore.held_here(), "the index took the product's semaphore, not its own lock"
