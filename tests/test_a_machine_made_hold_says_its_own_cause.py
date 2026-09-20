"""A hold the factory made says what it IS, instead of having its cause read back out of its prose.

THE DEFECT, DRIVEN. #184's merge watch parks on a check it has already typed, and writes the
check's NAME and the vendor's remedy into the park's note. `techlead/classify.py` decides who acts
by matching that note against its rules — so a blocking check a team called *"rate-limit tests"*
matched the throttling rule, came back `transient`, and the workflow did what it does for
throttling: announced *"This is throttling and it passes on its own"* and auto-resumed. Measured on
the real `JobWorkflow`: **four agent passes instead of one**, three of them spent re-running the
whole job against a required review no pass can settle — the loop #184 exists to end, reached
through the words a vendor or a team chose.

The cure is the one `attempts_spent` already taught this codebase (#124): what a machine knows is
DATA. `RunResult.hold_cause` carries the class, the park payload carries it to the rounds, and
`classify` prefers a declaration over prose. Prose stays the reading for a hold that only has
prose — including the one hold in these paths that genuinely knows nothing more than a forge's
own error.

    the classifier   a declaration wins; a stranger's word is not a declaration; no cause, no change
    the producers    what each #184 path declares, from the REAL `what_to_repair` and the real note
    the workflow     the same job, on a real engine: one park, one agent pass — and the replay
    the rounds       a gate hold is never resumed by the hourly round
"""

from __future__ import annotations

import importlib
import uuid
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Replayer, Worker

import tests.test_a_failing_check_is_read_for_what_it_is as ci
from openfactory.contracts import RunResult
from openfactory.runtime.repairable import what_to_repair
from openfactory.runtime.temporal.workflow import JobParams, JobWorkflow
from openfactory.techlead import watch

# THE MODULE, READ THROUGH `importlib`, and `GATE` with a fallback — so this file still COLLECTS
# against a tree that has neither the cause nor the `cause=` keyword, which is how it was measured
# red. (`import openfactory.techlead.classify as …` is not that module: the package re-exports the
# FUNCTION under that name, and this very fix met it as "'module' object is not callable".)
_causes = importlib.import_module("openfactory.techlead.classify")
CODE, ENVIRONMENT = _causes.CODE, _causes.ENVIRONMENT
TRANSIENT, UNKNOWN = _causes.TRANSIENT, _causes.UNKNOWN
Verdict, classify, remedy_for = _causes.Verdict, _causes.classify, _causes.remedy_for
GATE = getattr(_causes, "GATE", "gate")

# ═══ the words that make prose dangerous ════════════════════════════════════════════════════════

#: Check names a team or a vendor may legitimately choose, each one hitting a rule that means
#: "the factory retries this itself". None of them is about throttling, a network or a race.
INNOCENT_NAMES = [
    "rate-limit tests",                 # transient / throttled
    "connection reset regression",      # transient / network
    "429 budget check",                 # transient / throttled
    "still running e2e",                # transient / race
]


class _Forge:
    """A forge whose one blocking check is a PROCESS gate — a required review — under a name."""

    checks_are_typed = True

    def __init__(self, name: str):
        self.name = name

    def pr_checks(self, *, pr):
        return [{"name": self.name, "bucket": "fail", "blocking": True, "kind": "process",
                 "remedy": "The reviewers this branch requires must approve the pull request."}]

    def failed_ci_logs(self, *, pr):
        return ""


def _gate_hold(name: str) -> RunResult:
    """The hold the REAL repair gate builds for that check (`runtime/repairable.py`)."""
    held, _ = what_to_repair(lambda: _Forge(name), "12", "https://forge/pr/1")
    assert held is not None and held.merge_refused is True
    return held


# ═══ the classifier ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("name", INNOCENT_NAMES)
def test_a_checks_name_no_longer_decides_what_a_hold_is(name):
    """THE DEFECT, at the seam. The same note, read as prose, is a `transient` the factory retries
    — and the retry is a whole agent pass at a gate only a person can open."""
    held = _gate_hold(name)
    assert name in held.note, "the note no longer carries the check's name — this proves nothing"

    from_prose = classify(held.note)
    declared = classify(held.note, cause=held.hold_cause)

    assert from_prose.cause == TRANSIENT and remedy_for(from_prose).action == "retry", (
        f"{name!r} stopped tripping a retry rule; pick another name or this guard is decoration")
    assert declared.cause == GATE
    assert remedy_for(declared).action == "escalate"


