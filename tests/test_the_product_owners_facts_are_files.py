"""The product owner's facts are files — the board whole, the open loops, the decisions register
(#33, slice 4; ADR-0041's pattern on the PO's side of the line).

`role.py::_board_section` injects the board as prose under a budget: `Done` is numbers alone, a
long column loses its titles, and what the role asked people to decide reaches the prompt only as
the one-line `pending` summary. The tech-lead had exactly this shape (#169) and moved its facts to
files the harness greps (`techlead/pack.py`). The product role's docs and code were files already;
now the board, the loops and the decisions are files beside them — and the manifest names what
could NOT be read, which is the instrument #33's measurement needs.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from openfactory.memory.ledger import ACCEPTANCE, CLOSED, DECISION, Loop, open_loop
from openfactory.product import facts
from openfactory.product.role import ProductRole
from openfactory.techlead.pack import _PREFIX

ROOT = Path(__file__).resolve().parent.parent


class _Agent:
    name = "fake"


def _card(number, title, column, state="open", reason=""):
    return SimpleNamespace(number=number, title=title, column=column, state=state,
                           state_reason=reason)


def _board(done: int = 60) -> list:
    cards = [_card(1, "Login with SSO", "To Do"), _card(2, "Export CSV", "In Progress")]
    cards += [_card(100 + i, f"Finished thing {i}", "Done", state="closed",
                    reason="completed" if i % 7 else "not_planned") for i in range(done)]
    return cards


def _loops() -> list[Loop]:
    asked = open_loop(DECISION, "relatorio-mensal", owner="product", ts="2026-09-01T10:00:00",
                      about="C0ABC", context={"asked": "o relatório mensal entra no Q4?"})
    answered = open_loop(DECISION, "exportar-csv", owner="product", ts="2026-08-20T10:00:00",
                         context={"asked": "exportar CSV fica para depois?"})
    closed = Loop(**{**answered.__dict__, "state": CLOSED, "outcome": "answered"})
    delivery = open_loop(ACCEPTANCE, "12", owner="product", ts="2026-08-30T09:00:00")
    theirs = open_loop(DECISION, "not-ours", owner="techlead", ts="2026-09-01T11:00:00")
    return [asked, answered, closed, delivery, theirs]


# ── rendering: whole, and honest about a failed read ───────────────────────────────────────────

def test_the_board_file_is_WHOLE_where_the_prompt_section_is_budgeted():
    """The section drops `Done`'s titles for economy and says so; the file is where they are."""
    board = _board(done=60)
    text = facts.render_board(board)
    section = "\n".join(ProductRole(_Agent(), cards=board)._board_section())

    assert "Finished thing 59" in text and "Finished thing 59" not in section
    assert "## Done (60)" in text and "[closed:not_planned]" in text, \
        "identity never travels without its qualifier — the file says how a card closed"
    assert "#1 [open] — Login with SSO" in text and "## To Do (1)" in text
    assert "not the same as absent from the product" in text


def test_a_failed_board_read_renders_NOTHING_and_becomes_a_gap():
    """A file saying 'the board is empty' over a read that failed is the claim this pack exists
    to prevent. `None` is a failed read; `[]` is an empty board, and the two stay apart."""
    assert facts.render_board(None) == ""
    assert "empty" in facts.render_board([])

    files, gaps = facts.gather("acme", None, read=lambda _p: [])
    assert "board.md" not in files
    assert any("could not be read" in g and "do not report any card as absent" in g for g in gaps)


def test_the_loops_file_is_what_the_role_waits_on_and_nobody_else_s():
    text = facts.render_loops(_loops())

    assert "decision `relatorio-mensal`" in text and "since 2026-09-01" in text
    assert "o relatório mensal entra no Q4?" in text and "(about C0ABC)" in text
    assert "acceptance `12`" in text
    assert "exportar-csv" not in text, "an answered decision is not waiting on anybody"
    assert "not-ours" not in text, "the tech-lead's loops are its own pack's business"
    assert "closes by OBSERVATION" in text
    assert "Nothing is open" in facts.render_loops([])


