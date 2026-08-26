""""Not paused" is a setting. "Fires every three minutes" is a fact (#140).

The panel's job is to answer one question — *will the next card in TO-DO be picked up?* — and until
now it answered it from a switch. `intake()` read `.schedule.state.paused` and threw away
everything else `describe()` had already returned, so:

  * the page HARD-CODED "(scanned every 3 min)". An operator who turned that dial in the Temporal
    UI during an incident — which `ensure_poller`'s own docstring protects as a live operational
    lever — got a screen that went on quoting the old number.
  * a schedule that was switched on and had **stopped firing** read exactly like a healthy one.
    Nothing anywhere could tell them apart, on the surface whose entire purpose is telling them
    apart.

Measured on the live pilot, from the SAME `describe()` call that was already being paid for:

    recent_actions    10   (last fired 22:06:00)
    next_action_times [22:09:00, 22:12:00]
    interval          0:03:00
    num_actions       2454

THE HONESTY CEILING, and every reader of these fields inherits it: `recent_actions` proves a tick
FIRED — that the poll workflow was STARTED. It does not prove a scan COMPLETED. A dead worker
leaves the schedule firing happily into an empty task queue. So the copy downstream may say "the
poller last fired X ago" and may never say "the last scan completed".

SECONDS ARE COMPUTED ON THE SERVER. The browser's clock is not the deployment's: a laptop four
minutes fast reads a healthy three-minute poller as stalled, and a slow one reads a dead poller as
fresh — the reassuring direction, which is the one that costs something.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from openfactory.runtime.temporal import view as tv

UNREAD = ("fired_ago_s", "next_in_s", "every_s", "num_actions", "running_now", "created_ago_s")


class _Action:
    def __init__(self, scheduled_at=None, started_at=None):
        self.scheduled_at, self.started_at = scheduled_at, started_at


class _Info:
    def __init__(self, *, recent=(), nxt=(), num=0, running=(), created=None):
        self.recent_actions = list(recent)
        self.next_action_times = list(nxt)
        self.num_actions = num
        self.running_actions = list(running)
        self.created_at = created


class _Spec:
    def __init__(self, every=None):
        self.intervals = [type("I", (), {"every": every})()] if every else []


def _cad(info=None, spec=None):
    unread = dict.fromkeys([*UNREAD, "fired_at", "next_at"])
    return tv._cadence(info, spec, unread)


# ── 1. what the schedule actually says ──────────────────────────────────────────────────────────

def test_the_last_tick_and_the_next_one_are_reported_in_SECONDS():
    now = datetime.now(UTC)
    got = _cad(_Info(recent=[_Action(scheduled_at=now - timedelta(minutes=2))],
                     nxt=[now + timedelta(minutes=1)], num=2454),
               _Spec(every=timedelta(minutes=3)))

    assert 110 <= got["fired_ago_s"] <= 130, got
    assert 50 <= got["next_in_s"] <= 70, got
    assert got["every_s"] == 180.0, "the schedule's own interval is not reported"
    assert got["num_actions"] == 2454


def test_the_interval_comes_from_the_SCHEDULE_and_is_not_a_literal():
    """The panel said "every 3 min" in prose. An operator who turned the dial got a screen that
    kept quoting the old number — and `ensure_poller` deliberately never overwrites that dial at
    boot, precisely because somebody may have turned it during an incident."""
    assert _cad(_Info(), _Spec(every=timedelta(minutes=17)))["every_s"] == 1020.0


def test_a_TICK_ALREADY_DUE_reports_a_NEGATIVE_wait_rather_than_zero():
    """The one number here that must not be clamped. A next action in the past is exactly the
    signal that nobody is servicing this schedule; flooring it at zero renders a dead poller as
    one that is about to fire."""
    now = datetime.now(UTC)
    got = _cad(_Info(nxt=[now - timedelta(minutes=9)]), _Spec(every=timedelta(minutes=3)))

    assert got["next_in_s"] < -500, f"an overdue tick reads as {got['next_in_s']}"


def test_a_CLOCK_THAT_DISAGREES_never_produces_a_tick_that_fired_in_the_future():
    """`fired_ago_s` IS clamped, for the opposite reason: a negative age is not a signal about the
    schedule, it is two clocks disagreeing, and a caller computing with it gets nonsense."""
    got = _cad(_Info(recent=[_Action(scheduled_at=datetime.now(UTC) + timedelta(minutes=5))]),
               _Spec(every=timedelta(minutes=3)))

    assert got["fired_ago_s"] == 0.0, got


def test_the_tick_it_BELONGS_to_wins_over_the_moment_a_worker_took_it():
    """`scheduled_at` is the cadence question. `started_at` can lag it by however long the task
    queue was backed up, which would make a healthy schedule look late."""
    now = datetime.now(UTC)
    got = _cad(_Info(recent=[_Action(scheduled_at=now - timedelta(minutes=3),
                                     started_at=now - timedelta(seconds=5))]),
               _Spec(every=timedelta(minutes=3)))

    assert got["fired_ago_s"] > 120, "the pickup time was reported as the tick time"


def test_a_tick_with_ONLY_a_start_time_still_counts():
    """The fallback. Some server versions fill one and not the other, and refusing to answer at
    all would demote a healthy poller to unknown on a technicality."""
    got = _cad(_Info(recent=[_Action(started_at=datetime.now(UTC) - timedelta(minutes=1))]),
               _Spec(every=timedelta(minutes=3)))

    assert got["fired_ago_s"] is not None and got["fired_ago_s"] > 30


def test_the_LATEST_tick_is_reported_not_the_first_in_the_list():
    """`recent_actions` ordering is the server's business, not ours. Taking `[0]` or `[-1]` would
    make this correct by luck."""
    now = datetime.now(UTC)
    got = _cad(_Info(recent=[_Action(scheduled_at=now - timedelta(minutes=30)),
                             _Action(scheduled_at=now - timedelta(minutes=1)),
                             _Action(scheduled_at=now - timedelta(minutes=15))]),
               _Spec(every=timedelta(minutes=3)))

    assert got["fired_ago_s"] < 120, f"an older tick was reported as the last one: {got}"


# ── 2. not told is its own answer ───────────────────────────────────────────────────────────────

def test_a_server_that_says_NOTHING_about_cadence_answers_None_and_not_zero():
    """Every double in this suite, and an older Temporal server, expose `.schedule.state` alone.
    Zero would read as "it has never fired" — a claim — where the truth is "nobody told us"."""
    got = _cad(None, None)
    assert all(got[k] is None for k in UNREAD), got


def test_a_schedule_that_has_NEVER_FIRED_is_not_the_same_as_one_we_could_not_read():
    """A freshly created schedule genuinely has no recent actions. It must be distinguishable from
    an unreadable one, or every new deployment reads as broken for its first three minutes."""
    now = datetime.now(UTC)
    got = _cad(_Info(recent=[], nxt=[now + timedelta(minutes=2)], num=0,
                     created=now - timedelta(seconds=40)),
               _Spec(every=timedelta(minutes=3)))

    assert got["fired_ago_s"] is None, "a schedule that never fired invented a last tick"
    assert got["num_actions"] == 0, "…and cannot be told apart from one that has"
    assert got["created_ago_s"] is not None and got["created_ago_s"] > 30
    assert got["next_in_s"] > 0, "…and the engine has queued its first tick"


def test_a_MISSING_HALF_does_not_take_the_other_half_down():
    """Info without spec and spec without info both happen across server versions."""
    now = datetime.now(UTC)
    only_info = _cad(_Info(recent=[_Action(scheduled_at=now)], num=3), None)
    only_spec = _cad(None, _Spec(every=timedelta(minutes=3)))

    assert only_info["fired_ago_s"] is not None and only_info["every_s"] is None
    assert only_spec["every_s"] == 180.0 and only_spec["fired_ago_s"] is None


# ── 3. the switch survives everything above ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_BROKEN_CADENCE_READ_never_costs_the_switch_answer(monkeypatch):
    """The load-bearing separation. Whether pickup is on is the answer the floor cannot do
    without; the cadence is an enrichment. A schedule object whose `.info` blows up must still
    yield `on`, or a server-version difference silently turns every floor to Unknown."""
    monkeypatch.setattr(tv, "_watcher_schedule_ids", lambda: [])

    class _Exploding:
        @property
        def info(self):
            raise RuntimeError("this server does not do that")

        schedule = type("S", (), {"state": type("St", (), {"paused": False, "note": ""})(),
                                  "spec": None})()

    class _Client:
        def get_schedule_handle(self, _id):
            return type("H", (), {"describe": staticmethod(
                lambda: __import__("asyncio").sleep(0, result=_Exploding()))})()

    got = await tv.intake(_Client())
    assert got["known"] is True and got["on"] is True, got
    assert got["fired_ago_s"] is None, "a cadence that could not be read answered anyway"


def test_the_COPY_CEILING_is_written_where_the_next_reader_will_look():
    """`recent_actions` proves a tick fired, never that a scan completed — a dead worker leaves the
    schedule firing into an empty queue. That distinction is the whole difference between an
    honest `Armed` and a reassuring lie, so it lives in the docstring a reader lands on."""
    doc = (inspect.getdoc(tv.intake) or "") + (inspect.getdoc(tv._cadence) or "")
    assert "COMPLETED" in doc.upper() and "FIRED" in doc.upper(), (
        "nothing warns the next reader that a fired tick is not a completed scan")


def test_it_REACHES_the_panel():
    """Reachability, the defect class this repository has paid for sixteen times. The fields are
    decoration unless the payload the page reads carries them."""
    from openfactory.api import app as api

    src = inspect.getsource(api.temporal_stream) + inspect.getsource(api.temporal_jobs)
    assert src.count("tv.intake(client)") >= 2, (
        "the cadence is computed and reaches at most one of the two payloads the panel reads")
