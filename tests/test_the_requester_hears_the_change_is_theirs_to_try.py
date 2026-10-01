"""The product role tells the person who asked for a card that its change is now theirs to try
(#401) — and the agenda that lists what it owes them speaks their language.

MEASURED LIVE (2026-09-29, local board, a hosted forge, `merge_policy: human`, previews on). A
person reported a defect in a private conversation; the role filed it and answered "quando o
conserto sair, eu aviso aqui". The factory opened a pull request, the review approved it with flags,
the card went to Needs Action with the factory's comment on it and a "start a preview" button in
its drawer — and the role said NOTHING in the person's conversation. The person who had to try it
and decide the merge found out by opening the board. On the same screen the Agenda listed "tell you
when the problem reported is fixed · owed · you" in English, in a pt-BR product, under a tab
nothing explained.

WHAT IS PINNED HERE:

  - the event is told ONCE, when a pull request a person must decide enters the merge watch, to
    the conversation the card's requester asked in, with the card, its link, the change's link, the
    review in one line and what to do now;
  - it is not told for a card nobody asked for in a conversation;
  - a repeated poll — the tech-lead's round, a retried activity, a resumed merge — does not repeat
    it, and the round tells a gate the watch never did;
  - the watch calls it for a human-gated pull request only, behind its patch marker;
  - a preview that is already up is carried in the message (the seam for the auto-started one);
  - the agenda's lines, chip, date, empty message and the sentence saying what the tab is come in
    the project's language.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import Worker

from openfactory.contracts import JobState, RunResult
from openfactory.contracts.checks import CiDecision
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.contracts.review import ReviewResult
from openfactory.memory import store as loop_store
from openfactory.memory.ledger import DELIVERY, QUESTION, open_loop
from openfactory.product import agenda, events, followup, voice
from openfactory.review.verdict import headline
from openfactory.runtime.temporal import activities as acts
from openfactory.runtime.temporal.io import (
    JobParams,
    MergeCheckInput,
    ReadyForYouInput,
    RunJobInput,
)
from openfactory.runtime.temporal.workflow import JobWorkflow

ROOT = Path(__file__).resolve().parent.parent
LANG, AGENT, ROOM = "pt-BR", "Nina", "books"
#: The person who asked — an id no sentence of the role's could contain by accident.
ANA = "ana-requester-77"
ANAS = f"person:{ANA}"
PR = "https://forge.example/acme/books/pullrequest/12"
CARD_URL = "http://panel.example/p/books/card/500"
T0 = "2026-09-29T10:00:00+00:00"
#: A reviewer that approved and left a point for a person — what the live card carried.
FLAGGED = {"decision": "approved_with_findings", "score": 80,
           "findings": [{"severity": "high", "description": "the empty state is not covered",
                         "file": ""}]}


def _project(tmp_path, language: str = LANG) -> Project:
    return Project(name=ROOM, repo_path=str(tmp_path / "work" / ROOM), language=language,
                   product=ProductConfig(docs_repo="acme/books-docs", admins=[ANA],
                                         agent_name=AGENT))


def _defect(card: str = "500", *, where: str = ANAS):
    """The delivery loop `module._track_defect` opens when a person reports a problem."""
    return open_loop(DELIVERY, f"defeito-{card}", owner="product", ts=T0,
                     context={"issues": card, "defect": "1",
                              **followup.delivered_to(where, ANA)})


@pytest.fixture
def registry(monkeypatch, tmp_path) -> Project:
    from openfactory.registry import ProjectRegistry

    path = tmp_path / "registry.yaml"
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(path))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    project = _project(tmp_path)
    ProjectRegistry(path).add(project)
    return project


@pytest.fixture
def ledger(monkeypatch) -> SimpleNamespace:
    book = SimpleNamespace(rows=[])
    monkeypatch.setattr(loop_store, "read", lambda project, **_k: list(book.rows))
    monkeypatch.setattr(loop_store, "write",
                        lambda project, loops, **_k: book.rows.extend(loops) or len(loops))
    return book


@pytest.fixture
def told(registry, ledger, monkeypatch) -> list[dict]:
    """What reached the door — the real `_once` and its record in between."""
    said: list[dict] = []
    monkeypatch.setattr(events, "_tell", lambda project, **kw: said.append(kw) or True)
    monkeypatch.setattr(events, "_title_of", lambda project, card: "Relatório mensal")
    monkeypatch.setattr(events, "_card_url", lambda project, card: CARD_URL)
    monkeypatch.setattr(events, "_preview_offered", lambda project, card: True)
    return said


# ── 1. said once, where it was asked, with what a person can act on ────────────────────────────

def test_a_change_a_person_must_decide_is_told_ONCE_in_the_requesters_conversation(
        registry, ledger, told):
    ledger.rows = [_defect()]

    assert events.ready_for_you(registry, card="500", pr_url=PR, verdict=FLAGGED)

    assert [t["conversation"] for t in told] == [ANAS]
    text = told[0]["text"]
    assert text == voice.ready_for_you(ref="500", title="Relatório mensal", card_url=CARD_URL,
                                       review="flagged", preview=True,
                                       language=LANG, agent_name=AGENT)
    for part in ("o #500 (Relatório mensal) está pronto para você conferir",
                 "a revisão automática aprovou, com pontos para uma pessoa conferir",
                 f"O cartão: {CARD_URL}", "inicie a prévia",
                 "é a sua aprovação no cartão que coloca no produto", "peça um ajuste"):
        assert part in text, f"{part!r} is not in what the requester read:\n{text}"
    assert PR not in text, "the requester is sent to the pull request, not to the card"


def test_a_repeated_poll_a_retry_or_a_resumed_merge_does_NOT_say_it_again(registry, ledger,
                                                                         told):
    ledger.rows = [_defect()]
    assert events.ready_for_you(registry, card="500", pr_url=PR, verdict=FLAGGED)
    assert not events.ready_for_you(registry, card="500", pr_url=PR, verdict=FLAGGED)
    assert events.ready_at_the_gate(registry, [("500", PR)]) == []
    assert events.ready_at_the_gate(registry, [("500", PR)]) == []
    assert len(told) == 1, told


def test_a_NEW_pull_request_on_the_same_card_is_a_new_thing_to_try(registry, ledger, told):
    ledger.rows = [_defect()]
    assert events.ready_for_you(registry, card="500", pr_url=PR)
    assert events.ready_for_you(registry, card="500", pr_url=PR + "-2")
    assert len(told) == 2


def test_a_card_NOBODY_asked_for_in_a_conversation_is_not_announced(registry, ledger, told):
    """No delivery loop, or one with no conversation recorded: nothing is said — not even to the
    room, which already has the card's own comment — and nothing is recorded, so a later filing
    from a conversation is still told."""
    assert not events.ready_for_you(registry, card="777", pr_url=PR, verdict=FLAGGED)
    ledger.rows = [_defect("778", where="")]
    assert not events.ready_for_you(registry, card="778", pr_url=PR, verdict=FLAGGED)
    assert events.ready_at_the_gate(registry, [("777", PR), ("778", PR)]) == []
    assert told == []

    ledger.rows.append(_defect("777"))
    assert events.ready_for_you(registry, card="777", pr_url=PR)


def test_the_round_tells_a_gate_the_watch_never_did_and_the_watch_then_finds_it_told(
        registry, ledger, told):
    """A job whose history predates the watch's call, or a merge handed to a person later: the
    round sees the gate and not the verdict, so it says nothing about the review."""
    ledger.rows = [_defect()]
    assert events.ready_at_the_gate(registry, [("500", PR)]) == ["500"]
    assert not events.ready_for_you(registry, card="500", pr_url=PR, verdict=FLAGGED)
    assert len(told) == 1 and "revisão" not in told[0]["text"], told


def test_the_round_hands_its_merge_gates_to_the_event_before_the_two_day_reminder():
    source = (ROOT / "openfactory/runtime/temporal/activities.py").read_text()
    helper = source[source.index("def _pull_requests_waiting("):]
    helper = helper[:helper.index("\n@activity.defn")]
    assert "events.ready_at_the_gate(project, gates)" in helper
    assert helper.index("ready_at_the_gate") < helper.index("pull_requests_at_the_gate(")


def test_a_preview_already_up_is_IN_the_message_instead_of_start_the_preview(registry, ledger,
                                                                             told):
    """The seam for a preview that starts itself when the pull request opens."""
    ledger.rows = [_defect()]
    live = "https://web--books--500.preview.example/"
    assert events.ready_for_you(registry, card="500", pr_url=PR, preview_url=live)
    text = told[0]["text"]
    assert "https://web--books--500.preview.example" in text and "inicie a prévia" not in text


def test_with_no_preview_on_offer_it_never_sends_them_to_a_button_that_is_not_there(
        registry, ledger, told, monkeypatch):
    monkeypatch.setattr(events, "_preview_offered", lambda project, card: False)
    ledger.rows = [_defect()]
    assert events.ready_for_you(registry, card="500", pr_url=PR)
    assert "prévia" not in told[0]["text"] and "abra o cartão e confira" in told[0]["text"]


def test_a_project_with_NO_product_role_is_told_nothing(tmp_path, ledger, monkeypatch):
    said: list = []
    monkeypatch.setattr(events, "_tell", lambda project, **kw: said.append(kw) or True)
    ledger.rows = [_defect()]
    bare = Project(name="floor-only", repo_path=str(tmp_path / "w" / "f"))
    assert not events.ready_for_you(bare, card="500", pr_url=PR)
    assert said == []


# ── 2. the sentence ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["pt-BR", "en"])
@pytest.mark.parametrize("stance", ["approved", "flagged", "rejected", "unread",
                                    "not_verified", ""])
def test_the_sentence_is_in_the_clients_words_and_names_nobody(language, stance):
    for preview, live in ((True, ""), (False, ""), (False, "https://p.example")):
        text = voice.ready_for_you(ref="500", title="Relatório", card_url=CARD_URL,
                                   review=stance, preview=preview,
                                   preview_url=live, language=language, agent_name=AGENT)
        assert voice.jargon_in(text) == [], text
        assert ANA not in text
    pt = voice.ready_for_you(ref="500", review=stance, language="pt-BR")
    en = voice.ready_for_you(ref="500", review=stance, language="en")
    assert pt != en


def test_the_review_line_is_the_verdicts_own_word_never_re_read():
    """`headline` says the stance once; the sentence is chosen by it."""
    assert headline(FLAGGED)["stance"] == "flagged"
    assert headline({"decision": "rejected", "score": 20})["stance"] == "rejected"
    assert headline({"decision": "approved", "score": 95})["stance"] == "approved"
    assert headline({})["stance"] == "unread"
    assert headline({"decision": "approved", "stale": "a repair rewrote it"})["stance"] == "unread"
    assert headline({"decision": "approved", "evidence_checked": True,
                     "acceptance": [{"criterion": "c", "status": "passed"}]})["stance"] == (
        "not_verified"), "approved over evidence nothing executed is not an approval (#447)"
    assert set(voice._READY_REVIEW) == {"approved", "flagged", "rejected", "unread",
                                        "not_verified"}
    assert events._stance(None) == "", "an unknown verdict must say nothing, not 'no review'"


def test_no_link_is_written_into_the_tables():
    for table in (voice._READY_HEAD, voice._READY_CARD_LINK,
                  voice._READY_TRY_LIVE, voice._READY_TRY_PREVIEW, voice._READY_TRY_CARD,
                  voice._READY_NEXT, *voice._READY_REVIEW.values()):
        for sentence in table.values():
            assert "http" not in sentence, sentence


# ── 3. the watch tells it, once, for a human gate only ──────────────────────────────────────────

def test_the_watch_tells_the_requester_behind_its_patch_and_only_for_a_person_s_merge():
    src = inspect.getsource(JobWorkflow._watch_to_merge)
    marker = 'workflow.patched("the-requester-hears-it-is-theirs")'
    assert f"if not result.auto_merge and {marker}:" in src, (
        "an armed auto-merge must be ruled out BEFORE the marker, or every such job records one")
    assert src.index(marker) < src.index("self._tell_the_requester(") < src.index(
        "self._ci_merge_loop(")


async def test_the_activity_is_registered_and_reaches_the_event(registry, monkeypatch):
    from openfactory.runtime.temporal.worker import WORKER_ACTIVITIES

    assert acts.tell_the_requester in WORKER_ACTIVITIES
    heard: list = []
    monkeypatch.setattr(events, "ready_for_you",
                        lambda project, **kw: heard.append((project.name, kw)) or True)
    assert await ActivityEnvironment().run(
        acts.tell_the_requester,
        ReadyForYouInput(project=ROOM, issue="500", pr_url=PR, verdict=FLAGGED))
    # the live preview's link travels too since #405 met #401 — none is up here
    assert heard == [(ROOM, {"card": "500", "pr_url": PR, "verdict": FLAGGED,
                             "preview_url": ""})]
    assert events.PRODUCERS[events.READY_FOR_YOU].endswith("::tell_the_requester")


_TOLD: list[ReadyForYouInput] = []
_AUTO = [False]


@activity.defn(name="run_job")
async def _opens_a_pull_request(inp: RunJobInput) -> RunResult:
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url=PR,
                     branch="openfactory/500", auto_merge=_AUTO[0],
                     review=ReviewResult(decision="approved", score=90))


@activity.defn(name="tell_the_requester")
async def _tell(inp: ReadyForYouInput) -> bool:
    _TOLD.append(inp)
    return True


@activity.defn(name="check_pr_status")
async def _still_open(inp: MergeCheckInput) -> str:
    return "open"


@activity.defn(name="pr_mergeable_state")
async def _blocked(inp: MergeCheckInput) -> str:
    return "blocked"


@activity.defn(name="read_ci_checks")
async def _pending(inp: MergeCheckInput) -> CiDecision:
    return CiDecision(verdict="pending")


@activity.defn(name="fetch_ticket_title")
async def _title(inp) -> str:
    return "a ticket"


@activity.defn(name="refresh_knowledge")
async def _refresh(inp) -> str:
    return "published"


@activity.defn(name="notify_coordinator_say")
async def _say(inp) -> None:
    return None


_MOCKS = [_opens_a_pull_request, _tell, _still_open, _blocked, _pending, _title, _refresh, _say]


@pytest.fixture
async def env():
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


async def _run_to_the_gate(env, *, auto: bool) -> list[ReadyForYouInput]:
    _TOLD.clear()
    _AUTO[0] = auto
    async with Worker(env.client, task_queue="test-ready-for-you", workflows=[JobWorkflow],
                      activities=_MOCKS):
        h = await env.client.start_workflow(
            JobWorkflow.run,
            JobParams(project="p", issue="500", promote=False, merge_deadline_days=3650),
            id=f"wf-{uuid.uuid4()}", task_queue="test-ready-for-you")
        for _ in range(60):
            if await h.query(JobWorkflow.awaiting_merge):
                break
            await env.sleep(timedelta(seconds=1))
        # several polls of the watch go by: the telling is at the entry, never per poll
        for _ in range(5):
            await env.sleep(timedelta(minutes=2))
        await h.terminate("the test has what it came for")
    return list(_TOLD)


@pytest.mark.owns_its_engine
async def test_the_job_tells_the_requester_ONCE_when_its_pull_request_waits_on_a_person(env):
    told = await _run_to_the_gate(env, auto=False)
    assert [(t.issue, t.pr_url) for t in told] == [("500", PR)], told
    assert told[0].verdict and told[0].verdict["decision"] == "approved"


@pytest.mark.owns_its_engine
async def test_an_armed_auto_merge_tells_nobody_it_is_theirs(env):
    assert await _run_to_the_gate(env, auto=True) == []


# ── 4. the agenda, in the person's language ─────────────────────────────────────────────────────

def _items(language: str | None):
    rows = [_defect(),
            open_loop(DELIVERY, "7", owner="product", ts=T0,
                      context={"issues": "501", **followup.delivered_to(ANAS, ANA)}),
            open_loop(QUESTION, "42", owner="product", about="no-criteria", ts=T0,
                      context={"asked": "o que precisa ser verdade?"})]
    return agenda.items(rows, agenda.Viewer(own=ANAS, person=ANA), room=ROOM, language=language)


def test_the_agenda_speaks_the_projects_language():
    pt = {i.subject: i for i in _items("pt-BR")}
    assert pt["defeito-500"].said == "avisar você quando o problema reportado estiver corrigido"
    assert pt["defeito-500"].chip == "devo a você"
    assert pt["defeito-500"].when == "desde 2026-09-29"
    assert pt["7"].said == "avisar você quando o requisito 7 estiver pronto"
    assert pt["42"].said == "uma resposta sobre o #42" and pt["42"].chip == "espero da sala"
    assert agenda.render([], language="pt-BR") == voice.agenda_empty("pt-BR")
    assert "desde 2026-09-29" in agenda.render(list(pt.values()), language="pt-BR")

    en = {i.subject: i for i in _items("en")}
    assert en["defeito-500"].said == "tell you when the problem reported is fixed"
    assert en["defeito-500"].chip == "owed to you"
    for item in pt.values():
        assert "tell " not in item.said and "owed" not in item.chip and "since" not in item.when


def test_the_agenda_on_the_panel_says_what_it_is_in_the_projects_language(
        monkeypatch, registry, ledger):
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", f"tok-ana:{ANA}:Ana")
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)
    monkeypatch.delenv("OPENFACTORY_PRODUCT_TOKENS", raising=False)
    ledger.rows = [_defect()]
    from fastapi.testclient import TestClient

    from openfactory.api import app as api

    r = TestClient(api.app).post("/api/act/product_agenda", json={"params": {"project": ROOM}},
                                 headers={"authorization": "Bearer tok-ana"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["items"][0]["said"] == "avisar você quando o problema reportado estiver corrigido"
    assert data["items"][0]["chip"] == "devo a você"
    assert data["about"] == voice.agenda_about(agent_name=AGENT, language=LANG)
    assert data["about"].startswith(f"O que {AGENT} deve a você")
    assert data["empty"] == voice.agenda_empty(LANG)


def test_the_panel_draws_the_servers_words_for_the_agenda():
    page = (ROOT / "openfactory/api/panel.html").read_text()
    code = page[page.index("function loadAgenda("):page.index("function paintAgenda(")]
    paint = page[page.index("function paintAgenda("):]
    paint = paint[:paint.index("\n}\n")]
    assert "out.data.about" in code and "out.data.empty" in code
    assert "i.chip" in paint and "i.when" in paint and "_prod.agendaEmpty" in paint
    assert 'id="prodAgendaAbout"' in page and "_prod.agendaAbout" in paint
