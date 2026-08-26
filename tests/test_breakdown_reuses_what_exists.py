"""Breaking a requirement into work must NAME what the board already carries, never re-file it.

THE INCIDENT. Asked to break requirement 4 into tasks, the product role filed `#511` — an exact
duplicate of `#288` — two messages after having told the client, in writing, that "nenhum card novo
duplica isso". The client watched a promise break inside the same conversation that made it.

THE DIAGNOSIS ON THE TICKET WAS WRONG, and the wrong version is the more comfortable one: it said
the decomposition never sees the board. It does, and always did — `_board_section()` is part of
every prompt this role builds, titles included, 120 per column. Blindness would have been an easy
fix.

WHAT WAS ACTUALLY MISSING is worse and less visible: the task said "break this into issues", and the
answer shape held nothing but issues to CREATE. A model that recognised the duplicate perfectly had
no sentence available in which to say so — its only move was to emit the front, and the platform
filed every front it emitted. **A promise the output schema cannot express is one the system cannot
keep**, however good the model and however firm the prompt. That is the class this file guards, and
it is why the first test here is about a JSON field and not about intelligence.

WHY THE VERIFICATION IS ASYMMETRIC. `already_on_board` is a model's claim about a board, so it is
checked against the board we actually read. When it cannot be confirmed the work is FILED anyway:
a duplicate is visible on the board and closes in one click, while a front dropped on an unchecked
claim is invisible for ever and nobody ever learns it was owed. The two failures are not the same
size, so the guard must not be symmetric either.
"""

from __future__ import annotations

import inspect
import logging

from openfactory.contracts import AgentRunResult
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.product.config import ProductLink
from openfactory.product.corpus import Corpus, Requirement
from openfactory.product.loader import ProductContext
from openfactory.product.module import ProductModule
from openfactory.product.role import IssueDraft
from openfactory.product.triage import Ticket

DOCS = "acmecorp/acme-books-documentation"
ADMIN = "U0ADMIN"

#: the requirement that produced `#511`
REQ = Requirement(number=4, slug="portal", path="0004-portal.md",
                  title="Portal do cliente", status="accepted")


class _Harness:
    name = "recording"

    def __init__(self, answer="ok"):
        self.prompts: list[str] = []
        self.answer = answer

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.prompts.append(prompt)
        return AgentRunResult(ok=True, summary=self.answer)


class _Tracker:
    def __init__(self, *, comment_raises=False):
        self.created: list[str] = []
        self.comments: list[tuple[str, str]] = []
        self.comment_raises = comment_raises

    def find_ticket(self, *, title):
        return None

    def create_ticket(self, *, title, body):
        self.created.append(title)
        return f"#{900 + len(self.created)}"

    def comment(self, ref, body):
        if self.comment_raises:
            raise RuntimeError("secondary rate limit")
        self.comments.append((ref, body))


class _Board:
    def __init__(self):
        self.placed: list[tuple[int, str]] = []

    def add_item(self, *, issue_url):
        return True

    def set_column(self, *, issue, issue_url, name):
        self.placed.append((issue, name))
        return True


def _module(tmp_path, *, answer: str):
    ctx = ProductContext(
        link=ProductLink(active=True, docs_repo=DOCS, kind="ok", reason="fine"),
        corpus=Corpus(requirements=[REQ]),
        docs_path=str(tmp_path), docs_commit="abc123", requirements_dir="requirements")
    project = Project(name="books", repo_path="/work/books",
                      product=ProductConfig(docs_repo=DOCS, admins=[ADMIN]))
    h = _Harness(answer)
    return ProductModule(project, context=ctx, agent=h), h


def _with_board(mod, tickets: list[Ticket] | None, *, error: str = ""):
    """Point the module's ONE board read at a fixed board — the seam every caller here shares.

    Patched at `_read_board` rather than at `read_board` because that is the module's own seam and
    the thing this feature is specified against: `(tickets, error)`, where an error means the board
    is unknown rather than empty."""
    mod._read_board = lambda **_: ([] if tickets is None else list(tickets), error)  # noqa: SLF001
    return mod


#: what the model answers when it recognises the duplicate
_NAMES_288 = ('{"issues": [{"title": "Trocar a senha pelo portal", "objective": "o", '
              '"acceptance_criteria": ["c"], "already_on_board": 288}]}')

#: two fronts: one already carded, one genuinely new
_MIXED = ('{"issues": ['
          '{"title": "Trocar a senha pelo portal", "objective": "o", '
          '"acceptance_criteria": ["c"], "already_on_board": 288},'
          '{"title": "Exportar o extrato em CSV", "objective": "o", '
          '"acceptance_criteria": ["c"]}]}')

_OPEN_288 = [Ticket(number=288, title="Password reset from the portal", state="open",
                    column="Backlog")]


