"""Corpus health reaches EVERY prompt, and board write results are consumed — findings 6, 54, 56.

Three ways the module lied by omission:

- `_corpus_note()` reached exactly one consumer (`answer()`'s context default), so drafting,
  judging, refine and the queue reasoned over a broken corpus — two live versions of one promise —
  with no warning at all (finding 54). The note now rides `_role()`'s agent wrapper: one seam,
  every operation.
- `file_defect` called `ctx.corpus.get(...)` — a method `Corpus` never had — so every confirmed
  defect that CITED the requirement it violates (the case the prompt asks for) crashed with
  AttributeError after the channel had consumed the confirmation (finding 6).
- `file_defect`/`_file_one` discarded `set_column`'s bool, resurrecting the documented
  invisible-card defect through the failure path while the reply promised the client the card was
  queued (finding 56). `promote` always checked it; the siblings now do too.

Everything here drives the PRODUCTION methods with fakes injected only at the module's own seams
(agent, tracker, board) — no stubbed `file_defect`, no live network.
"""

from __future__ import annotations

import logging

from openfactory.contracts import AgentRunResult
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.product.config import ProductLink
from openfactory.product.corpus import Corpus, Finding, Requirement
from openfactory.product.loader import ProductContext
from openfactory.product.module import ProductModule

DOCS = "acmecorp/acme-books-documentation"
ADMIN = "U0ADMIN"


class _Harness:
    name = "recording"

    def __init__(self, answer="ok"):
        self.prompts: list[str] = []
        self.answer = answer

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.prompts.append(prompt)
        return AgentRunResult(ok=True, summary=self.answer)


class _Tracker:
    def __init__(self):
        self.created: list[tuple[str, str]] = []

    def find_ticket(self, *, title):
        return None

    def create_ticket(self, *, title, body):
        self.created.append((title, body))
        return f"#{500 + len(self.created)}"


class _Board:
    """`accepts=False` is the state finding 56 is about: `set_column` returns False (a rate-limited
    item edit, a refused move) and the card sits on the board with NO column."""

    def __init__(self, *, accepts=True):
        self.accepts = accepts
        self.placed: list[tuple[int, str]] = []

    def add_item(self, *, issue_url):
        return True

    def set_column(self, *, issue, issue_url, name):
        if not self.accepts:
            return False
        self.placed.append((issue, name))
        return True


def _broken_corpus() -> Corpus:
    """The live client's exact rot shape: one promise, two live versions, an error finding."""
    return Corpus(
        requirements=[Requirement(number=1, slug="x", path="0001-x.md", title="Pacote de fecho",
                                  status="accepted")],
        findings=[Finding(level="error", code="supersede-not-mutual", path="0002-y.md",
                          message="claims to supersede REQ-0001, but that file's status is "
                                  "'proposed'")])


def _module(tmp_path, *, corpus=None, answer="ok"):
    ctx = ProductContext(
        link=ProductLink(active=True, docs_repo=DOCS, kind="ok", reason="fine"),
        corpus=corpus or Corpus(requirements=[
            Requirement(number=1, slug="x", path="0001-x.md", title="Pacote de fecho",
                        status="accepted")]),
        docs_path=str(tmp_path), docs_commit="abc123", requirements_dir="requirements")
    project = Project(name="books", repo_path="/work/books",
                      product=ProductConfig(docs_repo=DOCS, admins=[ADMIN]))
    h = _Harness(answer)
    return ProductModule(project, context=ctx, agent=h), h


# ── finding 54: one seam, every consumer ───────────────────────────────────────────────────────
def test_corpus_errors_reach_the_DRAFT_prompt(tmp_path):
    """The exact failure: a draft touching a promise that exists in two live versions used to be
    argued from whichever file the model opened first, with no warning in the prompt."""
    mod, h = _module(tmp_path, corpus=_broken_corpus(),
                     answer='{"title":"t","must_be_true":["x"]}')

    assert mod.draft("mudar o pacote de fecho").ok is True
    assert "unresolved problem" in h.prompts[0]
    assert "supersede REQ-0001" in h.prompts[0]


def test_corpus_errors_reach_the_confirmation_JUDGE(tmp_path):
    """The judge decides whether to open a write in a person's name — over a corpus it must not
    trust silently."""
    mod, h = _module(tmp_path, corpus=_broken_corpus(), answer="neither")

    assert mod.confirmed("sim, mas explica primeiro", proposal="registrar o requisito") == "neither"
    assert "unresolved problem" in h.prompts[0]


