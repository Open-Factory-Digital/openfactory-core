"""The product's memory is written as it is confirmed, distilled when a conversation goes quiet,
read whole for "was this done before?", and never shows a client an internal document (#269 slice
3, ADR-0053 D4, D6, D7, D10, D14).

THE ACCEPTANCE CRITERIA, each a test below by name:

  - "was this asked before?" finds a request dropped two years earlier (the years-old fixture);
  - an internal-only document never appears in an answer to a client — the guard walks every path
    a document's text can take into a client turn: every prompt the model is asked, and every file
    of the view it reads, the facts pack and the searches' files included;
  - a distillate is written once per conversation span, through the semaphore, with no name from
    outside the conversation — none at all.

And the rules around them: the "done before?" search runs outside the semaphore, reads the whole
memory — dropped and superseded requirements, closed cards of any age, documents, distillates —
and names nobody; a private conversation's distillate comes back only to that conversation; a view
that cannot be made to its audience is empty, never the shared one; and a yes the semaphore
refused is staged again, never lost.

WHAT IS REAL. The documents pass, the index, the searches, the corpus, a real `ProductModule` turn
with its own view and facts pack, the product's semaphore, and a local bare git repository as the
context repository the distillates are pushed to. What is stood in for is only a MODEL: the harness
that answers a turn, and the distiller.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from openfactory.contracts import AgentRunResult
from openfactory.contracts.document import CLIENT, INTERNAL
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.memory.recall import CONVERSATION, Said
from openfactory.product import asked, semaphore
from openfactory.product import distil as distillation
from openfactory.product.config import ProductLink
from openfactory.product.documents.record import DISTILLATES, distillate_of, withheld
from openfactory.product.index import retrieval
from openfactory.product.index.items import conversation_digest
from openfactory.product.index.search import Query, search
from openfactory.product.index.store import Index
from openfactory.product.loader import ProductContext
from openfactory.product.module import ProductModule, _done_before
from openfactory.product.speaker import ADMIN, ENGINEER, Person
from openfactory.product.speaker import CLIENT as A_CLIENT
from tests import index_bed as bed

#: What only the fixture's internal documents say — the margin review, labelled internal by its
#: folder, and the kickoff notes, which nobody labelled and so are internal too.
INTERNAL_WORDS = ("fell to 12 percent", "will not be renewed", "2023-02-20-margin-review",
                  "Margin review — key accounts", "Margin review of the key accounts",
                  "billing team kept since 2016", "2020-02-10-kickoff")
MARGIN = "internal/2023-02-20-margin-review.md"
KICKOFF = "notes/2020-02-10-kickoff.md"

ROOM = "tidewater"
BRUNO = "person:bruno"
CARLA = "person:carla"


@pytest.fixture(autouse=True)
def _no_embedder_is_remembered():
    from openfactory.adapters.embed import registry

    registry._reset_for_tests()
    yield
    registry._reset_for_tests()


def _git(*args, cwd=None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout


def _project(**product) -> Project:
    return Project(name="tidewater", repo_path="/t",
                   tracker=ProviderRef(kind="github", repo="tidewater/tidewater"),
                   forge=ProviderRef(kind="github", repo="tidewater/tidewater"),
                   product=ProductConfig(docs_repo="tidewater/context", admins=["helena"],
                                         engineers=["bruno"], **product))


# ── "was this asked before?" reaches the whole memory (D7) ──────────────────────────────────────

def _asking_module(tmp_path, project, *, cards, conversation: str = CARLA,
                   audience: str = CLIENT, own: bool = True):
    """A module answering in `conversation`, whose board window is `cards` — the three reads
    `already_asked` makes of it, and the scope its searches run with."""
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    ctx = SimpleNamespace(available=True, corpus=bed.corpus(tmp_path / "context"),
                          requirements_dir="requirements")
    fake = SimpleNamespace(project=project, _board_cards=lambda: list(cards),
                           context=lambda: ctx, _combined=str(root),
                           _turn_view=str(root) if own else str(tmp_path),
                           _conversation=conversation, _documents_audience=audience)
    fake.already_asked = lambda text: ProductModule.already_asked(fake, text)
    return fake


@pytest.fixture
def no_ledger(monkeypatch):
    from openfactory.memory import store

    monkeypatch.setattr(store, "read", lambda _name: [])


def test_was_this_asked_before_finds_a_request_dropped_two_years_earlier(tmp_path, no_ledger):
    """THE ACCEPTANCE. In 2022 a fuel surcharge line was asked for, written as REQ-0007, and dropped
    at the November review; its card, #640, was closed as not planned. Years later a client asks
    for it again. The board a turn reads is a window — here, only what is open — and the card is
    not in it; the product's index still holds it, and the section says so, dated, naming nobody."""
    project, _index = bed.build(tmp_path)
    window = [card for card in bed.cards() if card.state == "open"]
    assert "640" not in {str(c.number) for c in window}, "the window must not hold the old card"
    fake = _asking_module(tmp_path, project, cards=window)

    section = fake.already_asked("We would like a fuel surcharge line on every invoice")

    line = next(x for x in section.splitlines() if "#640" in x)
    assert "closed as not planned" in line and "2022-11-20" in line, line
    assert "Fuel surcharge line on invoices" in line
    requirement = next(x for x in section.splitlines() if "REQ-0007" in x)
    assert "dropped" in requirement, requirement
    dropped_on = datetime(2022, 11, 20, tzinfo=UTC)
    assert datetime.now(UTC) - dropped_on > timedelta(days=2 * 365)
    assert "helena" not in section.lower(), "REQ-0007 names who asked; the section never does"
    assert retrieval.recorded(bed.KEY)[-1]["by"] == retrieval.DONE_BEFORE, \
        "the done-before search is recorded like every search"


