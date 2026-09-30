"""A card the product role opens is drafted from the conversation, checked, judged against a rubric,
and shown whole before the yes (#383).

THE DEFECT, AS IT HAPPENED. A person reported with a screenshot that a page stopped fitting on a
short viewport; the role read the image, found the earlier card about the same page, restated the
defect precisely and proposed a title. The person said "pode criar um card novo e siga para a
correção", confirmed the title, and the card that landed had that sentence as its whole body and its
title cut at 80 characters. Triage then flagged it as having nothing that says when it is done.

What these tests pin, seam by seam:

- the FLOOR refuses the gesture as a body, an over-long title, a card with no done criterion, a
  quote nobody said, and anything the pickup gate would refuse — without spending the judge;
- the VERDICT is computed from the judge's scores in code, and a partial scoring is no scoring;
- the LOOP drafts at most twice, feeds the floor's problems or the judge's findings to the redraft,
  and after two failures stages nothing and asks the judge's question;
- the TEMPLATE and the RUBRIC are the product's when its context repository carries usable ones,
  and a file that cannot be used is refused by name and replaced by the shipped one;
- the ENGINE drafts from this conversation only (never what memory adds from others), shows the
  whole card in the confirmation, and the yes writes exactly the card that was shown.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

import openfactory.product.channel as pc
from openfactory.product import cards
from openfactory.product import engine as engine_module
from openfactory.product.authoring import filed_by_the_product_role, ticket_body
from openfactory.product.cards import (
    ATTEMPTS,
    TITLE_LIMIT,
    CardDraft,
    Rubric,
    compose,
    floor,
    load_rubric,
    load_template,
    render,
    ruling,
    template_problem,
)
from openfactory.product.module import _WHAT_WAS_ASKED, _section_re
from openfactory.product.voice import card_needs, ticket_confirmation
from tests.test_confirmation_by_click import ADMIN, KEY, _project
from tests.the_chat_turn import chat_turn

#: THE FIXTURES BELOW ARE A PORTUGUESE CONVERSATION, so the cards they draft use the pt-BR layout
#: (#429) — the default layout is English.
PT = "pt-BR"

GESTURE = "pode criar um card novo e siga para a correção"

CONVERSATION = (
    "## Conversa até aqui (mais antigo primeiro)\n"
    "- pessoa: em telas menores a página inicial não é responsiva, corta a dica e às vezes o "
    "botão Criar some\n"
    "- você: na altura de ~646 px a caixa de texto empurra a dica e o botão Criar para fora da "
    "área visível, sem rolagem. O cartão #41 registrou só a dica; o botão é informação nova.")

GOOD = {
    "title": "Página inicial: botão Criar e dica fora da vista em telas baixas",
    "objective": "O botão Criar e a dica continuam alcançáveis em telas de pouca altura.",
    "description": "Com a janela a cerca de 646 px de altura, a caixa de texto da página inicial "
                   "empurra a dica e o botão Criar para fora da área visível, e a página não "
                   "rola. O cartão #41 registrou apenas a dica.",
    "done_when": ["Com 646 px de altura, o botão Criar e a dica ficam visíveis ou alcançáveis "
                  "por rolagem"],
    "out_of_scope": [],
    "related": [{"ref": "#41", "why": "mesma tela; registrou só a dica e foi fechado"}],
    "source_quote": "às vezes o botão Criar some",
    "questions": [],
}


def _scores(level: int, **low) -> dict:
    rubric = load_rubric()
    return {c.id: low.get(c.id, level) for c in rubric.criteria}


def _judge_says(level: int = 5, *, critical=(), findings=(), ask="", **low):
    return json.dumps({"scores": _scores(level, **low), "evidence": {}, "critical": list(critical),
                       "findings": list(findings), "ask": ask})


@pytest.fixture(autouse=True)
def _clean():
    pc._PENDING.clear()
    cards._OPEN.clear()
    yield
    pc._PENDING.clear()
    cards._OPEN.clear()


# ── the shipped files ──────────────────────────────────────────────────────────────────────────

def test_the_shipped_rubric_reads_and_every_criterion_has_a_rung_for_every_level():
    """A ladder with a gap is how a structurally complete, substantively empty card scores high:
    the judge has no rung that names it, and takes the next one up."""
    rubric = load_rubric()

    assert rubric.source == "shipped" and rubric.criteria
    for c in rubric.criteria:
        assert set(c.levels) == set(range(rubric.low, rubric.high + 1)), c.id
    assert "body_is_the_gesture" in rubric.critical


def test_the_shipped_template_is_one_the_loader_would_accept():
    assert template_problem(load_template()) == ""


def test_the_shipped_files_travel_with_the_package():
    """`pyproject.toml` ships `org_defaults/**/*.md` and `**/*.yaml` — the glob that once dropped
    every role prompt from the wheel. Both card files sit under it."""
    assert (cards._DEFAULTS / cards.RUBRIC_FILE).is_file()
    assert (cards._DEFAULTS / cards.TEMPLATE_FILE).is_file()


# ── render ─────────────────────────────────────────────────────────────────────────────────────

def test_a_section_whose_fields_are_all_empty_is_left_out():
    body = render(CardDraft.from_answer(GOOD), load_template(language=PT))

    assert "## Fora do escopo" not in body
    assert "## Relacionados" in body and "- #41 — mesma tela" in body
    assert "> às vezes o botão Criar some" in body
    assert "- Com 646 px de altura" in body


def test_a_literal_brace_in_a_products_template_is_text():
    body = render(CardDraft(title="t", description="d", done_when=["c"]),
                  "Formato {\"a\": 1}\n\n## O que foi pedido\n\n{description}\n\n"
                  "## Critérios de aceite\n\n{done_when}\n")

    assert '{"a": 1}' in body


# ── the floor ──────────────────────────────────────────────────────────────────────────────────

def _floor(raw: dict, request: str = GESTURE) -> list[str]:
    draft = CardDraft.from_answer(raw)
    return floor(draft, render(draft, load_template(language=PT)), request=request,
                 conversation=CONVERSATION)


def test_a_good_card_clears_the_floor():
    assert _floor(GOOD) == []


def test_the_gesture_as_the_body_is_refused():
    problems = _floor({**GOOD, "description": GESTURE})

    assert any("request to open the card" in p for p in problems)


def test_a_card_with_no_description_is_told_so_rather_than_called_a_gesture():
    problems = _floor({**GOOD, "description": ""})

    assert any("no description of the work" in p for p in problems)
    assert not any("request to open the card" in p for p in problems)


def test_a_title_over_the_bound_is_refused_and_never_cut():
    problems = _floor({**GOOD, "title": "x" * (TITLE_LIMIT + 1)})

    assert any(f"limit is {TITLE_LIMIT}" in p for p in problems)


def test_a_card_that_never_says_when_it_is_done_is_refused_by_the_floor_and_the_gate():
    problems = _floor({**GOOD, "done_when": []})

    assert any("nothing says when" in p for p in problems)
    assert any("pickup gate would refuse" in p for p in problems)


def test_a_quote_nobody_said_is_refused():
    problems = _floor({**GOOD, "source_quote": "o sistema inteiro caiu"})

    assert any("not in the conversation" in p for p in problems)


# ── the verdict ────────────────────────────────────────────────────────────────────────────────

def test_the_verdict_is_computed_from_the_scores_never_read_from_the_judge():
    rubric = load_rubric()

    assert ruling(_judge_says(5), rubric).passed
    low = ruling(_judge_says(5, faithful=2), rubric)
    assert not low.passed and any("floor" in b and "faithful" in b for b in low.because)
    mean = ruling(_judge_says(3), rubric)
    assert not mean.passed and mean.average == 3.0
    critical = ruling(_judge_says(5, critical=["body_is_the_gesture"]), rubric)
    assert not critical.passed and "body_is_the_gesture" in critical.critical


def test_a_partial_or_malformed_scoring_is_no_scoring():
    rubric = load_rubric()
    partial = json.loads(_judge_says(5))
    partial["scores"].pop("faithful")

    assert ruling(json.dumps(partial), rubric) is None
    assert ruling("a card that looks fine to me", rubric) is None
    assert ruling(None, rubric) is None
    out_of_scale = json.loads(_judge_says(5))
    out_of_scale["scores"]["title"] = 9
    assert ruling(json.dumps(out_of_scale), rubric) is None
    as_bool = json.loads(_judge_says(5))
    as_bool["scores"]["title"] = True
    assert ruling(json.dumps(as_bool), rubric) is None


def test_a_critical_failure_the_rubric_does_not_name_is_ignored():
    said = ruling(_judge_says(5, critical=["made_up"]), load_rubric())

    assert said.passed and said.critical == ()


# ── the loop ───────────────────────────────────────────────────────────────────────────────────

class _Script:
    """The role's drafting call, scripted: one answer per call, every prompt kept."""

    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def __call__(self, prompt: str):
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else None


