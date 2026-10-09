"""The notes the product role leaves on a card speak the PROJECT's language, and the capability
write answers in the conversation's (#538).

#513 moved every detail the role's writes answer into the voice. Two kinds of Portuguese-only text
were outside its scope and stayed:

- THE NOTES ON THE CARD. `_closing_note`, `_survivor_note`, `_align_note`, `_repoint_note` and
  `_refine_note` were composed in `module.py`, and #513 fixed only their `#`. MEASURED ON THE #513
  BRANCH (6fd4244) with this file: on a project that speaks English, a card closed in favour of
  another was left saying, in Portuguese, "closed at the request of U0ADMIN, in favour of #288: the
  work is followed there now", and the sweep that re-points an orphan wrote the Portuguese for
  "this card now carries out requirement 6, at the request of U0ADMIN: …" on it — all five
  notes, Portuguese on an English card.
- `capabilities.confirm_in_repository` refused a name in Portuguese ("that name is not the name of
  a capability") while the voice already held `not_a_capability` in both languages — and gave six
  other answers of its own in Portuguese, one of them carrying git's output.

Two things the review of the first cut found, in the same notes:

- THE SIGNATURE. `voice.signature` wrote "**Nina (produto):**" over every note on every project, so
  an English card read an English note under a Portuguese signature. It takes the card's language
  now, at every one of its call sites, and a guard holds each call to handing it one.
- "A PEDIDO DE O TIME". A note nobody asked for by name substituted "o time" after "de"; Portuguese
  contracts the preposition with the article, so the entry holds both ("do time"), as `_AGENDA_WHO`
  does. The acceptance stamp had the same composition after "em": "registrado em o cartão #12".

A CARD BELONGS TO THE PROJECT, NOT TO A CONVERSATION: somebody reads it months later with no idea
which conversation asked. So the notes follow `Project.language`, as the voice's `correction_note`
and `change_accepted_note` already did; the capability write answers whoever asked, in the
language its caller passes — the project's, as every write of the product's record does (#513).

WHAT IS DRIVEN HERE. Each note through the verb that writes it, on `test_card_maintenance`'s bed
(the real module, a tracker that records what it is asked), once per language, and compared whole
with the sentence written out below: pt-BR word for word as it read before — opening with a
capital after the signature now, as every catalogued sentence does
(`test_a_sentence_reads_right_without_its_signature`), and with refine's "1 critérios" now "1
critério" — and en its translation. The capability write through
`ProductModule.confirm_capability` on `test_capabilities_and_checks`'s bed (a real context
repository, a real clone), and directly where the module refuses before it is reached.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from openfactory.product import voice
from tests import test_card_maintenance as maintenance
from tests.test_capabilities_and_checks import _commit, bed  # noqa: F401 — the fixture
from tests.test_card_maintenance import (  # noqa: F401 — the bed and its isolation, reused
    _ALIGNED,
    _REFINED,
    ADMIN,
    _isolate,
    world,
)

ROOT = Path(__file__).resolve().parents[1]

#: The role's signature, in the card's language — "(produto)" headed every card until #538.
SIGNED = {"pt-BR": "**Nina (produto):**", "en": "**Nina (product):**"}
SIG = SIGNED["pt-BR"]

#: Every note, as the card is left saying it — pt-BR as it always read, but for its capital.
NOTES = {
    "pt-BR": {
        "closed": (f"{SIG} Fechado a pedido de {ADMIN}, em favor do #288: o trabalho passa a ser "
                   f"acompanhado lá.\n\nera o mesmo pedido"),
        "survivor": (f"{SIG} O #511 foi fechado em favor deste, a pedido de {ADMIN}. Se havia "
                     f"algo escrito lá que não está aqui, vale trazer antes de começar."),
        "removed": f"{SIG} Fechado a pedido de {ADMIN}.\n\nnão precisa mais",
        "aligned": (f"{SIG} Este cartão passou a executar o requisito 6, e reescrevi o que precisa "
                    f"ser verdade para dá-lo por pronto a partir dele — o texto que ele seguia "
                    f"antes foi substituído. Corrijam se eu entendi errado.\n\nO que eu não "
                    f"consegui determinar:\n- quem assina o aviso?"),
        "repointed": (f"{SIG} Este cartão passou a executar o requisito 6, a pedido de {ADMIN}: o "
                      f"requisito 4, que ele citava, foi substituído por aquele.\n\n**O que está "
                      f"escrito aqui como \"pronto\" continua igual, e foi escrito a partir do "
                      f"texto antigo.** Não revisei nada disso: rever pode mudar o que vai ser "
                      f"construído, e essa é uma decisão de vocês, não uma arrumação minha."),
        "refined": (f"{SIG} Este item não dizia quando estaria pronto, então seria recusado na "
                    f"entrada. Escrevi 1 critério a partir do que já estava descrito — corrijam "
                    f"se eu entendi errado.\n\nO que eu não consegui determinar:\n- quem confere "
                    f"o total?"),
    },
    "en": {
        "closed": (f"{SIGNED['en']} Closed at the request of {ADMIN}, in favour of #288: the work is "
                   f"followed there now.\n\nera o mesmo pedido"),
        "survivor": (f"{SIGNED['en']} #511 was closed in favour of this one, at the request of {ADMIN}. If "
                     f"something was written there that is not here, bring it over before "
                     f"starting."),
        "removed": f"{SIGNED['en']} Closed at the request of {ADMIN}.\n\nnão precisa mais",
        "aligned": (f"{SIGNED['en']} This card now carries out requirement 6, and I rewrote what has to be "
                    f"true to call it done from that text — the one it followed before was "
                    f"replaced. Correct me if I got it wrong.\n\nWhat I could not determine:\n"
                    f"- quem assina o aviso?"),
        "repointed": (f"{SIGNED['en']} This card now carries out requirement 6, at the request of {ADMIN}: "
                      f"requirement 4, which it cited, was replaced by that one.\n\n**What is "
                      f"written here as \"done\" is unchanged, and it was written from the older "
                      f"text.** I revised none of it: revising it can change what gets built, and "
                      f"that is your decision, not tidying of mine."),
        "refined": (f"{SIGNED['en']} This item did not say when it would be done, so pickup would have "
                    f"refused it. I wrote 1 criterion from what was already described — correct "
                    f"me if I got it wrong.\n\nWhat I could not determine:\n- quem confere o "
                    f"total?"),
    },
}


@pytest.fixture(params=sorted(NOTES))
def speaking(request, monkeypatch) -> str:
    """The maintenance bed's project, speaking `request.param` — the reasons and the model's
    questions stay in the words they were given, which is the point: only the frame is the
    platform's to translate."""
    language = request.param
    plain = maintenance._project
    monkeypatch.setattr(maintenance, "_project",
                        lambda: plain().model_copy(update={"language": language}))
    return language


