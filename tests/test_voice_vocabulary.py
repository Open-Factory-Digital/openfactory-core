"""She must use words the reader already owns — ADR-0026.

THE MESSAGE THAT CAUSED THIS. The product owner's second real conversation came back with "os 11
pontos de diagnóstico em revisão", "o canal de progresso de trabalhos (item 297)" and "Faixas 1 e
2". Their verdict, reading it as a client would: *"I cannot identify… what is this? would they be
items in the review column? the message came out very confusing"*.

Nothing failed. She had the board in her prompt, with its real column names, AND a rule forbidding
her to mention "boards or tickets". Banning the word does not remove the thing — it forces an
invention, and an invented name is strictly worse than the technical one: unmappable to anything
the reader can open, unverifiable, and precise-sounding while meaning nothing.

The same message was written in EUROPEAN Portuguese ("utilizador", "fecho do mês", "cifrados") to
a Brazilian reader. The project's language was known all along and never reached the model.

Both are the same defect class: the platform HAD the information and did not give it to the agent.
"""

from __future__ import annotations

import pytest

from openfactory.product.role import ProductRole
from openfactory.product.voice import AUDIENCE_RULES, language_rules


def _client_prompt(**kw) -> str:
    return ProductRole(None, **kw)._prompt("faça algo", "corpo", audience="client")


# ── the board is SHARED vocabulary, not jargon ─────────────────────────────────────────────────
def test_the_board_is_no_longer_forbidden():
    """The rule used to ban "boards or tickets" outright. That ban is what produced "pontos de
    diagnóstico" — she had "Review" in her prompt and was not allowed to say it."""
    assert "boards or tickets" not in AUDIENCE_RULES
    assert "column names exactly" in AUDIENCE_RULES, "she is not told to use the real column names"


def test_she_is_told_never_to_invent_a_name():
    """The rule that generalises past this one message: any concept the reader can already point
    at must be called by its own name."""
    assert "NEVER INVENT A NAME" in AUDIENCE_RULES
    # the actual phrases from the real message, so the guard is about THIS failure and not a mood
    for invented in ("pontos de diagnóstico", "canal de progresso de trabalhos", "Faixas 1 e 2"):
        assert invented in AUDIENCE_RULES, f"the rule does not show {invented!r} as a counterexample"


def test_the_delivery_machinery_is_still_hidden():
    """The fix must not swing the other way: PRs, branches and file paths stay out. What changed
    is WHERE the line sits, not that there is one."""
    for hidden in ("pull request", "branch", "commit", "file path"):
        assert hidden in AUDIENCE_RULES, hidden
    assert "instead of" in AUDIENCE_RULES, "the concrete substitutions were lost"


# ── dialect ────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(("pt_pt", "pt_br"), [
    ("utilizador", "usuário"), ("fecho", "fechamento"), ("cifrado", "criptografado"),
    ("equipa", "time"), ("ficheiro", "arquivo"),
])
def test_the_brazilian_rule_names_the_words_that_actually_differ(pt_pt, pt_br):
    """"Write in Portuguese" is the instruction that produced European Portuguese. The words that
    give the dialect away are listed, because that is what the model gets wrong."""
    rules = language_rules("pt-BR")
    assert pt_pt in rules and pt_br in rules, f"{pt_pt}/{pt_br} not distinguished"


def test_an_unknown_language_says_nothing_rather_than_guessing():
    """An invented instruction for a language nobody wrote rules for would be worse than letting
    the model read the room, which it does well when uninstructed."""
    assert language_rules("xx-YY") == ""


def test_the_dialect_rule_REACHES_THE_PROMPT():
    """Reach, again. `project.language` existed and was used by voice.py's fixed phrases while the
    model — which writes every free-form sentence a client reads — was never told."""
    assert "BRAZILIAN Portuguese" in _client_prompt(language="pt-BR")
    assert "EUROPEAN Portuguese" in _client_prompt(language="pt-PT")


