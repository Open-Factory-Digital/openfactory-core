"""A decision taken after the acceptance gets written into the requirement's own register.

THE EVIDENCE, 2026-07-31. The role proposed recording a dated, attributed decision in requirement
4's decision register. The product owner checked before recommending the client confirm it, and
found that
**nothing in the codebase wrote to that table**:

- `render_requirement` created the section, EMPTY
- `corpus._decision_rows` / `has_decisions` READ whatever was there
- `_cross_check` even emitted `no-write-back` when an agreed requirement recorded no decision
- and the writer did not exist

The third instance of one class in a single day (closing a card, retiring a requirement, recording
a decision): an everyday product-owner act with no operation behind it, so the agent NARRATES and
the client believes. Worse here than in the other two, because the corpus itself complained about
the absence of something nobody could write.

WHY IT MATTERS MORE THAN IT LOOKS. This is where the provenance of a decision taken AFTER the
acceptance lives. Without it the decision exists on a card nobody opens in three months, or in a
conversation that scrolls. The role put it better than anybody: *"if this only goes on the card, in three months nobody knows where it came from or that you were
the one who decided."*
"""

from __future__ import annotations

import re

import pytest

import openfactory.product.channel as pc
from openfactory.product.authoring import add_decision_row, render_requirement
from openfactory.product.corpus import _decision_rows, parse_requirement
from openfactory.product.intents import match_intent
from openfactory.product.role import RequirementDraft

TEMPLATE = render_requirement(
    RequirementDraft(title="Portal do cliente", why="porque sim", must_be_true=["abre"]),
    number=6, asked_by="<@UADM>", date="2026-07-01")


# ── 1. the round trip: what the writer writes, the reader reads ────────────────────────────────
def test_a_written_row_is_READ_BACK_by_the_corpus():
    """THE INVARIANT THIS FEATURE IS, and the reason the writer's half of the section finder lives
    in `corpus.py` beside the reader's. A writer with its own idea of where the table is appends
    rows outside it: `has_decisions` stays False, `no-write-back` keeps firing, and the client is
    looking at a decision the corpus swears was never recorded."""
    updated, outcome = add_decision_row(
        TEMPLATE, day="2026-07-31", decision="o pró-labore entra como despesa fixa",
        who="<@UADM>", where="conversa com o time de produto")

    assert outcome == "written"
    rows = _decision_rows(updated)
    assert len(rows) == 1, f"the corpus cannot see the row that was just written: {rows}"
    assert "pró-labore" in rows[0] and "<@UADM>" in rows[0] and "2026-07-31" in rows[0], rows[0]


def test_the_complaint_the_corpus_was_ALREADY_making_now_stops():
    """`_cross_check` emits `no-write-back` for an agreed requirement with an empty register. It
    was un-silenceable: the only thing that could answer it did not exist."""
    agreed = TEMPLATE.replace("- **Status:** proposed", "- **Status:** accepted")
    before, _ = parse_requirement(__import__("pathlib").Path("0006-portal.md"), agreed)
    assert before is not None and before.has_decisions is False

    written, _ = add_decision_row(agreed, day="2026-07-31", decision="usar o regime de caixa",
                                  who="<@UADM>")
    after, _ = parse_requirement(__import__("pathlib").Path("0006-portal.md"), written)

    assert after is not None and after.has_decisions is True


def test_a_second_decision_lands_UNDER_the_first_and_neither_is_lost():
    once, _ = add_decision_row(TEMPLATE, day="2026-07-31", decision="primeira", who="<@UADM>")
    twice, _ = add_decision_row(once, day="2026-08-02", decision="segunda", who="<@UADM>")

    rows = _decision_rows(twice)
    assert len(rows) == 2, rows
    assert "primeira" in rows[0] and "segunda" in rows[1], rows


def test_the_same_decision_on_the_same_day_is_not_written_twice():
    """A retried confirmation is not a second decision. Writing it twice would make one act look
    like two in the only record that answers "how often did this change?"."""
    once, _ = add_decision_row(TEMPLATE, day="2026-07-31", decision="usar caixa", who="<@UADM>")
    again, outcome = add_decision_row(once, day="2026-07-31", decision="usar caixa", who="<@UADM>")

    assert outcome == "duplicate"
    assert len(_decision_rows(again)) == 1


