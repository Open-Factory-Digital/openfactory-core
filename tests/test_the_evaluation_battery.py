"""The product role's evaluation battery — #266 slice 0, ADR-0051 decision 9.

WHAT IS PINNED HERE is the instrument, never a score: the score needs a live model and the
product owner's questions, and neither belongs in `make test`. So every question in this file is
TEST DATA, written to exercise the machinery — the shipped question file is empty, and the first
test below says so.

  - the question file's format: every shape it accepts, every entry it refuses, and a refusal that
    names the question and says whose move it is;
  - the scorer, on canned answers: right, wrong, uncited, a wrong abstention and a right one —
    each verdict saying who decided it, and the judge asked only what a string cannot answer;
  - the runner, with the model scripted at the harness boundary, through `engine.turn` over the
    real fixture — and the dated record it writes;
  - the fixture, loaded as a product the module accepts;
  - the two refusals: an empty battery, and a live run where none may happen.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from openfactory.contracts import AgentRunResult
from openfactory.product.evaluation import __main__ as cli
from openfactory.product.evaluation.battery import (
    NO_QUESTIONS,
    Battery,
    BatteryRefused,
    Claim,
    Question,
    Spellings,
    load_battery,
)
from openfactory.product.evaluation.run import (
    DEFAULT_FIXTURE,
    SPEAKERS,
    LiveRunRefused,
    isolated,
    load_fixture,
    run,
    write_record,
)
from openfactory.product.evaluation.score import (
    DETERMINISTIC,
    JUDGE,
    NOT_APPLICABLE,
    UNDECIDED,
    judge_prompt,
    score,
    totals,
)

ROOT = Path(__file__).resolve().parent.parent
SHIPPED = DEFAULT_FIXTURE / "questions.yaml"
REMINDERS = "context/requirements/0002-payment-reminders.md"


def _q(**kw) -> Question:
    """A test question: known by default, about the reminder requirement."""
    base = {"id": "first-reminder", "question": "When does the first reminder go out?",
            "facts": ["7 days"], "sources": [REMINDERS]}
    return Question(**{**base, **kw})


def _unknown(**kw) -> Question:
    base = {"id": "card-payments", "question": "Can a customer pay by card?",
            "expect_unknown": True}
    return Question(**{**base, **kw})


class _Judge:
    """A judge that answers with the text it was given, and counts what it was asked."""

    def __init__(self, reply: str | None = None, *, raises: bool = False) -> None:
        self.reply, self.raises, self.asked = reply, raises, []

    def __call__(self, prompt: str) -> str | None:
        self.asked.append(prompt)
        if self.raises:
            raise RuntimeError("the judge's harness died")
        return self.reply


# ══ 1. the question file ═══════════════════════════════════════════════════════════════════════

def test_the_shipped_question_file_is_valid_and_holds_NO_question():
    """Decision 9: the questions are the product owner's. The file ships with its format and
    nothing in it — a question here written by the implementer would be the split undone."""
    battery = load_battery(SHIPPED, fixture=DEFAULT_FIXTURE)

    assert battery.questions == []


def test_the_shipped_file_explains_its_format_before_anything_else():
    """The header is the format's documentation where the author is standing: every key, and who
    writes which half."""
    text = SHIPPED.read_text(encoding="utf-8")
    header = text.split("\nquestions:", 1)[0]

    assert all(line.startswith("#") or not line.strip() for line in header.splitlines())
    for key in ("id:", "question:", "audience:", "facts:", "any:", "claim:", "must_not:",
                "sources:", "cited_as:", "expect_unknown:"):
        assert key in header, f"the header does not show `{key}`"
    assert "decision 9" in header


def test_a_whole_question_loads_with_every_shape_of_fact(tmp_path):
    f = tmp_path / "q.yaml"
    f.write_text(
        "questions:\n"
        "  - id: first-reminder\n"
        "    question: When does the first reminder go out?\n"
        "    facts:\n"
        "      - 7 days\n"
        "      - any: [due date, overdue, 30]\n"
        "      - claim: it goes out a week after the invoice was due\n"
        "    must_not: [14 days]\n"
        "    sources:\n"
        f"      - {REMINDERS}\n"
        "      - path: source/larkledger/reminders.py\n"
        "        cited_as: [reminder schedule, 21]\n"
        "  - id: card-payments\n"
        "    question: Can a customer pay by card?\n"
        "    audience: product admin\n"
        "    expect_unknown: true\n"
        "    must_not: ['yes', 50]\n")

    one, two = load_battery(f, fixture=DEFAULT_FIXTURE).questions

    assert one.audience == "client", "an audience left out is the client (decision 8)"
    assert one.facts == [Spellings(any=["7 days"]), Spellings(any=["due date", "overdue", "30"]),
                         Claim(claim="it goes out a week after the invoice was due")]
    assert [s.path for s in one.sources] == [REMINDERS, "source/larkledger/reminders.py"]
    assert one.sources[1].cited_as == ["reminder schedule", "21"]
    assert (two.audience, two.expect_unknown, two.facts, two.sources) == \
        ("product admin", True, [], [])
    assert two.must_not == [Spellings(any=["yes"]), Spellings(any=["50"])], (
        "a bare number is the spelling a person typed")


def test_an_unquoted_yes_is_refused_rather_than_read_as_a_boolean(tmp_path):
    """YAML turns `yes` into True — no spelling of which is what the author meant."""
    f = tmp_path / "q.yaml"
    f.write_text("questions:\n  - id: card-payments\n    question: Card?\n"
                 "    expect_unknown: true\n    must_not: [yes]\n")

    with pytest.raises(BatteryRefused, match="put it in quotes"):
        load_battery(f)


def test_a_question_with_NO_expected_answer_yet_is_refused_naming_whose_it_is(tmp_path):
    """The product owner's half without the implementer's is not a question the role got wrong —
    scoring it would put an unfinished key into the role's number."""
    f = tmp_path / "q.yaml"
    f.write_text("questions:\n  - id: late-fees\n    question: Do we charge late fees?\n")

    with pytest.raises(BatteryRefused) as refused:
        load_battery(f)

    said = str(refused.value)
    assert "'late-fees'" in said and "implementer" in said and "decision 9" in said


