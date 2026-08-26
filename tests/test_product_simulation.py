"""Nina, end to end: real repositories, the real wiring, scripted only at the model boundary.

Every other test in this suite checks a piece. This one drives the whole path a message actually
takes — Slack listener → channel router → module → loader → corpus → role → authoring — and asserts
what a person would SEE.

It exists because the recurring defect in this module has not been broken logic, it has been logic
that nothing reaches: the write path was unreachable from the channel, the sweep's diff was never
called, and the Knowledge refresh died on its first line for weeks while reporting success. Unit
tests passed throughout all three.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from openfactory import namespace
from openfactory.contracts import AgentRunResult
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.product import channel as pc
from openfactory.product.loader import load_product_context
from openfactory.product.module import ProductModule
from openfactory.product.role import REQUEST_MARKER
from openfactory.product.voice import jargon_in
from openfactory.runtime.repo_cache import RepoCache

DOCS = "AcmeCorp/acme-books-documentation"
SRC = "AcmeCorp/acme-books"
APPROVER, CLIENT = "U0APPROVER", "U0CLIENT"

REQ_7 = """# REQ-0007 — Um extrato conciliado não muda

- **Status:** accepted
- **Asked by:** Alice
- **Date:** 2026-07-01

## Why

Auditoria exige que o que foi conciliado seja imutável.

## What must be true

- [ ] um extrato conciliado rejeita qualquer edição

## Decisions taken during execution

| date | decision | where it came from |
|---|---|---|
| 2026-07-02 | vale também para admin | #310 |
"""


def _git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def docs_repo(tmp_path):
    """A documentation repo laid out exactly as a client's is."""
    repo = tmp_path / "docs"
    (repo / namespace.DIR).mkdir(parents=True)
    (repo / "requirements").mkdir()
    (repo / namespace.PRODUCT_MANIFEST).write_text(
        f"product: books\nsources:\n  - {SRC}\nrequirements_dir: requirements\n")
    (repo / "requirements" / "0007-conciliado-imutavel.md").write_text(REQ_7)
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.email", "t@t", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "seed", cwd=repo)
    return repo


@pytest.fixture
def project():
    return Project(
        name="books", repo_path="/work/books",
        tracker={"kind": "github", "repo": SRC},
        # pt-BR DECLARED: this simulation asserts the platform's Portuguese sentences, so the
        # project names its language rather than inheriting a default (2026-08-14).
        language="pt-BR",
        product=ProductConfig(docs_repo=DOCS, channel_id="C0PROD",
                              admins=[APPROVER], agent_name="Nina"),
    )


class _Nina:
    """The model, scripted. Answers are keyed by phase so one fake serves the whole conversation."""

    name = "claude_code"

    def __init__(self, script: dict[str, str]) -> None:
        self.script, self.prompts = script, []

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.prompts.append((phase, prompt))
        return AgentRunResult(ok=True, summary=self.script.get(phase, ""))


@pytest.fixture
def nina(project, docs_repo, tmp_path, monkeypatch):
    """A module wired to the real loader, real corpus, real workspace — model scripted."""
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda project, repo="", *, token=None: str(docs_repo))
    cache = RepoCache(root=tmp_path / "cache")

    def _build(script: dict[str, str]):
        ctx = load_product_context(project, cache=cache, source_claim=DOCS)
        assert ctx.available, ctx.reason
        return ProductModule(project, context=ctx, agent=_Nina(script))

    return _build


@pytest.fixture(autouse=True)
def _clean_threads():
    pc._PENDING.clear()
    yield
    pc._PENDING.clear()


# ── the corpus is really loaded ─────────────────────────────────────────────────────────────────

def test_she_can_see_the_requirements_that_exist(nina):
    mod = nina({})
    corpus = mod.context().corpus
    assert [r.number for r in corpus.requirements] == [7]
    assert corpus.by_number(7).is_promise is True
    assert corpus.errors == []


