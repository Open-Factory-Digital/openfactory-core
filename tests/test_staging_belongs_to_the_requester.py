"""What is ready to try before it reaches anyone is the requester's to try, and their answer is read
where they are (#448, slice 4 — the first part).

WHAT WAS WRONG, read in the code on the branch slice 3 left. A job that merged and passed its
stages parks at the last gate before the product's users, and the tech-lead's hourly round offered
it (`activities._offer_the_release_to_the_client`):

  · to the product's ROOM, and nowhere else — the person who asked for the card heard it was ready
    to try only if they happened to read the room;
  · with one question, an acceptance loop that lived in the room — so their answer, given in their
    own conversation, was read against the room's question, and nothing of theirs was asked;
  · and a verdict closed the ONE loop it landed on, which was the only one there was.

WHAT IS PROVEN HERE, on the real ledger and the real acceptance store (SQLite, as a local
deployment runs them), the real record of what was told, the real round run as an activity, and
the real settling stage of the conversation with the real product module — doubled only where
something leaves the machine: the engine's client the round lists the parked jobs on, the door a
telling goes through (`events._tell`, which needs a running conversation), the card's title from
the board, and the release itself (`release.release`, which signals the engine):

  · the requester is told in their own conversation, once per run of the job and again for a new
    run, and a card nobody asked for in a conversation is the room's question alone;
  · their copy of the question opens beside the room's, lives in their conversation, and is the
    one their answer there reaches — while the room's turns never see it;
  · a verdict that counts closes every copy, from either side, and the round asks nothing again
    while either is open; a post that did not land opens nothing.

WHO PUTS IT IN FRONT OF EVERYONE (#448 slice 4, decided by the product owner's delegate). The
requester's own "it works" was refused at the gate that lists the product's admins, like a
stranger's. Now it is the input the last gate waits for, and the project says what it does
(`Project.release_by_requester`, the operator's, off by default): off, it is RECORDED — their copy
closes as `worked`, the room's stays open, the room is told once that they say it is right, and
they hear who puts it live; on, it releases as an admin's does. An admin's release after their yes
says so in the record it leaves. Proven on a LOCAL board, where the card records who asked for it
(`ProductModule.asked_for`), with the real record of what was told.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from temporalio.testing import ActivityEnvironment

from openfactory.contracts import JobState
from openfactory.memory import store as loop_store
from openfactory.memory.ledger import ACCEPTANCE, CLOSED, DELIVERY, close_by_observation, open_loop
from openfactory.memory.ledger import waiting as open_loops
from openfactory.product import accept, agenda, events, followup, voice
from openfactory.product.conversation import owner_of
from openfactory.product.speaker import sealed
from tests.the_card_at_its_last_gate import at_its_last_gate

LANG, AGENT = "en", "Nina"
#: The product's room — on the panel, the project's own name (`channel_destination`).
ROOM = "acme"
#: The person who asked for the card, the product admin, and the conversation the person asked in.
ASKER, ADMIN = "ana-asked-77", "po-admin-12"
THEIRS = f"person:{ASKER}"
#: Where the job says a person looks (`where_to_look`), and the card it was built for.
URL = "https://qa.acme.example"
CARD = "500"
PR = "https://forge.example/acme/pull/7"
T0 = "2026-10-01T10:00:00+00:00"
TITLE = "Export the list"


# ── the deployment: a registered project, its stores, and what was told ──────────────────────────

@pytest.fixture
def project(monkeypatch, tmp_path):
    """A registered project with a product role on the panel, and the platform's own store —
    SQLite on disk, which holds the ledger and the acceptances."""
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    ProjectRegistry().add(Project(
        name=ROOM, repo_path=str(tmp_path), language=LANG,
        product=ProductConfig(docs_repo="acme/docs", admins=[ADMIN], agent_name=AGENT)))
    # THE CARD'S DOOR READS THE CARD FIRST (#448 slice 6): this project names no tracker, and its
    # cards are the parked jobs' — open at their production gate
    at_its_last_gate(monkeypatch)
    return ProjectRegistry().get(ROOM)


@pytest.fixture
def card_of_theirs(monkeypatch, tmp_path):
    """`make(release_by_requester)` → `(project, card)`: the deployment above, on a LOCAL board
    where the card records who asked for it — what `ProductModule.asked_for` reads, so the
    requester is the card's own and not a name the test asserts (#448 slice 4)."""
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.product.board import forget_board
    from openfactory.registry import ProjectRegistry

    def make(release_by_requester: bool):
        monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
        monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
        monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
        monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
        monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
        ProjectRegistry().add(Project(
            name=ROOM, repo_path=str(tmp_path), language=LANG,
            tracker=ProviderRef(kind="local", repo=ROOM, options={}),
            product=ProductConfig(docs_repo="acme/docs", admins=[ADMIN], agent_name=AGENT),
            release_by_requester=release_by_requester))
        project = ProjectRegistry().get(ROOM)
        LocalBoardSetup().create(project=project, owner="", title=ROOM, token=None)
        forget_board()
        tracker = build_tracker(project)
        ref = tracker.create_ticket(title=TITLE, body="export the list", requester=ASKER)
        # WHERE A JOB PARKED AT ITS LAST GATE LEAVES ITS CARD: the column a person's gate is in,
        # which the card's door reads before a verdict there counts (#448 slice 6)
        tracker.set_state(ref, JobState.AWAITING_PROD_APPROVAL)
        return project, ref.lstrip("#")

    yield make
    forget_board()


