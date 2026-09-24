"""The briefing — what the product's owner carries in their head in the morning, in every answer's
prompt, with its source and its age on every line (#267 slice 2, ADR-0052 D5, D8–D10).

Run on the read model's own bed (`tests/the_product_bed.py`): two registry projects of one product,
a parked job the tech-lead diagnosed, a job waiting on a merge, a stalled one, a delivery awaiting
its requester's verdict, a decision asked of the person the turn answers, a release tag on each
member, and the people, the spend and the credential the bed plants to be withheld.

WHAT IS HELD HERE, and each is a row of `tools/mutations/267_the_briefing.py`:

  * on the fixture it lists the moving, parked and waiting cards and the version in production;
  * every line states its source and its age — the fact's own age where the platform recorded one;
  * it is bounded in lines and in characters, and says as a count what it left out;
  * a fact that could not be read is a line saying so;
  * the three withholdings: nobody named across conversations, no spend, no credential;
  * the register: the raw diagnosis to an engineer in private and to nobody else;
  * it is in the answer's prompt, in the board section's place, and the switch turns it off.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory.contracts import AgentRunResult
from openfactory.memory.ledger import CARD_QUESTION, DECISION, open_loop
from openfactory.product import briefing
from openfactory.product import model as read_model
from openfactory.product.module import ProductModule, _the_briefing
from openfactory.product.role import ProductRole
from openfactory.product.speaker import ADMIN, CLIENT, ENGINEER, Person, sealed
from openfactory.product.triage import Ticket
from tests import the_product_bed as bed
from tests.test_the_conversation_is_pinned import _Conversation
from tests.test_the_speaker_and_the_reply import EDU, ROOM, _project, _Room, ledger, table

__all__ = ["ledger", "table"]  # the speaker suite's fixtures, used by the engine's test below

ROOT = Path(__file__).resolve().parent.parent

#: The clock every rendering here is read at, and when the bed's model was read.
NOW = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)
READ = "2026-09-24T09:58:00+00:00"

#: How a line ends: `(<source> — <verb> <age>)`.
SUFFIX = re.compile(
    r" \((engine|ledger|release tag|board|floor|forge|tracker|registry|preview|the read model) — "
    r"(read|tried|asked|parked|started|ended|up) "
    r"(just now|\d+ min ago|\d+ h ago|1 day ago|\d+ days ago)\)$")
LEFT_OUT = re.compile(r"^(\d+) more lines? left out to keep this briefing short \((.+)\) — ")


@pytest.fixture
def made(tmp_path, monkeypatch):
    return bed.stand_up(tmp_path, monkeypatch)


def the_model(made):
    model = bed.the_model(made["acme-web"], corpus=bed.corpus())
    model.read_at = READ
    return model


def said(model, *, speaker: str = bed.YURI, raw: bool = False) -> briefing.Briefing:
    return briefing.render(model, speaker=speaker, raw=raw, now=NOW)


def plant(monkeypatch, loops: dict[str, list]) -> None:
    """More open loops in the bed's ledger, beside the ones it planted."""
    from openfactory.memory import store

    planted = store.read
    monkeypatch.setattr(store, "read",
                        lambda project, **k: [*planted(project, **k), *loops.get(project, [])])


def job(model, issue: str) -> dict:
    return next(j for j in model.now["acme-web"]["jobs"] if str(j["issue"]) == issue)


# ── what it says ────────────────────────────────────────────────────────────────────────────────

