"""The notes the product role leaves on a card speak the PROJECT's language, and the capability
write answers in the conversation's (#538).

#513 moved every detail the role's writes answer into the voice. Two kinds of Portuguese-only text
were outside its scope and stayed:

- THE NOTES ON THE CARD. `_closing_note`, `_survivor_note`, `_align_note`, `_repoint_note` and
  `_refine_note` were composed in `module.py`, and #513 fixed only their `#`. MEASURED ON THE #513
  BRANCH (6fd4244) with this file: on a project that speaks English, a card closed in favour of
  another was left saying "fechado a pedido de U0ADMIN, em favor do #288: o trabalho passa a ser
  acompanhado lá.", and the sweep that re-points an orphan wrote "este cartão passou a executar o
  requisito 6, a pedido de U0ADMIN: …" on it — all five notes, Portuguese on an English card.
- `capabilities.confirm_in_repository` refused a name with "esse nome não é o de uma capacidade"
  while the voice already held `not_a_capability` in both languages — and gave six other answers
  of its own in Portuguese, one of them carrying git's output.

A CARD BELONGS TO THE PROJECT, NOT TO A CONVERSATION: somebody reads it months later with no idea
which conversation asked. So the notes follow `Project.language`, as the voice's `correction_note`
and `change_accepted_note` already did; the capability write answers whoever asked, in the
language its caller passes — the project's, as every write of the product's record does (#513).

WHAT IS DRIVEN HERE. Each note through the verb that writes it, on `test_card_maintenance`'s bed
(the real module, a tracker that records what it is asked), once per language, and compared whole
with the sentence written out below: pt-BR byte for byte as it read before — but for refine's
"1 critérios", now "1 critério" — and en its translation. The capability write through
`ProductModule.confirm_capability` on `test_capabilities_and_checks`'s bed (a real context
repository, a real clone), and directly where the module refuses before it is reached.
"""

from __future__ import annotations

import logging

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

SIG = "**Nina (produto):**"

#: Every note, as the card is left saying it — pt-BR as it always read.
NOTES = {
    "pt-BR": {
        "closed": (f"{SIG} fechado a pedido de {ADMIN}, em favor do #288: o trabalho passa a ser "
                   f"acompanhado lá.\n\nera o mesmo pedido"),
        "survivor": (f"{SIG} o #511 foi fechado em favor deste, a pedido de {ADMIN}. Se havia "
                     f"algo escrito lá que não está aqui, vale trazer antes de começar."),
        "removed": f"{SIG} fechado a pedido de {ADMIN}.\n\nnão precisa mais",
        "aligned": (f"{SIG} este cartão passou a executar o requisito 6, e reescrevi o que precisa "
                    f"ser verdade para dá-lo por pronto a partir dele — o texto que ele seguia "
                    f"antes foi substituído. Corrijam se eu entendi errado.\n\nO que eu não "
                    f"consegui determinar:\n- quem assina o aviso?"),
        "repointed": (f"{SIG} este cartão passou a executar o requisito 6, a pedido de {ADMIN}: o "
                      f"requisito 4, que ele citava, foi substituído por aquele.\n\n**O que está "
                      f"escrito aqui como \"pronto\" continua igual, e foi escrito a partir do "
                      f"texto antigo.** Não revisei nada disso: rever pode mudar o que vai ser "
                      f"construído, e essa é uma decisão de vocês, não uma arrumação minha."),
        "refined": (f"{SIG} este item não dizia quando estaria pronto, então seria recusado na "
                    f"entrada. Escrevi 1 critério a partir do que já estava descrito — corrijam "
                    f"se eu entendi errado.\n\nO que eu não consegui determinar:\n- quem confere "
                    f"o total?"),
    },
    "en": {
        "closed": (f"{SIG} closed at the request of {ADMIN}, in favour of #288: the work is "
                   f"followed there now.\n\nera o mesmo pedido"),
        "survivor": (f"{SIG} #511 was closed in favour of this one, at the request of {ADMIN}. If "
                     f"something was written there that is not here, bring it over before "
                     f"starting."),
        "removed": f"{SIG} closed at the request of {ADMIN}.\n\nnão precisa mais",
        "aligned": (f"{SIG} this card now carries out requirement 6, and I rewrote what has to be "
                    f"true to call it done from that text — the one it followed before was "
                    f"replaced. Correct me if I got it wrong.\n\nWhat I could not determine:\n"
                    f"- quem assina o aviso?"),
        "repointed": (f"{SIG} this card now carries out requirement 6, at the request of {ADMIN}: "
                      f"requirement 4, which it cited, was replaced by that one.\n\n**What is "
                      f"written here as \"done\" is unchanged, and it was written from the older "
                      f"text.** I revised none of it: revising it can change what gets built, and "
                      f"that is your decision, not tidying of mine."),
        "refined": (f"{SIG} this item did not say when it would be done, so pickup would have "
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


@pytest.mark.parametrize("language", sorted(NOTES))
def test_a_note_names_a_jira_card_as_jira_does_and_nobody_as_the_team(language):
    """`ref_label` names the card, `#12` on a numbered board and `DAR-9` on Jira; a note nobody
    asked for by name is the team's, in the project's language — "o time" was the only word for it."""
    closed = voice.closing_note(in_favour_of="DAR-9", actor="", language=language)
    survivor = voice.survivor_note(closed="#DAR-10", actor="", language=language)
    repointed = voice.repoint_note(cited=4, successor=6, language=language)

    team = {"pt-BR": "o time", "en": "the team"}[language]
    assert closed.endswith(f"{team}, " + {"pt-BR": "em favor do DAR-9: o trabalho passa a ser "
                                                   "acompanhado lá.",
                                          "en": "in favour of DAR-9: the work is followed there "
                                                "now."}[language]), closed
    assert f"{team}." in survivor and "DAR-10" in survivor and "#DAR" not in survivor, survivor
    assert "a pedido de" not in repointed and "at the request of" not in repointed, (
        "a re-point nobody asked for names somebody")


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