def _compose(draft, judge):
    return compose(draft=draft, judge=judge, rubric=load_rubric(), template=load_template(language=PT),
                   conversation=CONVERSATION, request=GESTURE, reply="Abro o cartão.",
                   title=GOOD["title"], project_name="books")


def test_a_good_first_draft_that_the_judge_passes_is_ready_for_the_yes():
    judged = []
    out = _compose(_Script(GOOD), lambda p: judged.append(p) or _judge_says(5))

    assert out.ok and out.attempts == 1 and out.ruling.passed and not out.unjudged
    assert "## O que foi pedido" in out.card and GESTURE not in out.card
    [prompt] = judged
    assert CONVERSATION.splitlines()[1] in prompt and GOOD["title"] in prompt


def test_the_drafting_prompt_carries_the_conversation_the_reply_and_the_bound():
    script = _Script(GOOD)
    _compose(script, lambda p: _judge_says(5))

    [prompt] = script.prompts
    assert "646 px" in prompt and "Abro o cartão." in prompt and GESTURE in prompt
    assert f"at most {TITLE_LIMIT} characters" in prompt


def test_a_draft_that_fails_the_floor_is_redrafted_with_the_problems_and_no_judge_is_spent():
    script, judged = _Script({**GOOD, "description": GESTURE}, GOOD), []
    out = _compose(script, lambda p: judged.append(p) or _judge_says(5))

    assert out.ok and out.attempts == 2
    assert len(judged) == 1, "the floor's refusal must not cost a judge call"
    assert "request to open the card" in script.prompts[1]


def test_the_judges_findings_reach_the_redraft():
    answers = iter([_judge_says(2, findings=["say which screen size breaks the page"]),
                    _judge_says(5)])
    script = _Script(GOOD, GOOD)
    out = _compose(script, lambda p: next(answers))

    assert out.ok and out.attempts == 2
    assert "say which screen size breaks the page" in script.prompts[1]


def test_two_failures_stage_nothing_and_ask_the_judges_question():
    script = _Script(GOOD, GOOD, GOOD)
    out = _compose(script, lambda p: _judge_says(2, ask="Em qual tamanho de tela isso acontece?"))

    assert not out.ok and out.card == ""
    assert out.ask == "Em qual tamanho de tela isso acontece?"
    # THE NUMBER, NOT THE CONSTANT: a guard that reads `ATTEMPTS` moves with it and cannot see
    # the loop grow — one draft and one redraft is ADR-0006's bound
    assert len(script.prompts) == 2 == ATTEMPTS, "the loop is bounded"


