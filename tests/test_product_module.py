"""The module's front door: who may do what, and how it behaves when it cannot.

Called straight from a chat listener, so the contract under test is that every path returns a
result carrying a sentence — never an exception, never a silent no-op. A request that vanishes is
indistinguishable from a broken bot, and the person simply tries again.
"""

from __future__ import annotations

import pytest

from openfactory.contracts import AgentRunResult
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.product.config import ProductLink
from openfactory.product.corpus import Corpus, Finding, Requirement
from openfactory.product.loader import ProductContext
from openfactory.product.module import ProductModule, may_act, unauthorized_message

DOCS = "acmecorp/acme-books-documentation"
ADMIN, OUTSIDER = "U0ADMIN", "U0RANDOM"


class _Harness:
    name = "recording"

    def __init__(self, answer="ok"):
        self.prompts: list[str] = []
        self.answer = answer

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.prompts.append(prompt)
        return AgentRunResult(ok=True, summary=self.answer)


def _project(**kw):
    cfg = kw.pop("product", {"docs_repo": DOCS, "slack_admins": [ADMIN]})
    return Project(name="books", language="pt-BR", repo_path="/work/books",
                   product=ProductConfig(**cfg) if cfg is not None else None)


def _ctx(tmp_path, *, active=True, corpus=None, reason="nope"):
    return ProductContext(
        link=ProductLink(active=active, docs_repo=DOCS, kind="ok" if active else "config",
                         reason="fine" if active else reason),
        corpus=corpus or Corpus(requirements=[
            Requirement(number=1, slug="x", path="0001-x.md", title="Immutable statements",
                        status="accepted")]),
        docs_path=str(tmp_path), docs_commit="abc123", requirements_dir="requirements")


def _module(tmp_path, *, answer="ok", **kw):
    h = _Harness(answer)
    return ProductModule(_project(**kw.pop("project_kw", {})), context=_ctx(tmp_path, **kw),
                         agent=h), h


# ── authority ───────────────────────────────────────────────────────────────────────────────────

def test_only_listed_users_may_make_it_write():
    p = _project()
    assert may_act(p, ADMIN) is True
    assert may_act(p, OUTSIDER) is False


def test_an_empty_allowlist_means_nobody_which_is_the_safe_default():
    """Enabling the module must never silently hand out authoring rights."""
    from openfactory.product.voice import jargon_in

    p = _project(product={"docs_repo": DOCS})
    assert may_act(p, ADMIN) is False
    msg = unauthorized_message(p)
    assert "ainda não há ninguém" in msg           # says WHY, not just no
    assert jargon_in(msg) == []                     # …and says it to a client


def test_a_project_without_the_module_authorises_nobody():
    assert may_act(Project(name="x", repo_path="/t"), ADMIN) is False


def test_a_switched_off_module_authorises_nobody_either():
    p = _project(product={"docs_repo": DOCS, "slack_admins": [ADMIN], "enabled": False})
    assert may_act(p, ADMIN) is False


@pytest.mark.parametrize("user", ["", None, " ", "u0admin"])
def test_authority_is_an_exact_match(user):
    """A near-miss must not authorise: Slack ids are opaque and case-sensitive."""
    assert may_act(_project(), user) is False


# ── reading is open ─────────────────────────────────────────────────────────────────────────────

def test_anyone_may_ask_and_the_corpus_index_reaches_the_model(tmp_path):
    mod, h = _module(tmp_path, answer="Reconciled statements are immutable (REQ-0001).")
    res = mod.answer("are statements immutable?")
    assert res.ok and "REQ-0001" in res.text
    assert "REQ-0001" in h.prompts[0]


def test_drafting_is_read_only_so_it_is_not_gated(tmp_path):
    """The gate is on RECORDING a requirement, not on thinking about one — a draft writes nothing
    and is exactly what a conversation needs before anyone decides."""
    mod, _ = _module(tmp_path, answer='{"title":"t","must_be_true":["x"]}')
    assert mod.draft("let admins edit", asked_by="Alice").ok is True


def test_corpus_problems_travel_with_every_answer(tmp_path):
    """A role reasoning over a corpus with dangling references must say so rather than answer
    confidently from a broken map."""
    corpus = Corpus(
        requirements=[Requirement(number=1, slug="x", path="0001-x.md", status="accepted")],
        findings=[Finding(level="error", code="dangling-superseded-by", path="0001-x.md",
                          message="superseded by REQ-0099, which does not exist")])
    mod, h = _module(tmp_path, corpus=corpus)
    mod.answer("anything?")
    assert "unresolved problem" in h.prompts[0]
    assert "REQ-0099" in h.prompts[0]


