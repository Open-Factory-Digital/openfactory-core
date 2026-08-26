"""The tech-lead on rounds (ADR-0020 §3).

Everything else it does happens because something called it. These are the failures no event
reports: a park nobody answered — #478 held the floor for eighteen hours and no event ever fired
again — an idle floor beside a queue, and one systemic cause wearing three ticket numbers.
"""

from __future__ import annotations

import pytest

from openfactory.techlead.watch import (
    IDLE,
    RECURRING,
    STUCK,
    Finding,
    FloorState,
    Parked,
    report,
    watch,
)

THROTTLED = "box failed: gh project field-list failed: GraphQL: API rate limit exceeded"


def _kinds(findings) -> set[str]:
    return {f.kind for f in findings}


# ── the park nobody answered ────────────────────────────────────────────────────────────────────

def test_the_478_case_is_SEEN_and_acted_on():
    """A park the factory could have fixed, still sitting there hours later. Nothing else notices
    it: the event that created it fired once, and never again."""
    state = FloorState(parked=[Parked(ticket=478, hours=18, note=THROTTLED)])
    found = watch(state)
    stuck = [f for f in found if f.kind == STUCK]
    assert stuck and stuck[0].ticket == 478
    assert stuck[0].resumable is True
    # RENDERED PER LANGUAGE SINCE #124 — the claim is that a self-healing park is NAMED as one,
    # so it is pinned in both, which also catches an entry translated into only one.
    assert "passes by itself" in stuck[0].detail
    assert "passa sozinho" in watch(state, language="pt-BR")[0].detail


def test_a_park_waiting_on_a_PERSON_is_reported_but_never_resumed():
    """Pressing resume on a decision somebody owes is not helpfulness, it is losing their answer."""
    state = FloorState(parked=[
        Parked(ticket=412, hours=9, note="decision needed — qual formato de export?")])
    found = watch(state)
    assert found[0].resumable is False
    assert "waiting on a decision" in found[0].detail
    assert "esperando uma decisão" in watch(state, language="pt-BR")[0].detail


def test_a_park_that_JUST_happened_is_left_alone():
    """A person deserves a chance to answer before an agent starts narrating their inbox back."""
    assert watch(FloorState(parked=[Parked(ticket=1, hours=0.5, note=THROTTLED)])) == []


def test_an_unknown_failure_is_reported_but_NOT_resumed():
    """The classifier's asymmetry has to survive into the rounds: retrying what nobody understood
    is the same mistake with an hourly schedule attached."""
    found = watch(FloorState(parked=[Parked(ticket=9, hours=8, note="algo muito estranho")]))
    assert found[0].resumable is False


# ── the floor that should be moving ─────────────────────────────────────────────────────────────

def test_an_idle_floor_with_work_queued_is_a_symptom_not_a_pause():
    """The poller ticks every three minutes. Nothing running with a queue means the pickup path is
    broken, not busy."""
    state = FloorState(running=0, queued=[500, 501], idle_minutes=90)
    found = watch(state)
    assert IDLE in _kinds(found)
    assert "should not happen" in found[0].action
    assert "não deveria acontecer" in watch(state, language="pt-BR")[0].action


def test_an_idle_floor_with_NOTHING_queued_is_just_quiet():
    assert watch(FloorState(running=0, queued=[], idle_minutes=600)) == []


def test_a_busy_floor_is_not_reported():
    assert watch(FloorState(running=1, queued=[500], idle_minutes=0)) == []


def test_a_brief_gap_is_not_an_incident():
    assert watch(FloorState(running=0, queued=[1], idle_minutes=4)) == []


# ── one problem wearing three numbers ───────────────────────────────────────────────────────────

def test_the_same_cause_across_tickets_is_ONE_problem():
    """Each diagnosis saw only its own ticket, so nothing in the system could ever say this."""
    state = FloorState(recent_causes={"transient": 4, "code": 1})
    found = watch(state)
    assert RECURRING in _kinds(found)
    assert "4 different tickets" in found[0].detail
    assert "4 tickets diferentes" in watch(state, language="pt-BR")[0].detail
    assert "not three" in found[0].action
    assert "não três" in watch(state, language="pt-BR")[0].action


def test_bad_luck_twice_is_not_a_pattern():
    assert watch(FloorState(recent_causes={"transient": 2})) == []


# ── what it says ────────────────────────────────────────────────────────────────────────────────

def test_it_says_NOTHING_when_there_is_nothing_to_say():
    """A watcher that reports "all fine" every hour is one nobody reads on the hour that matters."""
    assert report(watch(FloorState())) == ""