def test_a_closed_card_and_the_one_it_closed_into_say_so(speaking, world):  # noqa: F811
    language = speaking
    mod, _ = world()

    assert mod.close_card(511, actor=ADMIN, in_favour_of=288, reason="era o mesmo pedido").ok

    [(_ref, closing)] = world.tracker.closed
    assert closing == NOTES[language]["closed"], closing
    assert world.tracker.comments == [("#288", NOTES[language]["survivor"])], world.tracker.comments


def test_a_removed_card_says_who_asked(speaking, world):  # noqa: F811
    """A row with no removal of its own closes the card, with the note on it (`remove_ticket`)."""
    language = speaking
    mod, _ = world()

    assert mod.withdraw_card("600", actor=ADMIN, reason="não precisa mais", remove=True).ok

    [(_ref, note)] = world.tracker.closed
    assert note == NOTES[language]["removed"], note


def test_an_aligned_card_says_what_it_now_carries_out(speaking, world):  # noqa: F811
    language = speaking
    mod, _ = world(_ALIGNED)

    assert mod.align_card(288, requirement=6, actor=ADMIN).ok

    assert world.tracker.comments == [("#288", NOTES[language]["aligned"])], world.tracker.comments


def test_a_repointed_card_warns_that_its_criteria_are_older(speaking, world):  # noqa: F811
    language = speaking
    mod, _ = world()

    mod.repoint_orphans(actor=ADMIN)

    ref, note = world.tracker.comments[0]
    assert (ref, note) == ("#510", NOTES[language]["repointed"]), (ref, note)


def test_a_refined_card_says_who_wrote_its_criteria(speaking, world):  # noqa: F811
    language = speaking
    mod, _ = world(_REFINED)

    assert mod.refine(288, actor=ADMIN).ok

    assert world.tracker.comments == [("#288", NOTES[language]["refined"])], world.tracker.comments


#: A note nobody asked for by name, on a Jira card: the team asked, said as Portuguese says it.
NOBODY_NAMED = {
    "pt-BR": {"closed": ("**Produto:** Fechado a pedido do time, em favor do DAR-9: o trabalho "
                         "passa a ser acompanhado lá."),
              "survivor": ("**Produto:** O DAR-10 foi fechado em favor deste, a pedido do time. Se "
                           "havia algo escrito lá que não está aqui, vale trazer antes de "
                           "começar.")},
    "en": {"closed": ("**Product:** Closed at the request of the team, in favour of DAR-9: the "
                      "work is followed there now."),
           "survivor": ("**Product:** DAR-10 was closed in favour of this one, at the request of "
                        "the team. If something was written there that is not here, bring it "
                        "over before starting.")},
}