@pytest.fixture
def told(monkeypatch, tmp_path) -> SimpleNamespace:
    """Every telling the door was handed — the room's question and the requester's own — and the
    real record of what was told, on disk. `refuse` names conversations the door will not take."""
    book = SimpleNamespace(said=[], refuse=set())

    def _tell(project, *, id, conversation, text):
        if conversation in book.refuse:
            return False
        book.said.append({"id": id, "conversation": conversation, "text": text})
        return True

    monkeypatch.setattr(events, "_tell", _tell)
    monkeypatch.setattr(events, "_title_of", lambda project, card: TITLE)
    monkeypatch.setattr(events, "_store_path", lambda project: tmp_path / "memory" / "events.json")
    return book


@pytest.fixture(autouse=True)
def _nothing_staged_nothing_recorded(monkeypatch):
    """A turn reads what is staged and records what it said; neither is under test here."""
    from openfactory.memory import transcript
    from openfactory.product import staging

    monkeypatch.setattr(staging, "_PENDING", {})
    monkeypatch.setattr(staging, "_EXPIRED_TOMBSTONES", {})
    monkeypatch.setattr(transcript, "record", lambda *a, **k: "")
    monkeypatch.setattr(transcript, "recent", lambda *a, **k: [])


class _Released(list):
    """`(issue, approver)` for every release the gate let through, and the record each left."""

    def __init__(self) -> None:
        super().__init__()
        self.comments: list[str] = []


@pytest.fixture
def released(monkeypatch) -> list:
    """Every release the gate let through — the act, not its sentence."""
    calls = _Released()

    def _release(project, issue, *, approver, comment=""):
        calls.append((str(issue), approver))
        calls.comments.append(comment)
        return True, ""

    monkeypatch.setattr("openfactory.product.release.release", _release)
    return calls


def _asked_in_their_conversation(where: str = THEIRS, card: str = CARD) -> None:
    """The card's delivery, as the work was filed from the requester's conversation."""
    loop_store.write(ROOM, [open_loop(DELIVERY, "7", owner=followup.OWNER, ts=T0,
                                      context={"issues": card,
                                               **followup.delivered_to(where, ASKER)})])


def _releases() -> list:
    return [x for x in open_loops(loop_store.read(ROOM), owner=followup.OWNER)
            if x.kind == ACCEPTANCE and followup.is_release(x)]


def _closed() -> dict:
    """Every release loop's latest outcome, by where it was asked."""
    from openfactory.memory.ledger import fold

    return {x.about: x.outcome for x in fold(loop_store.read(ROOM))
            if x.kind == ACCEPTANCE and followup.is_release(x) and x.state == CLOSED}


