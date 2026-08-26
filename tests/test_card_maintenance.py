"""The cards themselves: closing one, aligning one, and repairing the ones a supersession orphaned.

THE LIVE STATE THESE EXIST TO REPAIR, which is why the fixture below is not invented:

  * REQ-0006 is the client's one accepted promise; REQ-0004 is `superseded-by 0006`, and REQ-0002
    before it is `superseded-by 0004` — so a successor read one hop at a time lands on a retired
    text, and the card is an orphan again the moment anybody looks;
  * thirteen open cards still cite REQ-0004, pinned to its file and its commit, under the printed
    rule that nothing in them may go beyond that requirement — follow the rule and you build the
    old promise;
  * #511 duplicates #288, the decision to close it was taken and confirmed by the client, and
    NOTHING recorded it because no operation existed. She answered "Registrado o pedido junto ao
    time" and the next queue proposal put #511 first.

EVERY TEST HERE DRIVES THE PRODUCTION CALL PATH. The tracker and the board read are replaced at
their own seams — the adapter the module builds, and `board.read_board` — never the logic above
them. "Built, tested, reached by nothing" has happened fourteen times in this repository, and it is
always a test that re-implemented the thing it was checking.
"""

from __future__ import annotations

import logging
import subprocess

import pytest

from openfactory.contracts import AgentRunResult
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import FactoryBoard, Project, ProviderRef
from openfactory.ops import impediment
from openfactory.ops.impediment import PRODUCT_BOARD_UNREADABLE, PRODUCT_CANNOT_WRITE
from openfactory.product import board as board_module
from openfactory.product.config import ProductLink
from openfactory.product.corpus import Corpus, Requirement
from openfactory.product.loader import ProductContext
from openfactory.product.module import ProductModule, _with_criteria
from openfactory.product.triage import Ticket
from openfactory.product.voice import client_safe_detail, jargon_in

DOCS = "acmecorp/acme-books-documentation"
COMMIT = "c0ebc3c6620a1f"
ADMIN, OUTSIDER = "U0ADMIN", "U0RANDOM"
#: where the requirement files live INSIDE the documentation repo. Not "requirements": a directory
#: that happens to be the default would let a bare filename pass every assertion here.
REQUIREMENTS_DIR = "requisitos"

#: the thirteen that outlived REQ-0004 (issue #17), plus the pair that had to be merged (issue #3)
ORPHANS = [510, *range(512, 524)]


# ── the world, as production shaped it ──────────────────────────────────────────────────────────

def _card_body(*, objective: str, cites: int, criteria: list[str],
               out_of_scope: list[str] | None = None) -> str:
    """A card exactly as `issue_body` filed it — the shape the repair has to recognise."""
    from openfactory.product.authoring import issue_body
    from openfactory.product.role import IssueDraft

    return issue_body(IssueDraft(objective=objective, acceptance_criteria=criteria,
                                 out_of_scope=out_of_scope or [], cites=cites),
                      requirement_path=f"{REQUIREMENTS_DIR}/{cites:04d}-conferencia-de-notas.md",
                      docs_repo=DOCS, commit=COMMIT)


def _corpus() -> Corpus:
    """0002 → 0004 → 0006, plus one abandoned text with nothing behind it — and 0008 → 0009, the
    supersession that is only half decided.

    0009 is the shape `propose_requirement` writes and the recovery sweep merges: the replacement
    lands as `proposed` and stamps `superseded-by` on its predecessor IN THE SAME COMMIT, hours
    before anybody has agreed to it. Paths are bare filenames because that is what the corpus reads
    off disk (`corpus._read`); the directory lives on the context."""
    return Corpus(requirements=[
        Requirement(number=2, slug="conferencia", path="0002-conferencia.md", title="Conferência",
                    status="superseded", superseded_by=4),
        Requirement(number=4, slug="conferencia-de-notas", path="0004-conferencia-de-notas.md",
                    title="Conferência de notas", status="superseded", superseded_by=6),
        Requirement(number=5, slug="abandonado", path="0005-abandonado.md", title="Abandonado",
                    status="dropped"),
        Requirement(number=6, slug="conferencia-de-notas", path="0006-conferencia-de-notas.md",
                    title="Conferência de notas", status="accepted",
                    body="# REQ-0006 — Conferência de notas\n\n## What must be true\n\n"
                         "- [ ] todo aviso diz o que fazer a seguir\n"),
        Requirement(number=8, slug="fecho-mensal", path="0008-fecho-mensal.md",
                    title="Fecho mensal", status="superseded", superseded_by=9),
        Requirement(number=9, slug="fecho-mensal", path="0009-fecho-mensal.md",
                    title="Fecho mensal", status="proposed",
                    body="# REQ-0009 — Fecho mensal\n\n## What must be true\n\n"
                         "- [ ] o fecho sai no dia 5\n"),
    ])


class _Board:
    """The client's board, as `read_board` reports it — and as writes change it.

    Bodies live HERE rather than in each test because the idempotency claim is only worth something
    if the second read sees what the first run wrote."""

    def __init__(self) -> None:
        self.tickets: dict[int, Ticket] = {}
        self.error = ""
        for n in ORPHANS:
            # #512 also carries what REQ-0004 said was NOT to be touched. `issue_body` files that
            # section in English; `refine` writes the same one in pt-BR (#606 below). Both are read
            # by the executor under the rule that nothing may go beyond the requirement.
            self._add(n, f"Frente {n}",
                      _card_body(objective=f"o pedaço {n}", cites=4,
                                 criteria=[f"o pedaço {n} funciona"],
                                 out_of_scope=["não mexer no fecho mensal"] if n == 512 else []))
        # the duplicate pair: #288 predates every requirement and cites nothing
        self._add(288, "Conferência de notas de entrada",
                  "## Objective\n\nConferir as notas de entrada, escrito à mão por gente.\n")
        self._add(511, "Check inbound invoices",
                  _card_body(objective="o mesmo que o #288", cites=4, criteria=["confere"]))
        # a card whose requirement was ABANDONED — nothing took its place, so nothing to point at
        self._add(600, "Frente antiga", _card_body(objective="x", cites=5, criteria=["y"]))
        # already closed: a closed card executes nothing
        self._add(601, "Frente entregue", _card_body(objective="x", cites=4, criteria=["y"]),
                  state="closed")
        # the oldest chain — this is what catches a successor read one hop at a time
        self._add(602, "Frente de 2026", _card_body(objective="x", cites=2, criteria=["y"]))
        # a retired number MENTIONED in prose, cited nowhere: somebody explaining themselves
        self._add(603, "Conversa antiga",
                  "## Objective\n\nIsto veio do REQ-0004 originalmente, mas hoje é outra coisa.\n")
        # and one that cites the LIVE requirement while still talking about the old one
        self._add(604, "Frente atual",
                  _card_body(objective="substitui o que o REQ-0004 pedia", cites=6,
                             criteria=["z"]))
        # cites a requirement whose replacement exists but has NOT been agreed to yet
        self._add(605, "Fecho mensal", _card_body(objective="fechar o mês", cites=8,
                                                  criteria=["o fecho sai"]))
        # refined by the platform: `refine` writes its criteria in pt-BR, under its own heading
        self._add(606, "Frente refinada", _with_criteria(
            "## Objective\n\nconferir o lote do dia, escrito por gente.\n",
            {"criteria": ["o lote fecha sem sobra"], "questions": [],
             "out_of_scope": ["não mexer no fecho mensal"]}, agent="Nina"))
        # the same writer's THIRD section: what it could not determine about the text the card
        # followed then, and the line signing the criteria as read off the card's own description
        self._add(607, "Frente refinada com perguntas", _with_criteria(
            "## Objective\n\nfechar o mês, escrito por gente.\n",
            {"criteria": ["o fecho sai no prazo"], "out_of_scope": [],
             "questions": ["Qual o prazo do fechamento mensal?"]}, agent="Nina"))

    def _add(self, number: int, title: str, body: str, *, state: str = "open") -> None:
        self.tickets[number] = Ticket(number=number, title=title, body=body, state=state,
                                      column="Backlog")

    def read(self, project, *, token=None, limit=300, fresh=False):
        if self.error:
            return [], self.error
        return list(self.tickets.values()), ""