# ── 1. the shape that made the promise keepable at all ────────────────────────────────────────
def test_the_answer_shape_can_SAY_that_a_front_already_exists():
    """The root defect, guarded where it lived: in the schema, not in the model.

    Before this field the only expressible answer was "create it". No prompt wording and no model
    could have avoided `#511`, because the sentence "this already exists" did not exist."""
    draft = IssueDraft(title="t", already_on_board=288)
    assert draft.already_on_board == "288", "the model answered 288 as an int and it must arrive as the ref"

    from openfactory.product.role import _ISSUES_SCHEMA

    assert "already_on_board" in _ISSUES_SCHEMA, (
        "the field exists on the model but the model is never told it may use it — the promise is "
        "unkeepable again, one layer down")


def test_the_decomposition_is_TOLD_to_look_at_the_board_it_is_shown(tmp_path):
    """The board was always in this prompt; the instruction to use it was not."""
    mod, h = _module(tmp_path, answer=_MIXED)
    _with_board(mod, _OPEN_288)

    mod.file_issues(REQ, actor=ADMIN, tracker=_Tracker(), board=_Board())

    prompt = h.prompts[0]
    assert "#288" in prompt and "Password reset from the portal" in prompt, (
        "the card it must not duplicate is not in the prompt")
    assert "already_on_board" in prompt, "there is no instruction to reuse anything"
    assert "OUTCOMES, not titles" in prompt, (
        "the two cards that collided said the same thing in two languages — matching by title is "
        "the failure being fixed, so the prompt must say what to match on")


# ── 2. behaviour: the duplicate is not created ────────────────────────────────────────────────
def test_a_front_already_on_the_board_files_NOTHING(tmp_path):
    """The incident, driven through the production path."""
    mod, _ = _module(tmp_path, answer=_NAMES_288)
    _with_board(mod, _OPEN_288)
    tracker = _Tracker()

    results = mod.file_issues(REQ, actor=ADMIN, tracker=tracker, board=_Board())

    assert tracker.created == [], f"it filed the duplicate anyway: {tracker.created}"
    assert len(results) == 1
    assert results[0].ok is True and results[0].existed is True
    assert results[0].ref == "#288", results[0]


def test_the_reused_card_is_told_which_requirement_it_now_serves(tmp_path):
    """Reuse without the citation has the duplicate's own problem: the link exists in one chat
    message and nowhere a person opening the card will ever look."""
    mod, _ = _module(tmp_path, answer=_NAMES_288)
    _with_board(mod, _OPEN_288)
    tracker = _Tracker()

    mod.file_issues(REQ, actor=ADMIN, tracker=tracker, board=_Board())

    assert tracker.comments, "the card serves a requirement it does not mention"
    ref, body = tracker.comments[0]
    assert ref == "#288" and "REQ-0004" in body, tracker.comments


def test_a_refused_comment_does_not_turn_a_reuse_back_into_a_duplicate(tmp_path):
    """Best-effort is the CALLER's decision (adapters/tracker/base.py). Here the caller decides
    the annotation is a courtesy and the reuse is the act — a rate-limited comment must not undo
    the whole point of the feature."""
    mod, _ = _module(tmp_path, answer=_NAMES_288)
    _with_board(mod, _OPEN_288)
    tracker = _Tracker(comment_raises=True)

    results = mod.file_issues(REQ, actor=ADMIN, tracker=tracker, board=_Board())

    assert tracker.created == [], "a failed comment resurrected the duplicate"
    assert results[0].ref == "#288" and results[0].existed is True


def test_the_new_front_still_lands_while_the_known_one_is_reused(tmp_path):
    """The guard that proves the retreat must not become a system that files nothing."""
    mod, _ = _module(tmp_path, answer=_MIXED)
    _with_board(mod, _OPEN_288)
    tracker, board = _Tracker(), _Board()

    results = mod.file_issues(REQ, actor=ADMIN, tracker=tracker, board=board)

    assert tracker.created == ["Exportar o extrato em CSV"], tracker.created
    assert [r.ref for r in results] == ["#288", "#901"], results
    assert board.placed == [("901", "Backlog")], (
        "the reused card was re-placed, or the new one was not")


# ── 3. an unverifiable claim files the work — the asymmetry ───────────────────────────────────
def test_a_card_that_is_NOT_open_on_the_board_is_not_trusted(tmp_path, caplog):
    """A hallucinated number must not be able to delete a front of work.

    The direction is deliberate: file it. A duplicate is on the board where a person sees it; work
    dropped on an unchecked claim is invisible and nobody ever learns it was owed."""
    mod, _ = _module(tmp_path, answer=_NAMES_288)
    _with_board(mod, [Ticket(number=999, title="something else", state="open")])
    tracker = _Tracker()

    with caplog.at_level(logging.WARNING, logger="openfactory.product"):
        results = mod.file_issues(REQ, actor=ADMIN, tracker=tracker, board=_Board())

    assert tracker.created == ["Trocar a senha pelo portal"], (
        "a front of work was dropped on a claim about a card the board does not have")
    assert results[0].existed is False
    assert any("OPENFACTORY_PRODUCT_REUSE_UNKNOWN" in r.getMessage() for r in caplog.records)


