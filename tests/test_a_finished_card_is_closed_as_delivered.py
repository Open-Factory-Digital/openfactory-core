"""A card in Done is closed as what it is — delivered — and the refusal is only said where it is
true (#162).

#153 gave `card_close` the stage gate `card_edit` has, so a card the factory has taken up is not
closed from under its job. That gate read every column except `backlog` and `todo` as "a job may be
working on it right now", and Done is one of them. Driven on `main` at `219fb25`:

    Backlog       close ok=True
    TO-DO         close ok=True
    In progress   close ok=False | … a job may be working on it right now … Stop the job first
    In review     close ok=False
    Needs Action  close ok=False
    Done          close ok=False | … a job may be working on it right now … Stop the job first

For Done the sentence is not true and its remedy does not exist: the job has finished and there is
nothing to stop. It is also the state triage reports as `done-but-open` — *"close it, or move it
back if it is not actually done"* — so the platform asked for a close it refused.

AND LETTING IT THROUGH IS NOT ENOUGH. `card_close` closes with `delivered=False`, which is right
for an operator withdrawing a card and wrong for one that shipped: `triage.Ticket.delivered` reads
that word, and eleven cards closed as duplicates once came back downstream as completed work. The
mirror image — shipped work recorded as withdrawn — drops it from every account of what was
delivered. So the COLUMN decides the word, not the caller: nobody can record shipped work as
withdrawn by reaching for the only close verb the board has.

AND THE COLUMN IS NOT THE JOB (review of #191, measured 2026-09-20 by reading the workflow). The
same sentence stayed on `in_review` and `needs_action`, and it is not true there either. A card in
Needs Action often has NO job on it: the gather asks its question, parks the card and returns
`SKIPPED`, completing the workflow; an impediment deadline elapses and `_wait_operator` returns
the park untouched, completing it too. And where a job IS alive — the merge watch through review,
a park holding on `wait_condition` — `stop` refuses it by design (*"it is not stuck … answer it
with `merge`, `adjust` or `discard`"*), so the remedy the close named was one this platform
declines to perform. So the close asks the ENGINE, and only in the three columns where the board
says a job might be there: Done, Backlog and TO-DO never pay for it.

Each case drives the real action row over the real local board and reads the board's own record.
"""

from __future__ import annotations

import pytest

from openfactory.contracts import JobState


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """A registered local project whose board `project init` has already created."""
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    registry = ProjectRegistry()
    registry.add(Project(name="acme", repo_path=str(tmp_path),
                         tracker=ProviderRef(kind="local", repo="acme", options={})))
    project = registry.get("acme")
    LocalBoardSetup().create(project=project, owner="", title="acme", token=None)
    return project


@pytest.fixture
def tracker(deployment):
    from openfactory.adapters.tracker.registry import build_tracker

    return build_tracker(deployment)


def _act(name: str, **params):
    import asyncio

    from openfactory import actions

    who = actions.Actor(id="me", display="Me", via="panel", admin=True)
    return asyncio.run(actions.perform(name, by=who, **params))


def _card_in(deployment, tracker, column: str) -> str:
    from openfactory.adapters.board import build_board

    ref = tracker.create_ticket(title="Lock the statement", body="## Objective\n\nLock it\n")
    assert build_board(deployment).set_column(issue=ref, issue_url="", name=column), column
    return ref


class _Handle:
    """A job in the engine. `answers` are the `awaiting_*` queries every surface asks it."""

    def __init__(self, status=None, answers=None, missing=False):
        from openfactory.runtime.temporal.view import WorkflowExecutionStatus

        self._status = WorkflowExecutionStatus.RUNNING if status is None else status
        self._answers = answers or {}
        self._missing = missing
        self.id = "openfactory-acme-1"

    async def describe(self):
        if self._missing:
            raise RuntimeError("workflow not found")

        class D:
            status = self._status
        return D()

    async def query(self, name):
        return self._answers.get(name)


def _ended() -> _Handle:
    """A job the engine still has a record of, and which is no longer running."""
    from openfactory.runtime.temporal.view import WorkflowExecutionStatus

    return _Handle(status=WorkflowExecutionStatus.COMPLETED)


@pytest.fixture
def engine(monkeypatch):
    """Put a job (or no job, or no engine) behind the close, and count the times it is asked.

    The engine is doubled at `_connected`, the seam every action row in the catalogue resolves
    the durable engine through, so the row under test is the real one."""
    from openfactory.actions import catalog

    asked: list[str] = []

    def _put(handle=None, *, unreachable=False):
        class _Client:
            def get_workflow_handle(self, wf_id):
                asked.append(wf_id)
                return handle

        async def _connected():
            if unreachable:
                return None, catalog.refused(catalog.UNAVAILABLE,
                                             "the durable engine is not answering.")
            return _Client(), None

        monkeypatch.setattr(catalog, "_connected", _connected)
        return asked

    return _put