def test_every_finding_says_what_happens_next():
    found = watch(FloorState(
        parked=[Parked(ticket=478, hours=18, note=THROTTLED),
                Parked(ticket=412, hours=9, note="decision needed — x")],
        running=0, queued=[1], idle_minutes=90, recent_causes={"transient": 3}))
    assert len(found) == 4
    for f in found:
        assert f.action, f
    text = report(found, agent_name="Tech lead")
    assert "#478" in text and "#412" in text


@pytest.mark.parametrize("hours", [3, 8, 18, 100])
def test_a_park_is_reported_however_long_it_has_been_there(hours):
    """It must not stop mentioning something because it has been wrong for a long time."""
    assert watch(FloorState(parked=[Parked(ticket=1, hours=hours, note=THROTTLED)]))


# ── the wiring ──────────────────────────────────────────────────────────────────────────────────

def test_the_rounds_run_HOURLY_not_weekly():
    """A park holding the floor costs capacity every hour it sits; a rotting backlog costs over
    weeks. Two watchers, two cadences."""
    from openfactory.runtime.temporal.schedule import PRODUCT_EVERY_HOURS, WATCH_EVERY_HOURS

    assert WATCH_EVERY_HOURS == 1
    assert WATCH_EVERY_HOURS < PRODUCT_EVERY_HOURS