def test_without_a_judges_question_the_drafts_own_questions_are_asked():
    raw = {**GOOD, "questions": ["Acontece também no celular?"]}
    out = _compose(_Script(raw, raw), lambda p: _judge_says(2))

    assert not out.ok and out.ask == "Acontece também no celular?"


def test_no_judge_shows_the_card_marked_unjudged():
    out = _compose(_Script(GOOD), None)

    assert out.ok and out.unjudged and out.ruling is None


def test_an_unreadable_judge_shows_the_card_marked_unjudged(caplog):
    with caplog.at_level(logging.WARNING):
        out = _compose(_Script(GOOD), lambda p: "looks good")

    assert out.ok and out.unjudged
    assert "OPENFACTORY_CARD_JUDGE_UNREADABLE" in caplog.text


def test_a_role_that_never_answers_json_ends_with_no_card_and_no_question():
    out = _compose(_Script(None, None), lambda p: _judge_says(5))

    assert not out.ok and out.draft is None and out.ask == ""


def test_every_verdict_is_logged_with_what_recomputes_it(caplog):
    with caplog.at_level(logging.INFO):
        _compose(_Script(GOOD), lambda p: _judge_says(5, title=4))

    line = next(r.getMessage() for r in caplog.records
                if "OPENFACTORY_CARD_JUDGED" in r.getMessage())
    assert "verdict=pass" in line and "product-card-quality@" in line and '"title": 4' in line


# ── the product's own files ────────────────────────────────────────────────────────────────────

def test_a_products_rubric_in_its_context_repository_is_the_one_used(tmp_path):
    (tmp_path / "cards").mkdir()
    shipped = (cards._DEFAULTS / cards.RUBRIC_FILE).read_text()
    (tmp_path / "cards" / "rubric.yaml").write_text(
        shipped.replace("average: 4.0", "average: 4.5").replace("id: product-card-quality",
                                                                "id: our-cards"))

    rubric = load_rubric(str(tmp_path))

    assert (rubric.id, rubric.average, rubric.source) == ("our-cards", 4.5, "cards/rubric.yaml")


@pytest.mark.parametrize("text", ["- just a list", "criteria: []\n", "scale: {min: 5, max: 1}\n"
                                  "criteria: [{id: a}]\n"])
def test_a_products_rubric_that_cannot_be_used_is_refused_by_name(tmp_path, caplog, text):
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / "rubric.yaml").write_text(text)

    with caplog.at_level(logging.WARNING):
        rubric = load_rubric(str(tmp_path))

    assert rubric.source == "shipped"
    assert "OPENFACTORY_CARD_RUBRIC_REFUSED" in caplog.text


def test_a_products_template_is_used_when_it_keeps_what_every_card_needs(tmp_path):
    (tmp_path / "cards").mkdir()
    own = (f"## Objetivo\n\n{{objective}}\n\n## {_WHAT_WAS_ASKED['request']}\n\n{{description}}"
           "\n\n## Definition of done\n\n{done_when}\n\n## Nota do time\n\nRevisar com o PO.\n")
    (tmp_path / "cards" / "template.md").write_text(own)

    assert load_template(str(tmp_path)) == own


@pytest.mark.parametrize("own, why", [
    ("## O que foi pedido\n\n{description}\n\n## Pronto quando\n\n{done_when}\n", "pickup gate"),
    ("## Descrição\n\n{description}\n\n## Critérios de aceite\n\n{done_when}\n", "correction"),
    ("## O que foi pedido\n\n{description}\n\n## Critérios de aceite\n\n{done_when}\n{owner}\n",
     "owner"),
    ("## O que foi pedido\n\n{description}\n", "done_when"),
])
def test_a_products_template_that_would_lose_the_card_is_refused_by_name(tmp_path, caplog, own,
                                                                          why):
    """A criteria heading the parser does not know would make EVERY card fail the floor, and the
    section a correction rewrites is the one `correct_card` looks for by name."""
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / "template.md").write_text(own)

    with caplog.at_level(logging.WARNING):
        used = load_template(str(tmp_path))

    assert used == (cards._DEFAULTS / cards.TEMPLATE_FILE).read_text()
    assert "OPENFACTORY_CARD_TEMPLATE_REFUSED" in caplog.text and why in caplog.text


def test_a_broken_yaml_file_is_refused_rather_than_losing_the_card(tmp_path, caplog):
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / "rubric.yaml").write_text("criteria: [unclosed")

    assert load_rubric(str(tmp_path)).source == "shipped"


def test_a_rubric_whose_bar_is_outside_its_scale_is_refused():
    with pytest.raises(ValueError, match="outside the scale"):
        Rubric.parse("scale: {min: 1, max: 5}\npass: {average: 7}\ncriteria: [{id: a}]\n")


# ── the engine: the conversation in, the whole card out, the same card written ─────────────────

class _World:
    """The boundary fake the sibling suite uses, with the drafting verb: its `compose_card` runs
    the REAL loop over a scripted draft and judge, so only the model calls are fakes."""

    def __init__(self, *drafts, judge=None):
        self.script = _Script(*drafts)
        self.judge = judge if judge is not None else (lambda p: _judge_says(5))
        self.composed: list[dict] = []
        self.filed: list[dict] = []

    def settle_acceptance(self, text):
        return None

    def close_decisions_answered(self, *, channel=""):
        return 0

    def confirmed(self, reply, *, proposal):
        return "neither"

    def context(self):
        return SimpleNamespace(available=True, reason="")

    def answer(self, question, *, context="", conversation="", **_):
        self.answered = getattr(self, "answered", 0) + 1
        return SimpleNamespace(ok=True, is_ticket=True, ticket_title=GOOD["title"],
                               is_defect=False, is_request=False, decisions=[], gesture="",
                               text="Certo — abro o cartão com o que vimos na imagem.",
                               violates=None)

    def compose_card(self, **kw):
        self.composed.append(kw)
        return compose(draft=self.script, judge=self.judge, rubric=load_rubric(),
                       template=load_template(kind=kw.get("kind", "ticket"),
                                              language=kw.get("language")), **kw)

    def file_ticket(self, *, title, described, reported_by, source="", card=""):
        self.filed.append({"title": title, "described": described, "card": card})
        return SimpleNamespace(ok=True, ref="#77", url="https://forge/x/77", detail="",
                               existed=False)


