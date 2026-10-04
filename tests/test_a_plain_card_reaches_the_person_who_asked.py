"""A card the product role opens as a plain card reaches the person who asked for it (#481).

EVERY EVENT ABOUT A CARD FINDS ITS REQUESTER THROUGH THE CARD'S OPEN DELIVERY LOOP
(`events.requester_conversation`), and a delivery loop was opened in two places only: a reported
defect (`file_defect` → `_track_defect`) and a requirement's cards (`_open_delivery`). A card asked
for with `[[TICKET]]` and filed by `file_ticket` opened none, so the conversation that asked for it
heard nothing: not that the change was theirs to try (#401), not that it shipped, not that it was
withdrawn. The card recorded who asked, and the staged entry where; neither reached a loop.

MEASURED ON `main` (7fa72bc) WITH THIS FILE: 10 of its 11 cases fail. The card is filed and placed
in Backlog, the ledger holds no delivery loop for it, `events.ready_for_you` returns False with
nothing told, and the delivered card is announced to nobody. The one that passes is the card filed
with no conversation, which opens nothing on either side.

AND WHAT THE LOOP LEADS TO SAYS "CARD". Every sentence a delivery loop reaches was written for a
requirement or a defect: opened as a defect's is, the card would have been announced as "o que foi
pedido no requisito cartao-12", and the agenda, the acceptance, the release question and the
acceptance judge would have read the same handle as a requirement. Section 2 pins each.

WHAT IS DRIVEN HERE IS THE CONVERSATION OVER THE LOCAL BOARD AND THE REAL LEDGER: the chat turn
stages the card the role heard asked for and a "sim" files it through the real pen
(`ProductModule.file_ticket`) onto the local row; the events read the ledger written on the
deployment's SQLite store. The role's judgement in the conversation is stood in (it hears the
`[[TICKET]]` marker through the role's own pattern), and the door is the one seam faked: what
reached it is recorded.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

import openfactory.product.channel as pc
from openfactory.memory import store as loop_store
from openfactory.memory.ledger import ACCEPTANCE, DELIVERY, waiting
from openfactory.product import agenda, events, followup, voice
from openfactory.product.role import _TICKET_RE, ProductAnswer
from tests.the_chat_turn import chat_turn

LANG, AGENT, ROOM = "pt-BR", "Nina", "acme"
#: The person who asks — an admin, so her own yes files the card.
ANA = "ana-requester-77"
ANAS = f"person:{ANA}"
PR = "https://forge.example/acme/acme/pull/3"
SAID = "Certo, abro um cartão para isso.\n[[TICKET: Exportar o relatório mensal em CSV]]"
TITLE = "Exportar o relatório mensal em CSV"


@pytest.fixture(autouse=True)
def _clean():
    pc._PENDING.clear()
    yield
    pc._PENDING.clear()


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A registered project on the local row, its board created, and its memory on SQLite."""
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    registry = ProjectRegistry()
    registry.add(Project(name=ROOM, repo_path=str(tmp_path), language=LANG,
                         tracker=ProviderRef(kind="local", repo=ROOM, options={}),
                         product=ProductConfig(docs_repo="acme/acme-docs", admins=[ANA],
                                               agent_name=AGENT)))
    found = registry.get(ROOM)
    LocalBoardSetup().create(project=found, owner="", title=ROOM, token=None)
    return found


@pytest.fixture
def told(project, monkeypatch) -> list[dict]:
    """What reached the door — `_once` and its record of what was told run as they are."""
    said: list[dict] = []
    monkeypatch.setattr(events, "_tell", lambda project, **kw: said.append(kw) or True)
    monkeypatch.setattr(events, "_preview_offered", lambda project, card: False)
    return said


def _pen(project, tmp_path):
    """The product role's real pen, over the project's own tracker and board."""
    from openfactory.product.config import ProductLink
    from openfactory.product.loader import ProductContext
    from openfactory.product.module import ProductModule
    from tests.test_card_maintenance import COMMIT, REQUIREMENTS_DIR, _corpus, _Harness

    ctx = ProductContext(link=ProductLink(active=True, docs_repo="acme/acme-docs", kind="ok",
                                          reason="fine"),
                         corpus=_corpus(), docs_path=str(tmp_path), docs_commit=COMMIT,
                         requirements_dir=REQUIREMENTS_DIR)
    return ProductModule(project, context=ctx, agent=_Harness("{}"))


