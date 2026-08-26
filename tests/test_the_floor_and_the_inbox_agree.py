"""The floor and the inbox answered one question in two places (#164).

Seven findings, all the same shape: a fact decided in one module and copied into another, where
the copy is what somebody reads.

THE ONE THAT SHOWED ON THE PILOT'S SCREEN: a rate-limit park that the engine resumes by itself in
half an hour was announced as *Needs you*. `wait_is_over` — written for exactly this question, and
extracted because two answers to it had already disagreed out loud (#146) — was not asked.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from openfactory.floor import ladder

NOW = datetime.now(UTC)


def _park(minutes: int, **extra) -> dict:
    return {"project": "m", "issue": "7", "state": "paused", "attention": True,
            "action": {"kind": "rate_limit", "note": "GitHub rate limit",
                       "wakes_at": (NOW + timedelta(minutes=minutes)).isoformat()}, **extra}


def _rung(job: dict) -> int:
    return ladder.state(ladder.FloorInputs(jobs=[job], inbox=None)).rung


# ── 1. a machine-owned wait is not a person's problem ───────────────────────────────────────────

def test_a_FRESH_rate_park_is_a_clock_not_a_person():
    """The engine resumes it in half an hour. Announcing it as *Needs you* summons somebody to
    type what the machine is about to do unprompted — which is the sentence #146 already cost."""
    assert _rung(_park(30)) == 6


def test_and_one_PAST_its_wake_up_is_a_person_again():
    """The positive twin: a park that should have resumed and has not is exactly what rung 5 is
    for, and a filter that swallowed it would hide a stopped factory.

    IT ASSERTS THE SENTENCE, NOT THE RUNG. Measured while mutating this guard: a filter that
    swallows every self-clearing wait still lands on rung 5, because the overdue sweep below it
    picks the same job up under its own word. The rung is right by accident and the reason is
    generic — "it should have resumed by now" instead of the park naming its own retry time. Two
    paths to one number is exactly how a broken filter passes for working.
    """
    got = ladder.state(ladder.FloorInputs(jobs=[_park(-30)], inbox=None))

    assert got.rung == 5
    assert got.clause == "m #7 — " + ladder.NEED_PHRASE["rate_limit"], (
        f"the park did not reach rung 5 by its own reason: {got.clause!r}")


def test_a_WEDGED_job_is_never_machine_owned_however_it_is_parked():
    """Wedged means nothing can move it — the opposite claim to "the engine will"."""
    assert _rung(_park(30, wedged=True)) == 5


def test_an_ARMED_auto_merge_is_a_clock():
    job = {"project": "m", "issue": "7", "state": "pr_open", "attention": True,
           "action": {"kind": "merge_wait", "auto": True, "pr_url": "u"}}

    assert _rung(job) == 6


def test_but_an_UNARMED_merge_gate_is_a_person(monkeypatch):
    """`merge_wait` is machine-owned only when armed. Measured before this guard existed: the
    filter swallowed the human gate entirely and the floor answered rung 8 — "could not read
    whether anybody is needed" — about a pull request waiting on its reader."""
    job = {"project": "m", "issue": "7", "state": "pr_open", "attention": True,
           "action": {"kind": "merge_wait", "auto": False, "pr_url": "u"}}

    assert _rung(job) == 5


def test_an_impediment_is_a_person_immediately():
    job = {"project": "m", "issue": "7", "state": "on_hold", "attention": True,
           "action": {"kind": "impediment", "note": "no acceptance criteria"}}

    assert _rung(job) == 5


# ── 2. one vocabulary for "why does this need a person" ─────────────────────────────────────────

@pytest.mark.parametrize("job,word", [
    ({"state": "paused", "action": {"kind": "rate_limit"}}, "rate_limit"),
    ({"state": "running", "wedged": True, "action": {"kind": "impediment"}}, "wedged"),
    ({"state": "awaiting_prod_approval", "action": {}}, "approval"),
    ({"state": "awaiting_your_merge", "action": {}}, "merge"),
    ({"state": "on_hold", "action": {"decision": {"options": []}}}, "decision"),
    # BOTH AT ONCE, and the inbox's answer is `decision`: a question a person can answer outranks
    # "nothing can move it", because answering it IS what moves it. Ordering only shows in a row
    # that matches two branches, so a table of one-branch rows cannot see a reorder at all.
    ({"state": "on_hold", "wedged": True, "action": {"decision": {"options": []}}}, "decision"),
    ({"state": "paused", "wedged": True, "action": {"kind": "rate_limit"}}, "rate_limit"),
    ({"state": "on_hold", "action": {"kind": "impediment"}}, "impediment"),
])
def test_the_floor_names_every_shape_the_inbox_names(job, word):
    """`/api/inbox` built this vocabulary in its own branches: `decision` first, `wedged` fifth,
    and a sixth word — `rate_limit` — the floor did not have at all. So a rate-limited park was
    `impediment` on one surface and `rate_limit` on the other, about one job at one instant."""
    assert ladder.need_kind(job) == word


