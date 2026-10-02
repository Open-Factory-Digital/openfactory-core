"""The card's door does exactly what its table says, and nothing else (ADR-0055 D2, D3, D5, D9).

DERIVED FROM THE TABLES, NOT RESTATED. For every event a slice has decided, the door is driven
against a double of every port and the calls it made are compared with the row of
`consequences` — so an event added without deciding what follows it fails, and so does a
consequence nobody applies. Every *(state, event)* pair is either driven through the door or
asserted refused with no write at all.

AND THE RECORD'S RULES, on a store that keeps it: the same event arriving again is answered from
its own row and never decided twice; a transition that lost the race for the card's next number
decides again against what the winner made true; the record is written before any effect; and the
sweep applies again only what failed on the card's LATEST transition — an older one's late effect
is superseded, never applied backwards.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pytest

from openfactory.lifecycle import record
from openfactory.lifecycle.card import transition
from openfactory.lifecycle.executor import SUPERSEDED, converge
from openfactory.lifecycle.ports import Seen
from openfactory.lifecycle.table import (
    ALLOWED,
    DECIDED,
    OBSERVED,
    ONLY_ON_A_CLOSED_CARD,
    CardEvent,
    Close,
    Column,
    Comment,
    Forget,
    Loops,
    Place,
    Preview,
    Remove,
    Reopen,
    State,
    Tell,
    allowed,
    consequences,
    name_of,
)
from openfactory.observability.metrics import InMemoryMetricsSink


class Project:
    name = "acme"
    language = "en"


@dataclass
class Ports:
    """A double of every port the door touches. `seen` is where the card is; `breaks` names the
    effects that raise; `calls` is every write, in order."""

    seen_as: Seen
    sink_: object = None
    breaks: set[str] = field(default_factory=set)
    calls: list[tuple] = field(default_factory=list)
    name: str = "acme"
    after_record: object = None

    def sink(self):
        if self.sink_ is None:
            raise record.Unrecordable("this double keeps no record")
        return self.sink_

    def seen(self, card):
        return self.seen_as

    def asked_in(self, card):
        return "dm:ana"

    def _do(self, what, *args):
        if what in self.breaks:
            raise RuntimeError(f"the {what} port is down")
        if self.after_record is not None:
            self.after_record(what)
        self.calls.append((what, *args))
        return f"{what} done"

    def column(self, card, key):
        return self._do("column", card, key)

    def place(self, card, key, *, name=""):
        return self._do("place", card, key)

    def close(self, card, *, delivered, note):
        return self._do("close", card, delivered, note)

    def remove(self, card, *, note, by, why):
        return self._do("remove", card, note, by, why)

    def reopen(self, card):
        return self._do("reopen", card)

    def comment(self, card, text):
        return self._do("comment", card, text)

    def loops(self, card, action, *, about=""):
        return self._do("loops", card, action)

    def tell(self, card, *, notice, event_id, title, removed, opened_by, conversation,
             pass_number=0):
        return self._do("tell", card, notice)

    def preview(self, card, *, action, by):
        return self._do("preview", card, action)

    def forget(self):
        return self._do("forget")

    def deliver_what_remains(self):
        self.calls.append(("deliver_what_remains",))


#: Which port call each effect is, and with what — so the comparison reads the table's argument.
def _call_of(effect, carried: bool):
    if isinstance(effect, Column):
        return ("column", effect.key)
    if isinstance(effect, Place):
        return ("place", effect.key)
    if isinstance(effect, Close):
        return ("close", effect.delivered)
    if isinstance(effect, Remove):
        return ("remove",)
    if isinstance(effect, Reopen):
        return ("reopen",)
    if isinstance(effect, Comment):
        return None if carried else ("comment",)
    if isinstance(effect, Loops):
        return ("loops", effect.action)
    if isinstance(effect, Tell):
        return ("tell", effect.notice)
    if isinstance(effect, Preview):
        return ("preview", effect.action)
    if isinstance(effect, Forget):
        return ("forget",)
    raise AssertionError(f"an effect this test cannot map: {effect!r}")


def _shape(call: tuple) -> tuple:
    """A call as `_call_of` spells it: the port, and the argument the table decides."""
    what = call[0]
    if what in ("column", "place", "loops", "tell", "preview"):
        return (what, call[2])
    if what == "close":
        return (what, call[2])
    return (what,)


def _a_state_it_happens_in(event: CardEvent) -> State | None:
    states = sorted(ALLOWED[event])
    return states[0] if states else None


def _drive(event, state, *, open_card=True, facts=None, ports=None, **kw):
    ports = ports or Ports(Seen(state=state, open=open_card, title="Monthly report"))
    moved = transition(Project(), "#12", event, by="ana", why="asked twice", facts=facts,
                       ports=ports, **kw)
    return moved, ports


# ── 1. derived from `consequences`: every decided event does its row, and only its row ─────────

@pytest.mark.parametrize("delivered", [False, True])
@pytest.mark.parametrize("event", sorted(DECIDED))
def test_every_decided_event_does_exactly_what_its_row_says(event, delivered):
    facts = {"delivered": delivered}
    open_card = event not in ONLY_ON_A_CLOSED_CARD
    moved, ports = _drive(event, _a_state_it_happens_in(event), open_card=open_card,
                          facts=facts)

    # the facts the door decided with — it adds where the card was (`before`)
    row = consequences(event, moved.facts)
    carried = any(isinstance(e, Close | Remove) for e in row)
    assert moved.ok, moved.refused
    assert [_shape(c) for c in ports.calls] == \
        [c for c in (_call_of(e, carried) for e in row) if c is not None]
    assert [name for name, _ in moved.effects] == [name_of(e) for e in row]
    assert all(outcome for _, outcome in moved.effects), "an effect with no outcome recorded"


def test_an_event_no_slice_has_decided_is_refused_everywhere_and_has_no_row():
    """D2's default: an event becomes possible only when somebody writes where it may happen and
    what follows it. A row of consequences for an event no state allows would be dead; an event a
    state allows with no row would be applied as nothing."""
    for event in CardEvent:
        if event in DECIDED:
            consequences(event, {})          # every decided event has a row
            continue
        assert ALLOWED[event] == frozenset(), event
        with pytest.raises(KeyError):
            consequences(event, {})


# ── 2. derived from `allowed`: every pair is driven, or refused with no write ───────────────────

@pytest.mark.parametrize("open_card", [True, False])
@pytest.mark.parametrize("state", [*State, None], ids=lambda s: getattr(s, "value", "unplaced"))
@pytest.mark.parametrize("event", list(CardEvent))
def test_every_state_and_event_is_either_driven_through_the_door_or_refused(event, state,
                                                                            open_card):
    moved, ports = _drive(event, state, open_card=open_card)

    if allowed(state, event, open_card=open_card) is None:
        assert moved.ok, moved.refused
        assert ports.calls, "an allowed transition that wrote nothing"
    else:
        assert not moved.ok and moved.refused, "a refused transition said nothing"
        assert ports.calls == [], f"a refused transition wrote {ports.calls}"
        assert "12" in moved.refused and "Nothing was changed" in moved.refused


def test_a_reopen_asks_for_the_closed_card_itself():
    """The defect the inventory found: `card_reopen` checked nothing, and on the local board a card
    in progress went back to Backlog. A finished card is `delivered` whether or not it is closed,
    so the tracker's own word decides."""
    assert allowed(State.DELIVERED, CardEvent.REOPENED, open_card=True) is not None
    assert allowed(State.DELIVERED, CardEvent.REOPENED, open_card=False) is None
    assert allowed(State.CLOSED, CardEvent.REOPENED, open_card=False) is None
    assert allowed(State.RUNNING, CardEvent.REOPENED, open_card=True) is not None