@pytest.mark.parametrize("entry, says", [
    ({"audience": "manager"}, "audience"),
    ({"asked_by": "someone"}, "asked_by"),
    ({"id": "First Reminder"}, "is not an id"),
    ({"sources": ["requirements/0002-payment-reminders.md"]}, "is not a path in the fixture"),
    ({"sources": ["context/../secrets.md"]}, "is not a path in the fixture"),
    ({"sources": []}, "no source"),
    ({"facts": []}, "no fact"),
    ({"expect_unknown": True}, "no facts and no sources"),
])
def test_an_entry_the_format_does_not_allow_is_refused_by_name(tmp_path, entry, says):
    import yaml

    q = {"id": "first-reminder", "question": "When?", "facts": ["7 days"],
         "sources": [REMINDERS], **entry}
    f = tmp_path / "q.yaml"
    f.write_text(yaml.safe_dump({"questions": [q]}))

    with pytest.raises(BatteryRefused) as refused:
        load_battery(f)

    assert says in str(refused.value), str(refused.value)


def test_two_questions_with_one_id_are_refused(tmp_path):
    f = tmp_path / "q.yaml"
    one = ("  - id: same\n    question: q\n    facts: [a]\n"
           f"    sources: [{REMINDERS}]\n")
    f.write_text("questions:\n" + one + one)

    with pytest.raises(BatteryRefused, match="used twice"):
        load_battery(f)


def test_an_expected_source_the_fixture_does_not_hold_is_refused(tmp_path):
    """A typo in a source would fail every answer to it as uncited and blame the role."""
    f = tmp_path / "q.yaml"
    f.write_text("questions:\n  - id: q1\n    question: q\n    facts: [a]\n"
                 "    sources: [context/requirements/0009-nothing.md]\n")

    load_battery(f)                                         # the format alone accepts it
    with pytest.raises(BatteryRefused, match="0009-nothing.md"):
        load_battery(f, fixture=DEFAULT_FIXTURE)