def _record(deployment, ref: str) -> tuple[str, str, str]:
    """`(state, closed_reason, column_key)` as the board's own table holds them."""
    from openfactory.adapters.board_db import connect
    from openfactory.contracts.refs import canonical_ref

    with connect() as conn:
        row = conn.execute(
            "SELECT state, closed_reason, column_key FROM cards WHERE project = ? AND ref = ?",
            (deployment.name, int(canonical_ref(ref)))).fetchone()
    return row["state"], row["closed_reason"] or "", row["column_key"]


# ── the vocabulary ──────────────────────────────────────────────────────────────────────────────

def test_the_columns_say_which_of_them_mean_FINISHED():
    """A named set beside `BEFORE_THE_FACTORY`, so no caller compares a column to a string."""
    from openfactory.adapters.board import columns

    assert columns.has_finished("done")
    assert [k for k in columns.BOARD_ORDER if columns.has_finished(k)] == ["done"]
    assert not columns.has_finished(""), "an unmapped column is *cannot tell*, not *finished*"
    # finished is a kind of started: the factory DID take the card up, which is why an edit of it
    # stays refused
    assert all(columns.has_started(k) for k in columns.AFTER_THE_FACTORY)


def test_a_job_may_be_running_in_exactly_the_three_columns_between():
    from openfactory.adapters.board import columns

    assert [k for k in columns.BOARD_ORDER if columns.may_be_running(k)] == [
        "in_progress", "in_review", "needs_action"]
    assert not columns.may_be_running("")


# ── the close ───────────────────────────────────────────────────────────────────────────────────

def test_a_card_in_DONE_is_closed_and_recorded_as_DELIVERED(deployment, tracker):
    ref = _card_in(deployment, tracker, "Done")

    out = _act("card_close", project="acme", issue=ref, reason="shipped last week, never closed")

    assert out.ok, out.message
    state, word, column = _record(deployment, ref)
    assert state == "closed"
    assert word == "completed", "shipped work was recorded as withdrawn"
    assert column == "done", "closing a finished card moved it off Done"
    assert any("never closed" in c.body for c in (tracker.comments(ref) or []))


def test_the_answer_says_it_was_closed_as_DELIVERED(deployment, tracker):
    """Two closes mean two things, and the person who clicked is told which one happened."""
    finished = _card_in(deployment, tracker, "Done")
    queued = _card_in(deployment, tracker, "TO-DO")

    shipped = _act("card_close", project="acme", issue=finished, reason="done")
    withdrawn = _act("card_close", project="acme", issue=queued, reason="not needed")

    assert "delivered" in shipped.message and shipped.data.get("delivered") is True
    assert "delivered" not in withdrawn.message and withdrawn.data.get("delivered") is False


@pytest.mark.parametrize("column", ["Backlog", "TO-DO"])
def test_a_card_nobody_took_up_is_still_closed_as_NOT_delivered(deployment, tracker, column):
    ref = _card_in(deployment, tracker, column)

    out = _act("card_close", project="acme", issue=ref, reason="asked for by mistake")

    assert out.ok, out.message
    assert _record(deployment, ref)[:2] == ("closed", "not_planned")


@pytest.mark.parametrize("column", ["In progress", "In review", "Needs Action"])
def test_where_a_job_IS_running_on_it_the_close_is_still_refused(deployment, tracker, engine,
                                                                 column):
    """A job in the engine, running and waiting on nobody — the one shape `stop` accepts, and the
    only one this sentence is true of."""
    engine(_Handle())
    ref = _card_in(deployment, tracker, column)

    out = _act("card_close", project="acme", issue=ref, reason="not needed")

    assert not out.ok and column in out.message and "`stop`" in out.message, out.message
    assert _record(deployment, ref)[0] == "open"


def test_the_refusal_about_a_running_job_is_never_said_of_a_finished_card(deployment, tracker):
    """The sentence this issue is named for: there is no job to stop on a card in Done."""
    ref = _card_in(deployment, tracker, "Done")

    out = _act("card_close", project="acme", issue=ref, reason="done")

    assert "may be working" not in out.message and "`stop`" not in out.message, out.message


