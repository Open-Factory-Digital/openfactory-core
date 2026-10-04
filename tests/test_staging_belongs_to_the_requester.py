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

WHAT IS NOT DECIDED HERE, AND IS PINNED AS IT STANDS: who may put it in front of everyone. The
requester's own "it works" still reaches the gate that lists the product's admins (`may_act`), and
is refused there like anybody's; that is the who-may decision of #448 slice 4, pending.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from temporalio.testing import ActivityEnvironment

from openfactory.memory import store as loop_store
from openfactory.memory.ledger import ACCEPTANCE, CLOSED, DELIVERY, close_by_observation, open_loop
from openfactory.memory.ledger import waiting as open_loops
from openfactory.product import accept, agenda, events, followup, voice
from openfactory.product.conversation import owner_of
from openfactory.product.speaker import sealed

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
    return ProjectRegistry().get(ROOM)


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


@pytest.fixture
def released(monkeypatch) -> list:
    """Every release the gate let through — the act, not its sentence."""
    calls: list = []

    def _release(project, issue, *, approver, comment=""):
        calls.append((str(issue), approver))
        return True, ""

    monkeypatch.setattr("openfactory.product.release.release", _release)
    return calls


def _asked_in_their_conversation(where: str = THEIRS) -> None:
    """The card's delivery, as the work was filed from the requester's conversation."""
    loop_store.write(ROOM, [open_loop(DELIVERY, "7", owner=followup.OWNER, ts=T0,
                                      context={"issues": CARD,
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


def test_the_requesters_yes_is_refused_by_the_admin_gate_as_it_stands(project, told, engine,
                                                                     released):
    """PENDING THE WHO-MAY DECISION OF #448 SLICE 4. The requester's "funcionou" reaches the release
    gate — it is no longer lost in a conversation nobody asked in — and the gate still lists only
    the product's admins (`may_act`), so it is refused and both copies stay open for somebody who
    may answer. When the product owner decides who may put a change in front of everyone, this is
    the test that changes."""
    from openfactory.product.module import unauthorized_message

    _asked_in_their_conversation()
    engine.parks(CARD, run="run-1")
    _round(project, engine)

    settled = _answer(project, "funcionou", who=ASKER, where=THEIRS)

    assert settled.reply == unauthorized_message(project)
    assert released == []
    assert len(_releases()) == 2


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
    from pathlib import Path

    assert events.STAGED in events.KINDS
    assert events.PRODUCERS[events.STAGED] == (
        "openfactory/runtime/temporal/activities.py::_offer_the_release_to_the_client")
    source = (Path(__file__).resolve().parent.parent
              / "openfactory/runtime/temporal/activities.py").read_text()
    start = source.index("async def _offer_the_release_to_the_client(")
    assert "events.staged_for_you," in source[start:source.index("\ndef ", start)]