#: The fixture's briefing for the person the turn answers, as a client reads it.
FIXTURE = [
    "1 card is moving: acme-api#7 (stalled — nothing left can advance it) (engine — read 2 min ago)",
    "In production (the newest release tag): acme-web v1.4.2-q7 · acme-api v0.9.0-api-q7 "
    "(release tag — read 2 min ago)",
    "acme-web#39 «WEB39-title Migrate the invoices table» is parked: it waits on a person — it is "
    "on hold until somebody answers what it asks; the tech-lead's diagnosis is on its card "
    "(engine — parked 5 days ago)",
    "acme-web#41 «WEB41-title Export the monthly report» waits on a person to merge its pull "
    "request (or ask for an adjustment) (engine — started 5 days ago)",
    "A delivery (`40`) waits on its requester to say whether it worked (ledger — asked 6 days ago)",
    "The decision «WEB-loop-asked CSV or XLSX?» waits on you (ledger — asked 4 days ago)",
    "A delivery (`API-delivery-7`) waits on its requester to say whether it worked "
    "(ledger — asked 3 days ago)",
    "Delivered in the last 7 days: acme-web#40 (merged; deployed) (engine — ended 6 days ago)",
]


def test_on_the_fixture_it_lists_the_moving_parked_and_waiting_cards_and_what_is_in_production(
        made):
    got = said(the_model(made))
    assert list(got.lines) == FIXTURE
    assert got.left_out == 0 and not got.raw


def test_the_factory_s_own_loops_are_not_the_owner_s_morning(made):
    """The tech-lead's finding on #41 waits on an operator; it is in `now.md`, not here."""
    text = said(the_model(made)).text
    assert "WEB-finding" not in text and "finding" not in text


def test_every_line_states_its_source_and_its_age(made, monkeypatch):
    from openfactory.runtime.temporal import view as tv

    for raw in (False, True):
        for line in said(the_model(made), raw=raw).lines:
            assert SUFFIX.search(line), line

    async def down():
        raise ConnectionError("the engine is down")

    monkeypatch.setattr(tv, "connect", down)
    bed.forget()
    lines = said(the_model(made)).lines
    assert lines and all(SUFFIX.search(line) for line in lines), lines


def test_the_age_is_the_fact_s_own_where_the_platform_recorded_one_and_the_reading_s_otherwise(
        made):
    lines = said(the_model(made)).lines
    assert lines[2].endswith("(engine — parked 5 days ago)"), "when the job parked"
    assert lines[5].endswith("(ledger — asked 4 days ago)"), "when the decision was asked"
    assert lines[7].endswith("(engine — ended 6 days ago)"), "when the job ended"
    assert lines[1].endswith("(release tag — read 2 min ago)"), "a tag has no date: the reading's"


@pytest.mark.parametrize(("stamp", "said_as"), [
    ("2026-09-24T09:59:30+00:00", "just now"),
    ("2026-09-24T09:48:00Z", "12 min ago"),
    ("2026-09-24T07:00:00+00:00", "3 h ago"),
    ("2026-09-23T09:00:00+00:00", "1 day ago"),
    ("2026-09-19T09:20:00", "5 days ago"),
    ("2026-09-25T10:00:00+00:00", "just now"),
    ("not a date", "at not a date"),
    ("", "at a time not recorded"),
])
def test_an_age_is_said_as_a_person_says_it_and_never_guessed(stamp, said_as):
    assert briefing.age(stamp, NOW) == said_as


# ── the bound ───────────────────────────────────────────────────────────────────────────────────

def _decisions(n: int) -> list:
    return [open_loop(DECISION, f"q{i:02d}", owner="product",
                      ts=f"2026-09-2{i % 3}T{i % 24:02d}:00:00+00:00",
                      context={"asked": f"question {i:02d} about the export?"})
            for i in range(n)]


def _all_lines(model) -> list[str]:
    """Every line the briefing would say with no bound — what the count is held against."""
    import unittest.mock as mock

    with mock.patch.object(briefing, "MAX_LINES", 10_000), \
            mock.patch.object(briefing, "MAX_CHARS", 10_000_000):
        return list(said(model).lines)