def test_a_pipe_in_the_decision_does_not_rewrite_the_row():
    """An unescaped `|` splits one decision into two cells and shifts every later column, so the
    row renders as a different sentence than the person approved. Escaped rather than refused —
    the platform's table format is not a limit on what a client may decide."""
    updated, _ = add_decision_row(
        TEMPLATE, day="2026-07-31", who="<@UADM>",
        decision="regime de caixa | não competência")

    rows = _decision_rows(updated)
    assert len(rows) == 1
    # cells, not characters: the escaped pipe is still a `|` in the text and must not be counted
    # as a separator — which is exactly the confusion the escape exists to settle.
    cells = re.split(r"(?<!\\)\|", rows[0].strip().strip("|"))
    assert len(cells) == 3, f"the row grew a column: {rows[0]}"
    assert "não competência" in cells[1], cells


def test_a_file_with_NO_register_is_refused_rather_than_given_one():
    """A requirement written before the template had this section is a real state in the live
    client's base. Inventing the heading would put a table into a document whose shape nobody
    chose — the repair belongs to a person who can look at it."""
    stripped = TEMPLATE.split("## Decisions taken during execution")[0]

    updated, outcome = add_decision_row(stripped, day="2026-07-31", decision="x", who="<@UADM>")

    assert outcome == "no-section"
    assert updated == stripped, "the document was changed by a write that reported it had not been"


def test_the_row_lands_in_the_DECISION_table_and_not_in_another_one():
    """The naive writer finds the last `|` line in the file and writes under it. A requirement whose
    "Affects" section holds a table would then take the decision into THAT one, where
    `has_decisions` never sees it and `no-write-back` goes on complaining about a decision the
    client watched being recorded."""
    decoy = TEMPLATE.replace(
        "## Affects\n",
        "## Affects\n\n| file | why |\n|---|---|\n| `app.py` | it is where this lives |\n")

    updated, outcome = add_decision_row(decoy, day="2026-07-31", decision="a decisão",
                                        who="<@UADM>")

    assert outcome == "written"
    assert len(_decision_rows(updated)) == 1, "the row went into the wrong table"
    assert "| `app.py` | it is where this lives |" in updated, "the decoy table was disturbed"


def test_the_writer_and_the_reader_share_ONE_heading():
    """Four places agree on this string. Three of them agreeing by having been typed the same way
    is a fourth waiting to drift — and the one that drifts is the WRITER, whose rows then land in a
    section nothing reads while the file looks correct."""
    import inspect

    from openfactory.product import authoring, corpus

    assert f"## {corpus.DECISIONS_HEADING}" in TEMPLATE
    src = inspect.getsource(authoring.add_decision_row)
    assert "find_decisions_table" in src, "the writer located the table with its own idea of it"


# ── 2. the gesture, and what it refuses ────────────────────────────────────────────────────────
@pytest.mark.parametrize(("phrase", "decision"), [
    ("registra no requisito 6 que o pró-labore entra como despesa fixa",
     "o pró-labore entra como despesa fixa"),
    ("Nina, anota no requisito 4 que decidimos usar o CNPJ da matriz",
     "decidimos usar o CNPJ da matriz"),
    ("grava no requisito 6: o corte é dia 25", "o corte é dia 25"),
])
def test_a_person_records_a_decision_in_their_own_words(phrase, decision):
    matched = match_intent(phrase)

    assert matched and matched[0] == "decision", f"{phrase!r} -> {matched}"
    assert matched[1]["decision"] == decision, matched


@pytest.mark.parametrize("phrase", [
    "não registra nada no requisito 6",
    "você registrou algo no requisito 6?",
])
def test_a_negation_or_a_question_writes_nothing(phrase):
    matched = match_intent(phrase)

    assert not (matched and matched[0] == "decision"), f"{phrase!r} -> {matched}"


@pytest.mark.parametrize(("phrase", "intent"), [
    ("aceita o requisito 6", "accept"),
    ("cancela o requisito 2", "drop"),
    ("quebra o requisito 8 em tarefas", "breakdown"),
    ("alinha o #288 ao requisito 6", "align"),
    ("fecha o #511", "close"),
])
def test_the_neighbouring_gestures_are_untouched(phrase, intent):
    assert match_intent(phrase)[0] == intent, match_intent(phrase)


# ── 3. the staged act: shown verbatim, gated, and fingerprinted by its own sentence ────────────
class _Result:
    def __init__(self, ok=True, detail="", ref="", existed=False):
        self.ok, self.detail, self.ref, self.existed = ok, detail, ref, existed
        self.url, self.merged = "", True


class _Req:
    def __init__(self, number=6, status="accepted"):
        self.number, self.status = number, status
        self.title, self.slug, self.path = "Portal do cliente", "portal", "0006-portal.md"

    @property
    def is_live(self):
        return self.status not in ("superseded", "dropped")

    @property
    def is_promise(self):
        return self.status == "accepted"