# ── 3. the rows the defects of #411 earned, by name ───────────────────────────────────────────

def test_the_five_consumers_the_defects_missed_are_each_in_the_rows():
    """#411's table, as the rows that end it: the snapshot (#393), the column (#409), the promise,
    the requester's conversation (#401) and the preview (#405)."""
    backlog = (CardEvent.DISCARDED, CardEvent.SKIPPED, CardEvent.STOPPED)
    gone = (CardEvent.WITHDRAWN, CardEvent.REMOVED)
    for event in DECIDED:
        assert Forget() in consequences(event, {}), f"{event}: the snapshot is not forgotten"
    for event in backlog:
        row = consequences(event, {})
        assert Column("backlog") in row, f"{event}: the card stays where it was (#409)"
        assert Tell("stopped_work") in row, f"{event}: the requester is not told (#401)"
        assert Preview("stop") in row, f"{event}: the preview runs until its TTL (#405)"
        assert not any(isinstance(e, Loops) for e in row), (
            f"{event}: work back in the backlog cancels the promise it still owes (D10)")
    for row in [consequences(e, {}) for e in gone] + [consequences(CardEvent.CLOSED, {})]:
        assert Loops("cancel") in row, "a card that is gone keeps its promise open for ever"
        assert Tell("will_not_be_built") in row and Preview("stop") in row
    delivered = consequences(CardEvent.CLOSED, {"delivered": True})
    assert not any(isinstance(e, Loops | Tell | Preview) for e in delivered), (
        "closing finished work cancels its promise or tells somebody it will not be built")
    assert Loops("restore") in consequences(CardEvent.REOPENED, {})