def test_the_index_alone_finds_a_dropped_request_with_no_board_and_no_corpus(tmp_path):
    """What the index found is a lead of its own: with no board read and no corpus handed in, the
    dropped requirement and its card are still found, from the whole memory."""
    project, _index = bed.build(tmp_path)
    found = retrieval.done_before(project, "a fuel surcharge line on every invoice")

    matches = asked.already_asked("a fuel surcharge line on every invoice", found=found.hits)

    refs = {m.ref: m for m in matches}
    assert "#640" in refs and refs["#640"].kind == "ticket", matches
    assert "REQ-0007" in refs and "(dropped)" in refs["REQ-0007"].where, matches
    assert all(not m.who for m in matches), "the index keeps nobody's name, and none is added"


def test_done_before_reads_superseded_requirements_and_documents(tmp_path):
    """A superseded requirement comes back in the history of what replaced it — and the done-before
    check lists it, saying what superseded it; a document that recorded the old rule is a lead."""
    project, _index = bed.build(tmp_path)
    text = "invoice numbers restart every January with the year as a prefix"
    found = retrieval.done_before(project, text, audience=CLIENT)

    matches = asked.already_asked(text, found=found.hits, limit=10)

    by_ref = {m.ref: m for m in matches}
    assert "REQ-0004" in by_ref and "superseded by REQ-0009" in by_ref["REQ-0004"].where, matches
    assert any(m.kind in ("document", "decision") and "2021-03-15" in m.where
               for m in matches), matches
    assert "#498" in by_ref, "the card that built the old rule is found, whatever its age"


def test_done_before_shows_every_person_every_document(tmp_path, no_ledger):
    """The product owner's decision of 2026-09-25: a client asking, an engineer in private and a
    pack another conversation may read are all shown the internal document — the check reads
    what every turn reads."""
    from openfactory.product.documents.record import turn_audience

    project, _index = bed.build(tmp_path)
    window = [card for card in bed.cards() if card.state == "open"]
    question = "the margin on the Nordwind account and the volume discount renewal"
    everybody = turn_audience(Person(id="carla", role=A_CLIENT), private=False)

    client = _asking_module(tmp_path, project, cards=window,
                            audience=everybody).already_asked(question)
    engineer = _asking_module(tmp_path, project, cards=window, conversation=BRUNO,
                              audience=everybody).already_asked(question)
    shared = _asking_module(tmp_path, project, cards=window, conversation=BRUNO,
                            audience=everybody, own=False).already_asked(question)
    for said in (client, engineer, shared):
        assert MARGIN in said, said


def test_the_done_before_search_never_runs_under_the_semaphore(tmp_path, no_ledger, caplog):
    project, _index = bed.build(tmp_path)
    fake = _asking_module(tmp_path, project, cards=[])
    before = len(retrieval.recorded(bed.KEY))

    with semaphore.held(project):
        with caplog.at_level("WARNING", logger="openfactory.product"):
            assert _done_before(fake, "a fuel surcharge line on every invoice") == []
        assert "could not be searched" not in caplog.text, "it did not even try under the lock"
        with pytest.raises(semaphore.ModelUnderSemaphore):
            retrieval.done_before(project, "a fuel surcharge line on every invoice")

    assert len(retrieval.recorded(bed.KEY)) == before, "nothing was searched under the lock"
    assert _done_before(fake, "a fuel surcharge line on every invoice"), "and outside it, it is"


def test_the_switch_turns_the_done_before_search_off(tmp_path, monkeypatch, no_ledger):
    project, _index = bed.build(tmp_path)
    monkeypatch.setenv(retrieval.SWITCH_ENV, "off")

    assert _done_before(_asking_module(tmp_path, project, cards=[]),
                        "a fuel surcharge line on every invoice") == []


def test_the_draft_is_checked_against_what_the_answer_was_shown(tmp_path, no_ledger):
    """The duplicate check before a draft is staged reads the same whole-memory section: the role is
    told to report a dropped or superseded twin as a `duplicates` conflict, before the yes."""
    from openfactory.product.role import ProductRole

    project, _index = bed.build(tmp_path)
    fake = _asking_module(tmp_path, project, cards=[])
    seen: list[str] = []

    class _Harness:
        name = "stub"

        def ask(self, *, sandbox, workspace, prompt, phase="ask"):
            seen.append(prompt)
            return AgentRunResult(ok=True, summary='{"title": "Fuel surcharge line", '
                                                   '"must_be_true": ["it shows"]}')

    role = ProductRole(_Harness())
    fake._workspace = lambda: (None, None)
    fake._role = lambda **_kw: role
    drafted = ProductModule.draft(fake, "a fuel surcharge line on every invoice")

    assert drafted.ok
    assert "# Possibly already asked" in seen[-1] and "#640" in seen[-1], seen[-1]
    assert "`duplicates` conflict" in seen[-1]

    older = ProductRole(_Harness())
    older.draft = lambda *, sandbox, workspace, request, asked_by="": "drafted as before"
    fake._role = lambda **_kw: older
    assert ProductModule.draft(fake, "x y z") == "drafted as before", \
        "a role whose draft predates the section is called exactly as before"


# ── an internal document never reaches a client's turn, by any path (D10) ───────────────────────

class _Reader:
    """A harness that answers from a script and records, for every question it is asked, the
    prompt and every file of the directory it stands in — everything a model can read."""

    name = "stub"

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.read: list[str] = []

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.read.append(prompt)
        root = Path(workspace.path)
        for path in sorted(root.rglob("*")):
            if path.is_file():
                self.read.append(f"{path.relative_to(root)}\n{path.read_text(errors='replace')}")
        said = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return AgentRunResult(ok=True, summary=said)