def test_a_gate_is_never_retried__at_any_budget():
    """Not "retried fewer times": a required review is not a thing more passes settle."""
    for spent in (0, 1, 5):
        got = remedy_for(Verdict(cause=GATE, detail="the-forge-gate"), already_tried=spent)
        assert got.action == "escalate" and got.wait_seconds == 0 and got.attempts_left == 0
    said = remedy_for(Verdict(cause=GATE, detail="the-forge-gate"), language="pt-BR")
    assert said.teaches_the_verbs and "`resume`" in said.say and "`skip`" in said.say
    assert "pull request" in said.say, "the pt-BR sentence was not rendered"


def test_a_declared_hold_keeps_what_the_sentences_are_built_from():
    """The verdict is not only a word. `detail` is the phrase a rendered sentence interpolates,
    and `detail_source` is the note `remedy_for` reads an exhaustion out of — a declaration that
    dropped either would trade one silent wrong answer for another."""
    from openfactory.techlead import voice

    assert classify("anything", cause=CODE).detail == "the-change"
    assert classify("anything", cause=GATE).detail == "the-forge-gate"
    said = remedy_for(classify("throttled again", cause=TRANSIENT)).say
    assert voice.say(voice.DETAIL, "throttled", None) in said

    spent = remedy_for(classify("still rate-limited after 3 auto-resumes", cause=TRANSIENT))
    assert spent.action == "escalate", (
        "a declared hold lost the note, so the exhaustion stated in its own prose went unread")


def test_a_hold_that_says_nothing_is_read_exactly_as_it_was():
    """PROSE STAYS THE FALLBACK. Every park made before this field, and every one whose producer
    cannot name the class, must classify as it always did."""
    for note, expected in (("rate limit exceeded", TRANSIENT),
                           ("403 Forbidden", ENVIRONMENT),
                           ("something nobody wrote a rule for", UNKNOWN)):
        assert classify(note).cause == expected
        assert classify(note, cause="").cause == expected


@pytest.mark.parametrize("claimed", ["banana", "GATE", " gate", 7, None, MagicMock()])
def test_a_word_nobody_recognises_is_not_a_declaration(claimed):
    """A cause outside the taxonomy — or a test double answering every attribute — must not invent
    a class, or a remedy. The rules run, exactly as they do for a hold with no declaration."""
    assert classify("rate limit exceeded", cause=claimed).cause == TRANSIENT


def test_a_declaration_is_taken_over_prose_that_says_the_opposite():
    """Both directions, so this is a preference and not a special case for one word."""
    assert classify("rate limit exceeded", cause=GATE).cause == GATE
    assert classify("'a gate' must pass before this pull request can merge", cause=TRANSIENT) \
        .cause == TRANSIENT


# ═══ what each of #184's paths declares ═════════════════════════════════════════════════════════

def test_the_repair_gate_declares_a_gate__and_keeps_the_sentence_a_person_reads():
    held = _gate_hold("Work item linking")
    assert held.hold_cause == GATE
    assert "'Work item linking'" in held.note and "no change to the code settles" in held.note


def test_a_check_with_no_log_is_a_gate_too():
    """`ASK` either way: nothing a repair pass could act on, so a person reads it on the forge."""
    class Blind(_Forge):
        def pr_checks(self, *, pr):
            return [{"name": "license/cla", "bucket": "fail", "blocking": True, "kind": "unknown"}]

    held, _ = what_to_repair(lambda: Blind(""), "12", "https://forge/pr/1")
    assert held.hold_cause == GATE and classify(held.note, cause=held.hold_cause).cause == GATE


def test_the_unreadable_forge_declares_nothing__on_purpose(monkeypatch):
    """The one hold in these paths that knows no more than the sentence it was handed. A 403 and a
    throttle need different people, and the rules read the vendor's own error better than a guess
    made where it is caught."""
    monkeypatch.setattr("openfactory.runtime.repairable.time.sleep", lambda _s: None)

    class Refuses:
        checks_are_typed = True

        def __init__(self, why):
            self.why = why

        def pr_checks(self, *, pr):
            raise RuntimeError(self.why)

    for why, expected in (("403 Forbidden", ENVIRONMENT),
                          ("API rate limit exceeded for installation", TRANSIENT)):
        held, _ = what_to_repair(lambda w=why: Refuses(w), "12", "https://forge/pr/1")
        assert held.hold_cause == "", "a hold declared a class it cannot know"
        assert classify(held.note, cause=held.hold_cause).cause == expected


