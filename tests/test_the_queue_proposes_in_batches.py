"""What only means something delivered together is proposed together, and never cut in half.

The product owner, 2026-07-31: *"she has to be able to organise logical batches of tasks"*. The
queue was
an ordered list with a reason per item, truncated at five, and no way to say *"these three only
make sense delivered together"*.

WHY IT IS NOT COSMETIC. Half a change in staging is precisely the thing a client CANNOT test — and
their test is what becomes the production approval. So a queue able to split a deliverable does not
merely look untidy: it produces a staging environment nobody can sign off, which is the one place
this whole surface is trying to reach.

THE DEFECT WAS THE LIMIT, NOT THE MISSING LABEL. `items[:limit]` ran after the ordering, so a group
straddling position five was silently cut: two of its three tickets queued, the third left in the
backlog, and nothing anywhere said so.
"""

from __future__ import annotations

import pytest

from openfactory.product.queue import Proposed, QueueProposal, proposal_prompt, whole_batches
from openfactory.product.triage import Ticket
from openfactory.product.voice import queue_proposal


def _p(ticket: int, batch: str = "", why: str = "porque sim") -> Proposed:
    return Proposed(ticket=ticket, why=why, batch=batch)


#: THE REAL OBJECT, not a stub. A hand-written double that carried only the three fields the reply
#: happened to read is how the opening line came to assert "nothing queued" while `todo` held two
#: cards: nothing in any test could see the field it was lying about.
def _Readiness(**kw):                                        # noqa: N802 — reads as a constructor
    from openfactory.product.queue import Readiness

    return Readiness(**{"ready": [1], **kw})


# ── 1. the cut ─────────────────────────────────────────────────────────────────────────────────

def test_a_batch_straddling_the_limit_is_not_cut_in_half():
    """The exact failure: two of three queued, the third left behind, staging carrying a change
    nobody can exercise."""
    items = [_p(1), _p(2), _p(3),
             _p(4, "emitir e cancelar uma nota"),
             _p(5, "emitir e cancelar uma nota"),
             _p(6, "emitir e cancelar uma nota")]

    kept, cut = whole_batches(items, limit=5)

    assert [i.ticket for i in kept] == ["1", "2", "3"], [i.ticket for i in kept]
    assert [i.ticket for i in cut] == ["4", "5", "6"], (
        "the batch was split, so staging would hold two thirds of one deliverable")


def test_a_batch_that_FITS_is_taken_whole():
    items = [_p(1), _p(2, "trocar a senha"), _p(3, "trocar a senha")]

    kept, cut = whole_batches(items, limit=5)

    assert [i.ticket for i in kept] == ["1", "2", "3"]
    assert cut == []


def test_a_batch_BIGGER_than_the_limit_still_goes_out_when_it_comes_first():
    """The alternative is proposing nothing while the floor sits idle. The limit is a courtesy
    about message length; the batch is a statement about testability, and testability wins — but
    the caller says so rather than stretching in silence."""
    items = [_p(n, "o fechamento mensal inteiro") for n in range(1, 8)]

    kept, cut = whole_batches(items, limit=5)

    assert len(kept) == 7 and cut == [], "it proposed nothing while there was ready work"


def test_two_UNGROUPED_items_never_merge_into_one_unit():
    """An item that delivers on its own is exactly what the limit was written for. Keying the
    groups by the empty label would have fused every ungrouped item into one indivisible blob —
    the limit would then admit all of them or none."""
    items = [_p(n) for n in range(1, 9)]

    kept, cut = whole_batches(items, limit=5)

    assert len(kept) == 5 and len(cut) == 3


def test_the_order_survives_the_grouping():
    """The poller pulls in board order, so a sequence that comes back shuffled is not the sequence
    anybody approved."""
    items = [_p(9), _p(3, "b"), _p(7), _p(4, "b"), _p(1)]

    kept, _ = whole_batches(items, limit=10)

    assert [i.ticket for i in kept] == ["9", "3", "4", "7", "1"], (
        "the batch's members were gathered but the run order was rewritten")


# ── 2. the client can SEE the batch ────────────────────────────────────────────────────────────

def test_the_reply_says_what_the_client_will_be_able_to_TRY():
    """Grouping in the model and printing one flat list would leave the client approving a
    sequence with no way to see that three of its items are one deliverable — the care real in the
    JSON and absent everywhere a person looks."""
    proposal = QueueProposal(items=[
        _p(287, why="tira o segredo exposto do ar"),
        _p(510, "emitir e cancelar uma nota", why="emite"),
        _p(515, "emitir e cancelar uma nota", why="cancela"),
    ])

    said = queue_proposal(_Readiness(), proposal,
                          titles={287: "Segredo vazado", 510: "Emitir", 515: "Cancelar"},
                          language="pt-BR")

    assert "emitir e cancelar uma nota" in said, said
    assert "testar" in said.lower(), f"the group is shown but not what it buys them: {said}"
    assert said.index("#287") < said.index("emitir e cancelar"), (
        "the batch header landed above an item that is not in it")


