"""A parked job must never be silent.

The house invariant: every stall either self-heals within a bound or asks a human with EXECUTABLE
options. On 2026-07-27 #478 parked and #dark-factory-dev showed nothing for eighteen hours while the
single-line floor was held and no other work ran.

The cause was not a missing feature. The alert existed — as a side effect of `diagnose_impediment`,
an expensive operation (a repo clone plus a model pass) whose failure is deliberately swallowed so
it can never block a park. Its agent could not authenticate and its GitHub reads were throttled, so
it failed, silently, and took the only notification with it.
"""

from __future__ import annotations

from pathlib import Path

ACTIVITIES = Path("openfactory/runtime/temporal/activities.py").read_text()
WORKFLOW = Path("openfactory/runtime/temporal/workflow.py").read_text()


def _say_body() -> str:
    body = ACTIVITIES[ACTIVITIES.index("async def notify_coordinator_say("):]
    return body[: body.index("\ndef ", 1)]


def test_a_park_reaches_slack_WITHOUT_the_diagnosis():
    """An alert that depends on a model call and a repo clone is not an alert."""
    assert 'inp.kind in ("pickup", "merge", "needs_action")' in _say_body()


def test_the_park_alert_says_what_to_DO():
    """A message saying only that something stopped leaves the reader to find the panel and work
    out their options — the same silence with extra steps."""
    # ANCHORED ON THE CALL, NOT ON A CHARACTER COUNT. The window was `[:3000]`, and ten lines of
    # comment explaining why `resume` is now conditional pushed the assertion's own subject out of
    # it — a guard failing because the code around it grew, which teaches everyone to widen the
    # number instead of reading the failure (2026-08-16).
    #
    # AND ON THE KEYS, NOT THE SENTENCES (#160). Both were welded Portuguese here; they now live
    # in `techlead/voice.NARRATION`, one row per language, and the guard follows them there — the
    # assertion is the same one either way (this message teaches the two verbs), but a literal
    # would have made the guard fail on the first project that reads it in English.
    from openfactory.techlead import voice

    start = WORKFLOW.index('workflow.patched("park-says-needs-action")')
    park = WORKFLOW[start:WORKFLOW.index('"needs_action")', start) + 40]
    assert '"park.both-verbs"' in park and '"park.skip-only"' in park
    assert '"park.needs-you"' in park

    for key in ("park.both-verbs", "park.skip-only", "park.needs-you"):
        assert key in voice.NARRATION, f"{key} is announced and has no entry"
    for language in ("en", "pt-BR"):
        assert "resume #" in voice.NARRATION["park.both-verbs"][language]
        assert "skip #" in voice.NARRATION["park.both-verbs"][language]
        assert "skip #" in voice.NARRATION["park.skip-only"][language]


def test_a_park_is_louder_than_a_pickup():
    """"picked up #478" and "#478 stopped and needs you" must not arrive looking the same."""
    assert 'level = "warning" if inp.kind == "needs_action" else "info"' in _say_body()


def test_the_diagnosis_is_still_ATTEMPTED_and_still_cannot_block():
    """It remains the detail on an alert people have already seen — additive, never load-bearing."""
    park = WORKFLOW[WORKFLOW.index("TECH-LEAD DIAGNOSIS"):][:1600]
    assert "diagnose_impediment" in park
    assert "never block the park" in park


def test_the_alert_was_not_REORDERED_ahead_of_the_diagnosis():
    """Tempting, and wrong while a job is parked on the old order: reordering these commands
    diverges its replay. The fix was to stop the alert DEPENDING on the diagnosis, not to move it."""
    diagnosis_at = WORKFLOW.index('workflow.patched("park-techlead-diagnosis")')
    alert_at = WORKFLOW.index('workflow.patched("park-says-needs-action")')
    assert diagnosis_at < alert_at