def test_the_spent_repair_passes_are_the_changes_problem__not_a_mystery():
    """`CI still failing after N repair attempt(s)` matched no rule at all: the watch knew exactly
    what it was and the escalation said "I could not identify the cause"."""
    note = "CI still failing after 2 repair attempt(s) — needs a human"
    assert classify(note).cause == UNKNOWN, "a rule now reads this note; re-aim this guard"
    assert classify(note, cause=CODE).cause == CODE
    assert "the change itself is wrong" in remedy_for(classify(note, cause=CODE)).reason


# ═══ the workflow, on a real engine ═════════════════════════════════════════════════════════════

MARKER = "a-hold-says-its-own-cause"
TQ = "test-a-hold-says-its-own-cause"
engine = pytest.mark.owns_its_engine


@pytest.fixture
async def env():
    from temporalio.testing import WorkflowEnvironment

    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


SAID: list[str] = []


def _mocks(hold: RunResult | None):
    """#197's own mocks, with the coordinator's line CAPTURED — what a person is told is half of
    what this fix changes — and, when there is one, a repair that hands back `hold`."""
    @activity.defn(name="repair_ci")
    async def held(inp: ci.CiRepairInput) -> RunResult:
        ci._REPAIRS.append(inp)
        return hold.model_copy(update={"ticket_id": inp.issue, "pr_url": inp.pr_url})

    @activity.defn(name="notify_coordinator_say")
    async def said(inp) -> None:
        SAID.append(f"{inp.get('kind')}: {inp.get('text')}")

    SAID.clear()
    keep = [m for m in ci.MOCKS if m not in (ci.mock_repair, ci.mock_say)] + [said]
    # `None` means "let #197's own repair mock answer": the job then spends its repair passes and
    # the WATCH writes the hold, which is the one this case is about.
    return keep + [ci.mock_repair if hold is None else held]


async def _drive(env, hold: RunResult, *, bound: int = 40):
    """Run the real job until it parks for a person; return the park kinds it passed through and
    that job's own history. Bounded, so a mutant that reintroduces the nap cannot hang the runner."""
    ci._reset(ci.RED_BUILD, open_for=99)
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow],
                      activities=_mocks(hold)):
        h = await env.client.start_workflow(
            JobWorkflow.run,
            JobParams(project="p", issue="12", promote=False, merge_deadline_days=3650),
            id=f"wf-{uuid.uuid4()}", task_queue=TQ)
        seen: list[str] = []
        parked: dict = {}
        for _ in range(bound):
            parked = await h.query(JobWorkflow.awaiting_action) or {}
            kind = parked.get("kind")
            if kind and (not seen or seen[-1] != kind):
                seen.append(kind)
            if kind == "impediment":
                break
            await env.sleep(timedelta(minutes=10))
        else:
            raise AssertionError(f"the job never asked a person — it went through {seen}")
        await h.signal(JobWorkflow.act_on_impediment, args=["skip", "skip"])
        await h.result()
        return seen, await h.fetch_history(), parked


@engine
async def test_the_case_driven__one_agent_pass_and_one_park(env):
    """THE MEASUREMENT. Against the prose reading this job ran the agent FOUR times and announced
    three self-healing naps; the hold it is parking on is a required review."""
    seen, _, _ = await _drive(env, _gate_hold("rate-limit tests"))

    assert seen == ["impediment"], f"the job self-healed at a gate: {seen}"
    assert len(ci._RUNS) == 1, f"{len(ci._RUNS)} agent passes on a gate only a person opens"
    # AND WHAT THE PERSON IS TOLD. Read from the prose, this park announced a nap — "This is
    # throttling and it passes on its own" — about a required review.
    told = "\n".join(SAID)
    assert "passes on its own" not in told, told
    assert "no change to the code settles" in told and "rate-limit tests" in told