def test_the_requirement_INDEX_reaches_the_model_but_not_its_whole_text(nina, project):
    mod = nina({"product_answer": "Não muda, requisito 7."})
    pc.handle(project, text="posso editar um conciliado?", user=CLIENT, thread="t", module=mod)
    phase, prompt = mod._agent.prompts[0]
    assert phase == "product_answer"
    assert "REQ-0007" in prompt                       # the index locates it
    assert "0007-conciliado-imutavel.md" in prompt    # …and says where to open it
    assert "Auditoria exige" not in prompt            # the body is NOT inlined


# ── a question ──────────────────────────────────────────────────────────────────────────────────

def test_a_question_is_answered_and_nothing_is_staged(nina, project):
    mod = nina({"product_answer": "Não. O requisito 7 diz que conciliado não muda."})
    reply = pc.handle(project, text="dá pra editar um extrato já conciliado?",
                      user=CLIENT, thread="t1", module=mod)
    assert "requisito 7" in reply
    assert jargon_in(reply) == []
    assert pc.pending_for("t1") is None


# ── a request, with the conflict it creates ─────────────────────────────────────────────────────

_DRAFT_WITH_CONFLICT = json.dumps({
    "title": "Administrador corrige extrato conciliado",
    "why": "contadores precisam corrigir um erro de digitação depois de conciliar",
    "must_be_true": ["um administrador pode corrigir um extrato conciliado",
                     "toda correção fica registrada com autor e data"],
    "conflicts": [{"requirement": 7, "kind": "contradicts",
                   "explanation": "o requisito 7 diz que conciliado não muda"}],
})


def test_a_request_becomes_a_draft_and_the_CONFLICT_comes_first(nina, project):
    """The single most valuable thing this role produces: "that reverses something you decided"."""
    mod = nina({"product_answer": f"Hoje não dá.\n{REQUEST_MARKER}",
                "product_draft": _DRAFT_WITH_CONFLICT})
    reply = pc.handle(project, text="preciso que um admin consiga corrigir um conciliado",
                      user=CLIENT, thread="t1", module=mod)

    assert "requisito 7" in reply
    assert reply.index("requisito 7") < reply.index("Entendi certo")
    assert "mudança de ideia" in reply
    assert jargon_in(reply) == []
    assert pc.pending_for("t1") is not None


def test_the_asker_is_carried_into_the_draft_as_provenance(nina, project):
    mod = nina({"product_answer": f"ok\n{REQUEST_MARKER}", "product_draft": _DRAFT_WITH_CONFLICT})
    pc.handle(project, text="preciso de X", user=CLIENT, thread="t1", module=mod)
    draft_prompt = next(p for phase, p in mod._agent.prompts if phase == "product_draft")
    assert CLIENT in draft_prompt


# ── confirming ──────────────────────────────────────────────────────────────────────────────────

def _staged(nina_factory, project, thread="t1"):
    mod = nina_factory({"product_answer": f"ok\n{REQUEST_MARKER}",
                        "product_draft": _DRAFT_WITH_CONFLICT})
    pc.handle(project, text="preciso que admin corrija conciliado", user=CLIENT,
              thread=thread, module=mod)
    return mod


def test_an_outsider_cannot_confirm_and_the_draft_SURVIVES(nina, project):
    mod = _staged(nina, project)
    reply = pc.handle(project, text="sim", user=CLIENT, thread="t1", module=mod)
    assert "aprova" in reply.lower()
    assert pc.pending_for("t1") is not None


@pytest.mark.parametrize("qualified", [
    "ok mas e se o extrato for de outro mês?",
    "sim, porém só para o dono da conta",
    "certo — e quem audita isso?",
])
def test_a_QUALIFIED_reply_is_treated_as_conversation_not_consent(nina, project, qualified):
    mod = _staged(nina, project)
    mod._agent.script["product_answer"] = "Boa pergunta."
    pc.handle(project, text=qualified, user=APPROVER, thread="t1", module=mod)
    assert pc.pending_for("t1") is not None       # still waiting: nobody confirmed anything