# ── the engine's client, as the round reaches it ─────────────────────────────────────────────────

class _Handle:
    def __init__(self, job: dict) -> None:
        self.job = job

    async def query(self, what):
        if what == "awaiting_approval":
            return True
        return {"stage": "qa", "url": self.job["url"]}


class _Engine:
    """The running jobs the round lists — each parked at the last gate, in a run of its own."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}

    def parks(self, card: str, *, run: str, url: str = URL) -> None:
        from openfactory.runtime.temporal.view import job_id

        self.jobs[job_id(ROOM, card)] = {"run": run, "url": url}

    async def list_workflows(self, _query):
        for wf_id, job in list(self.jobs.items()):
            yield SimpleNamespace(id=wf_id, run_id=job["run"])

    def get_workflow_handle(self, wf_id, run_id=None):
        return _Handle(self.jobs[wf_id])


@pytest.fixture
def engine() -> _Engine:
    return _Engine()


def _round(project, engine) -> str:
    from openfactory.runtime.temporal import activities as acts

    return asyncio.run(ActivityEnvironment().run(acts._offer_the_release_to_the_client, project,
                                                 engine))


def _module(project):
    from openfactory.product.module import ProductModule

    return ProductModule(project, via="panel")


def _answer(project, text: str, *, who: str, where: str):
    """A message, read by the conversation's settling stage as it ships, with the real module."""
    from openfactory.product import engine as turn

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(turn, "find_waiting", lambda *a, **k: (None, None))
        return turn.settle(project, text=text, user=who, thread=where, module=_module(project))


# ── 1. the requester hears it, where they asked, once per run ────────────────────────────────────

def test_the_job_says_which_run_it_is_parked_in(engine):
    from openfactory.product import release

    engine.parks(CARD, run="run-1")
    assert asyncio.run(release.parked_for_release(engine, ROOM)) == [(CARD, URL, "run-1")]


def test_the_requester_is_told_in_their_conversation_and_the_room_is_still_asked(
        project, told, engine):
    _asked_in_their_conversation()
    engine.parks(CARD, run="run-1")

    assert _round(project, engine) == "release-asked:1"

    room, theirs = told.said
    assert room["conversation"] == ROOM
    assert room["text"] == followup.release_question(requirement="7", where=URL, agent_name=AGENT,
                                                     language=LANG)
    assert theirs["conversation"] == THEIRS
    assert theirs["text"] == voice.staged_for_you(ref=CARD, title=TITLE, where=URL, language=LANG,
                                                  agent_name=AGENT)


def test_once_per_run_and_again_for_a_new_run(project, told):
    _asked_in_their_conversation()

    assert events.staged_for_you(project, card=CARD, where=URL, run="run-1")
    assert not events.staged_for_you(project, card=CARD, where=URL, run="run-1"), (
        "told twice for one run")
    assert events.staged_for_you(project, card=CARD, where=URL, run="run-2"), (
        "a new run of the card's job, with something new to try, was not told")
    assert [t["conversation"] for t in told.said] == [THEIRS, THEIRS]


def test_a_new_run_parked_after_the_last_was_answered_is_told_again_by_the_round(
        project, told, engine, released):
    _asked_in_their_conversation()
    engine.parks(CARD, run="run-1")
    _round(project, engine)
    _answer(project, "funcionou", who=ADMIN, where=ROOM)
    told.said.clear()

    engine.parks(CARD, run="run-2")
    _round(project, engine)

    assert [t["conversation"] for t in told.said] == [ROOM, THEIRS]
    assert len(_releases()) == 2


def test_a_card_nobody_asked_for_in_a_conversation_is_the_rooms_question_alone(
        project, told, engine):
    engine.parks(CARD, run="run-1")

    _round(project, engine)

    assert [t["conversation"] for t in told.said] == [ROOM]
    [loop] = _releases()
    assert "conversation" not in loop.context and loop.about == ROOM