def _turn(tmp_path, monkeypatch, *, person: Person, private: bool, conversation: str):
    """A REAL module turn on the years-old fixture: its view made to its audience, its facts pack
    written with the search before the turn, a `[[BUSCA]]` round, the answer's done-before section
    — and then the draft of the same message. Returns what the model could read, all of it."""
    from openfactory.product.corpus import load_corpus
    from openfactory.product.domain import load_domain

    project, _index = bed.build(tmp_path)
    root = tmp_path / "context"
    harness = _Reader("[[BUSCA: margin review Nordwind volume discount]]",
                      "I could not find anything about that.",
                      '{"title": "Nordwind terms", "must_be_true": ["they hold"]}')
    ctx = ProductContext(link=ProductLink(active=True, docs_repo="tidewater/context", kind="ok"),
                         corpus=load_corpus(root / "requirements"),
                         domain=load_domain(root / "domain"), docs_path=str(root),
                         requirements_dir="requirements")
    module = ProductModule(project, token="", context=ctx, agent=harness)
    monkeypatch.setattr(module, "_source_checkout", lambda: None)
    monkeypatch.setattr(module, "_board_cards", lambda: bed.cards())
    from openfactory.memory import store

    monkeypatch.setattr(store, "read", lambda _name: [])
    module.answering_in(conversation)
    question = "What is our margin on Nordwind, and is their volume discount renewed?"
    try:
        answer = module.answer(question, speaker=person, private=private)
        assert answer.ok, answer
        module.draft(question)
    finally:
        module.release()
    return harness.read


@pytest.mark.parametrize(("person", "private", "conversation"), [
    (Person(id="carla", role=A_CLIENT), False, ROOM),
    (Person(id="carla", role=A_CLIENT), True, CARLA),
    (Person(id="bruno", role=ENGINEER), False, ROOM),
    (Person(id="helena", role=ADMIN, approver=True), False, ROOM),
], ids=["client-in-a-room", "client-in-private", "engineer-in-a-room", "admin-in-a-room"])
def test_every_person_s_turn_reads_every_document_by_every_path(
        tmp_path, monkeypatch, person, private, conversation):
    """THE ACCEPTANCE (the product owner's decision of 2026-09-25, replacing #266 decision 8 for
    what the role reads): whoever talks to the role — a client, an engineer, an admin, in a room or
    in private — reads everything the product exposes. Every prompt the model is asked in the turn
    and every file of the directory it stands in is read, and the internal documents are there:
    the margin review (labelled by its folder) and the kickoff notes (labelled by nobody)."""
    read = _turn(tmp_path, monkeypatch, person=person, private=private,
                 conversation=conversation)

    assert len(read) > 3, "the walk read nothing"
    found = sorted({word for text in read for word in INTERNAL_WORDS if word in text})
    assert found == sorted(INTERNAL_WORDS), f"a document was withheld from a turn: {found}"
    assert any(text.startswith(MARGIN) for text in read), "the document is in the view"
    assert any("found/search-1.md" in text for text in read), "the marker's round was walked"
    assert any("found/before-the-turn.md" in text for text in read), "the pre-turn search was"
    assert any("## The request" in text for text in read), "and the draft's prompt"


@pytest.mark.parametrize("person", [Person(id="bruno", role=ENGINEER),
                                    Person(id="helena", role=ADMIN, approver=True)],
                         ids=["engineer", "admin"])
def test_the_product_s_own_people_in_private_are_shown_it(tmp_path, monkeypatch, person):
    """The control: the same walk, for one of the product's own people alone with the role, finds
    the internal document — in the view and in the searches — so the guard above can see it."""
    read = _turn(tmp_path, monkeypatch, person=person, private=True, conversation=BRUNO)

    assert any("fell to 12 percent" in text for text in read)
    assert any(text.startswith(MARGIN) for text in read), "the document is in the view"


def test_a_client_s_view_holds_exactly_what_a_client_may_read(tmp_path):
    """The rule the view is made with, on the fixture: the client's documents and the curated
    truth — the requirements and the glossary — and nothing labelled internal or labelled by
    nobody. The index withholds the same ones (`test_the_hybrid_index`)."""
    from openfactory.product.documents.ingest import documents_in
    from openfactory.product.index.sync import is_requirement_file

    root = bed.context(tmp_path)

    def curated(path: str) -> bool:
        return is_requirement_file(path, "requirements") or path.startswith("domain/")

    held = withheld(root, CLIENT, curated=curated)
    assert held == [MARGIN, KICKOFF], held
    assert withheld(root, INTERNAL, curated=curated) == []
    shown = [p for p in documents_in(root) if p not in held]
    assert "client/minutes/2023-03-12-billing-review.md" in shown
    assert "requirements/0007-fuel-surcharge-line.md" in shown and "domain/glossary.md" in shown


def test_a_document_that_says_it_is_internal_is_internal_wherever_it_sits(tmp_path):
    """The narrowest label wins: a file under `client/` whose own front matter says internal is
    not a client's to read — the path cannot widen what the document says of itself."""
    root = bed.context(tmp_path)
    (root / "client" / "for-us-only.md").write_text(
        "---\naudience: internal\n---\n# Our pricing floor for Nordwind\n")

    assert "client/for-us-only.md" in withheld(root, CLIENT)
    assert "client/for-us-only.md" not in withheld(root, INTERNAL)