def test_an_approver_records_it_and_hears_it_in_their_own_terms(nina, project, monkeypatch):
    import openfactory.product.module as module

    # staged FIRST: the loader uses the same `clone_url`, so patching it before the context is
    # built would break the checkout this test depends on
    mod = _staged(nina, project)

    seen = {}
    monkeypatch.setattr(module, "propose_requirement",
                        lambda **kw: seen.update(kw) or module.WriteResult(
                            ok=True, url="https://github.com/x/pull/9"))
    reply = pc.handle(project, text="sim", user=APPROVER, thread="t1", module=mod)

    assert seen["number"] == 8                     # one past REQ-0007, never reusing a number
    assert seen["requirements_dir"] == "requirements"
    assert seen["draft"].title.startswith("Administrador")
    assert CLIENT in seen["asked_by"]              # the person who WANTED it, not who approved

    assert "requisito 8" in reply
    assert "https://github.com/x/pull/9" not in reply, "a code-forge link reached the client"
    assert "http" not in reply, "a link of any kind reached the client (ADR-0032)"
    assert "Nada está sendo construído ainda" in reply
    assert jargon_in(reply) == []
    assert pc.pending_for("t1") is None


# ── the module speaks for itself when it cannot work ────────────────────────────────────────────

def test_a_broken_documentation_repo_admits_it_would_be_guessing(project, tmp_path, monkeypatch):
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda p, r="", *, token=None: str(tmp_path / "does-not-exist"))
    ctx = load_product_context(project, cache=RepoCache(root=tmp_path / "c"), source_claim=DOCS)
    mod = ProductModule(project, context=ctx, agent=_Nina({}))

    reply = pc.handle(project, text="o que a gente prometeu?", user=CLIENT, thread="t", module=mod)
    assert "chute" in reply
    assert "clone" not in reply.lower() and "repo" not in reply.lower()


def test_she_introduces_herself_by_name(nina, project):
    reply = pc.handle(project, text="Nina, se apresenta", user=CLIENT, thread="t", module=nina({}))
    assert "meu nome é Nina" in reply
    assert jargon_in(reply) == []


# ── the capabilities that were reachable only from tests ────────────────────────────────────────

def test_every_capability_is_reachable_from_a_REAL_entry_point():
    """The recurring defect in this module, four times over: something built, tested, and reached
    by nothing. The write path, the sweep's diff, the Knowledge refresh, and then three more found
    by auditing — filing work, the brownfield pass, and the Needs Action classification.

    Unit tests cannot catch this by construction: they ARE the caller that makes it look used."""
    from pathlib import Path

    channel = Path("openfactory/product/channel.py").read_text()
    module = Path("openfactory/product/module.py").read_text()
    activities = Path("openfactory/runtime/temporal/activities.py").read_text()

    reachable = channel + module + activities
    for capability in ("file_issues", "review_needs_action", "break_down",
                       "triage_board", "introduce", "classify_prompt", "report.since("):
        assert capability in reachable, f"{capability} is reached only from tests"


def test_asking_to_break_down_a_requirement_files_the_work(nina, project, monkeypatch):
    class _Tracker:
        def __init__(self):
            self.created = []

        def find_ticket(self, *, title):
            return None

        def create_ticket(self, *, title, body):
            self.created.append((title, body))
            return f"#{600 + len(self.created)}"

    tracker = _Tracker()
    mod = nina({"product_issues": json.dumps({"issues": [
        {"title": "Tela de correção", "objective": "o", "acceptance_criteria": ["c"],
         "target_repo": SRC}]})})
    monkeypatch.setattr(mod, "_tracker", lambda: tracker)

    results = mod.break_down(7, actor=APPROVER)
    assert [r.ok for r in results] == [True]
    assert tracker.created and "REQ-0007" in tracker.created[0][1]