def test_a_requester_who_asked_in_the_room_is_not_told_twice_there(project, told, engine):
    _asked_in_their_conversation(where=ROOM)
    engine.parks(CARD, run="run-1")

    _round(project, engine)

    assert [t["conversation"] for t in told.said] == [ROOM]
    assert len(_releases()) == 1


def test_a_card_with_no_delivery_is_told_where_its_requester_accepted_it(project, told, engine):
    """A card the role opened from a request opens no delivery loop: the acceptance's conversation
    is the way back to the person who asked, as it is for `merged_for_you`."""
    assert accept.record(ROOM, accept.Acceptance(card=CARD, pr_url=PR, head="c0ffee", by=ASKER,
                                                 where=THEIRS))
    engine.parks(CARD, run="run-1")

    _round(project, engine)

    assert [t["conversation"] for t in told.said] == [ROOM, THEIRS]
    [theirs] = [x for x in _releases() if x.context.get("conversation")]
    assert theirs.context["requester"] == sealed(ASKER)


# ── 2. their copy of the question lives where they are ───────────────────────────────────────────

def test_both_copies_open_and_each_lives_where_it_was_asked(project, told, engine):
    _asked_in_their_conversation()
    engine.parks(CARD, run="run-1")

    _round(project, engine)

    rooms, theirs = sorted(_releases(), key=lambda x: bool(x.context.get("conversation")))
    assert (rooms.about, theirs.about) == (ROOM, THEIRS), "two copies, two rows of the ledger"
    assert followup.is_release(rooms) == followup.is_release(theirs) == CARD
    assert theirs.context["conversation"] == THEIRS
    # THE CONVERSATION IS KEPT AS IT IS — it is where the reminder goes, and a digest cannot be
    # sent to; the PERSON is a digest, sealed once, as the card's delivery holds it
    assert theirs.context["requester"] == sealed(ASKER) != sealed(sealed(ASKER))

    # THE RUN RIDES ON BOTH (#448 slice 4): what the room is told when they say it is right is
    # keyed on it (`events.tried_and_right`)
    assert rooms.context["run"] == theirs.context["run"] == "run-1"

    assert agenda.audience(rooms, room=ROOM).room
    mine = agenda.audience(theirs, room=ROOM)
    assert not mine.room and mine.conversation == sealed(owner_of(THEIRS))
    assert mine.person == sealed(ASKER)


def test_their_answer_in_their_conversation_reaches_their_copy(project, told, engine):
    from openfactory.product.module import _acceptances_here

    _asked_in_their_conversation()
    engine.parks(CARD, run="run-1")
    _round(project, engine)

    for said in ("funcionou", "não funcionou"):
        verdict, loop, ambiguous = _module(project).settle_acceptance(said, conversation=THEIRS)
        assert loop.context.get("conversation") == THEIRS, said
        assert not ambiguous, "one release asked in two places was read as two"
    assert len(_releases()) == 2, "the settling stage closed a release — only the gate may"

    in_the_room = _acceptances_here(project, loop_store.read(ROOM), ROOM)
    assert [x.about for x in in_the_room] == [ROOM], "the room's turn sees the requester's copy"
    verdict, loop, _ = _module(project).settle_acceptance("funcionou", conversation=ROOM)
    assert "conversation" not in loop.context


def test_naming_the_release_in_their_conversation_is_a_name_not_a_second_guess(
        project, told, engine):
    """With another release waiting, "#500 funcionou" names one release — that it has two copies
    does not make the name a guess between them."""
    _asked_in_their_conversation()
    engine.parks(CARD, run="run-1")
    engine.parks("501", run="run-9")
    _round(project, engine)

    verdict, loop, ambiguous = _module(project).settle_acceptance(f"#{CARD} funcionou",
                                                                  conversation=THEIRS)
    assert (verdict, followup.is_release(loop), loop.about, ambiguous) == (
        "worked", CARD, THEIRS, False)