def test_the_decisions_register_keeps_the_answered_ones_with_their_outcome():
    text = facts.render_decisions(_loops())

    assert "`exportar-csv` — ANSWERED (answered)" in text
    assert "`relatorio-mensal` — OPEN: o relatório mensal entra no Q4?" in text
    assert text.index("exportar-csv") < text.index("relatorio-mensal"), "oldest first: a history"
    assert "not-ours" not in text
    assert "never a guess about what was decided" in text


def test_an_unreadable_ledger_is_a_GAP_not_an_empty_file():
    def unreadable(_project):
        raise RuntimeError("database is locked")

    files, gaps = facts.gather("acme", _board(2), read=unreadable)

    assert "board.md" in files and "loops.md" not in files and "decisions.md" not in files
    assert any("ledger could not be read" in g and "database is locked" in g for g in gaps)
    assert any("unknown, not empty" in g for g in gaps)


# ── writing: the pack, its manifest, and the previous pack ─────────────────────────────────────

def test_the_pack_is_written_with_a_manifest_that_names_the_gaps(tmp_path):
    files, gaps = facts.gather("acme", _board(3), read=lambda _p: _loops())
    gaps.append("the comments of #2 could not be read (HTTP 502)")

    into = facts.write_facts(tmp_path, files=files, gaps=gaps)

    assert into is not None and into.name.startswith(_PREFIX)
    assert {p.name for p in into.iterdir()} == {"README.md", "board.md", "loops.md",
                                                "decisions.md"}
    readme = (into / "README.md").read_text()
    for name in facts.FILES:
        assert f"`{into.name}/{name}`" in readme
    assert "HTTP 502" in readme and "FAILED READS, not absences" in readme


def test_the_previous_pack_is_removed_because_the_root_is_stable(tmp_path):
    """The tech-lead writes into a per-job worktree that is thrown away; this role's workspace is
    rebuilt in place on every message, so a directory per message would accumulate for ever."""
    files, _ = facts.gather("acme", _board(1), read=lambda _p: [])
    first = facts.write_facts(tmp_path, files=files, gaps=[])
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "keep.md").write_text("theirs", encoding="utf-8")

    second = facts.write_facts(tmp_path, files=files, gaps=[])

    assert second is not None and second != first
    assert not first.exists() and second.is_dir()
    assert (tmp_path / "docs" / "keep.md").read_text() == "theirs", "only our prefix is touched"


def test_an_unwritable_root_costs_the_pack_and_never_the_answer(tmp_path):
    missing = tmp_path / "nowhere"
    missing.write_text("a file where a directory was expected", encoding="utf-8")

    assert facts.write_facts(missing, files={"board.md": "# x\n" * 10}, gaps=[]) is None


def test_no_git_directory_is_conjured_into_a_composed_root(tmp_path):
    """`techlead.pack._exclude` mkdirs `.git/info` — right in a checkout, wrong in a composed
    workspace root that is not a repository at all."""
    files, _ = facts.gather("acme", _board(1), read=lambda _p: [])

    facts.write_facts(tmp_path, files=files, gaps=[])
    assert not (tmp_path / ".git").exists()

    (tmp_path / ".git").mkdir()
    into = facts.write_facts(tmp_path, files=files, gaps=[])
    assert into.name in (tmp_path / ".git" / "info" / "exclude").read_text()


# ── the mount decides, and the role is told only when it is true ───────────────────────────────

def test_mounted_reports_the_facts_only_when_the_manifest_is_ON_DISK(tmp_path):
    from openfactory.product.module import ProductModule

    root = tmp_path / "ws"
    (root / "docs").mkdir(parents=True)
    (root / "code").mkdir()
    pack = root / f"{_PREFIX}deadbeef"
    fake = SimpleNamespace(_workspace=lambda: None, _combined=str(root),
                           _mounted_code=str(root / "code"), _facts_dir=pack)

    assert "facts" not in ProductModule.mounted(fake), "a pack nobody wrote was announced"

    pack.mkdir()
    (pack / "README.md").write_text("# facts\n", encoding="utf-8")
    assert ProductModule.mounted(fake)["facts"] == pack.name

    docs_only = SimpleNamespace(_workspace=lambda: None, _combined=str(root),
                                _mounted_code=None, _facts_dir=pack)
    assert ProductModule.mounted(docs_only)["facts"] == pack.name, \
        "documentation-only is still a workspace with a pack in it"