def test_it_is_bounded_in_lines_and_says_how_many_it_left_out(made, monkeypatch):
    plant(monkeypatch, {"acme-web": _decisions(30)})
    model = the_model(made)
    every = _all_lines(model)
    got = said(model)

    assert len(every) == len(FIXTURE) + 30
    assert len(got.lines) == briefing.MAX_LINES
    assert len(got.text) <= briefing.MAX_CHARS
    count = LEFT_OUT.match(got.lines[-1])
    assert count, got.lines[-1]
    assert int(count.group(1)) == got.left_out == len(every) - (len(got.lines) - 1)
    assert count.group(2) == f"{got.left_out - 1} waiting, 1 delivered", "counted by kind"
    assert got.lines[:-1] == tuple(every[:len(got.lines) - 1]), "in order, from the top"
    assert got.lines[1].startswith("In production"), "what matters most is kept"


def test_it_is_bounded_in_characters_when_the_lines_are_long(made, monkeypatch):
    plant(monkeypatch, {"acme-web": [
        open_loop("question", f"a question about the export number {i} " * 8, owner="product",
                  ts=f"2026-09-20T{i:02d}:00:00+00:00") for i in range(10)]})
    model = the_model(made)
    every = _all_lines(model)
    got = said(model)

    assert sum(len(x) for x in every[:briefing.MAX_LINES - 1]) > briefing.MAX_CHARS, (
        "the lines alone would fit the line bound and break the character bound")
    assert len(got.text) <= briefing.MAX_CHARS
    assert len(got.lines) < briefing.MAX_LINES, "the characters, not the lines, cut this one"
    count = LEFT_OUT.match(got.lines[-1])
    assert count and int(count.group(1)) == got.left_out > 0
    assert int(count.group(1)) == len(every) - (len(got.lines) - 1)


def test_a_long_line_is_cut_and_keeps_its_source_and_its_age(made, monkeypatch):
    monkeypatch.setitem(bed.THREADS, ("acme-web", "39"), [
        ("openfactory-bot", "### Tech-lead triage\n" + "the migration has no rollback. " * 30,
         "2026-09-19T09:30:00Z")])
    bed.forget()
    line = next(x for x in said(the_model(made), raw=True).lines if x.startswith("acme-web#39"))
    body = SUFFIX.split(line)[0]
    assert len(body) <= briefing.LINE_CHARS and body.endswith("…"), body
    assert line.endswith("(engine — parked 5 days ago)")


# ── what could not be read ──────────────────────────────────────────────────────────────────────

def test_a_fact_that_could_not_be_read_is_a_line_saying_so(made, monkeypatch):
    from openfactory.runtime.temporal import view as tv

    async def down():
        raise ConnectionError("the engine is down")

    monkeypatch.setattr(tv, "connect", down)
    bed.forget()
    lines = said(the_model(made)).lines

    engine_line = next(x for x in lines if x.startswith("the engine's jobs could not be read"))
    assert engine_line.endswith("(engine — tried 2 min ago)")
    assert "unknown, not idle" in engine_line
    assert not any("is moving" in x for x in lines), "an unread floor is never an idle one"
    assert not any("waits on a person to merge" in x for x in lines)


def test_an_unreadable_board_and_ledger_are_lines_with_their_own_source(made, monkeypatch):
    from openfactory.memory import store

    listing = bed.Tracker.list_tickets

    def ledger_down(project, **_k):
        raise RuntimeError("the ledger is down")

    monkeypatch.setattr(bed.Tracker, "list_tickets",
                        lambda self, **kw: None if self.project == "acme-api"
                        else listing(self, **kw))
    monkeypatch.setattr(store, "read", ledger_down)
    bed.forget()
    lines = said(the_model(made)).lines

    assert any(x.startswith("acme-api: the board could not be read")
               and x.endswith("(board — tried 2 min ago)") for x in lines), lines
    assert any("the open-loop ledger could not be read" in x
               and x.endswith("(ledger — tried 2 min ago)") for x in lines), lines
    assert not any(x.startswith("A delivery") for x in lines), "no loop is said from no ledger"


# ── the withholdings ────────────────────────────────────────────────────────────────────────────