@pytest.mark.parametrize(("status", "must_say"), [
    # THE REFUSAL IS ONE RULE WITH THREE ANSWERS, because the person's next move differs. A
    # proposal needs confirming; a reading of the code must not be agreed to casually, since doing
    # so freezes today's behaviour — bugs included — into a promise; a retired text needs somebody
    # to say which one replaced it. Asserting one shared phrase used to hide that, and a single
    # sentence for all three left the reader with nothing to do.
    ("proposed", "confirm"),
    ("observed", "j[áa] faz hoje"),
    ("superseded", "j[áa] n[ãa]o vale"),
])
def test_work_is_never_filed_from_a_requirement_nobody_agreed_to(nina, status, must_say):
    """A proposal, or a reading of the code, is not something to build. Filing work from one would
    commit the factory to a decision nobody has made."""
    import re as _re

    mod = nina({})
    mod.context().corpus.requirements[0].status = status

    results = mod.break_down(7, actor=APPROVER)

    assert results[0].ok is False, f"work was filed from a {status!r} requirement"
    assert _re.search(must_say, results[0].detail, _re.IGNORECASE), results[0].detail
    # and never the raw English status, which is what the first version of this message leaked
    assert status not in results[0].detail, results[0].detail


def test_breaking_down_a_requirement_that_does_not_exist_says_so(nina):
    results = nina({}).break_down(99, actor=APPROVER)
    assert results[0].ok is False and "99" in results[0].detail


def test_the_module_finds_a_credential_on_its_own(monkeypatch, project):
    """A documentation repo is PRIVATE. Both real entry points construct this with no token, so an
    unauthenticated clone would fail and the role would answer "I can't see the requirements" to
    every message — while every test passed, because tests hand it a checkout directly."""
    import openfactory.credentials as bot

    monkeypatch.setattr(bot, "forge_token", lambda: "ghs_from_the_env")
    assert ProductModule(project).token == "ghs_from_the_env"


def test_an_explicit_token_still_wins(project):
    assert ProductModule(project, token="explicit").token == "explicit"


def test_no_credential_anywhere_is_None_not_an_empty_string(monkeypatch, project):
    """`clone_url(repo, "")` and `clone_url(repo, None)` must not differ by accident."""
    import openfactory.credentials as bot
    import openfactory.factory as factory

    monkeypatch.setattr(bot, "forge_token", lambda: "")
    monkeypatch.setattr(factory, "github_app_token_from_env", lambda: "")
    assert ProductModule(project).token is None


# ── the situations a product owner actually handles ─────────────────────────────────────────────

def _ask(nina_factory, project, text, *, thread="t", answer, draft=None, user=CLIENT):
    script = {"product_answer": answer}
    if draft:
        script["product_draft"] = draft
    mod = nina_factory(script)
    return mod, pc.handle(project, text=text, user=user, thread=thread, module=mod)


def test_scenario_asking_for_something_that_ALREADY_EXISTS(nina, project):
    """The cheapest thing a product owner saves: work nobody needed to do twice."""
    draft = json.dumps({
        "title": "Impedir edição de conciliado",
        "must_be_true": ["um extrato conciliado rejeita edição"],
        "conflicts": [{"requirement": 7, "kind": "duplicates",
                       "explanation": "o requisito 7 já garante exatamente isso"}]})
    _, reply = _ask(nina, project, "quero que conciliado não possa ser editado",
                    answer=f"Isso já está garantido.\n{REQUEST_MARKER}", draft=draft)
    assert "requisito 7" in reply
    assert reply.index("requisito 7") < reply.index("Entendi certo")
    assert jargon_in(reply) == []


def test_scenario_asking_for_something_that_REVERSES_a_decision(nina, project):
    """The push-back that pays for the role: not "no", but "that reverses REQ-7 — did you mean
    to?" — said before anything is written down."""
    draft = json.dumps({
        "title": "Administrador corrige conciliado",
        "must_be_true": ["um administrador pode corrigir"],
        "conflicts": [{"requirement": 7, "kind": "contradicts",
                       "explanation": "o requisito 7 diz que conciliado não muda, inclusive "
                                      "para admin"}]})
    _, reply = _ask(nina, project, "admin tem que poder corrigir conciliado",
                    answer=f"Hoje não dá.\n{REQUEST_MARKER}", draft=draft)
    assert "mudança de ideia" in reply
    assert "não muda" in reply