def test_the_section_names_the_files_and_the_rule_about_failed_reads():
    role = ProductRole(_Agent(), mounted={"docs": "docs", "code": "code",
                                          "facts": ".openfactory-facts-ab12"})
    text = "\n".join(role._facts_section())

    assert ".openfactory-facts-ab12/README.md" in text
    assert ".openfactory-facts-ab12/board.md" in text and "WHOLE" in text
    assert "loops.md" in text and "decisions.md" in text
    assert "FAILED READ is not an absence" in text


def test_a_role_with_no_pack_is_told_NOTHING_and_the_mount_decides(monkeypatch, tmp_path):
    """Mirrors the bundle's guard: a pack under THIS process's cwd must not conjure a section
    for a role whose workspace has none."""
    (tmp_path / f"{_PREFIX}cafe").mkdir()
    (tmp_path / f"{_PREFIX}cafe" / "README.md").write_text("# facts\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert ProductRole(_Agent(), mounted={"docs": "docs", "code": "code"})._facts_section() == []


def test_the_prompt_carries_the_section_after_the_bundle_s():
    role = ProductRole(_Agent(), mounted={"docs": "docs", "code": "code", "okf": "docs/.okf",
                                          "facts": ".openfactory-facts-ab12"})
    prompt = role._prompt("say hello", "")

    assert "# The facts, as files" in prompt
    assert prompt.index("# What the code itself says") < prompt.index("# The facts, as files")


def test_the_module_writes_the_pack_and_logs_the_measurement(tmp_path, monkeypatch, caplog):
    """The one line per pass with the file and gap counts — the number #33's measurement adds
    up, which a manifest inside a worktree cannot be."""
    from openfactory.product.module import ProductModule

    root = tmp_path / "ws"
    root.mkdir()
    fake = SimpleNamespace(project=SimpleNamespace(name="acme"), _combined=str(root),
                           _workspace=lambda: None, _board_cards=lambda: None)
    monkeypatch.setattr(facts, "gather",
                        lambda name, cards, read=None: ({"loops.md": "# loops\n" * 5},
                                                        ["the board could not be read"]))

    with caplog.at_level("INFO", logger="openfactory.product"):
        into = ProductModule._write_facts(fake)

    assert into is not None and (into / "README.md").is_file()
    assert "OPENFACTORY_PRODUCT_FACTS project=acme files=1 gaps=1 written=yes" in caplog.text


def test_the_role_is_built_with_the_pack_written_first(tmp_path, monkeypatch):
    """The wiring, exercised: `_role()` writes the pack and hands the role a mount that names
    it — the seam every conversational operation goes through, so a pack written by nothing
    would be the fifteenth mechanism built and reached by nothing."""
    from openfactory.product.loader import Corpus
    from openfactory.product.module import ProductModule

    root = tmp_path / "ws"
    (root / "docs").mkdir(parents=True)
    (root / "code").mkdir()
    monkeypatch.setattr(facts, "gather",
                        lambda name, cards, read=None: ({"board.md": "# board\n" * 5}, []))
    fake = SimpleNamespace(
        _agent=_Agent(), _corpus_note=lambda: "",
        project=SimpleNamespace(name="acme", product=None, language=""),
        context=lambda: SimpleNamespace(corpus=Corpus(), domain=None),
        _board_cards=lambda: [], _workspace=lambda: None,
        _combined=str(root), _mounted_code=str(root / "code"))
    fake._write_facts = lambda: ProductModule._write_facts(fake)
    fake.mounted = lambda: ProductModule.mounted(fake)

    role = ProductModule._role(fake)

    where = role.mounted.get("facts")
    assert where and (root / where / "README.md").is_file() and (root / where / "board.md").is_file()
    assert "# The facts, as files" in "\n".join(role._facts_section())


def test_the_client_s_document_says_what_the_role_can_open():
    text = (ROOT / "docs/reference/product-role.md").read_text()
    assert "facts pack" in text and "could **not** be read" in text