def test_another_release_waiting_is_still_a_choice_and_each_is_named_once(project, told, engine):
    from openfactory.product.engine import _waiting_release_refs

    _asked_in_their_conversation()
    engine.parks(CARD, run="run-1")
    engine.parks("501", run="run-9")
    _round(project, engine)

    _, _, ambiguous = _module(project).settle_acceptance("funcionou", conversation=THEIRS)
    assert ambiguous, "two different releases waiting were read as one"
    assert _waiting_release_refs(project) == [CARD, "501"]


# ── 3. a verdict that counts closes every copy ───────────────────────────────────────────────────

def test_an_admins_release_from_the_room_closes_both_copies(project, told, engine, released):
    _asked_in_their_conversation()
    engine.parks(CARD, run="run-1")
    _round(project, engine)

    _answer(project, "funcionou", who=ADMIN, where=ROOM)

    assert released == [(CARD, ADMIN)]
    assert _releases() == [], "the requester is still being asked about a change already out"
    assert _closed() == {ROOM: "worked", THEIRS: "worked"}


def test_a_verdict_closes_the_copies_of_its_own_release_and_no_other(project, told, engine,
                                                                     released):
    _asked_in_their_conversation()
    engine.parks(CARD, run="run-1")
    engine.parks("501", run="run-9")
    _round(project, engine)

    _answer(project, f"#{CARD} funcionou", who=ADMIN, where=ROOM)

    assert released == [(CARD, ADMIN)]
    assert [followup.is_release(x) for x in _releases()] == ["501"]


def test_the_requesters_no_closes_both_copies_and_releases_nothing(project, told, engine,
                                                                  released):
    _asked_in_their_conversation()
    engine.parks(CARD, run="run-1")
    _round(project, engine)

    _answer(project, "não funcionou", who=ASKER, where=THEIRS)

    assert released == []
    assert _releases() == [], "the room is still being asked to release what did not work"
    assert _closed() == {ROOM: "did-not-work", THEIRS: "did-not-work"}


# ── 3b. who puts it in front of everyone (#448 slice 4) ─────────────────────────────────────────

def _at_the_last_gate(project, card, engine, told, *, run: str = "run-1") -> None:
    """The card's change parked at the last gate, asked in the room and of its requester."""
    _asked_in_their_conversation(card=card)
    engine.parks(card, run=run)
    _round(project, engine)
    told.said.clear()


@pytest.mark.parametrize("theirs_counts", [False, True])
def test_the_requesters_yes_is_the_projects_to_count(card_of_theirs, told, engine, released,
                                                     theirs_counts):
    """THE DECISION, BOTH WAYS. Off (the default): their yes is recorded — their copy closes as
    `worked`, the room's stays open for an admin, the room is told, and they hear who puts it live.
    On: their yes releases it, as an admin's does, and says whose it was in the release's record."""
    project, card = card_of_theirs(theirs_counts)
    _at_the_last_gate(project, card, engine, told)

    settled = _answer(project, "funcionou", who=ASKER, where=THEIRS)

    if theirs_counts:
        assert released == [(card, ASKER)]
        assert released.comments == [voice.engine_said("released_by_requester", language=LANG)]
        assert _releases() == [] and _closed() == {ROOM: "worked", THEIRS: "worked"}
        assert told.said == [], "the room was told to release what is already going out"
        assert settled.reply == f"{AGENT}: " + voice.engine_said("releasing", language=LANG)
        return
    assert released == [], "the requester's word released it where the project does not let it"
    assert [x.about for x in _releases()] == [ROOM], "the room's question went with their yes"
    assert _closed() == {THEIRS: "worked"}, "their yes was not recorded"
    [room] = told.said
    assert room["conversation"] == ROOM
    assert room["text"] == voice.tried_and_right(ref=card, title=TITLE, where=URL, language=LANG,
                                                 agent_name=AGENT)
    assert settled.reply == f"{AGENT}: " + voice.requester_said_right(ref=card, told=True,
                                                                      language=LANG)


