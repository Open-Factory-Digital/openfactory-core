"""A card is written in the language of the conversation it came from (#429).

Found live: a person wrote to the product role in English on a project set to `en`, the frames
around the card came out in English, and the card itself — every heading and, following them,
every sentence the drafter wrote — was Portuguese. The shipped layouts were Portuguese only, the
model wrote in the layout's language, and nothing checked.
"""

from __future__ import annotations

import pytest

from openfactory.language.written import not_in, written_in
from openfactory.product import cards
from openfactory.product.cards import CardDraft, load_template, render, template_problem
from openfactory.product.module import _WHAT_WAS_ASKED, _corrected, _section_re
from openfactory.product.voice import admins_must_confirm

PT_HEADINGS = ("Objetivo", "O que foi pedido", "O que está acontecendo", "Critérios de aceite",
               "Fora do escopo", "Relacionados", "Nas palavras")

EN_DRAFT = CardDraft(
    title="Home: the composer is cut off on short windows",
    objective="The Home composer stays reachable when the window is short.",
    description=("The composer's outer container is locked to the viewport height and hides its "
                 "overflow, so when the window is shorter than that the bottom row with the "
                 "Create button is cut off and there is no scrollbar to reach it."),
    done_when=["The Create button is visible and reachable at a window height of 500 pixels"],
    source_quote="the text box and buttons get cut off")

PT_DRAFT = CardDraft(
    title="Home: o composer fica cortado em janelas baixas",
    objective="O composer da Home continua acessível quando a janela é baixa.",
    description=("O container externo do composer tem a altura travada na altura da viewport e "
                 "esconde o que passa dela, então quando a janela é mais baixa que isso a linha "
                 "de baixo com o botão Create fica cortada e não há barra de rolagem para chegar "
                 "nela."),
    done_when=["O botão Create fica visível e alcançável com a janela em 500 pixels de altura"],
    source_quote="o campo de texto e os botões ficam cortados")


@pytest.mark.parametrize("kind", ["ticket", "defect"])
def test_an_english_conversation_gets_an_english_layout_with_no_portuguese_heading(kind):
    for language in ("en", None, "es"):  # the default, and a language with no layout of its own
        layout = load_template(kind=kind, language=language)
        assert template_problem(layout, kind) == ""
        body = render(EN_DRAFT, layout)
        assert not [h for h in PT_HEADINGS if h in body], (language, body)


@pytest.mark.parametrize("kind", ["ticket", "defect"])
def test_a_portuguese_conversation_keeps_its_portuguese_layout(kind):
    layout = load_template(kind=kind, language="pt-BR")
    assert template_problem(layout, kind) == ""
    assert "## Objetivo" in layout and "## Critérios de aceite" in layout


def test_every_shipped_layout_is_one_the_loader_accepts_in_every_language_it_ships_in():
    shipped = sorted(p.name for p in cards._DEFAULTS.glob("*.md"))
    assert shipped == ["defect-template.md", "defect-template.pt-BR.md", "template.md",
                       "template.pt-BR.md"], "a new layout file: add it to the two tests above"
    for name in shipped:
        kind = "defect" if name.startswith("defect") else "ticket"
        assert template_problem((cards._DEFAULTS / name).read_text(), kind) == "", name


def test_the_products_own_layout_in_the_language_wins_then_its_own_then_the_shipped(tmp_path):
    (tmp_path / "cards").mkdir()
    own = load_template(language="pt-BR").replace("## Objetivo", "## Meta do cartão")
    (tmp_path / "cards" / "template.md").write_text(own)
    # THE PRODUCT'S OWN WINS over a shipped one in the right language
    assert load_template(str(tmp_path), language="en") == own
    english = load_template(language="en").replace("## Objective", "## Goal of the card")
    (tmp_path / "cards" / "template.en.md").write_text(english)
    assert load_template(str(tmp_path), language="en") == english
    assert load_template(str(tmp_path), language="pt-BR") == own


@pytest.mark.parametrize("language,section,name", [
    ("en", "request", "What was asked"),
    ("pt-BR", "request", "O que foi pedido"),
    ("en", "defect", "What is happening"),
    ("pt-BR", "defect", "O que está acontecendo"),
])
def test_a_correction_finds_its_section_in_either_language_and_keeps_its_name(language, section,
                                                                              name):
    kind = "ticket" if section == "request" else "defect"
    body = render(EN_DRAFT if language == "en" else PT_DRAFT,
                  load_template(kind=kind, language=language))
    assert len(_section_re(_WHAT_WAS_ASKED[section]).findall(body)) == 1

    after, old, _removed = _corrected(body, section, "the corrected text")

    assert old and "the corrected text" in after
    assert f"## {name}\n\nthe corrected text" in after, "the section keeps the name it had"
    assert len(_section_re(_WHAT_WAS_ASKED[section]).findall(after)) == 1