class _Tracker:
    """The tracker at the production seam, recording what was asked of it."""

    def __init__(self, *, breaks: str = "") -> None:
        self.closed: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []
        self.bodies: list[tuple[str, str]] = []
        self.breaks = breaks
        self.board: _Board | None = None

    def close_ticket(self, ref: str, reason: str, *, delivered: bool = True) -> None:
        self._maybe_break("close")
        self.closed.append((ref, reason))
        if self.board is not None:
            n = int(ref.lstrip("#"))
            self.board.tickets[n] = self.board.tickets[n].model_copy(update={"state": "closed"})

    def comment(self, ref: str, body: str) -> None:
        self._maybe_break("comment")
        self.comments.append((ref, body))

    def update_body(self, ref: str, body: str) -> None:
        self._maybe_break("update")
        self.bodies.append((ref, body))
        if self.board is not None:
            n = int(ref.lstrip("#"))
            self.board.tickets[n] = self.board.tickets[n].model_copy(update={"body": body})

    def _maybe_break(self, op: str) -> None:
        if self.breaks == op:
            raise RuntimeError(f"the forge refused to {op}")


class _FactoryTracker(_Tracker):
    """The FACTORY's board — where impediments go. Never the client's (ADR-0027)."""

    def __init__(self) -> None:
        super().__init__()
        self.tickets: dict[str, str] = {}
        self.created: list[tuple[str, str]] = []
        self._next = 900

    def find_ticket(self, *, title: str):
        return self.tickets.get(title)

    def create_ticket(self, *, title: str, body: str) -> str:
        # the factory's board runs on the same App quota as the client's, so it refuses for the
        # same reasons — a double that always accepts cannot show what a refusal costs
        self._maybe_break("create")
        self._next += 1
        self.tickets[title] = f"#{self._next}"
        self.created.append((title, body))
        return f"#{self._next}"

    def close_ticket(self, ref: str, reason: str, *, delivered: bool = True) -> None:
        self.closed.append((ref, reason))
        for title, r in list(self.tickets.items()):
            if r == ref:
                del self.tickets[title]

    def add_label(self, ref: str, label: str) -> None:
        pass

    def set_assignees(self, ref: str, logins: list[str]) -> None:
        pass


class _Harness:
    """The agent. Records every prompt, so a test can prove what the model was actually given."""

    name = "recording"

    def __init__(self, answer: str = "{}") -> None:
        self.prompts: list[str] = []
        self.answer = answer

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.prompts.append(prompt)
        return AgentRunResult(ok=True, summary=self.answer)


def _project() -> Project:
    return Project(
        name="books", repo_path="/work/books",
        factory_board=FactoryBoard(
            tracker=ProviderRef(kind="github", repo="AcmeCorp/openfactory"),
            supervisor="aliceferreira"),
        product=ProductConfig(docs_repo=DOCS, channel_id="C1", admins=[ADMIN],
                              agent_name="Nina"))