@pytest.fixture
def _earlier_turns(monkeypatch):
    """The conversation as the transcript renders it, and what memory adds from OTHER
    conversations — which must reach the answer and never the card."""
    from openfactory.memory import transcript

    monkeypatch.setattr(transcript, "render", lambda *a, **k: CONVERSATION)
    monkeypatch.setattr(engine_module, "_with_elsewhere",
                        lambda project, said, text, **k: f"{said}\n\nELSEWHERE: outra conversa")


def test_the_card_is_drafted_from_this_conversation_and_never_from_another(_earlier_turns):
    world = _World(GOOD)

    chat_turn(_project(), text=GESTURE, user=ADMIN, thread=KEY, module=world)

    [kw] = world.composed
    assert kw["request"] == GESTURE
    assert "646 px" in kw["conversation"]
    assert "ELSEWHERE" not in kw["conversation"], "another conversation must not reach a card"
    assert kw["title"] == GOOD["title"] and "imagem" in kw["reply"]


def test_the_confirmation_shows_the_whole_card_and_the_yes_writes_that_card(_earlier_turns):
    world = _World(GOOD)

    asked = str(chat_turn(_project(), text=GESTURE, user=ADMIN, thread=KEY, module=world))

    staged = pc.find_waiting(KEY, KEY)[1]
    assert staged["kind"] == "ticket" and staged["title"] == GOOD["title"]
    assert staged["card"] in asked, "the person must read the body that will be written"
    assert staged["judged"]["average"] == 5.0
    assert "Confirma" in asked and world.filed == []

    chat_turn(_project(), text="sim", user=ADMIN, thread=KEY, module=world)

    [filed] = world.filed
    assert filed["card"] == staged["card"] and filed["title"] == GOOD["title"]
    assert filed["described"] == GESTURE, "the request travels as the source, not as the body"


def test_a_card_that_fails_twice_stages_nothing_and_asks(_earlier_turns):
    world = _World(GOOD, GOOD, judge=lambda p: _judge_says(2, ask="Qual tela exatamente?"))

    said = str(chat_turn(_project(), text=GESTURE, user=ADMIN, thread=KEY, module=world))

    assert pc.find_waiting(KEY, KEY)[1] is None
    assert card_needs(ask="Qual tela exatamente?", language="pt-BR") in said
    assert world.filed == []


def test_an_unjudged_card_is_shown_with_the_warning(_earlier_turns):
    world = _World(GOOD, judge=lambda p: None)

    said = str(chat_turn(_project(), text=GESTURE, user=ADMIN, thread=KEY, module=world))

    assert "Não consegui revisar este cartão" in said
    assert pc.find_waiting(KEY, KEY)[1]["judged"] == {"unjudged": True,
                                                       "rubric": "product-card-quality@1.0.0"}


def test_the_confirmation_without_a_card_is_the_title_one(lang="pt-BR"):
    """An entry staged by a module that cannot draft — the sibling suite's double — still asks
    with its title, exactly as before."""
    assert "*X*" in ticket_confirmation(title="X", language=lang)


# ── the pen: what is written ───────────────────────────────────────────────────────────────────

def test_the_body_written_is_the_card_under_the_codes_own_lines():
    card = render(CardDraft.from_answer(GOOD), load_template(language=PT))

    body = ticket_body(language=PT, described=GESTURE, reported_by="<@U1>", source="#produto", card=card)

    assert filed_by_the_product_role(body) == "request", "correct_card must still know it"
    assert body.index("**Pedido por:**") < body.index("## Objetivo")
    # the section a correction rewrites, found as a correction finds it — under its pt-BR name here
    assert len(_section_re(_WHAT_WAS_ASKED["request"]).findall(body)) == 1
    assert GESTURE not in body.split("## Nas palavras")[0]


def test_an_over_long_title_is_refused_by_the_pen_and_nothing_is_opened(tmp_path):
    from tests.test_the_product_owner_opens_a_card_as_described import _module, _Tracker

    tracker = _Tracker()
    result = _module(tmp_path, tracker).file_ticket(
        title="y" * (TITLE_LIMIT + 5), described="d", reported_by="<@U1>", tracker=tracker,
        board=None)

    assert not result.ok and tracker.created == []
    assert str(TITLE_LIMIT) in result.detail


def test_the_role_is_told_the_bound_and_to_restate_before_the_marker():
    from pathlib import Path

    src = (Path(cards.__file__).parent / "role.py").read_text(encoding="utf-8")
    at = src.index("IF THEY ASKED YOU TO OPEN A CARD")

    assert "at most 80 characters" in src[at:at + 900]
    assert str(TITLE_LIMIT) == "80", "the prompt's number and the bound must move together"


# ── the module: the loop wired to the role and to the reviewer axis ────────────────────────────