def test_the_floor_refuses_a_card_clearly_in_another_language_and_says_which():
    en_body = render(EN_DRAFT, load_template(language="en"))
    pt_body = render(PT_DRAFT, load_template(language="pt-BR"))

    def problems(draft, body, language):
        return cards.floor(draft, body, request="x", conversation=draft.source_quote,
                           language=language)

    assert problems(EN_DRAFT, en_body, "en") == []
    assert problems(PT_DRAFT, pt_body, "pt-BR") == []
    said = problems(PT_DRAFT, pt_body, "en")
    assert said and "Portuguese" in said[-1] and "English" in said[-1]
    said = problems(EN_DRAFT, en_body, "pt-BR")
    assert said and "English" in said[-1] and "Portuguese" in said[-1]
    # NO LANGUAGE NAMED, OR ONE IT HAS NO WORDS FOR: no check — a refusal costs the card
    assert problems(PT_DRAFT, pt_body, None) == []
    assert problems(PT_DRAFT, pt_body, "de") == []


def test_only_a_clear_miss_counts_as_one():
    assert written_in(EN_DRAFT.description) == "en"
    assert written_in(PT_DRAFT.description) == "pt"
    # too little to tell: names and a few words are in every language
    assert written_in("Fix the Studio login button") is None
    assert written_in("o botão Create do Studio") is None
    assert not_in("Fix the Studio login button", "pt-BR") is None


def test_the_drafter_is_told_the_language_by_name_and_that_the_layout_does_not_decide_it():
    said = cards.draft_prompt(conversation="c", request="r", reply="", intake="", title="",
                              template=load_template(language="en"), feedback=[],
                              language="en")
    assert "Write every field in en" in said and "whatever language the layout" in said
    assert "# Language\n\nWrite in English." in said
    unnamed = cards.draft_prompt(conversation="c", request="r", reply="", intake="", title="",
                                 template=load_template(), feedback=[])
    assert "Write it in the person's language." in unnamed


def test_the_admins_line_is_in_the_conversations_language():
    for act in ("record", "order", "card", "note", "decision", "closing", "correction", "change"):
        en = admins_must_confirm("<@A>", act, language="en")
        pt = admins_must_confirm("<@A>", act, language="pt-BR")
        assert en.startswith("\n\n(<@A>: ") and en.endswith("needs your confirmation.)")
        assert pt.endswith("precisa da sua confirmação.)")
        assert written_in(en) != "pt" and "precisa" not in en


def test_the_module_drafts_in_the_projects_language_when_the_caller_names_none(monkeypatch):
    """`compose_card` falls back to the project's language, and hands it to the layout, the
    drafter and the floor alike."""
    from types import SimpleNamespace

    from openfactory.product.module import ProductModule

    seen = {}
    monkeypatch.setattr(cards, "load_template",
                        lambda docs, kind, language=None: seen.setdefault("layout", language)
                        or "")
    monkeypatch.setattr(cards, "load_rubric", lambda docs: None)
    monkeypatch.setattr(cards, "compose", lambda **kw: seen.setdefault("compose", kw["language"]))
    module = ProductModule.__new__(ProductModule)
    module.project = SimpleNamespace(name="p", language="pt-BR")
    module._agent = SimpleNamespace(name="engine")
    module._handed_card_judge = None
    monkeypatch.setattr(module, "context",
                        lambda: SimpleNamespace(available=True, docs_path=""), raising=False)
    monkeypatch.setattr(module, "_card_judge", lambda harness: None, raising=False)

    module.compose_card(request="r")
    assert seen == {"layout": "pt-BR", "compose": "pt-BR"}
    seen.clear()
    module.compose_card(request="r", language="en")
    assert seen == {"layout": "en", "compose": "en"}


def test_the_loop_hands_the_language_to_the_drafter_and_redrafts_a_card_in_the_wrong_one():
    """End to end through `compose`: a Portuguese draft for an English conversation is refused by
    the floor, the redraft is asked with that problem, and the prompt named the language both
    times."""
    import dataclasses

    prompts = []
    drafts = iter([PT_DRAFT, EN_DRAFT])

    def draft(prompt):
        prompts.append(prompt)
        return dataclasses.asdict(next(drafts))

    out = cards.compose(draft=draft, judge=None, rubric=cards.load_rubric(),
                        template=load_template(language="en"), conversation=EN_DRAFT.source_quote,
                        request="it is broken", language="en")

    assert out.ok and out.draft.title == EN_DRAFT.title and out.attempts == 2
    assert all("Write every field in en" in p for p in prompts)
    assert "the card is written in Portuguese" in prompts[1]


# ── what the person sees after the yes, in the conversation's language ──────────────────────────

def _english(text: str) -> None:
    from tests.test_no_portuguese_is_welded_into_the_core import is_portuguese

    lines = [ln for ln in text.splitlines() if ln.strip() and is_portuguese(ln)]
    assert not lines, "Portuguese in an English reply or card:\n" + "\n".join(lines)


