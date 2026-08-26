"""One section, one identity, whatever language the client speaks (#160).

`authoring.py` writes `## Acceptance criteria`. `_with_criteria` — the repair the product role runs
on a card that has none — wrote `## Critérios de aceite`, on every project, in every language.

That is not a translation bug. It is the SECOND NAME that `_ALSO_CALLED` exists to survive, minted
by us: a card through both writers carries two acceptance sections, they disagree, and whoever picks
it up builds whichever came first. `align_card`'s own docstring names this state as the defect it
exists to repair — and the repair manufactured it.

A HEADING IS AN IDENTITY, NOT PROSE. `_section_re` matches it, `_rewritten` strips by it, and the
executor's "nothing beyond the requirement" rule stands on the Source line that follows it. The
phrasebooks state the rule for themselves ("never an identity, never a key somebody matches on");
this is that rule applied to a card's structure. The one PROSE line under the headings is what
follows the project's language.
"""

from __future__ import annotations

import pytest

from openfactory.product.module import _ALSO_CALLED, _section_re, _with_criteria

ANSWER = {"criteria": ["it adds up"], "out_of_scope": ["the closing"], "questions": ["by when?"]}


@pytest.mark.parametrize("language", ["pt-BR", "en", None, "de"])
def test_the_headings_are_the_SAME_whatever_the_client_speaks(language):
    body = _with_criteria("original text", ANSWER, agent="Produto", language=language)

    assert "## Acceptance criteria" in body
    assert "## Out of scope" in body
    assert "## Open questions" in body
    assert "Critérios de aceite" not in body and "Fora de escopo" not in body


def test_and_the_SENTENCE_under_them_is_the_clients_own():
    """The attribution line is prose — somebody reads it — so it is the half that translates."""
    pt = _with_criteria("t", ANSWER, agent="Produto", language="pt-BR")
    en = _with_criteria("t", ANSWER, agent="Produto", language="en")

    assert "critérios escritos a partir do que já estava descrito" in pt
    assert "criteria written from what was already described" in en
    assert pt != en


def test_the_card_the_platform_WRITES_and_the_card_it_READS_use_one_name():
    """The two writers, measured against each other. `issue_body` is the main one; `_with_criteria`
    is the repair. Two names is the state that put two acceptance sections on one card."""
    from openfactory.product.authoring import issue_body
    from openfactory.product.role import IssueDraft

    authored = issue_body(IssueDraft(acceptance_criteria=["a"], out_of_scope=["b"], cites=1),
                          requirement_path="requirements/REQ-0001.md", docs_repo="o/docs")
    repaired = _with_criteria("t", ANSWER, agent="Produto", language="pt-BR")

    for heading in ("## Acceptance criteria", "## Out of scope"):
        assert heading in authored and heading in repaired, heading


@pytest.mark.parametrize("old_name", ["Critérios de aceite", "Criterios de aceite",
                                      "Fora de escopo", "Em aberto"])
def test_every_name_ever_MINTED_stays_readable(old_name):
    """Cards written before this are on real boards. A reader that stops recognising the old name
    silently reads an empty section and adds a second one — which is the defect, restarted."""
    canonical = {"Critérios de aceite": "Acceptance criteria",
                 "Criterios de aceite": "Acceptance criteria",
                 "Fora de escopo": "Out of scope",
                 "Em aberto": "Open questions"}[old_name]

    text = f"before\n\n## {old_name}\n\n- [ ] the old promise\n\n## Source\n\nREQ-0001\n"

    assert _section_re(canonical).search(text), (
        f"a card written as '{old_name}' is invisible to the reader of '{canonical}'")


def test_and_the_alias_table_covers_every_section_the_repair_writes():
    """The trap this file is about, stated as a property: a section written under two names and
    listed under one is the half the alignment leaves behind. Measured — `Em aberto` was exactly
    that, and the strip named it directly, so the day the heading was canonicalised the retired
    text's open questions survived the alignment."""
    written = {"acceptance criteria", "out of scope", "open questions"}

    assert written <= set(_ALSO_CALLED), (
        f"sections the repair writes with no alias entry: {sorted(written - set(_ALSO_CALLED))}")