class _Product:
    def __init__(self, admins):
        self.admins = list(admins)
        self.agent_name, self.docs_repo, self.channel_id = "Nina", "a/docs", "C1"
        self.enabled, self.docs_branch = True, "main"


class _Project:
    name, language = "books", "pt-BR"

    def __init__(self, admins=("UADM",)):
        self.product = _Product(list(admins))


class _Module:
    def __init__(self, req=None, *, records=None):
        self.reqs = [req if req is not None else _Req()]
        self.recorded = None
        self._records = records or _Result(ok=True, ref="0006-portal.md")

    def context(self):
        from types import SimpleNamespace

        reqs = self.reqs

        class _Corpus:
            def by_number(self, n):
                return next((r for r in reqs if r.number == n), None)

        return SimpleNamespace(available=True, corpus=_Corpus(), reason="")

    def record_decision(self, number, *, decision, actor, where=""):
        self.recorded = (number, decision, actor, where)
        return self._records

    def confirmed(self, *_a, **_k):
        return "neither"

    def settle_acceptance(self, _t):
        return None


@pytest.fixture(autouse=True)
def _clean_stage(monkeypatch):
    # THE STATE LIVES IN `openfactory/product/staging.py` NOW (#98 slice 3), so isolation is
    # applied THERE. Rebinding the re-export on `product_channel` would leave the code
    # reading the original dict: the fixture would look like it isolates and would not,
    # which is how a staged proposal leaked into the next test when this move was first
    # attempted — with the symptom landing far from the cause.
    from openfactory.product import staging as _staging
    monkeypatch.setattr(_staging, "_PENDING", {})
    monkeypatch.setattr(_staging, "_EXPIRED_TOMBSTONES", {})
    from openfactory.memory import transcript

    monkeypatch.setattr(transcript, "record", lambda *a, **k: "")
    monkeypatch.setattr(transcript, "recent", lambda *a, **k: [])
    yield


def test_the_whole_gesture_reaches_the_write_through_the_channel():
    project, module = _Project(), _Module()

    asked = pc.handle(project, text="registra no requisito 6 que o corte é dia 25",
                      user="UADM", thread="C1", channel="C1", module=module)
    assert module.recorded is None, "it wrote before anybody confirmed"
    assert "o corte é dia 25" in asked, (
        f"the sentence to be written was not shown back verbatim: {asked}")

    said = pc.handle(project, text="sim", user="UADM", thread="C1", channel="C1", module=module)

    assert module.recorded is not None, "the confirmation reached nothing"
    number, decision, actor, where = module.recorded
    assert (number, decision, actor) == (6, "o corte é dia 25", "UADM"), module.recorded
    assert "produto" in where, f"the provenance says nothing a reader can use: {where!r}"
    assert "requisito 6" in said and "documento" in said, said


def test_the_confirmation_says_the_promise_is_UNCHANGED():
    """A person who confirms a decision believing they amended the requirement has agreed to
    something they did not mean. The two acts are one message apart in a chat window."""
    asked = pc.handle(_Project(), text="registra no requisito 6 que o corte é dia 25",
                      user="UADM", thread="C1", channel="C1", module=_Module())

    assert "não muda o que o requisito promete" in asked, asked


def test_a_NON_APPROVER_cannot_record_a_decision():
    project, module = _Project(admins=["UADM"]), _Module()
    pc.remember("C1", {"kind": "decision", "number": 6, "channel": "C1",
                       "decision": "o corte é dia 25"})

    pc.handle(project, text="sim", user="UOUTRO", thread="C1", channel="C1", module=module)

    assert module.recorded is None, "somebody who could not confirm wrote into the document"


def test_a_requirement_that_NO_LONGER_HOLDS_is_refused_with_a_way_forward():
    module = _Module(_Req(status="dropped"))

    said = pc.handle(_Project(), text="registra no requisito 6 que o corte é dia 25",
                     user="UADM", thread="C1", channel="C1", module=module)

    assert pc.pending_for("C1") is None, "it staged a write into a document nobody executes"
    assert "qual requisito" in said.lower(), f"a refusal with no way forward: {said}"


def test_TWO_DECISIONS_on_one_requirement_never_share_a_button():
    """The exact race the fingerprint exists for, on the newest branch that can lose it. Without
    the sentence in the summary both entries hash identically, so the button posted for the first
    records the second — into a register whose whole value is that nobody edits it afterwards."""
    first = {"kind": "decision", "number": 6, "channel": "C1", "decision": "o corte é dia 25"}
    second = {"kind": "decision", "number": 6, "channel": "C1", "decision": "o corte é dia 30"}

    assert pc.proposal_token("C1", first) != pc.proposal_token("C1", second), (
        "one button would perform either decision")