def _people_in_the_text(monkeypatch):
    """A decision asked of ZELDA whose label names QUINN, a question the factory asked ZELDA on
    #39, and the tech-lead naming ZELDA in its diagnosis."""
    plant(monkeypatch, {"acme-web": [
        open_loop(DECISION, "WEB-loop-who-sees", owner="product",
                  ts="2026-09-22T10:00:00+00:00", about=f"person:{bed.ZELDA}",
                  context={"asked": f"should {bed.QUINN} see the export too?",
                           "asked_of": sealed(bed.ZELDA),
                           "asked_in": sealed(f"person:{bed.ZELDA}")}),
        open_loop(CARD_QUESTION, "39", owner="techlead", ts="2026-09-22T09:00:00+00:00",
                  about="q-hash", context={"requester": bed.ZELDA_FORGE,
                                           "question": "which table is the old one?"})]})
    monkeypatch.setitem(bed.THREADS, ("acme-web", "39"), [
        ("openfactory-bot", f"### Tech-lead triage\nWEB39-diagnosis {bed.ZELDA} asked for it and "
                            f"the migration has no rollback", "2026-09-19T09:30:00Z")])
    bed.forget()


def test_nobody_is_named_across_conversations(made, monkeypatch):
    _people_in_the_text(monkeypatch)
    model = the_model(made)
    for raw in (False, True):
        text = said(model, raw=raw).text
        for who in bed.PEOPLE:
            assert who not in text, (raw, who)
    text = said(model, raw=True).text
    assert "should [a person] see the export too?" in text, "withheld where it rides"
    assert "WEB39-diagnosis [a person] asked for it" in text
    assert "The decision «WEB-loop-asked CSV or XLSX?» waits on you " in text
    assert "«should [a person] see the export too?» waits on the person it was asked of" in text
    assert ("acme-web#39 waits on its requester to answer the question the factory asked on the "
            "card") in text
    assert "A delivery (`40`) waits on its requester" in text


def test_the_person_spoken_to_is_you_and_nobody_else_is(made, monkeypatch):
    _people_in_the_text(monkeypatch)
    model = the_model(made)

    zelda = said(model, speaker=bed.ZELDA).text
    assert "A delivery (`40`) waits on you (the person speaking)" in zelda
    assert "«should [a person] see the export too?» waits on you " in zelda
    assert "«WEB-loop-asked CSV or XLSX?» waits on the person it was asked of" in zelda

    nobody = said(model, speaker="").text
    assert " waits on you" not in nobody and "[you]" not in nobody


def test_spend_never_appears_in_any_register(made, monkeypatch):
    monkeypatch.setitem(bed.THREADS, ("acme-web", "39"), [
        ("openfactory-bot", f"### Tech-lead triage\nWEB39-diagnosis the pass stopped\n"
                            f"{bed.SPEND_LINE}\nsplit it", "2026-09-19T09:30:00Z")])
    bed.forget()
    model = the_model(made)
    job(model, "39")["detail"]["why"] = bed.CEILING
    job(model, "41")["detail"]["why"] = ("The review rejected it, the pass had billed $3.21 by "
                                         "then")
    for raw in (False, True):
        text = said(model, raw=raw).text
        assert not re.search(r"\$\s?\d", text), text
        for figure in bed.SPEND_WORDS:
            assert figure not in text, (raw, figure)
    raw = said(model, raw=True).text
    assert "WEB39-diagnosis the pass stopped split it" in raw, "the rest of the diagnosis stays"
    assert "the engine's reason: The review rejected it" in raw


def test_no_credential_reaches_the_briefing(made, monkeypatch):
    monkeypatch.setitem(bed.THREADS, ("acme-web", "39"), [
        ("openfactory-bot", f"### Tech-lead triage\nWEB39-diagnosis the token {bed.TOKEN} "
                            f"expired", "2026-09-19T09:30:00Z")])

    def refused(self):
        raise RuntimeError(f"401 from https://x-access-token:{bed.TOKEN}@forge.example/acme")

    monkeypatch.setattr(bed.Forge, "latest_tag", refused)
    bed.forget()
    model = the_model(made)
    for raw in (False, True):
        text = said(model, raw=raw).text
        assert bed.TOKEN not in text and "x-access-token" not in text, raw
    raw = said(model, raw=True).text
    assert f"the token {read_model.WITHHELD_CREDENTIAL} expired" in raw
    assert "401 from https://forge.example/acme" in raw, "the gap is said, its credential is not"