def test_the_module_drafts_in_a_room_with_nothing_to_open_and_judges_on_the_reviewer_axis(
        tmp_path, monkeypatch):
    """The first live card drafted in the role's workspace and spent 27 turns exploring the code
    before writing what the prompt already held. The draft now stands in an empty room, on the
    product role's engine; the judge on the reviewer's."""
    from openfactory.product.config import ProductLink
    from openfactory.product.loader import ProductContext
    from openfactory.product.module import ProductModule
    from tests.test_card_maintenance import COMMIT, DOCS, REQUIREMENTS_DIR, _corpus
    from tests.test_card_maintenance import _project as _module_project

    class _Engine:
        name = "engine"

        def __init__(self):
            self.rooms = []

        def ask(self, *, sandbox, workspace, prompt, phase):
            from pathlib import Path

            self.rooms.append((phase, sorted(p.name for p in Path(workspace.path).iterdir())))
            return SimpleNamespace(ok=True, raw_output=json.dumps(GOOD), result=json.dumps(GOOD),
                                   text=json.dumps(GOOD), cost_usd=None, num_turns=1)

    monkeypatch.setattr("openfactory.adapters.agent.base.final_text",
                        lambda res: getattr(res, "text", ""))
    engine = _Engine()
    ctx = ProductContext(link=ProductLink(active=True, docs_repo=DOCS, kind="ok", reason="fine"),
                         corpus=_corpus(), docs_path=str(tmp_path), docs_commit=COMMIT,
                         requirements_dir=REQUIREMENTS_DIR)
    monkeypatch.setattr(cards, "build_judge", lambda project: pytest.fail("a live judge"))
    judged = []
    module = ProductModule(_module_project(), context=ctx, agent=engine,
                           card_judge=cards.in_a_room(_module_project(), engine,
                                                      cards.JUDGE_PHASE))
    engine_ask = engine.ask
    engine.ask = lambda **kw: judged.append(kw["phase"]) or engine_ask(**kw)

    out = module.compose_card(request=GESTURE, conversation=CONVERSATION, reply="Abro.",
                              language=PT)

    assert out.ok and out.draft.title == GOOD["title"]
    assert engine.rooms == [(cards.DRAFT_PHASE, []), (cards.JUDGE_PHASE, [])], (
        "the draft and the judge each stand in an empty room — and a module handed a harness "
        "judges only with what it was handed, never with a live one")


def test_every_verdict_is_a_row_kept_whatever_the_log_level(monkeypatch):
    """The worker that first ran this logged warnings only, and two blocking verdicts left nothing
    to read back. The verdict is a row in the metrics store, beside the calls' costs."""
    rows = []
    monkeypatch.setattr("openfactory.observability.registry.deployment_metrics_sink",
                        lambda: SimpleNamespace(record=lambda rec: rows.append(rec) or True))

    _compose(_Script({**GOOD, "description": GESTURE}, GOOD),
             lambda p: _judge_says(5, title=4))

    verdicts = [r for r in rows if r.kind == "card_verdict"]
    assert [v.extra["verdict"] for v in verdicts] == ["floor", "pass"]
    assert verdicts[0].extra["problems"] and verdicts[1].extra["scores"]["title"] == 4
    assert verdicts[1].extra["rubric"].startswith("product-card-quality@")


def test_the_judge_never_asks_for_a_name_and_the_role_never_asks_for_the_yes_itself():
    """The first live block asked the person what they call the screen — a name nobody needs to
    build the fix — after the role had already asked "Confirma?" in its own words."""
    from pathlib import Path

    prompt = cards.judge_prompt(load_rubric(), conversation=CONVERSATION, request=GESTURE,
                                card="# t")
    assert "Never for a name, a label or wording" in prompt
    src = (Path(cards.__file__).parent / "role.py").read_text(encoding="utf-8")
    at = src.index("IF THEY ASKED YOU TO OPEN A CARD")
    assert "do NOT ask them to " in src[at:at + 1200]


# ── the answer to a held question goes straight to one redraft ─────────────────────────────────

def _blocked_then(*verdicts):
    """A judge that blocks twice (with a question), then says each of `verdicts` in turn."""
    said = iter([_judge_says(2, ask="Em qual altura de tela isso acontece?",
                             findings=["say at which height the page breaks"])] * 2
                + list(verdicts))
    return lambda p: next(said)


def test_the_answer_to_the_judges_question_goes_straight_to_one_redraft(_earlier_turns):
    """The first live card: the judge blocked twice and asked; the answer was read as a whole new
    turn — the role's full answer, a new gesture, the loop from the first draft: nine calls. Now
    the answer is taken to ONE redraft, and the role's answer is not asked at all."""
    world = _World(GOOD, GOOD, GOOD, judge=_blocked_then(_judge_says(5)))

    asked = str(chat_turn(_project(), text=GESTURE, user=ADMIN, thread=KEY, module=world))
    assert "Em qual altura de tela" in asked and pc.find_waiting(KEY, KEY)[1] is None
    assert world.answered == 1

    shown = str(chat_turn(_project(), text="acontece com 646 px de altura", user=ADMIN,
                          thread=KEY, module=world))

    assert world.answered == 1, "the answer must not start a new turn of the role"
    [_, resumed] = world.composed
    assert resumed["answered"].answer == "acontece com 646 px de altura"
    assert resumed["request"] == GESTURE, "the card still comes from the request that asked for it"
    assert len(world.script.prompts) == 3, "one redraft, not the loop from the start"
    assert "acontece com 646 px de altura" in world.script.prompts[-1]
    assert GOOD["title"] in world.script.prompts[-1], "the redraft keeps the previous draft"
    staged = pc.find_waiting(KEY, KEY)[1]
    assert staged["kind"] == "ticket" and staged["card"] in shown