# ── 4. the record: recorded first, the same event once, a race decided again ──────────────────

def test_the_transition_is_recorded_before_any_effect_is_applied():
    sink = InMemoryMetricsSink()
    seen_in_record: list[int] = []
    ports = Ports(Seen(state=State.BACKLOG), sink_=sink)
    ports.after_record = lambda what: seen_in_record.append(
        len(record.read(sink, "acme", "12").rows))

    moved, _ = _drive(CardEvent.REMOVED, State.BACKLOG, ports=ports)

    assert moved.recorded and moved.seq == 1
    assert seen_in_record and set(seen_in_record) == {1}, (
        "an effect ran before the transition was in the record")


def test_the_same_event_arriving_again_is_answered_from_its_row_and_never_decided_twice():
    """A retried request carries its event id. By the time it arrives the card has moved, so
    deciding again would refuse a transition that in fact succeeded (D5, the event id first)."""
    sink = InMemoryMetricsSink()
    first, ports = _drive(CardEvent.REMOVED, State.BACKLOG, event_id="click-1",
                          ports=Ports(Seen(state=State.BACKLOG), sink_=sink))
    ports.seen_as = Seen(state=State.REMOVED)       # what the first one made true
    writes = len(ports.calls)

    again, _ = _drive(CardEvent.REMOVED, State.REMOVED, event_id="click-1", ports=ports)

    assert first.ok and again.ok and again.replayed, again.refused
    assert again.seq == first.seq and again.effects == first.effects
    assert len(ports.calls) == writes, "the same event was applied twice"
    assert len(record.read(sink, "acme", "12").rows) == 1


def test_a_transition_that_lost_the_race_for_the_cards_number_decides_again():
    """A person closes a card while somebody removes it. One of them takes the card's next number;
    the other reads the card again and is judged against what the winner made true — never applied
    beside it (D5, the sequence number second)."""
    sink = InMemoryMetricsSink()
    ports = Ports(Seen(state=State.BACKLOG), sink_=sink)
    real = sink.record_if_absent

    def the_other_one_first(rec, *, key):
        sink.record_if_absent = real
        winner = record.Row(card="12", seq=1, event_id="closed-elsewhere", event="closed",
                            by="bruno", effects=())
        record.write(sink, "acme", winner)
        ports.seen_as = Seen(state=State.CLOSED, open=False)
        return real(rec, key=key)

    sink.record_if_absent = the_other_one_first
    moved, _ = _drive(CardEvent.REMOVED, State.BACKLOG, ports=ports)

    assert not moved.ok and "closed" in moved.refused, moved
    assert ports.calls == [], "the loser applied its effects beside the winner's"
    assert [r.event for r in record.read(sink, "acme", "12").rows] == ["closed"]