# ── the registers ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("role", "private", "raw"), [
    (ENGINEER, True, True),
    (ENGINEER, False, False),
    (CLIENT, True, False),
    (ADMIN, True, False),
    (CLIENT, False, False),
], ids=["engineer-in-private", "engineer-in-a-room", "client-in-private", "admin-in-private",
        "client-in-a-room"])
def test_the_raw_diagnosis_is_an_engineer_s_in_private_and_nobody_else_s(role, private, raw):
    assert briefing.raw_for(Person(id="p", role=role), private=private) is raw
    assert briefing.raw_for(None, private=True) is False


def test_an_engineer_in_private_reads_the_diagnosis_and_a_client_never_does(made):
    model = the_model(made)
    raw = said(model, raw=True).text
    translated = said(model).text

    for fact in ("WEB39-diagnosis the migration has no rollback",
                 "WEB39-question keep the old table?", "WEB41-review the migration has no rollback",
                 "is parked (on_hold)"):
        assert fact in raw, fact
    for raw_only in ("WEB39-diagnosis", "WEB39-question", "WEB39-note", "WEB41-review",
                     "REJECTED", "the engine's reason"):
        assert raw_only not in translated, raw_only
    assert "the tech-lead's diagnosis is on its card" in translated


def test_a_parked_card_nobody_has_diagnosed_is_briefed_as_diagnosis_pending(made, monkeypatch):
    monkeypatch.setitem(bed.THREADS, ("acme-web", "39"), [])
    bed.forget()
    model = the_model(made)
    assert "WEB39-diagnosis" not in said(model, raw=True).text
    assert "answers what it asks; diagnosis pending (engine" in said(model).text
    assert "the tech-lead's diagnosis on its card: pending" in said(model, raw=True).text


def test_the_section_says_the_register_it_was_rendered_in():
    def section(raw: bool) -> str:
        role = ProductRole(_Harness(), briefing=briefing.Briefing(lines=("x (engine — read "
                                                                         "just now)",), raw=raw),
                           mounted={"facts": ".openfactory-facts-ab12"})
        return "\n".join(role._briefing_section())

    assert "speaking privately with an engineer" in section(True)
    assert "never quote it" in section(False) and "privately" not in section(False)
    assert ".openfactory-facts-ab12/now.md" in section(False)


def test_the_module_reads_the_register_from_the_speaker_and_the_conversation(monkeypatch):
    from openfactory.product.config import ProductLink
    from openfactory.product.loader import ProductContext

    seen: list = []
    module = ProductModule(_project(engineers=(EDU,)), context=ProductContext(
        link=ProductLink(active=True, docs_repo="a/b")))
    monkeypatch.setattr(module, "_workspace", lambda: (None, None))
    monkeypatch.setattr(module, "already_asked", lambda _q: "")

    class _Role:
        def answer(self, **_kw):
            seen.append(module._raw_diagnosis)
            return SimpleNamespace(ok=True, text="ok", reading=None)

    monkeypatch.setattr(module, "_role", lambda **_kw: _Role())
    monkeypatch.setattr("openfactory.product.module._bound_answer", lambda _m, answer: answer)
    engineer = Person(id=EDU, role=ENGINEER)
    client = Person(id="U0CAIO", role=CLIENT)

    module.answer("por que parou?", speaker=engineer, private=True)
    module.answer("por que parou?", speaker=engineer)
    module.answer("por que parou?", speaker=client, private=True)

    assert seen == [True, False, False]


class _Private(_Room):
    """The speaker suite's room, remembering whether each answer was in a private conversation."""

    def __init__(self, project, **kw) -> None:
        super().__init__(project, **kw)
        self.privates: list = []

    def answer(self, question, *, speaker=None, private=False, **kw):
        self.privates.append(private)
        return super().answer(question, speaker=speaker, **kw)