def test_scenario_asking_for_something_with_IMPACT_elsewhere(nina, project):
    """Not a contradiction — a consequence. Saying it up front is the difference between a decision
    and a surprise."""
    draft = json.dumps({
        "title": "Reabrir período contábil",
        "must_be_true": ["um período fechado pode ser reaberto por um administrador"],
        "conflicts": [{"requirement": 7, "kind": "depends_on",
                       "explanation": "reabrir um período mexe no que o requisito 7 protege — "
                                      "os extratos conciliados dentro dele"}]})
    _, reply = _ask(nina, project, "precisamos poder reabrir um período fechado",
                    answer=f"Dá pra fazer, mas tem consequência.\n{REQUEST_MARKER}", draft=draft)
    assert "requisito 7" in reply and "mexe no que" in reply


def test_scenario_a_VAGUE_request_is_refused_while_the_person_is_still_there(nina, project):
    """"melhora os relatórios" states nothing testable. Refusing it now costs a sentence; letting it
    through costs a job that parks hours later with nobody able to say whether it is done."""
    mod, reply = _ask(nina, project, "melhora os relatórios",
                      answer=f"Preciso entender melhor.\n{REQUEST_MARKER}",
                      draft=json.dumps({"title": "Melhorar relatórios", "must_be_true": []}))
    assert "Preciso entender melhor" in reply
    assert pc.pending_for("t") is None       # nothing was staged for approval


def test_scenario_an_IDLE_factory_with_a_full_backlog_is_the_headline(nina, project, monkeypatch):
    """The finding that costs something every hour it stays true — and the one this role exists to
    catch. A tidy backlog beside an idle floor is a week of capacity nobody spent."""
    from openfactory.product.queue import Proposed, QueueProposal, Readiness
    from openfactory.product.voice import queue_proposal

    state = Readiness(in_progress=0, todo=[], ready=[505, 478], needs_refinement=[141])
    assert state.wasting_capacity is True

    text = queue_proposal(
        state,
        QueueProposal(items=[Proposed(ticket=505, why="fecha a régua de propostas"),
                             Proposed(ticket=478, why="desbloqueia o relatório pedido")]),
        titles={505: "Ativar regras", 478: "Exportar conciliação"}, agent_name="Nina",
        language="pt-BR")

    assert "capacidade indo embora" in text
    assert text.index("#505") < text.index("#478")     # the ORDER is the proposal
    assert "Aprovo?" in text
    assert jargon_in(text) == []


def test_scenario_idle_but_NOTHING_is_ready_says_whose_job_that_is(nina):
    """The honest answer is not "pick something" — it is "these need criteria first", which is the
    product role's own work rather than a request for someone else's."""
    from openfactory.product.queue import QueueProposal, Readiness
    from openfactory.product.voice import queue_proposal

    state = Readiness(in_progress=0, todo=[], ready=[], needs_refinement=[141, 138, 137])
    assert state.blocked_by_refinement is True
    text = queue_proposal(state, QueueProposal(), agent_name="Nina", language="pt-BR")
    assert "nenhum deles diz quando estaria pronto" in text
    assert "Isso é comigo" in text


def test_the_proposal_can_never_name_a_ticket_that_cannot_START(nina, project, monkeypatch):
    """A model naming something parked, unrefined or imaginary would have a person approving work
    that cannot begin — and the approval is the money."""
    from openfactory.product.triage import Ticket

    mod = nina({"product_queue": json.dumps({"items": [
        {"ticket": 505, "why": "ok"},          # a real candidate
        {"ticket": 141, "why": "não refinado"},  # backlog, no criteria
        {"ticket": 9999, "why": "inventado"}]})})
    monkeypatch.setattr(
        "openfactory.product.board.read_board",
        lambda project, **kw: ([
            Ticket(number=505, title="pronto", column="Backlog", body="- [ ] x"),
            Ticket(number=141, title="vago", column="Backlog", body="sem criterio"),
        ], ""))

    state, proposal, error = mod.propose_queue()
    assert error == ""
    assert [i.ticket for i in proposal.items] == ["505"]


