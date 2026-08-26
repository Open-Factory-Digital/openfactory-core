"""The requirements corpus — parsing, indexing, and the decay it exists to detect (ADR-0019 §3).

The failure this guards against is silent: nothing crashes, a document simply stops being true. So
the tests are written around the specific ways that happens rather than around the happy path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openfactory.product import load_corpus
from openfactory.product.corpus import ACCEPTED, PROPOSED, parse_requirement

BODY = """# REQ-{n:04d} — {title}

- **Status:** {status}
- **Asked by:** Alice
- **Date:** 2026-07-26
- **Supersedes:** {supersedes}

## Why

Because.

## What must be true

- [ ] something observable

## Affects

- `AcmeCorp/acme-books`

## Decisions taken during execution

| date | decision | where it came from |
|---|---|---|
{rows}"""


def _write(d: Path, n: int, *, title="a thing", status=PROPOSED, supersedes="—",
           rows="", name=None) -> Path:
    p = d / (name or f"{n:04d}-a-thing.md")
    p.write_text(BODY.format(n=n, title=title, status=status, supersedes=supersedes, rows=rows))
    return p


def _codes(corpus) -> set[str]:
    return {f.code for f in corpus.findings}


# ── parsing ─────────────────────────────────────────────────────────────────────────────────────

def test_a_requirement_carries_its_provenance(tmp_path):
    _write(tmp_path, 1, title="Recurring-payment proposals", status=ACCEPTED,
           rows="| 2026-07-26 | scope cut to weekly only | #504 |")
    r = load_corpus(tmp_path).by_number(1)
    assert r.title == "Recurring-payment proposals"
    assert r.status == ACCEPTED and r.asked_by == "Alice" and r.date == "2026-07-26"
    assert r.affects == ["AcmeCorp/acme-books"]
    assert r.has_decisions is True


def test_the_number_comes_from_the_FILENAME_so_two_files_cannot_share_an_identity(tmp_path):
    _write(tmp_path, 1, name="0001-first.md")
    _write(tmp_path, 1, name="0002-second.md")  # heading says REQ-0001, filename says 0002
    c = load_corpus(tmp_path)
    assert {r.number for r in c.requirements} == {1, 2}
    assert "number-mismatch" in _codes(c)


def test_a_duplicate_number_is_refused_rather_than_letting_the_last_file_win(tmp_path):
    _write(tmp_path, 3, name="0003-one.md")
    _write(tmp_path, 3, name="0003-two.md")
    c = load_corpus(tmp_path)
    assert len(c.requirements) == 1
    assert "duplicate-number" in _codes(c)


def test_a_badly_named_file_is_a_finding_not_a_crash(tmp_path):
    (tmp_path / "notes.md").write_text("# REQ-0009 — stray")
    _write(tmp_path, 1)
    c = load_corpus(tmp_path)
    assert [r.number for r in c.requirements] == [1]  # the good one still loads
    assert "filename" in _codes(c)


def test_the_template_is_never_counted_as_a_requirement(tmp_path):
    _write(tmp_path, 0, name="0000-template.md")
    assert load_corpus(tmp_path).requirements == []


def test_a_missing_directory_reports_instead_of_raising(tmp_path):
    c = load_corpus(tmp_path / "nope")
    assert c.requirements == [] and "no-directory" in _codes(c)


@pytest.mark.parametrize("line", [
    "- **Status:** accepted",
    "- Status: accepted",
    "* **Status**: ACCEPTED",
    "-   **Status:**   accepted   <!-- proposed · accepted -->",
])
def test_status_survives_a_human_editing_markdown_by_hand(tmp_path, line):
    (tmp_path / "0001-x.md").write_text(f"# REQ-0001 — x\n\n{line}\n")
    assert load_corpus(tmp_path).by_number(1).status == ACCEPTED


# ── status must never over-promise ──────────────────────────────────────────────────────────────

def test_an_unreadable_status_falls_back_to_PROPOSED_never_to_accepted(tmp_path):
    """An unreadable status must not promote a draft into something the factory will build."""
    (tmp_path / "0001-x.md").write_text("# REQ-0001 — x\n\n- **Status:** probably fine?\n")
    c = load_corpus(tmp_path)
    assert c.by_number(1).status == PROPOSED
    assert "status-unknown" in _codes(c)


def test_a_missing_status_falls_back_to_PROPOSED_with_a_warning(tmp_path):
    (tmp_path / "0001-x.md").write_text("# REQ-0001 — x\n\nno metadata at all\n")
    c = load_corpus(tmp_path)
    assert c.by_number(1).status == PROPOSED
    assert "status-missing" in _codes(c)


def test_superseded_requirements_are_kept_but_never_counted_as_live(tmp_path):
    """The history of what was decided and then reversed is what stops the same question being
    asked a third time — but it must never be handed to an agent as current truth."""
    _write(tmp_path, 1, status="superseded-by 0002", name="0001-old.md")
    _write(tmp_path, 2, status=ACCEPTED, supersedes="0001", name="0002-new.md",
           rows="| 2026-07-26 | replaced 0001 | thread |")
    c = load_corpus(tmp_path)
    assert len(c.requirements) == 2
    assert [r.number for r in c.live()] == [2]
    assert c.by_number(1).superseded_by == 2


def test_superseded_without_a_target_is_an_error_because_it_sends_the_reader_nowhere(tmp_path):
    _write(tmp_path, 1, status="superseded")
    assert "superseded-without-target" in _codes(load_corpus(tmp_path))


# ── cross-file consistency ──────────────────────────────────────────────────────────────────────

def test_a_dangling_superseded_by_is_an_error(tmp_path):
    _write(tmp_path, 1, status="superseded-by 0099")
    assert "dangling-superseded-by" in _codes(load_corpus(tmp_path))


def test_a_requirement_cannot_supersede_itself(tmp_path):
    _write(tmp_path, 1, status="superseded-by 0001")
    assert "self-superseded" in _codes(load_corpus(tmp_path))


def test_both_halves_of_a_replacement_must_agree(tmp_path):
    """Otherwise the corpus asserts that one requirement is both replaced and current — and a
    reader (or an agent) has no way to tell which half to believe."""
    _write(tmp_path, 1, status=ACCEPTED, name="0001-old.md",
           rows="| 2026-07-26 | shipped | #1 |")
    _write(tmp_path, 2, status=ACCEPTED, supersedes="0001", name="0002-new.md",
           rows="| 2026-07-26 | replaced 0001 | #2 |")
    c = load_corpus(tmp_path)
    assert "supersede-not-mutual" in _codes(c)


def test_superseding_a_requirement_that_does_not_exist_is_an_error(tmp_path):
    _write(tmp_path, 2, supersedes="0099")
    assert "dangling-supersedes" in _codes(load_corpus(tmp_path))


# ── the rot signal ──────────────────────────────────────────────────────────────────────────────

def test_an_accepted_requirement_with_no_write_back_is_FLAGGED(tmp_path):
    """THE failure mode ADR-0019 names: if execution outcomes stop reaching the documents, the
    corpus becomes a wish-list describing a product nobody built. Silent by nature, so it has to be
    detected rather than waited for."""
    _write(tmp_path, 1, status=ACCEPTED, rows="")
    c = load_corpus(tmp_path)
    assert "no-write-back" in _codes(c)
    assert [f.level for f in c.findings if f.code == "no-write-back"] == ["warn"]


def test_a_proposed_requirement_is_not_nagged_about_write_back(tmp_path):
    """Nothing has been executed yet, so there is nothing to write back. A validator that cries
    wolf on every draft is one nobody reads."""
    _write(tmp_path, 1, status=PROPOSED, rows="")
    assert "no-write-back" not in _codes(load_corpus(tmp_path))


def test_the_template_header_row_is_not_mistaken_for_a_decision(tmp_path):
    """The scaffold ships an empty table. Counting its header as a write-back would make every
    fresh requirement look maintained."""
    _write(tmp_path, 1, status=ACCEPTED, rows="")
    assert load_corpus(tmp_path).by_number(1).has_decisions is False


def test_accepted_without_provenance_warns_but_still_loads(tmp_path):
    (tmp_path / "0001-x.md").write_text(
        "# REQ-0001 — x\n\n- **Status:** accepted\n\n"
        "## Decisions taken during execution\n\n| date | decision | where |\n|---|---|---|\n"
        "| 2026-07-26 | done | #1 |\n")
    c = load_corpus(tmp_path)
    assert c.by_number(1) is not None
    assert {"no-asker", "no-date"} <= _codes(c)


# ── robustness ──────────────────────────────────────────────────────────────────────────────────

def test_one_broken_file_never_takes_the_whole_corpus_down(tmp_path):
    """Taking the product role offline over one typo is far worse than flagging one requirement."""
    _write(tmp_path, 1)
    (tmp_path / "0002-binary.md").write_bytes(b"\xff\xfe\x00 not utf-8 \xff")
    _write(tmp_path, 3)
    c = load_corpus(tmp_path)
    assert {r.number for r in c.requirements} >= {1, 3}


def test_non_markdown_files_are_ignored_quietly(tmp_path):
    _write(tmp_path, 1)
    (tmp_path / "diagram.png").write_bytes(b"\x89PNG")
    (tmp_path / "sub").mkdir()
    c = load_corpus(tmp_path)
    assert len(c.requirements) == 1 and c.errors == []


def test_an_empty_file_is_a_finding_not_an_exception(tmp_path):
    (tmp_path / "0001-empty.md").write_text("")
    c = load_corpus(tmp_path)
    assert c.by_number(1) is not None and "title-missing" in _codes(c)


def test_parse_requirement_reports_the_filename_in_every_finding(tmp_path):
    """A validator that says "3 problems" without saying where is one nobody runs twice."""
    req, findings = parse_requirement(Path("bad name.md"), "")
    assert req is None
    assert findings and all(f.path == "bad name.md" for f in findings)


def test_the_summary_separates_DECISIONS_from_readings_of_the_code(tmp_path):
    """"we have 40 requirements" must never quietly mean "40 readings of the code and no
    decisions" — the distinction the `observed` status exists to preserve."""
    _write(tmp_path, 1, status=ACCEPTED, rows="| 2026-07-26 | shipped | #1 |")
    _write(tmp_path, 2, status="observed", name="0002-x.md")
    _write(tmp_path, 3, status="superseded-by 0001", name="0003-x.md")
    s = load_corpus(tmp_path).summary()
    assert "3 requirements" in s
    assert "1 accepted" in s
    assert "1 observed (unconfirmed)" in s
    assert "error" in s and "warning" in s


def test_the_real_template_shipped_to_clients_parses_and_is_excluded():
    """The scaffold in the documentation repo must stay loadable — if it drifts from the parser,
    every new client starts with a corpus full of findings."""
    tpl = Path(__file__).resolve().parents[1] / "openfactory" / "org_defaults" / "requirements"
    if not tpl.is_dir():
        pytest.skip("template not vendored in this checkout")
    c = load_corpus(tpl)
    assert c.requirements == [] and c.errors == []