@pytest.mark.parametrize("language", sorted(NOBODY_NAMED))
def test_a_note_names_a_jira_card_as_jira_does_and_nobody_as_the_team(language):
    """`ref_label` names the card, `#12` on a numbered board and `DAR-9` on Jira; a note nobody
    asked for by name is the team's, in the project's language.

    "A PEDIDO DO TIME", NEVER "DE O TIME". The template said "a pedido de {who}" and nobody named
    was "o time", so the pt-BR note read "a pedido de o time" — Portuguese contracts the
    preposition with the article, and only the entry that holds both can say it right."""
    closed = voice.closing_note(in_favour_of="DAR-9", actor="", language=language)
    survivor = voice.survivor_note(closed="#DAR-10", actor="", language=language)
    repointed = voice.repoint_note(cited=4, successor=6, language=language)

    assert closed == NOBODY_NAMED[language]["closed"], closed
    assert survivor == NOBODY_NAMED[language]["survivor"], survivor
    assert "de o " not in closed + survivor
    assert "a pedido" not in repointed and "at the request" not in repointed, (
        "a re-point nobody asked for names somebody")


@pytest.mark.parametrize(("cards", "said"), [
    (["12"], "O aceite ficou registrado no cartão #12, em seu nome."),
    (["12", "DAR-31"], "O aceite ficou registrado nos cartões #12 e DAR-31, em seu nome."),
])
def test_an_acceptance_is_said_recorded_ON_the_card_as_portuguese_contracts_it(cards, said):
    """The same composition, the other preposition: "registrado em {cards}" with `_named_cards`'
    "o cartão #12" read "registrado em o cartão #12"."""
    assert voice.acceptance_stamped(cards=cards, language="pt-BR") == said
    assert voice.acceptance_stamped(cards=cards[:1], language="en") == (
        "The acceptance is recorded on card #12, in your name.")


# ── the signature over every note: the card's language too ───────────────────────────────────

def _signed(language: str) -> dict[str, str]:
    """Every composer that signs what it writes on a card, rendered for Nina in `language`."""
    from openfactory.product import needs_action
    from openfactory.product.module import _with_criteria

    verdict = needs_action.Verdict(ticket="12", cause="technical", confidence="high")
    mine = needs_action.Verdict(ticket="12", cause="requirement", confidence="high", fix="f")
    nina = {"agent_name": "Nina", "language": language}
    return {
        "acceptance_stamp": voice.acceptance_stamp(number=4, actor="ana", day="2026-10-05",
                                                   where="x", **nina),
        "closing_note": voice.closing_note(in_favour_of="31", actor="ana", **nina),
        "survivor_note": voice.survivor_note(closed="12", actor="ana", **nina),
        "correction_note": voice.correction_note(kind="request", actor="ana", text_changed=True,
                                                 old_text="x", **nina),
        "change_accepted_note": voice.change_accepted_note(by="ana", head="abcdef1234",
                                                           pr_url="https://x/pr/1", **nina),
        "align_note": voice.align_note(requirement=6, **nina),
        "repoint_note": voice.repoint_note(cited=4, successor=6, **nina),
        "refine_note": voice.refine_note(criteria=2, **nina),
        "hand_back_comment": needs_action.hand_back_comment(verdict, **nina),
        "fix_comment": needs_action.fix_comment(mine, **nina),
        "with_criteria": _with_criteria("body", {"criteria": ["c"]}, agent="Nina",
                                        language=language),
    }


@pytest.mark.parametrize("language", sorted(SIGNED))
def test_every_signature_on_a_card_is_in_the_cards_language(language):
    """"**Nina (produto):**" headed every note on every project, so an English card read English
    under a Portuguese signature once #538 had translated the notes themselves."""
    other = SIGNED["en" if language == "pt-BR" else "pt-BR"]
    for name, text in _signed(language).items():
        assert SIGNED[language] in text and other not in text, (name, text)


#: Where `voice.signature` is called, by the files that import it — `inspect.signature` and the
#: tech-lead memory's `signature` (a failure fingerprint) are other functions of the same name.
SIGNERS = ("openfactory/product/voice.py", "openfactory/product/needs_action.py",
           "openfactory/product/module.py")