def test_an_answer_the_judge_still_blocks_shows_the_card_with_what_it_still_says(_earlier_turns):
    """Asked once, answered once: the card is shown for the yes with the review's remaining
    findings, rather than asking again — the yes is still the only write."""
    world = _World(GOOD, GOOD, GOOD,
                   judge=_blocked_then(_judge_says(2, findings=["name the screen size"])))
    chat_turn(_project(), text=GESTURE, user=ADMIN, thread=KEY, module=world)

    shown = str(chat_turn(_project(), text="em telas baixas", user=ADMIN, thread=KEY,
                          module=world))

    assert len(world.script.prompts) == 3, "asked once, answered once: ONE redraft, no second"
    staged = pc.find_waiting(KEY, KEY)[1]
    assert staged["kind"] == "ticket" and staged["judged"]["disputed"] == ["name the screen size"]
    assert "A revisão automática ainda aponta: name the screen size" in shown
    chat_turn(_project(), text="sim", user=ADMIN, thread=KEY, module=world)
    assert [f["card"] for f in world.filed] == [staged["card"]]


def test_declining_the_question_drops_it_and_the_message_is_a_conversation(_earlier_turns):
    world = _World(GOOD, GOOD, judge=_blocked_then())
    chat_turn(_project(), text=GESTURE, user=ADMIN, thread=KEY, module=world)

    chat_turn(_project(), text="não", user=ADMIN, thread=KEY, module=world)

    assert world.answered == 2 and len(world.composed) == 2, "declined: a turn like any other"
    assert len(cards._OPEN) == 0


def test_a_question_is_held_for_the_person_it_was_asked_of_only(_earlier_turns):
    from tests.test_confirmation_by_click import _project as _p

    world = _World(GOOD, GOOD, judge=_blocked_then())
    chat_turn(_p(), text=GESTURE, user=ADMIN, thread=KEY, module=world)

    assert cards.take_question("somebody-else") is None
    assert len(cards._OPEN) == 1


def test_a_question_older_than_a_proposal_is_not_an_answer(monkeypatch):
    from openfactory.product.staging import PROPOSAL_TTL_SECONDS

    assert cards.QUESTION_TTL_SECONDS == PROPOSAL_TTL_SECONDS, "one clock for both"
    composed = cards.Composed(draft=CardDraft.from_answer(GOOD), ask="?")
    cards.hold_question("k", composed, GESTURE)
    cards._OPEN["k"] = cards.OpenQuestion(**{**cards._OPEN["k"].__dict__,
                                            "at": cards._OPEN["k"].at - PROPOSAL_TTL_SECONDS - 1})

    assert cards.take_question("k") is None


def test_the_judge_and_the_draft_are_told_to_be_brief():
    """The first live judgements wrote six to nine thousand tokens each — over a minute of output
    per verdict for a JSON of five numbers."""
    prompt = cards.judge_prompt(load_rubric(), conversation=CONVERSATION, request=GESTURE,
                                card="# t")
    assert "BE BRIEF" in prompt and "at most three `findings`" in prompt
    drafting = cards.draft_prompt(conversation=CONVERSATION, request=GESTURE, reply="", intake="",
                                  title="", template=load_template(language=PT), feedback=[])
    assert "Answer at once" in drafting and "nothing to look up" in drafting


# ── the defect path runs the same loop (#392) ──────────────────────────────────────────────────

class _Reporter(_World):
    """The same world, whose answer reads the message as a broken promise."""

    def __init__(self, *drafts, judge=None, violates=None):
        super().__init__(*drafts, judge=judge)
        self.violates = violates
        self.defects: list[dict] = []

    def answer(self, question, *, context="", conversation="", **_):
        self.answered = getattr(self, "answered", 0) + 1
        return SimpleNamespace(ok=True, is_ticket=False, ticket_title="", is_defect=True,
                               is_request=False, decisions=[], gesture="",
                               text="Isso quebra o que já prometemos.", violates=self.violates)

    def file_defect(self, *, restated, reported_by, violates, severity="", source="",
                    card="", title="", **_):
        self.defects.append({"restated": restated, "card": card, "title": title,
                             "violates": violates})
        return SimpleNamespace(ok=True, ref="#78", url="https://forge/x/78", detail="",
                               existed=False)


REPORT = ("Percebi que a caixa de texto assim como o botao nao estao responsivos se minimizo a "
          "tela verticalmente. veja o screenshot")


def test_a_defect_is_drafted_judged_and_shown_whole_and_the_yes_writes_that_card(_earlier_turns):
    """Measured live after #383 shipped: the role read a report as a broken promise, and the
    defect path staged the person's message as its restatement — the card read "percebi que a
    caixa de texto… veja o screenshot", titled "…nao estao responsivos se minimiz"."""
    world = _Reporter(GOOD, violates=7)

    asked = str(chat_turn(_project(), text=REPORT, user=ADMIN, thread=KEY, module=world))

    [kw] = world.composed
    assert kw["kind"] == "defect" and kw["request"] == REPORT
    assert "reported something the product does wrong" in world.script.prompts[0]
    staged = pc.find_waiting(KEY, KEY)[1]
    assert staged["kind"] == "defect" and staged["title"] == GOOD["title"]
    assert staged["card"] in asked and "## O que está acontecendo" in staged["card"]
    assert REPORT not in staged["restated"], "the report is the source, never the restatement"
    assert "requisito 7" in asked

    chat_turn(_project(), text="sim", user=ADMIN, thread=KEY, module=world)

    [filed] = world.defects
    assert filed["card"] == staged["card"] and filed["title"] == GOOD["title"]
    assert filed["violates"] == 7


def test_a_defects_question_is_held_and_its_answer_stages_a_defect(_earlier_turns):
    world = _Reporter(GOOD, GOOD, GOOD, judge=_blocked_then(_judge_says(5)), violates=7)
    chat_turn(_project(), text=REPORT, user=ADMIN, thread=KEY, module=world)

    chat_turn(_project(), text="com 646 px de altura", user=ADMIN, thread=KEY, module=world)

    assert world.answered == 1
    staged = pc.find_waiting(KEY, KEY)[1]
    assert staged["kind"] == "defect" and staged["violates"] == 7


