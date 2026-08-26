"""The tech-lead and the panel disagreed about the same job, out loud, in a client's Slack (#146).

MEASURED, on one job at one instant — a park on a usage limit, four hours old, due to resume by
itself in twenty-five minutes:

    the panel      Waiting on a clock — acme #7 is parked on a usage limit —
                   it retries by itself at 22:25          ← nobody is needed
    the tech-lead  stopped 4h ago, waiting on a decision from you.
                   I need you: … Reply `resume` and I will try again…

So the tech-lead summoned a human for a job the engine was about to resume on its own, and asked
them to type the very thing it was about to do. On the surface being sold as an integration.

WHY IT HAPPENED, and it is not carelessness. `watch()` predates `wakes_at`: until #140 no park
could say when it woke, so patience had to be measured in hours-since-parked and a cause the
classifier could not name had to escalate. The engine learned the answer and the narrator was
never told — two ladders over the same facts, exactly the defect #141 removed inside the panel and
#144 removed between the panel and the platform, one layer further out.

WHAT MUST NOT CHANGE, and this file exists to hold it while the classification moves:

    the voice        `report()` and `voice.py`, in the project's language. The client reads this.
    the dampening    `worth_saying`'s REPEAT_AFTER — without it the tech-lead is a spammer.
    the patience     a park younger than STUCK_PARK_HOURS is still left alone.
    the gate rule    a pull request waiting overnight is `at_a_gate`, never wedged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from openfactory.techlead import voice
from openfactory.techlead.watch import (
    IDLE,
    RECURRING,
    REPEAT_AFTER,
    STUCK,
    WAITING,
    AtAGate,
    FloorState,
    Parked,
    report,
    watch,
    worth_saying,
)

NOW = datetime(2026, 8, 19, 22, 0, tzinfo=UTC)


def _floor(**over) -> FloorState:
    base = {"parked": [], "running": 0, "queued": [], "idle_minutes": 0.0,
            "long_running": [], "at_a_gate": [], "recent_causes": {}}
    base.update(over)
    return FloorState(**base)


def _in(minutes: int) -> str:
    return (NOW + timedelta(minutes=minutes)).isoformat()


# ── 1. the voice, locked before anything moves ──────────────────────────────────────────────────

@pytest.mark.parametrize("language", [None, "en", "pt-BR"])
def test_every_finding_still_SAYS_something_and_says_what_happens_next(language):
    """The floor of the tech-lead's usefulness, in every language it speaks: a finding with no
    sentence is a notification, and a sentence with no next step is a complaint."""
    found = watch(_floor(
        parked=[Parked(ticket="1", hours=9.0, note="boom")],
        long_running=[("2", 14.0)],
        at_a_gate=[AtAGate(ticket="3", hours=20.0, gate="merge")],
        running=0, queued=["4"], idle_minutes=45.0,
        recent_causes={"flaky network": 4}), language=language)

    assert found, "the tech-lead went silent on a floor with four different problems"
    for f in found:
        assert f.detail.strip(), f"{f.kind} has no sentence at all"
        assert f.action.strip(), f"{f.kind} says what is wrong and not what happens next"


def test_the_PROJECTS_LANGUAGE_is_what_it_speaks():
    """The factory speaking FIRST, on a schedule nobody asked for — so it uses the project's
    configured language, never a question's (#124). This is the half a client reads."""
    en = watch(_floor(long_running=[("7", 14.0)]), language="en")[0]
    pt = watch(_floor(long_running=[("7", 14.0)]), language="pt-BR")[0]

    assert en.detail != pt.detail, "the two languages produce the same sentence"
    assert en.detail == voice.say(voice.FINDING, "wedged.detail", "en", hours=14.0)
    assert pt.detail == voice.say(voice.FINDING, "wedged.detail", "pt-BR", hours=14.0)


def test_the_REPORT_still_renders_in_both_languages():
    """`report()` is the whole message, not a finding. It is what lands in the channel."""
    found = watch(_floor(parked=[Parked(ticket="9", hours=5.0, note="boom")]), language="pt-BR")
    text = report(found, agent_name="tech-lead", language="pt-BR")

    assert text.strip(), "the round produced findings and said nothing"
    assert "9" in text, "the message does not name the ticket it is about"