def signatures(source: str) -> tuple[int, list[str]]:
    """`(calls, unsigned)`: how many bare `signature(…)` calls `source` makes, and `line
    (function)` for each that hands it no `language=` — the default is English, so a call that
    forgets says "(product)" on a Portuguese card."""
    tree = ast.parse(source)
    parents = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

    def verb(node) -> str:
        while id(node) in parents:
            node = parents[id(node)]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
        return "<module>"

    found = [call for call in ast.walk(tree)
             if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "signature"]
    return len(found), [f"{call.lineno} ({verb(call)})" for call in found
                        if not any(k.arg == "language" for k in call.keywords)]


def test_every_signature_is_handed_the_language_of_its_card():
    calls, unsigned = 0, []
    for rel in SIGNERS:
        made, missing = signatures((ROOT / rel).read_text(encoding="utf-8"))
        calls += made
        unsigned += [f"{rel}:{where}" for where in missing]
    # ten when #538 landed: eight in the voice, the hand-back's, and the criteria's line
    assert calls >= 10, f"the scan found {calls} signatures — it is looking in the wrong place"
    assert not unsigned, "a signature with no language:\n  " + "\n  ".join(unsigned)


def test_the_signature_guard_can_actually_see_one():
    """THE POSITIVE TWIN: a call with no language is caught, one with it is not, and a method
    called `signature` (`inspect.signature(f)`) is not this one."""
    source = '''
def bare(agent):
    return signature(agent)

def handed(agent, lang):
    return signature(agent, language=lang) + str(inspect.signature(bare))
'''
    calls, unsigned = signatures(source)
    assert calls == 2 and [w.split(" ", 1)[1] for w in unsigned] == ["(bare)"], (calls, unsigned)


# ── the capability write ─────────────────────────────────────────────────────────────────────

CAPABILITY = {
    "pt-BR": {"name": "esse nome não é o de uma capacidade",
              "retired": ("essa capacidade foi aposentada — confirmar de novo é uma decisão a "
                          "registrar por escrito, não um sim"),
              "failed": ("não consegui registrar a confirmação da capacidade checkout agora. Nada "
                         "mudou — o time foi avisado e resolve.")},
    "en": {"name": "that name is not the name of a capability",
           "retired": ("that capability was retired — confirming it again is a decision to record "
                       "in writing, not a yes"),
           "failed": ("I could not record the confirmation of capability checkout just now. "
                      "Nothing changed — the team has been told and will sort it out.")},
}


@pytest.mark.parametrize("language", sorted(CAPABILITY))
def test_a_name_that_is_no_capability_is_refused_in_the_language_asked(language):
    from openfactory.product.capabilities import confirm_in_repository

    refused = confirm_in_repository(docs_repo="quayside-context", clone_url="file:///nowhere",
                                    slug="../requirements/0001", flow=None, confirmed_by="ines",
                                    language=language)

    assert (refused.ok, refused.detail) == (False, CAPABILITY[language]["name"])


@pytest.mark.parametrize("language", sorted(CAPABILITY))
def test_a_retired_capability_is_refused_in_the_projects_language(bed, language):  # noqa: F811
    """Through the module: `confirm_capability` hands the write the project's language, as every
    write of the product's record does — the file is read in the clone, past every check the
    module makes on its own."""
    folder = bed.context / "capabilities"
    folder.mkdir()
    (folder / "checkout.md").write_text("---\ntitle: Checkout\nstatus: retired\n---\n\n# X\n")
    _commit(bed.context, "a capability taken back")
    bed.project = bed.project.model_copy(update={"language": language})

    refused = bed.module().confirm_capability("checkout", actor="ines")

    assert (refused.ok, refused.detail) == (False, CAPABILITY[language]["retired"])


@pytest.mark.parametrize("language", sorted(CAPABILITY))
def test_a_clone_that_failed_is_the_teams_to_read_and_the_persons_to_hear(language, caplog):
    """The clone's output named the repository and carried git's own words into the detail; it is
    the log's now, and the person reads that nothing changed — what the module says when the write
    raises."""
    from openfactory.product.capabilities import confirm_in_repository

    with caplog.at_level(logging.WARNING, logger="openfactory.product"):
        failed = confirm_in_repository(docs_repo="quayside-context",
                                       clone_url="file:///nowhere/at-all", slug="checkout",
                                       flow=None, confirmed_by="ines", language=language)

    assert (failed.ok, failed.detail) == (False, CAPABILITY[language]["failed"])
    assert ("OPENFACTORY_PRODUCT_WRITE_FAILED act=confirm capability checkout "
            "ref=capabilities/checkout.md — could not clone in quayside-context") in caplog.text