def test_the_defect_body_is_the_card_under_the_codes_own_lines_and_promise():
    from openfactory.product.authoring import defect_body

    card = render(CardDraft.from_answer(GOOD), load_template(kind="defect", language=PT))
    body = defect_body(language=PT, restated="x", reported_by="<@U1>", severity="", source="#produto",
                       requirement=None, requirement_path="", docs_repo="a/docs", card=card)

    assert filed_by_the_product_role(body) == "defect", "correct_card must still know it"
    assert len(_section_re(_WHAT_WAS_ASKED["defect"]).findall(body)) == 1
    # THE CODE'S CLOSING SECTION, whichever name it has: "A promessa violada" before #399, "Sem
    # requisito escrito" for a defect that cites none after it — the card sits above it either way
    closing = next(h for h in ("## A promessa violada", "## Sem requisito escrito") if h in body)
    assert body.index("## Objetivo") < body.index(closing)


def test_the_shipped_defect_template_is_one_the_loader_accepts_and_a_ticket_one_is_not():
    assert template_problem(load_template(kind="defect"), "defect") == ""
    assert "What is happening" in template_problem(load_template(language=PT), "defect")
    assert "What is happening" in template_problem(load_template(), "defect")


def test_an_over_long_defect_title_is_refused_by_the_pen(tmp_path):
    from tests.test_the_product_owner_opens_a_card_as_described import _module, _Tracker

    tracker = _Tracker()
    result = _module(tmp_path, tracker).file_defect(
        restated="r", reported_by="<@U1>", violates=None, tracker=tracker, board=None,
        card="## O que está acontecendo\n\nd", title="z" * (TITLE_LIMIT + 1))

    assert not result.ok and tracker.created == []


# ── the cards a requirement is broken into pass the same check (#392) ──────────────────────────

ISSUE = {"title": "Exportar o relatório mensal em CSV", "objective": "O relatório mensal pode "
         "ser baixado em CSV com os totais do mês.", "acceptance_criteria": [
             "Baixar o relatório de setembro entrega um CSV com uma linha por lançamento"],
         "out_of_scope": [], "target_repo": "", "cites": 7, "already_on_board": None}
SOURCE = "REQ-0007 — Relatório em CSV\n\nO cliente precisa baixar o relatório mensal em CSV."


def _body(fields: dict) -> str:
    from openfactory.product.authoring import issue_body
    from openfactory.product.role import IssueDraft

    return issue_body(IssueDraft(**fields), requirement_path="requirements/0007.md",
                      docs_repo="a/docs")


def _vet(fields, judge, redraft=None):
    return cards.vet_issue(fields, body_of=_body, source=SOURCE, rubric=load_rubric(),
                           judge=judge, redraft=redraft, project_name="books")


def test_a_requirements_card_the_judge_passes_is_filed_as_drafted():
    prompts = []
    kept, why = _vet(dict(ISSUE), lambda p: prompts.append(p) or _judge_says(5))

    assert kept == ISSUE and why == ""
    [prompt] = prompts
    assert cards.REQUIREMENT_NOTE in prompt and "REQ-0007" in prompt


def test_a_requirements_card_with_no_criterion_is_redrafted_before_any_judge():
    judged, asked = [], []

    def redraft(prompt):
        asked.append(prompt)
        return {"acceptance_criteria": ["O CSV tem uma linha por lançamento do mês"]}

    kept, why = _vet({**ISSUE, "acceptance_criteria": []},
                     lambda p: judged.append(p) or _judge_says(5), redraft)

    assert why == "" and kept["acceptance_criteria"] == ["O CSV tem uma linha por lançamento do mês"]
    assert len(judged) == 1, "the floor refused the first draft without spending the judge"
    assert "nothing says when" in asked[0]


def test_a_requirements_card_the_judge_blocks_twice_is_not_filed_and_says_why():
    kept, why = _vet(dict(ISSUE), lambda p: _judge_says(2, findings=["name the file format"]),
                     lambda p: dict(ISSUE))

    assert kept is None and "name the file format" in why


def test_the_breakdown_files_nothing_the_review_refuses_and_says_which_front(tmp_path):
    """Through `ProductModule.breakdown` with a harness that breaks the requirement into one card
    and then, asked to review it, blocks it: nothing reaches the tracker, and the result names
    the front and what it lacks."""
    from openfactory.product.role import IssueDraft
    from tests.test_the_product_owner_opens_a_card_as_described import _module, _Tracker

    tracker = _Tracker()
    module = _module(tmp_path, tracker)
    requirement = SimpleNamespace(number=7, title="Relatório em CSV", body="baixar em CSV",
                                  asked_by="", path="0007.md")
    vet = module._vetter(requirement, tracker)
    module._vetter = lambda req, tr: (lambda draft: (None, "name the file format"))

    result = module._file_one(IssueDraft(**ISSUE), requirement, tracker, None,
                              vet=module._vetter(requirement, tracker))

    assert callable(vet)
    assert not result.ok and tracker.created == []
    assert "Exportar o relatório mensal em CSV" in result.detail
    assert "name the file format" in result.detail