def test_a_file_that_is_not_yaml_or_not_a_mapping_is_refused_with_its_path(tmp_path):
    bad, listed = tmp_path / "bad.yaml", tmp_path / "list.yaml"
    bad.write_text("questions: [\n")
    listed.write_text("- id: x\n")

    for f, says in ((bad, "not valid YAML"), (listed, "must be a mapping")):
        with pytest.raises(BatteryRefused) as refused:
            load_battery(f)
        assert str(f) in str(refused.value) and says in str(refused.value)


# ══ 2. the scorer, on canned answers ═══════════════════════════════════════════════════════════

def test_a_RIGHT_answer_passes_all_three_and_no_model_is_asked():
    judge = _Judge()
    s = score(_q(), "The first reminder goes out 7 days after the due date (REQ-0002).",
              judge=judge)

    assert (s.correct.passed, s.cited.passed, s.abstained_correctly.passed) == (True, True, True)
    assert {s.correct.decided_by, s.cited.decided_by, s.abstained_correctly.decided_by} == \
        {DETERMINISTIC}
    assert judge.asked == [], "a string comparison answered everything; the judge was asked"


@pytest.mark.parametrize("answer", [
    "Seven days late — **7** DAYS after the due date, as requirement 2 says.",
    "Aos 7 days, conforme o requisito 2.",
    "REQ-2: 7 days.",
    "req 0002 says 7 days",
])
def test_a_fact_and_a_requirement_are_recognised_however_they_are_spelled(answer):
    s = score(_q(), answer)

    assert s.correct.passed is True, s.correct.why
    assert s.cited.passed is True, s.cited.why


def test_a_WRONG_answer_fails_correct_and_says_what_is_missing():
    s = score(_q(), "The first reminder goes out 14 days after the due date (REQ-0002).")

    assert s.correct.passed is False and s.correct.decided_by == DETERMINISTIC
    assert "missing: 7 days" in s.correct.why
    assert s.cited.passed is True, "a wrong answer can still cite the right place"


def test_seven_days_is_not_found_inside_seventeen():
    assert score(_q(), "It goes out 17 days late (REQ-0002).").correct.passed is False


def test_saying_what_it_must_not_fails_correct_even_with_every_fact_there():
    s = score(_q(must_not=["14 days"]), "7 days, and again at 14 days (REQ-0002).")

    assert s.correct.passed is False
    assert "says what it must not: 14 days" in s.correct.why


def test_an_UNCITED_answer_is_correct_and_not_cited():
    s = score(_q(), "The first reminder goes out 7 days after the due date.")

    assert s.correct.passed is True
    assert s.cited.passed is False and s.cited.decided_by == DETERMINISTIC
    assert REMINDERS in s.cited.why


def test_requirement_twenty_is_not_requirement_two():
    assert score(_q(), "7 days, see REQ-0020.").cited.passed is False


def test_a_code_source_is_cited_by_its_path_or_its_file_name_and_a_named_spelling_counts():
    q = _q(sources=["source/larkledger/reminders.py",
                    {"path": "context/domain/glossary.md", "cited_as": ["the glossary"]}])

    assert score(q, "7 days — larkledger/reminders.py; see the glossary.").cited.passed is True
    assert score(q, "7 days — reminders.py; the glossary says so.").cited.passed is True
    assert score(q, "7 days — reminders.py.").cited.passed is False


def test_a_WRONG_abstention_fails_abstained_correctly():
    """A known answer, and the role said it does not know. With no judge the phrase decides."""
    s = score(_q(), "I don't know when the first reminder goes out.")

    assert s.abstained is True
    assert s.abstained_correctly.passed is False
    assert s.abstained_correctly.decided_by == DETERMINISTIC
    assert s.correct.passed is False


def test_a_phrase_that_counts_AGAINST_the_role_is_the_judge_s_to_confirm():
    """"I could not find X, but it is 7 days" answered. The phrase list sees an abstention; since
    that reading would fail the role, the judge decides."""
    answer = "I could not find the email template, but the first reminder is 7 days late (REQ-2)."
    answered, abstained = _Judge('{"abstains": false}'), _Judge('{"abstains": true}')

    kept = score(_q(), answer, judge=answered)
    failed = score(_q(), answer, judge=abstained)

    assert (kept.abstained_correctly.passed, kept.abstained_correctly.decided_by) == (True, JUDGE)
    assert (failed.abstained_correctly.passed, failed.abstained_correctly.decided_by) == \
        (False, JUDGE)
    assert "## Abstention" in answered.asked[0]


