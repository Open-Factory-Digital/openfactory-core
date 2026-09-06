"""The structural documents speak the project's Portuguese — pt-PT is not pt-BR.

THE FIRST LIVE BACKFILL, LISBON, 2026-09-06. The product is registered `pt-PT`; the agent's
directive already tells the two apart, so the five documents' prose came back in European
Portuguese — and every sentence the PLATFORM wrote around it came back in Brazilian Portuguese:
*arquivo* for file, *enxergou* for saw, *verbete* for a glossary entry, *mostrando*, *de fato*,
and the reader addressed with the Brazilian second person. `_words` served the one `pt` table to
every `pt-*` project, and that table is Brazilian by its own comment. A document half in one
Portuguese and half in the other reads as nobody's.

What this file holds:
  1. `pt-PT` is its own table, and the region is read whatever a person typed;
  2. no string in it — shared or overridden — carries a Brazilianism, so a key edited in `pt`
     cannot bring one back unnoticed;
  3. the two tables have exactly the same keys: an override cannot invent a key or lose one;
  4. the rendered survey, the document header and the questions a deterministic pass raises say
     *ficheiro* under `pt-PT` and *arquivo* under `pt-BR`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from openfactory.onboarding import context as ctx

#: the words that mark a sentence as Brazilian to a reader in Lisbon — word-bounded, so `teto`
#: does not match `completo` and `fato` does not match `fatos` in an unrelated string
BRAZILIANISMS = ("arquivo", "arquivos", "você", "vocês", "enxergou", "verbete", "mostrando",
                 "de fato", "detectada", "encanamento", "ao menos", "desenvolvedores",
                 "os demais", "teto", "acharia", "olhando", "seus arquivos", "não dá para")


def _brazilianisms_in(text: str) -> list[str]:
    return [w for w in BRAZILIANISMS if re.search(rf"\b{re.escape(w)}\b", text, re.IGNORECASE)]


# ── 1. the table and the region ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("language", ["pt-PT", "pt_PT", "PT-pt", "pt-pt"])
def test_pt_PT_is_read_whatever_a_person_typed(language):
    assert ctx._words(language)["t_file"] == "ficheiro", language


@pytest.mark.parametrize("language", ["pt-BR", "pt", "pt_BR", "PT"])
def test_every_other_portuguese_stays_brazilian(language):
    assert ctx._words(language)["t_file"] == "arquivo", language


def test_english_is_untouched():
    assert ctx._words("en")["t_file"] == "file"


# ── 2. no Brazilianism in any pt-PT string ───────────────────────────────────────────────────


def test_no_string_in_the_pt_PT_table_carries_a_brazilianism():
    offenders = {key: found for key, text in ctx._words("pt-PT").items()
                 if (found := _brazilianisms_in(text))}
    assert not offenders, (
        f"Brazilian wording reached the pt-PT table — an override is missing or a shared key "
        f"was edited: {offenders}")


def test_the_brazilian_table_is_still_brazilian():
    """The guard above would be decoration if the Brazilian table had quietly been rewritten."""
    assert _brazilianisms_in(ctx._words("pt-BR")["t_file"]) == ["arquivo"]


# ── 3. key parity ────────────────────────────────────────────────────────────────────────────


def test_the_two_portuguese_tables_have_exactly_the_same_keys():
    assert set(ctx._words("pt-PT")) == set(ctx._words("pt-BR")), (
        "an override invented a key or the table lost one — a renderer would KeyError on one "
        "language and not the other")
    assert set(ctx._PT_PT) <= set(ctx._HEADINGS["pt"]), "an override names a key `pt` lacks"


# ── 4. what a reader sees ────────────────────────────────────────────────────────────────────


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    return tmp_path


def test_the_rendered_survey_says_ficheiro_under_pt_PT_and_arquivo_under_pt_BR(tmp_path):
    s = ctx.survey(_repo(tmp_path))

    lisbon = ctx.render_survey(s, language="pt-PT")
    sao_paulo = ctx.render_survey(s, language="pt-BR")

    assert "ficheiros" in lisbon and not _brazilianisms_in(lisbon), _brazilianisms_in(lisbon)
    assert "arquivos" in sao_paulo


def test_the_document_header_and_the_questions_follow(tmp_path):
    s = ctx.survey(_repo(tmp_path))

    header = "\n".join(ctx._doc_header(s, ctx._words("pt-PT")))
    questions = ctx.propose_context(s, ask=None, language="pt-PT").questions

    assert "ficheiro" in header and not _brazilianisms_in(header)
    assert questions, "a module with no test must raise at least one question"
    leaked = {q: found for q in questions if (found := _brazilianisms_in(q))}
    assert not leaked, leaked