def test_the_rounds_only_resume_what_they_flagged_as_resumable():
    """Guarded on the CALL, not on its exact spelling.

    The first version of this asserted the literal string `signal("act_on_impediment", "resume",
    "")` — which is the call that raised TypeError on every attempt in production, because the
    Temporal SDK takes `args=[...]` keyword-only. The test pinned the bug in place and reported
    green, because a string match proves the source contains certain characters, not that the call
    is callable. tests/test_temporal_call_arity.py now checks it against the real signature."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("openfactory/runtime/temporal/activities.py").read_text())
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "techlead_watch"
    )
    src = ast.unparse(fn)
    # the guard is now the inverted form (`if not (...): continue`) — assert the CONDITION exists
    # on the path to the signal, whichever way it is spelt
    assert "finding.resumable and finding.ticket" in src, "it would resume anything it found"

    calls = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and getattr(n.func, "attr", "") == "signal"
        and any(getattr(a, "value", None) == "act_on_impediment" for a in n.args)
    ]
    assert len(calls) == 1, "the resume signal is sent from more than one place, or from none"
    values = [ast.unparse(a) for a in calls[0].args[1:]] + [
        ast.unparse(k.value) for k in calls[0].keywords if k.arg == "args"
    ]
    assert any("resume" in v for v in values), f"the signal does not carry 'resume': {values}"


def test_the_rounds_say_what_they_did_even_when_the_signal_failed():
    """Saying it still matters if the resume missed — otherwise a failed action is a silent one."""
    from pathlib import Path

    body = Path("openfactory/runtime/temporal/activities.py").read_text()
    body = body[body.index("async def techlead_watch("):]
    resumed_at = body.index("resumed.append")
    # posting now goes through the CHANNEL adapter (`channel/registry.py`) rather than naming
    # Slack — Telegram plugs in without touching this ordering rule
    said_at = body.index(".say(")
    assert resumed_at < said_at


# ── what the client actually saw, 2026-07-27 ────────────────────────────────────────────────────

def test_it_never_announces_a_retry_it_has_not_done():
    """The screenshot: "vou tentar de novo agora" on a retry that had already failed with a
    TypeError. An announcement of an action that never happened is the "confident wrong remedy"
    ADR-0020 warns about — once messages are aspirational, none of them are trusted."""
    from openfactory.techlead.watch import RESUME_FAILED, RESUMED, Finding, report

    f = Finding(kind="stuck-park", ticket=478, resumable=True, progress=19,
                detail="stopped 19h ago on something that passes by itself",
                action="vou tentar de novo agora — throttled")

    # outcomes are keyed by the finding's IDENTITY, not its ticket number: a ticket resumed this
    # round can also carry an unacknowledged review reminder, and a number-keyed outcome rewrote
    # the reminder line into "retomei" — losing the ack instruction it existed to deliver
    did = report([f], outcomes={f.key: RESUMED})
    assert "vou tentar" not in did, "still promises instead of reporting"
    assert "resumed it" in did

    failed = report([f], outcomes={f.key: RESUME_FAILED})
    assert "vou tentar" not in failed
    assert "could not" in failed
    assert "resume 478" in failed, "a failed action must hand the person something executable"


def test_a_reminder_on_a_resumed_ticket_keeps_its_ack_instruction():
    """The collision, asserted directly: same ticket number, two different findings, one outcome."""
    from openfactory.techlead.watch import RESUMED
    resumed = Finding(kind="stuck-park", ticket=478, resumable=True, progress=19, detail="parado")
    reminder = Finding(kind="stuck-park", ticket=478, resumable=False, progress=30,
                       detail="entregue com a revisão apontando algo sério",
                       action="ninguém olhou ainda — responda `ack 478` quando alguém assumir")
    text = report([resumed, reminder], outcomes={resumed.key: RESUMED})
    assert "resumed it" in text, "the resumed line lost its outcome"
    assert "ack 478" in text, "the reminder was rewritten by the resume outcome"


def test_the_report_uses_slack_bold_not_markdown():
    """`**#478**` reached the client with the asterisks printed."""
    from openfactory.techlead.watch import Finding, report

    out = report([Finding(kind="stuck-park", ticket=478, detail="parado", action="x")])
    assert "**" not in out
    assert "*#478*" in out


def test_the_same_finding_is_not_repeated_every_round():
    """Reported identically at 21h and again at 21h38. Twice in forty minutes is noise, and a
    channel people skim is worse than no channel."""
    from openfactory.techlead.watch import Finding, worth_saying

    first = [Finding(kind="stuck-park", ticket=478, detail="parado há 19h", progress=19.0)]
    say, memory = worth_saying(first, {})
    assert len(say) == 1, "a new finding must always be said"

    again = [Finding(kind="stuck-park", ticket=478, detail="parado há 20h", progress=20.0)]
    say, memory = worth_saying(again, memory)
    assert say == [], "one hour later, unchanged — this is the 21h38 repeat"


def test_but_a_park_nobody_answers_is_said_again_eventually():
    """Suppression is not a mute button: something still stuck six hours later is worth the reminder,
    with the new number."""
    from openfactory.techlead.watch import Finding, worth_saying

    _, memory = worth_saying(
        [Finding(kind="stuck-park", ticket=478, detail="parado há 19h", progress=19.0)], {})
    say, _ = worth_saying(
        [Finding(kind="stuck-park", ticket=478, detail="parado há 25h", progress=25.0)], memory)
    assert len(say) == 1 and "25h" in say[0].detail


def test_a_park_that_stops_being_self_healing_is_said_immediately():
    """The most important thing a round can report: the factory has given up and a person is now
    needed. It must not be suppressed as "the same finding"."""
    from openfactory.techlead.watch import Finding, worth_saying

    _, memory = worth_saying(
        [Finding(kind="stuck-park", ticket=478, resumable=True, progress=19.0, detail="a")], {})
    say, _ = worth_saying(
        [Finding(kind="stuck-park", ticket=478, resumable=False, progress=19.5, detail="b")],
        memory)
    assert len(say) == 1, "an escalation was suppressed as a repeat"


def test_a_problem_that_returns_is_reported_again():
    """Memory carries forward only what is STILL true. A finding suppressed by a stale entry from
    last week is a silence nobody chose."""
    from openfactory.techlead.watch import Finding, worth_saying

    _, memory = worth_saying(
        [Finding(kind="idle-floor", detail="ocioso", progress=30.0)], {})
    cleared, memory2 = worth_saying([], memory)
    assert cleared == [] and memory2 == {}, "nothing wrong now → nothing carried forward"
    say, _ = worth_saying([Finding(kind="idle-floor", detail="ocioso", progress=25.0)], memory2)
    assert len(say) == 1, "it came back and was suppressed by a stale entry"


# ── the rounds exist WITHOUT Slack, and something actually creates them ─────────────────────────

def test_the_watch_needs_no_channel_only_an_enabled_project():
    """`if not project.channel_id: continue` was Slack as a precondition for a capability — the
    exact shape ADR-0038 forbids. A deployment with no Slack had no on-call rounds at all,
    silently; the panel then truthfully pinned a red "watcher unknown" pill that nobody could
    act on. The rounds speak through whatever notifier the project resolves, which since the
    panel became the default voice is never nothing."""
    import ast
    import inspect
    import textwrap

    from openfactory.runtime.temporal import schedule

    # AST, not substring: the docstring EXPLAINS why channel_id must not gate this, and a text
    # search would trip on the explanation — the exact failure _code_names was built against.
    tree = ast.parse(textwrap.dedent(inspect.getsource(schedule.ensure_techlead_watch)))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "channel_id" not in attrs, "the watch is gated on a Slack channel again"
    assert "enabled" in attrs, "a disabled project's floor is off — narrating it hourly is noise"


def test_the_worker_startup_ensures_the_watches():
    """`ensure_techlead_watch` existed, was tested, and was called by NOTHING — no command, no
    startup path, no deploy step. The worker owns the floor, so the worker ensures the watchers
    over it, idempotently, every start."""
    import inspect

    from openfactory.runtime.temporal import worker

    src = inspect.getsource(worker.main)
    assert "ensure_techlead_watch" in src, "the watches are reached by nothing again"


# ── the neighbour that kept the same gate (C-38) ─────────────────────────────────────────────────

def test_the_product_sweep_needs_the_MODULE_not_a_slack_channel():
    """`ensure_techlead_watch` was freed from its Slack gate; `ensure_product_sweeps`, directly
    below it in the same file, kept an identical one — so a product module on a panel-only
    deployment got no sweep at all. Surfaced as `watcher unknown: openfactory-product-sweep-fx-dsk` in
    the panel, for a project whose product module IS configured.

    AST, not substring: the docstring names `channel_id` while explaining why it must not gate."""
    import ast
    import inspect

    from openfactory.runtime.temporal import schedule as sched

    tree = ast.parse(inspect.getsource(sched.ensure_product_sweeps).lstrip())
    reads = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "channel_id" not in reads, (
        "the product sweep is gated on a Slack channel — ADR-0038: the panel is the reference "
        "surface and a channel is an add-on"
    )
    # THE POSITIVE TWIN, AS A CALL AND NOT A SUBSTRING. This line was `assert "product" in
    # getsource(...)` — a TAUTOLOGY, found by the 2026-08-17 guard audit: `getsource` includes the
    # `def ensure_product_sweeps` line, whose own name contains "product", so the assertion could
    # never fail whatever the body did. What the sweep is actually gated on is the project's
    # product MODULE, read via `getattr(project, "product", None)` — asserted as that call.
    gates_on_product = any(
        isinstance(n, ast.Call) and getattr(n.func, "id", "") == "getattr"
        and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant)
        and n.args[1].value == "product"
        for n in ast.walk(tree))
    assert gates_on_product, (
        "the sweep no longer gates on the product module — every project gets one, or none do")


def test_ensure_all_is_the_ONE_reconciler_the_worker_calls():
    """The worker briefly called `ensure_techlead_watch` a second time, on a mistaken reading that
    nothing called it — reconciling half of what `ensure_all` already reconciles, and hiding the
    product sweep's absence behind a green log line about watches."""
    import ast
    import inspect

    from openfactory.runtime.temporal import worker as w

    tree = ast.parse(inspect.getsource(w.main).lstrip())
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "ensure_all" in called
    assert "ensure_techlead_watch" not in called, "reconcile through ensure_all, not one branch"