def test_a_RIGHT_abstention_passes_and_cites_nothing_it_was_not_asked_to():
    judge = _Judge()
    s = score(_unknown(), "I do not know — nothing I can read says how customers pay.",
              judge=judge)

    assert (s.correct.passed, s.correct.decided_by) == (True, DETERMINISTIC)
    assert (s.abstained_correctly.passed, s.abstained_correctly.decided_by) == \
        (True, DETERMINISTIC)
    assert (s.cited.passed, s.cited.decided_by) == (None, NOT_APPLICABLE)
    assert judge.asked == []


def test_an_abstention_in_other_words_is_found_by_the_judge():
    judge = _Judge('{"abstains": true}')
    s = score(_unknown(), "Nothing written covers card payments yet.", judge=judge)

    assert (s.abstained_correctly.passed, s.abstained_correctly.decided_by) == (True, JUDGE)
    assert (s.correct.passed, s.correct.decided_by) == (True, JUDGE)


def test_an_answer_to_a_question_nobody_can_answer_fails_correct_and_abstention():
    s = score(_unknown(), "Yes, customers can pay by card.", judge=_Judge('{"abstains": false}'))

    assert s.correct.passed is False and s.abstained_correctly.passed is False
    assert "right answer is" in s.correct.why


def test_a_tempting_guess_under_must_not_fails_even_when_it_also_hedges():
    s = score(_unknown(must_not=["by card"]), "I don't know; probably by card.")

    assert s.abstained_correctly.passed is True
    assert s.correct.passed is False and "by card" in s.correct.why


def test_a_CLAIM_is_decided_by_the_judge_and_only_the_claims_are_sent():
    q = _q(facts=["7 days", {"claim": "the owner is told after the second reminder"}],
           must_not=[{"claim": "a third reminder is sent"}])
    judge = _Judge('{"states": [true], "asserts": [false]}')

    s = score(q, "7 days late the first goes out; after the second, the owner hears (REQ-0002).",
              judge=judge)

    assert (s.correct.passed, s.correct.decided_by) == (True, JUDGE)
    (prompt,) = judge.asked
    assert "1. the owner is told after the second reminder" in prompt
    assert "1. a third reminder is sent" in prompt
    assert "7 days" not in prompt.split("## Statements", 1)[1], "a spelling was sent to the judge"


def test_a_claim_the_judge_says_is_missing_fails_correct():
    q = _q(facts=["7 days", {"claim": "the owner is told after the second reminder"}])
    s = score(q, "7 days (REQ-0002).", judge=_Judge('{"states": [false]}'))

    assert (s.correct.passed, s.correct.decided_by) == (False, JUDGE)
    assert "the owner is told" in s.correct.why


@pytest.mark.parametrize("judge", [
    None,
    _Judge(None),
    _Judge("I think it says so."),
    _Judge('{"states": [true, true]}'),
    _Judge('{"states": ["yes"]}'),
    _Judge(raises=True),
], ids=["no-judge", "no-answer", "prose", "wrong-length", "not-a-boolean", "raises"])
def test_a_verdict_the_judge_could_not_give_is_UNDECIDED_never_a_pass_or_a_fail(judge):
    q = _q(facts=["7 days", {"claim": "the owner is told after the second reminder"}])
    s = score(q, "7 days (REQ-0002).", judge=judge)

    assert (s.correct.passed, s.correct.decided_by) == (None, UNDECIDED)
    assert s.cited.passed is True, "what a string decides is decided whatever the judge did"


def test_a_forbidden_claim_the_judge_finds_fails_correct():
    q = _q(must_not=[{"claim": "a third reminder is sent"}])
    s = score(q, "7 days, then 21, then weekly (REQ-0002).", judge=_Judge('{"asserts": [true]}'))

    assert (s.correct.passed, s.correct.decided_by) == (False, JUDGE)
    assert "says what it must not: a third reminder is sent" in s.correct.why