class _Conversation:
    """The role in the conversation: it hears a card asked for — the `[[TICKET]]` marker, read by
    the role's own pattern — and drafts none (the card is staged as said). The pen is the real
    one."""

    def __init__(self, pen) -> None:
        self.file_ticket = pen.file_ticket

    def settle_acceptance(self, text, **_):
        return None

    def close_decisions_answered(self, **_):
        return 0

    def confirmed(self, reply, *, proposal):
        return "neither"

    def context(self):
        return SimpleNamespace(available=True, reason="")

    def answer(self, question, **_):
        marker = _TICKET_RE.search(SAID)
        return ProductAnswer(ok=True, text=_TICKET_RE.sub("", SAID).strip(), is_ticket=True,
                             ticket_title=(marker.group("title") or "").strip())


def _asked_and_filed(project, tmp_path) -> str:
    """Ana asks for the card in her conversation and says yes: the card's ref."""
    talk = _Conversation(_pen(project, tmp_path))
    staged = chat_turn(project, text="abre um cartão para exportar o relatório mensal em CSV",
                       user=ANA, thread=ANAS, module=talk)
    assert staged and TITLE in str(staged), staged
    filed = chat_turn(project, text="sim", user=ANA, thread=ANAS, module=talk)
    from openfactory.adapters.tracker.registry import build_tracker

    ref = build_tracker(project).find_ticket(title=TITLE)
    assert ref and str(ref).lstrip("#") in str(filed), filed
    return str(ref).lstrip("#")


def _deliveries(project) -> list:
    return [x for x in waiting(loop_store.read(project.name)) if x.kind == DELIVERY]


# ── 1. the scenario: asked in a conversation, offered, delivered ────────────────────────────────

def test_a_card_asked_for_in_a_conversation_is_offered_and_delivered_THERE(project, tmp_path,
                                                                          told):
    card = _asked_and_filed(project, tmp_path)

    # filed where the role files every card, with the conversation that asked for it on its loop
    from openfactory.adapters.board import build_board

    assert build_board(project).items_in_status("Backlog") == [card]
    assert events.requester_conversation(project, card) == ANAS

    # its pull request waits on a person: the requester hears it is theirs to try, where she asked
    assert events.ready_for_you(project, card=card, pr_url=PR)
    assert [t["conversation"] for t in told] == [ANAS]
    assert f"#{card} ({TITLE})" in told[0]["text"], told[0]["text"]

    # it is delivered — closed as finished work through its door, whose `Loops("deliver")` is the
    # one announcer (#414): she hears it is in the product, where she asked, and is asked if it
    # works
    from openfactory.lifecycle import CardEvent, transition
    from openfactory.memory.ledger import fold

    moved = transition(project, card, CardEvent.CLOSED, by=ANA,
                       facts={"delivered": True, "note": "shipped in !3"})
    assert moved.outcome("loops") == "1 announced", moved.effects
    written = fold(loop_store.read(project.name))

    assert [t["conversation"] for t in told] == [ANAS, ANAS]
    [delivery] = [x for x in written if x.kind == DELIVERY]
    assert told[1]["text"] == (
        followup.delivered_text(delivery, agent_name=AGENT, language=LANG)
        + followup.acceptance_question(delivery, agent_name=AGENT, language=LANG))
    assert f"o #{card} ({TITLE}) já entrou no produto" in told[1]["text"], told[1]["text"]
    assert "requisito" not in told[1]["text"], "a card nobody argued into a requirement"
    assert _deliveries(project) == [], "the delivery is closed once it is told"
    [asked] = [x for x in written if x.kind == ACCEPTANCE]
    assert asked.context["conversation"] == ANAS and asked.context.get("ticket")


def test_the_loop_records_where_it_was_asked_and_a_digest_of_who(project, tmp_path, told):
    from openfactory.product.speaker import sealed

    card = _asked_and_filed(project, tmp_path)

    [loop] = _deliveries(project)
    assert loop.context == {"issues": card, "ticket": "1", "title": TITLE,
                            "conversation": ANAS, "requester": sealed(ANA)}
    assert ANA not in repr(loop.context).replace(ANAS, "")


def test_a_card_filed_with_NO_conversation_opens_nothing_as_before(project, tmp_path, told):
    """The panel's and the API's row (`product_file_ticket`) name no conversation: nothing is
    owed to anybody, and nothing is said."""
    result = _pen(project, tmp_path).file_ticket(title=TITLE, described="o relatório",
                                                 reported_by=ANA)

    assert result.ok and result.ref
    assert _deliveries(project) == []
    assert not events.ready_for_you(project, card=result.ref.lstrip("#"), pr_url=PR)
    assert told == []