def test_the_room_is_told_once_and_their_second_yes_is_answered_the_same(
        card_of_theirs, told, engine, released):
    project, card = card_of_theirs(False)
    _at_the_last_gate(project, card, engine, told)

    first = _answer(project, "funcionou", who=ASKER, where=THEIRS)
    second = _answer(project, "funcionou", who=ASKER, where=THEIRS)

    assert [t["conversation"] for t in told.said] == [ROOM], "the room was told twice"
    assert second.reply == first.reply, "the second yes was told the room does not know"
    assert released == [] and [x.about for x in _releases()] == [ROOM]


def test_an_admins_release_after_their_yes_records_that_they_said_it_was_right(
        card_of_theirs, told, engine, released):
    project, card = card_of_theirs(False)
    _at_the_last_gate(project, card, engine, told)
    _answer(project, "funcionou", who=ASKER, where=THEIRS)

    _answer(project, "funcionou", who=ADMIN, where=ROOM)

    assert released == [(card, ADMIN)]
    assert released.comments == [voice.engine_said("released_after_the_requester",
                                                   language=LANG)]
    assert _releases() == []


def test_an_admins_release_says_the_requester_said_so_only_of_the_asking_they_answered(
        card_of_theirs, told, engine, released):
    """Their yes to an EARLIER asking is not a yes to this one: the job ran again, they were not
    reached this time, and the admin's release is recorded as the admin's alone."""
    project, card = card_of_theirs(False)
    _at_the_last_gate(project, card, engine, told)
    _answer(project, "funcionou", who=ASKER, where=THEIRS)
    _answer(project, "não funcionou", who=ADMIN, where=ROOM)
    assert _releases() == []
    told.refuse = {THEIRS}
    engine.parks(card, run="run-2")
    _round(project, engine)
    assert [x.about for x in _releases()] == [ROOM], "the test did not ask the room alone"

    _answer(project, "funcionou", who=ADMIN, where=ROOM)

    assert released.comments == [voice.engine_said("released_by_client", language=LANG)]


def test_an_admins_release_without_their_yes_is_the_admins(card_of_theirs, told, engine,
                                                           released):
    project, card = card_of_theirs(False)
    _at_the_last_gate(project, card, engine, told)

    _answer(project, "funcionou", who=ADMIN, where=ROOM)

    assert released == [(card, ADMIN)]
    assert released.comments == [voice.engine_said("released_by_client", language=LANG)]


def test_somebody_who_neither_asked_nor_may_approve_is_refused_and_nothing_closes(
        card_of_theirs, told, engine, released):
    """Even where the requester's word counts: the rule is the CARD's requester, never whoever
    answers — and never a guest."""
    from openfactory.product.module import unauthorized_message
    from openfactory.product.speaker import GUEST

    project, card = card_of_theirs(True)
    _at_the_last_gate(project, card, engine, told)

    for who in ("somebody-else-42", GUEST):
        settled = _answer(project, "funcionou", who=who, where=ROOM)
        assert settled.reply == unauthorized_message(project), who
    assert released == [] and len(_releases()) == 2 and told.said == []


def test_the_room_hears_their_name_when_the_people_store_knows_it(card_of_theirs, told, engine,
                                                                  released):
    from openfactory.identity.people import PASSWORD_MIN_CHARS, PeopleStore

    project, card = card_of_theirs(False)
    store = PeopleStore()
    token, _ = store.invite(ASKER, by=ADMIN)
    assert not isinstance(store.register(token=token, display="Ana Souza",
                                         password="x" * PASSWORD_MIN_CHARS), str)
    _at_the_last_gate(project, card, engine, told)

    _answer(project, "funcionou", who=ASKER, where=THEIRS)

    [room] = told.said
    assert room["text"] == voice.tried_and_right(ref=card, title=TITLE, who="Ana Souza",
                                                 where=URL, language=LANG, agent_name=AGENT)


def test_an_id_is_never_said_as_a_name():
    from openfactory.product.engine import _name_of

    assert _name_of("nobody-registered") == ""