def test_an_abstention_the_judge_could_not_rule_on_is_UNDECIDED():
    """No phrase where "I do not know" was expected, and the judge gave nothing readable: whether
    the role abstained is not known, so neither is whether it was right."""
    s = score(_unknown(), "Card payments arrive next year.", judge=_Judge(None))

    assert s.abstained is None
    assert (s.abstained_correctly.passed, s.abstained_correctly.decided_by) == (None, UNDECIDED)
    assert (s.correct.passed, s.correct.decided_by) == (None, UNDECIDED)


def test_a_deterministic_failure_is_final_whatever_the_judge_says():
    q = _q(facts=["7 days", {"claim": "the owner is told"}])
    s = score(q, "14 days (REQ-0002).", judge=_Judge('{"states": [true]}'))

    assert (s.correct.passed, s.correct.decided_by) == (False, DETERMINISTIC)


def test_the_judge_is_asked_only_the_sections_an_answer_needs():
    only_abstention = judge_prompt(_unknown(), "x", claims=[], forbidden=[], abstention=True)
    only_claims = judge_prompt(_q(), "x", claims=["a"], forbidden=[], abstention=False)

    assert "## Abstention" in only_abstention and "## Statements" not in only_abstention
    assert '{"abstains": true or false}' in only_abstention
    assert "## Statements" in only_claims and "## Abstention" not in only_claims
    assert '"states": [1 booleans, in order]' in only_claims


def test_the_totals_count_each_verdict_apart():
    right = score(_q(), "7 days (REQ-0002).")
    uncited = score(_q(), "7 days.")
    abstained = score(_unknown(), "I don't know.")
    undecided = score(_q(facts=[{"claim": "x"}]), "7 days (REQ-0002).")

    t = totals([right, uncited, abstained, undecided])

    assert t["correct"].model_dump() == {"passed": 3, "failed": 0, "undecided": 1,
                                         "not_applicable": 0}
    assert t["cited"].model_dump() == {"passed": 2, "failed": 1, "undecided": 0,
                                       "not_applicable": 1}
    assert t["abstained_correctly"].model_dump() == {"passed": 4, "failed": 0, "undecided": 0,
                                                     "not_applicable": 0}


# ══ 3. the fixture is a product the module accepts ═════════════════════════════════════════════

def test_the_fixture_loads_as_a_product_the_module_accepts(tmp_path):
    """Through the product loader, as a real one-machine product: the three declarations agree,
    the corpus and the glossary parse clean, decisions are recorded, and the code is mounted."""
    from openfactory.product.module import ProductModule

    with isolated(tmp_path):
        project, ctx = load_fixture(DEFAULT_FIXTURE, tmp_path)
        module = ProductModule(project, context=ctx)
        mounted = module.mounted()
        readable = (Path(module._combined) / mounted["code"] / "larkledger" / "reminders.py")\
            .is_file()
        module.release()

    assert ctx.available, ctx.reason
    assert ctx.link.kind == "ok" and ctx.link.warnings == []
    assert [r.number for r in ctx.corpus.requirements] == [1, 2, 3]
    assert ctx.corpus.errors == [] and ctx.domain.findings == []
    assert [r.has_decisions for r in ctx.corpus.requirements] == [True, True, False]
    assert {f.term for f in ctx.domain.facts} >= {"Due date", "Payment term"}
    assert mounted["code"], "the role would be told it cannot open the code"
    assert readable, "the code is named in the prompt and its files are not in the view"