# ── arriving, refining, and remembering ─────────────────────────────────────────────────────────

def test_she_arrives_saying_where_things_STAND_not_just_hello(nina, project, monkeypatch):
    """An agent that says hello and nothing else has to be asked a question before it is worth
    anything — and the first thing anybody wants to know is whether the factory is doing something."""
    from openfactory.product.triage import Ticket

    monkeypatch.setattr("openfactory.product.board.read_board", lambda project, **kw: ([
        Ticket(number=1, column="Backlog", body="- [ ] pronto"),
        Ticket(number=2, column="Backlog", body="vago"),
    ], ""))
    text = nina({}).introduce()
    assert "meu nome é Nina" in text
    assert "capacidade indo embora" in text        # the fact that costs money leads
    assert "#2" in text                            # …and the ticket it names is one you can open
    assert "O que eu faria primeiro" in text       # …and it ends somewhere actionable
    assert jargon_in(text) == []


def test_arriving_still_works_when_the_board_does_not(nina, project, monkeypatch):
    monkeypatch.setattr("openfactory.product.board.read_board",
                        lambda project, **kw: ([], "o quadro não respondeu"))
    text = nina({}).introduce()
    assert "meu nome é Nina" in text
    assert "Como está agora" not in text


def test_refining_APPENDS_and_never_rewrites_what_somebody_wrote(nina, project, monkeypatch):
    """An agent that silently replaces a description teaches people to distrust everything it
    touches."""
    from openfactory.product.triage import Ticket

    class _Tracker:
        def __init__(self):
            self.body = None
            self.comments = []

        def update_body(self, ref, body):
            self.body = body

        def comment(self, ref, body):
            self.comments.append(body)

    monkeypatch.setattr("openfactory.product.board.read_board", lambda project, **kw: ([
        Ticket(number=141, title="Exportar", body="O contador precisa exportar.", column="Backlog"),
    ], ""))
    tracker = _Tracker()
    mod = nina({"product_refine": json.dumps({
        "criteria": ["o arquivo sai em CSV", "inclui o período escolhido"],
        "questions": ["inclui lançamentos cancelados?"]})})

    res = mod.refine(141, actor=APPROVER, tracker=tracker)
    assert res.ok
    assert "O contador precisa exportar." in tracker.body      # the original survives
    assert "- [ ] o arquivo sai em CSV" in tracker.body
    assert "inclui lançamentos cancelados?" in tracker.body    # what it could not determine
    assert tracker.comments and "corrijam se eu entendi errado" in tracker.comments[0]


def test_a_ticket_that_is_already_clear_is_LEFT_ALONE(nina, project, monkeypatch):
    """Improving prose nobody complained about is how an agent churns a board and teaches people to
    stop reading its comments."""
    from openfactory.product.triage import Ticket

    monkeypatch.setattr("openfactory.product.board.read_board", lambda project, **kw: ([
        Ticket(number=9, title="ok", body="## Critérios\n- [ ] já está claro", column="Backlog"),
    ], ""))
    res = nina({}).refine(9, actor=APPROVER, tracker=object())
    assert res.ok and res.existed and "não mexi" in res.detail


def test_refining_is_gated_like_every_other_write(nina, project, monkeypatch):
    from openfactory.product.triage import Ticket

    monkeypatch.setattr("openfactory.product.board.read_board", lambda project, **kw: ([
        Ticket(number=141, body="vago", column="Backlog")], ""))
    res = nina({}).refine(141, actor=CLIENT, tracker=object())
    assert res.ok is False and "aprova" in res.detail.lower()


def test_a_trend_needs_two_looks_and_says_so_only_then():
    """A count says how bad things are; the same count beside last week's says whether anybody is
    winning."""
    from openfactory.product.queue import Readiness
    from openfactory.product.voice import situation

    state = Readiness(in_progress=0, todo=[], ready=[1, 2], needs_refinement=[3])
    assert "Desde a última vez" not in situation(state, requirements=1, language="pt-BR")
    assert "cresceu **1**" in situation(state, requirements=1, previous_backlog=2,
                                        language="pt-BR")