def test_items_that_stand_ALONE_after_a_batch_are_not_swallowed_by_it():
    proposal = QueueProposal(items=[
        _p(510, "emitir e cancelar uma nota"),
        _p(515, "emitir e cancelar uma nota"),
        _p(287),
    ])

    said = queue_proposal(_Readiness(), proposal, language="pt-BR")

    assert "Independentes" in said, (
        f"#287 reads as part of the batch above it, which it is not: {said}")
    assert said.index("Independentes") < said.index("#287"), said


def test_a_proposal_with_NO_batches_reads_exactly_as_it_did():
    """The feature is an addition. A queue of independent items must not grow ceremony it does not
    need — most queues are exactly that."""
    proposal = QueueProposal(items=[_p(1), _p(2)])

    said = queue_proposal(_Readiness(), proposal, language="pt-BR")

    assert "Juntos" not in said and "Independentes" not in said, said
    assert "#1" in said and "#2" in said


# ── 3. what the role is asked, and what the cut says out loud ──────────────────────────────────

def test_the_role_is_asked_the_question_that_DEFINES_a_batch():
    prompt = proposal_prompt(
        readiness=_Readiness(),
        candidates=[Ticket(number=1, title="x"), Ticket(number=2, title="y")],
        limit=5)

    assert "batch" in prompt, "the answer shape can group but the task never asks for it"
    assert "half" in prompt.lower(), (
        "the test that decides a batch — could the client try half of it? — is not stated")
    assert "sign off" in prompt.lower() or "sign-off" in prompt.lower(), (
        "nothing connects grouping to why it matters, so it becomes a tidiness exercise")


# ── 4. reachability: production applies it, and says what it left ─────────────────────────────

def _module(tmp_path, answer: str):
    """A real `ProductModule` with fakes only at its own seams — the board and the harness."""
    from openfactory.contracts import AgentRunResult
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project
    from openfactory.product.config import ProductLink
    from openfactory.product.corpus import Corpus
    from openfactory.product.loader import ProductContext
    from openfactory.product.module import ProductModule

    class _Harness:
        name = "recording"

        def __init__(self):
            self.prompts: list[str] = []

        def ask(self, *, sandbox, workspace, prompt, phase="ask"):
            self.prompts.append(prompt)
            return AgentRunResult(ok=True, summary=answer)

    ctx = ProductContext(
        link=ProductLink(active=True, docs_repo="a/docs", kind="ok", reason="fine"),
        corpus=Corpus(requirements=[]), docs_path=str(tmp_path), docs_commit="abc",
        requirements_dir="requirements")
    project = Project(name="books", repo_path="/w",
                      product=ProductConfig(docs_repo="a/docs", admins=["U0ADMIN"]))
    mod = ProductModule(project, context=ctx, agent=_Harness())
    # `- [ ]` is what makes a Backlog card READY rather than needing refinement — without it
    # `readiness` files all six under `needs_refinement`, there are no candidates, and the method
    # returns an empty proposal for a reason that has nothing to do with batches.
    mod._read_board = lambda **_: (      # noqa: SLF001
        [Ticket(number=n, title=f"t{n}", state="open", column="Backlog",
                body="- [ ] algo verificável")
         for n in (1, 2, 3, 4, 5, 6)], "")
    return mod


_STRADDLES = (
    '{"items": ['
    '{"ticket": 1, "why": "a"}, {"ticket": 2, "why": "b"}, {"ticket": 3, "why": "c"},'
    '{"ticket": 4, "why": "d", "batch": "emitir e cancelar uma nota"},'
    '{"ticket": 5, "why": "e", "batch": "emitir e cancelar uma nota"},'
    '{"ticket": 6, "why": "f", "batch": "emitir e cancelar uma nota"}],'
    ' "held_back": [], "note": ""}')


def test_propose_queue_ITSELF_cuts_at_the_batch_boundary(tmp_path):
    """The guard that matters. `whole_batches` could be perfect and unreachable: `[:limit]` is one
    line in the production method, and every test above would still pass with it in place. This
    repository has shipped "built, tested, reached by nothing" fourteen times."""
    mod = _module(tmp_path, _STRADDLES)

    _state, proposal, error = mod.propose_queue(limit=5)

    assert not error, error
    assert [i.ticket for i in proposal.items] == ["1", "2", "3"], (
        f"production still splits the batch: {[i.ticket for i in proposal.items]}")


def test_what_was_left_out_is_NAMED_in_the_proposal(tmp_path):
    """No silent caps. "What happened to the rest?" is the first question a proposed queue gets,
    and an omission with no sentence reads as an oversight rather than a decision."""
    mod = _module(tmp_path, _STRADDLES)

    _state, proposal, _ = mod.propose_queue(limit=5)

    assert "#4" in proposal.note and "#6" in proposal.note, (
        f"three tickets vanished from the proposal with nothing said: {proposal.note!r}")


def test_a_ticket_that_is_not_a_CANDIDATE_is_still_refused(tmp_path):
    """The older guard, re-asserted because the batch cut now runs beside it: a model naming a
    parked or imaginary ticket would have a person approving work that cannot start."""
    mod = _module(tmp_path,
                  '{"items": [{"ticket": 1, "why": "a"}, {"ticket": 999, "why": "inventado"}],'
                  ' "held_back": [], "note": ""}')

    _state, proposal, _ = mod.propose_queue(limit=5)

    assert [i.ticket for i in proposal.items] == ["1"], proposal.items