def test_the_board_is_read_ONCE_for_the_refusal_and_for_the_word(deployment, tracker,
                                                                  monkeypatch):
    """On a hosted board each read is an API call — and two reads can disagree about a card that
    moved between them, refusing on one column and recording on another."""
    from openfactory.adapters.board.local import LocalBoard

    ref = _card_in(deployment, tracker, "Done")
    reads: list[int] = []
    real = LocalBoard.columns

    def _counted(self):
        reads.append(1)
        return real(self)

    monkeypatch.setattr(LocalBoard, "columns", _counted)

    out = _act("card_close", project="acme", issue=ref, reason="shipped")

    assert out.ok and len(reads) == 1, (out.message, len(reads))


def test_a_RENAMED_done_column_is_still_done(tmp_path, monkeypatch):
    """The key decides, never the name: a board that says `Concluído` maps it (C-14)."""
    from openfactory.actions import catalog

    class _Board:
        def columns(self):
            return {"7": "Concluído"}

    class _Tracker:
        options = {"columns": {"done": "Concluído"}}

    class _Project:
        name = "acme"
        tracker = _Tracker()

    stage = catalog._stage(_Project(), _Board(), "7")
    assert stage.key == "done" and not stage.cannot_tell
    assert catalog._stage_refusal(_Project(), _Board(), "7", act="close") == ""


# ── the column says a job MAY be on it; the engine says whether one IS (review of #191) ─────────

@pytest.mark.parametrize("column", ["In progress", "In review", "Needs Action"])
def test_a_card_whose_job_has_ENDED_is_closed_wherever_the_column_left_it(deployment, tracker,
                                                                          engine, column):
    """The defect #162 was filed for, in the columns it was not filed about. A card sits in Needs
    Action with no job on it in two reachable ways — the gather asks its question, parks the card
    and returns `SKIPPED`; an impediment deadline elapses and the park is returned untouched — and
    in both the refusal told a person to stop a job the engine does not have."""
    engine(_Handle(missing=True))
    ref = _card_in(deployment, tracker, column)

    out = _act("card_close", project="acme", issue=ref, reason="we are not doing this after all")

    assert out.ok, out.message
    assert "`stop`" not in out.message and "may be working" not in out.message, out.message
    assert _record(deployment, ref)[0] == "closed"


@pytest.mark.parametrize("column", ["In progress", "In review", "Needs Action"])
def test_a_card_the_factory_never_FINISHED_is_never_closed_as_delivered(deployment, tracker,
                                                                        engine, column):
    """The pin on the carve-out. `has_finished` decides one word and one word only, and widening
    `AFTER_THE_FACTORY` to cover a column a card can be parked in for ever would record work that
    never shipped as delivered — `triage.Ticket.delivered` reads it downstream."""
    engine(_ended())
    ref = _card_in(deployment, tracker, column)

    out = _act("card_close", project="acme", issue=ref, reason="withdrawn")

    assert out.ok, out.message
    assert _record(deployment, ref)[1] == "not_planned", "work that never shipped read as delivered"
    assert out.data.get("delivered") is False


@pytest.mark.parametrize("gate,payload,verb", [
    # The park: `_wait_operator` holds on `wait_condition`, and `stop` refuses a job at a gate.
    ("awaiting_action", {"kind": "impediment"}, "skip"),
    # The merge watch: alive for up to `merge_deadline_days`, and `stop` refuses this one too.
    ("awaiting_merge", {"pr_url": "https://f/1"}, "discard"),
    ("awaiting_approval", True, "Approve button"),
])
def test_a_job_WAITING_ON_A_PERSON_is_named_with_the_verb_that_answers_it(deployment, tracker,
                                                                          engine, gate, payload,
                                                                          verb):
    """`stop` itself refuses all three — *"it is not stuck … answer it with …"* — so a close that
    prescribed `stop` sent the reader to a row that would decline. The refusal now names the verb
    that does answer, read from the same table `stop` reads."""
    engine(_Handle(answers={gate: payload}))
    ref = _card_in(deployment, tracker, "Needs Action")

    out = _act("card_close", project="acme", issue=ref, reason="not needed")

    assert not out.ok and verb in out.message, out.message
    assert "`stop`" not in out.message, "it still prescribes the one verb this job would refuse"
    assert _record(deployment, ref)[0] == "open"


def test_an_engine_that_CANNOT_BE_ASKED_refuses_rather_than_closing(deployment, tracker, engine):
    """"I could not read" is not "there is none" — the tracker port's own rule. The gate fails in
    the direction that keeps a card on the board."""
    engine(unreachable=True)
    ref = _card_in(deployment, tracker, "In progress")

    out = _act("card_close", project="acme", issue=ref, reason="not needed")

    assert not out.ok and "engine" in out.message, out.message
    assert _record(deployment, ref)[0] == "open"