def test_a_clean_corpus_adds_no_noise_to_the_prompt(tmp_path):
    mod, h = _module(tmp_path)
    mod.answer("anything?")
    assert "unresolved problem" not in h.prompts[0]


# ── unavailable is a sentence, never an exception ───────────────────────────────────────────────

def test_an_unavailable_module_answers_with_its_reason(tmp_path):
    mod, _ = _module(tmp_path, active=False, reason="`.openfactory/product.yaml` is missing")
    res = mod.answer("anything?")
    assert res.ok is False and "product.yaml" in res.error


def test_an_unavailable_module_refuses_to_draft_with_the_same_reason(tmp_path):
    mod, _ = _module(tmp_path, active=False, reason="the docs repo could not be checked out")
    assert mod.draft("x").ok is False


def test_health_reads_like_something_a_human_can_act_on(tmp_path):
    ready, _ = _module(tmp_path)
    assert "ready" in ready.health() and DOCS in ready.health()
    broken, _ = _module(tmp_path, active=False, reason="somebody renamed the folder")
    assert "unavailable" in broken.health() and "renamed" in broken.health()


# ── writing is gated ────────────────────────────────────────────────────────────────────────────

def test_an_unauthorised_user_cannot_record_a_requirement(tmp_path):
    mod, _ = _module(tmp_path, answer='{"title":"t","must_be_true":["x"]}')
    draft = mod.draft("let admins edit")
    res = mod.propose(draft, actor=OUTSIDER)
    assert res.ok is False
    assert "permissão de aprovação" in res.detail  # refused, in terms the asker can act on


def test_a_refused_write_says_so_out_loud_rather_than_doing_nothing(tmp_path):
    """A request that vanishes is indistinguishable from a broken bot, and the person tries
    again — and again."""
    mod, _ = _module(tmp_path, answer='{"title":"t","must_be_true":["x"]}')
    assert mod.propose(mod.draft("x"), actor=OUTSIDER).detail


def test_an_unreadable_draft_is_never_recorded_even_by_an_admin(tmp_path):
    """Authority does not repair a draft nobody could parse.

    The refusal is the ROLE's diagnosis — "the recording harness's draft could not be read
    (JSONDecodeError)" — and it used to be handed on as the client's sentence."""
    mod, _ = _module(tmp_path, answer="I think it's probably fine")
    res = mod.propose(mod.draft("x"), actor=ADMIN)
    assert res.ok is False and "não registrei nada" in res.detail
    assert "could not be read" not in res.detail and "harness" not in res.detail


def test_proposing_uses_the_draft_the_human_saw(tmp_path, monkeypatch):
    """Re-deriving a draft at write time would commit something nobody reviewed — the text in the
    conversation and the text in the pull request must be the same text."""
    import openfactory.product.module as module

    seen = {}
    monkeypatch.setattr(module, "propose_requirement",
                        lambda **kw: seen.update(kw) or module.WriteResult(ok=True, url="u"))
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda p, r="", *, token=None: "url")

    mod, _ = _module(tmp_path, answer='{"title":"Editable statements","must_be_true":["a"]}')
    draft = mod.draft("let admins edit", asked_by="Alice")
    res = mod.propose(draft, actor=ADMIN, asked_by="Alice", date="2026-07-26")

    assert res.ok
    assert seen["draft"] is draft.draft
    assert seen["number"] == 2                      # one past the highest in the corpus
    assert seen["requirements_dir"] == "requirements"
    assert seen["asked_by"] == "Alice"


def test_a_failure_while_writing_is_reported_not_raised(tmp_path, monkeypatch):
    import openfactory.product.module as module

    def _boom(**kw):
        raise RuntimeError("github is on fire")

    monkeypatch.setattr(module, "propose_requirement", _boom)
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda p, r="", *, token=None: "url")

    mod, _ = _module(tmp_path, answer='{"title":"t","must_be_true":["x"]}')
    res = mod.propose(mod.draft("x"), actor=ADMIN)
    assert res.ok is False and "o time foi avisado" in res.detail
    assert "on fire" not in res.detail, "the exception went into a business conversation"


# ── filing work into Backlog ────────────────────────────────────────────────────────────────────