def test_a_CLOSED_card_is_not_a_place_to_put_new_work(tmp_path):
    """`#288` closed means the work is over, not that this requirement is already served."""
    mod, _ = _module(tmp_path, answer=_NAMES_288)
    _with_board(mod, [Ticket(number=288, title="Password reset", state="closed",
                             state_reason="completed", column="Done")])
    tracker = _Tracker()

    mod.file_issues(REQ, actor=ADMIN, tracker=tracker, board=_Board())

    assert tracker.created == ["Trocar a senha pelo portal"], (
        "the front was hung on a closed card and will never be delivered")


def test_a_board_that_could_not_be_READ_confirms_nothing(tmp_path, caplog):
    """An unreadable board is not an empty one. Nothing can be verified against it, so nothing is
    dropped on the strength of a claim about it — and the log says which state this was."""
    mod, _ = _module(tmp_path, answer=_NAMES_288)
    _with_board(mod, None, error="the board could not be read")
    tracker = _Tracker()

    with caplog.at_level(logging.WARNING, logger="openfactory.product"):
        mod.file_issues(REQ, actor=ADMIN, tracker=tracker, board=_Board())

    assert tracker.created == ["Trocar a senha pelo portal"], (
        "work was dropped on a claim about a board nobody could read")
    assert any("OPENFACTORY_PRODUCT_REUSE_UNVERIFIED" in r.getMessage() for r in caplog.records)


def test_an_EMPTY_board_is_vouched_for_and_an_unreadable_one_is_not(tmp_path):
    """The two states that a single falsy value would have merged. An empty board is knowledge:
    nothing exists, so every front is new — and that is a different sentence from "I don't know"."""
    mod, _ = _module(tmp_path, answer=_NAMES_288)
    _with_board(mod, [])
    tracker = _Tracker()

    mod.file_issues(REQ, actor=ADMIN, tracker=tracker, board=_Board())

    assert tracker.created == ["Trocar a senha pelo portal"]


# ── 4. reachability: the production path, not a path a test invented ──────────────────────────
def test_file_issues_is_the_ONLY_caller_and_it_passes_what_it_read():
    """THIS REPO'S SIGNATURE DEFECT, guarded rather than hoped about: built, tested, reached by
    nothing (14 instances and counting). `_file_one` could grow a perfect verification that
    production never hands an argument to, and every behaviour test above would still pass if they
    called `_file_one` directly — which is exactly why they do not.

    Read off the source: `known_open` must be produced by `file_issues` and threaded into the call,
    and it must default to `None` (unverifiable) so a caller added next month cannot silently opt
    into trusting a model's claim by forgetting an argument."""
    src = inspect.getsource(ProductModule.file_issues)
    assert "known_open=known_open" in src, (
        "file_issues does not pass the board it read to the filing — the verification is "
        "unreachable from production")
    assert "self._read_board()" in src, "file_issues never reads the board it must verify against"

    sig = inspect.signature(ProductModule._file_one)
    assert sig.parameters["known_open"].default is None, (
        "the default is not the unverifiable one, so forgetting the argument silently trusts the "
        "model instead of refusing to")

    from openfactory.product import module as m

    callers = [line for line in inspect.getsource(m).splitlines() if "_file_one(" in line
               and "def _file_one" not in line]
    assert len(callers) == 1, f"another caller appeared and was not audited: {callers}"


def test_the_check_verifies_the_SAME_board_the_role_was_shown(tmp_path):
    """The two must not be allowed to disagree. If the prompt lists `#288` and the verification is
    derived from a different read, the role names a card it was shown and the filing calls it
    unknown — the duplicate comes back through the fix that was meant to stop it."""
    mod, h = _module(tmp_path, answer=_NAMES_288)
    reads: list[int] = []

    def _one_board(**_):
        reads.append(1)
        return list(_OPEN_288), ""

    mod._read_board = _one_board  # noqa: SLF001
    tracker = _Tracker()

    mod.file_issues(REQ, actor=ADMIN, tracker=tracker, board=_Board())

    assert "#288" in h.prompts[0], "the prompt did not list the card"
    assert tracker.created == [], "the filing did not recognise the card the prompt listed"
    assert len(reads) == 1, (
        f"the board was read {len(reads)}× for one breakdown — the quota is shared with the "
        f"poller and every job, and two reads can also disagree")