def test_a_person_registered_with_no_name_is_not_named_by_their_id(card_of_theirs):
    """`register` keeps the id as the display when none was chosen — an identity provider's key,
    which the room is never handed as a name."""
    from openfactory.identity.people import PASSWORD_MIN_CHARS, PeopleStore
    from openfactory.product.engine import _name_of

    card_of_theirs(False)
    store = PeopleStore()
    token, _ = store.invite(ASKER, by=ADMIN)
    store.register(token=token, display="", password="x" * PASSWORD_MIN_CHARS)
    assert PeopleStore().snapshot().people[ASKER].display == ASKER
    assert _name_of(ASKER) == ""


def test_the_room_is_told_once_per_run_and_again_for_a_new_one(project, told):
    assert events.tried_and_right(project, card=CARD, run="run-1", where=URL)
    assert events.tried_and_right(project, card=CARD, run="run-1", where=URL), (
        "told once already, and the room was said not to know")
    assert events.tried_and_right(project, card=CARD, run="run-2", where=URL)
    assert [t["conversation"] for t in told.said] == [ROOM, ROOM]
    told.refuse = {ROOM}
    assert not events.tried_and_right(project, card=CARD, run="run-3", where=URL), (
        "a telling the door did not take was reported as known")


def test_a_not_yet_that_could_be_either_of_two_closes_nothing_and_asks_which(project, told,
                                                                           engine, released):
    """A "não funcionou" closes the question it lands on and sends that card back for another
    pass — on a guess, the wrong card would be rebuilt."""
    from openfactory.product.engine import _waiting_release_refs

    _asked_in_their_conversation()
    engine.parks(CARD, run="run-1")
    engine.parks("501", run="run-9")
    _round(project, engine)

    settled = _answer(project, "não funcionou", who=ADMIN, where=ROOM)

    assert settled.not_yet == "", "a pass was asked for on a guess"
    assert len(_releases()) == 3, "a question was closed on a guess"
    listed = ", ".join(f"#{r}" for r in _waiting_release_refs(project))
    assert settled.reply == f"{AGENT}: " + voice.engine_said(
        "not_yet_ambiguous", language=LANG, which=f" ({listed})")


def test_a_not_yet_names_the_card_for_another_pass_and_a_yes_names_none(project, told, engine,
                                                                       released):
    _asked_in_their_conversation()
    engine.parks(CARD, run="run-1")
    _round(project, engine)

    assert _answer(project, "funcionou", who=ADMIN, where=ROOM).not_yet == ""
    engine.parks(CARD, run="run-2")
    _round(project, engine)
    assert _answer(project, "não funcionou", who=ASKER, where=THEIRS).not_yet == CARD


@pytest.mark.parametrize("language", ["en", "pt-BR"])
def test_what_they_and_the_room_read_has_no_pipeline_vocabulary(language):
    said = [voice.requester_said_right(ref=CARD, told=told, language=language)
            for told in (True, False)]
    said += [voice.tried_and_right(ref=CARD, title=TITLE, who=who, where=where,
                                   language=language, agent_name=AGENT)
             for who in ("", "Ana Souza") for where in (URL, "")]
    for text in said:
        prose = text.replace(URL, "«the address»").lower()
        assert not voice.jargon_in(prose), voice.jargon_in(prose)
        for word in ("staging", "deploy", "release", "produção", "production", "pipeline"):
            assert word not in prose, f"{word!r} reached a person: {text}"
    assert "admin" in said[0].lower()
    assert (URL in said[2]) and (URL not in said[3]), "the address was dropped, or one implied"
    # NO ADDRESS IS NO "AT": the sentence changes, never a preposition left hanging
    nowhere = {"en": " tried it and says it is right", "pt-BR": " experimentou e diz que"}
    assert nowhere[language] in said[3], said[3]
    assert "Ana Souza" in said[4]