class _Tracker:
    def __init__(self, existing=None, explode=False):
        self.created: list[tuple[str, str]] = []
        self.existing = existing or {}
        self.explode = explode

    def find_ticket(self, *, title):
        return self.existing.get(title)

    def create_ticket(self, *, title, body):
        if self.explode:
            raise RuntimeError("github said no")
        self.created.append((title, body))
        return f"#{500 + len(self.created)}"


class _Board:
    def __init__(self):
        self.columns: list[str] = []
        self.added: list[str] = []

    def add_item(self, *, issue_url):
        self.added.append(issue_url)

    def set_column(self, *, issue, issue_url, name):
        self.columns.append(name)
        return True


_TWO_ISSUES = ('{"issues": [{"title": "Add the review queue", "objective": "o", '
               '"acceptance_criteria": ["c"], "target_repo": "AcmeCorp/acme-books"}, '
               '{"title": "Badge the nav", "objective": "o", "acceptance_criteria": ["c"]}]}')


def _req():
    return Requirement(number=4, slug="x", path="requirements/0004-x.md", title="Review queue",
                       status="accepted")


def test_filing_lands_issues_in_BACKLOG_never_in_todo(tmp_path):
    """THE money gate. TO-DO is what the poller pulls, so the column is a literal here and not a
    parameter any caller could choose."""
    mod, _ = _module(tmp_path, answer=_TWO_ISSUES)
    tracker, board = _Tracker(), _Board()
    results = mod.file_issues(_req(), actor=ADMIN, tracker=tracker, board=board)

    assert [r.ok for r in results] == [True, True]
    assert board.columns == ["Backlog", "Backlog"]
    assert "TO-DO" not in board.columns


def test_every_filed_issue_cites_its_requirement(tmp_path):
    mod, _ = _module(tmp_path, answer=_TWO_ISSUES)
    tracker = _Tracker()
    mod.file_issues(_req(), actor=ADMIN, tracker=tracker, board=None)
    for _title, body in tracker.created:
        assert "REQ-0004" in body
        assert "requirements/0004-x.md" in body


def test_an_unauthorised_user_cannot_file_work(tmp_path):
    mod, _ = _module(tmp_path, answer=_TWO_ISSUES)
    tracker = _Tracker()
    results = mod.file_issues(_req(), actor=OUTSIDER, tracker=tracker, board=None)
    assert results[0].ok is False and tracker.created == []


def test_filing_twice_does_not_duplicate_the_work(tmp_path):
    """A retried conversation must not file the same issue again — an existing issue with this
    title is this operation's own prior result far more often than it is a coincidence."""
    mod, _ = _module(tmp_path, answer=_TWO_ISSUES)
    tracker = _Tracker(existing={"Add the review queue": "#501"})
    results = mod.file_issues(_req(), actor=ADMIN, tracker=tracker, board=None)

    assert results[0].existed is True and results[0].ref == "#501"
    assert [t for t, _ in tracker.created] == ["Badge the nav"]


def test_one_failing_issue_does_not_lose_the_others(tmp_path):
    """A partial failure is reported per item, so the caller can say exactly which ones landed."""
    mod, _ = _module(tmp_path, answer=_TWO_ISSUES)
    results = mod.file_issues(_req(), actor=ADMIN, tracker=_Tracker(explode=True), board=None)
    assert all(r.ok is False for r in results)
    assert all("as outras frentes seguiram" in r.detail for r in results)
    assert not any("github said no" in r.detail for r in results), \
        "the forge's exception was reported to the client as the reason"


def test_an_issue_that_could_not_be_placed_still_counts_as_filed(tmp_path):
    """The issue exists; where its card sits is cosmetic. Reporting failure would invite someone to
    file it a second time.

    A board that RAISED and a board that answered `False` leave the same card in the same state, so
    they say the same sentence — the raising half used to answer in English with the exception
    inside it."""
    class _BadBoard(_Board):
        def set_column(self, **kw):
            raise RuntimeError("board unreachable")

    mod, _ = _module(tmp_path, answer=_TWO_ISSUES)
    results = mod.file_issues(_req(), actor=ADMIN, tracker=_Tracker(), board=_BadBoard())
    assert results[0].ok is True and "sem coluna" in results[0].detail
    assert "board unreachable" not in results[0].detail


def test_an_unreadable_breakdown_files_nothing(tmp_path):
    mod, _ = _module(tmp_path, answer="I reckon two issues would do it")
    tracker = _Tracker()
    results = mod.file_issues(_req(), actor=ADMIN, tracker=tracker, board=None)
    assert results[0].ok is False and tracker.created == []