# ── 2. the dampening, which is what keeps it from becoming noise ────────────────────────────────

def test_an_UNCHANGED_situation_is_not_restated_every_round():
    """Not a mute button: a park nobody answers is said again, later, with the new number. The
    point is that an unchanged situation restated on the hour trains everybody to skim past the
    channel — and the one hour that matters is the one they skim."""
    found = watch(_floor(parked=[Parked(ticket="1", hours=5.0, note="boom")]))
    first, said = worth_saying(found, {})
    assert first, "nothing was said the first time"

    again, _ = worth_saying(found, said)
    assert not again, "the same unchanged finding was announced twice in a row"


def test_the_per_kind_patience_survives():
    """A gate doing its job is news once a shift, not once an hour; a recurring cause is the
    opposite. These numbers ARE the behaviour."""
    assert REPEAT_AFTER[WAITING] > REPEAT_AFTER[STUCK] > REPEAT_AFTER[RECURRING]
    assert REPEAT_AFTER[IDLE] >= 60.0


# ── 3. the patience and the gate rule ───────────────────────────────────────────────────────────

def test_a_park_that_JUST_happened_is_left_alone():
    assert watch(_floor(parked=[Parked(ticket="1", hours=0.5, note="boom")])) == []


def test_a_PULL_REQUEST_waiting_overnight_is_a_GATE_and_never_wedged():
    """The diversion that must survive: a PR waiting for a human all night is the system working.
    Calling it wedged would send somebody to terminate a job doing exactly what it should."""
    found = watch(_floor(at_a_gate=[AtAGate(ticket="7", hours=14.0, gate="merge")]))

    assert [f.kind for f in found] == [WAITING], found


def test_an_ARMED_AUTO_MERGE_gets_the_wedged_jobs_patience_and_its_own_sentence():
    """A build is not a person. Chasing somebody about an auto-merge after eight hours is the same
    false alarm wearing a smaller hat."""
    assert watch(_floor(at_a_gate=[AtAGate(ticket="7", hours=9.0, gate="ci")])) == []
    late = watch(_floor(at_a_gate=[AtAGate(ticket="7", hours=14.0, gate="ci")]))
    assert [f.kind for f in late] == [WAITING]


# ── 4. THE DEFECT: a self-clearing wait is not a person's problem ───────────────────────────────

def test_a_park_that_WAKES_BY_ITSELF_is_not_announced_as_stuck():
    """THE MEASURED CASE. Four hours parked on a usage limit, twenty-five minutes from resuming on
    its own — and the tech-lead asked a human to type `resume`, which is what the engine was about
    to do. The panel, given the same job, said "it retries by itself at 22:25"."""
    found = watch(_floor(parked=[Parked(ticket="7", hours=4.0, note="usage limit",
                                        kind="rate_limit", wakes_at=_in(25))]), now=NOW)

    assert found == [], (
        f"the tech-lead summoned a human for a job the engine resumes in 25 minutes: {found}")


def test_a_park_PAST_its_own_deadline_is_still_announced():
    """The positive twin, and the one that decides whether this is safe. A park that promised to
    wake and did not is precisely what a human must hear about — silence there would turn a
    self-clearing wait into a silent forever-wait."""
    found = watch(_floor(parked=[Parked(ticket="7", hours=4.0, note="usage limit",
                                        kind="rate_limit", wakes_at=_in(-90))]), now=NOW)

    assert [f.kind for f in found] == [STUCK], found
    assert found[0].detail.strip() and found[0].action.strip()


def test_a_park_with_NO_deadline_is_announced_exactly_as_before():
    """Most parks carry no wake-up: an impediment holds until somebody answers. Nothing about
    those changes, which is what keeps this a narrowing rather than a rewrite."""
    found = watch(_floor(parked=[Parked(ticket="7", hours=5.0, note="boom")]), now=NOW)
    assert [f.kind for f in found] == [STUCK]