def test_a_clean_corpus_adds_no_warning_to_any_prompt(tmp_path):
    mod, h = _module(tmp_path, answer='{"title":"t","must_be_true":["x"]}')
    mod.draft("x")
    assert "unresolved problem" not in h.prompts[0]


def test_the_note_travels_ONCE_not_twice(tmp_path):
    """`answer()` used to default the note into `context`; with the one-seam wrapper the same
    warning must not arrive duplicated."""
    mod, h = _module(tmp_path, corpus=_broken_corpus())
    mod.answer("como está o fecho?")
    assert h.prompts[0].count("unresolved problem") == 1


# ── finding 6: a defect that cites a requirement must FILE, not crash ──────────────────────────
def test_a_defect_that_CITES_a_requirement_is_filed_with_the_citation(tmp_path):
    """`ctx.corpus.get` — a method Corpus never had — crashed exactly the case the answer prompt
    asks her to produce ([[DEFEITO:REQ-NNNN]]), after the confirmation was already consumed."""
    mod, _ = _module(tmp_path)
    tracker = _Tracker()

    res = mod.file_defect(restated="o fecho não gera o pacote completo", reported_by="<@U1>",
                          violates=1, severity="alta", tracker=tracker, board=None)

    assert res.ok is True, res.detail
    _title, body = tracker.created[0]
    assert "REQ-0001" in body, "the violated promise is not cited"
    assert "0001-x.md" in body


def test_a_defect_citing_an_UNKNOWN_requirement_still_files(tmp_path):
    """`by_number` answers None for a number the corpus does not have — the defect lands with the
    honest 'could not point at the promise' section instead of crashing."""
    mod, _ = _module(tmp_path)
    tracker = _Tracker()

    res = mod.file_defect(restated="algo quebrou no fecho", reported_by="<@U1>",
                          violates=42, tracker=tracker, board=None)

    assert res.ok is True, res.detail
    assert "Não foi possível apontar" in tracker.created[0][1]


# ── finding 56: the board's `False` is a fact, not noise ───────────────────────────────────────
def test_a_refused_defect_placement_is_SAID_and_logged_not_swallowed(tmp_path, caplog):
    """`promote` checks `set_column`'s bool; `file_defect` discarded it — a column-less card that
    `readiness`/`propose_queue` (exact column match, no else-branch) can never surface, behind a
    reply promising the client it was queued."""
    mod, _ = _module(tmp_path)

    with caplog.at_level(logging.WARNING, logger="openfactory.product"):
        res = mod.file_defect(restated="o fecho não gera o pacote", reported_by="<@U1>",
                              violates=1, tracker=_Tracker(), board=_Board(accepts=False))

    assert res.ok is True, "the issue exists — reporting failure would invite a duplicate"
    assert "quadro" in res.detail, "the reply would still promise a queue the card is invisible to"
    assert any("OPENFACTORY_PRODUCT_DEFECT_NOT_PLACED" in r.getMessage() for r in caplog.records)


def test_an_accepted_defect_placement_keeps_the_reply_clean(tmp_path):
    mod, _ = _module(tmp_path)
    board = _Board()

    res = mod.file_defect(restated="o fecho não gera o pacote", reported_by="<@U1>",
                          violates=1, tracker=_Tracker(), board=board)

    assert res.ok is True and res.detail == ""
    assert board.placed == [("501", ProductModule.FILING_COLUMN)]


def test_a_refused_issue_placement_is_surfaced_per_item(tmp_path, caplog):
    """The sibling path (`_file_one`) had the same discarded bool."""
    mod, _ = _module(
        tmp_path,
        answer='{"issues": [{"title": "Gerar o pacote", "objective": "o", '
               '"acceptance_criteria": ["c"]}]}')

    with caplog.at_level(logging.WARNING, logger="openfactory.product"):
        results = mod.file_issues(
            Requirement(number=1, slug="x", path="0001-x.md", title="Pacote", status="accepted"),
            actor=ADMIN, tracker=_Tracker(), board=_Board(accepts=False))

    assert results[0].ok is True
    assert "coluna" in results[0].detail, "the invisible-card state is not reported"
    assert any("OPENFACTORY_PRODUCT_CARD_NOT_PLACED" in r.getMessage() for r in caplog.records)