def test_the_module_hands_the_project_language_to_the_role():
    """The seam between them: a rule that only works when a test constructs the role by hand is
    this repository's signature defect."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("openfactory/product/module.py").read_text())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "ProductRole"
             and any(k.arg == "language" for k in n.keywords)]
    assert calls, "ProductModule builds the role without a language — the rule never fires"


def test_the_team_facing_prompt_gets_neither():
    """An issue body is read by the executor and by the team. Softening it into business prose, or
    pinning its dialect, strips detail the people acting on it need — two surfaces, not one voice."""
    team = ProductRole(None, language="pt-BR")._prompt("faça algo", "corpo", audience="team")
    assert "BRAZILIAN Portuguese" not in team
    assert "NEVER INVENT A NAME" not in team


# ── the board she is shown ─────────────────────────────────────────────────────────────────────
def test_a_real_backlog_fits_without_truncation():
    """A 52-card Backlog hid twelve cards behind a cap of 40. She noticed the gap, could not see
    why, and asked the client for board access she already had — so the plan she proposed silently
    excluded a fifth of the column."""
    from openfactory.product.role import ProductRole

    board = {i: "Backlog" for i in range(1, 53)}
    titles = {i: f"card {i}" for i in range(1, 53)}
    section = "\n".join(ProductRole(None, board=board, titles=titles)._board_section())

    for n in (1, 41, 52):
        assert f"card {n}" in section, f"#{n} never reached the prompt"


def test_a_cut_EXPLAINS_ITSELF():
    """"(+12 outros nesta coluna)" reads identically as "I am not allowed to see these" and "the
    prompt truncated them". An agent that cannot tell those apart misdiagnoses its own blindness
    — and asks a client to fix something only the team can."""
    from openfactory.product.role import ProductRole

    board = {i: "Backlog" for i in range(1, 400)}
    section = "\n".join(ProductRole(None, board=board,
                                    titles={i: f"c{i}" for i in range(1, 400)})._board_section())

    assert "NÃO por falta de acesso" in section, section[-300:]
    assert "orçamento" in section, "the reason for the cut is not stated"


def test_Done_drops_the_TITLE_and_never_the_IDENTITY():
    """The exemption that makes the higher cap affordable — 190 finished titles cost more tokens
    than every other column together — WITHOUT the blindness it used to carry.

    The first version printed a count and nothing else, so "o que aconteceu com o #511?" was
    unanswerable: absent-from-the-prompt and absent-from-the-product looked identical. A product
    owner is asked that question constantly, and on 2026-08-01 she had to answer "não sei se foi
    fechado, movido ou renumerado" about a card SHE had closed the day before.

    So the budget takes the description and never the existence."""
    from openfactory.product.role import ProductRole

    board = {i: "Done" for i in range(1, 200)}
    section = "\n".join(ProductRole(None, board=board,
                                    titles={i: f"feito {i}" for i in range(1, 200)})._board_section())

    assert "feito 1" not in section, "Done titles are being pasted"
    assert "#511" not in section, "sanity: 511 is not in this fixture"
    for n in (1, 87, 199):
        assert f"#{n}" in section, f"#{n} vanished — 'concluído' and 'inexistente' are one again"
    # and the economy the exemption exists for is still real
    assert len(section) < 4000, f"the ids cost {len(section)}c — the exemption stopped paying"


def test_a_card_closed_as_NOT_PLANNED_can_never_be_read_as_delivered():
    """CLOSED IS NOT DELIVERED. Eleven cards were closed as `not_planned` in one sitting on
    2026-07-29, and counting them as delivered made the platform announce work nobody did.

    That rule lived only on the SWEEP's path (`activities._closed_issue_numbers`) because the
    conversational surface received `{number: column}` and `{number: title}` — no state, no reason.
    Printing the Done ids without moving the rule would have handed the model exactly the material
    to say "#500 está entregue" on the one surface where the delivery predicate did not exist."""
    from openfactory.product.role import ProductRole
    from openfactory.product.triage import Ticket

    section = "\n".join(ProductRole(None, cards=[
        Ticket(number=500, title="Cancelamento", state="closed",
               state_reason="not_planned", column="Done"),
        Ticket(number=511, title="Decrypt", state="closed",
               state_reason="completed", column="Done"),
    ])._board_section())

    # THE EXCEPTION IS WHAT IS PRINTED. Annotating all 203 finished cards cost 5.700 characters in
    # every prompt — seven times what the first version of this claimed — and put `fechado`, a word
    # `voice._CLAIMED_DONE` watches for, in front of the role two hundred times a turn. Marking
    # only what CONTRADICTS the column says strictly more for ~1.700.
    assert "#500 (cancelado)" in section, section
    assert "#511" in section and "#511 (" not in section, (
        f"a delivered card in Done should carry no mark at all: {section}")
    assert "fechado" not in section, "the prompt primes her with the word the detector watches"


def test_a_card_whose_STATE_IS_UNKNOWN_gets_no_verdict_at_all():
    """The honest answer for a caller that handed over columns and titles alone. Inferring delivery
    from the column is the mistake this whole change exists to prevent: `close_card` closes a
    ticket without moving its card, and the board's own automation moves cards without anyone
    closing the ticket — `triage` has a rule for each direction (`done-but-open`,
    `closed-elsewhere`) precisely because they diverge."""
    from openfactory.product.role import ProductRole

    section = "\n".join(ProductRole(None, board={511: "Done"},
                                    titles={511: "Decrypt"})._board_section())

    assert "#511" in section
    assert "cancelado" not in section and "aberto" not in section, (
        f"it guessed an outcome from the column: {section}")


def test_the_board_section_declares_the_SCOPE_of_what_it_shows():
    """"Not in this list" may become a fact about the READING and never about the product. Without
    the scope stated, a card outside the board read (board.py caps the sweep) reads as a card that
    does not exist — and she would tell a client so."""
    from openfactory.product.role import ProductRole

    section = "\n".join(ProductRole(None, board={1: "Backlog"}, titles={1: "x"})._board_section())

    assert "AS READ FOR THIS MESSAGE" in section, section


def test_the_two_divergences_triage_names_are_both_VISIBLE_in_the_prompt():
    """`close_card` closes a ticket without moving its card, and the board's own automation moves
    cards without anyone closing the ticket. `triage` has a rule for each direction — `done-but-open`
    and `closed-elsewhere` — because both really happen, and the conversational surface could see
    neither: the column was all it had."""
    from openfactory.product.role import ProductRole
    from openfactory.product.triage import Ticket

    section = "\n".join(ProductRole(None, cards=[
        Ticket(number=250, title="aberto no Done", state="open", column="Done"),
        Ticket(number=511, title="fechado fora do Done", state="closed",
               state_reason="completed", column="TO-DO"),
    ])._board_section())

    assert "#250 (ainda aberto)" in section, section      # done-but-open
    assert "#511 (entregue)" in section, section          # closed-elsewhere


def test_a_card_the_PLATFORM_closed_as_a_duplicate_is_not_read_as_delivered():
    """The write side of the same rule. `close_ticket` set only the COMMENT, so GitHub defaulted
    `stateReason` to COMPLETED — and `#511`, closed as a duplicate of `#288` at a client's request,
    came back marked as delivered work to every reader downstream."""
    import inspect

    from openfactory.product.module import ProductModule

    src = inspect.getsource(ProductModule.close_card)
    assert "delivered=False" in src, (
        "a card taken off the list of work is being recorded as work that shipped")
