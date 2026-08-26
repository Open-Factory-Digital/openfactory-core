"""A wait nobody can time, and a stall nobody can see (#140).

Two holes on the same subject — *when does this move again?* — found while planning the status
vocabulary, because the vocabulary promises answers the platform could not give.

  1. **A PARKED JOB COULD NOT SAY WHEN IT WAKES.** The park payload carried `retry_at`, a vendor
     string that `_pause_backoff` DELIBERATELY REFUSES to obey ("formats vary, clocks skew"). The
     real wake-up is `min(30·(n+1), 120)` minutes and was exposed to nobody. So every surface could
     say "paused" and none could say until when, and a 30-minute backoff read exactly like a job
     nobody will ever resume. A screen promoting a park to "needs a human" off `retry_at` would
     fire up to 100 minutes before the workflow intended to resume by itself — the panel and the
     engine disagreeing about the same fact.

  2. **A WEDGED JOB PRODUCED NO INBOX ITEM AT ALL.** `is_wedged` is a live job with no gate, no
     park, running past `LONG_RUNNING_HOURS` — so its `state` is `running`, it matched none of the
     inbox's branches and none of `_ATTENTION`. It was visible only to somebody looking at that one
     project's page, and invisible to Slack, to `/api/inbox` and to every other channel, on the one
     surface whose entire job is "does anything need me?". And it holds the floor slot while it
     sits there, so nothing else starts either: the quietest possible way for a factory to stop.

REPLAY SAFETY. `workflow.now()` is deterministic and neither new line issues a command, so an
in-flight job replays unchanged — this needs no `workflow.patched()` (contrast #71, where a new
command did).
"""

from __future__ import annotations

import inspect
from datetime import timedelta

from openfactory.api import app as api
from openfactory.runtime.temporal import workflow as wf

# ── 1. the park says when it wakes ──────────────────────────────────────────────────────────────

def test_the_park_carries_the_deadline_THE_TIMER_WILL_ACTUALLY_USE():
    src = inspect.getsource(wf.JobWorkflow._wait_operator)
    assert '"parked_at": parked_at.isoformat()' in src, "a park still records no start time"
    assert '"wakes_at": ((parked_at + timeout).isoformat()' in src, (
        "the wake-up is still not derived from the timeout the workflow actually sleeps on")


def test_it_is_computed_from_the_TIMEOUT_and_not_from_the_vendor_string():
    """The distinction the whole card turns on. `retry_at` is still carried — it is the provider's
    own claim and worth showing — but it may never BE the wake-up, because this module refuses to
    obey it a few lines below."""
    src = inspect.getsource(wf.JobWorkflow._wait_operator)
    wakes = src[src.index('"wakes_at"'):]
    wakes = wakes[:wakes.index("\n", wakes.index("None)"))]
    assert "retry_at" not in wakes, (
        f"the wake-up is built from the vendor string the engine refuses to trust: {wakes!r}")
    assert "timeout" in wakes, "the wake-up is not derived from the timer at all"
    assert '"retry_at": getattr(result, "retry_at", None)' in src, (
        "the provider's own claim was dropped — it is evidence, it just is not the answer")


def test_the_CLOCK_is_the_replay_safe_one():
    """`datetime.now()` inside a workflow is non-deterministic and breaks replay. `workflow.now()`
    is the established pattern in this module (359, 842, 847)."""
    src = inspect.getsource(wf.JobWorkflow._wait_operator)
    assert "parked_at = workflow.now()" in src
    assert "datetime.now(" not in src, "a wall clock crept into a replayed workflow"


def test_a_park_that_HOLDS_UNTIL_ANSWERED_reports_no_deadline_rather_than_a_date():
    """A decision park passes ten years, because a decision is always human and must never time
    out. Rendering that raw would put a date in the next decade on screen as though somebody had
    set it — a screen inventing a deadline. `None` says the true thing: nothing moves this on its
    own."""
    assert wf._HELD_UNTIL_ANSWERED <= timedelta(days=60), (
        "the horizon is so far out that a real deadline would be suppressed as if it were one of "
        "the ten-year decision parks")
    assert wf._HELD_UNTIL_ANSWERED >= timedelta(days=7), (
        "the horizon is short enough to suppress a legitimate multi-day merge deadline")
    src = inspect.getsource(wf.JobWorkflow._wait_operator)
    assert "if timeout <= _HELD_UNTIL_ANSWERED else None" in src