def test_a_store_that_cannot_keep_the_record_is_named_and_the_decision_still_happens(caplog):
    caplog.set_level(logging.WARNING)
    moved, ports = _drive(CardEvent.WITHDRAWN, State.TODO,
                          ports=Ports(Seen(state=State.TODO), sink_=None, name="acme-norecord"))

    assert moved.ok and not moved.recorded
    assert ("close", "12", False) == ports.calls[0][:3]
    assert "OPENFACTORY_CARD_RECORD_REFUSED" in caplog.text


# ── 5. the sweep: converged, and never backwards ──────────────────────────────────────────────

def test_the_sweep_applies_again_what_failed_on_the_cards_latest_transition():
    sink = InMemoryMetricsSink()
    ports = Ports(Seen(state=State.TODO), sink_=sink, breaks={"tell"})
    moved, _ = _drive(CardEvent.WITHDRAWN, State.TODO, ports=ports)
    assert moved.outcome("tell").startswith("failed")

    ports.breaks = set()
    ports.calls.clear()
    said = converge(Project(), ports=ports)

    assert [c[0] for c in ports.calls] == ["tell"], ports.calls
    assert any("tell" in line for line in said)
    [row] = record.read(sink, "acme", "12").rows
    told = row.effects.index("tell:will_not_be_built")
    assert row.outcome(told) == "tell done" and row.attempts(told) == 2


def test_the_sweep_never_applies_an_older_transitions_late_effect():
    """A card withdrawn and then reopened by a person: the withdrawal's late column, comment or
    telling would undo what the person did since. It is marked superseded instead."""
    sink = InMemoryMetricsSink()
    ports = Ports(Seen(state=State.TODO), sink_=sink, breaks={"close"})
    _drive(CardEvent.WITHDRAWN, State.TODO, ports=ports)
    ports.breaks = set()
    ports.seen_as = Seen(state=State.CLOSED, open=False)
    _drive(CardEvent.REOPENED, State.CLOSED, open_card=False, ports=ports)

    ports.calls.clear()
    converge(Project(), ports=ports)

    assert ports.calls == [], f"the sweep applied an older transition's effect: {ports.calls}"
    older = record.read(sink, "acme", "12").rows[0]
    assert older.outcome(older.effects.index("close:false")) == SUPERSEDED


# ── 6. the store's conditional write, on the store that ships ─────────────────────────────────

def test_the_sqlite_store_refuses_the_second_writer_of_one_key_and_reads_a_prefix_in_order(
        tmp_path):
    from openfactory.observability.metrics import KeyedSink, MetricRecord
    from openfactory.observability.sqlite_metrics import SqliteMetricsSink

    sink = SqliteMetricsSink(tmp_path / "m.db")
    assert isinstance(sink, KeyedSink)

    def rec(n):
        return MetricRecord(project="acme", ticket="12", ts="2026-10-01T10:00:00+00:00",
                            kind="card_transition", extra={"n": n})

    assert sink.record_if_absent(rec(1), key="card#12#00000002") is True
    assert sink.record_if_absent(rec(2), key="card#12#00000002") is False
    assert sink.record_if_absent(rec(3), key="card#12#00000001") is True
    assert sink.record_if_absent(rec(4), key="card#120#00000001") is True
    got = sink.records_under("acme", "card#12#")
    assert [r["extra"]["n"] for r in got] == [3, 1], "a prefix read out of order, or too wide"


def test_the_rows_keep_what_the_boards_own_gates_refused():
    """The table mirrors what the board's gates answered before it existed (#384, #162), so moving
    a writer through the door refuses nothing a person could do and allows nothing they could not:
    a card the factory finished is never removed — what was done and said on it is history — and a
    card already closed is not closed, withdrawn or removed again."""
    for gone in (CardEvent.REMOVED, CardEvent.WITHDRAWN):
        assert allowed(State.DELIVERED, gone) is not None, f"{gone} of finished work"
        assert allowed(State.CLOSED, gone, open_card=False) is not None, f"{gone} of a closed card"
    assert allowed(State.CLOSED, CardEvent.CLOSED, open_card=False) is not None
    assert allowed(State.DELIVERED, CardEvent.CLOSED) is None, "a finished card closes, delivered"
    for before_pickup in (State.BACKLOG, State.TODO):
        assert allowed(before_pickup, CardEvent.REMOVED) is None
        assert allowed(before_pickup, CardEvent.DISCARDED) is not None, (
            "a card no job has is 'discarded' — there is no pull request to close")