def test_and_the_inbox_takes_that_word_rather_than_choosing_its_own():
    """Reachability: the words agreeing is worth nothing if the endpoint still writes its own."""
    import ast

    from openfactory.api import app

    # THE `kind` KEY SPECIFICALLY, not the word anywhere. `"merge"` and `"decision"` are also
    # option KEYS on this endpoint — the verbs a person presses — and those are its own to name.
    # A blunter search flags them and teaches the next reader to delete the guard.
    src = inspect.getsource(app.inbox)
    spelled = []
    for node in ast.walk(ast.parse(inspect.cleandoc("\n" + src))):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=False):
            if (isinstance(key, ast.Constant) and key.value == "kind"
                    and isinstance(value, ast.Constant)):
                spelled.append(value.value)

    assert not spelled, f"the inbox still spells its own kinds: {sorted(set(spelled))}"
    assert "need_kind(j)" in src, "the inbox does not ask the floor at all"


# ── 3. the panel stops keeping copies ───────────────────────────────────────────────────────────

def test_the_page_is_served_the_facts_the_SERVER_owns():
    from openfactory.api.app import _panel_vocabulary
    from openfactory.runtime.temporal.view import ATTENTION_STATES
    from openfactory.runtime.temporal.workflow import merge_wait_note

    said = _panel_vocabulary()

    assert set(said["alarm"]) == set(ATTENTION_STATES)
    # The rate floor LEFT the vocabulary when it left core: it is the adapter's own number and
    # travels on the budget it judges (`tracker.base.Budget.floor`), so the page never compares
    # a count against a threshold — `low` arrives already decided.
    assert "rate_floor" not in said
    assert said["merge_wait"] == {"auto": merge_wait_note(True), "human": merge_wait_note(False)}


def test_and_the_page_no_longer_CARRIES_them():
    """Two of the three had already drifted: `ALARM` was missing `paused` AND
    `awaiting_prod_approval`, so the bar counting what needs a person did not count a production
    release gate — the same defect #166 fixed one surface over."""
    import re
    from pathlib import Path

    from openfactory import api

    page = (Path(inspect.getfile(api)).parent / "panel.html").read_text()
    code = "\n".join(re.sub(r"(^|\s)//.*$", "", ln) for ln in page.splitlines())

    assert "__VOCABULARY__" in code, "the page is not given the server's words at all"
    assert "_RATE_FLOOR=200" not in code
    assert 'waiting for CI / the merge' not in code, "the engine's sentence is copied again"
    assert 'new Set(["failed"' not in code, "the attention states are hand-listed again"


def test_the_placeholder_is_RESOLVED_when_the_page_is_served():
    """A page shipped with `__VOCABULARY__` unsubstituted is a blank screen — the substitution is
    the only thing between the two."""
    from openfactory.api.app import _read_panel

    assert "__VOCABULARY__" not in _read_panel()


# ── 4. the vendor's claim decides nothing, and the rule has one home ────────────────────────────

def test_the_resume_sweep_obeys_the_ENGINES_backoff():
    from openfactory.scheduler import resume_epoch

    paused = "2026-07-12T10:00:00+00:00"

    assert resume_epoch(paused, "2026-07-12T10:30:00+00:00") == resume_epoch(paused, None)


def test_the_wedged_rule_is_ASKED_not_re_derived():
    """`view.is_wedged` exists because a rule inlined is a rule no guard can drive — its own
    docstring says a mutation replacing it with `False` passed every test while the Stop button
    vanished. The tech-lead's round reproduced two of its three conditions."""
    from openfactory.runtime.temporal import activities

    src = inspect.getsource(activities._techlead_watch_findings
                            if hasattr(activities, "_techlead_watch_findings") else activities)

    assert "is_wedged(" in src, "the round decides `wedged` for itself again"