def test_a_board_that_could_not_be_READ_is_still_refused_about_the_board(deployment, tracker,
                                                                         engine, monkeypatch):
    """The engine is asked about the JOB, never about a card nobody can place. An unreadable board
    answering through a quiet engine would turn "I cannot tell where this card is" into a close."""
    from openfactory.adapters.board.local import LocalBoard

    asked = engine(_Handle(missing=True))
    ref = _card_in(deployment, tracker, "In progress")
    monkeypatch.setattr(LocalBoard, "columns", lambda self: None)

    out = _act("card_close", project="acme", issue=ref, reason="not needed")

    assert not out.ok and "could not be read" in out.message, out.message
    assert not asked, "the engine was asked about a card the board could not place"


@pytest.mark.parametrize("column", ["Done", "Backlog", "TO-DO"])
def test_the_engine_is_asked_ONLY_where_the_column_says_a_job_may_be_on_it(deployment, tracker,
                                                                           engine, column):
    """A withdraw and the close #162 opened stay one board read and no engine call — on a hosted
    deployment that is a network round trip on the commonest path there is."""
    asked = engine(_Handle())
    ref = _card_in(deployment, tracker, column)

    out = _act("card_close", project="acme", issue=ref, reason="done with it")

    assert out.ok, out.message
    assert not asked, f"closing from {column} asked the engine: {asked}"


# ── what it must not loosen ─────────────────────────────────────────────────────────────────────

def test_a_finished_card_is_still_NOT_edited(deployment, tracker):
    """The text a delivered card carries is the record of what was asked. The edit gate stays
    shut — and says why in words that are true of a finished card."""
    ref = _card_in(deployment, tracker, "Done")

    out = _act("card_edit", project="acme", issue=ref, title="renamed after the fact")

    assert not out.ok, out.message
    assert tracker.get_ticket(ref).title == "Lock the statement"
    assert "Done" in out.message
    assert "reads next" not in out.message, (
        "a finished card was told the factory will read a comment next — no job is coming")


def test_a_running_card_keeps_the_edit_refusal_it_had(deployment, tracker):
    ref = _card_in(deployment, tracker, "TO-DO")
    tracker.set_state(ref, JobState.IMPLEMENTING)

    out = _act("card_edit", project="acme", issue=ref, title="renamed")

    assert not out.ok and "it read at pickup" in out.message, out.message


def test_a_delivered_close_can_be_reopened_and_says_so_on_the_card(deployment, tracker):
    """The undo stays whole: the card comes back open, where the row puts a reopened card, with
    the record of the close still on its thread."""
    ref = _card_in(deployment, tracker, "Done")
    _act("card_close", project="acme", issue=ref, reason="shipped")

    out = _act("card_reopen", project="acme", issue=ref)

    assert out.ok, out.message
    state, word, _column = _record(deployment, ref)
    assert (state, word) == ("open", "")
    assert any("shipped" in c.body for c in (tracker.comments(ref) or []))


def test_a_row_that_takes_only_the_ports_two_arguments_is_still_closed(deployment, tracker,
                                                                        monkeypatch):
    """An add-on row written before `delivered` existed closes INTO done, which is the delivered
    reading already — so a finished card on it still closes. (It was the shipped Jira row until
    #203; every shipped row takes the keyword now, and `tracker.base.close_ticket` is what meets
    the ones in the field.)"""
    ref = _card_in(deployment, tracker, "Done")
    calls: list[tuple] = []

    def _two_args_only(self, ref, reason):
        calls.append((ref, reason))

    monkeypatch.setattr(type(tracker), "close_ticket", _two_args_only)

    out = _act("card_close", project="acme", issue=ref, reason="shipped")

    assert out.ok and len(calls) == 1, out.message


def test_and_a_WITHDRAWN_card_on_such_a_row_is_refused_by_name_and_stays_open(deployment, tracker,
                                                                             monkeypatch):
    """#203. The `except TypeError` fallback closed it with the word dropped — recorded as delivered
    work, which is the one thing this close exists not to say."""
    ref = _card_in(deployment, tracker, "TO-DO")
    calls: list[tuple] = []

    def _two_args_only(self, ref, reason):
        calls.append((ref, reason))

    monkeypatch.setattr(type(tracker), "close_ticket", _two_args_only)

    out = _act("card_close", project="acme", issue=ref, reason="asked for twice")

    assert not out.ok and calls == [], out.message
    assert "`delivered`" in out.message and "still open" in out.message
    assert _record(deployment, ref)[0] == "open"