@pytest.fixture(autouse=True)
def _isolate():
    """`impediment._LAST` and the board snapshot are process-global by design — the first is what
    stops one forge call per client message. A suite whose result depends on file order proves
    nothing."""
    impediment._LAST.clear()
    board_module.forget_board()
    yield
    impediment._LAST.clear()
    board_module.forget_board()


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A module wired to a fake board, a fake tracker and a fake factory board — everything else is
    the real thing."""
    board, tracker, factory = _Board(), _Tracker(), _FactoryTracker()
    tracker.board = board
    monkeypatch.setattr(board_module, "read_board", board.read)
    monkeypatch.setattr(impediment, "_tracker_for", lambda project, tracker=None: factory)

    def _build(answer: str = "{}", *, breaks: str = ""):
        tracker.breaks = breaks
        ctx = ProductContext(
            link=ProductLink(active=True, docs_repo=DOCS, kind="ok", reason="fine"),
            corpus=_corpus(), docs_path=str(tmp_path), docs_commit=COMMIT,
            requirements_dir=REQUIREMENTS_DIR)
        harness = _Harness(answer)
        mod = ProductModule(_project(), context=ctx, agent=harness, tracker=tracker)
        return mod, harness

    _build.board = board          # type: ignore[attr-defined]
    _build.tracker = tracker      # type: ignore[attr-defined]
    _build.factory = factory      # type: ignore[attr-defined]
    return _build


# ── closing a card: one act, linked both ways ───────────────────────────────────────────────────

def test_closing_a_card_is_one_act_that_links_both_ways(world):
    """The decision to close #511 in favour of #288 was taken and confirmed, and nothing recorded
    it. A close with no pointer leaves the next reader asking why work vanished; a pointer with no
    close leaves the duplicate on the board and the queue proposes it first."""
    mod, _ = world()

    res = mod.close_card(511, actor=ADMIN, in_favour_of=288)

    assert res.ok is True and res.ref == "#511"
    assert [ref for ref, _ in world.tracker.closed] == ["#511"]
    _, closing = world.tracker.closed[0]
    assert "#288" in closing, "the closed card does not say where the work went"
    assert f"<@{ADMIN}>" in closing, "nobody is named on the decision"
    assert [ref for ref, _ in world.tracker.comments] == ["#288"]
    assert "#511" in world.tracker.comments[0][1], "the surviving card never learns what it absorbed"


def test_closing_needs_no_survivor_but_still_names_who_decided(world):
    mod, _ = world()

    assert mod.close_card(511, actor=ADMIN, reason="não vamos fazer isso").ok is True

    _, closing = world.tracker.closed[0]
    assert f"<@{ADMIN}>" in closing and "não vamos fazer isso" in closing
    assert world.tracker.comments == [], "a card that replaces nothing was commented on anyway"


def test_closing_is_gated_like_every_other_write(world):
    mod, _ = world()

    res = mod.close_card(511, actor=OUTSIDER, in_favour_of=288)

    assert res.ok is False and res.detail
    assert world.tracker.closed == [], "an unauthorised close reached the forge"


def test_a_card_already_closed_is_an_answer_not_a_second_close(world):
    mod, _ = world()

    res = mod.close_card(601, actor=ADMIN)

    assert res.ok is False and res.existed is True and "já estava fechado" in res.detail
    assert world.tracker.closed == []


def test_a_card_that_is_not_on_the_board_is_never_closed_blindly(world):
    mod, _ = world()

    res = mod.close_card(9999, actor=ADMIN)

    assert res.ok is False and "9999" in res.detail
    assert world.tracker.closed == []


def test_closing_in_favour_of_a_card_that_does_not_exist_writes_nothing(world):
    """A dangling pointer is worse than no pointer at all (`corpus._cross_check` says so about
    requirements, and a card is read by the same people)."""
    mod, _ = world()

    res = mod.close_card(511, actor=ADMIN, in_favour_of=9999)

    assert res.ok is False and "9999" in res.detail
    assert world.tracker.closed == [], "a card was closed pointing at nothing"


def test_closing_in_favour_of_a_card_that_is_ALSO_closed_writes_nothing(world):
    """The board is read with `--state all`, so a card closed last month is on the list and passes
    "does the survivor exist?". Folding work into it closes both and the work is tracked nowhere —
    worse than the dangling pointer above, because this one reads as correct on the way past."""
    mod, _ = world()

    res = mod.close_card(511, actor=ADMIN, in_favour_of=601)

    assert res.ok is False and "601" in res.detail
    assert world.tracker.closed == [], "the work was closed into a card nobody is watching"
    assert world.tracker.comments == []


def test_a_close_that_could_not_be_linked_still_reports_the_close(world):
    """The close happened. Reporting failure would invite somebody to close it again."""
    mod, _ = world(breaks="comment")

    res = mod.close_card(511, actor=ADMIN, in_favour_of=288)

    assert res.ok is True and "#288" in res.detail
    assert world.tracker.closed, "the close was rolled back because a comment failed"


# ── aligning a card to the requirement it should execute ────────────────────────────────────────

_ALIGNED = ('{"criteria": ["todo aviso diz o que fazer a seguir", "o total confere"], '
            '"out_of_scope": [], "questions": ["quem assina o aviso?"]}')


def test_aligning_makes_the_card_cite_the_named_requirement(world):
    """#288 predates every requirement and had no citation at all — after this it executes 0006,
    pinned to its file and the commit it was read from."""
    mod, _ = world(_ALIGNED)

    res = mod.align_card(288, requirement=6, actor=ADMIN)

    assert res.ok is True
    _, body = world.tracker.bodies[0]
    assert "REQ-0006" in body and "0006-conferencia-de-notas.md" in body
    assert COMMIT[:12] in body
    assert "REQ-0004" not in body


def test_the_criteria_are_derived_from_that_requirement_and_nothing_else(world):
    mod, harness = world(_ALIGNED)

    mod.align_card(288, requirement=6, actor=ADMIN)

    prompt = harness.prompts[-1]
    assert "REQ-0006" in prompt
    assert "todo aviso diz o que fazer a seguir" in prompt, "the requirement's own text never " \
                                                            "reached the model"
    _, body = world.tracker.bodies[0]
    assert "- [ ] todo aviso diz o que fazer a seguir" in body
    assert "- [ ] o total confere" in body


def test_aligning_keeps_what_a_person_wrote(world):
    """#288 was typed by a human. An agent that silently replaces a description teaches people to
    distrust everything it touches."""
    mod, _ = world(_ALIGNED)

    mod.align_card(288, requirement=6, actor=ADMIN)

    _, body = world.tracker.bodies[0]
    assert "escrito à mão por gente" in body


def test_aligning_an_orphan_replaces_its_criteria_rather_than_stacking_a_second_set(world):
    mod, _ = world(_ALIGNED)

    mod.align_card(516, requirement=6, actor=ADMIN)

    _, body = world.tracker.bodies[0]
    assert body.count("## Acceptance criteria") == 1
    assert "o pedaço 516 funciona" not in body, "the old criteria survived the alignment"


def test_aligning_says_out_loud_that_it_rewrote_the_criteria(world):
    mod, _ = world(_ALIGNED)

    mod.align_card(516, requirement=6, actor=ADMIN)

    _, note = world.tracker.comments[0]
    assert "requisito 6" in note
    assert "quem assina o aviso?" in note, "what she could not determine was dropped"


def test_aligning_refuses_a_requirement_that_is_no_longer_live(world):
    """Aligning onto a retired text is the defect this method repairs, performed on purpose."""
    mod, _ = world(_ALIGNED)

    res = mod.align_card(288, requirement=4, actor=ADMIN)

    assert res.ok is False and "4" in res.detail
    assert world.tracker.bodies == []


def test_aligning_refuses_a_requirement_nobody_has_agreed_to_yet(world):
    """`proposed` is LIVE — it is neither superseded nor dropped — and it is not something to
    build. The card would carry criteria derived from a proposal, under the printed rule that
    nothing in it may go beyond that requirement, while the client may still say no."""
    mod, harness = world(_ALIGNED)

    res = mod.align_card(288, requirement=9, actor=ADMIN)

    assert res.ok is False and "9" in res.detail
    assert world.tracker.bodies == [], "a card was written from a text nobody agreed to"
    assert harness.prompts == [], "a refused alignment still paid for a model call"


def test_both_acts_that_aim_the_factory_refuse_a_proposal_with_the_SAME_sentence(world):
    """`break_down` refused this and `align_card` did not — the rule was stated one method away
    and not copied. One sentence for one rule: a person told two different things about it learns
    the rule is arbitrary."""
    mod, _ = world(_ALIGNED)

    aligned = mod.align_card(288, requirement=9, actor=ADMIN)
    filed = mod.break_down(9, actor=ADMIN)

    assert aligned.detail == filed[0].detail
    assert "acordado" in aligned.detail
    assert "proposed" not in aligned.detail, "the client was handed the machine's word for it"


def test_aligning_a_REFINED_card_replaces_its_criteria_instead_of_stacking_a_second_set(world):
    """`refine` writes `## Critérios de aceite`; `issue_body` writes `## Acceptance criteria`. One
    section, two names the platform itself uses — and surgery that knows only one of them ADDS the
    new set under a comment saying the old one was substituted. Whoever picks the card up then
    builds the older promise, which is the defect this method exists to repair."""
    mod, _ = world(_ALIGNED)

    res = mod.align_card(606, requirement=6, actor=ADMIN)

    assert res.ok is True
    _, body = world.tracker.bodies[0]
    assert "o lote fecha sem sobra" not in body, "the card kept the criteria it had before"
    assert body.count("## Acceptance criteria") == 1
    assert "## Critérios de aceite" not in body, "the card carries two sets of criteria at once"
    assert "escrito por gente" in body, "what a person wrote was taken away"


#: what the model returns when the NEW requirement excludes something of its own
_ALIGNED_WITH_SCOPE = ('{"criteria": ["todo aviso diz o que fazer a seguir"], '
                       '"out_of_scope": ["não mexer no cadastro de clientes"], "questions": []}')


def test_an_aligned_card_keeps_no_EXCLUSION_from_the_text_it_stopped_executing(world):
    """The sibling of the criteria, one section down and asked for by the same schema. The answer's
    `out_of_scope` was thrown away, so the card came out of the alignment carrying the RETIRED
    requirement's exclusions under a Source line ordering the executor not to go beyond the new
    one — one fresh set and one stale one, which is the state this method exists to repair."""
    mod, _ = world(_ALIGNED_WITH_SCOPE)

    res = mod.align_card(512, requirement=6, actor=ADMIN)

    assert res.ok is True
    _, body = world.tracker.bodies[0]
    assert "não mexer no fecho mensal" not in body, "the retired text's exclusions survived"
    assert "não mexer no cadastro de clientes" in body, "what the new requirement excludes was lost"
    assert body.count("## Out of scope") == 1


def test_an_aligned_card_carries_ONE_set_of_exclusions_whatever_they_were_called(world):
    """`issue_body` writes `## Out of scope` and `refine` writes `## Fora de escopo` — one section
    under two names this platform itself uses. Surgery that knows one of them adds the new set
    beside the old, and whoever picks the card up honours the replaced requirement's limits."""
    mod, _ = world(_ALIGNED_WITH_SCOPE)

    res = mod.align_card(606, requirement=6, actor=ADMIN)

    assert res.ok is True
    _, body = world.tracker.bodies[0]
    assert "## Fora de escopo" not in body, "the card carries two sets of exclusions at once"
    assert body.count("## Out of scope") == 1
    assert "não mexer no fecho mensal" not in body
    assert "escrito por gente" in body, "what a person wrote was taken away"


def test_an_alignment_that_excludes_NOTHING_still_takes_the_old_exclusions_away(world):
    """The dangerous half: a section the new render is silent about is not a section to keep. It is
    the retired requirement's, and it stays under a citation saying otherwise."""
    mod, _ = world(_ALIGNED)   # "out_of_scope": []

    res = mod.align_card(512, requirement=6, actor=ADMIN)

    assert res.ok is True
    _, body = world.tracker.bodies[0]
    assert "não mexer no fecho mensal" not in body
    assert "Out of scope" not in body and "Fora de escopo" not in body
    assert "## Acceptance criteria" in body and "## Source" in body