def test_the_engine_says_whether_the_conversation_is_the_person_s_alone(table, ledger):
    project = _project(engineers=(EDU,))
    module = _Private(project)
    talk = _Conversation(project, module)

    talk.say("o que está parado?", user=EDU, thread=f"person:{EDU}")
    talk.say("o que está parado?", user=EDU, thread=ROOM)

    assert module.privates == [True, False]


# ── in the prompt ───────────────────────────────────────────────────────────────────────────────

class _Harness:
    name = "recording"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.prompts.append(prompt)
        return AgentRunResult(ok=True, summary="ok")


BOARD = "# The board (already read for you"
SITUATION = "# The situation now (the briefing"
CARDS = [Ticket(number="41", title="WEB41-title Export the monthly report", column="In review",
                state="open")]


def _asked(role: ProductRole, monkeypatch) -> str:
    monkeypatch.setattr(ProductRole, "_meter", lambda *a, **k: None)
    role.answer(sandbox=None, workspace=None, question="o que está parado?")
    return role.agent.prompts[-1]


def test_an_answer_carries_the_briefing_in_the_board_section_s_place(made, monkeypatch):
    got = said(the_model(made))
    role = ProductRole(_Harness(), cards=CARDS, briefing=got,
                       mounted={"docs": "docs", "code": "code",
                                "facts": ".openfactory-facts-ab12"})
    prompt = _asked(role, monkeypatch)

    assert SITUATION in prompt and BOARD not in prompt
    for line in got.lines:
        assert f"- {line}" in prompt
    assert "the one place every card is" in prompt, "board.md is where every card is now"
    assert prompt.index("# The facts, as files") < prompt.index(SITUATION) < prompt.index(
        "## Question"), "after every section that changes less often, before the question"


def test_every_other_operation_keeps_the_board_and_carries_no_briefing(made, monkeypatch):
    role = ProductRole(_Harness(), cards=CARDS, briefing=said(the_model(made)),
                       mounted={"docs": "docs", "code": "code",
                                "facts": ".openfactory-facts-ab12"})
    for prompt in (role._prompt("break it into issues", ""), role._prompt("draft it", "",
                                                                             audience="client")):
        assert BOARD in prompt and SITUATION not in prompt


def test_with_no_pack_to_open_the_board_section_stays_beside_the_briefing(made, monkeypatch):
    role = ProductRole(_Harness(), cards=CARDS, briefing=said(the_model(made)),
                       mounted={"docs": "docs", "code": "code"})
    prompt = _asked(role, monkeypatch)
    assert SITUATION in prompt and BOARD in prompt
    assert "could not be written for this message" in prompt


def test_with_no_briefing_the_answer_is_the_prompt_it_was(monkeypatch):
    role = ProductRole(_Harness(), cards=CARDS,
                       mounted={"docs": "docs", "code": "code",
                                "facts": ".openfactory-facts-ab12"})
    prompt = _asked(role, monkeypatch)
    assert BOARD in prompt and SITUATION not in prompt
    assert "where the board section above is a budgeted rendering" in prompt


# ── the switch, and the module that hands it over ──────────────────────────────────────────────

@pytest.mark.parametrize(("value", "on"), [
    (None, True), ("", True), ("on", True), ("1", True), ("yes", True), ("sim", True),
    ("off", False), ("OFF", False), ("0", False), ("false", False), ("no", False),
    (" off ", False),
])
def test_the_switch_is_on_unless_it_says_off(monkeypatch, value, on):
    if value is None:
        monkeypatch.delenv(briefing.SWITCH_ENV, raising=False)
    else:
        monkeypatch.setenv(briefing.SWITCH_ENV, value)
    assert briefing.enabled() is on