def test_an_answer_moves_only_a_card_still_parked_on_its_question():
    """#413: the answer to a card's question returns it to the queue from the park the question put
    it in — never a card somebody already moved on, and never one that is gone, whose question
    closes as cancelled because nobody will pick the card up."""
    for parked in ("waiting_on_a_person", ""):
        row = consequences(CardEvent.QUESTION_ANSWERED, {"before": parked})
        assert Column("todo") in row and Loops("answer") in row, parked
    for moved_on in ("backlog", "todo", "running", "delivered"):
        row = consequences(CardEvent.QUESTION_ANSWERED, {"before": moved_on})
        assert not any(isinstance(e, Column) for e in row), f"{moved_on}: moved back"
        assert Loops("answer") in row
    for gone in ("closed", "removed"):
        assert consequences(CardEvent.QUESTION_ANSWERED, {"before": gone}) == (Loops("moot"),)


def test_a_decision_the_jobs_own_ending_already_carried_out_is_not_refused():
    """#413: a person's skip signals the job, and the job's settle can record before the row does.
    The row's decision then finds the card already where it would leave it: it stands, and nothing
    is applied twice — where it used to be refused for a skip the engine had in fact performed."""
    sink = InMemoryMetricsSink()
    ports = Ports(Seen(state=State.WAITING_ON_A_PERSON), sink_=sink)

    def the_job_settles_first():
        record.write(sink, "acme", record.Row(card="12", seq=1, event_id="settled-by-the-job",
                                              event="skipped", by="the workflow", effects=()))
        ports.seen_as = Seen(state=State.BACKLOG)
        return None

    moved, _ = _drive(CardEvent.SKIPPED, State.WAITING_ON_A_PERSON, ports=ports,
                      act=the_job_settles_first)

    assert moved.ok and not moved.refused, moved
    assert ports.calls == [], "the job's ending was applied a second time"


def test_every_adjust_pass_ends_the_way_the_first_did():
    """#448: when a pass ends, the preview shows the new head and its requester is told that this
    pass is theirs to try — the two things the live run found missing."""
    row = consequences(CardEvent.ADJUSTED, {})
    assert Preview("rebuild") in row, "the preview goes on showing the pass before"
    assert Tell("pass_ready") in row, "the requester never hears the pass is ready"


# ── 7. filing, the operator's two columns, and edits (#414) ───────────────────────────────────

def test_a_card_is_filed_and_moved_only_within_the_operators_two_columns():
    """Cards land in the backlog (ADR-0019 §5), and a person moves them between the backlog and the
    queue. A filing into a column the factory writes places nothing; a move out of a column a job
    holds the card in is refused — ending a job is `stop`, `skip` or `discard`, which tell it."""
    assert consequences(CardEvent.FILED, {}) == (Place("backlog"), Forget())
    assert consequences(CardEvent.FILED, {"column": "todo"})[0] == Place("todo")
    for factory in ("in_progress", "in_review", "needs_action", "done"):
        assert not any(isinstance(e, Place) for e in
                       consequences(CardEvent.FILED, {"column": factory})), factory
    assert consequences(CardEvent.FILED, {"column": ""}) == (Forget(),), (
        "a caller with no board was given a placement")
    for event in (CardEvent.PROMOTED, CardEvent.REORDERED, CardEvent.EDITED):
        for held in (State.RUNNING, State.DELIVERED, State.CLOSED):
            assert allowed(held, event, open_card=held is not State.CLOSED) is not None, (
                f"{event} of a card the factory holds or finished")
    assert allowed(State.WAITING_ON_A_PERSON, CardEvent.PROMOTED) is None, (
        "a parked card no job waits on can no longer be queued again by hand")
    assert allowed(State.WAITING_ON_A_PERSON, CardEvent.REORDERED) is not None
    assert allowed(State.WAITING_ON_A_PERSON, CardEvent.EDITED) is not None