def test_an_aligned_card_keeps_no_QUESTION_and_no_ATTRIBUTION_from_the_text_it_left_behind(world):
    """The third section `refine` writes, and the one the rewrite did not list.

    This is the flow the refusal advertises: #607 already says when it would be done, so `refine`
    declines and tells the client to align it — and the card came out with fresh criteria above the
    OLD open questions, derived from the retired text, plus the signature claiming those criteria
    were read off the card's own description. Both sit under the Source line ordering whoever works
    it not to go beyond the new requirement, and the questions are the only ones on the card.

    One fresh set and one stale set is the state `_rewritten` exists to prevent; a section it was
    never told about is that state with a different heading."""
    mod, _ = world(_ALIGNED)

    res = mod.align_card(607, requirement=6, actor=ADMIN)

    assert res.ok is True
    _, body = world.tracker.bodies[0]
    assert "Qual o prazo do fechamento mensal?" not in body, \
        "the retired text's open questions survived the alignment"
    assert "## Em aberto" not in body
    assert "critérios escritos a partir do que já estava descrito" not in body, \
        "the card still attributes its new criteria to its own old description"
    assert "escrito por gente" in body, "what a person wrote was taken away"
    assert "- [ ] o total confere" in body and "## Source" in body
    assert "quem assina o aviso?" in world.tracker.comments[0][1], \
        "what she could not determine about the NEW requirement was dropped"


def test_an_alignment_that_landed_is_not_undone_by_the_note_that_failed(world):
    """`close_card` gets this right and its two siblings did not: sharing one `try` reports a
    rewrite that DID happen as a total failure, and the admin is told the card still executes the
    old text while its criteria have in fact already been replaced."""
    mod, _ = world(_ALIGNED, breaks="comment")

    res = mod.align_card(516, requirement=6, actor=ADMIN)

    assert res.ok is True, "the rewrite was reported as failed after it had landed"
    assert [ref for ref, _ in world.tracker.bodies] == ["#516"]
    assert "#516" in res.detail, "nothing says the card was rewritten without its explanation"


def test_aligning_is_gated_and_costs_nothing_when_refused(world):
    mod, harness = world(_ALIGNED)

    res = mod.align_card(288, requirement=6, actor=OUTSIDER)

    assert res.ok is False
    assert harness.prompts == [], "an unauthorised request still paid for a model call"
    assert world.tracker.bodies == []


def test_an_unreadable_answer_leaves_the_card_alone(world):
    mod, _ = world("acho que dois critérios bastam")

    res = mod.align_card(288, requirement=6, actor=ADMIN)

    assert res.ok is False
    assert world.tracker.bodies == []


# ── refining a card: the same two writes, and the writer the rule was not copied to ─────────────

#: what the model returns for a card that says nothing about when it would be done
_REFINED = ('{"criteria": ["o lote fecha sem sobra"], "out_of_scope": [], '
            '"questions": ["quem confere o total?"]}')


def test_a_refinement_that_landed_is_not_undone_by_the_note_that_failed(world, caplog):
    """The third writer of one rule, and the one it was not copied to: `close_card` states it,
    `align_card` and `repoint_orphans` follow it, and `refine` kept both writes under one `try`.

    Here the wrong answer repairs itself in the worst direction. The criteria ARE on the card, the
    client is told they are not, and the next attempt — theirs, or the sweep's — appends a second
    set under its own heading: the two-sets-on-one-card state the alignment exists to repair.

    And the success carries what it did NOT do, in the client's words: an `ok` that says only "1
    critérios" leaves the reply announcing a comment nobody wrote, which is the same act as
    announcing a card that was never closed."""
    from openfactory.product.voice import client_safe_detail

    mod, _ = world(_REFINED, breaks="comment")

    with caplog.at_level(logging.WARNING):
        res = mod.refine(288, actor=ADMIN)

    assert res.ok is True, "a refinement that landed was reported as a failure"
    assert [ref for ref, _ in world.tracker.bodies] == ["#288"]
    assert "- [ ] o lote fecha sem sobra" in world.tracker.bodies[0][1]
    assert "não consegui deixar o comentário" in res.detail, \
        "the missing note was computed for us and never offered to the person it concerns"
    assert client_safe_detail(res.detail)[1] == "", "the sentence cannot reach a client as written"
    assert "OPENFACTORY_PRODUCT_REFINE_UNEXPLAINED" in caplog.text, \
        "the attribution was lost with nothing in the log saying so"


def test_the_snapshot_is_dropped_by_the_write_that_changed_the_card_not_by_the_note(world,
                                                                                   monkeypatch):
    """WHY THE ORDER IS LOAD-BEARING. `has_criteria` — the check that decides whether refining is
    needed at all — is read from the cached board. Leaving the invalidation behind a write that can
    fail means the snapshot keeps saying the card has no criteria for as long as it lives, so the
    duplicate set is not a possibility, it is what the next pass does."""
    forgotten: list[str] = []
    monkeypatch.setattr(board_module, "forget_board",
                        lambda name=None: forgotten.append(name))
    mod, _ = world(_REFINED, breaks="comment")

    mod.refine(288, actor=ADMIN)

    assert forgotten == ["books"], "the board we cached still shows a card that changed"


def test_a_card_the_forge_would_not_rewrite_is_never_commented_on(world):
    """The other half: nothing landed, so nothing may be said on the card — and what the client
    reads is a sentence, never the forge's own words."""
    mod, _ = world(_REFINED, breaks="update")

    res = mod.refine(288, actor=ADMIN)

    assert res.ok is False
    assert world.tracker.comments == [], "the card was told about a rewrite that never happened"
    assert "refused" not in res.detail and "Error" not in res.detail, \
        "the forge's own words went into a business conversation"
    assert "#288" in res.detail


def test_no_act_on_a_card_shares_a_try_with_the_comment_that_explains_it():
    """A GUARD, not a case — the fourth writer inherits the rule instead of rediscovering it.

    Four methods here write to a card and then say on it what they did. Three had the two writes
    separated and `refine` did not, which is this repository's signature failure inside the fix for
    it: the lesson learned in one file, and not copied to the method below. A courtesy comment may
    never decide the fate of the act it describes, so it may never share its `try`."""
    import ast
    from pathlib import Path

    import openfactory.product.module as module

    #: everything that CHANGES a card. A comment sharing a `try` with any of them can report it as
    #: having failed — or, wrapped the other way, be swallowed by its success.
    acts = {"update_body", "close_ticket", "create_ticket", "set_state", "add_item", "set_column"}
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    shared: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        called = {getattr(call.func, "attr", "") for stmt in node.body
                  for call in ast.walk(stmt) if isinstance(call, ast.Call)}
        if "comment" in called and called & acts:
            shared.append(f"module.py:{node.lineno} ({', '.join(sorted(called & acts))})")

    assert not shared, (
        "a comment shares a `try` with the write it describes, so one can undo the other:\n  "
        + "\n  ".join(shared))


# ── the orphans of a replaced requirement ───────────────────────────────────────────────────────

def test_every_open_card_citing_a_retired_requirement_is_found(world):
    mod, _ = world()

    orphans = mod.orphaned_cards()

    assert {n for n, _, _ in orphans} == {str(n) for n in (*ORPHANS, 511, 602)}, "an orphan was missed"
    assert len([n for n, cited, _ in orphans if cited == 4]) == len(ORPHANS) + 1


def test_the_successor_is_the_LAST_live_requirement_not_the_next_one(world):
    """0002 → 0004 → 0006. Repointing #602 at 0004 would make it an orphan again immediately."""
    mod, _ = world()

    successors = {n: s for n, _, s in mod.orphaned_cards()}

    assert successors["602"] == 6, "the chain was followed one hop and stopped on a retired text"
    assert set(successors.values()) == {6}