def _fake_module(made, tmp_path, *, raw: bool = False):
    """`ProductModule._role`'s seam with the pack really written from the bed's model: the facts
    on disk, the mount that names them, and the briefing rendered from the same model."""
    from openfactory.product.loader import Corpus

    root = tmp_path / "ws"
    (root / "docs").mkdir(parents=True)
    (root / "code").mkdir()
    fake = SimpleNamespace(
        _agent=_Harness(), _corpus_note=lambda: "", project=made["acme-web"],
        context=lambda: SimpleNamespace(corpus=Corpus(), domain=None, available=True),
        _board_cards=lambda: list(CARDS), _workspace=lambda: None,
        _combined=str(root), _mounted_code=str(root / "code"), _turn_view=str(root),
        _facts_for=bed.YURI, _raw_diagnosis=raw, _product_model=the_model(made))
    fake._write_facts = lambda: ProductModule._write_facts(fake)
    fake.mounted = lambda: ProductModule.mounted(fake)
    # every source of the product (#268): none known here, so the one mount above renders
    fake.mounts = lambda: None
    fake.onboarding = lambda: []
    return fake


def test_the_module_hands_the_role_the_briefing_of_the_model_it_wrote_the_pack_from(
        made, tmp_path, monkeypatch, caplog):
    monkeypatch.delenv(briefing.SWITCH_ENV, raising=False)
    fake = _fake_module(made, tmp_path)
    with caplog.at_level("INFO", logger="openfactory.product"):
        role = ProductModule._role(fake)
    prompt = _asked(role, monkeypatch)

    assert role.briefing is not None and not role.briefing.raw
    assert SITUATION in prompt and BOARD not in prompt
    assert "acme-web#39 «WEB39-title Migrate the invoices table» is parked" in prompt
    assert "The decision «WEB-loop-asked CSV or XLSX?» waits on you " in prompt, (
        "rendered for the person the turn answers")
    assert _the_briefing(fake) is role.briefing, "once per module"
    assert re.search(r"OPENFACTORY_PRODUCT_BRIEFING project=acme-web state=on lines=\d+ "
                     r"chars=\d+ left_out=0 raw=no", caplog.text), caplog.text


def test_the_switch_off_takes_the_briefing_away_and_brings_the_board_back(made, tmp_path,
                                                                        monkeypatch, caplog):
    monkeypatch.setenv(briefing.SWITCH_ENV, "off")
    fake = _fake_module(made, tmp_path)
    with caplog.at_level("INFO", logger="openfactory.product"):
        role = ProductModule._role(fake)
    prompt = _asked(role, monkeypatch)

    assert role.briefing is None
    assert SITUATION not in prompt and BOARD in prompt
    assert role.mounted.get("facts"), "the files are the same in both arms"
    assert "OPENFACTORY_PRODUCT_BRIEFING project=acme-web state=off" in caplog.text


def test_a_pass_that_answers_nobody_or_has_no_model_carries_no_briefing(made, tmp_path):
    fake = _fake_module(made, tmp_path)
    del fake._facts_for
    assert _the_briefing(fake) is None
    fake = _fake_module(made, tmp_path / "b")
    fake._product_model = None
    assert _the_briefing(fake) is None


def test_the_engineer_s_register_reaches_the_rendering(made, tmp_path):
    got = _the_briefing(_fake_module(made, tmp_path, raw=True))
    assert got.raw and "WEB39-diagnosis the migration has no rollback" in got.text


def test_the_configuration_documents_the_switch_and_the_default_the_code_has():
    text = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
    row = re.search(rf"^\| `{briefing.SWITCH_ENV}` \| `([^`]+)` \|", text, re.M)
    assert row, f"{briefing.SWITCH_ENV} is not documented"
    assert row.group(1) == briefing.DEFAULT and briefing.DEFAULT not in briefing._OFF
    assert "briefing" in (ROOT / "docs/reference/product-role.md").read_text(encoding="utf-8")


# ── the hook, and the loop the briefing's example is ────────────────────────────────────────────