def test_the_requesters_yes_is_a_known_event_told_by_the_settling_stage():
    """Through the card's door since #448 slice 6: the settling stage hands `accepted` at the last
    gate to it, and the door's port tells the room."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    assert events.TRIED in events.KINDS
    assert events.PRODUCERS[events.TRIED] == "openfactory/lifecycle/ports.py::tell"
    source = (root / "openfactory/product/engine.py").read_text()
    start = source.index("def _the_requesters_yes(")
    assert "CardEvent.ACCEPTED" in source[start:source.index("\ndef ", start)]
    ports = (root / "openfactory/lifecycle/ports.py").read_text()
    start = ports.index("    def tell(")
    assert "events.tried_it_right(" in ports[start:ports.index("\n    def ", start + 10)]


def test_the_flag_is_the_operators_and_off_by_default():
    from openfactory.contracts.project import Project

    assert Project(name="a", repo_path=".").release_by_requester is False
    assert Project(name="a", repo_path=".", release_by_requester=True).release_by_requester


# ── 4. the round asks once, and only what landed ─────────────────────────────────────────────────

@pytest.mark.parametrize("still_open", [ROOM, THEIRS])
def test_the_round_asks_nothing_again_while_either_copy_is_open(project, told, engine,
                                                                 still_open):
    _asked_in_their_conversation()
    engine.parks(CARD, run="run-1")
    _round(project, engine)
    told.said.clear()

    assert _round(project, engine) == "release-asked:0"
    assert told.said == [] and len(_releases()) == 2

    gone = [x for x in _releases() if x.about != still_open]
    loop_store.write(ROOM, close_by_observation(
        loop_store.read(ROOM), {(ACCEPTANCE, x.subject, x.about): "worked" for x in gone}))
    assert [x.about for x in _releases()] == [still_open]

    assert _round(project, engine) == "release-asked:0", f"asked again with {still_open} open"
    assert told.said == []


def test_a_room_post_that_did_not_land_opens_nothing_and_tells_nobody(project, told, engine):
    _asked_in_their_conversation()
    engine.parks(CARD, run="run-1")
    told.refuse = {ROOM}

    assert _round(project, engine) == "release-asked:0"

    assert told.said == [] and _releases() == []


def test_a_telling_the_door_did_not_take_opens_no_copy_of_theirs(project, told, engine):
    _asked_in_their_conversation()
    engine.parks(CARD, run="run-1")
    told.refuse = {THEIRS}

    _round(project, engine)

    [loop] = _releases()
    assert loop.about == ROOM and "conversation" not in loop.context


# ── 5. in their words, and wired ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["en", "pt-BR"])
@pytest.mark.parametrize("where", [URL, ""])
def test_what_the_requester_reads_has_no_pipeline_vocabulary(language, where):
    said = voice.staged_for_you(ref=CARD, title=TITLE, where=where, language=language,
                                agent_name=AGENT)
    prose = said.replace(URL, "«the address»").lower()

    assert not voice.jargon_in(prose), voice.jargon_in(prose)
    for word in ("staging", "deploy", "release", "produção", "production", "pipeline"):
        assert word not in prose, f"{word!r} reached the requester: {said}"
    assert (URL in said) == bool(where), "the address was dropped, or one was implied"
    assert said.startswith(f"{AGENT}: ")


def test_the_words_are_in_the_projects_language():
    pt = voice.staged_for_you(ref=CARD, where=URL, language="pt-BR")
    en = voice.staged_for_you(ref=CARD, where=URL, language="en")

    assert pt.startswith("O #500: a mudança que você pediu está pronta para você experimentar")
    assert en.startswith("#500: the change you asked for is ready for you to try")
    assert "não tenho o endereço" in voice.staged_for_you(ref=CARD, language="pt-BR")


def test_the_event_is_a_known_kind_told_by_the_hourly_round():
    """Through the card's door since #448 slice 6: the round hands each asking to it as `staged`,
    and the door's port tells the requester."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    assert events.STAGED in events.KINDS
    assert events.PRODUCERS[events.STAGED] == "openfactory/lifecycle/ports.py::tell"
    source = (root / "openfactory/runtime/temporal/activities.py").read_text()
    start = source.index("async def _offer_the_release_to_the_client(")
    assert "CardEvent.STAGED" in source[start:source.index("\ndef ", start)]
    ports = (root / "openfactory/lifecycle/ports.py").read_text()
    start = ports.index("    def tell(")
    assert "events.to_try_at_the_stage(" in ports[start:ports.index("\n    def ", start + 10)]