def test_a_closed_card_and_a_card_with_no_citation_are_not_orphans(world):
    mod, _ = world()

    found = {n for n, _, _ in mod.orphaned_cards()}

    assert 601 not in found, "a closed card executes nothing"
    assert 288 not in found, "a card that cites nothing was claimed to cite something"


def test_a_requirement_MENTIONED_in_prose_is_not_a_citation(world):
    """The Source line is what an executor is told not to go beyond; a number in the description is
    somebody explaining themselves. Repointing on a mention would rewrite cards nobody claimed were
    derived from anything — including one that already executes the live text."""
    mod, _ = world()

    found = {n for n, _, _ in mod.orphaned_cards()}

    assert 603 not in found, "a card was repointed because its prose mentioned an old number"
    assert 604 not in found, "a card already citing the live requirement was called an orphan"


def test_an_abandoned_requirement_leaves_its_card_alone(world):
    """`dropped` means nothing took its place. Inventing a target would send the reader somewhere
    nobody decided."""
    mod, _ = world()

    assert 600 not in {n for n, _, _ in mod.orphaned_cards()}


def test_a_replacement_nobody_has_agreed_to_is_not_somewhere_to_repoint_a_card(world):
    """REQ-0008 was retired by REQ-0009 in the commit that PROPOSED it, and the recovery sweep
    merges that commit before anybody has said yes. This runs UNATTENDED and hourly, with no actor
    and no confirmation, and it announces itself to the client channel — so following `is_live`
    here retargets cards onto a text the client may still reject and tells them it happened.

    The card stays where it is: nothing has taken 0008's place YET, and the sweep after the
    confirmation is what repairs it."""
    mod, _ = world()

    assert 605 not in {n for n, _, _ in mod.orphaned_cards()}

    mod.repoint_orphans()

    assert "#605" not in [ref for ref, _ in world.tracker.bodies]


def test_nothing_to_AIM_at_is_never_the_answer_to_what_replaced_this(world):
    """`_successor` answers what an unattended repair may re-aim a card at, and its None carries
    exactly that meaning: 0009 exists, reads perfectly, and simply has not been agreed to yet.

    A caller that reads the same None as "the corpus has no replacement" tells the client a
    readable text cannot be found and raises a broken-chain alarm on the ordinary healthy shape.
    The reading is pinned here, where the answer is produced, because the two consumers sit in
    different layers and share this one private function precisely so they cannot disagree."""
    from openfactory.product.module import _successor

    corpus = _corpus()

    assert _successor(corpus, 8) is None, "an unagreed replacement became somewhere to aim at"
    assert corpus.by_number(8).superseded_by == 9
    assert corpus.by_number(9) is not None, \
        "the corpus can read 0009 — a caller may only say it cannot when by_number says so"
    assert _successor(corpus, 2) == 6, "the chain was followed one hop and stopped"


def test_finding_orphans_costs_no_model_call(world):
    mod, harness = world()

    mod.orphaned_cards()

    assert harness.prompts == [], "a deterministic read spent money"


# ── repointing: bookkeeping the platform owes, and nothing more ─────────────────────────────────

def test_repointing_rewrites_the_citation_of_every_orphan(world):
    mod, _ = world()

    results = mod.repoint_orphans()

    assert len(results) == len(ORPHANS) + 2 and all(r.ok for r in results)
    for _ref, body in world.tracker.bodies:
        assert "REQ-0006" in body and "0006-conferencia-de-notas.md" in body
        assert "REQ-0004" not in body and "REQ-0002" not in body


def test_repointing_never_rewrites_what_must_be_true(world):
    """Re-deriving criteria spends money and changes what gets BUILT — that is a decision, and it
    belongs to `align_card` behind a confirmation."""
    mod, _ = world()
    before = world.board.tickets[516].body

    mod.repoint_orphans()

    after = dict(world.tracker.bodies)["#516"]
    from openfactory.product.module import _section_of

    assert _section_of(after, "Acceptance criteria") == _section_of(before, "Acceptance criteria")
    assert "o pedaço 516 funciona" in after


def test_the_comment_says_the_criteria_were_written_against_the_older_text(world):
    """Whoever picks the card up must not read the new citation and assume somebody checked."""
    mod, _ = world()

    mod.repoint_orphans()

    _, note = world.tracker.comments[0]
    assert "requisito 6" in note and "requisito 4" in note
    assert "texto antigo" in note


def test_repointing_twice_changes_nothing_the_second_time(world):
    """Idempotent BY CONSTRUCTION: a card citing a live requirement is not an orphan."""
    mod, _ = world()

    first = mod.repoint_orphans()
    written = len(world.tracker.bodies)
    second = mod.repoint_orphans()

    assert first and second == []
    assert len(world.tracker.bodies) == written, "the second pass wrote to the forge again"
    assert mod.orphaned_cards() == []


def test_repointing_costs_no_model_call(world):
    mod, harness = world()

    mod.repoint_orphans()

    assert harness.prompts == [], "bookkeeping spent a model call"


def test_a_repoint_that_would_change_nothing_is_never_announced(world, monkeypatch):
    """The whole reason `_source_section` is rendered by `issue_body` is that one renderer cannot
    drift from itself — but if it ever stopped producing a Source block, writing the body back
    unchanged and commenting "this card now executes 6" would be announcing an act that did not
    happen. That is the defect this platform exists to make impossible (ADR-0028)."""
    import openfactory.product.module as module

    monkeypatch.setattr(module, "issue_body", lambda *a, **kw: "## Objective\n\nsem citação\n")
    mod, _ = world()

    assert mod.repoint_orphans() == []
    assert world.tracker.bodies == [] and world.tracker.comments == []


def test_one_card_that_could_not_be_written_does_not_lose_the_others(world):
    mod, _ = world(breaks="update")

    results = mod.repoint_orphans()

    assert results and all(r.ok is False for r in results)
    assert len(results) == len(ORPHANS) + 2, "the first failure ended the pass"


def test_a_citation_that_moved_is_reported_even_when_its_warning_could_not_be_left(world, caplog):
    """Here the cost of one shared `try` is PERMANENT: the card has stopped being an orphan, so no
    later sweep comes back for the sentence saying its criteria were written against the replaced
    text. Reporting the card as failed on top of that would hide the repair that did land."""
    mod, _ = world(breaks="comment")

    with caplog.at_level(logging.WARNING):
        results = mod.repoint_orphans()

    assert results and all(r.ok for r in results), "a landed repoint was reported as a failure"
    assert len(world.tracker.bodies) == len(results)
    assert "OPENFACTORY_PRODUCT_REPOINT_UNEXPLAINED" in caplog.text, \
        "a card was left citing a new requirement with nothing saying its criteria are older"


class _Filing(_Tracker):
    """A forge that files, keeping every body it was handed."""

    def __init__(self) -> None:
        super().__init__()
        self.created: list[tuple[str, str]] = []

    def find_ticket(self, *, title):
        return None

    def create_ticket(self, *, title, body):
        self.created.append((title, body))
        return "#700"


def test_every_citation_points_at_the_file_as_it_lives_in_the_docs_repo(world):
    """The corpus reads the requirement's number off its FILENAME and stores exactly that; the file
    itself lives under the manifest's directory. `accept` learned this after every accept answered
    "não encontrei o requisito" about a requirement it had just listed — and the writers that
    render a citation each repeated it, so the card sent whoever follows it (a person, or the agent
    told not to go beyond that requirement) to a path that resolves to nothing.

    ALL FOUR, because the fourth is how the lesson got here. Three were repaired and `defect_body`
    went on rendering the raw field, on the one card whose whole purpose is to name the promise
    that was broken. They now share one renderer (`authoring.requirement_file`), so the fifth
    writer inherits the answer instead of the trap."""
    where = f"{REQUIREMENTS_DIR}/0006-conferencia-de-notas.md"
    mod, _ = world(_ALIGNED)

    mod.repoint_orphans()
    assert world.tracker.bodies
    for _ref, body in world.tracker.bodies:
        assert where in body, "a repointed card cites a path that is not in the repository"

    mod.align_card(288, requirement=6, actor=ADMIN)
    assert where in world.tracker.bodies[-1][1]

    filing = _Filing()
    filer, _ = world('{"issues": [{"title": "Uma frente", "objective": "o", '
                     '"acceptance_criteria": ["c"]}]}')
    filer.file_issues(_corpus().by_number(6), actor=ADMIN, tracker=filing, board=None)
    assert filing.created and all(where in body for _t, body in filing.created)

    reporting = _Filing()
    reporter, _ = world()
    res = reporter.file_defect(restated="o aviso não sai", reported_by="<@U1>", violates=6,
                               tracker=reporting, board=None)
    assert res.ok and reporting.created
    assert where in reporting.created[0][1], \
        "the defect card names the broken promise at a path nobody can open"