def test_a_preview_the_model_carries_is_a_line_with_its_age(made):
    """ADR-0050 is not on this base; the hook says a preview the day the model carries one."""
    model = the_model(made)
    assert not any("preview" in line for line in said(model).lines)
    model.now["acme-web"]["previews"] = [{"card": "38", "url": "https://preview.example/38",
                                          "up_since": "2026-09-24T09:20:00+00:00"}]
    assert ("acme-web#38's preview is up at https://preview.example/38 (preview — up 40 min ago)"
            in said(model).lines)


def test_a_question_asked_on_a_card_waits_on_its_requester_in_the_files_too(made, monkeypatch,
                                                                          tmp_path):
    """ADR-0052's own example — "#42 has waited 2 days on a decision from its requester" — is a
    card question: the tech-lead's loop, and the requester's to close. `now.md` said "an
    operator"; both now say it the same way."""
    from openfactory.product import facts

    _people_in_the_text(monkeypatch)
    model = the_model(made)
    files, _ = facts.gather("acme-web", None, model=model, speaker=bed.YURI)
    assert "card_question `39` waits on its requester" in files["now.md"]
    assert any(line.startswith("acme-web#39 waits on its requester to answer the question")
               and line.endswith("(ledger — asked 2 days ago)") for line in said(model).lines)


# ── the agenda this conversation may read, in the model as in loops.md (#267 slices 1–3) ──────

def test_a_decision_asked_in_somebody_s_private_conversation_never_reaches_another_s_turn(
        made, monkeypatch):
    """The read model's loops are the agenda the conversation a turn answers in may read — the
    rule `loops.md` and the panel's `/api/loops` already follow (slice 3). `now.md` and the
    briefing are read by that one turn, and a decision asked in Ana's private conversation is not
    Bruno's to see: not her name, and not what she was asked either. Her own turn sees it."""
    from openfactory.product.module import _loops_seen_in
    from openfactory.product.speaker import sealed

    ana, bruno = "person:ana-private-1", "person:bruno-private-2"
    plant(monkeypatch, {"acme-web": [open_loop(
        DECISION, "salario", owner="product", ts="2026-09-22T10:00:00+00:00",
        context={"asked": "SEGREDO-DA-ANA which salary band?", "asked_of": sealed("ana-private-1"),
                 "asked_in": sealed(ana)})]})

    def seen_by(conversation: str) -> str:
        model = read_model.build(made["acme-web"], corpus=bed.corpus(),
                                 loops_seen=lambda m: _loops_seen_in(m, conversation, m.name))
        model.read_at = READ
        return "\n".join([*read_model.render(model).values(), said(model).text])

    assert "SEGREDO-DA-ANA" not in seen_by(bruno)
    assert "SEGREDO-DA-ANA" in seen_by(ana)


def test_a_turn_builds_its_model_with_the_agenda_of_the_conversation_it_answers_in(
        made, monkeypatch):
    """The same, through the path a turn takes: the engine tells the module where it answers
    (`answering_in`), and the model the module builds for the facts pack and the briefing reads
    the ledger as that conversation may."""
    from openfactory.product.module import _the_read_model
    from openfactory.product.speaker import sealed

    ana, bruno = "person:ana-private-1", "person:bruno-private-2"
    plant(monkeypatch, {"acme-web": [open_loop(
        DECISION, "salario", owner="product", ts="2026-09-22T10:00:00+00:00",
        context={"asked": "SEGREDO-DA-ANA which salary band?", "asked_of": sealed("ana-private-1"),
                 "asked_in": sealed(ana)})]})

    def a_turn_in(conversation: str) -> str:
        module = SimpleNamespace(
            project=made["acme-web"], _facts_for="", _conversation=conversation,
            context=lambda: SimpleNamespace(available=True, corpus=bed.corpus()))
        model = _the_read_model(module, "")["model"]
        model.read_at = READ
        return "\n".join([*read_model.render(model).values(), said(model).text])

    assert "SEGREDO-DA-ANA" not in a_turn_in(bruno)
    assert "SEGREDO-DA-ANA" in a_turn_in(ana)