def test_a_promotion_is_placed_and_says_nothing_and_an_edit_is_one_comment():
    assert consequences(CardEvent.PROMOTED, {}) == (Place("todo"), Forget())
    assert consequences(CardEvent.REORDERED, {}) == (Place("backlog"), Forget())
    assert consequences(CardEvent.EDITED, {}) == (Comment(), Forget())


# ── 8. a change made in the vendor's own interface (D8, #414) ─────────────────────────────────

_WRITES = ("column", "place", "close", "remove", "reopen", "comment")


@pytest.mark.parametrize("delivered", [False, True])
@pytest.mark.parametrize("event", sorted(DECIDED))
def test_an_observed_change_does_what_its_row_says_minus_the_writes_to_the_card(event,
                                                                               delivered):
    """Derived from the table, like the first: an observed event writes NOTHING to the card —
    the vendor's interface made that write — and everything else of its row happens."""
    was = _a_state_it_happens_in(event)
    ports = Ports(Seen(state=State.CLOSED, open=False, title="Monthly report"))
    moved = transition(Project(), "#12", event, by=OBSERVED, ports=ports,
                       facts={"delivered": delivered, "before": was.value if was else ""})

    assert moved.ok, moved.refused
    row = consequences(event, moved.facts)
    assert moved.facts["observed"] is True
    assert [_shape(c) for c in ports.calls] == [c for c in (_call_of(e, False) for e in row)
                                                if c is not None]
    assert not [c for c in ports.calls if c[0] in _WRITES], ports.calls


def test_a_closed_card_left_in_the_queue_is_filed_where_its_close_puts_it():
    """The one write an observed change makes: the BOARD following a close, from the pickup column
    only — what the stale-pickup healer did by hand (#413). On a row whose column is its status a
    closed card is never there, and moving it would reopen it."""
    gone = consequences(CardEvent.CLOSED, {"observed": True, "column": "todo"})
    assert gone[0] == Column("backlog") and Loops("cancel") in gone
    done = consequences(CardEvent.CLOSED, {"observed": True, "column": "todo", "delivered": True})
    assert done == (Column("done"), Forget())
    for elsewhere in ("backlog", "done", "in_progress", ""):
        row = consequences(CardEvent.CLOSED, {"observed": True, "column": elsewhere})
        assert not any(isinstance(e, Column) for e in row), elsewhere


def test_an_observed_change_is_judged_against_what_the_platform_last_knew():
    """The tracker already shows the change, so asked of it a close would be refused as the close
    of a closed card. The record's latest transition says where the card was — and a close the
    record already holds is not observed twice."""
    sink = InMemoryMetricsSink()
    ports = Ports(Seen(state=State.BACKLOG), sink_=sink)
    assert _drive(CardEvent.PROMOTED, State.BACKLOG, ports=ports)[0].ok

    ports.seen_as = Seen(state=State.CLOSED, open=False)      # closed on the vendor's screen
    ports.calls.clear()
    moved = transition(Project(), "#12", CardEvent.CLOSED, by=OBSERVED, ports=ports,
                       facts={"delivered": False})
    assert moved.ok and moved.before is State.TODO, moved
    assert ("loops", "12", "cancel") in ports.calls
    assert ("tell", "12", "will_not_be_built") in ports.calls
    assert [r.event for r in record.read(sink, "acme", "12").rows] == ["promoted", "closed"]

    ports.calls.clear()
    again = transition(Project(), "#12", CardEvent.CLOSED, by=OBSERVED, ports=ports,
                       facts={"delivered": False})
    assert not again.ok and ports.calls == [], "a close the record holds was observed twice"


def test_an_observed_reopen_is_judged_from_the_close_the_record_holds():
    sink = InMemoryMetricsSink()
    ports = Ports(Seen(state=State.BACKLOG), sink_=sink)
    record.write(sink, "acme", record.Row(card="12", seq=1, event_id="w", event="withdrawn",
                                          by="ana", before="backlog", after="closed"))

    moved = transition(Project(), "#12", CardEvent.REOPENED, by=OBSERVED, ports=ports)

    assert moved.ok and moved.before is State.CLOSED, moved
    assert ("loops", "12", "restore") in ports.calls
    assert not [c for c in ports.calls if c[0] in _WRITES], ports.calls