# ── the two remaining degradations reach the factory board ──────────────────────────────────────

def test_a_board_it_cannot_read_opens_exactly_one_impediment(world):
    """Ten messages against a broken board must cost one ticket, not ten: this runs on the path of
    every client message and the App quota is shared with the poller and every job."""
    mod, _ = world()
    world.board.error = "could not list the issues of AcmeCorp/acme-books"

    for _ in range(10):
        mod.orphaned_cards()

    titles = [t for t, _ in world.factory.created]
    assert len(titles) == 1, f"{len(titles)} tickets for one trouble"
    assert impediment.title_for("books", PRODUCT_BOARD_UNREADABLE) == titles[0]
    assert "could not list the issues" in world.factory.created[0][1]


def test_a_filing_the_factory_board_REFUSED_is_filed_on_the_next_message(world):
    """One throttled create must not silence the whole channel for the life of the worker.

    Every product capability that promises something reaches the factory through one seam, so an
    impediment remembered as filed when the create had raised takes them ALL down at once: nothing
    on the board, one log line at the moment it happened, and the client still reading "o time foi
    avisado" on every refusal after it. Driven from the degradation itself, not from `report`."""
    mod, _ = world()
    world.board.error = "could not list the issues of AcmeCorp/acme-books"
    world.factory.breaks = "create"

    mod.orphaned_cards()
    assert world.factory.created == [], "the double accepted a create it was told to refuse"

    world.factory.breaks = ""
    mod.orphaned_cards()

    assert [t for t, _ in world.factory.created] == [
        impediment.title_for("books", PRODUCT_BOARD_UNREADABLE)], \
        "the impediment was remembered as filed, so it never was"


def test_a_board_that_reads_again_closes_it_by_observation(world):
    mod, _ = world()
    world.board.error = "throttled"
    mod.orphaned_cards()
    assert world.factory.created

    world.board.error = ""
    mod.orphaned_cards()

    assert world.factory.closed, "nobody observed the board working again"
    assert world.factory.tickets == {}


def test_the_conversational_path_reports_the_board_too(world):
    """`_board_cards` runs on EVERY client message — the reader most likely to notice first, and
    the one that used to swallow the failure into a log line. (Was `_board_columns`, which handed
    over `{number: column}`; it now hands over whole tickets, so the conversational surface can
    read `state`/`state_reason` and stop being the one place delivery is ungoverned.)"""
    mod, _ = world()
    world.board.error = "unreachable"

    mod._board_cards()

    assert world.factory.created


def test_a_write_that_failed_for_a_machine_reason_opens_one_impediment(world):
    mod, _ = world(breaks="update")

    mod.repoint_orphans()

    titles = [t for t, _ in world.factory.created]
    assert titles == [impediment.title_for("books", PRODUCT_CANNOT_WRITE)], \
        "fourteen failed writes filed one ticket each, or none at all"
    assert "update_body" in world.factory.created[0][1]


def test_a_close_the_forge_refused_reaches_the_factory_and_announces_nothing(world):
    mod, _ = world(breaks="close")

    res = mod.close_card(511, actor=ADMIN, in_favour_of=288)

    assert res.ok is False and res.detail
    assert [t for t, _ in world.factory.created] == [
        impediment.title_for("books", PRODUCT_CANNOT_WRITE)]
    assert world.tracker.comments == [], "the survivor was told about a close that never happened"


def test_a_LOOKUP_that_aborts_a_write_is_the_write_failing(world):
    """`_file_one` and `file_defect` ask "does this already exist?" before creating. A lookup that
    raises means the create never ran — the client hears the same sentence as for any other broken
    write, and an operator who only hears about half of them triages a board that lies."""
    class _Blind(_Tracker):
        def find_ticket(self, *, title):
            raise RuntimeError("the forge could not be reached")

    mod, _ = world('{"issues": [{"title": "Uma frente", "objective": "o", '
                   '"acceptance_criteria": ["c"]}]}')
    mod._given_tracker = _Blind()

    results = mod.file_issues(_corpus().by_number(6), actor=ADMIN, board=None)

    assert all(r.ok is False for r in results)
    assert impediment.title_for("books", PRODUCT_CANNOT_WRITE) in [
        t for t, _ in world.factory.created]


def test_the_next_write_that_works_closes_it(world):
    mod, _ = world(breaks="update")
    mod.repoint_orphans()
    assert world.factory.created

    world.tracker.breaks = ""
    mod.repoint_orphans()

    assert world.factory.closed, "an operator who fixed it and a fix that never happened look alike"


def test_a_close_that_lands_is_evidence_the_capability_is_back(world):
    """Any write that works closes it — the impediment is about the capability, not about the one
    operation that happened to notice it was gone."""
    mod, _ = world(breaks="update")
    mod.repoint_orphans()
    assert world.factory.created

    world.tracker.breaks = ""
    assert mod.close_card(511, actor=ADMIN, in_favour_of=288).ok is True

    assert world.factory.closed


def test_a_read_coming_back_is_not_evidence_that_writing_works(world):
    """Asymmetric on purpose. A lookup that fails aborts a write, so it OPENS the ticket; a lookup
    that succeeds only proves the forge answered. Closing "uma escrita falhou" on that would be a
    self-report wearing the clothes of an observation (ADR-0021)."""
    class _Known(_Tracker):
        def find_ticket(self, *, title):
            return "#42"

    mod, _ = world(breaks="update")
    mod.repoint_orphans()
    assert world.factory.created

    mod._given_tracker = _Known()
    mod.file_defect(restated="a conciliação duplica lançamentos", reported_by="<@U1>",
                    violates=None, board=None)

    assert world.factory.closed == [], "a read closed a ticket about writing"


def test_a_business_refusal_never_reaches_the_factory_board(world):
    """"That card is already closed" is an answer somebody can act on in the conversation. A board
    carrying those alongside real breakage is a board nobody triages."""
    mod, _ = world()

    mod.close_card(601, actor=ADMIN)                       # already closed
    mod.close_card(511, actor=OUTSIDER, in_favour_of=288)  # not authorised
    mod.align_card(288, requirement=4, actor=ADMIN)        # requirement retired

    assert world.factory.created == []


def test_a_board_that_REFUSES_a_placement_is_a_machine_failure_too(world):
    """A card with no column is invisible to `readiness` and `propose_queue` for ever, while the
    reply told the client it was filed. `False` from a board is the write not happening — reading
    it as a quieter success is exactly how that state was reached (ADR-0030).

    Filed with NO board argument, so the placement comes through the production default."""
    class _Refusing:
        def add_item(self, *, issue_url):
            return True

        def set_column(self, *, issue, issue_url, name):
            return False

    class _Filing(_Tracker):
        def find_ticket(self, *, title):
            return None

        def create_ticket(self, *, title, body):
            return "#700"

    mod, _ = world('{"issues": [{"title": "Uma frente", "objective": "o", '
                   '"acceptance_criteria": ["c"]}]}')
    mod._given_tracker, mod._given_board = _Filing(), _Refusing()

    mod.file_issues(_corpus().by_number(6), actor=ADMIN)

    filed_for = dict(world.factory.created)
    title = impediment.title_for("books", PRODUCT_CANNOT_WRITE)
    assert title in filed_for, "the board refused and the factory never heard about it"
    assert "set_column" in filed_for[title]