def test_every_card_the_product_role_creates_goes_through_the_loop():
    """ONE DOOR FOR EVERY CARD (#392). The requested card went through the loop and the defect and
    the requirement's cards did not — three pens, one checked. So every `create_ticket` the product
    module issues must sit in one of the three writers, and each writer must be reached through
    the check: the gestures compose before staging, and `_file_one` vets before it files. A fourth
    pen fails here until it is put behind the same door."""
    import ast
    import inspect
    from pathlib import Path

    from openfactory.product import engine, module

    writers = {"file_ticket", "file_defect", "_file_one"}
    found = set()
    for path in Path(module.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # THE OUTERMOST function holding the call: a writer's nested `_open` is that writer
        tops = [n for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            tops += [n for n in cls.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
        for fn in tops:
            for call in ast.walk(fn):
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "create_ticket"):
                    found.add((path.name, fn.name))
    outside = {f for f in found if f[1] not in writers}
    assert not outside, f"a card is created outside the three checked writers: {sorted(outside)}"
    assert {name for _, name in found} == writers, "the scope moved: re-read which pens exist"

    gestures = inspect.getsource(engine.gestures)
    assert gestures.count("compose(") >= 2, "a gesture stages a card the loop never saw"
    filed = inspect.getsource(module.ProductModule._file_one)
    assert "vet(draft)" in filed, "the requirement's cards are filed unchecked"
    assert "vet=vet" in inspect.getsource(module.ProductModule.file_issues)


def test_the_judge_sees_what_the_author_saw_the_reply_and_the_persons_answer():
    """Measured live: the draft was written from the role's reply (it had read the code and the
    board) and from the person's answer to the held question; the judge saw neither, and called
    the CSS analysis and the person's own "claramente isso é um bug" invented."""
    judged = []
    held = CardDraft.from_answer(GOOD)
    compose(draft=_Script(GOOD), judge=lambda p: judged.append(p) or _judge_says(5),
            rubric=load_rubric(), template=load_template(language=PT), conversation=CONVERSATION,
            request=GESTURE, reply="Abri o CSS: `.home-workspace` trava a altura.",
            answered=cards.Answered(question="O que é pronto?", answer="claramente isso é um bug",
                                    draft=held))
    [prompt] = judged

    assert "`.home-workspace` trava a altura" in prompt
    assert "claramente isso é um bug" in prompt
    assert "nothing in it is the person's words" in prompt


def test_an_unread_judge_files_no_card_of_a_requirement():
    """Review of #390: the requested card and the defect show an unjudged card to a person before
    the yes; a requirement's cards have nobody in the loop, so an unread judge files nothing."""
    kept, why = _vet(dict(ISSUE), lambda p: "looks fine to me")

    assert kept is None and "não respondeu" in why


def test_a_redraft_that_answers_nothing_spends_no_second_judge():
    judged = []
    kept, _ = _vet(dict(ISSUE), lambda p: judged.append(p) or _judge_says(2), lambda p: None)

    assert kept is None and len(judged) == 1


def test_the_breakdown_stops_starting_cards_past_its_budget_and_says_which(tmp_path, monkeypatch):
    from openfactory.product import module as module_
    from tests.test_the_product_owner_opens_a_card_as_described import _module, _Tracker

    tracker = _Tracker()
    mod = _module(tmp_path, tracker)
    calls = []

    def _clock():
        calls.append(1)
        return 0.0 if len(calls) == 1 else cards.BREAKDOWN_BUDGET_SECONDS + len(calls)

    monkeypatch.setattr(module_.time, "monotonic", _clock)
    from openfactory.product.role import IssueDraft

    drafts = SimpleNamespace(ok=True, issues=[IssueDraft(**ISSUE), IssueDraft(**{
        **ISSUE, "title": "Segunda frente"})])
    monkeypatch.setattr(mod, "_role", lambda **k: SimpleNamespace(issues_for=lambda **kw: drafts))
    monkeypatch.setattr(mod, "_workspace", lambda: (None, None))
    monkeypatch.setattr(mod, "_read_board", lambda **k: ([], ""))
    monkeypatch.setattr(mod, "_file_one", lambda draft, *a, **k: pytest.fail("filed past budget"))
    requirement = SimpleNamespace(number=7, title="t", body="b", asked_by="", path="0007.md",
                                  is_live=True, is_promise=True, came_from_the_code=False)
    monkeypatch.setattr(mod, "context", lambda **k: SimpleNamespace(
        available=True, docs_path=str(tmp_path), link=SimpleNamespace(docs_repo="a/docs"),
        corpus=SimpleNamespace(by_number=lambda n: requirement), docs_commit=""))
    monkeypatch.setattr(mod, "_open_delivery", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_vetter", lambda req, tr: None)
    monkeypatch.setattr(module_, "may_act", lambda *a, **k: True)

    results = mod.file_issues(requirement, actor="<@U1>", tracker=tracker, board=None)

    assert [r.ok for r in results] == [False, False]
    assert "não deu tempo" in results[0].detail and "Segunda frente" in results[1].detail


def test_a_str_room_reaches_the_box_as_a_path_so_the_judge_can_stage_its_prompt(monkeypatch):
    """Review of #390: the judge's room is a `TemporaryDirectory()` str, and the box divides its
    root (`stage_input`). On 0.4.1 a str root killed every judging turn (#380). The room is handed
    as a Path whatever the box does, so the card judge cannot reintroduce it at any merge order."""
    from openfactory.adapters.sandbox import registry as sandbox_registry

    seen = []
    monkeypatch.setattr(sandbox_registry, "judging_worktree",
                        lambda project, root: seen.append(root) or SimpleNamespace())
    harness = SimpleNamespace(name="h", ask=lambda **kw: SimpleNamespace(ok=False))
    cards.in_a_room(SimpleNamespace(name="p"), harness, cards.JUDGE_PHASE)("prompt")

    from pathlib import Path

    assert seen and isinstance(seen[0], Path)


def test_the_card_loop_says_each_draft_and_each_review_while_the_person_waits():
    """#395 measured ~174 s of draft, judge, redraft, judge after the answer, with nothing said.
    The loop names each step on the surface that can show it."""
    from openfactory.product import progress

    said = []
    with progress.reporting(lambda stage, counts: said.append((stage, dict(counts)))):
        _compose(_Script({**GOOD, "description": GESTURE}, GOOD), lambda p: _judge_says(5))

    assert said == [("card_draft", {"step": 1, "of": 2}), ("card_draft", {"step": 2, "of": 2}),
                    ("card_review", {"step": 2, "of": 2})]