def test_the_two_LADDERS_agree_about_one_job():
    """The claim the whole card is about, asserted as an equivalence rather than as two separate
    behaviours: whatever the panel calls a self-clearing wait, the tech-lead stays quiet about —
    and whatever the panel calls a person's problem, the tech-lead speaks up about."""
    from openfactory import floor

    for minutes, panel_word, should_speak in ((25, "Waiting on a clock", False),
                                              (-90, "Needs you", True)):
        job = {"project": "acme", "issue": "7", "status": "running", "wedged": False,
               "action": {"kind": "rate_limit", "note": "usage limit", "wakes_at": _in(minutes)}}
        seen = floor.state(floor.FloorInputs(jobs=[job], connected=True, engine_address="e",
                                             inbox=[], now=NOW), "acme")
        heard = watch(_floor(parked=[Parked(ticket="7", hours=4.0, note="usage limit",
                                            kind="rate_limit", wakes_at=_in(minutes))]), now=NOW)

        assert seen.word == panel_word, f"the panel says {seen.word!r}, expected {panel_word!r}"
        assert bool(heard) is should_speak, (
            f"the panel says {seen.word!r} and the tech-lead "
            f"{'speaks' if heard else 'stays quiet'} — they disagree about one job")


def test_the_FIELD_ACTUALLY_TRAVELS_from_the_workflow_to_the_rounds():
    """REACHABILITY, the defect class this repository has paid for sixteen times: the rule can be
    perfect and the field never arrive. The workflow has stamped `wakes_at` on every park since
    #140 and the rounds read it for the first time here — a gap that existed precisely because
    nobody asserted the chain, only its ends."""
    import inspect

    from openfactory.runtime.temporal import activities, workflow

    assert '"wakes_at"' in inspect.getsource(workflow.JobWorkflow._wait_operator), (
        "the engine no longer records when it will resume a park")
    assert 'wakes_at=str(state.get("wakes_at")' in inspect.getsource(activities), (
        "the rounds build a Parked without the deadline, so the shared rule is asked about "
        "nothing and every park escalates on hours alone again")
    assert "wakes_at" in Parked.__dataclass_fields__


def test_the_PANEL_asks_the_shared_rule_rather_than_a_copy_of_it():
    """Two implementations that agree today are two implementations. `is_overdue` must DELEGATE —
    a re-implementation beside it is how these two drifted while both looked correct."""
    import inspect

    from openfactory.floor.ladder import is_overdue

    assert "wait_is_over(" in inspect.getsource(is_overdue), (
        "the panel carries its own copy of the rule again")


def test_a_RATE_LIMIT_park_with_no_deadline_is_still_the_engines_business():
    """A park that carries no wake-up is a person's problem — EXCEPT a rate-limit one, which the
    engine always resumes. Dropping that distinction turns every unstamped rate-limit park (every
    job parked before this shipped) into an alarm on the first round after a deploy."""
    from openfactory.floor.ladder import wait_is_over

    assert wait_is_over(None, "rate_limit", NOW) is False
    assert wait_is_over(None, "impediment", NOW) is True


def test_the_GRACE_after_a_deadline_is_real():
    """A wait is not late the instant it is due. Clocks disagree, a worker takes a moment to pick
    the timer up, and an alarm that fires on the second would fire on every healthy resume."""
    from openfactory.floor.ladder import OVERDUE_S, wait_is_over

    assert OVERDUE_S >= 60, f"the grace is {OVERDUE_S}s — an alarm on every healthy resume"
    just_due = (NOW - timedelta(seconds=OVERDUE_S / 2)).isoformat()
    long_due = (NOW - timedelta(seconds=OVERDUE_S * 3)).isoformat()
    assert wait_is_over(just_due, "rate_limit", NOW) is False, "late the instant it was due"
    assert wait_is_over(long_due, "rate_limit", NOW) is True, "never late at all"


def test_ONE_RULE_decides_it_for_both():
    """Asserted on the call, not on the agreement above: two implementations that happen to agree
    today are two implementations. `watch` asks the same function the floor asks."""
    import inspect

    src = inspect.getsource(watch)
    assert "wait_is_over" in src, (
        "the tech-lead decides for itself whether a wait is over — which is how these two came to "
        "disagree in the first place")