def test_the_run_leaves_this_process_s_stores_as_it_found_them(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_METRICS_TABLE", "a-real-table")
    before = {k: os.environ.get(k) for k in ("OPENFACTORY_METRICS_SINK", "OPENFACTORY_REPO_CACHE",
                                              "OPENFACTORY_LOG_DIR", "OPENFACTORY_BOARD_DB",
                                              "OPENFACTORY_METRICS_TABLE")}

    with isolated(tmp_path):
        assert os.environ["OPENFACTORY_METRICS_SINK"] == "null"
        assert "OPENFACTORY_METRICS_TABLE" not in os.environ, "the run would write a real table"
        assert os.environ["OPENFACTORY_REPO_CACHE"].startswith(str(tmp_path))

    assert {k: os.environ.get(k) for k in before} == before


# ══ 4. the runner, with the model scripted, through the one door ═══════════════════════════════

class _Harness:
    """A harness double: `answer(prompt)` decides the text, every prompt is kept."""

    name = "scripted"
    model = "scripted-model"

    def __init__(self, answer) -> None:
        self.answer, self.prompts = answer, []

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.prompts.append((phase, prompt))
        return AgentRunResult(ok=True, summary=self.answer(prompt))


def _role_answers(prompt: str) -> str:
    question = prompt.rsplit("## Question", 1)[-1]
    if "first reminder" in question:
        return "The first reminder goes out 7 days after the due date (REQ-0002)."
    if "invoice hold" in question:
        return "Up to 50 lines."
    return "Nothing written covers card payments."


_BATTERY = Battery(questions=[
    {"id": "first-reminder", "question": "When does the first reminder go out?",
     "facts": ["7 days"], "sources": [REMINDERS]},
    {"id": "max-lines", "question": "How many lines can one invoice hold?",
     "audience": "engineer", "facts": ["50"], "sources": ["source/larkledger/invoices.py"]},
    {"id": "card-payments", "question": "Can a customer pay by card?",
     "audience": "product admin", "expect_unknown": True},
])


def test_the_runner_asks_every_question_through_the_engine_and_records_the_verdicts(
        tmp_path, monkeypatch):
    from openfactory.product import engine

    doors: list = []
    real = engine.turn

    def door(project, message, *, module=None):
        doors.append(message)
        return real(project, message, module=module)

    monkeypatch.setattr(engine, "turn", door)
    role, judge = _Harness(_role_answers), _Harness(lambda p: '{"abstains": true}')

    record = run(_BATTERY, fixture=DEFAULT_FIXTURE, workdir=tmp_path, agent=role, judge=judge)

    # through the one door, one conversation per question, spoken by the audience's person
    assert [m.text for m in doors] == [q.question for q in _BATTERY.questions]
    assert len({m.conversation for m in doors}) == 3
    assert [m.speaker for m in doors] == [SPEAKERS["client"], SPEAKERS["engineer"],
                                          SPEAKERS["product admin"]]
    # the REAL role wrote the prompt, over the fixture: its requirement index, its code mounted
    phase, prompt = role.prompts[0]
    assert phase == "product_answer"
    assert "REQ-0002" in prompt and "0002-payment-reminders.md" in prompt
    assert "src/larkledger/" in prompt
    # the verdicts, and who decided each
    first, lines, cards = record.answers
    assert first.answer == "The first reminder goes out 7 days after the due date (REQ-0002)."
    assert (first.correct.passed, first.cited.passed, first.abstained_correctly.passed) == \
        (True, True, True)
    assert (lines.correct.passed, lines.cited.passed) == (True, False)
    assert (cards.abstained_correctly.passed, cards.abstained_correctly.decided_by) == \
        (True, JUDGE)
    assert [r["kind"] for r in first.replies][-1] == "answer"
    assert record.totals["cited"].model_dump() == {"passed": 1, "failed": 1, "undecided": 0,
                                                   "not_applicable": 1}
    # what answered, and from which commit
    assert (record.role.harness, record.role.model) == ("scripted", "scripted-model")
    assert re.fullmatch(r"[0-9a-f]{40}", record.commit)
    assert record.fixture == "larkledger"


def test_the_record_is_written_dated_as_json_and_a_short_summary(tmp_path):
    role, judge = _Harness(_role_answers), _Harness(lambda p: '{"abstains": true}')
    record = run(_BATTERY, fixture=DEFAULT_FIXTURE, workdir=tmp_path / "run", agent=role,
                 judge=judge, questions_file=SHIPPED)

    as_json, as_md = write_record(record, tmp_path / "results")

    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d{6}Z-larkledger\.json", as_json.name)
    assert as_md.name == as_json.name.replace(".json", ".md")
    import json

    data = json.loads(as_json.read_text())
    assert data["commit"] == record.commit and data["role"]["model"] == "scripted-model"
    assert data["questions_file"] == "tests/fixtures/evaluation/larkledger/questions.yaml"
    assert [a["id"] for a in data["answers"]] == ["first-reminder", "max-lines", "card-payments"]
    summary = as_md.read_text()
    assert record.commit in summary and "scripted-model" in summary
    assert "| cited | 1 | 1 | 0 | 1 |" in summary
    assert "| max-lines | engineer | yes · deterministic | no · deterministic |" in summary


# ══ 5. the two refusals ════════════════════════════════════════════════════════════════════════

def test_an_EMPTY_battery_refuses_with_the_sentence_and_writes_nothing(tmp_path, capsys):
    """The shipped file, run as `make eval-product` runs it."""
    code = cli.main(["--results", str(tmp_path / "results")])

    assert code != 0
    assert NO_QUESTIONS in capsys.readouterr().err
    assert NO_QUESTIONS == ("the battery has no questions yet; the product owner writes them "
                            "(decision 9)")
    assert not (tmp_path / "results").exists()


def test_the_runner_itself_refuses_an_empty_battery(tmp_path):
    with pytest.raises(BatteryRefused, match=re.escape(NO_QUESTIONS)):
        run(Battery(), fixture=DEFAULT_FIXTURE, workdir=tmp_path,
            agent=_Harness(_role_answers), judge=_Harness(lambda p: "{}"))


@pytest.fixture
def _no_live_model(monkeypatch):
    """Whatever the runner does, building a real harness here fails the test loudly — so a
    refusal that stopped working could never spend tokens on its way to going red."""
    def refuse(*_a, **_k):
        raise AssertionError("a LIVE harness was built inside the test suite")

    monkeypatch.setattr("openfactory.adapters.agent.registry.build_product", refuse)
    monkeypatch.setattr("openfactory.adapters.agent.registry.build_asker", refuse)


@pytest.mark.usefixtures("_no_live_model")
@pytest.mark.parametrize("scripted", ["neither", "only-the-role", "only-the-judge"])
def test_a_LIVE_run_inside_the_suite_is_refused_by_name(tmp_path, scripted):
    role = _Harness(_role_answers) if scripted == "only-the-role" else None
    judge = _Harness(lambda p: "{}") if scripted == "only-the-judge" else None

    with pytest.raises(LiveRunRefused, match="never runs inside the test suite"):
        run(_BATTERY, fixture=DEFAULT_FIXTURE, workdir=tmp_path, agent=role, judge=judge)


def _rules() -> dict[str, tuple[list[str], list[str]]]:
    """`target -> (prerequisites, recipe lines)`, read off the Makefile."""
    rules: dict[str, tuple[list[str], list[str]]] = {}
    current = None
    for line in (ROOT / "Makefile").read_text().splitlines():
        rule = re.match(r"^([A-Za-z0-9_-]+):(?!=)([^#]*)", line)
        if rule:
            current = rule.group(1)
            rules[current] = (rule.group(2).split(), [])
        elif line.startswith("\t") and current:
            rules[current][1].append(line.strip())
        elif line.strip() and not line.startswith("#"):
            current = None
    return rules


def test_make_test_and_make_check_never_reach_the_battery():
    """The battery spends tokens; `make test` runs on every commit. Nothing `test` or `check`
    reaches — prerequisite or recipe — may be the battery or run its module."""
    rules = _rules()
    reached, todo = set(), ["test", "check"]
    while todo:
        target = todo.pop()
        if target in reached:
            continue
        reached.add(target)
        todo += [p for p in rules.get(target, ([], []))[0] if p in rules]

    assert "eval-product" not in reached
    recipes = [line for t in reached for line in rules[t][1]]
    assert not [line for line in recipes if "evaluation" in line or "eval-product" in line], \
        recipes


def test_the_battery_runs_from_make():
    """Slice 0's acceptance: the battery runs from `make`."""
    rules = _rules()

    assert "eval-product" in rules
    assert rules["eval-product"][1] == ["python -m openfactory.product.evaluation"]


def test_the_cli_refuses_a_fixture_that_is_not_there(tmp_path, capsys):
    """A wheel carries no suite tree — the battery says where it runs rather than a traceback."""
    code = cli.main(["--fixture", str(tmp_path / "nowhere")])

    assert code != 0
    assert "runs from a checkout" in capsys.readouterr().err