@engine
async def test_the_park_carries_the_cause_to_whoever_reads_the_payload(env):
    """The rounds read the park payload and nothing else (#124's lesson, again)."""
    _, _, parked = await _drive(env, _gate_hold("rate-limit tests"))

    assert parked["cause"] == GATE


@engine
async def test_a_job_parked_before_the_marker_replays_on_the_reading_it_recorded(env,
                                                                                 monkeypatch):
    """A job sitting in this loop today recorded the PROSE verdict: naps and a re-run. Its history
    must replay on this code, so the declaration is behind `workflow.patched`."""
    hold = _gate_hold("rate-limit tests")
    with monkeypatch.context() as m:
        # ONLY THIS MARKER. #197's own marker stays true: the history to replay is a job in
        # TODAY's watch that parked under the PROSE reading, which is what is in flight.
        from temporalio import workflow as tw

        real = tw.patched
        m.setattr(tw, "patched", lambda name: False if name == MARKER else real(name))
        seen, history, _ = await _drive(env, hold)
        assert seen[0] == "self_healing", (
            "the pre-marker arm did not take the prose reading it is here to preserve")

    await Replayer(workflows=[JobWorkflow],
                   data_converter=pydantic_data_converter).replay_workflow(history)

    # VERIFY THE VERIFIER (#197's discipline): the same history through the NEW arm is a
    # non-deterministic replay — the declaration skips the nap the history recorded — so the green
    # replay above is the marker working rather than a replayer that cannot tell.
    from temporalio import workflow as tw

    real = tw.patched
    monkeypatch.setattr(tw, "patched", lambda name: True if name == MARKER else real(name))
    with pytest.raises(Exception) as caught:
        await Replayer(workflows=[JobWorkflow],
                       data_converter=pydantic_data_converter).replay_workflow(history)
    assert "determinis" in str(caught.value).lower() or "TMPRL1100" in str(caught.value), (
        f"the ungated replay failed for another reason: {caught.value!r}")


@engine
async def test_the_spent_repair_passes_park_as_the_changes_problem(env):
    """The watch's OWN hold, driven: the repair passes are spent and the checks are still red.
    Its note matches no rule, so the escalation said "I could not identify the cause" about a
    hold the watch had counted itself."""
    _, _, parked = await _drive(env, None)

    assert "repair attempt(s)" in parked["note"], parked["note"]
    assert parked["cause"] == CODE
    assert "could not identify the cause" not in "\n".join(SAID), "\n".join(SAID)


# ═══ the hourly round ═══════════════════════════════════════════════════════════════════════════

def _round(note: str, cause: str) -> watch.Finding:
    state = watch.FloorState(
        parked=[watch.Parked(ticket="12", hours=9.0, note=note, cause=cause)],
        running=0, queued=[], long_running=[], at_a_gate=[], idle_minutes=0)
    return next(f for f in watch.watch(state) if f.ticket == "12")


def test_the_gatherer_hands_the_parks_declaration_on():
    """ASSERTED ON THE SOURCE, for the reason `test_a_job_at_a_gate_is_not_counted_as_RUNNING_by
    _the_gatherer` states about this same function: it needs a live engine to execute. The claim
    is narrow and mechanical — the `Parked` the round reasons over is built from the payload's own
    `cause`, not from a constant."""
    import ast
    import inspect

    from openfactory.runtime.temporal import activities

    tree = ast.parse(inspect.getsource(activities.techlead_watch).lstrip())
    built = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "Parked"]
    assert built, "the gatherer never records a parked job — this guard measures nothing"
    passed = [ast.unparse(k.value) for c in built for k in c.keywords if k.arg == "cause"]
    assert passed and all("state.get" in p and "cause" in p for p in passed), (
        f"the round's parked jobs carry {passed or 'no cause at all'} — the declaration the park "
        f"payload carries is dropped on the way in, and the note is all the round has again")


def test_the_round_does_not_press_resume_on_a_gate():
    """`findings` decides whether the tech-lead resumes a park by itself. Reading the note alone,
    a check named "rate-limit tests" made it announce a self-healing park and press the button."""
    held = _gate_hold("rate-limit tests")

    as_prose = _round(held.note, "")
    declared = _round(held.note, held.hold_cause)

    assert as_prose.resumable is True, "the note stopped tripping the retry path — re-aim this"
    assert declared.resumable is False
    assert "only a person" in declared.action or "pull request" in declared.action