def test_a_view_whose_documents_cannot_be_judged_is_empty(tmp_path, monkeypatch, caplog):
    from openfactory.product.documents import record

    root = bed.context(tmp_path)
    module = ProductModule(bed.project(tmp_path), context=ProductContext(
        link=ProductLink(active=True, docs_repo="tidewater/context", kind="ok"),
        docs_path=str(root), requirements_dir="requirements"))

    def unjudged(*_a, **_k):
        raise OSError("permission denied")

    monkeypatch.setattr(record, "withheld", unjudged)
    with caplog.at_level("ERROR", logger="openfactory.product"):
        made = module._own_view(str(tmp_path / "turns"), docs=root, shared=str(root))

    assert made != str(root) and not any(Path(made).iterdir()), made
    assert "OPENFACTORY_PRODUCT_VIEW_UNJUDGED" in caplog.text
    assert "could not be judged" in _view_gap(module)


def _view_gap(module) -> str:
    from openfactory.product.module import _the_view_s_gap

    return " ".join(_the_view_s_gap(module))


def test_a_folder_holding_only_what_is_withheld_is_not_made_either(tmp_path):
    from openfactory.product.workspace import release_turn_view, turn_view

    root = bed.context(tmp_path)
    turns = tmp_path / "tidewater-turns"
    view = turn_view(turns, docs=root, withheld=[MARGIN, KICKOFF])
    try:
        assert not (view / "internal").exists(), "a folder's name is content too"
        assert not (view / "notes").exists()
        assert (view / "client" / "minutes" / "2023-03-12-billing-review.md").is_file()
    finally:
        release_turn_view(view)