def test_the_card_body_the_board_gets_is_english_in_english_and_read_back_in_both():
    from types import SimpleNamespace

    from openfactory.product.authoring import defect_body, filed_by_the_product_role, ticket_body
    from openfactory.product.module import _cited_requirement

    req = SimpleNamespace(number=7)
    for language, card in (("en", ""), ("en", render(EN_DRAFT, load_template(language="en")))):
        asked = ticket_body(described="an export", reported_by="", source="#product",
                            docs_repo="a/docs", card=card, language=language)
        broken = defect_body(restated="it breaks", reported_by="<@U1>", severity="high",
                             source="#product", requirement=req, requirement_path="r/0007.md",
                             docs_repo="a/docs", commit="abc", card=card, language=language)
        unwritten = defect_body(restated="it breaks", reported_by="<@U1>", severity="",
                                source="", requirement=None, requirement_path="",
                                docs_repo="a/docs", card=card, language=language)
        for body in (asked, broken, unwritten):
            _english(body)
        assert filed_by_the_product_role(asked) == "request"
        assert filed_by_the_product_role(broken) == filed_by_the_product_role(unwritten) == "defect"
        assert _cited_requirement(broken) == 7
    # AND A PORTUGUESE CARD IS STILL READ: the markers of every language are one marker
    pt = defect_body(restated="quebra", reported_by="", severity="", source="", requirement=req,
                     requirement_path="r/0007.md", docs_repo="a/docs", language="pt-BR")
    assert "**Tipo:** defeito" in pt and filed_by_the_product_role(pt) == "defect"
    assert _cited_requirement(pt) == 7
    # a defect that cites its promise by the heading alone (filed before `## Source` existed)
    for heading in ("## The broken promise — REQ-0007", "## A promessa violada — REQ-0007"):
        assert _cited_requirement(f"{heading}\n\nx\n") == 7, heading


def test_the_reply_after_a_requirements_yes_is_english_in_english():
    from types import SimpleNamespace

    from openfactory.product.confirm import _breakdown_reply

    def result(ref, *, ok=True, existed=False, detail=""):
        return SimpleNamespace(ok=ok, ref=ref, existed=existed, detail=detail)

    for results in ([result("#1")], [result("#1"), result("#2")],
                    [result("#1", existed=True), result("#2")],
                    [result("#1", existed=True)], [result("#1"), result("", ok=False,
                                                                        detail="refused")], []):
        _english(_breakdown_reply(results, 7, "", "en"))
    pt = _breakdown_reply([result("#1"), result("#2")], 7, "", "pt-BR")
    assert "O requisito 7 virou **2** tarefas" in pt and "Estão no Backlog" in pt


def test_the_pen_answers_in_the_projects_language(tmp_path):
    from types import SimpleNamespace

    from openfactory.product.module import _FILING, ProductModule

    module = ProductModule.__new__(ProductModule)
    module.project = SimpleNamespace(name="p", language="en")
    module.context = lambda: SimpleNamespace(available=True)
    assert module.file_ticket(title=" ", described="", reported_by="").detail == \
        _FILING["en"]["no_title"]
    for said in _FILING["en"].values():
        _english(said)


def test_the_engines_own_sentences_are_english_in_english():
    from openfactory.product.engine import _conflict_line
    from openfactory.product.voice import _ENGINE_SAID, engine_said

    assert set(_ENGINE_SAID["en"]) == set(_ENGINE_SAID["pt-BR"])
    for key in _ENGINE_SAID["en"]:
        _english(engine_said(key, language="en", number=7, which=" (#1, #2)"))
    from types import SimpleNamespace

    assert _conflict_line(SimpleNamespace(requirement=3, explanation="x"), "en") == \
        "requirement 3 — x"
    assert _conflict_line(SimpleNamespace(requirement=None, explanation="x"), "pt-BR") == \
        "algo já decidido — x"


def test_the_panels_copy_of_a_proposal_is_in_the_conversations_language_and_its_token_is_not():
    """The panel mirrors a staged proposal for a person to read, so its summary follows the
    language; the button's fingerprint hashes the pt-BR summary always, so a button approves the
    same proposal whatever language it was shown in."""
    from openfactory.product.staging import _proposal_summary, proposal_token

    entry = {"kind": "defect", "title": "t", "restated": "the composer is cut off",
             "number": 7}
    english = _proposal_summary(entry, language="en")
    assert english.startswith("kind: defect") and "text: the composer is cut off" in english
    _english(english)
    assert _proposal_summary(entry).startswith("tipo: defect")
    from hashlib import blake2b

    pt = blake2b(_proposal_summary(entry, language="pt-BR").encode(), digest_size=6).hexdigest()
    assert proposal_token("k", entry) == f"k|{pt}", "the fingerprint reads the pt-BR summary"


def test_an_english_claim_of_a_write_is_caught_and_an_english_i_cannot_see_is_excused():
    from openfactory.product.voice import claims_a_write

    assert claims_a_write("Registered the request with the team.") == "Registered"
    assert claims_a_write("Noted.") == "Noted"
    assert claims_a_write("I cannot see the result of what was recorded.") == ""