def test_the_same_card_is_followed_ONCE(project, tmp_path):
    """Deduplicated as a defect's is: an open loop on the card is not opened again — the promise
    the card's filing carries, opened by its door (#414), applied twice and spelled both ways."""
    from openfactory.lifecycle import loops

    pen = _pen(project, tmp_path)

    loops.owe(project, "12", pen._track_ticket("12", title=TITLE, conversation=ANAS,
                                               requester=ANA))
    loops.owe(project, "12", pen._track_ticket("#12", title=TITLE, conversation=ANAS,
                                               requester=ANA))

    assert [x.subject for x in _deliveries(project)] == ["cartao-12"]


# ── 2. what the loop drags along says "card", never "requirement" ──────────────────────────────

def _card_loop(**context):
    return followup.open_loop(DELIVERY, "cartao-12", owner=followup.OWNER,
                              ts="2026-10-02T10:00:00+00:00",
                              context={"issues": "12", "ticket": "1", "title": TITLE,
                                       **followup.delivered_to(ANAS, ANA), **context})


@pytest.mark.parametrize("language", ["pt-BR", "en"])
def test_the_delivery_names_the_card_and_never_a_requirement(language):
    said = followup.delivered_text(_card_loop(), agent_name=AGENT, language=language)

    assert "#12 (" + TITLE + ")" in said
    assert "cartao-12" not in said
    assert "requisito" not in said and "requirement" not in said
    assert said != followup.delivered_text(_card_loop(ticket=""), language=language)


def test_the_agenda_says_what_is_owed_and_awaited_about_a_card():
    loop = _card_loop()
    asked = followup.acceptance_of(loop, ts="2026-10-03T10:00:00+00:00")
    asked = replace(asked, context={**asked.context, **followup.delivered_to(ANAS, ANA)})
    viewer = agenda.Viewer(own=ANAS, person=ANA)

    for language, owed, awaited in (
            ("pt-BR", "avisar você quando o cartão pedido entrar no produto",
             "saber de você se o cartão entregue funciona"),
            ("en", "tell you when the card asked for is in the product",
             "hear from you whether the card delivered works")):
        said = {x.kind: x for x in agenda.items([loop, asked], viewer, room=ROOM,
                                                language=language)}
        assert said[DELIVERY].said == owed and said[DELIVERY].what == TITLE
        assert said[ACCEPTANCE].said == awaited and said[ACCEPTANCE].what == TITLE


def test_two_open_acceptances_name_the_card_by_its_title_not_as_a_requirement():
    asked = followup.acceptance_of(_card_loop(), ts="2026-10-03T10:00:00+00:00")

    assert f"({TITLE})" in followup.accepted_text(asked, ambiguous=True)
    assert f"({TITLE})" in followup.rejected_text(asked, ambiguous=True)
    assert "requisito" not in followup.accepted_text(asked, ambiguous=True)


def test_the_release_question_is_not_told_a_card_is_a_requirement():
    """`requirement_behind` reads the open deliveries for the requirement an issue belongs to; a
    card's loop — and a defect's — names none."""
    defect = followup.open_loop(DELIVERY, "defeito-13", owner=followup.OWNER, ts="t",
                                context={"issues": "13", "defect": "1"})
    requirement = followup.open_loop(DELIVERY, "7", owner=followup.OWNER, ts="t",
                                     context={"issues": "14"})
    loops = [_card_loop(), defect, requirement]

    assert followup.requirement_behind("12", loops) == ""
    assert followup.requirement_behind("13", loops) == ""
    assert followup.requirement_behind("14", loops) == "7"
    assert "requisito" not in followup.release_question(
        requirement=followup.requirement_behind("12", loops), where="https://x", language=LANG)


def test_the_judge_is_told_a_card_was_delivered(project, tmp_path, monkeypatch):
    """What the acceptance judge reads as "what they were told was delivered"."""
    from openfactory.product import module as product_module

    pen = _pen(project, tmp_path)
    asked = followup.acceptance_of(_card_loop(), ts="2026-10-03T10:00:00+00:00")
    heard: list[str] = []
    monkeypatch.setattr(product_module, "_acceptances_here", lambda *_a, **_k: [asked])
    monkeypatch.setattr(pen, "_workspace", lambda: (None, None))
    monkeypatch.setattr(pen, "_role", lambda **_k: SimpleNamespace(
        judge_acceptance=lambda **kw: heard.append(kw["delivered"]) or "worked"))

    assert pen._judge_acceptance("funcionou", conversation=ANAS) == "worked"
    assert heard == [f"the card they asked for: {TITLE}"]


def test_the_voice_names_a_card_as_the_other_events_do():
    """The card in the delivery is spelled by the one helper every card event uses."""
    assert voice._card("12", TITLE, LANG) in followup.delivered_text(_card_loop(), language=LANG)
