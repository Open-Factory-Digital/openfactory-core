"""The product role knows what day it is, and when each line before it was said.

Observed by the product owner on the local bed: after five days without writing, the role
answered "como combinamos ontem". Its prompt carried the conversation as `who: text` lines with no
time on any of them and said nowhere what day it was — five days of silence read as one sitting.
`product/clock.py` closes it with two facts, and these tests hold them where the model reads them:

  1. every line of the conversation says when it was said;
  2. the turn says what day it is and how long ago the previous message was, in calendar days
     counted here — never left to the model's arithmetic;
  3. both reach the prompt, the time last before the question (it changes every turn), and the
     role's task says relative words are read from them;
  4. the day is the product's people's (`product.timezone`), and UTC is said as UTC.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.memory import transcript
from openfactory.product import clock
from tests.test_transcript_memory import store  # noqa: F401 — the fixture, reused
from tests.the_chat_turn import chat_turn

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def _project(timezone: str = "") -> Project:
    return Project(name="books", repo_path="/t", language="pt-BR",
                   tracker=ProviderRef(kind="github", repo="a/b"),
                   forge=ProviderRef(kind="github", repo="a/b"),
                   product=ProductConfig(docs_repo="a/docs", agent_name="Nina",
                                         timezone=timezone))


# ── 1. the clock counts calendar days, in somebody's zone ───────────────────────────────────────

def test_yesterday_is_the_calendar_day_before_whatever_the_hours():
    late = datetime(2026, 9, 20, 23, 50, tzinfo=UTC)
    assert clock.days_between(late, late + timedelta(minutes=20)) == 1
    assert clock.days_between(late - timedelta(hours=10), late) == 0
    assert clock.days_between(late, late + timedelta(days=5)) == 5


def test_the_day_is_counted_in_the_product_s_zone_not_in_utc():
    """22:00 in São Paulo is 01:00 UTC the next day: in UTC the two moments below are a day apart,
    for the people of the product they are one evening."""
    evening = datetime(2026, 9, 21, 0, 30, tzinfo=UTC)     # 21:30 on the 20th in São Paulo
    later = datetime(2026, 9, 21, 1, 30, tzinfo=UTC)       # 22:30 on the 20th in São Paulo
    before = datetime(2026, 9, 20, 23, 0, tzinfo=UTC)      # 20:00 on the 20th in São Paulo
    assert clock.days_between(before, later) == 1
    assert clock.days_between(before, later, SAO_PAULO) == 0
    assert clock.stamp(evening.isoformat(), SAO_PAULO) == "2026-09-20 21:30"


def test_five_days_of_silence_are_said_as_five_days_never_as_yesterday():
    last = datetime(2026, 9, 20, 16, 3, tzinfo=UTC)
    block = clock.now_block(last + timedelta(days=5, hours=2), last_ts=last.isoformat())
    assert block.startswith("## When\n")
    assert "Now: Friday 2026-09-25 18:03 (UTC)." in block
    assert "Sunday 2026-09-20 16:03 — 5 days ago." in block
    assert "yesterday" not in block

    assert "yesterday." in clock.now_block(last + timedelta(days=1), last_ts=last.isoformat())
    assert "earlier today." in clock.now_block(last + timedelta(hours=3), last_ts=last.isoformat())


def test_a_first_message_is_told_nothing_was_said_before_it():
    block = clock.now_block(datetime(2026, 9, 25, 9, 0, tzinfo=UTC))
    assert "opens the conversation" in block
    assert "ago" not in block


def test_a_line_with_no_readable_time_is_printed_without_one():
    assert clock.stamp("") == ""
    assert clock.stamp("not a time") == ""
    # a row written without an offset is UTC's, as every row of the transcript is
    assert clock.stamp("2026-09-20T16:03:00") == "2026-09-20 16:03"


def test_the_zone_is_the_registry_s_and_an_unknown_one_is_utc_said_as_utc(caplog):
    assert clock.zone_of(_project()) == (UTC, "UTC")
    zone, name = clock.zone_of(_project("America/Sao_Paulo"))
    assert name == "America/Sao_Paulo" and str(zone) == "America/Sao_Paulo"
    with caplog.at_level(logging.WARNING):
        assert clock.zone_of(_project("Mars/Olympus_Mons")) == (UTC, "UTC")
    assert "cannot be resolved" in caplog.text


# ── 2. every line of the conversation says when it was said ─────────────────────────────────────

def test_the_renderer_stamps_each_line_only_when_the_caller_asks():
    turns = [transcript.Turn(role="person", text="o fechamento roda sozinho?", actor="Ana",
                             ts="2026-09-20T16:03:00+00:00"),
             transcript.Turn(role="agent", text="ainda não", ts="2026-09-20T16:04:00+00:00")]
    stamped = transcript.render(turns, agent_name="Nina", stamp=clock.stamp)
    assert "[2026-09-20 16:03] Ana: o fechamento roda sozinho?" in stamped
    assert "[2026-09-20 16:04] Nina: ainda não" in stamped
    # the tech-lead's block and the thread row are as they were
    assert "[" not in transcript.render(turns, agent_name="Nina")


def test_the_retrieval_query_still_reads_the_words_of_a_stamped_line():
    from openfactory.product.index.retrieval import _said_before

    block = ("## Conversa até aqui (mais antigo primeiro)\n"
             "[2026-09-20 16:03] Ana: o fechamento contábil roda sozinho?\n"
             "[2026-09-20 16:04] Nina: ainda não")
    assert _said_before(block) == "o fechamento contábil roda sozinho?\nainda não"


# ── 3. both reach the prompt ────────────────────────────────────────────────────────────────────

class _Module:
    def __init__(self):
        self.seen: dict = {}

    def settle_acceptance(self, text):
        return None

    def context(self):
        return SimpleNamespace(available=True, reason="")

    def answer(self, question, *, context="", conversation="", now="", **_):
        self.seen.update(question=question, conversation=conversation, now=now)
        return SimpleNamespace(ok=True, text="retomando de onde paramos", is_defect=False,
                               asked_for_something=False)


def test_a_turn_five_days_after_the_last_hands_the_model_five_days(store, monkeypatch):  # noqa: F811
    import openfactory.product.channel as pc

    monkeypatch.setattr(pc, "_reply_of", lambda answer, **kw: answer.text, raising=False)
    project = _project()
    transcript.record(project.name, thread="T5", role="person",
                      text="o fechamento contábil já roda sozinho?", actor="U1")
    transcript.record(project.name, thread="T5", role="agent", text="ainda não")
    monkeypatch.setattr(clock, "current", lambda: datetime.now(UTC) + timedelta(days=5))

    module = _Module()
    chat_turn(project, text="e aí, andou?", user="U1", thread="T5", module=module)

    now, convo = module.seen.get("now", ""), module.seen.get("conversation", "")
    assert "5 days ago" in now, f"the role was not told how long the silence was: {now!r}"
    assert "(UTC)" in now
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    assert f"[{today} " in convo, f"the conversation's lines carry no time: {convo!r}"
    assert "e aí, andou?" not in convo


def test_a_module_that_predates_the_clock_is_answered_as_before(store, monkeypatch):  # noqa: F811
    import openfactory.product.channel as pc

    monkeypatch.setattr(pc, "_reply_of", lambda answer, **kw: answer.text, raising=False)

    class _Old(_Module):
        def answer(self, question, *, context="", conversation="", pending=""):
            self.seen.update(question=question, conversation=conversation)
            return SimpleNamespace(ok=True, text="ok", is_defect=False, asked_for_something=False)

    module = _Old()
    chat_turn(_project(), text="oi", user="U1", thread="T6", module=module)
    assert module.seen.get("question") == "oi"


def test_the_time_sits_last_before_the_question_and_the_task_says_how_to_read_it():
    from openfactory.product.role import ProductRole

    captured: dict = {}

    class _Role(ProductRole):
        def _prompt(self, instruction, body, **kw):
            captured.update(instruction=instruction, body=body)
            return body

        def _ask(self, *a, **kw):
            return SimpleNamespace(ok=False, raw_output="", summary="")

    when = clock.now_block(datetime(2026, 9, 25, 9, 0, tzinfo=UTC),
                           last_ts="2026-09-20T16:03:00+00:00")
    _Role(agent=None).answer(  # type: ignore[arg-type]
        sandbox=None, workspace=None, question="e agora?",
        conversation="## Conversa até aqui\n[2026-09-20 16:03] pessoa: oi", now=when)

    body = captured["body"]
    assert body.index("Conversa até aqui") < body.index("## When") < body.index("## Question"), \
        f"the time is out of place:\n{body}"
    assert "TIME IS READ, NEVER ASSUMED" in captured["instruction"]
    assert "not yesterday" in captured["instruction"]


@pytest.mark.parametrize("zone", ["America/Sao_Paulo"])
def test_the_registry_takes_a_timezone(zone):
    assert ProductConfig(docs_repo="a/docs", timezone=zone).timezone == zone
    assert ProductConfig(docs_repo="a/docs").timezone == ""


def test_the_module_hands_the_time_to_the_role(monkeypatch):
    """The engine tells the module, and the module is the one that builds the role's call — a
    keyword dropped there leaves every test above green and the prompt without its day."""
    from openfactory.product import module as module_mod
    from openfactory.product.module import ProductModule

    got: dict = {}

    class _Role:
        def answer(self, **kw):
            got.update(kw)
            return SimpleNamespace(ok=False, text="", reading=None, evidence=None)

    mod = ProductModule.__new__(ProductModule)
    monkeypatch.setattr(mod, "context", lambda: SimpleNamespace(available=True, reason=""),
                        raising=False)
    monkeypatch.setattr(mod, "_workspace", lambda: (None, None), raising=False)
    monkeypatch.setattr(mod, "_role", lambda **_k: _Role(), raising=False)
    monkeypatch.setattr(mod, "already_asked", lambda _q: "", raising=False)
    monkeypatch.setattr(module_mod, "_signal_gaps", lambda *_a, **_k: [])
    when = clock.now_block(datetime(2026, 9, 25, 9, 0, tzinfo=UTC))
    mod.answer("e agora?", now=when)
    assert got.get("now") == when