def test_a_view_that_cannot_be_made_to_its_audience_is_empty_never_the_shared_one(
        tmp_path, monkeypatch, caplog):
    from openfactory.product import workspace

    root = bed.context(tmp_path)
    module = ProductModule(bed.project(tmp_path), context=ProductContext(
        link=ProductLink(active=True, docs_repo="tidewater/context", kind="ok"),
        docs_path=str(root), requirements_dir="requirements"))

    # SOMETHING MUST BE WITHHELD FOR A VIEW TO BE MADE: every document is everybody's now, and
    # what is still withheld is another person's private conversation, read into its summary
    other = root / "conversations" / "direct" / ("0" * 16) / "summary.md"
    other.parent.mkdir(parents=True)
    other.write_text("# somebody else's private conversation\n")

    def broken(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(workspace, "turn_view", broken)
    with caplog.at_level("ERROR", logger="openfactory.product"):
        made = module._own_view(str(tmp_path / "turns"), docs=root, shared=str(root))

    assert made != str(root) and not any(Path(made).iterdir()), made
    assert "OPENFACTORY_PRODUCT_EMPTY_VIEW" in caplog.text


def test_the_manifest_says_no_document_was_left_out_of_a_client_s_workspace(tmp_path,
                                                                             monkeypatch):
    read = _turn(tmp_path, monkeypatch, person=Person(id="carla", role=A_CLIENT), private=True,
                 conversation=CARLA)

    readme = next(text for text in read
                  if re.match(r"^\.openfactory-facts-\w+/README\.md\n", text))
    assert "are not in your workspace" not in readme, readme


def test_a_view_made_before_the_answer_holds_every_document(tmp_path):
    """A stage that runs before the answer — a judge of a yes — makes the view with no audience
    told: every document, as every turn's (the product owner's decision of 2026-09-25)."""
    root = bed.context(tmp_path)
    module = ProductModule(bed.project(tmp_path), context=ProductContext(
        link=ProductLink(active=True, docs_repo="tidewater/context", kind="ok"),
        docs_path=str(root), requirements_dir="requirements"))
    module._source_checkout = lambda: None
    try:
        module._workspace()
        view = Path(module._combined)
        assert (view / MARGIN).exists() and (view / KICKOFF).exists()
        assert (view / "requirements" / "0009-one-invoice-sequence.md").is_file()
    finally:
        module.release()


# ── a quiet conversation, distilled once per span, through the semaphore, naming nobody (D4) ────

def _said(where: str, text: str, *, at: datetime, actor: str = "", role: str = "person",
          addressed: bool = True) -> Said:
    ts = at.isoformat()
    return Said(id=f"t:{where}:{ts}", ts=ts, store=CONVERSATION, where=where, role=role,
                actor=actor if role == "person" else "", text=text, addressed=addressed)


NOW = datetime(2026, 9, 24, 18, 0, tzinfo=UTC)


def _conversations(now: datetime = NOW) -> list[Said]:
    """Three conversations: the room, quiet for nine hours; Bruno's, an engineer's in private,
    quiet for seven; Carla's, still talking. The words name people, as people's words do."""
    earlier = now - timedelta(hours=10)
    return [
        _said(ROOM, "Helena here: we want a fuel surcharge line on every invoice again.",
              at=earlier, actor="helena"),
        _said(ROOM, "REQ-0007 asked for that and was dropped at the November 2022 review.",
              at=earlier + timedelta(minutes=1), role="agent"),
        _said(ROOM, "Then leave it dropped. Statements stay monthly — write to "
                    "helena@tidewater.example if Bruno disagrees.",
              at=earlier + timedelta(minutes=2), actor="helena"),
        _said(ROOM, "(to Bruno) lunch at one?", at=earlier + timedelta(minutes=3),
              actor="helena", addressed=False),
        _said(BRUNO, "The reminder job should run at six in the morning, not at noon.",
              at=now - timedelta(hours=8), actor="bruno"),
        _said(BRUNO, "Understood — reminders at six in the morning.",
              at=now - timedelta(hours=7), role="agent"),
        _said(CARLA, "Can statements be sent as PDF?", at=now - timedelta(minutes=30),
              actor="carla"),
        _said(CARLA, "They are, since REQ-0006.", at=now - timedelta(minutes=29), role="agent"),
    ]


class _Distiller:
    """The model, stood in for: it reads each span as a list of what was agreed and asked — and it
    names people, as a careless model would, so the scrub is what is tested."""

    def __init__(self, project) -> None:
        self.project = project
        self.spans: list = []
        self.held: list[bool] = []
        self._lock = threading.Lock()

    def distil(self, span):
        with self._lock:
            self.spans.append(span)
            self.held.append(semaphore.held_here(self.project))
        return distillation.Distilled(
            agreed=["Helena agreed that statements stay monthly; ask helena@tidewater.example "
                    "or <@U0HELENA>."],
            asked=[f"A fuel surcharge line on every invoice — {span.conversation} asked, "
                   f"and Bruno too (@bruno)."],
            refused=["The fuel surcharge line stays dropped (REQ-0007)."],
            by="stub/distiller")


@pytest.fixture
def base(tmp_path) -> Path:
    """The context repository's base — a BARE repository seeded with the years-old fixture."""
    bare = tmp_path / "context.git"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    _git("clone", "-q", str(bare), str(seed))
    shutil.copytree(bed.FIXTURE / "context", seed, dirs_exist_ok=True)
    _git("add", "-A", cwd=seed)
    _git("commit", "-qm", "seed", cwd=seed)
    _git("push", "-q", "origin", "HEAD:main", cwd=seed)
    return bare


def _checkout(base: Path, into: Path) -> Path:
    if into.exists():
        shutil.rmtree(into)
    _git("clone", "-q", str(base), str(into))
    return into


def _writer(project, base: Path, checkout: Path) -> ProductModule:
    ctx = ProductContext(link=ProductLink(active=True, docs_repo="tidewater/context", kind="ok"),
                         docs_path=str(checkout), requirements_dir="requirements")
    module = ProductModule(project, token="", context=ctx)
    module._clone_url = lambda repo: str(base)
    return module


def _distillates(base: Path) -> list[str]:
    listed = _git("ls-tree", "-r", "--name-only", "main", DISTILLATES, cwd=base).splitlines()
    return sorted(listed)


def _file(base: Path, path: str) -> str:
    return _git("show", f"main:{path}", cwd=base)


@pytest.fixture
def spied(monkeypatch):
    """Whether each write of a distillate ran while the product's semaphore was held."""
    from openfactory.product import authoring

    held: list[bool] = []
    real = authoring.record_distillate

    def write(**kw):
        held.append(semaphore.held_here())
        return real(**kw)

    monkeypatch.setattr(authoring, "record_distillate", write)
    return held


def test_a_quiet_conversation_is_distilled_once_per_span_through_the_semaphore_naming_nobody(
        tmp_path, base, spied):
    """THE ACCEPTANCE. The room and Bruno's conversation went quiet; Carla's did not. Each quiet one
    is written once, under `conversations/`, through the product's semaphore — the model ran
    before, outside it — and the file names nobody: not the people in it, not the people of the
    other conversations, not an address, a mention or a private conversation's key."""
    project = _project()
    distiller = _Distiller(project)
    module = _writer(project, base, _checkout(base, tmp_path / "one"))

    report = distillation.distil(project, module=module, root=tmp_path / "one",
                                 said=_conversations(), distiller=distiller, now=NOW)

    written = _distillates(base)
    assert len(written) == 2 and len(report.written) == 2, (written, report)
    kinds = {distillate_of(p) for p in written}
    assert kinds == {(False, conversation_digest(ROOM)), (True, conversation_digest(BRUNO))}
    assert spied == [True, True], "every distillate is written under the product's semaphore"
    assert distiller.held == [False, False], "and the model never runs under it"
    for path in written:
        text = _file(base, path)
        for name in ("helena", "bruno", "carla", "tidewater.example", "<@", "person:", "@"):
            assert name not in text.lower(), f"{name!r} is in {path}:\n{text}"
    said_to_the_model = [line.who for span in distiller.spans for line in span.lines]
    assert set(said_to_the_model) == {"a product admin", "the role", "an engineer"}
    assert not any("lunch" in line.text for span in distiller.spans for line in span.lines), \
        "a line said in a group to somebody else is never handed over"
    assert not any("helena" in line.text.lower() for span in distiller.spans
                   for line in span.lines), "the lines name nobody the product knows"


def test_the_same_span_is_never_distilled_twice(tmp_path, base, spied):
    """Run again with the repository as it is now, nothing is ready and no model is asked; run
    again from a checkout that has not seen the first pass — a pass racing it — the model reads
    it again, and the write, which re-reads the base under the semaphore, writes nothing."""
    project = _project()
    first = _Distiller(project)
    distillation.distil(project, module=_writer(project, base, _checkout(base, tmp_path / "a")),
                        root=tmp_path / "a", said=_conversations(), distiller=first, now=NOW)
    stale = tmp_path / "stale"
    shutil.copytree(bed.FIXTURE / "context", stale)
    assert len(_distillates(base)) == 2

    fresh = _Distiller(project)
    again = distillation.distil(project, module=_writer(project, base,
                                                        _checkout(base, tmp_path / "b")),
                                root=tmp_path / "b", said=_conversations(), distiller=fresh,
                                now=NOW + timedelta(hours=1))
    assert fresh.spans == [] and again.written == [], "nothing new is ready"

    racing = _Distiller(project)
    raced = distillation.distil(project, module=_writer(project, base, stale), root=stale,
                                said=_conversations(), distiller=racing, now=NOW)
    assert len(racing.spans) == 2 and len(raced.already) == 2 and raced.written == []
    assert len(_distillates(base)) == 2, "a span is written once, whoever runs it"

    # A PASS THAT SAW MORE: a line said since, and a span that overlaps the one already written —
    # its path is another, and the base, read under the semaphore, still refuses it
    later = [*_conversations(), _said(ROOM, "And the reference goes on the statement too.",
                                      at=NOW - timedelta(hours=6, minutes=30), actor="helena")]
    longer = distillation.distil(project, module=_writer(project, base, stale), root=stale,
                                 said=later, distiller=_Distiller(project), now=NOW)
    assert longer.written == [] and len(_distillates(base)) == 2, _distillates(base)


def test_two_passes_at_once_write_one_distillate_per_span(tmp_path, base):
    project = _project()
    passes = []
    for name in ("x", "y"):
        root = _checkout(base, tmp_path / name)
        passes.append((_writer(project, base, root), root))
    reports: list = [None, None]

    def run(i: int) -> None:
        module, root = passes[i]
        reports[i] = distillation.distil(project, module=module, root=root,
                                         said=_conversations(), distiller=_Distiller(project),
                                         now=NOW)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    assert len(_distillates(base)) == 2, _distillates(base)
    assert sorted(len(r.written) for r in reports) == [0, 2] or \
        sum(len(r.written) for r in reports) == 2, reports


def test_what_is_said_after_a_distillate_is_the_next_span_alone(tmp_path, base):
    project = _project()
    lines = _conversations()
    distillation.distil(project, module=_writer(project, base, _checkout(base, tmp_path / "a")),
                        root=tmp_path / "a", said=lines, distiller=_Distiller(project), now=NOW)
    [room] = [p for p in _distillates(base) if distillate_of(p)[0] is False]
    first_until = yaml.safe_load(_file(base, room).split("---")[1])["until"]

    later = NOW + timedelta(hours=1)
    more = [*lines,
            _said(ROOM, "One more thing: add the customer's reference to every statement.",
                  at=later, actor="helena"),
            _said(ROOM, "Noted — the customer's reference on statements.",
                  at=later + timedelta(minutes=1), role="agent")]
    second = _Distiller(project)
    distillation.distil(project, module=_writer(project, base, _checkout(base, tmp_path / "b")),
                        root=tmp_path / "b", said=more, distiller=second,
                        now=later + timedelta(hours=7))

    [span] = [s for s in second.spans if s.conversation == ROOM]
    assert span.after == first_until and span.since > first_until
    assert [line.text for line in span.lines][0].startswith("One more thing")
    rooms = [p for p in _distillates(base) if distillate_of(p)[0] is False]
    assert len(rooms) == 2, rooms


def test_a_conversation_still_talking_or_with_nothing_to_say_is_not_distilled():
    project = _project()
    spans = distillation.spans(project, _conversations(), distilled={}, now=NOW)
    assert {s.conversation for s in spans} == {ROOM, BRUNO}

    lonely = [_said("room-2", "hello?", at=NOW - timedelta(hours=9), actor="carla")]
    assert distillation.spans(project, lonely, distilled={}, now=NOW) == [], \
        "a span needs an exchange — a person's line and the role's"


def test_a_span_is_bounded_and_the_rest_is_the_next_one(monkeypatch):
    project = _project()
    monkeypatch.setattr(distillation, "MAX_LINES", 4)
    start = NOW - timedelta(hours=20)
    lines = [_said(ROOM, f"line {n}", at=start + timedelta(minutes=n),
                   actor="helena" if n % 2 == 0 else "", role="person" if n % 2 == 0 else "agent")
             for n in range(10)]

    [span] = distillation.spans(project, lines, distilled={}, now=NOW)
    assert [line.text for line in span.lines] == ["line 0", "line 1", "line 2", "line 3"]
    [rest] = distillation.spans(project, lines, distilled={conversation_digest(ROOM): span.until},
                                now=NOW)
    assert rest.lines[0].text == "line 4"


def test_a_distillate_is_labelled_for_whom_its_conversation_was_read_by(tmp_path, base):
    project = _project()
    distillation.distil(project, module=_writer(project, base, _checkout(base, tmp_path / "a")),
                        root=tmp_path / "a", said=_conversations(),
                        distiller=_Distiller(project), now=NOW)
    fronts = {distillate_of(p)[0]: yaml.safe_load(_file(base, p).split("---")[1])
              for p in _distillates(base)}

    assert fronts[False]["audience"] == CLIENT, "a room is the client's reading, whoever spoke"
    assert fronts[True]["audience"] == INTERNAL, "an engineer's private conversation is internal"
    assert fronts[True]["private"] is True and fronts[False]["private"] is False
    assert fronts[False]["kind"] == "conversation-distillate"


def test_a_private_conversation_s_distillate_comes_back_only_to_it(tmp_path, base):
    """Ingested and indexed, a DIRECT distillate is found by its own conversation's search and by
    no other — not even another conversation of the same person's audience — while the room's is
    found from anywhere a client may read; and the view holds it only for its own conversation."""
    from openfactory.product.documents.ingest import ingest
    from openfactory.product.documents.store import Store
    from openfactory.product.index.sync import sync
    from openfactory.product.key import product_key

    project = _project()
    distillation.distil(project, module=_writer(project, base, _checkout(base, tmp_path / "a")),
                        root=tmp_path / "a", said=_conversations(),
                        distiller=_Distiller(project), now=NOW)
    root = _checkout(base, tmp_path / "read")
    key = product_key(project)
    report = ingest(project, root=root, reader=bed.FixtureReader(),
                    announce=lambda *_a, **_k: False)
    assert not any(p.startswith(DISTILLATES) for p, _ in report.unreadable)
    index = Index(key)
    sync(index, records=Store(key), corpus=bed.corpus(root))

    def found(own: str, audience: str, text: str) -> set[str]:
        hits = search(index, Query(text=text, audience=audience, own=own)).hits
        return {h.source for h in hits if h.kind == "distillate"}

    [bruno] = [p for p in _distillates(base) if distillate_of(p)[0]]
    [room] = [p for p in _distillates(base) if not distillate_of(p)[0]]
    assert bruno in found(BRUNO, INTERNAL, "fuel surcharge statements monthly")
    assert bruno not in found("person:someone-else", INTERNAL,
                              "fuel surcharge statements monthly")
    assert bruno not in found(CARLA, CLIENT, "fuel surcharge statements monthly")
    assert room in found(CARLA, CLIENT, "fuel surcharge statements monthly")

    assert bruno not in withheld(root, INTERNAL, own=BRUNO)
    assert bruno in withheld(root, INTERNAL, own=CARLA)
    assert room not in withheld(root, CLIENT, own=CARLA)


def test_done_before_finds_what_a_room_asked_and_let_drop(tmp_path, base, no_ledger):
    """A distilled conversation is part of the whole memory: asked for again from another
    conversation, the room's distillate is a lead — cited by what it is and when, naming nobody."""
    from openfactory.product.documents.ingest import ingest
    from openfactory.product.documents.store import Store
    from openfactory.product.index.sync import sync
    from openfactory.product.key import product_key

    project = _project()
    distillation.distil(project, module=_writer(project, base, _checkout(base, tmp_path / "a")),
                        root=tmp_path / "a", said=_conversations(),
                        distiller=_Distiller(project), now=NOW)
    root = _checkout(base, tmp_path / "context")
    key = product_key(project)
    ingest(project, root=root, reader=bed.FixtureReader(), announce=lambda *_a, **_k: False)
    sync(Index(key), records=Store(key), corpus=bed.corpus(root))

    found = retrieval.done_before(project, "fuel surcharge line on every invoice stays dropped",
                                  conversation=CARLA)
    matches = asked.already_asked("fuel surcharge line on every invoice stays dropped",
                                  found=found.hits, limit=10)

    conversation = next(m for m in matches if m.kind == "conversation")
    assert "distilled" in conversation.where and "never a decision" in conversation.where
    rendered = asked.render(matches, name_people=False)
    assert "helena" not in rendered.lower() and "bruno" not in rendered.lower()


def test_the_documents_pass_neither_announces_nor_re_reads_a_distillate(tmp_path, base):
    from openfactory.product.documents.ingest import ingest

    project = _project()
    distillation.distil(project, module=_writer(project, base, _checkout(base, tmp_path / "a")),
                        root=tmp_path / "a", said=_conversations(),
                        distiller=_Distiller(project), now=NOW)
    root = _checkout(base, tmp_path / "read")
    read: list[str] = []
    told: list[str] = []

    class _Reader(bed.FixtureReader):
        def read(self, record):
            read.append(record.path)
            return super().read(record)

    ingest(project, root=root, reader=_Reader(), announce=lambda *_a, **_k: False)
    ingest(project, root=root, paths=_distillates(base), reader=_Reader(),
           announce=lambda _p, record, **_k: told.append(record.path) or True,
           conversation=CARLA)

    assert not any(p.startswith(DISTILLATES) for p in read), "a reading is not read again"
    assert told == [], "the platform's own reading of a conversation is nobody's news"


def test_a_pass_distils_a_few_and_leaves_the_rest_for_the_next(tmp_path, base):
    project = _project()
    report = distillation.distil(project, module=_writer(project, base,
                                                         _checkout(base, tmp_path / "a")),
                                 root=tmp_path / "a", said=_conversations(),
                                 distiller=_Distiller(project), now=NOW, limit=1)

    assert len(report.written) == 1 and report.left == 1
    assert "1 left for the next pass" in report.sentence()


def test_nothing_is_distilled_under_the_semaphore(tmp_path, base):
    project = _project()
    module = _writer(project, base, _checkout(base, tmp_path / "a"))
    with semaphore.held(project), pytest.raises(semaphore.ModelUnderSemaphore):
        distillation.distil(project, module=module, root=tmp_path / "a", said=_conversations(),
                            distiller=_Distiller(project), now=NOW)
    with semaphore.held(project), pytest.raises(semaphore.ModelUnderSemaphore):
        distillation.ModelDistiller(project=project, harness=object()).distil(
            distillation.spans(project, _conversations(), distilled={}, now=NOW)[0])


def test_a_model_that_cannot_read_a_span_writes_nothing_and_says_so(tmp_path, base):
    project = _project()

    class _Mute:
        def distil(self, span):
            return distillation.Distilled(error="the model did not answer")

    report = distillation.distil(project, module=_writer(project, base,
                                                         _checkout(base, tmp_path / "a")),
                                 root=tmp_path / "a", said=_conversations(), distiller=_Mute(),
                                 now=NOW)
    assert _distillates(base) == [] and len(report.unread) == 2
    assert "could not read" in report.sentence()


def test_the_default_distiller_reads_one_conversation_in_a_room_of_its_own(tmp_path):
    """The documents' reader, handed the span's lines by role and nothing else, read-only."""
    project = _project()
    seen: dict = {}

    class _Harness:
        name = "stub"
        model = "m"

        def ask(self, *, sandbox, workspace, prompt, phase="ask"):
            seen["files"] = sorted(p.name for p in Path(workspace.path).iterdir())
            seen["text"] = (Path(workspace.path) / "conversation.txt").read_text()
            seen["prompt"], seen["phase"] = prompt, phase
            return AgentRunResult(ok=True, summary='{"agreed": ["statements stay monthly"], '
                                                   '"asked": [], "decided": [], "refused": [], '
                                                   '"open": []}')

    [room, _bruno] = distillation.spans(project, _conversations(), distilled={}, now=NOW)
    got = distillation.ModelDistiller(project=project, harness=_Harness()).distil(room)

    assert got.agreed == ["statements stay monthly"] and got.by == "stub/m"
    assert seen["files"] == ["conversation.txt"] and seen["phase"] == distillation.PHASE
    assert "a product admin:" in seen["text"] and "helena" not in seen["text"].lower()
    assert "NAME NOBODY" in seen["prompt"]


# ── saved when confirmed (ADR-0051 D10) ─────────────────────────────────────────────────────────

class _Writes:
    """A module that records which write each confirmation performs, and when."""

    def __init__(self) -> None:
        self.called: list[str] = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def write(*_a, **_k):
            self.called.append(name)
            done = SimpleNamespace(ok=True, existed=False, ref="#1", url="", detail="",
                                   number=7, merged=False, just_asked=False,
                                   nothing_to_build=False)
            return [done] if name in ("promote", "reorder") else done

        return write


#: What each confirmation writes, by the kind staged — every kind the executor knows.
WRITES = {"queue": "promote", "defect": "file_defect", "ticket": "file_ticket",
          "reorder": "reorder", "accept": "accept", "drop": "drop",
          "decision": "record_decision", "close": "close_card", "align": "align_card",
          "correct": "correct_card", "fact": "note_fact", "draft": "propose"}


def _entry(kind: str) -> dict:
    from openfactory.product.role import ProductAnswer, RequirementDraft

    return {"kind": kind, "numbers": ["1"], "restated": "it breaks", "title": "a card",
            "number": 1, "requirement": 2, "decision": "we decided", "term": "t", "body": "b",
            "text": "t", "answer": ProductAnswer(ok=True, draft=RequirementDraft(
                title="x", must_be_true=["y"]))}


@pytest.mark.parametrize("kind", sorted(WRITES))
def test_every_confirmation_writes_when_it_is_confirmed(kind, monkeypatch):
    """The rule, walked over every kind a person can say yes to: the yes performs its write in the
    confirmation itself — nothing confirmed waits for the conversation to end."""
    from openfactory.product import confirm as confirm_module
    from openfactory.product import staging

    assert set(WRITES) == {*confirm_module._EXECUTORS, "draft"}, "a kind this walk does not know"
    monkeypatch.setattr(confirm_module, "_also_broke_it_down",
                        lambda *a, **k: "broken down")
    module = _Writes()
    project = _project()
    staging.forget("walk")
    staging.remember("walk", _entry(kind))
    entry = staging.pending_for("walk")
    monkeypatch.setattr("openfactory.product.module.may_act", lambda *a, **k: True)
    monkeypatch.setattr(confirm_module, "not_theirs", lambda *a, **k: "")

    confirm_module.confirm(project, key="walk", entry=entry, module=module, user="helena")

    assert module.called and module.called[0] == WRITES[kind], module.called


@pytest.mark.parametrize(("outcomes", "again"), [
    (["refused"], True), (["refused", "refused"], True), (["found"], False),
    (["written"], False), (["written", "refused"], False), (["refused", "written"], False),
    ([], False)])
def test_only_a_yes_that_wrote_nothing_for_contention_is_staged_again(outcomes, again):
    from openfactory.product.confirm import _refused_for_contention

    module = SimpleNamespace(_write_outcomes=["written", *outcomes])
    assert _refused_for_contention(module, 1) is again


def test_a_yes_the_semaphore_refused_is_staged_again_and_the_next_yes_writes_it(
        tmp_path, base, monkeypatch):
    """A yes whose write waited for the product's semaphore and did not get it wrote nothing; it
    used to be consumed with it, so "ask me again" meant saying it all again. It waits again, and
    the next yes records it."""
    from openfactory.product import confirm as confirm_module
    from openfactory.product import staging
    from openfactory.product.corpus import load_corpus

    project = _project()
    root = _checkout(base, tmp_path / "read")
    ctx = ProductContext(link=ProductLink(active=True, docs_repo="tidewater/context", kind="ok"),
                         corpus=load_corpus(root / "requirements"), docs_path=str(root),
                         requirements_dir="requirements")
    monkeypatch.setattr("openfactory.product.module._tell_the_factory", lambda *a, **k: None)
    key = "person:helena"
    staging.forget(key)
    staging.remember(key, {"kind": "decision", "number": 9, "channel": "",
                           "decision": "numbers never restart"}, project=project,
                     person="helena")

    def busy(*_a, **_k):
        raise semaphore.Busy("product", 45.0)

    real = semaphore.check_and_write
    monkeypatch.setattr(semaphore, "check_and_write", busy)
    first = ProductModule(project, token="", context=ctx)
    first._clone_url = lambda repo: str(base)
    said = confirm_module.confirm(project, key=key, entry=staging.pending_for(key),
                                  module=first, user="helena")
    assert "Nada" in said or "Nothing" in said
    assert staging.pending_for(key) is not None, "the refused yes waits for the next one"

    monkeypatch.setattr(semaphore, "check_and_write", real)
    second = ProductModule(project, token="", context=ctx)
    second._clone_url = lambda repo: str(base)
    confirm_module.confirm(project, key=key, entry=staging.pending_for(key), module=second,
                           user="helena")
    assert staging.pending_for(key) is None
    assert "numbers never restart" in _file(base, "requirements/0009-one-invoice-sequence.md")