# ── the module over the REAL tracker: a fake that raises proves nothing about production ────────

class _GH:
    """The `gh` binary's whole contract: an exit code, and text on two streams.

    THE FAKES ABOVE RAISE, AND THE PRODUCTION ADAPTER DID NOT. Every guard in this file was
    exercised against a double that honoured a contract `GitHubIssuesTracker` broke — it called
    `gh`, ignored the exit code and returned None — so the guard was reached by nothing where it
    mattered. These two drive the module through the real adapter with a scripted binary.

    Failures exit 1 with a stderr carrying no rate-limit marker, so `_gh`'s backoff never sleeps.
    """

    def __init__(self, *, fails: str) -> None:
        self.calls: list[list[str]] = []
        self.fails = fails

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        if self.fails in " ".join(argv):
            return subprocess.CompletedProcess(
                argv, 1, stdout="", stderr="HTTP 403: Resource not accessible by integration")
        return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")

    def matching(self, *needles: str) -> list[list[str]]:
        return [c for c in self.calls if all(n in " ".join(c) for n in needles)]


def _real_tracker():
    from openfactory.adapters.tracker.github import GitHubIssuesTracker

    return GitHubIssuesTracker("AcmeCorp/acme-books")


def test_a_close_the_real_forge_refused_is_never_announced_as_a_close(world, monkeypatch):
    """#511 stays open, the client is not told it was closed, and #288 is not told it absorbed
    anything. The failure this recreates is louder than the one it repairs: "Registrado o pedido
    junto ao time" said nothing had happened, and a swallowed exit code says the opposite."""
    gh = _GH(fails="issue close")
    monkeypatch.setattr(subprocess, "run", gh)
    mod, _ = world()
    mod._given_tracker = _real_tracker()

    res = mod.close_card(511, actor=ADMIN, in_favour_of=288)

    assert res.ok is False, "a close the forge refused was reported to the client as done"
    assert res.detail and "gh " not in res.detail
    assert gh.matching("issue comment") == [], \
        "the surviving card was told it absorbed a close that never happened"
    assert [t for t, _ in world.factory.created] == [
        impediment.title_for("books", PRODUCT_CANNOT_WRITE)]


def test_a_search_the_real_forge_refused_never_files_a_second_card(world, monkeypatch):
    """The lookup that gates a create. GitHub's search has its own, much lower limit than issue
    creation, so it failing while `issue create` still works is the ordinary case — and reading
    that as "no such card" is the platform manufacturing the #511-duplicates-#288 state itself."""
    gh = _GH(fails="issue list")
    monkeypatch.setattr(subprocess, "run", gh)
    mod, _ = world()
    mod._given_tracker = _real_tracker()

    res = mod.file_defect(restated="a conciliação duplica lançamentos", reported_by="<@U1>",
                          violates=6, board=None)

    assert res.ok is False, "a card was reported as filed on a search that never ran"
    assert gh.matching("issue create") == [], "a throttled search filed a duplicate card"
    assert impediment.title_for("books", PRODUCT_CANNOT_WRITE) in [
        t for t, _ in world.factory.created]


def test_reporting_trouble_never_costs_the_client_their_answer(world, monkeypatch):
    """Nothing may raise out of the reporting path — an impediment that ate a reply would be a
    worse bug than the one it reports. Broken at the seam this module owns, not inside
    `impediment`: that module swallows its own trouble, and a guard that only works because
    something downstream is also careful is not a guard."""
    def _explode(*a, **kw):
        raise RuntimeError("the factory board is on fire")

    monkeypatch.setattr(impediment, "report", _explode)
    monkeypatch.setattr(impediment, "resolved", _explode)
    mod, _ = world()

    assert mod.close_card(511, actor=ADMIN, in_favour_of=288).ok is True
    world.board.error = "unreachable"
    assert mod.orphaned_cards() == []


# ── what a client may read is COMPOSED, never caught ────────────────────────────────────────────
#
# `WriteResult.detail` serves two audiences with opposite needs, and the channel sanitises it at the
# boundary by recognising machinery SHAPES — `fatal:`, an HTTP code, a path, a `*Error` name. That
# guard can only catch what it has already been shown, so every assertion below checks the detail is
# CLEAN AT THE SOURCE (`client_safe_detail` finds nothing to relocate), not merely rescued.

#: What `gh` is running when a card is moved between columns. The whole argv ends up inside
#: `TimeoutExpired`, and none of it — not the mutation, not the project's own field ids — carries a
#: shape the boundary knows.
_GH_MOVE = ["gh", "api", "graphql", "-f",
            'query=mutation{updateProjectV2ItemFieldValue(input:{projectId:"PVT_kwDOA",'
            'itemId:"PVTI_lADO",fieldId:"PVTSSF_lADO",'
            'value:{singleSelectOptionId:"f75ad846"}}){projectV2Item{id}}}']


class _SlowBoard:
    """The client's board, with `gh` timing out on ONE card — the ordinary partial failure.

    Injected at the production seam (`_given_board`), so the write goes through `_WatchedWrites`
    and the exception is re-raised exactly as it is in production."""

    def __init__(self, *, times_out: int) -> None:
        self.times_out = times_out
        self.moved: list[int] = []

    def add_item(self, *, issue_url):
        return True

    def set_column(self, *, issue, issue_url, name):
        if issue == self.times_out:
            raise subprocess.TimeoutExpired(cmd=_GH_MOVE, timeout=30)
        self.moved.append(issue)
        return True


def test_the_forges_own_argv_is_never_what_the_client_reads_about_the_queue(world, caplog):
    """An approver types "sim" on a staged queue proposal and one `gh` call times out.

    `promote` answered `detail=str(exc)[:160]`, and BOTH branches of the reply speak that field: the
    total failure is the whole message, and the partial one appends it under a pt-BR headline — so
    "1 não entraram:" continued into a shell argv carrying a GraphQL mutation and the board's own
    Status field id. The client runs an accounting firm.

    The boundary could not have saved it, and this test says so out loud: the sanitiser recognises
    machinery it has been shown, and an argv is not on that list."""
    mod, _ = world()
    board = _SlowBoard(times_out="513")
    mod._given_board = board

    with caplog.at_level(logging.WARNING):
        results = mod.promote([512, 513], actor=ADMIN)

    landed = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    assert [r.ref for r in landed] == ["#512"], "one slow card lost the one that moved"
    assert [r.ref for r in failed] == ["#513"] and board.moved == ["512"]

    detail = failed[0].detail
    for leak in ("gh", "graphql", "mutation", "PVTSSF", "PVT_kwDOA", "Command", "timed out"):
        assert leak not in detail, f"{leak!r} reached a business conversation: {detail}"
    assert client_safe_detail(detail, language="pt-BR") == (detail, ""), \
        "the sentence still needed the boundary to rescue it — it was not composed"
    assert jargon_in(detail) == [], detail

    raw = str(subprocess.TimeoutExpired(cmd=_GH_MOVE, timeout=30))
    assert client_safe_detail(raw, language="pt-BR") == (raw, ""), (
        "this assertion is the reason the fix is at the source: the boundary reads SHAPES, and it "
        "hands an argv straight through")
    assert "PVTSSF_lADO" in caplog.text and "OPENFACTORY_PRODUCT_WRITE_FAILED" in caplog.text, \
        "the diagnosis was dropped rather than relocated to where an operator reads it"