@pytest.mark.parametrize("limit", [1, 3, 5])
def test_nothing_is_ever_dropped_without_being_counted(limit):
    """No silent caps: everything that goes in comes out in one of the two lists."""
    items = [_p(1), _p(2, "a"), _p(3, "a"), _p(4), _p(5, "b"), _p(6, "b"), _p(7)]

    kept, cut = whole_batches(items, limit=limit)

    assert sorted(i.ticket for i in kept + cut) == ["1", "2", "3", "4", "5", "6", "7"]
    assert not ({i.ticket for i in kept} & {i.ticket for i in cut}), "a ticket is in both lists"


# ── 5. the prompt states FACTS, not a boolean collapsed into prose ─────────────────────────────

def test_the_opening_line_never_lies_about_what_is_QUEUED():
    """The line read "The factory has nothing queued and {nothing|work} in flight" — with "nothing
    queued" HARD-CODED and the single variable choosing the word for the OTHER fact. With TO-DO
    holding two cards and nothing running it said "nothing queued and work in flight", and BOTH
    clauses were false: the role ordered a queue while reading that the queue did not exist, and
    proposed as "next to start" a card the poller was about to pull.

    `readiness.idle` collapses two independent facts into one boolean. It is a predicate for
    deciding WHETHER to propose — never a sentence."""
    from openfactory.product.queue import Readiness

    prompt = proposal_prompt(readiness=Readiness(todo=[31, 32], ready=[40], in_progress=0),
                             candidates=[Ticket(number=40, title="x")], limit=5,
                             titles={31: "Nota", 32: "Fecho"})
    head = prompt.splitlines()[0]

    assert "nothing queued" not in head, head
    assert "#31" in head and "#32" in head, f"the queue it is ordering is invisible to it: {head}"


def test_the_opening_line_never_lies_about_what_is_RUNNING():
    from openfactory.product.queue import Readiness

    idle = proposal_prompt(readiness=Readiness(todo=[], ready=[40], in_progress=0),
                           candidates=[Ticket(number=40, title="x")], limit=5).splitlines()[0]
    busy = proposal_prompt(readiness=Readiness(todo=[], ready=[40], in_progress=2),
                           candidates=[Ticket(number=40, title="x")], limit=5).splitlines()[0]

    assert "nada" in idle and "2" not in idle, idle
    assert "2" in busy, busy


def test_candidates_CUT_by_the_caller_are_declared():
    """`role._board_section` learned this the expensive way — "a cut that does not explain itself
    makes an agent misdiagnose its own blindness" — and the lesson had not reached here. The caller
    sliced at 40 and this rendered the slice under a heading that reads as the whole, so twenty
    ready tickets could never be proposed while the reply called the list complete."""
    from openfactory.product.queue import Readiness

    prompt = proposal_prompt(readiness=Readiness(ready=[1]),
                             candidates=[Ticket(number=1, title="x")], limit=5,
                             total_candidates=60)

    assert "+59" in prompt, prompt
    assert "NÃO por falta de acesso" in prompt


def test_a_judgement_is_never_ASKED_over_bare_numbers():
    """The prompt asks whether a non-candidate looks MORE VALUABLE than what was proposed. Over a
    list of integers that is unanswerable — and the role has said so itself: "tenho só os
    identificadores dos itens, não o texto de cada um"."""
    from openfactory.product.queue import Readiness

    prompt = proposal_prompt(readiness=Readiness(ready=[1], needs_refinement=[47]),
                             candidates=[Ticket(number=1, title="x")], limit=5,
                             titles={47: "Conciliação automática"})

    assert "Conciliação automática" in prompt, "it asks for a judgement it gave no material for"


def test_what_a_PERSON_is_holding_is_shown_rather_than_silently_dropped():
    """`readiness()` reads labels and bodies to decide these are somebody's — the expensive part —
    and the prompt never mentioned them. For the role they did not exist, so "não achei mais nada
    aproveitável no backlog" was a claim of completeness she had no way to make."""
    from openfactory.product.queue import Readiness

    prompt = proposal_prompt(readiness=Readiness(ready=[1], parked=[12, 19]),
                             candidates=[Ticket(number=1, title="x")], limit=5,
                             titles={12: "Spike TOConline", 19: "Epic conciliação"})

    assert "#12" in prompt and "#19" in prompt
    assert "NOT non-existent" in prompt, "they are shown but not distinguished from absent"


def test_the_CALLER_passes_what_the_renderer_needs_to_be_honest():
    """Reachability. `total_candidates` and `titles` could be perfect and never supplied — and the
    prompt would go quiet again with every test above still green, because they call the renderer
    directly."""
    import inspect

    from openfactory.product.module import ProductModule

    src = inspect.getsource(ProductModule.propose_queue)
    assert "total_candidates=" in src, "the cut is invisible to the renderer again"
    assert "titles=" in src, "the judgement is asked over bare numbers again"