def test_a_REAL_backoff_is_still_reported_as_a_time():
    """The positive twin, and the one that decides whether this was worth doing: the rate-limit
    park's 30-to-120-minute ladder is far inside the horizon, so it keeps a real instant."""
    for spent in range(4):
        backoff = wf.JobWorkflow._pause_backoff(spent)
        assert backoff <= wf._HELD_UNTIL_ANSWERED, (
            f"a {backoff} backoff would be reported as having no deadline at all")


def test_the_deadline_REACHES_the_channels():
    """Reachability. The field is decoration if the feed every channel reads drops it — which is
    exactly what happened to `retry_at`, carried on the park since it existed and never once put
    on `/api/inbox`."""
    src = inspect.getsource(api.inbox)
    for field in ("parked_at", "wakes_at", "retry_at"):
        assert f'"{field}": act.get("{field}")' in src, (
            f"{field} stops at the workflow and reaches no channel")


# ── 2. the wedged job is somebody's problem ─────────────────────────────────────────────────────

def test_a_WEDGED_job_becomes_an_inbox_item():
    """BEHAVIOUR, not source text. This asserted the literal `"kind": "wedged"` in the endpoint —
    and the word moved to `ladder.need_kind` when the inbox and the floor stopped keeping two
    vocabularies for one question (#164). The claim is about what the FEED says, which survives
    the word moving."""
    from openfactory.floor.ladder import need_kind

    src = inspect.getsource(api.inbox)
    assert 'elif j.get("wedged"):' in src, (
        "a job that is running and cannot move still produces no item on the feed every channel "
        "reads — it is visible only to somebody already looking at that project's page")
    assert need_kind({"state": "running", "wedged": True, "action": {"kind": "impediment"}}) == (
        "wedged"), "a wedged job is labelled as something else on the feed every channel reads"


def test_it_offers_the_verb_THAT_EXISTS_and_says_what_it_costs():
    """No fake buttons. `stop` is a registered action (`actions/catalog.py`), and the consequence
    is stated because ending a run sounds destructive and is not: the branch survives."""
    src = inspect.getsource(api.inbox)
    branch = src[src.index('elif j.get("wedged"):'):]
    branch = branch[:branch.index("elif state in tv.ATTENTION_STATES")]
    assert '"/api/act/stop"' in branch, "the item names no way to act on it"
    assert '"key": "stop"' in branch
    assert "untouched" in branch, "it does not say that the branch and commits survive"

    from openfactory import actions

    assert "stop" in actions.names(), (
        "the inbox offers `stop` and no such action is registered — a button that refuses")


def test_it_is_checked_BEFORE_the_generic_impediment_branch():
    """Ordering, and it matters: a wedged job's state is `running`, which is not in `_ATTENTION`,
    so the generic branch would never catch it — but a future widening of `_ATTENTION` would
    silently swallow the specific answer into the vague one."""
    src = inspect.getsource(api.inbox)
    assert src.index('elif j.get("wedged"):') < src.index("elif state in tv.ATTENTION_STATES"), (
        "the generic impediment branch now shadows the wedged one")


def test_a_HEALTHY_running_job_produces_NOTHING():
    """The positive twin, and the expensive direction. This feed is what a human is asked to look
    at; an item for every running job would train everybody to ignore it."""
    # DRIVEN, not read: a job with no action, no gate and `wedged` false must yield no item.
    import asyncio

    class _TV:
        # The route now asks the module that OWNS the word rather than keeping its own copy
        # (#144), so the double has to carry it too.
        ATTENTION_STATES = frozenset({"on_hold", "needs_refinement", "paused", "blocked",
                                      "failed", "awaiting_prod_approval", "awaiting_your_merge"})

        @staticmethod
        async def connect():
            return object()

        @staticmethod
        async def list_jobs(_c, _ns):
            return [{"project": "acme", "issue": "1", "title": "t", "state": "running",
                     "action": None, "wedged": False}]

    import openfactory.api.app as mod

    old = mod._temporal
    mod._temporal = lambda: (_TV(), "addr", "ns")
    try:
        assert asyncio.run(api.inbox()) == [], "a perfectly healthy running job asks for a human"
    finally:
        mod._temporal = old