def test_a_throttled_board_never_answers_a_refinement_in_the_platforms_own_words(world, caplog):
    """`read_board`'s error is written for an operator and NAMES THE REPOSITORY. `refine` returned
    it as its detail, so on a throttled App quota — which this deployment lives with — the client's
    whole reply was "could not list the issues of AcmeCorp/acme-books".

    Its two siblings, `close_card` and `align_card`, already spoke a pt-BR sentence here. This is
    the one that was left behind, and all three now say it with one voice."""
    mod, _ = world()
    world.board.error = "could not list the issues of AcmeCorp/acme-books"

    with caplog.at_level(logging.WARNING):
        res = mod.refine(516, actor=ADMIN)

    assert res.ok is False
    assert "AcmeCorp/acme-books" not in res.detail
    assert "issues" not in res.detail and "could not" not in res.detail
    assert client_safe_detail(res.detail, language="pt-BR") == (res.detail, "")
    assert jargon_in(res.detail) == [], res.detail
    assert world.tracker.bodies == [], "a card was rewritten from a board nobody could read"
    assert "AcmeCorp/acme-books" in caplog.text, "the diagnosis reached nobody"

    assert mod.close_card(516, actor=ADMIN).detail == res.detail
    assert mod.align_card(516, requirement=6, actor=ADMIN).detail == res.detail


def test_no_failure_branch_builds_a_client_sentence_out_of_what_it_caught():
    """A GUARD, not a case — the next writer of a failure branch inherits the rule instead of
    rediscovering it, which is how nine sites came to leak while one was being repaired.

    Every `except` in this module reports through `_could_not`, which takes the sentence and the
    cause as SEPARATE arguments and renders only the first. TWO SHAPES ARE FORBIDDEN, and a guard
    that knew only the first would wave the original defect straight back in: a branch that builds
    its own `WriteResult` has the exception in scope and a `detail=` to put it in, and a branch that
    interpolates the exception into the SENTENCE it hands `_could_not` has done the same thing one
    layer in — `f"não consegui registrar ({exc})"` is how five of these sites actually leaked."""
    import ast
    from pathlib import Path

    import openfactory.product.module as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    built = [f"module.py:{call.lineno}"
             for handler in ast.walk(tree) if isinstance(handler, ast.ExceptHandler)
             for call in ast.walk(handler)
             if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "WriteResult"]
    assert not built, (
        "a failure branch composes its own result with the exception in scope:\n  "
        + "\n  ".join(built))

    #: Where a caught exception IS allowed to go. `log.*` and `exc_info` are the operator's copy;
    #: `cause=` is `_could_not`'s log-only argument; `self._tell` is `_WatchedWrites` reporting to
    #: the FACTORY's board, which is an operator surface and never the client's channel (ADR-0027).
    rendered = []
    for handler in (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)):
        if not handler.name:
            continue
        allowed: set[int] = set()
        for call in (c for c in ast.walk(handler) if isinstance(c, ast.Call)):
            fn = call.func
            to_operators = (isinstance(fn, ast.Attribute)
                            and ((isinstance(fn.value, ast.Name) and fn.value.id == "log")
                                 or fn.attr == "_tell"))
            if to_operators:
                allowed |= {id(x) for x in ast.walk(call)}
            for kw in call.keywords:
                if kw.arg in {"cause", "exc_info"}:
                    allowed |= {id(x) for x in ast.walk(kw.value)}
        rendered += [f"module.py:{n.lineno}" for n in ast.walk(handler)
                     if isinstance(n, ast.Name) and n.id == handler.name
                     and id(n) not in allowed]
    assert not rendered, (
        "a caught exception is rendered somewhere a client can read it — it may only be logged or "
        "passed as `cause`:\n  " + "\n  ".join(rendered))

    poison = str(subprocess.TimeoutExpired(cmd=_GH_MOVE, timeout=30))
    said = module._could_not("não consegui agora.", act="move a card", cause=poison, ref="#1")
    assert said.detail == "não consegui agora." and said.ok is False and said.ref == "#1"
    assert poison not in said.detail


def test_every_write_that_skips_the_gate_is_named_where_the_gate_is_declared():
    """The AUTHORITY block at the top of `module.py` lists the four writes that do not call
    `may_act` themselves. A fifth added without a line there is indistinguishable from a gate
    somebody forgot — which is the whole reason the list exists rather than the argument being left
    in each method.

    Reachability is transitive, because that is how the gate actually works: `break_down` writes
    through `file_issues`, and `file_issues` is where the allowlist is checked."""
    import ast
    from pathlib import Path

    import openfactory.product.module as module

    #: what changes something in the CLIENT's world — their board, their documentation repo.
    #: Anything else a method writes (the ledger, the factory's own impediments) is the platform
    #: keeping its own books and is nobody's to authorise.
    writes = {"create_ticket", "update_body", "comment", "close_ticket", "add_item", "set_column",
              "add_label", "remove_label", "set_assignees", "set_state",
              "propose_requirement", "accept_requirement", "drop_requirement", "record_fact",
              "propose_baseline"}

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == "ProductModule")
    calls: dict[str, set[str]] = {}
    writes_itself: dict[str, bool] = {}
    gates_itself: dict[str, bool] = {}
    for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef)):
        named, on_self = set(), set()
        for call in (c for c in ast.walk(fn) if isinstance(c, ast.Call)):
            if isinstance(call.func, ast.Name):
                named.add(call.func.id)
            elif isinstance(call.func, ast.Attribute):
                named.add(call.func.attr)
                if isinstance(call.func.value, ast.Name) and call.func.value.id == "self":
                    on_self.add(call.func.attr)
        calls[fn.name], writes_itself[fn.name] = on_self, bool(named & writes)
        gates_itself[fn.name] = "may_act" in named

    def reaches(name: str, prop: dict[str, bool], seen: set[str] | None = None) -> bool:
        seen = set() if seen is None else seen
        if name in seen or name not in prop:
            return False
        seen.add(name)
        return prop[name] or any(reaches(m, prop, seen) for m in calls.get(name, ()))

    ungated = sorted(n for n in calls
                     if not n.startswith("_")
                     and reaches(n, writes_itself) and not reaches(n, gates_itself))
    assert ungated, "the census found no writers at all — it has stopped measuring anything"
    undeclared = [n for n in ungated if n not in (module.__doc__ or "")]
    assert not undeclared, (
        "these change a client's board or documentation without asking `may_act`, and the "
        f"AUTHORITY block does not say on whose authority: {', '.join(undeclared)}")


def test_the_one_write_with_no_human_in_it_stays_inside_its_declared_boundary(world):
    """`repoint_orphans` is the single act in this module with nobody in the loop — hourly,
    `actor=""`, no staged proposal. That is deliberate and declared, and it holds only inside a
    boundary that must never widen:

        it changes WHICH REQUIREMENT A CARD CITES, and nothing else on the card
        it aims only at the successor THE CORPUS NAMES — it decides nothing, so it costs no model
        it takes no card and no requirement from its caller

    Widen any of the three and an unattended process is taking a decision in a client's name. The
    first is checked byte for byte over every card it touched, because "only the citation" is
    exactly the claim that would rot if a later author folded a criteria rewrite in here rather
    than into `align_card`, where a person confirms it."""
    import inspect

    from openfactory.product.module import _section_of, _section_re

    mod, harness = world()
    before = {n: t.body for n, t in world.board.tickets.items()}

    results = mod.repoint_orphans()

    assert results and world.tracker.bodies
    for ref, after in world.tracker.bodies:
        card = int(ref.lstrip("#"))
        was = before[card]
        assert _section_re("Source").sub("", after) == _section_re("Source").sub("", was), (
            f"the unattended repair changed more of #{card} than its citation")
        assert _section_of(after, "Source") != _section_of(was, "Source")

    assert harness.prompts == [], "an act nobody authorised asked a model what to do"
    assert set(inspect.signature(mod.repoint_orphans).parameters) == {"actor"}, (
        "the unattended repair now takes a target from its caller, so what it writes is no longer "
        "decided by the corpus alone")