def test_ensure_all_covers_every_schedule_the_codebase_defines():
    """A new `ensure_*` that ensure_all forgets is a schedule no deploy ever creates."""
    import ast
    import inspect

    from openfactory.runtime.temporal import schedule as sched

    defined = {n for n in dir(sched) if n.startswith("ensure_") and n != "ensure_all"}
    tree = ast.parse(inspect.getsource(sched.ensure_all).lstrip())
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert defined <= called, f"ensure_all never calls: {sorted(defined - called)}"


# ── reconcile means both directions (found live, 2026-08-06) ─────────────────────────────────────

def test_ensure_all_also_RETIRES_what_no_longer_belongs():
    """`ensure_*` created and updated, and nothing ever removed. A project renamed, removed, or
    moved to another deployment left its watch and its sweep running for ever — each firing on
    schedule, each failing `KeyError: project not registered`, each a red line in the log
    indistinguishable from one that means something.

    Found live: an `openfactory-product-sweep-<project>` schedule firing hourly against a registry holding
    six fixture projects and no such project."""
    import ast
    import inspect

    from openfactory.runtime.temporal import schedule as sched

    tree = ast.parse(inspect.getsource(sched.ensure_all).lstrip())
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "retire_orphan_schedules" in called


def test_an_unreadable_registry_retires_NOTHING():
    """An empty or failed read must never look like "this deployment has no projects" — that
    reading deletes every schedule the platform owns."""
    import inspect

    from openfactory.runtime.temporal import schedule as sched

    src = inspect.getsource(sched.retire_orphan_schedules)
    assert "if not known:" in src
    assert "return []" in src


def test_only_OUR_prefixes_are_ever_considered():
    """A schedule this code did not create is not this code's to delete."""
    import inspect

    from openfactory.runtime.temporal import schedule as sched

    src = inspect.getsource(sched.retire_orphan_schedules)
    assert "WATCH_SCHEDULE_PREFIX" in src and "PRODUCT_SCHEDULE_PREFIX" in src
    assert "startswith" in src
